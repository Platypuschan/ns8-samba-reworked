#!/bin/bash

# SPDX-License-Identifier: GPL-3.0-or-later

# Experiment: can a DC come back from its offline backup under its old name,
# IP and computer account, like a snapshot, and catch up by replication?
#
#   snapshot-restore.sh OUTPUT_DIR naive|nonauth
#
# naive:   start the old database unchanged (expected: USN rollback).
# nonauth: new invocationId, saved up-to-dateness vector and a discarded RID
#          pool, like a Windows non-authoritative restore.
#
# DC A (dc1) survives; DC B (dc2) is backed up, changed, lost and restored.
# Run as root on a disposable host.

set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:?Pass an output directory for logs}
mode=${2:?Pass naive or nonauth}
[[ ${mode} == naive || ${mode} == nonauth ]] || { echo "unknown mode ${mode}" >&2; exit 2; }
mkdir -p "${out}"
out=$(cd "${out}" && pwd)
work=${out}/work
mkdir -p "${work}"

upstream_version=$(tr -d '[:space:]' < "${repo_root}/UPSTREAM_VERSION")
image=ghcr.io/nethserver/samba-dc:${upstream_version}
overlay=${repo_root}/overlay/imageroot

export IT_NETWORK=samba-snap
subnet=10.89.1.0/24
a_ip=10.89.1.11
b_ip=10.89.1.12
realm=AD.EXAMPLE.TEST
domain=ad.example.test
nbdomain=AD
# Test-only credentials for a throwaway domain.
admin_pass='Integration-Admin-2026!'
service_pass='Integration-Service-2026!'
user_pass='Integration-User-2026!'

failures=0
results=()
pass() { results+=("PASS  $*"); printf '\n=== PASS: %s\n' "$*"; }
fail() { results+=("FAIL  $*"); printf '\n::error::FAIL: %s\n' "$*"; failures=$((failures + 1)); }
info() { results+=("INFO  $*"); printf '\n=== INFO: %s\n' "$*"; }
check() {
    local name=$1
    shift
    if "$@"; then pass "${name}"; else fail "${name}"; fi
}
section() { printf '\n##################### %s #####################\n' "$*"; }

poll() {
    local deadline=$((SECONDS + $1))
    shift
    until "$@" >/dev/null 2>&1; do
        ((SECONDS < deadline)) || return 1
        sleep 5
    done
}

on_a() { podman exec dc1 "$@"; }
on_b() { podman exec samba-dc "$@"; }
sam() { local c=$1; shift; podman exec "${c}" ldbsearch -H /var/lib/samba/private/sam.ldb "$@"; }

showrepl() { podman exec "$1" samba-tool drs showrepl --json; }
replication_clean() {
    showrepl "$1" | jq -e '
        ((.repsFrom // []) | length > 0) and
        ([(.repsFrom // [])[], (.repsTo // [])[] | .["consecutive failures"]] | all(. == 0))'
}
inbound_clean() {
    showrepl "$1" | jq -e '((.repsFrom // []) | length > 0) and
        ([(.repsFrom // [])[] | .["consecutive failures"]] | all(. == 0))'
}
user_exists() { podman exec "$1" samba-tool user show "$2"; }
description_is() {
    [[ $(sam "$1" "(sAMAccountName=$2)" description | sed -n 's/^description: //p') == "$3" ]]
}
user_sid() { sam "$1" "(sAMAccountName=$2)" objectSid | sed -n 's/^objectSid: //p'; }
highest_usn() { sam "$1" -b '' -s base highestCommittedUSN | sed -n 's/^highestCommittedUSN: //p'; }
ntds_invocation_id() {
    sam "$1" -b "CN=NTDS Settings,CN=$2,CN=Servers,CN=Default-First-Site-Name,CN=Sites,CN=Configuration,DC=ad,DC=example,DC=test" \
        -s base invocationId | sed -n 's/^invocationId: //p'
}
duplicate_sids() {
    { sam dc1 '(objectSid=*)' objectSid; sam samba-dc '(objectSid=*)' objectSid; } 2>/dev/null |
        sed -n 's/^objectSid: \(S-1-5-21-.*\)$/\1/p' | sort | uniq -c | awk '$1 > 2 {print $2}'
}

kinit_at() {
    podman run --rm -i --network="${IT_NETWORK}" --entrypoint=/bin/bash \
        --env=KDC="$1" --env=PRINCIPAL="$2@${realm}" --env=KPASS="$3" --env=REALM="${realm}" \
        "${image}" -s <<'EOF'
set -e
printf '[libdefaults]\n default_realm = %s\n dns_lookup_kdc = false\n[realms]\n %s = {\n  kdc = %s\n }\n' \
    "${REALM}" "${REALM}" "${KDC}" > /tmp/krb5.conf
KRB5_CONFIG=/tmp/krb5.conf kinit "${PRINCIPAL}" <<<"${KPASS}"
EOF
}

fast_replication_config() {
    podman run --rm --volume="$1:/etc/samba:z" --entrypoint=/bin/bash "${image}" -c \
        'printf "kccsrv:periodic_interval = 15\ndreplsrv:periodic_interval = 15\n" >> /etc/samba/include.conf'
}

b_env() {
    export IPADDRESS=${b_ip} HOSTNAME=dc2.${domain} REALM=${realm} NBDOMAIN=${nbdomain} \
        SAMBA_DC_IMAGE=${image}
}
start_b() { ( b_env; "${repo_root}/integration/bin/systemctl" --user enable --now samba-dc.service ); }
remove_b() {
    podman rm --force --ignore samba-dc samba-provisioning >/dev/null
    podman volume rm --force data config shares homes >/dev/null 2>&1 || true
}

cleanup() { podman rm --force --ignore dc1 samba-dc samba-provisioning >/dev/null 2>&1; }
trap cleanup EXIT

summary() {
    printf '\n##################### Summary (%s) #####################\n' "${mode}"
    printf '%s\n' "${results[@]}" | tee "${out}/summary.txt"
    if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
        {
            printf '## Snapshot restore experiment: %s\n\n```\n' "${mode}"
            printf '%s\n' "${results[@]}"
            printf '```\n'
        } >> "${GITHUB_STEP_SUMMARY}"
    fi
}
abort() { fail "$*"; summary; exit 1; }

#######################################################################
section "Setup: DC A (dc1) and DC B (dc2) in one domain"
podman --version
podman pull -q "${image}"
podman network rm --force "${IT_NETWORK}" >/dev/null 2>&1
podman network create --disable-dns --subnet="${subnet}" "${IT_NETWORK}"
remove_b
podman volume rm --force a-data a-config a-shares a-homes >/dev/null 2>&1

podman run --rm --network="${IT_NETWORK}" --ip="${a_ip}" --hostname="dc1.${domain}" \
    --dns=none --no-hosts \
    --env=REALM="${realm}" --env=IPADDRESS="${a_ip}" --env=NBDOMAIN="${nbdomain}" \
    --env=SVCUSER=ldapservice --env=SVCPASS="${service_pass}" \
    --env=ADMINCREDS="$(printf 'administrator\t%s' "${admin_pass}" | base64 --wrap=0)" \
    --volume=a-data:/var/lib/samba:z --volume=a-config:/etc/samba:z \
    --volume=a-shares:/srv/shares:z --volume=a-homes:/srv/homes:z \
    "${image}" new-domain > "${out}/dc1-provision.log" 2>&1 || abort "DC A provisioning"
fast_replication_config a-config
podman run --detach --name=dc1 --replace --network="${IT_NETWORK}" --ip="${a_ip}" \
    --hostname="dc1.${domain}" --dns=none --no-hosts \
    --env=REALM="${realm}" --env=IPADDRESS="${a_ip}" --env=NBDOMAIN="${nbdomain}" \
    --volume=a-data:/var/lib/samba:z --volume=a-config:/etc/samba:z \
    --volume=a-shares:/srv/shares --volume=a-homes:/srv/homes \
    "${image}" </dev/null >/dev/null 2>&1
for port in 53 88 389 3268; do
    poll 180 bash -c "exec 3<>/dev/tcp/${a_ip}/${port}" || abort "DC A start"
done

podman run --rm --dns=none --no-hosts --network="${IT_NETWORK}" --ip="${b_ip}" \
    --hostname="dc2.${domain}" \
    --env=REALM="${realm}" --env=IPADDRESS="${b_ip}" --env=NBDOMAIN="${nbdomain}" \
    --env=JOINADDRESS="${a_ip}" \
    --env=ADMINUSER_B64="$(printf administrator | base64 --wrap=0)" \
    --env=ADMINPASS_B64="$(printf '%s' "${admin_pass}" | base64 --wrap=0)" \
    --name=samba-provisioning \
    --volume=data:/var/lib/samba:z --volume=config:/etc/samba:z \
    --volume=shares:/srv/shares:z --volume=homes:/srv/homes:z \
    --volume="${overlay}/bin/join-domain-checked:/run/join-domain-checked:ro,z" \
    "${image}" /run/join-domain-checked > "${out}/dc2-join.log" 2>&1 || abort "DC B join"
fast_replication_config config
start_b || abort "DC B start"
check "Initial replication on DC B is clean" poll 300 replication_clean samba-dc
check "Initial replication on DC A is clean" poll 300 replication_clean dc1

on_a samba-tool user create pre-a "${user_pass}" >/dev/null
on_b samba-tool user create pre-b "${user_pass}" >/dev/null
check "pre-a reaches DC B" poll 300 user_exists samba-dc pre-a
check "pre-b reaches DC A" poll 300 user_exists dc1 pre-b

#######################################################################
section "Backup DC B like module-dump-state"
old_invocation=$(ntds_invocation_id samba-dc dc2)
backup_usn=$(highest_usn samba-dc)
on_b bash -c 'cd /var/lib/samba && rm -rf backup && samba-tool domain backup offline --targetdir=backup &&
    mv backup/samba-backup-*.tar.bz2 backup/samba-backup.tar.bz2' > "${out}/backup.log" 2>&1 ||
    abort "Offline backup of DC B"
on_b tar -tjf /var/lib/samba/backup/samba-backup.tar.bz2 > "${out}/backup-contents.txt"
mkdir -p "${work}/backup"
podman run --rm --volume=config:/src/config:z --volume=data:/src/data:z \
    --volume="${work}/backup:/dst:z" --entrypoint=tar "${image}" \
    -C /src -cf /dst/volumes.tar config data/backup
info "DC B at backup: invocationId ${old_invocation}, highestCommittedUSN ${backup_usn}"

#######################################################################
section "Changes after the backup, then DC B is lost"
on_a samba-tool user create post-a "${user_pass}" >/dev/null
on_b samba-tool user create post-b "${user_pass}" >/dev/null
post_b_sid=$(user_sid samba-dc post-b)
podman exec -i samba-dc ldbmodify -H /var/lib/samba/private/sam.ldb >/dev/null <<EOF
dn: CN=pre-a,CN=Users,DC=ad,DC=example,DC=test
changetype: modify
replace: description
description: changed-on-b-after-backup
EOF
# Move DC B's USN well past the backup. After a naive restore, its next
# changes reuse USNs that DC A already considers replicated.
for i in $(seq 1 300); do
    printf 'dn: CN=pre-b,CN=Users,DC=ad,DC=example,DC=test\nchangetype: modify\nreplace: description\ndescription: bulk-%s\n\n' "${i}"
done | podman exec -i samba-dc ldbmodify -H /var/lib/samba/private/sam.ldb >/dev/null
check "DC A has post-b before DC B is lost" poll 300 user_exists dc1 post-b
check "DC A has DC B's last description change" poll 300 description_is dc1 pre-b bulk-300
check "DC A has DC B's change to pre-a" poll 300 description_is dc1 pre-a changed-on-b-after-backup
lost_usn=$(highest_usn samba-dc)
info "DC B when lost: highestCommittedUSN ${lost_usn} (backup ${backup_usn}); post-b SID ${post_b_sid}"
showrepl dc1 > "${out}/showrepl-dc1-before-loss.json"
"${repo_root}/integration/bin/systemctl" --user stop samba-dc.service
remove_b

#######################################################################
section "Restore DC B from the snapshot (${mode})"
podman volume create data >/dev/null
podman volume create config >/dev/null
podman run --rm --volume=config:/dst/config:z --volume=data:/dst/data:z \
    --volume="${work}/backup:/src:z" --entrypoint=tar "${image}" -C /dst -xf /src/volumes.tar
podman run --rm -i --volume=data:/var/lib/samba:z --volume=config:/etc/samba:z \
    --volume="${repo_root}/integration/lib/snapshot_restore.py:/run/snapshot_restore.py:ro,z" \
    --entrypoint=/bin/bash --env=MODE="${mode}" "${image}" -s \
    > "${out}/snapshot-restore.json" 2> "${out}/snapshot-restore.log" <<'EOF'
set -ex
cd /var/lib/samba
rm -rf snap && mkdir snap
tar -xjf backup/samba-backup.tar.bz2 -C snap
find snap -maxdepth 2 >&2
rm -rf private sysvol
mv snap/private .
[[ -d snap/state/sysvol ]] && mv snap/state/sysvol .
for f in snap/state/*.tdb; do [[ -e ${f} ]] && mv -f "${f}" .; done
rm -rf snap backup
python3 /run/snapshot_restore.py "${MODE}"
net cache flush >&2
EOF
code=$?
cat "${out}/snapshot-restore.log" "${out}/snapshot-restore.json"
[[ ${code} == 0 ]] || abort "Snapshot preparation (${mode})"
new_invocation=$(jq -r '.new_invocation_id // empty' "${out}/snapshot-restore.json")
info "Prepared snapshot: $(jq -c '{removed_markers, highest_usn, rid_set_before, rid_set_after, new_invocation_id}' "${out}/snapshot-restore.json")"

start_b
check "Restored DC B starts under its old name and IP" test $? -eq 0
podman logs samba-dc > "${out}/dc2-start.log" 2>&1

#######################################################################
section "Checks after the snapshot restore"
check "DC B inbound replication is clean" poll 300 inbound_clean samba-dc
check "DC B receives a user DC A created after the backup" poll 300 user_exists samba-dc post-a
check "DC B gets back its own lost user post-b" poll 300 user_exists samba-dc post-b
check "DC B gets back its own lost change to pre-a" poll 300 description_is samba-dc pre-a changed-on-b-after-backup
check "DC B gets back its own lost bulk changes" poll 300 description_is samba-dc pre-b bulk-300

# RID allocation may need a round trip to the RID master; retry the creation.
create_after_restore() { on_b samba-tool user create after-restore-b "${user_pass}" || user_exists samba-dc after-restore-b; }
check "DC B can create a user after the restore" poll 180 create_after_restore
after_sid=$(user_sid samba-dc after-restore-b)
info "post-b SID ${post_b_sid}, after-restore-b SID ${after_sid:-none}"
check "The new user does not reuse the SID of post-b" bash -c "[[ -n '${after_sid}' && '${after_sid}' != '${post_b_sid}' ]]"
check "A user created on DC B after the restore reaches DC A" poll 300 user_exists dc1 after-restore-b
podman exec -i samba-dc ldbmodify -H /var/lib/samba/private/sam.ldb >/dev/null <<EOF
dn: CN=pre-a,CN=Users,DC=ad,DC=example,DC=test
changetype: modify
replace: description
description: changed-on-b-after-restore
EOF
check "A change on DC B after the restore reaches DC A" poll 300 description_is dc1 pre-a changed-on-b-after-restore
on_a samba-tool user create after-restore-a "${user_pass}" >/dev/null
check "A user created on DC A after the restore reaches DC B" poll 300 user_exists samba-dc after-restore-a
check "DC A replication with DC B is clean" poll 300 replication_clean dc1
check "DC B replication is clean" poll 300 replication_clean samba-dc
dups=$(duplicate_sids)
check "No SID is used by two objects" test -z "${dups}"
[[ -z ${dups} ]] || info "Duplicate SIDs: ${dups}"
if [[ ${mode} == nonauth ]]; then
    check "DC A sees DC B's new invocationId" \
        poll 300 bash -c "[[ \$(podman exec dc1 ldbsearch -H /var/lib/samba/private/sam.ldb -b 'CN=NTDS Settings,CN=DC2,CN=Servers,CN=Default-First-Site-Name,CN=Sites,CN=Configuration,DC=ad,DC=example,DC=test' -s base invocationId | sed -n 's/^invocationId: //p') == '${new_invocation}' ]]"
fi
check "DC B issues a Kerberos ticket for post-a" kinit_at "${b_ip}" post-a "${user_pass}"
check "DC A issues a Kerberos ticket for after-restore-b" kinit_at "${a_ip}" after-restore-b "${user_pass}"
for c in dc1 samba-dc; do
    podman exec "${c}" samba-tool dbcheck --cross-ncs > "${out}/dbcheck-${c}.txt" 2>&1
    check "dbcheck --cross-ncs on ${c} finds no errors" test $? -eq 0
done
showrepl dc1 > "${out}/showrepl-dc1-final.json" 2>&1
showrepl samba-dc > "${out}/showrepl-dc2-final.json" 2>&1
podman logs --tail 500 dc1 > "${out}/dc1-final.log" 2>&1
podman logs --tail 500 samba-dc > "${out}/dc2-final.log" 2>&1

summary
exit $((failures > 0))
