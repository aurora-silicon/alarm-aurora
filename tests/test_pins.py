from pathlib import Path
import json
import re
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True  # scripts/ is scanned with bash -n in CI
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib  # noqa: E402
class PinTests(unittest.TestCase):
    def test_hardware_recipes_match_the_recorded_source_pins(self):
        pins = json.loads((ROOT / 'sources.json').read_text())
        for name in ['aura', 'uboot-aurora', 'mesa-aurora', 'speakerguardd', 'speakerguardd-v2', 'aurora-audio', 'alsa-ucm-conf-aurora', 'aurora-bless', 'avd-fw', 'libva-v4l2-request-avd', 'upower-aurora', 'omarchy-ane-tools', 'mil-hwx-compiler', 'aurora-camera-denoise', 'aurora-kbd-light', 'aurora-xart', 'aurora-touchid-rearm', 'aurora-sep-host-state', 'aurora-fido', 'aurora-sep-sk', 'aurora-sep-luks', 'aurora-wifi-firmware']:
            self.assertIn(pins[name]['commit'], (ROOT / 'packages' / name / 'PKGBUILD').read_text())
        self.assertIn(pins['kernel-aurora']['commit'], (ROOT / 'packages/linux-aurora/PKGBUILD').read_text())
        firstboot = (ROOT / 'packages/aurora-firstboot/PKGBUILD').read_text()
        self.assertIn(pins['aurora-firstboot']['commit'], firstboot)
        self.assertIn(pins['aurora-firstboot']['sha256'], firstboot)
        self.assertRegex(firstboot, rf"(?m)^pkgver={re.escape(pins['aurora-firstboot']['version'])}$")
    def test_kernel_depends_on_the_avd_firmware_that_fits_the_t8122_sram_window(self):
        # linux#2586 maps the T8122 (M3) CM3 SRAM at +0x90000, which only the
        # 64 KiB v4 image of avd-fw ea8ae7c8 (0.1.aurora4) fits; the older
        # 0x12000-byte image (0.1.aurora3) fails the probe with -EINVAL.
        kernel = (ROOT / 'packages/linux-aurora/PKGBUILD').read_text()
        body = kernel.split('\n_package_kernel() {\n', 1)[1].split('\n}\n', 1)[0]
        deps = re.search(r"(?m)^\s*depends=\((.*)\)$", body).group(1)
        self.assertEqual(re.findall(r"'avd-fw([<>=]*)([^']*)'", deps), [('>=', '0.1.aurora4')])
        self.assertLess(updatelib.alpm_vercmp('0.1.aurora3-1', '0.1.aurora4'), 0)
        # The recipe builds a 64 KiB v4 image at or above that version.
        firmware = (ROOT / 'packages/avd-fw/PKGBUILD').read_text()
        self.assertIn("('v4-t0', 0x10000, '", firmware)
        version = re.search(r'(?m)^pkgver=(\S+)$', firmware).group(1)
        self.assertGreaterEqual(updatelib.alpm_vercmp(version, '0.1.aurora4'), 0)
    def test_speakerguardd_v2_switches_by_preset_beside_the_legacy_stack(self):
        pins = json.loads((ROOT / 'sources.json').read_text())['speakerguardd-v2']
        text = (ROOT / 'packages/speakerguardd-v2/PKGBUILD').read_text()
        self.assertIn(pins['sha256'], text)
        self.assertRegex(text, r"(?m)^pkgname=\('speakerguardd-v2'\)$")
        # Sorts above every retired preview build (RC7 was 1.0.0alpha.1-25).
        self.assertRegex(text, r"(?m)^pkgver=1\.0\.0alpha\.2$")
        self.assertRegex(text, r"(?m)^pkgrel=\d+$")
        self.assertEqual(pins['version'], '1.0.0-alpha.2')
        self.assertNotRegex(text, r'(?m)^\s*(conflicts|replaces|provides)=')
        main = text.split('package_speakerguardd-v2() {', 1)[1].split('\n}', 1)[0]
        # The gate in every unit decides; the older daemons carry it the other way round.
        self.assertIn("f'ExecCondition={lx}/speakerguardd-gate v2'", text)
        self.assertIn("f'ExecCondition={lx}/speakerguardd-gate prepare'", text)
        self.assertIn('for u in speakersafetyd speakerguardd; do', main)
        self.assertIn('packaging/session/gate.json', main)
        # verify needs the macOS parity attestation (speakerguardd#114).
        self.assertIn('packaging/session/parity.json', main)
        # The speaker graph needs Aurora's PipeWire (volume applied once,
        # refused starts recovered); plain 'pipewire' was met by stock builds.
        deps = re.search(r"(?m)^\s*depends=\((.*?)\)", main).group(1)
        self.assertIn("'pipewire-speaker-graph>=2'", deps)
        self.assertIn('pipewire-speaker-graph=2', (ROOT / 'packages/pipewire/PKGBUILD').read_text())
        self.assertNotIn('machines.json', main)
        # The default audio stack keeps the legacy daemons as the fallback and
        # pulls v2 with the upgrade tool, whose preset switches a Mac at boot
        # only on a passing self-check; it replaces only the retired builds.
        audio = (ROOT / 'packages/aurora-audio/PKGBUILD').read_text()
        self.assertIn("'speakersafetyd' 'speakerguardd' 'alsa-utils-aurora'", audio)
        self.assertIn("'speakerguardd-v2>=1.0.0alpha.2-1' 'aurora-speaker-upgrade>=0.1-0.18'", audio)
        self.assertIn("conflicts=('asahi-audio' 'asahi-audio-aurora' 'speakerguardd-v2<=1.0.0alpha.1-25')", audio)
        self.assertIn("replaces=('asahi-audio-aurora' 'speakerguardd-v2<=1.0.0alpha.1-25')", audio)
        for pkg in (ROOT / 'packages').glob('*/PKGBUILD'):
            if pkg.parent.name in ('speakerguardd-v2', 'aurora-audio'):
                continue
            body = pkg.read_text()
            for m in re.finditer(r"(?ms)^\s*depends=\((.*?)\)", body):
                self.assertNotIn('speakerguardd-v2', m.group(1), pkg)
        up = ROOT / 'packages/aurora-speaker-upgrade'
        upgrade = (up / 'PKGBUILD').read_text()
        self.assertIn(json.loads((ROOT / 'sources.json').read_text())['aurora-speaker-upgrade']['commit'], upgrade)
        self.assertEqual([l for l in (up / '90-aurora-speaker-upgrade.preset').read_text().splitlines()
                          if l and not l.startswith('#')], ['enable aurora-speaker-upgrade.service'])
        self.assertIn('install=aurora-speaker-upgrade.install', upgrade)
        self.assertIn('/usr/lib/systemd/system-preset/90-aurora-speaker-upgrade.preset', upgrade)
        self.assertIn('systemctl --preset-mode=enable-only preset aurora-speaker-upgrade.service',
                      (up / 'aurora-speaker-upgrade.install').read_text())
    def test_diagnostics_are_opt_in_and_follow_their_pin(self):
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-diag']
        text = (ROOT / 'packages/aurora-diag/PKGBUILD').read_text()
        self.assertRegex(text, rf"(?m)^_commit={pin['commit']}$")
        self.assertIn(pin['sha256'], text)
        self.assertRegex(text, rf"(?m)^pkgver={re.escape(pin['version'])}$")
        self.assertEqual(pin['archive_root'], 'aurora-diag-' + pin['commit'])
        self.assertIn('make -C "aurora-diag-$_commit" check', text)
        self.assertRegex(text, r"(?m)^depends=\('python'\)$")
        # Opt-in: in no package group, pulled by no package, not in any image.
        self.assertNotRegex(text, r'(?m)^groups=')
        for pkg in (ROOT / 'packages').glob('*/PKGBUILD'):
            if pkg.parent.name == 'aurora-diag':
                continue
            for m in re.finditer(r"(?ms)^\s*depends=\((.*?)\)", pkg.read_text()):
                self.assertNotRegex(m.group(1), r"'aurora-diag[<>=']", pkg)
        self.assertNotIn('aurora-diag', (ROOT / 'scripts/build-image').read_text())
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
