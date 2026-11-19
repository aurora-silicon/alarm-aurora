"""The kernel recipe ships the userpages launcher; the kernel needs no user4k= argument."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / 'packages/linux-aurora'
PKGBUILD = (KERNEL / 'PKGBUILD').read_text()


class UserPagesTests(unittest.TestCase):
    def test_split_package_is_built_from_the_kernel_source(self):
        self.assertRegex(PKGBUILD, r'(?m)^pkgname=\("\$pkgbase" "\$pkgbase-headers" aurora-userpages\)$')
        build = PKGBUILD.split('\nbuild() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('\n  make -C tools/aurora-userpages', build)
        package = PKGBUILD.split('\npackage_aurora-userpages() {', 1)[1].split('\n}', 1)[0]
        for line in ('install -Dm755 tools/aurora-userpages/userpages "$pkgdir/usr/bin/userpages"',
                     'install -Dm644 tools/aurora-userpages/README.rst "$pkgdir/usr/share/doc/aurora-userpages/README.rst"'):
            self.assertIn(line, package)
        # No GRUB drop-in: the kernel offers 4K userspace pages by default.
        self.assertNotIn('grub.d', package)
        self.assertNotIn('user4k=on', PKGBUILD)
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

    def test_every_image_ships_it_and_boots_without_user4k(self):
        build = (ROOT / 'scripts/build-image').read_text()
        packages = re.search(r'(?s)^packages=\((.*?)\)\n', build, re.M).group(1).split()
        self.assertIn('aurora-userpages', packages)
        mkconfig = build.index('chroot "$mountroot" grub-mkconfig -o /boot/grub/grub.cfg\n')
        check = build.index("nomatch -E '^\\s*linux\\s.*\\suser4k=' \"$mountroot/boot/grub/grub.cfg\"")
        self.assertLess(mkconfig, check)
        pattern = re.search(r"nomatch -E '([^']+)'", build[check:]).group(1)
        for line, found in (('\tlinux\t/vmlinuz-linux-aurora root=UUID=r rw rootflags=subvol=root user4k=on quiet', True),
                            ('\tlinux\t/vmlinuz-linux-aurora root=UUID=r rw quiet', False)):
            result = subprocess.run(['grep', '-Eq', pattern], input=line + '\n', text=True)
            self.assertEqual(result.returncode == 0, found, line)

if __name__ == '__main__':
    unittest.main()
