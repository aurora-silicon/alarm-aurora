#!/usr/bin/env python3
"""Build the ALARM test image inside a builder VM: the NixOS test image from
../nixos-vm booted under QEMU (hvf), with this directory shared over 9p and
the target image attached as /dev/vdb. Used because the Lima arm64 guest was
below its free-space guard.

usage: qemu-builder.py VARIANT    (writes VARIANT.raw, VARIANT-build.log)
"""
import os, re, socket, subprocess, sys, time
D = os.path.dirname(os.path.abspath(__file__))
V = sys.argv[1]
target = os.path.join(D, f'{V}.raw')
if os.path.exists(target):
    os.unlink(target)
subprocess.run(['truncate', '-s', '6G', target], check=True)
overlay = os.path.join(D, 'builder.qcow2')
subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'raw', '-b',
                os.path.join(D, '..', 'nixos-vm', 'test.raw'), overlay], check=True)
mon, ser = os.path.join(D, 'builder.mon'), os.path.join(D, 'builder.ser')
for p in (mon, ser):
    if os.path.exists(p):
        os.unlink(p)
q = subprocess.Popen(['qemu-system-aarch64', '-M', 'virt', '-accel', 'hvf', '-cpu', 'host', '-smp', '4', '-m', '3072',
    '-bios', '/opt/homebrew/share/qemu/edk2-aarch64-code.fd',
    '-drive', f'file={overlay},if=virtio,format=qcow2', '-drive', f'file={target},if=virtio,format=raw',
    '-virtfs', f'local,path={D},mount_tag=w,security_model=none,id=w',
    '-nic', 'user,model=virtio-net-pci', '-device', 'virtio-gpu-pci', '-device', 'virtio-keyboard-pci',
    '-display', 'none', '-serial', f'unix:{ser},server=on,wait=off', '-monitor', f'unix:{mon},server=on,wait=off'])
log = open(os.path.join(D, f'{V}-builder-console.log'), 'w')
t0 = time.time()
while not (os.path.exists(ser) and os.path.exists(mon)):
    time.sleep(0.1)
time.sleep(0.3)
s = socket.socket(socket.AF_UNIX); s.connect(ser); s.settimeout(0.5)
buf = ''
def pump():
    global buf
    try:
        data = s.recv(65536).decode(errors='replace')
    except socket.timeout:
        return
    buf += data; log.write(data); log.flush()
def wait_for(text, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if text in buf:
            return True
        pump()
    raise SystemExit(f'timeout waiting for {text!r}')
def monitor(cmd):
    m = socket.socket(socket.AF_UNIX); m.connect(mon); m.settimeout(1)
    try: m.recv(4096)
    except socket.timeout: pass
    m.sendall((cmd + '\n').encode()); time.sleep(0.2); m.close()
# The builder's own LUKS prompt (plymouth on the display): type the passphrase.
while time.time() - t0 < 20:
    pump()
for ch in 'aurora-luks-test':
    monitor('sendkey ' + {'-': 'minus'}.get(ch, ch)); time.sleep(0.1)
monitor('sendkey ret')
wait_for('login:', 120)
s.sendall(b'root\n'); wait_for('Password:', 20)
s.sendall(b'aurora\n'); time.sleep(2); buf = ''
cmd = (f'mkdir -p /w && mount -t 9p -o trans=virtio,version=9p2000.L,msize=262144 w /w && '
       f'bash /w/build-image-vm.sh {V} > /w/{V}-build.log 2>&1; echo BUILD-EXIT=$?\n')
s.sendall(cmd.encode())
end = time.time() + 3600
while time.time() < end and not re.search(r'BUILD-EXIT=\d+', buf):
    pump()
pump()
m = re.search(r'BUILD-EXIT=(\d+)', buf); code = m.group(1) if m else 'timeout'
s.sendall(b'sync; umount /w; poweroff\n')
try:
    q.wait(timeout=60)
except subprocess.TimeoutExpired:
    monitor('quit'); q.wait(timeout=20)
os.unlink(overlay)
print(f'{V}: build exit {code}, {time.time() - t0:.0f} s')
