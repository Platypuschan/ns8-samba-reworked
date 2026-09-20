# Operations

## Post-join checks

Run these checks before treating the new DC as available:

```bash
runagent -m samba1 podman exec samba-dc samba-tool drs showrepl
runagent -m samba1 podman exec samba-dc samba-tool dbcheck --cross-ncs
runagent -m samba1 podman exec samba-dc samba-tool fsmo show

dig @192.168.178.12 _ldap._tcp.dc._msdcs.ad.own-hub.de SRV +short
dig @10.5.0.2 _ldap._tcp.dc._msdcs.ad.own-hub.de SRV +short
```

Expected results:

- Each DC lists the other as an inbound replication neighbor.
- The most recent attempts are successful for all naming contexts.
- `dbcheck` reports zero errors.
- All FSMO roles still have a live owner.
- Both DNS servers return both current DCs after registration converges.
- The destination NS8 cluster lists its local Samba module as the sole local
  provider for `ad.own-hub.de`. It does not list the Netcup NS8 module because
  NS8 service discovery is intentionally not shared between the clusters.

## SYSVOL limitation

Samba AD database and integrated-DNS records replicate through DRS. SYSVOL is
not continuously replicated between Samba DCs by this module. Do not introduce
GPO files or logon scripts unless a separate, tested SYSVOL synchronization and
conflict-avoidance design is added later.

## Updates

Keep a domain controller on a pinned custom image tag. Review the generated
GitHub release and CI result, then use the normal NS8 module update mechanism
to move to the next custom tag. Never replace the running module image merely
because `latest` changed.

After every update, repeat `drs showrepl`, `dbcheck --cross-ncs`, DNS SRV, LDAP,
and Kerberos checks.

## Removal

Do not delete the VM or NS8 module first. Demote a reachable DC normally. If it
is permanently unreachable, remove its AD metadata from a surviving DC with
the deliberate dead-server procedure, then remove stale DNS and verify
`dbcheck --cross-ncs` before deleting the NS8 provider/module.

The exact recovery command depends on which DC survives. Confirm FSMO
ownership and domain health immediately before removal.
