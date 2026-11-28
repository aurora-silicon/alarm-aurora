# speakerguardd v2

speakerguardd v2 is the only speaker protection on every Mac, and the only
program that takes the kernel's speaker interlock. The Asahi stack is gone:
aurora-audio 4.1.aurora2-19 depends on speakerguardd-v2 and
aurora-speaker-upgrade, replaces the speakersafetyd and
speakersafetyd-aurora-profiles builds this repository shipped and
speakerguardd 0.1, and installs no Asahi speaker graph. `pacman -Syu` removes
the old packages in the same transaction. The speakersafetyd replaces are
versioned and there is no conflict, so a speakersafetyd that a user later
installs and selects on purpose stays installed across upgrades.

`aurora-speaker-upgrade` moves a Mac's speakers to v2 with that Mac's own
tuning:

```sh
sudo aurora-speaker-upgrade --check    # dry run: collect, compile and self-check; nothing stored or switched
sudo aurora-speaker-upgrade            # switches only if this Mac's self-check passes
sudo aurora-speaker-upgrade status
```

The `aurora-speaker-upgrade` boot unit, enabled by preset, runs the same
switch at boot without a prompt, and moves only a speaker whose protected
playback rows are on record; a refusal is recorded and not retried until the
kernel, speakerguardd v2 or the tool changes. A Mac that v2 does not qualify
keeps its speakers at the kernel's floor by default.

## Optional user opt-out (`aurora-speaker-stack`)

Users who explicitly choose to run `speakersafetyd` instead of speakerguardd v2
can opt out with one command:

```sh
sudo aurora-speaker-stack select speakersafetyd
```

This checks kernel support and installs `speakersafetyd` first, masks the v2
and upgrade units, switches the kernel interlock, records the choice in
`/etc/aurora/speaker-stack.conf`, installs a root `ExecStartPre` drop-in on
`speakersafetyd.service` (`aurora-speaker-stack interlock-apply`) so the
per-bind kernel interlock is armed on every boot, and starts
`speakersafetyd.service`. Later `pacman -Syu` upgrades read
`/etc/aurora/speaker-stack.conf` and preserve the opt-out.

Because `aurora-audio` no longer installs the Asahi speaker DSP graphs, speaker
FIRs, or WirePlumber raw speaker volume lock, opting into stock
`speakersafetyd` runs without those Asahi speaker profiles unless supplied
separately.

To inspect the current state or return to speakerguardd v2:

```sh
aurora-speaker-stack status
sudo aurora-speaker-stack select sgv2
```

See `man 8 aurora-speaker-stack`.
