"""The ALARM Edge overlay feed and Edge images (aurora-distributions docs/edge-train.md)."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import edgelib  # noqa: E402
import updatelib  # noqa: E402


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


site = module('edge_channel_site', 'scripts/channel-site.py')
proof = module('edge_image_proof', 'scripts/edge-image-proof.py')

LINUX = {'repository': 'aurora-silicon/linux', 'branch': 'aurora-edge', 'revision': '1' * 40, 'tree': '2' * 40}
MESA = {'repository': 'aurora-silicon/mesa', 'branch': 'aurora-edge', 'revision': '3' * 40, 'tree': '4' * 40}
PACMAN = """[options]
Architecture = aarch64

[core]
Include = /etc/pacman.d/mirrorlist
"""


class OverlayTests(unittest.TestCase):
    def test_edge_tags_are_their_own_namespace(self):
        self.assertEqual(edgelib.snapshot('edge-20261121.1'), 'edge-20261121.1')
        for tag in ('testing-20261121.1', 'edge-latest', 'edge-20261121.1/x'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                edgelib.snapshot(tag)

    def test_the_overlay_carries_only_kernel_and_mesa_packages(self):
        rows = [('linux-aurora', 'linux-aurora', '7.3.0.aurora1-43'),
                ('linux-aurora', 'linux-aurora-headers', '7.3.0.aurora1-43'),
                ('mesa-aurora', 'vulkan-aurora', '26.3.0-35'), ('mesa-aurora', 'mesa-aurora', '26.3.0-35'),
                ('aurora-flatpak-gl', 'aurora-flatpak-gl', '26.3.0-35'),
                ('mesa-aurora-fex-guest', 'mesa-aurora-fex-guest', '26.3.0-35')]
        self.assertEqual(edgelib.select(rows), sorted(name for _, name, _ in rows))
        with self.assertRaisesRegex(ValueError, 'not a kernel or Mesa'):
            edgelib.select(rows + [('aura', 'aura', '1.0.0b14-1')])
        with self.assertRaisesRegex(ValueError, 'one version'):
            edgelib.select(rows + [('mesa-aurora', 'opencl-rusticl-aurora', '26.3.0-34')])
        with self.assertRaisesRegex(ValueError, 'one version'):
            edgelib.select(rows[2:])

    def test_staging_may_change_only_the_pair_recipes(self):
        edgelib.check_staging_files(['sources.json', 'packages/linux-aurora/PKGBUILD', 'packages/linux-aurora/config',
                                     'packages/mesa-aurora/PKGBUILD', 'packages/aurora-flatpak-gl/PKGBUILD'])
        for path in ('packages/aura/PKGBUILD', '.github/workflows/packages.yml', 'scripts/build-package'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'outside the kernel and Mesa'):
                edgelib.check_staging_files(['sources.json', path])

    def test_packaged_sources_are_one_pair(self):
        sources = {'linux-aurora': {'commit': LINUX['revision']}, 'mesa-aurora': {'commit': MESA['revision']},
                   'mesa-aurora-fex-guest': {'commit': MESA['revision']}}
        trees = {'linux': LINUX['tree'], 'mesa': MESA['tree']}
        self.assertEqual(edgelib.packaged_sources(sources, trees), {'linux': LINUX, 'mesa': MESA})
        sources['mesa-aurora-fex-guest']['commit'] = '5' * 40
        with self.assertRaisesRegex(ValueError, 'one Mesa'):
            edgelib.packaged_sources(sources, trees)


class GateTests(unittest.TestCase):
    def record(self, tag='edge-20261121.1'):
        return {'schema_version': 1, 'release': 'alpha.4', 'pair': {'linux': LINUX, 'mesa': MESA},
                'distributions': {'arch': {'repository': 'aurora-silicon/alarm-aurora', 'snapshot': tag}}}

    def sources(self, mesa=None):
        return {'schema': 1, 'channel': 'edge', 'packaged_sources': {'linux': LINUX, 'mesa': mesa or MESA}}

    def test_edge_is_a_channel_with_its_own_database(self):
        self.assertIn('edge', site.CHANNELS)
        self.assertEqual(site.database('edge'), 'aurora-edge')
        self.assertEqual(site.database('testing'), 'aurora')
        self.assertTrue(site.publisher('edge').endswith('/publish-edge.yml'))
        updatelib.record_channel(updatelib.empty_channels('aurora-silicon/alarm-aurora'), 'edge', {'tag': 'edge-20261121.1'})

    def test_only_the_adopted_train_snapshot_moves_the_overlay(self):
        edgelib.edge_gate(self.record(), 'edge-20261121.1', self.sources())
        for record, tag, sources, message in (
                (self.record('edge-20261120.1'), 'edge-20261121.1', self.sources(), 'adopted Edge train'),
                (self.record(), 'edge-20261121.1', self.sources(mesa=dict(MESA, revision='5' * 40)), 'pair'),
                (None, 'edge-20261121.1', self.sources(), 'adopted Edge train')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                edgelib.edge_gate(record, tag, sources)


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        modules = self.root / 'usr/lib/modules/7.3.0-aurora1-43-aurora'
        modules.mkdir(parents=True)
        (modules / 'vmlinuz').write_bytes(b'kernel image')
        (self.root / 'usr/lib/libvulkan_asahi.so').write_bytes(b'mesa dso')
        (self.root / 'etc').mkdir()
        self.sources = {'linux': LINUX, 'mesa': MESA}

    def write_conf(self, text):
        (self.root / 'etc/pacman.conf').write_text(text)

    def test_build_and_sealed_sections(self):
        text = edgelib.add_sections(PACMAN, 'testing-20261121.1', 'edge-20261121.1')
        self.assertLess(text.index('[aurora-edge]'), text.index('[aurora]'))
        self.assertLess(text.index('[aurora]'), text.index('[core]'))
        self.assertIn('Server = https://github.com/aurora-silicon/alarm-aurora/releases/download/edge-20261121.1\n', text)
        sealed = edgelib.seal(text, 'testing-20261121.1', 'edge-20261121.1')
        self.assertIn('[aurora-edge]\nSigLevel = Required DatabaseRequired\nServer = ' + edgelib.FEED + '\n', sealed)
        self.assertIn('[aurora]\nSigLevel = Required DatabaseRequired\n'
                      'Server = https://aurorasilicon.org/alarm-aurora/testing/aarch64\n', sealed)
        self.assertNotIn('alarm-aurora/releases/download', sealed)
        plain = edgelib.add_sections(PACMAN, 'testing-20261121.1', None)
        self.assertNotIn('[aurora-edge]', plain)

    def test_proof_records_the_overlay_build(self):
        self.write_conf(edgelib.seal(edgelib.add_sections(PACMAN, 'testing-20261121.1', 'edge-20261121.1'),
                                     'testing-20261121.1', 'edge-20261121.1'))
        result = proof.proof(self.root, 'arch-kde', 'edge-20261121.1', self.sources)
        self.assertEqual((result['schema'], result['distribution'], result['channel']), (2, 'arch', 'edge'))
        self.assertEqual(result['feed'], edgelib.FEED)
        self.assertEqual(result['files']['kernelImageSHA256'], 'sha256:' + hashlib.sha256(b'kernel image').hexdigest())
        self.assertEqual(result['files']['mesaDsoSHA256'], 'sha256:' + hashlib.sha256(b'mesa dso').hexdigest())

    def test_an_image_without_the_overlay_first_has_no_proof(self):
        self.write_conf(edgelib.seal(edgelib.add_sections(PACMAN, 'testing-20261121.1', None), 'testing-20261121.1', None))
        with self.assertRaisesRegex(ValueError, 'Edge feed'):
            proof.proof(self.root, 'arch-kde', 'edge-20261121.1', self.sources)


class WorkflowTests(unittest.TestCase):
    def test_overlay_is_signed_only_on_main_in_the_signing_environment(self):
        text = (ROOT / '.github/workflows/publish-edge.yml').read_text()
        collect, rest = text.split('\n  sign:\n', 1)
        sign = rest.split('\n  release:\n', 1)[0]
        self.assertIn('environment: testing-signing', sign)
        self.assertIn('--network none', sign)
        self.assertIn('--repository-name aurora-edge', sign)
        self.assertNotIn('secrets.', collect)
        self.assertIn("github.ref == 'refs/heads/main'", collect)

    def test_deploys_and_images_know_edge(self):
        deploy = (ROOT / '.github/workflows/deploy-snapshot.yml').read_text()
        self.assertIn('options: [testing, stable, edge]', deploy)
        self.assertIn('site/installer/edge-train.json', deploy)
        images = (ROOT / '.github/workflows/images.yml').read_text()
        self.assertIn('options: [testing, stable, edge]', images)
        self.assertIn('out/*-installer/edge-image-proof.json', images)


if __name__ == '__main__':
    unittest.main()


closure = module('edge_closure', 'scripts/check-edge-closure.py')
feed = module('feed_depends_for_edge', 'scripts/check-feed-depends.py')


def package(name, version, depends=(), conflicts=(), provides=()):
    return {'name': name, 'version': version, 'depends': list(depends), 'conflicts': list(conflicts),
            'provides': list(provides)}


class ClosureTests(unittest.TestCase):
    """[aurora-edge] must resolve against the served [aurora] Testing feed and Arch Linux ARM."""

    def setUp(self):
        self.overlay = [package('linux-aurora', '7.3.0.aurora1-43', depends=('avd-fw>=0.1.aurora3', 'kmod')),
                        package('mesa-aurora', '1:26.3.0-35', depends=('libdrm',), provides=('mesa=26.3.0',))]
        self.testing = [package('linux-aurora', '7.3.0.aurora1-41'), package('avd-fw', '0.1.aurora3-1'),
                        package('aurora-boot', '20261018-20', depends=('linux-aurora>=7.3.0.aurora1-37',)),
                        package('mesa-aurora', '1:26.3.0-30')]
        self.upstream = [feed.Package('kmod', '34-1', origin='core'), feed.Package('libdrm', '2.4.124-1', origin='extra'),
                         feed.Package('avd-fw', '0.1-1', origin='extra')]
        self.aurora = {'linux-aurora', 'avd-fw', 'aurora-boot', 'mesa-aurora', 'aura'}

    def problems(self):
        return closure.problems(self.overlay, self.testing, self.upstream, self.aurora)

    def test_a_consistent_overlay_passes(self):
        self.assertEqual(self.problems(), [])

    def test_an_overlay_depend_testing_does_not_meet_is_refused(self):
        self.overlay[0]['depends'] = ['avd-fw>=0.1.aurora4', 'kmod']
        found = self.problems()
        self.assertTrue(found and 'avd-fw>=0.1.aurora4' in found[0], found)

    def test_an_aurora_package_testing_dropped_is_refused(self):
        # avd-fw is an Aurora recipe: it must come from Aurora's feeds, not from upstream.
        self.overlay[0]['depends'] = ['avd-fw>=0.1.aurora4', 'kmod']
        self.testing = [row for row in self.testing if row['name'] != 'avd-fw']
        found = self.problems()
        self.assertTrue(found and 'avd-fw' in found[0] and 'Testing' in found[0], found)

    def test_an_upstream_depend_no_repository_serves_is_refused(self):
        self.upstream = [row for row in self.upstream if row.name != 'libdrm']
        found = self.problems()
        self.assertTrue(found and 'libdrm' in found[0] and 'Arch Linux ARM' in found[0], found)

    def test_a_testing_floor_above_the_edge_kernel_is_refused(self):
        self.testing[2]['depends'] = ['linux-aurora>=7.3.0.aurora1-44']
        found = self.problems()
        self.assertTrue(found and 'aurora-boot' in found[0] and 'Testing copy' in found[0], found)

    def test_a_testing_conflict_with_the_edge_kernel_is_refused(self):
        self.testing.append(package('aurora-sep', '0.3-1', conflicts=('linux-aurora<7.3.0.aurora1-44',)))
        found = self.problems()
        self.assertTrue(found and 'aurora-sep' in found[0], found)

    def test_an_overlay_provide_satisfies_testing(self):
        self.testing.append(package('mesa-demos', '9.0-1', depends=('mesa>=26.3',)))
        self.assertEqual(self.problems(), [])
        self.testing[-1]['depends'] = ['mesa>=27']
        self.assertTrue(self.problems())

    def test_aurora_names_come_from_every_recipe_in_the_repository(self):
        names = closure.aurora_names(ROOT)
        for name in ('avd-fw', 'linux-aurora', 'aurora-userpages', 'vulkan-aurora', 'alsa-card-profiles',
                     'aurora-stage2-trial', 'linux-asahi'):
            self.assertIn(name, names)
        self.assertNotIn('kmod', names)

    def test_a_missing_or_unreadable_database_fails_the_deploy(self):
        with tempfile.TemporaryDirectory() as temporary:
            served = Path(temporary) / 'site'
            (served / 'edge/aarch64').mkdir(parents=True)
            (served / 'testing/aarch64').mkdir(parents=True)
            (served / 'testing/aarch64/aurora.db.tar.gz').write_bytes(b'not a pacman database')
            with self.assertRaisesRegex(SystemExit, 'close over'):
                site.check_closure(served)
            (served / 'edge/aarch64/aurora-edge.db.tar.gz').write_bytes(b'not a pacman database either')
            with self.assertRaisesRegex(SystemExit, 'close over'):
                site.check_closure(served)

    def test_the_deploy_runs_the_check_whenever_both_feeds_are_served(self):
        text = (ROOT / 'scripts/channel-site.py').read_text()
        self.assertIn("if target.get('edge') and target.get('testing'):\n        check_closure(site)", text)


class SplitPackageTests(unittest.TestCase):
    def test_pkgname_is_read_without_running_the_recipe(self):
        self.assertEqual(edgelib.pkgnames((ROOT / 'packages/linux-aurora/PKGBUILD').read_text()),
                         ['linux-aurora', 'linux-aurora-headers', 'aurora-userpages'])
        self.assertEqual(edgelib.pkgnames((ROOT / 'packages/mesa-aurora/PKGBUILD').read_text()),
                         ['mesa-aurora', 'vulkan-aurora', 'opencl-rusticl-aurora', 'vulkan-lavapipe-aurora'])
        self.assertEqual(edgelib.pkgnames('pkgname=aurora-flatpak-gl\n'), ['aurora-flatpak-gl'])
        with self.assertRaisesRegex(ValueError, 'pkgname'):
            edgelib.pkgnames('pkgname=("$other")\n')

    def test_every_recipe_in_the_repository_is_readable(self):
        for recipe in sorted((ROOT / 'packages').glob('*/PKGBUILD')):
            with self.subTest(recipe=recipe.parent.name):
                self.assertTrue(edgelib.pkgnames(recipe.read_text()))
        self.assertIn('alsa-card-profiles', edgelib.pkgnames((ROOT / 'packages/pipewire/PKGBUILD').read_text()))

    def test_literal_provides_are_read_and_computed_ones_left_to_the_databases(self):
        text = '''pkgbase=linux-aurora
provides=(WIREGUARD-MODULE linux-asahi=${pkgver} "${_ctxr_provides[@]}")
  provides=("vulkan-asahi=$epoch:$pkgver" 'vulkan-driver'
            libvulkan_lvp.so  # trailing comment
            lib$_pwname.so)
'''
        self.assertEqual(edgelib.provided_names(text),
                         ['WIREGUARD-MODULE', 'linux-asahi', 'vulkan-asahi', 'vulkan-driver', 'libvulkan_lvp.so'])

    def test_every_split_package_must_be_in_the_overlay(self):
        expected = ['linux-aurora', 'linux-aurora-headers', 'aurora-userpages']
        edgelib.check_complete(['aurora-userpages', 'linux-aurora', 'linux-aurora-headers'], expected)
        with self.assertRaisesRegex(ValueError, 'linux-aurora-headers'):
            edgelib.check_complete(['linux-aurora', 'aurora-userpages'], expected)
        with self.assertRaisesRegex(ValueError, 'extra'):
            edgelib.check_complete(expected + ['linux-aurora-docs'], expected)


class EdgeDocsTests(unittest.TestCase):
    def test_docs_state_what_alarm_edge_qualifies_and_how_to_roll_back(self):
        text = (ROOT / 'docs/updates.md').read_text()
        self.assertIn('qualifies only the kernel and Mesa', text)
        self.assertIn('epoch', text)
