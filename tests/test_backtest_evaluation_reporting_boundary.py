from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import ai_value_scanner.backtest as backtest
from ai_value_scanner.evaluation.backtest import (
    build_signal_diagnostics,
    event_backtest,
    forward_return,
    forward_return_with_exit,
    summarize_backtest,
    summarize_backtest_by_segment,
)
from ai_value_scanner.reporting.backtest import (
    build_markdown_report,
    resolve_output_paths,
)


class TestBacktestEvaluationBoundary(unittest.TestCase):
    def test_backtest_reexports_canonical_evaluation_functions(self) -> None:
        self.assertIs(backtest.forward_return, forward_return)
        self.assertIs(backtest.forward_return_with_exit, forward_return_with_exit)
        self.assertIs(backtest.event_backtest, event_backtest)
        self.assertIs(backtest.summarize_backtest, summarize_backtest)
        self.assertIs(
            backtest.summarize_backtest_by_segment,
            summarize_backtest_by_segment,
        )
        self.assertIs(backtest.build_signal_diagnostics, build_signal_diagnostics)

    def test_forward_return_golden(self) -> None:
        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-01-02", tz="UTC"),
                pd.Timestamp("2026-01-05", tz="UTC"),
                pd.Timestamp("2026-01-06", tz="UTC"),
            ]
        )
        prices = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "close": [100.0, 103.0, 106.0],
            },
            index=idx,
        )
        ret, exit_date = forward_return_with_exit(
            prices,
            "2026-01-02",
            horizon=2,
            roundtrip_cost=0.01,
            entry_price_mode="next_open",
            exit_price_mode="close",
        )
        self.assertAlmostEqual(ret, (106.0 / 101.0) - 1.0 - 0.01, places=12)
        self.assertEqual(exit_date, pd.Timestamp("2026-01-06", tz="UTC"))
        self.assertAlmostEqual(
            forward_return(
                prices,
                "2026-01-02",
                horizon=2,
                roundtrip_cost=0.01,
            ),
            ret,
            places=12,
        )

    def test_event_and_summary_golden(self) -> None:
        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-01-02", tz="UTC"),
                pd.Timestamp("2026-01-05", tz="UTC"),
                pd.Timestamp("2026-01-06", tz="UTC"),
            ]
        )
        price_map = {
            "AAA": pd.DataFrame(
                {"open": [10.0, 10.0, 10.0], "close": [10.0, 11.0, 12.0]},
                index=idx,
            ),
            "QQQ": pd.DataFrame(
                {"open": [20.0, 20.0, 20.0], "close": [20.0, 21.0, 22.0]},
                index=idx,
            ),
        }
        signals = pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "run_stem": "r1",
                    "run_ts_utc": "2026-01-02T00:00:00Z",
                    "signal_date": "2026-01-02",
                    "list_type": "low_value",
                    "symbols": ["AAA"],
                    "n_selected": 1,
                    "benchmark_trailing_60d": 0.1,
                    "regime": "up",
                }
            ]
        )
        events, benchmarks = event_backtest(
            signals,
            price_map,
            horizons=[1],
            roundtrip_cost=0.0,
            benchmark_symbols=["QQQ"],
        )
        self.assertEqual(events.iloc[0]["event_status"], "valid")
        self.assertAlmostEqual(float(events.iloc[0]["portfolio_return"]), 0.1, places=12)
        self.assertAlmostEqual(float(benchmarks.iloc[0]["benchmark_return"]), 0.05, places=12)

        summary = summarize_backtest(events, benchmarks)
        self.assertEqual(int(summary.iloc[0]["n_events_total"]), 1)
        self.assertEqual(int(summary.iloc[0]["n_events_valid"]), 1)
        self.assertAlmostEqual(float(summary.iloc[0]["avg_return"]), 0.1, places=12)
        self.assertAlmostEqual(float(summary.iloc[0]["avg_excess_vs_QQQ"]), 0.05, places=12)

        segments = summarize_backtest_by_segment(events, benchmarks)
        self.assertEqual(segments.iloc[0]["segment"], "2026YTD")

    def test_signal_diagnostics_contract(self) -> None:
        signals = pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "run_stem": "r1",
                    "signal_date": "2026-01-02",
                    "list_type": "momentum",
                    "watchlist_source": "frozen",
                    "channel_counts": json.dumps({"core_ai": 1}),
                    "channel_symbols": json.dumps({"core_ai": ["AAA"]}),
                    "filter_diagnostics": json.dumps(
                        {
                            "core_ai": {
                                "n_input": 10,
                                "n_filtered": 4,
                                "n_ranked": 4,
                                "first_fail": {
                                    "top_reason": "min_price",
                                    "top_pct": 0.2,
                                },
                                "near_miss": {
                                    "top_reason": "min_return_20d",
                                    "top_pct": 0.1,
                                    "reasons": [],
                                },
                                "layer_summary": {
                                    "base_hard": {
                                        "before": 10,
                                        "remaining": 8,
                                        "removed": 2,
                                        "pass_rate": 0.8,
                                    }
                                },
                            }
                        }
                    ),
                }
            ]
        )
        diagnostics, channel = build_signal_diagnostics(signals)
        self.assertEqual(diagnostics.iloc[0]["layer"], "base_hard")
        self.assertEqual(int(diagnostics.iloc[0]["removed"]), 2)
        self.assertEqual(channel.iloc[0]["selected_symbols"], "AAA")
        self.assertEqual(channel.iloc[0]["top_first_fail"], "min_price")


class TestBacktestReportingBoundary(unittest.TestCase):
    def test_run_backtest_globals_are_bound_to_shared_modules(self) -> None:
        globals_map = backtest.run_backtest.__globals__
        self.assertIs(globals_map["event_backtest"], event_backtest)
        self.assertIs(globals_map["summarize_backtest"], summarize_backtest)
        self.assertIs(
            globals_map["summarize_backtest_by_segment"],
            summarize_backtest_by_segment,
        )
        self.assertIs(
            globals_map["build_signal_diagnostics"],
            build_signal_diagnostics,
        )
        self.assertIs(globals_map["build_markdown_report"], build_markdown_report)
        self.assertIs(globals_map["resolve_output_paths"], resolve_output_paths)

    def test_output_paths_keep_existing_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = resolve_output_paths("gate", root, "historical_replay")
            self.assertEqual(
                [path.name for path in paths],
                [
                    "gate_events.csv",
                    "gate_summary.csv",
                    "gate_benchmarks.csv",
                    "gate_segments.csv",
                    "gate_report.md",
                ],
            )

    def test_markdown_renderer_keeps_core_sections(self) -> None:
        cfg = SimpleNamespace(
            mode="existing_runs",
            list_types=["low_value"],
            horizons=[20],
            top_n=10,
            per_channel_top_n=True,
            trading_cost_bps=5.0,
            entry_price_mode="next_open",
            exit_price_mode="close",
        )
        summary = pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "list_type": "low_value",
                    "horizon_days": 20,
                    "n_events_valid": 1,
                    "n_events_total": 1,
                    "avg_return": 0.1,
                    "win_rate": 1.0,
                    "avg_excess_vs_QQQ": 0.03,
                    "n_no_signal_events": 0,
                    "n_unpriced_events": 0,
                }
            ]
        )
        segments = summary.assign(segment="2026YTD")
        channels = pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "list_type": "low_value",
                    "channel": "core_ai",
                    "n_selected_channel": 1,
                    "n_ranked": 2,
                    "top_first_fail": "min_price",
                }
            ]
        )
        report = build_markdown_report(
            cfg=cfg,
            signals=pd.DataFrame([{"x": 1}]),
            summary=summary,
            segment_summary=segments,
            signal_diagnostics=pd.DataFrame(),
            signal_channel_summary=channels,
            events_path=Path("events.csv"),
            summary_path=Path("summary.csv"),
            benchmarks_path=Path("benchmarks.csv"),
            segment_path=Path("segments.csv"),
            signal_diagnostics_path=Path("diagnostics.csv"),
            signal_channel_summary_path=Path("channels.csv"),
        )
        self.assertIn("# Backtest Report", report)
        self.assertIn("## Summary", report)
        self.assertIn("base | low_value | H=20", report)
        self.assertIn("## Signal Diagnostics", report)
        self.assertIn("common_first_fail=min_price", report)
        self.assertIn("- events: events.csv", report)


if __name__ == "__main__":
    unittest.main()
