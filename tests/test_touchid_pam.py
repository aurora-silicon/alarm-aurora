from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packages/aurora-sep/touchid-pam'
LINE = '-auth      sufficient   pam_fprintd.so\n'
COMMENT = '# Touch ID (aurora-sep): a fingerprint, or else the password.\n'
SUDO = ('#%PAM-1.0\nauth\t\tinclude\t\tsystem-auth\naccount\t\tinclude\t\tsystem-auth\n'
        'session\t\tinclude\t\tsystem-auth\nsession\t\toptional\tpam_systemd.so class=none\n')
POLKIT = ('#%PAM-1.0\n\nauth       include      system-auth\naccount    include      system-auth\n'
          'password   include      system-auth\nsession    include      system-auth\n')


class TouchIdPamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.pamd, self.vendor, self.state = base / 'etc/pam.d', base / 'usr/lib/pam.d', base / 'state'
        self.pamd.mkdir(parents=True)
        self.vendor.mkdir(parents=True)
        (self.pamd / 'sudo').write_text(SUDO)
        (self.vendor / 'polkit-1').write_text(POLKIT)

    def tearDown(self):
        self.temporary.cleanup()

    def run_script(self, *arguments):
        env = dict(os.environ, AURORA_PAM_DIR=str(self.pamd), AURORA_PAM_VENDOR_DIR=str(self.vendor),
                   AURORA_SEP_STATE_DIR=str(self.state))
        result = subprocess.run(['sh', str(SCRIPT), *arguments], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result

    def test_sufficient_fingerprint_goes_in_front_of_sudo_and_polkit(self):
        self.run_script()
        self.assertEqual((self.pamd / 'sudo').read_text(), SUDO.replace('auth\t\tinclude', COMMENT + LINE + 'auth\t\tinclude', 1))
        self.assertEqual((self.pamd / 'polkit-1').read_text(),
                         POLKIT.replace('auth       include', COMMENT + LINE + 'auth       include', 1))
        self.assertEqual((self.vendor / 'polkit-1').read_text(), POLKIT)

    def test_running_again_changes_nothing(self):
        self.run_script()
        before = ((self.pamd / 'sudo').read_text(), (self.pamd / 'polkit-1').read_text())
        self.run_script()
        self.assertEqual(before, ((self.pamd / 'sudo').read_text(), (self.pamd / 'polkit-1').read_text()))

    def test_an_owner_s_removal_or_edit_is_kept(self):
        self.run_script()
        (self.pamd / 'sudo').write_text(SUDO)
        (self.pamd / 'polkit-1').write_text(POLKIT + '# mine\n')
        (self.vendor / 'polkit-1').write_text(POLKIT + 'auth optional pam_permit.so\n')
        self.run_script()
        self.assertEqual((self.pamd / 'sudo').read_text(), SUDO)
        self.assertEqual((self.pamd / 'polkit-1').read_text(), POLKIT + '# mine\n')
        (self.pamd / 'polkit-1').unlink()
        self.run_script()
        self.assertFalse((self.pamd / 'polkit-1').exists())

    def test_polkit_s_own_changes_are_followed(self):
        self.run_script()
        (self.vendor / 'polkit-1').write_text(POLKIT.replace('system-auth', 'system-login'))
        self.run_script()
        self.assertIn('auth       include      system-login', (self.pamd / 'polkit-1').read_text())
        self.assertIn(LINE, (self.pamd / 'polkit-1').read_text())

    def test_existing_fingerprint_lines_are_not_doubled(self):
        (self.pamd / 'sudo').write_text('auth sufficient pam_fprintd.so\n' + SUDO)
        (self.pamd / 'polkit-1').write_text('auth sufficient pam_fprintd.so\n' + POLKIT)
        self.run_script()
        self.assertEqual((self.pamd / 'sudo').read_text().count('pam_fprintd.so'), 1)
        self.assertEqual((self.pamd / 'polkit-1').read_text().count('pam_fprintd.so'), 1)

    def test_remove_restores_what_was_there(self):
        self.run_script()
        self.run_script('--remove')
        self.assertEqual((self.pamd / 'sudo').read_text(), SUDO)
        self.assertFalse((self.pamd / 'polkit-1').exists())


if __name__ == '__main__':
    unittest.main()
