# MethaneScope AI · Lesson 2.10 — Real NASA EMIT Multi-Granule Acquisition

## Goal
Extend the **existing** MethaneScope project from 1 stored NASA EMIT granule to a *small collection of independent granules*, without deleting or rewriting any original files or existing PostGIS tables. This adds **download** capability, not unattended scheduling.

### Proven current baseline (from your Lesson 2.9 screenshot)
- All **25 earlier tests passed**.
- 1 real EMIT CH4PLM V002 granule is already stored in PostGIS, with 1 GeoJSON feature.
- The ingestion pipeline correctly returns `SKIPPED` for a repeated granule.
- Scientific validation of methane emissions remains **NOT_ESTABLISHED**.

## Contents (additive only)
```
MethaneScope/
  methanescope/acquire.py                         # NEW, do not replace pipeline.py
  tests/test_acquire.py                           # NEW
  12_multi_granule_nasa_emit_acquisition.ipynb    # NEW
  README_Lesson_2_10.md                           # NEW
```

Extract ZIP into your **existing** `MethaneScope` folder. Existing files named `.env`, `data/`, `outputs/`, `docker-compose.postgis.yml`, `pipeline.py`, `store.py`, `monitor.py`, `scheduler.py` should not be deleted or replaced.

## Before you begin
1. Use Git Bash in your existing MethaneScope root.
2. Activate your established environment: `source .venv/Scripts/activate`.
3. Install the Earthdata downloader: `python -m pip install earthaccess`.
4. Sign up for a free NASA Earthdata Login if needed at https://urs.earthdata.nasa.gov/users/new.
5. Ensure your internet connection and free disk space are adequate. Version 2 files are not guaranteed to be tiny; begin with 2–3 granules, not 20.
6. **Docker is optional during NASA catalogue discovery and download**; Docker/PostGIS is required only for database ingestion.

## 1. Execute tests
```bash
python -m pytest -q tests/test_acquire.py
python -m pytest -q tests/test_science.py tests/test_monitor.py tests/test_reliability.py tests/test_scheduler.py tests/test_acquire.py
```
The added module has **8 locally executed tests passing** (with a mock NASA API and a generated test GeoTIFF). The combined total on your workstation should be 33 if your earlier 25 still pass. Neither live NASA authentication nor real downloads were possible to test here. Report genuine failures instead of forcing the expected number.

## 2. Discover NASA granules (READ-ONLY with respect to your NASA files and DB)
```bash
python -m methanescope.acquire plan --search-limit 40 --max-new 3
```
The plan searches NASA's `EMITL2BCH4PLM` collection at `version=002`, filters for paired raster and GeoJSON-metadata assets, and selects up to three granules *not already present locally*. It prefers different observation days if available. Discovery writes `outputs/acquisition/last_plan.json`.

If fewer than three are found, try a different search limit or an appropriate window, for example:
```bash
python -m methanescope.acquire plan --search-limit 100 --max-new 3 --temporal-start 2024-01-01 --temporal-end 2025-12-31
```
The dataset is event-filtered: there may be no plume granules for some dates/areas. NASA EMIT also had an acquisition gap from September 2022 to January 2023.

## 3. Explicitly download a SMALL batch
Only after reviewing the plan, run:
```bash
python -m methanescope.acquire download --search-limit 40 --max-new 3 --execute
```
This command prompts for Earthdata Login if necessary. It downloads to a temporary staging directory, checks the raster and GeoJSON structure, and moves valid pairs to `data/raw/nasa_emit/` using original filenames. It **refuses to overwrite** an existing file if the bytes differ. The report is `outputs/acquisition/last_download.json`.

If `ERROR`, inspect the staging directory named in the report; do not rename original NASA files or disable validation.

**Do not share NASA credentials/tokens** in notebook screenshots or logs.

## 4. Rerun the existing Lesson 2.3 QA (MANDATORY)
Back up your previously accepted CSV:
```bash
cp outputs/emit_batch/emit_accepted_for_ingestion.csv outputs/emit_batch/emit_accepted_before_lesson210.csv
```
Open `MethaneScope_Lesson_2_3_NASA_Metadata_Pairing_Fixed.ipynb` in JupyterLab. Set `MODE = "real"`. Then **Restart Kernel and Run All Cells**. Carefully inspect all REVIEW, CONFLICT and REJECTED records. Only the `ACCEPTED` manifest gets ingested.

## 5. Ingest accepted records without editing SQL schema
```bash
docker compose -f docker-compose.postgis.yml up -d
python -m methanescope.pipeline discover
python -m methanescope.pipeline validate
python -m methanescope.scheduler plan
python -m methanescope.scheduler run --execute
python -m methanescope.pipeline status
```
The previously stored observation should be `SKIPPED`; new validated records should be `INSERTED`. If `ERROR` or `CONFLICT` appears, STOP, read the audit JSON, and fix the root issue. Do not drop volumes/tables or force acceptance.

## 6. Study in JupyterLab
Open `12_multi_granule_nasa_emit_acquisition.ipynb` from your MethaneScope project root. Its `ALLOW_DOWNLOAD` flag starts `False` as an additional safeguard. It includes notebook-based discovery, cautious download, QA instructions, a read-only PostGIS analysis query, and scientific questions.

### Science you must remember
- A plume product shows detections and is **not** a catalogue of all observing opportunities.
- **Do not estimate source persistency** as `number of plume detections / number of plume files`; this lacks a denominator of valid non-detections and knowledge of detection sensitivity.
- Methane enhancement in **ppm m** does not directly equal emission rate in **kg/h**.
- Separate raster footprints from plume polygon geometries and from emission-source location estimates.
- Multiple granules do not imply distinct emission events or distinct sources.

## Troubleshooting
| Problem | First action |
|---|---|
| `ModuleNotFoundError: earthaccess` | `python -m pip install earthaccess` from your `.venv` |
| No granules found | Increase `--search-limit`; try a sensible temporal range; review NASA product availability |
| NASA login fails | Confirm your Earthdata account; rerun `earthaccess.login()` locally; never publish credentials |
| Missing/ambiguous `CH4PLMMETA` pair | Check `outputs/acquisition/last_plan.json`, do not guess matches |
| Acquisition `ERROR` | Read `last_download.json` and staging folder; stop rather than ingest |
| No new `ACCEPTED` records | Inspect Lesson 2.3 `emit_batch_issues.json` |
| PostGIS connection fails | `docker compose -f docker-compose.postgis.yml ps`; check `.env` and port `5433` |
| Database says `SKIPPED` | Normal for a granule already stored unchanged |

## Official documentation
- Dataset DOI: https://doi.org/10.5067/EMIT/EMITL2BCH4PLM.002
- Earthaccess: https://earthaccess.readthedocs.io/en/stable/user/quick-start/
- NASA EMIT data-access tutorial: https://nasa.github.io/LPDAAC-Data-Resources/external/How_to_find_and_access_EMIT_data.html
- EMIT plume timeseries: https://nasa.github.io/LPDAAC-Data-Resources/external/Visualizing_Methane_Plume_Timeseries.html
