from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / 'packages/linux-aurora'
# Desktop images unlock a LUKS root, run Bluetooth and a firewall, read exFAT
# media and take generic HID input. A kernel without any of these must not ship.
REQUIRED = ('DM_CRYPT', 'DM_INTEGRITY', 'BT', 'NF_TABLES', 'EXFAT_FS', 'HID_GENERIC')
# Apple N1 radio drivers: required whenever the pinned source defines them.
RADIOS = ('APPLE_CENTAURI', 'APPLE_CENTAURI_T6050', 'APPLE_CENTAURI_T6050_WIFI', 'BT_CENTAURI', 'BT_HCICENTAURI')


def values(path):
    result = {}
    for line in path.read_text().splitlines():
        found = re.match(r'(CONFIG_[A-Za-z0-9_]+)=(.*)$', line)
        if found:
            result[found[1]] = found[2]
        found = re.match(r'# (CONFIG_[A-Za-z0-9_]+) is not set$', line)
        if found:
            result[found[1]] = 'n'
    return result


class KernelConfigTests(unittest.TestCase):
    def test_full_config_keeps_the_desktop_requirements(self):
        config = values(KERNEL / 'config')
        for option in REQUIRED:
            with self.subTest(option=option):
                self.assertIn(config.get('CONFIG_' + option, 'n'), ('y', 'm'))
        self.assertEqual(config.get('CONFIG_RUST'), 'y')

    def test_hardware_has_one_source(self):
        recipe = (KERNEL / 'PKGBUILD').read_text()
        self.assertIn('arch/arm64/configs/asahi.config', recipe)
        self.assertNotIn('common.config', recipe)
        self.assertFalse((KERNEL / 'common.config').exists())

    def test_build_starts_from_the_full_config_and_checks_requirements(self):
        recipe = (KERNEL / 'PKGBUILD').read_text()
        self.assertIn('cp ../config build/base/.config', recipe)
        self.assertNotIn(' defconfig\n', recipe)
        found = re.search(r'for option in ([A-Z0-9_ ]+); do\n\s+grep -Eqx "CONFIG_\$\{option\}=\[ym\]"', recipe)
        self.assertIsNotNone(found)
        self.assertEqual(set(found[1].split()), set(REQUIRED))

    def test_build_requires_the_n1_radio_drivers_the_source_defines(self):
        recipe = (KERNEL / 'PKGBUILD').read_text()
        found = re.search(r'for option in ([A-Z0-9_ ]+); do\n'
                          r'\s+grep -rqx --include=\'Kconfig\*\' "config \$\{option\}" drivers \|\| continue\n'
                          r'\s+grep -Eqx "CONFIG_\$\{option\}=\[ym\]" build/base/\.config', recipe)
        self.assertIsNotNone(found)
        self.assertEqual(set(found[1].split()), set(RADIOS))


if __name__ == '__main__':
    unittest.main()
