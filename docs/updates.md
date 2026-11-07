# Updates: from a source branch to installed Macs

The cross-distribution overview, threat model and key procedures are in
[aurora-distributions/docs/updates.md](https://github.com/aurora-silicon/aurora-distributions/blob/main/docs/updates.md).
This page is the ALARM runbook.

## Installed systems

`scripts/build-image` adds `[aurora]` before `[core]` in `/etc/pacman.conf` with
`SigLevel = Required DatabaseRequired`, builds from the immutable snapshot release, then points the
section at `https://aurorasilicon.org/alarm-aurora/<channel>/aarch64`. `<channel>` is the `images.yml`
input; the default, `testing`, is today's URL. The Aurora key is locally signed in the image and shipped
by `aurora-keyring`, whose install script imports added keys on every upgrade.

On a kernel, aura or U-Boot update, asahi-scripts' pacman hook runs `update-m1n1`, which writes aura,
every DTB of the newest `*-ARCH` kernel and U-Boot into the ESP Stage 2 (keeping `boot.bin.old`), and
mkinitcpio rebuilds the initramfs with the `asahi` and `aurora-vendor` hooks, which read this Mac's
firmware from the ESP at boot.

The aura package ships `/usr/share/aura/monitor-free` once its pinned source has no monitor. The recipe
declares that in `_monitor_free`, and `prepare()` refuses a source that disagrees (`src/ctxr_exec.c`, or no
`src/monitor.c`). aura 1.0.0b7 is the first pin without the monitor (aura#77), so `_monitor_free` is 1.

Such an aura moves the kernel into the CTXR window, which only a kernel built with
`CONFIG_ARM64_CTXR_EXECMEM` keeps its code inside. With `_monitor_free=1`, aura depends on
`aurora-ctxr-execmem`, which `linux-aurora` provides when its `_ctxr_execmem=1`. Its `prepare()` checks
that flag against the resolved configuration, so it can be set only with a kernel pin that has
aurora-silicon/linux#985. `tests/test_update_m1n1.py` fails if `_monitor_free` is set without it.
Every kernel pin since 4731456 has it, and `packages/linux-aurora/config` turns it on, so `_ctxr_execmem` is 1.

With the marker, a Mac that boots a Mach-O Stage 1 (`/proc/device-tree/compatible` names one of the chips
in the installer's `AuraStage1Format.usesMachO`: T8130 and later, T6040 and later) gets
`m1n1/boot-ctxr.bin` instead, keeping `boot-ctxr.bin.old`, with only this board's DTBs. It never touches
`m1n1/boot.bin`, because the padded Stage 1 these Macs enroll chainloads `boot-ctxr.bin`. M1 to M3 Macs
only ever use `boot.bin`.

Image builds set `AURORA_DEVICE_TREE_COMPATIBLE=/nonexistent`, so `update-m1n1` writes `boot.bin` as before
whichever Mac builds the image. If the image's aura has the marker, `scripts/prepare-ctxr-stage2.py` then
adds `boot-ctxr.bin`, a copy of it, to the image's ESP, and `boot-ctxr-<board>.bin`, a copy of
`boot-<board>.bin`, for each Mach-O board. The installer picks the board's file over the combined one. The
script fails the image if any of them is over 16 MiB. Without the marker the image has no `boot-ctxr.bin`,
and the installer refuses it on Mach-O Macs, so no Mac gets a `boot-ctxr.bin` that updates don't refresh.

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| `track-sources.yml` | every 30 min (`TRACK_SOURCES`), manual | Moves `aura`, `kernel-aurora`, `mesa-aurora` (see `tracking.json`) to their branch tips in one PR on `auto/track-sources`, dispatches `packages.yml` on it, merges when green (`AUTO_MERGE_SOURCES`), mirrors pinned archives to the `source-cache` release |
| `packages.yml` | push, PR, manual | Native builds; attests every package |
| `publish.yml` | after a main build and every 6 h (`AUTO_PUBLISH_TESTING`), manual | Resolves the newest qualifying build of every recipe (no run list), carries unchanged recipes from the newest snapshot, refuses version regressions, signs in `testing-signing`, releases `testing-YYYYMMDD.N` with an attestation; deploys to testing if `AUTO_DEPLOY_TESTING` or `deploy=yes` |
| `deploy-snapshot.yml` | manual or called | Serves a snapshot on `testing` or `stable`; assembles the whole site (both channels), verifies every signature and attestation, compares with the live database, records `channels.json` on the `channels` branch |
| `promote.yml` | manual | One click: `stable` gets what `testing` serves, after a `stable-promotion` reviewer approves |
| `images.yml` | manual or after a testing deploy (`AUTO_IMAGES`) | Builds an image from a snapshot; `channel` sets the feed it follows |
| `payload-after-images.yml` | after an image build (`AUTO_PAYLOADS`) | Signed payload release; catalog adoption stays manual |

## Common tasks

```sh
# Publish whatever main has built (dry run first: throwaway key, no release)
gh workflow run publish.yml -R aurora-silicon/alarm-aurora --ref main -f dry-run=true
gh workflow run publish.yml -R aurora-silicon/alarm-aurora --ref main -f deploy=no

# Serve a snapshot to testing users, then promote it
gh workflow run deploy-snapshot.yml -R aurora-silicon/alarm-aurora --ref main -f channel=testing -f release-tag=testing-YYYYMMDD.N
gh workflow run promote.yml -R aurora-silicon/alarm-aurora --ref main

# Roll testing back (needs a stable-promotion approval)
gh workflow run deploy-snapshot.yml -R aurora-silicon/alarm-aurora --ref main -f channel=testing \
  -f release-tag=<older tag> -f allow-downgrade=true

# See what a source update would look like, without touching anything
gh workflow run track-sources.yml -R aurora-silicon/alarm-aurora --ref main -f dry-run=true
```

The old manual inputs still work: `publish.yml -f build-run='<ids>' -f release-tag=<tag>`.

## Notes

- Changing `packages.yml`, `scripts/ci-build-package`, `scripts/fetch-base.py`, `images/base.json` or the
  build-system key makes every earlier build ineligible. The next publication then requests a full main
  build before it can complete.
- A tracker PR is left alone once anyone but the bot pushes to it.
- `channels.json` on the `channels` branch is the record of what each channel serves; the deployed site
  carries a copy.
