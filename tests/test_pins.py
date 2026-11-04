from pathlib import Path
import json
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PinTests(unittest.TestCase):
    def test_hardware_recipes_match_the_recorded_source_pins(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ['aura', 'uboot-aurora', 'mesa-aurora', 'speakerguardd', 'speakerguardd-v2', 'aurora-audio', 'alsa-ucm-conf-aurora', 'aurora-bless', 'avd-fw', 'upower-aurora', 'omarchy-ane-tools', 'mil-hwx-compiler', 'aurora-camera-denoise']:
            self.assertIn(pins[name]['commit'], (ROOT / 'packages' / name / 'PKGBUILD').read_text())
        self.assertIn(pins['kernel-aurora']['commit'], (ROOT / 'packages/linux-aurora/PKGBUILD').read_text())
        firstboot = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()
        self.assertIn(pins['aurora-firstboot']['commit'], firstboot)
        self.assertIn(pins['aurora-firstboot']['sha256'], firstboot)
        self.assertRegex(firstboot, rf"(?m)^pkgver={re.escape(pins['aurora-firstboot']['version'])}$")
    def test_speakerguardd_v2_is_parallel_and_opt_in(self):
        pins = json.loads((ROOT / 'sources.json').read_text())['speakerguardd-v2']
        text = (ROOT / 'packages/speakerguardd-v2/PKGBUILD').read_text()
        self.assertIn(pins['sha256'], text)
        main = text.split('package_speakerguardd-v2() {', 1)[1].split('\n}', 1)[0]
        optin = text.split('package_speakerguardd-v2-replace-legacy() {', 1)[1].split('\n}', 1)[0]
        # The preview installs beside the 0.1 daemon and speakersafetyd.
        self.assertNotRegex(main, r'(?m)^\s*(conflicts|replaces|provides)=')
        self.assertIn('/usr/lib/speakerguardd-v2/speakerguardd', main)
        self.assertIn('/usr/lib/lv2/sgv2.lv2', main)
        # Only the clearly named opt-in conflicts. pacman takes a package by its
        # exact name before a provider, so its provides never pull it in, and
        # it has no replaces=, so -Syu never swaps a machine over.
        self.assertRegex(optin, r"(?m)^\s*conflicts=\('speakerguardd' 'speakersafetyd'\)$")
        self.assertNotRegex(text, r'(?m)^\s*replaces=')
        self.assertIn('multi-user.target.wants/speakerguardd-v2.service', optin)
    def test_base_image_is_signed_and_hash_pinned(self):
        lock = json.loads((ROOT / 'images/base.json').read_text())
        self.assertRegex(lock['sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(lock['signing_fingerprint'], r'^[0-9A-F]{40}$')
        self.assertTrue((ROOT / 'keys/archlinuxarm-build-system.asc').is_file())
if __name__ == '__main__': unittest.main()
