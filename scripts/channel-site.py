#!/usr/bin/env python3
"""Assemble the ALARM update site for every channel and record channel state.

GitHub Pages serves one site per repository, so every deployment publishes all
channels: testing/aarch64 and stable/aarch64, each a byte-for-byte copy of an
immutable signed snapshot release. `assemble` downloads and authenticates them
and writes the next channel state; `record` commits that state after Pages
has accepted the site.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402
import edgelib  # noqa: E402

TAG = re.compile(r'testing-[A-Za-z0-9._-]+')
SITE_BUDGET = 900_000_000
CHANNELS = ('testing', 'stable', 'edge')


def database(channel):
    """Edge serves the small [aurora-edge] overlay; the other channels serve [aurora]."""
    return edgelib.DATABASE if channel == 'edge' else 'aurora'


def publisher(channel):
    return '.github/workflows/' + ('publish-edge.yml' if channel == 'edge' else 'publish.yml')


def keyring(home):
    home.parent.mkdir(parents=True, exist_ok=True)
    home.mkdir(mode=0o700, exist_ok=True)
    subprocess.run(['gpg', '--homedir', str(home), '--batch', '--import', str(ROOT / 'keys/aurora-alarm.asc')],
                   check=True, capture_output=True)
    listing = subprocess.check_output(['gpg', '--homedir', str(home), '--batch', '--with-colons', '--list-keys'],
                                      text=True)
    fingerprint = (ROOT / 'keys/fingerprint.txt').read_text().strip()
    if fingerprint not in [line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:')]:
        raise ValueError('keys/aurora-alarm.asc does not hold the recorded fingerprint')
    return home, fingerprint


def checksum_index(path):
    listed = {}
    for line in path.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip('*')
        if name in listed:
            raise ValueError(f'{path}: repeated checksum for {name}')
        listed[name] = digest
    return listed


def verify_attestations(directory, repository, channel='testing', *, source_digest=None):
    """Verify one release attestation for the full checksum index.

    With a source digest, verify the downloaded metadata subset against that
    index and require the exact main-branch publication source.
    """
    sums = directory / 'SHA256SUMS'
    if not sums.exists():
        return 'none (snapshot predates attestations)'
    listed = checksum_index(sums)
    actual = {path.name: lib.sha256_file(path) for path in directory.iterdir() if path.name != 'SHA256SUMS'}
    if not actual.items() <= listed.items() or (source_digest is None and listed != actual):
        raise ValueError(f'{directory}: SHA256SUMS does not match the downloaded assets')
    source = ['--source-ref', 'refs/heads/main', '--source-digest', source_digest] if source_digest else []
    result = subprocess.run(['gh', 'attestation', 'verify', str(directory / 'manifest.json'), '--repo', repository,
                             '--signer-workflow', f'{repository}/{publisher(channel)}',
                             *source, '--deny-self-hosted-runners', '--format', 'json'],
                            check=True, capture_output=True, text=True)
    attestations = ({(s['name'], s['digest']['sha256']) for s in v['verificationResult']['statement']['subject']}
                    for v in json.loads(result.stdout))
    if not any(listed.items() <= subjects for subjects in attestations):
        raise ValueError(f'{directory}: the provenance attestation does not cover every asset')
    return 'verified'


def fetch_edge_base(repository, tag, destination, home, fingerprint):
    edgelib.testing_snapshot(tag)
    destination.mkdir(parents=True)
    archive = destination / 'aurora.db.tar.gz'
    manifest_path = destination / 'manifest.json'
    provenance_path = destination / 'publication-inputs.json'
    lib.gh('release', 'download', tag, '--repo', repository, '--dir', str(destination),
           '--pattern', manifest_path.name, '--pattern', 'SHA256SUMS',
           '--pattern', archive.name, '--pattern', archive.name + '.sig', '--pattern', provenance_path.name)
    provenance = json.loads(provenance_path.read_text())
    revision = provenance['publishing_commit']
    if not edgelib.REVISION.fullmatch(revision) \
            or verify_attestations(destination, repository, source_digest=revision) != 'verified':
        raise ValueError(f'{tag}: the Edge base requires hosted provenance')
    manifest = json.loads(manifest_path.read_text())
    if (manifest['channel'] != 'testing' or manifest['dry_run'] is not False
            or manifest['architecture'] != 'aarch64' or manifest['signing_key'] != fingerprint):
        raise ValueError(f'{tag}: invalid signed Edge base manifest')
    packages = {item['filename']: item['sha256'] for item in manifest['packages']}
    if not packages or len(packages) != len(manifest['packages']) \
            or not packages.items() <= checksum_index(destination / 'SHA256SUMS').items():
        raise ValueError(f'{tag}: the Edge base checksum index does not cover every package')
    owners = {}
    for artifact in provenance['artifacts']:
        for name in artifact['packages']:
            owners.setdefault(name, set()).add(artifact['name'])
    if any(len(owners.get(name, ())) != 1 for name in packages):
        raise ValueError(f'{tag}: the Edge base package build records are incomplete or ambiguous')
    subprocess.run(['gpg', '--homedir', str(home), '--batch', '--verify', str(archive) + '.sig', str(archive)],
                   check=True, capture_output=True)
    return {'tag': tag, 'packaging_commit': revision, 'manifest_sha256': lib.sha256_file(manifest_path),
            'database_sha256': lib.sha256_file(archive), 'provenance_sha256': lib.sha256_file(provenance_path)}


def fetch_snapshot(repository, tag, destination, home, fingerprint, channel='testing'):
    if channel == 'edge':
        edgelib.snapshot(tag)
    elif not TAG.fullmatch(tag):
        raise ValueError(f'not a testing snapshot tag: {tag}')
    destination.mkdir(parents=True)
    lib.gh('release', 'download', tag, '--repo', repository, '--dir', str(destination))
    for signature in sorted(destination.glob('*.sig')):
        subprocess.run(['gpg', '--homedir', str(home), '--batch', '--verify', str(signature),
                        str(signature.with_suffix(''))], check=True, capture_output=True)
    if not (destination / f'{database(channel)}.db.sig').exists():
        raise ValueError(f'{tag}: the pacman database is unsigned')
    manifest = json.loads((destination / 'manifest.json').read_text())
    if manifest.get('dry_run') or manifest.get('signing_key') not in (None, fingerprint):
        raise ValueError(f'{tag}: not signed by the release key')
    for record in manifest['packages']:
        path = destination / record['filename']
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != record['bytes']
                or lib.sha256_file(path) != record['sha256']
                or not (destination / (record['filename'] + '.sig')).is_file()):
            raise ValueError(f'{tag}: {record["filename"]} does not match its manifest')
    if (manifest.get('channel', 'testing') == 'edge') != (channel == 'edge'):
        raise ValueError(f'{tag}: an Edge overlay serves only the edge channel, and only it')
    provenance = verify_attestations(destination, repository, channel)
    if channel == 'edge' and (provenance != 'verified' or not (destination / 'edge-sources.json').is_file()):
        raise ValueError(f'{tag}: the Edge overlay requires a source record and hosted provenance')
    return provenance


def check_closure(site, base_database=None):
    """Validate the overlay against an Aurora base and the Arch Linux ARM feeds."""
    if base_database is None:
        base_database = Path(site) / 'testing/aarch64/aurora.db.tar.gz'
    closure = subprocess.run([sys.executable, str(ROOT / 'scripts/check-edge-closure.py'),
                              '--overlay', str(Path(site) / 'edge/aarch64/aurora-edge.db.tar.gz'),
                              '--testing', str(base_database)],
                             capture_output=True, text=True)
    if closure.returncode:
        print(closure.stdout + closure.stderr, file=sys.stderr)
        raise SystemExit('The Edge overlay does not close over the selected Aurora base and upstream feeds.')


def live_database(site_url, channel, work, home):
    """The signed database the channel serves now, or None if it serves none."""
    base = f'{site_url.rstrip("/")}/{channel}/aarch64'
    name = database(channel)
    database_path, signature = work / f'{name}.db', work / f'{name}.db.sig'
    try:
        lib.download([base + f'/{name}.db'], database_path, attempts=3)
        lib.download([base + f'/{name}.db.sig'], signature, attempts=3)
    except RuntimeError as error:
        if 'HTTP 404' in str(error):
            return None
        raise
    subprocess.run(['gpg', '--homedir', str(home), '--batch', '--verify', str(signature), str(database_path)],
                   check=True, capture_output=True)
    return database_path


def release_commit(repository, tag):
    release = lib.gh_api(f'repos/{repository}/releases/tags/{tag}')
    return release['target_commitish'], release['created_at']


def assemble(args):
    repository = args.repository
    state = lib.load_channels(ROOT, repository)
    current = {channel: state['channels'].get(channel, {}).get('tag') for channel in CHANNELS}
    tag = args.tag
    if args.channel == 'stable':
        tag = tag or current['testing']
        if not tag:
            raise SystemExit('Nothing is on testing to promote.')
        served = lib.served_on(state, 'testing', 'tag', tag)
        if not served:
            raise SystemExit(f'{tag} has never been served on testing; promote only what testing users had.')
        first = min(item['deployed_at'] for item in served)
        soaked = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.datetime.fromisoformat(first.replace('Z', '+00:00'))).total_seconds() / 3600
        if soaked < args.min_soak_hours:
            raise SystemExit(f'{tag} has been on testing for {soaked:.1f} h; the minimum is {args.min_soak_hours} h.')
    if not tag:
        raise SystemExit(f'A release tag is required for the {args.channel} channel.')
    if args.channel == 'edge':
        # Every distribution's Edge feed moves with the adopted aurora-distributions train.
        if not args.edge_train:
            raise SystemExit('An Edge deploy needs the adopted Edge train record (--edge-train).')
        edgelib.snapshot(tag)
    target = dict(current, **{args.channel: tag})
    site = Path(args.site)
    if site.exists():
        raise SystemExit('use a new site directory')
    home, fingerprint = keyring(Path(args.work) / 'gnupg')
    provenance = {}
    for channel in CHANNELS:
        if target[channel]:
            provenance[channel] = fetch_snapshot(repository, target[channel], site / channel / 'aarch64',
                                                 home, fingerprint, channel)
    if target.get('edge'):
        sources = json.loads((site / 'edge/aarch64/edge-sources.json').read_text())
        if args.channel == 'edge':
            edgelib.edge_gate(json.loads(Path(args.edge_train).read_text()), tag, sources)
        base = sources.get('base')
        if base is not None:
            directory = Path(args.work) / 'edge-base'
            if fetch_edge_base(repository, base['tag'], directory, home, fingerprint) != base:
                raise ValueError('the signed Edge base differs from the overlay source record')
            check_closure(site, directory / 'aurora.db.tar.gz')
    if target.get('edge') and target.get('testing'):
        check_closure(site)
    previous = current[args.channel]
    report = ''
    live = live_database(args.site_url, args.channel, Path(args.work) / 'live', home)
    if live is None and previous and previous != tag:
        old = Path(args.work) / 'previous'
        old.mkdir(parents=True)
        lib.gh('release', 'download', previous, '--repo', repository, '--pattern', f'{database(args.channel)}.db.tar.gz',
               '--dir', str(old))
        live = old / f'{database(args.channel)}.db.tar.gz'
    if live is not None:
        # Compare with what installed systems on this channel can already have.
        command = [sys.executable, str(ROOT / 'scripts/check-feed-versions.py'), '--old',
                   str(live), '--new', str(site / args.channel / f'aarch64/{database(args.channel)}.db.tar.gz')]
        if args.allow_downgrade:
            command.append('--allow-downgrade')
        checked = subprocess.run(command, capture_output=True, text=True)
        report = checked.stdout + checked.stderr
        if checked.returncode:
            print(report, file=sys.stderr)
            raise SystemExit('The new snapshot would downgrade packages on this channel.')
    total = sum(path.stat().st_size for path in site.rglob('*') if path.is_file())
    if total >= SITE_BUDGET:
        raise SystemExit(f'site is {total} bytes; Pages allows about 1 GB')
    shutil.copyfile(ROOT / 'keys/aurora-alarm.asc', site / 'aurora-alarm.asc')
    commit, created = release_commit(repository, tag)
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entry = {'tag': tag, 'commit': commit, 'released_at': created, 'deployed_at': now,
             'run_id': os.environ.get('GITHUB_RUN_ID', ''), 'actor': os.environ.get('GITHUB_ACTOR', ''),
             'provenance': provenance[args.channel]}
    new_state = lib.record_channel(state, args.channel, entry)
    public = {'repository': repository, 'channels': new_state['channels'], 'updated_at': now}
    (site / 'channels.json').write_text(json.dumps(public, indent=2, sort_keys=True) + '\n')
    lines = ['<!doctype html><title>Aurora Alarm</title><h1>Aurora Alarm package feeds</h1><ul>']
    for channel in CHANNELS:
        if target[channel]:
            lines.append(f'<li>{channel}: <code>[{database(channel)}] Server = https://aurorasilicon.org/alarm-aurora/{channel}/$arch</code>'
                         f' ({target[channel]})</li>')
    (site / 'index.html').write_text('\n'.join(lines) + '</ul>\n')
    Path(args.state_out).write_text(json.dumps(new_state, indent=2) + '\n')
    summary = [f'## {args.channel}: {previous or "(none)"} -> {tag}', '']
    summary += [f'- {channel}: `{target[channel]}` (attestation: {provenance[channel]})'
                for channel in CHANNELS if target[channel]]
    summary += ['', f'Site size: {total} bytes.', '', '```', report.strip() or 'no package changes', '```']
    print('\n'.join(summary))


def record(args):
    state = json.loads(Path(args.state).read_text())
    if state.get('repository') != args.repository:
        raise SystemExit('state belongs to another repository')
    entry = state['channels'][args.channel]
    lib.commit_channels(ROOT, state, f'Serve {entry["tag"]} on {args.channel}\n\nRun {entry.get("run_id", "")}')
    print(f'Recorded {entry["tag"]} on {args.channel}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('assemble')
    build.add_argument('--channel', choices=CHANNELS, required=True)
    build.add_argument('--tag', default='')
    build.add_argument('--allow-downgrade', action='store_true')
    build.add_argument('--min-soak-hours', type=float, default=0.0)
    build.add_argument('--site', required=True)
    build.add_argument('--work', required=True)
    build.add_argument('--site-url', default='https://aurorasilicon.org/alarm-aurora')
    build.add_argument('--state-out', required=True)
    build.add_argument('--edge-train', help="aurora-distributions' adopted site/installer/edge-train.json")
    store = commands.add_parser('record')
    store.add_argument('--channel', choices=CHANNELS, required=True)
    store.add_argument('--state', required=True)
    base = commands.add_parser('edge-base', help='verify and record the immutable Edge base')
    base.add_argument('--tag', required=True)
    base.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('--repository owner/name is required')
    if args.command == 'edge-base':
        home, fingerprint = keyring(args.work / 'gnupg')
        print(json.dumps(fetch_edge_base(args.repository, args.tag, args.work / 'edge-base', home, fingerprint)))
    elif args.command == 'assemble':
        assemble(args)
    else:
        record(args)


if __name__ == '__main__':
    main()
