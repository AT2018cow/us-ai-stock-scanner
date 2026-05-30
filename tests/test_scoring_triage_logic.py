from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.scanner import assign_triage_label, robust_normalize_score


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


if __name__ == "__main__":
    unittest.main()
