"""Offline logind file selection; policy checks remain in test_check_basics."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_check_basics as fixtures

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check-basics.py'
spec = importlib.util.spec_from_file_location('check_basics_logind', SCRIPT)
basics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(basics)

# Highest priority first, as documented by systemd 262 logind.conf(5).
DIRECTORIES = ('/etc/systemd', '/run/systemd', '/usr/local/lib/systemd', '/usr/lib/systemd')


def config(**values):
    return '[Login]\n' + ''.join(f'{key}={value}\n' for key, value in values.items())


class LogindConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = basics.Root(self.base)

    def write(self, name, text):
        fixtures.write(self.base / name.lstrip('/'), text)

    def link(self, name, target):
        fixtures.link(self.base / name.lstrip('/'), target)

    def test_local_main_replaces_whole_vendor_file(self):
        local = config(HandlePowerKey='suspend')
        self.write('/etc/systemd/logind.conf', local)
        self.write('/usr/lib/systemd/logind.conf',
                   config(HandlePowerKey='poweroff', HandlePowerKeyLongPress='ignore'))
        texts = basics.logind_texts(self.root)
        self.assertEqual(texts, [local])
        self.assertIsNone(basics.config_value(texts, '[Login]', 'HandlePowerKeyLongPress'))

    def test_empty_main_still_shadows_vendor(self):
        self.write('/etc/systemd/logind.conf', '')
        self.write('/usr/lib/systemd/logind.conf', config(HandlePowerKey='poweroff'))
        self.assertEqual(basics.logind_texts(self.root), [''])

    def test_main_fallback_order(self):
        for index, directory in enumerate(DIRECTORIES):
            self.write(f'{directory}/logind.conf', config(IdleActionSec=index))
        for index, directory in enumerate(DIRECTORIES):
            with self.subTest(directory=directory):
                self.assertEqual(basics.logind_texts(self.root), [config(IdleActionSec=index)])
                (self.base / directory.lstrip('/') / 'logind.conf').unlink()
        self.assertEqual(basics.logind_texts(self.root), [])

    def test_dropins_sort_globally_and_override_main(self):
        main = config(HandlePowerKey='poweroff')
        early = config(HandlePowerKey='ignore')
        late = config(HandlePowerKey='suspend')
        self.write('/etc/systemd/logind.conf', main)
        self.write('/etc/systemd/logind.conf.d/10-local.conf', early)
        self.write('/usr/lib/systemd/logind.conf.d/90-vendor.conf', late)
        self.assertEqual(basics.logind_texts(self.root), [main, early, late])
        self.assertEqual(basics.config_value(basics.logind_texts(self.root),
                                            '[Login]', 'HandlePowerKey'), 'suspend')

    def test_same_name_dropin_priority_in_all_directories(self):
        for index, directory in enumerate(DIRECTORIES):
            self.write(f'{directory}/logind.conf.d/50-same.conf', config(IdleActionSec=index))
        for index, directory in enumerate(DIRECTORIES):
            with self.subTest(directory=directory):
                self.assertEqual(basics.logind_texts(self.root), [config(IdleActionSec=index)])
                (self.base / directory.lstrip('/') / 'logind.conf.d/50-same.conf').unlink()

    def test_empty_dropin_replaces_whole_lower_priority_file(self):
        self.write('/usr/lib/systemd/logind.conf.d/50-same.conf', config(HandlePowerKey='poweroff'))
        self.write('/run/systemd/logind.conf.d/50-same.conf', '')
        self.assertEqual(basics.logind_texts(self.root), [''])

    def test_dev_null_masks_main_and_same_name_dropin(self):
        self.write('/usr/lib/systemd/logind.conf', config(HandlePowerKey='poweroff'))
        self.write('/usr/lib/systemd/logind.conf.d/50-masked.conf', config(HandlePowerKey='ignore'))
        self.link('/etc/systemd/logind.conf', '/dev/null')
        self.link('/etc/systemd/logind.conf.d/50-masked.conf', '/dev/null')
        remaining = config(HandlePowerKey='suspend')
        self.write('/run/systemd/logind.conf.d/90-remaining.conf', remaining)
        self.assertEqual(basics.logind_texts(self.root), [remaining])

    def test_absolute_and_relative_file_symlinks_stay_in_image(self):
        main = config(HandlePowerKey='suspend')
        absolute = config(HandlePowerKeyLongPress='poweroff')
        relative = config(IdleAction='ignore')
        self.write('/nix/store/main.conf', main)
        self.write('/nix/store/absolute.conf', absolute)
        self.write('/nix/store/relative.conf', relative)
        self.link('/etc/systemd/logind.conf.d/20-absolute.conf', '/nix/store/absolute.conf')
        self.link('/etc/systemd/logind.conf.d/30-relative.conf', '../../../nix/store/relative.conf')
        for target in ('/nix/store/main.conf', '../../nix/store/main.conf'):
            with self.subTest(main_link=target):
                self.link('/etc/systemd/logind.conf', target)
                self.assertEqual(basics.logind_texts(self.root), [main, absolute, relative])
                (self.base / 'etc/systemd/logind.conf').unlink()

    def test_dropin_directory_symlink_stays_in_image(self):
        expected = config(HandlePowerKey='suspend')
        self.write('/nix/store/dropins/50-power.conf', expected)
        self.write('/usr/lib/systemd/logind.conf.d/50-power.conf', config(HandlePowerKey='poweroff'))
        self.link('/nix/store/mask', '/dev/null')
        for target in ('/nix/store/dropins', '../../nix/store/dropins'):
            with self.subTest(directory_link=target):
                self.link('/etc/systemd/logind.conf.d', target)
                self.assertEqual(basics.logind_texts(self.root), [expected])
                (self.base / 'nix/store/dropins/50-power.conf').unlink()
                self.link('/nix/store/dropins/50-power.conf', '../mask')
                self.assertEqual(basics.logind_texts(self.root), [])
                (self.base / 'nix/store/dropins/50-power.conf').unlink()
                self.write('/nix/store/dropins/50-power.conf', expected)
                (self.base / 'etc/systemd/logind.conf.d').unlink()

    def test_dangling_dropin_shadows_same_name_vendor_file(self):
        self.write('/usr/lib/systemd/logind.conf.d/50-power.conf', config(HandlePowerKey='poweroff'))
        self.link('/etc/systemd/logind.conf.d/50-power.conf', '/missing.conf')
        self.assertEqual(basics.logind_texts(self.root), [])

    def test_dangling_main_falls_back_and_mask_chain_suppresses_dropin(self):
        expected = config(HandlePowerKey='suspend')
        self.link('/etc/systemd/logind.conf', '/missing.conf')
        self.write('/run/systemd/logind.conf', expected)
        self.write('/usr/lib/systemd/logind.conf.d/50-mask.conf', config(HandlePowerKey='ignore'))
        self.link('/etc/systemd/logind.conf.d/50-mask.conf', '../mask')
        self.link('/etc/systemd/mask', '/dev/null')
        self.assertEqual(basics.logind_texts(self.root), [expected])

    def test_nixos_closure_mapping_and_vendor_fallback(self):
        system = '/nix/store/test-system'
        self.root = basics.Root(self.base, system)
        local = config(HandlePowerKey='suspend')
        closure_vendor = config(HandlePowerKey='poweroff')
        fallback = config(HandlePowerKeyLongPress='ignore')
        self.link(f'{system}/etc', '/nix/store/test-etc/etc')
        self.link(f'{system}/sw', '/nix/store/test-sw')
        self.write('/nix/store/test-etc/etc/systemd/logind.conf', local)
        self.write('/nix/store/test-sw/lib/systemd/logind.conf', closure_vendor)
        self.write('/usr/lib/systemd/logind.conf', fallback)
        # The closure's /etc and sw mappings take the places of /etc and /usr.
        self.write('/etc/systemd/logind.conf', config(HandlePowerKey='ignore'))
        self.write('/usr/lib/systemd/logind.conf.d/50-same.conf', fallback)
        self.link('/nix/store/test-sw/lib/systemd/logind.conf.d/50-same.conf', '/nix/store/power.conf')
        self.write('/nix/store/power.conf', closure_vendor)
        self.assertEqual(basics.logind_texts(self.root), [local, closure_vendor])
        self.link('/nix/store/test-etc/etc/systemd/logind.conf.d/50-same.conf', '/dev/null')
        self.assertEqual(basics.logind_texts(self.root), [local])
        (self.base / 'nix/store/test-etc/etc/systemd/logind.conf').unlink()
        self.assertEqual(basics.logind_texts(self.root), [closure_vendor])
        (self.base / 'nix/store/test-sw/lib/systemd/logind.conf').unlink()
        self.assertEqual(basics.logind_texts(self.root), [fallback])

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'requires systemd-analyze for file-selection comparison')
    def test_selection_agrees_with_systemd_cat_config(self):
        # Compare selected content and ordering, not runtime logind semantics.
        for index, directory in enumerate(DIRECTORIES):
            self.write(f'{directory}/logind.conf', config(IdleActionSec=index))
            self.write(f'{directory}/logind.conf.d/50-same.conf', config(InhibitDelayMaxSec=index))
        self.write('/etc/systemd/logind.conf.d/10-early.conf', config(IdleAction='ignore'))
        self.write('/usr/lib/systemd/logind.conf.d/90-late.conf', config(IdleAction='lock'))

        def compare():
            result = subprocess.run(['systemd-analyze', f'--root={self.base}', 'cat-config',
                                     'systemd/logind.conf'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            def content(text):
                return [line for line in text.splitlines() if line and not line.startswith('#')]

            self.assertEqual(content('\n'.join(basics.logind_texts(self.root))), content(result.stdout))

        for directory in DIRECTORIES:
            with self.subTest(main_and_dropin_priority=directory):
                compare()
                (self.base / directory.lstrip('/') / 'logind.conf').unlink()
                (self.base / directory.lstrip('/') / 'logind.conf.d/50-same.conf').unlink()
        self.write('/usr/lib/systemd/logind.conf', config(HandlePowerKey='poweroff'))
        self.write('/etc/systemd/logind.conf', '')
        with self.subTest(empty_main=True):
            compare()
        (self.base / 'etc/systemd/logind.conf').unlink()
        self.link('/etc/systemd/logind.conf', '/dev/null')
        self.link('/etc/systemd/logind.conf.d/90-late.conf', '/dev/null')
        with self.subTest(masks=True):
            compare()
        (self.base / 'etc/systemd/logind.conf').unlink()
        self.write('/nix/store/main.conf', config(HandlePowerKey='suspend'))
        self.write('/nix/store/drop.conf', config(HandlePowerKeyLongPress='poweroff'))
        # v255.4 conf_files_cat() uses host access() for the main file, unlike
        # v262.2's in-root chase. Keep this comparison confined to the image on
        # both versions by using relative file links. Absolute links have direct
        # expected-content coverage above; they are not a portable --root oracle.
        # https://github.com/systemd/systemd-stable/blob/v255.4/src/shared/pretty-print.c#L393-L402
        self.link('/etc/systemd/logind.conf', '../../nix/store/main.conf')
        self.link('/run/systemd/logind.conf.d/60-link.conf', '../../../nix/store/drop.conf')
        with self.subTest(image_symlinks=True):
            compare()

    def test_cli_uses_local_main_instead_of_shadowed_vendor_policy(self):
        fixture = fixtures.CheckBasicsTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        root = fixture.desktop_root('minimal')
        # Exercise main selection independently of the fixture's package drop-ins.
        shutil.rmtree(root / 'etc/systemd/logind.conf.d')
        # Both a false rejection and a false acceptance with the old reader.
        for local_key, vendor_key, expected_exit in (('suspend', 'poweroff', 0),
                                                     ('poweroff', 'suspend', 1)):
            with self.subTest(local=local_key, vendor=vendor_key):
                fixtures.write(root / 'etc/systemd/logind.conf',
                               config(HandlePowerKey=local_key, HandlePowerKeyLongPress='poweroff'))
                fixtures.write(root / 'usr/lib/systemd/logind.conf',
                               config(HandlePowerKey=vendor_key, HandlePowerKeyLongPress='poweroff'))
                result = fixture.check('--profile', 'minimal', '--root', str(root))
                self.assertEqual(result.returncode, expected_exit, result.stdout)
                expected = ('touchid: ok' if expected_exit == 0 else
                            'touchid: FAIL: logind HandlePowerKey=poweroff, not suspend')
                self.assertIn(expected, result.stdout)


if __name__ == '__main__':
    unittest.main()
