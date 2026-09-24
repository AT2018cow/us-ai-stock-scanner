from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.scanner import (
    ScanConfig,
    build_filter_steps,
    load_config,
)


def _trend_stock(symbol: str = "TREND") -> dict[str, object]:
    """Mirror-image of a balanced pick: above SMA200, near 52w highs, strong momentum."""
    return {
        "symbol": symbol,
        "price": 120.0,
        "price_to_sma200": 1.12,          # 12% above its 200d line
        "days_below_sma200": 0,            # never below recently
        "range_position_52w": 0.93,        # top 7% of 52-week range
        "drawdown_from_52w_high": 0.04,    # 4% below the 52w high
        "return_20d": 0.18,                # strong 20d momentum
        "return_60d": 0.22,
        "benchmark_trend_ok": True,
    }


def _pullback_stock(symbol: str = "PULL") -> dict[str, object]:
    """Classic balanced pick: deep pullback, below SMA200, recovering."""
    return {
        "symbol": symbol,
        "price": 60.0,
        "price_to_sma200": 0.94,           # 6% below its 200d line
        "days_below_sma200": 18,           # 18 consecutive days below
        "range_position_52w": 0.30,        # lower third of the 52w range
        "drawdown_from_52w_high": 0.28,    # deep drawdown
        "return_20d": -0.05,
        "return_60d": -0.08,
        "benchmark_trend_ok": True,
    }


def _base_frame() -> pd.DataFrame:
    # Structural filters only need these columns; fill the rest with neutral
    # values that pass common gates.
    df = pd.DataFrame([_trend_stock(), _pullback_stock()])
    for col in [
        "dollar_volume", "market_cap", "revenue", "net_income", "adjusted_net_income",
        "operating_cash_flow", "free_cash_flow", "ebit", "adjusted_ebit", "adjusted_ebitda",
        "revenue_yoy", "net_income_yoy", "adjusted_net_income_yoy", "ebit_yoy",
        "adjusted_ebit_yoy", "da_yoy", "operating_cash_flow_yoy", "shares_yoy",
        "receivables_yoy", "inventory_yoy", "receivables_growth_gap", "inventory_growth_gap",
        "interest_coverage", "net_debt_to_ebitda", "current_ratio",
        "current_debt_ratio", "ocf_to_net_income", "accrual_ratio",
        "fundamental_quality_score", "volatility_60d", "avg_dollar_volume_20d",
        "net_margin", "ps", "pe", "ev_to_ebit", "fcf_yield",
        "peer_median_ps", "peer_median_pe", "ps_discount", "pe_discount",
        "ps_percentile_in_sic", "pe_percentile_in_sic", "ps_hist_percentile",
        "pe_hist_percentile", "expectation_proxy", "cycle_proxy", "adv_participation",
        "estimated_slippage_bps", "min_ps_discount", "min_pe_discount",
        "ai_link_score", "watchlist_etf_count", "watchlist_bucket", "sic",
    ]:
        if col not in df.columns:
            df[col] = 1.0 if col not in ("ps_discount", "pe_discount", "peer_median_ps", "peer_median_pe", "sic") else 0.5
    # neutral-but-passing values for the common gates
    df["dollar_volume"] = 5e7
    df["market_cap"] = 5e10
    df["revenue"] = 1e10
    df["net_income"] = 1e9
    df["adjusted_net_income"] = 1e9
    df["free_cash_flow"] = 5e8
    df["revenue_yoy"] = 0.10
    df["net_income_yoy"] = 0.10
    df["fundamental_quality_score"] = 0.80
    df["accrual_ratio"] = -0.1
    df["volatility_60d"] = 0.30
    df["avg_dollar_volume_20d"] = 3e7
    df["ps"] = 2.0
    df["pe"] = 12.0
    df["ev_to_ebit"] = 10.0
    df["fcf_yield"] = 0.06
    df["peer_median_ps"] = 3.0
    df["peer_median_pe"] = 18.0
    df["ps_discount"] = 1 - df["ps"] / df["peer_median_ps"]
    df["pe_discount"] = 1 - df["pe"] / df["peer_median_pe"]
    df["ps_percentile_in_sic"] = 0.3
    df["pe_percentile_in_sic"] = 0.3
    df["ps_hist_percentile"] = 0.2
    df["pe_hist_percentile"] = 0.2
    df["ai_link_score"] = 0.5
    df["watchlist_etf_count"] = 2
    df["watchlist_bucket"] = "core_ai"
    df["sic"] = "7370"
    df["expectation_proxy"] = 0.1
    df["cycle_proxy"] = 0.0
    df["adv_participation"] = 0.001
    df["estimated_slippage_bps"] = 6.0
    df["shares_yoy"] = 0.01
    df["receivables_yoy"] = 0.10
    df["inventory_yoy"] = 0.10
    df["receivables_growth_gap"] = 0.0
    df["inventory_growth_gap"] = 0.0
    df["interest_coverage"] = 10.0
    df["net_debt_to_ebitda"] = 1.0
    df["current_ratio"] = 2.0
    df["current_debt_ratio"] = 0.2
    df["ocf_to_net_income"] = 1.2
    df["net_margin"] = 0.10
    df["ebit"] = 1.5e9
    df["adjusted_ebit"] = 1.5e9
    df["operating_cash_flow"] = 1.2e9
    df["adjusted_ebitda"] = 1.8e9
    df["days_below_sma200"] = [0, 18]
    return df


class TestStyleMirror(unittest.TestCase):
    def _structural_only(self, cfg: ScanConfig, channel: str = "core_ai") -> dict[str, object]:
        steps = build_filter_steps(cfg, channel, cfg.channel_profiles[channel])
        frame = _base_frame()
        for _, mask_fn in steps:
            frame = frame[mask_fn(frame)]
        return {"trend": "TREND" in set(frame["symbol"]), "pullback": "PULL" in set(frame["symbol"])}

    def test_risk_off_rejects_trend_stock_keeps_pullback(self) -> None:
        # Two-style architecture: risk_off is the defensive leg (pullback +
        # quality + deep-bear breaker); it must keep the mirror behavior
        # previously asserted for the archived balanced profile.
        cfg = load_config("configs/config.risk_off.json")
        survived = self._structural_only(cfg)
        self.assertFalse(survived["trend"], "risk_off must reject an extended trend stock")
        self.assertTrue(survived["pullback"], "risk_off must keep the deep-pullback stock")

    def test_risk_on_rejects_pullback_keeps_trend(self) -> None:
        cfg = load_config("configs/config.risk_on.json")
        survived = self._structural_only(cfg)
        self.assertTrue(survived["trend"], "risk_on must keep the trend stock")
        self.assertFalse(survived["pullback"], "risk_on must reject the deep-pullback stock")

    def test_risk_off_trend_filter_blocks_when_benchmark_below_sma(self) -> None:
        cfg = load_config("configs/config.risk_off.json")
        self.assertEqual(cfg.benchmark_trend_filter_symbol, "QQQ")
        steps = dict(build_filter_steps(cfg, "core_ai", cfg.channel_profiles["core_ai"]))
        self.assertIn("benchmark_trend_filter", steps)
        frame = _base_frame()
        frame["benchmark_trend_ok"] = False
        kept = steps["benchmark_trend_filter"](frame)
        self.assertEqual(frame.loc[kept].shape[0], 0)
        frame["benchmark_trend_ok"] = True
        kept = steps["benchmark_trend_filter"](frame)
        self.assertEqual(frame.loc[kept].shape[0], 2)
        # missing column fails open
        frame2 = frame.drop(columns=["benchmark_trend_ok"])
        kept = steps["benchmark_trend_filter"](frame2)
        self.assertEqual(frame2.loc[kept].shape[0], 2)

    def test_both_styles_carry_trend_filter(self) -> None:
        # Two-style architecture: risk_on (dual-momentum tail guard) and
        # risk_off (defensive core) both carry the QQQ breaker; the archived
        # balanced profile stays unconditional.
        for cfg_path in ["configs/config.risk_on.json", "configs/config.risk_off.json"]:
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.benchmark_trend_filter_symbol, "QQQ")
        archived = load_config("configs/archive/config.balanced.json")
        self.assertIsNone(archived.benchmark_trend_filter_symbol)

    def test_benchmark_breaker_mounts_on_all_list_types(self) -> None:
        # Regression: the breaker used to be wired only into the low_value
        # steps, leaving the momentum list (risk_on's PRIMARY) unprotected —
        # e.g. an ED signal fired on 2025-04-30 while QQQ sat below its own
        # 200d SMA. When enabled it must gate every list of the config.
        from ai_value_scanner.scanner import (
            build_industry_trend_steps,
            build_momentum_steps,
        )

        for cfg_path in ["configs/config.risk_on.json", "configs/config.risk_off.json"]:
            cfg = load_config(cfg_path)
            channel = "core_ai"
            profile = cfg.channel_profiles[channel]
            for name, steps in [
                ("low_value", build_filter_steps(cfg, channel, profile)),
                ("trend", build_industry_trend_steps(cfg, channel, profile)[0]),
                ("momentum", build_momentum_steps(cfg, channel, profile)[0]),
            ]:
                names = [s for s, _ in steps]
                self.assertIn(
                    "benchmark_trend_filter",
                    names,
                    f"{cfg_path}:{name} list missing the benchmark breaker",
                )
        # The archived balanced profile stays unconditional (historical
        # reference; two-style promote targets are risk_on/risk_off).
        cfg = load_config("configs/archive/config.balanced.json")
        profile = cfg.channel_profiles["core_ai"]
        for name, steps in [
            ("low_value", build_filter_steps(cfg, "core_ai", profile)),
            ("trend", build_industry_trend_steps(cfg, "core_ai", profile)[0]),
            ("momentum", build_momentum_steps(cfg, "core_ai", profile)[0]),
        ]:
            names = [s for s, _ in steps]
            self.assertNotIn("benchmark_trend_filter", names, "archived balanced must stay unconditional")


if __name__ == "__main__":
    unittest.main()
