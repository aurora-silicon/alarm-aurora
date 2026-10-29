#!/bin/bash
# Refuse a repository from an older Mesa or missing either supported runtime.
set -euo pipefail
repo=${1:?repository path required}
commit=${2:?exact Mesa commit required}
[[ $commit =~ ^[0-9a-f]{40}$ && -d $repo/objects ]]
for branch in 25.08 26.08; do
  [[ $(cat "$repo/aurora-mesa-commit.$branch") == "$commit" ]] || {
    echo "Flatpak GL $branch was not built from Mesa $commit" >&2; exit 1;
  }
  ref=runtime/org.freedesktop.Platform.GL.aurora/aarch64/$branch
  ostree --repo="$repo" show "$ref" | grep -Fq "Aurora Mesa $commit for $branch"
done
