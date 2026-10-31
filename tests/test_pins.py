from pathlib import Path
import json
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PinTests(unittest.TestCase):
    def test_hardware_recipes_match_the_recorded_source_pins(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ['aura', 'uboot-aurora', 'mesa-aurora', 'speakerguardd', 'aurora-audio', 'alsa-ucm-conf-aurora', 'aurora-bless', 'avd-fw', 'upower-aurora', 'aurora-camera-denoise']:
            self.assertIn(pins[name]['commit'], (ROOT / 'packages' / name / 'PKGBUILD').read_text())
        self.assertIn(pins['kernel-aurora']['commit'], (ROOT / 'packages/linux-aurora/PKGBUILD').read_text())
        firstboot = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()
        self.assertIn(pins['aurora-firstboot']['commit'], firstboot)
        self.assertIn(pins['aurora-firstboot']['sha256'], firstboot)
        self.assertRegex(firstboot, rf"(?m)^pkgver={re.escape(pins['aurora-firstboot']['version'])}$")
    def test_base_image_is_signed_and_hash_pinned(self):
        lock = json.loads((ROOT / 'images/base.json').read_text())
        self.assertRegex(lock['sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(lock['signing_fingerprint'], r'^[0-9A-F]{40}$')
        self.assertTrue((ROOT / 'keys/archlinuxarm-build-system.asc').is_file())
if __name__ == '__main__': unittest.main()
