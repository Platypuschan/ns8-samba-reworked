#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.machinery
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
MONITOR_PATH = REPOSITORY / "overlay/imageroot/bin/check-ad-replication"


class ReplicationMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        os.environ.update(
            {
                "AGENT_STATE_DIR": cls.temporary_directory.name,
                "SERVER_ROLE": "dc",
                "NTFY_REPLICATION_ENABLED": "1",
                "NTFY_REPLICATION_FAILURE_THRESHOLD": "2",
                "NTFY_REPLICATION_BASE_URL": "https://ntfy.example.com",
                "NTFY_REPLICATION_TOPIC": "ad-replication",
                "NTFY_REPLICATION_TOKEN": "tk_secret",
                "HOSTNAME": "dc-local.ad.example.com",
            }
        )
        loader = importlib.machinery.SourceFileLoader(
            "check_ad_replication", str(MONITOR_PATH)
        )
        module = types.ModuleType(loader.name)
        loader.exec_module(module)
        cls.monitor = module

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def setUp(self):
        self.monitor.STATE_FILE.unlink(missing_ok=True)

    @staticmethod
    def replication_payload(failure_count):
        return {
            "repsFrom": [
                {
                    "NC dn": "DC=ad,DC=example,DC=com",
                    "DSA": "REMOTE\\DC1",
                    "DSA objectGUID": "11111111-1111-1111-1111-111111111111",
                    "last attempt time": "2026-09-21 12:00:00",
                    "last attempt message": "WERR_BAD_NET_RESP",
                    "consecutive failures": failure_count,
                    "is deleted": False,
                }
            ],
            "repsTo": [],
        }

    @staticmethod
    def command_result(payload=None, returncode=0, stderr=""):
        return subprocess.CompletedProcess(
            args=["samba-tool"],
            returncode=returncode,
            stdout=json.dumps(payload) if payload is not None else "",
            stderr=stderr,
        )

    def test_threshold_uses_samba_consecutive_failure_counter(self):
        below_threshold = self.monitor.replication_failures(
            self.replication_payload(1), 2
        )
        at_threshold = self.monitor.replication_failures(
            self.replication_payload(2), 2
        )

        self.assertEqual(below_threshold, [])
        self.assertEqual(len(at_threshold), 1)
        self.assertEqual(at_threshold[0]["count"], 2)
        self.assertEqual(at_threshold[0]["direction"], "inbound")

    def test_one_notification_per_incident_and_reset_after_recovery(self):
        failing_result = self.command_result(self.replication_payload(2))
        healthy_result = self.command_result(self.replication_payload(0))

        with mock.patch.object(
            self.monitor.subprocess, "run", return_value=failing_result
        ), mock.patch.object(self.monitor, "send_ntfy") as send_ntfy:
            self.assertEqual(self.monitor.main(), 0)
            self.assertEqual(self.monitor.main(), 0)
            self.assertEqual(send_ntfy.call_count, 1)

            self.monitor.subprocess.run.return_value = healthy_result
            self.assertEqual(self.monitor.main(), 0)

            self.monitor.subprocess.run.return_value = failing_result
            self.assertEqual(self.monitor.main(), 0)
            self.assertEqual(send_ntfy.call_count, 2)

    def test_status_probe_uses_same_threshold(self):
        failed_probe = self.command_result(returncode=1, stderr="container down")

        with mock.patch.object(
            self.monitor.subprocess, "run", return_value=failed_probe
        ), mock.patch.object(self.monitor, "send_ntfy") as send_ntfy:
            self.assertEqual(self.monitor.main(), 0)
            send_ntfy.assert_not_called()

            self.assertEqual(self.monitor.main(), 0)
            send_ntfy.assert_called_once()

            self.assertEqual(self.monitor.main(), 0)
            send_ntfy.assert_called_once()

    def test_ntfy_request_uses_topic_and_bearer_token(self):
        response = mock.MagicMock()
        response.status = 200
        response.__enter__.return_value = response

        with mock.patch.object(
            self.monitor, "urlopen", return_value=response
        ) as urlopen:
            self.monitor.send_ntfy("Replication failed", "Details")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://ntfy.example.com/ad-replication",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer tk_secret")
        self.assertEqual(request.data, b"Details")
        urlopen.assert_called_once_with(request, timeout=15)


if __name__ == "__main__":
    unittest.main()
