from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import ai_value_scanner.scanner as scanner
from ai_value_scanner.config import ScanConfig
from ai_value_scanner.reporting.scan import (
    build_run_report_markdown,
    default_run_stem,
    log_status,
    resolve_output_paths,
    write_csv_atomic,
)
import ai_value_scanner.strategy.research as research


class TestScannerReportingBoundary(unittest.TestCase):
    def test_scanner_workflow_globals_are_bound_to_reporting_module(self) -> None:
        globals_map = scanner.run_scan.__globals__
        self.assertIs(globals_map["log_status"], log_status)
        self.assertIs(globals_map["resolve_output_paths"], resolve_output_paths)
        self.assertIs(
            globals_map["build_run_report_markdown"],
            build_run_report_markdown,
        )
        self.assertIs(globals_map["write_csv_atomic"], write_csv_atomic)

    def test_scanner_cli_parser_is_restored(self) -> None:
        parser = scanner.build_parser()
        args = parser.parse_args(
            [
                "--config",
                "configs/config.risk_on.json",
                "--max-symbols",
                "25",
                "--output",
                "out.csv",
            ]
        )
        self.assertEqual(args.config, "configs/config.risk_on.json")
        self.assertEqual(args.max_symbols, 25)
        self.assertEqual(args.output, "out.csv")

    def test_research_module_contains_no_reporting_or_cli_surface(self) -> None:
        for name in (
            "log_status",
            "default_run_stem",
            "resolve_output_paths",
            "build_run_report_markdown",
            "build_parser",
        ):
            self.assertFalse(hasattr(research, name), name)

    def test_output_paths_and_atomic_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = ScanConfig()
            cfg.output_dir = td
            cfg.max_symbols = 12
            started = datetime(2026, 10, 8, 12, 34, 56, tzinfo=timezone.utc)

            self.assertEqual(
                default_run_stem(started, cfg.max_symbols),
                "ai_value_scan_20261008T123456Z_sample12",
            )
            paths = resolve_output_paths(
                cfg,
                started,
                None,
                None,
                None,
                None,
            )
            self.assertEqual(
                paths["ranked_csv"].name,
                "ai_value_scan_20261008T123456Z_sample12_ranked.csv",
            )
            frame = pd.DataFrame({"symbol": ["AAA"], "score": [1.0]})
            write_csv_atomic(frame, paths["ranked_csv"])
            loaded = pd.read_csv(paths["ranked_csv"])
            pd.testing.assert_frame_equal(loaded, frame)

    def test_report_renderer_keeps_core_sections(self) -> None:
        started = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 10, 8, 12, 1, tzinfo=timezone.utc)
        ranked = pd.DataFrame(
            {
                "symbol": ["AAA"],
                "channel": ["core_ai"],
                "triage_label": ["keep"],
                "research_priority": ["research_now"],
                "composite_score": [0.8],
                "ai_link_score": [0.7],
                "watchlist_bucket": ["core_ai"],
                "watchlist_etf_count": [2],
                "watchlist_etfs": ["AIQ,SMH"],
                "ps_discount": [0.2],
                "pe_discount": [0.1],
                "research_risks": [""],
            }
        )
        paths = {
            "ranked_csv": Path("ranked.csv"),
            "diagnostics_base": Path("diag.csv"),
            "network_json": Path("network.json"),
            "report_md": Path("report.md"),
        }
        report = build_run_report_markdown(
            started_at=started,
            finished_at=finished,
            ranked=ranked,
            channel_profiles={"core_ai": {}},
            filtered_counts={"core_ai": 1},
            watchlist_counts={"core_ai": 1},
            watchlist_symbol_count=1,
            merged_count=10,
            prefilter_count=5,
            paths=paths,
            network_issue_flag=False,
            sec_cache_summary="ok",
            strategy_style="risk_off",
            scan_config_path="configs/config.risk_off.json",
        )
        self.assertIn("# AI Value Scan Report", report)
        self.assertIn("- Strategy-Style: risk_off", report)
        self.assertIn("## Shortlist", report)
        self.assertIn("AAA | triage=keep", report)
        self.assertIn("- sec cache: ok", report)


if __name__ == "__main__":
    unittest.main()
