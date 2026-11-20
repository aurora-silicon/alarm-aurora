"""x86_64 Flatpak apps: one FEX bundle, the x86_64 GL.aurora extension and its override."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GL = ROOT / 'packages/aurora-flatpak-gl'
X86 = ROOT / 'packages/aurora-flatpak-gl-x86_64'
FEX = ROOT / 'packages/fex-emu'
BUNDLE = '/usr/lib/x86_64-linux-gnu/GL/aurora/fex'
spec = importlib.util.spec_from_file_location('x86_tree', X86 / 'validate-tree.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
COMMIT = 'c208afc352e9d4c10ee71c883a369a9079dd7d84'


def assignment(path, key):
    return re.search(rf'^{key}=(.*)$', path.read_text(), re.M)[1]


class FexBundleTests(unittest.TestCase):
    def test_fex_emu_owns_the_only_x86_registrations_and_points_them_at_the_bundle(self):
        for name, machine in (('FEX-x86.conf', r'\x03\x00'), ('FEX-x86_64.conf', r'\x3e\x00')):
            with self.subTest(name=name):
                lines = [l for l in (FEX / name).read_text().splitlines() if not l.startswith('#')]
                self.assertEqual(len(lines), 1)
                fields = lines[0].split(':')
                self.assertEqual(fields[1], name.removesuffix('.conf'))
                self.assertTrue(fields[4].endswith(machine))
                self.assertEqual(fields[6:], [BUNDLE + '/FEX', 'POCF'])
        recipe = (FEX / 'PKGBUILD').read_text()
        self.assertIn(f'bash fex-bundle build "$pkgdir{BUNDLE}"', recipe)
        for name in ('FEX-x86.conf', 'FEX-x86_64.conf'):
            self.assertIn(f'install -Dm644 {name} "$pkgdir/usr/lib/binfmt.d/{name}"', recipe)
        # Nothing else in the tree registers an x86 interpreter.
        for path in (ROOT / 'packages').rglob('*'):
            if path.is_file() and path.parent != FEX and path.suffix in ('.conf', '.hook', ''):
                with self.subTest(path=str(path.relative_to(ROOT))):
                    self.assertNotIn(r'\x02\x00\x3e\x00', path.read_text(errors='replace'))

    def test_bundle_script_targets_the_extension_path(self):
        script = (FEX / 'fex-bundle').read_text()
        self.assertIn(f'final={BUNDLE}\n', script)
        self.assertIn('--set-interpreter "$final/ld-linux-aarch64.so.1" --force-rpath --set-rpath "$final"', script)

    def test_x86_extension_takes_the_vdso_thunk_from_the_packaged_fex(self):
        recipe = X86 / 'PKGBUILD'
        self.assertEqual(assignment(recipe, '_fex_commit'), assignment(FEX / 'PKGBUILD', '_commit'))
        self.assertEqual(assignment(recipe, '_fex_sha256'), assignment(FEX / 'PKGBUILD', '_sha256'))
        self.assertIn('cmake --build guest-thunks --target VDSO-guest', recipe.read_text())


class ManifestTests(unittest.TestCase):
    def test_x86_drivers_link_no_llvm_and_live_under_the_x86_prefix(self):
        text = (X86 / 'org.freedesktop.Platform.GL.aurora.yml.in').read_text()
        self.assertNotIn('aarch64-linux-gnu', text)
        mesa = text[text.index('  - name: mesa\n'):]
        for option in ('-Dllvm=disabled', '-Dgallium-drivers=asahi,zink', '-Dvulkan-drivers=asahi',
                       '-Dmesa-clc=system', '-Dprecomp-compiler=system'):
            self.assertIn('      - ' + option + '\n', mesa)
        self.assertNotIn('libLLVM', mesa)
        self.assertIn('  - /share/build-tools\n', text)
        self.assertIn('prefix: /usr/lib/x86_64-linux-gnu/GL/aurora\n', text)

    def test_mesa_consumers_include_the_x86_extension(self):
        for field in ('epoch', 'pkgver', 'pkgrel', '_commit', '_sha256'):
            self.assertEqual(assignment(X86 / 'PKGBUILD', field), assignment(GL / 'PKGBUILD', field))


class TreeValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trees = Path(self.tmp.name)
        elf = b'\x7fELF\x02\x01' + bytes(12) + struct.pack('<H', 62)
        for branch in validator.BRANCHES:
            root = self.trees / branch / 'files'
            self.write(root / '.aurora-mesa-commit', COMMIT)
            for name in ('lib/libvulkan_asahi.so', 'lib/libEGL_mesa.so.0', 'lib/libGLX_mesa.so.0',
                         'lib/dri/asahi_dri.so', 'lib/dri/zink_dri.so', 'GuestThunks/libVDSO-guest.so'):
                self.write(root / name, elf + f' Mesa (git-{COMMIT[:10]}), Borealis'.encode())
            for path, lib in (('vulkan/icd.d/asahi_icd.x86_64.json', 'libvulkan_asahi.so'),
                              ('glvnd/egl_vendor.d/50_mesa.json', 'libEGL_mesa.so.0')):
                self.write(root / path, json.dumps({'ICD': {'library_path': validator.PREFIX + 'lib/' + lib}}))
            self.write(root / 'share/drirc.d/00-hk-defaults.conf', 'hk_report_honeykrisp_driver_id')
            self.write(self.trees / branch / 'metadata',
                       f'[Runtime]\nname={validator.ID}\n'
                       f'[ExtensionOf]\nref=runtime/org.freedesktop.Platform/x86_64/{branch}\npriority=10\n')

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)

    def test_complete_trees(self):
        validator.validate(self.trees, COMMIT)

    def test_aarch64_library_is_rejected(self):
        self.write(self.trees / '26.08/files/lib/dri/zink_dri.so', b'\x7fELF\x02\x01' + bytes(12) + struct.pack('<H', 183))
        with self.assertRaisesRegex(ValueError, 'not an x86-64'):
            validator.validate(self.trees, COMMIT)

    def test_llvm_and_a_packaged_fex_bundle_are_rejected(self):
        path = self.trees / '25.08/files/lib/libGLX_mesa.so.0'
        path.write_bytes(path.read_bytes() + b'libLLVM.so.22.1')
        with self.assertRaisesRegex(ValueError, 'links LLVM'):
            validator.validate(self.trees, COMMIT)
        path.write_bytes(path.read_bytes().replace(b'libLLVM.so.22.1', b''))
        self.write(self.trees / '25.08/files/fex/FEX', b'')
        with self.assertRaisesRegex(ValueError, 'FEX bundle'):
            validator.validate(self.trees, COMMIT)

    def test_aarch64_runtime_is_rejected(self):
        path = self.trees / '25.08/metadata'
        path.write_text(path.read_text().replace('/x86_64/', '/aarch64/'))
        with self.assertRaisesRegex(ValueError, 'identity or priority'):
            validator.validate(self.trees, COMMIT)


FAKE_FLATPAK = r'''#!/bin/bash
printf '%s\n' "$*" >> "$TEST_LOG"
case $1 in
  remotes) [ -f "$TEST_REMOTES" ] && cat "$TEST_REMOTES" ;;
  remote-add) printf '%s\n' "${@: -2:1}" >> "$TEST_REMOTES" ;;
  list) printf '%s\n' org.freedesktop.Platform.GL.aurora/aarch64/26.08 org.freedesktop.Platform.GL.aurora/x86_64/26.08 ;;
  override) printf '%s\n' "${3#--env=}" >> "$TEST_OVERRIDES" ;;
  build-export)
    work=${@: -2:1}
    [ -x "$work/files/fex/FEX" ] && [ -f "$work/files/GuestThunks/libVDSO-guest.so" ] && echo "exported with FEX ${@: -1}" >> "$TEST_LOG"
    mkdir -p "${@: -3:1}" ;;
esac
'''


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name)
        repo = root / 'repo'
        (repo / 'objects').mkdir(parents=True)
        refs = repo / 'refs/heads/runtime/org.freedesktop.Platform.GL.aurora/aarch64'
        refs.mkdir(parents=True)
        (refs / '26.08').touch()
        self.trees, self.fex, self.overrides = root / 'trees', root / 'fex', root / 'global'
        tree = self.trees / '26.08'
        (tree / 'files/GuestThunks').mkdir(parents=True)
        (tree / 'files/GuestThunks/libVDSO-guest.so').touch()
        (tree / 'files/.aurora-mesa-commit').write_text(COMMIT)
        (tree / 'metadata').touch()
        self.helper = root / 'helper'
        self.helper.write_text((GL / 'aurora-flatpak-gl').read_text()
            .replace('repo=/usr/share/aurora-flatpak-gl/repo', f'repo={repo}')
            .replace('x86_trees=/usr/share/aurora-flatpak-gl/x86_64', f'x86_trees={self.trees}')
            .replace('fex=/usr/lib/x86_64-linux-gnu/GL/aurora/fex', f'fex={self.fex}')
            .replace('x86_repo=/var/lib/aurora-flatpak-gl/repo', f'x86_repo={root}/state/repo')
            .replace('overrides=/var/lib/flatpak/overrides/global', f'overrides={self.overrides}'))
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'flatpak').write_text(FAKE_FLATPAK)
        (bin_dir / 'flatpak').chmod(0o755)
        self.log = root / 'calls'
        self.env = {**os.environ, 'PATH': f'{bin_dir}:' + os.environ['PATH'], 'TMPDIR': str(root),
                    'TEST_LOG': str(self.log), 'TEST_OVERRIDES': str(self.overrides),
                    'TEST_REMOTES': str(root / 'remotes')}

    def run_helper(self, action):
        return subprocess.run(['bash', str(self.helper), action], env=self.env).returncode

    def test_both_architectures_and_the_x86_extension_with_fex(self):
        self.fex.mkdir()
        (self.fex / 'FEX').touch(mode=0o755)
        # The value the aarch64-only release wrote is replaced, not kept as an admin choice.
        self.overrides.write_text('[Environment]\nVK_DRIVER_FILES=/usr/lib/aarch64-linux-gnu/GL/vulkan/icd.d/'
                                  'asahi_icd.aarch64.json:/usr/lib/aarch64-linux-gnu/GL/vulkan/icd.d/lvp_icd.aarch64.json\n'
                                  'OTHER=keep\n')
        for _ in range(2):
            self.assertEqual(self.run_helper('enable'), 0)
        calls = self.log.read_text()
        self.assertIn('install --system --noninteractive -y --or-update aurora-gl '
                      'runtime/org.freedesktop.Platform.GL.aurora/aarch64/26.08', calls)
        self.assertIn('install --system --noninteractive -y --or-update aurora-gl-x86_64 '
                      'runtime/org.freedesktop.Platform.GL.aurora/x86_64/26.08', calls)
        self.assertEqual(calls.count('exported with FEX 26.08'), 2)
        self.assertIn('build-export --runtime --files=files --arch=x86_64', calls)
        values = dict(l.split('=', 1) for l in self.overrides.read_text().splitlines() if '=' in l)
        self.assertEqual(values['VK_DRIVER_FILES'].split(':'), [
            '/usr/lib/aarch64-linux-gnu/GL/vulkan/icd.d/asahi_icd.aarch64.json',
            '/usr/lib/aarch64-linux-gnu/GL/vulkan/icd.d/lvp_icd.aarch64.json',
            '/usr/lib/x86_64-linux-gnu/GL/vulkan/icd.d/asahi_icd.x86_64.json',
            '/usr/lib/x86_64-linux-gnu/GL/vulkan/icd.d/lvp_icd.x86_64.json'])
        self.assertEqual(values['__EGL_VENDOR_LIBRARY_FILENAMES'],
                         '/usr/lib/aarch64-linux-gnu/GL/glvnd/egl_vendor.d/50_mesa.json:'
                         '/usr/lib/x86_64-linux-gnu/GL/glvnd/egl_vendor.d/50_mesa.json')
        self.assertEqual(values['LIBGL_DRIVERS_PATH'],
                         '/usr/lib/aarch64-linux-gnu/GL/lib/dri:/usr/lib/x86_64-linux-gnu/GL/lib/dri')
        self.assertEqual(values['FEX_THUNKGUESTLIBS'], '/usr/lib/x86_64-linux-gnu/GL/aurora/GuestThunks')
        self.assertEqual(self.overrides.read_text().count('VK_DRIVER_FILES='), 1)
        self.assertEqual(self.run_helper('disable'), 0)
        self.assertEqual(self.overrides.read_text(), '[Environment]\nOTHER=keep\n')
        calls = self.log.read_text()
        for ref in ('aarch64', 'x86_64'):
            self.assertIn(f'uninstall --system --noninteractive -y runtime/org.freedesktop.Platform.GL.aurora/{ref}/26.08', calls)
        self.assertIn('remote-delete --system --force aurora-gl-x86_64', calls)
        self.assertFalse((self.root / 'state/repo').exists())

    def test_trees_without_fex_install_no_x86_extension(self):
        self.assertNotEqual(self.run_helper('enable'), 0)
        calls = self.log.read_text()
        self.assertNotIn('--arch=x86_64', calls)
        self.assertIn('aarch64/26.08', calls)


class ExportWrapperTests(unittest.TestCase):
    def test_x86_entries_start_in_a_4k_tree_and_stale_copies_go(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exports, out = root / 'exports', root / 'out'
            exports.mkdir()
            out.mkdir()
            (exports / 'org.x.X.desktop').write_text(
                '[Desktop Entry]\nExec=/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=x org.x.X @@u %u @@\n'
                'TryExec=/usr/bin/flatpak\n[Desktop Action c]\nExec=/usr/bin/flatpak run --arch=x86_64 org.x.X config\n')
            (exports / 'org.a.A.desktop').write_text('[Desktop Entry]\nExec=/usr/bin/flatpak run --arch=aarch64 org.a.A\n')
            (out / 'org.gone.desktop').write_text('stale')
            env = {**os.environ, 'AURORA_FLATPAK_EXPORTS': str(exports), 'AURORA_FLATPAK_X86_EXPORTS': str(out)}
            for _ in range(2):
                subprocess.run(['bash', str(GL / 'aurora-flatpak-x86-exports')], env=env, check=True)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['org.x.X.desktop'])
            self.assertEqual([l for l in (out / 'org.x.X.desktop').read_text().splitlines() if l.startswith('Exec=')], [
                'Exec=/usr/bin/userpages 4k /usr/bin/flatpak run --branch=stable --arch=x86_64 --command=x org.x.X @@u %u @@',
                'Exec=/usr/bin/userpages 4k /usr/bin/flatpak run --arch=x86_64 org.x.X config'])

    def test_session_lists_the_copies_ahead_of_flatpak(self):
        out = subprocess.check_output(['sh', str(GL / '61-aurora-flatpak-x86-exports')],
                                      env={'XDG_DATA_DIRS': '/var/lib/flatpak/exports/share:/usr/share'}, text=True)
        self.assertEqual(out, 'XDG_DATA_DIRS=/var/lib/aurora-flatpak-gl/exports/share:/var/lib/flatpak/exports/share:/usr/share\n')
        again = subprocess.check_output(['sh', str(GL / '61-aurora-flatpak-x86-exports')],
                                        env={'XDG_DATA_DIRS': out.strip().split('=', 1)[1]}, text=True)
        self.assertEqual(again, '')
        recipe = (GL / 'PKGBUILD').read_text()
        self.assertIn('"$pkgdir/usr/lib/systemd/system/paths.target.wants/aurora-flatpak-x86-exports.path"', recipe)
        self.assertIn('"aurora-flatpak-gl-x86_64=$epoch:$pkgver-$pkgrel"', recipe)


if __name__ == '__main__':
    unittest.main()
