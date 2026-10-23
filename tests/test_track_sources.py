import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import sys as _sys
_sys.dont_write_bytecode = True  # scripts/ is scanned with bash -n in CI

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('track_sources', ROOT / 'scripts/track-sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NEW = 'c' * 40
TODAY = datetime.date(2026, 10, 23)


class AlarmRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in module.RECIPES.values():
            shutil.copytree(ROOT / 'packages' / name, self.root / 'packages' / name)
        self.pins = json.loads((ROOT / 'sources.json').read_text())

    def item(self, key, **extra):
        return {'key': key, 'old': self.pins[key]['commit'], 'new': NEW, **extra}

    def field(self, name, field):
        for line in (self.root / 'packages' / name / 'PKGBUILD').read_text().splitlines():
            if line.startswith(field + '='):
                return line.split('=', 1)[1]
        raise AssertionError(field)

    def test_aura_moves_commit_qualification_record_and_its_checksum(self):
        item = self.item('aura')
        module.update_recipe(self.root, item, TODAY)
        directory = self.root / 'packages/aura'
        self.assertEqual(self.field('aura', '_commit'), NEW)
        self.assertEqual(self.field('aura', 'pkgver'), '0.1.0.r20261023')
        self.assertEqual(self.field('aura', 'pkgrel'), '1')
        record = json.loads((directory / 'build-qualification.json').read_text())
        self.assertEqual(record['source_commit'], NEW)
        self.assertFalse(record['hardware_tested'])
        digest = hashlib.sha256((directory / 'build-qualification.json').read_bytes()).hexdigest()
        self.assertIn(digest, (directory / 'PKGBUILD').read_text())
        self.assertEqual(item['package_version'], '0.1.0.r20261023-1')

    def test_same_day_aura_update_increments_pkgrel(self):
        pkgbuild = self.root / 'packages/aura/PKGBUILD'
        text = pkgbuild.read_text()
        current = self.field('aura', 'pkgver')
        pkgbuild.write_text(text.replace(f'pkgver={current}', 'pkgver=0.1.0.r20261023'))
        before = int(self.field('aura', 'pkgrel'))
        module.update_recipe(self.root, self.item('aura'), TODAY)
        self.assertEqual(int(self.field('aura', 'pkgrel')), before + 1)

    def test_mesa_version_encodes_upstream_release_date_and_commit(self):
        item = self.item('mesa-aurora', upstream_version='26.3.0-devel', version='26.3.0')
        module.update_recipe(self.root, item, TODAY)
        self.assertEqual(self.field('mesa-aurora', 'pkgver'), '26.3.0_devel.20261023.' + NEW[:11])
        self.assertEqual(self.field('mesa-aurora', 'pkgrel'), '1')
        self.assertEqual(self.field('mesa-aurora', '_commit'), NEW)

    def test_kernel_version_change_resets_pkgrel_and_asks_for_review(self):
        current = self.field('linux-aurora', '_auroraver')
        item = self.item('kernel-aurora', version='7.9.0-rc1', upstream_version='7.9.0-rc1')
        notes = module.update_recipe(self.root, item, TODAY)
        self.assertEqual(self.field('linux-aurora', '_auroraver'), '7.9.0rc1')
        self.assertEqual(self.field('linux-aurora', 'pkgrel'), '1')
        self.assertTrue(any(current in note for note in notes))
        same = self.item('kernel-aurora', version='7.9.0-rc1', upstream_version='7.9.0-rc1')
        same['old'] = NEW
        same['new'] = 'd' * 40
        module.update_recipe(self.root, same, TODAY)
        self.assertEqual(self.field('linux-aurora', 'pkgrel'), '2')

    def test_tracked_sources_have_recipes(self):
        tracking = json.loads((ROOT / 'tracking.json').read_text())
        self.assertEqual(set(tracking['sources']), set(module.RECIPES))
        for name in module.RECIPES.values():
            self.assertTrue((ROOT / 'packages' / name / 'PKGBUILD').is_file())


if __name__ == '__main__':
    unittest.main()
