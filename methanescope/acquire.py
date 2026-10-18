"""MethaneScope Lesson 2.10 — cautious acquisition of NASA EMIT CH4PLM V002.

No database modifications. No automatic schedule. Only --execute downloads.
Searches NASA Earthdata CMR for real granules; downloads each pair into a
staging directory, validates pair structure, and refuses overwrite conflicts.
The existing Lesson 2.3 remains the authority for scientific-data ingestion QA.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse, unquote
from uuid import uuid4

PRODUCT = 'EMITL2BCH4PLM'
VERSION = '002'
STEM_RE = re.compile(r'^EMIT_L2B_CH4PLM_002_(\d{8}T\d{6})_([A-Za-z0-9]+)$', re.I)
EXTENSIONS = {'.tif': 'raster', '.tiff': 'raster', '.json': 'metadata', '.geojson': 'metadata'}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalized_stem(filename: str):
    """NASA CH4PLMMETA is metadata for corresponding CH4PLM raster."""
    stem = Path(filename).stem
    stem = re.sub(r'(?i)^EMIT_L2B_CH4PLMMETA_', 'EMIT_L2B_CH4PLM_', stem)
    return stem.upper()


def asset_filename(url: str):
    parts = urlparse(url)
    if parts.scheme != 'https' or not parts.hostname:
        raise ValueError('Only HTTPS archive links are allowed')
    # Safely extract final filename, rather than trusting remote directory paths.
    name = unquote(parts.path.rsplit('/', 1)[-1])
    if not name or '/' in name or '\\' in name or name in {'.', '..'}:
        raise ValueError('Unsafe remote filename')
    return name


def usable_assets(granule) -> tuple[str, dict[str, str]]:
    """Select exactly one matched EMIT V002 TIF+JSON pair per CMR granule.

    Other assets are ignored, but any duplicate matching raster or metadata
    within the granule causes an ambiguity error rather than a guess.
    """
    grouped: dict[str, dict[str, list[str]]] = {}
    for url in granule.data_links():
        name = asset_filename(str(url))
        kind = EXTENSIONS.get(Path(name).suffix.lower())
        if not kind:
            continue
        stem = normalized_stem(name)
        if not STEM_RE.fullmatch(stem):
            continue
        grouped.setdefault(stem, {'raster': [], 'metadata': []})[kind].append(str(url))
    pairs = [(stem, a) for stem, a in grouped.items() if len(a['raster']) == 1 and len(a['metadata']) == 1]
    if len(pairs) != 1:
        raise ValueError(f'Expected one unambiguous EMIT V002 raster/metadata pair; found {len(pairs)}')
    stem, assets = pairs[0]
    # Any duplicate matching links for the selected stem makes it ambiguous.
    return stem, {key: val[0] for key, val in assets.items()}


def local_pair(root: Path, stem: str) -> bool:
    """True only when both expected files already exist in the raw archive."""
    raw = root / 'data' / 'raw' / 'nasa_emit'
    rasters = list(raw.rglob(stem + '.tif')) + list(raw.rglob(stem + '.tiff'))
    metas = list(raw.rglob(stem.replace('CH4PLM_', 'CH4PLMMETA_', 1) + '.json'))
    metas += list(raw.rglob(stem + '.json'))
    metas += list(raw.rglob(stem + '.geojson'))
    return bool(rasters and metas)


def describe_results(root: Path, results: list, max_new: int):
    records, selected = [], []
    seen = set()
    selected_days = set()
    for granule in results:
        try:
            stem, assets = usable_assets(granule)
        except ValueError as exc:
            records.append({'id': str(granule.get('umm', {}).get('GranuleUR', 'unknown')),
                            'status': 'REVIEW', 'reason': str(exc)})
            continue
        if stem in seen:
            records.append({'id': stem, 'status': 'DUPLICATE_SEARCH_RESULT'})
            continue
        seen.add(stem)
        if local_pair(root, stem):
            records.append({'id': stem, 'status': 'ALREADY_LOCAL'})
        else:
            item = {'id': stem, 'status': 'AVAILABLE',
                    'raster_filename': asset_filename(assets['raster']),
                    'metadata_filename': asset_filename(assets['metadata'])}
            records.append(item)
            # Prefer distinct observation dates among available results in first pass.
            date = STEM_RE.fullmatch(stem).group(1)[:8]
            if len(selected) < max_new and date not in selected_days:
                selected.append((granule, stem, assets))
                selected_days.add(date)
    # Fill remaining slots without constraining to distinct dates.
    if len(selected) < max_new:
        chosen = {stem for _, stem, _ in selected}
        for granule in results:
            try:
                stem, assets = usable_assets(granule)
            except ValueError:
                continue
            if stem not in chosen and not local_pair(root, stem):
                selected.append((granule, stem, assets))
                chosen.add(stem)
            if len(selected) == max_new:
                break
    return records, selected


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_pair_files(raster: Path, metadata: Path, stem: str) -> dict:
    import rasterio
    from shapely.geometry import shape
    if normalized_stem(raster.name) != stem or normalized_stem(metadata.name) != stem:
        raise ValueError('Downloaded file identities do not match planned granule')
    if raster.stat().st_size == 0 or metadata.stat().st_size == 0:
        raise ValueError('Empty downloaded asset')
    with rasterio.open(raster) as src:
        if src.count != 1 or src.crs is None or src.width < 1 or src.height < 1:
            raise ValueError('Raster missing its single band or georeferencing')
        footprint = list(src.bounds)
    with metadata.open(encoding='utf-8') as f:
        content = json.load(f)
    features = (content.get('features') if content.get('type') == 'FeatureCollection'
                else [content] if content.get('type') == 'Feature' else None)
    if not features or len(features) > 10000:
        raise ValueError('Metadata contains no usable GeoJSON features')
    for i, feat in enumerate(features):
        if feat.get('type') != 'Feature' or not feat.get('geometry'):
            raise ValueError(f'Metadata feature {i} is missing geometry')
        geom = shape(feat['geometry'])
        if geom.is_empty or not geom.is_valid:
            raise ValueError(f'Invalid metadata geometry {i}')
    return {'id': stem, 'raster_sha256': sha256(raster), 'metadata_sha256': sha256(metadata),
            'feature_count': len(features), 'raster_bounds_native_crs': footprint}


def place_verified(root: Path, raster: Path, metadata: Path, stem: str) -> dict:
    """Move validated assets to raw archive without overwriting prior observations."""
    facts = verify_pair_files(raster, metadata, stem)
    raw = root / 'data' / 'raw' / 'nasa_emit'
    raw.mkdir(parents=True, exist_ok=True)
    paths = (raster, metadata)
    for src in paths:
        dest = raw / src.name
        if dest.exists() and sha256(dest) != sha256(src):
            raise RuntimeError(f'Conflict: destination already exists with different contents: {dest}')
    moved = []
    for src in paths:
        dest = raw / src.name
        if not dest.exists():
            src.replace(dest)
        moved.append(str(dest.relative_to(root)))
    return {**facts, 'status': 'DOWNLOADED', 'files': moved}


def run(root: Path, *, execute: bool = False, search_limit: int = 30,
        max_new: int = 3, temporal: tuple[str, str] | None = None,
        earthaccess_module=None) -> dict:
    if not 1 <= search_limit <= 200:
        raise ValueError('search-limit must be between 1 and 200')
    if not 1 <= max_new <= 10:
        raise ValueError('max-new must be between 1 and 10')
    root = root.resolve()
    if not (root / 'data').is_dir():
        raise FileNotFoundError('Run from existing MethaneScope project root (data/ missing)')
    if earthaccess_module is None:
        import earthaccess as earthaccess_module
    params = {'short_name': PRODUCT, 'version': VERSION, 'count': search_limit}
    if temporal:
        params['temporal'] = temporal
    results = earthaccess_module.search_data(**params)
    records, selected = describe_results(root, results, max_new)
    report: dict = {'generated_utc': utc_now(), 'product': PRODUCT, 'version': VERSION,
                    'mode': 'DOWNLOAD' if execute else 'DRY_RUN', 'searched': len(results),
                    'status_counts': dict(Counter(x['status'] for x in records)),
                    'planned_new_ids': [s for _, s, _ in selected],
                    'downloaded': [], 'items': records,
                    'scientific_validation': 'NOT_ESTABLISHED'}
    target = root / 'outputs' / 'acquisition'
    target.mkdir(parents=True, exist_ok=True)
    # Dry-run never calls login or download.
    if execute and selected:
        auth = earthaccess_module.login()
        if not getattr(auth, 'authenticated', False):
            raise RuntimeError('NASA Earthdata authentication did not succeed')
        for granule, stem, assets in selected:
            stage = root / 'data' / 'staging' / 'emit_lesson210' / (stem + '_' + uuid4().hex[:10])
            stage.mkdir(parents=True, exist_ok=False)
            try:
                # NASA supplies one raster and metadata document per plume granule.
                downloaded = earthaccess_module.download([granule], local_path=str(stage), threads=1, force=False)
                files = [Path(p) for p in downloaded]
                candidates_r = [p for p in files if p.is_file() and p.suffix.lower() in {'.tif', '.tiff'} and normalized_stem(p.name) == stem]
                candidates_m = [p for p in files if p.is_file() and p.suffix.lower() in {'.json', '.geojson'} and normalized_stem(p.name) == stem]
                if len(candidates_r) != 1 or len(candidates_m) != 1:
                    raise ValueError(f'Expected exactly one raster and metadata for {stem}; got {len(candidates_r)} raster(s) and {len(candidates_m)} metadata file(s)')
                item = place_verified(root, candidates_r[0], candidates_m[0], stem)
                report['downloaded'].append(item)
            except Exception as exc:
                report['downloaded'].append({'id': stem, 'status': 'ERROR', 'message': f'{type(exc).__name__}: {exc}', 'staging_folder': str(stage)})
                break  # Stop after first failure; do not continue blind downloads.
    outfile = target / ('last_download.json' if execute else 'last_plan.json')
    outfile.write_text(json.dumps(report, indent=2), encoding='utf-8')
    report['report_file'] = str(outfile.relative_to(root))
    return report


def main():
    parser = argparse.ArgumentParser(description='NASA EMIT V002 cautious multi-granule acquisition')
    parser.add_argument('command', choices=['plan', 'download'])
    parser.add_argument('--root', default='.', type=Path)
    parser.add_argument('--search-limit', type=int, default=30)
    parser.add_argument('--max-new', type=int, default=3)
    parser.add_argument('--temporal-start', default=None)
    parser.add_argument('--temporal-end', default=None)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if bool(args.temporal_start) != bool(args.temporal_end):
        parser.error('Provide both --temporal-start and --temporal-end')
    if args.command == 'plan' and args.execute:
        parser.error('The plan command cannot execute downloads')
    temporal = (args.temporal_start, args.temporal_end) if args.temporal_start else None
    try:
        report = run(args.root, execute=(args.command == 'download' and args.execute),
                     search_limit=args.search_limit, max_new=args.max_new, temporal=temporal)
        print(json.dumps({k:v for k,v in report.items() if k != 'items'}, indent=2))
        return 1 if any(x.get('status') == 'ERROR' for x in report['downloaded']) else 0
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f'ACQUISITION BLOCKED: {type(exc).__name__}: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
