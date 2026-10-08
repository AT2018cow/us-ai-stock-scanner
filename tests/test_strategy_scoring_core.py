from __future__ import annotations

import unittest

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.strategy.scoring import (
    robust_normalize_score,
    score_and_rank,
)


class TestSharedScoringCore(unittest.TestCase):
    def test_robust_normalization_golden_and_missing_neutral(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0, None], index=["A", "B", "C", "D"])
        out = robust_normalize_score(series, 0.0, 1.0)

        self.assertAlmostEqual(float(out.loc["A"]), 0.22710251943568419, places=12)
        self.assertEqual(float(out.loc["B"]), 0.5)
        self.assertAlmostEqual(float(out.loc["C"]), 0.7728974805643158, places=12)
        self.assertEqual(float(out.loc["D"]), 0.5)

    def test_score_and_rank_is_pure_and_preserves_value_order(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "ps_discount": [1.0, 2.0, 3.0],
            }
        )
        before = frame.copy(deep=True)
        out = score_and_rank(
            frame,
            {"ps_discount": 1.0},
            0.0,
            1.0,
            overvaluation_penalty_weight=0.0,
            deterioration_penalty_weight=0.0,
            pe_cash_backing_haircut=0.0,
        )

        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(out["symbol"].tolist(), ["C", "B", "A"])
        by_symbol = out.set_index("symbol")
        self.assertAlmostEqual(
            float(by_symbol.loc["A", "ps_discount_norm"]),
            0.22710251943568419,
            places=12,
        )
        self.assertEqual(float(by_symbol.loc["B", "composite_score"]), 0.5)
        self.assertAlmostEqual(
            float(by_symbol.loc["C", "composite_score"]),
            0.7728974805643158,
            places=12,
        )

    def test_soft_pass_rate_contributes_exactly(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "soft_pass_count": [0.0, 2.0, 4.0],
                "soft_total": [4.0, 4.0, 4.0],
            }
        )
        out = score_and_rank(
            frame,
            {"soft_pass_rate": 1.0},
            0.05,
            0.95,
            overvaluation_penalty_weight=0.0,
            deterioration_penalty_weight=0.0,
            pe_cash_backing_haircut=0.0,
        )
        by_symbol = out.set_index("symbol")
        self.assertEqual(float(by_symbol.loc["A", "soft_pass_rate"]), 0.0)
        self.assertEqual(float(by_symbol.loc["B", "soft_pass_rate"]), 0.5)
        self.assertEqual(float(by_symbol.loc["C", "soft_pass_rate"]), 1.0)
        self.assertEqual(out["symbol"].tolist(), ["C", "B", "A"])

    def test_penalty_formulas_are_pinned(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A"],
                "ps_percentile_in_sic": [0.8],
                "pe_percentile_in_sic": [0.7],
                "revenue_yoy": [-0.3],
                "adjusted_net_income_yoy": [-0.6],
                "net_income_yoy": [-0.1],
            }
        )
        out = score_and_rank(
            frame,
            {},
            0.05,
            0.95,
            overvaluation_penalty_weight=0.2,
            deterioration_penalty_weight=0.3,
            pe_cash_backing_haircut=0.0,
        )
        row = out.iloc[0]
        self.assertAlmostEqual(float(row["overvaluation_penalty"]), 0.5, places=12)
        self.assertAlmostEqual(float(row["deterioration_penalty"]), 0.6, places=12)
        # Default component weights contribute neutral 0.5 for the missing
        # default-weight components: 0.40+0.30+0.05+0.10+0.10 = 0.95.
        # Base = 0.475; penalties = 0.10 + 0.18.
        self.assertAlmostEqual(float(row["composite_score"]), 0.195, places=12)

    def test_pe_cash_backing_haircut_remains_one_sided(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B"],
                "pe_discount": [0.8, 0.2],
                "ocf_to_net_income": [0.0, 1.0],
            }
        )
        out = score_and_rank(
            frame,
            {"pe_discount": 1.0},
            0.0,
            1.0,
            overvaluation_penalty_weight=0.0,
            deterioration_penalty_weight=0.0,
            pe_cash_backing_haircut=1.0,
        )
        by_symbol = out.set_index("symbol")
        self.assertEqual(float(by_symbol.loc["A", "pe_discount_norm"]), 0.5)
        self.assertLess(float(by_symbol.loc["B", "pe_discount_norm"]), 0.5)

    def test_scanner_and_replay_reference_same_scoring_core(self) -> None:
        self.assertIs(scanner.robust_normalize_score, robust_normalize_score)
        self.assertIs(scanner.score_and_rank, score_and_rank)
        self.assertIs(backtest.score_and_rank, score_and_rank)


if __name__ == "__main__":
    unittest.main()
