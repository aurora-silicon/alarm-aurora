from contextlib import contextmanager
from pathlib import Path
import os
import dbus
import re
import socket
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
OFFER = re.compile(rb"fprintd:password-switch:([0-9a-f]{32})\n")
INTERFACE = "net.reactivated.Fprint.PasswordSwitch"
PREFIX = "/net/reactivated/Fprint/PasswordSwitch/"
AGENT_PREFIX = "net.reactivated.Fprint.PasswordSwitch.Agent.p"


@contextmanager
def reader(mode, *, announce=True):
    global stop_log
    temporary = tempfile.TemporaryDirectory()
    stop_log = Path(temporary.name) / "verify-stop"
    daemon = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE, text=True,
    )
    address = daemon.stdout.readline().strip()
    mock = subprocess.Popen(
        ["/usr/bin/python3", str(HERE / "mock-fprintd.py"), address, mode, str(stop_log)],
        stdout=subprocess.PIPE, text=True,
    )
    agent = None
    try:
        assert mock.stdout.readline().strip() == "ready"
        if announce:
            agent = dbus.bus.BusConnection(address)
            assert agent.request_name(AGENT_PREFIX + str(os.getpid()), dbus.bus.NAME_FLAG_DO_NOT_QUEUE) == dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER
        yield address
    finally:
        if agent is not None:
            agent.close()
        for process in (mock, daemon):
            process.terminate()
            process.wait(timeout=3)
        temporary.cleanup()


@contextmanager
def authenticate(address, *, timeout=10, enabled=True):
    with tempfile.TemporaryDirectory() as tmp:
        args = "polkit-password-switch" if enabled else ""
        (Path(tmp) / "polkit-1").write_text(
            f"auth sufficient {HERE}/pam_fprintd-switch.so {args} timeout={timeout} max-tries=1\n"
            f"auth required {HERE}/pam_mock_password.so\n"
        )
        peer, helper_socket = socket.socketpair()
        with peer, helper_socket:
            peer.settimeout(3)
            env = {key: value for key, value in os.environ.items() if key != "DBUS_SYSTEM_BUS_ADDRESS"}
            if address:
                env["DBUS_SYSTEM_BUS_ADDRESS"] = address
            user = "test-user" if address else os.environ["USER"]
            helper = subprocess.Popen(
                [str(HERE / "pam-test"), tmp, user],
                stdin=helper_socket, stdout=helper_socket, env=env,
            )
            helper_socket.close()
            try:
                with peer.makefile("rb") as output:
                    yield peer, output, helper
            finally:
                if helper.poll() is None:
                    helper.terminate()
                    helper.wait(timeout=3)


def offer(output):
    while line := output.readline():
        if match := OFFER.fullmatch(line):
            return match[1].decode()
    raise AssertionError("No switch offer")


def password_prompt(output, *, expect_offer=True):
    while line := output.readline():
        if not expect_offer:
            assert not OFFER.fullmatch(line), line
        if line == b"Password:\n":
            return
    raise AssertionError("No password prompt")


def signal(address, token, *payload):
    bus = dbus.bus.BusConnection(address) if address else dbus.SystemBus(private=True)
    message = dbus.lowlevel.SignalMessage(PREFIX + token, INTERFACE, "UsePassword")
    if payload:
        message.append(payload[1], signature=payload[0])
    bus.send_message(message)
    bus.flush()
    return bus


@contextmanager
def foreign_sender(address, token):
    # Hold the sender's bus connection open until PAM resolves its PID and UID.
    program = """
import dbus, sys
bus = dbus.bus.BusConnection(sys.argv[1]) if sys.argv[1] else dbus.SystemBus(private=True)
message = dbus.lowlevel.SignalMessage(sys.argv[2], sys.argv[3], 'UsePassword')
bus.send_message(message)
bus.flush()
print('sent', flush=True)
sys.stdin.readline()
"""
    process = subprocess.Popen(
        ["/usr/bin/python3", "-c", program, address or "", PREFIX + token, INTERFACE],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout.readline().strip() == "sent"
        assert process.poll() is None
        yield
    finally:
        process.stdin.close()
        process.wait(timeout=3)


def assert_scan_continues(peer, reason):
    peer.settimeout(0.2)
    try:
        pending = peer.recv(1, socket.MSG_PEEK)
    except TimeoutError:
        return
    finally:
        peer.settimeout(3)
    raise AssertionError(f"{reason}: unexpected PAM response {pending!r}")


def result(output, helper, code):
    assert output.readline() == f"RESULT {code}\n".encode()
    assert helper.wait(timeout=3) == code


with reader("wait") as address:
    with authenticate(address) as (peer, output, helper):
        first = offer(output)
        started = time.monotonic()
        agent = signal(address, first)
        password_prompt(output)
        assert stop_log.read_text() == "stop\n", "switch must stop verification before password prompt"
        assert time.monotonic() - started < 1
        peer.sendall(b"wrong-password\n")
        result(output, helper, 7)
    with authenticate(address) as (peer, output, helper):
        second = offer(output)
        assert first != second
        agent = signal(address, first)
        malformed = signal(address, second, "s", "unexpected-payload")
        assert_scan_continues(peer, "Stale or malformed signal")
        with foreign_sender(address, second):
            assert_scan_continues(peer, "Another process with the current token")
        agent = signal(address, second)
        password_prompt(output)
        peer.sendall(b"test-only-password\n")
        result(output, helper, 0)
    with authenticate(address, timeout=1) as (peer, output, helper):
        token = offer(output)
        password_prompt(output)
        agent = signal(address, token)
        # The first password attempt still belongs to the user.
        peer.sendall(b"test-only-password\n")
        result(output, helper, 0)
    with authenticate(address, timeout=1, enabled=False) as (peer, output, helper):
        password_prompt(output, expect_offer=False)
        peer.sendall(b"test-only-password\n")
        result(output, helper, 0)

# A stock agent must not see a token even when the PAM option is enabled.
with reader("wait", announce=False) as address:
    with authenticate(address, timeout=1) as (peer, output, helper):
        password_prompt(output, expect_offer=False)
        peer.sendall(b"test-only-password\n")
        result(output, helper, 0)

    # A different process cannot advertise support on behalf of the socket peer.
    program = """
import dbus, sys
bus = dbus.bus.BusConnection(sys.argv[1])
assert bus.request_name(sys.argv[2], dbus.bus.NAME_FLAG_DO_NOT_QUEUE) == dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER
print('ready', flush=True)
sys.stdin.readline()
"""
    imposter = subprocess.Popen(["/usr/bin/python3", "-c", program, address, AGENT_PREFIX + str(os.getpid())],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert imposter.stdout.readline().strip() == "ready"
        with authenticate(address, timeout=1) as (peer, output, helper):
            password_prompt(output, expect_offer=False)
            peer.sendall(b"test-only-password\n")
            result(output, helper, 0)
    finally:
        imposter.stdin.close()
        imposter.wait(timeout=3)

with reader("match") as address:
    with authenticate(address) as (_, output, helper):
        offer(output)
        result(output, helper, 0)

print("PASS: immediate switch, valid and invalid passwords, same-UID foreign sender, stale and malformed signals, late click, opt-out, stock agent, foreign advertiser, fingerprint match")
