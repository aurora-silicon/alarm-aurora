# aurora-diag

`aurora-diag` is the bring-up and regression tool for Aurora on Apple
silicon. It lists sensors, clocks, hardware blocks, services and the GPU
APIs, says what works and what does not, and has `check`, `snapshot`,
`diff` and `report` commands for comparing kernels. `aurora-panic-log`
prints the last panic iBoot kept for the next OS and any kdump crash
dumps. Source: https://github.com/aurora-silicon/aurora-diag (MIT).

The package is opt-in. It is in no package group, no other package
depends on it and no image installs it. Install it with
`sudo pacman -S aurora-diag`. It needs only python; the dashboard uses
python-textual and some sections read vulkaninfo, eglinfo/glxinfo,
amixer, iw, smartctl, bluetoothctl and gdbus when they are present. These
are optdepends.

Fedora (`dnf install aurora-diag`) and NixOS (`aurora.diag.enable = true`
or `pkgs.aurora-diag`) package the same commit and run the same
`make check` suite during the build.

## Updating the pin

`sources.json` pins the commit, version and SHA-256 of the GitHub
archive. To move to a new commit, set `commit`, `version`, `source_url`,
`archive_root` and `sha256` there, then set `_commit`, `pkgver` (and
`pkgrel=1`) and `sha256sums` in `packages/aurora-diag/PKGBUILD`. The hash
is that of
`https://codeload.github.com/aurora-silicon/aurora-diag/tar.gz/<commit>`.
`tests/test_pins.py` checks that the PKGBUILD and the pin agree.
