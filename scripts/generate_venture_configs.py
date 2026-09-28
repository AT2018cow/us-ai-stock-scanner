"""Generate per-theme VENTURE scan configs (docs/multi_theme_expansion.md §6.3).

Base = the theme config (configs/config.theme.<name>.json: theme benchmarks,
saturation, disclosure weight 0, snapshot isolation), overridden with the
venture sleeve semantics:

- Definitional window (HARD): market cap $100M-$3B, daily dollar volume >= $500k
- No profitability hard gates (require_positive_* false except revenue);
  all valuation/quality thresholds nulled — early 10x candidates are
  structurally unprofitable and expensive on current fundamentals
- Venture scoring (low_value): revenue acceleration 0.25, theme purity
  0.20, momentum onset 0.10+0.05, operating leverage (ebit/ocf yoy) 0.10,
  liquidity 0.05, soft layer down-weighted to 0.15 (venture deliberately
  relaxes quality constraints)
- Research gates: no risk exclusions, all priorities except avoid_for_now
  admitted, score floor 0 — the venture score is the sorter
- Dilution (shares_yoy) threshold nulled: MONITOR-ONLY by design (10x
  paths almost always dilute)

Idempotent: rerun overwrites.

Usage:
    .venv/bin/python scripts/generate_venture_configs.py [--theme nuclear]
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

THEMES = ["nuclear", "quantum", "biotech", "rare_earth", "critical_minerals"]

VENTURE_LOW_VALUE_WEIGHTS = {
    "revenue_yoy": 0.25,
    "ai_link_score": 0.20,
    "return_20d": 0.10,
    "return_60d": 0.05,
    "ebit_yoy": 0.05,
    "operating_cash_flow_yoy": 0.05,
    "liquidity": 0.05,
    "soft_pass_rate": 0.15,
    # All valuation/quality keys intentionally 0: venture does not rank by
    # cheapness or current profitability.
    "ps_discount": 0.0,
    "pe_discount": 0.0,
    "ps_percentile_low": 0.0,
    "pe_percentile_low": 0.0,
    "ev_to_ebit_low": 0.0,
    "fcf_yield": 0.0,
    "net_margin": 0.0,
    "net_income_yoy": 0.0,
    "watchlist_etf_count": 0.0,
    "range_position_52w_low": 0.0,
    "drawdown_from_52w_high": 0.0,
    "days_below_sma200": 0.0,
    "fundamental_quality_score": 0.0,
    "net_debt_to_ebitda_low": 0.0,
    "interest_coverage": 0.0,
    "ocf_to_net_income": 0.0,
    "accrual_ratio_low": 0.0,
    "shares_yoy_low": 0.0,
    "ps_hist_percentile_low": 0.0,
    "pe_hist_percentile_low": 0.0,
    "expectation_proxy": 0.0,
    "cycle_proxy": 0.0,
    "adv_participation_low": 0.0,
    "estimated_slippage_bps_low": 0.0,
    "current_debt_ratio_low": 0.0,
    "inventory_growth_gap_low": 0.0,
}


def venture_overrides(base: dict) -> dict:
    cfg = deepcopy(base)
    # ---- Definitional window (hard gates) ----
    cfg["min_market_cap"] = 1e8
    cfg["max_market_cap"] = 3e9
    cfg["min_dollar_volume"] = 5e5
    # ---- No profitability gates ----
    cfg["require_positive_revenue"] = True
    cfg["require_positive_net_income"] = False
    cfg["require_positive_operating_cash_flow"] = False
    cfg["require_positive_free_cash_flow"] = False
    cfg["require_positive_ebit"] = False
    # ---- Null out valuation/quality thresholds (no soft dims, no weights) ----
    for key in [
        "min_ps_discount", "min_pe_discount",
        "max_ps_percentile_in_sic", "max_pe_percentile_in_sic",
        "max_ev_to_ebit", "min_fcf_yield",
        "max_ps_hist_percentile", "max_pe_hist_percentile",
        "max_net_debt_to_ebitda", "min_interest_coverage",
        "min_ocf_to_net_income", "max_accrual_ratio",
        "max_receivables_growth_gap", "max_inventory_growth_gap",
        "max_shares_yoy",  # dilution: monitor-only
        "min_expectation_proxy", "min_cycle_proxy",
        "min_fundamental_quality_score",
        "min_net_margin", "max_ps", "max_pe",
        # Flow magnitude floors off (soft anyway, but 10M/20M floors would
        # dent soft_pass_rate for small names).
        "min_free_cash_flow", "min_net_income", "min_operating_cash_flow", "min_ebit",
        "min_revenue",
    ]:
        cfg[key] = None
    # Global style-structural price gates off (early 10x paths can sit below
    # SMA200 or have risen hard already).
    for key in [
        "min_drawdown_from_52w_high", "max_range_position_52w",
        "max_price_to_sma200", "min_days_below_sma200",
        "min_return_20d", "min_return_60d", "max_20d_return",
        "max_60d_volatility", "min_drawdown_percentile",
        "min_avg_dollar_volume_20d_percentile", "max_60d_volatility_percentile",
    ]:
        cfg[key] = None
    # Growth floor as the one soft fundamental requirement: no shrinking revenue.
    cfg["min_revenue_yoy"] = 0.0
    # ---- Research gates: scoring is the sorter ----
    cfg["low_value_excluded_research_risks"] = []
    cfg["low_value_allowed_research_priorities"] = [
        "research_now", "watch_for_pullback", "theme_only", "left_side_watch",
    ]
    cfg["low_value_min_research_score"] = 0.0
    cfg["research_pool_min_score"] = 0.0
    cfg["research_pool_top_n"] = 50
    # ---- Venture scoring ----
    profiles = cfg.get("channel_profiles") or {}
    for bucket, prof in profiles.items():
        prof["score_weights"] = dict(VENTURE_LOW_VALUE_WEIGHTS)
        # Theme purity handled by the score weight; L3 (pre-ETF) names must
        # not be killed by membership/link gates.
        prof["min_watchlist_etf_count"] = 0
        prof["min_ai_link_score"] = None
        # style-structural price gates off (early 10x paths can be below SMA200)
        prof["min_drawdown_from_52w_high"] = None
        prof["max_range_position_52w"] = None
        prof["max_price_to_sma200"] = None
        prof["min_days_below_sma200"] = 0
        prof["min_return_20d"] = None
        prof["min_return_60d"] = None
        prof["max_20d_return"] = None
        prof["max_60d_volatility"] = None
        prof["min_drawdown_percentile"] = None
        prof["min_avg_dollar_volume_20d_percentile"] = None
        prof["max_60d_volatility_percentile"] = None
        prof["min_fundamental_quality_score"] = None
        prof["min_ps_discount"] = None
        prof["min_pe_discount"] = None
        prof["max_ps_percentile_in_sic"] = None
        prof["max_pe_percentile_in_sic"] = None
        prof["max_ev_to_ebit"] = None
        prof["min_fcf_yield"] = None
        prof["min_revenue_yoy"] = 0.0
        prof["min_net_income_yoy"] = None
        prof["max_ps_hist_percentile"] = None
        prof["max_pe_hist_percentile"] = None
    return cfg


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--theme", default=None, help="Only this theme")
    args = p.parse_args()
    themes = [args.theme] if args.theme else THEMES
    for theme in themes:
        base_path = Path(f"configs/config.theme.{theme}.json")
        if not base_path.exists():
            raise SystemExit(f"missing {base_path} — run generate_theme_configs.py first")
        base = json.loads(base_path.read_text())
        cfg = venture_overrides(base)
        cfg["watchlist_csv_path"] = f"data/venture_watchlist_{theme}.csv"
        cfg["_venture_meta"] = {
            "sleeve": "venture",
            "theme": theme,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "design": "docs/multi_theme_expansion.md §6.3",
            "risk_model": "P0 paper only — 0.25-0.5% per name, 20-40 names, no -25% stops, "
                          "expect 60-80% of names to lose 50%+; capital gated on matured cohorts",
        }
        out = Path(f"configs/config.venture.{theme}.json")
        out.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        print(f"generated {out}")


if __name__ == "__main__":
    main()
