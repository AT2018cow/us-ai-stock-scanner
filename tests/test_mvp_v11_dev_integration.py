"""Synthetic full 24-month execution contract: no real v3 or external data."""
from __future__ import annotations

import unittest

import pandas as pd

from scripts.mvp_v11_candidate_preflight import run_preflight
from scripts.mvp_v11_dev_return_experiment import evaluate_development


class TestSyntheticDevReturnIntegration(unittest.TestCase):
    def test_only_24_development_dates_1440_paired_rows(self):
        rows = []
        dates = pd.date_range("2023-01-31", periods=24, freq="ME")
        for day in dates:
            dt = day.strftime("%Y-%m-%d")
            for i in range(16):
                rows.append({
                    "signal_date": dt,
                    "symbol": f"S{i:02d}",
                    "market_asof": dt,
                    "fundamental_data_asof": (day - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                    "price_to_sma200": 1.04,
                    "price_to_sma50": 1.02,
                    "return_20d": .05,
                    "return_60d": .09,
                    "relative_strength_60d_qqq": -.01 if i % 2 else .07,
                    "drawdown_from_52w_high": .12,
                    "range_position_52w": .7,
                    "regime": "up",
                    "fwd_ret_20": .03 + i / 10000,
                    "qqq_return_20": .01,
                    "fwd_ret_60": .06 + i / 10000,
                    "qqq_return_60": .02,
                    "fwd_ret_120": .08 + i / 10000,
                    "qqq_return_120": .03,
                    "label_end_20": (day + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                    "label_end_60": (day + pd.Timedelta(days=90)).strftime("%Y-%m-%d"),
                    "label_end_120": (day + pd.Timedelta(days=180)).strftime("%Y-%m-%d"),
                })
        frame = pd.DataFrame(rows)
        events = pd.DataFrame([
            {"symbol": "WOLF", "prev_date": "2023-01-31", "date": "2023-02-28",
             "reason": "REORG_JUMP_BACKDATED", "null_labels": True},
        ] + [
            {"symbol": f"BAD{i}", "prev_date": "2023-01-31",
             "date": "2023-02-28", "reason": "SHARE_JUMP_UNEXPLAINED",
             "null_labels": False}
            for i in range(51)
        ])
        review = pd.DataFrame(columns=[
            "symbol", "event_date", "severe_shares_change", "null_labels",
        ])
        preflight, _, _ = run_preflight(frame, events=review)
        paired, diff, migration, metrics, diagnostics = evaluate_development(
            frame, events=events, event_review=review,
            frozen_membership=preflight,
        )
        self.assertEqual(len(paired), 1440)
        self.assertEqual(paired.signal_date.nunique(), 24)
        self.assertEqual(set(paired.horizon), {20, 60, 120})
        self.assertEqual(set(paired.cap), {5, 15})
        self.assertEqual(len(metrics), 180)  # dev, 2023, 2024 ×10×3×2
        self.assertEqual(set(metrics.period), {
            "2023", "2024", "2023_2024_development",
        })
        self.assertTrue(paired.primary_paired_valid.all())
        self.assertTrue(metrics.loc[
            metrics.candidate_id == "B0", "mean_paired_delta"
        ].abs().lt(1e-9).all())
        self.assertTrue(set(diff.columns) >= {
            "added" if False else "direction", "delta_contribution_to_top15",
        })
        self.assertEqual(diagnostics["expected_date_count"], 24)

    def test_duplicate_development_date_row_rejected(self):
        frame = pd.DataFrame([
            {"signal_date": "2024-01-31", "symbol": "A",
             "fundamental_data_asof": "2024-01-01",
             "label_end_20": "2024-02-20",
             "label_end_60": "2024-05-01",
             "label_end_120": "2024-09-01",
             "fwd_ret_20": .01, "qqq_return_20": .02,
             "fwd_ret_60": .01, "qqq_return_60": .02,
             "fwd_ret_120": .01, "qqq_return_120": .02},
        ] * 2)
        with self.assertRaisesRegex(ValueError, "24 dates"):
            evaluate_development(
                frame, events=pd.DataFrame(), event_review=pd.DataFrame(),
                frozen_membership=pd.DataFrame(),
            )


if __name__ == "__main__":
    unittest.main()
