"""Unit tests for Phase M4 dual-track paired validation (synthetic only).

Covers paired date-equal excess, block bootstrap CI determinism, LOO
sensitivity, human-utility metrics, bespoke-vs-production fidelity,
Report v2 parity, and honest epistemic labeling. No network, no frozen
datasets, no production modification.
"""

from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.research import m4_paired_validation as m4


def _row(symbol: str, signal_date: str = "2023-01-31", **overrides) -> dict:
    base = {
        "symbol": symbol, "signal_date": signal_date,
        "fundamental_data_asof": "2023-01-20", "market_asof": signal_date,
        "net_margin": 0.15, "free_cash_flow": 100.0, "revenue": 1000.0,
        "ocf_to_net_income": 1.50, "accrual_ratio": -0.25,
        "revenue_yoy": 0.30, "adjusted_net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.25, "ebit": 150.0, "adjusted_ebit": 160.0,
        "net_debt_to_ebitda": 1.0, "interest_coverage": 6.0, "current_ratio": 2.0,
        "shares_yoy": 0.01, "fcf_yield": 0.04,
        "ps_hist_percentile": 0.50, "pe_hist_percentile": 0.50,
        "receivables_growth_gap": 0.20, "inventory_growth_gap": 0.05,
        "price_to_sma200": 1.05, "price_to_sma50": 1.03, "days_below_sma200": 0,
        "return_20d": 0.05, "return_60d": 0.10, "drawdown_from_52w_high": 0.10,
        "range_position_52w": 0.82, "relative_strength_60d_qqq": 0.02,
        "volatility_60d": 0.30, "regime": "up", "benchmark_trend_ok": True,
        "fwd_ret_20": 0.02, "fwd_ret_60": 0.05, "fwd_ret_120": 0.08,
        "qqq_return_20": 0.01, "qqq_return_60": 0.02, "qqq_return_120": 0.03,
    }
    base.update(overrides)
    return base


class TestPartitions(unittest.TestCase):
    def test_dev_post_all_split(self) -> None:
        dates = ["2023-01-31", "2024-12-31", "2025-01-31", "2026-03-31"]
        parts = m4.partition_dates(dates)
        self.assertEqual(parts["DEV_2023_2024"], ["2023-01-31", "2024-12-31"])
        self.assertEqual(parts["POST2024_HELD_OUT"], ["2025-01-31", "2026-03-31"])
        self.assertEqual(parts["ALL_39_DATES"], sorted(dates))

    def test_tiers_are_honest(self) -> None:
        self.assertEqual(m4.TIER_DEV, "RETROSPECTIVE_DEVELOPMENT")
        self.assertIn("HELD_OUT", m4.TIER_POST2024)
        self.assertIn("REPLAY", m4.TIER_ALL)
        self.assertNotIn("OOS", m4.TIER_POST2024 + m4.TIER_ALL + m4.TIER_DEV)

    def test_year_and_regime_buckets(self) -> None:
        self.assertEqual(m4.year_bucket("2026-02-27"), "2026Q1")
        self.assertEqual(m4.year_bucket("2024-06-28"), "2024")
        self.assertEqual(m4.regime_class("up", True), "UP_SUPPORTIVE")
        self.assertEqual(m4.regime_class("down", True), "DEFENSIVE_OR_DOWN")
        self.assertEqual(m4.regime_class("up", False), "DEFENSIVE_OR_DOWN")
        self.assertEqual(m4.regime_class(None, None), "UNCLASSIFIED")


class TestBespokeFidelity(unittest.TestCase):
    def test_matches_production_all_variants(self) -> None:
        frame = pd.DataFrame([
            _row("AAA"), _row("BBB", net_margin=-0.05, accrual_ratio=0.30),
            _row("CCC", price_to_sma200=0.90),
        ])
        bespoke = m4.evaluate_date_frame(frame, "2023-01-31")
        combos = {"v1_baseline": {}, "h1_quality_only": {"quality_version": "v2"},
                  "h2_entry_only": {"entry_version": "v2"},
                  "h3_action_only": {"action_version": "v2"},
                  "v2_combined": {"policy_version": "v2"}}
        for variant, kwargs in combos.items():
            with self.subTest(variant=variant):
                reference = {d.symbol: d for d in build_stock_decisions(
                    frame, decision_date="2023-01-31",
                    generated_at_utc="2023-01-31T23:59:59+00:00", **kwargs)}
                for record in bespoke[variant]["records"]:
                    decision = reference[record.symbol]
                    self.assertEqual(record.grade, decision.quality.grade.value)
                    self.assertEqual(record.state, decision.entry.state.value)
                    self.assertEqual(record.action, decision.action_state.value)
                    self.assertEqual(record.priority, decision.priority)
                    self.assertEqual(record.quality_score, decision.quality.score)
                    self.assertEqual(record.entry_score, decision.entry.score)


class TestHumanUtility(unittest.TestCase):
    def test_contradictory_and_silent(self) -> None:
        frame = pd.DataFrame([
            _row("CASHCOW"),  # negative accrual + strong conversion -> contradictory
            _row("CLEAN", accrual_ratio=0.02),
        ])
        records = m4.evaluate_date_frame(frame, "2023-01-31")["v1_baseline"]["records"]
        utility = m4.human_utility_for_scope(records)
        self.assertEqual(utility["n_contradictory_cash_accrual"], 1)
        # positive-accrual weak + strong conversion is legitimate signal, not contradiction
        frame2 = pd.DataFrame([_row("AGG", accrual_ratio=0.30)])
        records2 = m4.evaluate_date_frame(frame2, "2023-01-31")["v1_baseline"]["records"]
        utility2 = m4.human_utility_for_scope(records2)
        self.assertEqual(utility2["n_contradictory_cash_accrual"], 0)

    def test_top15_shares(self) -> None:
        rows = [_row(f"S{i:02d}",
                     price_to_sma200=1.05 if i < 10 else 0.90) for i in range(20)]
        frame = pd.DataFrame(rows)
        records = m4.evaluate_date_frame(frame, "2023-01-31")["v1_baseline"]["records"]
        utility = m4.human_utility_for_scope(records)
        self.assertIsNotNone(utility["mean_top15_ready_share"])
        self.assertGreaterEqual(utility["mean_top15_ready_share"], 0.0)
        self.assertLessEqual(utility["mean_top15_ready_share"], 1.0)


class TestPairedEconomics(unittest.TestCase):
    def test_date_means_and_summary(self) -> None:
        frame = pd.DataFrame([
            _row("A", fwd_ret_60=0.10, qqq_return_60=0.02),
            _row("B", fwd_ret_60=float("nan"), qqq_return_60=0.02),
        ])
        mean, n_obs = m4.date_cohort_excess(frame, {"A", "B", "ZZZ"}, 60)
        self.assertAlmostEqual(mean, 0.08)
        self.assertEqual(n_obs, 1)
        summary = m4.summarize_date_means([0.10, -0.04, 0.03])
        self.assertEqual(summary["n_matured_dates"], 3)
        self.assertAlmostEqual(summary["mean"], 0.03)
        self.assertAlmostEqual(summary["worst"], -0.04)
        empty = m4.summarize_date_means([])
        self.assertEqual(empty["n_matured_dates"], 0)
        self.assertIsNone(empty["mean"])

    def test_paired_deltas_bootstrap_loo(self) -> None:
        variant = {"2023-01-31": 0.05, "2023-02-28": 0.01, "2023-03-31": -0.02}
        baseline = {"2023-01-31": 0.02, "2023-02-28": 0.02, "2023-03-31": 0.02,
                    "2023-04-28": 0.02}
        first = m4.paired_delta_stats(variant, baseline)
        second = m4.paired_delta_stats(variant, baseline)
        self.assertEqual(first, second)  # deterministic seed
        self.assertAlmostEqual(first["mean_paired_delta_60d"], -0.006667)
        self.assertLessEqual(first["ci95_low_60d"], first["mean_paired_delta_60d"])
        self.assertGreaterEqual(first["ci95_high_60d"], first["mean_paired_delta_60d"])
        self.assertLessEqual(first["loo_min_mean_delta_60d"], first["mean_paired_delta_60d"])
        self.assertEqual(first["n_paired_dates"], 3)  # unpaired date ignored
        empty = m4.paired_delta_stats({}, {})
        self.assertIsNone(empty["mean_paired_delta_60d"])

    def test_embargo_by_construction(self) -> None:
        # periods are explicit date lists; a 2025 date can never enter DEV means
        parts = m4.partition_dates(["2023-01-31", "2025-06-30"])
        self.assertNotIn("2025-06-30", parts["DEV_2023_2024"])
        self.assertIn("2025-06-30", parts["POST2024_HELD_OUT"])


class TestGateRules(unittest.TestCase):
    def test_human_verdict(self) -> None:
        v1 = {"n_contradictory_cash_accrual": 10, "n_silent_non_ready_entry": 0,
              "mean_top15_ready_share": 0.90}
        good = {"n_contradictory_cash_accrual": 0, "n_silent_non_ready_entry": 0,
                "mean_top15_ready_share": 0.92}
        self.assertEqual(m4.human_utility_verdict(good, v1)["verdict"], "PASS")
        self.assertEqual(m4.human_utility_verdict(v1, v1)["verdict"], "FAIL")
        worse_share = dict(good, mean_top15_ready_share=0.80)
        self.assertEqual(m4.human_utility_verdict(worse_share, v1)["verdict"], "FAIL")

    def test_economic_verdict_classes(self) -> None:
        self.assertEqual(
            m4.economic_verdict({"mean_paired_delta_60d": 0.01,
                                 "loo_min_mean_delta_60d": 0.002,
                                 "ci95_low_60d": 0.001}), "POSITIVE_ROBUST")
        self.assertEqual(
            m4.economic_verdict({"mean_paired_delta_60d": 0.01,
                                 "loo_min_mean_delta_60d": -0.002,
                                 "ci95_low_60d": -0.005}),
            "POSITIVE_POINT_ESTIMATE_CI_WIDE")
        self.assertEqual(
            m4.economic_verdict({"mean_paired_delta_60d": -0.01,
                                 "loo_min_mean_delta_60d": -0.02,
                                 "ci95_low_60d": -0.03}), "NEGATIVE_OR_FLAT")
        self.assertEqual(
            m4.economic_verdict({"mean_paired_delta_60d": None,
                                 "loo_min_mean_delta_60d": None,
                                 "ci95_low_60d": None}), "NEGATIVE_OR_FLAT")

    def test_overall_recommendation(self) -> None:
        human = {"v2_combined": {"verdict": "PASS"},
                 "h1_quality_only": {"verdict": "PASS"}}
        post = {"v2_combined": "POSITIVE_ROBUST", "h1_quality_only": "NEGATIVE_OR_FLAT"}
        allp = {"v2_combined": "POSITIVE_ROBUST", "h1_quality_only": "NEGATIVE_OR_FLAT"}
        out = m4.overall_recommendation(human, post, allp)
        self.assertEqual(out["shadow_candidates"], ["v2_combined"])
        self.assertIn('policy_version="v1"', out["recommendation"])
        out = m4.overall_recommendation(
            {"v2_combined": {"verdict": "FAIL"}}, post, allp)
        self.assertEqual(out["shadow_candidates"], [])
        self.assertIn("Retain v1", out["recommendation"])


class TestReportParity(unittest.TestCase):
    def test_render_and_check_v2(self) -> None:
        frame = pd.DataFrame([_row("AAA"), _row("BBB", net_margin=-0.05)])
        decisions = build_stock_decisions(
            frame, decision_date="2023-01-31",
            generated_at_utc="2023-01-31T23:59:59+00:00")
        check = m4.render_and_check_v2(decisions, title="M4 test")
        self.assertTrue(check["report_v2_parity_ok"])
        self.assertEqual(check["n_exceptions"], 0)
        self.assertEqual(check["n_absolute_paths"], 0)

    def test_no_absolute_paths(self) -> None:
        self.assertTrue(m4.contains_absolute_path("see /home/user/x.md"))
        self.assertTrue(m4.contains_absolute_path("wrote /tmp/abc/y.csv"))
        self.assertFalse(m4.contains_absolute_path("docs/m4_paired_validation_20261015/x.md"))


class TestFrozenAdapter(unittest.TestCase):
    def test_scored_row_from_frozen(self) -> None:
        decision = {
            "symbol": "crm", "decision_date": "2026-10-12", "priority": 10,
            "quality": {"grade": "A", "score": 0.84, "confidence": 1.0,
                        "positives": [{"code": "ocf_to_net_income_strong",
                                       "metric": "ocf_to_net_income", "value": 1.5}],
                        "risks": [], "missing": []},
            "entry": {"state": "WATCH_BREAKOUT", "score": 0.9, "confidence": 1.0,
                      "positives": [{"code": "price_above_sma200",
                                     "metric": "price_to_sma200", "value": 1.17}],
                      "risks": []},
            "action_state": "WATCH_BREAKOUT",
        }
        record = m4.scored_row_from_frozen(decision)
        self.assertEqual(record.symbol, "CRM")
        self.assertAlmostEqual(record.ocf_to_net_income, 1.5)
        self.assertIsNone(record.accrual_ratio)  # silent stays missing
        self.assertIn("ocf_to_net_income_strong", record.quality_positives)


if __name__ == "__main__":
    unittest.main()
