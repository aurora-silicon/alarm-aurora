#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
ROOT = Path(__file__).resolve().parents[1]
lock = json.loads((ROOT / 'images/base.json').read_text())
output = ROOT / 'cache/base'
output.mkdir(parents=True, exist_ok=True)
archive = output / 'ArchLinuxARM-aarch64.tar.gz'
for url, target in [(lock['url'], archive), (lock['signature_url'], archive.with_suffix('.gz.sig'))]:
    if not target.exists():
        pending = target.with_suffix('.download')
        with urllib.request.urlopen(url, timeout=180) as source, pending.open('wb') as dest:
            shutil.copyfileobj(source, dest)
        pending.rename(target)
with archive.open('rb') as stream:
    if hashlib.file_digest(stream, 'sha256').hexdigest() != lock['sha256']:
        raise SystemExit('ALARM root filesystem digest mismatch')
with tempfile.TemporaryDirectory() as home:
    gpg = ['gpg', '--no-options', '--homedir', home, '--batch']
    subprocess.run(gpg + ['--import', str(ROOT / 'keys/archlinuxarm-build-system.asc')], check=True)
    result = subprocess.run(gpg + ['--status-fd', '1', '--verify', str(archive.with_suffix('.gz.sig')), str(archive)], check=True, text=True, capture_output=True)
    if '[GNUPG:] VALIDSIG ' + lock['signing_fingerprint'] not in result.stdout:
        raise SystemExit('ALARM root filesystem signer mismatch')
print(archive)
