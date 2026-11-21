from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / 'packages/linux-aurora'
# Desktop images unlock a LUKS root, run Bluetooth and a firewall, read exFAT
# media and take generic HID input. A kernel without any of these must not ship.
REQUIRED = ('DM_CRYPT', 'DM_INTEGRITY', 'BT', 'NF_TABLES', 'EXFAT_FS', 'HID_GENERIC')


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
    def test_hardware_has_one_source(self):
        recipe = (KERNEL / 'PKGBUILD').read_text()
        self.assertIn('arch/arm64/configs/asahi.config', recipe)
        self.assertNotIn('common.config', recipe)
        self.assertFalse((KERNEL / 'common.config').exists())

    def test_build_uses_the_kernel_source_configuration_and_checks_requirements(self):
        recipe = (KERNEL / 'PKGBUILD').read_text()
        self.assertIn('_make O="$PWD/build/base" aurora_defconfig', recipe)
        # No packaged base or overlay; only the release name is set here.
        self.assertFalse((KERNEL / 'config').exists())
        self.assertNotIn('merge_config.sh', recipe)
        changes = re.findall(r'^\s*scripts/config (.*)$', recipe, re.M)
        self.assertEqual(changes, ["--file build/base/.config --set-str LOCALVERSION '-ARCH' --disable LOCALVERSION_AUTO"])
        self.assertIn('arch/arm64/configs/aurora-base.config arch/arm64/configs/asahi.config build/base/.config',
                      recipe)
        found = re.search(r'for option in ([A-Z0-9_ ]+); do\n\s+grep -Eqx "CONFIG_\$\{option\}=\[ym\]"', recipe)
        self.assertIsNotNone(found)
        self.assertEqual(set(found[1].split()), set(REQUIRED))


if __name__ == '__main__':
    unittest.main()
