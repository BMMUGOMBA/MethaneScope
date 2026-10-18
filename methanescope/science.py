"""Read-only validation for EMIT Version 002 files.

All NASA data remain untouched. Accepting a file for engineering ingestion does
NOT scientifically validate its methane concentration or emission estimates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform_bounds
from shapely.geometry import shape

REQUIRED_COLUMNS = {
    "mode", "status", "data_origin", "granule_id", "path",
    "raster_sha256", "geojson_path", "geojson_sha256",
    "valid_pixels", "maximum_enhancement_ppm_m",
}
EMIT_ID = re.compile(
    r"^EMIT_L2B_CH4PLM_002_(?P<date>\d{8}T\d{6})_(?P<id>[A-Za-z0-9]+)$",
    re.IGNORECASE,
)


def identity(path: Path) -> str:
    """Normalise NASA's CH4PLMMETA companion prefix to its raster stem."""
    stem = path.stem.casefold()
    prefix = "emit_l2b_ch4plmmeta_"
    if stem.startswith(prefix):
        return "emit_l2b_ch4plm_" + stem[len(prefix):]
    return stem


def discover(root: Path) -> list[dict]:
    """Inventory candidate files; this function does NOT approve them."""
    raw = root / "data" / "raw" / "nasa_emit"
    if not raw.exists():
        raise FileNotFoundError(f"Missing NASA input folder: {raw}")
    rasters = sorted(p for p in raw.rglob("*") if p.is_file() and p.suffix.lower() in {".tif", ".tiff"})
    metadata = sorted(p for p in raw.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".geojson"})
    result = []
    for raster in rasters:
        candidates = [m for m in metadata if identity(m) == identity(raster)]
        local = [m for m in candidates if m.parent == raster.parent]
        matches = local if local else candidates
        status = "MATCHED" if len(matches) == 1 else ("MISSING_METADATA" if not matches else "AMBIGUOUS_METADATA")
        result.append({"raster": str(raster.relative_to(root)), "metadata": str(matches[0].relative_to(root)) if len(matches) == 1 else "", "pair_status": status})
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    """Resolve manifest-relative files while blocking directory escape."""
    if not relative or not isinstance(relative, str):
        raise ValueError("Manifest file path is empty")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Unsafe path: {relative!r}")
    resolved = (root / rel).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the project directory")
    if not resolved.is_file():
        raise FileNotFoundError(f"Source file missing: {resolved}")
    return resolved


def load_manifest(root: Path) -> tuple[str, list[dict]]:
    path = root / "outputs" / "emit_batch" / "emit_accepted_for_ingestion.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Run Lesson 2.3 first. Missing: {path}")
    data = pd.read_csv(path, keep_default_na=False)
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"Missing manifest columns: {sorted(missing)}")
    if data.empty:
        raise ValueError("No ACCEPTED records in Lesson 2.3 manifest. Fix QA issues first.")
    if not data["status"].eq("ACCEPTED").all():
        raise ValueError("Manifest contains records not classified ACCEPTED")
    modes = set(data["mode"])
    if len(modes) != 1 or not modes <= {"real", "demo"}:
        raise ValueError(f"Mixed or unknown modes: {modes}")
    mode = next(iter(modes))
    expected_origin = "NASA_CANDIDATE_UNVERIFIED" if mode == "real" else "SYNTHETIC_QA_TEST"
    if not data["data_origin"].eq(expected_origin).all():
        raise ValueError("Manifest provenance is inconsistent with its mode")
    for field in ("granule_id", "raster_sha256"):
        if data[field].duplicated().any():
            raise ValueError(f"Duplicate {field} among ACCEPTED rows")
    return mode, data.to_dict(orient="records")


def utc_acquisition(granule_id: str):
    match = EMIT_ID.fullmatch(granule_id)
    if not match:
        raise ValueError(f"Unrecognised EMIT V002 granule ID: {granule_id}")
    return datetime.strptime(match.group("date"), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


@dataclass
class ValidatedGranule:
    manifest: dict
    raster: Path
    metadata: Path
    acquired_at: datetime
    bounds_wgs84: tuple[float, float, float, float]
    features: list[tuple[int, str, str]]


def validate_one(root: Path, row: dict) -> ValidatedGranule:
    """Independently re-check Lesson 2.3 acceptance and file provenance."""
    if row.get("status") != "ACCEPTED":
        raise ValueError("Refusing non-ACCEPTED manifest row")
    granule_id = str(row["granule_id"])
    timestamp = utc_acquisition(granule_id)
    raster = safe_file(root, str(row["path"]))
    metadata = safe_file(root, str(row["geojson_path"]))
    if raster.stem != granule_id or identity(raster) != identity(metadata):
        raise ValueError("NASA raster and metadata identity mismatch")
    if raster.suffix.lower() not in {".tif", ".tiff"} or metadata.suffix.lower() not in {".json", ".geojson"}:
        raise ValueError("Unexpected raster or metadata extension")
    # Keep the sample in the expected input collection.
    raw = root / "data" / ("raw/nasa_emit" if row["mode"] == "real" else "demo_emit_batch")
    if not raster.resolve().is_relative_to(raw.resolve()) or not metadata.resolve().is_relative_to(raw.resolve()):
        raise ValueError("Source files are not inside the selected raw/demo collection")
    if sha256_file(raster) != str(row["raster_sha256"]):
        raise ValueError("Raster SHA-256 changed since Lesson 2.3")
    if sha256_file(metadata) != str(row["geojson_sha256"]):
        raise ValueError("Metadata SHA-256 changed since Lesson 2.3")
    with rasterio.open(raster) as src:
        if src.count != 1 or src.crs is None:
            raise ValueError("Expected a single-band georeferenced raster")
        pixels = np.ma.masked_invalid(src.read(1, masked=True).astype("float64"))
        vals = pixels.compressed()
        if len(vals) < 1 or len(vals) != int(row["valid_pixels"]):
            raise ValueError("Valid pixel count does not match manifest")
        maximum = float(row["maximum_enhancement_ppm_m"])
        if not math.isfinite(maximum) or not math.isclose(float(vals.max()), maximum, rel_tol=1e-7, abs_tol=1e-6):
            raise ValueError("Maximum enhancement value changed since Lesson 2.3")
        bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    west, south, east, north = bounds
    if not all(math.isfinite(v) for v in bounds) or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Invalid or antimeridian-crossing raster footprint")
    content = json.loads(metadata.read_text(encoding="utf-8"))
    if content.get("type") == "FeatureCollection":
        features = content.get("features")
    elif content.get("type") == "Feature":
        features = [content]
    else:
        raise ValueError("Metadata must be GeoJSON Feature or FeatureCollection")
    if not isinstance(features, list) or not 1 <= len(features) <= 10000:
        raise ValueError("Missing or excessive GeoJSON features")
    validated = []
    for index, item in enumerate(features):
        if item.get("type") != "Feature" or not item.get("geometry"):
            raise ValueError(f"Feature {index} has no geometry")
        geom = item["geometry"]
        shape_obj = shape(geom)
        if shape_obj.is_empty or not shape_obj.is_valid:
            raise ValueError(f"Feature {index} geometry is invalid")
        a, b, c, d = shape_obj.bounds
        if not (-180 <= a <= c <= 180 and -90 <= b <= d <= 90):
            raise ValueError(f"Feature {index} coordinates outside WGS84 bounds")
        validated.append((index, json.dumps(geom), json.dumps(item.get("properties") or {})))
    return ValidatedGranule(row, raster, metadata, timestamp, (west, south, east, north), validated)
