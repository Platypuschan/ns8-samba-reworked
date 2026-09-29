#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import base64
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

    def test_restore_rejects_multiline_backup_before_upstream_copy(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        agent.set_env = mock.Mock()
        for field in ("SVCPASS", "NTFY_REPLICATION_TOKEN"):
            with self.subTest(field=field), self.assertRaises(SystemExit) as caught:
                self.run_action(
                    ACTIONS / "restore-module/04validate_environment",
                    {"environment": {field: "secret\nIPADDRESS=10.5.4.1"}},
                    {"agent": agent},
                )
            self.assertEqual(caught.exception.code, 2)
        agent.set_env.assert_not_called()
        agent.set_status.assert_called_with("validation-failed")

    def test_restore_rejects_malformed_one_time_credentials_before_copy(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        agent.set_env = mock.Mock()
        valid = {"environment": {"PROVISION_MODE": "join-remote-domain"},
                 "recovery_adminuser": "Administrator", "recovery_adminpass": "secret"}
        cases = (
            ("recovery_adminuser", "Admin\nistrator", "invalid_join_credentials_linebreak"),
            ("recovery_adminpass", "secret\rmore", "invalid_join_credentials_linebreak"),
            ("recovery_adminuser", "Admin\tistrator", "invalid_join_credentials_control_character"),
            ("recovery_adminpass", "secret\x00more", "invalid_join_credentials_control_character"),
            ("recovery_adminpass", "", "invalid_recovery_credentials"),
            ("recovery_adminuser", 42, "invalid_recovery_credentials"),
        )
        for field, value, code in cases:
            with self.subTest(field=field, value=repr(value)):
                output = io.StringIO()
                with mock.patch.dict(sys.modules, {"agent": agent}), mock.patch.object(
                    sys, "stdin", io.StringIO(json.dumps({**valid, field: value}))
                ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        runpy.run_path(str(ACTIONS / "restore-module/04validate_environment"),
                                       run_name="__main__")
                self.assertEqual(caught.exception.code, 2)
                error = json.loads(output.getvalue())[0]
                self.assertEqual((error["field"], error["error"], error["value"]),
                                 (field, code, ""))
                if value:
                    self.assertNotIn(str(value), output.getvalue())
        for missing in ("recovery_adminuser", "recovery_adminpass"):
            with self.subTest(missing=missing):
                payload = {key: value for key, value in valid.items() if key != missing}
                with self.assertRaises(SystemExit) as caught:
                    self.run_action(ACTIONS / "restore-module/04validate_environment",
                                    payload, {"agent": agent})
                self.assertEqual(caught.exception.code, 2)
        agent.set_env.assert_not_called()
        agent.set_status.assert_called_with("validation-failed")
        self.run_action(ACTIONS / "restore-module/04validate_environment",
                        {"environment": valid["environment"]}, {"agent": agent})
        self.run_action(ACTIONS / "restore-module/04validate_environment",
                        {**valid, "recovery_adminpass": "\tsecret\t"}, {"agent": agent})

    def test_configuration_rejects_multiline_service_password(self):
        agent = types.ModuleType("agent")
        agent.set_env = mock.Mock()
        agent.set_status = mock.Mock()
        with mock.patch.dict(os.environ, {"MODULE_ID": "samba1"}):
            with self.assertRaises(SystemExit) as caught:
                self.run_action(
                    ACTIONS / "configure-remote-domain/05set_env",
                    {"realm": "ad.example.org", "ldapservice_password": "secret\nIPADDRESS=10.5.4.1"},
                    {"agent": agent},
                )
        self.assertEqual(caught.exception.code, 2)
        agent.set_env.assert_not_called()

    def test_join_credentials_reject_linebreaks_without_echoing_secrets(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        payload = {"adminuser": "Administrator", "adminpass": "secret"}
        for field, value in (("adminuser", "Admin\nother"),
                             ("adminpass", "secret\rsecond")):
            with self.subTest(field=field):
                output = io.StringIO()
                with mock.patch.dict(sys.modules, {"agent": agent}), mock.patch.object(
                    sys, "stdin", io.StringIO(json.dumps({**payload, field: value}))
                ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        runpy.run_path(str(ACTIONS / "configure-remote-domain/01validate_credentials"),
                                       run_name="__main__")
                self.assertEqual(caught.exception.code, 2)
                error = json.loads(output.getvalue())[0]
                self.assertEqual(error["field"], field)
                self.assertEqual(error["value"], "")
                self.assertEqual(error["error"], "invalid_join_credentials_linebreak")
                self.assertNotIn(value, output.getvalue())
        agent.set_status.assert_called_with("validation-failed")
        self.run_action(ACTIONS / "configure-remote-domain/01validate_credentials",
                        payload, {"agent": agent})
        for field, value in (("adminuser", "Admin\tother"),
                             ("adminuser", "Admin\x00other"),
                             ("adminpass", "secret\x00more")):
            with self.subTest(field=field, value=repr(value)):
                output = io.StringIO()
                with mock.patch.dict(sys.modules, {"agent": agent}), mock.patch.object(
                    sys, "stdin", io.StringIO(json.dumps({**payload, field: value}))
                ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        runpy.run_path(str(ACTIONS / "configure-remote-domain/01validate_credentials"),
                                       run_name="__main__")
                self.assertEqual(caught.exception.code, 2)
                error = json.loads(output.getvalue())[0]
                self.assertEqual((error["field"], error["error"], error["value"]),
                                 (field, "invalid_join_credentials_control_character", ""))
                self.assertNotIn(value, output.getvalue())
        self.run_action(ACTIONS / "configure-remote-domain/01validate_credentials",
                        {**payload, "adminpass": "\tsecret\t"}, {"agent": agent})

    def test_monitor_rejects_multiline_settings_even_when_disabled(self):
        agent = types.ModuleType("agent")
        agent.set_env = mock.Mock()
        agent.set_status = mock.Mock()
        for field in ("base_url", "topic", "token"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                with mock.patch.dict(os.environ, {"SERVER_ROLE": "dc", "AGENT_STATE_DIR": directory}, clear=True):
                    with self.assertRaises(SystemExit) as caught:
                        self.run_action(
                            ACTIONS / "set-replication-monitor/50set",
                            {"enabled": False, "failure_threshold": 2,
                             field: "value\rIPADDRESS=10.5.4.1"},
                            {"agent": agent},
                        )
                self.assertEqual(caught.exception.code, 2)
        agent.set_env.assert_not_called()

    def test_set_ipaddress_rejects_vpn_only_for_remote_dc(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        rdb = mock.MagicMock()
        rdb.__enter__.return_value.get.return_value = "10.5.4.0/24"
        agent.redis_connect = mock.Mock(return_value=rdb)
        script = ACTIONS / "set-ipaddress/02validate_remote_ip"
        payload = {"ipaddress": "10.5.4.7"}
        with mock.patch.dict(os.environ, {"PROVISION_MODE": "join-remote-domain"}):
            with self.assertRaises(SystemExit) as caught:
                self.run_action(script, payload, {"agent": agent})
            self.assertEqual(caught.exception.code, 2)
            self.run_action(script, {"ipaddress": "192.0.2.7"}, {"agent": agent})
        with mock.patch.dict(os.environ, {"PROVISION_MODE": "new-domain"}):
            self.run_action(script, payload, {"agent": agent})
        agent.set_status.assert_called_once_with("validation-failed")

    def test_remote_restore_rejects_upstream_vpn_fallback(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        rdb = mock.MagicMock()
        rdb.__enter__.return_value.get.return_value = "10.5.4.0/24"
        agent.redis_connect = mock.Mock(return_value=rdb)
        request = {"environment": {"PROVISION_MODE": "join-remote-domain"}}
        with mock.patch.dict(os.environ, {"IPADDRESS": "10.5.4.7"}):
            with self.assertRaises(SystemExit) as caught:
                self.run_action(
                    ACTIONS / "restore-module/08validate_remote_ip", request,
                    {"agent": agent},
                )
        self.assertEqual(caught.exception.code, 2)
        agent.set_status.assert_called_once_with("validation-failed")

        with mock.patch.dict(os.environ, {"IPADDRESS": ""}):
            with self.assertRaises(SystemExit) as caught:
                self.run_action(ACTIONS / "restore-module/08validate_remote_ip",
                                request, {"agent": agent})
        self.assertEqual(caught.exception.code, 2)

        with mock.patch.dict(os.environ, {"IPADDRESS": "192.0.2.4"}):
            self.run_action(ACTIONS / "restore-module/08validate_remote_ip",
                            request, {"agent": agent})
        self.assertEqual(agent.set_status.call_count, 2)

    # samba-tool drs showrepl --json formats timestamps with nttime2string.
    SAMBA_SUCCESS = '"Mon Sep 28 19:12:25 2026 UTC"'
    SAMBA_NEVER = '"NTTIME(0)"'

    def run_remote_restore(self, join_exit=0, drs_exit=0, drs_failures=0,
                           drs_last_success=SAMBA_SUCCESS, drs_to_failures=0,
                           drs_to_last_success=SAMBA_SUCCESS,
                           credentials=None, restore_audit=False):
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
                "      sed -n 's/^ADMINUSER_B64=//p' \"${argument#*=}\" | base64 -d > \"$FAKE_CREDS.user\"\n"
                "      sed -n 's/^ADMINPASS_B64=//p' \"${argument#*=}\" | base64 -d > \"$FAKE_CREDS.pass\"\n"
                "      grep -c '^REUSE_BACKUP_MACHINEPASS=1$' \"${argument#*=}\" > \"$FAKE_CREDS.reuse\" || true\n"
                "    fi\n"
                "  done\n"
                "  exit \"$FAKE_JOIN_EXIT\"\n"
                "fi\n"
                "if [[ $* == *'--entrypoint=/bin/bash'* ]]; then exit 0; fi\n"
                "if [[ $* == *'drs showrepl --json'* ]]; then\n"
                "  printf '{\"repsFrom\":[{\"consecutive failures\":%s,\"last success\":%s}],\"repsTo\":[{\"consecutive failures\":%s,\"last success\":%s}]}\\n' \"$FAKE_DRS_FAILURES\" \"$FAKE_DRS_LAST_SUCCESS\" \"$FAKE_DRS_TO_FAILURES\" \"$FAKE_DRS_TO_LAST_SUCCESS\"\n"
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
                "FAKE_DRS_LAST_SUCCESS": drs_last_success,
                "FAKE_DRS_TO_FAILURES": str(drs_to_failures),
                "FAKE_DRS_TO_LAST_SUCCESS": drs_to_last_success,
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
            agent = types.ModuleType("agent")
            agent.set_env = mock.Mock(
                side_effect=lambda name, value: environment.__setitem__(name, value)
            )
            with mock.patch.dict(os.environ, environment):
                try:
                    rename_log = self.run_action(
                        ACTIONS / "restore-module/55rename_forced_dc", {},
                        {"agent": agent},
                    )
                except SystemExit as caught:
                    self.assertEqual(caught.code, 0)
                    rename_log = ""
            restore = subprocess.run(
                ["bash", str(ACTIONS / "restore-module/60resume_state")],
                text=True, capture_output=True, cwd=work, env=environment, check=False,
            )
            self.assertEqual(restore.returncode, 0, restore.stderr)
            self.reused_machine_password = (work / "creds.reuse").read_text().strip() == "1"
            return (calls.read_text(), (work / "remote-restore-mode").read_text(),
                    ((work / "creds.user").read_text(), (work / "creds.pass").read_text()),
                    join.stderr + rename_log + restore.stderr,
                    environment["HOSTNAME"])

    def test_remote_restore_rejoins_when_domain_and_credentials_work(self):
        calls, mode, credentials, logs, hostname = self.run_remote_restore(restore_audit=True, credentials={
            "recovery_adminuser": "Administrator", "recovery_adminpass": "once-only",
        })
        self.assertEqual(mode, "joined\n")
        self.assertEqual(credentials, ("Administrator", "once-only"))
        self.assertTrue(self.reused_machine_password)
        self.assertEqual(hostname, "dc2r1.ad.example.org")
        self.assertIn("drs showrepl --json", calls)
        self.assertNotIn("samba-tool domain backup restore", calls)
        self.assertNotIn("once-only", logs)
        self.assertLess(calls.index("--name=timescaledb"), calls.index("/run/join-domain-checked"))
        self.assertEqual(calls.count("--name=timescaledb"), 1)

    def test_remote_restore_forces_domain_backup_after_join_failure(self):
        calls, mode, credentials, logs, hostname = self.run_remote_restore(join_exit=34)
        self.assertEqual(mode, "forced\n")
        self.assertEqual(credentials, ("ldapservice", "saved-service-secret"))
        self.assertIn("samba-tool domain backup restore", calls)
        self.assertEqual(hostname, "dc2r2.ad.example.org")
        self.assertIn("--hostname=dc2r2.ad.example.org", calls)
        self.assertIn("FORCED RESTORE", logs)
        self.assertNotIn("saved-service-secret", logs)

    def test_remote_restore_forces_domain_backup_after_drs_failure(self):
        calls, mode, _, _, hostname = self.run_remote_restore(drs_failures=3)
        self.assertEqual(mode, "forced\n")
        self.assertEqual(hostname, "dc2r2.ad.example.org")
        self.assertIn("systemctl --user stop samba-dc.service", calls)
        self.assertIn("samba-tool domain backup restore", calls)

    def test_remote_restore_forces_domain_backup_without_inbound_success(self):
        calls, mode, _, _, hostname = self.run_remote_restore(drs_last_success=self.SAMBA_NEVER)
        self.assertEqual(mode, "forced\n")
        self.assertEqual(hostname, "dc2r2.ad.example.org")
        self.assertIn("samba-tool domain backup restore", calls)

    def test_remote_restore_warns_if_outbound_status_is_not_yet_confirmed(self):
        calls, mode, _, logs, hostname = self.run_remote_restore(
            drs_to_last_success=self.SAMBA_NEVER)
        self.assertEqual(mode, "joined\n")
        self.assertEqual(hostname, "dc2r1.ad.example.org")
        self.assertNotIn("samba-tool domain backup restore", calls)
        self.assertIn("Outbound DRS notification is not confirmed", logs)

    def test_remote_restore_preserves_password_tabs(self):
        _, mode, credentials, _, _ = self.run_remote_restore(credentials={
            "recovery_adminuser": "Administrator", "recovery_adminpass": "\tsecret\t",
        })
        self.assertEqual(mode, "joined\n")
        self.assertEqual(credentials, ("Administrator", "\tsecret\t"))

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

    def test_initial_join_preserves_password_tabs(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            fake_podman = work / "podman"
            fake_podman.write_text(
                "#!/bin/bash\n"
                "for argument; do\n"
                "  if [[ $argument == --env-file=* ]]; then\n"
                "    cp \"${argument#*=}\" \"$FAKE_ENV_FILE\"\n"
                "  fi\n"
                "done\n"
                "exit 1\n"
            )
            fake_podman.chmod(0o755)
            (work / "environment").write_text("IPADDRESS=192.0.2.4\n")
            stored = work / "join.env"
            result = subprocess.run(
                ["bash", str(ACTIONS / "configure-remote-domain/40start_provisioning")],
                input=json.dumps({"adminuser": "Administrator", "adminpass": "\tsecret\t"}),
                text=True, capture_output=True, cwd=work, check=False,
                env={**os.environ, "PODMAN_BIN": str(fake_podman),
                     "FAKE_ENV_FILE": str(stored), "PROVISION_TYPE": "join-domain",
                     "JOINADDRESS": "192.0.2.3", "HOSTNAME": "dc2.example.org",
                     "SAMBA_DC_IMAGE": "samba:test", "AGENT_INSTALL_DIR": str(ROOT / "overlay/imageroot")},
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            values = dict(line.split("=", 1) for line in stored.read_text().splitlines())
            self.assertEqual(base64.b64decode(values["ADMINUSER_B64"]).decode(), "Administrator")
            self.assertEqual(base64.b64decode(values["ADMINPASS_B64"]).decode(), "\tsecret\t")
            self.assertNotIn("secret", stored.read_text())
            self.assertNotIn("REUSE_BACKUP_MACHINEPASS", stored.read_text())


if __name__ == "__main__":
    unittest.main()
