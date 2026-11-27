#!/usr/bin/env python3
"""Refuse a package set in which a package depends on something nothing provides.

pacman resolves every depend of the packages an upgrade brings in, and one
that no configured repository satisfies stops the whole `pacman -Syu`, not
just that package: a linux-aurora that needs an avd-fw the feed does not carry
holds back every update. Each depend of each package in the set must be met,
with pacman's rules (a package of that name, or a provides entry, at a version
alpm_vercmp accepts), by the set itself or by the repositories that follow
[aurora] in the fleet's pacman.conf: asahi-alarm (scripts/build-image adds it)
and Arch Linux ARM's own core, extra, alarm and aur.

    check-feed-depends.py --new DIR_OR_DB [--upstream NAME=DB ...]

--new is the directory of package archives being published, or a pacman
database. Without --upstream, the upstream databases are downloaded.
"""
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

# The Arch Linux ARM mirror the image base comes from.
_BASE = urlsplit(json.loads((ROOT / 'images/base.json').read_text())['url'])
MIRROR = f'{_BASE.scheme}://{_BASE.netloc}/aarch64'
UPSTREAM = {
    'asahi-alarm': 'https://github.com/asahi-alarm/asahi-alarm/releases/download/aarch64/asahi-alarm.db',
    **{repo: f'{MIRROR}/{repo}/{repo}.db' for repo in ('core', 'extra', 'alarm', 'aur')},
}
DEPEND = re.compile(r'([^<>=]+)(?:(>=|<=|=|<|>)(.+))?')


class Package:
    def __init__(self, name, version, depends=(), provides=(), origin=''):
        self.name, self.version, self.origin = name, version, origin
        self.depends, self.provides = list(depends), list(provides)

    def __repr__(self):
        return f'{self.name} {self.version} ({self.origin})'


def parse(text):
    """(name, operator or None, version or None), as libalpm reads a depend."""
    match = DEPEND.fullmatch(text)
    if not match:
        raise ValueError(f'Unreadable dependency: {text!r}')
    return match.groups()


def version_ok(have, operator, want):
    result = lib.alpm_vercmp(have, want)
    return {'>=': result >= 0, '<=': result <= 0, '=': result == 0, '<': result < 0, '>': result > 0}[operator]


def satisfies(package, depend):
    """libalpm's _alpm_depcmp: by name, or by a provides entry; an
    unversioned provides meets only an unversioned depend."""
    name, operator, want = depend
    if package.name == name and (operator is None or version_ok(package.version, operator, want)):
        return True
    for provided, provided_operator, version in map(parse, package.provides):
        if provided == name and (operator is None or (provided_operator == '=' and version_ok(version, operator, want))):
            return True
    return False


def database_packages(data, origin):
    """Every package in a pacman database archive. Each entry's fields are in
    its desc file; older databases (Arch Linux ARM's) keep %DEPENDS% and
    %PROVIDES% in a separate depends file beside it."""
    entries = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive:
            directory, _, filename = member.name.rpartition('/')
            if not member.isfile() or filename not in ('desc', 'depends'):
                continue
            fields, key = entries.setdefault(directory, {}), None
            for line in archive.extractfile(member).read().decode().splitlines():
                if line.startswith('%') and line.endswith('%'):
                    key = line.strip('%')
                    fields[key] = []
                elif line and key:
                    fields[key].append(line)
    return [Package(fields['NAME'][0], fields['VERSION'][0], fields.get('DEPENDS', ()), fields.get('PROVIDES', ()), origin)
            for fields in entries.values()]


def pkginfo(path):
    """The .PKGINFO text of a package archive; makepkg writes it first."""
    if path.name.endswith('.zst'):
        process = subprocess.Popen(['zstd', '-dcq', str(path)], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                for member in archive:
                    if member.name == '.PKGINFO':
                        return archive.extractfile(member).read().decode()
        finally:
            process.stdout.close()
            process.kill()
            process.wait()
    else:
        with tarfile.open(path, 'r:*') as archive:
            return archive.extractfile('.PKGINFO').read().decode()
    raise ValueError(f'{path.name} has no .PKGINFO')


def archive_packages(directory, origin):
    packages = []
    for path in sorted(Path(directory).iterdir()):
        if '.pkg.tar.' not in path.name or path.name.endswith('.sig'):
            continue
        values = {}
        for line in pkginfo(path).splitlines():
            if ' = ' in line and not line.startswith('#'):
                key, value = line.split(' = ', 1)
                values.setdefault(key, []).append(value)
        packages.append(Package(values['pkgname'][0], values['pkgver'][0], values.get('depend', ()),
                                values.get('provides', ()), origin))
    return packages


def unmet(candidates, upstream):
    """[(package, depend text, [what carries that name])] that nothing satisfies."""
    index = {}
    for package in [*candidates, *upstream]:
        for name in {package.name, *(parse(p)[0] for p in package.provides)}:
            index.setdefault(name, []).append(package)
    missing = []
    for package in candidates:
        for text in package.depends:
            depend = parse(text)
            offered = index.get(depend[0], [])
            if not any(satisfies(other, depend) for other in offered):
                missing.append((package, text, offered))
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--new', required=True, type=Path, help='package directory or pacman database being published')
    parser.add_argument('--upstream', action='append', default=[], metavar='NAME=DB',
                        help='a local upstream database; replaces the downloaded set')
    args = parser.parse_args()
    if args.new.is_dir():
        candidates = archive_packages(args.new, 'aurora')
    else:
        candidates = database_packages(args.new.read_bytes(), 'aurora')
    if not candidates:
        raise SystemExit(f'No packages in {args.new}')
    sources = dict(item.split('=', 1) for item in args.upstream)
    upstream = []
    with tempfile.TemporaryDirectory(prefix='aurora-upstream-db-') as temporary:
        if not sources:
            for repo, url in UPSTREAM.items():
                sources[repo] = Path(temporary) / f'{repo}.db'
                lib.download([url], sources[repo], attempts=4, timeout=120)
        for repo, path in sources.items():
            upstream += database_packages(Path(path).read_bytes(), repo)
    missing = unmet(candidates, upstream)
    for package, text, offered in missing:
        have = ', '.join(f'{other.name} {other.version} [{other.origin}]' for other in offered) or 'nothing'
        print(f'UNMET {package.name} {package.version} depends on {text}; available: {have}')
    if missing:
        raise SystemExit(f'{len(missing)} depends of the set cannot be met; pacman -Syu would stop on them.')
    print(f'Every depend of the {len(candidates)} packages is met by the set or {", ".join(sorted(sources))} '
          f'({len(upstream)} upstream packages)')


if __name__ == '__main__':
    main()
