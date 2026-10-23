#!/usr/bin/env python3
"""Refuse a package set that would move any package to an older version.

Each side is a pacman database (aurora.db.tar.gz or aurora.db) or a directory
of package archives. Versions compare with pacman's rules, so pacman on an
installed system would never see the new set as a downgrade. Removed packages
are reported; they do not fail the check.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import updatelib as lib  # noqa: E402


def _fields(text):
    fields, key = {}, None
    for line in text.splitlines():
        if line.startswith('%') and line.endswith('%'):
            key = line.strip('%')
            fields[key] = []
        elif line and key:
            fields[key].append(line)
    return fields


def database_versions(path):
    versions = {}
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            if member.isfile() and member.name.endswith('/desc'):
                fields = _fields(archive.extractfile(member).read().decode())
                versions[fields['NAME'][0]] = fields['VERSION'][0]
    return versions


def pkginfo(path):
    path = Path(path)
    if path.name.endswith('.zst'):
        data = subprocess.run(['zstd', '-dc', str(path)], check=True, capture_output=True).stdout
        import io
        archive = tarfile.open(fileobj=io.BytesIO(data), mode='r:')
    else:
        archive = tarfile.open(path, 'r:*')
    with archive:
        text = archive.extractfile('.PKGINFO').read().decode()
    values = dict(line.split(' = ', 1) for line in text.splitlines() if ' = ' in line and not line.startswith('#'))
    return values['pkgname'], values['pkgver']


def versions(source):
    source = Path(source)
    if source.is_dir():
        found = {}
        for path in sorted(source.iterdir()):
            if '.pkg.tar.' in path.name and not path.name.endswith('.sig'):
                name, version = pkginfo(path)
                if name in found:
                    raise ValueError(f'{name} appears twice')
                found[name] = version
        return found
    return database_versions(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', required=True, help='previous database or package directory')
    parser.add_argument('--new', required=True, help='candidate database or package directory')
    parser.add_argument('--allow-downgrade', action='store_true')
    args = parser.parse_args()
    old, new = versions(args.old), versions(args.new)
    downgraded, removed, added = lib.regressions(old, new, lib.alpm_vercmp)
    changed = sorted(name for name in old.keys() & new.keys() if old[name] != new[name])
    for name in changed:
        print(f'{name}: {old[name]} -> {new[name]}')
    for name in added:
        print(f'{name}: new at {new[name]}')
    for name in removed:
        print(f'{name}: removed (was {old[name]})')
    if downgraded:
        for name, before, after in downgraded:
            print(f'DOWNGRADE {name}: {before} -> {after}', file=sys.stderr)
        if not args.allow_downgrade:
            raise SystemExit('The candidate would downgrade installed packages; see above.')
    print(f'{len(changed)} changed, {len(added)} added, {len(removed)} removed, {len(downgraded)} downgraded')


if __name__ == '__main__':
    main()
