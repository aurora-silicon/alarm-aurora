"""FFmpeg and gst-plugins-good are ALARM's recipes plus the V4L2 ProRes patches."""
import hashlib
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FFMPEG_PATCHES = [
    '0001-avcodec-v4l2_buffers-use-the-driver-s-strides-for-si.patch',
    '0002-avcodec-v4l2_context-pick-the-raw-V4L2-format-the-dr.patch',
    '0003-avcodec-v4l2_m2m-add-ProRes-decoder-and-encoder.patch',
]
GST_PATCHES = ['0001-v4l2-add-ProRes-decoder-and-encoder.patch',
               '0002-v4l2videodec-switch-to-a-supported-capture-format-be.patch']


def recipe(name, expression):
    return subprocess.check_output(['bash', '-c', 'cd "$1"; source ./PKGBUILD; ' + expression,
                                    'recipe', str(ROOT / 'packages' / name)], text=True)


class ProResV4l2Tests(unittest.TestCase):
    def test_every_local_source_is_checked(self):
        for name in ('ffmpeg', 'gst-plugins-good'):
            sources = recipe(name, 'printf "%s\\n" "${source[@]}"').split()
            sums = recipe(name, 'printf "%s\\n" "${b2sums[@]}"').split()
            self.assertEqual(len(sources), len(sums), name)
            for source, digest in zip(sources, sums):
                if '://' not in source:
                    with self.subTest(package=name, source=source):
                        data = (ROOT / 'packages' / name / source).read_bytes()
                        self.assertEqual(hashlib.blake2b(data).hexdigest(), digest)

    def test_patches_are_sources_and_applied(self):
        for name, patches in (('ffmpeg', FFMPEG_PATCHES), ('gst-plugins-good', GST_PATCHES)):
            sources = recipe(name, 'printf "%s\\n" "${source[@]}"').split()
            prepare = recipe(name, 'declare -f prepare')
            for patch in patches:
                with self.subTest(package=name, patch=patch):
                    self.assertIn(patch, sources)
                    self.assertIn('../' + patch, prepare)

    def test_ffmpeg_requires_v4l2_mem2mem_and_replaces_alarm(self):
        text = (ROOT / 'packages/ffmpeg/PKGBUILD').read_text()
        self.assertIn('    --enable-v4l2-m2m \\\n', text)
        # ALARM's 2:9.0.2-5; the Aurora pkgrel sorts above it.
        self.assertEqual(recipe('ffmpeg', 'echo "$epoch:$pkgver-$pkgrel"').strip(), '2:9.0.2-5.1')

    def test_gst_plugins_good_installs_with_alarms_gstreamer_rebuilds(self):
        depends = recipe('gst-plugins-good', 'printf "%s\\n" "${depends[@]}"').split()
        # ALARM's split packages pin each other at pkgver-pkgrel; this one
        # must not, or ALARM's next GStreamer rebuild cannot install.
        self.assertIn('gstreamer>=1.28.9', depends)
        self.assertIn('gst-plugins-base-libs>=1.28.9', depends)
        self.assertFalse([d for d in depends if d.startswith('gst') and '=' in d and '>=' not in d])
        self.assertEqual(recipe('gst-plugins-good', 'echo "$pkgver-$pkgrel"').strip(), '1.28.9-3.1')
        build = recipe('gst-plugins-good', 'declare -f build')
        # ALARM ships these plugins in gst-plugin-gtk, -qmlgl and -qml6.
        for option in ('gtk3', 'qt5', 'qt6'):
            self.assertIn(f'-D {option}=disabled', build)


if __name__ == '__main__':
    unittest.main()
