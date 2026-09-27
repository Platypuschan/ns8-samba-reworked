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

    def test_restore_refuses_remote_dc_before_upstream_copy(self):
        agent = types.ModuleType("agent")
        agent.set_weight = mock.Mock()
        agent.set_status = mock.Mock()
        with self.assertRaises(SystemExit) as caught:
            self.run_action(
                ACTIONS / "restore-module/04reject_remote_domain",
                {"environment": {"PROVISION_MODE": "join-remote-domain"}},
                {"agent": agent},
            )
        self.assertEqual(caught.exception.code, 2)
        agent.set_status.assert_called_once_with("validation-failed")

    def test_restore_preserves_monitor_settings_for_allowed_backup(self):
        agent = types.ModuleType("agent")
        agent.set_env = mock.Mock()
        environment = {
            "PROVISION_MODE": "join-domain",
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

    def test_false_success_from_upstream_join_does_not_start_dc(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            fake_podman = work / "podman"
            fake_podman.write_text(
                "#!/bin/bash\n"
                "if [[ $* == *--entrypoint=/bin/bash* ]]; then\n"
                "  echo '{\"repsFrom\":[]}'\n"
                "fi\n"
                "exit 0\n"
            )
            fake_podman.chmod(0o755)
            environment_file = work / "environment"
            environment_file.write_text("IPADDRESS=192.0.2.4\nREALM=AD.EXAMPLE.ORG\n")
            environment = {
                **os.environ,
                "PODMAN_BIN": str(fake_podman),
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
                "if [[ $* == *--entrypoint=/bin/bash* ]]; then\n"
                "  echo '{\"repsFrom\":[{\"consecutive failures\":0}]}'\n"
                "fi\n"
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
