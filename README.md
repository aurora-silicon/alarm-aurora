# Aurora ALARM

Arch Linux ARM packages and images for Aurora on Apple Silicon. The native [Aurora installer](https://github.com/aurora-silicon/aurora-installer) offers KDE Plasma, GNOME and minimal profiles, alongside Fedora and NixOS.

Hardware PKGBUILDs retain the provenance of Aurora's reviewed Arch packaging and pin the common Aurora kernel, Mesa, Aura and U-Boot sources. `sources.json` records the shared revisions; `images/base.json` pins the official signed Arch Linux ARM root filesystem. The included build-system public key verifies the image's detached signature before extraction.

```sh
python3 scripts/fetch-base.py
bash scripts/build-package aura
```

Package builds require native AArch64 Linux. CI uses an isolated signed ALARM root filesystem; it never installs packages or boot files on the runner host. Binary packages are written to `out/packages/`.

Development status: native package builds, the signed testing repository and KDE, GNOME and minimal development installer payloads are published. These are development artifacts; physical installation, encrypted first boot and update/reboot qualification remain pending. Device firmware/calibration is extracted from the target Mac.

Package recipes originated from aurora-silicon/omarchy-pkgs at 533635f0715c28c5e375b1ec7324f31d43b69efc. This repository carries the independent Aurora distribution integration; it does not install the Omarchy desktop.


The dedicated ALARM package/database signing key is committed under `keys/aurora-alarm.asc`, fingerprint `A33623FB30665BEFAA0FFB6DE35EC749219B20F7`. `scripts/sign-repository.py` signs and verifies every archive and both pacman databases. The manual publication workflow requires a successful complete main-branch build at the same commit and publishes an immutable testing snapshot. Packages preserve their epoch metadata while using portable asset filenames. No private signing material is committed.

Native local Aura, U-Boot, ALSA/audio, bless, speakerguardd, firmware and boot package builds have passed. Mesa passes all 72 tests and the compiler-runtime dependency check. The published development feed and installer images precede the latest kernel and radio changes; the refreshed set requires publication and installation qualification. These results do not establish an ALARM boot on Neo.

The default image includes Aurora's `avd-fw` and `upower-aurora` forks. UPower is selected in the initial desktop transaction so its provider satisfies desktop dependencies; the image rejects stock `upower` alongside it. Kernel packages carry the accepted M4+ wait-state fix while the source pin remains on the shared 7.2.10 tree.
