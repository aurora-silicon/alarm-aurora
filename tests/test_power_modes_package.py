"""aurora-power-budget ships aurora-power-modes, and pacman applies its presets."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages/aurora-firstboot'
PKGBUILD = (PACKAGE / 'PKGBUILD').read_text()
MARKER = '/var/lib/aurora/power-modes-preset-done'


def body(name):
    return PKGBUILD.split(f'package_{name}() {{', 1)[1].split('\n}', 1)[0]


def preset(name):
    """The units a split package's preset file enables."""
    text = body(name).split("<<'EOF'\n", 1)[1].split('\nEOF', 1)[0]
    return [line.split()[1] for line in text.splitlines() if line.startswith('enable ')]


def functions(script):
    """A scriptlet's functions, by name."""
    return {m.group(1): m.group(2) for m in re.finditer(r'(?ms)^(\w+)\(\) \{\n(.*?)^\}', script)}


class PowerModesPackageTests(unittest.TestCase):
    def setUp(self):
        self.budget = body('aurora-power-budget')
        self.script = (PACKAGE / 'aurora-power-budget.install').read_text()

    def test_source_has_the_daemon_its_unit_and_its_config(self):
        # aurora-platform e3bc82ab is the first commit that installs the commented config.
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-firstboot']
        self.assertEqual(pin['commit'], '32e6b82ae7b775b552902f027ad8be976c09163d')
        self.assertIn(f"_commit={pin['commit']}", PKGBUILD)
        self.assertRegex(PKGBUILD, r'(?m)^pkgrel=9$')

    def test_config_is_under_etc_and_kept_across_upgrades(self):
        self.assertIn('make -C "aurora-platform-$_commit" install-power DESTDIR="$pkgdir" PREFIX=/usr SYSCONFDIR=/etc',
                      self.budget)
        self.assertIn("backup=('etc/aurora/power-modes.conf')", self.budget)
        self.assertIn('install -dm755 "$pkgdir/var/lib/aurora"', self.budget)

    def test_both_power_units_are_enabled_by_preset(self):
        self.assertEqual(preset('aurora-power-budget'), ['aurora-power-budget.service', 'aurora-power-modes.service'])

    def test_every_package_with_a_preset_applies_it_on_install(self):
        # pacman runs no presets: each split package that ships one has an
        # install script whose post_install presets exactly those units.
        for name in ('aurora-firstboot', 'aurora-power-budget', 'aurora-secboot'):
            with self.subTest(package=name):
                self.assertIn(f'  install={name}.install\n', body(name))
                post = functions((PACKAGE / f'{name}.install').read_text())['post_install']
                line = next(l for l in post.splitlines() if 'preset' in l)
                self.assertEqual(line, '  systemctl --preset-mode=enable-only preset ' + ' '.join(preset(name))
                                 + ' >/dev/null 2>&1 || :')
        self.assertNotIn('install=', body('aurora-gamemode'))

    def test_every_enabled_unit_is_disabled_on_removal(self):
        for name in ('aurora-firstboot', 'aurora-power-budget', 'aurora-secboot'):
            with self.subTest(package=name):
                remove = functions((PACKAGE / f'{name}.install').read_text())['pre_remove']
                line = next(l for l in remove.splitlines() if 'systemctl disable' in l)
                self.assertEqual(line.split('disable', 1)[1].replace('--now', '').split('>')[0].split(), preset(name))

    def test_upgrades_never_restart_first_boot_setup(self):
        self.assertNotIn('post_upgrade', functions((PACKAGE / 'aurora-firstboot.install').read_text()))
        self.assertNotIn('restart', (PACKAGE / 'aurora-firstboot.install').read_text().replace('restarts', ''))

    def test_upgrade_presets_power_modes_once_and_only_beside_an_enabled_budget(self):
        # The same logic as Fedora's %post for aurora-power-budget 0.1.13-7.
        upgrade = functions(self.script)['post_upgrade']
        code = '\n'.join(l for l in upgrade.splitlines() if not l.lstrip().startswith('#'))
        self.assertEqual(code, f"""  if [ ! -e {MARKER} ] &&
     systemctl -q is-enabled aurora-power-budget.service 2>/dev/null; then
    systemctl --preset-mode=enable-only preset aurora-power-modes.service >/dev/null 2>&1 || :
  fi
  mkdir -p /var/lib/aurora && touch {MARKER} || :
  systemctl try-restart aurora-power-budget.service aurora-power-modes.service >/dev/null 2>&1 || :""")
        self.assertIn(f'touch {MARKER}', functions(self.script)['post_install'])
        self.assertIn(f'rm -f {MARKER}', functions(self.script)['pre_remove'])

    @unittest.skipUnless(shutil.which('sh'), 'needs sh')
    def test_scriptlets_run_as_fedora_post_does(self):
        # Run the functions with systemctl, mkdir, touch and rm kept inside a
        # scratch root: which units each transaction presets.
        def run(function, *, marker, budget_enabled):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if marker:
                    (root / 'var/lib/aurora').mkdir(parents=True)
                    (root / MARKER[1:]).touch()
                script = self.script.replace('/var/lib/aurora', f'{root}/var/lib/aurora')
                stub = f"""systemctl() {{
  case "$*" in
    *is-enabled*) return {0 if budget_enabled else 1};;
    *) printf '%s\\n' "$*" >> {root}/calls;;
  esac
}}
"""
                subprocess.run(['sh', '-euc', stub + script + f'\n{function} 0.1.13-7 0.1.13-6\n'], check=True)
                calls = (root / 'calls').read_text().splitlines() if (root / 'calls').exists() else []
                return [c for c in calls if ' preset ' in f' {c} '], (root / MARKER[1:]).exists()

        both = '--preset-mode=enable-only preset aurora-power-budget.service aurora-power-modes.service'
        modes = '--preset-mode=enable-only preset aurora-power-modes.service'
        self.assertEqual(run('post_install', marker=False, budget_enabled=False), ([both], True))
        self.assertEqual(run('post_upgrade', marker=False, budget_enabled=True), ([modes], True))
        # The administrator disabled aurora-power-budget: the new unit stays off, for good.
        self.assertEqual(run('post_upgrade', marker=False, budget_enabled=False), ([], True))
        # A later upgrade never presets again.
        self.assertEqual(run('post_upgrade', marker=True, budget_enabled=True), ([], True))
        self.assertEqual(run('pre_remove', marker=True, budget_enabled=True), ([], False))

    def test_scriptlets_are_valid_sh(self):
        for path in sorted(PACKAGE.glob('*.install')):
            with self.subTest(script=path.name):
                subprocess.run(['sh', '-n', str(path)], check=True)

    def test_power_defaults_still_come_first(self):
        # aurora-power-modes records the values it finds at start as its baseline.
        unit = (ROOT / 'packages/aurora-system-fixes/aurora-power-defaults.service').read_text()
        self.assertRegex(unit, r'(?m)^Before=.*\baurora-power-modes\.service\b')


if __name__ == '__main__':
    unittest.main()
