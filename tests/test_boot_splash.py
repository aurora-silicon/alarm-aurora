"""The splash comes up early and GRUB leaves the boot logo on screen (Fedora #148, #149, #151)."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT/'packages/aurora-boot'
PLYMOUTH = ROOT/'packages/plymouth'
DROPIN = BOOT/'40-aurora-console.cfg'


def grub(defaults):
    """grub-mkconfig sources /etc/default/grub, then each grub.d drop-in."""
    script = (defaults + '\n. "$1"\nprintf "%s|%s|%s" "${GRUB_TERMINAL_OUTPUT-}" '
              '"${GRUB_TIMEOUT_STYLE-}" "${GRUB_TIMEOUT-}"')
    return subprocess.run(['sh', '-c', script, 'sh', str(DROPIN)], check=True,
                          capture_output=True, text=True).stdout.split('|')


class BootSplashTests(unittest.TestCase):
    def test_initramfs_coldplugs_the_display_before_the_other_devices(self):
        hooks = subprocess.run(['bash', '-c', 'source "$1"; printf "%s\\n" "${HOOKS[@]}"', 'test',
                                str(BOOT/'90-aurora.conf')], check=True, capture_output=True, text=True).stdout.split()
        self.assertIn('aurora-early-kms', hooks)
        install = (BOOT/'aurora-early-kms.install').read_text()
        for line in ('add_module appledrm?', 'add_binary bash', 'add_binary udevadm',
                     'add_file /usr/libexec/aurora/aurora-early-kms',
                     'add_file /usr/lib/aurora/initrd/aurora-early-kms.service /usr/lib/systemd/system/aurora-early-kms.service',
                     'add_symlink /usr/lib/systemd/system/sysinit.target.wants/aurora-early-kms.service ../aurora-early-kms.service'):
            self.assertIn('\n  ' + line + '\n', install)
        unit = (BOOT/'aurora-early-kms.service').read_text()
        self.assertIn('\nDefaultDependencies=no\n', unit)
        self.assertIn('\nAfter=systemd-udevd.service\n', unit)
        self.assertIn('\nBefore=systemd-udev-trigger.service plymouth-start.service\n', unit)
        self.assertIn('\nExecStart=/usr/libexec/aurora/aurora-early-kms\n', unit)
        script = (BOOT/'aurora-early-kms').read_text()
        self.assertIn('*Capple,display-subsystem*|*Capple,dcp*)', script)
        # appledrm waits for every DCP: an external DCP's Type-C chain comes up with it.
        self.assertIn('*Capple,*atcphy*|*Capple,*-i2cC*|*Capple,i2c)', script)
        for module in ('i2c-pasemi-platform', 'phy-apple-atc', 'phy-ti-cd2e22', 'tps6598x'):
            self.assertIn(f'\n  add_module {module}?\n', install)
        self.assertIn('"$dev"/supplier:*', script)
        self.assertTrue(script.rstrip().endswith('udevadm trigger --action=add --subsystem-match=drm'))
        # It queues the display ahead of the coldplug but never waits for it.
        self.assertNotIn('--settle', script)
        self.assertNotIn('udevadm settle', script)
        subprocess.run(['bash', '-n', str(BOOT/'aurora-early-kms')], check=True)
        pkgbuild = (BOOT/'PKGBUILD').read_text()
        for line in ('install -Dm644 aurora-early-kms.install "$pkgdir/usr/lib/initcpio/install/aurora-early-kms"',
                     'install -Dm755 aurora-early-kms "$pkgdir/usr/libexec/aurora/aurora-early-kms"',
                     'install -Dm644 aurora-early-kms.service "$pkgdir/usr/lib/aurora/initrd/aurora-early-kms.service"'):
            self.assertIn(line, pkgbuild)
        hook = (BOOT/'aurora-boot.hook').read_text().splitlines()
        for target in ('usr/lib/initcpio/install/aurora-early-kms', 'usr/libexec/aurora/aurora-early-kms',
                       'usr/lib/aurora/initrd/aurora-early-kms.service'):
            self.assertIn('Target = ' + target, hook)

    def test_plymouth_starts_without_waiting_for_the_coldplug(self):
        patch = (PLYMOUTH/'0001-systemd-units-Start-plymouthd-without-waiting-for-coldplug.patch').read_text()
        self.assertIn('\n+After=systemd-vconsole-setup.service systemd-udevd.service dracut-pre-trigger.service\n', patch)
        self.assertIn('patch -Np1 -i "$srcdir/0001-systemd-units-Start-plymouthd-without-waiting-for-coldplug.patch"',
                      (PLYMOUTH/'PKGBUILD').read_text())

    def test_plymouth_keeps_drm_fbdevs_off_the_frame_buffer_plugin(self):
        # Fedora's carry, byte for byte: a DRM-emulated fbdev is the DRM device
        # plymouth already drives, whatever udev has enumerated so far.
        name = '0001-ply-device-manager-Fix-race-in-fb_device_has_drm_dev.patch'
        patch = (PLYMOUTH/name).read_text()
        self.assertIn('drmfb', patch)
        pkgbuild = (PLYMOUTH/'PKGBUILD').read_text()
        apply = f'patch -Np1 -i "$srcdir/{name}"'
        self.assertIn(apply, pkgbuild)
        # git cherry-pick needs a clean tree for ply-device-manager.c.
        self.assertGreater(pkgbuild.index(apply), pkgbuild.index('git cherry-pick -n cea90be39d263e388003a07d125b469c0803d55c'))

    def test_a_serial_console_does_not_force_the_text_splash(self):
        def cmdline(defaults):
            script = defaults + '\n. "$1"\nprintf "%s" "${GRUB_CMDLINE_LINUX-}"'
            return subprocess.run(['sh', '-c', script, 'sh', str(DROPIN)], check=True,
                                  capture_output=True, text=True).stdout
        self.assertEqual(cmdline('GRUB_CMDLINE_LINUX=""'), 'plymouth.ignore-serial-consoles')
        self.assertEqual(cmdline('GRUB_CMDLINE_LINUX="rw"'), 'rw plymouth.ignore-serial-consoles')
        # Already there, on either line: added once only.
        self.assertEqual(cmdline('GRUB_CMDLINE_LINUX_DEFAULT="quiet plymouth.ignore-serial-consoles"'), '')

    def test_grub_stays_on_the_console_unless_the_owner_chose(self):
        arch = 'GRUB_TIMEOUT=5\nGRUB_TIMEOUT_STYLE=menu\n#GRUB_TERMINAL_OUTPUT=console'
        self.assertEqual(grub(arch), ['console', 'hidden', '1'])
        # The owner's own choices win.
        self.assertEqual(grub(arch + '\nGRUB_TERMINAL_OUTPUT=gfxterm'), ['gfxterm', 'hidden', '1'])
        self.assertEqual(grub('GRUB_TIMEOUT=5\nGRUB_TIMEOUT_STYLE=countdown'), ['console', 'countdown', '5'])
        self.assertEqual(grub('GRUB_TIMEOUT=10\nGRUB_TIMEOUT_STYLE=menu'), ['console', 'menu', '10'])
        self.assertEqual(grub('GRUB_TIMEOUT=0\nGRUB_TIMEOUT_STYLE=hidden'), ['console', 'hidden', '0'])
        pkgbuild = (BOOT/'PKGBUILD').read_text()
        self.assertIn('install -Dm644 40-aurora-console.cfg "$pkgdir/etc/default/grub.d/40-aurora-console.cfg"', pkgbuild)
        self.assertIn('install -Dm644 aurora-grub.hook "$pkgdir/usr/share/libalpm/hooks/95-aurora-grub.hook"', pkgbuild)
        # pacman runs hooks in name order; grub-mkconfig must see the kernel that
        # 90-mkinitcpio-install puts back in /boot.
        self.assertGreater('95-aurora-grub.hook', '90-mkinitcpio-install.hook')
        hook = (BOOT/'aurora-grub.hook').read_text()
        self.assertIn('\nTarget = etc/default/grub.d/40-aurora-console.cfg\n', hook)
        self.assertIn('\nTarget = etc/default/grub.d/50-aurora-user4k.cfg\n', hook)
        self.assertIn('\nTarget = usr/lib/modules/*/vmlinuz\n', hook)
        self.assertIn("[ -f /boot/grub/grub.cfg ] && [ -x /usr/bin/grub-mkconfig ] || exit 0; "
                      "exec /usr/bin/grub-mkconfig -o /boot/grub/grub.cfg'", hook)


if __name__ == '__main__':
    unittest.main()
