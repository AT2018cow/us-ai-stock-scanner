from __future__ import annotations

import unittest
from pathlib import Path

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner import config
from ai_value_scanner.evaluation import backtest as evaluation
from ai_value_scanner.features import ai_link, derived, peer_valuation, price, valuation
from ai_value_scanner.fundamentals import accounting, reconstruction, shares
from ai_value_scanner.reporting import backtest as backtest_reporting
from ai_value_scanner.reporting import scan as scan_reporting
from ai_value_scanner.strategy import filtering, research, rules, scoring, selection


class TestModularRefactorClosure(unittest.TestCase):
    def test_scanner_uses_canonical_config_fundamentals_features(self) -> None:
        self.assertIs(scanner.ScanConfig, config.ScanConfig)
        self.assertIs(scanner.load_config, config.load_config)
        self.assertIs(scanner.compute_adjusted_metrics, accounting.compute_adjusted_metrics)
        self.assertIs(scanner.derive_accounting_metrics, accounting.derive_accounting_metrics)
        self.assertIs(scanner.current_ttm_pair, reconstruction.current_ttm_pair)
        self.assertIs(
            scanner.assess_share_count_integrity,
            shares.assess_share_count_integrity,
        )
        self.assertIs(
            scanner.compute_cross_section_derived_features,
            derived.compute_cross_section_derived_features,
        )
        self.assertIs(
            scanner.compute_ai_link_score,
            ai_link.compute_ai_link_score,
        )
        self.assertIs(
            scanner.compute_peer_relative_valuation,
            peer_valuation.compute_peer_relative_valuation,
        )
        self.assertIs(
            scanner.compute_price_history_features,
            price.compute_price_history_features,
        )
        self.assertIs(
            scanner.compute_historical_valuation_percentile,
            valuation.compute_historical_valuation_percentile,
        )

    def test_scanner_uses_canonical_strategy_and_reporting(self) -> None:
        self.assertIs(scanner.score_and_rank, scoring.score_and_rank)
        self.assertIs(
            scanner.apply_scored_or_hard_filters,
            filtering.apply_scored_or_hard_filters,
        )
        self.assertIs(scanner.build_filter_steps, rules.build_filter_steps)
        self.assertIs(
            scanner.build_industry_trend_steps,
            rules.build_industry_trend_steps,
        )
        self.assertIs(scanner.build_momentum_steps, rules.build_momentum_steps)
        self.assertIs(
            scanner.build_research_assessment,
            research.build_research_assessment,
        )
        self.assertIs(
            scanner.apply_low_value_research_gate,
            research.apply_low_value_research_gate,
        )
        self.assertIs(scanner.apply_group_caps, selection.apply_group_caps)
        self.assertIs(
            scanner.dedupe_symbol_by_best_channel,
            selection.dedupe_symbol_by_best_channel,
        )
        self.assertIs(
            scanner.build_run_report_markdown,
            scan_reporting.build_run_report_markdown,
        )
        self.assertIs(scanner.resolve_output_paths, scan_reporting.resolve_output_paths)

    def test_backtest_uses_canonical_shared_core(self) -> None:
        self.assertIs(backtest.ScanConfig, config.ScanConfig)
        self.assertIs(backtest.load_config, config.load_config)
        self.assertIs(
            backtest.compute_adjusted_metrics,
            accounting.compute_adjusted_metrics,
        )
        self.assertIs(
            backtest.derive_accounting_metrics,
            accounting.derive_accounting_metrics,
        )
        self.assertIs(backtest.current_ttm_pair, reconstruction.current_ttm_pair)
        self.assertIs(
            backtest.assess_share_count_integrity,
            shares.assess_share_count_integrity,
        )
        self.assertIs(
            backtest.compute_cross_section_derived_features,
            derived.compute_cross_section_derived_features,
        )
        self.assertIs(
            backtest.compute_ai_link_score,
            ai_link.compute_ai_link_score,
        )
        self.assertIs(
            backtest.compute_peer_relative_valuation,
            peer_valuation.compute_peer_relative_valuation,
        )
        self.assertIs(
            backtest.compute_price_history_features,
            price.compute_price_history_features,
        )
        self.assertIs(
            backtest.compute_historical_valuation_percentile,
            valuation.compute_historical_valuation_percentile,
        )
        self.assertIs(backtest.score_and_rank, scoring.score_and_rank)
        self.assertIs(
            backtest.apply_scored_or_hard_filters,
            filtering.apply_scored_or_hard_filters,
        )
        self.assertIs(backtest.build_filter_steps, rules.build_filter_steps)
        self.assertIs(
            backtest.build_industry_trend_steps,
            rules.build_industry_trend_steps,
        )
        self.assertIs(backtest.build_momentum_steps, rules.build_momentum_steps)
        self.assertIs(
            backtest.build_research_assessment,
            research.build_research_assessment,
        )
        self.assertIs(backtest.apply_group_caps, selection.apply_group_caps)

    def test_backtest_uses_canonical_evaluation_and_reporting(self) -> None:
        self.assertIs(backtest.forward_return, evaluation.forward_return)
        self.assertIs(backtest.event_backtest, evaluation.event_backtest)
        self.assertIs(backtest.summarize_backtest, evaluation.summarize_backtest)
        self.assertIs(
            backtest.summarize_backtest_by_segment,
            evaluation.summarize_backtest_by_segment,
        )
        self.assertIs(
            backtest.build_signal_diagnostics,
            evaluation.build_signal_diagnostics,
        )
        self.assertIs(
            backtest.build_markdown_report,
            backtest_reporting.build_markdown_report,
        )
        self.assertIs(
            backtest.resolve_output_paths,
            backtest_reporting.resolve_output_paths,
        )

    def test_workflow_entry_globals_are_bound(self) -> None:
        scan_globals = scanner.run_scan.__globals__
        self.assertIs(
            scan_globals["build_run_report_markdown"],
            scan_reporting.build_run_report_markdown,
        )
        self.assertIs(
            scan_globals["resolve_output_paths"],
            scan_reporting.resolve_output_paths,
        )

        bt_globals = backtest.run_backtest.__globals__
        self.assertIs(bt_globals["event_backtest"], evaluation.event_backtest)
        self.assertIs(
            bt_globals["summarize_backtest"],
            evaluation.summarize_backtest,
        )
        self.assertIs(
            bt_globals["build_markdown_report"],
            backtest_reporting.build_markdown_report,
        )

    def test_canonical_packages_do_not_import_workflow_facades(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "ai_value_scanner"
        packages = [
            "fundamentals",
            "features",
            "strategy",
            "evaluation",
            "reporting",
            "validation",
        ]
        forbidden = (
            "from ai_value_scanner.scanner import",
            "import ai_value_scanner.scanner",
            "from ai_value_scanner.backtest import",
            "import ai_value_scanner.backtest",
        )
        violations: list[str] = []
        for package in packages:
            for path in sorted((root / package).glob("*.py")):
                text = path.read_text(encoding="utf-8")
                for marker in forbidden:
                    if marker in text:
                        violations.append(f"{path.relative_to(root)}: {marker}")
        self.assertEqual(violations, [])

    def test_weight_dataset_script_uses_canonical_evaluation_layer(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "extract_weight_dataset.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "from ai_value_scanner.evaluation.backtest import",
            text,
        )
        self.assertNotIn(
            "    _hold_window_mature,\n)",
            text.split("from ai_value_scanner.backtest import", 1)[-1].split(
                "from ai_value_scanner.evaluation.backtest import", 1
            )[0],
        )


if __name__ == "__main__":
    unittest.main()
