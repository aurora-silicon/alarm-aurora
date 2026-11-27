#!/usr/bin/env python3
"""Check a finished mesa-aurora-fex-guest payload without running guest code."""
import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import struct
import sys

LAYER = 'usr/share/guestos/aurora-fex-mesa-layer'
ARCHITECTURES = (
    ('x86_64-linux-gnu', 'x86_64', 'lib', 2, 62),
    ('i386-linux-gnu', 'i686', 'lib32', 1, 3),
)


class Payload:
    """Resolve guest symlinks inside this tree, never against the host root.

    Inputs must be quiescent while checking (no concurrent extraction/writers).
    Absolute links are guest-absolute; relative links cannot climb above root.
    """
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError(f'{root}: expected a directory')

    def path(self, name):
        pending = list(PurePosixPath(name).parts)
        parts = []
        links = 0
        while pending:
            part = pending.pop(0)
            if part in ('/', '//'):
                parts = []
                continue
            if part in ('', '.'):
                continue
            if part == '..':
                if not parts:
                    raise ValueError(f'{name}: path escapes the payload')
                parts.pop()
                continue
            candidate = self.root.joinpath(*parts, part)
            try:
                mode = candidate.lstat().st_mode
            except FileNotFoundError:
                raise ValueError(f'{name}: missing packaged path {candidate.relative_to(self.root)}') from None
            if stat.S_ISLNK(mode):
                links += 1
                if links > 40:
                    raise ValueError(f'{name}: symlink loop or chain longer than 40 links')
                pending = list(PurePosixPath(candidate.readlink()).parts) + pending
            else:
                if pending and not stat.S_ISDIR(mode):
                    raise ValueError(f'{name}: {candidate.relative_to(self.root)} is not a directory')
                parts.append(part)
        return self.root.joinpath(*parts)

    def file(self, name):
        path = self.path(name)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError(f'{name}: expected a regular packaged file')
        return path

    def json(self, name):
        try:
            return json.loads(self.file(name).read_text(encoding='utf-8'))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f'{name}: invalid JSON: {error}') from None

    def elf(self, name, elf_class, machine):
        with self.file(name).open('rb') as stream:
            header = stream.read(64)
        size = 64 if elf_class == 2 else 52
        # Only ELF headers are inspected, not dynamic dependency closure.
        if (len(header) < size or header[:7] != b'\x7fELF' + bytes((elf_class, 1, 1))
                or struct.unpack_from('<HHI', header, 16) != (3, machine, 1)
                or struct.unpack_from('<H', header, 52 if elf_class == 2 else 40)[0] != size):
            arch = 'x86_64 (EM_X86_64=62)' if machine == 62 else 'i686 (EM_386=3)'
            bits = 64 if elf_class == 2 else 32
            raise ValueError(f'{name}: expected little-endian ELF{bits} '
                             f'ET_DYN library for {arch}; invalid or wrong-architecture ELF header')


def check_provider(payload):
    name = 'graphics_provider.json'
    data = payload.json(name)
    provider = data.get('graphics_provider_v0') if isinstance(data, dict) else None
    if not isinstance(provider, dict) or provider.get('root') != './':
        raise ValueError(f'{name}: graphics_provider_v0.root must be "./" (this layer)')
    architectures = provider.get('architectures')
    if not isinstance(architectures, dict):
        raise ValueError(f'{name}: missing architectures mapping')
    for arch, _, libdir, _, _ in ARCHITECTURES:
        mapping = architectures.get(arch)
        expected = {'dri': f'/usr/{libdir}/dri',
                    'fallback_library_paths': [f'/usr/{libdir}'],
                    'gconv': f'/usr/{libdir}/gconv'}
        for key, value in expected.items():
            if not isinstance(mapping, dict) or mapping.get(key) != value:
                raise ValueError(f'{name}: {arch}.{key} must be {value!r}')
        # gconv comes from the underlying guest root, not this Mesa layer.
        if not payload.path(f'usr/{libdir}/dri').is_dir():
            raise ValueError(f'{name}: {arch} DRI path is not a packaged directory')


def check_lib64(payload):
    usr = payload.path('usr')
    path = usr / 'lib64'
    if path.is_symlink():
        if payload.path('usr/lib64') != payload.path('usr/lib'):
            raise ValueError('usr/lib64: only a symlink to packaged usr/lib is allowed')
    elif path.exists():
        raise ValueError('usr/lib64: real path shadows the Arch guest layout; use usr/lib and usr/lib32')


def check_icd(payload, arch, libdir, elf_class, machine):
    name = f'usr/share/vulkan/icd.d/asahi_icd.{arch}.json'
    data = payload.json(name)
    icd = data.get('ICD') if isinstance(data, dict) else None
    expected = f'/usr/{libdir}/libvulkan_asahi.so'
    if not isinstance(icd, dict) or icd.get('library_path') != expected:
        raise ValueError(f'{name}: ICD.library_path must be {expected!r}')
    payload.elf(expected, elf_class, machine)


def validate_payload(root):
    """Return all independent failures in a finished layer (empty means pass)."""
    payload = Payload(root)
    errors = []

    def check(function, *args):
        try:
            function(payload, *args)
        except (OSError, ValueError) as error:
            errors.append(str(error))

    check(check_lib64)
    check(check_provider)
    for _, arch, libdir, elf_class, machine in ARCHITECTURES:
        check(check_icd, arch, libdir, elf_class, machine)
        for library in ('libdisplay-info.so.3', 'libEGL_mesa.so.0', 'libGLX_mesa.so.0',
                        'libgbm.so.1', 'gbm/dri_gbm.so', 'dri/asahi_dri.so',
                        'dri/zink_dri.so', 'dri/swrast_dri.so'):
            check(Payload.elf, f'usr/{libdir}/{library}', elf_class, machine)

        def gallium(payload):
            directory = payload.path(f'usr/{libdir}')
            libraries = sorted(directory.glob('libgallium-*.so'))
            if not libraries:
                raise ValueError(f'usr/{libdir}/libgallium-*.so: missing packaged Mesa library')
            for library in libraries:
                payload.elf(f'usr/{libdir}/{library.name}', elf_class, machine)

        check(gallium)
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    roots = parser.add_mutually_exclusive_group(required=True)
    roots.add_argument('--package-root', type=Path, help='extracted finished package root (not srcdir or pkgdir parent)')
    roots.add_argument('--layer-root', type=Path, help='finished aurora-fex-mesa-layer directory itself')
    args = parser.parse_args(argv)
    try:
        if args.package_root is not None:
            package = Payload(args.package_root)
            root = package.path(LAYER)
            if root != package.root / LAYER:
                raise ValueError(f'{LAYER}: package layer location must not be redirected by symlinks')
        else:
            root = args.layer_root
        errors = validate_payload(root)
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        for error in errors:
            print(f'FEX guest payload: {error}', file=sys.stderr)
        return 1
    print('FEX guest payload: OK (Arch x86_64 usr/lib and i686 usr/lib32; final provider, ICDs and required ELF headers)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
