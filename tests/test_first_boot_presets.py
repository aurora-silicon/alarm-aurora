"""An install's first boot applies every preset; the image leaves it nothing to change."""
from fnmatch import fnmatchcase
import hashlib
from pathlib import Path
import os
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT/'packages/aurora-boot'
BUILD_IMAGE = (ROOT/'scripts/build-image').read_text()
PASS = 'chroot "$mountroot" systemctl preset-all --preset-mode=enable-only\n'
GATE = re.search(r'(?ms)^# The first boot must find nothing left to change\..*?^fi\n', BUILD_IMAGE)


def system_presets():
    """Every system preset an Aurora package installs, by file name."""
    presets = {}
    for pkgbuild in sorted(ROOT.glob('packages/*/PKGBUILD')):
        text = pkgbuild.read_text()
        for name, body in re.findall(r'install -Dm644 /dev/stdin "\$pkgdir/usr/lib/systemd/system-preset/([^"]+)"'
                                     r" <<'(?:EOF|PRESET)'\n(.*?)\n(?:EOF|PRESET)\n", text, re.S):
            presets[name] = body
        for source, name in re.findall(r'install -Dm644 (\S+) "\$pkgdir/usr/lib/systemd/system-preset/([^"]+)"', text):
            if source != '/dev/stdin':
                presets[name] = (pkgbuild.parent/source).read_text()
    return presets


def resolve(unit, presets):
    """systemd's rule: files in name order, the first matching line wins."""
    for name in sorted(presets):
        for line in presets[name].splitlines():
            words = line.split()
            if len(words) >= 2 and words[0] in ('enable', 'disable', 'ignore') and fnmatchcase(unit, words[1]):
                return words[0], name
    return None, None


class ImagePresetTests(unittest.TestCase):
    def test_aurora_boot_ships_the_image_preset_ahead_of_systemds(self):
        recipe = (BOOT/'PKGBUILD').read_text()
        self.assertIn('install -Dm644 80-aurora-image.preset '
                      '"$pkgdir/usr/lib/systemd/system-preset/80-aurora-image.preset"', recipe)
        sources = subprocess.check_output(['bash', '-c', 'source "$1"; for i in "${!source[@]}"; do '
                                           'printf "%s %s\\n" "${source[$i]}" "${sha256sums[$i]}"; done',
                                           'test', str(BOOT/'PKGBUILD')], text=True)
        digests = dict(line.split() for line in sources.splitlines())
        self.assertEqual(digests['80-aurora-image.preset'],
                         hashlib.sha256((BOOT/'80-aurora-image.preset').read_bytes()).hexdigest())
        # Lines in an earlier file win, so this one must sort before systemd's.
        self.assertEqual(sorted(['90-systemd.preset', '80-aurora-image.preset', '99-default.preset'])[0],
                         '80-aurora-image.preset')

    def test_units_build_image_disables_stay_off_on_the_first_boot(self):
        presets = system_presets()
        disabled = [unit for line in re.findall(r'(?m)^chroot "\$mountroot" systemctl disable (.*)$', BUILD_IMAGE)
                    for unit in line.split()]
        self.assertIn('systemd-networkd-wait-online.service', disabled)
        self.assertIn('sshd.service', disabled)
        for unit in disabled:
            with self.subTest(unit=unit):
                self.assertEqual(resolve(unit, presets), ('disable', '80-aurora-image.preset'))

    def test_systemd_units_the_image_keeps_off(self):
        presets = system_presets()
        # systemd 262's 90-systemd.preset enables these.
        for unit in ('systemd-networkd.service', 'systemd-networkd.socket', 'systemd-networkd-wait-online.service',
                     'systemd-networkd-varlink.socket', 'systemd-network-generator.service',
                     'systemd-boot-update.service', 'systemd-boot-clear-sysfail.service',
                     'systemd-journald-audit.socket'):
            with self.subTest(unit=unit):
                self.assertEqual(resolve(unit, presets)[0], 'disable')
        # The network, DNS and clock the image uses keep their own presets.
        for unit in ('NetworkManager.service', 'NetworkManager-wait-online.service', 'systemd-resolved.service',
                     'systemd-timesyncd.service', 'systemd-homed.service', 'systemd-sysext.service'):
            with self.subTest(unit=unit):
                self.assertEqual(resolve(unit, presets), (None, None))

    def test_presets_apply_before_the_images_own_choices_and_are_checked_last(self):
        self.assertIsNotNone(GATE)
        first_unit = re.search(r'(?m)^chroot "\$mountroot" systemctl (enable|disable|mask) ', BUILD_IMAGE).start()
        self.assertLess(BUILD_IMAGE.index(PASS), first_unit)
        self.assertGreater(BUILD_IMAGE.index(PASS), BUILD_IMAGE.index("printf 'uninitialized\\n' > "))
        last_unit = max(match.start() for match in re.finditer(r'systemctl (enable|disable|mask|set-default) ',
                                                               BUILD_IMAGE))
        self.assertGreater(GATE.start(), last_unit)
        self.assertLess(GATE.start(), BUILD_IMAGE.index('scripts/check-basics.py" --profile "${profile#arch-}" --root'))

    def test_gate_refuses_an_image_a_first_boot_would_change(self):
        # Run build-image's own gate with chroot answering as systemctl would.
        stub = '''chroot() { [[ $1 == "$mountroot" && $* == *"systemctl preset-all --preset-mode=enable-only" ]] || return 9
          printf '%b' "$PRESET_OUTPUT"; return "$PRESET_STATUS"; }
        '''

        def run(output, status=0):
            return subprocess.run(['bash', '-c', 'set -euo pipefail; mountroot=/image; ' + stub + GATE.group(0) + 'true\n'],
                                  text=True, capture_output=True,
                                  env={**os.environ, 'PRESET_OUTPUT': output, 'PRESET_STATUS': str(status)}).returncode
        self.assertEqual(run(''), 0)
        self.assertEqual(run('Configuration file /usr/lib/systemd/system/x.service is marked executable.\n'), 0)
        self.assertNotEqual(run("Created symlink '/etc/systemd/system/multi-user.target.wants/systemd-networkd.service'"
                                " → '/usr/lib/systemd/system/systemd-networkd.service'.\n"), 0)
        self.assertNotEqual(run("Removed '/etc/systemd/system/default.target'.\n"), 0)
        self.assertNotEqual(run('Failed to preset all units: File exists\n', 1), 0)


if __name__ == '__main__':
    unittest.main()
