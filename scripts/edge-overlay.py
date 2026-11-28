#!/usr/bin/env python3
"""Collect the unsigned [aurora-edge] overlay from one edge-staging package build.

Keeps exactly the kernel and Mesa packages (edgelib.FAMILIES), refuses any
other recipe, and writes `edge-sources.json` with the packaged aurora-edge pair.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edgelib  # noqa: E402


def pkginfo(path):
    text = subprocess.check_output(['bsdtar', '-xOf', str(path), '.PKGINFO'], text=True)
    fields = {}
    for line in text.splitlines():
        key, _, value = line.partition(' = ')
        fields.setdefault(key, value)
    return fields.get('pkgbase') or fields['pkgname'], fields['pkgname'], fields['pkgver']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True, help='downloaded, attested package artifacts')
    parser.add_argument('--sources', type=Path, required=True, help='sources.json of the edge-staging head')
    parser.add_argument('--recipes', type=Path, required=True,
                        help='<recipe>/PKGBUILD of the four Edge recipes at the edge-staging head')
    parser.add_argument('--trees', type=Path, required=True)
    parser.add_argument('--build-run', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('use a fresh output directory')
    files = sorted(path for path in args.packages.rglob('*.pkg.tar.*') if not path.name.endswith('.sig'))
    rows = {path: pkginfo(path) for path in files}
    names = edgelib.select(list(rows.values()))
    expected = [name for bases in edgelib.FAMILIES.values() for base in bases
                for name in edgelib.pkgnames((args.recipes / base / 'PKGBUILD').read_text())]
    edgelib.check_complete(names, expected)
    args.output.mkdir(parents=True)
    for path in files:
        shutil.copyfile(path, args.output / path.name)
    trees = json.loads(args.trees.read_text())
    record = {'schema': 1, 'channel': 'edge', 'build_run': args.build_run, 'packages': names,
              'packaged_sources': edgelib.packaged_sources(json.loads(args.sources.read_text()),
                                                           trees)}
    if 'linux_release_sha256' in trees:
        record['kernel_release'] = {'tag': 'aurora-edge', 'source_sha256': trees['linux_release_sha256']}
    args.record.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(f'Edge overlay: {len(names)} kernel and Mesa packages from build {args.build_run}')


if __name__ == '__main__':
    main()
