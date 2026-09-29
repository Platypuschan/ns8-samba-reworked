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

For `PROVISION_MODE=join-remote-domain`, the module attempts a fresh join using
the saved peer address, realm, service account, and password. A module-level
restore request may supply one-time `recovery_adminuser` and
`recovery_adminpass` for the join. The cluster restore action does not forward
those fields. A direct restore must supply both nonempty values or omit both;
malformed credentials fail validation before the restore copies backup data.
Passwords with tabs are supported, while user names with tabs are rejected.
With the usual non-admin `ldapservice` account its join will
normally fail. After join, the DC must start and report successful inbound
replication. The action reports the outbound DRS notification separately,
without treating a pending notification as a failed join. On failure it stops
a partially started DC, restores the offline
domain archive, and starts the independent DC. Inspect
`state/remote-restore-mode` and the restore log to see `joined` or `forced`.
The outbound notification does not prove that the surviving DC pulled changes;
check `samba-tool drs showrepl` on the surviving DC after a successful join.

The restored DC rejoins under its previous name and reuses the machine account
password from the offline backup. The surviving DC may still hold Kerberos
service tickets for that name. With a new password the restored DC rejects
them, and the surviving DC cannot replicate from it until its Samba restarts.
If the backup holds no usable password, the join uses a new one and the
restore log says so; then restart `samba-dc` on the surviving DC after the
restore.

**A forced restore can split a live domain.** Keep the two copies isolated
until you choose which one will be authoritative. Verify authentication against
the restored DC, then reconcile client DNS settings and any directory changes.
A failed or partially successful join can leave a stale DC computer account
and server/NTDS Settings objects and DNS A/SRV records on the surviving
domain. The forced copy uses another new DC name after an attempted join; it
does not remove those objects. Check the surviving domain before another join.
If the restored address would be empty or inside the target node's cluster
VPN, restore fails before joining or rebuilding. Move the original address to
the target node or use a node with a reachable non-VPN address, then retry.
Monitoring settings from the backup are retained.

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
