from pathlib import Path
import json
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PinTests(unittest.TestCase):
    def test_hardware_recipes_match_the_recorded_source_pins(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ['aura', 'uboot-aurora', 'mesa-aurora', 'speakerguardd', 'speakerguardd-v2', 'aurora-audio', 'alsa-ucm-conf-aurora', 'aurora-bless', 'avd-fw', 'libva-v4l2-request-avd', 'upower-aurora', 'omarchy-ane-tools', 'mil-hwx-compiler', 'aurora-camera-denoise', 'aurora-kbd-light']:
            self.assertIn(pins[name]['commit'], (ROOT / 'packages' / name / 'PKGBUILD').read_text())
        self.assertIn(pins['kernel-aurora']['commit'], (ROOT / 'packages/linux-aurora/PKGBUILD').read_text())
        firstboot = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()
        self.assertIn(pins['aurora-firstboot']['commit'], firstboot)
        self.assertIn(pins['aurora-firstboot']['sha256'], firstboot)
        self.assertRegex(firstboot, rf"(?m)^pkgver={re.escape(pins['aurora-firstboot']['version'])}$")
    def test_speakerguardd_v2_installs_everywhere_gated_by_board(self):
        pins = json.loads((ROOT / 'sources.json').read_text())['speakerguardd-v2']
        text = (ROOT / 'packages/speakerguardd-v2/PKGBUILD').read_text()
        self.assertIn(pins['sha256'], text)
        self.assertRegex(text, r"(?m)^pkgname=\('speakerguardd-v2'\)$")
        main = text.split('package_speakerguardd-v2() {', 1)[1].split('\n}', 1)[0]
        # Beside the 0.1 daemon and speakersafetyd: nothing conflicts or replaces.
        self.assertNotRegex(text, r'(?m)^\s*(conflicts|replaces|provides)=')
        self.assertIn('/usr/lib/speakerguardd-v2', main)
        self.assertIn('/usr/lib/lv2/sgv2.lv2', main)
        # Enabled by the package; the gate in every unit decides.
        self.assertIn('multi-user.target.wants', main)
        self.assertIn('pipewire.service.wants', main)
        for u in ['speakerguardd-v2-provision.service', 'speakerguardd-v2-seat.path', 'speakerguardd-v2-graph.service']:
            self.assertIn(u, main)
        self.assertIn("'Requires=speakerguardd-v2-provision.service speakerguardd-v2-selfcheck.service'", text)
        self.assertIn("f'ExecCondition={lx}/speakerguardd-gate v2'", text)
        # The older daemons carry the same gate, the other way round.
        self.assertIn('for u in speakersafetyd speakerguardd; do', main)
        self.assertIn('60-speakerguardd-v2-gate.conf', main)
        # The gate and its data are upstream's: no distribution copy.
        self.assertFalse((ROOT / 'packages/speakerguardd-v2/speakerguardd-v2-gate').exists())
        self.assertIn('packaging/session/gate.json', main)
        # Every per-board value is derived on the Mac (wiring.py): no machine table.
        self.assertNotIn('machines.json', main)
        self.assertIn('packaging/session/wiring.py', main)
        self.assertIn('python -I packaging/session/test_provision.py', text)
        audio = (ROOT / 'packages/aurora-audio/PKGBUILD').read_text()
        self.assertIn("'speakersafetyd' 'speakerguardd' 'speakerguardd-v2'", audio)
    def test_base_image_is_signed_and_hash_pinned(self):
        lock = json.loads((ROOT / 'images/base.json').read_text())
        self.assertRegex(lock['sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(lock['signing_fingerprint'], r'^[0-9A-F]{40}$')
        self.assertTrue((ROOT / 'keys/archlinuxarm-build-system.asc').is_file())
if __name__ == '__main__': unittest.main()
