# Operations

## Post-join checks

Run these checks before treating the new DC as available:

```bash
runagent -m samba1 podman exec samba-dc samba-tool drs showrepl
runagent -m samba1 podman exec samba-dc samba-tool dbcheck --cross-ncs
runagent -m samba1 podman exec samba-dc samba-tool fsmo show

dig @192.0.2.12 _ldap._tcp.dc._msdcs.ad.example.com SRV +short
dig @198.51.100.2 _ldap._tcp.dc._msdcs.ad.example.com SRV +short
```

Expected results:

- Each DC lists the other as an inbound replication neighbor.
- The most recent attempts are successful for all naming contexts.
- `dbcheck` reports zero errors.
- All FSMO roles still have a live owner.
- Both DNS servers return both current DCs after registration converges.
- The destination NS8 cluster lists its local Samba module as the sole local
  provider for `ad.example.com`. It does not list the remote NS8 module because
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

## Replication notification monitor

The optional monitor is configured on the module **Settings** page. Its timer
and most recent run can be inspected on the node that hosts the Samba module:

```bash
runagent -m samba1 systemctl --user status ad-replication-monitor.timer
runagent -m samba1 systemctl --user status ad-replication-monitor.service
runagent -m samba1 journalctl --user-unit ad-replication-monitor.service --since today
```

Run an immediate check without waiting for the five-minute timer:

```bash
runagent -m samba1 check-ad-replication
```

The monitor sends one alert per failing replication connection. It clears a
connection's latch only after Samba reports a successful replication, and a
failed status check leaves existing replication latches intact. The state file is
`state/ad-replication-monitor-state.json`; disabling notifications removes it.
The ntfy token is stored in the module environment and is never emitted by the
`get-replication-monitor` action.

## Restoring a remote-joined DC

For `PROVISION_MODE=join-remote-domain` the restore tries three steps, in
this order, and records the result in `state/remote-restore-mode`
(`snapshot`, `joined` or `forced`) and in the restore log.

1. **Snapshot restore.** The DC comes back from its offline backup under its
   original name, address and computer account, like a Windows
   non-authoritative restore. Before it starts, it gets a new invocationId, an
   up-to-dateness vector that covers the backup and a used-up RID pool. It then
   pulls everything it missed, including its own changes made after the
   backup, and hands out RIDs only from a new pool. No credentials are needed.
   The step runs only if the backed-up address is available on the node, the
   surviving DC answers on ports 88 and 389, the DC held no FSMO role at
   backup time, and the backup is younger than the tombstone lifetime minus
   one day. It succeeds only when this DC reports successful inbound
   replication and the surviving DC, read with this DC's computer account,
   shows the new invocationId, which proves that it replicated from this DC.
   Otherwise the DC is stopped, its database removed, and the restore
   continues. Samba has no command for this procedure; the module applies the
   same database changes that `samba-tool domain backup restore` uses, but
   keeps the DC's identity.
2. **Rejoin under a new name.** The DC joins the surviving domain as a new DC
   under the `rN` name that upstream assigns during restore (for example
   `dc2r1`). A module-level restore request may supply one-time
   `recovery_adminuser` and `recovery_adminpass`, usually a domain
   administrator. Without them the saved `ldapservice` account is tried,
   which normally lacks join permission. A direct restore must supply both
   nonempty values or omit both; malformed credentials fail validation before
   the restore copies backup data. Passwords with tabs are supported, while
   user names with tabs are rejected. After the join the DC must start and
   report successful inbound replication.
3. **Forced restore.** The offline domain archive becomes an independent copy
   of the domain, started under another new name after an attempted join (for
   example `dc2r2`). No credentials are needed.

The cluster restore action does not forward the `recovery_*` fields; use a
module-level `restore-module` request to pass them.

**A forced restore can split a live domain.** Keep the two copies isolated
until you choose which one will be authoritative. Verify authentication against
the restored DC, then reconcile client DNS settings and any directory changes.
After a rejoin or forced restore the previous DC name stays registered in the
surviving domain, together with its DNS A/SRV records, and so do objects of a
failed join. Remove them there, for example with `samba-tool domain demote
--remove-other-dead-server=<old name>` on the surviving DC, and check
`dbcheck --cross-ncs`.

If the backed-up address is not available on the target node, upstream
substitutes the node's cluster VPN address, which a remote DC cannot use. Pass
`recovery_ipaddress` with one of the node's non-VPN addresses in the
module-level request; the error message lists the candidates. The snapshot
step is skipped then, because it keeps the original address. Without
`recovery_ipaddress`, or if the result would be empty or inside the cluster
VPN, the restore fails before any branch starts. Monitoring settings from the
backup are retained.

During provisioning the module bind-mounts a corrected copy of the upstream
`join-domain` script into the official Samba runtime image. This preserves
the actual `samba-tool domain join` exit code before the DC is started. After
installation, check both inbound and outbound replication on the running DC.

## Removal

Do not delete the VM or NS8 module first. Demote a reachable DC normally. If it
is permanently unreachable, remove its AD metadata from a surviving DC with
the deliberate dead-server procedure, then remove stale DNS and verify
`dbcheck --cross-ncs` before deleting the NS8 provider/module.

The exact recovery command depends on which DC survives. Confirm FSMO
ownership and domain health immediately before removal.
