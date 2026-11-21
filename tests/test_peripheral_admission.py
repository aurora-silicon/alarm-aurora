import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages/aurora-firmware'
MT7932_FIRMWARE = (
    'mediatek/mt7932/IZUBA_WIFI_MT7932_patch_mcu_1_2_hdr.bin', 'mediatek/mt7932/IZUBA_W7932_2.bin',
    'mediatek/mt7932/ppr.bin', 'mediatek/mt7932/oca2.bin', 'mediatek/mt7932/wcal.bin',
    'mediatek/mt7932/config-original.bin', 'mediatek/MT7932B0_OS_TypeB_0.1.44.0_241001003711.bin',
    'mediatek/MT7932B1_OS_TypeB_0.1.133.0_260128190103.bin',
    'mediatek/MT7932_PTB_IzubaA_0.1.0.0_20251021141303.ptx', 'mediatek/j700-mt7932-btcal.bin',
    'mediatek/j700-mt7932-bdaddr.bin', 'mediatek/mt7932/policy/world-XZ.bin',
)


NEO = 'apple,j700\0apple,t8140\0'
M2 = 'apple,j413\0apple,t8112\0'


def device_tree(root, compatible, radio='pci14e4,4433', als_calibration=None, trackpad=True):
    """A device tree in the shape of the live one: the parts the admission reads."""
    dt = root / 'dt'
    dt.mkdir(parents=True, exist_ok=True)

    def node(path, compatible, **properties):
        directory = dt / path
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'compatible').write_bytes(compatible.encode())
        for name, value in properties.items():
            (directory / name.replace('_', '-')).write_bytes(value.encode())
        return directory

    (dt / 'compatible').write_bytes(compatible.encode())
    soc = compatible.split('\0')[1].removeprefix('apple,')
    node('soc', 'simple-bus\0')
    wifi = '/soc/pcie@1cb0000000/pci@0,0/wifi@0,0'
    node(wifi.lstrip('/'), radio + '\0')
    (dt / 'aliases').mkdir(exist_ok=True)
    (dt / 'aliases/wifi0').write_bytes(wifi.encode() + b'\0')
    node('soc/aop@310c00000', f'apple,{soc}-aop\0')
    als = {} if als_calibration is None else {'firmware_name': als_calibration + '\0'}
    node('soc/aop@310c00000/als', f'apple,{soc}-aop-als\0apple,aop-als\0', **als)
    if trackpad:
        hid = node('soc/fifo@314b14000/input@8000', 'apple,dockchannel-hid\0')
        (hid / 'multi-touch').mkdir()
    return dt


class PeripheralAdmissionTests(unittest.TestCase):
    def admit(self, root, compatible, bluetooth=False, **tree):
        dt = root / 'dt'
        if not dt.exists():
            device_tree(root, compatible, **tree)
        modprobe = root / 'modprobe'
        modprobe.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$AURORA_TEST_CALLS"\n')
        modprobe.chmod(0o755)
        calls = root / 'module-calls'
        calls.unlink(missing_ok=True)
        env = dict(
            os.environ,
            AURORA_DT_ROOT=str(dt),
            AURORA_FIRMWARE_ROOT=str(root / 'firmware'),
            AURORA_MODPROBE=str(modprobe),
            AURORA_TEST_CALLS=str(calls),
            AURORA_ADMIT_BLUETOOTH='1' if bluetooth else '0',
        )
        script = PACKAGE / 'aurora-peripheral-firmware.sh'
        result = subprocess.run(['sh', str(script)], check=True, env=env, capture_output=True)
        return calls.read_text().splitlines(), result.stderr

    @staticmethod
    def firmware(root, *names):
        for name in names:
            path = root / 'firmware' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')

    def neo(self, root):
        device_tree(root, NEO, radio='pci14c3,7932', als_calibration='apple/j700-aop-als-cal.bin')

    def test_neo_keyboard_probe_follows_firmware_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.neo(root)
            self.firmware(root, 'apple/tpmtfw-j700.bin')
            calls, stderr = self.admit(root, NEO)
            self.assertEqual(calls, ['dockchannel-hid'])
            self.assertNotIn(b'trackpad firmware missing', stderr)
            self.assertIn(b'ALS calibration apple/j700-aop-als-cal.bin missing', stderr)

            (root / 'firmware/apple/tpmtfw-j700.bin').unlink()
            calls, stderr = self.admit(root, NEO)
            self.assertIn(b'trackpad firmware missing', stderr)
            self.assertEqual(calls, ['dockchannel-hid'])

    def test_neo_admits_aop_and_radio_once_their_firmware_is_in_place(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.neo(root)
            self.firmware(root, 'apple/tpmtfw-j700.bin', 'apple/j700-aop-als-cal.bin', *MT7932_FIRMWARE)
            calls, stderr = self.admit(root, NEO)
            self.assertEqual(calls, ['dockchannel-hid', 'aop', 'mt7932-fullmac'], stderr)
            calls, stderr = self.admit(root, NEO, bluetooth=True)
            self.assertEqual(calls, ['dockchannel-hid', 'aop', 'mt7932-fullmac', 'mt7932_bt_pcie'], stderr)

            (root / 'firmware' / MT7932_FIRMWARE[0]).unlink()
            calls, stderr = self.admit(root, NEO)
            self.assertEqual(calls, ['dockchannel-hid', 'aop'])
            self.assertIn(b'required firmware is missing: ' + MT7932_FIRMWARE[0].encode(), stderr)

    def test_selection_follows_the_device_tree_not_the_board(self):
        # The same board name with a Broadcom radio and an ALS that names no
        # calibration file: aop loads and the MT7932 drivers stay out.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls, stderr = self.admit(root, NEO)
            self.assertEqual(calls, ['dockchannel-hid', 'aop'], stderr)
        # An MT7932 behind wifi0 on another board is admitted as on the Neo.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.firmware(root, 'apple/tpmtfw-j413.bin', *MT7932_FIRMWARE)
            calls, stderr = self.admit(root, M2, radio='pci14c3,7932')
            self.assertEqual(calls, ['dockchannel-hid', 'aop', 'mt7932-fullmac'], stderr)

    def test_other_macs_keep_their_keyboard_driver(self):
        # M2 and later MacBooks use the same driver; desktops only load it.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.firmware(root, 'apple/tpmtfw-j413.bin')
            calls, stderr = self.admit(root, M2)
            self.assertEqual(calls, ['dockchannel-hid', 'aop'])
            self.assertNotIn(b'trackpad firmware missing', stderr)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls, stderr = self.admit(root, M2)
            self.assertEqual(calls, ['dockchannel-hid', 'aop'])
            self.assertIn(b'trackpad firmware missing', stderr)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls, stderr = self.admit(root, 'apple,j274\0apple,t8103\0', trackpad=False)
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
        compatible = 'apple,j575c\0apple,t6041\0'
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
                    calls, stderr = self.admit(root, compatible, trackpad=False)
                finally:
                    del os.environ['AURORA_PCI_ROOT']
                self.assertEqual(calls, ['dockchannel-hid', 'aop'])
                self.assertEqual(bind.read_text(), expected)
                self.assertEqual(b'probed with vendor firmware' in stderr, bool(expected))

    def test_keyboard_driver_autoload_waits_for_admission(self):
        blacklist = (PACKAGE / 'aurora-firmware-order.conf').read_text().splitlines()
        self.assertIn('blacklist dockchannel-hid', blacklist)
        self.assertIn('  add_module dockchannel-hid', (PACKAGE / 'aurora-vendor.install').read_text().splitlines())

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
