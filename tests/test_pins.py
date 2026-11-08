from pathlib import Path
import json
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PinTests(unittest.TestCase):
    def test_hardware_recipes_match_the_recorded_source_pins(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ['aura', 'uboot-aurora', 'mesa-aurora', 'speakerguardd', 'aurora-audio', 'alsa-ucm-conf-aurora', 'aurora-bless', 'avd-fw', 'libva-v4l2-request-avd', 'upower-aurora', 'omarchy-ane-tools', 'mil-hwx-compiler', 'aurora-camera-denoise', 'aurora-kbd-light', 'aurora-xart', 'aurora-touchid-rearm', 'aurora-fido']:
            self.assertIn(pins[name]['commit'], (ROOT / 'packages' / name / 'PKGBUILD').read_text())
        self.assertIn(pins['kernel-aurora']['commit'], (ROOT / 'packages/linux-aurora/PKGBUILD').read_text())
        firstboot = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()
        self.assertIn(pins['aurora-firstboot']['commit'], firstboot)
        self.assertIn(pins['aurora-firstboot']['sha256'], firstboot)
        self.assertRegex(firstboot, rf"(?m)^pkgver={re.escape(pins['aurora-firstboot']['version'])}$")
    def test_aurora_sep_ships_the_touch_id_reset(self):
        sep = ROOT / 'packages/aurora-sep'
        self.assertIn("'aurora-xart')", (sep / 'PKGBUILD').read_text())
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-xart']
        text = (ROOT / 'packages/aurora-xart/PKGBUILD').read_text()
        self.assertIn(pin['sha256'], text)
        self.assertRegex(text, rf"(?m)^pkgver={re.escape(pin['version'])}$")
        self.assertIn('make -C "aurora-xart-$_commit" check', text)
        # The installer script is not shipped here; the packaged tool is.
        for doc in ('README.md', 'XART-SAFETY.md'):
            body = (sep / doc).read_text()
            self.assertNotIn('install-aurora-sep.sh --reset-touchid', body)
            self.assertIn('aurora-xart reset-touchid', body)
    def test_base_image_is_signed_and_hash_pinned(self):
        lock = json.loads((ROOT / 'images/base.json').read_text())
        self.assertRegex(lock['sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(lock['signing_fingerprint'], r'^[0-9A-F]{40}$')
        self.assertTrue((ROOT / 'keys/archlinuxarm-build-system.asc').is_file())
if __name__ == '__main__': unittest.main()
