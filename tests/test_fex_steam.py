"""FEX and Steam come from Aurora under the names users type."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def sources(name):
    """(source, sha256) pairs as makepkg sees them."""
    out = subprocess.check_output(['bash', '-c',
        'source "$1"; for i in "${!source[@]}"; do printf "%s %s\\n" "${source[$i]}" "${sha256sums[$i]}"; done',
        'sources', str(ROOT / 'packages' / name / 'PKGBUILD')], text=True)
    return [line.split() for line in out.splitlines()]


def field(name, function, key):
    """An array assigned in PKGBUILD (function=None) or in one package function,
    evaluated by bash without running any function body."""
    text = (ROOT / 'packages' / name / 'PKGBUILD').read_text()
    if function:
        body = re.search(rf'(?ms)^{re.escape(function)}\(\) \{{\n(.*?)^\}}', text)[1]
        assignment = re.search(rf'(?ms)^\s*{key}=\(.*?\)$', body)[0]
        script = 'source "$1"; ' + assignment.strip() + f'; printf "%s\\n" "${{{key}[@]}}"'
    else:
        script = f'source "$1"; printf "%s\\n" "${{{key}[@]}}"'
    out = subprocess.check_output(['bash', '-c', script, 'field', str(ROOT / 'packages' / name / 'PKGBUILD')], text=True)
    return out.split('\n')[:-1]


class FexSteamTests(unittest.TestCase):
    def test_fex_pins_the_fork_and_its_submodules(self):
        pin = json.loads((ROOT / 'sources.json').read_text())['fex-emu']
        text = (ROOT / 'packages/fex-emu/PKGBUILD').read_text()
        self.assertEqual(re.search(r'^_commit=(.*)$', text, re.M)[1], pin['commit'])
        self.assertIn('_sha256=' + pin['sha256'], text)
        listed = dict(sources('fex-emu'))
        for name, record in pin['extra_sources'].items():
            url = f'{name}-{record["commit"]}.tar.gz::{record["source_url"]}'
            with self.subTest(submodule=name):
                self.assertEqual(listed[url], record['sha256'])
        for source, digest in listed.items():
            if '://' not in source:
                self.assertEqual(hashlib.sha256((ROOT / 'packages/fex-emu' / source).read_bytes()).hexdigest(), digest)

    def test_fex_emu_takes_over_fex_emu_and_not_fex(self):
        self.assertEqual(field('fex-emu', None, 'pkgname'), ['fex-emu', 'FEX-Emu'])
        # `fex` is not ours to take (Fedora's is an unrelated tool).
        self.assertNotIn('provides=', re.search(r'(?ms)^package_fex-emu\(\) \{\n(.*?)^\}', (ROOT / 'packages/fex-emu/PKGBUILD').read_text())[1])
        self.assertEqual(field('fex-emu', 'package_fex-emu', 'conflicts'), ['FEX-Emu<2610'])
        depends = field('fex-emu', 'package_FEX-Emu', 'depends')
        self.assertEqual(len(depends), 1)
        self.assertTrue(depends[0].startswith('fex-emu=2610'))

    def test_steam_replaces_the_muvm_wrapper_and_uses_the_system_launcher(self):
        d = ROOT / 'packages/aurora-steam-native'
        pin = json.loads((ROOT / 'sources.json').read_text())['aurora-steam-native']
        text = (d / 'PKGBUILD').read_text()
        self.assertEqual(re.search(r'^_commit=(.*)$', text, re.M)[1], pin['commit'])
        self.assertIn('_sha256=' + pin['sha256'], text)
        self.assertEqual(field('aurora-steam-native', None, 'pkgname'), ['aurora-steam-native', 'steam'])
        # The Asahi ALARM `steam` is 20241231-4; the epoch keeps ours newer.
        self.assertEqual(field('aurora-steam-native', None, 'epoch'), ['1'])
        depends = field('aurora-steam-native', 'package_aurora-steam-native', 'depends')
        for name in ('aurora-userpages', 'fex-emu', 'gtk2', 'python'):
            self.assertIn(name, depends)
        self.assertIn("'s,@USERPAGES@,/usr/bin/userpages,'", text)
        for source, digest in sources('aurora-steam-native'):
            if '://' not in source:
                self.assertEqual(hashlib.sha256((d / source).read_bytes()).hexdigest(), digest)
        subprocess.run(['bash', '-n', str(d / 'steam')], check=True)

    def test_gtk2_is_built_here_for_the_native_client(self):
        # Arch Linux ARM dropped GTK 2; steamui.so needs libgtk-x11-2.0.so.0.
        self.assertEqual(field('gtk2', None, 'arch'), ['aarch64'])
        self.assertIn('libgtk-x11-2.0.so', field('gtk2', 'package', 'provides'))


if __name__ == '__main__':
    unittest.main()
