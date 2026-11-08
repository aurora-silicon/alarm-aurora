# speakerguardd-v2

speakerguardd 1.0 (`1.0.0-alpha`), the in-graph speaker protection from the
`v2` branch of aurora-silicon/speakerguardd. It is a new program, not an
upgrade of the 0.1 daemon, so it is packaged under its own name and installs
beside the older daemons, speakerguardd 0.1 and speakersafetyd.

## Install everywhere, gate by board

Every Mac carries both stacks: aurora-platform and aurora-audio require
speakerguardd-v2 beside the older daemons. Nothing replaces or obsoletes
anything. At every boot the fleet gate (`speakerguardd-gate`, the
`ExecCondition=` of every unit of both stacks) starts exactly one of them:

- **v2** on a board whose protection unit is at parity and that passed an
  audible run on the shipped tree, when the kernel has the v2 interface (the
  "Speaker Protection" control);
- **the older daemons** everywhere else, as long as the kernel has no v2
  interface. On a v2 kernel they have nothing to own, so a board outside
  the gate then runs neither, and the kernel holds its speakers at its
  floor.

The kernel is the switch. Every fleet kernel today lacks the v2 interface,
so every Mac stays on the older daemons. The kernel that brings the
interface moves every gated Mac at once (option A: it lands once lsm2 and
atsp reach parity). The gate's data is speakerguardd's own
(`/usr/share/speakerguardd/gate.json`: the units at parity and the qualified
boards per unit), so it is the same in every distribution and never edited
here. Nothing about a board is entered by hand: the protection unit is the
one the Mac's own tuning names, and the channel map, card, amplifiers and
sense lanes are derived from its device tree and tuning at run time
(`wiring.py`), so a new Mac needs no table entry. The cutover adds lsm2 and atsp to `units_at_parity` and drops the
per-board run, which makes the gate every board with a parity unit.

`speakerguardd-gate explain` (beside the supervisor) prints the decision.
For qualification itself, an administrator can name an unqualified board in
`/etc/speakerguardd/allow-unqualified`.

## No manual steps

On a gated board, `speakerguardd-v2-provision.service` runs before the
self-check and the supervisor, which both require it:

- it compiles the installer's tuning bundle (`/lib/firmware/vendor/apple/audio-tuning`,
  or the ESP's vendorfw archive) into `/var/lib/speakerguardd/params.bin`;
- it binds the blob to the board, kernel, bundle, macOS build and compiler,
  and recompiles when one changes;
- it resolves the seat user by name, never by a fixed uid;
- it writes `/etc/speakerguardd/speakerguardd.conf`.

After the self-check passes, the machine's PipeWire and WirePlumber files are
generated into `/run/speakerguardd-graph`. The user unit
`speakerguardd-v2-graph.service` links them for the seat user only.
`speakerguardd-v2-seat.path` provisions again when another user takes
seat0. Any failure fails closed: the supervisor does not start, the kernel's
floor holds, and the journal says why.

Overrides, all optional, go in `/etc/speakerguardd/provision.conf`:
`SGV2_SEAT_USER=<name>` and `SGV2_BUNDLE=<path>`.

## What it installs

| Path | What |
|---|---|
| `speakerguardd-v2/` under `/usr/libexec` (Fedora), `/usr/lib` (Arch) or `libexec` (Nix) | The supervisor, `speakerguardd-provision`, `speakerguardd-gate`, `speakerguardd-selfcheck`, `speakerguardd-session` |
| `speakerguardd-v2{,-provision,-selfcheck,-seat}.service`, `speakerguardd-v2-seat.path` | The upstream units, renamed and enabled, each one gated |
| `speakerguardd-v2-session.service`, `speakerguardd-v2-graph.service` (user units) | The session helper, and the seat user's graph links |
| `60-speakerguardd-v2-gate.conf` in `speakersafetyd.service.d` and `speakerguardd.service.d` | The gate on the older daemons' units |
| `sgv2.lv2` in the distribution's LV2 directory | The protection unit for the PipeWire filter-chain |
| `aurora-speaker-tuning` | Reader, validator and compiler for the Mac's own tuning bundle |
| `/usr/share/speakerguardd/` | `gate.json` and the reference graphs |
| SELinux module `speakerguardd` (Fedora) | Upstream's policy: `speakerguardd_t`, with the program, `/run/speakerguardd` and `/var/lib/speakerguardd` labelled |

## Rollback

| | Back to the older daemons |
|---|---|
| Any distribution | Boot a kernel without the v2 interface. The gate starts the older daemons again, with no package change |
| One Mac, without a kernel change | `systemctl disable speakerguardd-v2.service`. On a v2 kernel this leaves the speakers at the kernel's floor, because the older daemons cannot drive that kernel |
| NixOS | `aurora.speakerguardd.v2.enable = false;` removes v2 and its gate, and the older daemons run as before |

The older daemons stay installed throughout, so the rollback needs no
download.

## Source

The pin is a commit on the `v2` branch. Bump it as the lanes merge there.
`aurora-speaker-tuning` is based on aurora-audio-dsp by saku (MIT); its
notice is installed with the licence.
