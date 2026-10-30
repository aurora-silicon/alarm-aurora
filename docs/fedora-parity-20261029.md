# Fedora parity, 29 October 2026

This ports the Fedora packaging work from 28 and 29 October to native Arch
recipes. Package builds and installer assembly are separate checks. No physical
Arch boot is claimed here. Publication still requires a complete signed package
snapshot and the normal installer qualification.

| Fedora change | Arch equivalent | Verification |
| --- | --- | --- |
| https://github.com/aurora-silicon/fedora-aurora/pull/32 | `alsa-utils-aurora` builds ALSA 1.2.16 with the identical locked-control patch. It provides and conflicts with stock `alsa-utils`; `aurora-audio` requires the patched provider. | Native package build applies the patch and runs upstream `make check`. A real locked-control restore is a separate boot check. |
| https://github.com/aurora-silicon/fedora-aurora/pull/33 | `aurora-audio` installs `MODULES+=(snd-seq)` in mkinitcpio's config directory and a pacman transaction hook regenerates initramfs after install, upgrade or removal. The universal kernel requests `CONFIG_SND_SEQUENCER=m`. | Local-source checksum test; native package and image builds. Inspect the generated initramfs before boot qualification. |
| https://github.com/aurora-silicon/fedora-aurora/pull/34 | Audio recipe and `sources.json` use f513878c9c5144d2ab582b314081227a208777e3 and archive SHA256 a4997e87b298cc5ff1cfff117be1b7a9dcb6f683ea21acce15c439c08fefec07. UCM moves to Fedora's matching a270b2e2d705ed521b07d008aac45283c75fb986 (lid mic jack, fedora-aurora PR 43). | Pin and local-source checksum tests; makepkg verifies the audio archive. |
| https://github.com/aurora-silicon/fedora-aurora/pull/35 and https://github.com/aurora-silicon/fedora-aurora/pull/38 | Independent `aurora-system-fixes` package carries all four malcontent drop-ins, each naming upstream fix af8226a7d3c3. It depends only on systemd and preserves distribution identity. | Native package build and package file listing. Stop latency on an Arch install remains a hardware check. |
| https://github.com/aurora-silicon/fedora-aurora/pull/36 | `aurora-flatpak-gl` builds and packages `org.freedesktop.Platform.GL.aurora/aarch64/25.08` and `/26.08`, with priority 10, the same driver manifest and merged GL paths. environment.d and profile.d default `FLATPAK_GL_DRIVERS` to `aurora:default:host`. Pacman install/upgrade hooks install and pin both branches and set the three global loader overrides. Removal undoes the package's settings. Explicit administrator values are retained. | Native AArch64 Flatpak build; lifecycle fixture covers install, upgrade and removal while retaining administrator settings. Image assembly requires both installed branches. Actual renderer selection needs an Arch desktop. |
| https://github.com/aurora-silicon/fedora-aurora/pull/40 and https://github.com/aurora-silicon/fedora-aurora/pull/42 | Host Mesa, FEX guest Mesa and Flatpak GL share epoch, pkgver, pkgrel and commit. The tracker updates all three and dispatches all three builds. Flatpak packaging checks both commit stamps and OSTree export subjects and refuses a stale or incomplete repository, including under `--nocheck`. | Lockstep and tracker tests; missing/stale/mislabelled repository regression test; native package builds. The merge-on-planned-main guard is separately owned by https://github.com/aurora-silicon/alarm-aurora/pull/29 and is intentionally not duplicated here. |
| https://github.com/aurora-silicon/fedora-aurora/pull/39 | Kernel d266c703c13f099068284d622d397292241a0224 and Mesa 108c7218bbb6cddcb91c29680ff0770d29afcecc, including fleet 0.17's D3D11 RTE fix. | Source-pin tests, native kernel and Mesa builds; Mesa's existing upstream test suite and compiler-runtime dependency check remain required. |
| FEX guest Mesa at the host pin | `mesa-aurora-fex-guest` is an Arch `PKGBUILD` built on x86_64 with multilib. Both ELF classes are installed as a separate read-only overlay at the same paths Fedora uses. No LLVM, SPIRV-Tools, sensors or unwind runtime dependencies are permitted. | Native x86 Arch container build, ELF class/machine and dynamic dependency checks. FEX execution and compatibility with the user's guest rootfs require separate runtime qualification. The package does not download or replace that rootfs. |
| Current `avd-fw` pin | Already identical: 9cbde5c7d993844bf086318974958b11076600a0. Every installer profile already installs it. | Existing source-pin test. |
| Current Aura boot pin | Match Fedora's ec4a6ab8b4252079e78196515577d73ef0a86135, including the merged M4 Max NVMe admission and ANS buffer reservations. The kernel requires the new Arch package version. Since superseded by aura 1.0.0b1 (0ca7bf85c9946a7ec90a5701c126b70ed144bd34, #34), which contains ec4a6ab8. | Source-pin and qualification-record checks, plus a native Aura build. The candidate remains explicitly not hardware-qualified and does not enroll Stage 1. The boot fixes are public in https://github.com/aurora-silicon/aura/pull/1 and https://github.com/aurora-silicon/aura/pull/8. |
| Universal kernel and https://github.com/aurora-silicon/linux/pull/554 | One `defconfig` plus the pinned kernel's `asahi.config` plus the common Arch policy. No Neo fragment or retained full distro config. Superseded by #44: the defconfig base lacked dm-crypt, so images could not build an encrypted-root initramfs; the recipe now starts from the full distribution config resolved against the pin, with both fragments applied on top. Explicit SMC, RTC, SPMI and NVMEM built-ins, sequencer module and both Type-C alternate-mode modules. Ordered validation rejects lost shared hardware requirements. | Validator regression test; native build resolves Kconfig and validates both fragments before compiling. Existing `-ARCH` release suffix is retained for DTB discovery. |
| https://github.com/aurora-silicon/fedora-aurora/pull/41 | Deferred until the Fedora VRR change merges, as requested. Existing saved monitor choices must continue to win when it is ported. | Fedora PR was open when this port began. Recheck its status before closing parity. The preferred-panel mode also depends on https://github.com/aurora-silicon/linux/pull/562. |

All three installer profiles select the added packages. Image assembly checks the
exact versions of all four host/guest/Flatpak graphics packages and requires both
Flatpak extension branches to be installed. Nothing here publishes a package
snapshot, changes boot parameters or establishes a successful Arch boot.

The previous universal-config proposal at
https://github.com/aurora-silicon/alarm-aurora/pull/27 uses an older kernel pin
and the retained full distro base. This change implements the requested
`defconfig` baseline directly and retains ordered shared-hardware validation.
That proposal needs reconciliation before either kernel recipe is merged.

Run the source checks with `python3 -m unittest discover -s tests -p 'test_*.py'`.
On macOS, the two existing UAPI compilation tests require Linux headers and fail
on the unmodified base as well. Linux CI runs the complete suite. Native package
builds use the signed ALARM root for AArch64 packages, and an isolated x86_64 Arch
multilib container for the FEX layer. Flatpak uses an OCI container imported from
the same signature-verified ALARM archive, since Linux refuses its unprivileged
user namespaces inside a plain chroot. Flatpak builds include both runtime payloads;
there is no settings-only success path.

The Flatpak container also extracts the finished package and runs its actual
helper against a fresh system Flatpak installation with no parent runtimes or
apps installed. It enables twice, verifies both refs and pins, checks the three
loader overrides and the shell default/user override, then removes everything
and verifies cleanup. This exercises the image's first package installation
without signing or publishing a snapshot.
