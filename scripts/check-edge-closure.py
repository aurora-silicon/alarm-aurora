#!/usr/bin/env python3
"""Refuse an [aurora-edge] overlay that does not close over what Edge installs resolve against.

Edge installs list [aurora-edge] ahead of [aurora] (Testing), and Arch Linux
ARM's core, extra, alarm and aur plus asahi-alarm after them. libalpm takes a
package from the first repository that has its name, and resolves a depend from
the first repository whose package satisfies it. So:

- an overlay depend on an overlay name must be met by the overlay;
- an overlay depend on any other Aurora name (every pkgname and provide of
  packages/*, and every package and provide the two feeds serve) must be met by
  Testing: Aurora packages never come from upstream;
- every other overlay depend must be met by the upstream repositories;
- a Testing package that depends on an overlay name must be met by the overlay's
  version, or libalpm silently installs the Testing copy;
- no Testing package may conflict with an overlay package, or the reverse.

Depends are matched with check-feed-depends.py's libalpm rules.

    check-edge-closure.py --overlay aurora-edge.db.tar.gz --testing aurora.db.tar.gz [--upstream NAME=DB ...]

Without --upstream, the upstream databases are downloaded. A missing or
unreadable database is an error, never a pass.
"""
import argparse
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import edgelib  # noqa: E402
import updatelib as lib  # noqa: E402

_spec = importlib.util.spec_from_file_location('check_feed_depends', ROOT / 'scripts/check-feed-depends.py')
feed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feed)


def aurora_names(root=ROOT):
    """Every package name and literal provide the repository's recipes declare."""
    names = set()
    for recipe in sorted(Path(root).glob('packages/*/PKGBUILD')):
        text = recipe.read_text()
        names.update(edgelib.pkgnames(text))
        names.update(edgelib.provided_names(text))
    return names


def _package(row, origin):
    return feed.Package(row['name'], row['version'], row['depends'], row['provides'], origin)


def _names(row):
    return {row['name'], *(feed.parse(text)[0] for text in row['provides'])}


def problems(overlay, testing, upstream, aurora):
    """Human-readable closure failures; empty when the overlay is safe to serve beside Testing.

    `overlay` and `testing` are rows (name, version, depends, conflicts,
    provides); `upstream` are check-feed-depends Packages; `aurora` the
    Aurora-owned names.
    """
    found = []
    overlay_names = {name for row in overlay for name in _names(row)}
    shadowed = {row['name'] for row in overlay}
    visible = [row for row in testing if row['name'] not in shadowed]
    owned = set(aurora) | overlay_names | {name for row in testing for name in _names(row)}
    edge = [_package(row, 'aurora-edge') for row in overlay]
    served = [_package(row, 'aurora') for row in visible]
    for row in overlay:
        for text in row['depends']:
            relation = feed.parse(text)
            if relation[0] in overlay_names:
                if not any(feed.satisfies(other, relation) for other in edge):
                    found.append(f'{row["name"]} needs {text}, which [aurora-edge] does not meet')
            elif relation[0] in owned:
                if not any(feed.satisfies(other, relation) for other in served):
                    found.append(f'{row["name"]} needs {text}: an Aurora package Testing does not serve '
                                 'at that version')
            elif not any(feed.satisfies(other, relation) for other in upstream):
                found.append(f'{row["name"]} needs {text}, which no Arch Linux ARM or asahi-alarm repository serves')
    for row in visible:
        for text in row['depends']:
            relation = feed.parse(text)
            if relation[0] in overlay_names and not any(feed.satisfies(other, relation) for other in edge):
                found.append(f'Testing {row["name"]} needs {text}: [aurora-edge] does not meet it, '
                             'so pacman would install the Testing copy')
        for text in row['conflicts']:
            relation = feed.parse(text)
            for other in edge:
                if feed.satisfies(other, relation):
                    found.append(f'Testing {row["name"]} conflicts with {text}: [aurora-edge] '
                                 f'serves {other.name} {other.version}')
    for row in overlay:
        for text in row['conflicts']:
            relation = feed.parse(text)
            for other in served:
                if feed.satisfies(other, relation):
                    found.append(f'{row["name"]} conflicts with {text}: Testing serves {other.name} {other.version}')
    return found


def database(data):
    """Rows of a pacman database archive: check-feed-depends' packages plus their conflicts."""
    entries = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive:
            directory, _, filename = member.name.rpartition('/')
            if not member.isfile() or filename not in ('desc', 'depends'):
                continue
            entry, key = entries.setdefault(directory, {}), None
            for line in archive.extractfile(member).read().decode().splitlines():
                if line.startswith('%') and line.endswith('%'):
                    key = line.strip('%')
                    entry.setdefault(key, [])
                elif line and key in ('NAME', 'CONFLICTS'):
                    entry[key].append(line)
    conflicts = {entry['NAME'][0]: entry.get('CONFLICTS', []) for entry in entries.values() if entry.get('NAME')}
    packages = feed.database_packages(data, 'db')
    if not packages:
        raise ValueError('the database lists no packages')
    return [{'name': package.name, 'version': package.version, 'depends': list(package.depends),
             'provides': list(package.provides), 'conflicts': list(conflicts.get(package.name, []))}
            for package in packages]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--testing', type=Path, required=True)
    parser.add_argument('--upstream', action='append', default=[], metavar='NAME=DB',
                        help='a local upstream database; replaces the downloaded set')
    args = parser.parse_args()
    # Local databases first: a missing or unreadable one fails before any download.
    overlay = database(args.overlay.read_bytes())
    testing = database(args.testing.read_bytes())
    sources = dict(item.split('=', 1) for item in args.upstream)
    upstream = []
    with tempfile.TemporaryDirectory(prefix='aurora-edge-upstream-') as temporary:
        if not sources:
            for repo, url in feed.UPSTREAM.items():
                sources[repo] = Path(temporary) / f'{repo}.db'
                lib.download([url], sources[repo], attempts=4, timeout=120)
        for repo, path in sources.items():
            upstream += feed.database_packages(Path(path).read_bytes(), repo)
    found = problems(overlay, testing, upstream, aurora_names())
    for line in found:
        print(line, file=sys.stderr)
    if found:
        raise SystemExit('The [aurora-edge] overlay does not close over Testing and Arch Linux ARM.')
    print(f'[aurora-edge] closes over Testing and {", ".join(sorted(sources))}.')


if __name__ == '__main__':
    main()
