import configparser
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'packages/aurora-m5-platform-config'


def ini(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


class M5PlatformConfigTests(unittest.TestCase):
    def test_policy_unit_runs_on_the_j714s_only_before_logind(self):
        unit = ini(PKG / 'aurora-m5-sleep-policy.service')
        self.assertEqual(unit['Unit']['ConditionFirmware'], 'device-tree-compatible(apple,j714s)')
        self.assertEqual(unit['Service']['Type'], 'oneshot')
        self.assertIn('systemd-logind.service', unit['Unit']['Before'].split())
        self.assertNotIn('Install', unit)
        lines = (PKG / 'aurora-m5-sleep-policy.service').read_text().splitlines()
        self.assertEqual([l.split()[-1] for l in lines if l.startswith('ExecStart=')], [
            '/run/systemd/sleep.conf.d/90-aurora-m5-deep.conf',
            '/run/systemd/logind.conf.d/90-aurora-m5-lid.conf'])
        pkgbuild = (PKG / 'PKGBUILD').read_text()
        self.assertIn('ln -s ../aurora-m5-sleep-policy.service '
                      '"$pkgdir/usr/lib/systemd/system/sysinit.target.wants/aurora-m5-sleep-policy.service"', pkgbuild)
        self.assertIn("backup=('etc/aurora-m5-sleep.conf')", pkgbuild)

    def test_deep_sleep_only_and_the_lid_suspends(self):
        self.assertEqual(dict(ini(PKG / '90-aurora-m5-deep.conf')['Sleep']),
                         {'AllowSuspend': 'yes', 'SuspendState': 'mem', 'MemorySleepMode': 'deep'})
        lid = ini(PKG / '90-aurora-m5-lid.conf')['Login']
        self.assertEqual(dict(lid), {'HandleLidSwitch': 'suspend', 'HandleLidSwitchExternalPower': 'suspend',
                                     'HandleLidSwitchDocked': 'suspend'})

    def test_rtc_hook_checks_the_board_first(self):
        hook = (PKG / '50-aurora-m5-rtc-safety').read_text().splitlines()
        first = next(line for line in hook if line and not line.startswith('#'))
        self.assertEqual(first, "tr '\\0' '\\n' < /proc/device-tree/compatible 2>/dev/null"
                                " | grep -qx 'apple,j714s' || exit 0")
        compatible = Path('/proc/device-tree/compatible')
        if compatible.is_file() and b'apple,j714s' in compatible.read_bytes().split(b'\0'):
            self.skipTest('would arm the RTC alarm of this J714s')
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['sh', str(PKG / '50-aurora-m5-rtc-safety'), 'pre'], cwd=tmp,
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        if compatible.exists():
            self.assertEqual(result.stderr, '')
        else:
            # A host with no device tree (the CI runners): the shell opens the file before the
            # 2>/dev/null applies and prints that one error. Every Mac has the file.
            self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
            self.assertIn('/proc/device-tree/compatible', result.stderr)

    def test_aurora_boot_pulls_it_in(self):
        self.assertIn("'aurora-m5-platform-config'", (ROOT / 'packages/aurora-boot/PKGBUILD').read_text())


if __name__ == '__main__':
    unittest.main()
