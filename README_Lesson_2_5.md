# MethaneScope AI — Lesson 2.5: Your first reusable ingestion application

**Starting point:** You completed Lesson 2.3 with `ACCEPTED = 1` and Lesson 2.4 with `INSERTED = 1`, `stored_granules = 1`, `stored_features = 1`. The previous database schema remains in place. We will not recreate, delete, or reset the database.

## Learning objectives

By the end of this lesson, you should be able to explain the difference between (a) discovery, (b) engineering validation, (c) transactional database ingestion and (d) audit logging, run the pipeline from Git Bash without opening a notebook, and prove that reprocessing the same input is idempotent.

## What this version does (and doesn't)

**It does:** inventory EMIT `CH4PLM` / `CH4PLMMETA` pairs, independently revalidate an accepted Lesson 2.3 manifest, re-check checksums and geometries, store into the **existing Lesson 2.4 tables**, write structured run audits, and report counts. It does not modify raw NASA files.

**It does not yet:** schedule new downloads, discover data through NASA Earthdata APIs, produce validated emission rates, ingest other satellite missions, deploy to Azure, or claim scientific validation. Those are later stages. Discovering files does NOT classify them ACCEPTED; Lesson 2.3 remains the separate acceptance gate.

## Installation (Windows + Git Bash)

1. Open the **existing** `MethaneScope` folder in Windows Explorer. Extract this ZIP **into the MethaneScope root**, not into `data/`, and make sure `methanescope/pipeline.py` is immediately under your project root. Keep your previous notebooks, `data/`, `outputs/`, `.env`, and Docker volume unchanged.
2. Start Docker Desktop. In Git Bash, from the MethaneScope folder, run:

```bash
source .venv/Scripts/activate
docker compose -f docker-compose.postgis.yml up -d
docker compose -f docker-compose.postgis.yml ps
python -m pip install -r requirements-lesson25.txt
```

3. Check that `outputs/emit_batch/emit_accepted_for_ingestion.csv` still exists and has your accepted NASA record; the ZIP deliberately contains **no raw NASA files or manifests**, and won't replace them.
4. Run **one command at a time**:

```bash
python -m methanescope.pipeline discover
python -m methanescope.pipeline validate
python -m methanescope.pipeline ingest
python -m methanescope.pipeline status
python -m pytest -q tests/test_science.py
```

Or open the included `07_automated_satellite_ingestion.ipynb` in JupyterLab and execute its code cells in order. The notebook runs the same package via your active Python executable.

## Expected behaviour for your current data

Because Lesson 2.4 **already inserted** the one NASA EMIT granule, the Lesson 2.5 `ingest` command should normally print **`SKIPPED`**, not `INSERTED`. This is the desired outcome: no duplicate granule is created. Run `status` to confirm counts. If you see `CONFLICT` or `ERROR`, stop and share the exact message; do not delete the database or source files.

`discover` should report `MATCHED` for the CH4PLM raster and its CH4PLMMETA metadata. `validate` should report `VALID` for the accepted record. They are different checks.

If `ingest` reports `INSERTED`, it may be because you connected to another fresh database. Check the `.env` configuration and prior Lesson 2.4 audit before assuming this is an error.

## Outputs

- `outputs/pipeline/discovered_candidates.csv` — inventory only, not approval
- `outputs/pipeline/<timestamp>_validate_outcomes.csv` — validation detail
- `outputs/pipeline/<timestamp>_ingest_outcomes.csv` — insertion/skip/conflict detail
- `outputs/pipeline/<timestamp>_ingest_summary.json` — ingest counts and source
- `outputs/pipeline/pipeline.log` — time-stamped log, no database password

## Scientific warning

A valid ingestion record is not necessarily a scientifically valid methane emission estimate. EMIT enhancement (`ppm m`) is not emission rate (`kg/h`). We never turn the raster maximum into an annual emission estimate.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Docker not found | Start Docker Desktop and verify CLI |
| Connection timeout | `docker compose -f docker-compose.postgis.yml ps`; expect healthy port 5433 |
| `.env` missing | Keep your Lesson 2.4 `.env` in the project root; never share passwords |
| `No ACCEPTED records` | Re-run fixed Lesson 2.3 in `MODE="real"` and investigate QA |
| `Raster/metadata identity mismatch` | Should be `CH4PLM` paired with `CH4PLMMETA` and identical version/time/id |
| `SHA-256 changed` | Source files changed since the manifest was produced; re-run Lesson 2.3, don't bypass checks |
| `Missing table ...` | Finish Lesson 2.4; 2.5 does not migrate existing schemas |
| `SKIPPED` | Success: same real granule already ingested |
| `CONFLICT` | Stop: same ID or checksum differs; investigate, don't delete |

## Knowledge checkpoint

1. Why must `discover` never automatically label a file ACCEPTED?
2. What is the difference between a checksum and a granule ID?
3. Why are we expecting `SKIPPED` on the first Lesson 2.5 database run?
4. Why should one granule and all its associated GeoJSON features be written within one database transaction?
5. What would you need to change before calling this a production ingestion system?

**Next lesson (2.6):** Quality monitoring, failure classification, and a small scheduled batch runner. We will tackle one capability at a time.
