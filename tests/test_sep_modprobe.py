"""SEP writes are always on. apple_sep has no xart_writes or provision_keybag
parameter (aurora-silicon/linux#2591), and nothing this repository ships
sets one: no modprobe.d file, no modprobe command line, no kernel command
line. A value given twice also stopped older kernels loading the driver."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'packages'
SEP = PACKAGES / 'aurora-sep'
REMOVED = ('xart_writes', 'provision_keybag')
# kmod's search order: a file hides one of the same name further down.
DIRS = ('etc/modprobe.d', 'run/modprobe.d', 'usr/lib/modprobe.d')
MODPROBE = shutil.which('modprobe', path=os.environ.get('PATH', '') + ':/usr/sbin:/sbin')
_names = '|'.join(REMOVED)
# A modprobe.d options line, a modprobe command line or a kernel command line
# that gives apple_sep one of the removed parameters.
SETS = re.compile(rf'^\s*options\s+apple_sep\b.*\b(?:{_names})\b'
                  rf'|\bmodprobe(?:\s+-\S+)*\s+apple_sep\b[^;|&"\n]*\b(?:{_names})='
                  rf'|\bapple_sep\.(?:{_names})=', re.M)


def tracked_files():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'],
                             capture_output=True, check=True).stdout.decode()
        names = [n for n in out.split('\0') if n]
    except (OSError, subprocess.CalledProcessError):
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
                 if p.is_file() and '.git' not in p.parts]
    for name in names:
        path = ROOT / name
        if path.parts[len(ROOT.parts)] == 'tests' or not path.is_file():
            continue
        yield path


def shipped_text(path):
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        return ''
    return text


def apple_sep_lines(text):
    """The words of every modprobe.d line for apple_sep."""
    for line in text.splitlines():
        w = shlex.split(line, comments=True)
        if len(w) >= 2 and w[1] == 'apple_sep':
            yield w


def modprobe_d_installs(pkgbuild):
    """{installed path: source file} for every file a PKGBUILD puts in modprobe.d."""
    installs = {}
    for source, target in re.findall(
            r'(?m)^\s*install\s+-\S+\s+(\S+)\s+"\$pkgdir(/\S*/modprobe\.d/[^"]+)"$',
            pkgbuild.read_text()):
        installs[target] = pkgbuild.parent / source
    return installs


class SepWritesAlwaysOnTests(unittest.TestCase):
    def test_nothing_shipped_sets_a_removed_parameter(self):
        found = [f'{path.relative_to(ROOT)}: {m.group(0).strip()}'
                 for path in tracked_files() for m in SETS.finditer(shipped_text(path))]
        self.assertEqual(found, [])

    def test_no_packaged_modprobe_d_file_sets_a_write_option(self):
        pkgbuilds = sorted(PACKAGES.glob('*/PKGBUILD'))
        self.assertTrue(pkgbuilds)
        for pkgbuild in pkgbuilds:
            for target, source in modprobe_d_installs(pkgbuild).items():
                with self.subTest(package=pkgbuild.parent.name, target=target):
                    for w in apple_sep_lines(source.read_text()):
                        self.assertFalse([o for o in w[2:] if o.split('=', 1)[0] in REMOVED], w)

    def test_aurora_sep_ships_only_the_load_ordering_blacklist(self):
        pkgbuild = SEP / 'PKGBUILD'
        installs = modprobe_d_installs(pkgbuild)
        self.assertEqual(set(installs), {'/usr/lib/modprobe.d/aurora-sep-load.conf'})
        self.assertEqual(list(apple_sep_lines(installs.popitem()[1].read_text())),
                         [['blacklist', 'apple_sep']])
        self.assertNotIn('aurora-sep-modprobe.conf', pkgbuild.read_text())
        self.assertFalse((SEP / 'aurora-sep-modprobe.conf').exists())

    def test_load_driver_passes_no_options(self):
        text = (SEP / 'load-driver').read_text()
        calls = [w for w in map(lambda l: shlex.split(l, comments=True), text.splitlines())
                 if w[:1] == ['modprobe'] and 'apple_sep' in w]
        self.assertEqual(calls, [['modprobe', 'apple_sep']])
        for name in REMOVED:
            self.assertNotIn(name, text)

    def test_messages_name_no_off_switch(self):
        status = (SEP / 'aurora-sep').read_text()
        ready = (SEP / 'aurora-sep-ready').read_text()
        for text in (status, ready):
            for name in REMOVED:
                self.assertNotIn(f'{name}=0', text)
        self.assertIn('"xART writes are disabled: the store is read-only this boot', status)
        self.assertIn('echo "xART writes are disabled (the store is read-only this boot', ready)

    @unittest.skipUnless(sys.platform == 'linux' and MODPROBE, 'needs kmod')
    def test_kmod_sees_no_write_option(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for target, source in modprobe_d_installs(SEP / 'PKGBUILD').items():
                path = root / target.lstrip('/')
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, path)
            config = [f'--config={root / d}' for d in DIRS if (root / d).is_dir()]
            out = subprocess.run([MODPROBE, *config, '-c'], capture_output=True, text=True,
                                 check=True).stdout
        lines = [line.split() for line in out.splitlines() if line.split()[1:2] == ['apple_sep']]
        self.assertEqual(lines, [['blacklist', 'apple_sep']])


if __name__ == '__main__':
    unittest.main()
