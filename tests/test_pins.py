from pathlib import Path
import json
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PinTests(unittest.TestCase):
    def test_hardware_recipes_match_the_recorded_source_pins(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ['aura', 'uboot-aurora', 'mesa-aurora', 'speakerguardd', 'speakerguardd-v2', 'aurora-audio', 'alsa-ucm-conf-aurora', 'aurora-bless', 'avd-fw', 'libva-v4l2-request-avd', 'upower-aurora', 'omarchy-ane-tools', 'mil-hwx-compiler', 'aurora-camera-denoise', 'aurora-kbd-light', 'aurora-xart', 'aurora-touchid-rearm', 'aurora-fido']:
            self.assertIn(pins[name]['commit'], (ROOT / 'packages' / name / 'PKGBUILD').read_text())
        self.assertIn(pins['kernel-aurora']['commit'], (ROOT / 'packages/linux-aurora/PKGBUILD').read_text())
        firstboot = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()
        self.assertIn(pins['aurora-firstboot']['commit'], firstboot)
        self.assertIn(pins['aurora-firstboot']['sha256'], firstboot)
        self.assertRegex(firstboot, rf"(?m)^pkgver={re.escape(pins['aurora-firstboot']['version'])}$")
    def test_speakerguardd_v2_is_opt_in_beside_the_legacy_stack(self):
        pins = json.loads((ROOT / 'sources.json').read_text())['speakerguardd-v2']
        text = (ROOT / 'packages/speakerguardd-v2/PKGBUILD').read_text()
        self.assertIn(pins['sha256'], text)
        self.assertRegex(text, r"(?m)^pkgname=\('speakerguardd-v2'\)$")
        # Sorts above every retired preview build (RC7 was 1.0.0alpha.1-25).
        self.assertRegex(text, r"(?m)^pkgver=1\.0\.0alpha\.1$")
        self.assertGreater(int(re.search(r"(?m)^pkgrel=(\d+)$", text).group(1)), 25)
        self.assertNotRegex(text, r'(?m)^\s*(conflicts|replaces|provides)=')
        main = text.split('package_speakerguardd-v2() {', 1)[1].split('\n}', 1)[0]
        # The gate in every unit decides; the older daemons carry it the other way round.
        self.assertIn("f'ExecCondition={lx}/speakerguardd-gate v2'", text)
        self.assertIn("f'ExecCondition={lx}/speakerguardd-gate prepare'", text)
        self.assertIn('for u in speakersafetyd speakerguardd; do', main)
        self.assertIn('packaging/session/gate.json', main)
        # verify needs the macOS parity attestation (speakerguardd#114).
        self.assertIn('packaging/session/parity.json', main)
        self.assertNotIn('machines.json', main)
        # Switch-on: the default audio stack pulls v2 and the
        # upgrade tool beside the legacy daemons, and replaces only retired builds.
        audio = (ROOT / 'packages/aurora-audio/PKGBUILD').read_text()
        self.assertIn("'speakersafetyd' 'speakerguardd' 'alsa-utils-aurora'", audio)
        self.assertIn("'speakerguardd-v2>=1.0.0alpha.1-31' 'aurora-speaker-upgrade>=0.1-0.8'", audio)
        self.assertIn("conflicts=('asahi-audio' 'asahi-audio-aurora' 'speakerguardd-v2<=1.0.0alpha.1-25')", audio)
        self.assertIn("replaces=('asahi-audio-aurora' 'speakerguardd-v2<=1.0.0alpha.1-25')", audio)
        up = ROOT / 'packages/aurora-speaker-upgrade'
        self.assertEqual([l for l in (up / '90-aurora-speaker-upgrade.preset').read_text().splitlines()
                          if l and not l.startswith('#')], ['enable aurora-speaker-upgrade.service'])
        self.assertIn('install=aurora-speaker-upgrade.install', (up / 'PKGBUILD').read_text())
        self.assertIn('systemctl --preset-mode=enable-only preset aurora-speaker-upgrade.service',
                      (up / 'aurora-speaker-upgrade.install').read_text())
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
