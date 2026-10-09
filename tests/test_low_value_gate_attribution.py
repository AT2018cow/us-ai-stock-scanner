from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import low_value_gate_attribution as attribution  # noqa: E402


class TestLowValueGateAttributionParity(unittest.TestCase):
    def test_research_assessment_does_not_see_dataset_channel(self) -> None:
        dataset = pd.DataFrame(
            [
                {
                    "signal_date": "2025-01-31",
                    "list_type": "low_value",
                    "channel": "ai_enabler",
                    "symbol": "TER",
                    "x": 1.0,
                }
            ]
        )
        cfg = SimpleNamespace(
            strategy_style="risk_off",
            channel_profiles={"ai_enabler": {}},
            score_winsor_lower_q=0.05,
            score_winsor_upper_q=0.95,
            score_penalty_overvaluation=0.2,
            score_penalty_deterioration=0.2,
            pe_cash_backing_haircut=1.0,
            max_per_sector_per_list=None,
            max_per_watchlist_etf_source_per_list=None,
        )

        def fake_score(frame: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
            out = frame.copy()
            out["composite_score"] = 1.0
            return out

        def fake_assessment(
            frame: pd.DataFrame,
            list_type: str,
        ) -> pd.DataFrame:
            self.assertEqual(list_type, "low_value")
            self.assertNotIn(
                "channel",
                frame.columns,
                "dataset channel must not leak into production-parity assessment",
            )
            out = frame.copy()
            out["research_priority"] = "research_now"
            out["research_score"] = 2.0
            out["research_risks"] = ""
            out["research_tags"] = ""
            out["research_summary"] = ""
            return out

        with (
            mock.patch.object(
                attribution,
                "build_steps_and_weights",
                return_value=([], {"x": 1.0}),
            ),
            mock.patch.object(
                attribution,
                "score_and_rank",
                side_effect=fake_score,
            ),
            mock.patch.object(
                attribution,
                "apply_research_assessment",
                side_effect=fake_assessment,
            ),
            mock.patch.object(
                attribution,
                "apply_low_value_research_gate",
                side_effect=lambda frame, config: frame,
            ),
        ):
            states = attribution.build_risk_off_group_states(
                dataset,
                cfg,
                ["ai_enabler"],
                top_n=10,
            )

        state = states[("2025-01-31", "ai_enabler")]
        self.assertNotIn("channel", state["assessed"].columns)
        self.assertEqual(
            state["assessed"]["research_priority"].tolist(),
            ["research_now"],
        )


if __name__ == "__main__":
    unittest.main()
