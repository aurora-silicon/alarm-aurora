import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys as _sys
_sys.dont_write_bytecode = True  # scripts/ is scanned with bash -n in CI

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('request_builds', ROOT / 'scripts/request-builds.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REPOSITORY = 'aurora-silicon/alarm-aurora'
MISSING = ['alarm-aura', 'alarm-linux-aurora', 'alarm-mesa-aurora']


class RequestBuildsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in module.resolve.collect.SHARED:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('builder\n')
        for name in ('aura', 'mesa-aurora', 'linux-aurora'):
            recipe = self.root / 'packages' / name / 'PKGBUILD'
            recipe.parent.mkdir(parents=True)
            recipe.write_text('pkgrel=1\n')
        (self.root / 'sources.json').write_text(json.dumps({'aura': {'commit': '1'}}))
        self.git('init', '-q')
        self.head = self.commit()
        self.runs, self.jobs = [], {}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@example.org', 'commit', '-qm', 'step')
        return self.git('rev-parse', 'HEAD')

    def add_run(self, run_id, status='completed', conclusion='failure', sha=None, jobs=(), event='push', attempt=1):
        """A packages.yml run with `jobs` given as (name, conclusion or None) pairs; newest last."""
        record = {'id': run_id, 'head_sha': sha or self.head, 'head_branch': 'main', 'event': event,
                  'path': '.github/workflows/packages.yml', 'head_repository': {'full_name': REPOSITORY},
                  'created_at': f'2026-11-21T00:{run_id:02d}:00Z', 'status': status,
                  'conclusion': conclusion if status == 'completed' else None, 'run_attempt': attempt}
        self.runs.insert(0, record)
        self.jobs[run_id] = [{'name': name, 'status': 'completed' if result else 'in_progress',
                              'conclusion': result, 'html_url': f'https://example.org/job/{run_id}/{name}'}
                             for name, result in jobs]
        return record

    def decide(self, missing=MISSING, **limits):
        return module.decide(self.root, REPOSITORY, missing, self.runs, lambda run_id: self.jobs[run_id], **limits)

    def main(self):
        """Run the script as publish.yml does; return (dispatched package lists, output, exit status).
        Re-run requests are kept in self.reruns."""
        plan = self.root / 'build-plan.json'
        plan.write_text(json.dumps({'action': 'missing', 'missing': MISSING}))
        dispatched = []

        def api(route, paginate=False):
            if route.endswith('/jobs?per_page=100'):
                return [{'jobs': self.jobs[int(route.split('/')[-2])]}]
            return {'workflow_runs': list(self.runs)}

        self.reruns = []

        def gh(*args):
            if args[:2] == ('run', 'rerun'):
                self.assertEqual(args[3:], ('--repo', REPOSITORY, '--failed'))
                self.reruns.append(int(args[2]))
                return
            self.assertEqual(args[:6], ('workflow', 'run', 'packages.yml', '--repo', REPOSITORY, '--ref'))
            dispatched.append(args[-1].removeprefix('packages=').split())

        output, status = io.StringIO(), 0
        argv = ['request-builds.py', '--repository', REPOSITORY, '--plan', str(plan)]
        with patch.object(module, 'ROOT', self.root), patch.object(module.lib, 'gh_api', api), \
                patch.object(module.lib, 'gh', gh), patch.object(_sys, 'argv', argv), \
                contextlib.redirect_stdout(output):
            try:
                module.main()
            except SystemExit as error:
                status = error.code
        return dispatched, output.getvalue(), status

    def test_nothing_built_requests_every_missing_recipe_in_one_run(self):
        dispatched, output, status = self.main()
        self.assertEqual(dispatched, [['aura', 'linux-aurora', 'mesa-aurora']])
        self.assertIn('Requested on main: aura linux-aurora mesa-aurora', output)
        self.assertEqual(status, 0)

    def test_an_active_build_of_todays_recipe_is_left_to_make_it(self):
        # A long kernel build on main must not hold back everything else.
        self.add_run(1, status='in_progress', jobs=[('metadata', 'success'), ('build (linux-aurora)', None)])
        decision = self.decide()
        self.assertEqual(list(decision['covered']), ['alarm-linux-aurora'])
        self.assertEqual(decision['fresh'], ['alarm-aura', 'alarm-mesa-aurora'])
        dispatched, output, _ = self.main()
        self.assertEqual(dispatched, [['aura', 'mesa-aurora']])
        self.assertIn('Building in [run 1]', output)

    def test_a_second_publication_does_not_stack_a_duplicate_request(self):
        first, _, _ = self.main()
        self.assertEqual(len(first), 1)
        # The requested run exists but has not expanded its matrix yet.
        self.add_run(2, status='queued', event='workflow_dispatch', jobs=[('metadata', None)])
        second, output, _ = self.main()
        self.assertEqual(second, [])
        self.assertIn('has not planned its builds yet', output)
        # Once planned, it covers exactly what it builds.
        self.jobs[2] = [{'name': 'metadata', 'status': 'completed', 'conclusion': 'success'}] + [
            {'name': f'build ({name.removeprefix("alarm-")})', 'status': 'queued', 'conclusion': None}
            for name in MISSING]
        third, _, _ = self.main()
        self.assertEqual(third, [])

    def test_an_active_run_with_a_failed_job_makes_nothing(self):
        self.add_run(1, status='in_progress', jobs=[('metadata', 'success'), ('build (aura)', None),
                                                ('build (mesa-aurora)', 'failure')])
        decision = self.decide()
        self.assertEqual(decision['covered'], {})
        self.assertEqual(decision['fresh'], ['alarm-aura', 'alarm-linux-aurora'])
        self.assertEqual(decision['retry'], ['alarm-mesa-aurora'])

    def test_a_build_of_an_older_recipe_does_not_count(self):
        self.add_run(1, status='in_progress', jobs=[('metadata', 'success'), ('build (aura)', None)])
        (self.root / 'packages/aura/PKGBUILD').write_text('pkgrel=2\n')
        self.head = self.commit()
        decision = self.decide()
        self.assertEqual(decision['covered'], {})
        self.assertIn('alarm-aura', decision['fresh'])

    def test_a_run_that_failed_in_one_build_has_only_that_job_re_run(self):
        # One mirror timeout must not cost a full rebuild of the run's other recipes.
        self.add_run(1, jobs=[('metadata', 'success'), ('build (aura)', 'success'), ('build (mesa-aurora)', 'failure'),
                              ('build (linux-aurora)', 'success')])
        dispatched, output, status = self.main()
        self.assertEqual(dispatched, [])
        self.assertEqual(self.reruns, [1])
        self.assertIn('Re-running the failed jobs of [run 1]', output)
        self.assertIn('(attempt 2) so its builds count: aura linux-aurora mesa-aurora', output)
        self.assertEqual(status, 0)
        # While the re-run attempt runs, the next publication leaves it alone.
        self.runs[0].update(status='queued', conclusion=None, run_attempt=2)
        self.jobs[1][2].update(status='queued', conclusion=None)
        again, _, _ = self.main()
        self.assertEqual((again, self.reruns), ([], []))

    def test_a_recipe_that_failed_once_is_retried_apart_from_the_others(self):
        # Once the run's re-run attempts are spent, its good builds are requested again apart
        # from the recipe that failed.
        self.add_run(1, attempt=module.MAX_ATTEMPTS,
                     jobs=[('metadata', 'success'), ('build (aura)', 'success'), ('build (mesa-aurora)', 'failure'),
                           ('build (linux-aurora)', 'success')])
        dispatched, output, status = self.main()
        self.assertEqual(self.reruns, [])
        self.assertEqual(dispatched, [['aura', 'linux-aurora'], ['mesa-aurora']])
        self.assertIn('Requested again on main, in a run of their own: mesa-aurora', output)
        self.assertIn('mesa-aurora: its last build of this recipe failed ([run 1](https://example.org/job/1/', output)
        self.assertEqual(status, 0)

    def test_a_recipe_that_keeps_failing_is_named_and_not_requested_again(self):
        # The uboot-aurora case: every full rebuild failed on the same recipe.
        for run_id in (1, 2):
            self.add_run(run_id, jobs=[('metadata', 'success'), ('build (aura)', 'success'),
                                   ('build (mesa-aurora)', 'success'), ('build (linux-aurora)', 'failure')])
        dispatched, output, status = self.main()
        self.assertEqual(dispatched, [['aura', 'mesa-aurora']])
        self.assertEqual(self.reruns, [])  # a recipe out of retries is not re-run either
        self.assertIn('**linux-aurora is not requested again**: its build of this recipe failed 2 times in a row', output)
        self.assertIn('::error::linux-aurora failed to build 2 times in a row', output)
        self.assertEqual(status, 1)

    def test_a_newer_successful_build_resets_the_failure_count(self):
        self.add_run(1, jobs=[('metadata', 'success'), ('build (linux-aurora)', 'failure')])
        self.add_run(2, jobs=[('metadata', 'success'), ('build (linux-aurora)', 'success'), ('build (aura)', 'failure')])
        self.add_run(3, jobs=[('metadata', 'success'), ('build (linux-aurora)', 'failure')])
        decision = self.decide(max_attempts=1)
        self.assertEqual(decision['retry'], ['alarm-aura', 'alarm-linux-aurora'])
        self.assertEqual(decision['exhausted'], [])
        # With attempts left, each failed run that holds a recipe's newest build is re-run instead.
        reruns = {item['run']['id']: item['recipes'] for item in self.decide()['reruns']}
        self.assertEqual(reruns, {3: ['alarm-linux-aurora'], 2: ['alarm-aura']})

    def test_a_fixed_recipe_starts_with_no_failures(self):
        for run_id in (1, 2):
            self.add_run(run_id, jobs=[('metadata', 'success'), ('build (linux-aurora)', 'failure')])
        (self.root / 'packages/linux-aurora/PKGBUILD').write_text('pkgrel=2\n')
        self.head = self.commit()
        self.assertIn('alarm-linux-aurora', self.decide()['fresh'])

    def test_runs_failing_outside_the_builds_stop_the_requests(self):
        # Each failed run starts publication again; a broken check must not loop.
        for run_id in (1, 2):
            self.add_run(run_id, event='workflow_dispatch', jobs=[('metadata', 'failure'), ('fex-overlay', 'success')])
        dispatched, output, status = self.main()
        self.assertEqual(dispatched, [])
        self.assertIn('failed outside the package builds**: [metadata](https://example.org/job/2/metadata)', output)
        self.assertEqual(status, 1)
        # One such failure, or a newer run that got through, is not enough to stop.
        self.add_run(3, jobs=[('metadata', 'success'), ('build (aura)', 'failure')])
        self.assertEqual(self.decide()['broken'], [])

    def test_pull_request_and_unmerged_runs_are_ignored(self):
        self.add_run(1, status='in_progress', event='pull_request', jobs=[('metadata', None)])
        self.git('checkout', '-q', '-b', 'side')
        (self.root / 'README').write_text('side\n')
        side = self.commit()
        self.git('checkout', '-q', '-')
        self.add_run(2, status='in_progress', event='workflow_dispatch', sha=side, jobs=[('metadata', None)])
        decision = self.decide()
        self.assertEqual(decision['waiting'], [])
        self.assertEqual(decision['fresh'], MISSING)


class WorkflowTests(unittest.TestCase):
    def test_publication_hands_the_decision_to_the_script(self):
        workflow = (ROOT / '.github/workflows/publish.yml').read_text()
        job = workflow.split('\n  request-builds:\n', 1)[1].split('\n  collect:\n', 1)[0]
        self.assertIn('python3 scripts/request-builds.py --repository "$GITHUB_REPOSITORY" --plan build-plan.json', job)
        self.assertIn('fetch-depth: 0', job)
        self.assertNotIn('select(.status != "completed")', job)
        # A failed main build plans again, so it is retried or named, not left for the schedule.
        plan = workflow.split('\n  plan:\n', 1)[1].split('\n    runs-on:', 1)[0]
        self.assertIn("github.event.workflow_run.conclusion == 'failure'", plan)


if __name__ == '__main__':
    unittest.main()
