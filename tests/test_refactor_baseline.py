from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import ai_value_scanner.backtest as backtest


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


baseline = _load_script("refactor_baseline.py")
tuner = _load_script("tune_parameters.py")


def _write_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_backtest_artifacts(outputs: Path, prefix: str) -> None:
    _write_csv(
        outputs / f"{prefix}_events_signals.csv",
        [
            {
                "scenario": "base",
                "list_type": "low_value",
                "signal_date": "2025-01-31",
                "symbols": "['AAA']",
            }
        ],
    )
    _write_csv(
        outputs / f"{prefix}_events.csv",
        [
            {
                "scenario": "base",
                "list_type": "low_value",
                "horizon_days": 20,
                "signal_date": "2025-01-31",
                "event_status": "valid",
                "portfolio_return": 0.1,
            }
        ],
    )
    _write_csv(
        outputs / f"{prefix}_summary.csv",
        [
            {
                "scenario": "base",
                "list_type": "low_value",
                "horizon_days": 20,
                "n_events_total": 1,
                "n_events_valid": 1,
                "n_no_signal_events": 0,
                "n_unpriced_events": 0,
                "n_partial_valid_events": 0,
                "avg_return": 0.1,
                "median_return": 0.1,
                "win_rate": 1.0,
                "std_return": 0.0,
                "avg_excess_vs_QQQ": 0.03,
            }
        ],
    )
    _write_csv(
        outputs / f"{prefix}_benchmarks.csv",
        [
            {
                "scenario": "base",
                "signal_date": "2025-01-31",
                "horizon_days": 20,
                "benchmark": "QQQ",
                "benchmark_return": 0.07,
            }
        ],
    )
    _write_csv(
        outputs / f"{prefix}_segments.csv",
        [
            {
                "scenario": "base",
                "segment": "up",
                "list_type": "low_value",
                "horizon_days": 20,
                "avg_return": 0.1,
            }
        ],
    )
    _write_csv(
        outputs / f"{prefix}_events_signal_diagnostics.csv",
        [{"scenario": "base", "list_type": "low_value", "n_input": 10}],
    )
    _write_csv(
        outputs / f"{prefix}_events_signal_channel_summary.csv",
        [
            {
                "scenario": "base",
                "list_type": "low_value",
                "channel": "core_ai",
                "n_selected_channel": 1,
            }
        ],
    )
    (outputs / f"{prefix}_report.md").write_text("# synthetic\n")
    (outputs / f"{prefix}_report_network.json").write_text(
        json.dumps(
            {
                "had_rate_limit_or_network_issue": False,
                "stale_market_data_fallback_used": False,
                "data_provenance": {"alpaca": {}},
            }
        )
    )


def _write_tuning_artifacts(outputs: Path, prefix: str) -> None:
    _write_csv(
        outputs / f"{prefix}_results.csv",
        [
            {
                "cid": "c000",
                "objective_score": 0.1,
                "balanced_rank_score": 0.1,
                "constraints_passed": True,
            }
        ],
    )
    (outputs / f"{prefix}_summary.json").write_text(
        json.dumps(
            {
                "selection_mode": "walk_forward",
                "candidates": 1,
                "picks": {"risk_off": "c000"},
                "walk_forward": {
                    "risk_off": {
                        "final_candidate": "c000",
                        "promotion_eligible": False,
                    }
                },
            }
        )
    )
    (outputs / f"{prefix}_report.md").write_text("# tuner\n")


class TestRefactorBaselineTool(unittest.TestCase):
    def test_directory_contract_changes_when_snapshot_set_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.csv").write_text("symbol\nAAA\n")
            first = baseline.directory_contract(root)
            (root / "b.csv").write_text("symbol\nBBB\n")
            second = baseline.directory_contract(root)
        self.assertEqual(first["file_count"], 1)
        self.assertEqual(second["file_count"], 2)
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_capture_manifest_records_inputs_and_deterministic_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outputs = root / "outputs"
            outputs.mkdir()
            configs = root / "configs"
            configs.mkdir()
            data = root / "data"
            data.mkdir()
            history = root / "frozen_history"
            history.mkdir()

            (configs / "risk_off.json").write_text(
                json.dumps({"config_schema_version": 1, "strategy_style": "risk_off"})
            )
            (configs / "risk_on.json").write_text(
                json.dumps({"config_schema_version": 1, "strategy_style": "risk_on"})
            )
            (configs / "space.json").write_text(json.dumps({"axes": [{"name": "x"}]}))
            (data / "watchlist.csv").write_text(
                "symbol,bucket,etf_count,etfs,enabled\nAAA,core_ai,1,ETF,1\n"
            )
            (history / "ai_watchlist_20260922T000000Z.csv").write_text(
                "symbol,bucket,etf_count,etfs,enabled\nAAA,core_ai,1,ETF,1\n"
            )

            _write_backtest_artifacts(outputs, "base_risk_off")
            _write_backtest_artifacts(outputs, "base_risk_on")
            _write_tuning_artifacts(outputs, "base_tuner")

            args = argparse.Namespace(
                repo_root=str(root),
                outputs_dir="outputs",
                risk_off_prefix="base_risk_off",
                risk_on_prefix="base_risk_on",
                tuning_prefix="base_tuner",
                risk_off_config="configs/risk_off.json",
                risk_on_config="configs/risk_on.json",
                param_space="configs/space.json",
                watchlist="data/watchlist.csv",
                watchlist_history_dir="frozen_history",
                replay_start="2023-01-01",
                replay_end="2026-03-31",
                rebalance_frequency="monthly",
                require_clean=True,
                baseline_id="baseline-test",
            )
            with mock.patch.object(
                baseline,
                "git_context",
                return_value={
                    "commit": "abc123",
                    "branch": "main",
                    "dirty": False,
                    "dirty_paths": [],
                },
            ):
                manifest = baseline.capture_manifest(args)

        self.assertEqual(manifest["git"]["commit"], "abc123")
        self.assertEqual(manifest["inputs"]["watchlist"]["unique_symbols"], 1)
        self.assertEqual(manifest["inputs"]["watchlist_history"]["file_count"], 1)
        self.assertEqual(
            manifest["runs"]["risk_off"]["summary_contract"][0]["avg_return"],
            0.1,
        )
        self.assertEqual(manifest["tuning_smoke"]["selection_mode"], "walk_forward")

    def test_compare_manifest_ignores_input_location_paths(self) -> None:
        base = {
            "schema_version": 1,
            "experiment_contract": {
                "historical_replay_start": "2023-01-01",
                "historical_replay_end": "2026-03-31",
                "rebalance_frequency": "monthly",
                "watchlist_csv_path": "outputs/base_watchlist.csv",
                "watchlist_history_dir": "outputs/base_history",
            },
            "inputs": {
                key: {"sha256": "same"}
                for key in (
                    "risk_off_config",
                    "risk_on_config",
                    "tuner_param_space",
                    "watchlist",
                    "watchlist_history",
                )
            },
            "runs": {
                style: {
                    "deterministic_sha256": {"summary": "aaa"},
                    "summary_contract": [{"avg_return": 0.1}],
                    "signals_contract": {"rows": 1},
                }
                for style in ("risk_off", "risk_on")
            },
        }
        current = json.loads(json.dumps(base))
        current["experiment_contract"]["watchlist_csv_path"] = (
            "evidence/baselines/pre_e01/base_watchlist.csv"
        )
        current["experiment_contract"]["watchlist_history_dir"] = (
            "evidence/baselines/pre_e01/base_history"
        )
        self.assertEqual(baseline.compare_manifest(base, current), [])

    def test_compare_manifest_still_checks_semantic_experiment_settings(self) -> None:
        base = {
            "schema_version": 1,
            "experiment_contract": {
                "rebalance_frequency": "monthly",
                "watchlist_csv_path": "outputs/base.csv",
            },
            "inputs": {
                key: {"sha256": "same"}
                for key in (
                    "risk_off_config",
                    "risk_on_config",
                    "tuner_param_space",
                    "watchlist",
                    "watchlist_history",
                )
            },
            "runs": {
                style: {
                    "deterministic_sha256": {"summary": "aaa"},
                    "summary_contract": [{"avg_return": 0.1}],
                    "signals_contract": {"rows": 1},
                }
                for style in ("risk_off", "risk_on")
            },
        }
        current = json.loads(json.dumps(base))
        current["experiment_contract"]["rebalance_frequency"] = "weekly"
        diffs = baseline.compare_manifest(base, current)
        self.assertTrue(any("experiment_contract" in x for x in diffs))

    def test_compare_manifest_detects_deterministic_output_drift(self) -> None:
        base = {
            "schema_version": 1,
            "experiment_contract": {"x": 1},
            "inputs": {
                key: {"sha256": "same"}
                for key in (
                    "risk_off_config",
                    "risk_on_config",
                    "tuner_param_space",
                    "watchlist",
                    "watchlist_history",
                )
            },
            "runs": {
                style: {
                    "deterministic_sha256": {"summary": "aaa"},
                    "summary_contract": [{"avg_return": 0.1}],
                    "signals_contract": {"rows": 1},
                }
                for style in ("risk_off", "risk_on")
            },
        }
        current = json.loads(json.dumps(base))
        current["runs"]["risk_on"]["summary_contract"][0]["avg_return"] = 0.2
        diffs = baseline.compare_manifest(base, current)
        self.assertTrue(any("runs.risk_on.summary_contract" in x for x in diffs))

    def test_tuner_exposes_watchlist_history_dir_without_changing_default(self) -> None:
        with mock.patch.object(sys, "argv", ["tune_parameters.py"]):
            args = tuner.parse_args()
        self.assertEqual(args.watchlist_history_dir, "data/watchlist_history")
        self.assertIsNone(args.watchlist_csv_path)

    def test_backtest_watchlist_overrides_default_off(self) -> None:
        args = backtest.build_parser().parse_args([])
        self.assertEqual(args.watchlist_history_dir, "data/watchlist_history")
        self.assertIsNone(args.watchlist_csv_path)

        args = backtest.build_parser().parse_args(
            [
                "--watchlist-csv-path",
                "outputs/frozen.csv",
                "--watchlist-history-dir",
                "outputs/frozen_history",
            ]
        )
        self.assertEqual(args.watchlist_csv_path, "outputs/frozen.csv")
        self.assertEqual(args.watchlist_history_dir, "outputs/frozen_history")


if __name__ == "__main__":
    unittest.main()
