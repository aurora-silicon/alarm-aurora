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

The kernel prepares the pinned, corrected bindgen at
`tools/aurora-bindgen/build/bin/bindgen` before configuration. Kbuild selects it
automatically, including out-of-tree builds. No `BINDGEN=` make argument or
export is required. Fedora and ALARM build and compile-test the generator from
the kernel's checked source manifest; Nix uses the matching patched derivation
and links its executable into that entry point. ALARM retains its exact
compiler-lint adapter there. Every emitted layout assertion remains mandatory.
Stock bindgen 0.73.2 loses alignment on empty C records such as
`sched_statistics` with `SCHEDSTATS=n`; enabling statistics is not the fix.

Cons3 also pins FAT's default codepage 437 and ASCII charset, with both
converters built into the kernel. Asahi's early dracut vendor-firmware hook
mounts the ESP without charset options; it must not depend on a charset module
missing from initramfs. XZ and Zstd firmware loading are enabled for compressed
distribution firmware files. The shared fragment carries these requirements.

The retained Apple-only policy bases also resolve the shared DAX requirements
with memory hotplug/hot-remove enabled and keep socket diagnostics and the
Apple HID core built in with their built-in consumers. They explicitly exclude
ACPI I2C HID and Qualcomm on-SoC QMI audio offload, which are internal
transports absent on Apple DT machines; ordinary OF HID and USB audio remain
enabled. Validation applies the ordered shared/common policy without ignoring
unmet requests. No display handoff or device admission gate is relaxed.
