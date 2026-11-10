"""CTXR slot routing, image preparation and the packaged updater contracts.

The updater's Arch layout (bootchain_arch.py over fedora-aurora's bootchain.py)
runs against a temporary root with valid DTBs and a declared kernel DT ABI
generation. scripts/test-stage2-transactions runs the shell entry point and
the pacman hook in real pacman transactions.
"""
import contextlib
import io
import gzip
import hashlib
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch
import re
import struct
import subprocess
import sys
import shutil
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packages/asahi-scripts/update-m1n1'
HELPER = ROOT / 'packages/asahi-scripts/bootchain_arch.py'
SHARED = ROOT / 'packages/asahi-scripts/bootchain.py'
_helper_spec = importlib.util.spec_from_file_location('ctxr_bootchain_arch', HELPER)
bootchain = importlib.util.module_from_spec(_helper_spec)
_helper_spec.loader.exec_module(bootchain)
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
    struct_offset = 56
    strings_offset = struct_offset + len(body)
    total = strings_offset + len(strings)
    header = struct.pack('>10I', 0xD00DFEED, total, struct_offset, strings_offset, 40,
                         17, 16, 0, len(strings), len(body))
    return header + b'\0' * 16 + body + strings


def compatible_file(board, chip):
    return f'apple,{board}\0apple,{chip}\0apple,arm-platform\0'.encode()


def load_prepare():
    spec = importlib.util.spec_from_file_location('prepare_ctxr_stage2', ROOT / 'scripts/prepare-ctxr-stage2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare_ctxr = load_prepare()


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class UpdateM1n1(unittest.TestCase):
    NAMES = ('t8103-j274.dtb', 't6040-j616s-tether.dtb', 't6040-j616s.dtb',
             't8140-j700-ane-test.dtb', 't8140-j700.dtb', 't8132-j713.dtb')
    TREES = {name: device_tree([f'apple,{name.split("-", 1)[1].split(".", 1)[0].split("-", 1)[0]}',
                               f'apple,{name.split("-", 1)[0]}', f'fixture,{name}']) for name in NAMES}

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
        # Arch's linux-aurora layout: one flat dtbs directory per kernel release.
        installed = root / 'usr/lib/modules/7.3.0-1-24-ARCH/dtbs'
        installed.mkdir(parents=True)
        (installed.parent / 'vmlinuz').write_bytes(b'fixture kernel')
        (installed.parent / 'dtb-abi').write_text('1\n')
        (installed.parent / 'pkgbase').write_text('linux-aurora\n')
        (root / 'boot').mkdir()
        (root / 'boot/vmlinuz-linux-aurora').write_bytes(b'fixture kernel')
        for name, data in self.TREES.items():
            (self.dtbs / name).write_bytes(data)
            (installed / name).write_bytes(data)
        (root / 'm1n1.bin').write_bytes(AURA)
        (root / 'u-boot-nodtb.bin').write_bytes(UBOOT)
        self.compatible = root / 'compatible'
        self.marker = root / 'monitor-free'

    def run_update(self, *args, **env):
        settings = dict(M1N1='/m1n1.bin', U_BOOT='/u-boot-nodtb.bin', TARGET='/esp/m1n1/boot.bin',
                        DTBS='/dtbs/*.dtb', CONFIG='/m1n1.conf',
                        AURORA_DEVICE_TREE_COMPATIBLE='/compatible', AURORA_MONITOR_FREE_MARKER='/monitor-free')
        settings.update(env)
        if args:
            settings['TARGET'] = str(args[0])
        if settings['DTBS'] is None:
            del settings['DTBS']
        for key in ('M1N1', 'U_BOOT', 'TARGET', 'DTBS', 'CONFIG',
                    'AURORA_DEVICE_TREE_COMPATIBLE', 'AURORA_MONITOR_FREE_MARKER'):
            if key in settings:
                settings[key] = settings[key].replace(str(self.root), '')
        output = io.StringIO()
        try:
            locale = {key: value for key, value in settings.items() if key in ('LC_ALL', 'LOCPATH')}
            with patch.dict(os.environ, locale), contextlib.redirect_stdout(output):
                bootchain.ArchUpdate(self.root, settings).apply()
        except (bootchain.Refused, OSError) as error:
            return subprocess.CompletedProcess(['update-m1n1'], 1, output.getvalue(), str(error))
        return subprocess.CompletedProcess(['update-m1n1'], 0, output.getvalue(), '')

    def on(self, board, chip):
        self.compatible.write_bytes(compatible_file(board, chip))

    def monitor_free(self):
        self.marker.write_bytes(b'')

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

    def assert_updated_boot_bin(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_parts(self.boot), self.parts(sorted(self.TREES)))
        self.assertEqual((self.esp / 'm1n1/boot.bin.old').read_bytes(), FROZEN)
        self.assertFalse(self.ctxr.exists())
        self.assertNotIn('WARNING', result.stderr)
        self.assertIn('m1n1/boot.bin', result.stdout)

    def test_macho_without_the_marker_keeps_updating_boot_bin(self):
        for chip in MACHO_CHIPS:
            with self.subTest(chip):
                self.boot.write_bytes(FROZEN)
                (self.esp / 'm1n1/boot.bin.old').unlink(missing_ok=True)
                self.on('j700', chip)
                self.assert_updated_boot_bin(self.run_update())

    def test_macho_with_the_marker_leaves_boot_bin_byte_identical(self):
        self.monitor_free()
        for chip in MACHO_CHIPS:
            with self.subTest(chip):
                self.on('j700', chip)
                self.ctxr.unlink(missing_ok=True)
                result = self.run_update()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_frozen()
                self.assertTrue(self.ctxr.is_file())

    def test_macho_with_the_marker_says_where_the_update_went_and_warns_nothing(self):
        self.monitor_free()
        self.on('j700', 't8140')
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('Stage 2 verified at', result.stdout)
        self.assertIn('boot-ctxr.bin', result.stdout)
        self.assert_frozen()

    def en_us(self):
        """An en_US.UTF-8 locale that sorts these trees unlike C, built here when the system has none."""
        environment = {'LC_ALL': 'en_US.UTF-8'}
        names = subprocess.run(['locale', '-a'], capture_output=True, text=True).stdout.split()
        if not any(name.lower().replace('-', '') == 'en_us.utf8' for name in names):
            path = self.root / 'locales'
            path.mkdir()
            try:
                subprocess.run(['localedef', '-i', 'en_US', '-f', 'UTF-8', str(path / 'en_US.UTF-8')],
                               capture_output=True)
            except OSError:
                pass
            if not (path / 'en_US.UTF-8').exists():
                self.skipTest('en_US.UTF-8 is not installed and localedef could not build it')
            environment['LOCPATH'] = str(path)
        order = subprocess.run(['bash', '-c', 'printf "%s\\n" t6040-j616s*.dtb'], cwd=self.dtbs,
                               env=dict(os.environ, **environment), capture_output=True, text=True).stdout
        if order.split() != ['t6040-j616s.dtb', 't6040-j616s-tether.dtb']:
            self.skipTest('this en_US.UTF-8 sorts the trees as C does, so it would prove nothing')
        return environment

    def test_macho_stage2_holds_only_this_boards_trees_in_byte_order(self):
        self.monitor_free()
        # The old shell updater sorted its DTB glob by locale; the shared
        # helper sorts file names bytewise whatever the locale.
        for locale in ({'LC_ALL': 'C'}, self.en_us()):
            with self.subTest(locale=locale):
                self.on('j700', 't8140')
                self.assertEqual(self.run_update(**locale).returncode, 0)
                self.assertEqual(self.read_parts(self.ctxr),
                                 self.parts(['t8140-j700-ane-test.dtb', 't8140-j700.dtb']))
                self.on('j616s', 't6040')
                self.assertEqual(self.run_update(**locale).returncode, 0)
                self.assertEqual(self.read_parts(self.ctxr),
                                 self.parts(['t6040-j616s-tether.dtb', 't6040-j616s.dtb']))

    def test_macho_board_name_is_matched_whole(self):
        self.monitor_free()
        self.on('j616', 't6040')
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('have no apple,j616', result.stderr)
        self.assertFalse(self.ctxr.exists())

    def test_macho_update_keeps_the_previous_ctxr_stage2(self):
        self.monitor_free()
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
        self.monitor_free()
        self.on('j700', 't8140')
        self.assertEqual(self.run_update().returncode, 0)
        old = self.esp / 'm1n1/boot-ctxr.bin.old'
        old.write_bytes(b'older generation')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(old.read_bytes(), b'older generation')
        self.assert_frozen()

    def test_macho_explicit_boot_bin_target_is_redirected(self):
        self.monitor_free()
        self.on('j700', 't8140')
        self.assertEqual(self.run_update(str(self.boot)).returncode, 0)
        self.assert_frozen()
        self.assertTrue(self.ctxr.is_file())

    def test_macho_explicit_other_target_is_written_as_given(self):
        self.monitor_free()
        self.on('j700', 't8140')
        other = self.root / 'other.bin'
        result = self.run_update(str(other))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('WARNING', result.stderr)
        self.assertEqual(self.read_parts(other), self.parts(['t8140-j700-ane-test.dtb', 't8140-j700.dtb']))
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())

    def test_macho_without_a_tree_for_the_board_changes_nothing(self):
        # Refuse before changing the image; the pacman hook reports it.
        self.monitor_free()
        self.on('j873g', 't8152')
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('have no apple,j873g', result.stderr)
        self.assert_frozen()
        self.assertFalse(self.ctxr.exists())
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.new').exists())

    def test_a_ctxr_stage2_over_auras_slot_is_not_written(self):
        self.monitor_free()
        self.on('j700', 't8140')
        self.assertEqual(self.run_update().returncode, 0)
        first = self.ctxr.read_bytes()
        (self.root / 'm1n1.bin').write_bytes(b'\0' * (16 << 20))
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('16 MiB', result.stderr)
        self.assertEqual(self.ctxr.read_bytes(), first)
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.new').exists())
        self.assertFalse((self.esp / 'm1n1/boot-ctxr.bin.old').exists())
        self.assert_frozen()

    def test_earlier_chips_are_the_same_with_and_without_the_marker(self):
        for marked in (False, True):
            if marked:
                self.monitor_free()
            for chip in EARLIER_CHIPS:
                with self.subTest(chip=chip, marked=marked):
                    self.boot.write_bytes(FROZEN)
                    (self.esp / 'm1n1/boot.bin.old').unlink(missing_ok=True)
                    self.on('j274', chip)
                    self.assert_updated_boot_bin(self.run_update())

    def test_earlier_chip_leaves_a_present_ctxr_file_alone(self):
        self.monitor_free()
        self.on('j274', 't8103')
        self.ctxr.write_bytes(b'not ours')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(self.ctxr.read_bytes(), b'not ours')

    def test_without_a_device_tree_it_writes_boot_bin_as_an_image_build_needs(self):
        self.monitor_free()
        self.assert_updated_boot_bin(self.run_update(str(self.boot)))

    def test_an_image_build_on_a_macho_host_ignores_its_device_tree(self):
        self.monitor_free()
        self.on('j700', 't8140')
        self.assert_updated_boot_bin(self.run_update(str(self.boot), AURORA_DEVICE_TREE_COMPATIBLE='/nonexistent'))

    def test_another_machine_is_treated_as_upstream_does(self):
        self.monitor_free()
        self.compatible.write_bytes(b'linux,dummy-virt\0')
        self.assert_updated_boot_bin(self.run_update())

    def test_without_dtbs_the_newest_kernels_own_trees_are_used(self):
        self.on('j274', 't8103')
        self.assert_updated_boot_bin(self.run_update(DTBS=None))

    def test_m1n1_conf_options_reach_the_ctxr_stage2(self):
        self.monitor_free()
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

    def test_a_second_run_replaces_what_the_first_wrote(self):
        prepare_ctxr.prepare(self.m1n1, self.m1n1)
        (self.m1n1 / 'boot.bin').write_bytes(b'rebuilt combined')
        prepare_ctxr.prepare(self.m1n1, self.m1n1)
        self.assertEqual((self.m1n1 / 'boot-ctxr.bin').read_bytes(), b'rebuilt combined')

    def test_a_magic_inside_aura_is_not_mistaken_for_the_tree(self):
        path = self.m1n1 / 'boot-j700.bin'
        path.write_bytes(prepare_ctxr.DTB_MAGIC + b'\xff' * 60 + path.read_bytes())
        prepare_ctxr.prepare(self.m1n1, self.m1n1)
        self.assertTrue((self.m1n1 / 'boot-ctxr-j700.bin').is_file())

    def test_an_image_build_refuses_any_problem(self):
        cases = {
            'missing required board': lambda: (self.m1n1 / 'boot-j614s.bin').unlink(),
            'board file without its tree': lambda: (self.m1n1 / 'boot-j700.bin').write_bytes(b'no tree'),
            'oversized board file': lambda: (self.m1n1 / 'boot-j700.bin').write_bytes(
                board_image('j700', 't8140') + b'\0' * prepare_ctxr.MAX_STAGE2_BYTES),
            'oversized shared file': lambda: (self.m1n1 / 'boot.bin').write_bytes(
                b'\0' * (prepare_ctxr.MAX_STAGE2_BYTES + 1)),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                with self.assertRaises(ValueError):
                    prepare_ctxr.prepare(self.m1n1, self.m1n1)

    def test_a_shared_file_at_the_limit_is_accepted(self):
        (self.m1n1 / 'boot.bin').write_bytes(b'\0' * prepare_ctxr.MAX_STAGE2_BYTES)
        self.assertIn('boot-ctxr.bin', prepare_ctxr.prepare(self.m1n1, self.m1n1))

    def test_keep_going_only_leaves_out_the_file_with_the_problem(self):
        (self.m1n1 / 'boot-j614s.bin').unlink()
        (self.m1n1 / 'boot-j700.bin').write_bytes(board_image('j700', 't8140') + b'\0' * prepare_ctxr.MAX_STAGE2_BYTES)
        written = prepare_ctxr.prepare(self.m1n1, self.m1n1, keep_going=True)
        self.assertEqual(sorted(written), ['boot-ctxr-j616s.bin', 'boot-ctxr-j713.bin', 'boot-ctxr-j873g.bin', 'boot-ctxr.bin'])

    def test_chip_list_matches_the_update_tool(self):
        for chip in MACHO_CHIPS:
            self.assertTrue(prepare_ctxr.uses_macho([f'apple,{chip}']), chip)
        for chip in EARLIER_CHIPS:
            self.assertFalse(prepare_ctxr.uses_macho([f'apple,{chip}']), chip)


def git_blob(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


# fedora-aurora packages/update-m1n1 (aurora-silicon/fedora-aurora#193, #207, #226, #232, #251) as git
# blob ids: these files are shared with Fedora byte for byte.
FEDORA_BLOBS = {
    'bootchain.py': '78b96a05168e7ead90abc8e1d8149351ff214f54',
    'test_bootchain.py': '28b5fe74520f754a0a69f4f14dcee83bd2e4a9cd',
    'aurora-stage2-commit.service': '6f9de701f9485dc4b869e8b73f4ef35aa67dbeae',
    'aurora-stage2-guard.service': '693a255c2bedb707e55fb0e7db45ae9d9d87949d',
    'aurora-stage2-guard.timer': '02dfb37c3eb71a9531276a026b25c62ac84ef1cb',
    '90-aurora-stage2.preset': 'e7e350b52d42ea65cae85d97bb1bb5cf778c1608',
}
# fedora-aurora packages/kernel-aurora/dtb-abi: both kernels declare one generation.
FEDORA_DTB_ABI = 'd00491fd7e5bb6fa28c517a0bb32b8b506539d4d'


class Recipes(unittest.TestCase):
    def test_the_package_ships_the_tested_files(self):
        recipe = PKGBUILD.read_text()
        sources = recipe.split('sha256sums=', 1)[0]
        for path in sorted(PKGBUILD.parent.iterdir()):
            if (not path.is_file() or path.name in ('PKGBUILD', 'asahi-scripts.install')
                    or path.name.startswith('.') or path.suffix == '.pyc'):
                continue
            with self.subTest(path.name):
                self.assertRegex(sources, rf'(?m)^\s+{re.escape(path.name)}\)?$')
                self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), recipe)
        self.assertIn('install -m755 "${srcdir}/update-m1n1" update-m1n1', recipe)
        self.assertIn('install -m644 "${srcdir}/95-m1n1-install.hook" libalpm/hooks/95-m1n1-install.hook',
                      recipe)
        self.assertIn('install -Dm644 -t "$pkgdir/usr/libexec/aurora" bootchain.py bootchain_arch.py', recipe)
        self.assertIn('install -Dm755 aurora-stage2-commit "$pkgdir/usr/libexec/aurora/aurora-stage2-commit"', recipe)
        self.assertIn('python3 test_bootchain.py\n  python3 test_bootchain_arch.py', recipe)

    def test_shared_files_are_fedoras_byte_for_byte(self):
        for name, blob in FEDORA_BLOBS.items():
            with self.subTest(name):
                self.assertEqual(git_blob(PKGBUILD.parent / name), blob)
        self.assertEqual(git_blob(ROOT / 'packages/linux-aurora/dtb-abi'), FEDORA_DTB_ABI)

    def test_units_run_the_arch_commit_helper(self):
        units = PKGBUILD.parent
        self.assertIn('ExecStart=/usr/libexec/aurora/aurora-stage2-commit\n',
                      (units / 'aurora-stage2-commit.service').read_text())
        self.assertIn('ExecStart=/usr/libexec/aurora/aurora-stage2-commit --guard\n',
                      (units / 'aurora-stage2-guard.service').read_text())
        self.assertIn('exec /usr/bin/update-m1n1 "$@"', (units / 'aurora-stage2-commit').read_text())
        self.assertIn('/usr/libexec/aurora/bootchain_arch.py', SCRIPT.read_text())
        install = (units / 'asahi-scripts.install').read_text()
        self.assertIn('preset \\\n    aurora-stage2-commit.service aurora-stage2-guard.timer', install)
        # 20261023-4 brought the units; later releases must not preset them again.
        self.assertIn('vercmp "$2" 20261023-4', install)
        self.assertRegex(PKGBUILD.read_text(), r'(?m)^pkgver=20261023$')
        self.assertRegex(PKGBUILD.read_text(), r'(?m)^pkgrel=8$')

    def test_the_hook_runs_after_kernel_removal_too(self):
        hook = (PKGBUILD.parent / '95-m1n1-install.hook').read_text()
        for line in ('Operation = Install', 'Operation = Upgrade', 'Operation = Remove',
                     'Target = usr/lib/modules/*/dtbs/*', 'Target = usr/lib/modules/*/dtb-abi',
                     'Target = usr/lib/asahi-boot/*', 'When = PostTransaction', 'Exec = /usr/bin/update-m1n1'):
            self.assertIn(line + '\n', hook)

    def test_aura_needs_the_capability_only_this_package_provides(self):
        self.assertRegex(PKGBUILD.read_text(),
                         r"(?m)^provides=\('aurora-stage2-ctxr-slot=1' 'aurora-stage2-trial=1'\)$")
        aura = (ROOT / 'packages/aura/PKGBUILD').read_text()
        self.assertRegex(aura, r"(?m)^  depends=\(.*'aurora-stage2-ctxr-slot'.*\)$")

    def test_boot_chain_packages_need_the_trial_updater(self):
        aura = (ROOT / 'packages/aura/PKGBUILD').read_text()
        self.assertRegex(aura, r"(?m)^  depends=\(.*'aurora-stage2-trial'.*\)$")
        uboot = (ROOT / 'packages/uboot-aurora/PKGBUILD').read_text()
        self.assertRegex(uboot, r"(?m)^  depends=\('aurora-stage2-trial'\)$")
        kernel = (ROOT / 'packages/linux-aurora/PKGBUILD').read_text()
        self.assertRegex(kernel, r'(?m)^  depends=\(.* aurora-stage2-trial .*\)$')

    def test_the_kernel_ships_its_dt_abi_generation(self):
        kernel = (ROOT / 'packages/linux-aurora/PKGBUILD').read_text()
        self.assertRegex(kernel.split('sha256sums=', 1)[0], r'(?m)^\s+dtb-abi\)$')
        self.assertIn(hashlib.sha256((ROOT / 'packages/linux-aurora/dtb-abi').read_bytes()).hexdigest(), kernel)
        install = '  install -m644 "$srcdir/dtb-abi" "$modulesdir/dtb-abi"\n'
        self.assertIn(install, kernel)
        self.assertLess(kernel.index('local modulesdir="$pkgdir/usr/lib/modules/$kernver"'), kernel.index(install))
        self.assertRegex((ROOT / 'packages/linux-aurora/dtb-abi').read_text(), r'\A(0|[1-9][0-9]*)\n\Z')

    def flag(self, recipe, name):
        return int(re.search(rf'(?m)^{name}=([01])$', (ROOT / 'packages' / recipe / 'PKGBUILD').read_text())[1])

    def sourced(self, recipe, name, value, array):
        """An array a PKGBUILD sets from one of its flags, with the flag set to value."""
        text = (ROOT / 'packages' / recipe / 'PKGBUILD').read_text()
        text = re.sub(rf'(?m)^{name}=[01]$', f'{name}={value}', text)
        result = subprocess.run(['bash', '-c', f'source /dev/stdin; printf "%s\\n" "${{{array}[@]}}"'],
                                input=text, capture_output=True, text=True, check=True)
        return result.stdout.split()

    def step(self, recipe, start, end):
        """The lines of a PKGBUILD from the one starting `start` to the next one equal to `end`."""
        text = (ROOT / 'packages' / recipe / 'PKGBUILD').read_text()
        return re.search(rf'(?ms)^{re.escape(start)}.*?^{re.escape(end)}$', text)[0]

    def test_an_aura_without_the_monitor_needs_a_kernel_that_keeps_its_code_in_the_window(self):
        # The flags are checked against the pinned source and the resolved
        # configuration when the packages build, so this is what they ship.
        monitor_free = self.flag('aura', '_monitor_free')
        ctxr_execmem = self.flag('linux-aurora', '_ctxr_execmem')
        if monitor_free:
            self.assertEqual(ctxr_execmem, 1, 'aura without the monitor needs CONFIG_ARM64_CTXR_EXECMEM=y')
        config = (ROOT / 'packages/linux-aurora/config').read_text().splitlines()
        self.assertIn('CONFIG_ARM64_CTXR_EXECMEM=y', config)

    def test_the_flags_become_the_requirement_and_its_provider(self):
        for value, expected in ((0, []), (1, ['aurora-ctxr-execmem'])):
            with self.subTest(value=value):
                self.assertEqual(self.sourced('aura', '_monitor_free', value, '_ctxr_kernel'), expected)
                self.assertEqual(
                    self.sourced('linux-aurora', '_ctxr_execmem', value, '_ctxr_provides'), expected)
        aura = (ROOT / 'packages/aura/PKGBUILD').read_text()
        self.assertRegex(aura, r'(?m)^  depends=\(.*"\$\{_ctxr_kernel\[@\]\}"\)$')
        kernel = (ROOT / 'packages/linux-aurora/PKGBUILD').read_text()
        self.assertRegex(kernel, r'(?m)^  provides=\(.*"\$\{_ctxr_provides\[@\]\}"\)$')

    def test_the_kernel_recipe_refuses_a_flag_its_configuration_disagrees_with(self):
        check = self.step('linux-aurora', '  local ctxr=0', '  fi')
        for line, flag, ok in (('CONFIG_ARM64_CTXR_EXECMEM=y', 1, True), ('', 0, True),
                               ('CONFIG_ARM64_CTXR_EXECMEM=y', 0, False), ('', 1, False)):
            with self.subTest(line=line, flag=flag), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'build/base').mkdir(parents=True)
                (root / 'build/base/.config').write_text(line + '\n')
                result = subprocess.run(['bash', '-c', f'_ctxr_execmem={flag}; f() {{\n{check}\n}}; f'],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, ok, result.stderr)

    def test_the_aura_recipe_refuses_a_flag_the_pinned_source_disagrees_with(self):
        check = self.step('aura', '  local found=0', '  fi')
        marker = self.step('aura', '  if (( _monitor_free )); then', '  fi')
        cases = {'monitor': (('monitor.c',), 0), 'monitor-free': (('ctxr_exec.c',), 1),
                 'both': (('monitor.c', 'ctxr_exec.c'), 1), 'renamed': (('other.c',), 1)}
        for name, (files, source) in cases.items():
            for flag in (0, 1):
                with self.subTest(name, flag=flag), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    (root / 'aura/src').mkdir(parents=True)
                    for file in files:
                        (root / 'aura/src' / file).write_text('')
                    result = subprocess.run(
                        ['bash', '-c', f'_monitor_free={flag}; f() {{\n{check}\n{marker}\n}}; f'],
                        cwd=root, capture_output=True, text=True,
                        env=dict(os.environ, pkgdir=str(root / 'pkg')))
                    self.assertEqual(result.returncode == 0, flag == source, result.stderr)
                    self.assertEqual((root / 'pkg/usr/share/aura/monitor-free').exists(),
                                     flag == source == 1)

    def test_image_build_writes_the_stage2_in_the_c_locale(self):
        text = (ROOT / 'scripts/build-image').read_text()
        self.assertIn('LC_ALL=C chroot "$mountroot" update-m1n1 /boot/efi/m1n1/boot.bin', text)

    def test_the_tool_and_the_recipe_agree_on_the_marker_path(self):
        for path in (SCRIPT, SHARED):
            self.assertIn('/usr/share/aura/monitor-free', path.read_text())

    def test_image_build_ignores_the_builders_device_tree(self):
        text = (ROOT / 'scripts/build-image').read_text()
        export = text.index('export AURORA_DEVICE_TREE_COMPATIBLE=/nonexistent')
        self.assertLess(export, text.index('chroot "$mountroot"'))

    def test_image_build_adds_the_ctxr_files_after_the_finalizer(self):
        text = (ROOT / 'scripts/build-image').read_text()
        finalize = text.index('finalize-image"')
        ctxr = text.index('prepare-ctxr-stage2.py')
        archive = text.index('-filesystems.tar.zst')
        self.assertLess(finalize, ctxr)
        self.assertLess(ctxr, archive)


    def test_image_build_adds_the_ctxr_files_only_with_the_marker(self):
        text = (ROOT / 'scripts/build-image').read_text()
        check = text.index('if [[ -e $mountroot/usr/share/aura/monitor-free ]]; then monitor_free=true; fi')
        unmount = text.rindex("for path in dev proc sys run boot/efi boot ''")
        guarded = text.index('if $monitor_free; then\n  python3 "$root/scripts/prepare-ctxr-stage2.py"')
        self.assertLess(check, unmount)
        self.assertLess(unmount, guarded)
        self.assertEqual(text.count('prepare-ctxr-stage2.py'), 1)

if __name__ == '__main__':
    unittest.main()
