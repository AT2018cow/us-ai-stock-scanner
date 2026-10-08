from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sweep_score_weights as sweep  # noqa: E402

from ai_value_scanner.config import ScanConfig  # noqa: E402
from ai_value_scanner.strategy.selection import apply_group_caps  # noqa: E402


class TestOfflineWeightSweepParity(unittest.TestCase):
    def setUp(self) -> None:
        sweep.winsor_lower_q = 0.02
        sweep.winsor_upper_q = 0.98
        sweep.penalty_over = 0.0
        sweep.penalty_det = 0.0

    def test_cap_selector_matches_production_group_caps(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D"],
                "sic": ["1010", "1090", "2010", "2090"],
                "watchlist_etfs": ["AIQ", "AIQ", "SMH", "SMH"],
                "composite_score": [0.9, 0.8, 0.7, 0.6],
            }
        )
        production = apply_group_caps(
            frame,
            max_per_sector=1,
            max_per_watchlist_etf_source=1,
        ).head(10)

        picked = sweep._select_ranked_indices_with_caps(
            scores=frame["composite_score"].to_numpy(dtype="float64"),
            gate_allowed=np.ones(len(frame), dtype=bool),
            sic=frame["sic"].tolist(),
            watchlist_etfs=frame["watchlist_etfs"].tolist(),
            top_n=10,
            max_per_sector=1,
            max_per_watchlist_etf_source=1,
        )
        offline = frame.iloc[picked]
        self.assertEqual(
            offline["symbol"].tolist(),
            production["symbol"].tolist(),
        )

    def test_research_gate_runs_before_caps_and_top_n(self) -> None:
        dataset = pd.DataFrame(
            {
                "signal_date": ["2025-01-31", "2025-01-31"],
                "list_type": ["low_value", "low_value"],
                "channel": ["core_ai", "core_ai"],
                "symbol": ["DROP", "KEEP"],
                "sic": ["1010", "1090"],
                "watchlist_etfs": ["AIQ", "AIQ"],
                "watchlist_etf_count": [1, 1],
                "x": [0.9, 0.8],
                "fwd_ret_20": [0.9, 0.1],
            }
        )
        base_weights = {
            "low_value": {
                "core_ai": {
                    "x": 1.0,
                    "soft_pass_rate": 0.0,
                }
            }
        }
        cfg = ScanConfig()
        cfg.channel_profiles = {"core_ai": {}}
        cfg.low_value_allowed_research_priorities = ["research_now"]
        cfg.low_value_excluded_research_risks = []
        cfg.low_value_min_research_score = 0.0

        def fake_score(frame: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
            out = frame.copy()
            out["x_norm"] = pd.to_numeric(out["x"], errors="coerce")
            out["soft_pass_rate"] = 0.0
            out["overvaluation_penalty"] = 0.0
            out["deterioration_penalty"] = 0.0
            out["composite_score"] = out["x_norm"]
            return out.sort_values("composite_score", ascending=False)

        def fake_assessment(frame: pd.DataFrame, list_type: str) -> pd.DataFrame:
            out = frame.copy()
            out["research_priority"] = [
                "research_now" if symbol == "KEEP" else "theme_only"
                for symbol in out["symbol"]
            ]
            out["research_score"] = 3.0
            out["research_risks"] = ""
            out["research_tags"] = ""
            out["research_summary"] = ""
            return out

        with (
            mock.patch(
                "ai_value_scanner.scanner.score_and_rank",
                side_effect=fake_score,
            ),
            mock.patch.object(
                sweep,
                "apply_research_assessment",
                side_effect=fake_assessment,
            ),
        ):
            groups = sweep.precompute_groups(
                dataset,
                base_weights,
                [20],
                scan_config=cfg,
                channel_order=["core_ai"],
            )

        event = sweep.score_candidate(
            groups,
            {"low_value": {"x": 1.0}},
            {"low_value": 0.0},
            [20],
            1,
            max_per_sector=1,
            max_per_watchlist_etf_source=1,
            channel_order=["core_ai"],
        ).iloc[0]
        self.assertEqual(int(event["n_picked"]), 1)
        self.assertAlmostEqual(float(event["mean_ret"]), 0.1)

    def test_channel_order_controls_cross_channel_dedup_source(self) -> None:
        def group(ret: float) -> dict:
            return {
                "axes": ["x"],
                "norm": np.asarray([[1.0]], dtype="float64"),
                "soft_rate": np.asarray([0.0], dtype="float64"),
                "ovp": np.asarray([0.0], dtype="float64"),
                "det": np.asarray([0.0], dtype="float64"),
                "fwd": np.asarray([[ret]], dtype="float64"),
                "symbols": ["AAA"],
                "sic": [""],
                "watchlist_etfs": [""],
                "watchlist_etf_count": np.asarray([0.0], dtype="float64"),
                "gate_allowed": np.asarray([True], dtype=bool),
            }

        # Intentionally insert ai_enabler first. Production config order is
        # supplied separately and must win over dict/group insertion order.
        groups = {
            ("2025-01-31", "momentum", "ai_enabler"): group(0.9),
            ("2025-01-31", "momentum", "core_ai"): group(0.1),
        }
        event = sweep.score_candidate(
            groups,
            {"momentum": {"x": 1.0}},
            {"momentum": 0.0},
            [20],
            1,
            channel_order=["core_ai", "ai_enabler"],
        ).iloc[0]
        self.assertEqual(int(event["n_picked"]), 1)
        self.assertAlmostEqual(float(event["mean_ret"]), 0.1)


if __name__ == "__main__":
    unittest.main()
