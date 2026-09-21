ARG UPSTREAM_VERSION

FROM docker.io/library/node:24-slim AS ui-builder

ARG UPSTREAM_VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

RUN curl --fail --location --retry 3 \
        "https://github.com/NethServer/ns8-samba/archive/refs/tags/${UPSTREAM_VERSION}.tar.gz" \
        --output upstream.tar.gz \
    && tar --extract --gzip --file upstream.tar.gz \
    && mv "ns8-samba-${UPSTREAM_VERSION}/ui" /usr/src/ui \
    && rm -rf upstream.tar.gz "ns8-samba-${UPSTREAM_VERSION}"

COPY ui-overlay/ /usr/src/ui/
COPY scripts/patch-ui.mjs /tmp/patch-ui.mjs

RUN node /tmp/patch-ui.mjs /usr/src/ui \
    && cd /usr/src/ui \
    && corepack enable \
    && yarn install --immutable \
    && NODE_OPTIONS=--openssl-legacy-provider yarn build

FROM ghcr.io/nethserver/samba:${UPSTREAM_VERSION}

ARG UPSTREAM_VERSION
ARG CUSTOM_VERSION=dev

LABEL org.opencontainers.image.title="NS8 Samba remote-join overlay" \
      org.opencontainers.image.description="Cross-cluster AD DC join UI and replication notifications for NS8 Samba" \
      org.opencontainers.image.source="https://github.com/Platypuschan/ns8-samba-reworked" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="${CUSTOM_VERSION}" \
      io.github.platypuschan.ns8-samba-reworked.upstream-version="${UPSTREAM_VERSION}"

# The upstream module image is a scratch-based NS8 module bundle. Retain its
# labels and runtime images, then overlay the custom actions, units, and UI.
COPY overlay/ /
COPY --from=ui-builder /usr/src/ui/dist/ /ui/
