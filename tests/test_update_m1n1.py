"""The ESP Stage 2 files an update and an image build write, per Mac.

The shipped update-m1n1 runs for real against a temporary ESP. Only the system
paths it hardcodes are redirected, as the package build does for its config
file, and the ESP mount is stubbed.
"""
import gzip
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packages/asahi-scripts/update-m1n1'
PKGBUILD = ROOT / 'packages/asahi-scripts/PKGBUILD'

# Every chip AuraStage1Format.usesMachO admits or names, and every one below it.
MACHO_CHIPS = ('t8132', 't6040', 't6041', 't8140', 't8142', 't8152', 't6050', 't6051', 't6052', 't8130', 't8fff', 't6fff')
EARLIER_CHIPS = ('t8103', 't8112', 't8122', 't6000', 't6001', 't6002', 't6020', 't6021', 't6022', 't6030', 't6031', 't6034', 't8015')

AURA = b'AURA-STAGE2-BINARY'
UBOOT = b'u-boot payload'
FROZEN = b'frozen old aura stage 2'


def device_tree(compatibles):
    """A minimal valid flattened device tree whose root has these compatibles."""
    strings = b'compatible\0'
    value = b''.join(item.encode() + b'\0' for item in compatibles)
    padded = value + b'\0' * (-len(value) % 4)
    body = (struct.pack('>I', 1) + b'\0\0\0\0'
            + struct.pack('>III', 3, len(value), 0) + padded
            + struct.pack('>I', 2) + struct.pack('>I', 9))
    struct_offset = 40
    strings_offset = struct_offset + len(body)
    total = strings_offset + len(strings)
    header = struct.pack('>10I', 0xD00DFEED, total, struct_offset, strings_offset, 40,
                         17, 16, 0, len(strings), len(body))
    return header + body + strings


def compatible_file(board, chip):
    return f'apple,{board}\0apple,{chip}\0apple,arm-platform\0'.encode()


def load_prepare():
    spec = importlib.util.spec_from_file_location('prepare_ctxr_stage2', ROOT / 'scripts/prepare-ctxr-stage2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare_ctxr = load_prepare()


class UpdateM1n1(unittest.TestCase):
    TREES = {'t8103-j274.dtb': b'dtb-j274', 't6040-j616s-tether.dtb': b'dtb-j616s-tether',
             't6040-j616s.dtb': b'dtb-j616s', 't8140-j700-ane-test.dtb': b'dtb-j700-ane',
             't8140-j700.dtb': b'dtb-j700', 't8132-j713.dtb': b'dtb-j713'}

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = root = Path(temp.name)
        self.esp = root / 'esp'
        (self.esp / 'm1n1').mkdir(parents=True)
        self.boot = self.esp / 'm1n1/boot.bin'
        self.ctxr = self.esp / 'm1n1/boot-ctxr.bin'
        self.boot.write_bytes(FROZEN)
        os.utime(self.boot, (1000000, 1000000))
        self.dtbs = root / 'dtbs'
        self.dtbs.mkdir()
        for name, data in self.TREES.items():
            (self.dtbs / name).write_bytes(data)
        (root / 'm1n1.bin').write_bytes(AURA)
        (root / 'u-boot-nodtb.bin').write_bytes(UBOOT)
        run = root / 'run'
        run.mkdir()
        bindir = root / 'bin'
        bindir.mkdir()
        # The ESP mount becomes a link to the fixture ESP; umount removes it.
        (bindir / 'functions.sh').write_text(
            'info() { :; }\nwarn() { echo "$@" >&2; }\n'
            f'mount_sys_esp() {{ ln -s "{self.esp}" "$1"; }}\n')
        (bindir / 'umount').write_text('#!/bin/sh\nrm -f "$1"\n')
        (bindir / 'umount').chmod(0o755)
        text = SCRIPT.read_text()
        for system, fixture in (('/run/', f'{run}/'), ('/etc/default/', f'{root}/default-')):
            self.assertIn(system, text)
            text = text.replace(system, fixture)
        self.script = bindir / 'update-m1n1'
        self.script.write_text(text)
        self.script.chmod(0o755)
        self.compatible = root / 'compatible'

    def run_update(self, *args, shell='sh', **env):
        environment = dict(os.environ, PATH=f'{self.root / "bin"}:{os.environ["PATH"]}', LC_ALL='C',
                           SOURCE=str(self.root), DTBS=f'{self.dtbs}/*.dtb',
                           CONFIG=str(self.root / 'm1n1.conf'),
                           AURORA_DEVICE_TREE_COMPATIBLE=str(self.compatible))
        environment.update(env)
        return subprocess.run([shell, str(self.script), *args], env=environment,
                              capture_output=True, text=True)

    def on(self, board, chip):
        self.compatible.write_bytes(compatible_file(board, chip))

    def parts(self, trees, aura=AURA, options=b''):
        return aura + b''.join(self.TREES[name] for name in trees), UBOOT, options

    def read_parts(self, path):
        """A Stage 2 split at its gzip member: the aura and trees, U-Boot, the option lines."""
        data = path.read_bytes()
        cursor = data.index(b'\x1f\x8b\x08')
        inflater = zlib.decompressobj(wbits=31)
        return data[:cursor], inflater.decompress(data[cursor:]), inflater.unused_data

    def assert_frozen(self):
        self.assertEqual(self.boot.read_bytes(), FROZEN)
        self.assertEqual(self.boot.stat().st_mtime, 1000000)
        self.assertFalse((self.esp / 'm1n1/boot.bin.old').exists())
        self.assertFalse((self.esp / 'm1n1/boot.bin.new').exists())

    def test_every_macho_chip_leaves_boot_bin_byte_identical(self):
        for chip in MACHO_CHIPS:
            with self.subTest(chip):
                self.on('j700', chip)
                self.ctxr.unlink(missing_ok=True)
                result = self.run_update()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_frozen()
                self.assertTrue(self.ctxr.is_file())

    def test_macho_stage2_holds_only_this_boards_trees_in_byte_order(self):
        # Arch's sh is bash, which sorts globs by locale.
        for shell in ('sh', 'bash'):
            with self.subTest(shell):
                self.on('j700', 't8140')
                self.assertEqual(self.run_update(shell=shell, LC_ALL='en_US.UTF-8').returncode, 0)
                self.assertEqual(self.read_parts(self.ctxr),
                                 self.parts(['t8140-j700-ane-test.dtb', 't8140-j700.dtb']))
                self.on('j616s', 't6040')
                self.assertEqual(self.run_update(shell=shell, LC_ALL='en_US.UTF-8').returncode, 0)
                self.assertEqual(self.read_parts(self.ctxr),
                                 self.parts(['t6040-j616s-tether.dtb', 't6040-j616s.dtb']))

    def test_macho_board_name_is_matched_whole(self):
        self.on('j616', 't6040')
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no device tree for j616', result.stderr)

    def test_macho_update_keeps_the_previous_ctxr_stage2(self):
        self.on('j700', 't8140')
        self.assertEqual(self.run_update().returncode, 0)
        first = self.ctxr.read_bytes()
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.old').exists())
        (self.root / 'm1n1.bin').write_bytes(b'NEWER-AURA')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual((self.esp / 'm1n1/boot-ctxr.bin.old').read_bytes(), first)
        self.assertTrue(self.ctxr.read_bytes().startswith(b'NEWER-AURA'))
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.new').exists())
        self.assert_frozen()

    def test_macho_unchanged_stage2_keeps_the_rollback_copy(self):
        self.on('j700', 't8140')
        self.assertEqual(self.run_update().returncode, 0)
        old = self.esp / 'm1n1/boot-ctxr.bin.old'
        old.write_bytes(b'older generation')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(old.read_bytes(), b'older generation')
        self.assert_frozen()

    def test_macho_explicit_boot_bin_target_is_redirected(self):
        self.on('j700', 't8140')
        self.assertEqual(self.run_update(str(self.boot)).returncode, 0)
        self.assert_frozen()
        self.assertTrue(self.ctxr.is_file())

    def test_macho_explicit_other_target_is_written_as_given(self):
        self.on('j700', 't8140')
        other = self.root / 'other.bin'
        self.assertEqual(self.run_update(str(other)).returncode, 0)
        self.assertEqual(self.read_parts(other), self.parts(['t8140-j700-ane-test.dtb', 't8140-j700.dtb']))
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())

    def test_macho_without_a_tree_for_the_board_changes_nothing(self):
        self.on('j873g', 't8152')
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no device tree for j873g', result.stderr)
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.new').exists())

    def test_earlier_chips_keep_updating_boot_bin_with_every_tree(self):
        for chip in EARLIER_CHIPS:
            with self.subTest(chip):
                self.boot.write_bytes(FROZEN)
                (self.esp / 'm1n1/boot.bin.old').unlink(missing_ok=True)
                self.on('j274', chip)
                result = self.run_update()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.read_parts(self.boot), self.parts(sorted(self.TREES)))
                self.assertEqual((self.esp / 'm1n1/boot.bin.old').read_bytes(), FROZEN)
                self.assertFalse(self.ctxr.exists())

    def test_earlier_chip_leaves_a_present_ctxr_file_alone(self):
        self.on('j274', 't8103')
        self.ctxr.write_bytes(b'not ours')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(self.ctxr.read_bytes(), b'not ours')

    def test_without_a_device_tree_it_writes_boot_bin_as_an_image_build_needs(self):
        self.assertEqual(self.run_update(str(self.boot)).returncode, 0)
        self.assertEqual(self.read_parts(self.boot), self.parts(sorted(self.TREES)))
        self.assertFalse(self.ctxr.exists())

    def test_another_machine_is_treated_as_upstream_does(self):
        self.compatible.write_bytes(b'linux,dummy-virt\0')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(self.read_parts(self.boot), self.parts(sorted(self.TREES)))
        self.assertFalse(self.ctxr.exists())

    def test_m1n1_conf_options_reach_the_ctxr_stage2(self):
        self.on('j700', 't8140')
        (self.root / 'm1n1.conf').write_text('chosen.bootargs=quiet\nnot an option\n')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(self.read_parts(self.ctxr),
                         self.parts(['t8140-j700-ane-test.dtb', 't8140-j700.dtb'], options=b'chosen.bootargs=quiet\n'))


def board_image(board, chip):
    return AURA + device_tree([f'apple,{board}', f'apple,{chip}', 'apple,arm-platform']) + gzip.compress(UBOOT, mtime=0)


class PrepareCtxrStage2(unittest.TestCase):
    BOARDS = {'j274': 't8103', 'j700': 't8140', 'j616s': 't6040', 'j614s': 't6040', 'j713': 't8132', 'j873g': 't8152'}

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.m1n1 = Path(temp.name) / 'esp/m1n1'
        self.m1n1.mkdir(parents=True)
        (self.m1n1 / 'boot.bin').write_bytes(b'combined')
        for board, chip in self.BOARDS.items():
            (self.m1n1 / f'boot-{board}.bin').write_bytes(board_image(board, chip))

    def test_image_esp_carries_both_files_and_each_macho_boards_own(self):
        before = {path.name: path.read_bytes() for path in self.m1n1.iterdir()}
        written = prepare_ctxr.prepare(self.m1n1, self.m1n1)
        self.assertEqual(sorted(written), ['boot-ctxr-j614s.bin', 'boot-ctxr-j616s.bin', 'boot-ctxr-j700.bin',
                                           'boot-ctxr-j713.bin', 'boot-ctxr-j873g.bin', 'boot-ctxr.bin'])
        self.assertEqual((self.m1n1 / 'boot-ctxr.bin').read_bytes(), b'combined')
        self.assertEqual((self.m1n1 / 'boot-ctxr-j700.bin').read_bytes(), before['boot-j700.bin'])
        self.assertFalse((self.m1n1 / 'boot-ctxr-j274.bin').exists())
        for name, data in before.items():
            self.assertEqual((self.m1n1 / name).read_bytes(), data)

    def test_a_magic_inside_aura_is_not_mistaken_for_the_tree(self):
        path = self.m1n1 / 'boot-j700.bin'
        path.write_bytes(prepare_ctxr.DTB_MAGIC + b'\xff' * 60 + path.read_bytes())
        prepare_ctxr.prepare(self.m1n1, self.m1n1)
        self.assertTrue((self.m1n1 / 'boot-ctxr-j700.bin').is_file())

    def test_refusals(self):
        cases = {
            'missing required board': lambda: (self.m1n1 / 'boot-j614s.bin').unlink(),
            'board file without its tree': lambda: (self.m1n1 / 'boot-j700.bin').write_bytes(b'no tree'),
            'oversized board file': lambda: (self.m1n1 / 'boot-j700.bin').write_bytes(
                board_image('j700', 't8140') + b'\0' * prepare_ctxr.MAX_BOARD_BYTES),
            'existing output': lambda: (self.m1n1 / 'boot-ctxr.bin').write_bytes(b'stale'),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                with self.assertRaises(ValueError):
                    prepare_ctxr.prepare(self.m1n1, self.m1n1)

    def test_chip_list_matches_the_update_tool(self):
        for chip in MACHO_CHIPS:
            self.assertTrue(prepare_ctxr.uses_macho([f'apple,{chip}']), chip)
        for chip in EARLIER_CHIPS:
            self.assertFalse(prepare_ctxr.uses_macho([f'apple,{chip}']), chip)


class Recipes(unittest.TestCase):
    def test_the_package_ships_the_tested_script(self):
        recipe = PKGBUILD.read_text()
        self.assertIn('update-m1n1)', recipe.split('sha256sums=', 1)[0])
        digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        self.assertIn(digest, recipe)
        self.assertIn('install -m755 "${srcdir}/update-m1n1" update-m1n1', recipe)

    def test_aura_needs_the_package_that_writes_boot_ctxr(self):
        scripts = PKGBUILD.read_text()
        version = re.search(r'(?m)^pkgver=(\S+)$', scripts)[1]
        release = re.search(r'(?m)^pkgrel=(\S+)$', scripts)[1]
        self.assertIn(f"'asahi-scripts>={version}-{release}'", (ROOT / 'packages/aura/PKGBUILD').read_text())

    def test_image_build_adds_the_ctxr_files_after_the_finalizer(self):
        text = (ROOT / 'scripts/build-image').read_text()
        finalize = text.index('finalize-image"')
        ctxr = text.index('prepare-ctxr-stage2.py')
        archive = text.index('-filesystems.tar.zst')
        self.assertLess(finalize, ctxr)
        self.assertLess(ctxr, archive)


if __name__ == '__main__':
    unittest.main()
