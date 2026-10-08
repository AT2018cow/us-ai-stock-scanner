from __future__ import annotations

import unittest

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.config import ScanConfig, load_config
from ai_value_scanner.strategy.research import (
    apply_low_value_research_gate,
    apply_triage_labels,
    build_research_assessment,
)
from ai_value_scanner.strategy.rules import (
    build_benchmark_trend_step,
    build_filter_steps,
    build_industry_trend_steps,
    build_momentum_steps,
    channel_bucket_mask,
    passes_sic_filters,
    watchlist_member_mask,
)


class TestStrategyRuleBuilders(unittest.TestCase):
    def test_promoted_styles_keep_structural_steps_and_breaker(self) -> None:
        risk_off = load_config("configs/config.risk_off.json")
        risk_on = load_config("configs/config.risk_on.json")

        off_steps = build_filter_steps(
            risk_off,
            "core_ai",
            risk_off.channel_profiles["core_ai"],
        )
        on_steps = build_filter_steps(
            risk_on,
            "core_ai",
            risk_on.channel_profiles["core_ai"],
        )
        off_names = [name for name, _ in off_steps]
        on_names = [name for name, _ in on_steps]

        for name in (
            "min_drawdown_from_52w_high",
            "max_range_position_52w",
            "max_price_to_sma200",
            "benchmark_trend_filter",
        ):
            self.assertIn(name, off_names)

        for name in (
            "min_price_to_sma200",
            "min_range_position_52w",
            "min_return_20d",
            "min_return_60d",
            "benchmark_trend_filter",
        ):
            self.assertIn(name, on_names)

        trend_steps, _ = build_industry_trend_steps(
            risk_off,
            "core_ai",
            risk_off.channel_profiles["core_ai"],
        )
        momentum_steps, _ = build_momentum_steps(
            risk_on,
            "core_ai",
            risk_on.channel_profiles["core_ai"],
        )
        self.assertIn(
            "benchmark_trend_filter",
            [name for name, _ in trend_steps],
        )
        self.assertIn(
            "benchmark_trend_filter",
            [name for name, _ in momentum_steps],
        )

    def test_benchmark_breaker_fails_open_on_missing_state(self) -> None:
        cfg = ScanConfig()
        cfg.benchmark_trend_filter_symbol = "QQQ"
        step = build_benchmark_trend_step(cfg)
        self.assertIsNotNone(step)
        name, mask_fn = step
        self.assertEqual(name, "benchmark_trend_filter")

        missing = pd.DataFrame({"symbol": ["A", "B"]})
        self.assertEqual(mask_fn(missing).tolist(), [True, True])

        explicit = pd.DataFrame(
            {"benchmark_trend_ok": [True, False, None]}
        )
        self.assertEqual(
            mask_fn(explicit).tolist(),
            [True, False, True],
        )

    def test_watchlist_channel_and_sic_helpers(self) -> None:
        frame = pd.DataFrame(
            {
                "watchlist_bucket": [
                    "core_ai,ai_enabler",
                    "",
                    None,
                ],
                "watchlist_etf_count": [0, 2, 0],
            }
        )
        self.assertEqual(
            watchlist_member_mask(frame).tolist(),
            [True, True, True],
        )
        self.assertEqual(
            channel_bucket_mask(frame, "ai_enabler").tolist(),
            [True, False, False],
        )
        self.assertTrue(passes_sic_filters("3571", []))
        self.assertFalse(passes_sic_filters("3571", ["3571"]))
        self.assertFalse(passes_sic_filters(None, []))

    def test_scanner_and_replay_share_rule_builders(self) -> None:
        self.assertIs(scanner.build_filter_steps, build_filter_steps)
        self.assertIs(
            scanner.build_industry_trend_steps,
            build_industry_trend_steps,
        )
        self.assertIs(scanner.build_momentum_steps, build_momentum_steps)
        self.assertIs(backtest.build_filter_steps, build_filter_steps)
        self.assertIs(
            backtest.build_industry_trend_steps,
            build_industry_trend_steps,
        )
        self.assertIs(backtest.build_momentum_steps, build_momentum_steps)


class TestStrategyResearchCore(unittest.TestCase):
    def test_research_assessment_golden_case(self) -> None:
        row = pd.Series(
            {
                "ps_hist_percentile": 0.20,
                "pe_hist_percentile": 0.40,
                "ps_discount": 0.15,
                "pe_discount": 0.05,
                "ps_percentile_in_sic": 0.30,
                "pe_percentile_in_sic": 0.45,
                "fundamental_quality_score": 0.90,
                "ai_link_score": 0.60,
                "fcf_yield": 0.08,
                "ev_to_ebit": 10.0,
                "pe": 20.0,
                "ps": 3.0,
                "revenue_yoy": 0.12,
                "net_income_yoy": 0.20,
                "return_20d": 0.06,
                "return_60d": 0.12,
                "price_to_sma200": 1.10,
                "drawdown_from_52w_high": 0.05,
                "watchlist_etfs": "AIQ,SMH",
                "watchlist_bucket": "ai_enabler",
                "channel": "ai_enabler",
            }
        )
        result = build_research_assessment(row, "low_value")
        self.assertEqual(result["research_priority"], "research_now")
        self.assertEqual(float(result["research_score"]), 11.2)
        tags = set(result["research_tags"].split(","))
        self.assertTrue(
            {
                "cheap_relative_to_history",
                "cheap_relative_to_peers",
                "cash_flow_value",
                "quality_compounder",
                "strong_ai_link",
                "ai_infrastructure_exposure",
                "momentum_breakout",
            }.issubset(tags)
        )
        self.assertEqual(result["research_risks"], "no_major_risk_flag")

    def test_low_value_gate_uses_configured_priority_risk_and_score(self) -> None:
        cfg = ScanConfig()
        cfg.low_value_allowed_research_priorities = [
            "research_now",
            "watch_for_pullback",
        ]
        cfg.low_value_excluded_research_risks = ["possible_value_trap"]
        cfg.low_value_min_research_score = 1.0
        frame = pd.DataFrame(
            {
                "symbol": ["KEEP", "THEME", "TRAP", "LOW"],
                "research_priority": [
                    "research_now",
                    "theme_only",
                    "research_now",
                    "watch_for_pullback",
                ],
                "research_risks": [
                    "",
                    "",
                    "possible_value_trap",
                    "",
                ],
                "research_score": [2.0, 3.0, 4.0, 0.5],
            }
        )
        out = apply_low_value_research_gate(frame, cfg)
        self.assertEqual(out["symbol"].tolist(), ["KEEP"])

    def test_triage_labels_are_pure_and_channel_specific(self) -> None:
        frame = pd.DataFrame(
            {
                "channel": ["core_ai", "core_ai", "core_ai"],
                "composite_score": [0.8, 0.4, 0.2],
                "ps_discount": [0.2, 0.0, -0.1],
                "pe_discount": [0.2, 0.0, -0.1],
            }
        )
        before = frame.copy(deep=True)
        rules = {
            "keep": {
                "core_ai": {
                    "min_composite_score": 0.7,
                    "min_ps_discount": 0.1,
                    "min_pe_discount": 0.1,
                }
            },
            "drop": {
                "max_composite_score": 0.25,
                "require_both_value_premium": True,
            },
        }
        out = apply_triage_labels(frame, rules)
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(
            out["triage_label"].tolist(),
            ["keep", "watch", "drop"],
        )

    def test_scanner_and_replay_share_research_core(self) -> None:
        self.assertIs(
            scanner.build_research_assessment,
            build_research_assessment,
        )
        self.assertIs(
            scanner.apply_low_value_research_gate,
            apply_low_value_research_gate,
        )
        self.assertIs(
            backtest.build_research_assessment,
            build_research_assessment,
        )
        self.assertIs(
            backtest.apply_low_value_research_gate,
            apply_low_value_research_gate,
        )


if __name__ == "__main__":
    unittest.main()
