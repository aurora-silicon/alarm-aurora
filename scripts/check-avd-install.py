#!/usr/bin/env python3
"""Verify installed private binaries, dynamic linking and pacman co-installation."""
from pathlib import Path
import re
import subprocess


def run(*args):
    text = subprocess.check_output(args, text=True)
    print(text, end='')
    return text


assert 'v4l2request' in run('ffmpeg-avd', '-hide_banner', '-hwaccels').splitlines()
modes = run('mpv-avd', '--no-config', '--hwdec=help')
assert re.search(r'\bv4l2request\b', modes)
assert re.search(r'\bv4l2request-copy\b', modes)
for name in ('ffmpeg-avd', 'ffprobe-avd', 'mpv-avd'):
    binary = f'/usr/bin/{name}'
    assert 'AArch64' in run('readelf', '-h', binary)
    linked = run('ldd', binary)
    assert 'not found' not in linked
    ffmpeg = re.findall(r'\b(lib(?:avcodec|avdevice|avfilter|avformat|avutil|swresample|swscale)\.so\S*) => (\S+)', linked)
    assert ffmpeg, name
    assert all(path.startswith('/usr/lib/aurora-avd/') for _, path in ffmpeg), ffmpeg
    dynamic = run('readelf', '-d', binary)
    assert '/usr/lib/aurora-avd' in dynamic
    assert '/tmp/' not in dynamic and '/stage/' not in dynamic, dynamic
stock = set(run('pacman', '-Qql', 'ffmpeg', 'mpv').splitlines())
candidate = set(run('pacman', '-Qql', 'ffmpeg-avd', 'mpv-avd').splitlines())
assert not {p for p in stock & candidate if not p.endswith('/')}, stock & candidate
for path in candidate:
    assert path.endswith('/') or path.startswith(('/usr/lib/aurora-avd/', '/usr/share/licenses/')) or path in {
        '/usr/bin/ffmpeg-avd', '/usr/bin/ffprobe-avd', '/usr/bin/mpv-avd'}, path
print('Private FFmpeg library resolution and stock package co-installation passed')
