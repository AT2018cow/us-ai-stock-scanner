from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.features.ai_link import (
    ai_etf_consensus_score,
    ai_market_link_score,
    compute_ai_link_score,
)
from ai_value_scanner.features.valuation import (
    compute_historical_valuation_percentile,
    lookup_close_on_or_before,
    lookup_value_on_or_before,
    safe_divide,
)


class TestValuationFeatureCore(unittest.TestCase):
    def test_historical_valuation_percentile_golden(self) -> None:
        closes = [
            (pd.Timestamp("2025-01-10", tz="UTC"), 10.0),
            (pd.Timestamp("2025-02-10", tz="UTC"), 20.0),
            (pd.Timestamp("2025-03-10", tz="UTC"), 30.0),
        ]
        denominators = [
            (pd.Timestamp("2025-01-10", tz="UTC"), 100.0),
            (pd.Timestamp("2025-02-10", tz="UTC"), 100.0),
            (pd.Timestamp("2025-03-10", tz="UTC"), 100.0),
        ]
        shares = [
            (pd.Timestamp("2025-01-10", tz="UTC"), 10.0),
            (pd.Timestamp("2025-02-10", tz="UTC"), 10.0),
            (pd.Timestamp("2025-03-10", tz="UTC"), 10.0),
        ]
        pct, obs = compute_historical_valuation_percentile(
            current_multiple=2.0,
            closes=closes,
            denominator_history=denominators,
            shares_history=shares,
            current_shares=10.0,
            window_days=365,
        )
        self.assertEqual(obs, 3)
        self.assertEqual(pct, 0.666667)

    def test_historical_valuation_uses_current_shares_as_fallback(self) -> None:
        closes = [
            (pd.Timestamp("2025-01-10", tz="UTC"), 10.0),
            (pd.Timestamp("2025-02-10", tz="UTC"), 20.0),
            (pd.Timestamp("2025-03-10", tz="UTC"), 30.0),
        ]
        denominators = [(ts, 100.0) for ts, _ in closes]
        pct, obs = compute_historical_valuation_percentile(
            current_multiple=2.0,
            closes=closes,
            denominator_history=denominators,
            shares_history=[],
            current_shares=10.0,
            window_days=365,
        )
        self.assertEqual((pct, obs), (0.666667, 3))

    def test_lookup_close_gap_and_value_selection(self) -> None:
        points = [
            (pd.Timestamp("2025-01-01", tz="UTC"), 10.0),
            (pd.Timestamp("2025-02-01", tz="UTC"), 20.0),
        ]
        self.assertEqual(
            lookup_value_on_or_before(
                points,
                pd.Timestamp("2025-02-15", tz="UTC"),
            ),
            20.0,
        )
        self.assertEqual(
            lookup_close_on_or_before(
                points,
                pd.Timestamp("2025-02-10", tz="UTC"),
                max_gap_days=14,
            ),
            20.0,
        )
        self.assertIsNone(
            lookup_close_on_or_before(
                points,
                pd.Timestamp("2025-03-01", tz="UTC"),
                max_gap_days=14,
            )
        )

    def test_safe_divide_preserves_missing_and_zero_semantics(self) -> None:
        out = safe_divide(
            pd.Series([10.0, 10.0, np.nan]),
            pd.Series([2.0, 0.0, 5.0]),
        )
        self.assertEqual(float(out.iloc[0]), 5.0)
        self.assertTrue(np.isnan(out.iloc[1]))
        self.assertTrue(np.isnan(out.iloc[2]))


class TestAiLinkFeatureCore(unittest.TestCase):
    def test_component_golden_values(self) -> None:
        self.assertEqual(ai_etf_consensus_score(3, 4), 0.75)
        market = ai_market_link_score(
            symbol_return_20d=0.12,
            symbol_return_60d=0.18,
            benchmark_return_20d=0.10,
            benchmark_return_60d=0.20,
            tol_20d=0.25,
            tol_60d=0.40,
        )
        self.assertEqual(market, 0.938)

    def test_weighted_composition_preserves_non_renormalized_scale(self) -> None:
        cfg = scanner.ScanConfig()
        cfg.ai_link_weight_etf_consensus = 0.40
        cfg.ai_link_weight_disclosure = 0.0
        cfg.ai_link_weight_market_link = 0.15
        cfg.ai_link_weight_backlog = 0.10
        score = compute_ai_link_score(
            cfg,
            ai_etf_score=0.9,
            ai_disclosure_score=1.0,
            ai_market_score=0.8,
            ai_backlog_signal=0.5,
        )
        self.assertAlmostEqual(score, 0.53, places=12)

    def test_weighted_composition_clips_to_unit_interval(self) -> None:
        cfg = scanner.ScanConfig()
        cfg.ai_link_weight_etf_consensus = 1.0
        cfg.ai_link_weight_disclosure = 1.0
        cfg.ai_link_weight_market_link = 1.0
        cfg.ai_link_weight_backlog = 1.0
        self.assertEqual(
            compute_ai_link_score(cfg, 1.0, 1.0, 1.0, 1.0),
            1.0,
        )

    def test_scanner_and_replay_reexport_same_feature_functions(self) -> None:
        self.assertIs(scanner.compute_historical_valuation_percentile, compute_historical_valuation_percentile)
        self.assertIs(backtest.compute_historical_valuation_percentile, compute_historical_valuation_percentile)
        self.assertIs(scanner.ai_etf_consensus_score, ai_etf_consensus_score)
        self.assertIs(backtest.ai_etf_consensus_score, ai_etf_consensus_score)
        self.assertIs(scanner.ai_market_link_score, ai_market_link_score)
        self.assertIs(backtest.ai_market_link_score, ai_market_link_score)
        self.assertIs(backtest.compute_ai_link_score, compute_ai_link_score)


if __name__ == "__main__":
    unittest.main()
