ARG UPSTREAM_VERSION
FROM ghcr.io/nethserver/samba:${UPSTREAM_VERSION}

ARG UPSTREAM_VERSION
ARG CUSTOM_VERSION=dev

LABEL org.opencontainers.image.title="NS8 Samba remote-join overlay" \
      org.opencontainers.image.description="CLI-only cross-cluster AD DC join support for NS8 Samba" \
      org.opencontainers.image.source="https://github.com/Platypuschan/ns8-samba-reworked" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="${CUSTOM_VERSION}" \
      io.github.platypuschan.ns8-samba-reworked.upstream-version="${UPSTREAM_VERSION}"

# The upstream module image is a scratch-based NS8 module bundle. Overlay only
# the extra agent action; retain its labels, UI, systemd units and runtime image.
COPY overlay/ /
