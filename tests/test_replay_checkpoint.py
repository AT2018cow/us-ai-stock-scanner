from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.backtest import BacktestConfig, build_parser
from ai_value_scanner.replay_checkpoint import (
    SignalDateCheckpointStore,
    path_sha256,
)


class TestSignalDateCheckpointStore(unittest.TestCase):
    def test_round_trip_and_commit_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            commits: list[int] = []
            root = Path(tmp) / "checkpoint"
            store = SignalDateCheckpointStore(
                root,
                {"style": "risk_on", "input_hash": "abc"},
                resume=False,
                commit_callback=lambda: commits.append(1),
            )
            store.save(
                "2025-01-31",
                [
                    {
                        "signal_date": "2025-01-31",
                        "list_type": "momentum",
                        "symbols": ["AAA", "BBB"],
                        "n_selected": 2,
                    }
                ],
                "snapshot",
            )
            self.assertGreaterEqual(len(commits), 2)

            resumed = SignalDateCheckpointStore(
                root,
                {"style": "risk_on", "input_hash": "abc"},
                resume=True,
            )
            payload = resumed.load("2025-01-31")
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["watchlist_source"], "snapshot")
            self.assertEqual(payload["rows"][0]["symbols"], ["AAA", "BBB"])

    def test_resume_rejects_manifest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoint"
            SignalDateCheckpointStore(
                root,
                {"style": "risk_on", "input_hash": "abc"},
                resume=False,
            )
            with self.assertRaisesRegex(ValueError, "manifest mismatch"):
                SignalDateCheckpointStore(
                    root,
                    {"style": "risk_on", "input_hash": "different"},
                    resume=True,
                )

    def test_fresh_run_clears_stale_date_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoint"
            store = SignalDateCheckpointStore(
                root,
                {"style": "risk_on"},
                resume=False,
            )
            store.save("2025-01-31", [], "snapshot")
            self.assertTrue(store.path_for_date("2025-01-31").exists())

            fresh = SignalDateCheckpointStore(
                root,
                {"style": "risk_on"},
                resume=False,
            )
            self.assertFalse(fresh.path_for_date("2025-01-31").exists())

    def test_directory_hash_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("one")
            first = path_sha256(root)
            (root / "a.txt").write_text("two")
            second = path_sha256(root)
            self.assertNotEqual(first, second)

    def test_modal_baseline_runner_source_parses(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "modal_baseline_executor.py").read_text()
        ast.parse(source)

    def test_backtest_parser_exposes_checkpoint_controls(self) -> None:
        args = build_parser().parse_args(
            [
                "--signal-checkpoint-dir",
                "outputs/checkpoints",
                "--resume-signal-checkpoints",
            ]
        )
        self.assertEqual(args.signal_checkpoint_dir, "outputs/checkpoints")
        self.assertTrue(args.resume_signal_checkpoints)


if __name__ == "__main__":
    unittest.main()
