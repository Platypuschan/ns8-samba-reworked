# NS8 Samba reworked

`ns8-samba-reworked` is a provisioning and monitoring overlay for the official
NS8 Samba module. It permits an NS8 Samba domain controller on one standalone
NS8 cluster to join an existing Active Directory domain hosted by a Samba DC
on another standalone NS8 cluster. The cross-cluster join is available from
the module web UI and from the API/CLI.

The two NS8 systems remain independent leader nodes. They do **not** form an
NS8 cluster. Only Active Directory data is replicated by Samba.

## Scope

- Base image: `ghcr.io/nethserver/samba`, pinned by `UPSTREAM_VERSION`.
- Runtime: the unmodified official `samba-dc` image selected by the base
  module's `org.nethserver.images` label.
- Added API action: `configure-remote-domain`.
- LDAP bind identity: the existing `ldapservice` user and password from the
  source NS8 Samba provider.
- Configuration: the module web UI offers a remote-domain-controller join
  wizard while preserving the upstream local file-server workflow.
- Monitoring: optional ntfy notification when a Samba replication connection
  reaches a configured number of consecutive failures.
- Releases: GitHub Actions checks the latest stable upstream release daily,
  tests a candidate image, and publishes a new custom package only after the
  tests pass.

This project does **not** add SYSVOL replication. GPOs and logon scripts are
therefore out of scope. Use this only for a domain where ongoing SYSVOL content
synchronization is not required.

## Network prerequisites

The DCs need stable, bidirectional routed connectivity. Do not rely on an
NS8-cluster WireGuard route because these hosts intentionally belong to
different clusters.

Allow at least DNS (TCP/UDP 53), Kerberos (TCP/UDP 88 and 464), NTP (UDP 123),
LDAP/LDAPS (TCP/UDP 389, TCP 636), SMB (TCP 445), endpoint mapper (TCP 135),
Global Catalog (TCP 3268/3269), and AD dynamic RPC (TCP 49152-65535) between
the DC addresses. Correct forward and reverse routing is mandatory.

Before installing, verify from the new NS8 host that the existing DC answers
authoritative AD DNS directly:

```bash
dig @198.51.100.2 _ldap._tcp.dc._msdcs.ad.example.com SRV +short
dig @198.51.100.2 dc1.ad.example.com A +short
```

## Install the pinned module image

Run this on the new standalone NS8 leader. Pin the custom version used in
production; do not deploy `latest` to a domain controller.

```bash
api-cli run add-internal-provider --data '{
  "image": "ghcr.io/platypuschan/samba:1.1.0",
  "node": 1
}'
```

Record the returned module ID. On a new cluster it will normally be `samba1`.

The package may initially be private after its first GHCR publication. If so,
make the `samba` package public in the repository owner's GitHub package
settings before installing it on NS8.

## Reuse `ldapservice` safely

The destination provider must advertise the same `ldapservice` password as
the existing provider. Do not create or reset that account.

On the existing remote NS8 leader, export only the required non-interactive
provider values to a root-only file:

```bash
umask 077
runagent -m samba1 python3 - <<'PY' > /root/ns8-samba-remote-source.json
import json
import os

print(json.dumps({
    "nbdomain": os.environ["NBDOMAIN"],
    "ldapservice_password": os.environ["SVCPASS"],
}))
PY
```

Transfer that file through an encrypted, authenticated channel to the new
leader as `/root/ns8-samba-remote-source.json`, still mode `0600`. Delete both
copies after the join succeeds.

## Join from the web UI

Open the newly installed Samba instance in the NS8 application view. In the
first-configuration wizard select **Join a remote AD domain as a domain
controller**, then enter:

- the AD DNS domain/realm and NetBIOS domain name;
- the directly reachable IP address of an existing writable DC;
- the existing provider's `ldapservice` password;
- Domain Admin credentials for the join; and
- the new DC host name and local IP address.

The UI calls the same validated `configure-remote-domain` action documented
below. Secrets are sent in the task payload and are never returned by a read
action.

## Join the remote AD domain

On the new local NS8 leader, run the action. Secrets are sent on standard input,
not exposed in process arguments or shell history:

```bash
read -rsp 'AD join password: ' AD_ADMIN_PASSWORD
echo

jq -n \
  --slurpfile source /root/ns8-samba-remote-source.json \
  --arg adminpass "$AD_ADMIN_PASSWORD" \
  --arg realm 'ad.example.com' \
  --arg hostname 'DC-LOCAL' \
  --arg ipaddress '192.0.2.12' \
  --arg joinaddress '198.51.100.2' \
  '{
    adminuser: "Administrator",
    adminpass: $adminpass,
    realm: $realm,
    nbdomain: $source[0].nbdomain,
    hostname: $hostname,
    ipaddress: $ipaddress,
    joinaddress: $joinaddress,
    ldapservice_password: $source[0].ldapservice_password
  }' |
  api-cli run module/samba1/configure-remote-domain --data -

unset AD_ADMIN_PASSWORD
rm -f /root/ns8-samba-remote-source.json
```

The action validates that:

- the realm is not already registered in the destination NS8 cluster;
- the requested local DC address is available for Samba;
- the remote DC answers the AD LDAP SRV query directly;
- the new DC hostname is not already present in AD DNS; and
- the remote DC accepts TCP connections on 53, 88, 135, 389, and 445.

The checks do not replace firewall verification for UDP services or dynamic
RPC ports.

## Verify the result

On both DCs, replication should show the other DC with successful inbound
neighbors:

```bash
runagent -m samba1 podman exec samba-dc samba-tool drs showrepl
runagent -m samba1 podman exec samba-dc samba-tool fsmo show
```

On the new local NS8 leader also verify the local NS8 provider registration:

```bash
api-cli run list-user-domains |
jq '.domains[] | select(.name == "ad.example.com")'
```

Operational checks and removal precautions are in
[`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## ntfy replication notifications

After the DC is configured, open **Settings** and enable **AD replication
notifications**. Configure the ntfy server base URL, topic, an optional access
token, and the number of consecutive failures that must be reached before a
notification is sent.

The monitor runs every five minutes and reads `samba-tool drs showrepl --json`.
The threshold is applied to Samba's own `consecutive failures` value for every
non-deleted inbound and outbound replication connection. One message is sent
per active incident; successful replication resets the incident so a later
failure can notify again. A failure to execute the health check itself uses
the same threshold and produces a distinct warning.

The access token is write-only in the UI/API: the read action reports only
whether a token is configured.

## Development

Run source-only checks without a container engine:

```bash
./scripts/test-source.sh
```

Build and validate the complete derived image with Docker:

```bash
./scripts/test-image.sh
```

`test-image.sh` verifies the overlay, inherited module labels, expected
official `samba-dc` runtime tag, executable action steps, and compatibility
with the upstream action layout.

## Release model

`.github/workflows/upstream-release.yml` runs daily and on changes to `main`.
It queries the latest non-prerelease GitHub release of
`NethServer/ns8-samba`. When the upstream version changes it:

1. downloads the matching upstream UI source and builds the customized UI;
2. builds the overlay on that exact upstream module image;
3. runs the source and image compatibility tests;
4. updates `UPSTREAM_VERSION` and increments the custom minor version;
5. pushes the tested image to `ghcr.io/platypuschan/samba`;
6. creates a matching Git tag and GitHub release.

If testing fails, neither version files nor packages are released. Upstream
changes that break one of the reused action steps therefore stop at CI.
The UI patch also uses explicit source anchors; an incompatible upstream UI
change fails the candidate build instead of silently dropping custom fields.

## License

GPL-3.0-or-later. See `LICENSE` and `NOTICE.md`.
