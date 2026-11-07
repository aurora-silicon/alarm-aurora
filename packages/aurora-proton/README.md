# Aurora Proton for native ARM64 Steam

`aurora-proton` ships the rebuilt native ARM64 `ntdll.so`, the attributed
LGPL SVE/SME signal-record guard, licences and pinned GE-Proton11-9 metadata.
It rebuilds only that library after GE's complete Wine-Staging and Wine patch
preparation. The build refuses exported-symbol changes, additional NEEDED
libraries or a GLIBC requirement above GE's original library, and retains
its original RPATH/RUNPATH. The seven source hashes and exact GE, Wine and
Wine-Staging commits are recorded in `sources.json` and the installed manifest.

The package is small: GE's full runtime is downloaded on first use, not included
in the pacman archive. Before starting Steam or Play, the launcher verifies the
pinned archive SHA256, extracts safely in a private staging directory, replaces
only `ntdll.so` and the compatibility-tool identifier, and atomically publishes
a writable revision. GE's other release files and bundled licences remain.
Preparation never writes into the system package tree.

The system manifest is under
`/usr/share/aurora-proton/Aurora-Proton11-9-<pkgrel>.alarm`, selected by `current`.
The writable tool lives under
`${XDG_DATA_HOME:-$HOME/.local/share}/aurora-proton/<revision>`; the verified
archive is cached under `${XDG_CACHE_HOME:-$HOME/.cache}/aurora-proton`.
Allow about 620 MiB for the download plus roughly 2 GiB for the writable tool.
Preparation is serialized between Steam and Play. Failed downloads/extractions
never publish a partial tool, and the next launch can retry. Older revisions
and personal `user_settings.py` are retained; unmanaged targets are not replaced.

Nonempty `STEAM_EXTRA_COMPAT_TOOLS_PATHS` takes precedence.
`AURORA_STEAM_PROTON=0` disables default download/preparation and path injection
without removing custom tools. For offline preparation, set
`AURORA_PROTON_ARCHIVE=/path/to/GE-Proton11-9-aarch64.tar.gz`; its checksum must
still match the installed manifest. No URL or checksum override is accepted.

Aurora Play discovers native compatibility tools by their ARM64 Wine ELF,
including custom GE tools, and changes only settings files it owns. Stats is
available only with a native MangoHud Vulkan layer; MangoHud is optional on
ALARM and is not bundled here. Personal settings remain untouched.

Use `/usr/bin/steam` and `/usr/bin/aurora-play`. A manual upstream installation
may have older overrides in `~/.local/bin` or a desktop file in
`~/.local/share/applications`; review those if they shadow packaged launchers,
preserving personal modifications. Normal package installations already use
the private per-user client prefix and need no launcher migration.

The build helpers derive from `nixos-aurora/pkgs/proton`; packaging follows this
repository's MIT licence. The Wine guard retains Ryan Murray's attribution
and LGPL licence. Building and ABI checks do not qualify games or hardware.
