import os
from pathlib import Path
import subprocess
import tempfile
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


if __name__ == '__main__':
    unittest.main()
