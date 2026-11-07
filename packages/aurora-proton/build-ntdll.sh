#!/bin/bash
# SPDX-License-Identifier: MIT
# Adapted from nixos-aurora/pkgs/proton/ntdll.nix; reproduce GE's Wine prep.
set -euo pipefail
[[ $# == 8 ]] || { echo 'usage: build-ntdll WORK WINE GE STAGING RESTORE VKXML VIDEOXML FIX' >&2; exit 2; }
work=$(realpath -m "$1")
wine=$(realpath "$2")
ge=$(realpath "$3")
staging=$(realpath "$4")
restore=$(realpath "$5")
vk=$(realpath "$6")
video=$(realpath "$7")
fix=$(realpath "$8")
mkdir -p "$work/ge"
tar -xf "$ge" -C "$work/ge" --strip-components=1
mkdir -p "$work/ge/wine" "$work/ge/wine-staging"
tar -xf "$wine" -C "$work/ge/wine" --strip-components=1
tar -xf "$staging" -C "$work/ge/wine-staging" --strip-components=1
python3 - "$work/ge" "$restore" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
apply = root / 'wine-staging/patches/gitapply.sh'
text = apply.read_text()
assert '|+|-' in text and text.count('nogit=0') == 1
# git apply inside a distribution checkout silently skips unrelated-prefix
# paths. Use Staging's own standalone implementation, as the Nix build does.
apply.write_text(text.replace('|+|-', '|[+]|-').replace('nogit=0', 'nogit=1'))
text = (root / 'patches/protonprep-valve-staging.sh').read_text()
begin, end = '### (2) WINE PATCHING ###', '### END WINE PATCHING ###'
assert text.count(begin) == text.count(end) == 1
body = text[text.index(begin):text.index(end) + len(end)]
body = '\n'.join(line for line in body.splitlines()
                 if not line.strip().startswith(('git reset --hard HEAD', 'git clean -xdf')))
revert = 'git revert --no-commit e813ca5771658b00875924ab88d525322e50d39f'
assert body.count(revert) == 1
# The absolute path is an argv argument to patch, never executable text.
body = body.replace(revert, 'patch -Rp1 < "$AURORA_RESTORE_CONFIGURE"')
(root / 'prepare-wine.sh').write_text('\n'.join(text.splitlines()[:14]) + '\n' + body + '\n')
PY
export AURORA_RESTORE_CONFIGURE="$restore"
(cd "$work/ge/wineopenxr" && patch -Np1 < ../patches/wineopenxr/wineopenxr_decouple.patch)
(cd "$work/ge" && bash -e prepare-wine.sh)
cd "$work/ge/wine"
patch -Np1 < "$fix"
perl tools/make_requests
perl tools/make_specfiles
(cd dlls/winevulkan && python3 make_vulkan -x "$vk" -X "$video")
autoreconf -if
# GE's assembly entry points are not compatible with distro-injected LTO.
# Let Wine choose its own default flags, matching the audited native build.
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS OBJCFLAGS OBJCXXFLAGS
mkdir build
cd build
../configure --enable-archs=aarch64 --disable-tests --without-x --without-freetype --without-fontconfig
make -j "${AURORA_BUILD_JOBS:-4}" dlls/ntdll/ntdll.so
