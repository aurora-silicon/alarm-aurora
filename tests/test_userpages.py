"""The kernel recipe ships the userpages launcher and turns user4k=on by default."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / 'packages/linux-aurora'
PKGBUILD = (KERNEL / 'PKGBUILD').read_text()
DROPIN = KERNEL / '50-aurora-user4k.cfg'


def grub_cmdline(linux, default):
    """grub-mkconfig sources /etc/default/grub, then each grub.d drop-in."""
    script = 'GRUB_CMDLINE_LINUX=$1; GRUB_CMDLINE_LINUX_DEFAULT=$2; . "$3"; printf "%s|%s" "$GRUB_CMDLINE_LINUX" "$GRUB_CMDLINE_LINUX_DEFAULT"'
    return subprocess.run(['sh', '-c', script, 'sh', linux, default, str(DROPIN)], check=True,
                          capture_output=True, text=True).stdout.split('|')


class UserPagesTests(unittest.TestCase):
    def test_split_package_is_built_from_the_kernel_source(self):
        self.assertRegex(PKGBUILD, r'(?m)^pkgname=\("\$pkgbase" "\$pkgbase-headers" aurora-userpages\)$')
        build = PKGBUILD.split('\nbuild() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('\n  make -C tools/aurora-userpages', build)
        package = PKGBUILD.split('\npackage_aurora-userpages() {', 1)[1].split('\n}', 1)[0]
        for line in ('install -Dm755 tools/aurora-userpages/userpages "$pkgdir/usr/bin/userpages"',
                     'install -Dm644 tools/aurora-userpages/README.rst "$pkgdir/usr/share/doc/aurora-userpages/README.rst"',
                     'install -Dm644 "$srcdir/50-aurora-user4k.cfg" "$pkgdir/etc/default/grub.d/50-aurora-user4k.cfg"',
                     'install -Dm644 "$srcdir/aurora-userpages.hook" "$pkgdir/usr/share/libalpm/hooks/90-aurora-userpages.hook"'):
            self.assertIn(line, package)
        # An ordinary upgrade of the kernel installs it on existing systems.
        kernel = PKGBUILD.split('\n_package_kernel() {', 1)[1].split('\n}', 1)[0]
        self.assertRegex(kernel, r'(?m)^  depends=\(.*\baurora-userpages\)$')

    def test_local_sources_match_their_checksums(self):
        sources = re.search(r'(?s)\nsource=\((.*?)\)\n', PKGBUILD).group(1).split()
        sums = re.search(r'(?s)\nsha256sums=\((.*?)\)\n', PKGBUILD).group(1).replace("'", '').split()
        self.assertEqual(len(sources), len(sums))
        for source, digest in zip(sources, sums):
            if '::' in source:
                continue
            with self.subTest(source=source):
                self.assertEqual(hashlib.sha256((KERNEL / source).read_bytes()).hexdigest(), digest)

    def test_grub_dropin_adds_user4k_unless_the_owner_set_it(self):
        image = ('rootflags=subvol=root', 'quiet loglevel=3 rd.udev.log_level=3 systemd.show_status=auto console=tty0')
        self.assertEqual(grub_cmdline(*image), ['rootflags=subvol=root user4k=on', image[1]])
        self.assertEqual(grub_cmdline('', ''), ['user4k=on', ''])
        for linux, default in (('rootflags=subvol=root', 'quiet user4k=off'), ('user4k=off', 'quiet'),
                               ('rootflags=subvol=root user4k=on', 'quiet'), ('root=x', 'quiet\tuser4k=0')):
            with self.subTest(linux=linux, default=default):
                self.assertEqual(grub_cmdline(linux, default), [linux, default])
        # Only a whole argument counts.
        self.assertEqual(grub_cmdline('xuser4k=off', '')[0], 'xuser4k=off user4k=on')

    def test_hook_regenerates_grub_only_where_it_is_set_up(self):
        hook = (KERNEL / 'aurora-userpages.hook').read_text()
        self.assertIn('\nTarget = etc/default/grub.d/50-aurora-user4k.cfg\n', hook)
        self.assertIn('\nWhen = PostTransaction\n', hook)
        command = re.search(r"(?m)^Exec = /usr/bin/sh -c '(.*)'$", hook).group(1)
        self.assertTrue(command.startswith('[ -f /boot/grub/grub.cfg ] && [ -x /usr/bin/grub-mkconfig ] || exit 0;'))
        self.assertTrue(command.endswith('exec /usr/bin/grub-mkconfig -o /boot/grub/grub.cfg'))

    def test_every_image_ships_it_and_boots_with_user4k(self):
        build = (ROOT / 'scripts/build-image').read_text()
        packages = re.search(r'(?s)^packages=\((.*?)\)\n', build, re.M).group(1).split()
        self.assertIn('aurora-userpages', packages)
        mkconfig = build.index('chroot "$mountroot" grub-mkconfig -o /boot/grub/grub.cfg\n')
        check = build.index("grep -Eq '^\\s*linux\\s.*\\suser4k=on(\\s|$)' \"$mountroot/boot/grub/grub.cfg\"")
        self.assertLess(mkconfig, check)
        pattern = re.search(r"grep -Eq '([^']+)'", build[check:]).group(1)
        for line, found in (('\tlinux\t/vmlinuz-linux-aurora root=UUID=r rw rootflags=subvol=root user4k=on quiet', True),
                            ('\tlinux\t/vmlinuz-linux-aurora root=UUID=r rw quiet', False)):
            result = subprocess.run(['grep', '-Eq', pattern], input=line + '\n', text=True)
            self.assertEqual(result.returncode == 0, found, line)


if __name__ == '__main__':
    unittest.main()
