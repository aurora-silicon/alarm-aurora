from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'packages/aurora-omarchy-polkit/aurora-polkit-pam'

class PamSwitchLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pam = root / 'polkit-1'
        self.marker = root / 'sha256'
        self.state = root / 'state'
        self.original = 'auth sufficient pam_fprintd.so timeout=10\nauth required pam_unix.so\n'
        self.pam.write_text(self.original)
        self.env = dict(os.environ, AURORA_POLKIT_PAM=str(self.pam), AURORA_POLKIT_STATE=str(self.state), AURORA_SEP_POLKIT_MARKER=str(self.marker))

    def run_cli(self, action, success=True):
        p = subprocess.run([str(SCRIPT), action], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode == 0, success, p.stderr)

    def test_owned_checksum_and_round_trip(self):
        self.marker.write_text(hashlib.sha256(self.pam.read_bytes()).hexdigest() + '\n')
        self.run_cli('--enable')
        self.assertIn('pam_fprintd.so timeout=10 polkit-password-switch\n', self.pam.read_text())
        self.assertEqual(self.marker.read_text().strip(), hashlib.sha256(self.pam.read_bytes()).hexdigest())
        self.run_cli('--disable')
        self.assertEqual(self.pam.read_text(), self.original)
        self.assertEqual(self.marker.read_text().strip(), hashlib.sha256(self.pam.read_bytes()).hexdigest())
        self.run_cli('--disable')

    def test_unrelated_edit_is_preserved_and_ownership_not_claimed(self):
        self.marker.write_text(hashlib.sha256(self.pam.read_bytes()).hexdigest() + '\n')
        self.run_cli('--enable')
        marker = self.marker.read_text()
        self.pam.write_text(self.pam.read_text() + '# administrator edit\n')
        self.run_cli('--disable')
        self.assertEqual(self.pam.read_text(), self.original + '# administrator edit\n')
        self.assertEqual(self.marker.read_text(), marker)

    def test_changed_managed_line_blocks_removal(self):
        self.run_cli('--enable')
        self.pam.write_text(self.pam.read_text().replace('timeout=10', 'timeout=5'))
        saved = self.pam.read_text()
        self.run_cli('--disable', success=False)
        self.assertEqual(self.pam.read_text(), saved)
        self.assertTrue((self.state / 'pam-edit.json').exists())

    def test_ambiguous_or_unowned_configuration_is_not_changed(self):
        self.pam.write_text(self.original + 'auth sufficient pam_fprintd.so\n')
        self.run_cli('--enable', success=False)
        self.assertNotIn('polkit-password-switch', self.pam.read_text())
        self.pam.write_text(self.original.replace('timeout=10', 'polkit-password-switch'))
        self.run_cli('--enable', success=False)
        self.run_cli('--disable')
        self.assertIn('polkit-password-switch', self.pam.read_text())

if __name__ == '__main__':
    unittest.main()
