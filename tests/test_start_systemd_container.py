"""scripts/start-systemd-container.py: returns on systemd's READY=1, fails when the
container stops first, and passes the notify socket into the container."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'start-systemd-container.py'

# A fake docker. `run` records its arguments and, as the container's systemd
# would, sends the datagrams in $FAKE_SEND to the notify socket it was given.
# `wait` prints $FAKE_EXIT when set (the container stopped), else blocks.
FAKE = r'''#!/usr/bin/env python3
import os, pathlib, socket, sys, time
log = pathlib.Path(os.environ['FAKE_DIR']) / 'calls'
with log.open('a') as stream:
    stream.write(' '.join(sys.argv[1:]) + '\n')
if sys.argv[1] == 'run':
    args = sys.argv[2:]
    env = dict(a.split('=', 1) for a in (args[i + 1] for i, x in enumerate(args) if x == '-e'))
    host, mount = next(args[i + 1] for i, x in enumerate(args) if x == '-v').split(':')
    path = env['NOTIFY_SOCKET'].replace(mount, host, 1)
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        for datagram in filter(None, os.environ.get('FAKE_SEND', '').split('|')):
            sock.sendto(datagram.encode().replace(b'\\n', b'\n'), path)
    print('0123456789ab')
elif sys.argv[1] == 'wait':
    if os.environ.get('FAKE_EXIT'):
        print(os.environ['FAKE_EXIT'])
    else:
        time.sleep(60)
'''


class StartSystemdContainer(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = pathlib.Path(temporary.name)
        self.docker = self.dir / 'docker'
        self.docker.write_text(FAKE)
        self.docker.chmod(0o755)

    def run_script(self, send='', exit_status=''):
        env = dict(os.environ, DOCKER=str(self.docker), FAKE_DIR=str(self.dir), FAKE_SEND=send, FAKE_EXIT=exit_status)
        return subprocess.run([sys.executable, str(SCRIPT), 'box', '--privileged', 'image', '/sbin/init'],
                              env=env, capture_output=True, text=True, timeout=30)

    def calls(self):
        return (self.dir / 'calls').read_text().splitlines()

    def test_returns_once_systemd_is_ready(self):
        result = self.run_script(send='STATUS=Starting\\nX_SYSTEMD_UNIT_ACTIVE=basic.target|STATUS=Startup finished\\nREADY=1')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.calls()[0].split()
        self.assertEqual(run[:4], ['run', '-d', '--name', 'box'])
        self.assertIn('NOTIFY_SOCKET=/run/host-notify/notify', run)
        self.assertEqual(run[-3:], ['--privileged', 'image', '/sbin/init'])

    def test_progress_messages_are_not_readiness(self):
        result = self.run_script(send='STATUS=Starting\\nREADY=0|X_SYSTEMD_READY=1', exit_status='137')
        self.assertEqual(result.returncode, 1)
        self.assertIn('box stopped (status 137) before systemd finished start-up', result.stderr)

    def test_a_container_that_stops_first_fails(self):
        result = self.run_script(exit_status='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('status 1', result.stderr)

    def test_requires_a_name_and_an_image(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'box'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('usage', result.stderr)


if __name__ == '__main__':
    unittest.main()
