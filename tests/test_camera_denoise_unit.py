import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'packages' / 'aurora-camera-denoise'


class CameraDenoiseUnitTests(unittest.TestCase):
    def test_user_unit_skips_root_and_system_users(self):
        pkgbuild = (PKG / 'PKGBUILD').read_text()
        patches = re.findall(r"'([^']+\.patch)'", pkgbuild)
        self.assertEqual(patches, ['0001-systemd-skip-root-and-system-users.patch'])
        self.assertIn('patch -d "camera-denoise-$_commit" -p1 < ' + patches[0], pkgbuild)
        text = (PKG / patches[0]).read_text()
        for line in ('+ConditionUser=!root', '+ConditionUser=!@system',
                     '+StartLimitIntervalSec=60', '+StartLimitBurst=5', '+RestartSec=5'):
            self.assertIn(line + '\n', text)
        # check() runs the meson test the patch adds.
        self.assertIn('meson test -C build', pkgbuild.split('check()', 1)[1])


if __name__ == '__main__':
    unittest.main()
