#!/usr/bin/env python3
"""Assemble a complete set from authenticated, input-identical native builds."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

SHARED = ('.github/workflows/packages.yml', 'scripts/ci-build-package',
          'scripts/fetch-base.py', 'images/base.json', 'keys/archlinuxarm-build-system.asc')
PACKAGE = re.compile(r'[A-Za-z0-9_.+:~-]+\.pkg\.tar\.(xz|zst|gz)')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def eligible_recipes(root, metadata, repository):
    commit = metadata.get('head_sha', '')
    if (metadata.get('conclusion') != 'success' or metadata.get('head_branch') != 'main'
            or metadata.get('head_repository', {}).get('full_name') != repository
            or metadata.get('path') != '.github/workflows/packages.yml'
            or metadata.get('event') not in ('push', 'workflow_dispatch')
            or not re.fullmatch('[a-f0-9]{40}', commit)):
        raise ValueError('Not a successful native main-branch build from this repository')
    if subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', commit, 'HEAD']).returncode:
        raise ValueError('Build source is not merged into the publisher')
    for path in SHARED:
        if git(root, 'rev-parse', f'{commit}:{path}') != git(root, 'rev-parse', f'HEAD:{path}'):
            raise ValueError(f'Build tooling changed: {path}')
    previous = json.loads(git(root, 'show', f'{commit}:sources.json'))
    current = json.loads((root / 'sources.json').read_text())
    result = set()
    for recipe in (root / 'packages').glob('*/PKGBUILD'):
        name = recipe.parent.name
        key = 'kernel-aurora' if name == 'linux-aurora' else name
        if subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{commit}:packages/{name}'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            continue
        if (git(root, 'rev-parse', f'{commit}:packages/{name}')
                == git(root, 'rev-parse', f'HEAD:packages/{name}')
                and previous.get(key) == current.get(key)):
            result.add('alarm-' + name)
    return result


def collect_archive(archive, artifact, output):
    with archive.open('rb') as stream:
        digest = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != artifact.get('digest'):
        raise ValueError('CI artifact digest mismatch')
    packages = []
    with zipfile.ZipFile(archive) as entries:
        if sum(entry.file_size for entry in entries.infolist()) > 2_000_000_000:
            raise ValueError('Expanded artifact exceeds publication budget')
        for entry in entries.infolist():
            name = Path(entry.filename).name
            if not PACKAGE.fullmatch(name):
                continue
            if entry.is_dir() or entry.file_size >= 900_000_000 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe package artifact')
            incoming = output / (name + '.incoming')
            try:
                with entries.open(entry) as source, incoming.open('xb') as target:
                    shutil.copyfileobj(source, target)
                destination = output / name
                if destination.exists():
                    with incoming.open('rb') as left, destination.open('rb') as right:
                        if hashlib.file_digest(left, 'sha256').digest() != hashlib.file_digest(right, 'sha256').digest():
                            raise ValueError('Conflicting duplicate package')
                else:
                    incoming.rename(destination)
                packages.append(name)
            finally:
                incoming.unlink(missing_ok=True)
    return packages


def gh_json(*args):
    return json.loads(subprocess.check_output(['gh', 'api', *args]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.output.exists() or any(not re.fullmatch('[0-9]+', run) for run in args.runs):
        parser.error('Use a fresh output and numeric native build IDs')
    expected = {'alarm-' + path.parent.name for path in (root / 'packages').glob('*/PKGBUILD')}
    selected = {}
    builds = []
    # Later explicitly supplied runs take precedence for an unchanged recipe.
    for run in args.runs:
        metadata = gh_json(f'repos/{args.repository}/actions/runs/{run}')
        eligible = eligible_recipes(root, metadata, args.repository)
        pages = gh_json('--paginate', '--slurp', f'repos/{args.repository}/actions/runs/{run}/artifacts?per_page=100')
        grouped = {}
        for artifact in [item for page in pages for item in page['artifacts']]:
            if artifact['name'] in eligible:
                if artifact['expired'] or not isinstance(artifact['id'], int):
                    raise ValueError('Required CI artifact is unavailable')
                grouped.setdefault(artifact['name'], []).append((run, artifact))
        selected.update(grouped)
        builds.append({key: metadata[key] for key in ('id', 'head_sha', 'path', 'event', 'conclusion')})
    if set(selected) != expected:
        raise ValueError(f'Complete input-identical recipe matrix required; missing {sorted(expected - selected.keys())}')
    artifacts = [record for group in selected.values() for record in group]
    if sum(item['size_in_bytes'] for _, item in artifacts) >= 1_500_000_000:
        raise ValueError('Native artifacts exceed download budget')
    args.output.mkdir()
    downloads = Path('publication-downloads')
    downloads.mkdir()
    populated = set()
    receipt = []
    for run, artifact in artifacts:
        archive = downloads / f'{artifact["id"]}.zip'
        with archive.open('xb') as stream:
            subprocess.run(['gh', 'api', f'repos/{args.repository}/actions/artifacts/{artifact["id"]}/zip'], stdout=stream, check=True)
        packages = collect_archive(archive, artifact, args.output)
        if packages:
            populated.add(artifact['name'])
        receipt.append({'build_run': run, 'artifact_id': artifact['id'], 'name': artifact['name'],
                        'digest': artifact['digest'], 'packages': packages})
    if populated != expected:
        raise ValueError(f'A recipe has no actual package archive: {sorted(expected - populated)}')
    Path('build.json').write_text(json.dumps({'schema': 2, 'builds': builds}, indent=2) + '\n')
    Path('publication-inputs.json').write_text(json.dumps({'builds': builds, 'artifacts': receipt}, indent=2) + '\n')
    print(f'Authenticated {len(populated)} recipe outputs from {len(builds)} native build(s)')


if __name__ == '__main__':
    main()
