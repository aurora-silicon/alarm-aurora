#!/usr/bin/env python3
"""Prepare a writable native GE tool from a pinned archive and packaged ntdll."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022):
        raise ValueError(f'not a private user-owned directory: {path}')
    path.chmod(0o700)


@contextlib.contextmanager
def installation_lock(root):
    descriptor = os.open(root / '.prepare.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ValueError('unsafe Proton preparation lock')
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def verified_archive(manifest, cache, offline=None):
    if offline:
        archive = Path(offline)
        if digest(archive) != manifest['archive_sha256']:
            raise ValueError('offline GE archive does not match its pinned SHA256')
        return archive
    private_directory(cache)
    archive = cache / (manifest['archive_sha256'] + '.tar.gz')
    if archive.is_file() and digest(archive) == manifest['archive_sha256']:
        return archive
    print(f"Downloading {manifest['archive_name']} for Aurora Proton...", file=sys.stderr)
    descriptor, temporary = tempfile.mkstemp(prefix='.download.', dir=cache)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as output, urllib.request.urlopen(
                manifest['archive_url'], timeout=60) as source:
            remaining = manifest['archive_bytes']
            while chunk := source.read(min(1024 * 1024, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError('GE download exceeds its pinned archive size')
                output.write(chunk)
            if remaining:
                raise ValueError('GE download is shorter than its pinned archive size')
            output.flush()
            os.fsync(output.fileno())
        if digest(temporary) != manifest['archive_sha256']:
            raise ValueError('GE download does not match its pinned SHA256')
        os.replace(temporary, archive)
        return archive
    finally:
        temporary.unlink(missing_ok=True)


def extract(archive, directory, root_name):
    with tarfile.open(archive, 'r:*') as source:
        members = source.getmembers()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != root_name or '..' in parts:
                raise ValueError(f'unexpected GE archive path: {member.name}')
        source.extractall(directory, members=members, filter='data')
    return directory / root_name


def managed_target(target, source):
    if not target.exists() and not target.is_symlink():
        return False
    marker = target / '.aurora-proton-source'
    if (not target.is_symlink() and target.is_dir() and marker.is_file()
            and not marker.is_symlink() and marker.read_text().strip() == str(source)):
        return True
    raise FileExistsError(f'refusing to overwrite existing compatibility tool: {target}')


def prepare(source, data, cache, offline=None):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((source / 'manifest.json').read_text())
    if (manifest.get('schema') != 1
            or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('archive_sha256', ''))
            or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('ntdll_sha256', ''))
            or not manifest.get('archive_url', '').startswith('https://')
            or not isinstance(manifest.get('archive_bytes'), int) or manifest['archive_bytes'] <= 0
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', manifest.get('archive_root', ''))
            or manifest['archive_root'] in ('.', '..')):
        raise ValueError('invalid packaged Proton manifest')
    root = Path(data) / 'aurora-proton'
    private_directory(root)
    target = root / source.name
    with installation_lock(root):
        if managed_target(target, source):
            return target
        replacement = source / 'ntdll.so'
        if digest(replacement) != manifest['ntdll_sha256']:
            raise ValueError('packaged ntdll does not match its recorded SHA256')
        archive = verified_archive(manifest, Path(cache) / 'aurora-proton', offline)
        print('Preparing the writable Aurora Proton tool...', file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix='.install.', dir=root) as temporary:
            payload = extract(archive, Path(temporary), manifest['archive_root'])
            required = ['proton', 'compatibilitytool.vdf', 'files/lib/wine/aarch64-unix/ntdll.so']
            for name in required:
                path = payload / name
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(payload):
                    raise ValueError(f'invalid GE tool member: {name}')
            for path in [payload, *payload.rglob('*')]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR
                               | (stat.S_IXUSR if path.is_dir() else 0))
            shutil.copyfile(replacement, payload / required[2])
            compatibility = payload / 'compatibilitytool.vdf'
            text = compatibility.read_text()
            if manifest['original_tool'] not in text:
                raise ValueError('GE compatibility-tool identifier is missing')
            compatibility.write_text(text.replace(manifest['original_tool'], manifest['tool']))
            (payload / '.aurora-proton-source').write_text(str(source) + '\n')
            # GNU mv uses RENAME_NOREPLACE for --no-clobber. Staging and target
            # share the same parent filesystem; never replace an unmanaged path.
            subprocess.run(['mv', '-T', '--no-clobber', str(payload), str(target)], check=True)
            if payload.exists():
                raise FileExistsError(f'compatibility-tool target appeared during installation: {target}')
            if not managed_target(target, source):
                raise ValueError('Proton installation did not publish a complete tool')
            return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    arguments = parser.parse_args()
    home = Path.home()
    try:
        target = prepare(arguments.source, os.environ.get('XDG_DATA_HOME') or home / '.local/share',
                         os.environ.get('XDG_CACHE_HOME') or home / '.cache',
                         os.environ.get('AURORA_PROTON_ARCHIVE'))
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'aurora-proton: {error}\n')
    print(target)


if __name__ == '__main__':
    main()
