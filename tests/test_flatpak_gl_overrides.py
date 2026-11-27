"""Exercise override cleanup through the real helper and isolated command faults.

Flatpak is always an inert fixture; injected tools otherwise delegate only to
known local utilities. Permission and file-size cases use real filesystem errors.
"""
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'packages/aurora-flatpak-gl/aurora-flatpak-gl'
GL = '/usr/lib/aarch64-linux-gnu/GL'
OWNED = (
    f'VK_DRIVER_FILES={GL}/vulkan/icd.d/asahi_icd.aarch64.json:{GL}/vulkan/icd.d/lvp_icd.aarch64.json',
    f'__EGL_VENDOR_LIBRARY_FILENAMES={GL}/glvnd/egl_vendor.d/50_mesa.json',
    f'LIBGL_DRIVERS_PATH={GL}/lib/dri',
)
ADMIN = '[Environment]\nVK_DRIVER_FILES=/admin/custom.json\nOTHER=keep\n[Context]\nshared=network;\n'

FAKE_FLATPAK = r'''#!/bin/bash
printf '%s\n' "$*" >> "$TEST_STATE/calls"
case $1 in
  list) cat "$TEST_STATE/installed" ;;
  remotes) cat "$TEST_STATE/remotes" ;;
  uninstall) : > "$TEST_STATE/installed" ;;
  remote-delete) : > "$TEST_STATE/remotes" ;;
  pin) ;;
  *) echo 'unexpected fake flatpak command' >&2; exit 99 ;;
esac
'''

# Fail only the named operation, with the real helper supplying all paths and
# control flow. A partial filter result must never replace the original.
FAULT_TOOL = r'''
import os, pathlib, subprocess, sys
command = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
fault = os.environ.get('TEST_FAULT', '')
target = os.environ['AURORA_FLATPAK_GL_OVERRIDES']
if command == 'mktemp' and fault == 'open':
    result = subprocess.run([REAL_TOOLS[command], *args], capture_output=True, text=True, check=True)
    pathlib.Path(result.stdout.strip()).chmod(0o400)
    print(result.stdout, end='')
    sys.exit(0)
fail = ((command == 'grep' and '-vxF' in args and fault == 'filter')
        or (command == 'grep' and '-qvE' in args and fault in ('inspect', 'inspect-and-cleanup'))
        or (command == 'mktemp' and fault == 'create')
        or (command == 'cp' and fault == 'metadata')
        or (command == 'mv' and fault == 'replace')
        or (command == 'rm' and target in args and fault == 'remove')
        or (command == 'rm' and target not in args and fault in ('cleanup', 'inspect-and-cleanup')))
if fail:
    if command == 'grep' and '-vxF' in args:
        print('[Environment]\nPARTIAL=must-not-commit')
    print('fixture: ' + command + ' ' + fault + ' failed', file=sys.stderr)
    sys.exit(2 if command == 'grep' else 1)
os.execv(REAL_TOOLS[command], [command, *args])
'''


class OverrideCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        self.overrides = self.root / 'global'
        self.original = '[Environment]\n' + '\n'.join(OWNED) + '\n' + ADMIN
        self.overrides.write_text(self.original)
        self.overrides.chmod(0o640)
        os.utime(self.overrides, ns=(1_700_000_000_000_000_000,) * 2)
        (self.state / 'installed').write_text('org.freedesktop.Platform.GL.aurora/aarch64/25.08\n')
        (self.state / 'remotes').write_text('aurora-gl\n')
        (self.bin / 'flatpak').write_text(FAKE_FLATPAK)
        (self.bin / 'flatpak').chmod(0o755)
        tools = {name: shutil.which(name) for name in ('grep', 'mktemp', 'cp', 'mv', 'rm')}
        self.assertTrue(all(tools.values()), tools)
        for name in tools:
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\nREAL_TOOLS = ' + repr(tools) + '\n' + FAULT_TOOL)
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                        TEST_STATE=str(self.state), TEST_FAULT='',
                        AURORA_FLATPAK_GL_REPO=str(self.root / 'repo'),
                        AURORA_FLATPAK_GL_OVERRIDES=str(self.overrides))
        for key in ('HOME', 'TMPDIR', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME',
                    'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR'):
            path = self.root / key.lower()
            path.mkdir()
            self.env[key] = str(path)

    def run_helper(self, fault='', preexec_fn=None):
        return subprocess.run(['bash', str(HELPER), 'disable'],
                              env=dict(self.env, TEST_FAULT=fault),
                              capture_output=True, text=True, preexec_fn=preexec_fn)

    def metadata(self):
        value = self.overrides.stat()
        return (stat.S_IMODE(value.st_mode), value.st_uid, value.st_gid, value.st_mtime_ns)

    def assert_failed_without_commit(self, result, before):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('aurora-flatpak-gl:', result.stderr)
        self.assertEqual(self.overrides.read_text(), self.original)
        self.assertEqual(self.metadata(), before)
        # disable queries the refs and remotes first (#392); nothing past those
        # read-only queries runs until the override cleanup succeeds.
        calls = (self.state / 'calls').read_text().splitlines() if (self.state / 'calls').exists() else []
        self.assertEqual([c.split()[0] for c in calls if c], ['list', 'remotes'][:len(calls)], calls)
        self.assertIn('GL.aurora', (self.state / 'installed').read_text())
        self.assertEqual((self.state / 'remotes').read_text(), 'aurora-gl\n')

    def assert_retry(self, expected=None):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        if expected is None:
            self.assertEqual(self.overrides.read_text(), '[Environment]\n' + ADMIN)
        else:
            self.assertFalse(self.overrides.exists())
        self.assertEqual((self.state / 'installed').read_text(), '')
        self.assertEqual((self.state / 'remotes').read_text(), '')

    def check_fault(self, fault):
        before = self.metadata()
        self.assert_failed_without_commit(self.run_helper(fault), before)
        self.assertFalse(list(self.root.glob('global.*')))
        self.assert_retry()

    def test_filter_failure_preserves_original_and_retries(self):
        self.check_fault('filter')

    def test_content_inspection_failure_is_not_empty(self):
        self.check_fault('inspect')

    def test_temp_creation_failure_preserves_original_and_retries(self):
        self.check_fault('create')

    @unittest.skipIf(os.geteuid() == 0, 'requires unprivileged filesystem permission checks')
    def test_temp_open_failure_is_not_an_empty_filter_result(self):
        self.check_fault('open')

    def test_metadata_failure_preserves_original_and_retries(self):
        self.check_fault('metadata')

    def test_replace_failure_preserves_original_and_retries(self):
        self.check_fault('replace')

    def test_final_removal_failure_preserves_original_and_retries(self):
        self.original = '[Environment]\n' + '\n'.join(OWNED) + '\n'
        self.overrides.write_text(self.original)
        before = self.metadata()
        self.assert_failed_without_commit(self.run_helper('remove'), before)
        self.assertFalse(list(self.root.glob('global.*')))
        self.assert_retry(expected='absent')

    def test_empty_result_temp_cleanup_failure_preserves_original(self):
        self.original = '\n'.join(OWNED) + '\n'
        self.overrides.write_text(self.original)
        before = self.metadata()
        self.assert_failed_without_commit(self.run_helper('cleanup'), before)
        leftovers = list(self.root.glob('global.*'))
        self.assertEqual(len(leftovers), 1)
        self.assertEqual(stat.S_IMODE(leftovers[0].stat().st_mode), 0o600)
        self.assert_retry(expected='absent')
        self.assertTrue(leftovers[0].exists())  # A retry owns only its new temp.

    def test_failed_error_path_temp_cleanup_is_reported(self):
        before = self.metadata()
        result = self.run_helper('inspect-and-cleanup')
        self.assert_failed_without_commit(result, before)
        self.assertIn('fixture: rm inspect-and-cleanup failed', result.stderr)
        self.assertEqual(len(list(self.root.glob('global.*'))), 1)
        self.assert_retry()

    @unittest.skipIf(os.geteuid() == 0, 'requires unprivileged filesystem permission checks')
    def test_unreadable_original_preserved_and_retries(self):
        self.overrides.chmod(0)
        before = self.metadata()
        result = self.run_helper()
        self.assertTrue(self.overrides.exists(), result.stderr)
        self.overrides.chmod(0o640)
        self.assert_failed_without_commit(result, (0o640, *before[1:]))
        self.assertFalse(list(self.root.glob('global.*')))
        self.assert_retry()

    @unittest.skipIf(os.geteuid() == 0, 'requires unprivileged filesystem permission checks')
    def test_unwritable_directory_preserves_original_and_retries(self):
        before = self.metadata()
        self.root.chmod(0o500)
        try:
            result = self.run_helper()
        finally:
            self.root.chmod(0o700)
        self.assert_failed_without_commit(result, before)
        self.assert_retry()

    def test_actual_filter_write_failure_preserves_original_and_retries(self):
        def limit_output_file():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (32, 32))
        before = self.metadata()
        self.assert_failed_without_commit(self.run_helper(preexec_fn=limit_output_file), before)
        self.assertFalse(list(self.root.glob('global.*')))
        self.assert_retry()

    def test_preserves_admin_groups_values_and_metadata(self):
        before = self.metadata()
        self.assert_retry()
        self.assertEqual(self.metadata(), before)

    def test_readonly_original_keeps_restrictive_permissions(self):
        # Replacement needs directory access; the destination mode stays read-only.
        self.overrides.chmod(0o400)
        before = self.metadata()
        self.assert_retry()
        self.assertEqual(self.metadata(), before)

    def test_no_helper_values_preserves_admin_settings(self):
        self.overrides.write_text(ADMIN)
        before = self.metadata()
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.overrides.read_text(), ADMIN)
        self.assertEqual(self.metadata(), before)

    def test_absent_override_does_not_create_temporary_file(self):
        self.overrides.unlink()
        result = self.run_helper('create')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.overrides.exists())
        self.assertFalse(list(self.root.glob('global.*')))

    def test_empty_result_is_valid(self):
        # grep -v returns one when every line is owned; this is not an error.
        self.overrides.write_text('\n'.join(OWNED) + '\n')
        self.assert_retry(expected='absent')
        self.assertFalse(list(self.root.glob('global.*')))

    def test_empty_groups_only_are_removed(self):
        self.overrides.write_text('[Environment]\n\n[Context]\n \t\n')
        self.assert_retry(expected='absent')

    def test_unrelated_predictable_temp_is_untouched(self):
        unrelated = self.root / 'global.tmp'
        unrelated.write_text('unrelated administrator file\n')
        unrelated.chmod(0o600)
        # Reading the file may bump atime; compare what a rewrite would change.
        def identity(st): return (st.st_ino, st.st_size, st.st_mode, st.st_mtime_ns)
        before = identity(unrelated.stat())
        self.assert_retry()
        self.assertTrue(unrelated.exists())
        self.assertEqual(unrelated.read_text(), 'unrelated administrator file\n')
        self.assertEqual(identity(unrelated.stat()), before)


if __name__ == '__main__':
    unittest.main()
