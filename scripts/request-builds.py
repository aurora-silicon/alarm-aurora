#!/usr/bin/env python3
"""Request native builds for the recipes a publication is missing, once.

publish.yml's plan names every recipe that has no publishable build
(`missing` in build-plan.json). For each one this decides:

  - An active packages.yml run that builds it from today's recipe makes it:
    nothing is requested, and that run's completion starts publication again.
    A run with a failed or cancelled job concludes failure, so it makes
    nothing.
  - While an active run has not planned its matrix yet, nothing is requested
    at all: it may be the run an earlier publication asked for.
  - A recipe whose newest build of today's recipe failed is requested again in
    a run of its own, so it cannot fail the run of the others. After
    MAX_FAILURES such failures in a row it is not requested again; it is named
    with its failed jobs and the step fails, because only a change (or a
    deliberate re-run) can fix it.
  - A run that failed only in builds of today's recipes, each of them still
    under MAX_FAILURES, has just its failed jobs re-run (up to MAX_ATTEMPTS
    attempts) when it holds the newest build of the recipes it would supply:
    once they pass, the run concludes success and all its builds count.
  - Every other recipe is requested in one run.
  - After MAX_FAILURES runs in a row failed outside the package builds (the
    metadata checks, the overlay or Touch ID upgrade tests), nothing is
    requested: another run would fail the same way, and each failure starts
    publication again.

"Today's recipe" is the rule publication uses (collect-publication-inputs.py):
the run's commit is merged, and the build tooling, the recipe and its source
pin are unchanged since.

    request-builds.py --repository OWNER/NAME --plan build-plan.json [--summary FILE] [--dry-run]
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

_spec = importlib.util.spec_from_file_location('resolve', ROOT / 'scripts/resolve-build-runs.py')
resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve)

WORKFLOW = 'packages.yml'
MAX_FAILURES = 2
MAX_ATTEMPTS = 3
FAILED = {'failure', 'timed_out', 'startup_failure'}
BUILD_JOB = re.compile(r'build \((.+)\)')


def same_inputs(root, run, repository):
    """Recipes the run builds from today's inputs, whatever its conclusion."""
    return resolve.eligible(root, {**run, 'conclusion': 'success'}, repository)


def builds(jobs):
    """{recipe: job} for the run's matrix builds."""
    return {'alarm-' + match[1]: job for job in jobs if (match := BUILD_JOB.fullmatch(job.get('name', '')))}


def planned(jobs):
    """Whether the matrix exists yet: a skipped one is a single job named "build"."""
    return any(job.get('name') == 'build' or BUILD_JOB.fullmatch(job.get('name', '')) for job in jobs)


def decide(root, repository, missing, runs, jobs_for, max_failures=MAX_FAILURES, max_attempts=MAX_ATTEMPTS):
    """What to do for each missing recipe, from runs newest first."""
    missing = list(missing)
    covered, waiting, failures, settled = {}, [], {name: [] for name in missing}, set()
    broken, works = [], False  # runs that failed outside the builds; a newer run that did not
    history, newest = [], {}  # failed runs, and the newest of them that built each recipe
    for run in runs:
        current = same_inputs(root, run, repository)
        inputs = current & set(missing)
        if not inputs:
            continue
        if run.get('status') == 'completed' and run.get('conclusion') == 'success':
            works = True
            continue
        jobs = jobs_for(run['id'])
        built = builds(jobs)
        doomed = any(job.get('conclusion') in FAILED | {'cancelled'} for job in jobs)
        if run.get('status') != 'completed' and not doomed:
            if not planned(jobs):
                waiting.append(run)
                continue
            for name in inputs & built.keys():
                covered.setdefault(name, run)
            continue
        # A run that concluded (or will conclude) failure: its builds are history.
        outside = [job for job in jobs
                   if job.get('conclusion') in FAILED and not BUILD_JOB.fullmatch(job.get('name', ''))]
        if outside and not works:
            broken.append({'run': run, 'jobs': outside})
        elif any(job.get('conclusion') in FAILED | {'success'} for job in built.values()):
            works = True
        history.append({'run': run, 'current': current, 'built': built, 'outside': outside})
        for name in sorted(inputs & built.keys()):
            if name in covered or name in settled:
                continue
            newest.setdefault(name, run['id'])
            conclusion = built[name].get('conclusion')
            if conclusion in FAILED:
                failures[name].append({**built[name], 'run': run})
            elif conclusion == 'success':
                settled.add(name)
    # Re-running only a run's failed jobs makes every other build of it count. That
    # needs each failed job to be a build of today's recipe that may still be retried,
    # and the run to hold the newest build of the recipes it would supply.
    reruns = []
    for item in history:
        run, built = item['run'], item['built']
        failed = {name for name, job in built.items() if job.get('conclusion') in FAILED}
        supplies = [name for name in missing if name not in covered and newest.get(name) == run['id']]
        if (run.get('status') != 'completed' or run.get('conclusion') != 'failure' or item['outside']
                or run.get('run_attempt', 1) >= max_attempts or not failed or not failed <= item['current']
                or any(len(failures.get(name, ())) >= max_failures for name in failed)
                or not (failed & set(missing)) <= set(supplies) or not supplies):
            continue
        reruns.append({'run': run, 'recipes': supplies})
        for name in supplies:
            covered[name] = run
    rerun_ids = {item['run']['id'] for item in reruns}
    left = [name for name in missing if name not in covered]
    return {
        'covered': {name: covered[name] for name in missing
                    if name in covered and covered[name]['id'] not in rerun_ids},
        'reruns': reruns,
        'waiting': waiting,
        'fresh': [name for name in left if not failures[name]],
        'retry': [name for name in left if 0 < len(failures[name]) < max_failures],
        'exhausted': [name for name in left if len(failures[name]) >= max_failures],
        'failures': {name: jobs for name, jobs in failures.items() if jobs and name in left},
        'broken': broken if len(broken) >= max_failures else [],
    }


def report(decision, repository, requested):
    url = f'https://github.com/{repository}/actions/runs'
    lines = ['### Native builds this publication is missing', '']
    by_run = {}
    for name, run in decision['covered'].items():
        by_run.setdefault(run['id'], []).append(name.removeprefix('alarm-'))
    for run_id, names in by_run.items():
        lines.append(f'- Building in [run {run_id}]({url}/{run_id}): {" ".join(names)}')
    for item in decision['reruns']:
        run = item['run']
        lines.append(f'- Re-running the failed jobs of [run {run["id"]}]({url}/{run["id"]}) '
                     f'(attempt {run.get("run_attempt", 1) + 1}) so its builds count: '
                     f'{" ".join(name.removeprefix("alarm-") for name in item["recipes"])}')
    for run in decision['waiting']:
        lines.append(f'- [Run {run["id"]}]({url}/{run["id"]}) has not planned its builds yet; '
                     'nothing is requested until it has.')
    for label, names in requested:
        lines.append(f'- {label}: {" ".join(name.removeprefix("alarm-") for name in names)}')
    for item in decision['broken']:
        jobs = ', '.join(f'[{job["name"]}]({job.get("html_url") or url + "/" + str(item["run"]["id"])})'
                         for job in item['jobs'])
        lines.append(f'- **[Run {item["run"]["id"]}]({url}/{item["run"]["id"]}) failed outside the package '
                     f'builds**: {jobs}.')
    if decision['broken']:
        lines.append(f'- Nothing is requested: the last {len(decision["broken"])} runs failed before their builds '
                     'could count. Fix that first.')
    for name in decision['retry'] + decision['exhausted']:
        jobs = ', '.join(f'[run {job["run"]["id"]}]({job.get("html_url") or url + "/" + str(job["run"]["id"])})'
                         for job in decision['failures'][name])
        short = name.removeprefix('alarm-')
        if name in decision['exhausted']:
            lines.append(f'- **{short} is not requested again**: its build of this recipe failed '
                         f'{len(decision["failures"][name])} times in a row ({jobs}). Fix the recipe, '
                         'or re-run those jobs if the failure was transient.')
        else:
            lines.append(f'- {short}: its last build of this recipe failed ({jobs}).')
    return '\n'.join(lines) + '\n'


def request(repository, names, dry_run):
    if names and not dry_run:
        lib.gh('workflow', 'run', WORKFLOW, '--repo', repository, '--ref', 'main',
               '-f', 'packages=' + ' '.join(name.removeprefix('alarm-') for name in names))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--summary', type=Path, help='append the Markdown report here')
    parser.add_argument('--dry-run', action='store_true', help='decide and report; request nothing')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name')
    plan = json.loads(args.plan.read_text())
    if plan.get('action') != 'missing' or not plan.get('missing'):
        print('Nothing is missing.')
        return
    runs = lib.gh_api(f'repos/{args.repository}/actions/workflows/{WORKFLOW}/runs?per_page=100')['workflow_runs']
    runs = sorted(runs, key=lambda run: (run['created_at'], run['id']), reverse=True)

    def jobs_for(run_id):
        pages = lib.gh_api(f'repos/{args.repository}/actions/runs/{run_id}/jobs?per_page=100', paginate=True)
        return [job for page in pages for job in page['jobs']]

    decision = decide(ROOT, args.repository, plan['missing'], runs, jobs_for)
    if decision['waiting'] or decision['broken']:
        decision['reruns'] = []
    requested = []
    if not decision['waiting'] and not decision['broken']:
        for item in decision['reruns']:
            if not args.dry_run:
                lib.gh('run', 'rerun', str(item['run']['id']), '--repo', args.repository, '--failed')
        if decision['fresh']:
            request(args.repository, decision['fresh'], args.dry_run)
            requested.append(('Requested on main', decision['fresh']))
        if decision['retry']:
            request(args.repository, decision['retry'], args.dry_run)
            requested.append(('Requested again on main, in a run of their own', decision['retry']))
    text = report(decision, args.repository, requested)
    print(text, end='')
    if args.summary:
        with args.summary.open('a') as summary:
            summary.write(text)
    for name in decision['exhausted']:
        print(f'::error::{name.removeprefix("alarm-")} failed to build {len(decision["failures"][name])} times '
              'in a row from its current recipe; it is not requested again.')
    if decision['broken']:
        print(f'::error::The last {len(decision["broken"])} native builds failed outside the package builds; '
              'nothing is requested.')
    if decision['exhausted'] or decision['broken']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
