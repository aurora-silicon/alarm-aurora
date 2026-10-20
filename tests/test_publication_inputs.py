import hashlib
import types
import json
from contextlib import chdir
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / 'scripts/collect-publication-inputs.py'
module = types.ModuleType('publication')
module.__file__ = str(script)
# Load the fixture without leaving bytecode in the shell-script scan directory.
exec(compile(script.read_text(), str(script), 'exec'), module.__dict__)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in module.SHARED:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('unchanged build input\n')
        for name in ('linux-aurora', 'firstboot', 'mesa'):
            file = self.root / 'packages' / name / 'PKGBUILD'
            file.parent.mkdir(parents=True)
            file.write_text('pkgver=1\n')
        (self.root / 'sources.json').write_text(json.dumps({'kernel-aurora': {'commit': 'a'}, 'firstboot': {'commit': 'b'}}))
        self.git('init', '-q')
        self.commit()
        self.metadata = {'head_sha': self.git('rev-parse', 'HEAD'), 'head_branch': 'main', 'conclusion': 'success',
                         'head_repository': {'full_name': 'aurora-silicon/alarm-aurora'}, 'path': '.github/workflows/packages.yml', 'event': 'push'}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.org', 'commit', '-qm', 'fixture')

    def eligible(self, metadata=None):
        return module.eligible_recipes(self.root, metadata or self.metadata, 'aurora-silicon/alarm-aurora')

    def test_publisher_only_changes_reuse_all_recipes(self):
        (self.root / '.github/workflows/publish.yml').write_text('new publisher\n')
        self.commit()
        self.assertEqual(self.eligible(), {'alarm-linux-aurora', 'alarm-firstboot', 'alarm-mesa'})

    def test_manual_branch_build_can_be_reused_only_after_its_commit_is_merged(self):
        manual = {**self.metadata, 'head_branch': 'update/kernel', 'event': 'workflow_dispatch'}
        self.assertEqual(self.eligible(manual), {'alarm-linux-aurora', 'alarm-firstboot', 'alarm-mesa'})
        (self.root / 'README').write_text('not merged\n')
        self.commit()
        manual['head_sha'] = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '--detach', self.metadata['head_sha'])
        with self.assertRaisesRegex(ValueError, 'not merged'):
            self.eligible(manual)

    def test_changed_recipe_or_source_pin_cannot_reuse_its_old_artifact(self):
        (self.root / 'packages/firstboot/PKGBUILD').write_text('pkgver=2\n')
        pins = json.loads((self.root / 'sources.json').read_text())
        pins['kernel-aurora']['commit'] = 'new'
        (self.root / 'sources.json').write_text(json.dumps(pins))
        self.commit()
        self.assertEqual(self.eligible(), {'alarm-mesa'})

    def test_builder_changes_and_foreign_failed_or_unmerged_runs_are_rejected(self):
        for updates in [{'conclusion': 'failure'}, {'head_branch': 'other'}, {'event': 'pull_request'},
                        {'head_repository': {'full_name': 'other/repo'}}, {'path': '.github/workflows/other.yml'}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.eligible({**self.metadata, **updates})
        (self.root / module.SHARED[0]).write_text('new builder\n')
        self.commit()
        with self.assertRaises(ValueError):
            self.eligible()
        foreign = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '--detach', self.metadata['head_sha'])
        with self.assertRaises(ValueError):
            self.eligible({**self.metadata, 'head_sha': foreign})

    def artifact(self, name, content):
        archive = self.root / name
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('build.log', 'log only is not a package')
            for path, data in content.items():
                z.writestr(path, data)
        return archive, {'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}

    def test_artifact_digest_duplicate_bytes_and_actual_package_are_checked(self):
        output = self.root / 'out'
        output.mkdir()
        archive, metadata = self.artifact('first.zip', {'out/packages/test-1-aarch64.pkg.tar.zst': b'package'})
        self.assertEqual(module.collect_archive(archive, metadata, output), ['test-1-aarch64.pkg.tar.zst'])
        module.collect_archive(archive, metadata, output)
        with self.assertRaises(ValueError):
            module.collect_archive(archive, {'digest': 'sha256:' + '0' * 64}, output)
        conflict, other = self.artifact('conflict.zip', {'test-1-aarch64.pkg.tar.zst': b'different'})
        with self.assertRaises(ValueError):
            module.collect_archive(conflict, other, output)
        thin, thin_metadata = self.artifact('thin.zip', {})
        self.assertEqual(module.collect_archive(thin, thin_metadata, output), [])
        self.assertEqual((output / 'test-1-aarch64.pkg.tar.zst').read_bytes(), b'package')
        self.assertEqual(list(output.glob('*.incoming')), [])

    def collect_fixture(self, log_only):
        artifacts = []
        sources = {}
        for index, name in enumerate(('linux-aurora', 'firstboot', 'mesa'), 1):
            files = {} if log_only and name == 'firstboot' else {name + '-1-aarch64.pkg.tar.zst': name.encode()}
            archive, metadata = self.artifact(name + '.zip', files)
            sources[str(index)] = archive
            artifacts.append({**metadata, 'id': index, 'name': 'alarm-' + name,
                              'expired': False, 'size_in_bytes': archive.stat().st_size})
        metadata = {**self.metadata, 'id': 99}
        original = subprocess.run

        def download(args, **kwargs):
            if args[:2] == ['gh', 'api']:
                artifact = args[2].split('/')[-2]
                kwargs['stdout'].write(sources[artifact].read_bytes())
                return subprocess.CompletedProcess(args, 0)
            return original(args, **kwargs)

        def api(*args):
            return [{'artifacts': artifacts}] if 'artifacts?' in args[-1] else metadata

        with chdir(self.root), patch.object(module, '__file__', str(self.root / 'scripts/collect-publication-inputs.py')), \
                patch.object(module, 'gh_json', side_effect=api), patch.object(subprocess, 'run', side_effect=download), \
                patch('sys.argv', ['collect', '--runs', '99', '--repository', 'aurora-silicon/alarm-aurora', '--output', 'complete']):
            module.main()

    def test_complete_collector_rejects_a_log_only_recipe_artifact(self):
        with self.assertRaisesRegex(ValueError, 'no actual package'):
            self.collect_fixture(True)
        self.assertFalse((self.root / 'publication-inputs.json').exists())

    def test_complete_collector_records_every_authenticated_recipe(self):
        self.collect_fixture(False)
        record = json.loads((self.root / 'publication-inputs.json').read_text())
        self.assertEqual(len(record['artifacts']), 3)
        self.assertEqual({a['name'] for a in record['artifacts']}, {'alarm-linux-aurora', 'alarm-firstboot', 'alarm-mesa'})
        self.assertTrue(all(a['packages'] for a in record['artifacts']))
        self.assertEqual(len(list((self.root / 'complete').glob('*.pkg.tar.zst'))), 3)


if __name__ == '__main__':
    unittest.main()
