#!/bin/bash

# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

python3 "${repo_root}/tests/test_overlay.py" "${repo_root}"
python3 "${repo_root}/tests/test_replication_monitor.py"

if command -v node >/dev/null 2>&1; then
    node --check "${repo_root}/scripts/patch-ui.mjs"
fi

while IFS= read -r script; do
    if [[ $(head -n 1 "${script}") == '#!/bin/bash' ]]; then
        bash -n "${script}"
    fi
done < <(find \
    "${repo_root}/overlay/imageroot/actions" \
    "${repo_root}/scripts" \
    -type f -perm -u+x -print | sort)

next_version=$(python3 "${repo_root}/scripts/next-version.py" 1.2.3)
if [[ ${next_version} != 1.3.0 ]]; then
    printf 'Unexpected version increment: %s\n' "${next_version}" >&2
    exit 1
fi

printf 'Source checks passed.\n'
