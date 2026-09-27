#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / "overlay/imageroot/actions"


class RemoteLifecycleTests(unittest.TestCase):
    def run_action(self, path, payload, modules):
        output = io.StringIO()
        with mock.patch.dict(sys.modules, modules), mock.patch.object(
            sys, "stdin", io.StringIO(json.dumps(payload))
        ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(path), run_name="__main__")
        return output.getvalue()

    def test_restore_preserves_remote_join_and_monitor_settings(self):
        agent = types.ModuleType("agent")
        agent.set_env = mock.Mock()
        environment = {
            "PROVISION_MODE": "join-remote-domain",
            "JOINADDRESS": "192.0.2.3",
            "NTFY_REPLICATION_ENABLED": "1",
            "NTFY_REPLICATION_FAILURE_THRESHOLD": "5",
            "NTFY_REPLICATION_BASE_URL": "https://ntfy.example.org",
            "NTFY_REPLICATION_TOPIC": "replication",
            "NTFY_REPLICATION_TOKEN": "secret",
        }
        self.run_action(
            ACTIONS / "restore-module/07copy_custom_env",
            {"environment": environment},
            {"agent": agent},
        )
        self.assertEqual(dict(call.args for call in agent.set_env.call_args_list), environment)

    def run_remote_restore(self, join_exit=0, drs_exit=0, drs_failures=0, credentials=None,
                           restore_audit=False):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            calls = work / "calls"
            fake_podman = bin_dir / "podman"
            fake_podman.write_text(
                "#!/bin/bash\n"
                "printf 'podman %s\\n' \"$*\" >> \"$FAKE_CALLS\"\n"
                "if [[ $* == 'volume exists timescaledb' ]]; then\n"
                "  [[ -f $FAKE_TIMESCALE_VOLUME ]]\n"
                "  exit $?\n"
                "fi\n"
                "if [[ $* == *'--name=timescaledb'* ]]; then\n"
                "  touch \"$FAKE_TIMESCALE_VOLUME\"\n"
                "  exit 0\n"
                "fi\n"
                "if [[ $* == *'/run/join-domain-checked'* ]]; then\n"
                "  for argument; do\n"
                "    if [[ $argument == --env-file=* ]]; then\n"
                "      sed -n 's/^ADMINCREDS=//p' \"${argument#*=}\" | base64 -d > \"$FAKE_CREDS\"\n"
                "    fi\n"
                "  done\n"
                "  exit \"$FAKE_JOIN_EXIT\"\n"
                "fi\n"
                "if [[ $* == *'--entrypoint=/bin/bash'* ]]; then exit 0; fi\n"
                "if [[ $* == *'drs showrepl --json'* ]]; then\n"
                "  printf '{\"repsFrom\":[{\"consecutive failures\":%s}]}\\n' \"$FAKE_DRS_FAILURES\"\n"
                "  exit \"$FAKE_DRS_EXIT\"\n"
                "fi\n"
                "if [[ $* == *'--workdir=/var/lib/samba'* ]]; then\n"
                "  cat >> \"$FAKE_CALLS\"\n"
                "fi\n"
                "exit 0\n"
            )
            fake_podman.chmod(0o755)
            systemctl = bin_dir / "systemctl"
            systemctl.write_text(
                "#!/bin/bash\n"
                "printf 'systemctl %s\\n' \"$*\" >> \"$FAKE_CALLS\"\n"
                "if [[ $* == *'is-active --quiet'* ]]; then exit 1; fi\n"
            )
            systemctl.chmod(0o755)
            sleep = bin_dir / "sleep"
            sleep.write_text("#!/bin/bash\nexit 0\n")
            sleep.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": str(bin_dir) + ":" + os.environ["PATH"],
                "PODMAN_BIN": str(fake_podman),
                "FAKE_CALLS": str(calls),
                "FAKE_CREDS": str(work / "creds"),
                "FAKE_TIMESCALE_VOLUME": str(work / "timescale-volume"),
                "FAKE_JOIN_EXIT": str(join_exit),
                "FAKE_DRS_EXIT": str(drs_exit),
                "FAKE_DRS_FAILURES": str(drs_failures),
                "AGENT_STATE_DIR": str(work),
                "AGENT_INSTALL_DIR": str(ROOT / "overlay/imageroot"),
                "PROVISION_MODE": "join-remote-domain",
                "PROVISION_TYPE": "join-domain",
                "SERVER_ROLE": "dc",
                "IPADDRESS": "192.0.2.4",
                "HOSTNAME": "dc2r1.ad.example.org",
                "REALM": "AD.EXAMPLE.ORG",
                "JOINADDRESS": "192.0.2.3",
                "SVCUSER": "ldapservice",
                "SVCPASS": "saved-service-secret",
                "SAMBA_DC_IMAGE": "samba:test",
                "TIMESCALEDB_IMAGE": "timescale:test",
            }
            if restore_audit:
                (work / "timescaledb.env").write_text("SAMBA_AUDIT_PASSWORD=placeholder\n")
            audit = subprocess.run(
                ["bash", str(ACTIONS / "restore-module/40restore_timescaledb")],
                text=True, capture_output=True, cwd=work, env=environment, check=False,
            )
            self.assertEqual(audit.returncode, 0, audit.stderr)
            join = subprocess.run(
                ["bash", str(ACTIONS / "restore-module/50attempt_remote_rejoin")],
                input=json.dumps(credentials or {}), text=True, capture_output=True,
                cwd=work, env=environment, check=False,
            )
            self.assertEqual(join.returncode, 0, join.stderr)
            restore = subprocess.run(
                ["bash", str(ACTIONS / "restore-module/60resume_state")],
                text=True, capture_output=True, cwd=work, env=environment, check=False,
            )
            self.assertEqual(restore.returncode, 0, restore.stderr)
            return (calls.read_text(), (work / "remote-restore-mode").read_text(),
                    (work / "creds").read_text(), join.stderr + restore.stderr)

    def test_remote_restore_rejoins_when_domain_and_credentials_work(self):
        calls, mode, credentials, logs = self.run_remote_restore(restore_audit=True, credentials={
            "recovery_adminuser": "Administrator", "recovery_adminpass": "once-only",
        })
        self.assertEqual(mode, "joined\n")
        self.assertEqual(credentials, "Administrator\tonce-only")
        self.assertIn("drs showrepl --json", calls)
        self.assertNotIn("samba-tool domain backup restore", calls)
        self.assertNotIn("once-only", logs)
        self.assertLess(calls.index("--name=timescaledb"), calls.index("/run/join-domain-checked"))
        self.assertEqual(calls.count("--name=timescaledb"), 1)

    def test_remote_restore_forces_domain_backup_after_join_failure(self):
        calls, mode, credentials, logs = self.run_remote_restore(join_exit=34)
        self.assertEqual(mode, "forced\n")
        self.assertEqual(credentials, "ldapservice\tsaved-service-secret")
        self.assertIn("samba-tool domain backup restore", calls)
        self.assertIn("FORCED RESTORE", logs)
        self.assertNotIn("saved-service-secret", logs)

    def test_remote_restore_forces_domain_backup_after_drs_failure(self):
        calls, mode, _, _ = self.run_remote_restore(drs_failures=3)
        self.assertEqual(mode, "forced\n")
        self.assertIn("systemctl --user stop samba-dc.service", calls)
        self.assertIn("samba-tool domain backup restore", calls)

    def test_cli_rejects_cluster_vpn_dc_address(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        rdb = mock.MagicMock()
        rdb.__enter__.return_value.get.return_value = "10.5.0.0/16"
        agent.redis_connect = mock.Mock(return_value=rdb)
        dns = types.ModuleType("dns")
        dns.__path__ = []
        dns.exception = types.ModuleType("dns.exception")
        dns.resolver = types.ModuleType("dns.resolver")
        output = io.StringIO()
        with mock.patch.dict(sys.modules, {
            "agent": agent, "dns": dns, "dns.exception": dns.exception,
            "dns.resolver": dns.resolver,
        }), mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
            "realm": "ad.example.org", "hostname": "dc2",
            "ipaddress": "10.5.0.2", "joinaddress": "192.0.2.3",
        }))), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(ACTIONS / "configure-remote-domain/03validate_remote"))
        self.assertEqual(caught.exception.code, 10)
        self.assertEqual(json.loads(output.getvalue())[0]["error"], "dc_vpn_address_forbidden")

    def test_failed_or_incomplete_join_does_not_start_dc(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            fake_podman = work / "podman"
            fake_podman.write_text(
                "#!/bin/bash\n"
                "if [[ $* == *--entrypoint=/bin/bash* ]]; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 0\n"
            )
            fake_podman.chmod(0o755)
            environment_file = work / "environment"
            environment_file.write_text("IPADDRESS=192.0.2.4\nREALM=AD.EXAMPLE.ORG\n")
            environment = {
                **os.environ,
                "PODMAN_BIN": str(fake_podman),
                "AGENT_INSTALL_DIR": str(ROOT / "overlay/imageroot"),
                "JOINADDRESS": "192.0.2.3",
                "SAMBA_DC_IMAGE": "samba:test",
                "PROVISION_TYPE": "join-domain",
                "HOSTNAME": "dc2.ad.example.org",
            }
            result = subprocess.run(
                ["bash", str(ACTIONS / "configure-remote-domain/40start_provisioning")],
                input='{"adminuser":"Administrator","adminpass":"test"}',
                text=True,
                capture_output=True,
                cwd=work,
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("IPADDRESS=", environment_file.read_text())

            fake_podman.write_text(
                "#!/bin/bash\n"
                "exit 0\n"
            )
            environment_file.write_text("IPADDRESS=192.0.2.4\nREALM=AD.EXAMPLE.ORG\n")
            result = subprocess.run(
                ["bash", str(ACTIONS / "configure-remote-domain/40start_provisioning")],
                input='{"adminuser":"Administrator","adminpass":"test"}',
                text=True,
                capture_output=True,
                cwd=work,
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("IPADDRESS=192.0.2.4", environment_file.read_text())


if __name__ == "__main__":
    unittest.main()
