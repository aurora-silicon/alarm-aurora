# Aurora SEP integration

The shared kernel builds SEP as a module. The root filesystem supplies the
identity state, boot-container device link and per-device calibration, so an
early built-in probe cannot initialize the driver reliably.

The boot timer starts the loader after local filesystems are available, without
holding up the desktop. fprintd also joins initialization when requested. The
modprobe alias blacklist only defers automatic probing: the service explicitly
loads SEP on every supported boot. The loader skips an older running
kernel with SEP built in, and starts normally after reboot into the module-based
kernel. The package conflicts with an older `linux-aurora`, so it holds the packaged
kernel to one with the module-based driver and still installs beside a kernel
from outside pacman; the units then run only where `apple_sep` is a loadable
module.

Calibration extraction reads the local boot container without modifying it. A
private cache is bound to its partition identity and SHA-256. The device-tree
firmware name is respected. No calibration data is distributed or reused across
machines. Models without a fingerprint reader can still initialize SEP trusted
keys; missing calibration is reported without suppressing the cryptographic
services. Read XART-SAFETY.md for persistent identity ownership constraints and
OS-IDENTITY.md for running Linux beside macOS.

On a Mac with a reader, `aurora-sep-ready.service` opens `/dev/sep-bio` before
fprintd starts, which restores the enrolled fingerprints. It reports Touch ID
ready only when the driver says the sensor attached, the fingerprints were
restored and a match can save its state past the xART guard. When matching is
blocked it logs the reason and the documented `xart_guard=0` opt-out and fails
the unit; when that cannot be told yet it logs "matching UNVERIFIED".

The Aurora libfprint build keeps the full upstream driver set and adds the SEP
biometric interface. This package does not edit PAM, replace password login or
change the power-button action; enable `pam_fprintd` in the PAM stacks that
should accept a fingerprint. Use the desktop's fingerprint
enrollment flow once hardware qualification is complete. Module reload cannot
repeat the secure enclave handoff; driver updates take effect after a full
reboot.

Two choices are left to the owner. GNOME Shell offers fingerprint only on the
lock screen; `sudo systemctl enable aurora-sep-greeter-fingerprint.service`
also offers it at the login screen from the next boot (it needs `gresource`
from glib2-devel, and a fingerprint login cannot unlock the keyring). The
Touch ID sensor is the power button, and outside GNOME a short press powers
off; to make it suspend instead, copy
`/usr/share/doc/aurora-sep/logind-aurora-sep.conf` to
`/etc/systemd/logind.conf.d/50-aurora-sep.conf`.

Arch Linux ARM does not ship SELinux, so this package carries no policy
module. The Fedora package's `aurora-sep-selinux` labels `/dev/sep-bio` and
lets fprintd read the lid switch; here the fprintd drop-ins from this package
and `libfprint-aurora` are all the access control there is.
