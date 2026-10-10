from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import ai_value_scanner.backtest as backtest
from ai_value_scanner.decision import EntryState
from ai_value_scanner.decision.entry import (
    ENTRY_POLICY_VERSION,
    build_entry_quality_v1,
)
from ai_value_scanner.evaluation.entry_quality import (
    apply_entry_quality_v1,
    build_entry_quality_evaluation_frame,
    build_entry_state_transitions,
    summarize_entry_state_cohorts,
    summarize_entry_state_concentration,
    summarize_entry_state_persistence,
    validate_entry_replay_frame,
)
from ai_value_scanner.features.price import compute_price_history_features


def _ready_entry_metrics() -> dict[str, object]:
    return {
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.03,
        "days_below_sma200": 0,
        "return_20d": 0.05,
        "return_60d": 0.10,
        "drawdown_from_52w_high": 0.08,
        "range_position_52w": 0.82,
        "relative_strength_60d_qqq": 0.04,
        "volatility_60d": 0.35,
        "regime": "up",
        "benchmark_trend_ok": True,
        "market_asof": "2026-10-09",
    }


def _strong_quality_metrics() -> dict[str, object]:
    return {
        "net_margin": 0.25,
        "free_cash_flow": 100.0,
        "ocf_to_net_income": 1.20,
        "accrual_ratio": 0.03,
        "revenue_yoy": 0.20,
        "adjusted_net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.20,
        "net_debt_to_ebitda": 0.0,
        "interest_coverage": 10.0,
        "current_ratio": 2.0,
        "shares_yoy": 0.0,
        "fcf_yield": 0.06,
        "ps_hist_percentile": 0.20,
        "pe_hist_percentile": 0.30,
        "receivables_growth_gap": 0.0,
        "inventory_growth_gap": 0.0,
        "shares_stale": False,
    }


def _weak_quality_metrics() -> dict[str, object]:
    return {
        "net_margin": -0.10,
        "free_cash_flow": -100.0,
        "ocf_to_net_income": 0.10,
        "accrual_ratio": 0.50,
        "revenue_yoy": -0.20,
        "adjusted_net_income_yoy": -0.30,
        "operating_cash_flow_yoy": -0.20,
        "net_debt_to_ebitda": 6.0,
        "interest_coverage": 0.5,
        "current_ratio": 0.5,
        "shares_yoy": 0.20,
        "fcf_yield": -0.05,
        "ps_hist_percentile": 0.95,
        "pe_hist_percentile": 0.95,
        "receivables_growth_gap": 0.40,
        "inventory_growth_gap": 0.45,
        "shares_stale": False,
    }


class TestEntryQualityV1(unittest.TestCase):
    def test_policy_is_frozen_and_healthy_setup_is_entry_ready(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(),
            decision_date="2026-10-10",
        )
        self.assertEqual(ENTRY_POLICY_VERSION, "entry_quality_v1_2026-10-10")
        self.assertIs(decision.state, EntryState.ENTRY_READY)
        self.assertGreater(float(decision.score or 0.0), 0.70)
        self.assertGreater(float(decision.confidence), 0.90)
        self.assertEqual(decision.market_asof, "2026-10-09")

    def test_high_recent_return_is_watch_pullback_not_entry_ready(self) -> None:
        metrics = _ready_entry_metrics()
        metrics["return_20d"] = 0.20
        decision = build_entry_quality_v1(
            metrics,
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_PULLBACK)
        self.assertTrue(
            any(item.code == "return_20d_overextended" for item in decision.risks)
        )

    def test_trend_damage_has_priority_over_overextension(self) -> None:
        metrics = _ready_entry_metrics()
        metrics["price_to_sma200"] = 0.93
        metrics["return_20d"] = 0.20
        decision = build_entry_quality_v1(
            metrics,
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.TREND_DAMAGED)

    def test_incomplete_confirmation_falls_back_to_watch_breakout(self) -> None:
        metrics = _ready_entry_metrics()
        metrics["price_to_sma50"] = 0.96
        metrics["return_20d"] = -0.01
        decision = build_entry_quality_v1(
            metrics,
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)

    def test_defensive_regime_requires_stronger_relative_confirmation(self) -> None:
        metrics = _ready_entry_metrics()
        metrics["regime"] = "down"
        metrics["benchmark_trend_ok"] = False
        decision = build_entry_quality_v1(
            metrics,
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)

        metrics["relative_strength_60d_qqq"] = 0.06
        decision_strong_rs = build_entry_quality_v1(
            metrics,
            decision_date="2026-10-10",
        )
        self.assertIs(decision_strong_rs.state, EntryState.ENTRY_READY)

    def test_missing_stale_and_future_market_data_are_explicit(self) -> None:
        missing = _ready_entry_metrics()
        missing["price_to_sma50"] = None
        missing_decision = build_entry_quality_v1(
            missing,
            decision_date="2026-10-10",
        )
        self.assertIs(missing_decision.state, EntryState.INSUFFICIENT_DATA)

        stale = _ready_entry_metrics()
        stale["market_asof"] = "2026-09-20"
        stale_decision = build_entry_quality_v1(
            stale,
            decision_date="2026-10-10",
        )
        self.assertIs(stale_decision.state, EntryState.INSUFFICIENT_DATA)
        self.assertTrue(
            any(
                item.code == "market_data_severely_stale"
                for item in stale_decision.risks
            )
        )

        future = _ready_entry_metrics()
        future["market_asof"] = "2026-10-11"
        with self.assertRaisesRegex(ValueError, "after decision_date"):
            build_entry_quality_v1(
                future,
                decision_date="2026-10-10",
            )

    def test_list_membership_does_not_change_entry_state(self) -> None:
        left = _ready_entry_metrics()
        left["list_type"] = "momentum"
        left["channel"] = "core_ai"
        right = _ready_entry_metrics()
        right["list_type"] = "low_value"
        right["channel"] = "ai_enabler"

        a = build_entry_quality_v1(left, decision_date="2026-10-10")
        b = build_entry_quality_v1(right, decision_date="2026-10-10")
        self.assertEqual(a.state, b.state)
        self.assertEqual(a.score, b.score)

    def test_replay_frame_rejects_future_market_data(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA"],
                "signal_date": ["2026-10-10"],
                "market_asof": ["2026-10-11"],
            }
        )
        with self.assertRaisesRegex(ValueError, "future market data"):
            validate_entry_replay_frame(frame)

    def test_company_quality_condition_keeps_only_a_b(self) -> None:
        strong = {
            **_strong_quality_metrics(),
            **_ready_entry_metrics(),
            "symbol": "AAA",
            "signal_date": "2026-10-10",
            "fundamental_data_asof": "2026-08-01",
            "fwd_ret_20": 0.10,
            "qqq_return_20": 0.03,
        }
        weak = {
            **_weak_quality_metrics(),
            **_ready_entry_metrics(),
            "symbol": "CCC",
            "signal_date": "2026-10-10",
            "fundamental_data_asof": "2026-08-01",
            "fwd_ret_20": -0.10,
            "qqq_return_20": 0.03,
        }
        evaluated = build_entry_quality_evaluation_frame(
            pd.DataFrame([strong, weak])
        )
        self.assertEqual(evaluated["symbol"].tolist(), ["AAA"])
        self.assertEqual(evaluated["quality_grade"].tolist(), ["A"])
        self.assertEqual(
            evaluated["entry_state"].tolist(),
            [EntryState.ENTRY_READY.value],
        )

    def test_apply_entry_decisions_preserves_canonical_state_fields(self) -> None:
        row = {
            **_ready_entry_metrics(),
            "symbol": "AAA",
            "signal_date": "2026-10-10",
        }
        out = apply_entry_quality_v1(pd.DataFrame([row]))
        self.assertEqual(out.iloc[0]["entry_state"], "ENTRY_READY")
        self.assertEqual(
            out.iloc[0]["entry_policy_version"],
            "entry_quality_v1_2026-10-10",
        )
        self.assertIn(
            "price_above_sma200",
            out.iloc[0]["entry_positive_codes"],
        )


class TestEntryQualityHistoricalEvaluation(unittest.TestCase):
    def test_state_cohorts_include_year_regime_quality_and_worst_date(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "signal_date": "2025-01-31",
                    "symbol": "AAA",
                    "quality_grade": "A",
                    "entry_state": "ENTRY_READY",
                    "regime": "up",
                    "fwd_ret_20": 0.20,
                    "qqq_return_20": 0.05,
                },
                {
                    "signal_date": "2025-01-31",
                    "symbol": "BBB",
                    "quality_grade": "B",
                    "entry_state": "ENTRY_READY",
                    "regime": "up",
                    "fwd_ret_20": 0.10,
                    "qqq_return_20": 0.05,
                },
                {
                    "signal_date": "2025-02-28",
                    "symbol": "AAA",
                    "quality_grade": "A",
                    "entry_state": "WATCH_PULLBACK",
                    "regime": "down",
                    "fwd_ret_20": -0.05,
                    "qqq_return_20": 0.01,
                },
                {
                    "signal_date": "2026-01-30",
                    "symbol": "CCC",
                    "quality_grade": "B",
                    "entry_state": "TREND_DAMAGED",
                    "regime": "down",
                    "fwd_ret_20": -0.15,
                    "qqq_return_20": -0.02,
                },
            ]
        )
        cohorts = summarize_entry_state_cohorts(frame, horizons=(20,))
        self.assertTrue(
            {"overall", "year", "regime", "quality_grade"}.issubset(
                set(cohorts["segment_type"])
            )
        )
        ready = cohorts[
            (cohorts["segment_type"] == "overall")
            & (cohorts["entry_state"] == "ENTRY_READY")
        ].iloc[0]
        self.assertAlmostEqual(float(ready["mean_return"]), 0.15, places=12)
        self.assertEqual(
            ready["worst_date_mean_return_date"],
            "2025-01-31",
        )

        concentration = summarize_entry_state_concentration(frame)
        ready_conc = concentration[
            concentration["entry_state"] == "ENTRY_READY"
        ].iloc[0]
        self.assertEqual(int(ready_conc["n_symbols"]), 2)

    def test_state_transitions_and_persistence_use_raw_adjacent_observations(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "signal_date": "2025-01-31",
                    "entry_state": "ENTRY_READY",
                },
                {
                    "symbol": "AAA",
                    "signal_date": "2025-02-28",
                    "entry_state": "ENTRY_READY",
                },
                {
                    "symbol": "AAA",
                    "signal_date": "2025-03-31",
                    "entry_state": "WATCH_PULLBACK",
                },
                {
                    "symbol": "BBB",
                    "signal_date": "2025-01-31",
                    "entry_state": "WATCH_BREAKOUT",
                },
                {
                    "symbol": "BBB",
                    "signal_date": "2025-03-31",
                    "entry_state": "WATCH_BREAKOUT",
                },
            ]
        )
        transitions = build_entry_state_transitions(frame)
        ready_ready = transitions[
            (transitions["from_state"] == "ENTRY_READY")
            & (transitions["to_state"] == "ENTRY_READY")
        ].iloc[0]
        self.assertEqual(int(ready_ready["n_transitions"]), 1)
        self.assertEqual(float(ready_ready["median_gap_days"]), 28.0)

        persistence = summarize_entry_state_persistence(frame)
        ready = persistence[
            persistence["from_state"] == "ENTRY_READY"
        ].iloc[0]
        self.assertEqual(int(ready["n_transitions"]), 2)
        self.assertAlmostEqual(float(ready["same_state_rate"]), 0.5, places=12)
        self.assertAlmostEqual(
            float(ready["median_gap_days"]),
            29.5,
            places=12,
        )


class TestEntryFeatureContract(unittest.TestCase):
    def test_sma50_requires_complete_window_and_is_shared(self) -> None:
        short = compute_price_history_features(
            current_price=100.0,
            range_highs=[101.0],
            range_lows=[99.0],
            closes=[100.0] * 49,
            dollar_volumes=[1_000_000.0] * 20,
        )
        self.assertIsNone(short["price_to_sma50"])

        full = compute_price_history_features(
            current_price=105.0,
            range_highs=[106.0],
            range_lows=[95.0],
            closes=[100.0] * 50,
            dollar_volumes=[1_000_000.0] * 20,
        )
        self.assertEqual(full["price_to_sma50"], 1.05)

    def test_replay_records_market_asof(self) -> None:
        idx = pd.date_range("2025-01-02", periods=260, freq="B", tz="UTC")
        closes = [100.0] * len(idx)
        frame = pd.DataFrame(
            {
                "open": closes,
                "high": [101.0] * len(idx),
                "low": [99.0] * len(idx),
                "close": closes,
                "volume": [1_000_000.0] * len(idx),
            },
            index=idx,
        )
        out = backtest.compute_price_features_asof(
            frame,
            asof=idx[-1] + pd.Timedelta(days=1),
            lookback_days=420,
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(
            out["market_asof"],
            idx[-1].date().isoformat(),
        )
        self.assertEqual(out["price_to_sma50"], 1.0)

    def test_extract_dataset_parser_preserves_default_and_adds_entry_mode(self) -> None:
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(scripts_dir))
        try:
            from extract_weight_dataset import build_parser
        finally:
            sys.path.pop(0)

        parser = build_parser()
        self.assertEqual(parser.parse_args([]).dataset_kind, "weight")
        self.assertEqual(
            parser.parse_args(
                ["--dataset-kind", "entry_quality"]
            ).dataset_kind,
            "entry_quality",
        )


if __name__ == "__main__":
    unittest.main()
