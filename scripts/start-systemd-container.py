#!/usr/bin/env python3
"""Start a container whose init is systemd and return once systemd has booted it.

usage: start-systemd-container.py NAME DOCKER-RUN-OPTIONS... IMAGE [COMMAND...]

systemd, as a container's init, sends READY=1 to the container manager's
$NOTIFY_SOCKET when start-up has finished, that is when its default target is
reached (systemd's container interface, docs/CONTAINER_INTERFACE.md). Docker
does not listen for it, so this binds that socket in a host directory, mounts
the directory into the container and waits for READY=1. If the container stops
first, this fails with the container's exit status. The container keeps
running detached, as with `docker run -d`.
"""
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile

MOUNT = '/run/host-notify'


def ready(datagram):
    return 'READY=1' in datagram.decode('utf-8', 'replace').splitlines()


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip().splitlines()[2])
    name, run = sys.argv[1], sys.argv[2:]
    docker = os.environ.get('DOCKER', 'docker')
    with tempfile.TemporaryDirectory(prefix='systemd-notify-') as directory:
        os.chmod(directory, 0o755)
        path = Path(directory) / 'notify'
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.bind(str(path))
            path.chmod(0o666)
            subprocess.run([docker, 'run', '-d', '--name', name, '-e', f'NOTIFY_SOCKET={MOUNT}/notify',
                            '-v', f'{directory}:{MOUNT}', *run], check=True, stdout=subprocess.DEVNULL)
            # `docker wait` prints the exit status when the container stops.
            waiter = subprocess.Popen([docker, 'wait', name], stdout=subprocess.PIPE)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(sock, selectors.EVENT_READ)
                    selector.register(waiter.stdout, selectors.EVENT_READ)
                    while True:
                        for key, _ in selector.select():
                            if key.fileobj is sock:
                                if ready(sock.recv(65536)):
                                    print(f'{name}: systemd finished start-up', file=sys.stderr)
                                    return 0
                            else:
                                status = waiter.stdout.read().decode().strip()
                                sys.exit(f'{name} stopped (status {status or "unknown"}) before systemd finished start-up')
            finally:
                if waiter.poll() is None:
                    waiter.kill()
                waiter.wait()


if __name__ == '__main__':
    sys.exit(main())
