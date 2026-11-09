#!/usr/bin/env python3
"""Refuse a recipe that would build an older version than the published feed has.

pacman never replaces a newer package with an older one, so such a package
would silently never reach updated installs. Every package each
packages/<name>/PKGBUILD builds is compared, with pacman's version rules,
with the version the published Aurora Alarm database lists for that name.
Names the feed does not have yet are new and pass.

    check-published-versions.py [--database FILE_OR_URL] [--channel testing]
"""
import argparse
import io
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

SITE = 'https://aurorasilicon.org/alarm-aurora'
# Sourcing a PKGBUILD only defines variables and functions; print what makepkg
# would name each package.
PRINT = r'''source ./PKGBUILD || exit
v="$pkgver-$pkgrel"
[[ -z ${epoch:-} ]] || v="$epoch:$v"
for n in "${pkgname[@]}"; do printf '%s %s\n' "$n" "$v"; done
'''


def database_versions(data):
    """{name: version} from a pacman database archive."""
    versions = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive:
            if member.isfile() and member.name.endswith('/desc'):
                key, fields = None, {}
                for line in archive.extractfile(member).read().decode().splitlines():
                    if line.startswith('%') and line.endswith('%'):
                        key = line.strip('%')
                    elif line and key and key not in fields:
                        fields[key] = line
                versions[fields['NAME']] = fields['VERSION']
    return versions


def recipe_versions(root=ROOT):
    """{name: version} that every packages/*/PKGBUILD builds."""
    versions = {}
    for pkgbuild in sorted((root / 'packages').glob('*/PKGBUILD')):
        run = subprocess.run(['bash', '-c', PRINT], cwd=pkgbuild.parent, capture_output=True, text=True)
        if run.returncode or not run.stdout.strip():
            raise SystemExit(f'packages/{pkgbuild.parent.name}/PKGBUILD: cannot read its version: {run.stderr.strip()}')
        out = run.stdout
        for line in out.splitlines():
            name, version = line.split(' ', 1)
            versions[name] = (version, pkgbuild.parent.name)
    return versions


def older(published, recipes):
    """[(name, recipe dir, recipe version, published version)] that would move backwards."""
    return [(name, directory, version, published[name])
            for name, (version, directory) in sorted(recipes.items())
            if name in published and lib.alpm_vercmp(version, published[name]) < 0]


def load(source):
    if source.startswith(('https://', 'http://')):
        with urllib.request.urlopen(source, timeout=60) as response:
            return response.read()
    return Path(source).read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', default='testing')
    parser.add_argument('--database', help='pacman database file or URL (default: the channel feed)')
    args = parser.parse_args()
    source = args.database or f'{SITE}/{args.channel}/aarch64/aurora.db'
    published = database_versions(load(source))
    regressions = older(published, recipe_versions())
    for name, directory, version, current in regressions:
        print(f'packages/{directory}: {name} {version} sorts before the published {current}')
    if regressions:
        return 1
    print(f'{len(published)} published packages; no recipe builds an older version ({source})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
