"""The shared negative checks in scripts/testlib.sh fail when they should."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'scripts/testlib.sh'


class TestlibTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # A pacman double: -Qq lists $PACKAGES; -Q NAME answers for a
        # provider too, as pacman does; PACMAN_FAILS breaks it.
        self.tool('pacman', r'''
[[ -z ${PACMAN_FAILS:-} ]] || { echo 'error: database locked' >&2; exit 1; }
if [[ $1 == -Qq ]]; then printf '%s\n' $PACKAGES; exit 0; fi
for name in $PACKAGES; do [[ $name == "$2" || $name == "$2"-aurora ]] && { echo "$name 1-1"; exit 0; }; done
exit 1
''')
        # chroot ROOT CMD...: run CMD, recording ROOT.
        self.tool('chroot', 'printf "%s\\n" "$1" > "$TEST_DIR/chroot-root"; shift; exec "$@"\n')

    def tool(self, name, body):
        path = self.dir / name
        path.write_text('#!/bin/bash\n' + body)
        path.chmod(0o755)

    def run_checks(self, body, packages='', **env):
        script = f'set -euo pipefail\nsource {LIB}\n{body}\necho REACHED\n'
        environment = dict(os.environ, PATH=f'{self.dir}:{os.environ["PATH"]}',
                           PACKAGES=packages, TEST_DIR=str(self.dir), **env)
        return subprocess.run(['bash', '-c', script], env=environment, cwd=self.dir,
                              capture_output=True, text=True)

    def assertPasses(self, body, **kwargs):
        result = self.run_checks(body, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('REACHED', result.stdout)

    def assertFails(self, body, **kwargs):
        result = self.run_checks(body, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('REACHED', result.stdout)
        return result

    def test_bare_negation_never_fails_under_set_e(self):
        # The reason for the helpers: both lines run on to the end.
        self.assertPasses('! true')
        self.assertPasses('! pacman -Q upower', packages='upower-aurora')

    def test_refute(self):
        self.assertPasses('refute false')
        self.assertIn('unexpected success: true', self.assertFails('refute true').stderr)

    def test_nomatch(self):
        (self.dir / 'ldd.txt').write_text('libc.so.6 => /usr/lib/libc.so.6\n')
        self.assertPasses("nomatch -F 'not found' ldd.txt")
        self.assertPasses("nomatch -x aurora-gl <<< 'flathub'")
        (self.dir / 'ldd.txt').write_text('libLLVM.so.21 => not found\n')
        self.assertIn('unexpected match', self.assertFails("nomatch -F 'not found' ldd.txt").stderr)
        self.assertFails("nomatch -x aurora-gl <<< 'aurora-gl'")
        # A missing file is a failure, not "no match".
        self.assertIn('grep failed (2)', self.assertFails("nomatch -F 'not found' missing.txt").stderr)

    def test_installed_is_exact(self):
        # The replacement provides the stock name: pacman -Q says yes, installed says no.
        self.assertPasses('pacman -Q upower >/dev/null; refute installed upower; installed upower-aurora',
                          packages='upower-aurora glibc')
        self.assertFails('refute installed upower', packages='upower glibc')
        self.assertFails('installed upower', packages='upower-aurora')
        self.assertFails('refute installed libfprint', packages='libfprint fprintd')

    def test_installed_fails_loudly_when_pacman_fails(self):
        result = self.assertFails('refute installed upower', packages='glibc', PACMAN_FAILS='1')
        self.assertIn('cannot list installed packages', result.stderr)

    def test_installed_in_a_chroot(self):
        self.assertPasses('refute installed /mnt upower', packages='upower-aurora')
        self.assertEqual((self.dir / 'chroot-root').read_text(), '/mnt\n')
        self.assertFails('refute installed /mnt upower', packages='upower')


if __name__ == '__main__':
    unittest.main()
