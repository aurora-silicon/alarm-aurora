# Vendor firmware handoff

This Mac's own firmware and calibration (Wi-Fi, Bluetooth, keyboard, Touch Bar,
AOP sensors) are not in the packages. The installer extracts them from macOS and
leaves them on the EFI system partition (ESP) as `vendorfw/firmware.cpio`.
`aurora-firmware` hands them to the kernel: `load-vendor-firmware` runs in the
initrd and again on the real root, extracts the archive into
`/run/aurora-firmware`, points the kernel firmware search path at it and admits
the peripherals that need it.

## What protects the archive

The ESP is a FAT filesystem outside every signature, so what can be trusted
depends on how the system booted.

- **Signed boot (the `aurora-secboot` secure path).** The UKI's signature
  covers its command line, and `aurora-secboot uki build` binds the archive
  there: `aurora.vendorfw=sha256:<digest>`, or `aurora.vendorfw=none` when the
  ESP had no archive. The first UKI built pins that value, `none` included, in
  `/var/lib/aurora/secboot/keys/vendorfw.sha256`, and the pin alone decides it
  from then on. `load-vendor-firmware` then copies the archive off the ESP,
  checks the copy against that digest and extracts only a matching copy. A
  different archive, `none`, an empty or a malformed value is refused with a
  logged reason: the firmware search path is left alone and the peripherals that
  need the archive are not admitted. The rest of the boot continues.

  After the installer replaces or adds the archive, for example after a macOS
  update, remove `vendorfw.sha256` and rebuild the UKI (`mkinitcpio -P`). Until
  then the new archive is refused.

- **Unsigned boot (GRUB).** The command line has no `aurora.vendorfw=`, and
  the archive is used as found. Nothing outside the ESP records it, and on
  this path U-Boot loads GRUB from the same ESP without checking it. So anyone
  who can write the ESP already controls the boot, and checking the archive
  would not change that. Use the secure path if ESP tampering is in your threat
  model.
