#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release-scope.sh"
WORKFLOW = SCRIPT.parents[1] / ".github/workflows/upstream-release.yml"


class ReleaseScopeTests(unittest.TestCase):
    def test_existing_tag_without_release_cannot_be_republished(self):
        workflow = WORKFLOW.read_text()
        step = workflow.split("      - name: Determine release target\n", 1)[1].split(
            "      - name: Capture source revision", 1
        )[0]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "UPSTREAM_VERSION").write_text("3.5.0\n")
            (work / "CUSTOM_VERSION").write_text("1.1.2\n")
            fake_bin = work / "bin"
            fake_bin.mkdir()
            gh = fake_bin / "gh"
            gh.write_text(
                "#!/bin/bash\n"
                "if [[ $1 == api ]]; then echo v3.5.0; exit 0; fi\n"
                "if [[ $1 == release && $2 == view ]]; then exit 1; fi\n"
                "exit 2\n"
            )
            gh.chmod(0o755)
            subprocess.run(["git", "init", "-q"], cwd=work, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=work, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=work, check=True)
            subprocess.run(["git", "add", "UPSTREAM_VERSION", "CUSTOM_VERSION"], cwd=work, check=True)
            subprocess.run(["git", "commit", "-qm", "Version files"], cwd=work, check=True)
            output = work / "output"
            environment = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "GITHUB_REPOSITORY": "example/ns8-samba-reworked",
                "GITHUB_REPOSITORY_OWNER": "example",
                "GITHUB_OUTPUT": str(output),
            }

            result = subprocess.run(["bash", "-c", script], cwd=work, env=environment,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("active=true", output.read_text())

            subprocess.run(["git", "tag", "v1.1.2"], cwd=work, check=True)
            result = subprocess.run(["bash", "-c", script], cwd=work, env=environment,
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite", result.stderr)

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

            (work / ".dockerignore").write_text("**/__pycache__/\n")
            git("add", ".")
            git("commit", "-qm", "Ignore generated Python files")
            self.assertEqual(
                subprocess.check_output(["bash", str(SCRIPT), "v1.1.1"],
                                        cwd=work, text=True).strip(),
                "true",
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
