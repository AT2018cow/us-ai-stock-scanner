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
            ("2025-01-31", "core_ai"): ["A", "B"],
            ("2025-01-31", "ai_enabler"): ["C", "D"],
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

    def test_baseline_parity_requires_symbol_order(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "signal_date": "2025-01-31",
                    "arm": "baseline",
                    "horizon_days": 20,
                    "channel_symbols_json": '{"core_ai":["B","A"]}',
                }
            ]
        )
        replay = {
            ("2025-01-31", "core_ai"): ["A", "B"],
        }
        out = ablation.build_baseline_parity(
            events,
            replay,
            ["core_ai"],
        )
        row = out.iloc[0]
        self.assertFalse(bool(row["exact_match"]))
        self.assertFalse(bool(row["order_match"]))
        self.assertAlmostEqual(float(row["jaccard"]), 1.0)

    def test_baseline_parity_detects_replay_date_missing_from_dataset(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "signal_date": "2025-01-31",
                    "arm": "baseline",
                    "horizon_days": 20,
                    "channel_symbols_json": '{"core_ai":["A"]}',
                }
            ]
        )
        replay = {
            ("2025-01-31", "core_ai"): ["A"],
            ("2025-02-28", "core_ai"): ["B"],
        }
        out = ablation.build_baseline_parity(
            events,
            replay,
            ["core_ai"],
        )
        missing = out[
            out["signal_date"].astype(str) == "2025-02-28"
        ].iloc[0]
        self.assertFalse(bool(missing["exact_match"]))
        self.assertEqual(missing["actual_n"], 0)
        self.assertEqual(missing["expected_only"], "B")

    def test_retrospective_gate_rejects_single_symbol_concentration(self) -> None:
        parity = pd.DataFrame({"exact_match": [True]})
        rows = [
            {
                "scope": "all",
                "scope_value": "ALL",
                "horizon_days": 120,
                "n_dates": 30,
                "avg_delta_return": 0.03,
                "positive_delta_ratio": 0.60,
                "top_abs_date_share": 0.20,
                "median_selection_jaccard": 0.70,
            },
            {
                "scope": "regime",
                "scope_value": "down",
                "horizon_days": 120,
                "n_dates": 8,
                "avg_delta_return": 0.01,
                "positive_delta_ratio": 0.50,
                "top_abs_date_share": 0.20,
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
                    "top_abs_date_share": 0.20,
                    "median_selection_jaccard": 0.70,
                }
            )
        symbols = pd.DataFrame(
            [
                {
                    "horizon_days": 120,
                    "side": "added",
                    "symbol": "A",
                    "positive_excess_share": 0.40,
                },
                {
                    "horizon_days": 120,
                    "side": "added",
                    "symbol": "B",
                    "positive_excess_share": 0.20,
                },
            ]
        )
        passed, failures = ablation.retrospective_gate(
            parity,
            pd.DataFrame(rows),
            symbols,
        )
        self.assertFalse(passed)
        self.assertIn(
            "added_120d_positive_excess_too_concentrated_by_symbol",
            failures,
        )

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

    def test_rank_channel_ignores_dataset_channel_column(self) -> None:
        """Research assessment must match production (no channel column).

        Production cross-sections carry no channel column at assessment
        time, so a dataset row labelled ai_enabler must not self-award
        ai_infrastructure_exposure. rank_channel output must be identical
        whether or not the input frame carries a channel column.
        """
        cfg = SimpleNamespace(
            strategy_style="risk_off",
            channel_profiles={"ai_enabler": {}},
            score_winsor_lower_q=0.05,
            score_winsor_upper_q=0.95,
            score_penalty_overvaluation=0.2,
            score_penalty_deterioration=0.2,
            pe_cash_backing_haircut=1.0,
            low_value_allowed_research_priorities=[
                "research_now",
                "watch_for_pullback",
            ],
            low_value_excluded_research_risks=[],
            low_value_min_research_score=0.0,
            max_per_sector_per_list=None,
            max_per_watchlist_etf_source_per_list=None,
        )
        steps = [("always_true", lambda frame: pd.Series(True, index=frame.index))]
        weights = {"x": 1.0}
        base_row = {
            "symbol": "TER",
            "x": 1.0,
            "watchlist_bucket": "core_ai",
            "watchlist_etfs": "ARKQ,SMH",
            "fundamental_quality_score": 0.99,
            "ai_link_score": 0.64,
            "pe": 34.5,
            "ps": 5.9,
            "revenue_yoy": -0.15,
            "net_income_yoy": -0.37,
            "return_20d": 0.07,
            "return_60d": 0.10,
            "price_to_sma200": 1.02,
            "drawdown_from_52w_high": 0.13,
            "fcf_yield": 0.027,
            "ev_to_ebit": 30.2,
            "net_margin": 0.17,
            "ps_hist_percentile": 1.0,
            "pe_hist_percentile": 0.875,
            "ps_discount": -0.40,
            "pe_discount": -0.36,
            "ps_percentile_in_sic": 1.0,
            "pe_percentile_in_sic": 0.71,
        }
        with_channel = pd.DataFrame(
            [{**base_row, "channel": "ai_enabler"}]
        )
        without_channel = pd.DataFrame(
            [{k: v for k, v in base_row.items()}]
        )

        original = ablation.build_steps_and_weights
        try:
            ablation.build_steps_and_weights = (
                lambda *args, **kwargs: (steps, weights)
            )
            ranked_with, _ = ablation.rank_channel(
                with_channel,
                cfg,
                "ai_enabler",
                "baseline",
                set(),
            )
            ranked_without, _ = ablation.rank_channel(
                without_channel,
                cfg,
                "ai_enabler",
                "baseline",
                set(),
            )
        finally:
            ablation.build_steps_and_weights = original

        self.assertEqual(
            ranked_with["symbol"].astype(str).tolist(),
            ranked_without["symbol"].astype(str).tolist(),
        )
        self.assertEqual(len(ranked_with), len(ranked_without))
        for col in (
            "research_score",
            "research_priority",
            "research_tags",
            "research_risks",
        ):
            self.assertIn(col, ranked_with.columns)
            self.assertIn(col, ranked_without.columns)
            self.assertEqual(
                ranked_with[col].astype(str).tolist(),
                ranked_without[col].astype(str).tolist(),
                f"research column {col} must not depend on the dataset channel label",
            )


if __name__ == "__main__":
    unittest.main()
