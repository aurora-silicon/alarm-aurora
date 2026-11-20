import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'packages' / 'aurora-flatpak-gl' / 'aurora-flatpak-gl'
ID = 'org.freedesktop.Platform.GL.aurora'

# Persist pins independently of installed refs, as Flatpak does. In particular,
# uninstall and remote-delete never erase pins. Captured pin output is indented;
# removal compares exact stored patterns and fails if the pattern is absent.
FAKE_FLATPAK = "#!" + sys.executable + "\n" + r'''import json
import os
from pathlib import Path
import sys

state = Path(os.environ['FAKE_FLATPAK_STATE'])
cmd, *argv = sys.argv[1:]
with (state / 'calls').open('a') as log:
    log.write(json.dumps([cmd, *argv]) + '\n')
args = [arg for arg in argv if not arg.startswith('-')]
op = ('pin-remove' if '--remove' in argv else 'pin-add' if args else 'pin-list') if cmd == 'pin' else cmd
fail = os.environ.get('FAKE_FLATPAK_FAIL', '')
failed = fail in (cmd, op, op + ':' + (args[-1] if args else ''))

def read(name):
    path = state / name
    return path.read_text().splitlines() if path.exists() else []

def write(name, values):
    (state / name).write_text(''.join(value + '\n' for value in sorted(set(values))))

if failed:
    if op == 'pin-list' and os.environ.get('FAKE_FLATPAK_PARTIAL'):
        print(''.join('  ' + pin + '\n' for pin in read('pins')), end='')
    sys.exit('error: ' + op + ' failed')
if cmd == 'remotes':
    print('\n'.join(read('remotes')))
elif cmd == 'remote-add':
    write('remotes', read('remotes') + [args[-2]])
elif cmd == 'remote-delete':
    write('remotes', [r for r in read('remotes') if r != args[0]])
elif cmd == 'list':
    print('\n'.join(read('installed')))
elif cmd == 'install':
    ref = args[1]
    write('installed', read('installed') + [ref.removeprefix('runtime/')])
    # Explicit runtime installs also auto-pin the canonical full ref.
    write('pins', read('pins') + [ref])
elif cmd == 'uninstall':
    write('installed', [r for r in read('installed') if r != args[0].removeprefix('runtime/')])
elif op == 'pin-list':
    print(''.join('  ' + pin + '\n' for pin in read('pins')), end='')
elif op == 'pin-remove':
    if args[0] not in read('pins'):
        sys.exit('error: No current pinned pattern matching ' + args[0])
    write('pins', [pin for pin in read('pins') if pin != args[0]])
elif op == 'pin-add':
    write('pins', read('pins') + [args[0]])
elif cmd == 'override':
    path = Path(os.environ['OVERRIDES'])
    lines = path.read_text().splitlines() if path.exists() else ['[Environment]']
    lines += [arg.removeprefix('--env=') for arg in argv if arg.startswith('--env=')]
    path.write_text('\n'.join(dict.fromkeys(lines)) + '\n')
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
        self.env = dict(os.environ, PATH=f'{bindir}:{os.environ["PATH"]}', FAKE_FLATPAK_STATE=str(self.state),
                        OVERRIDES=str(self.overrides), AURORA_FLATPAK_GL_REPO=str(self.repo),
                        AURORA_FLATPAK_GL_OVERRIDES=str(self.overrides))

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
        # A successful empty enumeration distinguishes absence from an error.
        self.run_helper('enable')
        (self.state / 'pins').write_text('')
        self.assertEqual(self.run_helper('disable').returncode, 0)

    def pins(self):
        path = self.state / 'pins'
        return path.read_text().splitlines() if path.exists() else []

    def calls(self):
        return [json.loads(line) for line in (self.state / 'calls').read_text().splitlines()]

    def seed(self, installed=(), pins=()):
        (self.state / 'installed').write_text(''.join(ref.removeprefix('runtime/') + '\n' for ref in installed))
        (self.state / 'pins').write_text(''.join(pin + '\n' for pin in pins))
        (self.state / 'remotes').write_text('aurora-gl\n')

    def test_failed_install_does_not_add_pin_and_other_ref_succeeds(self):
        first, second = [f'runtime/{ID}/aarch64/{branch}' for branch in ('25.08', '26.08')]
        self.env['FAKE_FLATPAK_FAIL'] = 'install:' + first
        result = self.run_helper('enable')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('install failed', result.stderr)
        self.assertEqual(self.pins(), [second])
        self.assertEqual(self.installed(), [second.removeprefix('runtime/')])
        self.assertNotIn(['pin', '--system', first], self.calls())
        self.assertIn(['pin', '--system', second], self.calls())

    def test_successful_installs_remain_pinned(self):
        self.assertEqual(self.run_helper('enable').returncode, 0)
        self.assertEqual(self.pins(), [f'runtime/{ref}' for ref in self.installed()])

    def test_failed_install_leaves_preexisting_pin_untouched(self):
        ref = f'runtime/{ID}/aarch64/25.08'
        self.seed(pins=[ref])
        self.env['FAKE_FLATPAK_FAIL'] = 'install'
        self.assertNotEqual(self.run_helper('enable').returncode, 0)
        self.assertEqual(self.pins(), [ref])
        self.assertFalse(any(call[0] == 'pin' for call in self.calls()))

    def test_pin_removal_failure_and_retry(self):
        ref = f'runtime/{ID}/aarch64/25.08'
        self.seed(installed=[ref], pins=[ref])
        self.env['FAKE_FLATPAK_FAIL'] = 'pin-remove'
        result = self.run_helper('disable')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pin-remove failed', result.stderr)
        self.assertIn(ref, result.stderr)
        self.assertEqual(self.pins(), [ref])
        self.assertEqual(self.installed(), [ref.removeprefix('runtime/')])
        self.assertFalse(any(call[0] in ('uninstall', 'remote-delete') for call in self.calls()))
        del self.env['FAKE_FLATPAK_FAIL']
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [])
        self.assertEqual(self.installed(), [])
        self.assertEqual(self.run_helper('disable').returncode, 0)

    def test_orphan_pins_survive_failure_then_retry_without_repo(self):
        # Old packaged branch, no deployment, no current packaged repository.
        ref = f'runtime/{ID}/aarch64/24.08'
        self.seed(pins=[ref])
        shutil.rmtree(self.repo)
        self.env['FAKE_FLATPAK_FAIL'] = 'pin-remove'
        self.assertNotEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [ref])
        del self.env['FAKE_FLATPAK_FAIL']
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [])
        self.assertFalse(any(call[0] == 'uninstall' for call in self.calls()))
        self.assertEqual(self.run_helper('disable').returncode, 0)

    def test_orphan_pin_is_cleaned_with_remote_already_absent(self):
        ref = f'runtime/{ID}/aarch64/24.08'
        self.seed(pins=[ref])
        (self.state / 'remotes').write_text('')
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [])

    def test_unrelated_exact_and_wildcard_pins_and_deployments_are_preserved(self):
        owned = f'runtime/{ID}/aarch64/old_branch-1.0'
        unrelated = [f'runtime/{ID}.Extra/aarch64/25.08',
                     'runtime/orgXfreedesktopXPlatformXGLXaurora/aarch64/25.08',
                     f'runtime/{ID}/x86_64/25.08',
                     'runtime/org.example.Runtime/aarch64/25.08']
        patterns = [f'runtime/{ID}/aarch64/*', f'runtime/{ID}/*/25.08',
                    f'runtime/{ID}*/aarch64/25.08', f'{ID}/aarch64/25.08',
                    f'runtime/{ID}/aarch64/', ID, 'runtime/org.freedesktop.Platform.GL.*']
        self.seed(installed=[owned, *unrelated], pins=[owned, *unrelated, *patterns])
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(set(self.pins()), set(unrelated + patterns))
        self.assertEqual(set(self.installed()), {ref.removeprefix('runtime/') for ref in unrelated})

    def test_multiple_refs_partial_pin_failure_is_not_hidden(self):
        first, second = [f'runtime/{ID}/aarch64/{branch}' for branch in ('25.08', '26.08')]
        self.seed(installed=[first, second], pins=[first, second])
        self.env['FAKE_FLATPAK_FAIL'] = 'pin-remove:' + first
        self.assertNotEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [first])
        self.assertEqual(len(self.installed()), 2)
        del self.env['FAKE_FLATPAK_FAIL']
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [])
        self.assertEqual(self.installed(), [])

    def test_pin_enumeration_failure_including_partial_output_stops_cleanup(self):
        ref = f'runtime/{ID}/aarch64/25.08'
        for partial in ('', '1'):
            with self.subTest(partial=partial):
                self.seed(installed=[ref], pins=[ref])
                self.overrides.write_text('[Environment]\nOTHER=keep\n')
                self.env['FAKE_FLATPAK_FAIL'] = 'pin-list'
                self.env['FAKE_FLATPAK_PARTIAL'] = partial
                result = self.run_helper('disable')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pin-list failed', result.stderr)
                self.assertEqual(self.pins(), [ref])
                self.assertEqual(self.installed(), [ref.removeprefix('runtime/')])
                self.assertEqual(self.overrides.read_text(), '[Environment]\nOTHER=keep\n')
                self.assertTrue(all(call[0] == 'pin' and '--remove' not in call for call in self.calls()))

    def test_uninstall_failure_after_unpin_is_retryable(self):
        ref = f'runtime/{ID}/aarch64/25.08'
        self.seed(installed=[ref], pins=[ref])
        self.env['FAKE_FLATPAK_FAIL'] = 'uninstall'
        self.assertNotEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.pins(), [])
        self.assertEqual(self.installed(), [ref.removeprefix('runtime/')])
        del self.env['FAKE_FLATPAK_FAIL']
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertEqual(self.installed(), [])

    def test_absent_pins_do_not_attempt_removal(self):
        self.seed(installed=[f'runtime/{ID}/aarch64/25.08'])
        self.assertEqual(self.run_helper('disable').returncode, 0)
        self.assertFalse(any(call[0] == 'pin' and '--remove' in call for call in self.calls()))
        self.assertEqual(self.run_helper('disable').returncode, 0)


if __name__ == '__main__':
    unittest.main()
