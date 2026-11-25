"""credentialsd and the patched portal reach only the systems that ask for them."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def top_level(text):
    """The PKGBUILD up to its first function."""
    return text[:re.search(r'^\w+\(\) \{', text, re.M).start()]


def function(text, name):
    return re.search(rf'^{name}\(\) \{{\n(.*?)^\}}', text, re.M | re.S)[1]


class CredentialsdTests(unittest.TestCase):
    def setUp(self):
        self.daemon = (ROOT / 'packages/credentialsd-aurora/PKGBUILD').read_text()
        self.portal = (ROOT / 'packages/xdg-desktop-portal-aurora/PKGBUILD').read_text()

    def test_portal_never_replaces_the_stock_package_on_update(self):
        self.assertNotRegex(self.portal, re.compile(r'^replaces=', re.M))
        self.assertIn('''provides=("xdg-desktop-portal=$pkgver" 'xdg-desktop-portal-credential')''', self.portal)
        self.assertIn("conflicts=('xdg-desktop-portal')", self.portal)

    def test_build_root_needs_no_aurora_package(self):
        # makepkg installs the top-level depends before the build; only
        # xdg-desktop-portal-aurora provides the credential portal.
        self.assertNotIn('xdg-desktop-portal-credential', top_level(self.daemon))
        self.assertIn("depends+=('xdg-desktop-portal-credential')", function(self.daemon, 'package'))
        self.assertNotIn('aurora', re.search(r'^depends=\((.*?)\)', top_level(self.daemon), re.M | re.S)[1])

    def test_daemon_turns_the_experimental_portal_on(self):
        self.assertIn('xdg-desktop-portal.service.d/50-credentialsd.conf', function(self.daemon, 'package'))
        dropin = (ROOT / 'packages/credentialsd-aurora/50-credentialsd.conf').read_text()
        self.assertIn('XDG_DESKTOP_PORTAL_ENABLE_EXPERIMENTAL=credential', dropin)

    def test_desktop_images_install_both_and_minimal_neither(self):
        image = (ROOT / 'scripts/build-image').read_text()
        for profile in ('arch-kde', 'arch-gnome'):
            line = re.search(rf'^  {profile}\) packages\+=\((.*?)\);;', image, re.M)[1].split()
            self.assertIn('xdg-desktop-portal-aurora', line)
            self.assertIn('credentialsd-aurora', line)
            self.assertNotIn('xdg-desktop-portal', line)
        base = re.search(r'^packages=\((.*?)\)', image, re.M | re.S)[1].split()
        self.assertNotIn('credentialsd-aurora', base)
        self.assertNotIn('xdg-desktop-portal-aurora', base)

    def test_agent_registers_as_a_provider(self):
        fido = (ROOT / 'packages/aurora-fido/PKGBUILD').read_text()
        self.assertIn('usr/share/credentialsd/providers/org.aurora.Passkeys.conf', function(fido, 'package'))
        provider = (ROOT / 'packages/aurora-fido/org.aurora.Passkeys.conf').read_text()
        self.assertIn('BusName=org.aurora.Passkeys1', provider)


if __name__ == '__main__':
    unittest.main()
