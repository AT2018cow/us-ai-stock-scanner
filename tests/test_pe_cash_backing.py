# Unit tests for the NI-based PE cheap-credit haircut in score_and_rank.
#
# Mechanism under test: after cross-sectional normalization, cheap-side
# (norm > 0.5) PE signals are shrunk toward 0.5 in proportion to OCF/NI
# cash backing. Expensive side is untouched; missing OCF/NI fails open.
import math
import unittest

import pandas as pd

from ai_value_scanner.scanner import score_and_rank


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": r["symbol"],
                "pe_discount": r.get("pe_discount"),
                "pe_percentile_in_sic": r.get("pe_percentile_in_sic", None),
                "ocf_to_net_income": r["ocf_to_net_income"],
            }
            for r in rows
        ]
    )


W_PE_ONLY = {"pe_discount": 1.0}
W_PE_PCT_ONLY = {"pe_percentile_low": 1.0}


class TestPeCashBackingHaircut(unittest.TestCase):
    def test_cash_poor_cheapest_name_demoted_below_cash_rich_peer(self):
        # 4 names; A has the lowest PE but no cash backing.
        df = make_df(
            [
                {"symbol": "A", "pe_discount": 0.9, "ocf_to_net_income": 0.0},
                {"symbol": "B", "pe_discount": 0.7, "ocf_to_net_income": 1.0},
                {"symbol": "C", "pe_discount": 0.5, "ocf_to_net_income": 1.0},
                {"symbol": "D", "pe_discount": 0.3, "ocf_to_net_income": 1.0},
            ]
        )
        before = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 0.0)
        after = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 1.0)
        self.assertEqual(list(before["symbol"]), ["A", "B", "C", "D"])
        self.assertEqual(list(after["symbol"]), ["B", "A", "C", "D"])

    def test_expensive_side_untouched(self):
        df = make_df(
            [
                {"symbol": "A", "pe_discount": 0.9, "ocf_to_net_income": 0.0},
                {"symbol": "B", "pe_discount": 0.7, "ocf_to_net_income": 1.0},
                {"symbol": "C", "pe_discount": 0.5, "ocf_to_net_income": 1.0},
                {"symbol": "D", "pe_discount": 0.3, "ocf_to_net_income": 1.0},
                {"symbol": "E", "pe_discount": -0.4, "ocf_to_net_income": 0.0},
                {"symbol": "F", "pe_discount": -0.6, "ocf_to_net_income": 1.0},
            ]
        )
        before = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 0.0)
        after = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 1.0)
        for sym in ("E", "F"):
            b = before.loc[before["symbol"] == sym].iloc[0]
            a = after.loc[after["symbol"] == sym].iloc[0]
            self.assertEqual(b["pe_discount_norm"], a["pe_discount_norm"])
            self.assertEqual(b["composite_score"], a["composite_score"])

    def test_missing_ocf_to_net_income_fails_open(self):
        df = make_df(
            [
                {"symbol": "A", "pe_discount": 0.9, "ocf_to_net_income": None},
                {"symbol": "B", "pe_discount": 0.7, "ocf_to_net_income": 1.0},
                {"symbol": "C", "pe_discount": 0.5, "ocf_to_net_income": 1.0},
                {"symbol": "D", "pe_discount": 0.3, "ocf_to_net_income": 1.0},
            ]
        )
        baseline = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 0.0)
        haircut = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 1.0)
        a_base = baseline.loc[baseline["symbol"] == "A"].iloc[0]
        a_cut = haircut.loc[haircut["symbol"] == "A"].iloc[0]
        self.assertEqual(a_base["pe_discount_norm"], a_cut["pe_discount_norm"])
        self.assertEqual(a_base["composite_score"], a_cut["composite_score"])

    def test_negative_ocf_to_net_income_collapses_cheap_credit_to_neutral(self):
        df = make_df(
            [
                {"symbol": "A", "pe_discount": 0.9, "ocf_to_net_income": -0.5},
                {"symbol": "B", "pe_discount": 0.7, "ocf_to_net_income": 1.0},
                {"symbol": "C", "pe_discount": 0.5, "ocf_to_net_income": 1.0},
                {"symbol": "D", "pe_discount": 0.3, "ocf_to_net_income": 1.0},
            ]
        )
        out = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 1.0)
        a = out.loc[out["symbol"] == "A"].iloc[0]
        self.assertEqual(a["pe_discount_norm"], 0.5)

    def test_haircut_strength_blends_factor(self):
        # With strength 0.5 and ocf/ni 0.5: factor = 1 - 0.5*(1-0.5) = 0.75.
        df = make_df(
            [
                {"symbol": "A", "pe_discount": 0.6, "ocf_to_net_income": 0.5},
                {"symbol": "B", "pe_discount": 0.4, "ocf_to_net_income": 0.5},
            ]
        )
        out = score_and_rank(df, W_PE_ONLY, 0.05, 0.95, 0.0, 0.0, 0.5)
        a = out.loc[out["symbol"] == "A"].iloc[0]
        expected = 0.5 + (sigmoid(1.0) - 0.5) * 0.75
        self.assertAlmostEqual(a["pe_discount_norm"], expected, places=12)
        self.assertAlmostEqual(a["composite_score"], expected, places=12)

    def test_pe_percentile_low_also_shrunk(self):
        # Percentiles at or below 0.5 keep the overvaluation penalty at zero,
        # isolating the haircut effect on pe_percentile_low.
        df = make_df(
            [
                {"symbol": "A", "pe_percentile_in_sic": 0.1, "ocf_to_net_income": 0.0},
                {"symbol": "B", "pe_percentile_in_sic": 0.2, "ocf_to_net_income": 1.0},
                {"symbol": "C", "pe_percentile_in_sic": 0.4, "ocf_to_net_income": 1.0},
            ]
        )
        before = score_and_rank(df, W_PE_PCT_ONLY, 0.05, 0.95, 0.0, 0.0, 0.0)
        after = score_and_rank(df, W_PE_PCT_ONLY, 0.05, 0.95, 0.0, 0.0, 1.0)
        a_before = before.loc[before["symbol"] == "A"].iloc[0]
        a_after = after.loc[after["symbol"] == "A"].iloc[0]
        b_before = before.loc[before["symbol"] == "B"].iloc[0]
        b_after = after.loc[after["symbol"] == "B"].iloc[0]
        self.assertEqual(list(before["symbol"]), ["A", "B", "C"])
        # A (cash poor) is demoted below B (cash rich) after the haircut.
        self.assertEqual(list(after["symbol"]), ["B", "A", "C"])
        self.assertLess(a_after["pe_percentile_low_norm"], a_before["pe_percentile_low_norm"])
        # B's cheap credit is untouched (cash backed).
        self.assertEqual(b_before["pe_percentile_low_norm"], b_after["pe_percentile_low_norm"])


if __name__ == "__main__":
    unittest.main()
