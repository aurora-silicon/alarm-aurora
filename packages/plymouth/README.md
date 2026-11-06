# Plymouth carries

Carry Arch's Plymouth 26.134.222-3 recipe as 26.134.222-6 for aarch64.
The [ALARM package](https://archlinuxarm.org/packages/aarch64/plymouth)
uses the Arch recipe without an ALARM override. The packaging and helper
files come from Arch packaging commit
`159d76948b6ade8aaa4c1eecba19019ff3b8043f`; its 0BSD license is retained
in `LICENSE`. The upstream XKB cherry-pick, mkinitcpio integration, font
changes, themes, and original BLAKE2 checksums are retained.

The production patch and GPL-2.0-or-later PTY regression are copied unchanged
from [Fedora carry #111](https://github.com/aurora-silicon/fedora-aurora/pull/111),
merged as `365f64902977d8b59de166722b2a3ef9ea1ae94d`. They have SHA-256
checksums in the recipe. Terminal input uses a separate nonblocking open
file description, preserving blocking output writes. Retire the carry when
the distribution includes an equivalent upstream fix.

`check()` compiles the PTY regression against the libraries just built and
runs it with a 15-second bound. It covers empty input, consumed readiness,
a termios reset, a partial canonical line, a subsequent complete line,
close/reopen cleanup, and the real keyboard event handler. No hardware
console is required.

`0001-systemd-units-Start-plymouthd-without-waiting-for-coldplug.patch` is
copied unchanged from [Fedora carry #149](https://github.com/aurora-silicon/fedora-aurora/pull/149).
It orders `plymouth-start.service` after `systemd-udevd.service` instead of
after the whole coldplug trigger. `aurora-boot`'s `aurora-early-kms` initcpio
hook coldplugs the Apple display before `systemd-udev-trigger`, so the splash
starts on appledrm in the initramfs. Retire the patch with the Fedora one.

## SDR display handoff

`0002-drm-Reset-inherited-HDR-connector-state-before-SDR.patch` and the
GPL-2.0-or-later `test-drm-sdr.c` regression are copied unchanged from
[Fedora carry #159](https://github.com/aurora-silicon/fedora-aurora/pull/159),
merged as `7dc345041f935449a706415cc7518dccdb691aaf`. Both have SHA-256
checksums in the recipe, and the patch applies cleanly to 26.134.222 after
the two carries above.

Plymouth's DRM renderer draws SDR pixels and presents them with legacy
`drmModeSetCrtc()`, which keeps the previous DRM master's connector
`HDR_OUTPUT_METADATA` and `Colorspace`. A compositor can drop master before
closing its file, so the reboot or shutdown splash could inherit PQ/BT.2020
and show a blown out logo. The patch clears both properties on the head's
connectors, clones included, in one blocking atomic commit before setting
the scanout buffer. A failed reset leaves scanout for a later retry, each
activation rechecks, and drivers without atomic support keep the legacy
path. The compositor restores its own HDR state when it takes control again.

`check()` compiles the DRM regression against the renderer source and the
libraries just built, with libdrm mocked, and runs it with a 15-second bound.
It checks that no SDR framebuffer is presented while either inherited
property is set, that clones reset together, that unrelated properties and
connectors are left alone, and covers SDR redraws, missing properties,
legacy drivers, allocation/query/commit failures and retry. No DRM device
is required.

Build with `bash scripts/build-package plymouth` on aarch64 ALARM, or use
the repository's signed ALARM container build. Recipe discovery automatically
adds this package to the native build matrix and complete signed repository
snapshot. Both desktop package lists in `scripts/build-image` already select
`plymouth`, and the Aurora repository precedes the distribution repository.
After upgrading an installed system, regenerate its initramfs with
`mkinitcpio -P` so it includes the patched libraries.
