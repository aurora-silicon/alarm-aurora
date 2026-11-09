"""check-published-versions refuses a recipe that sorts before the published feed."""
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('check_published_versions', ROOT / 'scripts/check-published-versions.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def database(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, version in entries.items():
            desc = f'%FILENAME%\n{name}-{version}-aarch64.pkg.tar.zst\n\n%NAME%\n{name}\n\n%VERSION%\n{version}\n\n'.encode()
            info = tarfile.TarInfo(f'{name}-{version}/desc')
            info.size = len(desc)
            archive.addfile(info, io.BytesIO(desc))
    return data.getvalue()


class PublishedVersionsTest(unittest.TestCase):
    def recipes(self, pkgbuilds):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for directory, text in pkgbuilds.items():
            (root / 'packages' / directory).mkdir(parents=True)
            (root / 'packages' / directory / 'PKGBUILD').write_text(text)
        return check.recipe_versions(root)

    def test_split_packages_epochs_and_computed_versions(self):
        recipes = self.recipes({
            'fex-emu': "pkgbase=fex-emu\npkgname=(fex-emu fex-emu-steam)\npkgver=2610.r1.abc\npkgrel=1\n",
            'pipewire': "pkgname=pipewire\nepoch=1\npkgver=1.6.10\npkgrel=1.4\n",
            'linux-aurora': "_v=7.3.0\npkgname=linux-aurora\npkgver=\"${_v}.aurora1\"\npkgrel=28\n",
        })
        self.assertEqual(recipes, {
            'fex-emu': ('2610.r1.abc-1', 'fex-emu'), 'fex-emu-steam': ('2610.r1.abc-1', 'fex-emu'),
            'pipewire': ('1:1.6.10-1.4', 'pipewire'), 'linux-aurora': ('7.3.0.aurora1-28', 'linux-aurora'),
        })

    def test_only_an_older_recipe_fails(self):
        published = check.database_versions(database({
            'plymouth': '26.134.222-7', 'pipewire': '1:1.6.10-1.4', 'gone': '1-1'}))
        recipes = self.recipes({
            'plymouth': "pkgname=plymouth\npkgver=26.134.222\npkgrel=6\n",
            'pipewire': "pkgname=pipewire\nepoch=1\npkgver=1.6.10\npkgrel=1.4\n",
            'new': "pkgname=new\npkgver=0.1\npkgrel=1\n",
        })
        self.assertEqual(check.older(published, recipes),
                         [('plymouth', 'plymouth', '26.134.222-6', '26.134.222-7')])

    def test_every_recipe_in_this_repository_has_a_version(self):
        recipes = check.recipe_versions()
        self.assertIn('linux-aurora', recipes)
        self.assertTrue(all(version for version, _ in recipes.values()))


if __name__ == '__main__':
    unittest.main()
