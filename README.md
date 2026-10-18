# Aurora ALARM

Arch Linux ARM packages and images for Aurora on Apple Silicon. The native [Aurora installer](https://github.com/aurora-silicon/aurora-installer) offers KDE Plasma, GNOME and minimal profiles, alongside Fedora and NixOS.

Hardware PKGBUILDs retain the provenance of Aurora's reviewed Arch packaging and pin the common Aurora kernel, Mesa, Aura and U-Boot sources. `sources.json` records the shared revisions; `images/base.json` pins the official signed Arch Linux ARM root filesystem. The included build-system public key verifies the image's detached signature before extraction.

```sh
python3 scripts/fetch-base.py
bash scripts/build-package aura
```

Package builds require native AArch64 Linux. CI uses an isolated signed ALARM root filesystem; it never installs packages or boot files on the runner host. Binary packages are written to `out/packages/`.

Development status: package recipes, verified base acquisition and native CI are present. Full package builds, a signed Aurora pacman repository, desktop image assembly and actual installation tests remain qualification work. No ALARM OS image is published yet. Device firmware/calibration is always extracted from the target Mac.

Package recipes originated from aurora-silicon/omarchy-pkgs at 533635f0715c28c5e375b1ec7324f31d43b69efc. This repository carries the independent Aurora distribution integration; it does not install the Omarchy desktop.
