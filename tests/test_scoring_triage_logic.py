from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.scanner import (
    assign_triage_label,
    build_research_assessment,
    robust_normalize_score,
)


class TestScoringTriageLogic(unittest.TestCase):
    def test_robust_normalize_score_missing_is_neutral(self) -> None:
        series = pd.Series([1.0, None, 3.0], dtype="float64")
        norm = robust_normalize_score(series, 0.05, 0.95)
        self.assertEqual(len(norm), 3)
        self.assertFalse(norm.isna().any())
        self.assertAlmostEqual(float(norm.iloc[1]), 0.5, places=6)

    def test_triage_drop_respects_require_both_value_premium(self) -> None:
        triage_rules = {
            "keep": {},
            "drop": {
                "max_composite_score": 0.35,
                "require_both_value_premium": True,
            },
        }
        row_not_drop = pd.Series(
            {
                "channel": "ai_peripheral",
                "composite_score": 0.20,
                "ps_discount": -0.10,
                "pe_discount": 0.10,
            }
        )
        row_drop = pd.Series(
            {
                "channel": "ai_peripheral",
                "composite_score": 0.20,
                "ps_discount": -0.10,
                "pe_discount": -0.05,
            }
        )
        self.assertEqual(assign_triage_label(row_not_drop, triage_rules), "watch")
        self.assertEqual(assign_triage_label(row_drop, triage_rules), "drop")

    def test_research_assessment_flags_high_quality_value_candidate(self) -> None:
        row = pd.Series(
            {
                "ps_hist_percentile": 0.15,
                "pe_hist_percentile": 0.20,
                "ps_discount": 0.18,
                "pe_discount": 0.12,
                "fundamental_quality_score": 0.90,
                "ai_link_score": 0.58,
                "fcf_yield": 0.08,
                "ev_to_ebit": 9.0,
                "pe": 14.0,
                "ps": 2.0,
                "revenue_yoy": 0.12,
                "net_income_yoy": 0.18,
                "return_20d": 0.02,
                "return_60d": 0.04,
                "drawdown_from_52w_high": 0.14,
                "price_to_sma200": 0.98,
                "watchlist_bucket": "ai_enabler",
                "watchlist_etfs": "GRID,PAVE",
                "channel": "ai_enabler",
            }
        )
        assessment = build_research_assessment(row, "low_value")
        self.assertEqual(assessment["research_priority"], "research_now")
        self.assertIn("cheap_relative_to_history", assessment["research_tags"])
        self.assertIn("quality_compounder", assessment["research_tags"])
        self.assertIn("strong_ai_link", assessment["research_tags"])

    def test_research_assessment_does_not_call_expensive_candidate_cheap(self) -> None:
        row = pd.Series(
            {
                "ps_hist_percentile": 0.80,
                "pe_hist_percentile": 0.85,
                "ps_discount": -0.30,
                "pe_discount": -0.20,
                "fundamental_quality_score": 0.92,
                "ai_link_score": 0.62,
                "fcf_yield": 0.02,
                "ev_to_ebit": 34.0,
                "pe": 38.0,
                "ps": 12.0,
                "revenue_yoy": 0.16,
                "net_income_yoy": 0.22,
                "return_20d": 0.08,
                "return_60d": 0.18,
                "drawdown_from_52w_high": 0.03,
                "price_to_sma200": 1.20,
                "watchlist_bucket": "core_ai",
                "watchlist_etfs": "AIQ,SMH",
                "channel": "core_ai",
            }
        )
        assessment = build_research_assessment(row, "momentum")
        self.assertEqual(assessment["research_priority"], "watch_for_pullback")
        self.assertIn("high_absolute_valuation", assessment["research_risks"])
        self.assertNotIn("cheap_relative_to_history", assessment["research_tags"])


if __name__ == "__main__":
    unittest.main()
