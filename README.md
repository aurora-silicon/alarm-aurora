# Aurora ALARM

Arch Linux ARM packages and images for Aurora on Apple Silicon. The native [Aurora installer](https://github.com/aurora-silicon/aurora-installer) offers KDE Plasma, GNOME and minimal profiles, alongside Fedora and NixOS.

Hardware PKGBUILDs retain the provenance of Aurora's reviewed Arch packaging and pin the common Aurora kernel, Mesa, Aura and U-Boot sources. `sources.json` records the shared revisions; `images/base.json` pins the official signed Arch Linux ARM root filesystem. The included build-system public key verifies the image's detached signature before extraction.

```sh
python3 scripts/fetch-base.py
bash scripts/build-package aura
```

Hardware package builds require native AArch64 Linux; the FEX guest layer requires x86_64 Arch with multilib. CI uses an isolated signed ALARM root filesystem; it never installs packages or boot files on the runner host. Binary packages are written to `out/packages/`.

Development status: native package builds, the signed testing repository and KDE, GNOME and minimal development installer payloads are published. These are development artifacts; physical installation, encrypted first boot and update/reboot qualification remain pending. Device firmware/calibration is extracted from the target Mac.

First boot: KDE and GNOME images boot to a Plymouth splash (`spinner` theme, `plymouth` initramfs hook right after `systemd`, `splash` on the kernel command line). `aurora-firstboot` asks for the new disk password on that splash, replaces the temporary LUKS key and starts the greeter; the desktop's own setup then creates the owner account in `wheel`, which the first boot allows to use sudo. KDE uses Plasma Setup, packaged here from the Plasma release because Arch Linux ARM does not ship it; SDDM keeps the splash until the greeter starts, as GDM does. GNOME uses GNOME Initial Setup, which GDM runs while no user exists; AccountsService adds its administrator to `wheel`. Minimal images have no splash and keep the text wizard on tty1, which also creates the account; `aurora.firstboot=text` on the kernel command line selects that wizard on a desktop that has no owner yet.

Image basics: `scripts/build-image` runs `scripts/check-basics.py` on the finished root and on the files the installer writes. The build fails unless the image has a generated UTF-8 default locale, its desktop's terminal (gnome-terminal, Console or Konsole) with a launcher, GNOME's backgrounds or Plasma's wallpapers, NetworkManager enabled with the desktop's network settings, logind's lid-close suspend left in place, OpenSSH installed with no sshd unit enabled, and a GRUB that finds /boot by filesystem UUID on the startup disk only. Every profile boots with `console=tty0`, so the splash and its prompts are drawn on the display.

Package recipes originated from aurora-silicon/omarchy-pkgs at 533635f0715c28c5e375b1ec7324f31d43b69efc. This repository carries the independent Aurora distribution integration; it does not install the Omarchy desktop.


The dedicated ALARM package/database public key is committed under `keys/aurora-alarm.asc`, fingerprint `A33623FB30665BEFAA0FFB6DE35EC749219B20F7`. `scripts/sign-repository.py` signs and verifies every archive and both pacman databases. The manual publication workflow accepts successful native main-branch build IDs or manual build IDs whose commits have since been merged, then assembles a complete package set. Each reused recipe and source pin must match the publishing commit exactly, the shared build tooling must be unchanged, and the build commit must be merged. Later supplied runs select the source for an unchanged recipe; every selected immutable artifact is checked against its GitHub digest, conflicting duplicate package bytes are rejected, and every recipe must supply an actual package archive. The resulting immutable snapshot retains the build and artifact provenance. Packages preserve their epoch metadata while using portable asset filenames. No private signing material is committed.

Source tracking, automatic snapshot publication, the testing and stable channels and their signing environments are described in [docs/updates.md](docs/updates.md).

Native local Aura, U-Boot, ALSA/audio, bless, speakerguardd, firmware and boot package builds have passed. Mesa passes all 72 tests and the compiler-runtime dependency check. The published development feed and installer images precede the latest kernel and radio changes; the refreshed set requires publication and installation qualification. These results do not establish an ALARM boot on Neo.

The default image includes Aurora's `avd-fw` and `upower-aurora` forks. UPower is selected in the initial desktop transaction so its provider satisfies desktop dependencies; the image rejects stock `upower` alongside it. The kernel uses the shared 7.3.0 tree with one universal defconfig plus the shared hardware requirements and Arch integration options.

The [28/29 October Fedora parity table](docs/fedora-parity-20261029.md) covers locked-control ALSA restore, sequencer modules in mkinitcpio, malcontent shutdown drop-ins and matching native, FEX guest and Flatpak Mesa. Every image selects these packages. FEX guest Mesa builds on x86_64 Arch; the remaining recipes build in the signed AArch64 root. Flatpak packages carry both supported runtime payloads and reject stale repositories. Build and boot qualification status is recorded separately in the parity PR.
