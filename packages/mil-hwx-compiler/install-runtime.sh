#!/bin/bash
set -euo pipefail
prefix=${1:?destination prefix}
sources=${2:?unpacked sources directory}
install -Dm755 build/mil-hwxc "$prefix/bin/mil-hwxc"
private="$prefix/lib/mil-hwx-compiler"
mkdir -p "$private"
cp -a .gnustep/lib/libobjc.so* .gnustep/lib/libgnustep-base.so* "$private/"
# These are private dependencies. Never publish global libobjc SONAME provides
# or make their incompatible ARC ABI available to unrelated GNUstep software.
patchelf --set-rpath '$ORIGIN/../lib/mil-hwx-compiler' "$prefix/bin/mil-hwxc"
for library in "$private"/*.so*; do
  if [ ! -L "$library" ]; then patchelf --set-rpath '$ORIGIN' "$library"; fi
done
licenses="$prefix/share/licenses/mil-hwx-compiler"
install -Dm644 LICENSE "$licenses/LICENSE"
install -Dm644 "$sources/libobjc2-a1faad66cee79f29c4ca268b004111edc33a2ae2/COPYING" "$licenses/libobjc2-COPYING"
install -Dm644 "$sources/libs-base-3d7013e144b153abcd6c088dc8d6c64ebd43bc4b/COPYING.LIB" "$licenses/gnustep-base-COPYING.LIB"
# Exercise the installed compiler with only its relative private-library path.
env -u LD_LIBRARY_PATH "$prefix/bin/mil-hwxc" --target H14 --mil tests/fixtures/h14/add.mil \
  --model-root . --output build/installed-h14-add
printf '%s  %s\n' b416b9d14059a0918f6b05bfcf4a8ba982dd92e7b25f2b042c1a15f1ab2a439a \
  build/installed-h14-add/program-0.anec | sha256sum -c -
