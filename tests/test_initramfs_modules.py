"""The initramfs carries the USB4 router with the Type-C port controllers."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT/'packages/aurora-boot'


def sourced(array):
    script = f'source "$1"; printf "%s\\n" "${{{array}[@]}}"'
    return subprocess.run(['bash', '-c', script, 'test', str(BOOT/'90-aurora.conf')],
                          check=True, text=True, capture_output=True).stdout.split()


class InitramfsModuleTests(unittest.TestCase):
    def test_usb4_router_comes_with_the_type_c_controllers(self):
        # The asahi hook carries tps6598x and sn201202x but not their router.
        self.assertIn('asahi', sourced('HOOKS'))
        self.assertIn('thunderbolt_apple?', sourced('MODULES'))
        config = (ROOT/'packages/linux-aurora/config').read_text().splitlines()
        self.assertIn('CONFIG_USB4_APPLE_SOC=m', config)

    def test_initramfs_is_rebuilt_when_the_boot_configuration_changes(self):
        hook = (BOOT/'aurora-boot.hook').read_text().splitlines()
        self.assertIn('Target = etc/mkinitcpio.conf.d/90-aurora.conf', hook)
        self.assertIn('Exec = /usr/bin/mkinitcpio -P', hook)
        pkgbuild = (BOOT/'PKGBUILD').read_text()
        self.assertIn("'aurora-boot.hook'", pkgbuild)
        self.assertIn('install -Dm644 aurora-boot.hook "$pkgdir/usr/share/libalpm/hooks/95-aurora-boot.hook"',
                      pkgbuild)


if __name__ == '__main__':
    unittest.main()
