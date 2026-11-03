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
        hooks = sourced('HOOKS')
        self.assertEqual(hooks.index('aurora-usb4'), hooks.index('asahi') + 1)
        hook = [line.strip() for line in (BOOT/'aurora-usb4.install').read_text().splitlines()]
        self.assertIn('add_module thunderbolt_apple?', hook)
        self.assertIn('install -Dm644 aurora-usb4.install "$pkgdir/usr/lib/initcpio/install/aurora-usb4"',
                      (BOOT/'PKGBUILD').read_text())
        config = (ROOT/'packages/linux-aurora/config').read_text().splitlines()
        self.assertIn('CONFIG_USB4_APPLE_SOC=m', config)

    def test_display_chain_and_pmp_come_before_the_root_is_unlocked(self):
        # The T6041 display gate waits 20 s for the PMP driver; on an encrypted
        # root, apple-pmp on the root filesystem arrives only after the passphrase.
        hooks = sourced('HOOKS')
        self.assertIn('aurora-display', hooks)
        self.assertLess(hooks.index('aurora-display'), hooks.index('sd-encrypt'))
        hook = [line.strip() for line in (BOOT/'aurora-display.install').read_text().splitlines()]
        for module in ('apple-pmp?', 'mux-apple-display-crossbar?', 'appledrm?'):
            self.assertIn(f'add_module {module}', hook)
        self.assertIn('install -Dm644 aurora-display.install "$pkgdir/usr/lib/initcpio/install/aurora-display"',
                      (BOOT/'PKGBUILD').read_text())
        self.assertIn('Target = usr/lib/initcpio/install/aurora-display',
                      (BOOT/'aurora-boot.hook').read_text().splitlines())
        config = (ROOT/'packages/linux-aurora/config').read_text().splitlines()
        for option in ('CONFIG_DRM_APPLE=m', 'CONFIG_APPLE_PMP=m'):
            self.assertIn(option, config)

    def test_modules_have_no_optional_suffix(self):
        # The systemd hook writes MODULES to modules-load.d unchanged, and
        # systemd-modules-load has no optional "name?" form.
        self.assertEqual([m for m in sourced('MODULES') if m.endswith('?')], [])

    def test_initramfs_is_rebuilt_when_the_boot_configuration_changes(self):
        hook = (BOOT/'aurora-boot.hook').read_text().splitlines()
        self.assertIn('Target = etc/mkinitcpio.conf.d/90-aurora.conf', hook)
        self.assertIn('Target = usr/lib/initcpio/install/aurora-usb4', hook)
        self.assertIn('Exec = /usr/bin/mkinitcpio -P', hook)
        pkgbuild = (BOOT/'PKGBUILD').read_text()
        self.assertIn("'aurora-boot.hook'", pkgbuild)
        self.assertIn('install -Dm644 aurora-boot.hook "$pkgdir/usr/share/libalpm/hooks/95-aurora-boot.hook"',
                      pkgbuild)


if __name__ == '__main__':
    unittest.main()
