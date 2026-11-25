import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages/aurora-firmware'


class PeripheralAdmissionTests(unittest.TestCase):
    def admit(self, root, compatible):
        (root / 'compatible').write_bytes(compatible)
        modprobe = root / 'modprobe'
        modprobe.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$AURORA_TEST_CALLS"\n')
        modprobe.chmod(0o755)
        calls = root / 'module-calls'
        calls.unlink(missing_ok=True)
        env = dict(
            os.environ,
            AURORA_DT_COMPATIBLE=str(root / 'compatible'),
            AURORA_FIRMWARE_ROOT=str(root / 'firmware'),
            AURORA_MODPROBE=str(modprobe),
            AURORA_TEST_CALLS=str(calls),
        )
        script = PACKAGE / 'aurora-peripheral-firmware.sh'
        result = subprocess.run(['sh', str(script)], check=True, env=env, capture_output=True)
        return calls.read_text().splitlines(), result.stderr

    def test_neo_keyboard_probe_follows_firmware_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trackpad = root / 'firmware/apple/tpmtfw-j700.bin'
            trackpad.parent.mkdir(parents=True)
            trackpad.write_bytes(b'fixture')
            calls, stderr = self.admit(root, b'apple,j700\0apple,t8140\0')
            self.assertEqual(calls, ['dockchannel-hid'])
            self.assertNotIn(b'trackpad firmware missing', stderr)

            trackpad.unlink()
            calls, stderr = self.admit(root, b'apple,j700\0apple,t8140\0')
            self.assertIn(b'trackpad firmware missing', stderr)
            self.assertEqual(calls, ['dockchannel-hid'])

    def test_other_macs_keep_their_keyboard_driver(self):
        # M2 and later MacBooks use the same driver; desktops only load it.
        with tempfile.TemporaryDirectory() as temporary:
            for compatible in [b'apple,j413\0apple,t8112\0', b'apple,j274\0apple,t8103\0']:
                calls, stderr = self.admit(Path(temporary), compatible)
                self.assertEqual(calls, ['dockchannel-hid', 'aop'])
                self.assertNotIn(b'trackpad firmware missing', stderr)

    def asmedia_bus(self, root, bound):
        pci = root / 'pci'
        device = pci / 'devices/0000:04:00.0'
        device.mkdir(parents=True)
        (device / 'vendor').write_text('0x1b21\n')
        (device / 'device').write_text('0x2142\n')
        if bound:
            (device / 'driver').mkdir()
        other = pci / 'devices/0000:03:00.0'
        other.mkdir()
        (other / 'vendor').write_text('0x1d6a\n')
        (other / 'device').write_text('0x04c0\n')
        (pci / 'drivers/xhci_hcd').mkdir(parents=True)
        (pci / 'drivers/xhci_hcd/bind').write_text('')
        return pci / 'drivers/xhci_hcd/bind'

    def test_unbound_asmedia_xhci_is_probed_once_firmware_is_reachable(self):
        compatible = b'apple,j575c\0apple,t6041\0'
        for bound, firmware, expected in [(False, True, '0000:04:00.0\n'), (True, True, ''),
                                          (False, False, '')]:
            with tempfile.TemporaryDirectory() as temporary, self.subTest(bound=bound, firmware=firmware):
                root = Path(temporary)
                bind = self.asmedia_bus(root, bound)
                if firmware:
                    blob = root / 'firmware/asmedia/asm2214a-apple.bin'
                    blob.parent.mkdir(parents=True)
                    blob.write_bytes(b'fixture')
                os.environ['AURORA_PCI_ROOT'] = str(root / 'pci')
                try:
                    calls, stderr = self.admit(root, compatible)
                finally:
                    del os.environ['AURORA_PCI_ROOT']
                self.assertEqual(calls, ['dockchannel-hid', 'aop'])
                self.assertEqual(bind.read_text(), expected)
                self.assertEqual(b'probed with vendor firmware' in stderr, bool(expected))

    def test_keyboard_driver_autoload_waits_for_admission(self):
        blacklist = (PACKAGE / 'aurora-firmware-order.conf').read_text().splitlines()
        self.assertIn('blacklist dockchannel-hid', blacklist)
        self.assertIn('  add_module dockchannel-hid', (PACKAGE / 'aurora-vendor.install').read_text().splitlines())

    def test_handoff_waits_for_the_esp_not_for_udev_to_settle(self):
        unit = (PACKAGE / 'aurora-vendor-firmware.service').read_text()
        self.assertNotIn('systemd-udev-settle', unit)
        for line in ('Wants=systemd-udevd.service systemd-udev-trigger.service',
                     'After=systemd-udevd.service systemd-udev-trigger.service'):
            self.assertIn(line, unit.splitlines())
        script = (PACKAGE / 'load-vendor-firmware').read_text()
        self.assertIn('udevadm wait --timeout=60 "$device"', script)
        self.assertNotIn('udevadm settle', script)
        # The keyboard is admitted before the disk unlock prompt, and the ESP
        # wait (60 s) ends inside systemd's default start timeout (90 s), so a
        # missing ESP cannot get the unit killed before admission.
        self.assertIn('cryptsetup-pre.target', unit.split('Before=', 1)[1].splitlines()[0].split())
        self.assertNotIn('TimeoutStartSec', unit)

    def esp_wait(self, root, appears_after, mode='initrd'):
        """Run the handoff while the ESP's device node shows up late or never.

        The fake udevadm honours --timeout in 50 ms ticks, so the 60 s bound
        is 3 s here; findmnt reports the ESP only once its node exists.
        """
        node = root / 'esp-node'
        esp = root / 'esp'
        (esp / 'vendorfw').mkdir(parents=True)
        (esp / 'vendorfw/firmware.cpio').write_bytes(b'fixture')
        tools = root / 'bin'
        tools.mkdir()
        for name, body in (
                ('udevadm', '[ "$1" = wait ] || exit 0\n'
                            'echo "udevadm $*" >> "$AURORA_TEST_CALLS"\n'
                            'ticks=${2#--timeout=}; ticks=$((ticks))\n'
                            'while [ ! -e "$AURORA_TEST_ESP_NODE" ]; do\n'
                            '  [ "$ticks" -gt 0 ] || exit 1\n'
                            '  sleep 0.05; ticks=$((ticks - 1))\n'
                            'done'),
                ('findmnt', f'[ -e "$AURORA_TEST_ESP_NODE" ] && echo "{esp}"'),
                ('mount', 'echo "mount $*" >> "$AURORA_TEST_CALLS"; exit 32'),
                ('cpio', 'echo cpio >> "$AURORA_TEST_CALLS"; mkdir -p vendorfw; '
                         'cat > vendorfw/.vendorfw.manifest'),
                ('modprobe', 'echo "modprobe $1" >> "$AURORA_TEST_CALLS"'),
                # The real admission script, installed executable by the package.
                ('admission', f'exec sh "{PACKAGE / "aurora-peripheral-firmware.sh"}"')):
            (tools / name).write_text(f'#!/bin/sh\n{body}\n')
            (tools / name).chmod(0o755)
        (root / 'property').write_bytes(b'5A1E0001-0000-4000-8000-00000000E5B0\0')
        (root / 'compatible').write_bytes(b'apple,j413\0apple,t8112\0')
        env = dict(
            os.environ,
            PATH=f'{tools}:{os.environ["PATH"]}',
            AURORA_ESP_PROPERTY=str(root / 'property'),
            AURORA_PERIPHERAL_ADMISSION=str(tools / 'admission'),
            AURORA_DT_COMPATIBLE=str(root / 'compatible'),
            AURORA_PCI_ROOT=str(root / 'pci'),
            AURORA_FIRMWARE_DESTINATION=str(root / 'destination'),
            AURORA_FIRMWARE_SEARCH_PATH=str(root / 'search-path'),
            AURORA_TEST_ESP_NODE=str(node),
            AURORA_TEST_CALLS=str(root / 'calls'),
        )
        start = time.monotonic()
        handoff = subprocess.Popen(['bash', str(PACKAGE / 'load-vendor-firmware'), mode], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if appears_after is not None:
            time.sleep(appears_after)
            node.touch()
        stdout, stderr = handoff.communicate(timeout=30)
        elapsed = time.monotonic() - start
        return handoff.returncode, stderr, (root / 'calls').read_text().splitlines(), elapsed

    def test_late_esp_is_waited_for_and_its_firmware_reaches_the_keyboard_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status, stderr, calls, elapsed = self.esp_wait(root, appears_after=0.5)
            self.assertEqual(status, 0, stderr)
            # The firmware is unpacked before the keyboard driver probes.
            self.assertEqual(calls, [
                'udevadm wait --timeout=60 /dev/disk/by-partuuid/5a1e0001-0000-4000-8000-00000000e5b0',
                'cpio', 'modprobe dockchannel-hid', 'modprobe aop'])
            self.assertEqual((root / 'search-path').read_text(), str(root / 'destination/vendorfw'))
            # The wait ends when the node appears, not at its bound.
            self.assertLess(elapsed, 2.5)

    def test_missing_esp_is_bounded_and_still_admits_the_keyboard(self):
        for mode, expected_status, message in (
                ('initrd', 0, b'handoff failed; the real root will retry it'),
                ('runtime', 1, b'handoff failed; admitting peripherals without it')):
            with tempfile.TemporaryDirectory() as temporary, self.subTest(mode=mode):
                root = Path(temporary)
                status, stderr, calls, elapsed = self.esp_wait(root, appears_after=None, mode=mode)
                self.assertEqual(status, expected_status, stderr)
                self.assertIn(message, stderr)
                self.assertEqual(calls, [
                    'udevadm wait --timeout=60 /dev/disk/by-partuuid/5a1e0001-0000-4000-8000-00000000e5b0',
                    'modprobe dockchannel-hid', 'modprobe aop'])
                self.assertFalse((root / 'search-path').exists())
                # 60 ticks of 50 ms: the wait gives up at its bound.
                self.assertGreaterEqual(elapsed, 2.5)
                self.assertLess(elapsed, 10)

    def test_failed_firmware_handoff_still_admits_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            admission = root / 'admission'
            admission.write_text('#!/bin/sh\necho "$AURORA_ADMIT_BLUETOOTH" >> "$AURORA_TEST_CALLS"\n')
            admission.chmod(0o755)
            calls = root / 'admissions'
            env = dict(
                os.environ,
                AURORA_ESP_PROPERTY=str(root / 'missing-property'),
                AURORA_PERIPHERAL_ADMISSION=str(admission),
                AURORA_TEST_CALLS=str(calls),
            )
            script = PACKAGE / 'load-vendor-firmware'
            subprocess.run(['bash', str(script)], check=True, env=env, capture_output=True)
            self.assertEqual(calls.read_text().splitlines(), ['0'])

            calls.unlink()
            (root / 'property').write_bytes(b'not-a-partition-uuid\0')
            env['AURORA_ESP_PROPERTY'] = str(root / 'property')
            result = subprocess.run(['bash', str(script), 'runtime'], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'handoff failed; admitting peripherals without it', result.stderr)
            self.assertEqual(calls.read_text().splitlines(), ['1'])

            # The initrd leaves the verdict to the real root's retry: a failed
            # initrd unit would stay listed as failed after switch-root.
            calls.unlink()
            result = subprocess.run(['bash', str(script)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'handoff failed; the real root will retry it', result.stderr)
            self.assertEqual(calls.read_text().splitlines(), ['0'])

    def runtime_handoff(self, root, esp):
        """The real-root retry, with the ESP already mounted at esp."""
        tools = root / 'bin'
        tools.mkdir()
        for name, body in (('udevadm', 'exit 0'), ('findmnt', f'echo "{esp}"'),
                           ('mount', 'echo "mount $*" >> "$AURORA_TEST_CALLS"; exit 32'),
                           ('cpio', 'echo "cpio $*" >> "$AURORA_TEST_CALLS"; mkdir -p vendorfw; '
                                    'cat > vendorfw/.vendorfw.manifest')):
            (tools / name).write_text(f'#!/bin/sh\n{body}\n')
            (tools / name).chmod(0o755)
        admission = root / 'admission'
        admission.write_text('#!/bin/sh\necho "admit $AURORA_ADMIT_BLUETOOTH" >> "$AURORA_TEST_CALLS"\n')
        admission.chmod(0o755)
        (root / 'property').write_bytes(b'5A1E0001-0000-4000-8000-00000000E5B0\0')
        env = dict(
            os.environ,
            PATH=f'{tools}:{os.environ["PATH"]}',
            AURORA_ESP_PROPERTY=str(root / 'property'),
            AURORA_PERIPHERAL_ADMISSION=str(admission),
            AURORA_FIRMWARE_DESTINATION=str(root / 'destination'),
            AURORA_FIRMWARE_SEARCH_PATH=str(root / 'search-path'),
            AURORA_TEST_CALLS=str(root / 'calls'),
        )
        result = subprocess.run(['bash', str(PACKAGE / 'load-vendor-firmware'), 'runtime'], env=env,
                                capture_output=True)
        return result, (root / 'calls').read_text().splitlines()

    def test_runtime_retry_reads_the_mounted_esp(self):
        # The real root has the ESP mounted read-write; mounting it again
        # read-only is refused, so the retry must read it in place.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'esp/vendorfw').mkdir(parents=True)
            (root / 'esp/vendorfw/firmware.cpio').write_bytes(b'fixture')
            result, calls = self.runtime_handoff(root, root / 'esp')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, ['cpio --quiet --extract --unconditional --no-absolute-filenames', 'admit 1'])
            self.assertEqual((root / 'destination/vendorfw/.vendorfw.manifest').read_bytes(), b'fixture')
            self.assertEqual((root / 'search-path').read_text(), str(root / 'destination/vendorfw'))

    def test_esp_without_vendor_firmware_admits_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'esp').mkdir()
            result, calls = self.runtime_handoff(root, root / 'esp')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'the ESP has no vendor firmware; admitting peripherals without it', result.stderr)
            self.assertNotIn(b'handoff failed', result.stderr)
            self.assertEqual(calls, ['admit 1'])
            self.assertFalse((root / 'search-path').exists())


if __name__ == '__main__':
    unittest.main()
