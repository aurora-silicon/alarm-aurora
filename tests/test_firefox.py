"""Firefox: Arch Linux ARM's recipe with the RDD V4L2 Request patch, rebuilt per update."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages' / 'firefox'
_spec = importlib.util.spec_from_file_location('importer', ROOT / 'scripts/import-alarm-firefox.py')
importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer)

ALARM = """\
pkgname=firefox
pkgver=161.0
pkgrel=2
arch=(x86_64)
source=(
  https://archive.mozilla.org/pub/firefox/releases/$pkgver/source/firefox-$pkgver.source.tar.xz{,.asc}
  $pkgname.desktop
)
validpgpkeys=(
  # Mozilla Software Releases <release@mozilla.com>
  14F26682D0916CDD81E37B6D61B7B526D98F0353
)
sha256sums=('aa'
            'SKIP'
            'bb')
b2sums=('cc'
        'SKIP'
        'dd')
_google_api_key=AIzaSyFAKE
prepare() {
  cat >.mozconfig <<END
ac_add_options --with-google-location-service-api-keyfile=${PWD@Q}/google-api-key
ac_add_options --with-google-safebrowsing-api-keyfile=${PWD@Q}/google-api-key
ac_add_options --with-system-nss
END
}
package() {
  install -Dvm644 /dev/stdin "$appdir/browser/defaults/preferences/vendor.js" <<END
pref("browser.gnome-search-provider.enabled", true);
END
}
"""
PATCHES = {'rdd-v4l2-request.patch': b'patch', **{name: name.encode() for name in importer.WEBAUTHN_PORTAL}}


class FirefoxRecipeTests(unittest.TestCase):
    def test_pkgbuild_edit(self):
        text = importer.edit_pkgbuild(ALARM, 'a' * 40, PATCHES)
        self.assertTrue(text.startswith('# aurora-builder: heavy\n'))
        self.assertIn('\npkgrel=2.3\n', text)
        self.assertIn('\narch=(aarch64)\n', text)
        self.assertIn('\n_google_api_key=\n', text)
        self.assertNotIn('api-keyfile', text)
        self.assertNotIn('validpgpkeys', text)
        self.assertNotIn('SKIP', text)
        self.assertIn('.source.tar.xz\n', text)
        self.assertIn('  rdd-v4l2-request.patch\n  # Aurora: WebAuthn through the credential portal', text)
        self.assertIn(f'  {importer.WEBAUTHN_PORTAL[-1]}\n)', text)
        self.assertRegex(text, r"sha256sums=\('aa'\n\s+'bb'(\n\s+'[0-9a-f]{64}'){8}\)")
        self.assertRegex(text, r"b2sums=\('cc'\n\s+'dd'(\n\s+'[0-9a-f]{128}'){8}\)")
        self.assertIn('pref("security.webauthn.use-xdg-desktop-portal", 1);\n', text)
        self.assertIn('pref("security.webauthn.use-xdg-desktop-portal.security-keys", false);\n', text)

    def test_pkgbuild_edit_refuses_an_unknown_recipe(self):
        for old in ('pkgrel=2\n', '_google_api_key=AIzaSyFAKE\n', "            'SKIP'\n"):
            with self.subTest(removed=old), self.assertRaises(SystemExit):
                importer.edit_pkgbuild(ALARM.replace(old, ''), 'a' * 40, PATCHES)

    def test_imported_recipe(self):
        text = (PACKAGE / 'PKGBUILD').read_text()
        self.assertTrue(text.startswith('# aurora-builder: heavy\n'))
        self.assertRegex(text, r'(?m)^pkgrel=\d+\.\d+$')
        self.assertRegex(text, r'(?m)^_google_api_key=$')
        self.assertIn('  rdd-v4l2-request.patch\n', text)
        for name in importer.WEBAUTHN_PORTAL:
            self.assertIn(f'  {name}\n', text)
            self.assertTrue((PACKAGE / name).is_file(), name)
        self.assertNotRegex(text, r'AIza')

    def test_seccomp_admits_exactly_four_media_ioctls(self):
        patch = (PACKAGE / 'rdd-v4l2-request.patch').read_text()
        added = ''.join(line[1:] for line in patch.splitlines(True)
                        if line.startswith('+') and not line.startswith('+++'))
        rule = re.search(r'\.ElseIf\(AnyOf\((.*?)\),\s*Allow\(\)\)', added, re.S)
        self.assertEqual(re.findall(r'request == (\w+)', rule[1]),
                         ['MEDIA_IOC_G_TOPOLOGY', 'MEDIA_IOC_REQUEST_ALLOC',
                          'MEDIA_REQUEST_IOC_QUEUE', 'MEDIA_REQUEST_IOC_REINIT'])
        self.assertIn('aM2mDevices.Contains(', patch)

    def test_patch_matches_the_fedora_and_nixos_copy(self):
        # Same bytes as fedora-aurora packages/firefox/rdd-v4l2-request.patch.
        self.assertTrue((PACKAGE / 'rdd-v4l2-request.patch').read_text().startswith('From '))


if __name__ == '__main__':
    unittest.main()
