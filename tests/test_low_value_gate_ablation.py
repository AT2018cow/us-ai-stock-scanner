from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import extract_weight_dataset as extractor  # noqa: E402
import low_value_gate_ablation as ablation  # noqa: E402


class TestLowValueGateAblation(unittest.TestCase):
    def test_research_survivor_expansion_allows_only_structural_steps(self) -> None:
        cfg = SimpleNamespace(strategy_style="risk_off")
        steps = [
            ("min_price", lambda frame: frame["x"] > 0),
            (
                "max_range_position_52w",
                lambda frame: frame["x"] <= 0.8,
            ),
        ]
        kept = extractor.research_skip_low_value_hard_steps(
            cfg,
            steps,
            ["max_range_position_52w"],
        )
        self.assertEqual([name for name, _ in kept], ["min_price"])

        with self.assertRaises(ValueError):
            extractor.research_skip_low_value_hard_steps(
                cfg,
                steps,
                ["min_price"],
            )

    def test_hard_to_soft_keeps_threshold_as_soft_condition(self) -> None:
        cfg = SimpleNamespace(
            strategy_style="risk_off",
            channel_profiles={"core_ai": {}},
        )
        steps = [
            ("min_price", lambda frame: frame["x"] > 0),
            (
                "max_range_position_52w",
                lambda frame: frame["x"] <= 0.8,
            ),
            ("min_quality", lambda frame: frame["q"] > 0),
        ]
        weights = {"x": 1.0}

        original = ablation.build_steps_and_weights
        try:
            ablation.build_steps_and_weights = (
                lambda *args, **kwargs: (steps, weights)
            )
            hard, soft, out_weights, active = (
                ablation.arm_filter_steps(
                    cfg,
                    "core_ai",
                    {},
                    "hard_to_soft",
                    {"max_range_position_52w"},
                )
            )
        finally:
            ablation.build_steps_and_weights = original

        self.assertEqual(
            [name for name, _ in hard],
            ["min_price"],
        )
        self.assertEqual(
            [name for name, _ in soft],
            ["min_quality", "max_range_position_52w"],
        )
        self.assertEqual(out_weights, weights)
        self.assertEqual(active, ["max_range_position_52w"])

    def test_baseline_parity_detects_exact_and_missing_symbols(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "signal_date": "2025-01-31",
                    "arm": "baseline",
                    "horizon_days": 20,
                    "channel_symbols_json": (
                        '{"core_ai":["A","B"],"ai_enabler":["C"]}'
                    ),
                }
            ]
        )
        replay = {
            ("2025-01-31", "core_ai"): {"A", "B"},
            ("2025-01-31", "ai_enabler"): {"C", "D"},
        }
        out = ablation.build_baseline_parity(
            events,
            replay,
            ["core_ai", "ai_enabler"],
        )
        core = out[out["channel"] == "core_ai"].iloc[0]
        enabler = out[out["channel"] == "ai_enabler"].iloc[0]
        self.assertTrue(bool(core["exact_match"]))
        self.assertFalse(bool(enabler["exact_match"]))
        self.assertEqual(enabler["expected_only"], "D")

    def test_retrospective_gate_requires_all_full_years_and_down_regime(self) -> None:
        parity = pd.DataFrame({"exact_match": [True, True]})
        rows = [
            {
                "scope": "all",
                "scope_value": "ALL",
                "horizon_days": 120,
                "n_dates": 34,
                "avg_delta_return": 0.03,
                "positive_delta_ratio": 0.60,
                "top_abs_date_share": 0.20,
                "median_selection_jaccard": 0.70,
            },
            {
                "scope": "regime",
                "scope_value": "down",
                "horizon_days": 120,
                "n_dates": 7,
                "avg_delta_return": 0.01,
                "positive_delta_ratio": 0.57,
                "top_abs_date_share": 0.30,
                "median_selection_jaccard": 0.70,
            },
        ]
        for year in ("2023", "2024", "2025"):
            rows.append(
                {
                    "scope": "year",
                    "scope_value": year,
                    "horizon_days": 120,
                    "n_dates": 10,
                    "avg_delta_return": 0.02,
                    "positive_delta_ratio": 0.60,
                    "top_abs_date_share": 0.25,
                    "median_selection_jaccard": 0.70,
                }
            )
        summary = pd.DataFrame(rows)
        passed, failures = ablation.retrospective_gate(
            parity,
            summary,
        )
        self.assertTrue(passed)
        self.assertEqual(failures, [])

        summary.loc[
            (summary["scope"] == "year")
            & (summary["scope_value"] == "2024"),
            "avg_delta_return",
        ] = -0.01
        passed, failures = ablation.retrospective_gate(
            parity,
            summary,
        )
        self.assertFalse(passed)
        self.assertIn(
            "2024_120d_delta_not_positive",
            failures,
        )

    def test_returns_by_symbol_rejects_channel_disagreement(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "A"],
                "fwd_ret_120": [0.10, 0.11],
            }
        )
        with self.assertRaises(ValueError):
            ablation.returns_by_symbol(frame, 120)

        frame["fwd_ret_120"] = [0.10, 0.10]
        out = ablation.returns_by_symbol(frame, 120)
        self.assertAlmostEqual(out["A"], 0.10)


if __name__ == "__main__":
    unittest.main()
