"""The login screen fingerprint unit only puts a GResource overlay in place
for the login screen's shell. It is ordered before the display manager and
must not order it after the Secure Enclave: aurora-sep-ready takes seconds,
and the login screen would wait for it."""
import configparser
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEP = ROOT / 'packages' / 'aurora-sep'
UNIT = SEP / 'aurora-sep-greeter-fingerprint.service'
# Units that finish only once the enclave is up.
ENCLAVE = {'aurora-sep.service', 'aurora-sep-ready.service', 'fprintd.service',
           'aurora-touchid-boot.service', 'aurora-touchid-setup.service'}


def unit():
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(UNIT.read_text())
    return parser


class GreeterUnit(unittest.TestCase):
    def names(self, key):
        return set(unit()['Unit'].get(key, '').split())

    def test_does_not_wait_for_the_enclave(self):
        for key in ('After', 'Wants', 'Requires', 'BindsTo'):
            with self.subTest(key=key):
                self.assertFalse(self.names(key) & ENCLAVE)

    def test_runs_before_the_login_screen(self):
        self.assertIn('gdm.service', self.names('Before'))
        self.assertEqual(unit()['Install']['WantedBy'].split(), ['gdm.service'])

    def test_does_not_pull_in_a_login_screen_restart(self):
        # The linux tree's unit enables aurora-sep-greeter-refresh.service,
        # which restarts the login screen when Touch ID comes up.
        self.assertNotIn('Also', unit()['Install'])
        self.assertFalse((SEP / 'aurora-sep-greeter-refresh.service').exists())

    def test_provenance_names_the_adaptation(self):
        provenance = json.loads((SEP / 'provenance.json').read_text())
        self.assertIn('aurora-sep-greeter-fingerprint.service', provenance['file_commits'])
        self.assertIn('aurora-sep-greeter-refresh.service', provenance['adaptations'])


if __name__ == '__main__':
    unittest.main()
