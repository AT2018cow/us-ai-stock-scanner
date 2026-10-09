from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ic_analysis as ic  # noqa: E402
import low_value_gate_attribution as lv  # noqa: E402


class TestAlphaAttribution(unittest.TestCase):
    def test_ic_detects_monotone_cross_section_and_all_channel_average(self) -> None:
        rows = []
        for channel in ("core_ai", "ai_enabler"):
            for idx in range(20):
                rows.append(
                    {
                        "signal_date": "2025-01-31",
                        "year": "2025",
                        "regime": "up",
                        "list_type": "low_value",
                        "channel": channel,
                        "symbol": f"{channel}_{idx}",
                        "composite_score": float(idx),
                        "fwd_ret_20": float(idx) / 100.0,
                    }
                )
        scored = pd.DataFrame(rows)
        out = ic.build_ic_by_date(
            scored,
            horizons=[20],
            min_cross_section=20,
        )
        self.assertEqual(len(out), 3)
        self.assertTrue(np.allclose(out["ic"].to_numpy(dtype=float), 1.0))
        all_row = out[out["channel"] == "ALL"].iloc[0]
        self.assertAlmostEqual(float(all_row["ic"]), 1.0)

    def test_decile_monotonicity_detects_ordered_score_spread(self) -> None:
        rows = []
        for idx in range(100):
            rows.append(
                {
                    "signal_date": "2025-01-31",
                    "year": "2025",
                    "regime": "up",
                    "list_type": "low_value",
                    "channel": "core_ai",
                    "symbol": f"S{idx:03d}",
                    "composite_score": float(idx),
                    "fwd_ret_120": float(idx) / 100.0,
                    "qqq_return_120": 0.10,
                }
            )
        scored = pd.DataFrame(rows)
        by_date = ic.build_decile_by_date(
            scored,
            horizons=[120],
            min_cross_section=20,
            deciles=10,
        )
        summary = ic.summarize_deciles(by_date)
        mono = ic.build_monotonicity(summary)
        row = mono[
            (mono["scope"] == "all")
            & (mono["channel"] == "core_ai")
        ].iloc[0]
        self.assertAlmostEqual(float(row["adjacent_up_ratio"]), 1.0)
        self.assertGreater(float(row["top_minus_bottom_excess"]), 0.0)
        self.assertAlmostEqual(float(row["decile_spearman_excess"]), 1.0)

    def test_score_survivors_uses_channel_production_weights(self) -> None:
        dataset = pd.DataFrame(
            {
                "signal_date": ["2025-01-31", "2025-01-31"],
                "list_type": ["low_value", "low_value"],
                "channel": ["core_ai", "core_ai"],
                "symbol": ["A", "B"],
                "regime": ["up", "up"],
                "soft_pass_count": [0, 0],
                "soft_total": [1, 1],
                "ps_discount": [1.0, 0.0],
                "pe_discount": [0.0, 1.0],
                "fwd_ret_20": [0.1, 0.2],
                "qqq_return_20": [0.0, 0.0],
            }
        )
        cfg = SimpleNamespace(
            channel_profiles={"core_ai": {}},
            score_winsor_lower_q=0.0,
            score_winsor_upper_q=1.0,
            score_penalty_overvaluation=0.0,
            score_penalty_deterioration=0.0,
            pe_cash_backing_haircut=0.0,
        )
        with mock.patch.object(
            ic,
            "build_steps_and_weights",
            return_value=(
                [],
                {
                    "ps_discount": 0.9,
                    "pe_discount": 0.1,
                    "soft_pass_rate": 0.0,
                },
            ),
        ):
            scored = ic.score_survivors(
                dataset,
                cfg,
                list_types=["low_value"],
                channels=["core_ai"],
                horizons=[20],
            )
        scores = scored.set_index("symbol")["composite_score"]
        self.assertGreater(float(scores["A"]), float(scores["B"]))

    def test_low_value_diagnosis_reports_hard_first_fail(self) -> None:
        source = pd.Series({"symbol": "A", "x": 0.5})
        state = {
            "hard_steps": [("min_x", lambda frame: frame["x"] >= 1.0)],
            "soft_steps": [],
            "ranked": pd.DataFrame(),
            "research_kept": pd.DataFrame(),
            "capped": pd.DataFrame(),
            "top_n": 10,
        }
        out = lv.diagnose_exclusion(
            source_row=source,
            signal_date="2025-01-31",
            channel="core_ai",
            symbol="A",
            state=state,
        )
        self.assertEqual(out["exclusion_stage"], "hard_filter")
        self.assertEqual(out["hard_first_fail"], "min_x")

    def test_low_value_diagnosis_distinguishes_research_gate_and_top_n(self) -> None:
        source = pd.Series({"symbol": "A", "x": 1.0})
        ranked = pd.DataFrame(
            {
                "symbol": ["A"],
                "composite_score": [0.5],
                "_rank_pre_research": [3],
                "research_priority": ["theme_only"],
                "research_score": [1.0],
                "research_risks": [""],
            }
        )
        research_removed = {
            "hard_steps": [],
            "soft_steps": [("soft_x", lambda frame: frame["x"] >= 2.0)],
            "ranked": ranked,
            "research_kept": ranked.iloc[0:0].copy(),
            "capped": ranked.iloc[0:0].copy(),
            "top_n": 10,
        }
        out = lv.diagnose_exclusion(
            source_row=source,
            signal_date="2025-01-31",
            channel="core_ai",
            symbol="A",
            state=research_removed,
        )
        self.assertEqual(out["exclusion_stage"], "research_gate")
        self.assertEqual(out["soft_failed_steps"], "soft_x")

        kept = ranked.copy()
        kept["_rank_post_research"] = [3]
        capped = kept.copy()
        capped["_rank_after_caps"] = [11]
        below_top_n = {
            "hard_steps": [],
            "soft_steps": [],
            "ranked": ranked,
            "research_kept": kept,
            "capped": capped,
            "top_n": 10,
        }
        out = lv.diagnose_exclusion(
            source_row=source,
            signal_date="2025-01-31",
            channel="core_ai",
            symbol="A",
            state=below_top_n,
        )
        self.assertEqual(out["exclusion_stage"], "below_top_n")
        self.assertEqual(int(out["risk_off_rank_after_caps"]), 11)


if __name__ == "__main__":
    unittest.main()
