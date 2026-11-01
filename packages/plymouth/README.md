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
