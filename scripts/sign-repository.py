#!/usr/bin/env python3
"""Create a signed pacman repository from a completed native package set."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--credentials-stdin', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; use a new snapshot directory')
    packages = sorted(args.packages.glob('*.pkg.tar.*'))
    if not packages or any(p.is_symlink() or not re.fullmatch(r'[A-Za-z0-9_.+:~-]+\.pkg\.tar\.(xz|zst|gz)', p.name) for p in packages):
        parser.error('expected regular versioned package archives')
    credentials = json.load(sys.stdin) if args.credentials_stdin else {
        'key': os.environ['ALARM_SIGNING_KEY'],
        'passphrase': os.environ['ALARM_SIGNING_PASSPHRASE'],
    }
    fingerprint = (ROOT / 'keys/fingerprint.txt').read_text().strip()
    args.output.mkdir(parents=True)
    manifest, names = [], set()
    with tempfile.TemporaryDirectory(prefix='aurora-alarm-sign-') as temporary:
        home = Path(temporary)
        passfile = home / 'passphrase'
        passfile.write_text(credentials['passphrase'])
        passfile.chmod(0o600)
        gpg = ['gpg', '--no-options', '--homedir', str(home), '--batch',
               '--pinentry-mode', 'loopback', '--passphrase-file', str(passfile)]
        run(*gpg, '--import', input=credentials['key'].encode(), stdout=subprocess.DEVNULL)
        listing = subprocess.check_output(gpg + ['--with-colons', '--list-secret-keys'], text=True)
        if fingerprint not in [line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:')]:
            raise ValueError('signing key differs from the committed public key')
        for package in packages:
            metadata = subprocess.check_output(['bsdtar', '-xOf', str(package), '.PKGINFO'], text=True)
            name = next(line.removeprefix('pkgname = ') for line in metadata.splitlines() if line.startswith('pkgname = '))
            if name in names:
                raise ValueError('multiple candidate versions of ' + name)
            names.add(name)
            # ALARM's epoch-bearing names contain ':'. Keep metadata unchanged,
            # and use a portable release asset name in the repository database.
            target = args.output / package.name.replace(':', '_')
            shutil.copyfile(package, target)
            run(*gpg, '--local-user', fingerprint, '--detach-sign', '--output', str(target) + '.sig', str(target))
            run(*gpg, '--verify', str(target) + '.sig', str(target))
            with target.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            manifest.append({'name': name, 'filename': target.name, 'bytes': target.stat().st_size, 'sha256': digest})
        run('repo-add', '--include-sigs', str(args.output / 'aurora.db.tar.gz'),
            *map(str, sorted([p for p in args.output.glob('*.pkg.tar.*') if not p.name.endswith('.sig')])))
        for filename in ('aurora.db.tar.gz', 'aurora.files.tar.gz'):
            target = args.output / filename
            run(*gpg, '--local-user', fingerprint, '--detach-sign', '--output', str(target) + '.sig', str(target))
            run(*gpg, '--verify', str(target) + '.sig', str(target))
            # Real copies are portable GitHub Release assets as well as HTTP files.
            alias = args.output / filename.removesuffix('.tar.gz')
            alias.unlink(missing_ok=True)
            shutil.copyfile(target, alias)
            shutil.copyfile(str(target) + '.sig', str(alias) + '.sig')
        run('gpgconf', '--homedir', str(home), '--kill', 'gpg-agent')
    shutil.copyfile(ROOT / 'keys/aurora-alarm.asc', args.output / 'aurora-alarm.asc')
    (args.output / 'manifest.json').write_text(json.dumps({
        'schema': 1, 'architecture': 'aarch64', 'channel': 'testing',
        'signing_key': fingerprint, 'packages': manifest,
    }, indent=2) + '\n')
    print(f'Prepared and verified {len(manifest)} signed ALARM packages and pacman databases')


if __name__ == '__main__':
    main()
