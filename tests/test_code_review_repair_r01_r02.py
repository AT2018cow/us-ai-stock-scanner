"""R01/R02 repair tests: accounting completeness states and signed growth.

R01: missing debt / cash / inventory inputs must never become positive
Company-Quality evidence, while explicitly reported zeros and normal
disclosure keep working.

R02: negative prior-period bases must not invert the economic direction of
earnings / operating-cash-flow growth.
"""

from __future__ import annotations

import unittest

from ai_value_scanner.decision.quality import (
    build_company_quality_v1,
    build_company_quality_v2,
)
from ai_value_scanner.fundamentals.accounting import (
    derive_accounting_metrics,
    growth_direction,
)


def _accounting_args(**overrides):
    args = {
        "revenue": 1000.0,
        "revenue_prev": 900.0,
        "net_income": 100.0,
        "net_income_prev": 90.0,
        "operating_cash_flow": 120.0,
        "operating_cash_flow_prev": 100.0,
        "capex_raw": -20.0,
        "ebit": 150.0,
        "ebit_prev": 130.0,
        "shares": 100.0,
        "shares_prev": 100.0,
        "cash_and_equivalents": 200.0,
        "debt_long_term": 50.0,
        "debt_current": 20.0,
        "current_assets": 500.0,
        "current_liabilities": 200.0,
        "receivables_current": 100.0,
        "receivables_prev": 90.0,
        "inventory_current": 80.0,
        "inventory_prev": 70.0,
        "interest_expense": -5.0,
        "depreciation_and_amortization": 20.0,
        "depreciation_and_amortization_prev": 18.0,
        "adjusted_net_income": 110.0,
        "adjusted_net_income_prev": 95.0,
        "adjusted_ebit": 160.0,
        "adjusted_ebit_prev": 135.0,
        "adjusted_ebitda": 180.0,
    }
    args.update(overrides)
    return args


def _evidence_codes(quality):
    return {
        "positives": {item.code for item in quality.positives},
        "risks": {item.code for item in quality.risks},
        "missing": {item.code for item in quality.missing},
    }


class TestDebtCompleteness(unittest.TestCase):
    def test_missing_debt_never_becomes_net_cash_evidence(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(debt_long_term=None, debt_current=None)
        )
        self.assertIsNone(metrics["total_debt"])
        self.assertIsNone(metrics["net_debt"])
        self.assertEqual(metrics["total_debt_source"], "missing")
        self.assertEqual(metrics["net_debt_source"], "missing")
        self.assertIsNone(metrics["net_debt_to_ebitda"])
        self.assertEqual(metrics["net_debt_to_ebitda_source"], "missing")

        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertNotIn("net_debt_to_ebitda_strong", codes["positives"])
                self.assertIn("net_debt_to_ebitda_missing", codes["missing"])

    def test_partial_debt_is_flagged_and_cannot_support_quality(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(debt_long_term=50.0, debt_current=None)
        )
        self.assertEqual(metrics["total_debt"], 50.0)
        self.assertEqual(metrics["total_debt_source"], "partial")
        self.assertEqual(metrics["net_debt_source"], "partial")
        self.assertEqual(metrics["net_debt_to_ebitda_source"], "partial")

        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertNotIn("net_debt_to_ebitda_strong", codes["positives"])
                self.assertIn("net_debt_to_ebitda_incomplete", codes["missing"])

    def test_partial_debt_high_leverage_still_raises_risk(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(
                debt_long_term=6000.0,
                debt_current=None,
                adjusted_ebitda=1000.0,
            )
        )
        self.assertEqual(metrics["net_debt_to_ebitda_source"], "partial")
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertIn("net_debt_to_ebitda_weak_incomplete", codes["risks"])
                self.assertNotIn("net_debt_to_ebitda_strong", codes["positives"])

    def test_missing_cash_makes_net_debt_unknown(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(cash_and_equivalents=None)
        )
        self.assertIsNone(metrics["net_debt"])
        self.assertEqual(metrics["net_debt_source"], "missing")
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertNotIn("net_debt_to_ebitda_strong", codes["positives"])

    def test_explicit_zero_debt_net_cash_still_supports_quality(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(
                debt_long_term=0.0,
                debt_current=0.0,
                cash_and_equivalents=500.0,
            )
        )
        self.assertEqual(metrics["total_debt"], 0.0)
        self.assertEqual(metrics["total_debt_source"], "reported")
        self.assertEqual(metrics["net_debt"], -500.0)
        self.assertEqual(metrics["net_debt_to_ebitda_source"], "reported")
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertIn("net_debt_to_ebitda_strong", codes["positives"])
                self.assertNotIn("net_debt_to_ebitda_incomplete", codes["missing"])


class TestInventoryCompleteness(unittest.TestCase):
    def test_missing_inventory_stays_missing(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(inventory_current=None, inventory_prev=None)
        )
        self.assertIsNone(metrics["inventory_growth_gap"])
        self.assertEqual(metrics["inventory_growth_gap_source"], "missing")
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertNotIn("inventory_growth_gap_strong", codes["positives"])
                self.assertIn("inventory_growth_gap_missing", codes["missing"])

    def test_partial_inventory_missing_stays_missing(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(inventory_current=80.0, inventory_prev=None)
        )
        self.assertIsNone(metrics["inventory_growth_gap"])
        self.assertEqual(metrics["inventory_growth_gap_source"], "missing")

    def test_reported_zero_inventory_uses_zero_growth(self) -> None:
        metrics = derive_accounting_metrics(
            **_accounting_args(
                inventory_current=0.0,
                inventory_prev=0.0,
                revenue=1200.0,
                revenue_prev=1000.0,
            )
        )
        self.assertEqual(metrics["inventory_growth_gap_source"], "reported")
        self.assertAlmostEqual(metrics["inventory_growth_gap"], -0.2, places=12)
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertIn("inventory_growth_gap_strong", codes["positives"])

    def test_normal_inventory_yoy_unchanged(self) -> None:
        metrics = derive_accounting_metrics(**_accounting_args())
        expected = (80.0 / 70.0 - 1.0) - (1000.0 / 900.0 - 1.0)
        self.assertEqual(metrics["inventory_growth_gap_source"], "reported")
        self.assertAlmostEqual(metrics["inventory_growth_gap"], expected, places=12)


class TestGrowthDirection(unittest.TestCase):
    def test_sign_matrix(self) -> None:
        cases = [
            (100.0, 100.0, "positive_base", 0.0),
            (120.0, 100.0, "positive_base", 0.2),
            (-50.0, -100.0, "both_negative", 0.5),
            (-200.0, -100.0, "both_negative", -1.0),
            (100.0, -100.0, "turnaround", 2.0),
            (-100.0, 100.0, "reversal", -2.0),
            (100.0, 0.0, "incomparable", None),
            (None, 100.0, None, None),
            (100.0, None, None, None),
        ]
        for latest, previous, direction, change in cases:
            with self.subTest(latest=latest, previous=previous):
                got_direction, got_change = growth_direction(latest, previous)
                self.assertEqual(got_direction, direction)
                if change is None:
                    self.assertIsNone(got_change)
                else:
                    self.assertAlmostEqual(got_change, change, places=12)


class TestNegativeBaseQuality(unittest.TestCase):
    def _quality(self, builder, latest, previous):
        metrics = {
            "adjusted_net_income": latest,
            "adjusted_net_income_prev": previous,
            "adjusted_net_income_yoy": (
                None if previous == 0 else latest / previous - 1.0
            ),
        }
        direction, change = growth_direction(latest, previous)
        metrics["adjusted_net_income_growth_direction"] = direction
        metrics["adjusted_net_income_growth"] = change
        return builder(metrics, decision_date="2026-10-09", data_asof="2026-08-01")

    def test_loss_widening_is_not_strong_growth(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = self._quality(builder, -200.0, -100.0)
                codes = _evidence_codes(quality)
                self.assertNotIn("adjusted_net_income_yoy_strong", codes["positives"])
                self.assertIn("adjusted_net_income_yoy_loss_widened", codes["risks"])

    def test_loss_narrowing_is_recovery_not_strong_growth(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = self._quality(builder, -50.0, -100.0)
                codes = _evidence_codes(quality)
                self.assertNotIn("adjusted_net_income_yoy_strong", codes["positives"])
                self.assertIn("adjusted_net_income_yoy_loss_narrowed", codes["positives"])

    def test_turnaround_is_not_strong_growth(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = self._quality(builder, 100.0, -100.0)
                codes = _evidence_codes(quality)
                self.assertNotIn("adjusted_net_income_yoy_strong", codes["positives"])
                self.assertIn("adjusted_net_income_yoy_turnaround", codes["positives"])

    def test_reversal_is_risk(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = self._quality(builder, -100.0, 100.0)
                codes = _evidence_codes(quality)
                self.assertNotIn("adjusted_net_income_yoy_strong", codes["positives"])
                self.assertIn("adjusted_net_income_yoy_reversal", codes["risks"])

    def test_zero_base_is_incomparable(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = self._quality(builder, 100.0, 0.0)
                codes = _evidence_codes(quality)
                self.assertNotIn("adjusted_net_income_yoy_strong", codes["positives"])
                self.assertIn(
                    "adjusted_net_income_yoy_incomparable_base", codes["missing"]
                )

    def test_positive_base_path_unchanged(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = self._quality(builder, 120.0, 100.0)
                codes = _evidence_codes(quality)
                self.assertIn("adjusted_net_income_yoy_strong", codes["positives"])

    def test_ocf_loss_widening_is_not_strong_growth(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                metrics = {
                    "operating_cash_flow_growth": -1.0,
                    "operating_cash_flow_growth_direction": "both_negative",
                    "operating_cash_flow_yoy": 1.0,
                }
                quality = builder(
                    metrics, decision_date="2026-10-09", data_asof="2026-08-01"
                )
                codes = _evidence_codes(quality)
                self.assertNotIn(
                    "operating_cash_flow_yoy_strong", codes["positives"]
                )
                self.assertIn("operating_cash_flow_yoy_loss_widened", codes["risks"])

    def test_legacy_yoy_only_dict_keeps_old_behavior(self) -> None:
        for builder in (build_company_quality_v1, build_company_quality_v2):
            with self.subTest(builder=builder.__name__):
                quality = builder(
                    {"adjusted_net_income_yoy": 0.20},
                    decision_date="2026-10-09",
                    data_asof="2026-08-01",
                )
                codes = _evidence_codes(quality)
                self.assertIn("adjusted_net_income_yoy_strong", codes["positives"])


if __name__ == "__main__":
    unittest.main()
