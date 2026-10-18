# MethaneScope AI — Lesson 2.9: Safe Scheduling, Backoff & Concurrency Control

**Prerequisite:** Lesson 2.8 verified (16 tests passing), Lesson 2.6 monitoring operational, PostGIS initialized. You already have one actual NASA EMIT candidate granule in PostGIS; **do not delete/reinitialize** the database.

## What is included?

- `methanescope/scheduler.py` — opt-in execution, manifest plan, local lock, conservative DB-only retries, audit history.
- `tests/test_scheduler.py` — nine tests with mocks and temporary directories; do not touch real NASA data or Docker.
- `11_safe_scheduling_and_backoff.ipynb` — instructional JupyterLab workbook.
- `scripts/run_scheduler_once.bat` — **manual** Windows batch launcher in dry-run mode by default.

**Important:** This is not a fully unattended satellite-data collection system. No recurring schedule is installed. It reuses the Lesson 2.3 accepted manifest; acquiring additional genuine NASA granules is a later lesson.

## Installation

1. Make a copy/commit of your project first if you wish.
2. Extract this ZIP **into the root of the current MethaneScope folder**. It only adds new files; do not overwrite `.env`, database, `data`, or existing modules.
3. From Git Bash in MethaneScope:

```bash
source .venv/Scripts/activate
docker compose -f docker-compose.postgis.yml up -d
python -m pytest -q tests/test_science.py tests/test_monitor.py tests/test_reliability.py tests/test_scheduler.py
python -m methanescope.scheduler plan
python -m methanescope.scheduler run
```

`run` defaults to **DRY_RUN**. It does not write new database records.

If the plan shows **mode=real** with your accepted NASA granule and tests are green, run once with:

```bash
python -m methanescope.scheduler run --execute --max-attempts 3 --base-delay 2
python -m methanescope.pipeline status
python -m methanescope.monitor report
```

**Expected with your current database:** `result: SUCCESS`, one attempt, underlying PostGIS ingestion `SKIPPED` (identical granule already stored), stored granules=1 and features=1. These are engineering pipeline checks, **not** independent scientific methane validation.

## How retries work

- Retry ONLY if the preflight failed because **PostgreSQL/PostGIS alone** is marked CRITICAL.
- Wait with exponential backoff (2 s, then 4 s, capped at 30 s by default).
- Do NOT retry data-validation errors, checksum changes, conflicts, or generic ingestion failures.
- Stop after at most 5 attempts. Default is 3.
- Multiple attempts may create multiple local failure events in existing monitoring history; this is expected and auditable.

## Concurrency protection

An atomic local file lock prevents two runs **using this scheduler and the same project directory** from executing concurrently. Existing unscheduled commands (`python -m methanescope.pipeline ingest` / `python -m methanescope.monitor run-once`) do **not** honor this new lock. Do not run those concurrently with scheduled execution. Local file locks are insufficient for scheduling across multiple machines; cloud deployment will use a database or managed lease.

If `.ingestion.lock` remains after a crash, do not immediately remove it: verify no process is running before manually removing a genuinely stale lock.

## Audits

- `outputs/scheduler/last_schedule_run.json` — latest scheduled/manual execution.
- `outputs/scheduler/scheduler_history.jsonl` — append-only execution summaries.
- Existing `outputs/monitoring/` files — individual monitored attempts and alerts.

## Windows Task Scheduler (OPTIONAL and NOT enabled by this package)

The included `scripts/run_scheduler_once.bat` runs in dry-run mode only. When ready for a local schedule, use Windows Task Scheduler to launch the batch script from an interactive user session and modify the command only after reviewing this safety guide; make sure Docker and your database are available. Prefer scheduling **one job only** and do not overlap it with interactive ingest commands. Do not store database passwords in command-line arguments, `.bat` files or code.

## Research integrity

NASA acquisition date and ingestion processing date are different. Do not interpret the old 2022 example granule as "new emissions" because the pipeline processes it today. `SUCCESS` means ingestion succeeded, not that the satellite's methane retrieval or emission rate was independently validated.

## Knowledge check

1. Why does a retryable database outage differ from an invalid NASA file?
2. Why is the `run` command a dry-run unless `--execute` is specified?
3. Why does a local file lock not protect against a second server?
4. Why should an already stored granule return `SKIPPED`?
5. What must be checked before putting the pipeline on a recurring schedule?
