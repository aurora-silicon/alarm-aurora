#!/usr/bin/env python3
"""Check the replacement ntdll ABI and retain the GE library's runtime path."""
import argparse
import os
from pathlib import Path
import re
import subprocess


def output(*arguments):
    return subprocess.check_output(arguments, text=True, env={**os.environ, "LC_ALL": "C"})


def properties(path):
    header = output("readelf", "--file-header", "--wide", str(path))
    if not all(value in header for value in ("ELF64", "little endian", "AArch64")):
        raise ValueError(f"not a native little-endian AArch64 ELF64 library: {path}")
    symbols = {line.split()[0] for line in output(
        "nm", "-D", "--defined-only", "--format=posix", str(path)).splitlines() if line.strip()}
    if not symbols:
        raise ValueError(f"no exported interface in {path}")
    dynamic = output("readelf", "--dynamic", "--wide", str(path))
    needed = set(re.findall(r"\(NEEDED\).*Shared library: \[(.*?)\]", dynamic))
    versions = set(re.findall(r"Name: (GLIBC_[^\s]+)", output(
        "readelf", "--version-info", "--wide", str(path))))
    paths = re.findall(r"\((RPATH|RUNPATH)\).*Library (?:rpath|runpath): \[(.*?)\]", dynamic)
    if len(paths) > 1:
        raise ValueError(f"ambiguous runtime path in {path}")
    return symbols, needed, versions, paths


def glibc_floor(versions):
    numeric = [tuple(map(int, version.removeprefix("GLIBC_").split(".")))
               for version in versions if re.fullmatch(r"GLIBC_\d+(?:\.\d+)+", version)]
    return max(numeric, default=())


def verify(original, replacement):
    before = properties(original)
    after = properties(replacement)
    if before[0] != after[0]:
        raise ValueError(f"exported symbols differ: missing={sorted(before[0] - after[0])}, "
                         f"additional={sorted(after[0] - before[0])}")
    if not after[1] <= before[1]:
        raise ValueError(f"replacement adds runtime libraries: {sorted(after[1] - before[1])}")
    if glibc_floor(after[2]) > glibc_floor(before[2]):
        raise ValueError(f"replacement raises GLIBC requirements: {glibc_floor(before[2])} "
                         f"-> {glibc_floor(after[2])}")
    special = lambda values: {value for value in values if not re.fullmatch(r"GLIBC_\d+(?:\.\d+)+", value)}
    if not special(after[2]) <= special(before[2]):
        raise ValueError(f"replacement adds GLIBC ABI requirements: {sorted(special(after[2]) - special(before[2]))}")
    if before[3]:
        kind, value = before[3][0]
        arguments = ["--force-rpath"] if kind == "RPATH" else []
        subprocess.run(["patchelf", *arguments, "--set-rpath", value, str(replacement)], check=True)
    else:
        subprocess.run(["patchelf", "--remove-rpath", str(replacement)], check=True)
    final = properties(replacement)
    if final[:3] != after[:3] or final[3] != before[3]:
        raise ValueError("runtime-path restoration changed the library interface")
    print(f"Verified {len(after[0])} exports, NEEDED={','.join(sorted(after[1]))}, "
          f"GLIBC floor={'.'.join(map(str, glibc_floor(after[2])))}, runtime path={before[3]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("replacement", type=Path)
    arguments = parser.parse_args()
    verify(arguments.original, arguments.replacement)


if __name__ == "__main__":
    main()
