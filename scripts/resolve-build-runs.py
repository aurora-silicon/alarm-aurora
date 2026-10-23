#!/usr/bin/env python3
"""Choose, for every ALARM recipe, the newest native build that may be published.

A build qualifies under the same rules as collect-publication-inputs.py: a
successful push build of main, or a manual build whose commit is merged, with
the recipe, its source pin and the shared build tooling unchanged since. For
each recipe the newest qualifying run with an unexpired artifact wins. A
recipe without one may be carried from the newest signed snapshot when that
snapshot's build of it qualifies the same way. Nothing is downloaded here.

The result is written as JSON with an `action`:
  publish     a new snapshot would differ from the newest one
  up-to-date  every recipe resolves to the artifact the newest snapshot holds
  missing     some recipe has no publishable build; `missing` names them
"""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

_spec = importlib.util.spec_from_file_location('collect', ROOT / 'scripts/collect-publication-inputs.py')
collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect)

WORKFLOW = 'packages.yml'
RETENTION_DAYS = 30


def recipes(root):
    return sorted('alarm-' + path.parent.name for path in (root / 'packages').glob('*/PKGBUILD'))


def eligible(root, run, repository):
    try:
        return collect.eligible_recipes(root, run, repository)
    except (ValueError, KeyError):
        return set()
    except Exception as error:  # an unreachable commit (e.g. force-pushed branch)
        lib.log(f'Run {run.get("id")}: skipped ({error})')
        return set()


def successful_runs(repository, now=None, api=lib.gh_api):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    oldest = now - datetime.timedelta(days=RETENTION_DAYS)
    runs = []
    for page in range(1, 6):
        data = api(f'repos/{repository}/actions/workflows/{WORKFLOW}/runs?status=success&per_page=100&page={page}')
        batch = data.get('workflow_runs', [])
        for run in batch:
            created = datetime.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
            if created >= oldest:
                runs.append(run)
        if len(batch) < 100 or any(datetime.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')) < oldest
                                   for run in batch):
            break
    return sorted(runs, key=lambda run: (run['created_at'], run['id']), reverse=True)


def newest_artifacts(repository, run_id, api=lib.gh_api):
    """Unexpired artifacts by name; a re-run's newest upload wins."""
    pages = api(f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100', paginate=True)
    newest = {}
    for artifact in [item for page in pages for item in page['artifacts']]:
        if artifact['expired']:
            continue
        current = newest.get(artifact['name'])
        if current is None or (artifact['created_at'], artifact['id']) > (current['created_at'], current['id']):
            newest[artifact['name']] = artifact
    return newest


def latest_snapshot(repository, prefix='testing-'):
    releases = lib.gh_api(f'repos/{repository}/releases?per_page=100')
    tags = [release for release in releases if release['tag_name'].startswith(prefix) and not release['draft']]
    return max(tags, key=lambda release: release['created_at'], default=None)


def base_recipes(root, repository, release):
    """Recipes the snapshot can supply: {recipe: entry with build provenance}."""
    if release is None:
        return {}
    assets = {asset['name']: asset for asset in release['assets']}
    if 'publication-inputs.json' not in assets:
        return {}
    inputs = json.loads(lib.gh('api', '-H', 'Accept: application/octet-stream',
                               f'repos/{repository}/releases/assets/{assets["publication-inputs.json"]["id"]}').stdout)
    heads = {str(build['id']): build['head_sha'] for build in inputs.get('builds', [])}
    result = {}
    for entry in inputs.get('artifacts', []):
        head = entry.get('head_sha') or heads.get(str(entry.get('build_run')))
        if not head or not entry.get('packages'):
            continue
        metadata = {'conclusion': 'success', 'head_repository': {'full_name': repository},
                    'path': f'.github/workflows/{WORKFLOW}', 'event': 'workflow_dispatch', 'head_sha': head,
                    'head_branch': 'main'}
        if entry['name'] in eligible(root, metadata, repository):
            result[entry['name']] = {**entry, 'head_sha': head}
    return result


def resolve(root, repository, runs, artifacts_for, base_release=None, base=None):
    wanted = recipes(root)
    chosen = {}
    for run in runs:
        pending = [name for name in wanted if name not in chosen]
        if not pending:
            break
        names = eligible(root, run, repository) & set(pending)
        if not names:
            continue
        artifacts = artifacts_for(run['id'])
        for name in sorted(names):
            artifact = artifacts.get(name)
            if artifact:
                chosen[name] = {'run': run['id'], 'head_sha': run['head_sha'], 'artifact': artifact['id'],
                                'digest': artifact['digest'], 'bytes': artifact['size_in_bytes']}
    base = base or {}
    for name in wanted:
        if name not in chosen and name in base:
            chosen[name] = {'base': base_release, 'run': base[name].get('build_run'),
                            'head_sha': base[name]['head_sha'], 'artifact': base[name].get('artifact_id'),
                            'packages': base[name]['packages']}
    missing = [name for name in wanted if name not in chosen]
    if missing:
        action = 'missing'
    elif base and all(item.get('base') or (name in base and base[name].get('artifact_id') == item['artifact'])
                      for name, item in chosen.items()) and set(base) >= set(wanted):
        action = 'up-to-date'
    else:
        action = 'publish'
    runs_used = sorted({item['run'] for item in chosen.values() if not item.get('base')},
                       key=lambda run_id: next(i for i, run in enumerate(reversed(runs)) if run['id'] == run_id))
    return {'schema': 1, 'action': action, 'head': lib.git(root, 'rev-parse', 'HEAD'),
            'base_release': base_release, 'runs': runs_used, 'recipes': chosen, 'missing': missing,
            'rebuild': [name.removeprefix('alarm-') for name in missing]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--base-release', help='snapshot to carry unchanged recipes from (default: newest testing-*)')
    parser.add_argument('--no-base', action='store_true', help='require a current build of every recipe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name')
    release = None
    if not args.no_base:
        if args.base_release:
            release = lib.gh_api(f'repos/{args.repository}/releases/tags/{args.base_release}')
        else:
            release = latest_snapshot(args.repository)
    base = base_recipes(ROOT, args.repository, release)
    plan = resolve(ROOT, args.repository, successful_runs(args.repository),
                   lambda run_id: newest_artifacts(args.repository, run_id),
                   release['tag_name'] if release else None, base)
    args.output.write_text(json.dumps(plan, indent=2) + '\n')
    lib.write_github_output(action=plan['action'], runs=' '.join(map(str, plan['runs'])),
                            base_release=plan['base_release'] or '', rebuild=' '.join(plan['rebuild']))
    for name, item in sorted(plan['recipes'].items()):
        source = f'snapshot {item["base"]}' if item.get('base') else f'run {item["run"]}'
        print(f'{name}: {source} ({item["head_sha"][:12]})')
    print(f'Action: {plan["action"]}' + (f'; missing {", ".join(plan["missing"])}' if plan['missing'] else ''))


if __name__ == '__main__':
    main()
