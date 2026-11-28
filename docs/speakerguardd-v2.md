# speakerguardd v2

`speakerguardd-v2` is the default speaker protection and voicing stack on all
Aurora Alarm installations (new installs and upgraded existing installs).
Legacy Asahi speaker DSP graphs, `speakerguardd` 0.1, and
`speakersafetyd-aurora-profiles` are retired on upgrade, and
`aurora-speaker-upgrade.service` migrates existing Macs at boot using the
pinned macOS restore image's tuning and the Mac's own calibration:

```sh
sudo aurora-speaker-upgrade --check    # dry run: collect, compile and self-check; nothing stored or switched
sudo aurora-speaker-upgrade            # switches only if this Mac's self-check passes
sudo aurora-speaker-upgrade status
```

## User opt-out (`aurora-speaker-stack`)

Users who explicitly want `speakersafetyd` instead of `speakerguardd` v2 can
switch with one command:

```sh
sudo aurora-speaker-stack select speakersafetyd
```

This records the selection in `/etc/aurora/speaker-stack.conf`, masks the v2
and upgrade units, installs `speakersafetyd`, hands over the kernel speaker
interlock where the running kernel supports the dual interface, and starts
`speakersafetyd.service`. Later package upgrades respect
`/etc/aurora/speaker-stack.conf` and keep the user's choice.

To inspect the current selection or switch back to `speakerguardd` v2:

```sh
aurora-speaker-stack status
sudo aurora-speaker-stack select sgv2
```

See `man 8 aurora-speaker-stack` for details.
