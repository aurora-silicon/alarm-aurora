"""Guard source lockstep and exercise lifecycle behavior without a device."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GL = ROOT / 'packages/aurora-flatpak-gl'


class ParityTests(unittest.TestCase):
    def test_mesa_consumers_pin_the_host_version_commit_and_archive(self):
        sources = json.loads((ROOT / 'sources.json').read_text())
        self.assertEqual(sources['mesa-aurora'], sources['mesa-aurora-fex-guest'])
        recipes = [(ROOT / 'packages' / name / 'PKGBUILD').read_text()
                   for name in ('mesa-aurora', 'mesa-aurora-fex-guest', 'aurora-flatpak-gl')]
        for field in ('epoch', 'pkgver', 'pkgrel', '_commit'):
            values = [re.search(rf'^{field}=(.*)$', text, re.M)[1] for text in recipes]
            self.assertEqual(len(set(values)), 1, (field, values))
        for text in recipes[1:]:
            self.assertIn('_sha256=' + sources['mesa-aurora']['sha256'], text)

    def test_local_source_checksums_are_current(self):
        # Parse through bash so source array ordering and variable expansion match makepkg.
        names = ('alsa-utils-aurora', 'aurora-audio', 'aurora-system-fixes',
                 'aurora-flatpak-gl', 'mesa-aurora-fex-guest', 'linux-aurora')
        for name in names:
            directory = ROOT / 'packages' / name
            result = subprocess.check_output(['bash', '-c',
                'source "$1"; for i in "${!source[@]}"; do printf "%s %s\\n" "${source[$i]}" "${sha256sums[$i]}"; done',
                'sources', str(directory / 'PKGBUILD')], text=True)
            for line in result.splitlines():
                source, digest = line.split()
                if '://' not in source:
                    with self.subTest(package=name, source=source):
                        self.assertEqual(hashlib.sha256((directory / source).read_bytes()).hexdigest(), digest)

    def test_flatpak_rejects_missing_stale_and_mislabelled_branches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / 'repo'
            (repo / 'objects').mkdir(parents=True)
            commit = 'a' * 40
            ostree = root / 'ostree'
            ostree.write_text('#!/bin/sh\nprintf "Aurora Mesa %s for %s\\n" "$TEST_COMMIT" "${3##*/}"\n')
            ostree.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'TEST_COMMIT': commit}
            def check():
                return subprocess.run(['bash', str(GL / 'validate-repo.sh'), str(repo), commit],
                                      env=env, capture_output=True).returncode
            self.assertNotEqual(check(), 0)
            for branch in ('25.08', '26.08'):
                (repo / f'aurora-mesa-commit.{branch}').write_text(commit + '\n')
            self.assertEqual(check(), 0)
            (repo / 'aurora-mesa-commit.26.08').write_text('b' * 40 + '\n')
            self.assertNotEqual(check(), 0)
            (repo / 'aurora-mesa-commit.26.08').write_text(commit + '\n')
            env['TEST_COMMIT'] = 'b' * 40
            self.assertNotEqual(check(), 0)

    def test_flatpak_install_upgrade_remove_preserves_admin_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, overrides, log = root / 'repo', root / 'global', root / 'calls'
            (repo / 'objects').mkdir(parents=True)
            refs = repo / 'refs/heads/runtime/org.freedesktop.Platform.GL.aurora/aarch64'
            refs.mkdir(parents=True)
            for branch in ('25.08', '26.08'):
                (refs / branch).touch()
            overrides.write_text('[Environment]\nVK_DRIVER_FILES=/admin/custom.json\nOTHER=keep\n')
            helper = root / 'helper'
            helper.write_text((GL / 'aurora-flatpak-gl').read_text()
                .replace('repo=/usr/share/aurora-flatpak-gl/repo', f'repo={repo}')
                .replace('overrides=/var/lib/flatpak/overrides/global', f'overrides={overrides}'))
            flatpak = root / 'flatpak'
            flatpak.write_text('''#!/bin/bash
printf '%s\n' "$*" >> "$TEST_LOG"
case $1 in
  remotes) echo aurora-gl ;;
  list) printf '%s\n' org.freedesktop.Platform.GL.aurora/aarch64/25.08 org.freedesktop.Platform.GL.aurora/aarch64/26.08 ;;
  override) printf '%s\n' "${3#--env=}" >> "$TEST_OVERRIDES" ;;
esac
''')
            flatpak.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                   'TEST_LOG': str(log), 'TEST_OVERRIDES': str(overrides)}
            for action in ('enable', 'enable', 'disable'):
                subprocess.run(['bash', str(helper), action], env=env, check=True)
            calls = log.read_text()
            for branch in ('25.08', '26.08'):
                self.assertIn('install --system --noninteractive -y --or-update aurora-gl runtime/'
                              'org.freedesktop.Platform.GL.aurora/aarch64/' + branch, calls)
            self.assertNotIn('--env=VK_DRIVER_FILES=', calls)
            self.assertEqual(overrides.read_text(),
                             '[Environment]\nVK_DRIVER_FILES=/admin/custom.json\nOTHER=keep\n')

    def test_ordered_kernel_requirements_still_reject_dropped_shared_hardware(self):
        spec = importlib.util.spec_from_file_location('config', ROOT / 'packages/linux-aurora/validate-config.py')
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared, policy, resolved = (root / name for name in ('shared', 'policy', 'resolved'))
            shared.write_text('CONFIG_SPI_HID_APPLE_OF=m\nCONFIG_APPLE_SEP=m\n')
            policy.write_text('CONFIG_SPI_HID_APPLE_OF=y\n')
            resolved.write_text('CONFIG_SPI_HID_APPLE_OF=y\nCONFIG_APPLE_SEP=m\n')
            validator.validate(shared, resolved, policy)
            resolved.write_text('CONFIG_SPI_HID_APPLE_OF=y\n# CONFIG_APPLE_SEP is not set\n')
            with self.assertRaisesRegex(ValueError, 'CONFIG_APPLE_SEP'):
                validator.validate(shared, resolved, policy)


if __name__ == '__main__':
    unittest.main()
