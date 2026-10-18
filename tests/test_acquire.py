import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from methanescope.acquire import (
    asset_filename, normalized_stem, usable_assets, describe_results, run, place_verified
)

STEM = 'EMIT_L2B_CH4PLM_002_20220810T064957_000485'
BASE = 'https://data.lpdaac.earthdatacloud.nasa.gov/asset/'


class FakeGranule(dict):
    def __init__(self, stem=STEM, metadata=True):
        super().__init__(umm={'GranuleUR': stem})
        self.stem = stem
        self.has_meta = metadata

    def data_links(self):
        ret = [BASE + self.stem + '.tif']
        if self.has_meta:
            ret.append(BASE + self.stem.replace('CH4PLM_', 'CH4PLMMETA_', 1) + '.json')
        return ret


class AcquisitionTests(unittest.TestCase):
    def test_nasa_metadata_identity(self):
        self.assertEqual(normalized_stem(STEM + '.tif'), normalized_stem(STEM.replace('CH4PLM_', 'CH4PLMMETA_', 1) + '.json'))

    def test_link_safety(self):
        self.assertRaises(ValueError, asset_filename, 'http://test/a.tif')
        self.assertRaises(ValueError, asset_filename, 'https://test/some%2Fpath.tif')
        self.assertEqual(asset_filename(BASE + STEM + '.tif?x=1'), STEM + '.tif')

    def test_asset_pairing(self):
        stem, assets = usable_assets(FakeGranule())
        self.assertEqual(stem, STEM)
        self.assertEqual(len(assets), 2)
        self.assertRaises(ValueError, usable_assets, FakeGranule(metadata=False))

    def test_dry_run_no_login(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            provider = MagicMock()
            provider.search_data.return_value = [FakeGranule()]
            report = run(root, max_new=1, earthaccess_module=provider)
            self.assertEqual(report['mode'], 'DRY_RUN')
            self.assertEqual(report['planned_new_ids'], [STEM])
            provider.login.assert_not_called()
            provider.download.assert_not_called()

    def test_existing_pair_not_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / 'data' / 'raw' / 'nasa_emit'
            raw.mkdir(parents=True)
            (raw / (STEM + '.tif')).write_bytes(b'test')
            (raw / (STEM.replace('CH4PLM_', 'CH4PLMMETA_', 1) + '.json')).write_text('{}')
            items, selected = describe_results(root, [FakeGranule()], 3)
            self.assertEqual(items[0]['status'], 'ALREADY_LOCAL')
            self.assertFalse(selected)

    def test_max_new_clamped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'data').mkdir()
            fake = [FakeGranule(STEM[:-6] + f'{i:06d}') for i in range(10)]
            _, selected = describe_results(root, fake, 3)
            self.assertEqual(len(selected), 3)

    def test_reject_bad_download_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'data').mkdir()
            a = root/(STEM+'.tif'); a.write_bytes(b'not a tiff')
            b = root/(STEM.replace('CH4PLM_', 'CH4PLMMETA_', 1)+'.json')
            b.write_text(json.dumps({'type':'FeatureCollection','features':[]}))
            with self.assertRaises(Exception):
                place_verified(root, a, b, STEM)
            self.assertFalse((root/'data'/'raw'/'nasa_emit').exists())


if __name__ == '__main__':
    unittest.main()

class MockedDownloadIntegrationTests(unittest.TestCase):
    def test_download_stage_then_preserve_on_rerun(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            g = FakeGranule()
            provider = MagicMock()
            provider.search_data.return_value = [g]
            provider.login.return_value.authenticated = True

            def fake_download(items, local_path, **kwargs):
                stage = Path(local_path)
                raster = stage / (STEM + '.tif')
                meta = stage / (STEM.replace('CH4PLM_', 'CH4PLMMETA_', 1) + '.json')
                with rasterio.open(
                    raster, 'w', driver='GTiff', width=8, height=8, count=1,
                    dtype='float32', crs='EPSG:4326', transform=from_origin(30, -10, .001, .001)
                ) as dst:
                    dst.write(np.ones((8,8), dtype='float32'), 1)
                geojson = {'type': 'FeatureCollection', 'features': [
                    {'type': 'Feature', 'properties': {}, 'geometry': {
                        'type': 'Polygon', 'coordinates': [[[30,-10], [30.01,-10], [30.01,-10.01], [30,-10.01], [30,-10]]]
                    }}
                ]}
                meta.write_text(json.dumps(geojson))
                return [raster, meta]

            provider.download.side_effect = fake_download
            first = run(root, execute=True, max_new=1, earthaccess_module=provider)
            self.assertEqual(len(first['downloaded']), 1)
            self.assertEqual(first['downloaded'][0]['status'], 'DOWNLOADED')
            raw = root/'data'/'raw'/'nasa_emit'
            self.assertEqual(len(list(raw.glob('*.tif'))), 1)
            self.assertEqual(len(list(raw.glob('*.json'))), 1)
            second = run(root, execute=True, max_new=1, earthaccess_module=provider)
            self.assertEqual(second['planned_new_ids'], [])
            self.assertEqual(provider.download.call_count, 1)
