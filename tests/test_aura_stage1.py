from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class AuraStage1Tests(unittest.TestCase):
    def test_both_stage1_forms_come_from_the_stage1_build(self):
        text = (ROOT / 'packages/aura/PKGBUILD').read_text()
        build = text.split('\nbuild() {\n', 1)[1].split('\n}\n', 1)[0]
        # The second `make clean` starts the Stage 2 build.
        stage1 = build.split('make clean', 2)[1]
        package = text.split('\npackage() {\n', 1)[1].split('\n}\n', 1)[0]
        for built, name in (('aura.bin', 'aura-raw.bin'), ('aura-boot.macho', 'aura-boot.macho')):
            with self.subTest(name=name):
                self.assertIn(f'install -Dm644 build/{built} "$srcdir/stage1/{name}"', stage1)
                self.assertIn(f'install -Dm644 stage1/{name} "$pkgdir/usr/share/aura/stage1/{name}"', package)
if __name__ == '__main__': unittest.main()
