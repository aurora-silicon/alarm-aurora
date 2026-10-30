#!/bin/bash
# Validate the actual OSTree payloads for both supported runtime branches.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 "$here/validate-repository.py" --repo "${1:?repository path required}" \
  --commit "${2:?exact Mesa commit required}"
