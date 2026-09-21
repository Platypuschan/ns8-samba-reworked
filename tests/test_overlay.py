#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
from pathlib import Path
import re
import subprocess
import sys


if len(sys.argv) not in (2, 3):
    raise SystemExit(f"usage: {sys.argv[0]} REPOSITORY_ROOT [EXPORTED_IMAGE_ROOT]")

repository = Path(sys.argv[1]).resolve()
image_root = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else None
action = repository / "overlay/imageroot/actions/configure-remote-domain"
get_monitor = repository / "overlay/imageroot/actions/get-replication-monitor"
set_monitor = repository / "overlay/imageroot/actions/set-replication-monitor"
monitor_bin = repository / "overlay/imageroot/bin/check-ad-replication"

required_files = {
    "validate-input.json",
    "01validate_realm",
    "02validate_ip",
    "02validate_lo",
    "03validate_remote",
    "05set_env",
    "40start_provisioning",
    "60start_service",
    "70update_routes",
    "80advertise_service",
    "80provision_metrics",
    "80start_amld",
    "90bind_user_domain",
}
assert {path.name for path in action.iterdir()} == required_files

schema = json.loads((action / "validate-input.json").read_text())
assert schema["$schema"].endswith("draft-07/schema#")
assert schema["additionalProperties"] is False
assert set(schema["required"]) == {
    "adminuser",
    "adminpass",
    "realm",
    "nbdomain",
    "hostname",
    "ipaddress",
    "joinaddress",
    "ldapservice_password",
}
assert schema["properties"]["adminpass"]["writeOnly"] is True
assert schema["properties"]["ldapservice_password"]["writeOnly"] is True
assert schema["properties"]["joinaddress"]["format"] == "ipv4"

get_monitor_schema = json.loads(
    (get_monitor / "validate-output.json").read_text()
)
assert get_monitor_schema["additionalProperties"] is False
assert set(get_monitor_schema["required"]) == {
    "available",
    "enabled",
    "base_url",
    "topic",
    "failure_threshold",
    "token_configured",
}

set_monitor_schema = json.loads(
    (set_monitor / "validate-input.json").read_text()
)
assert set_monitor_schema["additionalProperties"] is False
assert set(set_monitor_schema["required"]) == {
    "enabled",
    "failure_threshold",
}
assert set_monitor_schema["properties"]["token"]["writeOnly"] is True
assert set_monitor_schema["properties"]["failure_threshold"]["minimum"] == 1
assert set_monitor_schema["properties"]["failure_threshold"]["maximum"] == 1000

assert {path.name for path in get_monitor.iterdir()} == {
    "50read",
    "validate-output.json",
}
assert {path.name for path in set_monitor.iterdir()} == {
    "50set",
    "validate-input.json",
}

for executable in (
    get_monitor / "50read",
    set_monitor / "50set",
    monitor_bin,
    repository / "overlay/imageroot/update-module.d/25remote_join_role",
    repository / "overlay/imageroot/update-module.d/55replication_monitor",
    repository / "scripts/patch-ui.mjs",
):
    assert os.access(executable, os.X_OK), f"file is not executable: {executable}"

python_files = [
    action / "01validate_realm",
    action / "03validate_remote",
    action / "05set_env",
    get_monitor / "50read",
    set_monitor / "50set",
    monitor_bin,
    repository / "overlay/imageroot/actions/create-module/25remote_join_role",
    repository / "overlay/imageroot/update-module.d/25remote_join_role",
    repository / "scripts/next-version.py",
    repository / "tests/test_overlay.py",
    repository / "tests/test_replication_monitor.py",
]
for path in python_files:
    compile(path.read_text(), str(path), "exec")

shell_files = [
    path
    for path in repository.rglob("*")
    if path.is_file() and path.read_bytes().startswith(b"#!/bin/bash")
]
for path in shell_files:
    subprocess.run(["bash", "-n", str(path)], check=True)

for path in action.iterdir():
    if path.name != "validate-input.json":
        assert os.access(path, os.X_OK), f"action step is not executable: {path}"

set_env = (action / "05set_env").read_text()
assert 'agent.set_env("SVCUSER", "ldapservice")' in set_env
assert 'request["ldapservice_password"]' in set_env
assert 'agent.set_env("JOINADDRESS", request["joinaddress"])' in set_env
assert "secrets" not in set_env

provision = (action / "40start_provisioning").read_text()
assert '"${JOINADDRESS:?}"' in provision
assert "print-joinaddress" not in provision
assert '"${SAMBA_DC_IMAGE:?}" "${PROVISION_TYPE:?}"' in provision

remote_validation = (action / "03validate_remote").read_text()
for port in (53, 88, 135, 389, 445):
    assert re.search(rf"\b{port}\b", remote_validation)
assert "_ldap._tcp.dc._msdcs" in remote_validation

monitor_code = monitor_bin.read_text()
assert '"samba-tool"' in monitor_code
assert '"showrepl"' in monitor_code
assert '"--json"' in monitor_code
assert '"consecutive failures"' in monitor_code
assert 'headers["Authorization"] = "Bearer " + token' in monitor_code
assert "urlopen(request, timeout=15)" in monitor_code

role_code = (
    repository / "overlay/imageroot/actions/create-module/25remote_join_role"
).read_text()
for permitted_action in (
    "configure-remote-domain",
    "get-replication-monitor",
    "set-replication-monitor",
):
    assert permitted_action in role_code

service = (
    repository
    / "overlay/imageroot/systemd/user/ad-replication-monitor.service"
).read_text()
timer = (
    repository
    / "overlay/imageroot/systemd/user/ad-replication-monitor.timer"
).read_text()
assert "ExecStart=runagent check-ad-replication" in service
assert "OnUnitActiveSec=5min" in timer
assert "Persistent=true" in timer

wrapper_targets = {
    "02validate_ip": "02validate_ip",
    "02validate_lo": "02validate_lo",
    "60start_service": "60start_service",
    "70update_routes": "70update_routes",
    "80advertise_service": "80advertise_service",
    "80provision_metrics": "80provision_metrics",
    "80start_amld": "80start_amld",
    "90bind_user_domain": "90bind_user_domain",
}
for wrapper, target in wrapper_targets.items():
    expected = f"/actions/configure-module/{target}"
    assert expected in (action / wrapper).read_text()

overlay_paths = [path.as_posix().lower() for path in (repository / "overlay").rglob("*")]
assert not any("samba-dc" in path for path in overlay_paths)
overlay_code = "\n".join(
    path.read_text(errors="replace")
    for path in (repository / "overlay").rglob("*")
    if path.is_file()
)
assert "sysvol" not in overlay_code.lower()
assert "logon script" not in overlay_code.lower()

containerfile = (repository / "Containerfile").read_text()
assert "FROM ghcr.io/nethserver/samba:${UPSTREAM_VERSION}" in containerfile
assert "COPY overlay/ /" in containerfile
assert "FROM docker.io/library/node:24-slim AS ui-builder" in containerfile
assert "scripts/patch-ui.mjs" in containerfile
assert "COPY --from=ui-builder /usr/src/ui/dist/ /ui/" in containerfile

first_configuration = (
    repository
    / "ui-overlay/src/components/FirstConfigurationModal.vue"
).read_text()
replication_notifications = (
    repository
    / "ui-overlay/src/components/ReplicationNotifications.vue"
).read_text()
ui_patch = (repository / "scripts/patch-ui.mjs").read_text()
assert "configure-remote-domain" in first_configuration
assert "ldapservice_password" in first_configuration
assert "set-replication-monitor" in replication_notifications
assert "ReplicationNotifications" in ui_patch

for version_file in ("UPSTREAM_VERSION", "CUSTOM_VERSION"):
    version = (repository / version_file).read_text().strip()
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), version

if image_root is not None:
    installed_action = image_root / "imageroot/actions/configure-remote-domain"
    assert installed_action.is_dir()
    for filename in required_files:
        assert (installed_action / filename).is_file()
    for filename in required_files - {"validate-input.json"}:
        assert os.access(installed_action / filename, os.X_OK)
    for target in wrapper_targets.values():
        upstream_target = image_root / "imageroot/actions/configure-module" / target
        assert upstream_target.is_file(), f"upstream action step disappeared: {target}"
        assert os.access(upstream_target, os.X_OK)
    assert (
        image_root / "imageroot/actions/create-module/25remote_join_role"
    ).is_file()
    assert (
        image_root / "imageroot/bin/check-ad-replication"
    ).is_file()
    assert (
        image_root
        / "imageroot/systemd/user/ad-replication-monitor.timer"
    ).is_file()

    ui_root = image_root / "ui"
    assert (ui_root / "index.html").is_file()
    compiled_ui = b"\n".join(
        path.read_bytes()
        for path in ui_root.rglob("*")
        if path.is_file() and path.suffix in {".js", ".json"}
    )
    assert b"configure-remote-domain" in compiled_ui
    assert b"set-replication-monitor" in compiled_ui

print("Overlay checks passed.")
