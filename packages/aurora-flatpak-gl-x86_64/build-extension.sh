#!/bin/bash
# build-extension.sh BRANCH TREE [WORKDIR]
#
# Builds org.freedesktop.Platform.GL.aurora//BRANCH for x86_64 from the Mesa
# commit pinned for mesa-aurora in sources.json, on an x86_64 host, and writes
# the finished extension (metadata and files) to TREE. Needs flatpak and
# flatpak-builder, and the x86_64 org.freedesktop.Platform//BRANCH,
# org.freedesktop.Sdk//BRANCH and org.freedesktop.Sdk.Extension.llvm22//BRANCH
# installed for the user.
#
# The tree is not exported here: aurora-flatpak-gl adds fex-emu's FEX bundle
# (AArch64) as files/fex on the Mac and exports the result there, so the
# extension and the host run the same FEX. As for the aarch64 extension,
# ExtensionOf priority is 10, above GL.default.
set -euo pipefail
branch=${1:?runtime branch, e.g. 25.08}
tree=${2:?output tree}
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=${3:-$PWD/gl-aurora-x86_64-$branch}
commit=${AURORA_MESA_COMMIT:?exact Mesa commit is required}
sha256=${AURORA_MESA_SHA256:?Mesa archive SHA256 is required}
[[ $branch == 25.08 || $branch == 26.08 ]]
[[ $commit =~ ^[0-9a-f]{40}$ && $sha256 =~ ^[0-9a-f]{64}$ ]]
[[ $(uname -m) == x86_64 ]]
mkdir -p "$work"
manifest=$work/org.freedesktop.Platform.GL.aurora.yml
sed -e "s/@BRANCH@/$branch/g" -e "s/@COMMIT@/$commit/g" -e "s/@SHA256@/$sha256/g" \
  "$here/org.freedesktop.Platform.GL.aurora.yml.in" > "$manifest"
flatpak-builder --arch=x86_64 --disable-rofiles-fuse --force-clean \
  --state-dir="$work/state" "$work/build" "$manifest"
python3 - "$work/build/metadata" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
if '[ExtensionOf]' not in text:
    raise SystemExit('metadata has no [ExtensionOf] group')
lines = [l for l in text.splitlines() if not l.startswith('priority=')]
out = []
for l in lines:
    out.append(l)
    if l == '[ExtensionOf]':
        out.append('priority=10')
open(path, 'w').write('\n'.join(out) + '\n')
PY
echo "$commit" > "$work/build/files/.aurora-mesa-commit"
rm -rf "$tree"
mkdir -p "$tree"
cp -a "$work/build/metadata" "$work/build/files" "$tree/"
echo "built org.freedesktop.Platform.GL.aurora/x86_64/$branch from $commit"
