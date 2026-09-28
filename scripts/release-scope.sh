#!/bin/bash

# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail
released_sha=${1:?Pass the released tag or commit}

# A scheduled run must use the same source scope as the push trigger. Release
# only when an image or its build/release logic changed since the last tag.
if git diff --quiet "${released_sha}" HEAD -- \
    Containerfile .dockerignore UPSTREAM_VERSION CUSTOM_VERSION \
    overlay ui-overlay scripts tests .github/workflows/upstream-release.yml \
    >/dev/null; then
    printf 'false\n'
else
    printf 'true\n'
fi
