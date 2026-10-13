from __future__ import annotations

import unittest

import pandas as pd

from scripts.mvp_v11_data_risk_audit import prepare_review_queue


def _audit_inputs():
    dates = ["2024-01-31", "2024-02-29"]
    data = pd.DataFrame([
        {"signal_date": d, "symbol": sym,
         "fundamental_data_asof": "2024-01-10" if sym == "HXL" else None}
        for d in dates for sym in ("HXL", "WOLF")
    ])
    events = pd.DataFrame([
        {
            "symbol": "HXL", "date": "2024-02-29", "prev_date": "2024-01-31",
            "reason": "SHARE_JUMP_UNEXPLAINED", "null_labels": False,
            "nulled_h20": 0, "nulled_h60": 0, "nulled_h120": 0,
            "ratio": 1000000, "price_ratio": 1.1,
        },
        {
            "symbol": "WOLF", "date": "2024-02-29", "prev_date": "2024-01-31",
            "reason": "REORG_JUMP_BACKDATED", "null_labels": True,
            "nulled_h20": 0, "nulled_h60": 2, "nulled_h120": 5,
            "ratio": 1.0, "price_ratio": 23,
        },
    ])
    for i in range(50):
        events.loc[len(events)] = [
            f"SYM{i}", "2024-02-29", "2024-01-31",
            "SHARE_JUMP_UNEXPLAINED", False, 0, 0, 0, 2.0, 1.1,
        ]
    ranks = pd.DataFrame([
        {"signal_date": "2024-01-31", "v1_top5": "AAA;HXL",
         "v1_top15": "AAA;HXL;BBB"},
        {"signal_date": "2024-02-29", "v1_top5": "HXL;CCC",
         "v1_top15": "HXL;CCC;DDD"},
    ])
    return data, events, ranks


class TestMVPV11DataRiskAudit(unittest.TestCase):
    def test_audit_queue_is_review_only_and_prioritizes_exposed_events(self):
        data, events, ranks = _audit_inputs()
        summary, queue = prepare_review_queue(data, events, ranks)
        self.assertEqual(summary["verdict"], "DATA_RISK_REVIEW_REQUIRED")
        self.assertFalse(summary["ready_for_candidate_returns"])
        self.assertEqual(len(queue), 52)
        self.assertEqual(summary["n_51_audit_only"], 51)
        self.assertEqual(summary["n_label_nulling_events"], 1)
        hxl = queue[queue.symbol == "HXL"].iloc[0]
        self.assertTrue(hxl.severe_shares_change)
        self.assertTrue(hxl.top5_at_event)
        self.assertTrue(hxl.top15_at_previous_date)
        self.assertEqual(hxl.human_disposition, "UNREVIEWED")
        self.assertEqual(summary["n_missing_fundamental_asof"], 2)
        self.assertNotIn("fwd_ret_20", queue.columns)

    def test_events_count_or_nulling_identity_change_are_blocking(self):
        data, events, ranks = _audit_inputs()
        with self.assertRaisesRegex(ValueError, "52 original"):
            prepare_review_queue(data, events.head(51), ranks)
        events.loc[1, "symbol"] = "HXL"
        with self.assertRaisesRegex(ValueError, "WOLF nulling"):
            prepare_review_queue(data, events, ranks)

    def test_duplicate_rank_dates_are_blocking(self):
        data, events, ranks = _audit_inputs()
        ranks = pd.concat([ranks, ranks.head(1)], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate dates"):
            prepare_review_queue(data, events, ranks)


if __name__ == "__main__":
    unittest.main()
