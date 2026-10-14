"""Preflight only: no historical return comparison and no external API calls."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from scripts.mvp_v11_candidate_preflight import run_preflight, verify_registry, IDS


def synthetic():
    rows = [{
        "signal_date": "2024-01-31",
        "symbol": f"SYM{i:02d}",
        "market_asof": "2024-01-31",
        "fundamental_data_asof": "2024-01-20",
        "price_to_sma200": 1.04,
        "price_to_sma50": 1.02,
        "return_20d": .05,
        "return_60d": .1,
        "relative_strength_60d_qqq": .02 if i % 2 else -.01,
        "drawdown_from_52w_high": .11,
        "range_position_52w": .6,
        "regime": "up",
        "fwd_ret_60": 1e12 - i,
        "qqq_return_60": -1e12 + i,
    } for i in range(16)]
    events = pd.DataFrame(columns=[
        "symbol", "event_date", "severe_shares_change", "null_labels",
    ])
    return pd.DataFrame(rows), events


class TestCandidatePreflight(unittest.TestCase):
    def test_frozen_registry_matches_all_offline_candidates(self):
        repo_root = Path(__file__).resolve().parents[1]
        sha = verify_registry(repo_root / "configs/mvp_v11_candidate_registry.json")
        self.assertEqual(len(sha), 64)
        self.assertEqual(len(IDS), 10)

    def test_no_returns_in_membership_or_score_sidecars(self):
        df, events = synthetic()
        members, transitions, masks = run_preflight(df, events=events)
        self.assertEqual(len(members), 10)
        self.assertEqual(set(members.candidate_id), set(IDS))
        self.assertTrue(members.loc[members.candidate_id == "B0",
                                     "n_action_changed"].eq(0).all())
        self.assertTrue(members.n_top15_swaps.le(15).all())
        self.assertNotIn("fwd_ret_60", masks.columns)
        self.assertFalse(any("return" in name for name in members.columns))
        self.assertTrue(set(transitions.columns) >=
                        {"signal_date", "candidate_id", "n_rows"})
        df.fwd_ret_60 = -12345678
        df.qqq_return_60 = 12345678
        again, migrated, flags = run_preflight(df, events=events)
        pd.testing.assert_frame_equal(members, again)
        pd.testing.assert_frame_equal(transitions, migrated)
        pd.testing.assert_frame_equal(masks, flags)

    def test_2025_temporal_candidate_comparison_is_embargoed(self):
        dev, events = synthetic()
        future = dev.copy()
        future["signal_date"] = "2025-01-31"
        future["market_asof"] = "2025-01-31"
        future["fundamental_data_asof"] = "2025-01-20"
        combined = pd.concat([dev, future], ignore_index=True)
        memberships, _, sidecar = run_preflight(combined, events=events)
        self.assertEqual(len(memberships), 10)
        self.assertEqual(set(memberships.signal_date), {"2024-01-31"})
        self.assertEqual(len(sidecar), 32)


if __name__ == "__main__":
    unittest.main()
