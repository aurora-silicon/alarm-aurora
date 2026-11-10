# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise ENOSPC through the patched driver and fprintd using fake storage."""
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FPRINTD = ROOT / 'packages/fprintd-aurora'
LIBFPRINT = ROOT / 'packages/libfprint-aurora'


def recipe(directory, script):
    return subprocess.check_output(['bash', '-c', 'source "$1"; ' + script, 'recipe',
                                    str(directory / 'PKGBUILD')], text=True)


def prepared_patches(directory):
    # The order prepare() applies them in, which is the order that matters.
    return re.findall(r'^\s*patch -Np1 -i "\$srcdir/(\S+)"$',
                      (directory / 'PKGBUILD').read_text(), re.M)


class TouchIdCapacityTests(unittest.TestCase):
    def test_enospc_reports_full_without_collecting_any_sep_print(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            # Only these unchanged upstream functions are needed. Apply the
            # package's patch, not a reimplementation of the fixed callback.
            shutil.copytree(ROOT / 'tests/fixtures/fprintd-1.94.5', source, dirs_exist_ok=True)
            subprocess.run(['git', 'apply', str(FPRINTD / '0005-aurora-report-data-full-without-garbage-collection.patch')],
                           cwd=source, check=True)
            # The first patch creates the whole driver. The include filter
            # avoids needing unrelated libfprint files while applying the
            # driver's patch stack in prepare()'s order.
            patches = prepared_patches(LIBFPRINT)
            self.assertEqual(patches[0], 'libfprint-1.94.100-apple-sep.patch')
            self.assertEqual(patches[-1], '0011-aurora-report-fingerprint-storage-full.patch')
            for patch in patches:
                subprocess.run(['git', 'apply', '--include=libfprint/drivers/aurora/aurora.c',
                                str(LIBFPRINT / patch)], cwd=source, check=True)
            self.assertRegex((source / 'libfprint/drivers/aurora/aurora.c').read_text(),
                             r'(?m)^#define FP_COMPONENT "apple-sep"$')
            subprocess.run(['python3', str(FPRINTD / 'test_enroll_capacity.py'),
                            str(source / 'src/device.c'), '--aurora',
                            str(source / 'libfprint/drivers/aurora/aurora.c'),
                            '--enroll-utils', str(source / 'utils/enroll.c')], check=True)

    def test_data_full_driver_requires_the_guarded_daemon(self):
        provides = recipe(FPRINTD, 'printf "%s\\n" "${provides[@]}"').split()
        self.assertIn('fprintd-aurora-no-enroll-gc=1', provides)
        self.assertEqual(prepared_patches(FPRINTD)[-1],
                         '0005-aurora-report-data-full-without-garbage-collection.patch')
        # package() sets the library's runtime depends.
        depends = recipe(LIBFPRINT,
                         'meson() { :; }; install() { :; }; package; printf "%s\\n" "${depends[@]}"').split()
        self.assertIn('fprintd-aurora-no-enroll-gc>=1', depends)
        check = recipe(FPRINTD, 'declare -f check')
        self.assertIn('test_enroll_capacity.py', check)
        self.assertIn('--enroll-utils', check)

    def test_local_source_checksums_are_current(self):
        for directory in (FPRINTD, LIBFPRINT):
            pairs = recipe(directory, 'for i in "${!source[@]}"; do '
                           'printf "%s %s\\n" "${source[$i]}" "${sha256sums[$i]}"; done').splitlines()
            listed = {line.split()[0] for line in pairs}
            for patch in prepared_patches(directory):
                self.assertIn(patch, listed)
            for line in pairs:
                name, digest = line.split()
                if '://' not in name:
                    with self.subTest(package=directory.name, source=name):
                        self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
