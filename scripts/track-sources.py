#!/usr/bin/env python3
"""Propose Arch Linux ARM recipe updates for tracked upstream branches.

`plan` is read-only with respect to GitHub: it writes a patch and a result
record under --output. `open-pr` and `merge` act on GitHub with the workflow
token. See docs/updates.md.
"""
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trackerlib as tl  # noqa: E402
import updatelib as lib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECIPES = {'kernel-aurora': 'linux-aurora', 'aura': 'aura', 'mesa-aurora': 'mesa-aurora'}
KINDS = {'kernel-aurora': 'kernel', 'mesa-aurora': 'mesa'}
CI_WORKFLOWS = ['packages.yml']
# The only files a tracker proposal may change.
PATCH_PATHS = [r'sources\.json', r'packages/(linux-aurora|aura|mesa-aurora)/[^/]+']


def local_sources(directory):
    """Digests of the recipe's local files, to refresh sha256sums afterwards."""
    return {path.name: lib.sha256_file(path) for path in directory.iterdir()
            if path.is_file() and path.name != 'PKGBUILD'}


def update_recipe(root, item, today):
    """Apply one source update to its PKGBUILD. Returns review notes."""
    key = item['key']
    directory = root / 'packages' / RECIPES[key]
    before = local_sources(directory)
    for path in sorted(p for p in directory.iterdir() if p.is_file()):
        text = path.read_text()
        updated = tl.replace_commit(text, item['old'], item['new'])
        if updated != text:
            path.write_text(updated)
    pkgbuild = directory / 'PKGBUILD'
    text = pkgbuild.read_text()
    if f'_commit={item["new"]}' not in text:
        raise ValueError(f'{key}: PKGBUILD does not pin _commit to the new commit')
    notes = []
    stamp = today.strftime('%Y%m%d')
    if key == 'aura':
        text, old_ver, new_ver = tl.bump_assignment(
            text, 'pkgver', lambda value: re.sub(r'\.r\d{8}$', '', value) + '.r' + stamp)
    elif key == 'mesa-aurora':
        # 26.3.0-devel at a7e83fc2bc2, packaged on 2026-10-23:
        # 26.3.0_devel.20261023.a7e83fc2bc2
        upstream = item['upstream_version'].replace('-', '_')
        text, old_ver, new_ver = tl.bump_assignment(
            text, 'pkgver', lambda _: f'{upstream}.{stamp}.{item["new"][:11]}')
    elif key == 'kernel-aurora':
        text, old_ver, new_ver = tl.bump_assignment(text, '_auroraver', lambda _: tl.pacman_version(item['version']))
        if old_ver != new_ver:
            notes.append(f'kernel version {old_ver} -> {new_ver}: review the configuration fragments')
    else:
        raise ValueError(f'no recipe adapter for {key}')
    text, old_rel, new_rel = tl.bump_assignment(
        text, 'pkgrel', lambda value: '1' if old_ver != new_ver else str(int(value) + 1))
    pkgbuild.write_text(text)
    tl.refresh_pkgbuild_checksums(directory, before)
    item['package_version'] = f'{new_ver}-{new_rel}'
    return notes


def run_checks(root):
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'],
                   cwd=root, check=True)
    for path in sorted((root / 'packages').glob('*/PKGBUILD')):
        subprocess.run(['bash', '-n', str(path)], check=True)


def ci_inputs(packages):
    return {'packages.yml': {'packages': ' '.join(packages)}}


if __name__ == '__main__':
    tl.main(sys.modules[__name__])
