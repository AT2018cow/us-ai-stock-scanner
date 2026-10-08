from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

import ai_value_scanner.backtest as backtest
from ai_value_scanner.validation.snapshots import (
    FeatureSnapshotWriter,
    compare_snapshot_manifests,
    load_feature_snapshot,
    load_snapshot_manifest,
)


def _load_script(name: str):
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_script("fast_strategy_gate.py")


class TestFeatureSnapshotBundle(unittest.TestCase):
    def test_snapshot_is_deterministic_across_input_row_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left_dir = root / "left"
            right_dir = root / "right"
            frame = pd.DataFrame(
                {
                    "symbol": ["NA", "AAA"],
                    "sic": ["0010", "0020"],
                    "score_input": [2.5, 1.5],
                    "shares_stale": [False, True],
                }
            )

            left = FeatureSnapshotWriter(left_dir, metadata={"style": "risk_off"})
            left_record = left.write(
                style="risk_off",
                scenario="base",
                asof=pd.Timestamp("2026-06-30", tz="UTC"),
                frame=frame,
            )
            left.finalize()

            right = FeatureSnapshotWriter(right_dir, metadata={"style": "risk_off"})
            right_record = right.write(
                style="risk_off",
                scenario="base",
                asof=pd.Timestamp("2026-06-30", tz="UTC"),
                frame=frame.iloc[::-1],
            )
            right.finalize()

            self.assertEqual(left_record["sha256"], right_record["sha256"])
            left_manifest = load_snapshot_manifest(left_dir)
            right_manifest = load_snapshot_manifest(right_dir)
            self.assertEqual(
                compare_snapshot_manifests(left_manifest, right_manifest),
                [],
            )
            loaded = load_feature_snapshot(left_dir / left_record["path"])

        self.assertEqual(loaded["symbol"].tolist(), ["AAA", "NA"])
        self.assertEqual(loaded["sic"].tolist(), ["0020", "0010"])
        self.assertEqual(
            loaded.columns.tolist(),
            ["symbol", "score_input", "shares_stale", "sic"],
        )

    def test_manifest_compare_detects_feature_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left = FeatureSnapshotWriter(root / "left", metadata={"x": 1})
            right = FeatureSnapshotWriter(root / "right", metadata={"x": 1})
            left.write(
                style="risk_off",
                scenario="base",
                asof=pd.Timestamp("2026-06-30", tz="UTC"),
                frame=pd.DataFrame({"symbol": ["AAA"], "x": [1.0]}),
            )
            right.write(
                style="risk_off",
                scenario="base",
                asof=pd.Timestamp("2026-06-30", tz="UTC"),
                frame=pd.DataFrame({"symbol": ["AAA"], "x": [2.0]}),
            )
            left.finalize()
            right.finalize()
            diffs = compare_snapshot_manifests(
                load_snapshot_manifest(root / "left"),
                load_snapshot_manifest(root / "right"),
            )

        self.assertTrue(any("bundle_sha256" in diff for diff in diffs))


class TestFastStrategyGate(unittest.TestCase):
    def test_gate_runs_entirely_from_snapshot_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshots = root / "snapshots"
            writer = FeatureSnapshotWriter(snapshots)
            writer.write(
                style="risk_off",
                scenario="base",
                asof=pd.Timestamp("2026-06-30", tz="UTC"),
                frame=pd.DataFrame(
                    {
                        "symbol": ["BBB", "AAA"],
                        "feature": [2.0, 1.0],
                    }
                ),
            )
            writer.finalize()
            config_path = root / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")

            def fake_rank(**kwargs):
                frame = kwargs["df"]
                selected = sorted(frame["symbol"].astype(str).tolist())[:1]
                return selected, {
                    "channel_counts": {"core_ai": 1},
                    "selected_symbols": selected,
                }

            with (
                mock.patch.object(
                    gate,
                    "load_config",
                    return_value=SimpleNamespace(strategy_style="risk_off"),
                ),
                mock.patch.object(
                    gate.backtest,
                    "rank_and_pick_symbols_with_diagnostics",
                    side_effect=fake_rank,
                ) as rank,
            ):
                result = gate.build_gate_result(
                    snapshot_dir=snapshots,
                    scan_config_path=config_path,
                    list_types=["low_value", "momentum"],
                    top_n=10,
                    per_channel_top_n=True,
                    include_channels=["core_ai"],
                )

        self.assertEqual(rank.call_count, 2)
        self.assertEqual(result["strategy_style"], "risk_off")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(
            [entry["selected_symbols"] for entry in result["results"]],
            [["AAA"], ["AAA"]],
        )
        self.assertEqual(result["snapshot_bundle_sha256"].__len__(), 64)
        self.assertEqual(result["result_sha256"].__len__(), 64)

    def test_compare_gate_results_requires_identical_snapshot_and_outputs(self) -> None:
        baseline = {
            "schema_version": 1,
            "snapshot_bundle_sha256": "aaa",
            "snapshot_schema_version": 1,
            "scan_config_sha256": "bbb",
            "strategy_style": "risk_off",
            "parameters": {"top_n": 10},
            "result_sha256": "ccc",
            "results": [{"selected_symbols": ["AAA"]}],
        }
        current = json.loads(json.dumps(baseline))
        self.assertEqual(gate.compare_gate_results(baseline, current), [])
        current["result_sha256"] = "changed"
        current["results"][0]["selected_symbols"] = ["BBB"]
        diffs = gate.compare_gate_results(baseline, current)
        self.assertTrue(any("result_sha256" in diff for diff in diffs))
        self.assertIn("results differ", diffs)

    def test_backtest_parser_exposes_snapshot_only_controls(self) -> None:
        args = backtest.build_parser().parse_args(
            [
                "--feature-snapshot-dir",
                "outputs/fast_gate",
                "--feature-snapshot-dates",
                "2026-01-30,2026-03-31",
                "--feature-snapshot-only",
            ]
        )
        self.assertEqual(args.feature_snapshot_dir, "outputs/fast_gate")
        self.assertEqual(
            args.feature_snapshot_dates,
            "2026-01-30,2026-03-31",
        )
        self.assertTrue(args.feature_snapshot_only)


if __name__ == "__main__":
    unittest.main()
