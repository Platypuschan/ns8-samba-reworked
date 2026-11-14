#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

"""The ntfy token lives in a private file, never in the module environment."""

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
IMAGEROOT = ROOT / "overlay/imageroot"
sys.path.insert(0, str(IMAGEROOT / "pypkg"))
import replication_token  # noqa: E402


class ReplicationTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"AGENT_STATE_DIR": self.tmp.name, "SERVER_ROLE": "dc"}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.agent = types.ModuleType("agent")
        self.agent.set_env = mock.Mock()
        self.agent.unset_env = mock.Mock()
        self.agent.set_status = mock.Mock()

    def run_script(self, path, payload=None):
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"agent": self.agent}), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload or {}))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                runpy.run_path(str(path), run_name="__main__")
            except SystemExit as exit_request:
                if exit_request.code not in (None, 0):
                    raise
        return out.getvalue()

    # helper

    def test_written_private_and_read_back(self):
        replication_token.write("tk_secret")
        stored = replication_token.path()
        self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o600)
        self.assertEqual(replication_token.read(), "tk_secret")
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], [replication_token.NAME])

    def test_rejects_empty_and_multiline_tokens(self):
        for bad in ("", "a\nb", "a\rb"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                replication_token.write(bad)
        self.assertEqual(replication_token.read(), "")

    # update hook

    def hook(self):
        return IMAGEROOT / "update-module.d/54migrate_replication_token"

    def test_hook_moves_the_token_and_clears_the_environment(self):
        os.environ["NTFY_REPLICATION_TOKEN"] = "tk_old"
        self.run_script(self.hook())
        self.assertEqual(replication_token.read(), "tk_old")
        self.agent.unset_env.assert_called_once_with("NTFY_REPLICATION_TOKEN")

    def test_hook_without_a_token_does_nothing(self):
        self.run_script(self.hook())
        self.assertEqual(replication_token.read(), "")
        self.agent.unset_env.assert_not_called()

    def test_hook_keeps_the_newer_file_and_drops_the_stale_environment_value(self):
        replication_token.write("tk_new")
        os.environ["NTFY_REPLICATION_TOKEN"] = "tk_old"
        self.run_script(self.hook())
        self.assertEqual(replication_token.read(), "tk_new")
        self.agent.unset_env.assert_called_once_with("NTFY_REPLICATION_TOKEN")

    def test_hook_keeps_the_environment_value_if_the_file_cannot_be_written(self):
        os.environ["NTFY_REPLICATION_TOKEN"] = "tk_old"
        os.environ["AGENT_STATE_DIR"] = str(Path(self.tmp.name) / "missing")
        with self.assertRaises(OSError):
            self.run_script(self.hook())
        self.agent.unset_env.assert_not_called()

    def test_hook_is_repeatable(self):
        os.environ["NTFY_REPLICATION_TOKEN"] = "tk_old"
        self.run_script(self.hook())
        del os.environ["NTFY_REPLICATION_TOKEN"]
        self.run_script(self.hook())
        self.assertEqual(replication_token.read(), "tk_old")

    # actions

    def set_monitor(self, **request):
        return self.run_script(IMAGEROOT / "actions/set-replication-monitor/50set", {
            "enabled": False, "failure_threshold": 2, **request})

    def run_set_monitor(self, **request):
        with mock.patch("subprocess.run"):
            return self.set_monitor(**request)

    def test_set_stores_the_token_in_the_file_only(self):
        self.run_set_monitor(token="tk_secret")
        self.assertEqual(replication_token.read(), "tk_secret")
        names = [call.args[0] for call in self.agent.set_env.call_args_list]
        self.assertNotIn("NTFY_REPLICATION_TOKEN", names)

    def test_set_removes_a_leftover_environment_token(self):
        os.environ["NTFY_REPLICATION_TOKEN"] = "tk_old"
        self.run_set_monitor(token="tk_new")
        self.agent.unset_env.assert_called_once_with("NTFY_REPLICATION_TOKEN")
        self.assertEqual(replication_token.read(), "tk_new")

    def test_set_without_token_keeps_the_stored_one(self):
        replication_token.write("tk_keep")
        self.run_set_monitor()
        self.assertEqual(replication_token.read(), "tk_keep")

    def test_set_clear_token_removes_file_and_environment_value(self):
        replication_token.write("tk_gone")
        os.environ["NTFY_REPLICATION_TOKEN"] = "tk_gone"
        self.run_set_monitor(clear_token=True)
        self.assertEqual(replication_token.read(), "")
        self.agent.unset_env.assert_called_once_with("NTFY_REPLICATION_TOKEN")

    def get_monitor(self):
        return json.loads(self.run_script(IMAGEROOT / "actions/get-replication-monitor/50read"))

    def test_get_reports_a_configured_token_without_revealing_it(self):
        self.assertFalse(self.get_monitor()["token_configured"])
        replication_token.write("tk_secret")
        result = self.get_monitor()
        self.assertTrue(result["token_configured"])
        self.assertNotIn("tk_secret", json.dumps(result))

    # restore

    def restore(self, environment):
        return self.run_script(IMAGEROOT / "actions/restore-module/07copy_custom_env", {"environment": environment})

    def test_restore_of_an_old_backup_writes_the_file_not_the_environment(self):
        self.restore({"PROVISION_MODE": "join-remote-domain", "NTFY_REPLICATION_TOKEN": "tk_legacy"})
        self.assertEqual(replication_token.read(), "tk_legacy")
        names = [call.args[0] for call in self.agent.set_env.call_args_list]
        self.assertNotIn("NTFY_REPLICATION_TOKEN", names)

    def test_restore_of_a_new_backup_keeps_the_restored_file(self):
        replication_token.write("tk_from_restic")
        self.restore({"PROVISION_MODE": "join-remote-domain"})
        self.assertEqual(replication_token.read(), "tk_from_restic")

    def test_restore_does_not_replace_a_restored_file_with_an_old_value(self):
        replication_token.write("tk_from_restic")
        self.restore({"NTFY_REPLICATION_TOKEN": "tk_legacy"})
        self.assertEqual(replication_token.read(), "tk_from_restic")

    # backup contract

    def test_backup_list_contains_the_token_file_and_the_upstream_entries(self):
        lines = (IMAGEROOT / "etc/state-include.conf").read_text().splitlines()
        entries = [line for line in lines if line and not line.startswith("#")]
        self.assertIn("state/ntfy-replication-token", entries)
        for upstream in ("volumes/config", "volumes/data/backup", "volumes/shares", "volumes/homes",
                         "volumes/tsdb_backup", "state/timescaledb.env"):
            self.assertIn(upstream, entries)

    def test_the_build_pins_the_upstream_backup_list_by_hash(self):
        pins = (ROOT / "scripts/upstream-restore-state.sha256").read_text()
        self.assertIn("imageroot/etc/state-include.conf", pins)


if __name__ == "__main__":
    unittest.main()
