#!/bin/bash
# Build an Arch Linux ARM aarch64 UEFI disk image with a LUKS2 root that
# boots like an Aurora desktop image, for the alarm-aurora boot-splash test.
# Runs as root in a builder VM (the NixOS test image booted under QEMU with
# this directory shared over 9p at /w); the target image is /dev/vdb.
#
# usage: build-image.sh VARIANT
#   VARIANT  test | control: installs pkgs-VARIANT/*; for control, aurora-boot
#            is built here from src-control (alarm-aurora main).
#
# VM-only differences from scripts/build-image, the same for both variants:
# the stock linux-aarch64 kernel; a 99-vm.conf mkinitcpio drop-in that drops
# the Apple-only hooks (asahi, aurora-usb4, aurora-vendor, aurora-root) and
# adds the virtio drivers; ext4 instead of btrfs; rd.luks.name and a serial
# console on GRUB_CMDLINE_LINUX; a unit that reports the unlock on ttyAMA0.
set -euo pipefail
V=$1
D=$(cd "$(dirname "$0")" && pwd)
PASS=aurora-luks-test
LUKS_UUID=7a1c55e0-2026-4b03-9a11-0c0ffee0a1a1
DISK=/dev/vdb; MNT=/mnt/alarm; MAP=alarmluks-$V
PLY=$(ls "$D"/pkgs-$V/plymouth-26*-aarch64.pkg.tar.* | tail -1)
echo "plymouth: $PLY"
wipefs -qa "$DISK"
sfdisk -q "$DISK" <<'PT'
label: gpt
size=256MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name=ESP
size=768MiB, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name=boot
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name=root
PT
udevadm settle; LOOP=$DISK; P=$DISK
cleanup() { umount -R "$MNT" 2>/dev/null || true; cryptsetup close "$MAP" 2>/dev/null || true; }
trap cleanup EXIT
mkfs.vfat -F 32 -n ESP "${P}1" >/dev/null
mkfs.ext4 -q -L boot "${P}2"
printf '%s' "$PASS" | cryptsetup luksFormat --type luks2 --uuid "$LUKS_UUID" --pbkdf pbkdf2 --pbkdf-force-iterations 100000 --batch-mode "${P}3" -
printf '%s' "$PASS" | cryptsetup open "${P}3" "$MAP" --key-file -
mkfs.ext4 -q -L root "/dev/mapper/$MAP"
mkdir -p "$MNT"; mount "/dev/mapper/$MAP" "$MNT"
tar -xzpf "$D/dl/alarm.tar.gz" -C "$MNT" --numeric-owner 2>/dev/null || true
test -x "$MNT/usr/bin/pacman"
mount "${P}2" "$MNT/mnt"; cp -a "$MNT/boot/." "$MNT/mnt/"; umount "$MNT/mnt"
mount "${P}2" "$MNT/boot"; mkdir -p "$MNT/boot/efi"; mount "${P}1" "$MNT/boot/efi"
mount -t proc proc "$MNT/proc"; mount --rbind /sys "$MNT/sys"; mount --make-rslave "$MNT/sys"
mount --rbind /dev "$MNT/dev"; mount --make-rslave "$MNT/dev"; mount -t tmpfs tmpfs "$MNT/run"
rm -f "$MNT/etc/resolv.conf"; cp -L /etc/resolv.conf "$MNT/etc/resolv.conf"
mkdir -p "$MNT/var/tmp/pkgs"; cp "$PLY" "$MNT/var/tmp/pkgs/"
inr() { chroot "$MNT" /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/bin LANG=C.UTF-8 "$@"; }
inr sed -i '/^\[options\]/a DisableSandbox' /etc/pacman.conf
inr pacman-key --init >/dev/null 2>&1; inr pacman-key --populate archlinuxarm >/dev/null 2>&1
# The ALARM mirrors time out now and then; retry.
for try in 1 2 3; do inr pacman -Syu --noconfirm --needed grub cryptsetup mkinitcpio linux-aarch64 >/dev/null && break; sleep 5; done
# The Aurora packages under test. aurora-boot's dependencies are the Apple
# platform stack, which a VM can't use.
inr pacman -U --noconfirm --needed "/var/tmp/pkgs/${PLY##*/}" >/dev/null
if [[ $V == control ]]; then
  # alarm-aurora main's aurora-boot, built here as the unprivileged user.
  inr pacman -S --noconfirm --needed fakeroot binutils >/dev/null
  rm -rf "$MNT/var/tmp/aurora-boot"; cp -a "$D/src-control/aurora-boot" "$MNT/var/tmp/aurora-boot"
  inr chown -R alarm:alarm /var/tmp/aurora-boot
  inr su alarm -s /bin/bash -c 'cd /var/tmp/aurora-boot && PKGDEST=/var/tmp/aurora-boot makepkg --nodeps --noconfirm >/dev/null'
  BOOT=$(ls "$MNT"/var/tmp/aurora-boot/aurora-boot-*-any.pkg.tar.* | tail -1)
  cp "$BOOT" "$D/pkgs-control/"
else
  BOOT=$(ls "$D"/pkgs-$V/aurora-boot-*-any.pkg.tar.* | tail -1)
fi
echo "aurora-boot: $BOOT"
cp "$BOOT" "$MNT/var/tmp/pkgs/"
# aurora-boot's pacman hook runs mkinitcpio -P against the Apple hooks; the
# VM image is generated below instead.
inr pacman -U --noconfirm -dd "/var/tmp/pkgs/${BOOT##*/}" || true
inr pacman -Q plymouth aurora-boot linux-aarch64 grub mkinitcpio systemd
# Desktop image steps from scripts/build-image: theme and plymouth hook.
inr plymouth-set-default-theme spinner
# Extracted on the host from that tree's scripts/build-image heredoc.
cp "$D/95-aurora-plymouth.conf.$V" "$MNT/etc/mkinitcpio.conf.d/95-aurora-plymouth.conf"
cat > "$MNT/usr/lib/initcpio/install/vm-virtio" <<'HOOK'
#!/bin/bash
build() { map add_module virtio_pci virtio_blk virtio_gpu virtio_input; }
help() { echo 'QEMU virtio drivers for the test VM.'; }
HOOK
cat > "$MNT/etc/mkinitcpio.conf.d/99-vm.conf" <<'CONF'
# Test VM: no Apple hardware. Drop the Apple-only hooks, keep the order.
_vm_hooks=()
for _vm_hook in "${HOOKS[@]}"; do
  case $_vm_hook in asahi|aurora-usb4|aurora-vendor|aurora-root) ;; *) _vm_hooks+=("$_vm_hook") ;; esac
  [[ $_vm_hook == sd-vconsole ]] && _vm_hooks+=(vm-virtio)
done
HOOKS=("${_vm_hooks[@]}")
unset _vm_hook _vm_hooks
CONF
# Name the kernel as linux-aurora's /boot/vmlinuz-linux-aurora is named, so
# GRUB's 10_linux pairs it with its initramfs.
mv "$MNT/boot/Image" "$MNT/boot/vmlinuz-linux"
cat > "$MNT/etc/mkinitcpio.d/linux-aarch64.preset" <<'PRESET'
ALL_kver="/boot/vmlinuz-linux"
PRESETS=('default')
default_image="/boot/initramfs-linux.img"
# The test VM's initramfs must not depend on the build host's devices.
default_options="-S autodetect"
PRESET
inr bash -c 'source /etc/mkinitcpio.conf; for f in /etc/mkinitcpio.conf.d/*.conf; do source "$f"; done; echo "HOOKS: ${HOOKS[*]}"'
inr mkinitcpio -P
# /etc/fstab and GRUB as scripts/build-image writes them, on this layout.
root_uuid=$(blkid -s UUID -o value "/dev/mapper/$MAP"); boot_uuid=$(blkid -s UUID -o value "${P}2"); efi_uuid=$(blkid -s UUID -o value "${P}1")
printf 'UUID=%s / ext4 defaults 0 1\nUUID=%s /boot ext4 defaults 0 2\nUUID=%s /boot/efi vfat umask=0077 0 2\n' "$root_uuid" "$boot_uuid" "$efi_uuid" > "$MNT/etc/fstab"
printf '\nGRUB_CMDLINE_LINUX="rd.luks.name=%s=%s console=ttyAMA0 plymouth.ignore-serial-consoles"\n' "$LUKS_UUID" "$MAP" >> "$MNT/etc/default/grub"
printf 'GRUB_CMDLINE_LINUX_DEFAULT="%s"\n' 'quiet loglevel=3 rd.udev.log_level=3 systemd.show_status=auto console=tty0 splash' >> "$MNT/etc/default/grub"
cat > "$MNT/etc/systemd/system/aurora-unlock-ok.service" <<'UNIT'
[Unit]
Description=Report the LUKS unlock and the boot timings on the serial console
After=local-fs.target systemd-journald.service
[Service]
Type=oneshot
ExecStart=/bin/sh -c '{ echo "AURORA-UNLOCK-OK $(findmnt -no SOURCE /)"; grep -h "^After=" /usr/lib/systemd/system/plymouth-start.service; journalctl -b -o short-monotonic --no-pager | grep -E "Show Plymouth Boot Screen|Forward Password Requests to Plymouth|Coldplug All udev|Apple display|Cryptography Setup|cryptroot|Switching root|Reached target.*Initrd" | sed "s/^/J /"; echo AURORA-REPORT-END; } > /dev/ttyAMA0'
[Install]
WantedBy=multi-user.target
UNIT
inr systemctl enable aurora-unlock-ok.service
inr grub-install --target=arm64-efi --efi-directory=/boot/efi --removable --no-nvram
inr grub-mkconfig -o /boot/grub/grub.cfg
cp "$MNT/boot/grub/grub.cfg" "$D/$V-grub.cfg"; cp "$MNT/etc/default/grub" "$D/$V-default-grub"
grep -E "^\s*(linux|initrd)\s" "$D/$V-grub.cfg" | head -2
# grub-mkconfig writes root=UUID= when findfs resolves the root UUID and the
# /dev/mapper path otherwise; rd.luks.name above opens the volume under that
# same name, so either boots.
grep -Eq "root=(UUID=$root_uuid|/dev/mapper/$MAP) " "$MNT/boot/grub/grub.cfg"
grep -q "initrd.*/initramfs-linux.img" "$MNT/boot/grub/grub.cfg"
ls "$MNT/etc/default/grub.d" 2>/dev/null || true
sync
echo IMAGE-OK "$V"
