#!/usr/bin/env python3
"""Stop only key agents rooted in this disposable image, then await exit."""
import os
from pathlib import Path
import subprocess
import sys
import time

root = str(Path(sys.argv[1]).resolve())
agents = {"gpg-agent", "dirmngr", "scdaemon", "keyboxd"}


def remaining():
    found = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() not in agents:
                continue
            if os.readlink(process / "root") != root:
                continue
            # Zombies have released their mount and file references.
            if (process / "stat").read_text().rsplit(")", 1)[1].split()[0] != "Z":
                found.append(process.name)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return found


subprocess.run(["chroot", root, "gpgconf", "--homedir", "/etc/pacman.d/gnupg", "--kill", "all"], check=True)
deadline = time.monotonic() + 10
while remaining():
    if time.monotonic() >= deadline:
        raise SystemExit("Image key agents did not exit: " + ", ".join(remaining()))
    time.sleep(0.05)
print("Disposable image key agents have exited", flush=True)
