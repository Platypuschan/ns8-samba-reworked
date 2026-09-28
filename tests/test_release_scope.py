#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release-scope.sh"


class ReleaseScopeTests(unittest.TestCase):
    def test_daily_run_skips_docs_but_detects_image_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)

            def git(*args):
                return subprocess.run(
                    ["git", *args], cwd=work, check=True, capture_output=True, text=True
                ).stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (work / "README.md").write_text("Original documentation\n")
            git("add", ".")
            git("commit", "-qm", "Initial release")
            git("tag", "v1.1.1")

            (work / "README.md").write_text("Updated documentation\n")
            git("add", ".")
            git("commit", "-qm", "Edit README")
            self.assertEqual(
                subprocess.check_output(["bash", str(SCRIPT), "v1.1.1"],
                                        cwd=work, text=True).strip(),
                "false",
            )

            (work / "overlay").mkdir()
            (work / "overlay" / "restore").write_text("Changed image content\n")
            git("add", ".")
            git("commit", "-qm", "Change restore")
            self.assertEqual(
                subprocess.check_output(["bash", str(SCRIPT), "v1.1.1"],
                                        cwd=work, text=True).strip(),
                "true",
            )


if __name__ == "__main__":
    unittest.main()
