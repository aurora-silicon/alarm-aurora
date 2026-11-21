#!/bin/sh
# SPDX-License-Identifier: MIT
# Never reset a running device. Repeated modprobe of a loaded module is inert.
set -eu
firmware_root=${AURORA_FIRMWARE_ROOT:-/lib/firmware}
dt=${AURORA_DT_ROOT:-/sys/firmware/devicetree/base}
modprobe_command=${AURORA_MODPROBE:-modprobe}
pci_root=${AURORA_PCI_ROOT:-/sys/bus/pci}

has_firmware() {
  [ -s "$firmware_root/vendor/$1" ] || [ -s "$firmware_root/$1" ]
}

# Print every device-tree node whose compatible list has the entry $1.
dt_nodes() {
  find "$dt" -name compatible -type f -exec grep -lzxF -e "$1" {} + |
    while read -r path; do echo "${path%/compatible}"; done
}

# Per-device firmware is named after the board: the root's first compatible.
board=$(tr '\000' '\n' < "$dt/compatible" | head -n 1)
board=${board#apple,}

# An AOP ambient light sensor whose node names a calibration file reads it
# while aop probes, and aop does not probe again. Hold aop back until the
# file is in place.
aop_ready=true
for node in $(dt_nodes apple,aop-als); do
  [ -r "$node/firmware-name" ] || continue
  calibration=$(tr -d '\000' < "$node/firmware-name")
  if ! has_firmware "$calibration"; then
    echo "Aurora: ALS calibration $calibration missing; AOP probe deferred" >&2
    aop_ready=false
  fi
done

# A MediaTek MT7932 radio (Wi-Fi and Bluetooth, the PCI function behind the
# wifi0 alias) is held back from autoload: its drivers read these files
# while probing and do not probe again.
radio_ready=false
wifi=
if [ -r "$dt/aliases/wifi0" ]; then
  wifi=$(tr -d '\000' < "$dt/aliases/wifi0")
fi
if [ -n "$wifi" ] && tr '\000' '\n' < "$dt$wifi/compatible" | grep -qxF pci14c3,7932; then
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

# A built-in trackpad on the keyboard's DockChannel reads
# apple/tpmtfw-<board>.bin while it probes.
for node in $(dt_nodes apple,dockchannel-hid); do
  if [ -d "$node/multi-touch" ] && ! has_firmware "apple/tpmtfw-$board.bin"; then
    echo 'Aurora: trackpad firmware missing; keyboard probe continues' >&2
  fi
done
# The Neo and M2 and later MacBooks share this keyboard and trackpad driver.
# Its autoload waits for firmware, so load it on every Mac; a Mac without
# the device only loads the module.
"$modprobe_command" dockchannel-hid

if "$aop_ready"; then
  "$modprobe_command" aop
fi
if "$radio_ready"; then
  "$modprobe_command" mt7932-fullmac
  if [ "${AURORA_ADMIT_BLUETOOTH:-0}" = 1 ]; then
    "$modprobe_command" mt7932_bt_pcie
  fi
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
