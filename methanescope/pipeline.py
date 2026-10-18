"""Lesson 2.5 command-line entry point. From project root:

    python -m methanescope.pipeline discover
    python -m methanescope.pipeline validate
    python -m methanescope.pipeline ingest
    python -m methanescope.pipeline status
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

import pandas as pd

from .science import discover, load_manifest, validate_one
from .store import connection, assert_schema, source_for_mode, ingest_one, audit_run, counts_for_source

LOG = logging.getLogger("methanescope")


def setup_logging(root: Path) -> Path:
    out = root / "outputs" / "pipeline"
    out.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    for handler in (logging.FileHandler(out / "pipeline.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        LOG.addHandler(handler)
    return out


def validate_batch(root: Path):
    mode, rows = load_manifest(root)
    valid, results = [], []
    for row in rows:
        gid = str(row["granule_id"])
        try:
            item = validate_one(root, row)
            valid.append(item)
            results.append({"status": "VALID", "granule_id": gid, "message": f"{len(item.features)} GeoJSON feature(s)"})
        except Exception as exc:
            results.append({"status": "ERROR", "granule_id": gid, "message": f"{type(exc).__name__}: {exc}"})
    return mode, valid, results


def write_results(out: Path, command: str, mode: str, results: list[dict], extra: dict | None = None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{stamp}_{command}"
    result_csv = out / f"{prefix}_outcomes.csv"
    summary_json = out / f"{prefix}_summary.json"
    pd.DataFrame(results, columns=["status", "granule_id", "message"]).to_csv(result_csv, index=False)
    summary = {
        "timestamp_utc": stamp, "lesson": "2.5", "command": command,
        "mode": mode, "counts": dict(Counter(r["status"] for r in results)),
        "scientific_validation": "NOT_ESTABLISHED",
        "details": extra or {},
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOG.info("Audit files: %s and %s", result_csv, summary_json)
    return summary


def run(argv=None):
    parser = argparse.ArgumentParser(description="MethaneScope AI Lesson 2.5 satellite ingestion")
    parser.add_argument("command", choices=["discover", "validate", "ingest", "status"])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="MethaneScope project root")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / "data").is_dir():
        parser.error(f"Project root must contain data/: {root}")
    out = setup_logging(root)
    LOG.info("Command=%s Project=%s", args.command, root)

    if args.command == "discover":
        inventory = discover(root)
        for row in inventory:
            LOG.info("%s | %s | %s", row["pair_status"], row["raster"], row["metadata"])
        path = out / "discovered_candidates.csv"
        pd.DataFrame(inventory, columns=["raster", "metadata", "pair_status"]).to_csv(path, index=False)
        LOG.info("Discovered %s candidates. Saved %s", len(inventory), path)
        # Discovery does not mean scientific acceptance.
        return 0 if inventory else 1

    if args.command in ("validate", "ingest"):
        mode, valid, results = validate_batch(root)
        for r in results:
            LOG.info("%s | %s | %s", r["status"], r["granule_id"], r["message"])
        if args.command == "validate":
            write_results(out, "validate", mode, results)
            return 0 if len(valid) == len(results) else 1
        if len(valid) != len(results):
            LOG.error("Ingest blocked: at least one ACCEPTED manifest row failed independent revalidation. No database writes performed.")
            write_results(out, "ingest_blocked", mode, results)
            return 1
        with connection(root) as conn:
            version = assert_schema(conn)
            LOG.info("Connected PostGIS version: %s", version)
            source_id, source_code = source_for_mode(conn, mode)
            db_results = []
            for item in valid:
                try:
                    status, gid, message = ingest_one(conn, source_id, item)
                except Exception as exc:
                    status, gid, message = "ERROR", str(item.manifest["granule_id"]), f"{type(exc).__name__}: {exc}"
                db_results.append({"status": status, "granule_id": gid, "message": message})
                LOG.info("%s | %s | %s", status, gid, message)
            audit_id = audit_run(conn, mode, db_results)
            db_counts = counts_for_source(conn, source_id)
            LOG.info("Audit ID %s; source=%s; stored granules=%s, features=%s", audit_id, source_code, *db_counts)
        write_results(out, "ingest", mode, db_results, {"audit_id": audit_id, "source_code": source_code, "stored_granules": db_counts[0], "stored_features": db_counts[1]})
        return 1 if any(r["status"] in ("ERROR", "CONFLICT") for r in db_results) else 0

    if args.command == "status":
        with connection(root) as conn:
            version = assert_schema(conn)
            LOG.info("PostGIS version: %s", version)
            with conn.cursor() as cur:
                cur.execute("""SELECT s.source_code, count(g.id) AS n
                       FROM data_sources s
                       LEFT JOIN satellite_granules g ON g.source_id=s.id
                       GROUP BY s.source_code ORDER BY s.source_code""")
                for source, n in cur.fetchall():
                    LOG.info("Source %-24s stored granules=%d", source, n)
                cur.execute("SELECT count(*) FROM plume_features")
                LOG.info("Total stored GeoJSON features=%s", cur.fetchone()[0])
        return 0
    return 2


def main():
    try:
        raise SystemExit(run())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        LOG.error("%s: %s", type(exc).__name__, exc)
        raise SystemExit(1) from None
    except Exception:
        LOG.exception("Unexpected failure")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
