#!/bin/bash

# SPDX-License-Identifier: GPL-3.0-or-later

# Two-DC integration test with the official samba-dc image. DC A stands in for
# the surviving DC on the other NS8 leader; DC B runs this module's join,
# monitoring and restore scripts. Run as root on a disposable host.

set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:?Pass an output directory for logs}
mkdir -p "${out}"
out=$(cd "${out}" && pwd)
work=${out}/work
mkdir -p "${work}"

upstream_version=$(tr -d '[:space:]' < "${repo_root}/UPSTREAM_VERSION")
image=ghcr.io/nethserver/samba-dc:${upstream_version}
overlay=${repo_root}/overlay/imageroot
actions=${overlay}/actions

export IT_NETWORK=samba-it
subnet=10.89.0.0/24
a_ip=10.89.0.11
export IT_B_IP=10.89.0.12
unreachable_ip=10.89.0.99
realm=AD.EXAMPLE.TEST
domain=ad.example.test
nbdomain=AD
basedn=DC=ad,DC=example,DC=test
# Test-only credentials for a throwaway domain.
admin_pass='Integration-Admin-2026!'
service_pass='Integration-Service-2026!'
user_pass='Integration-User-2026!'
tab_pass=$'Tab\tJoin-2026!'
state=${work}/state

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

# poll SECONDS COMMAND...: retry every 5 s until COMMAND succeeds.
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

# Run one module action step as the NS8 agent would: in the state directory,
# with the current module environment loaded. Stdout goes to $2, stderr to
# the step log.
run_step() {
    local step=$1 stdout_file=$2 input=$3
    (
        cd "${state}" || exit 99
        set -a
        # shellcheck disable=SC1091
        source ./environment
        set +a
        export AGENT_STATE_DIR=${state} AGENT_INSTALL_DIR=${overlay} MODULE_ID=samba1 \
            SAMBA_DC_IMAGE=${image} PODMAN_BIN=${repo_root}/integration/bin/podman \
            PYTHONPATH=${repo_root}/integration/lib \
            PATH=${repo_root}/integration/bin:${PATH}
        printf '%s' "${input}" | "${step}"
    ) >"${stdout_file}" 2> >(tee -a "${out}/steps.log" >&2)
}

env_value() { sed -n "s/^$1=//p" "${state}/environment" | tail -n 1; }

environment_json() {
    python3 -c '
import json, sys
env = dict(line.rstrip("\n").split("=", 1) for line in open(sys.argv[1]) if "=" in line)
print(json.dumps(env))' "$1"
}

remove_b() {
    podman rm --force --ignore samba-dc samba-provisioning samba-restore >/dev/null
    podman volume rm --force data config shares homes >/dev/null 2>&1 || true
}

showrepl() { podman exec "$1" samba-tool drs showrepl --json; }

inbound_failures_at_least() {
    showrepl samba-dc | jq -e --argjson n "$1" \
        '[.repsFrom[]? | .["consecutive failures"]] | max // 0 | . >= $n'
}

replication_clean() {
    showrepl "$1" | jq -e '
        ((.repsFrom // []) | length > 0) and
        ([(.repsFrom // [])[], (.repsTo // [])[] | .["consecutive failures"]] | all(. == 0))'
}

user_exists() { podman exec "$1" samba-tool user show "$2"; }

kinit_at() {
    local kdc=$1 principal=$2 password=$3
    podman run --rm -i --network="${IT_NETWORK}" --entrypoint=/bin/bash \
        --env=KDC="${kdc}" --env=PRINCIPAL="${principal}@${realm}" \
        --env=KPASS="${password}" --env=REALM="${realm}" "${image}" -s <<'EOF'
set -e
cat > /tmp/krb5.conf <<CONF
[libdefaults]
    default_realm = ${REALM}
    dns_lookup_kdc = false
[realms]
    ${REALM} = {
        kdc = ${KDC}
    }
CONF
export KRB5_CONFIG=/tmp/krb5.conf
kinit "${PRINCIPAL}" <<<"${KPASS}"
klist
EOF
}

dig_at() {
    podman run --rm --network="${IT_NETWORK}" --entrypoint=dig "${image}" +short "@$1" "$2" "$3"
}

dns_a_is() { [[ $(dig_at "$1" "$2" A) == "$3" ]]; }
dns_srv_has() { dig_at "$1" "_ldap._tcp.${domain}" SRV | grep -qi "$2\.${domain}\.\?$"; }

ntfy_count() { if [[ -f ${out}/ntfy.jsonl ]]; then wc -l < "${out}/ntfy.jsonl"; else echo 0; fi; }

run_monitor() {
    (
        export AGENT_STATE_DIR=${work}/monitor-state SERVER_ROLE=dc NTFY_REPLICATION_ENABLED=1 \
            NTFY_REPLICATION_BASE_URL=http://127.0.0.1:18080 NTFY_REPLICATION_TOPIC='samba it' \
            NTFY_REPLICATION_TOKEN=itest-token NTFY_REPLICATION_FAILURE_THRESHOLD=2 \
            HOSTNAME=dc2.${domain}
        "${overlay}/bin/check-ad-replication"
    ) 2> >(tee -a "${out}/monitor.log" >&2)
}

fast_replication_config() {
    # Samba defaults to 5-minute KCC and DRS periodic runs. Shorten them so the
    # test observes replication and failures within minutes.
    podman run --rm --volume="$1:/etc/samba:z" --entrypoint=/bin/bash "${image}" -c \
        'printf "kccsrv:periodic_interval = 15\ndreplsrv:periodic_interval = 15\n" >> /etc/samba/include.conf'
}

cleanup() {
    podman rm --force --ignore dc1 samba-dc samba-provisioning samba-restore >/dev/null 2>&1
    [[ -z ${receiver_pid:-} ]] || kill "${receiver_pid}" 2>/dev/null
}
trap cleanup EXIT

summary() {
    printf '\n##################### Summary #####################\n'
    printf '%s\n' "${results[@]}" | tee "${out}/summary.txt"
    if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
        {
            printf '## Samba two-DC integration test\n\n```\n'
            printf '%s\n' "${results[@]}"
            printf '```\n'
        } >> "${GITHUB_STEP_SUMMARY}"
    fi
}

#######################################################################
section "Setup"
podman --version
podman pull -q "${image}"
podman network rm --force "${IT_NETWORK}" >/dev/null 2>&1
podman network create --disable-dns --subnet="${subnet}" "${IT_NETWORK}"
remove_b
podman volume rm --force a-data a-config a-shares a-homes >/dev/null 2>&1

section "Provision DC A (dc1) with the upstream new-domain script"
if ! podman run --rm --network="${IT_NETWORK}" --ip="${a_ip}" --hostname="dc1.${domain}" \
    --dns=none --no-hosts \
    --env=REALM="${realm}" --env=IPADDRESS="${a_ip}" --env=NBDOMAIN="${nbdomain}" \
    --env=SVCUSER=ldapservice --env=SVCPASS="${service_pass}" \
    --env=ADMINCREDS="$(printf 'administrator\t%s' "${admin_pass}" | base64 --wrap=0)" \
    --volume=a-data:/var/lib/samba:z --volume=a-config:/etc/samba:z \
    --volume=a-shares:/srv/shares:z --volume=a-homes:/srv/homes:z \
    "${image}" new-domain > "${out}/dc1-provision.log" 2>&1; then
    tail -n 50 "${out}/dc1-provision.log"
    fail "DC A provisioning"
    summary
    exit 1
fi
fast_replication_config a-config
start_dc1() {
    podman run --detach --name=dc1 --replace --network="${IT_NETWORK}" --ip="${a_ip}" \
        --hostname="dc1.${domain}" --dns=none --no-hosts \
        --env=REALM="${realm}" --env=IPADDRESS="${a_ip}" --env=NBDOMAIN="${nbdomain}" \
        --volume=a-data:/var/lib/samba:z --volume=a-config:/etc/samba:z \
        --volume=a-shares:/srv/shares --volume=a-homes:/srv/homes \
        "${image}" >/dev/null
    local port
    for port in 53 88 389 3268; do
        poll 180 bash -c "exec 3<>/dev/tcp/${a_ip}/${port}" || return 1
    done
}
if ! start_dc1; then
    podman logs --tail 80 dc1
    fail "DC A start"
    summary
    exit 1
fi
pass "DC A provisioned and listening"

on_a samba-tool user create tabadmin "${tab_pass}" >/dev/null
on_a samba-tool group addmembers "Domain Admins" tabadmin >/dev/null
on_a samba-tool user create plainuser "${user_pass}" >/dev/null

#######################################################################
section "Test 1a: wizard validation against the real DC"
mkdir -p "${state}"
: > "${state}/environment"
wizard_request() {
    jq -n --arg host "$1" --arg ip "${IT_B_IP}" --arg join "$2" --arg user "$3" --arg pass "$4" \
        --arg svc "${service_pass}" --arg realm "${domain}" --arg nb "${nbdomain}" \
        '{adminuser: $user, adminpass: $pass, realm: $realm, nbdomain: $nb, hostname: $host,
          ipaddress: $ip, joinaddress: $join, ldapservice_password: $svc}'
}
run_step "${actions}/configure-remote-domain/03validate_remote" "${work}/03-existing.out" \
    "$(wizard_request dc1 "${a_ip}" administrator x)"
code=$?
check "03validate_remote rejects a hostname already in AD DNS (exit ${code})" \
    bash -c "[[ ${code} == 8 ]] && jq -e '.[0].error == \"hostname_check_failed\"' '${work}/03-existing.out'"
run_step "${actions}/configure-remote-domain/03validate_remote" "${work}/03-unreachable.out" \
    "$(wizard_request dc2 "${unreachable_ip}" administrator x)"
code=$?
check "03validate_remote rejects an unreachable DC (exit ${code})" \
    bash -c "[[ ${code} == 6 ]] && jq -e '.[0].error == \"remote_dc_dns_check_failed\"' '${work}/03-unreachable.out'"
request=$(wizard_request dc2 "${a_ip}" tabadmin "${tab_pass}")
run_step "${actions}/configure-remote-domain/03validate_remote" /dev/null "${request}"
check "03validate_remote accepts the real remote DC" test $? -eq 0
run_step "${actions}/configure-remote-domain/01validate_credentials" /dev/null "${request}"
check "01validate_credentials accepts a password containing a tab" test $? -eq 0
run_step "${actions}/configure-remote-domain/05set_env" /dev/null "${request}"
check "05set_env writes the join environment" \
    bash -c "grep -qx 'HOSTNAME=dc2.${domain}' '${state}/environment' && grep -qx 'JOINADDRESS=${a_ip}' '${state}/environment'"

section "Test 1b: join error handling"
run_step "${actions}/configure-remote-domain/40start_provisioning" "${work}/40-badpass.out" \
    "$(jq -n '{adminuser: "administrator", adminpass: "wrong-password"}')"
code=$?
check "Wrong join password returns exit 33 / invalid_credentials (exit ${code})" \
    bash -c "[[ ${code} == 33 ]] && jq -e '.[0].error == \"invalid_credentials\"' '${work}/40-badpass.out'"
remove_b
printf 'IPADDRESS=%s\n' "${IT_B_IP}" >> "${state}/environment"

run_step "${actions}/configure-remote-domain/40start_provisioning" "${work}/40-plain.out" \
    "$(jq -n --arg p "${user_pass}" '{adminuser: "plainuser", adminpass: $p}')"
code=$?
check "Join without DC-join rights returns exit 34 / insufficient_permissions (exit ${code})" \
    bash -c "[[ ${code} == 34 ]] && jq -e '.[0].error == \"insufficient_permissions\"' '${work}/40-plain.out'"
on_a samba-tool computer list > "${work}/dc1-computers-after-failed-join.txt" 2>&1
if grep -qi '^dc2\$' "${work}/dc1-computers-after-failed-join.txt"; then
    info "Failed join left computer account DC2\$ on DC A"
else
    info "Failed join left no DC2\$ computer account on DC A"
fi
remove_b
grep -q '^IPADDRESS=' "${state}/environment" || printf 'IPADDRESS=%s\n' "${IT_B_IP}" >> "${state}/environment"

section "Test 1c: join DC B (dc2) with a tab in the admin password"
run_step "${actions}/configure-remote-domain/40start_provisioning" "${work}/40-join.out" \
    "$(jq -n --arg p "${tab_pass}" '{adminuser: "tabadmin", adminpass: $p}')"
code=$?
check "40start_provisioning joins DC B (exit ${code})" test "${code}" -eq 0
if [[ ${code} != 0 ]]; then
    summary
    exit 1
fi
fast_replication_config config
(
    set -a; source "${state}/environment"; set +a
    export SAMBA_DC_IMAGE=${image}
    "${repo_root}/integration/bin/systemctl" --user enable --now samba-dc.service
)
check "DC B starts and listens on 53/88/389/3268" test $? -eq 0

section "Test 1d: replication, Kerberos and DNS"
check "DC B inbound replication has no failures" poll 300 replication_clean samba-dc
check "DC A replicates with DC B without failures" poll 300 replication_clean dc1
showrepl samba-dc > "${out}/showrepl-dc2.json"
showrepl dc1 > "${out}/showrepl-dc1.json"
info "Real showrepl 'last success' value: $(jq -c '[.repsFrom[]? | .["last success"]] | .[0]' "${out}/showrepl-dc2.json")"

on_a samba-tool user create itest-a "${user_pass}" >/dev/null
check "User created on DC A replicates to DC B" poll 300 user_exists samba-dc itest-a
on_b samba-tool user create itest-b "${user_pass}" >/dev/null
check "User created on DC B replicates to DC A" poll 300 user_exists dc1 itest-b
check "DC B issues a Kerberos ticket for a user created on DC A" kinit_at "${IT_B_IP}" itest-a "${user_pass}"
check "DC A issues a Kerberos ticket for a user created on DC B" kinit_at "${a_ip}" itest-b "${user_pass}"
check "DNS on DC A resolves dc2" poll 300 dns_a_is "${a_ip}" "dc2.${domain}" "${IT_B_IP}"
check "DNS on DC B resolves dc1" poll 300 dns_a_is "${IT_B_IP}" "dc1.${domain}" "${a_ip}"
check "LDAP SRV on DC A lists dc2" poll 300 dns_srv_has "${a_ip}" dc2
check "LDAP SRV on DC B lists dc1" poll 300 dns_srv_has "${IT_B_IP}" dc1

#######################################################################
section "Test 2: replication monitor and ntfy"
python3 "${repo_root}/integration/lib/ntfy_receiver.py" 18080 "${out}/ntfy.jsonl" &
receiver_pid=$!
poll 30 bash -c 'exec 3<>/dev/tcp/127.0.0.1/18080'

run_monitor
code=$?
check "Monitor on healthy replication: exit 0, no notification (exit ${code})" \
    bash -c "[[ ${code} == 0 && $(ntfy_count) == 0 ]]"

podman stop -t 10 dc1 >/dev/null
on_b samba-tool user create itest-during-outage "${user_pass}" >/dev/null
check "DC B reports repeated inbound failures while DC A is down" poll 420 inbound_failures_at_least 2
showrepl samba-dc > "${out}/showrepl-dc2-outage.json"
run_monitor
check "Monitor sends one replication alert after the threshold" \
    bash -c "[[ $(ntfy_count) == 1 ]] && jq -e 'select(.title | startswith(\"AD replication failed on dc2\"))
        | select(.authorization == \"Bearer itest-token\" and .path == \"/samba%20it\")' '${out}/ntfy.jsonl'"
run_monitor
check "Monitor does not repeat the alert for the same failures" bash -c "[[ $(ntfy_count) == 1 ]]"

podman pause samba-dc >/dev/null
run_monitor
run_monitor
run_monitor
podman unpause samba-dc >/dev/null
check "Probe failure alert is sent once at the threshold" \
    bash -c "[[ $(ntfy_count) == 2 ]] && tail -n 1 '${out}/ntfy.jsonl' | jq -e '.title | startswith(\"AD replication check failed\")'"

start_dc1
check "DC B recovers inbound replication after DC A returns" poll 420 replication_clean samba-dc
run_monitor
check "Monitor clears the incident on recovery without a new alert" \
    bash -c "[[ $(ntfy_count) == 2 ]] && jq -e '.active_replication == [] and .probe_failures == 0' '${work}/monitor-state/ad-replication-monitor-state.json'"
kill "${receiver_pid}" 2>/dev/null
receiver_pid=

#######################################################################
section "Backup DC B like module-dump-state"
# Restore with Samba's default KCC/DRS timing, as on a real node.
podman run --rm --volume=config:/etc/samba:z --entrypoint=/bin/bash "${image}" -c \
    'sed -i "/periodic_interval/d" /etc/samba/include.conf'
on_b bash -c 'cd /var/lib/samba && rm -rf backup && samba-tool domain backup offline --targetdir=backup &&
    mv backup/samba-backup-*.tar.bz2 backup/samba-backup.tar.bz2' > "${out}/backup.log" 2>&1
check "Offline domain backup of DC B" test $? -eq 0
mkdir -p "${work}/backup"
podman run --rm --volume=config:/src/config:z --volume=data:/src/data:z \
    --volume="${work}/backup:/dst:z" --entrypoint=tar "${image}" \
    -C /src -cf /dst/volumes.tar config data/backup
cp "${state}/environment" "${work}/backup/environment"
on_a samba-tool user create itest-after-backup "${user_pass}" >/dev/null

restore_b() {
    "${repo_root}/integration/bin/systemctl" --user stop samba-dc.service
    remove_b
    rm -rf "${state}"
    mkdir -p "${state}"
    cp "${work}/backup/environment" "${state}/environment"
    podman volume create data >/dev/null
    podman volume create config >/dev/null
    podman run --rm --volume=config:/dst/config:z --volume=data:/dst/data:z \
        --volume="${work}/backup:/src:z" --entrypoint=tar "${image}" -C /dst -xf /src/volumes.tar
    local input step
    input=$(jq -n --argjson env "$(environment_json "${state}/environment")" '{environment: $env}')
    if [[ -n ${1:-} ]]; then
        input=$(jq --arg u administrator --arg p "$1" '. + {recovery_adminuser: $u, recovery_adminpass: $p}' <<< "${input}")
    fi
    for step in 04validate_environment 07copy_custom_env 08validate_remote_ip \
        50attempt_remote_rejoin 55rename_forced_dc 60resume_state; do
        printf -- '--- restore-module/%s\n' "${step}" >> "${out}/steps.log"
        run_step "${actions}/restore-module/${step}" /dev/null "${input}" || {
            printf 'restore-module/%s failed\n' "${step}" >&2
            return 1
        }
    done
}

#######################################################################
section "Test 4: restore DC B while DC A is alive (rejoin)"
restore_b "${admin_pass}" 2>&1 | tee "${out}/restore-rejoin.log"
check "Rejoin restore steps complete" test "${PIPESTATUS[0]}" -eq 0
check "Restore mode is 'joined'" grep -qx joined "${state}/remote-restore-mode"
check "Rejoined DC keeps its hostname" bash -c "[[ $(env_value HOSTNAME) == dc2.${domain} ]]"
check "Rejoined DC received a user created after the backup" poll 300 user_exists samba-dc itest-after-backup
on_b samba-tool user create itest-after-rejoin "${user_pass}" >/dev/null
check "User created on the rejoined DC replicates to DC A" poll 300 user_exists dc1 itest-after-rejoin
check "DC A replicates with the rejoined DC without failures" poll 420 replication_clean dc1
showrepl samba-dc > "${out}/showrepl-dc2-rejoined.json"

#######################################################################
section "Test 5: restore DC B while DC A is down (forced)"
podman stop -t 10 dc1 >/dev/null
restore_b 2>&1 | tee "${out}/restore-forced.log"
check "Forced restore steps complete" test "${PIPESTATUS[0]}" -eq 0
check "Restore mode is 'forced'" grep -qx forced "${state}/remote-restore-mode"
check "Forced restore renames the DC to dc2r1" bash -c "[[ $(env_value HOSTNAME) == dc2r1.${domain} ]]"
check "Forced DC is running" "${repo_root}/integration/bin/systemctl" --user is-active --quiet samba-dc.service
check "Forced DC contains a user from the backup" user_exists samba-dc itest-a
if user_exists samba-dc itest-after-backup >/dev/null 2>&1; then
    fail "Forced DC unexpectedly contains a user created after the backup"
else
    pass "Forced DC is an independent copy (no user created after the backup)"
fi
check "Forced DC issues Kerberos tickets" kinit_at "${IT_B_IP}" itest-a "${user_pass}"
showrepl samba-dc > "${out}/showrepl-dc2r1-forced.json" 2>&1
info "Forced DC replication partners: $(jq -c '[.repsFrom[]? | .["DSA"] // .["NTDS DN"]]' "${out}/showrepl-dc2r1-forced.json" 2>/dev/null)"

start_dc1
on_a ldbsearch -H /var/lib/samba/private/sam.ldb -b "CN=Sites,CN=Configuration,${basedn}" \
    objectClass=server dn > "${out}/dc1-servers-after-forced.txt" 2>&1
info "Server objects on DC A after the forced restore: $(grep -o '^dn: CN=[^,]*' "${out}/dc1-servers-after-forced.txt" | cut -d= -f2 | paste -sd ' ')"

summary
exit $((failures > 0))
