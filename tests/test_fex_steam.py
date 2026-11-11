"""FEX and Steam come from Aurora under the names users type."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def sources(name):
    """(source, sha256) pairs as makepkg sees them."""
    out = subprocess.check_output(['bash', '-c',
        'source "$1"; for i in "${!source[@]}"; do printf "%s %s\\n" "${source[$i]}" "${sha256sums[$i]}"; done',
        'sources', str(ROOT / 'packages' / name / 'PKGBUILD')], text=True)
    return [line.split() for line in out.splitlines()]


def field(name, function, key):
    """An array assigned in PKGBUILD (function=None) or in one package function,
    evaluated by bash without running any function body."""
    text = (ROOT / 'packages' / name / 'PKGBUILD').read_text()
    if function:
        body = re.search(rf'(?ms)^{re.escape(function)}\(\) \{{\n(.*?)^\}}', text)[1]
        assignment = re.search(rf'(?ms)^\s*{key}=\(.*?\)$', body)[0]
        script = 'source "$1"; ' + assignment.strip() + f'; printf "%s\\n" "${{{key}[@]}}"'
    else:
        script = f'source "$1"; printf "%s\\n" "${{{key}[@]}}"'
    out = subprocess.check_output(['bash', '-c', script, 'field', str(ROOT / 'packages' / name / 'PKGBUILD')], text=True)
    return out.split('\n')[:-1]


class FexSteamTests(unittest.TestCase):
    def test_fex_pins_the_fork_and_its_submodules(self):
        pin = json.loads((ROOT / 'sources.json').read_text())['fex-emu']
        text = (ROOT / 'packages/fex-emu/PKGBUILD').read_text()
        self.assertEqual(re.search(r'^_commit=(.*)$', text, re.M)[1], pin['commit'])
        self.assertIn('_sha256=' + pin['sha256'], text)
        listed = dict(sources('fex-emu'))
        for name, record in pin['extra_sources'].items():
            url = f'{name}-{record["commit"]}.tar.gz::{record["source_url"]}'
            with self.subTest(submodule=name):
                self.assertEqual(listed[url], record['sha256'])
        for source, digest in listed.items():
            if '://' not in source:
                self.assertEqual(hashlib.sha256((ROOT / 'packages/fex-emu' / source).read_bytes()).hexdigest(), digest)

    def test_fex_defaults_to_the_arch_rootfs_image(self):
        d = ROOT / 'packages/fex-emu'
        text = (d / 'PKGBUILD').read_text()
        # FEX reads its global config from DATA_DIRECTORY, by default
        # ${CMAKE_INSTALL_PREFIX}/share/fex-emu; a user's Config.json overrides it.
        self.assertNotIn('-DDATA_DIRECTORY', text)
        build = text.split('\nbuild() {', 1)[1].split('\n}', 1)[0]
        self.assertEqual(build.count('-DCMAKE_INSTALL_PREFIX=/usr '), 2)
        config = json.loads((d / 'Config.json').read_text())
        image = '/usr/share/fex-emu/RootFS/default.erofs'
        self.assertEqual(config, {'Config': {'RootFS': image}})
        self.assertIn(f'\nWhat={image}\n', (d / 'fex-guest-rootfs.mount').read_text())
        package = text.split('\npackage_fex-emu() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('install -Dm644 Config.json "$pkgdir/usr/share/fex-emu/Config.json"', package)
        self.assertEqual(field('fex-emu', 'package_fex-emu', 'backup'), ['usr/share/fex-emu/Config.json'])

    def test_fex_depends_on_its_rootfs_and_what_mounts_it(self):
        # pacman installs no optional dependencies: FEXBash needs the image and
        # erofsfuse (Arch's erofs-utils has no FUSE client) after `pacman -S fex-emu`.
        depends = field('fex-emu', 'package_fex-emu', 'depends')
        for name in ('fex-emu-rootfs-arch', 'erofsfuse', 'squashfuse'):
            self.assertIn(name, depends)
        optdepends = field('fex-emu', 'package_fex-emu', 'optdepends')
        self.assertFalse([o for o in optdepends if o.startswith('fex-emu-rootfs-arch')])
        d = ROOT / 'packages/fex-emu'
        text = (d / 'PKGBUILD').read_text()
        patch = '0001-FEXInterpreter-name-the-distribution-RootFS-package.patch'
        self.assertIn(patch, field('fex-emu', None, 'source'))
        self.assertIn(f'patch -Np1 -i "$srcdir/{patch}"', text.split('\nprepare() {', 1)[1].split('\n}', 1)[0])
        patched = (d / patch).read_text()
        self.assertIn('add_compile_definitions(ROOTFS_PACKAGE="${ROOTFS_PACKAGE}")', patched)
        self.assertIn('Install the {} package for the default RootFS', patched)
        build = text.split('\nbuild() {', 1)[1].split('\n}', 1)[0]
        main = build.split('cmake --build build', 1)[0]
        self.assertIn('-DROOTFS_PACKAGE=fex-emu-rootfs-arch', main)
        # A 4K page process can't read /dev/fuse on Aurora kernels: FEXServer
        # runs erofsfuse with native pages.
        native = '0002-FEXServer-run-the-RootFS-image-FUSE-helper-with-native-pages.patch'
        self.assertIn(native, field('fex-emu', None, 'source'))
        self.assertIn(f'patch -Np1 -i "$srcdir/{native}"', text.split('\nprepare() {', 1)[1].split('\n}', 1)[0])
        patched = (d / native).read_text()
        self.assertIn('+++ b/Source/Tools/FEXServer/SquashFS.cpp', patched)
        for line in ('+    prctl(PR_AURORA_SET_DEFAULT_PAGE_SIZE, 0UL, 0UL, 0UL, 0UL);',
                     '+    prctl(PR_AURORA_SET_EXEC_PAGE_SIZE, 0UL, 0UL, 0UL, 0UL);'):
            self.assertIn(line, patched)

    def test_fex_emu_takes_over_fex_emu_and_not_fex(self):
        self.assertEqual(field('fex-emu', None, 'pkgname'), ['fex-emu', 'fex-emu-steam'])
        # pacman -Syu moves an Asahi FEX-Emu install to fex-emu; `fex` is not
        # ours to take (Fedora's is an unrelated tool).
        provides = field('fex-emu', 'package_fex-emu', 'provides')
        self.assertEqual(len(provides), 1)
        self.assertTrue(provides[0].startswith('FEX-Emu='))
        self.assertEqual(field('fex-emu', 'package_fex-emu', 'conflicts'), ['FEX-Emu'])
        self.assertEqual(field('fex-emu', 'package_fex-emu', 'replaces'), ['FEX-Emu'])

    def test_no_two_packages_differ_only_in_case(self):
        # The testing snapshot publishes each package file as a release asset,
        # and release asset names are case-insensitive.
        names = {}
        for pkgbuild in sorted((ROOT / 'packages').glob('*/PKGBUILD')):
            for name in field(pkgbuild.parent.name, None, 'pkgname') or []:
                self.assertNotIn(name.lower(), names, f'{name} and {names.get(name.lower())}')
                names[name.lower()] = name

    def test_steam_replaces_the_muvm_wrapper_and_uses_the_system_launcher(self):
        d = ROOT / 'packages/aurora-steam-native'
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-steam-native']
        text = (d / 'PKGBUILD').read_text()
        self.assertEqual(re.search(r'^_commit=(.*)$', text, re.M)[1], pin['commit'])
        self.assertIn('_sha256=' + pin['sha256'], text)
        self.assertEqual(field('aurora-steam-native', None, 'pkgname'), ['aurora-steam-native', 'steam'])
        # The Asahi ALARM `steam` is 20241231-4; the epoch keeps ours newer.
        self.assertEqual(field('aurora-steam-native', None, 'epoch'), ['1'])
        depends = field('aurora-steam-native', 'package_aurora-steam-native', 'depends')
        for name in ('aurora-userpages', 'fex-emu', 'gtk2', 'python'):
            self.assertIn(name, depends)
        self.assertIn("'s,@USERPAGES@,/usr/bin/userpages,'", text)
        for source, digest in sources('aurora-steam-native'):
            if '://' not in source:
                self.assertEqual(hashlib.sha256((d / source).read_bytes()).hexdigest(), digest)
        subprocess.run(['bash', '-n', str(d / 'steam')], check=True)

    def test_fex_mounts_the_stock_guest_rootfs_below_the_aurora_mesa_layer(self):
        d = ROOT / 'packages/fex-emu'
        unit = (d / 'fex-guest-rootfs.mount').read_text()
        self.assertIn('What=/usr/share/fex-emu/RootFS/default.erofs\n', unit)
        self.assertIn('Where=/usr/share/guestos/fex-mesa\n', unit)
        service = (ROOT / 'packages/mesa-aurora-fex-guest/aurora-fex-mesa.service').read_text()
        self.assertIn('lowerdir=/usr/share/guestos/aurora-fex-mesa-layer:/usr/share/guestos/fex-mesa ', service)
        self.assertIn('Wants=usr-share-guestos-fex\\x2dmesa.mount\n', (d / '50-aurora-fex-rootfs.conf').read_text())
        hook = (d / '70-aurora-fex-provider.hook').read_text()
        self.assertIn('Target = usr/share/fex-emu/RootFS/default.erofs\n', hook)
        self.assertIn('Exec = /usr/lib/fex-emu/aurora-fex-provider-up\n', hook)
        text = (d / 'PKGBUILD').read_text()
        self.assertIn('"$pkgdir/usr/lib/systemd/system/aurora-fex-mesa.service.d/50-aurora-fex-rootfs.conf"', text)
        subprocess.run(['sh', '-n', str(d / 'aurora-fex-provider-up')], check=True)

    def test_gtk2_is_built_here_for_the_native_client(self):
        # Arch Linux ARM dropped GTK 2; steamui.so needs libgtk-x11-2.0.so.0.
        self.assertEqual(field('gtk2', None, 'arch'), ['aarch64'])
        self.assertIn('libgtk-x11-2.0.so', field('gtk2', 'package', 'provides'))


if __name__ == '__main__':
    unittest.main()
