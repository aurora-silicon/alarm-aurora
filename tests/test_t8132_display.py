from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT/'packages/aurora-boot'
DROPIN = BOOT/'46-aurora-t8132-display.cfg'
PARAMS = ('apple_dart.j713_dcp=1', 'apple_dart.j713_display=1')


def source(linux, default=''):
    """GRUB_CMDLINE_LINUX, _DEFAULT and the count of new shell variables after sourcing the drop-in."""
    script = ('GRUB_CMDLINE_LINUX="$1"; GRUB_CMDLINE_LINUX_DEFAULT="$2"; before=; after=; before=$(set | grep -c .); . "$3"; '
              'after=$(set | grep -c .); printf "%s\\n%s\\n%s\\n" "$GRUB_CMDLINE_LINUX" "$GRUB_CMDLINE_LINUX_DEFAULT" '
              '"$((after - before))"')
    out = subprocess.run(['sh', '-c', script, 'sh', linux, default, str(DROPIN)],
                         check=True, capture_output=True, text=True).stdout
    return out.split('\n')[:3]


class T8132DisplayTests(unittest.TestCase):
    def test_adds_both_parameters_once(self):
        linux, default, new_vars = source('rootflags=subvol=root', 'quiet')
        self.assertEqual(linux.split(), ['rootflags=subvol=root', *PARAMS])
        self.assertEqual(default, 'quiet')
        self.assertEqual(new_vars, '0')

    def test_empty_command_line(self):
        self.assertEqual(source('')[0].split(), list(PARAMS))

    def test_owner_value_wins(self):
        linux, default, _ = source('apple_dart.j713_dcp=0', 'apple_dart.j713_display=1')
        self.assertEqual(linux.split(), ['apple_dart.j713_dcp=0'])
        self.assertEqual(default, 'apple_dart.j713_display=1')

    def test_owner_value_with_dashes_or_tabs_wins(self):
        # The kernel treats - and _ alike in parameter names.
        linux, default, _ = source('apple-dart.j713-dcp=0', 'quiet\tapple_dart.j713_display=0')
        self.assertEqual(linux, 'apple-dart.j713-dcp=0')
        self.assertEqual(default, 'quiet\tapple_dart.j713_display=0')

    def test_package_installs_it_and_regenerates_grub(self):
        pkgbuild = (BOOT/'PKGBUILD').read_text()
        self.assertIn("'46-aurora-t8132-display.cfg'", pkgbuild)
        self.assertIn('install -Dm644 46-aurora-t8132-display.cfg '
                      '"$pkgdir/etc/default/grub.d/46-aurora-t8132-display.cfg"', pkgbuild)
        # Older kernels overflow the stack in the G16 probe once the display registers.
        self.assertIn("'linux-aurora>=7.3.0.aurora1-37'", pkgbuild)
        hook = (BOOT/'aurora-grub.hook').read_text().splitlines()
        self.assertIn('Target = etc/default/grub.d/46-aurora-t8132-display.cfg', hook)


if __name__ == '__main__':
    unittest.main()
