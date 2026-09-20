#!/bin/bash

# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
upstream_version=${1:-$(tr -d '[:space:]' < "${repo_root}/UPSTREAM_VERSION")}
image_ref=${2:-ns8-samba-reworked:test}
custom_version=${3:-$(tr -d '[:space:]' < "${repo_root}/CUSTOM_VERSION")}
rootfs=$(mktemp -d)
container_id=

cleanup() {
    if [[ -n ${container_id} ]]; then
        docker rm -f "${container_id}" >/dev/null 2>&1 || true
    fi
    rm -rf "${rootfs}"
}
trap cleanup EXIT

"${repo_root}/scripts/test-source.sh"

docker build \
    --pull \
    --build-arg "UPSTREAM_VERSION=${upstream_version}" \
    --build-arg "CUSTOM_VERSION=${custom_version}" \
    --tag "${image_ref}" \
    --file "${repo_root}/Containerfile" \
    "${repo_root}"

container_id=$(docker create "${image_ref}")
docker export "${container_id}" | tar -C "${rootfs}" -xf -

python3 "${repo_root}/tests/test_overlay.py" "${repo_root}" "${rootfs}"

runtime_images=$(docker image inspect \
    --format '{{ index .Config.Labels "org.nethserver.images" }}' \
    "${image_ref}")
if [[ ${runtime_images} != *"ghcr.io/nethserver/samba-dc:${upstream_version}"* ]]; then
    printf 'Unexpected inherited runtime images label: %s\n' "${runtime_images}" >&2
    exit 1
fi

max_per_node=$(docker image inspect \
    --format '{{ index .Config.Labels "org.nethserver.max-per-node" }}' \
    "${image_ref}")
if [[ ${max_per_node} != 1 ]]; then
    printf 'Unexpected max-per-node label: %s\n' "${max_per_node}" >&2
    exit 1
fi

entrypoint=$(docker image inspect --format '{{ json .Config.Entrypoint }}' "${image_ref}")
if [[ ${entrypoint} != '["/"]' ]]; then
    printf 'Unexpected module entrypoint: %s\n' "${entrypoint}" >&2
    exit 1
fi

reported_upstream=$(docker image inspect \
    --format '{{ index .Config.Labels "io.github.platypuschan.ns8-samba-reworked.upstream-version" }}' \
    "${image_ref}")
reported_custom=$(docker image inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' \
    "${image_ref}")
if [[ ${reported_upstream} != "${upstream_version}" || ${reported_custom} != "${custom_version}" ]]; then
    printf 'Unexpected version labels: upstream=%s custom=%s\n' \
        "${reported_upstream}" "${reported_custom}" >&2
    exit 1
fi

printf 'Image checks passed for upstream %s.\n' "${upstream_version}"
