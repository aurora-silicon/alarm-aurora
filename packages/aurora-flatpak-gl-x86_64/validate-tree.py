#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the x86_64 GL extension trees before packaging or export."""
import argparse
import configparser
import json
from pathlib import Path
import re
import struct

BRANCHES = ('25.08', '26.08')
ID = 'org.freedesktop.Platform.GL.aurora'
PREFIX = '/usr/lib/x86_64-linux-gnu/GL/aurora/'
X86_64 = 62


def elf_machine(path):
    with open(path, 'rb') as stream:
        header = stream.read(20)
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01':
        return None
    return struct.unpack('<H', header[18:20])[0]


def validate_payload(root, commit):
    root = Path(root).resolve()
    if (root / '.aurora-mesa-commit').read_text().strip() != commit:
        raise ValueError('GL payload has the wrong Mesa commit')
    for name in ('lib/libvulkan_asahi.so', 'lib/libEGL_mesa.so.0', 'lib/libGLX_mesa.so.0',
                 'lib/dri/asahi_dri.so', 'lib/dri/zink_dri.so',
                 'GuestThunks/libVDSO-guest.so'):
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f'{name}: symlink escapes the payload')
        if elf_machine(path) != X86_64:
            raise ValueError(f'{name}: not an x86-64 ELF library')
    for path in root.rglob('*.so*'):
        if path.is_file() and not path.is_symlink() and b'libLLVM.so' in path.read_bytes():
            raise ValueError(f'{path.relative_to(root)}: links LLVM')
    if (root / 'fex').exists():
        raise ValueError('the FEX bundle is added from fex-emu on the Mac, not here')
    for name, expected_library in (
            ('vulkan/icd.d/asahi_icd.x86_64.json', 'libvulkan_asahi.so'),
            ('glvnd/egl_vendor.d/50_mesa.json', 'libEGL_mesa.so.0')):
        data = json.loads((root / name).read_text())['ICD']
        library = data['library_path'].removeprefix(PREFIX)
        path = root / (library if '/' in library else 'lib/' + library)
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'{name}: library_path is absent from the payload')
        if path.resolve() != (root / 'lib' / expected_library).resolve(strict=True):
            raise ValueError(f'{name}: library_path selects the wrong driver')
    defaults = (root / 'share/drirc.d/00-hk-defaults.conf').read_text()
    if 'hk_report_honeykrisp_driver_id' not in defaults:
        raise ValueError('GL payload lacks the DXVK/vkd3d driver-ID defaults')
    expected = f'(git-{commit[:10]}), Borealis'.encode()
    if expected not in (root / 'lib/libvulkan_asahi.so').read_bytes():
        raise ValueError('GL driverInfo lacks the pinned commit and Borealis name')


def validate(trees, commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('expected a full Mesa commit')
    trees = Path(trees)
    for branch in BRANCHES:
        tree = trees / branch
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read_string((tree / 'metadata').read_text())
        if (metadata.get('Runtime', 'name') != ID
                or metadata.get('ExtensionOf', 'ref') != f'runtime/org.freedesktop.Platform/x86_64/{branch}'
                or metadata.getint('ExtensionOf', 'priority') != 10):
            raise ValueError(f'{branch}: wrong GL extension identity or priority')
        validate_payload(tree / 'files', commit)
        print(f'{ID}/x86_64/{branch}: complete x86_64 GL payload, Mesa {commit}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trees', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    validate(args.trees, args.commit)
