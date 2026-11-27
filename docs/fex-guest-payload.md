# Checking a finished FEX Mesa package

Run this **after packaging**, against an extracted `mesa-aurora-fex-guest`
archive, not `srcdir/layer` or the build host's libraries. `check()` runs before
`package()` copies the bundled libraries and provider into their final locations;
a passing build check cannot verify those copies.

From the repository root, with a trusted package archive:

```sh
payload=$(mktemp -d)
bsdtar -xf out/packages/mesa-aurora-fex-guest-VERSION-any.pkg.tar.zst -C "$payload"
python3 scripts/check-fex-guest-payload.py --package-root "$payload"
```

`--package-root` is the extraction directory containing
`usr/share/guestos/aurora-fex-mesa-layer`. It must contain only the finished
package, not a guest root with dependencies that could conceal missing files.
For an already extracted layer (including a read-only check of the installed
layer), use the explicitly different input:

```sh
python3 scripts/check-fex-guest-payload.py \
  --layer-root /usr/share/guestos/aurora-fex-mesa-layer
```

The checker uses Python's standard library on either AArch64 or x86_64. It reads
JSON and ELF headers; it never installs the package, runs package scripts or
foreign binaries, mounts anything, or changes the input. Keep the input tree
quiescent during the check. Success prints `FEX guest payload: OK (...)` and exits
zero. Failure prints paths and expected layouts/architectures to stderr and exits
one (invalid CLI arguments exit two).

The contract is the Arch guest layout proposed in
[#344](https://github.com/aurora-silicon/alarm-aurora/pull/344), addressing the
packaging report in [#335](https://github.com/aurora-silicon/alarm-aurora/issues/335):

- The final `graphics_provider.json` selects this layer (`root: "./"`) and maps
  x86_64/i386 library, DRI and gconv paths to `/usr/lib` and `/usr/lib32`.
  The gconv directories belong to the underlying guest root and need not ship
  in the Mesa layer.
- Each final Asahi Vulkan ICD selects `/usr/lib/libvulkan_asahi.so` (x86_64) or
  `/usr/lib32/libvulkan_asahi.so` (i686), with its target present in this payload.
- Both architectures have `libdisplay-info.so.3`, versioned `libgallium-*.so`,
  EGL, GLX, GBM, its DRI backend, and the Asahi, Zink and software DRI libraries.
  Required files have little-endian ELF shared-object headers of the correct
  class and machine (`EM_X86_64` or `EM_386`).
- A real `usr/lib64` is rejected. A symlink to packaged `usr/lib` is allowed.
  File and directory symlinks resolve within the layer: absolute links are
  interpreted relative to the **guest** root, never the host `/`. Dangling links,
  loops and relative paths escaping the layer fail. The package's layer location
  itself cannot be redirected to a source/build directory.

This command complements #344's layout fix and its author's stand-in-root `ldd`
checks. It does not implement that fix. While main still packages the old Fedora
layout, validating its finished package is expected to fail. For that reason the
post-package invocation is explicit rather than an unconditional step in
`scripts/ci-build-fex-guest`. Once the corrected layout lands, builders can run
the extraction and check above after that script finishes, before publishing
the archive. The regression tests already run in the existing package workflow's
`unittest discover` step, without building Mesa:

```sh
python3 -m unittest discover -s tests -p test_fex_guest_payload.py -v
```

The fixtures use synthetic ELF headers and exercise final trees, including a
valid build tree next to a broken finished package. Passing proves the listed
packaging checks only: it does not establish ELF loadability, full guest
dependency closure, provider behavior inside pressure-vessel, FEX/Steam operation
or successful rendering of a game. Real corrected-package validation and runtime
testing remain separate requirements.
