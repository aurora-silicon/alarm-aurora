from pathlib import Path
import hashlib
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
KEEP = ROOT / 'packages/aurora-keep-config'
# Aurora build -> the distribution package it replaces; both own the same
# backup files, so a swap goes through a conflict removal and a .pacsave.
SWAPS = {
    'upower-aurora': 'upower',
    'networkmanager-aurora': 'networkmanager',
    'gnome-settings-daemon-aurora': 'gnome-settings-daemon',
}
# Packages with backup files and conflicts that share no backup file with the
# package they conflict with.
NOT_SHARED = {
    'aurora-audio': 'asahi-audio ships no backup files',
    'aurora-sep': 'conflicts only with old linux-aurora builds',
    'fex-emu': 'FEX-Emu ships no backup files',
}
class KeepConfigTests(unittest.TestCase):
    def test_sources_match_their_checksums(self):
        text = (KEEP / 'PKGBUILD').read_text()
        names = re.search(r'(?m)^source=\((.*?)\)', text).group(1).split()
        sums = re.findall(r"'([0-9a-f]{64})'", re.search(r'(?ms)^sha256sums=\((.*?)\)', text).group(1))
        self.assertEqual(len(names), len(sums))
        for name, digest in zip(names, sums):
            self.assertEqual(hashlib.sha256((KEEP / name).read_bytes()).hexdigest(), digest, name)
    def test_hook_runs_the_installed_script_after_the_transaction(self):
        hook = (KEEP / 'aurora-keep-config.hook').read_text()
        pkgbuild = (KEEP / 'PKGBUILD').read_text()
        self.assertIn('Type = Package', hook)
        self.assertEqual(re.findall(r'(?m)^Operation = (\w+)$', hook), ['Install'])
        self.assertIn('When = PostTransaction', hook)
        self.assertIn('NeedsTargets', hook)
        self.assertIn('Exec = /usr/libexec/aurora/keep-config', hook)
        self.assertIn('"$pkgdir/usr/libexec/aurora/keep-config"', pkgbuild)
        self.assertIn('"$pkgdir/usr/share/libalpm/hooks/aurora-keep-config.hook"', pkgbuild)
    def test_every_swap_keeps_the_owner_config_both_ways(self):
        targets = set(re.findall(r'(?m)^Target = (\S+)$', (KEEP / 'aurora-keep-config.hook').read_text()))
        self.assertEqual(targets, set(SWAPS) | set(SWAPS.values()))
        workflow = (ROOT / '.github/workflows/packages.yml').read_text()
        for aurora, stock in SWAPS.items():
            text = (ROOT / 'packages' / aurora / 'PKGBUILD').read_text()
            self.assertRegex(text, rf"(?m)^conflicts=\('{stock}'\)$")
            self.assertRegex(text, r"(?m)^backup=\(")
            body = text.split('package() {', 1)[1].split('\n}', 1)[0]
            self.assertIn("depends+=('aurora-keep-config')", body)
            test = f'scripts/test-{stock}-upgrade'
            self.assertTrue((ROOT / test).is_file(), test)
            self.assertIn(f'/src/{test} /tmp/package-build', workflow)
            script = (ROOT / test).read_text()
            self.assertIn("== '[modified]' ]]", script)
            self.assertIn('kept the edited copy', script)
    def test_no_other_package_shares_backup_files_with_a_conflict(self):
        found = set()
        for pkgbuild in (ROOT / 'packages').glob('*/PKGBUILD'):
            text = pkgbuild.read_text()
            if re.search(r'(?m)^\s*backup=\(', text) and re.search(r'(?m)^\s*conflicts=\(', text):
                found.add(pkgbuild.parent.name)
        self.assertEqual(found, set(SWAPS) | set(NOT_SHARED))
if __name__ == '__main__':
    unittest.main()
