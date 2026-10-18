"""PostGIS persistence compatible with the schema built in Lesson 2.4."""
from __future__ import annotations
import json
import os
from pathlib import Path

from dotenv import load_dotenv


def connection(root: Path):
    import psycopg
    load_dotenv(root / ".env", override=True)
    mandatory = ["DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [name for name in mandatory if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing .env keys: {missing}")
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=8,
        autocommit=True,
    )


def assert_schema(conn):
    """Do not silently migrate/change Lesson 2.4's existing database."""
    with conn.cursor() as cur:
        cur.execute("SELECT PostGIS_Version()")
        version = cur.fetchone()[0]
        for name in ("data_sources", "satellite_granules", "plume_features", "ingestion_runs"):
            cur.execute("SELECT to_regclass(%s)", ("public." + name,))
            if not cur.fetchone()[0]:
                raise RuntimeError(f"Missing table {name}. Complete Lesson 2.4 first.")
    return version


def source_for_mode(conn, mode: str) -> tuple[int, str]:
    if mode not in {"real", "demo"}:
        raise ValueError("Mode must be real or demo")
    code = "NASA_EMIT_CANDIDATE" if mode == "real" else "SYNTHETIC_EMIT_QA"
    description = ("NASA EMIT candidate files; catalogue identity not independently verified"
                   if mode == "real" else "Synthetic Lesson 2.3 QA fixtures")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO data_sources (source_code, product, description)
                           VALUES (%s,%s,%s) ON CONFLICT (source_code) DO NOTHING""",
                        (code, "EMITL2BCH4PLM.002", description))
            cur.execute("SELECT id FROM data_sources WHERE source_code=%s", (code,))
            pk = cur.fetchone()[0]
    return pk, code


def ingest_one(conn, source_id: int, granule):
    """Atomic granule + features insertion; unchanged repeats are SKIPPED."""
    row = granule.manifest
    gid = str(row["granule_id"])
    raster_sha = str(row["raster_sha256"])
    metadata_sha = str(row["geojson_sha256"])
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""SELECT granule_id, raster_sha256, geojson_sha256
                           FROM satellite_granules
                           WHERE source_id=%s AND (granule_id=%s OR raster_sha256=%s)
                           FOR UPDATE""", (source_id, gid, raster_sha))
            prev = cur.fetchall()
            if prev:
                if len(prev) == 1 and prev[0][0] == gid and prev[0][1].strip() == raster_sha and (prev[0][2] or "").strip() == metadata_sha:
                    return "SKIPPED", gid, "Identical granule already stored"
                return "CONFLICT", gid, "Granule ID or raster checksum conflicts with existing data"
            w, s, e, n = granule.bounds_wgs84
            cur.execute("""INSERT INTO satellite_granules
              (source_id,granule_id,acquisition_time,raster_sha256,geojson_sha256,
               raster_path,geojson_path,valid_pixels,max_enhancement_ppm_m,
               data_origin,footprint,raw_manifest)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      ST_MakeEnvelope(%s,%s,%s,%s,4326),%s::jsonb)
              ON CONFLICT DO NOTHING RETURNING id""",
              (source_id, gid, granule.acquired_at, raster_sha, metadata_sha,
               str(row["path"]), str(row["geojson_path"]), int(row["valid_pixels"]),
               float(row["maximum_enhancement_ppm_m"]), str(row["data_origin"]),
               w, s, e, n, json.dumps(row, default=str)))
            new = cur.fetchone()
            if new is None:
                return "CONFLICT", gid, "Concurrent write or unique constraint prevented insert"
            granule_pk = new[0]
            for index, geometry_json, properties_json in granule.features:
                cur.execute("""INSERT INTO plume_features
                       (granule_pk,feature_index,geom,properties)
                       VALUES (%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb)""",
                            (granule_pk, index, geometry_json, properties_json))
    return "INSERTED", gid, f"{len(granule.features)} metadata feature(s) stored"


def audit_run(conn, mode: str, results: list[dict]) -> int:
    counts = {label: sum(r["status"] == label for r in results) for label in ("INSERTED", "SKIPPED", "ERROR", "CONFLICT")}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO ingestion_runs
               (source_mode,attempted,inserted,skipped,rejected,details)
               VALUES (%s,%s,%s,%s,%s,%s::jsonb) RETURNING id""",
              (mode, len(results), counts["INSERTED"], counts["SKIPPED"],
               counts["ERROR"] + counts["CONFLICT"], json.dumps(results)))
            return cur.fetchone()[0]


def counts_for_source(conn, source_id: int) -> tuple[int,int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM satellite_granules WHERE source_id=%s", (source_id,))
        granules = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM plume_features f
                     JOIN satellite_granules g ON g.id=f.granule_pk
                     WHERE g.source_id=%s""", (source_id,))
        features = cur.fetchone()[0]
    return granules, features
