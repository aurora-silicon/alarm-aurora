#!/bin/sh
# SPDX-License-Identifier: MIT
# Never reset a running device. Repeated modprobe of a loaded module is inert.
set -eu
firmware_root=${AURORA_FIRMWARE_ROOT:-/lib/firmware}
compatible=${AURORA_DT_COMPATIBLE:-/sys/firmware/devicetree/base/compatible}
modprobe_command=${AURORA_MODPROBE:-modprobe}
pci_root=${AURORA_PCI_ROOT:-/sys/bus/pci}

has_firmware() {
  [ -s "$firmware_root/vendor/$1" ] || [ -s "$firmware_root/$1" ]
}

neo=false
if grep -aq 'apple,j700' "$compatible"; then
  neo=true
  if has_firmware apple/j700-aop-als-cal.bin; then
    "$modprobe_command" aop
  else
    echo 'Aurora: ALS calibration missing; Neo AOP probe deferred' >&2
  fi
  radio_ready=true
  for name in \
    mediatek/mt7932/IZUBA_WIFI_MT7932_patch_mcu_1_2_hdr.bin \
    mediatek/mt7932/IZUBA_W7932_2.bin \
    mediatek/mt7932/ppr.bin mediatek/mt7932/oca2.bin \
    mediatek/mt7932/wcal.bin mediatek/mt7932/config-original.bin \
    mediatek/MT7932B0_OS_TypeB_0.1.44.0_241001003711.bin \
    mediatek/MT7932B1_OS_TypeB_0.1.133.0_260128190103.bin \
    mediatek/MT7932_PTB_IzubaA_0.1.0.0_20251021141303.ptx \
    mediatek/j700-mt7932-btcal.bin mediatek/j700-mt7932-bdaddr.bin \
    mediatek/mt7932/policy/world-XZ.bin; do
    if ! has_firmware "$name"; then
      echo "Aurora: required firmware is missing: $name; peripheral probe deferred" >&2
      radio_ready=false
    fi
  done
fi

if "$neo" && ! has_firmware apple/tpmtfw-j700.bin; then
  echo 'Aurora: trackpad firmware missing; keyboard probe continues' >&2
fi
# The Neo and M2 and later MacBooks share this keyboard and trackpad driver.
# Its autoload waits for firmware, so load it on every Mac; a Mac without
# the device only loads the module.
"$modprobe_command" dockchannel-hid

if "$neo"; then
  if "$radio_ready"; then
    "$modprobe_command" mt7932-fullmac
    if [ "${AURORA_ADMIT_BLUETOOTH:-0}" = 1 ]; then
      "$modprobe_command" mt7932_bt_pcie
    fi
  fi
else
  # Preserve ordinary non-Neo admission even if vendor extraction failed.
  "$modprobe_command" aop
fi
# Bluetooth is deliberately admitted later by its existing gated PCI service,
# after root firmware extraction. It is not necessary to unlock the root disk.

# xhci-pci is built in, so it probes the Mac Studio's and Mac mini's ASMedia
# controller (back USB-A, front USB-C) long before this handoff. After a warm
# reboot the chip still runs the firmware it was given; after a cold boot it
# runs its ROM, the probe fails for lack of asmedia/asm2214a-apple.bin, and
# nothing retries it. Probe a controller that has no driver once that file
# is reachable; one that is already bound is left alone.
if has_firmware asmedia/asm2214a-apple.bin; then
  for device in "$pci_root"/devices/*; do
    [ -e "$device/vendor" ] || continue
    [ "$(cat "$device/vendor"):$(cat "$device/device")" = 0x1b21:0x2142 ] || continue
    [ -e "$device/driver" ] && continue
    name=${device##*/}
    if echo "$name" > "$pci_root/drivers/xhci_hcd/bind" 2>/dev/null; then
      echo "Aurora: ASMedia xHCI $name probed with vendor firmware" >&2
    else
      echo "Aurora: ASMedia xHCI $name probe failed" >&2
    fi
  done
fi
