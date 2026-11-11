#!/usr/bin/env python3
"""Import Arch Linux ARM's Firefox recipe into packages/firefox with Aurora's changes.

The recipe is archlinuxarm/PKGBUILDs extra/firefox at the newest commit that
touched it, with these PKGBUILD edits (see `edit_pkgbuild`):

- add rdd-v4l2-request.patch (V4L2 stateless decoders in the RDD sandbox,
  Mozilla bug 2080696; prepare() applies every *.patch source);
- pkgrel N becomes N.1, so the rebuild replaces ALARM's firefox N;
- arch is aarch64 (the native builder's CARCH);
- Arch's Google API key is for Arch Linux only, so it is not used: the build
  has no Google key (as any build without one);
- the release tarball is pinned by its SHA-256/BLAKE2 sums instead of the
  detached signature, which needs Mozilla's key in the builder's keyring.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages' / 'firefox'
UPSTREAM = 'archlinuxarm/PKGBUILDs'
PATH = 'extra/firefox'
OURS = 'rdd-v4l2-request.patch'
KEEP = ('PKGBUILD', 'firefox-symbolic.svg', 'firefox.desktop', 'org.mozilla.firefox.metainfo.xml',
        '0001-Install-under-remoting-name.patch', 'LICENSE')
SUBREL = 1


def once(text, pattern, replacement, what):
    if len(re.findall(pattern, text, flags=re.M)) != 1:
        raise SystemExit(f'PKGBUILD: {what}: expected exactly one match for {pattern!r}')
    return re.sub(pattern, replacement, text, count=1, flags=re.M)


def array(text, name):
    match = re.search(rf'^{name}=\((.*?)\)$', text, re.M | re.S)
    if not match:
        raise SystemExit(f'PKGBUILD: no {name} array')
    return match


def edit_pkgbuild(text, commit, patch):
    text = once(text, r'^pkgrel=(\d+)$', rf'pkgrel=\g<1>.{SUBREL}', 'pkgrel')
    text = once(text, r'^arch=\(x86_64\)$', 'arch=(aarch64)', 'arch')
    text = once(text, r'^_google_api_key=\S+$', '_google_api_key=', 'Google API key')
    text = once(text, r'^ac_add_options --with-google-location-service-api-keyfile=.*\n', '', 'location key')
    text = once(text, r'^ac_add_options --with-google-safebrowsing-api-keyfile=.*\n', '', 'safebrowsing key')
    text = once(text, r'^(  https://archive\.mozilla\.org/\S+\.source\.tar\.xz)\{,\.asc\}$', r'\g<1>', 'tarball')
    # Drop the signature's SKIP entries (second element) and validpgpkeys.
    for name in ('sha256sums', 'b2sums'):
        match = array(text, name)
        sums = re.findall(r"'([^']*)'", match[1])
        if len(sums) < 2 or sums[1] != 'SKIP':
            raise SystemExit(f'PKGBUILD: {name} does not have the signature second')
        sums = [sums[0]] + sums[2:] + [hashlib.new('sha256' if name == 'sha256sums' else 'blake2b', patch).hexdigest()]
        indent = ' ' * (len(name) + 2)
        text = text[:match.start()] + f'{name}=(' + f'\n{indent}'.join(f"'{s}'" for s in sums) + ')' + text[match.end():]
    text = once(text, r'^validpgpkeys=\(\n(?:.*\n)*?\)\n', '', 'validpgpkeys')
    match = array(text, 'source')
    body = match[1].rstrip('\n') + f'\n\n  # Aurora: V4L2 stateless decoders in RDD (Mozilla bug 2080696)\n  {OURS}\n'
    text = text[:match.start()] + f'source=({body})' + text[match.end():]
    header = ('# aurora-builder: heavy\n'
              '# Aurora Silicon: Arch Linux ARM\'s firefox recipe (archlinuxarm/PKGBUILDs\n'
              f'# {PATH} at {commit[:12]}), imported by scripts/import-alarm-firefox.py;\n'
              '# edit that script, not this file.\n')
    return header + text


def api(path):
    request = urllib.request.Request(f'https://api.github.com/{path}', headers={'Accept': 'application/vnd.github+json'})
    try:
        token = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        token = ''
    if token:
        request.add_header('Authorization', f'Bearer {token}')
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--commit', help='archlinuxarm/PKGBUILDs commit (default: newest touching extra/firefox)')
    parser.add_argument('--check', action='store_true', help='fail if packages/firefox differs instead of writing')
    args = parser.parse_args()
    commit = args.commit or api(f'repos/{UPSTREAM}/commits?path={PATH}&per_page=1')[0]['sha']
    patch = (PACKAGE / OURS).read_bytes()
    wanted = {OURS: patch}
    for name in KEEP:
        data = base64.b64decode(api(f'repos/{UPSTREAM}/contents/{PATH}/{name}?ref={commit}')['content'])
        wanted[name] = edit_pkgbuild(data.decode(), commit, patch).encode() if name == 'PKGBUILD' else data
    present = {p.name: p.read_bytes() for p in PACKAGE.iterdir() if p.is_file()}
    if args.check:
        if present != wanted:
            raise SystemExit('packages/firefox is not the import of ' + commit[:12])
        print(f'packages/firefox matches {UPSTREAM} {commit[:12]}')
        return
    for name in set(present) - set(wanted):
        (PACKAGE / name).unlink()
    for name, data in wanted.items():
        if present.get(name) != data:
            (PACKAGE / name).write_bytes(data)
    version = re.search(r'^pkgver=(\S+)$', wanted['PKGBUILD'].decode(), re.M)[1]
    print(f'Imported Firefox {version} from {UPSTREAM} {commit[:12]}')


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    main()
