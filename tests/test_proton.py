import concurrent.futures
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
import sys
import tarfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_proton', ROOT / 'packages/aurora-proton/prepare-proton.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ProtonPreparation(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory(prefix='aurora proton '))
        self.root = Path(self.temporary)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.packaged = self.root / 'packaged'
        self.packaged.mkdir()
        self.current = self.packaged / 'current'
        self.archive = self.root / 'GE-fixture.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, value, mode in [('proton', b'#!/bin/sh\nexit 0\n', 0o755),
                                      ('compatibilitytool.vdf', b'GE-Proton11-9-aarch64', 0o644),
                                      ('files/lib/wine/aarch64-unix/ntdll.so', b'original fixture', 0o644)]:
                member = tarfile.TarInfo('GE-Proton11-9-aarch64/' + name)
                member.size, member.mode = len(value), mode
                archive.addfile(member, io.BytesIO(value))
        self.source = self.revision('Aurora-Proton11-9-1.alarm')
        self.current.symlink_to(self.source)
        self.lib = self.root / 'lib'
        self.lib.mkdir()
        self.prepare = self.lib / 'prepare-proton'
        self.prepare.write_text((ROOT / 'packages/aurora-steam-native/prepare-proton').read_text()
                                .replace('@PROTON@', shlex.quote(str(self.current)))
                                .replace('#!/bin/bash\n', '#!' + shutil.which('bash') + '\n', 1))
        self.prepare.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_DATA_HOME': str(self.home / 'data'),
                    'XDG_CACHE_HOME': str(self.home / 'cache'), 'AURORA_PROTON_ARCHIVE': str(self.archive)}
        self.env.pop('STEAM_EXTRA_COMPAT_TOOLS_PATHS', None)
        self.env.pop('AURORA_STEAM_PROTON', None)

    def revision(self, name):
        path = self.packaged / name
        path.mkdir()
        shutil.copyfile(ROOT / 'packages/aurora-proton/prepare-proton.py', path / 'prepare-proton.py')
        (path / 'ntdll.so').write_bytes(b'patched fixture')
        manifest = {'schema': 1, 'archive_sha256': bootstrap.digest(self.archive),
                    'archive_bytes': self.archive.stat().st_size, 'archive_name': self.archive.name,
                    'archive_root': 'GE-Proton11-9-aarch64', 'archive_url': 'https://example.invalid/pinned.tar.gz',
                    'ntdll_sha256': bootstrap.digest(path / 'ntdll.so'),
                    'original_tool': 'GE-Proton11-9-aarch64', 'tool': 'Aurora-Proton11-9'}
        (path / 'manifest.json').write_text(json.dumps(manifest))
        return path

    def run_prepare(self):
        return subprocess.run([str(self.prepare)], env=self.env, capture_output=True, text=True)

    def run_environment(self, **changes):
        env = {**self.env, **changes}
        script = 'lib=$1; source "$2"; printf "%s" "${STEAM_EXTRA_COMPAT_TOOLS_PATHS-absent}"'
        return subprocess.run(['bash', '-euc', script, 'fixture', str(self.lib),
                               str(ROOT / 'packages/aurora-steam-native/proton-env')],
                              env=env, capture_output=True, text=True)

    def test_copy_is_writable_and_preserves_personal_settings_on_repeat(self):
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = Path(result.stdout.strip())
        self.assertEqual(target.name, self.source.name)
        self.assertTrue((target / 'proton').stat().st_mode & 0o200)
        self.assertEqual((target / '.aurora-proton-source').read_text().strip(), str(self.source))
        settings = target / 'user_settings.py'
        settings.write_text('user_settings = {"PROTON_LOG": "1"}\n')
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(settings.read_text(), 'user_settings = {"PROTON_LOG": "1"}\n')
        self.assertFalse((self.source / 'user_settings.py').exists())
        self.assertEqual((target / 'files/lib/wine/aarch64-unix/ntdll.so').read_bytes(), b'patched fixture')
        self.assertEqual((target / 'compatibilitytool.vdf').read_text(), 'Aurora-Proton11-9')

    def test_distro_revision_change_keeps_old_copy_and_uses_new_payload(self):
        old = Path(self.run_prepare().stdout.strip())
        (old / 'user_settings.py').write_text('personal settings')
        newer = self.revision('Aurora-Proton11-9-2.alarm')
        self.current.unlink()
        self.current.symlink_to(newer)
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        new = Path(result.stdout.strip())
        self.assertNotEqual(old, new)
        self.assertEqual(new.name, newer.name)
        self.assertEqual((old / 'user_settings.py').read_text(), 'personal settings')
        self.assertFalse((new / 'user_settings.py').exists())

    def test_unmanaged_existing_target_is_not_overwritten(self):
        target = self.home / 'data/aurora-proton' / self.source.name
        target.mkdir(parents=True)
        (target / 'personal').write_text('preserve')
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(target.iterdir()), [target / 'personal'])
        self.assertEqual((target / 'personal').read_text(), 'preserve')

    def test_nonempty_custom_paths_and_optout_do_not_prepare_default(self):
        custom = '/home/owner/my tool:/home/owner/another tool'
        result = self.run_environment(STEAM_EXTRA_COMPAT_TOOLS_PATHS=custom)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, custom)
        result = self.run_environment(AURORA_STEAM_PROTON='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'absent')
        self.assertFalse((self.home / 'data').exists())

    def test_empty_custom_paths_prepare_the_default(self):
        result = self.run_environment(STEAM_EXTRA_COMPAT_TOOLS_PATHS='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout).name, self.source.name)
        self.assertTrue(Path(result.stdout).is_dir())

    def test_empty_xdg_directory_variables_use_home_defaults(self):
        self.env.update(XDG_DATA_HOME='', XDG_CACHE_HOME='')
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), self.home / '.local/share/aurora-proton' / self.source.name)

    def test_tampered_offline_archive_is_rejected_before_extraction(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'tampered')
        with mock.patch.object(bootstrap, 'extract') as extract:
            with self.assertRaisesRegex(ValueError, 'pinned SHA256'):
                bootstrap.prepare(self.source, self.home / 'data', self.home / 'cache', self.archive)
            extract.assert_not_called()
        self.assertFalse((self.home / 'data/aurora-proton' / self.source.name).exists())

    def test_interrupted_extraction_does_not_publish_and_can_retry(self):
        def interrupted(archive, directory, root):
            (directory / 'partial').write_bytes(b'partial')
            raise OSError('interrupted extraction')
        with mock.patch.object(bootstrap, 'extract', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'interrupted extraction'):
                bootstrap.prepare(self.source, self.home / 'data', self.home / 'cache', self.archive)
        parent = self.home / 'data/aurora-proton'
        self.assertFalse((parent / self.source.name).exists())
        self.assertEqual(list(parent.glob('.install.*')), [])
        self.assertEqual(self.run_prepare().returncode, 0)

    def test_unsafe_archive_links_cannot_write_outside_staging(self):
        malicious = self.root / 'unsafe.tar.gz'
        with tarfile.open(malicious, 'w:gz') as archive:
            link = tarfile.TarInfo('GE-Proton11-9-aarch64/escape')
            link.type, link.linkname = tarfile.SYMTYPE, str(self.home)
            archive.addfile(link)
            member = tarfile.TarInfo('GE-Proton11-9-aarch64/escape/should-not-exist')
            member.size = 3
            archive.addfile(member, io.BytesIO(b'bad'))
        with self.assertRaises(tarfile.FilterError):
            bootstrap.extract(malicious, self.root / 'staging', 'GE-Proton11-9-aarch64')
        self.assertFalse((self.home / 'should-not-exist').exists())

    def test_failed_tampered_truncated_and_oversized_downloads_do_not_publish_cache(self):
        manifest = json.loads((self.source / 'manifest.json').read_text())
        content = self.archive.read_bytes()
        bad_bodies = [content[:-1], content + b'extra', b'x' * len(content)]
        for index, body in enumerate(bad_bodies):
            cache = self.root / f'cache-{index}'
            with mock.patch.object(bootstrap.urllib.request, 'urlopen', return_value=io.BytesIO(body)):
                with self.assertRaises(ValueError):
                    bootstrap.verified_archive(manifest, cache)
            self.assertEqual(list(cache.iterdir()), [])
        cache = self.root / 'failed-download'
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', side_effect=OSError('network failed')):
            with self.assertRaisesRegex(OSError, 'network failed'):
                bootstrap.verified_archive(manifest, cache)
        self.assertEqual(list(cache.iterdir()), [])
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', return_value=io.BytesIO(content)):
            archive = bootstrap.verified_archive(manifest, cache)
        self.assertEqual(bootstrap.digest(archive), manifest['archive_sha256'])

    def test_simultaneous_steam_and_play_preparation_is_safe(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.run_prepare(), range(2)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(results[0].stdout, results[1].stdout)
        self.assertEqual(list((self.home / 'data/aurora-proton').glob('.install.*')), [])

    def public_launcher(self, name):
        (self.lib / 'bin').mkdir(exist_ok=True)
        reporter = ('#!' + sys.executable + '\nimport json,os,sys,shutil\n'
                    'print(json.dumps({"compat":os.environ.get("STEAM_EXTRA_COMPAT_TOOLS_PATHS"),'
                    '"system":os.environ.get("AURORA_SYSTEM_LAUNCHERS"),'
                    '"launcher":os.environ.get("AURORA_STEAM_LAUNCHER"),'
                    '"runtime_launcher":shutil.which("steam-runtime-launcher-service"),"argv":sys.argv[1:]}))\n')
        for entry in ('steam-native4k', 'aurora-play'):
            executable = self.lib / 'bin' / entry
            executable.write_text(reporter)
            executable.chmod(0o755)
        shutil.copyfile(ROOT / 'packages/aurora-steam-native/proton-env', self.lib / 'proton-env')
        pages = self.root / 'userpages'
        pages.write_text('#!' + shutil.which('bash') + '\n[ "$1" = 4k ] || exit 64\nshift\nexec "$@"\n')
        pages.chmod(0o755)
        launcher = self.root / name
        launcher.write_text((ROOT / 'packages/aurora-steam-native' / name).read_text()
                            .replace('@LIBDIR@', shlex.quote(str(self.lib)))
                            .replace('@USERPAGES@', '/unavailable-userpages')
                            .replace('@USER4K_HINT@', 'fixture hint'))
        return launcher, {**self.env, 'AURORA_STEAM_ROOT': str(self.root / 'native prefix'),
                          'AURORA_USERPAGES_LAUNCHER': str(pages)}

    def test_public_steam_prepares_tool_and_keeps_installer_on_system_launchers(self):
        launcher, env = self.public_launcher('steam')
        result = subprocess.run(['bash', str(launcher), 'argument with spaces'], env=env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(Path(row['compat']).name, self.source.name)
        self.assertEqual(row['system'], '1')
        self.assertEqual(row['argv'], ['argument with spaces'])

    def test_public_steam_exposes_runtime_launcher_for_default_and_custom_roots(self):
        launcher, env = self.public_launcher('steam')
        for custom in (False, True):
            with self.subTest(custom_root=custom):
                current_env = env.copy()
                if custom:
                    steam_root = Path(current_env['AURORA_STEAM_ROOT'])
                else:
                    current_env.pop('AURORA_STEAM_ROOT')
                    steam_root = self.home / '.steam/root'
                    client = steam_root / 'steamrtarm64/steam'
                    client.parent.mkdir(parents=True)
                    client.write_text('#!/bin/sh\nexit 0\n')
                    client.chmod(0o755)
                runtime = steam_root / 'steamapps/common/SteamLinuxRuntime_4-arm64/pressure-vessel/bin/steam-runtime-launcher-service'
                runtime.parent.mkdir(parents=True)
                runtime.write_text('#!/bin/sh\nexit 0\n')
                runtime.chmod(0o755)
                result = subprocess.run(['bash', str(launcher)], env=current_env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['runtime_launcher'], str(runtime))

    def test_public_play_prepares_tool_and_selects_public_steam_but_help_is_inert(self):
        launcher, env = self.public_launcher('aurora-play')
        result = subprocess.run(['bash', str(launcher), '--help'], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)['compat'])
        self.assertFalse((self.home / 'data').exists())
        result = subprocess.run(['bash', str(launcher)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(Path(row['compat']).name, self.source.name)
        self.assertEqual(row['launcher'], '/usr/bin/steam')


class ProtonSources(unittest.TestCase):
    def test_recipe_matches_all_seven_pinned_sources_and_local_digests(self):
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-proton']
        expected = {pin['archive_file'] + '::' + pin['source_url']: pin['sha256']}
        expected.update({record['archive_file'] + '::' + record['source_url']: record['sha256']
                         for record in pin['extra_sources'].values()})
        self.assertEqual(len(expected), 7)
        directory = ROOT / 'packages/aurora-proton'
        rows = subprocess.check_output(['bash', '-c', 'source "$1"; for i in "${!source[@]}"; do '
                                        'printf "%s %s\\n" "${source[$i]}" "${sha256sums[$i]}"; done',
                                        'fixture', str(directory / 'PKGBUILD')], text=True).splitlines()
        actual = dict(row.split() for row in rows)
        self.assertEqual({key: value for key, value in actual.items() if '::' in key}, expected)
        for name, digest in actual.items():
            if '::' not in name:
                self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest, name)
