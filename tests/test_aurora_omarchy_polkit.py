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
        self.bin = root / 'bin'
        self.bin.mkdir()
        for name, body in {'pacman': 'printf "aurora-omarchy-polkit 1-1\\nfprintd-aurora 1.94.5-5\\n"', 'vercmp': 'echo 0'}.items():
            tool = self.bin / name
            tool.write_text('#!/bin/sh\n' + body + '\n')
            tool.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], AURORA_POLKIT_PAM=str(self.pam), AURORA_POLKIT_STATE=str(self.state), AURORA_SEP_POLKIT_MARKER=str(self.marker))

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

    def test_upgrade_restores_only_previously_enabled_option(self):
        self.run_cli('--pre-transaction')
        self.run_cli('--post-transaction')
        self.assertEqual(self.pam.read_text(), self.original)
        self.run_cli('--enable')
        self.run_cli('--pre-transaction')
        self.assertEqual(self.pam.read_text(), self.original)
        self.run_cli('--pre-transaction')  # interrupted transaction followed by retry
        self.run_cli('--post-transaction')
        self.assertIn('polkit-password-switch', self.pam.read_text())
        self.assertFalse((self.state / 'pam-restore.json').exists())

    def test_upgrade_does_not_restore_changed_line_or_incompatible_version(self):
        self.run_cli('--enable')
        self.run_cli('--pre-transaction')
        self.pam.write_text(self.original.replace('timeout=10', 'timeout=5'))
        self.run_cli('--post-transaction', success=False)
        self.assertNotIn('polkit-password-switch', self.pam.read_text())
        self.pam.write_text(self.original)
        (self.bin / 'vercmp').write_text('#!/bin/sh\necho -1\n')
        self.run_cli('--post-transaction')
        self.assertEqual(self.pam.read_text(), self.original)
        self.assertFalse((self.state / 'pam-restore.json').exists())

    def test_missing_companion_does_not_restore(self):
        self.run_cli('--enable')
        self.run_cli('--pre-transaction')
        (self.bin / 'pacman').write_text('#!/bin/sh\nexit 1\n')
        self.run_cli('--post-transaction')
        self.assertEqual(self.pam.read_text(), self.original)
        self.assertFalse((self.state / 'pam-restore.json').exists())

    def test_failed_pre_hook_never_schedules_restore(self):
        self.run_cli('--enable')
        self.pam.write_text(self.pam.read_text().replace('timeout=10', 'timeout=5'))
        self.run_cli('--pre-transaction', success=False)
        self.assertFalse((self.state / 'pam-restore.json').exists())

    def test_manual_disable_cancels_pending_restore(self):
        self.run_cli('--enable')
        self.run_cli('--pre-transaction')
        self.run_cli('--disable')
        self.run_cli('--post-transaction')
        self.assertEqual(self.pam.read_text(), self.original)

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
