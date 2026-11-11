import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'packages' / 'aurora-camera-denoise'


class CameraDenoiseUnitTests(unittest.TestCase):
    def test_user_unit_skips_root_and_system_users(self):
        # camera-denoise#8 (ConditionUser, start limits) is in the pinned
        # commit, and check() runs its unit test (tests/check-unit.sh).
        pkgbuild = (PKG / 'PKGBUILD').read_text()
        pins = json.loads((ROOT / 'sources.json').read_text())
        commit = pins['aurora-camera-denoise']['commit']
        self.assertIn('_commit=' + commit, pkgbuild)
        self.assertNotEqual(commit, '456c567527d6bbba27d0aaeec1199032e0ec88c3')
        self.assertEqual(re.findall(r"'([^']+\.patch)'", pkgbuild), [])
        self.assertIn('meson test -C build', pkgbuild.split('check()', 1)[1])
        self.assertIn(pins['aurora-camera-denoise']['sha256'], pkgbuild)


if __name__ == '__main__':
    unittest.main()
