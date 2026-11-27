"""The keyring unit checks the keys themselves on every boot (alarm-aurora#245)."""
from pathlib import Path
import subprocess
import unittest

BOOT = Path(__file__).resolve().parents[1]/'packages/aurora-boot'


class KeyringCheckTest(unittest.TestCase):
    def test_unit_does_not_trust_a_marker(self):
        unit = (BOOT/'aurora-alarm-keyring.service').read_text()
        self.assertNotIn('ConditionPathExists', unit)
        self.assertIn('ExecStart=/usr/libexec/aurora/initialize-keyring\n', unit)

    def test_script_checks_master_key_and_trusted_keys(self):
        script = (BOOT/'initialize-keyring').read_text()
        self.assertIn('--list-secret-keys', script)
        self.assertIn('-trusted', script)
        self.assertIn('--import-ownertrust', script)
        # Keys reach the disk before the run counts as done.
        self.assertLess(script.index('sync -f "$gnupg"'), script.index('touch /var/lib/aurora/pacman-keyring-ready'))
        subprocess.run(['bash', '-n', str(BOOT/'initialize-keyring')], check=True)


if __name__ == '__main__':
    unittest.main()
