from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class AuraStage1Tests(unittest.TestCase):
    def test_both_stage1_forms_come_from_the_stage1_build(self):
        text = (ROOT / 'packages/aura/PKGBUILD').read_text()
        build = text.split('\nbuild() {\n', 1)[1].split('\n}\n', 1)[0]
        # The second `make clean` starts the secure-flavour Stage 1, the third the Stage 2 build.
        stage1 = build.split('make clean', 2)[1]
        package = text.split('\npackage() {\n', 1)[1].split('\n}\n', 1)[0]
        for built, name in (('aura.bin', 'aura-raw.bin'), ('aura-boot.macho', 'aura-boot.macho')):
            with self.subTest(name=name):
                self.assertIn(f'install -Dm644 build/{built} "$srcdir/stage1/{name}"', stage1)
                self.assertIn(f'install -Dm644 stage1/{name} "$pkgdir/usr/share/aura/stage1/{name}"', package)
    def test_secure_stage1_has_a_throwaway_key_and_ships_with_its_tools(self):
        text = (ROOT / 'packages/aura/PKGBUILD').read_text()
        build = text.split('\nbuild() {\n', 1)[1].split('\n}\n', 1)[0]
        secure = build.split('make clean', 3)[2]
        self.assertIn('secboot_sign.pubkey(os.urandom(32))', secure)
        self.assertIn('SECBOOT=audit SECBOOT_FLAVOUR=secure SECBOOT_PUBKEY="$srcdir/stage1/nobody.pub"', secure)
        self.assertIn('install -Dm644 build/aura.bin "$srcdir/stage1/aura-secure-raw.bin"', secure)
        self.assertIn('ESP_STAGE2=1', build.split('make clean', 3)[3])
        package = text.split('\npackage() {\n', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('install -Dm644 stage1/aura-secure-raw.bin "$pkgdir/usr/share/aura/stage1/aura-secure-raw.bin"', package)
        self.assertNotIn('nobody.pub', package)
        for tool in ('fill_stage1_config.py', 'secboot_sign.py', 'macho_boot_object.py'):
            self.assertIn(tool, package)
        self.assertIn('install -Dm644 aura/tools/recovery/enroll-stage1.sh "$pkgdir/usr/share/aura/tools/enroll-stage1.sh"', package)
if __name__ == '__main__': unittest.main()
