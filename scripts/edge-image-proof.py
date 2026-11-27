#!/usr/bin/env python3
"""Record what an ALARM Edge image carries: `edge-image-proof.json` schema 2.

aurora-distributions (scripts/edge_train.py) stages a payload only from an
image whose proof names the train's Edge overlay, the Edge feed, the packaged
aurora-edge pair and the image's own kernel and Mesa digests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edgelib  # noqa: E402

PROFILES = ('arch-kde', 'arch-gnome', 'arch-minimal')


def file_digest(path):
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def sections(text):
    """[(section, Server)] in pacman.conf order."""
    result, current = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            current = line[1:-1]
            result.append([current, None])
        elif current and line.startswith('Server = ') and result[-1][1] is None:
            result[-1][1] = line.removeprefix('Server = ')
    return [tuple(item) for item in result]


def proof(root, profile, tag, sources):
    root = Path(root).resolve(strict=True)
    if profile not in PROFILES:
        raise ValueError('not an ALARM profile: ' + profile)
    edgelib.snapshot(tag)
    order = sections((root / 'etc/pacman.conf').read_text())
    names = [name for name, _ in order]
    servers = dict(order)
    if (edgelib.DATABASE not in servers or 'aurora' not in servers
            or names.index(edgelib.DATABASE) > names.index('aurora')
            or servers[edgelib.DATABASE] != edgelib.FEED or servers['aurora'] != edgelib.TESTING_FEED):
        raise ValueError('the image does not follow the Edge feed ahead of Testing')
    kernels = sorted(path for path in (root / 'usr/lib/modules').glob('*/vmlinuz') if path.is_file())
    if len(kernels) != 1:
        raise ValueError('an Edge image carries exactly one kernel')
    dso = root / 'usr/lib/libvulkan_asahi.so'
    for path in (kernels[0], dso):
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('image member escapes its filesystem: ' + str(path))
    return {'schema': 2, 'distribution': 'arch', 'profile': profile, 'channel': 'edge',
            'snapshot': tag, 'feed': edgelib.FEED, 'packaged_sources': sources,
            'files': {'kernelImageSHA256': file_digest(kernels[0]), 'mesaDsoSHA256': file_digest(dso)}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--edge-sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.edge_sources.read_text())
    if record.get('schema') != 1 or record.get('channel') != 'edge':
        parser.error('not an Edge snapshot record')
    args.output.write_text(json.dumps(proof(args.root, args.profile, args.snapshot, record['packaged_sources']),
                                      indent=2, sort_keys=True) + '\n')
