# MethaneScope AI — Lesson 2.8: Controlled failure testing

This is an **additive-only teaching package** for an existing Lesson 2.6/2.7 project. It contains **only new files**:
- `10_failure_recovery_sandbox.ipynb`
- `tests/test_reliability.py`

**Do not delete or overwrite** `methanescope/`, existing notebooks, `.env`, `data/`, `outputs/`, Docker volumes, or PostGIS tables. No Docker shutdown or database mutation is part of these drills.

## Quick start

1. Extract the ZIP into your existing MethaneScope folder.
2. Activate `.venv` in Git Bash.
3. Run:

```bash
python -m pytest -q tests/test_science.py tests/test_monitor.py tests/test_reliability.py
```

Expected: **16 passed** with the baseline 11 previously verified tests.
4. Open JupyterLab: `python -m jupyter lab`.
5. Run notebook `10_failure_recovery_sandbox.ipynb` top to bottom.

## What the notebook does

- Reads `outputs/monitoring/run_history.jsonl` *without changing it*.
- Simulates `PREFLIGHT`, `DATA_VALIDATION`, `INGESTION`, and recovered `SUCCESS` runs with `unittest.mock` and `tempfile.TemporaryDirectory`.
- Shows that validation failures block ingestion.
- Plots **synthetic** monitor outcomes, never presented as real NASA pipeline reliability metrics.

## Why this is safe

- Each failure scenario patches the health checker and Python pipeline function in memory.
- Logs are written only under temporary directories automatically cleaned up after each drill.
- All tests use pytest's `tmp_path`, never your actual NASA files or PostgreSQL database.
- There is no automatic scheduling, retry loop, Docker command, external notification, or schema modification.

## Next planned milestone

Lesson 2.9 will address operational scheduling, concurrency protection, retry/backoff policy, and multi-granule workload tests. Those require separate validation before enabling any schedule.
