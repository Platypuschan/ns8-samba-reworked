#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

"""Prepare a DC database copied from an offline backup for a snapshot start.

Experiment only. Runs offline inside the samba-dc image, after the files of
"samba-tool domain backup offline" were put back in place.

naive:   remove the backup markers and start the old database as is.
nonauth: like a Windows non-authoritative restore. Keep the DC name, NTDS
         object and computer account, but record the up-to-dateness vector,
         discard the rest of the RID pool and use a new invocationId, so that
         partners neither skip this DC's new changes nor see reused RIDs.
"""

import json
import sys
import uuid

import ldb
from samba.auth import system_session
from samba.dcerpc import drsblobs, misc
from samba.dsdb import _dsdb_load_udv_v2
from samba.ndr import ndr_pack, ndr_unpack
from samba.param import LoadParm
from samba.samdb import SamDB


mode = sys.argv[1]
if mode not in ("naive", "nonauth"):
    sys.exit(f"unknown mode {mode}")

lp = LoadParm()
lp.load("/etc/samba/smb.conf")
samdb = SamDB(url=lp.samdb_url(), session_info=system_session(), lp=lp)
report = {"mode": mode}

# samba refuses to start a database carrying backup markers.
markers = ["sidForRestore", "backupRename", "backupDate", "backupType"]
res = samdb.search(base="@SAMBA_DSDB", scope=ldb.SCOPE_BASE, attrs=markers)
message = ldb.Message(ldb.Dn(samdb, "@SAMBA_DSDB"))
for marker in markers:
    if marker in res[0]:
        message[marker] = ldb.MessageElement([], ldb.FLAG_MOD_DELETE, marker)
if len(message) > 0:
    samdb.modify(message)
report["removed_markers"] = [m for m in markers if m in res[0]]

ntds_dn = samdb.get_dsServiceName()
old_invocation_id = samdb.get_invocation_id()
report["old_invocation_id"] = old_invocation_id
report["highest_usn"] = int(samdb.search(base="", scope=ldb.SCOPE_BASE,
                                         attrs=["highestCommittedUSN"])[0]
                            ["highestCommittedUSN"][0])

server_dn = samdb.get_serverName()
computer_dn = str(samdb.search(base=server_dn, scope=ldb.SCOPE_BASE,
                               attrs=["serverReference"])[0]["serverReference"][0])
rid_set_dn = str(samdb.search(base=computer_dn, scope=ldb.SCOPE_BASE,
                              attrs=["rIDSetReferences"])[0]["rIDSetReferences"][0])
rid_attrs = ["rIDAllocationPool", "rIDPreviousAllocationPool", "rIDNextRID"]


def rid_set():
    msg = samdb.search(base=rid_set_dn, scope=ldb.SCOPE_BASE, attrs=rid_attrs)[0]
    return {a: int(msg[a][0]) for a in rid_attrs if a in msg}


report["rid_set_before"] = rid_set()

if mode == "nonauth":
    ncs = [str(nc) for nc in samdb.search(base="", scope=ldb.SCOPE_BASE,
                                          attrs=["namingContexts"])[0]["namingContexts"]]
    # Store our own cursor under the old invocationId. Partners filter what
    # they send us with it, and the changes this DC made after the backup
    # (with higher USNs) still come back from them.
    for nc in ncs:
        cursors = _dsdb_load_udv_v2(samdb, nc)
        blob = drsblobs.replUpToDateVectorBlob()
        blob.version = 2
        blob.ctr.cursors = cursors
        blob.ctr.count = len(cursors)
        m = ldb.Message(ldb.Dn(samdb, nc))
        m["replUpToDateVector"] = ldb.MessageElement(ndr_pack(blob), ldb.FLAG_MOD_REPLACE,
                                                     "replUpToDateVector")
        samdb.modify(m)

    # Treat the whole current pool as used. The next account creation asks
    # the RID master for a fresh pool instead of reusing RIDs this DC may
    # have handed out after the backup.
    before = report["rid_set_before"]
    previous = before.get("rIDPreviousAllocationPool", before["rIDAllocationPool"])
    m = ldb.Message(ldb.Dn(samdb, rid_set_dn))
    m["rIDPreviousAllocationPool"] = ldb.MessageElement(str(previous), ldb.FLAG_MOD_REPLACE,
                                                        "rIDPreviousAllocationPool")
    m["rIDAllocationPool"] = ldb.MessageElement(str(previous), ldb.FLAG_MOD_REPLACE,
                                                "rIDAllocationPool")
    m["rIDNextRID"] = ldb.MessageElement(str(previous >> 32), ldb.FLAG_MOD_REPLACE, "rIDNextRID")
    samdb.modify(m)
    report["rid_set_after"] = rid_set()

    new_invocation_id = str(uuid.uuid4())
    m = ldb.Message(ldb.Dn(samdb, ntds_dn))
    m["invocationId"] = ldb.MessageElement(ndr_pack(misc.GUID(new_invocation_id)),
                                           ldb.FLAG_MOD_REPLACE, "invocationId")
    samdb.modify(m)
    stored = samdb.search(base=ntds_dn, scope=ldb.SCOPE_BASE, attrs=["invocationId"])[0]
    report["new_invocation_id"] = str(ndr_unpack(misc.GUID, stored["invocationId"][0]))

json.dump(report, sys.stdout, indent=2)
print()
