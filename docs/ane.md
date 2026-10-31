# ANE userspace packaging

These opt-in packages install no kernel modules, device-tree overlays, DKMS,
boot hooks, Apple firmware, or Apple models. The Aurora kernel supplies the driver.

| Payload | Fedora | ALARM | NixOS |
| --- | --- | --- | --- |
| omarchy-ane-tools | 0.5.7-2 | 0.5.7-2 | 0.5.7 |
| mil-hwx-compiler (mil-hwxc) | 0.3.1-1 | 0.3.1-1 | 0.3.1 |
| Tool commands | omarchy-ane-run, omarchy-ane-smoke, omarchy-ane-firmware-fetch | same | same |
| Smoke fixtures | h13-anec/add/program-0.anec, h14-anec/add/program-0.anec | same | same |
| Permissions | accel group, 0660, 70-omarchy-ane.rules | same | same |
| Shared inference runtime | reserved for t-3650 release | same | same |

The compiler pin is upstream tag v0.3.1, commit
927013f5480768b07c8e62a866e1514c41aba778. The MIT compiler installs only
`bin/mil-hwxc` and its license. On Fedora and ALARM, the recipe also builds
private `libobjc2` and GNUstep Base libraries from the exact commits in upstream's
bootstrap script, using verified archives and no build-time downloads. These
MIT/LGPL-2.1-or-later libraries live under `lib/mil-hwx-compiler`, with their
licenses, and do not replace or provide the system's GNUstep ABI. NixOS uses
nixpkgs' libobjc2/GNUstep derivations as runtime dependencies. No macOS frameworks
or compiled Apple model examples are installed. The compiler's H13 software
suite runs in every recipe; no device is needed.

The tools install the upstream MIT userspace runner (statically linked libane),
smoke and fetch scripts, the two add fixtures and LICENSE. A common small patch
makes smoke resolve fixtures relative to its installation prefix and names the
correct package in recovery messages. The rule and smoke patch are identical
across the three recipes. NixOS additionally patches interpreter/store paths
and the firmware location as described below. All three carry the same sysusers
entry; NixOS also declares the group through its module.

Enroll only intended users in `accel` (Fedora/ALARM: `sudo usermod -aG accel USER`;
NixOS: `users.users.USER.extraGroups = [ "accel" ];`), then log in again.
Reload udev rules and retrigger the accel device, or reboot, after installation.
Run `omarchy-ane-smoke`: it checks 20 add calls and emits one JSON result.
An unsupported chip or missing driver returns exit 2. Firmware fetching is
always an explicit owner action; no install hook runs it.

The shared inference runtime is deliberately not represented by a dummy package
or a hard dependency. Once t-3650 publishes an API and release, add its source
pin, CLI/library payload and optional integration in all three repositories.
This compiler package does not promise that every target is device-proven.

For M2-family firmware, run `sudo omarchy-ane-firmware-fetch`, then reboot.
The pin-checked raw image is installed in `/usr/lib/firmware/apple/ane`.
Build both recipes with `scripts/build-package PACKAGE` in a native ALARM root.

Fixture provenance: H13's upstream README identifies the open encoder output.
H14 add SHA-256 is
`b416b9d14059a0918f6b05bfcf4a8ba982dd92e7b25f2b042c1a15f1ab2a439a`.
The compiler v0.3.1's `tests/test_h14_fixture_programs.py` regenerates it from
`tests/fixtures/h14/add.mil` and checks this exact hash. All three compiler
recipes run that software suite, closing the earlier H14 provenance gap.
