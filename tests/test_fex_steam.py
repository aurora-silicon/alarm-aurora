"""FEX and Steam come from Aurora under the names users type."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import shutil
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
        # Games run under GameMode with Aurora's settings; upgrades bring it.
        self.assertIn('aurora-gamemode', field('aurora-steam-native', 'package_steam', 'depends'))
        self.assertIn('AURORA_STEAM_GAMEMODE', (d / 'steam').read_text())
        subprocess.run(['bash', '-n', str(d / 'steam')], check=True)

    def test_steam_registers_each_game_process_with_gamemode(self):
        # The watcher follows the client's logs/gameprocess_log.txt through
        # inotify, registers every tracked PID and sleeps in between.
        def watchers(root):
            found = []
            for proc in Path('/proc').iterdir():
                try:
                    argv = (proc / 'cmdline').read_bytes().split(b'\0')
                except OSError:
                    continue
                if argv[0] == b'aurora-steam-gamemode' and str(root).encode() in b' '.join(argv):
                    found.append(proc)
            return found

        def wait(condition):
            deadline = time.monotonic() + 10
            while not condition():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)

        def switches(proc):
            status = (proc / 'status').read_text()
            return int(re.search(r'(?m)^voluntary_ctxt_switches:\s+(\d+)$', status)[1])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lib, home, stubs, client = root / 'lib', root / 'home', root / 'stubs', root / 'client'
            for path in (lib / 'bin', client / 'steamrtarm64', client / 'logs', stubs, home / '.steam'):
                path.mkdir(parents=True)
            (home / '.steam/root').symlink_to(client)
            gamelog, log = client / 'logs/gameprocess_log.txt', root / 'busctl.log'
            gamelog.write_text('[2026-11-17 19:14:50] AppID 9 adding PID 999 as a tracked process\n')
            log.write_text('')
            bash = shutil.which('bash')

            def script(path, body):
                path.write_text(f'#!{bash}\n' + body)
                path.chmod(0o755)
            script(client / 'steamrtarm64/steam', '')
            script(lib / 'bin/steam-native4k', 'exec sleep 60\n')
            script(root / 'userpages', '')
            script(stubs / 'busctl', f'echo "busctl $*" >> {log}\n'
                   'case "$*" in *ListActivatableNames*) echo \'as 2 "org.freedesktop.DBus" "com.feralinteractive.GameMode"\';; esac\n')
            wrapper = root / 'steam'
            wrapper.write_text((ROOT / 'packages/aurora-steam-native/steam').read_text().replace('@LIBDIR@', str(lib))
                               .replace('@USERPAGES@', str(root / 'userpages')).replace('@USER4K_HINT@', 'hint'))
            wrapper.chmod(0o755)
            env = {'HOME': str(home), 'PATH': f'{stubs}:{os.environ["PATH"]}', 'USER': 'test'}

            def registered():
                return [line.split()[-1] for line in log.read_text().splitlines() if 'RegisterGameByPID ii' in line]

            steam = subprocess.Popen([bash, str(wrapper)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(lambda: len(watchers(client)) == 1)
                watcher = watchers(client)[0]
                wait(lambda: (watcher / 'stat').read_text().rsplit(')', 1)[1].split()[0] == 'S')
                with gamelog.open('a') as f:
                    f.write('[2026-11-20 10:00:00] AppID 383870 adding PID 4242 as a tracked process "x"\n'
                            '[2026-11-20 10:00:00] AppID 383870 adding PID 4243 as a')
                wait(lambda: registered() == ['4242'])
                with gamelog.open('a') as f:
                    f.write(' tracked process\n')
                wait(lambda: registered() == ['4242', '4243'])
                # Idle: blocked in select(), no wake-ups at all.
                time.sleep(0.5)
                before = switches(watcher)
                time.sleep(2)
                self.assertEqual(switches(watcher), before)
                # Steam rotates the log and starts a new one.
                gamelog.rename(gamelog.with_name('gameprocess_log.previous.txt'))
                gamelog.write_text('[2026-11-20 10:05:00] AppID 1 adding PID 5000 as a tracked process\n')
                wait(lambda: registered() == ['4242', '4243', '5000'])
                self.assertIn('busctl --user call com.feralinteractive.GameMode /com/feralinteractive/GameMode '
                              'com.feralinteractive.GameMode RegisterGameByPID ii', log.read_text())
            finally:
                steam.kill()
                steam.wait()
            # The watcher ends with Steam.
            wait(lambda: not watchers(client))
            # Opt-out: no watcher while Steam runs.
            steam = subprocess.Popen([bash, str(wrapper)], env={**env, 'AURORA_STEAM_GAMEMODE': '0'},
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(lambda: (Path('/proc') / str(steam.pid) / 'cmdline').read_bytes().startswith(b'sleep'))
                time.sleep(0.5)
                self.assertEqual(watchers(client), [])
            finally:
                steam.kill()
                steam.wait()
            self.assertEqual(registered(), ['4242', '4243', '5000'])
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

    def test_fex_uses_the_aurora_mesa_provider_while_it_is_mounted(self):
        d = ROOT / 'packages/fex-emu'
        # pacman has no weak dependencies, and the guest pins mesa-aurora's
        # build: Aurora's images carry it, fex-emu only suggests it.
        self.assertNotIn('mesa-aurora-fex-guest', field('fex-emu', 'package_fex-emu', 'depends'))
        self.assertIn('util-linux', field('fex-emu', 'package_fex-emu', 'depends'))
        self.assertTrue([o for o in field('fex-emu', 'package_fex-emu', 'optdepends')
                         if o.startswith('mesa-aurora-fex-guest: ')])
        self.assertIn('mesa-aurora-fex-guest', (ROOT / 'scripts/build-image').read_text())
        # FEX reads the runtime config over the global one, in the global layer only.
        patch = '0003-Config-read-a-runtime-system-config-over-the-global-one.patch'
        self.assertIn(patch, field('fex-emu', None, 'source'))
        text = (d / 'PKGBUILD').read_text()
        self.assertIn(f'patch -Np1 -i "$srcdir/{patch}"', text.split('\nprepare() {', 1)[1].split('\n}', 1)[0])
        body = (d / patch).read_text()
        self.assertIn('+  if (GetLayerType() == FEXCore::Config::LayerType::LAYER_GLOBAL_MAIN) {', body)
        self.assertIn('+    const fextl::string RuntimeConfig {"/run/fex-emu/Config.json"};', body)
        self.assertIn('grep -qaF /run/fex-emu/Config.json build/Bin/FEX', text.split('\ncheck() {', 1)[1].split('\n}', 1)[0])
        package = text.split('\npackage_fex-emu() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('install -Dm755 aurora-fex-rootfs "$pkgdir/usr/lib/fex-emu/aurora-fex-rootfs"', package)
        self.assertIn('install -Dm644 71-aurora-fex-rootfs.hook "$pkgdir/usr/share/libalpm/hooks/71-aurora-fex-rootfs.hook"',
                      package)
        dropin = (d / '50-aurora-fex-rootfs.conf').read_text()
        for key in ('ExecStartPost', 'ExecStopPost'):
            self.assertIn(f'\n{key}=-/usr/lib/fex-emu/aurora-fex-rootfs\n', dropin)
        self.assertIn('\nBefore=systemd-user-sessions.service\n', dropin)
        script = (d / 'aurora-fex-rootfs').read_text()
        self.assertIn('provider=/usr/share/guestos/aurora-fex-mesa\n', script)
        subprocess.run(['sh', '-n', str(d / 'aurora-fex-rootfs')], check=True)
        self.assertIn('/usr/lib/fex-emu/aurora-fex-rootfs || :\n', (d / 'aurora-fex-provider-up').read_text())
        # The installed global config still names the stock image.
        self.assertEqual(json.loads((d / 'Config.json').read_text()),
                         {'Config': {'RootFS': '/usr/share/fex-emu/RootFS/default.erofs'}})

    def test_gtk2_is_built_here_for_the_native_client(self):
        # Arch Linux ARM dropped GTK 2; steamui.so needs libgtk-x11-2.0.so.0.
        self.assertEqual(field('gtk2', None, 'arch'), ['aarch64'])
        self.assertIn('libgtk-x11-2.0.so', field('gtk2', 'package', 'provides'))


if __name__ == '__main__':
    unittest.main()
