import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'packages' / 'aurora-flatpak-gl' / 'aurora-flatpak-gl'
ID = 'org.freedesktop.Platform.GL.aurora'

# A flatpak stand-in that keeps the system installation in files: installed
# refs, pins, remotes and overrides. It never delegates to a real Flatpak.
# A fault can emit partial stdout before failing, as a query may do.
FAKE_FLATPAK = r'''#!/bin/bash
s=$FAKE_FLATPAK_STATE
touch "$s/installed" "$s/remotes" "$s/pins"
cmd=$1; shift
echo "$cmd" >> "$s/calls"
if [ "${FAKE_FLATPAK_FAIL:-}" = "$cmd" ]; then
  [ -z "${FAKE_FLATPAK_PARTIAL:-}" ] || printf '%s\n' "$FAKE_FLATPAK_PARTIAL"
  echo "error: $cmd failed" >&2
  exit 23
fi
args=()
for a in "$@"; do case $a in -*) ;; *) args+=("$a") ;; esac; done
case $cmd in
  remotes) cat "$s/remotes" ;;
  remote-add) echo "${args[-2]}" >> "$s/remotes" ;;
  remote-modify) ;;
  remote-delete) grep -vxF "${args[0]}" "$s/remotes" > "$s/r.tmp"; mv "$s/r.tmp" "$s/remotes" ;;
  list) cat "$s/installed" ;;
  install)
    ref=${args[1]#runtime/}
    grep -qxF "$ref" "$s/installed" || echo "$ref" >> "$s/installed"
    grep -qxF "${args[1]}" "$s/pins" || echo "${args[1]}" >> "$s/pins" ;;
  uninstall) grep -vxF "${args[0]#runtime/}" "$s/installed" > "$s/i.tmp"; mv "$s/i.tmp" "$s/installed" ;;
  pin)
    if [[ " $* " == *" --remove "* ]]; then
      grep -vxF "${args[0]}" "$s/pins" > "$s/p.tmp"; mv "$s/p.tmp" "$s/pins"
    else
      grep -qxF "${args[0]}" "$s/pins" || echo "${args[0]}" >> "$s/pins"
    fi ;;
  override)
    grep -qx '\[Environment\]' "$OVERRIDES" 2>/dev/null || echo '[Environment]' >> "$OVERRIDES"
    for a in "$@"; do case $a in --env=*) grep -qxF "${a#--env=}" "$OVERRIDES" || echo "${a#--env=}" >> "$OVERRIDES" ;; esac; done ;;
esac
'''


class FlatpakGlHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.state = self.tmp / 'state'
        self.state.mkdir()
        bindir = self.tmp / 'bin'
        bindir.mkdir()
        fake = bindir / 'flatpak'
        fake.write_text(FAKE_FLATPAK)
        fake.chmod(0o755)
        self.repo = self.tmp / 'repo'
        (self.repo / 'objects').mkdir(parents=True)
        heads = self.repo / 'refs/heads/runtime' / ID / 'aarch64'
        heads.mkdir(parents=True)
        for branch in ('25.08', '26.08'):
            (heads / branch).write_text('0' * 64 + '\n')
        self.overrides = self.tmp / 'global'
        # Even inherited user/XDG state and temporary files stay in this fixture.
        self.env = {'PATH': f'{bindir}:{os.environ["PATH"]}', 'LC_ALL': 'C',
                    'FAKE_FLATPAK_STATE': str(self.state), 'OVERRIDES': str(self.overrides),
                    'AURORA_FLATPAK_GL_REPO': str(self.repo),
                    'AURORA_FLATPAK_GL_OVERRIDES': str(self.overrides)}
        for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR', 'TMPDIR'):
            directory = self.tmp / key.lower()
            directory.mkdir(mode=0o700)
            self.env[key] = str(directory)

    def run_helper(self, action):
        return subprocess.run(['bash', str(HELPER), action], env=self.env, capture_output=True, text=True)

    def installed(self):
        path = self.state / 'installed'
        return path.read_text().split() if path.exists() else []

    def test_enable_then_disable(self):
        self.assertEqual(self.run_helper('enable').returncode, 0)
        self.assertEqual(self.installed(), [f'{ID}/aarch64/25.08', f'{ID}/aarch64/26.08'])
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.installed(), [])
        self.assertFalse(self.overrides.exists())

    def test_a_failed_pin_is_reported(self):
        # An unpinned GL.aurora is removed by "flatpak uninstall --unused".
        self.env['FAKE_FLATPAK_FAIL'] = 'pin'
        self.assertNotEqual(self.run_helper('enable').returncode, 0)

    def test_a_failed_uninstall_is_reported(self):
        self.run_helper('enable')
        self.env['FAKE_FLATPAK_FAIL'] = 'uninstall'
        self.assertNotEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(len(self.installed()), 2)

    def test_a_missing_pin_is_not_an_error(self):
        # "flatpak pin --remove" fails for a ref that was never pinned.
        self.run_helper('enable')
        self.env['FAKE_FLATPAK_FAIL'] = 'pin'
        self.assertEqual(self.run_helper('disable').returncode, 0)


    def calls(self):
        return (self.state / 'calls').read_text().splitlines()

    def snapshot(self):
        return {name: (self.state / name).read_text() for name in ('installed', 'pins', 'remotes')} | {
            'overrides': self.overrides.read_text() if self.overrides.exists() else None}

    def assert_success(self, action):
        result = self.run_helper(action)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_disable_query_failure_preserves_state_and_retries(self):
        for query, partial in (('list', ''), ('list', f'{ID}/aarch64/25.08'),
                               ('remotes', ''), ('remotes', 'aurora-gl')):
            with self.subTest(query=query, partial=bool(partial)):
                self.assert_success('enable')
                before = self.snapshot()
                offset = len(self.calls())
                self.env.update(FAKE_FLATPAK_FAIL=query, FAKE_FLATPAK_PARTIAL=partial)
                result = self.run_helper('disable')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'error: {query} failed', result.stderr)
                self.assertIn('aurora-flatpak-gl:', result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(set(self.calls()[offset:]) <= {'list', 'remotes'})
                self.env.pop('FAKE_FLATPAK_FAIL')
                self.env.pop('FAKE_FLATPAK_PARTIAL')
                self.assert_success('disable')
                self.assertEqual(self.snapshot(), {'installed': '', 'pins': '', 'remotes': '',
                                                  'overrides': None})

    def test_enable_remote_query_failure_stops_and_retries(self):
        for present in (False, True):
            for partial in ('', 'aurora-gl', 'flathub'):
                with self.subTest(present=present, partial=partial):
                    # Both existing and absent remotes must remain unknown on failure.
                    self.assert_success('enable')
                    if not present:
                        self.assert_success('disable')
                    before = self.snapshot()
                    offset = len(self.calls())
                    self.env.update(FAKE_FLATPAK_FAIL='remotes', FAKE_FLATPAK_PARTIAL=partial)
                    result = self.run_helper('enable')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('error: remotes failed', result.stderr)
                    self.assertIn('aurora-flatpak-gl:', result.stderr)
                    self.assertEqual(self.calls()[offset:], ['remotes'])
                    self.assertEqual(self.snapshot(), before)
                    self.env.pop('FAKE_FLATPAK_FAIL')
                    self.env.pop('FAKE_FLATPAK_PARTIAL')
                    self.assert_success('enable')
                    self.assert_success('disable')

    def test_failed_remote_setup_stops_dependent_work_and_retries(self):
        for command in ('remote-add', 'remote-modify'):
            with self.subTest(command=command):
                self.assert_success('enable')
                self.assert_success('disable')
                if command == 'remote-modify':
                    (self.state / 'remotes').write_text('aurora-gl\n')
                # Keep a custom administrator choice intact even when setup fails.
                original = '[Environment]\nVK_DRIVER_FILES=/admin/custom.json\nOTHER=keep\n'
                self.overrides.write_text(original)
                before = self.snapshot()
                offset = len(self.calls())
                self.env['FAKE_FLATPAK_FAIL'] = command
                result = self.run_helper('enable')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'error: {command} failed', result.stderr)
                self.assertEqual(self.calls()[offset:], ['remotes', command])
                self.assertEqual(self.snapshot(), before)
                self.env.pop('FAKE_FLATPAK_FAIL')
                self.assert_success('enable')
                self.assertEqual(len(self.installed()), 2)
                self.assert_success('disable')
                self.assertEqual(self.overrides.read_text(), original)

    def test_successful_empty_queries_allow_cleanup(self):
        # No installed runtimes is a successful discovery, even with policy to remove.
        self.assert_success('enable')
        (self.state / 'installed').write_text('')
        (self.state / 'pins').write_text('')
        offset = len(self.calls())
        self.assert_success('disable')
        self.assertEqual(self.calls()[offset:], ['list', 'remotes', 'remote-delete'])
        self.assertFalse(self.overrides.exists())
        # Neither runtimes nor a remote is an idempotent success.
        offset = len(self.calls())
        self.assert_success('disable')
        self.assertEqual(self.calls()[offset:], ['list', 'remotes'])

    def test_successful_absent_remote_does_not_prevent_runtime_cleanup(self):
        self.assert_success('enable')
        (self.state / 'remotes').write_text('')
        offset = len(self.calls())
        self.assert_success('disable')
        self.assertNotIn('remote-delete', self.calls()[offset:])
        self.assertEqual(self.installed(), [])
        self.assertEqual((self.state / 'pins').read_text(), '')
        self.assertFalse(self.overrides.exists())

    def test_unrelated_runtime_is_not_removed(self):
        other = 'org.freedesktop.Platform.GL.default/aarch64/25.08'
        (self.state / 'installed').write_text(other + '\n')
        self.assert_success('disable')
        self.assertEqual(self.installed(), [other])
        self.assertEqual(self.calls(), ['list', 'remotes'])

    def test_status_reports_failed_discovery_and_retries(self):
        self.assert_success('enable')
        for partial in ('', f'{ID}/aarch64/25.08'):
            with self.subTest(partial=bool(partial)):
                before = self.snapshot()
                self.env.update(FAKE_FLATPAK_FAIL='list', FAKE_FLATPAK_PARTIAL=partial)
                result = self.run_helper('status')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('error: list failed', result.stderr)
                self.assertIn('aurora-flatpak-gl:', result.stderr)
                self.assertNotIn(f'runtime/{ID}', result.stdout)
                self.assertEqual(self.snapshot(), before)
        self.env.pop('FAKE_FLATPAK_FAIL')
        self.env.pop('FAKE_FLATPAK_PARTIAL')
        self.assertIn(f'runtime/{ID}/aarch64/26.08', self.assert_success('status').stdout)

    def test_status_with_no_installed_runtimes_succeeds(self):
        self.assert_success('status')


if __name__ == '__main__':
    unittest.main()
