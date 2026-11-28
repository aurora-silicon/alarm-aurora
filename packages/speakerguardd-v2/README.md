# speakerguardd-v2

speakerguardd 1.0 (`1.0.0-alpha`), the in-graph speaker protection from
aurora-silicon/speakerguardd. It is the default speaker protection and voicing
stack on every Aurora installation.

## Default stack and automatic migration

`aurora-audio` requires `speakerguardd-v2` and `aurora-speaker-upgrade`,
installs no Asahi speaker DSP graphs, and retires the legacy Aurora speaker
packages (`speakersafetyd-aurora-profiles`, `speakerguardd` 0.1, and Aurora's
legacy `speakersafetyd` build) on upgrade.

At every boot `speakerguardd-gate` (the `ExecCondition=` of the v2 units)
starts v2 when this Mac's tuning compiled, passed the macOS parity attestation
and wiring self-check, and its speaker has protected playback rows on record.
Where v2 does not run, the kernel holds the speakers at its safe floor.

`speakerguardd-gate explain` prints the decision. `aurora-speaker-upgrade` is
enabled by preset and fetches the Mac's tuning from the pinned macOS restore
image on boot.

## No manual steps

`speakerguardd-v2-provision.service` runs before the self-check and the
supervisor, which both require it:

- it compiles the tuning bundle into `/var/lib/speakerguardd/params.bin`;
- it binds the blob to the board, kernel, bundle, macOS build and compiler,
  and recompiles when one changes;
- it resolves the seat user by name, never by a fixed uid;
- it writes `/etc/speakerguardd/speakerguardd.conf`.

After the self-check passes, the machine's PipeWire and WirePlumber files are
generated into `/run/speakerguardd-graph`. The user unit
`speakerguardd-v2-graph.service` links them for the seat user only.
`speakerguardd-v2-seat.path` provisions again when another user takes seat0.
Any failure fails closed: the supervisor does not start, the kernel's floor
holds, and the journal says why.

Overrides, all optional, go in `/etc/speakerguardd/provision.conf`:
`SGV2_SEAT_USER=<name>` and `SGV2_BUNDLE=<path>`.

## User opt-out (`aurora-speaker-stack`)

Users who explicitly want `speakersafetyd` instead of `speakerguardd-v2` can
switch with one command (see `man 8 aurora-speaker-stack`):

```sh
sudo aurora-speaker-stack select speakersafetyd
```

The choice is recorded in `/etc/aurora/speaker-stack.conf` and preserved across
later package upgrades. To return to `speakerguardd-v2`:

```sh
sudo aurora-speaker-stack select sgv2
```

## Source

The pin is a commit on speakerguardd's `main` branch. `aurora-speaker-tuning`
is based on aurora-audio-dsp by saku (MIT); its notice is installed with the
licence.
