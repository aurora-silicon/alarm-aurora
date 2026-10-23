import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys as _sys
_sys.dont_write_bytecode = True  # scripts/ is scanned with bash -n in CI

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resolve_build_runs', ROOT / 'scripts/resolve-build-runs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REPOSITORY = 'aurora-silicon/alarm-aurora'


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in module.collect.SHARED:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('builder\n')
        for name in ('aura', 'mesa-aurora', 'linux-aurora'):
            recipe = self.root / 'packages' / name / 'PKGBUILD'
            recipe.parent.mkdir(parents=True)
            recipe.write_text('pkgrel=1\n')
        (self.root / 'sources.json').write_text(json.dumps({'aura': {'commit': '1'}}))
        self.git('init', '-q')
        self.first = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@example.org', 'commit', '-qm', 'step')
        return self.git('rev-parse', 'HEAD')

    def run_record(self, run_id, sha, created):
        return {'id': run_id, 'head_sha': sha, 'head_branch': 'main', 'conclusion': 'success', 'event': 'push',
                'path': '.github/workflows/packages.yml', 'created_at': created,
                'head_repository': {'full_name': REPOSITORY}}

    def artifacts(self, mapping):
        def lookup(run_id):
            return {name: {'id': run_id * 10 + index, 'name': name, 'digest': 'sha256:x', 'size_in_bytes': 1}
                    for index, name in enumerate(mapping.get(run_id, []))}
        return lookup

    def resolve(self, runs, artifacts, base=None):
        with patch.object(module, 'ROOT', self.root):
            return module.resolve(self.root, REPOSITORY, runs, artifacts, 'testing-1' if base else None, base)

    def test_newest_qualifying_build_per_recipe_wins(self):
        full = self.run_record(1, self.first, '2026-10-20T00:00:00Z')
        (self.root / 'packages/aura/PKGBUILD').write_text('pkgrel=2\n')
        second = self.commit()
        aura_only = self.run_record(2, second, '2026-10-21T00:00:00Z')
        runs = [aura_only, full]
        plan = self.resolve(runs, self.artifacts({1: ['alarm-aura', 'alarm-mesa-aurora', 'alarm-linux-aurora'],
                                                  2: ['alarm-aura']}))
        self.assertEqual(plan['action'], 'publish')
        self.assertEqual(plan['recipes']['alarm-aura']['run'], 2)
        self.assertEqual(plan['recipes']['alarm-mesa-aurora']['run'], 1)
        self.assertEqual(plan['runs'], [1, 2])

    def test_changed_recipe_without_a_new_build_is_missing(self):
        full = self.run_record(1, self.first, '2026-10-20T00:00:00Z')
        (self.root / 'packages/aura/PKGBUILD').write_text('pkgrel=2\n')
        self.commit()
        plan = self.resolve([full], self.artifacts({1: ['alarm-aura', 'alarm-mesa-aurora', 'alarm-linux-aurora']}))
        self.assertEqual(plan['action'], 'missing')
        self.assertEqual(plan['rebuild'], ['aura'])

    def test_builder_change_invalidates_every_build(self):
        full = self.run_record(1, self.first, '2026-10-20T00:00:00Z')
        (self.root / module.collect.SHARED[0]).write_text('new builder\n')
        self.commit()
        plan = self.resolve([full], self.artifacts({1: ['alarm-aura', 'alarm-mesa-aurora', 'alarm-linux-aurora']}))
        self.assertEqual(sorted(plan['rebuild']), ['aura', 'linux-aurora', 'mesa-aurora'])

    def test_snapshot_carries_unchanged_recipes_and_detects_no_change(self):
        base = {name: {'name': name, 'build_run': 1, 'artifact_id': 10 + index, 'head_sha': self.first,
                       'packages': [name + '.pkg.tar.xz']}
                for index, name in enumerate(['alarm-aura', 'alarm-mesa-aurora', 'alarm-linux-aurora'])}
        plan = self.resolve([], self.artifacts({}), base)
        self.assertEqual(plan['action'], 'up-to-date')
        self.assertTrue(all(item['base'] == 'testing-1' for item in plan['recipes'].values()))
        (self.root / 'packages/aura/PKGBUILD').write_text('pkgrel=2\n')
        second = self.commit()
        plan = self.resolve([self.run_record(2, second, '2026-10-21T00:00:00Z')],
                            self.artifacts({2: ['alarm-aura']}), base)
        self.assertEqual(plan['action'], 'publish')
        self.assertEqual(plan['recipes']['alarm-aura']['run'], 2)
        self.assertEqual(plan['recipes']['alarm-mesa-aurora']['base'], 'testing-1')

    def test_failed_or_foreign_runs_are_ignored(self):
        bad = [{**self.run_record(1, self.first, '2026-10-20T00:00:00Z'), 'conclusion': 'failure'},
               {**self.run_record(2, self.first, '2026-10-20T00:00:00Z'), 'event': 'pull_request'},
               {**self.run_record(3, self.first, '2026-10-20T00:00:00Z'),
                'head_repository': {'full_name': 'fork/alarm-aurora'}}]
        plan = self.resolve(bad, self.artifacts({1: ['alarm-aura'], 2: ['alarm-aura'], 3: ['alarm-aura']}))
        self.assertEqual(plan['action'], 'missing')
        self.assertEqual(len(plan['rebuild']), 3)


class NewestArtifactTests(unittest.TestCase):
    def test_rerun_upload_replaces_the_failed_attempt(self):
        pages = [{'artifacts': [
            {'id': 1, 'name': 'alarm-aura', 'created_at': '2026-10-22T08:26:25Z', 'expired': False},
            {'id': 2, 'name': 'alarm-aura', 'created_at': '2026-10-22T09:29:35Z', 'expired': False},
            {'id': 3, 'name': 'alarm-mesa', 'created_at': '2026-10-22T09:00:00Z', 'expired': True}]}]
        newest = module.newest_artifacts(REPOSITORY, 7, api=lambda route, paginate=False: pages)
        self.assertEqual(newest['alarm-aura']['id'], 2)
        self.assertNotIn('alarm-mesa', newest)


if __name__ == '__main__':
    unittest.main()
