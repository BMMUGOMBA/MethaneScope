"""MethaneScope Lesson 2.9: safe, local, opt-in scheduling wrapper.

This module does not configure a recurring schedule. The `run` command is
DRY-RUN by default. Add --execute only after checking `plan` and `pytest`.
It never edits original NASA files or drops database tables.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import time

from . import monitor
from .science import discover, load_manifest


class LockBusyError(RuntimeError):
    """Another local MethaneScope scheduled operation owns the lock."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scheduler_dir(root: Path) -> Path:
    path = root / "outputs" / "scheduler"
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def exclusive_project_lock(root: Path):
    """Local atomic lock for this project directory; not a distributed lock.

    A stale file after an unexpected crash is deliberately NOT removed here.
    Inspect process status before manually resolving such a lock.
    """
    lock = scheduler_dir(root) / ".ingestion.lock"
    try:
        fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        try:
            info = lock.read_text(encoding="utf-8")
        except OSError:
            info = "Unable to read lock metadata"
        raise LockBusyError(f"Run already locked: {lock}\n{info}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                       "acquired_utc": utc_now()}, stream)
            stream.write("\n")
        yield lock
    finally:
        lock.unlink(missing_ok=True)


def plan(root: Path) -> dict:
    """Produce a read-only inventory; no Docker start or database writes."""
    mode, accepted = load_manifest(root)
    inventory = discover(root)
    return {
        "generated_utc": utc_now(),
        "mode": mode,
        "accepted_rows": len(accepted),
        "accepted_granules": [str(x["granule_id"]) for x in accepted],
        "candidate_rasters": len(inventory),
        "unmatched_rasters": sum(x["pair_status"] != "MATCHED" for x in inventory),
        "scientific_validation": "NOT_ESTABLISHED",
        "note": "Only records accepted in Lesson 2.3 manifest can be ingested",
    }


def retryable_db_preflight(event: dict) -> bool:
    """Only retry a failed preflight caused solely by database health.

    Do not retry a validation failure, checksum mismatch, conflict, or generic
    ingestion failure. Those need investigation, not blind automation.
    """
    if event.get("result") != "FAILED" or event.get("failure_class") != "PREFLIGHT":
        return False
    checks = event.get("preflight", {}).get("checks", [])
    critical = {c.get("check") for c in checks if c.get("status") == "CRITICAL"}
    return critical == {"postgresql_postgis"}


def exponential_wait(retry_index: int, base_seconds: float = 2, cap_seconds: float = 30) -> float:
    """retry_index=1 is the pause after attempt #1."""
    if retry_index < 1 or base_seconds < 0 or cap_seconds < 0:
        raise ValueError("Invalid retry/backoff configuration")
    return min(cap_seconds, base_seconds * (2 ** (retry_index - 1)))


def run_safely(root: Path, *, execute: bool = False,
               allow_demo: bool = False, max_attempts: int = 3,
               base_delay: float = 2.0, sleep_fn=None,
               monitored_run=None) -> dict:
    """One safely locked run with limited retry of database-only preflight errors.

    Inject monitored_run/sleep_fn in tests. No background process is created.
    """
    if not (1 <= max_attempts <= 5):
        raise ValueError("max_attempts must be between 1 and 5")
    if not 0 <= base_delay <= 60:
        raise ValueError("base_delay must be between 0 and 60 seconds")
    root = root.resolve()
    current = plan(root)
    if current["mode"] == "demo" and execute and not allow_demo:
        raise ValueError("Refusing DEMO database ingestion unless --allow-demo is explicit")
    if not execute:
        return {"result": "DRY_RUN", "plan": current,
                "message": "No ingestion executed. Use --execute after review."}
    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    runner = monitored_run if monitored_run is not None else monitor.run_once

    with exclusive_project_lock(root):
        events = []
        started = utc_now()
        for attempt in range(1, max_attempts + 1):
            event = runner(root)
            events.append({"attempt": attempt, "result": event.get("result"),
                           "failure_class": event.get("failure_class"),
                           "message": event.get("message")})
            if event.get("result") == "SUCCESS":
                break
            if attempt >= max_attempts or not retryable_db_preflight(event):
                break
            sleeper(exponential_wait(attempt, base_seconds=base_delay))

        completed = {
            "started_utc": started,
            "completed_utc": utc_now(),
            "result": events[-1]["result"],
            "attempt_count": len(events),
            "events": events,
            "mode": current["mode"],
            "accepted_rows": current["accepted_rows"],
            "scientific_validation": "NOT_ESTABLISHED",
            "note": "Local file lock; not safe for multi-host distributed scheduling",
        }
        target = scheduler_dir(root)
        monitor.write_json_atomic(target / "last_schedule_run.json", completed)
        monitor.append_jsonl(target / "scheduler_history.jsonl", completed)
        return completed


def execute(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MethaneScope Lesson 2.9 — safe, opt-in local scheduling")
    parser.add_argument("command", choices=["plan", "run"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--execute", action="store_true", help="Actually call existing monitored ingestion")
    parser.add_argument("--allow-demo", action="store_true", help="Explicitly permit synthetic demo ingestion")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--base-delay", type=float, default=2.0)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / "methanescope" / "monitor.py").is_file() or not (root / "data").is_dir():
        parser.error("Run from MethaneScope project root with Lesson 2.6 installed")
    try:
        if args.command == "plan":
            result = plan(root)
        else:
            result = run_safely(root, execute=args.execute, allow_demo=args.allow_demo,
                                max_attempts=args.max_attempts, base_delay=args.base_delay)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("result") in (None, "SUCCESS", "DRY_RUN") else 2
    except (LockBusyError, FileNotFoundError, RuntimeError, ValueError) as error:
        print(json.dumps({"result": "BLOCKED", "reason": str(error)}, indent=2))
        return 2


def main() -> None:
    raise SystemExit(execute())


if __name__ == "__main__":
    main()
