# AVD firmware changelog

## 2026-11-01: 6062e851

Update the pinned MIT-licensed firmware to
`6062e8516c0a751bc8e50f5d604a17395923189f` for per-image codec VP pools and
multi-VP decoding. Ship all eight images, including the new `avd-fw-v3-t2.bin`.

Keep upstream Meson defaults and the clang 22 toolchain requirements. The
package check prints and enforces all eight expected SHA-256 hashes, image
sizes, ARM ELF headers and reset vectors. Host build flags stay cleared or
disabled. Source archive SHA-256:
`49a631c8ba0c87bac187376bc642acaad1f62791dde6ed285fbc2bad21d60cf0`.

## 2026-11-01: 66c3911b

Update the pinned MIT-licensed firmware to
`66c3911bbaebdca90a179aa74c7addde9b2963ce` for queue ABI 2 with the SRAM
ring and VP DONE events. Install all seven images, including `avd-fw-v5-t2.bin`
for T6040, alongside v5-t1 for fallback.

Use upstream Meson defaults (`optimization=2`, `debug=false`) with host build
flags cleared or disabled. The package check prints and verifies all seven
clang 22 image SHA-256 hashes as well as sizes, ARM ELF headers and reset
vectors. A different toolchain must pass the same checks; mismatches fail the
build and require investigation rather than replacing the expected hashes.

Select ALARM's versioned clang22, llvm22 and lld22 packages, using
`/usr/lib/llvm22/bin` for the build. Rolling clang 23.1.4 produces a different
v2-t0 hash (`5d6b8b071975fc645fd42f8d450e997b74e8ab2afa11585019f9215aa8fe0c83`),
so it cannot satisfy the shared clang 22 manifest. The expected list stays fixed.
