# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise ENOSPC through the patched driver and fprintd using fake storage."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
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
    @unittest.skipUnless(os.environ.get('TOUCHID_SOURCE_ARCHIVES'),
                         'set TOUCHID_SOURCE_ARCHIVES to cached fprintd.tar.gz and libfprint.tar.gz')
    def test_full_public_prepare_stacks_preserve_both_features(self):
        # Optional offline integration: use checksum-verified public archives,
        # run the actual prepare() functions, and compile only fake-call tests.
        with tempfile.TemporaryDirectory() as directory:
            roots = []
            for package, archive in ((FPRINTD, 'fprintd.tar.gz'), (LIBFPRINT, 'libfprint.tar.gz')):
                source = Path(directory) / package.name
                shutil.copytree(package, source)
                data = (Path(os.environ['TOUCHID_SOURCE_ARCHIVES']) / archive).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),
                                 recipe(package, 'echo "${sha256sums[0]}"').strip())
                with tarfile.open(Path(os.environ['TOUCHID_SOURCE_ARCHIVES']) / archive) as upstream:
                    root = source / upstream.getmembers()[0].name.split('/')[0]
                    upstream.extractall(source, filter='data')
                subprocess.run(['bash', '-euc', 'source "$1"; srcdir=$2; cd "$srcdir"; prepare',
                                'prepare', str(source / 'PKGBUILD'), str(source)],
                               check=True, capture_output=True, text=True)
                roots.append(root)
            daemon, library = roots
            self.assertIn('polkit-password-switch', (daemon / 'pam/pam_fprintd.c').read_text())
            self.assertIn('request_password_switch', (daemon / 'pam/pam_fprintd.c').read_text())
            subprocess.run(['python3', str(FPRINTD / 'test_enroll_capacity.py'),
                            str(daemon / 'src/device.c'), '--aurora',
                            str(library / 'libfprint/drivers/aurora/aurora.c'), '--enroll-utils',
                            str(daemon / 'utils/enroll.c')], check=True)

    def test_capacity_patch_follows_existing_password_switch_patch(self):
        patches = prepared_patches(FPRINTD)
        self.assertEqual(patches[-2:], [
            '0005-opt-in-polkit-fingerprint-cancellation.patch',
            '0006-aurora-report-data-full-without-garbage-collection.patch',
        ])
        self.assertEqual(len({name[:4] for name in patches}), len(patches))
        self.assertGreaterEqual(int(recipe(FPRINTD, 'echo "$pkgrel"')), 6)
        self.assertIn('python-dbus', recipe(FPRINTD, 'echo "${checkdepends[@]}"').split())
        self.assertIn('python-gobject', recipe(FPRINTD, 'echo "${checkdepends[@]}"').split())

    def test_check_runs_both_password_switch_and_capacity_suites(self):
        # Exercise check()'s wiring without starting PAM or D-Bus. The actual
        # compiled callback tests run separately; these stubs only log commands.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            version = recipe(FPRINTD, 'echo "$pkgver"').strip()
            daemon = source / f'fprintd-v{version}'
            (daemon / 'src').mkdir(parents=True)
            (daemon / 'pam').mkdir()
            (daemon / 'utils').mkdir()
            (daemon / 'src/device.c').write_text(
                'verify-lockout verify-password-required-after-boot fp_device_get_password_required\n')
            (daemon / 'pam/pam_fprintd.c').write_text(
                'verify-lockout Your password is required to enable Touch ID.\n')
            for name in ('test_account_gate.py', 'test_password_switch.py',
                         'mock-fprintd.py', 'pam-test.c', 'test_enroll_capacity.py'):
                shutil.copyfile(FPRINTD / name, source / name)
            trace = source / 'commands'
            subprocess.run(['bash', '-euc', '''
                source "$1"
                srcdir=$2
                trace=$3
                python() { test -f "$1"; printf 'python %s\n' "$*" >> "$trace"; }
                cc() { printf 'cc %s\n' "$*" >> "$trace"; }
                check
            ''', 'check-wiring', str(FPRINTD / 'PKGBUILD'), str(source), str(trace)], check=True)
            tests = source / 'password-switch-tests'
            self.assertEqual(trace.read_text().splitlines(), [
                f'python {source}/test_account_gate.py {daemon}/src/device.c',
                f'cc -DMOCK_PASSWORD -fPIC -shared -o {tests}/pam_mock_password.so {source}/pam-test.c -lpam',
                f'cc -o {tests}/pam-test {source}/pam-test.c -lpam',
                f'python {tests}/test_password_switch.py',
                f'python {source}/test_enroll_capacity.py {daemon}/src/device.c --enroll-utils {daemon}/utils/enroll.c',
            ])
            self.assertEqual((tests / 'pam_fprintd-switch.so').readlink(),
                             source / 'build/pam/pam_fprintd.so')
            for name in ('test_password_switch.py', 'mock-fprintd.py'):
                self.assertEqual((tests / name).read_bytes(), (FPRINTD / name).read_bytes())

    def test_enospc_reports_full_without_collecting_any_sep_print(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            # Only these unchanged upstream functions are needed. Apply the
            # package's patch, not a reimplementation of the fixed callback.
            shutil.copytree(ROOT / 'tests/fixtures/fprintd-1.94.5', source, dirs_exist_ok=True)
            subprocess.run(['git', 'apply', str(FPRINTD / '0006-aurora-report-data-full-without-garbage-collection.patch')],
                           cwd=source, check=True)
            # The first patch creates the whole driver. The include filter
            # avoids needing unrelated libfprint files while applying the
            # driver's patch stack in prepare()'s order.
            patches = prepared_patches(LIBFPRINT)
            self.assertEqual(patches[0], 'libfprint-1.94.100-apple-sep.patch')
            self.assertEqual(patches[-1], '0012-aurora-report-fingerprint-storage-full.patch')
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
                         '0006-aurora-report-data-full-without-garbage-collection.patch')
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
