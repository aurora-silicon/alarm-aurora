"""Finished-package fixtures; synthetic ELF headers do not prove runtime behavior."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fex_payload', ROOT / 'scripts/check-fex-guest-payload.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def elf(elf_class, machine):
    size = 64 if elf_class == 2 else 52
    header = bytearray(size)
    header[:7] = b'\x7fELF' + bytes((elf_class, 1, 1))
    struct.pack_into('<HHI', header, 16, 3, machine, 1)
    struct.pack_into('<H', header, 52 if elf_class == 2 else 40, size)
    return header


class FinishedPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.package = Path(self.tmp.name) / 'package'
        self.layer = self.package / validator.LAYER
        architectures = {}
        for arch, icd_arch, libdir, elf_class, machine in validator.ARCHITECTURES:
            architectures[arch] = {
                'dri': f'/usr/{libdir}/dri',
                'fallback_library_paths': [f'/usr/{libdir}'],
                'gconv': f'/usr/{libdir}/gconv',
            }
            for name in ('libvulkan_asahi.so', 'libdisplay-info.so.3', 'libEGL_mesa.so.0.0.0',
                         'libGLX_mesa.so.0', 'libgbm.so.1', 'libgallium-26.3.0-devel.so',
                         'gbm/dri_gbm.so', 'dri/asahi_dri.so', 'dri/zink_dri.so', 'dri/swrast_dri.so'):
                self.write(f'usr/{libdir}/{name}', elf(elf_class, machine))
            (self.layer / f'usr/{libdir}/libEGL_mesa.so.0').symlink_to('libEGL_mesa.so.0.0.0')
            self.write(f'usr/share/vulkan/icd.d/asahi_icd.{icd_arch}.json',
                       json.dumps({'ICD': {'library_path': f'/usr/{libdir}/libvulkan_asahi.so'}}))
        self.provider = {'graphics_provider_v0': {'root': './', 'architectures': architectures}}
        self.write('graphics_provider.json', json.dumps(self.provider))

    def write(self, name, data):
        path = self.layer / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)

    def errors(self):
        return '\n'.join(validator.validate_payload(self.layer))

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = validator.main(list(map(str, args)))
        return result, out.getvalue(), err.getvalue()

    def test_complete_extracted_package_and_explicit_layer(self):
        for option, root in (('--package-root', self.package), ('--layer-root', self.layer)):
            result, out, err = self.cli(option, root)
            self.assertEqual((result, err), (0, ''))
            self.assertIn('FEX guest payload: OK', out)
        self.assertEqual(self.errors(), '')

    def test_input_root_is_explicit(self):
        result, out, err = self.cli('--package-root', self.layer)
        self.assertEqual((result, out), (1, ''))
        self.assertIn(validator.LAYER, err)

    def test_missing_root_has_actionable_failure_without_traceback(self):
        result, out, err = self.cli('--package-root', self.package / 'absent')
        self.assertEqual((result, out), (1, ''))
        self.assertIn('absent', err)
        self.assertNotIn('Traceback', err)

    def test_old_fedora_layout_is_rejected(self):
        (self.layer / 'usr/lib').rename(self.layer / 'usr/lib64')
        (self.layer / 'usr/lib32').rename(self.layer / 'usr/lib')
        (self.layer / 'graphics_provider.json').unlink()
        for arch, libdir in (('x86_64', 'lib64'), ('i686', 'lib')):
            self.write(f'usr/share/vulkan/icd.d/asahi_icd.{arch}.json',
                       json.dumps({'ICD': {'library_path': f'/usr/{libdir}/libvulkan_asahi.so'}}))
        errors = self.errors()
        for message in ('usr/lib64: real path shadows', 'graphics_provider.json: missing',
                        'ELF64', 'usr/lib32', 'ICD.library_path'):
            self.assertIn(message, errors)

    def test_provider_must_be_packaged_and_parseable(self):
        for value in ('{', '[]', '{}', '{"graphics_provider_v0": []}',
                      '{"graphics_provider_v0": {"root": "./"}}', b'\xff'):
            with self.subTest(value=value):
                self.write('graphics_provider.json', value)
                self.assertIn('graphics_provider.json:', self.errors())
        (self.layer / 'graphics_provider.json').unlink()
        self.assertIn('graphics_provider.json: missing', self.errors())

    def test_provider_mappings_and_root_are_checked(self):
        provider = self.provider['graphics_provider_v0']
        for bad in ('/', '../', '/usr', None):
            provider['root'] = bad
            self.write('graphics_provider.json', json.dumps(self.provider))
            self.assertIn('root must be', self.errors())
        provider['root'] = './'
        for arch, _, _, _, _ in validator.ARCHITECTURES:
            mapping = provider['architectures'][arch]
            for key in ('dri', 'fallback_library_paths', 'gconv'):
                original = mapping[key]
                for bad in (None, '/usr/lib64', ['/usr/lib64']):
                    with self.subTest(arch=arch, key=key, value=bad):
                        mapping[key] = bad
                        self.write('graphics_provider.json', json.dumps(self.provider))
                        self.assertIn(f'{arch}.{key}', self.errors())
                mapping[key] = original

    def test_final_libraries_required_for_both_architectures(self):
        for libdir in ('lib', 'lib32'):
            for name in ('libdisplay-info.so.3', 'libEGL_mesa.so.0', 'libGLX_mesa.so.0',
                         'libgbm.so.1', 'libgallium-26.3.0-devel.so', 'gbm/dri_gbm.so',
                         'dri/asahi_dri.so', 'dri/zink_dri.so', 'dri/swrast_dri.so'):
                with self.subTest(libdir=libdir, name=name):
                    path = self.layer / f'usr/{libdir}/{name}'
                    saved = path.with_name(path.name + '.saved')
                    path.rename(saved)
                    self.assertIn(f'usr/{libdir}/' + ('libgallium-*.so' if name.startswith('libgallium') else name), self.errors())
                    saved.rename(path)

    def test_wrong_elf_class_machine_endianness_and_malformed_headers(self):
        for _, _, libdir, elf_class, machine in validator.ARCHITECTURES:
            good = elf(elf_class, machine)
            bad_endian, bad_version, bad_size, bad_type = (bytearray(good) for _ in range(4))
            bad_endian[5] = 2
            bad_version[6] = 0
            struct.pack_into('<H', bad_size, 52 if elf_class == 2 else 40, 0)
            struct.pack_into('<H', bad_type, 16, 2)
            for bad in (b'', b'not ELF', good[:20], elf(elf_class, 183),
                        elf(3 - elf_class, machine), bad_endian, bad_version, bad_size, bad_type):
                with self.subTest(libdir=libdir, header=bad):
                    self.write(f'usr/{libdir}/libdisplay-info.so.3', bad)
                    self.assertIn(f'usr/{libdir}/libdisplay-info.so.3: expected little-endian ELF', self.errors())
            self.write(f'usr/{libdir}/libdisplay-info.so.3', good)

    def test_icds_must_be_packaged_valid_and_select_exact_arch_driver(self):
        for arch, libdir in (('x86_64', 'lib'), ('i686', 'lib32')):
            name = f'usr/share/vulkan/icd.d/asahi_icd.{arch}.json'
            good = (self.layer / name).read_bytes()
            for bad in ('{', '[]', '{}', '{"ICD": []}', json.dumps({'ICD': {'library_path':
                        f'/usr/{libdir}/libGLX_mesa.so.0'}}), json.dumps({'ICD': {'library_path':
                        '/usr/lib64/libvulkan_asahi.so'}}), json.dumps({'ICD': {'library_path':
                        '../../../../host.so'}})):
                self.write(name, bad)
                self.assertIn(name, self.errors())
            (self.layer / name).unlink()
            self.assertIn(name + ': missing', self.errors())
            self.write(name, good)

    def test_missing_and_wrong_arch_icd_targets(self):
        for _, _, libdir, elf_class, machine in validator.ARCHITECTURES:
            name = f'usr/{libdir}/libvulkan_asahi.so'
            (self.layer / name).unlink()
            self.assertIn(name + ': missing', self.errors())
            self.write(name, elf(elf_class, 183))
            self.assertIn(name + ': expected little-endian ELF', self.errors())
            self.write(name, elf(elf_class, machine))

    def test_benign_guest_symlinks(self):
        (self.layer / 'usr/lib64').symlink_to('lib')
        path = self.layer / 'usr/lib/libdisplay-info.so.3'
        path.rename(path.with_name('libdisplay-info.so.3.0'))
        path.symlink_to('/usr/lib/libdisplay-info.so.3.0')
        self.assertEqual(self.errors(), '')

    def test_wrong_or_dangling_lib64_alias(self):
        path = self.layer / 'usr/lib64'
        for target in ('lib32', 'missing', '../..', 'lib64'):
            path.symlink_to(target)
            self.assertIn('usr/lib64', self.errors())
            path.unlink()

    def test_file_symlinks_never_validate_host_libraries(self):
        host = Path(self.tmp.name) / 'host.so'
        host.write_bytes(elf(2, 62))
        path = self.layer / 'usr/lib/libdisplay-info.so.3'
        path.unlink()
        for target in (os.path.relpath(host, path.parent), str(host), '/' + str(host),
                       'missing.so', path.name):
            with self.subTest(target=target):
                path.symlink_to(target)
                self.assertIn('usr/lib/libdisplay-info.so.3:', self.errors())
                path.unlink()

    def test_directory_symlink_escape_is_rejected(self):
        directory = self.layer / 'usr/lib32'
        outside = Path(self.tmp.name) / 'outside'
        directory.rename(outside)
        directory.symlink_to(os.path.relpath(outside, directory.parent))
        self.assertIn('escapes the payload', self.errors())

    def test_provider_symlink_escape_is_rejected(self):
        path = self.layer / 'graphics_provider.json'
        outside = Path(self.tmp.name) / 'provider.json'
        path.rename(outside)
        path.symlink_to(os.path.relpath(outside, path.parent))
        self.assertIn('graphics_provider.json: path escapes', self.errors())

    def test_non_regular_file_is_rejected_without_reading(self):
        path = self.layer / 'usr/lib/libdisplay-info.so.3'
        path.unlink()
        os.mkfifo(path)
        self.assertIn('expected a regular packaged file', self.errors())

    def test_valid_build_tree_cannot_hide_bad_finished_payload(self):
        build = Path(self.tmp.name) / 'srcdir/layer'
        shutil.copytree(self.layer, build, symlinks=True)
        self.assertEqual(validator.validate_payload(build), [])
        (self.layer / 'graphics_provider.json').unlink()
        (self.layer / 'usr/lib32/libdisplay-info.so.3').unlink()
        result, out, err = self.cli('--package-root', self.package)
        self.assertEqual((result, out), (1, ''))
        self.assertIn('graphics_provider.json: missing', err)
        self.assertIn('usr/lib32/libdisplay-info.so.3: missing', err)

    def test_package_layer_cannot_redirect_to_build_tree(self):
        build = self.package / 'srcdir/layer'
        build.parent.mkdir()
        self.layer.rename(build)
        self.layer.symlink_to(os.path.relpath(build, self.layer.parent))
        result, _, err = self.cli('--package-root', self.package)
        self.assertEqual(result, 1)
        self.assertIn('must not be redirected', err)

    def test_check_does_not_modify_payload(self):
        def snapshot():
            return {str(p.relative_to(self.layer)): (p.lstat().st_mode, p.lstat().st_mtime_ns,
                    str(p.readlink()) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                    for p in self.layer.rglob('*')}
        before = snapshot()
        self.assertEqual(self.errors(), '')
        self.assertEqual(snapshot(), before)


if __name__ == '__main__':
    unittest.main()
