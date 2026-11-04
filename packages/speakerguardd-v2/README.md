# speakerguardd-v2

speakerguardd 1.0 (`1.0.0-alpha`), the in-graph speaker protection from the
`v2` branch of aurora-silicon/speakerguardd. It is a new program, not an
upgrade of the 0.1 daemon, so it is packaged under its own name and installs
beside what machines run today.

## What it installs

| Path | What |
|---|---|
| `speakerguardd-v2/speakerguardd` under `/usr/libexec` (Fedora) or `/usr/lib` (Arch) | The supervisor (`sgv2-supervisor`) |
| `speakerguardd-v2.service` | The upstream unit, renamed. No `OnFailure=` and no other daemon in it |
| `sgv2.lv2` in the distribution's LV2 directory | The protection unit (`sgv2-core` behind the `sgv2-lv2` host) for the PipeWire filter-chain |
| `aurora-speaker-tuning` | Reader and validator for the Mac's own tuning bundle |
| `speakerguardd-v2-selfcheck.service` | The first-boot wiring self-check: it derives the speaker wiring from the device tree and the tuning, proves it with zero-sample streams only, and binds the result to board, kernel and blob. The supervisor `Requires=` it |
| `speakerguardd-v2-session.service` (user unit) | The session helper: it links the amps into the graph only while the kernel grants protection |
| `speakerguardd-selfcheck`, `speakerguardd-session`, `wiring.py`, `speakerguardd-v2-gate` beside the supervisor | The programs the units run |
| `/usr/share/speakerguardd/` | `machines.json` and the per-machine PipeWire and WirePlumber graphs, as data only |
| SELinux module `speakerguardd` (Fedora) | Upstream's policy (`packaging/selinux`): `speakerguardd_t`, with the program, `/run/speakerguardd` and `/var/lib/speakerguardd` labelled |

Nothing is enabled. No graph loads the plugin, and no unit is enabled.

## The board gate

The opt-in adds `ExecCondition=speakerguardd-v2-gate` to all three units. A
unit starts only on a board that passed the 1.0 qualification, a passing
audible hardware run on the shipped tree. It is J616s only for now, and the
list is the same file in every distribution. On any other board the units do
not start, the journal says why, and the kernel's safe level holds. Nothing
changes silently. For qualification itself, an administrator can name the
board in `/etc/speakerguardd/allow-unqualified`.

Still to provision by hand, as `docs/NEW-PLATFORM.md` describes:
- `/etc/speakerguardd/speakerguardd.conf` (from `speakerguardd.conf.example`);
- the parameter blob compiled from the installer's tuning bundle;
- the machine's graph from `/usr/share/speakerguardd`.

These become automatic before 1.0 is the default.

## The opt-in

The switch is a separate, clearly named package or option:

| Distribution | Opt-in |
|---|---|
| Fedora | `dnf install --allowerasing speakerguardd-v2-replace-legacy` |
| Arch Linux ARM | `pacman -S speakerguardd-v2-replace-legacy` (answer yes to remove the conflicting packages) |
| NixOS | `aurora.speakerguardd.v2.replaceLegacy = true;` |

It conflicts with speakerguardd 0.1 and speakersafetyd and enables
`speakerguardd-v2.service`, and the audio packages that need a speaker
protection stay installed. It never uses `Obsoletes:` or `replaces=`: those
make an ordinary upgrade swap the daemon without being asked, and a machine
moves only after it passes the 1.0 qualification (parity with macOS, fault
injection, zero SELinux denials in enforcing mode, a clean boot log, and
loudness and clarity against macOS).

- Fedora: the opt-in provides neither old name, because dnf would then pick
  it for a plain `Requires: speakersafetyd` on a fresh install.
  aurora-audio and aurora-platform require `(speakersafetyd or
  speakerguardd-v2-replace-legacy)` (and the same for speakerguardd) and
  recommend the real daemons, which dnf then prefers.
- Arch Linux ARM: the opt-in provides both names. pacman takes a package by
  its exact name before any provider, so nothing pulls it in unasked.

To go back, install the older daemons again, which removes the opt-in and
disables the unit: `dnf install --allowerasing speakerguardd speakersafetyd`
or `pacman -S speakerguardd speakersafetyd`, or set `replaceLegacy = false`
on NixOS.

## Source

The pin is a commit on the `v2` branch. Bump it as the lanes merge there.
`aurora-speaker-tuning` is based on aurora-audio-dsp by saku (MIT); its
notice is installed with the licence.
