# ANE userspace packaging

These opt-in packages install no kernel modules, device-tree overlays, DKMS,
boot hooks, Apple firmware, or Apple models. The Aurora kernel supplies the driver.

| Payload | Fedora | ALARM | NixOS |
| --- | --- | --- | --- |
| omarchy-ane-tools | 0.5.13-2 | 0.5.13-1 | 0.5.13 |
| mil-hwx-compiler (mil-hwxc) | 0.3.3-1 | 0.3.3-2 | 0.3.3 |
| Tool commands | omarchy-ane-run, omarchy-ane-smoke, omarchy-ane-firmware-fetch | same | same |
| Smoke fixtures | h13-anec/add/program-0.anec, h14-anec/add/program-0.anec | same | same |
| Device permissions (every install, not these packages) | aurora-platform-core: accel group, 0660, session ACL, 70-aurora-accel.rules | aurora-system-fixes: same | platform module: same |
| Shared inference runtime | reserved for t-3650 release | same | same |

The compiler pin is upstream tag v0.3.1, commit
927013f5480768b07c8e62a866e1514c41aba778. The MIT compiler installs only
`bin/mil-hwxc` and its license. On Fedora and ALARM, the recipe also builds
private `libobjc2` and GNUstep Base libraries from the exact commits in upstream's
bootstrap script, using verified archives and no build-time downloads. These
MIT/LGPL-2.1-or-later libraries live under `lib/mil-hwx-compiler`, with their
licenses, and do not replace or provide the system's GNUstep ABI. NixOS uses
nixpkgs' libobjc2/make and a compiler-private Base 1.31.1 derivation from the
same source pin and upstream fix as runtime dependencies. No macOS frameworks
or compiled Apple model examples are installed. The compiler's H13 software
suite runs in every recipe; no device is needed.

The tools install the upstream MIT userspace runner (statically linked libane),
smoke and fetch scripts, the two add fixtures and LICENSE. A common small patch
makes smoke resolve fixtures relative to its installation prefix and names the
correct package in recovery messages. The smoke patch is identical across
the three recipes. NixOS additionally patches interpreter/store paths
and the firmware location as described below. The tools carry no device policy: the
`/dev/accel/accel*` rule and the `accel` group come with the platform on every
install (Fedora: aurora-platform-core; ALARM: aurora-system-fixes;
NixOS: the platform module), whether or not the tools are installed.

`/dev/accel/accel*` is mode 0660, group `accel`. The rule also tags it
`uaccess`, so the user of the active local (seat) session gets an ACL on it
while that session is in the foreground; systemd's own rules give accel nodes
no such ACL and would otherwise leave them mode 0666. For access outside a
local session (ssh, services), enroll the user in `accel` (Fedora/ALARM:
`sudo usermod -aG accel USER`; NixOS: `users.users.USER.extraGroups = [ "accel" ];`),
then log in again. Until this rule, a default install left the node mode 0666,
so ssh-only accounts and test harnesses that used it without the tools lose
access until they are in `accel`. An upgrade applies the mode to an existing
node at once (Fedora `%posttrans`, an ALARM pacman hook, a NixOS unit that runs
on switch), with an add event: a change event does not reapply the group and
mode. Fedora's SELinux policy has no file context for `/dev/accel` (the node is
`device_t`), so this covers unconfined users only, as before.
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


Source redistribution: the full upstream archives include unrelated binary
research inputs. `redistribute_source = false` excludes both archives from
Aurora's source mirror. Builders fetch and hash-check upstream directly;
only the explicit userspace output file lists are distributed. Fedora uses
NoSource: 0 and publishes `.nosrc.rpm` recipe packages (the GNUstep dependency
sources remain included). To rebuild one, first fetch the upstream source pin
with `scripts/fetch-sources.py PACKAGE --output SOURCES`. ALARM source exports
must use `makepkg --source`, which omits remote archives, rather than
`--allsource`. Nix publishes runtime outputs/closures, never these source
fetcher outputs. Owner-fetched firmware remains outside all distributable builds.


The private Fedora/ALARM GNUstep Base pin carries upstream fix
[4a61eee44f53](https://github.com/gnustep/libs-base/commit/4a61eee44f537e5f83f68d447c29a6e5b6e40fdc),
which removes an invalid `__block` instance-variable qualifier. NixOS uses the same Base pin/fix in a compiler-private derivation with
nixpkgs' libobjc2/make. Base 1.29 lacks required compiler APIs; the system
GNUstep package is not overridden.
