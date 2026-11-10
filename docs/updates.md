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

On a kernel, aura or U-Boot update (and after a kernel removal), the `95-m1n1-install.hook` pacman hook
that Aurora's `asahi-scripts` ships runs `update-m1n1` once after the transaction, and mkinitcpio
rebuilds the initramfs with the `asahi` and `aurora-vendor` hooks, which read this Mac's firmware from
the ESP at boot. `update-m1n1` composes aura, the newest installed kernel's device trees
(`/usr/lib/modules/<release>/dtbs`) and U-Boot into the ESP Stage 2. GRUB boots with the device tree
U-Boot hands it, so there is no `/boot/dtb` link to keep.

The updater is fedora-aurora's (aurora-silicon/fedora-aurora#193): `packages/asahi-scripts/bootchain.py`,
its test suite, the units and the preset are Fedora's `packages/update-m1n1` files byte for byte
(`tests/test_update_m1n1.py` checks their git blob ids). `bootchain_arch.py` gives that code Arch's
paths: flat `dtbs` directories, `/boot/vmlinuz-<pkgbase>` mapped to its package's kernel, no `/boot/dtb`,
and a `pacman -R` refusal. The kernel, aura and U-Boot packages depend on `aurora-stage2-trial`, which
only this `asahi-scripts` provides, so a stock asahi-alarm `asahi-scripts` cannot satisfy them.

### Device trees and the next boot

With aura Stage 1 1.0.0b4 or later (`aura,stage1-version` in the live device tree), the updater leaves
the working image in place. It writes `<target>.next` beside it, reads it back, checks every DTB header,
this Mac's root compatible and its display aliases, and records the attempt under
`/var/lib/aurora-stage2/attempts/<candidate sha256>`. It then writes the ESP root file `aura-try` with exactly
`armed\n<ESP-relative .next path>\n` (through `aura-try.tmp`, synced and renamed, then the ESP block
device is flushed). Stage 1 marks the try `spent` before loading the candidate, so any failure boots the
configured image next time. Older Stage 1 installations keep the direct atomic replacement and
`<target>.old` backup.

On the trial boot, `aurora-stage2-commit.service` (after `multi-user.target`) commits only if
`/proc/device-tree/chosen/aurora,trial` names the candidate, the candidate still matches its recorded
SHA-256, root is on NVMe, no DT-described device is still in deferred probe (debugfs must expose
`devices_deferred`), every enabled DCP has a bound driver, and no installed kernel needs an older DT ABI
generation. It saves `<target>.prev`, renames `.next` over the live image, flushes the ESP, verifies the
live SHA-256 and removes the marker; a failed write or read-back restores the previous image and keeps
the candidate. `aurora-stage2-guard.timer` reboots a trial that has not committed after twelve minutes,
covering a boot that feeds the hardware watchdog but never passes the checks.

After a fallback the commit service logs one line, keeps the working image and leaves `.next` and
`.next.json` for inspection; the recorded attempt means that exact candidate is never armed again
automatically. Any change to the Stage 2 inputs (kernel device trees, aura, U-Boot or `/etc/m1n1.conf`)
is a new candidate with its own trial, also on the same kernel release, and the previous candidate is
kept as `.failed-<sha256>`. A commit marks its record `committed`, so reverting to that exact image is
trialled again. Once a trial boot has committed, the rest of that boot is an ordinary boot and pacman
updates can stage the next candidate. Records named after a kernel release (asahi-scripts 20261023-4)
still block the candidate whose hash they contain. `journalctl -u aurora-stage2-commit -u aurora-stage2-guard` shows the outcome.
`asahi-scripts`' install script applies `90-aurora-stage2.preset` on install and on the upgrade that brings
the units (`systemctl --preset-mode=enable-only preset`), as Fedora's `%systemd_post` and `%triggerun` do.

### DT ABI generations

`linux-aurora` ships `/usr/lib/modules/<release>/dtb-abi` (`packages/linux-aurora/dtb-abi`, the same value
as fedora-aurora's `packages/kernel-aurora/dtb-abi`). Trees may change within a generation; only a change
older kernels cannot boot with needs a higher one. A kernel without the file counts as generation 1 (declaring it changed no device tree) and
a malformed value is refused. While any installed kernel (another kernel package, or a
`/boot/vmlinuz-<name>` GRUB still offers whose package is gone) has a lower generation than the newest
kernel's trees, `update-m1n1` refuses: Stage 2 stays as it is, and the message lists those kernels with a
`sudo pacman -R $(pacman -Qqo ...)` command. Nothing is removed automatically; removing them runs the hook
again and the new trees go in. A kernel that has no `dtbs` directory is refused the same way.

### Checking updater changes

`.github/workflows/stage2.yml` runs on changes to the updater, the boot-chain recipes and these tests.
One job runs the shared and Arch suites with dtc, plus shellcheck. The other builds `asahi-scripts` in
the signed ALARM root (its `check()` runs both suites) and runs `scripts/test-stage2-transactions` there:
real pacman transactions install synthetic kernels built with `linux-aurora`'s own install lines and
synthetic aura/U-Boot inputs, and check the first write, the `.old` backup, the generation refusal while
older kernels stay installed, the hook on removal and the input upgrade; the installed helper then runs
both suites against synthetic proc/sys trees for the trial, commit, fallback and guard states. No host
device or ESP is used. The workflow stays out of `packages.yml`, whose changes retire every earlier build
from publication.

### CTXR Stage 2 slots

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
`m1n1/boot-ctxr.bin` instead, with only this board's DTBs. A trial uses `boot-ctxr.bin.next` and a `.prev`
backup on commit; an older Stage 1 gets a direct replacement and `boot-ctxr.bin.old`. It never touches
`m1n1/boot.bin`, because the padded Stage 1 these Macs enroll chainloads `boot-ctxr.bin`. M1 to M3 Macs
only ever use `boot.bin`. A missing board tree or a candidate over aura's 16 MiB slot is refused before
either live image changes.

Image builds set `AURORA_DEVICE_TREE_COMPATIBLE=/nonexistent`, so `update-m1n1` writes `boot.bin` as before
whichever Mac builds the image. If the image's aura has the marker, `scripts/prepare-ctxr-stage2.py` then
adds `boot-ctxr.bin`, a copy of it, to the image's ESP, and `boot-ctxr-<board>.bin`, a copy of
`boot-<board>.bin`, for each Mach-O board. The installer picks the board's file over the combined one. The
script fails the image if any of them is over 16 MiB. Without the marker the image has no `boot-ctxr.bin`,
and the installer refuses it on Mach-O Macs, so no Mac gets a `boot-ctxr.bin` that updates don't refresh.

### Swapping a stock package for its Aurora build

`upower-aurora` and `networkmanager-aurora` conflict with Arch's `upower` and `networkmanager`, so moving
between them (either way) is a conflict removal and a fresh install, not an upgrade. pacman then saves an
edited `/etc/UPower/UPower.conf` or `/etc/NetworkManager/NetworkManager.conf` as `.pacsave` and installs
the default. Both packages depend on `aurora-keep-config`, whose PostTransaction hook puts the edited file
back when the new package's copy is unmodified and the `.pacsave` was made in that transaction; the new
default is left as `.pacnew`, as after an in-place upgrade (and as dnf does on Fedora). An older
`.pacsave` is left alone. `scripts/test-upower-upgrade` and `scripts/test-networkmanager-upgrade` swap,
roll back and check the edit stays active; `tests/test_keep_config.py` fails when another package gains
backup files and a conflict without being listed.

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
