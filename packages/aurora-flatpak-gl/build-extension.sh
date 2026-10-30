#!/bin/bash
# build-extension.sh BRANCH REPO [WORKDIR]
#
# Builds org.freedesktop.Platform.GL.aurora//BRANCH for aarch64 from the Mesa
# commit pinned for mesa-aurora in sources.json and exports it to the local
# OSTree repository REPO. Needs flatpak and flatpak-builder, and the aarch64
# org.freedesktop.Platform//BRANCH, org.freedesktop.Sdk//BRANCH and
# org.freedesktop.Sdk.Extension.llvm22//BRANCH
# installed for the user. On an x86_64 host, qemu-user binfmt runs the build.
#
# The extension is exported with ExtensionOf priority 10, above GL.default.
# Flatpak lists GL drivers in priority order, and the first driver to provide a
# merged file name (asahi_icd.aarch64.json, 50_mesa.json, asahi_dri.so, ...)
# keeps it, so with both drivers enabled the Aurora files are the ones apps see.
set -euo pipefail
branch=${1:?runtime branch, e.g. 25.08}
repo=${2:?OSTree repository path}
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=${3:-$PWD/gl-aurora-$branch}
commit=${AURORA_MESA_COMMIT:?exact Mesa commit is required}
sha256=${AURORA_MESA_SHA256:?Mesa archive SHA256 is required}
[[ $branch == 25.08 || $branch == 26.08 ]]
[[ $commit =~ ^[0-9a-f]{40}$ && $sha256 =~ ^[0-9a-f]{64}$ ]]
mkdir -p "$work"
manifest=$work/org.freedesktop.Platform.GL.aurora.yml
sed -e "s/@BRANCH@/$branch/g" -e "s/@COMMIT@/$commit/g" -e "s/@SHA256@/$sha256/g" \
  "$here/org.freedesktop.Platform.GL.aurora.yml.in" > "$manifest"
flatpak-builder --arch=aarch64 --disable-rofiles-fuse --force-clean \
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
flatpak build-export --arch=aarch64 \
  --subject="Aurora Mesa $commit for $branch" "$repo" "$work/build" "$branch"
flatpak build-update-repo "$repo"
# The PKGBUILD checks these against its Mesa commit.
echo "$commit" > "$repo/aurora-mesa-commit.$branch"
echo "exported org.freedesktop.Platform.GL.aurora/aarch64/$branch from $commit"
