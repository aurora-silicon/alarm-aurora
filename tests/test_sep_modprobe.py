"""load-driver leaves apple_sep's options to modprobe.d, so a read-only
/etc/modprobe.d/aurora-sep.conf beats the packaged defaults."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEP = ROOT / 'packages/aurora-sep'
DEFAULTS = 'usr/lib/modprobe.d/aurora-sep.conf'
READ_ONLY = 'options apple_sep xart_writes=0 provision_keybag=0\n'
# kmod's search order: a file hides one of the same name further down.
DIRS = ('etc/modprobe.d', 'run/modprobe.d', 'usr/lib/modprobe.d')
MODPROBE = shutil.which('modprobe', path=os.environ.get('PATH', '') + ':/usr/sbin:/sbin')


def options(root, argv=()):
    """apple_sep's parameters as modprobe passes them: modprobe.d by file
    name, then its own command line. The kernel keeps the last value."""
    files = {}
    for d in DIRS:
        for path in sorted((root / d).glob('*.conf')):
            files.setdefault(path.name, path)
    words = []
    for name in sorted(files):
        for line in files[name].read_text().splitlines():
            w = shlex.split(line, comments=True)
            if w[:2] == ['options', 'apple_sep']:
                words += w[2:]
    return dict(w.split('=', 1) for w in [*words, *argv])


def load_driver_argv():
    for line in (SEP / 'load-driver').read_text().splitlines():
        w = shlex.split(line, comments=True)
        if w[:2] == ['modprobe', 'apple_sep']:
            return w[2:]
    raise AssertionError('load-driver does not load apple_sep')


class SepModprobeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.install(DEFAULTS, (SEP / 'aurora-sep-modprobe.conf').read_text())
        self.install('usr/lib/modprobe.d/aurora-sep-load.conf', (SEP / 'aurora-sep-load.conf').read_text())

    def install(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_load_driver_passes_no_options(self):
        # Command-line options come after modprobe.d's and would win.
        self.assertEqual(load_driver_argv(), [])

    def test_the_defaults_keep_writes_and_provisioning_on(self):
        self.assertEqual(options(self.root, load_driver_argv()),
                         {'xart_writes': '1', 'provision_keybag': '1'})

    def test_a_read_only_etc_file_wins(self):
        self.install('etc/modprobe.d/aurora-sep.conf', READ_ONLY)
        self.assertEqual(options(self.root, load_driver_argv()),
                         {'xart_writes': '0', 'provision_keybag': '0'})
        # The options load-driver used to pass overrode it.
        self.assertEqual(options(self.root, ['xart_writes=1', 'provision_keybag=1']),
                         {'xart_writes': '1', 'provision_keybag': '1'})

    def test_the_package_installs_the_defaults(self):
        pkgbuild = (SEP / 'PKGBUILD').read_text()
        self.assertIn("'aurora-sep-modprobe.conf'", pkgbuild)
        self.assertIn('install -Dm644 aurora-sep-modprobe.conf '
                      '"$pkgdir/usr/lib/modprobe.d/aurora-sep.conf"', pkgbuild)

    @unittest.skipUnless(sys.platform == 'linux' and MODPROBE, 'needs kmod')
    def test_kmod_agrees(self):
        self.install('etc/modprobe.d/aurora-sep.conf', READ_ONLY)
        config = [f'--config={self.root / d}' for d in DIRS if (self.root / d).is_dir()]
        out = subprocess.run([MODPROBE, *config, '-c'], capture_output=True, text=True,
                             check=True).stdout
        lines = [line.split() for line in out.splitlines()
                 if line.startswith('options apple_sep ')]
        self.assertEqual(lines[-1], READ_ONLY.split())
        self.assertEqual(options(self.root), dict(w.split('=', 1) for line in lines
                                                   for w in line[2:]))


if __name__ == '__main__':
    unittest.main()
