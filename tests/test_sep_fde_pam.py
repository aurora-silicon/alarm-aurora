from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packages/aurora-sep-luks/sep-fde-pam'
# pambase's system-auth.
SYSTEM_AUTH = ('#%PAM-1.0\n\nauth       required                    pam_faillock.so      preauth\n'
               '-auth      [success=2 default=ignore]  pam_systemd_home.so\n'
               'auth       [success=1 default=bad]     pam_unix.so          try_first_pass nullok\n'
               'auth       [default=die]               pam_faillock.so      authfail\n'
               'auth       optional                    pam_permit.so\n'
               'auth       required                    pam_env.so\n'
               'auth       required                    pam_faillock.so      authsucc\n'
               '\n-account   [success=1 default=ignore]  pam_systemd_home.so\n'
               'account    required                    pam_unix.so\n'
               'account    optional                    pam_permit.so\n'
               'account    required                    pam_time.so\n'
               '\n-password  [success=1 default=ignore]  pam_systemd_home.so\n'
               'password   required                    pam_unix.so          try_first_pass nullok shadow\n'
               'password   optional                    pam_permit.so\n'
               '\n-session   optional                    pam_systemd_home.so\n'
               'session    required                    pam_limits.so\n'
               'session    required                    pam_unix.so\n'
               'session    optional                    pam_permit.so\n')
UNIX = 'password   required                    pam_unix.so          try_first_pass nullok shadow\n'
WIRED = ('# Disk password (aurora-sep-luks): follows a password pam_unix changed.\n'
         'password   [success=ok default=2]      pam_unix.so          try_first_pass nullok shadow\n'
         '-password  optional                    pam_aurora_sep_fde.so\n'
         'password   sufficient                  pam_permit.so\n'
         'password   required                    pam_deny.so\n')


class SepFdePamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.pamd, self.state = base / 'etc/pam.d', base / 'state'
        self.pamd.mkdir(parents=True)
        (self.pamd / 'system-auth').write_text(SYSTEM_AUTH)

    def tearDown(self):
        self.temporary.cleanup()

    def run_script(self, *arguments):
        env = dict(os.environ, AURORA_PAM_DIR=str(self.pamd), AURORA_SEP_STATE_DIR=str(self.state))
        result = subprocess.run(['sh', str(SCRIPT), *arguments], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result

    def text(self):
        return (self.pamd / 'system-auth').read_text()

    def test_disk_password_follows_a_pam_unix_change(self):
        self.run_script()
        self.assertEqual(self.text(), SYSTEM_AUTH.replace(UNIX, WIRED))
        lines = [l for l in self.text().splitlines() if l.startswith(('password', '-password'))]
        # pam_unix's failure jumps over the module and pam_permit onto pam_deny.
        self.assertEqual(lines[1].split()[1:4], ['[success=ok', 'default=2]', 'pam_unix.so'])
        self.assertTrue(lines[2].endswith('pam_aurora_sep_fde.so'))
        self.assertTrue(lines[4].endswith('pam_deny.so'))
        # systemd-homed's success skips exactly pam_unix and lands on the module.
        self.assertEqual(lines[0].split()[1], '[success=1')

    def test_running_again_changes_nothing(self):
        self.run_script()
        before = self.text()
        self.run_script()
        self.assertEqual(before, self.text())

    def test_remove_restores_the_original(self):
        self.run_script()
        (self.pamd / 'system-auth').write_text(self.text().replace(
            'session    required                    pam_limits.so\n',
            'session    required                    pam_limits.so\n# mine\n'))
        self.run_script('--remove')
        self.assertEqual(self.text(), SYSTEM_AUTH.replace('pam_limits.so\n', 'pam_limits.so\n# mine\n'))
        self.assertFalse((self.state / 'pam-system-auth-fde').exists())

    def test_an_owner_s_removal_is_kept(self):
        self.run_script()
        (self.pamd / 'system-auth').write_text(SYSTEM_AUTH)
        self.run_script()
        self.assertEqual(self.text(), SYSTEM_AUTH)

    def test_an_owner_s_own_line_is_left_alone(self):
        own = SYSTEM_AUTH.replace(UNIX, UNIX + 'password   optional   pam_aurora_sep_fde.so debug\n')
        (self.pamd / 'system-auth').write_text(own)
        self.run_script()
        self.assertEqual(self.text(), own)
        self.run_script('--remove')
        self.assertEqual(self.text(), own)

    def test_a_changed_pam_unix_line_is_left_alone(self):
        other = SYSTEM_AUTH.replace('password   required ', 'password   requisite')
        (self.pamd / 'system-auth').write_text(other)
        result = self.run_script()
        self.assertEqual(self.text(), other)
        self.assertIn('left as it is', result.stdout)
        self.assertFalse((self.state / 'pam-system-auth-fde').exists())


if __name__ == '__main__':
    unittest.main()
