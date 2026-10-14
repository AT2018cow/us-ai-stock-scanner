"""Regression for the actual authorized CLI process entrypoint.

Earlier unit tests imported evaluate_development as a module and missed that
`python scripts/mvp_v11_dev_return_experiment.py ...` lacked repo root
on sys.path. These subprocesses use NO historical inputs or returns.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mvp_v11_dev_return_experiment.py"


def invoke(*args: str, isolated: bool = False) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Explicitly prohibit accidental pass from pytest/CI/repo PYTHONPATH.
    env.pop("PYTHONPATH", None)
    cmd = [sys.executable]
    if isolated:
        cmd.append("-I")  # removes cwd / user site / PYTHONPATH conveniences
    cmd.extend([str(SCRIPT), *args])
    return subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True,
        timeout=45, check=False,
    )


class TestDevReturnCliEntrypoint(unittest.TestCase):
    def test_real_file_entrypoint_help_no_pythonpath(self) -> None:
        result = invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--authorize-2023-2024-dev-returns", result.stdout)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_python_isolated_mode_entrypoint(self) -> None:
        result = invoke("--help", isolated=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--expected-code-sha", result.stdout)

    def test_actual_cli_argument_shape_stops_at_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "must_not_exist"
            result = invoke(
                "--authorize-2023-2024-dev-returns", "NOT_APPROVED",
                "--expected-code-sha", "0" * 40,
                "--expected-protocol-sha256", "0" * 64,
                "--entry-dataset", str(Path(tmp) / "missing_v3.csv"),
                "--entry-meta", str(Path(tmp) / "missing_meta.json"),
                "--event-audit", str(Path(tmp) / "missing_events.csv"),
                "--event-review", str(Path(tmp) / "missing_review.csv"),
                "--frozen-membership", str(Path(tmp) / "missing_membership.csv"),
                "--output-dir", str(out),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "explicit project-owner approval for fixed DEV-only returns required",
                result.stderr,
                result.stderr,
            )
            self.assertNotIn("ModuleNotFoundError", result.stderr)
            self.assertFalse(out.exists(), "refused invocation must not create output")

    def test_authorized_phrase_wrong_code_sha_stops_before_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "must_not_exist"
            result = invoke(
                "--authorize-2023-2024-dev-returns",
                "I_APPROVE_FROZEN_2023_2024_DEV_ONLY",
                "--expected-code-sha", "0" * 40,
                "--expected-protocol-sha256", "0" * 64,
                "--entry-dataset", str(Path(tmp) / "missing_v3.csv"),
                "--entry-meta", str(Path(tmp) / "missing_meta.json"),
                "--event-audit", str(Path(tmp) / "missing_events.csv"),
                "--event-review", str(Path(tmp) / "missing_review.csv"),
                "--frozen-membership", str(Path(tmp) / "missing_membership.csv"),
                "--output-dir", str(out),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "code SHA not pinned to exact current Git HEAD",
                result.stderr,
                result.stderr,
            )
            self.assertNotIn("ModuleNotFoundError", result.stderr)
            self.assertFalse(out.exists(), "SHA refusal must not create output")


if __name__ == "__main__":
    unittest.main()
