# Plymouth terminal input carry

Carry Arch's Plymouth 26.134.222-3 recipe as 26.134.222-4 for aarch64.
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

Build with `bash scripts/build-package plymouth` on aarch64 ALARM, or use
the repository's signed ALARM container build. Recipe discovery automatically
adds this package to the native build matrix and complete signed repository
snapshot. Both desktop package lists in `scripts/build-image` already select
`plymouth`, and the Aurora repository precedes the distribution repository.
After upgrading an installed system, regenerate its initramfs with
`mkinitcpio -P` so it includes the patched libraries.

## Script keyboard lifetime and theme 1-4

The same carry also applies `0001-Fix-splash-keyboard-lifetime.patch`, copied
unchanged from the Ryan-authored t-4476 implementation. It notifies consumers
before freeing renderer keyboards, updates the script library on replacement
and detach, and preserves input handler ownership across hide/show. Removing
theme caps-lock polling alone cannot make the hide path safe.

`check-keyboard-lifetime.sh` runs native query and renderer-removal fixtures
against the just-built libraries and private X11/label modules under Xvfb.
The renderer fixture uses a private PTY and requires no hardware console.
The original terminal-input PTY regression remains enabled.

Plymouth 26.134.222-5 provides `plymouth-script-keyboard-lifetime=1` using
pacman's capability syntax. Theme 1-4 requires that capability >= 1.

Public GPL-2.0-or-later implementation sources are Plymouth
[24.004.60](https://gitlab.freedesktop.org/plymouth/plymouth/-/tree/d6e6366d622962dce02d8c7e4ab814f54a202509)
and [26.134.222](https://gitlab.freedesktop.org/plymouth/plymouth/-/tree/1aacf818fd5d1b6a7695546eb08fcbc46893dd0b).
Install the matching core and theme together and rebuild the initramfs or
NixOS boot generation. Preserve the previous packages, configuration and
initramfs or generation, and restore them together to roll back.
