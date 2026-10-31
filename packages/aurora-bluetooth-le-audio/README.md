# Aurora Bluetooth LE Audio defaults

This removable package enables experimental BlueZ LE Audio profiles and only
ISO sockets, alongside A2DP and HFP. It does not pair devices or start playback.
It does not implement missing controller transport support: BCM4388 PCIe ISO
streaming is still absent from the public shared kernel driver.

BlueZ still reads /etc/bluetooth/main.conf. Set BLUEZ_LE_AUDIO_OPTIONS="" in
/etc/bluetooth/le-audio.conf to return to main.conf alone. Package upgrades
preserve edits. The command-line kernel feature list takes precedence over
KernelExperimental in main.conf. An explicit Experimental=false in main.conf
can disable the experimental profiles.

To remove the BlueZ defaults, remove this package. Upstream WirePlumber roles
are preserved; this package does not install a role override. It is not
required by the protected platform or audio metapackage. After an authorized
install, configuration change, or removal, apply deliberately:

    sudo systemctl daemon-reload
    sudo systemctl restart bluetooth.service
    systemctl --user restart wireplumber.service
    bluetoothctl show

Bluetooth restarts can disconnect keyboards and mice. Use a local keyboard or
another connection. Keep output muted; no pairing or playback is needed to see
Published Audio Capabilities (1850) and Audio Stream Control (184e) UUIDs.

WirePlumber roles can be replaced in a later system or user config fragment:

    monitor.bluez.properties = {
      bluez5.roles = [ a2dp_sink a2dp_source hfp_hf hfp_ag ]
    }

The full source audit, three-distro parity table, installation, opt-out and
rollback instructions are in docs/bluetooth-le-audio.md in the distro repo.
