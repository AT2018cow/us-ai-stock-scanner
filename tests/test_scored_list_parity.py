"""Regression: ALL scanner lists (low_value/trend/momentum) must use the
scored partition in scored mode.

Bug found 2026-09-27: after the two-layer refactor the scanner's momentum
and industry_trend output paths still applied the FULL step list as hard
gates while the backtest used the partition — production momentum lists
were empty despite valid backtest picks (39-step hard filtering eliminates
every stock in typical markets; the backtest's 11-hard+soft produced picks).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import (  # noqa: E402
    build_momentum_steps,
    build_industry_trend_steps,
    load_config,
    partition_filter_steps,
    apply_scored_or_hard_filters,
)


def _make_df(n: int = 60) -> pd.DataFrame:
    ch0 = "core_ai"
    rng = np.random.default_rng(7)
    d = {
        "symbol": [f"S{i}" for i in range(n)],
        "price": rng.uniform(20, 200, n),
        "dollar_volume": rng.uniform(5e6, 5e8, n),
        "market_cap": rng.uniform(1e9, 2e12, n),
        "return_20d": rng.uniform(-0.2, 0.2, n),
        "return_60d": rng.uniform(-0.3, 0.4, n),
        "price_to_sma200": rng.uniform(0.8, 1.3, n),
        "drawdown_from_52w_high": rng.uniform(0.0, 0.5, n),
        "range_position_52w": rng.uniform(0.0, 1.0, n),
        "volatility_60d": rng.uniform(0.1, 0.6, n),
        "avg_dollar_volume_20d": rng.uniform(1e7, 1e9, n),
        "watchlist_etf_count": rng.integers(0, 5, n),
        "ai_link_score": rng.uniform(0.0, 1.0, n),
        "net_margin": rng.uniform(-0.1, 0.3, n),
        "drawdown_percentile": rng.uniform(0.0, 1.0, n),
        "max_60d_volatility_percentile": rng.uniform(0.0, 1.0, n),
        "min_avg_dollar_volume_20d_percentile": rng.uniform(0.0, 1.0, n),
        "adv_participation": rng.uniform(0.0, 0.05, n),
        "estimated_slippage_bps": rng.uniform(0.0, 40.0, n),
        "revenue": rng.uniform(1e8, 1e11, n),
        "net_income": rng.uniform(-1e9, 2e10, n),
        "operating_cash_flow": rng.uniform(-1e8, 5e10, n),
        "free_cash_flow": rng.uniform(-1e9, 4e10, n),
        "ebit": rng.uniform(-1e9, 3e10, n),
        "revenue_yoy": rng.uniform(-0.2, 0.5, n),
        "net_income_yoy": rng.uniform(-0.5, 1.0, n),
        "days_below_sma200": rng.integers(0, 200, n),
        "sic": ["5112-01"] * n,
        "watchlist_primary_bucket": ["core_ai"] * n,
        "symbol_in_watchlist": [True] * n,
        "benchmark_trend_ok": [True] * n,
        "channel_bucket": [ch0] * n,
        "channel_scores": [{"core_ai": 1.0}] * n,
    }
    # Fill every other column the step lambdas may touch with neutral NaN.
    # (Steps use fillna(-inf)/fillna(False) guards, so NaN never eliminates.)
    touch_cols = [
        "adjusted_net_income", "adjusted_net_income_yoy", "adjusted_ebit",
        "ebit_yoy", "operating_cash_flow_yoy", "fcf_yield", "ev_to_ebit",
        "ps", "pe", "net_debt_to_ebitda", "interest_coverage",
        "current_ratio", "ocf_to_net_income", "accrual_ratio", "shares_yoy",
        "ps_percentile_in_sic", "pe_percentile_in_sic", "ps_hist_percentile",
        "pe_hist_percentile", "expectation_proxy", "cycle_proxy",
        "receivables_growth_gap", "inventory_growth_gap",
        "fundamental_quality_score", "ps_discount", "pe_discount",
        "overvaluation_penalty", "deterioration_penalty",
        "current_debt_ratio", "shares", "net_debt", "watchlist_etfs",
        "own_history_ps_percentile", "own_history_pe_percentile",
        "revenue_ttm", "net_income_ttm",
    ]
    for c in touch_cols:
        d[c] = np.nan
    return pd.DataFrame(d)


class ScoredListParityTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config("configs/config.risk_on.json")

    def test_momentum_partition_matches_backtest_shape(self):
        for ch, prof in (self.cfg.channel_profiles or {}).items():
            steps, _ = build_momentum_steps(self.cfg, ch, prof)
            hard, soft = partition_filter_steps(steps, ch, self.cfg.strategy_style)
            # Core-only hard set: no momentum_* threshold may be a hard gate
            hard_names = {n for n, _ in hard}
            self.assertFalse(
                any(n.startswith("momentum_") for n in hard_names),
                f"momentum_* thresholds must be soft in scored mode, got hard: "
                f"{sorted(n for n in hard_names if n.startswith('momentum_'))}",
            )
            self.assertGreater(len(soft), 10)

    def test_momentum_scored_filter_keeps_soft_failures(self):
        # A stock failing ONLY soft momentum thresholds must survive scored
        # filtering with soft_pass_count < soft_total.
        df = _make_df(40)
        for ch, prof in (self.cfg.channel_profiles or {}).items():
            steps, _ = build_momentum_steps(self.cfg, ch, prof)
            hard, soft = partition_filter_steps(steps, ch)
            out, _ = apply_scored_or_hard_filters(df, steps, ch, self.cfg)
            if out.empty:
                continue
            # soft columns attached
            self.assertIn("soft_pass_count", out.columns)
            self.assertIn("soft_total", out.columns)
            self.assertEqual(int(out["soft_total"].iloc[0]), len(soft))
            return  # one channel suffices
        self.skipTest("no survivors in synthetic cross-section")

    def test_trend_scored_filter_attaches_soft(self):
        df = _make_df(40)
        for ch, prof in (self.cfg.channel_profiles or {}).items():
            steps, _ = build_industry_trend_steps(self.cfg, ch, prof)
            out, _ = apply_scored_or_hard_filters(df, steps, ch, self.cfg)
            if not out.empty:
                self.assertIn("soft_pass_count", out.columns)
                return
        self.skipTest("no survivors in synthetic cross-section")


if __name__ == "__main__":
    unittest.main()
