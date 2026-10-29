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

SHARED = ('.github/workflows/packages.yml', 'scripts/ci-build-package', 'scripts/ci-build-fex-guest',
          'scripts/ci-build-alarm-container',
          'scripts/fetch-base.py', 'images/base.json', 'keys/archlinuxarm-build-system.asc')
PACKAGE = re.compile(r'[A-Za-z0-9_.+:~-]+\.pkg\.tar\.(xz|zst|gz)')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def eligible_recipes(root, metadata, repository):
    commit = metadata.get('head_sha', '')
    if (metadata.get('conclusion') != 'success'
            or metadata.get('head_repository', {}).get('full_name') != repository
            or metadata.get('path') != '.github/workflows/packages.yml'
            or metadata.get('event') not in ('push', 'workflow_dispatch')
            or (metadata.get('event') == 'push' and metadata.get('head_branch') != 'main')
            or not re.fullmatch('[a-f0-9]{40}', commit)):
        raise ValueError('Not a successful native main-branch or manual build from this repository')
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
        key = {'linux-aurora': 'kernel-aurora', 'alsa-utils-aurora': 'alsa-utils',
               'aurora-flatpak-gl': 'mesa-aurora'}.get(name, name)
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


def newest_per_name(artifacts):
    """A re-run job uploads a new artifact under the same name; only the newest
    one belongs to the attempt that succeeded."""
    newest = {}
    for artifact in artifacts:
        current = newest.get(artifact['name'])
        if current is None or (artifact.get('created_at', ''), artifact['id']) > (current.get('created_at', ''), current['id']):
            newest[artifact['name']] = artifact
    return list(newest.values())


def attests(root, commit):
    """Whether the build workflow at `commit` records provenance attestations."""
    workflow = subprocess.run(['git', '-C', str(root), 'show', f'{commit}:.github/workflows/packages.yml'],
                              capture_output=True, text=True)
    return 'actions/attest-build-provenance' in workflow.stdout


def verify_attestation(path, repository, commit):
    subprocess.run(['gh', 'attestation', 'verify', str(path), '--repo', repository,
                    '--signer-workflow', f'{repository}/.github/workflows/packages.yml',
                    '--source-digest', commit, '--deny-self-hosted-runners'],
                   check=True, stdout=subprocess.DEVNULL)


def verify_base_package(path, manifest, gnupg_home):
    record = manifest.get(path.name)
    if (record is None or path.is_symlink() or path.stat().st_size != record['bytes']
            or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']):
        raise ValueError(f'Snapshot package does not match its manifest: {path.name}')
    subprocess.run(['gpg', '--homedir', str(gnupg_home), '--batch', '--verify', str(path) + '.sig', str(path)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def snapshot_keyring(root, home):
    home.mkdir(mode=0o700)
    subprocess.run(['gpg', '--homedir', str(home), '--batch', '--import', str(root / 'keys/aurora-alarm.asc')],
                   check=True, capture_output=True)
    listing = subprocess.check_output(['gpg', '--homedir', str(home), '--batch', '--with-colons', '--list-keys'],
                                      text=True)
    fingerprints = [line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:')]
    if (root / 'keys/fingerprint.txt').read_text().strip() not in fingerprints:
        raise ValueError('The committed key does not match keys/fingerprint.txt')
    return home


def collect_plan(root, plan, repository, output, base_dir=None, require_attestation=True):
    """Collect exactly the artifacts resolve-build-runs.py chose."""
    if plan.get('schema') != 1 or plan.get('action') != 'publish' or plan.get('missing'):
        raise ValueError('The build plan is not publishable')
    if plan['head'] != git(root, 'rev-parse', 'HEAD'):
        raise ValueError('The build plan was resolved for another commit')
    expected = {'alarm-' + path.parent.name for path in (root / 'packages').glob('*/PKGBUILD')}
    if set(plan['recipes']) != expected:
        raise ValueError('The build plan does not cover the current recipes')
    output.mkdir()
    downloads = Path('publication-downloads')
    downloads.mkdir(exist_ok=True)
    receipt, builds = [], {}
    keyring = None
    manifest = {}
    for name, item in sorted(plan['recipes'].items()):
        if item.get('base'):
            if base_dir is None:
                raise ValueError('A carried recipe needs the downloaded base snapshot')
            keyring = keyring or snapshot_keyring(root, Path('publication-keyring').resolve())
            manifest = manifest or {row['filename']: row for row in
                                    json.loads((base_dir / 'manifest.json').read_text())['packages']}
            metadata = {'conclusion': 'success', 'head_repository': {'full_name': repository},
                        'path': '.github/workflows/packages.yml', 'event': 'workflow_dispatch',
                        'head_sha': item['head_sha'], 'head_branch': 'main'}
            if name not in eligible_recipes(root, metadata, repository):
                raise ValueError(f'{name}: the snapshot build no longer matches the recipe')
            packages = []
            for filename in item['packages']:
                path = base_dir / filename
                if not PACKAGE.fullmatch(filename):
                    raise ValueError('Unexpected snapshot package name')
                verify_base_package(path, manifest, keyring)
                if require_attestation and attests(root, item['head_sha']):
                    verify_attestation(path, repository, item['head_sha'])
                shutil.copyfile(path, output / filename)
                packages.append(filename)
            receipt.append({'build_run': item.get('run'), 'artifact_id': item.get('artifact'), 'name': name,
                            'head_sha': item['head_sha'], 'reused_from': item['base'], 'packages': packages})
            continue
        run = str(item['run'])
        metadata = builds.get(run) or gh_json(f'repos/{repository}/actions/runs/{run}')
        builds[run] = metadata
        if name not in eligible_recipes(root, metadata, repository):
            raise ValueError(f'{name}: run {run} is not a publishable build of the current recipe')
        artifact = gh_json(f'repos/{repository}/actions/artifacts/{item["artifact"]}')
        if (artifact.get('workflow_run', {}).get('id') != int(run) or artifact['name'] != name
                or artifact['expired'] or artifact['digest'] != item['digest']):
            raise ValueError(f'{name}: artifact {item["artifact"]} is not the planned output of run {run}')
        archive = downloads / f'{artifact["id"]}.zip'
        with archive.open('wb') as stream:
            subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'],
                           stdout=stream, check=True)
        staging = downloads / f'{artifact["id"]}'
        staging.mkdir(exist_ok=True)
        packages = collect_archive(archive, artifact, staging)
        if not packages:
            raise ValueError(f'{name}: the artifact holds no package archive')
        for filename in packages:
            if require_attestation and attests(root, metadata['head_sha']):
                verify_attestation(staging / filename, repository, metadata['head_sha'])
            shutil.copyfile(staging / filename, output / filename)
        archive.unlink()
        receipt.append({'build_run': int(run), 'artifact_id': artifact['id'], 'name': name,
                        'head_sha': metadata['head_sha'], 'digest': artifact['digest'], 'packages': packages})
    names = [path.name for path in output.iterdir()]
    if len(names) != len({name for entry in receipt for name in entry['packages']}):
        raise ValueError('Two recipes produced the same package file')
    build_records = [{key: metadata[key] for key in ('id', 'head_sha', 'path', 'event', 'conclusion')}
                     for metadata in builds.values()]
    Path('build.json').write_text(json.dumps({'schema': 2, 'builds': build_records}, indent=2) + '\n')
    Path('publication-inputs.json').write_text(json.dumps(
        {'schema': 2, 'publishing_commit': plan['head'], 'base_release': plan.get('base_release'),
         'builds': build_records, 'artifacts': receipt}, indent=2) + '\n')
    print(f'Authenticated {len(receipt)} recipe outputs ({sum(1 for r in receipt if r.get("reused_from"))} carried)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--runs', nargs='+', help='explicit native build IDs; later runs win')
    source.add_argument('--plan', type=Path, help='exact artifacts chosen by resolve-build-runs.py')
    parser.add_argument('--base-dir', type=Path, help='downloaded base snapshot for carried recipes')
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.plan:
        if args.output.exists():
            parser.error('Use a fresh output')
        collect_plan(root, json.loads(args.plan.read_text()), args.repository, args.output, args.base_dir)
        return
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
        for artifact in newest_per_name([item for page in pages for item in page['artifacts']]):
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
