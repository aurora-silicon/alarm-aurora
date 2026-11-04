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
| SELinux module `speakerguardd` (Fedora) | `speakerguardd_t`, with the program and `/run/speakerguardd` labelled |

Nothing is enabled. No graph loads the plugin, and the unit stays disabled.

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
