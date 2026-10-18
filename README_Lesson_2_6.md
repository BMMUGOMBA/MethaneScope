# MethaneScope AI — Lesson 2.6: Monitoring, reliability, and a safe run-once pipeline

## Start here: prerequisites

Lesson 2.5 has been verified on your machine with **1 stored NASA EMIT candidate granule, 1 spatial feature and 5/5 tests passing**. Preserve your existing data and database. Lesson 2.6 is an **additive monitoring layer**. It creates no new PostGIS tables and never deletes or alters NASA raw files.

**Install:** Unzip this package into the root of your existing `MethaneScope` folder. Allow it to add `methanescope/monitor.py`, `tests/test_monitor.py`, `08_monitoring_reliability.ipynb`, `scripts/run_methanescope_once.bat`, and this README. **Do not delete or overwrite `methanescope/pipeline.py`, `science.py`, `store.py`, `.env`, `data/` or `outputs/`.**

### Commands (Windows Git Bash, from MethaneScope directory)

```bash
source .venv/Scripts/activate
docker compose -f docker-compose.postgis.yml up -d
python -m pytest -q tests/test_science.py tests/test_monitor.py
python -m methanescope.monitor health
python -m methanescope.monitor run-once
python -m methanescope.monitor report
```

Expected (given your existing valid input and healthy PostGIS):
- `health` result: `"status": "OK"` with database, manifest and file discovery checks.
- `run-once`: `"result": "SUCCESS"`. In the underlying pipeline logs, your existing NASA granule should say `SKIPPED`, which is **correct**.
- `report`: `last_run_result: SUCCESS` and a monitoring report saved under `outputs/monitoring/`.
- Your original **5 tests** plus **6 new unit tests** should pass (11 total).

### Files created

- `outputs/monitoring/last_health.json` — machine-readable health checks
- `outputs/monitoring/last_run.json` — latest run outcome
- `outputs/monitoring/run_history.jsonl` — append-only local run history
- `outputs/monitoring/alerts.jsonl` — local failure alerts (if failures occur)
- `outputs/monitoring/monitoring_report.json` — latest summary

The monitoring layer also reuses Lesson 2.5's `outputs/pipeline/` audit records. It **does not** send alerts or notifications to external systems.

## Scientific and operational cautions

- `ACCEPTED`, `VALID`, or `SUCCESS` means *engineering ingestion checks passed*, **not** the methane measurement has been scientifically validated.
- A `SKIPPED` status for an identical stored granule is idempotent success, not a failed ingestion.
- Never infer a source's emission persistence from a stale satellite acquisition date or an empty ingestion run. Do not treat the age of a 2022 sample file as a pipeline outage.
- The current wrapper runs validation and ingestion **on demand**. No automatic schedule is created by unpacking the ZIP. Schedule only after verifying reliable local runs and Docker availability.
- `alerts.jsonl` contains local failure records. The presence of a local alert entry does not mean a notification was sent.
- Monitoring a production system later requires managed secrets, retry/backoff strategy, distributed concurrency controls, storage and compute cost checks, and access-controlled observability.

## Error categories

| Status | Meaning | Action |
|---|---|---|
| `OK` | Required checks passed | Proceed |
| `WARN` | A non-blocking problem exists (e.g. an extra unmatched raster) | Review file inventory |
| `CRITICAL` | Missing manifest, no input rasters, database unreachable, or another blocked prerequisite | Stop and fix |
| `SUCCESS` | Validation and ingestion command completed | Review audit report |
| `FAILED / PREFLIGHT` | Ingestion intentionally blocked before processing | Inspect `last_run.json` checks |
| `FAILED / DATA_VALIDATION` | Previously accepted file failed independent validation | Re-run Lesson 2.3 and inspect SHA/metadata |
| `FAILED / INGESTION` | DB insertion failed or conflicted | Check logs and database state; do not reset |

## Optional future scheduler

A Windows batch script is included at `scripts/run_methanescope_once.bat` as a future Task Scheduler target. **The script does not schedule itself**. Verify the wrapper manually first. If scheduling later, configure Task Scheduler to run `cmd.exe` with arguments `/c "C:\path\to\MethaneScope\scripts\run_methanescope_once.bat"` and set the working directory to MethaneScope. Do not run jobs concurrently until locking/re-entrancy has been implemented. Docker Desktop must be available for DB access.

## Knowledge checkpoint

1. Why is `SKIPPED` an acceptable monitoring outcome?
2. What information belongs in a pipeline audit that must **not** be interpreted as scientific validity?
3. What should happen if the database cannot be reached during preflight checks?
4. Why do we save both `last_run.json` and append-only `run_history.jsonl`?
5. Why are notifications and automatic scheduling not enabled by this initial lesson?

**Next Lesson 2.7**: A monitoring dashboard, resilience tests, and safe scheduling after we confirm 2.6 works on your environment.
