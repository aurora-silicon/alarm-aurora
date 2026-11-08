"""PipeWire is ALARM's recipe plus the Aurora patches Fedora carries."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / 'packages/pipewire'
PATCHES = [
    '1000-module-raop-match-an-RTSP-reply-without-CSeq-to-the-.patch',
    '1001-module-raop-sink-say-why-a-receiver-session-was-drop.patch',
    '1002-module-raop-sink-default-sess.latency.msec-to-whole-.patch',
    '1003-module-raop-discover-reload-a-sink-that-unloaded-its.patch',
    '1004-module-raop-sink-give-up-on-a-session-that-never-rea.patch',
    '1005-filter-graph-follow-plugin-latency-after-activation.patch',
    '1006-filter-graph-keep-the-software-volume-at-unity-on-ev.patch',
    '1007-alsa-back-off-a-refused-snd_pcm_start-and-rate-limit.patch',
    '1008-alsa-a-start-on-a-suspended-PCM-is-expected-not-an-error.patch',
]


def recipe(expression):
    return subprocess.check_output(['bash', '-c', 'cd "$1"; source ./PKGBUILD; ' + expression,
                                    'recipe', str(RECIPE)], text=True)


class PipeWireTests(unittest.TestCase):
    def test_every_patch_is_a_checked_source(self):
        sources = recipe('printf "%s\\n" "${source[@]}"').split()
        sums = recipe('printf "%s\\n" "${b2sums[@]}"').split()
        self.assertEqual(len(sources), len(sums))
        self.assertEqual([s for s in sources if s.endswith('.patch')], PATCHES)
        self.assertEqual(sorted(p.name for p in RECIPE.glob('*.patch')), PATCHES)
        for source, digest in zip(sources, sums):
            if '://' not in source:
                with self.subTest(source=source):
                    self.assertEqual(hashlib.blake2b((RECIPE / source).read_bytes()).hexdigest(), digest)

    def test_prepare_applies_the_patches_in_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            srcdir = Path(temporary)
            (srcdir / 'pipewire').mkdir()
            bin_dir = srcdir / 'bin'
            bin_dir.mkdir()
            log = srcdir / 'applied'
            fake = bin_dir / 'patch'
            fake.write_text('#!/bin/bash\nprintf "%s\\n" "${@: -1}" >> "$PATCH_LOG"\n')
            fake.chmod(0o755)
            env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'PATCH_LOG': str(log)}
            subprocess.run(['bash', '-euo', 'pipefail', '-c', 'source "$1"; cd "$2"; prepare',
                            'prepare', str(RECIPE / 'PKGBUILD'), str(srcdir)],
                           env=env, check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(log.read_text().split(), ['../' + name for name in PATCHES])

    def test_release_replaces_alarm_and_runs_the_test_suite(self):
        text = (RECIPE / 'PKGBUILD').read_text()
        self.assertEqual(recipe('echo "$epoch:$pkgver"').strip(), '1:1.6.10')
        # ALARM's 1:1.6.10-1; a dotted pkgrel sorts above it.
        self.assertRegex(recipe('echo "$pkgrel"').strip(), r'^1\.[1-9][0-9]*$')
        self.assertEqual(recipe('echo "${arch[*]}"').strip(), 'aarch64')
        self.assertIn('1b902bd4b08f37ae3798a70ec597646a0c370b84', text)
        self.assertRegex(text, re.compile(r'^check\(\) \{\n  meson test -C build', re.M))
        # Every split package requires the exact matching build.
        self.assertIn('"libpipewire=$epoch:$pkgver-$pkgrel"', text)


if __name__ == '__main__':
    unittest.main()
