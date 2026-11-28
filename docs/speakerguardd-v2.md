# speakerguardd v2

speakerguardd v2 is the only speaker protection on every Mac, and the only
program that takes the kernel's speaker interlock. The Asahi stack is gone:
aurora-audio 4.1.aurora2-19 depends on speakerguardd-v2 and
aurora-speaker-upgrade, replaces and conflicts with speakersafetyd,
speakersafetyd-aurora-profiles and speakerguardd 0.1, and installs no Asahi
speaker graph. `pacman -Syu` removes the old packages in the same
transaction.

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
keeps its speakers at the kernel's floor: there is no other speaker stack to
fall back to.
