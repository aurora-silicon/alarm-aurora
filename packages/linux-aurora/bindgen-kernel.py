#!/usr/bin/env python3
"""Adapt one unsupported generated lint to Rust 1.85; retain layout assertions."""
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
binary = Path(__file__).resolve().parents[1] / "rust-bindgen-0.73.2/target/release/bindgen"
result = subprocess.run([str(binary), *args], stdout=subprocess.PIPE)
if result.returncode:
    sys.stdout.buffer.write(result.stdout)
    raise SystemExit(result.returncode)
output = None
for index, value in enumerate(args):
    if value in ("-o", "--output"):
        output = Path(args[index + 1])
    elif value.startswith("--output="):
        output = Path(value.split("=", 1)[1])
attribute = b"#[allow(unnecessary_transmutes)]\n"
if output is None:
    sys.stdout.buffer.write(result.stdout.replace(attribute, b""))
else:
    original = output.read_bytes()
    output.write_bytes(original.replace(attribute, b""))
    sys.stdout.buffer.write(result.stdout)
