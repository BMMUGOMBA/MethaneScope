"""Fast local tests; no NASA account or PostGIS needed."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from methanescope.science import discover, identity, load_manifest, safe_file, sha256_file, validate_one


def prepare(tmp_path):
    root = tmp_path
    folder = root / "data" / "raw" / "nasa_emit"
    folder.mkdir(parents=True)
    raster = folder / "EMIT_L2B_CH4PLM_002_20220810T064957_000485.tif"
    metadata = folder / "EMIT_L2B_CH4PLMMETA_002_20220810T064957_000485.json"
    image = np.array([[1, 2], [3, 4]], dtype=np.float32)
    with rasterio.open(raster, "w", driver="GTiff", height=2, width=2, count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(28, -17, .01, .01)) as dest:
        dest.write(image, 1)
    geo = {"type": "FeatureCollection", "features": [{"type": "Feature",
           "geometry": {"type": "Polygon", "coordinates": [[[28, -17], [28.02, -17],
           [28.02, -17.02], [28, -17.02], [28, -17]]]}, "properties": {"fixture": True}}]}
    metadata.write_text(json.dumps(geo), encoding="utf-8")
    return root, raster, metadata


def make_row(root, raster, metadata):
    return {"mode": "real", "status": "ACCEPTED", "data_origin": "NASA_CANDIDATE_UNVERIFIED",
            "granule_id": raster.stem, "path": str(raster.relative_to(root)),
            "raster_sha256": sha256_file(raster), "geojson_path": str(metadata.relative_to(root)),
            "geojson_sha256": sha256_file(metadata), "valid_pixels": 4,
            "maximum_enhancement_ppm_m": 4.0}


def test_nasa_metadata_identity_matches_raster(tmp_path):
    root, raster, meta = prepare(tmp_path)
    assert identity(raster) == identity(meta)
    assert discover(root)[0]["pair_status"] == "MATCHED"


def test_validation_preserves_scientific_provenance(tmp_path):
    root, raster, meta = prepare(tmp_path)
    granule = validate_one(root, make_row(root, raster, meta))
    assert len(granule.features) == 1
    assert granule.bounds_wgs84 == pytest.approx((28, -17.02, 28.02, -17))
    assert granule.acquired_at.year == 2022


def test_detects_checksum_change(tmp_path):
    root, raster, meta = prepare(tmp_path)
    row = make_row(root, raster, meta)
    meta.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="Metadata SHA-256 changed"):
        validate_one(root, row)


def test_rejects_unsafe_path(tmp_path):
    with pytest.raises(ValueError, match="Unsafe path"):
        safe_file(tmp_path, "../private.txt")


def test_accept_manifest_requires_single_mode_and_unique_ids(tmp_path):
    root, raster, meta = prepare(tmp_path)
    row = make_row(root, raster, meta)
    path = root / "outputs" / "emit_batch" / "emit_accepted_for_ingestion.csv"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row]).to_csv(path, index=False)
    mode, records = load_manifest(root)
    assert mode == "real" and len(records) == 1
    pd.DataFrame([row, row]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Duplicate granule_id"):
        load_manifest(root)
