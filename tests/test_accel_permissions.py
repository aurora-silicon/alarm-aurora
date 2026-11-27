"""The Neural Engine node's permissions on every install, not only with the ANE tools."""
import configparser
import fnmatch
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / 'packages' / 'aurora-system-fixes'
TOOLS = ROOT / 'packages' / 'omarchy-ane-tools'

# systemd's own rule for the subsystem (50-udev-default.rules), and the file
# that runs the uaccess builtin for nodes tagged uaccess.
SYSTEMD_RULES = {
    '50-udev-default.rules': 'SUBSYSTEM=="accel", GROUP="render", MODE="0666"\n',
}
SEAT_LATE = '73-seat-late.rules'
TOKEN = re.compile(r'([A-Z_]+(?:\{[^}]*\})?)\s*(==|!=|\+=|-=|:=|=)\s*"([^"]*)"')


def rules(text):
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            yield TOKEN.findall(line)


def matches(pattern, value):
    return any(fnmatch.fnmatchcase(value, alt) for alt in pattern.split('|'))


def apply(files, device):
    """Group, mode and tags that udev leaves on device after the files, in name order."""
    state = {'GROUP': 'root', 'MODE': '0600', 'TAG': set()}
    for name in sorted(files):
        for tokens in rules(files[name]):
            ok = True
            for key, op, value in tokens:
                if op == '==':
                    ok = ok and matches(value, device.get(key, ''))
                elif op == '!=':
                    ok = ok and not matches(value, device.get(key, ''))
            if not ok:
                continue
            for key, op, value in tokens:
                if key == 'TAG' and op == '+=':
                    state['TAG'].add(value)
                elif key in ('GROUP', 'MODE') and op in ('=', ':='):
                    state[key] = value
    return state


def rule_files(directory):
    return {p.name: p.read_text() for p in directory.iterdir() if p.name.endswith('.rules')}


class AccelPermissionTests(unittest.TestCase):
    NODE = {'SUBSYSTEM': 'accel', 'KERNEL': 'accel0'}

    def test_system_fixes_restricts_the_node_to_accel_and_the_session_user(self):
        files = dict(SYSTEMD_RULES)
        files.update(rule_files(PLATFORM))
        state = apply(files, self.NODE)
        self.assertEqual((state['GROUP'], state['MODE']), ('accel', '0660'))
        self.assertIn('uaccess', state['TAG'])
        # The tag must be set before the seat rules act on it.
        accel = [n for n, t in files.items() if 'SUBSYSTEM=="accel"' in t and n not in SYSTEMD_RULES]
        self.assertEqual(accel, ['70-aurora-accel.rules'])
        self.assertLess(accel[0], '71-seat.rules')
        self.assertLess(accel[0], SEAT_LATE)
        # Other accel nodes get the same policy; nothing else does.
        self.assertEqual(apply(files, {'SUBSYSTEM': 'accel', 'KERNEL': 'accel3'})['MODE'], '0660')
        self.assertEqual(apply(files, {'SUBSYSTEM': 'drm', 'KERNEL': 'renderD128'})['GROUP'], 'root')

    def test_system_fixes_installs_the_rule_and_the_group(self):
        pkgbuild = (PLATFORM / 'PKGBUILD').read_text()
        sources = pkgbuild.split('source=(', 1)[1].split(')', 1)[0].split()
        self.assertIn('70-aurora-accel.rules', sources)
        self.assertIn('aurora-accel.sysusers', sources)
        package = pkgbuild.split('package() {', 1)[1]
        self.assertIn('install -Dm644 70-aurora-accel.rules "$pkgdir/usr/lib/udev/rules.d/70-aurora-accel.rules"', package)
        self.assertIn('install -Dm644 aurora-accel.sysusers "$pkgdir/usr/lib/sysusers.d/aurora-accel.conf"', package)
        sysusers = [l.split() for l in (PLATFORM / 'aurora-accel.sysusers').read_text().splitlines()
                    if l and not l.startswith('#')]
        self.assertEqual(sysusers, [['g', 'accel', '-']])

    def test_an_upgrade_reapplies_the_policy_to_existing_nodes(self):
        hook = configparser.ConfigParser(interpolation=None, strict=False)
        hook.optionxform = str
        hook.read_string((PLATFORM / '36-aurora-accel-permissions.hook').read_text())
        self.assertEqual(hook['Trigger']['Target'], 'usr/lib/udev/rules.d/70-aurora-accel.rules')
        self.assertEqual(hook['Action']['When'], 'PostTransaction')
        run = hook['Action']['Exec']
        # An add event (a change event does not reapply GROUP and MODE), never
        # from a chroot or without a running udevd, and never failing the upgrade.
        self.assertIn('udevadm trigger --action=add --subsystem-match=accel', run)
        self.assertIn('systemd-detect-virt -q --chroot && exit 0', run)
        self.assertIn('[ -S /run/udev/control ] || exit 0', run)
        self.assertTrue(run.endswith("|| :'"), run)
        # After systemd's sysusers (20-) and udev reload (35-) hooks.
        self.assertGreater('36-aurora-accel-permissions.hook', '35-systemd-udev-reload.hook')
        pkgbuild = (PLATFORM / 'PKGBUILD').read_text()
        self.assertIn('"$pkgdir/usr/share/libalpm/hooks/36-aurora-accel-permissions.hook"', pkgbuild)

    def test_every_image_installs_system_fixes(self):
        build = (ROOT / 'scripts' / 'build-image').read_text()
        self.assertRegex(build, r'(?m)^\s+.*\baurora-system-fixes\b')
        self.assertRegex(build, r'pacman -Q [^\n]*\baurora-system-fixes\b')

    def test_the_ane_tools_carry_no_device_policy(self):
        pkgbuild = (TOOLS / 'PKGBUILD').read_text()
        self.assertEqual(rule_files(TOOLS), {})
        self.assertFalse(list(TOOLS.glob('*.sysusers')))
        self.assertNotIn('rules.d', pkgbuild)
        self.assertNotIn('sysusers.d', pkgbuild)
        self.assertIn("depends+=('aurora-system-fixes>=1-16')", pkgbuild)

    def test_no_other_package_sets_accel_permissions(self):
        owners = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'packages').rglob('*.rules')
                        if 'SUBSYSTEM=="accel"' in p.read_text())
        self.assertEqual(owners, ['packages/aurora-system-fixes/70-aurora-accel.rules'])


if __name__ == '__main__':
    unittest.main()
