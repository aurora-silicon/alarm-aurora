"""aurora-secboot ships the shared UKI pipeline with the mkinitcpio hook."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKGBUILD = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()


class SecbootPackageTests(unittest.TestCase):
    def package(self):
        return PKGBUILD.split('package_aurora-secboot() {', 1)[1].split('\n}', 1)[0]

    def test_split_package_is_built(self):
        self.assertRegex(PKGBUILD, r'(?m)^pkgname=\(.*\baurora-secboot\b.*\)$')

    def test_depends_on_the_signing_tools(self):
        depends = re.search(r"depends=\(([^)]*)\)", self.package()).group(1).split()
        for name in ('python', 'systemd', 'systemd-ukify', 'sbsigntools', 'openssl'):
            self.assertIn(f"'{name}'", depends)

    def test_installs_the_cli_and_the_mkinitcpio_hook(self):
        body = self.package()
        self.assertIn('make -C "aurora-platform-$_commit" install-secboot install-secboot-mkinitcpio', body)
        self.assertIn("backup=('etc/aurora/secboot.conf')", body)
        self.assertIn('enable aurora-secboot-adopt.service', body)

    def test_same_source_as_the_firstboot_pin(self):
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-firstboot']
        self.assertIn(f"_commit={pin['commit']}", PKGBUILD)

    def test_nothing_shipped_carries_lab_settings(self):
        for lab in ('debug_shell', 'panic=', 'watchdog_sec'):
            self.assertNotIn(lab, PKGBUILD)


if __name__ == '__main__':
    unittest.main()
