"""The shared Stage 2 updater on Arch's layout.

test_bootchain.py is fedora-aurora's suite for the shared bootchain.py and
runs unchanged. These cases cover what bootchain_arch.py changes (flat dtbs
directories, /boot/vmlinuz-<pkgbase>, no /boot/dtb, the pacman refusal) and
repeat the trial transactions on that layout: arm, commit on the trial boot,
keep the live image after a fallback, the guard's reboot, the DT ABI guard and
an aura update on the same kernel after a commit.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'bootchain_arch', Path(os.environ.get('BOOTCHAIN_ARCH_MODULE', PACKAGE / 'bootchain_arch.py')))
arch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arch)
bootchain = arch.bootchain


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class ArchLayout(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {'TARGET': '/esp/m1n1/boot.bin', 'M1N1': '/usr/lib/asahi-boot/m1n1.bin',
                    'U_BOOT': '/usr/lib/asahi-boot/u-boot-nodtb.bin'}
        self.put('/usr/lib/asahi-boot/m1n1.bin', b'AURA')
        self.put('/usr/lib/asahi-boot/u-boot-nodtb.bin', b'U-BOOT')
        self.target = self.put('/esp/m1n1/boot.bin', b'GOOD-STAGE2')
        self.backup = self.put('/esp/m1n1/boot.bin.old', b'OLDER-STAGE2')
        (self.root / 'boot').mkdir()

    def put(self, path, content):
        path = self.root / path.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def dtb(self, board, cells):
        dts = f'''/dts-v1/; / {{ compatible = "apple,{board}", "apple,t8112";
                  dart {{ compatible = "apple,t8110-dart"; #iommu-cells = <{cells}>; }}; }};'''
        return subprocess.check_output(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=dts.encode())

    def kernel(self, release, cells=1, board='j413', generation=1, pkgbase=None):
        """A kernel package as linux-aurora installs it, plus mkinitcpio's /boot copy."""
        self.put(f'/usr/lib/modules/{release}/vmlinuz', release.encode())
        if generation is not None:
            self.put(f'/usr/lib/modules/{release}/dtb-abi', f'{generation}\n'.encode())
        if pkgbase:
            self.put(f'/usr/lib/modules/{release}/pkgbase', f'{pkgbase}\n'.encode())
            self.put(f'/boot/vmlinuz-{pkgbase}', release.encode())
        return self.put(f'/usr/lib/modules/{release}/dtbs/t8112-{board}.dtb', self.dtb(board, cells))

    def apply(self):
        arch.ArchUpdate(self.root, self.env).apply()

    def unchanged(self):
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        self.assertFalse((self.root / 'boot/dtb').exists())

    def test_newest_kernel_trees_are_written_with_a_backup_and_no_boot_dtb(self):
        self.kernel('7.3.0-1-23-ARCH', pkgbase='linux-aurora-fallback')
        blob = self.kernel('7.3.0-1-24-ARCH', 5, pkgbase='linux-aurora').read_bytes()
        self.apply()
        payload = self.target.read_bytes()
        self.assertTrue(payload.startswith(b'AURA' + blob))
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        # GRUB boots with U-Boot's tree, so Arch keeps no /boot/dtb link.
        self.assertFalse((self.root / 'boot/dtb').exists())
        self.assertFalse(list((self.root / 'boot').glob('dtb-*')))
        self.apply()
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.target.read_bytes(), payload)

    def test_retained_older_generation_refuses_and_names_pacman(self):
        self.kernel('7.1.0-1-1-ARCH', generation=0, pkgbase='linux-aurora-old')
        self.kernel('7.2.0-1-1-ARCH', generation=1)
        self.kernel('7.3.0-1-1-ARCH', 5, generation=2, pkgbase='linux-aurora')
        with self.assertRaises(bootchain.Refused) as result:
            self.apply()
        message = str(result.exception)
        self.assertIn('DT ABI generation 2', message)
        self.assertIn('7.1.0-1-1-ARCH (generation 0), 7.2.0-1-1-ARCH (generation 1)', message)
        self.assertIn("`sudo pacman -R $(pacman -Qqo '/usr/lib/modules/7.1.0-1-1-ARCH/vmlinuz' "
                      "'/usr/lib/modules/7.2.0-1-1-ARCH/vmlinuz')`", message)
        self.assertIn('Stage 2 is kept', message)
        self.assertNotIn('dnf', message)
        self.assertNotIn('/boot/dtb', message)
        self.assertNotIn('\n', message)
        self.unchanged()

    def test_removing_the_older_kernel_lets_the_new_trees_through(self):
        self.kernel('7.1.0-1-1-ARCH', generation=0)
        new = self.kernel('7.3.0-1-1-ARCH', 5).read_bytes()
        with self.assertRaisesRegex(bootchain.Refused, 'generation 0'):
            self.apply()
        shutil.rmtree(self.root / 'usr/lib/modules/7.1.0-1-1-ARCH')
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA' + new))

    def test_missing_marker_is_generation_zero(self):
        self.kernel('7.1.0-1-1-ARCH', generation=None)
        self.kernel('7.3.0-1-1-ARCH')
        with self.assertRaisesRegex(bootchain.Refused, r'7.1.0-1-1-ARCH \(generation 0\)'):
            self.apply()
        self.unchanged()

    def test_invalid_marker_refuses(self):
        self.kernel('7.3.0-1-1-ARCH')
        self.put('/usr/lib/modules/7.3.0-1-1-ARCH/dtb-abi', b'one\n')
        with self.assertRaisesRegex(bootchain.Refused, 'invalid DT ABI generation'):
            self.apply()
        self.unchanged()

    def test_kernel_without_dtbs_refuses(self):
        self.kernel('7.3.0-1-1-ARCH')
        self.put('/usr/lib/modules/7.4.0-1-1-ARCH/vmlinuz', b'no trees')
        with self.assertRaisesRegex(bootchain.Refused, '7.4.0-1-1-ARCH has no DTB directory'):
            self.apply()
        self.unchanged()

    def test_fedora_dtb_directory_is_not_arch_layout(self):
        self.put('/usr/lib/modules/7.3.0-1-1-ARCH/vmlinuz', b'kernel')
        self.put('/usr/lib/modules/7.3.0-1-1-ARCH/dtb/apple/t8112-j413.dtb', self.dtb('j413', 1))
        with self.assertRaisesRegex(bootchain.Refused, 'no DTB directory'):
            self.apply()
        self.unchanged()

    def test_boot_image_without_its_package_is_not_ignored(self):
        self.kernel('7.3.0-1-1-ARCH', pkgbase='linux-aurora')
        self.put('/boot/vmlinuz-linux-gone', b'a kernel GRUB still offers')
        with self.assertRaisesRegex(bootchain.Refused, 'linux-gone has no DTB directory'):
            self.apply()
        self.unchanged()

    def test_boot_image_of_an_installed_package_is_that_kernel(self):
        self.kernel('7.3.0-1-1-ARCH', pkgbase='linux-aurora')
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))

    def test_no_kernel_preserves_stage2(self):
        with self.assertRaisesRegex(bootchain.Refused, 'no remaining installed kernels'):
            self.apply()
        self.unchanged()

    def test_unrelated_refusals_pass_through_unchanged(self):
        self.kernel('7.3.0-1-1-ARCH')
        self.put('/proc/device-tree/compatible', b'apple,j700\0')
        with self.assertRaisesRegex(bootchain.Refused, '^selected DTBs have no apple,j700$'):
            self.apply()
        self.unchanged()

    def test_failure_before_live_rename_keeps_live_stage2(self):
        self.kernel('7.3.0-1-1-ARCH')
        original = bootchain.os.replace
        def replace(source, destination):
            if destination == self.target:
                raise OSError('interrupted before commit')
            return original(source, destination)
        with patch.object(bootchain.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(list(self.target.parent.glob('.boot.bin.*')))

    def test_stage2_symlink_is_preserved(self):
        self.kernel('7.3.0-1-1-ARCH')
        self.target.unlink()
        self.target.symlink_to('boot.bin.old')
        with self.assertRaisesRegex(bootchain.Refused, 'target is a symlink'):
            self.apply()
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'), 'requires dtc')
class ArchTrial(unittest.TestCase):
    setUp = ArchLayout.setUp
    put = ArchLayout.put
    dtb = ArchLayout.dtb
    kernel = ArchLayout.kernel
    apply = ArchLayout.apply
    unchanged = ArchLayout.unchanged
    RELEASE = '7.3.0-1-24-ARCH'

    def trial_setup(self):
        self.env.update(ESP_ROOT='/esp', ESP_DEVICE='/dev/test-esp', ESP_FSTYPE='vfat')
        self.put('/proc/device-tree/compatible', b'apple,j413\0apple,t8112\0')
        self.put('/proc/device-tree/chosen/aura,stage1-version', b'1.0.0b8\0')
        self.kernel(self.RELEASE, pkgbase='linux-aurora')
        self.candidate = self.target.with_name('boot.bin.next')
        self.marker = self.root / 'esp/aura-try'
        self.prev = self.target.with_name('boot.bin.prev')
        self.attempts = self.root / 'var/lib/aurora-stage2/attempts'
        self.addCleanup(patch.stopall)
        patch.object(bootchain.Update, 'check_esp').start()
        self.flush = patch.object(bootchain.Update, 'flush_esp').start()

    def trial_boot(self):
        # aura Stage 1 marks the try spent before it loads the candidate.
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        self.put('/proc/device-tree/chosen/aurora,trial', b'm1n1/boot.bin.next\0')

    def commit(self):
        arch.ArchUpdate(self.root, self.env).commit()

    def guard(self):
        arch.ArchUpdate(self.root, self.env).guard()

    def sane(self):
        self.put('/sys/kernel/debug/devices_deferred', b'')
        self.put('/proc/device-tree/soc/dcp/compatible', b'apple,t8112-dcp\0')
        platform = self.root / 'sys/bus/platform/devices/dcp'
        platform.mkdir(parents=True)
        (platform / 'of_node').symlink_to(self.root / 'proc/device-tree/soc/dcp')
        driver = self.root / 'sys/bus/platform/drivers/dcp'
        driver.mkdir(parents=True)
        (platform / 'driver').symlink_to(driver)
        original = bootchain.subprocess.check_output
        def output(command, **kwargs):
            if command[0] == 'findmnt':
                return '/dev/mapper/root[/root]\n'
            if command[0] == 'lsblk':
                return 'dm-0\nnvme0n1p6\nnvme0n1\n'
            return original(command, **kwargs)
        patch.object(bootchain.subprocess, 'check_output', side_effect=output).start()

    def test_arm_keeps_the_live_image(self):
        self.trial_setup()
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertTrue(self.candidate.read_bytes().startswith(b'AURA'))
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.backup.read_bytes(), b'OLDER-STAGE2')
        self.assertFalse(self.prev.exists())
        self.assertTrue((self.attempts / hashlib.sha256(self.candidate.read_bytes()).hexdigest()).exists())
        self.commit()  # Still on the ordinary boot that armed it.
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_trial_boot_commits(self):
        self.trial_setup()
        self.apply()
        payload = self.candidate.read_bytes()
        self.trial_boot()
        self.sane()
        self.commit()
        self.assertEqual(self.target.read_bytes(), payload)
        self.assertEqual(self.prev.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())
        self.apply()  # The pacman hook on the same boot does not rearm.
        self.assertFalse(self.marker.exists())
        with patch.object(bootchain.subprocess, 'run') as command:
            self.guard()
        command.assert_not_called()

    def test_fallback_keeps_the_live_image_and_never_rearms_this_kernel(self):
        self.trial_setup()
        self.apply()
        payload = self.candidate.read_bytes()
        # aura spent the try, the candidate failed, the configured image booted.
        self.marker.write_bytes(b'spent\nm1n1/boot.bin.next\n')
        with patch('builtins.print') as log:
            self.commit()
        self.assertIn('fell back', log.call_args[0][0])
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertEqual(self.candidate.read_bytes(), payload)
        self.apply()
        self.assertTrue(self.marker.read_bytes().startswith(b'spent\n'))
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_aura_update_on_the_same_kernel_trials_after_a_commit(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        self.commit()
        committed = self.target.read_bytes()
        # Same boot, same kernel release: the new aura still gets its trial.
        self.put('/usr/lib/asahi-boot/m1n1.bin', b'AURA-2')
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot.bin.next\n')
        self.assertTrue(self.candidate.read_bytes().startswith(b'AURA-2'))
        self.assertEqual(self.target.read_bytes(), committed)
        with patch.object(bootchain.subprocess, 'run') as command:
            self.guard()
        command.assert_not_called()

    def test_guard_reboots_an_uncommitted_trial(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        with patch.object(bootchain.subprocess, 'run') as command:
            self.guard()
        command.assert_called_once_with(['systemctl', '--no-block', 'reboot'], check=True)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')

    def test_failed_boot_checks_refuse_the_commit(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        self.put('/sys/kernel/debug/devices_deferred', b'dcp\tplatform: waiting for supplier\n')
        with self.assertRaisesRegex(bootchain.Refused, 'DT device still deferred'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertTrue(self.marker.exists())

    def test_abi_refusal_precedes_every_esp_write(self):
        self.trial_setup()
        self.kernel('7.1.0-1-1-ARCH', generation=0)
        with self.assertRaisesRegex(bootchain.Refused, 'pacman -R'):
            self.apply()
        self.unchanged()
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())
        self.assertFalse(self.attempts.exists())

    def test_kernel_installed_after_arming_cannot_bypass_the_abi_guard(self):
        self.trial_setup()
        self.apply()
        self.trial_boot()
        self.sane()
        self.kernel('7.1.0-1-1-ARCH', generation=0)
        with self.assertRaisesRegex(bootchain.Refused, 'retained kernels now require an older'):
            self.commit()
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.prev.exists())

    def test_stage1_without_aura_try_replaces_directly(self):
        self.trial_setup()
        self.put('/proc/device-tree/chosen/aura,stage1-version', b'1.0.0b3\0')
        self.apply()
        self.assertTrue(self.target.read_bytes().startswith(b'AURA'))
        self.assertEqual(self.backup.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.candidate.exists())

    def test_ctxr_trial_and_commit_touch_only_the_ctxr_slot(self):
        self.trial_setup()
        self.put('/usr/share/aura/monitor-free', b'')
        self.put('/proc/device-tree/compatible', b'apple,j700\0apple,t8140\0')
        self.kernel(self.RELEASE, board='j700', pkgbase='linux-aurora')
        ctxr = self.put('/esp/m1n1/boot-ctxr.bin', b'GOOD-CTXR')
        candidate = ctxr.with_name('boot-ctxr.bin.next')
        self.apply()
        self.assertEqual(self.marker.read_bytes(), b'armed\nm1n1/boot-ctxr.bin.next\n')
        self.assertNotIn(self.dtb('j413', 1), candidate.read_bytes())
        payload = candidate.read_bytes()
        self.marker.write_bytes(b'spent\nm1n1/boot-ctxr.bin.next\n')
        self.put('/proc/device-tree/chosen/aurora,trial', b'm1n1/boot-ctxr.bin.next\0')
        self.sane()
        self.commit()
        self.assertEqual(ctxr.read_bytes(), payload)
        self.assertEqual(self.target.read_bytes(), b'GOOD-STAGE2')
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
