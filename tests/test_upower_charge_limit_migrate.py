from pathlib import Path
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages/upower-aurora'
SCRIPT = PACKAGE / 'upower-charge-limit-migrate'
LEGACY = 'etc/udev/macsmc-battery.conf'
STATUS = 'var/lib/upower/charging-threshold-status'
RULE = 'etc/udev/rules.d/61-upower-charge-limit.rules'
# fedora-aurora packages/upower-aurora: the same files on both distributions.
FEDORA_BLOBS = {
    'upower-charge-limit-migrate': '78182d4231d490c82cf535d35034013589a1ee68',
    'upower-charge-limit-migrate.service': '74f8054cacc84dca1e9cf28cb69e4990d3247ff0',
}


class MigrationTests(unittest.TestCase):
    """The one-time hand-over of a limit saved by the old macsmc-battery helper."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'root'
        (self.root / 'var/lib/upower').mkdir(parents=True)
        self.calls = Path(self.temporary.name) / 'udevadm.log'
        self.udevadm = Path(self.temporary.name) / 'udevadm'
        self.fake_udevadm(0)

    def tearDown(self):
        self.temporary.cleanup()

    def fake_udevadm(self, status):
        self.udevadm.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\nexit {status}\n')
        self.udevadm.chmod(0o755)

    def write(self, name, text, mtime=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def run_script(self, expected_status=0, **environment):
        env = dict(os.environ, UPOWER_MIGRATE_ROOT=str(self.root), UPOWER_MIGRATE_UDEVADM=str(self.udevadm))
        env.update(environment)
        result = subprocess.run(['sh', str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected_status, result.stderr)
        return result.stderr

    def udev_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def assert_migrated(self):
        self.assertFalse((self.root / LEGACY).exists())

    def test_without_the_old_file_nothing_changes(self):
        self.assertEqual(self.run_script(), '')
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*')),
                         ['var', 'var/lib', 'var/lib/upower'])
        self.assertEqual(self.udev_calls(), [])

    def test_default_limit_turns_upower_on(self):
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=80\n')
        self.run_script()
        status = self.root / STATUS
        # upowerd compares the whole file with "1".
        self.assertEqual(status.read_bytes(), b'1')
        self.assertEqual(status.stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.root / RULE).exists())
        self.assertEqual(self.udev_calls(), [])
        self.assert_migrated()

    def test_other_limit_is_kept_as_charge_limit(self):
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=75\n')
        self.run_script()
        self.assertEqual((self.root / STATUS).read_bytes(), b'1')
        rule = (self.root / RULE).read_text()
        self.assertIn('SUBSYSTEM=="power_supply", KERNEL=="macsmc-battery", ENV{CHARGE_LIMIT}="70,75"\n', rule)
        self.assertEqual((self.root / RULE).stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.udev_calls(), [
            'control --reload',
            'trigger --settle --action=change --subsystem-match=power_supply --sysname-match=macsmc-battery'])
        self.assert_migrated()

    def test_every_saved_limit_below_100(self):
        for limit in range(1, 100):
            with self.subTest(limit=limit):
                (self.root / STATUS).unlink(missing_ok=True)
                (self.root / RULE).unlink(missing_ok=True)
                self.write(LEGACY, f'CHARGE_CONTROL_END_THRESHOLD={limit}\n')
                self.run_script()
                self.assertEqual((self.root / STATUS).read_bytes(), b'1')
                if limit == 80:
                    self.assertFalse((self.root / RULE).exists())
                else:
                    self.assertIn(f'ENV{{CHARGE_LIMIT}}="{max(limit - 5, 0)},{limit}"', (self.root / RULE).read_text())
                self.assert_migrated()

    def test_no_limit_leaves_upower_as_it_is(self):
        for text in ('CHARGE_CONTROL_END_THRESHOLD=100\n', 'CHARGE_CONTROL_END_THRESHOLD=\n', '',
                     'CHARGE_CONTROL_END_THRESHOLD=0\n', 'CHARGE_CONTROL_END_THRESHOLD=101\n',
                     'CHARGE_CONTROL_END_THRESHOLD=080\n', 'CHARGE_CONTROL_END_THRESHOLD=-5\n',
                     'CHARGE_CONTROL_END_THRESHOLD= 80\n', 'CHARGE_CONTROL_END_THRESHOLD=80 \n',
                     'CHARGE_CONTROL_END_THRESHOLD=8O\n', 'OTHER=80\n'):
            with self.subTest(text=text):
                self.write(LEGACY, text)
                self.run_script()
                self.assertFalse((self.root / STATUS).exists())
                self.assertFalse((self.root / RULE).exists())
                self.assert_migrated()

    def test_last_saved_value_wins(self):
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=100\nCHARGE_CONTROL_END_THRESHOLD=80\n')
        self.run_script()
        self.assertEqual((self.root / STATUS).read_bytes(), b'1')

    def test_upower_switched_off_after_the_last_save_stays_off(self):
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=80\n', mtime=1_700_000_000)
        self.write(STATUS, '0', mtime=1_700_000_100)
        self.run_script()
        self.assertEqual((self.root / STATUS).read_bytes(), b'0')
        self.assert_migrated()

    def test_upower_switched_off_before_the_last_save_is_turned_on(self):
        self.write(STATUS, '0', mtime=1_700_000_000)
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=80\n', mtime=1_700_000_100)
        self.run_script()
        self.assertEqual((self.root / STATUS).read_bytes(), b'1')
        self.assert_migrated()

    def test_upower_already_on_is_not_rewritten(self):
        status = self.write(STATUS, '1')
        before = status.stat()
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=80\n')
        self.run_script()
        after = status.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assert_migrated()

    def test_missing_state_directory_is_created(self):
        shutil.rmtree(self.root / 'var')
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=80\n')
        self.run_script()
        self.assertEqual((self.root / STATUS).read_bytes(), b'1')

    def test_second_run_changes_nothing(self):
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=90\n')
        self.run_script()
        files = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
                 for p in self.root.rglob('*') if p.is_file()}
        calls = self.udev_calls()
        self.assertEqual(self.run_script(), '')
        self.assertEqual(files, {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
                                 for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.udev_calls(), calls)

    def test_recreated_legacy_reloads_without_rewriting_matching_files(self):
        # This is a completed migration followed by a new legacy save, not
        # an interruption. Matching files need no rewrite, but udev is notified.
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=90\n')
        self.run_script()
        files = {p: p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        calls = self.udev_calls()
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=90\n')
        self.run_script()
        self.assertEqual(files, {p: p.stat().st_mtime_ns for p in self.root.rglob('*')
                                 if p.is_file() and p.relative_to(self.root).as_posix() != LEGACY})
        self.assertEqual(self.udev_calls(), calls * 2)
        self.assert_migrated()

    def assert_retry_after_interruption(self, command, wrapper, exit_status):
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=90\n')
        bin_dir = Path(self.temporary.name) / 'bin'
        bin_dir.mkdir()
        shim = bin_dir / command
        shim.write_text('#!/bin/sh\n' + wrapper)
        shim.chmod(0o755)
        self.run_script(expected_status=exit_status, PATH=f'{bin_dir}:{os.environ["PATH"]}')
        self.assertEqual((self.root / LEGACY).read_text(), 'CHARGE_CONTROL_END_THRESHOLD=90\n')
        self.assertEqual((self.root / STATUS).read_bytes(), b'1')
        self.assertIn('ENV{CHARGE_LIMIT}="85,90"\n', (self.root / RULE).read_text())
        self.assertEqual(self.udev_calls(), [])
        files = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode)
                 for p in (self.root / STATUS, self.root / RULE)}

        self.run_script()
        self.assert_migrated()
        calls = [
            'control --reload',
            'trigger --settle --action=change --subsystem-match=power_supply --sysname-match=macsmc-battery']
        self.assertEqual(self.udev_calls(), calls)
        self.assertEqual(self.run_script(), '')
        self.assertEqual(self.udev_calls(), calls)
        self.assertEqual(files, {
            p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode) for p in files})

    def test_retry_after_real_rule_rename_notifies_udev(self):
        mv = shlex.quote(shutil.which('mv'))
        self.assert_retry_after_interruption('mv', f'''
{mv} "$@" || exit $?
if [ "$3" = "$UPOWER_MIGRATE_ROOT/{RULE}" ]; then exit 73; fi
''', 73)

    def test_retry_after_failure_before_legacy_removal_notifies_udev(self):
        rm = shlex.quote(shutil.which('rm'))
        self.assert_retry_after_interruption('rm', f'''
if [ "$2" = "$UPOWER_MIGRATE_ROOT/{LEGACY}" ]; then exit 74; fi
exec {rm} "$@"
''', 74)

    def test_old_restore_rule_still_installed_blocks_the_migration(self):
        for directory in ('usr/lib/udev/rules.d', 'etc/udev/rules.d', 'run/udev/rules.d'):
            with self.subTest(directory=directory):
                rule = self.write(f'{directory}/93-macsmc-battery-charge-control.rules', '# old\n')
                self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=80\n')
                self.assertIn('still installed', self.run_script())
                self.assertTrue((self.root / LEGACY).exists())
                self.assertFalse((self.root / STATUS).exists())
                rule.unlink()

    def test_udev_failure_keeps_the_migration(self):
        self.fake_udevadm(1)
        self.write(LEGACY, 'CHARGE_CONTROL_END_THRESHOLD=90\n')
        self.assertIn('applies from the next boot', self.run_script())
        self.assertIn('"85,90"', (self.root / RULE).read_text())
        self.assert_migrated()

    def test_unit_runs_before_upower_only_while_the_old_file_exists(self):
        unit = (PACKAGE / 'upower-charge-limit-migrate.service').read_text()
        self.assertIn('ConditionPathExists=/etc/udev/macsmc-battery.conf\n', unit)
        self.assertIn('Before=upower.service\n', unit)
        self.assertIn('Type=oneshot\n', unit)
        self.assertIn('ExecStart=/usr/libexec/aurora/upower-charge-limit-migrate\n', unit)

    @unittest.skipUnless(shutil.which('shellcheck'), 'shellcheck is not installed')
    def test_script_passes_shellcheck(self):
        subprocess.run(['shellcheck', '-s', 'sh', str(SCRIPT)], check=True)


class PackagingTests(unittest.TestCase):
    def test_upower_aurora_installs_the_migration_before_upowerd(self):
        recipe = (PACKAGE / 'PKGBUILD').read_text()
        names = re.search(r'(?ms)^source=\((.*?)\)', recipe).group(1).split()[1:]
        sums = re.findall(r"'([0-9a-f]{64})'", re.search(r'(?ms)^sha256sums=\((.*?)\)', recipe).group(1))[1:]
        self.assertEqual(names, ['upower-charge-limit-migrate', 'upower-charge-limit-migrate.service'])
        for name, digest in zip(names, sums, strict=True):
            self.assertEqual(hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest(), digest, name)
        self.assertIn('install -Dm755 upower-charge-limit-migrate "$pkgdir/usr/libexec/aurora/upower-charge-limit-migrate"',
                      recipe)
        self.assertIn('install -Dm644 -t "$pkgdir/usr/lib/systemd/system" upower-charge-limit-migrate.service', recipe)
        # A static wants link: the unit runs whenever upower.service starts, also on D-Bus activation.
        self.assertIn('ln -s ../upower-charge-limit-migrate.service "$pkgdir/usr/lib/systemd/system/upower.service.wants/"',
                      recipe)

    def test_the_migration_is_fedoras_byte_for_byte(self):
        for name, blob in FEDORA_BLOBS.items():
            with self.subTest(name):
                data = (PACKAGE / name).read_bytes()
                self.assertEqual(hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest(), blob)

    def test_asahi_scripts_does_not_install_the_old_helper(self):
        recipe = (ROOT / 'packages/asahi-scripts/PKGBUILD').read_text()
        package = recipe.split('package() {', 1)[1].split('\n}', 1)[0]
        install = package.index('make PREFIX=/usr DESTDIR=${pkgdir} install-arch\n')
        self.assertGreater(package.index('make PREFIX=/usr DESTDIR=${pkgdir} uninstall-macsmc-battery\n'), install)
        self.assertNotIn('macsmc-battery-systemd-units', recipe)
        script = (ROOT / 'packages/asahi-scripts/asahi-scripts.install').read_text()
        self.assertIn('vercmp "$2" 20261023-10', script)
        self.assertIn('systemctl stop macsmc-battery-charge-control-end-threshold.path', script)
