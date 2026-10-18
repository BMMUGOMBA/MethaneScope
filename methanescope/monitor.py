"""MethaneScope Lesson 2.6: local, read-only health monitoring and a safe run-once wrapper.

Adds a monitoring layer without migrating schema, deleting files, sending alerts,
or automatically scheduling anything. Uses Lesson 2.5's database and validation code.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from .science import discover, load_manifest
from .store import connection, assert_schema

SEVERITY = {"OK": 0, "WARN": 1, "CRITICAL": 2}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def monitor_dir(root: Path) -> Path:
    path = root / "outputs" / "monitoring"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_atomic(path: Path, doc: dict) -> None:
    """Avoid writing a partially complete latest-status file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, doc: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, default=str, ensure_ascii=False) + "\n")


def classify_health_checks(checks: list[dict]) -> str:
    worst = max((SEVERITY[x["status"]] for x in checks), default=2)
    return {level: key for key, level in SEVERITY.items()}[worst]


def health_snapshot(root: Path, check_db: bool = True) -> dict:
    """Checks prerequisites without mutating DB or raw NASA files."""
    checks: list[dict] = []

    def record(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    try:
        pairs = discover(root)
        stats = dict(Counter(row["pair_status"] for row in pairs))
        if not pairs:
            record("file_discovery", "CRITICAL", "No EMIT .tif/.tiff candidates found")
        elif any(row["pair_status"] != "MATCHED" for row in pairs):
            record("file_discovery", "WARN", f"{len(pairs)} rasters found; pair statuses={stats}")
        else:
            record("file_discovery", "OK", f"{len(pairs)} raster(s), all metadata paired")
    except Exception as exc:
        record("file_discovery", "CRITICAL", f"{type(exc).__name__}: {exc}")

    try:
        mode, accepted = load_manifest(root)
        record("accepted_manifest", "OK", f"Mode={mode}, ACCEPTED rows={len(accepted)}")
    except Exception as exc:
        record("accepted_manifest", "CRITICAL", f"{type(exc).__name__}: {exc}")

    if check_db:
        try:
            with connection(root) as conn:
                version = assert_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM satellite_granules")
                    n_granules = cur.fetchone()[0]
                    cur.execute("SELECT count(*) FROM plume_features")
                    n_features = cur.fetchone()[0]
            record("postgresql_postgis", "OK", f"PostGIS {version}; granules={n_granules}; features={n_features}")
        except Exception as exc:
            record("postgresql_postgis", "CRITICAL", f"{type(exc).__name__}: {exc}")

    return {"checked_utc": now_utc(), "status": classify_health_checks(checks), "checks": checks,
            "scientific_validation": "NOT_ESTABLISHED"}


def last_pipeline_summary(root: Path) -> dict | None:
    candidates = sorted((root / "outputs" / "pipeline").glob("*_ingest_summary.json"))
    for path in reversed(candidates):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            return {"filename": path.name, "summary": summary}
        except (ValueError, OSError):
            continue
    return None


def read_history(path: Path, limit: int = 10) -> list[dict]:
    if not path.is_file():
        return []
    # Daily local use: a modest history file; invalid individual JSON lines are ignored.
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def run_once(root: Path) -> dict:
    """Run Lesson 2.5 validation and ingestion once; no background scheduler."""
    from .pipeline import run as pipeline_run

    start = time.monotonic()
    initial = health_snapshot(root)
    event = {"started_utc": now_utc(), "command": "run-once", "result": "PENDING",
             "failure_class": None, "message": "", "preflight": initial,
             "scientific_validation": "NOT_ESTABLISHED"}
    if initial["status"] == "CRITICAL":
        event.update(result="FAILED", failure_class="PREFLIGHT", message="Prerequisite check failed; ingestion not attempted")
    else:
        try:
            validation_exit = pipeline_run(["validate", "--root", str(root)])
            event["validation_exit_code"] = validation_exit
            if validation_exit != 0:
                event.update(result="FAILED", failure_class="DATA_VALIDATION", message="Source validation failed; ingestion not attempted")
            else:
                ingest_exit = pipeline_run(["ingest", "--root", str(root)])
                event["ingestion_exit_code"] = ingest_exit
                outcome = last_pipeline_summary(root)
                event["latest_pipeline_audit"] = outcome
                if ingest_exit != 0:
                    event.update(result="FAILED", failure_class="INGESTION", message="Ingestion encountered an error/conflict")
                else:
                    event.update(result="SUCCESS", message="Validation and transactional ingestion completed")
        except Exception as exc:
            event.update(result="FAILED", failure_class="EXCEPTION", message=f"{type(exc).__name__}: {exc}")

    event["completed_utc"] = now_utc()
    event["duration_seconds"] = round(time.monotonic() - start, 3)
    folder = monitor_dir(root)
    write_json_atomic(folder / "last_run.json", event)
    append_jsonl(folder / "run_history.jsonl", event)
    if event["result"] != "SUCCESS":
        append_jsonl(folder / "alerts.jsonl", {"timestamp_utc": event["completed_utc"],
            "severity": "CRITICAL", "failure_class": event["failure_class"], "message": event["message"]})
    return event


def execute(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MethaneScope Lesson 2.6 monitoring")
    parser.add_argument("command", choices=["health", "run-once", "report"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / "data").is_dir() or not (root / "methanescope" / "pipeline.py").is_file():
        parser.error("Run from the MethaneScope project root (must contain data/ and methanescope/pipeline.py)")

    if args.command == "health":
        result = health_snapshot(root)
        write_json_atomic(monitor_dir(root) / "last_health.json", result)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "OK" else (1 if result["status"] == "WARN" else 2)

    if args.command == "run-once":
        result = run_once(root)
        print("\nMONITOR RESULT:")
        print(json.dumps({k: result.get(k) for k in ("result", "failure_class", "message", "duration_seconds", "completed_utc")}, indent=2))
        return 0 if result["result"] == "SUCCESS" else 2

    if args.command == "report":
        folder = monitor_dir(root)
        history = read_history(folder / "run_history.jsonl")
        latest = json.loads((folder / "last_run.json").read_text(encoding="utf-8")) if (folder / "last_run.json").is_file() else None
        counts = dict(Counter(row.get("result", "UNKNOWN") for row in history))
        report = {"generated_utc": now_utc(), "last_10_runs": counts,
                  "last_run": latest, "latest_ingest_audit": last_pipeline_summary(root),
                  "notice": "This report monitors engineering pipeline operation, not scientific emissions accuracy."}
        write_json_atomic(folder / "monitoring_report.json", report)
        print(json.dumps({"last_10_runs": counts,
                          "last_run_result": latest.get("result") if latest else "NOT_YET_RUN",
                          "latest_ingest_audit": report["latest_ingest_audit"]["filename"] if report["latest_ingest_audit"] else None}, indent=2))
        print("Full report:", folder / "monitoring_report.json")
        return 0
    return 2


def main() -> None:
    raise SystemExit(execute())


if __name__ == "__main__":
    main()
