from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.config import (
    ScanConfig,
    merge_soft_score_weights,
    resolve_channel_profile,
)


def percentile_floor_mask(series: pd.Series, q: float) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(False, index=series.index, dtype="bool")
    threshold = float(valid.quantile(q))
    return s.fillna(-np.inf) >= threshold


def percentile_cap_mask(series: pd.Series, q: float) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(False, index=series.index, dtype="bool")
    threshold = float(valid.quantile(q))
    return s.fillna(np.inf) <= threshold


HIGH_COVERAGE_HARD_FILTER_METRICS = {
    "fundamental_quality_score",
    "net_debt_to_ebitda",
    "current_ratio",
    "ocf_to_net_income",
    "accrual_ratio",
    "shares_yoy",
    "ps_hist_percentile",
    "pe_hist_percentile",
    "adv_participation",
    "estimated_slippage_bps",
}
MEDIUM_COVERAGE_HARD_FILTER_METRICS = {
    "interest_coverage",
    "receivables_growth_gap",
    "expectation_proxy",
    "cycle_proxy",
}
LOW_COVERAGE_HARD_FILTER_METRICS = {
    "current_debt_ratio",
    "inventory_growth_gap",
}


def hard_filter_metric_enabled(metric: str, config: ScanConfig, cp: dict[str, Any]) -> bool:
    mode = str(config.metric_hard_filter_coverage_mode or "high_coverage_only").strip().lower()
    if metric in LOW_COVERAGE_HARD_FILTER_METRICS:
        if metric == "current_debt_ratio" and cp.get("hard_filter_current_debt_ratio", False):
            return True
        if metric == "inventory_growth_gap" and cp.get("hard_filter_inventory_growth_gap", False):
            return True
        if bool(config.force_hard_filter_low_coverage_metrics):
            return True
        return False
    if mode == "all_metrics":
        return True
    if mode == "balanced":
        return metric in HIGH_COVERAGE_HARD_FILTER_METRICS or metric in MEDIUM_COVERAGE_HARD_FILTER_METRICS
    # high_coverage_only
    return metric in HIGH_COVERAGE_HARD_FILTER_METRICS

def watchlist_member_mask(frame: pd.DataFrame) -> pd.Series:
    if "watchlist_bucket" in frame.columns:
        bucket = frame["watchlist_bucket"].astype(str).str.strip()
    else:
        bucket = pd.Series("", index=frame.index, dtype="object")
    if "watchlist_etf_count" in frame.columns:
        etf_count = pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
    else:
        etf_count = pd.Series(0, index=frame.index, dtype="float64")
    return (bucket != "") | (etf_count > 0)


def channel_bucket_mask(frame: pd.DataFrame, channel_name: str) -> pd.Series:
    if "watchlist_bucket" not in frame.columns:
        return pd.Series(False, index=frame.index, dtype="bool")
    bucket = frame["watchlist_bucket"].fillna("").astype(str)
    pattern = rf"(?:^|,){re.escape(str(channel_name))}(?:,|$)"
    return bucket.str.contains(pattern, regex=True)


def passes_sic_filters(
    sic: str | None,
    exclude_codes: list[str],
) -> bool:
    if not sic:
        return False
    sic = str(sic)
    if exclude_codes and sic in exclude_codes:
        return False
    return True


def append_professional_filter_steps(
    steps: list[tuple[str, Any]], cp: dict[str, Any], config: ScanConfig
) -> list[tuple[str, Any]]:
    if cp["min_fundamental_quality_score"] is not None and hard_filter_metric_enabled(
        "fundamental_quality_score", config, cp
    ):
        steps.append(
            (
                "min_fundamental_quality_score",
                lambda frame: pd.to_numeric(frame["fundamental_quality_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_fundamental_quality_score"],
            )
        )
    if cp["max_net_debt_to_ebitda"] is not None and hard_filter_metric_enabled(
        "net_debt_to_ebitda", config, cp
    ):
        steps.append(
            (
                "max_net_debt_to_ebitda",
                lambda frame: (
                    pd.to_numeric(frame["net_debt_to_ebitda"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["net_debt_to_ebitda"], errors="coerce")
                        <= cp["max_net_debt_to_ebitda"]
                    )
                ),
            )
        )
    if cp["min_interest_coverage"] is not None and hard_filter_metric_enabled(
        "interest_coverage", config, cp
    ):
        steps.append(
            (
                "min_interest_coverage",
                lambda frame: (
                    pd.to_numeric(frame["interest_coverage"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["interest_coverage"], errors="coerce")
                        >= cp["min_interest_coverage"]
                    )
                ),
            )
        )
    if cp["max_current_debt_ratio"] is not None and hard_filter_metric_enabled(
        "current_debt_ratio", config, cp
    ):
        steps.append(
            (
                "max_current_debt_ratio",
                lambda frame: (
                    pd.to_numeric(frame["current_debt_ratio"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["current_debt_ratio"], errors="coerce")
                        <= cp["max_current_debt_ratio"]
                    )
                ),
            )
        )
    if cp["min_current_ratio"] is not None and hard_filter_metric_enabled("current_ratio", config, cp):
        steps.append(
            (
                "min_current_ratio",
                lambda frame: (
                    pd.to_numeric(frame["current_ratio"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["current_ratio"], errors="coerce")
                        >= cp["min_current_ratio"]
                    )
                ),
            )
        )
    if cp["min_ocf_to_net_income"] is not None and hard_filter_metric_enabled(
        "ocf_to_net_income", config, cp
    ):
        steps.append(
            (
                "min_ocf_to_net_income",
                lambda frame: (
                    pd.to_numeric(frame["ocf_to_net_income"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["ocf_to_net_income"], errors="coerce")
                        >= cp["min_ocf_to_net_income"]
                    )
                ),
            )
        )
    if cp["max_accrual_ratio"] is not None and hard_filter_metric_enabled("accrual_ratio", config, cp):
        steps.append(
            (
                "max_accrual_ratio",
                lambda frame: (
                    pd.to_numeric(frame["accrual_ratio"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["accrual_ratio"], errors="coerce")
                        <= cp["max_accrual_ratio"]
                    )
                ),
            )
        )
    if cp["max_receivables_growth_gap"] is not None and hard_filter_metric_enabled(
        "receivables_growth_gap", config, cp
    ):
        steps.append(
            (
                "max_receivables_growth_gap",
                lambda frame: (
                    pd.to_numeric(frame["receivables_growth_gap"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["receivables_growth_gap"], errors="coerce")
                        <= cp["max_receivables_growth_gap"]
                    )
                ),
            )
        )
    if cp["max_inventory_growth_gap"] is not None and hard_filter_metric_enabled(
        "inventory_growth_gap", config, cp
    ):
        steps.append(
            (
                "max_inventory_growth_gap",
                lambda frame: (
                    pd.to_numeric(frame["inventory_growth_gap"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["inventory_growth_gap"], errors="coerce")
                        <= cp["max_inventory_growth_gap"]
                    )
                ),
            )
        )
    if cp["max_shares_yoy"] is not None and hard_filter_metric_enabled("shares_yoy", config, cp):
        steps.append(
            (
                "max_shares_yoy",
                lambda frame: (
                    pd.to_numeric(frame["shares_yoy"], errors="coerce").isna()
                    | (pd.to_numeric(frame["shares_yoy"], errors="coerce") <= cp["max_shares_yoy"])
                ),
            )
        )
    if cp["max_ps_hist_percentile"] is not None and hard_filter_metric_enabled(
        "ps_hist_percentile", config, cp
    ):
        steps.append(
            (
                "max_ps_hist_percentile",
                lambda frame: (
                    pd.to_numeric(frame["ps_hist_percentile"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["ps_hist_percentile"], errors="coerce")
                        <= cp["max_ps_hist_percentile"]
                    )
                ),
            )
        )
    if cp["max_pe_hist_percentile"] is not None and hard_filter_metric_enabled(
        "pe_hist_percentile", config, cp
    ):
        steps.append(
            (
                "max_pe_hist_percentile",
                lambda frame: (
                    pd.to_numeric(frame["pe_hist_percentile"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["pe_hist_percentile"], errors="coerce")
                        <= cp["max_pe_hist_percentile"]
                    )
                ),
            )
        )
    if cp["min_expectation_proxy"] is not None and hard_filter_metric_enabled(
        "expectation_proxy", config, cp
    ):
        steps.append(
            (
                "min_expectation_proxy",
                lambda frame: (
                    pd.to_numeric(frame["expectation_proxy"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["expectation_proxy"], errors="coerce")
                        >= cp["min_expectation_proxy"]
                    )
                ),
            )
        )
    if cp["min_cycle_proxy"] is not None and hard_filter_metric_enabled("cycle_proxy", config, cp):
        steps.append(
            (
                "min_cycle_proxy",
                lambda frame: (
                    pd.to_numeric(frame["cycle_proxy"], errors="coerce").isna()
                    | (pd.to_numeric(frame["cycle_proxy"], errors="coerce") >= cp["min_cycle_proxy"])
                ),
            )
        )
    if cp["max_adv_participation"] is not None and hard_filter_metric_enabled(
        "adv_participation", config, cp
    ):
        steps.append(
            (
                "max_adv_participation",
                lambda frame: (
                    pd.to_numeric(frame["adv_participation"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["adv_participation"], errors="coerce")
                        <= cp["max_adv_participation"]
                    )
                ),
            )
        )
    if cp["max_estimated_slippage_bps"] is not None and hard_filter_metric_enabled(
        "estimated_slippage_bps", config, cp
    ):
        steps.append(
            (
                "max_estimated_slippage_bps",
                lambda frame: (
                    pd.to_numeric(frame["estimated_slippage_bps"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["estimated_slippage_bps"], errors="coerce")
                        <= cp["max_estimated_slippage_bps"]
                    )
                ),
            )
        )
    return steps

def build_benchmark_trend_step(config: ScanConfig) -> tuple[str, Any] | None:
    """Absolute-momentum circuit breaker shared by ALL list builders.

    When enabled (benchmark_trend_filter_symbol) and the benchmark trades
    below its own long-term trend, every list (low_value / industry_trend /
    momentum) of that config goes dark. Missing trend state fails open so a
    data gap cannot silently silence the defensive profile.
    """
    if not config.benchmark_trend_filter_symbol:
        return None

    def _benchmark_trend_mask(frame: pd.DataFrame) -> pd.Series:
        if "benchmark_trend_ok" not in frame.columns:
            return pd.Series(True, index=frame.index)
        return frame["benchmark_trend_ok"].fillna(True).astype(bool)

    return ("benchmark_trend_filter", _benchmark_trend_mask)


def build_filter_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> list[tuple[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)
    net_income_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    net_income_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        (
            "min_dollar_volume",
            lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume,
        ),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
        # Venture sleeve: max_market_cap is a definitional window gate and must
        # be a hard gate in the momentum/trend lists too (it already is in
        # build_filter_steps). Without it the quantum venture list filled with
        # mega-caps (AMD $992B vs the $3B window, 2026-09-28).
        *(
            [("max_market_cap", lambda frame: frame["market_cap"] <= config.max_market_cap)]
            if config.max_market_cap is not None
            else []
        ),
    ]

    if cp["require_positive_revenue"]:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if cp["require_positive_net_income"]:
        steps.append(
            (
                "positive_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_revenue"] is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= cp["min_revenue"]))
    if cp["min_net_income"] is not None:
        steps.append(
            (
                "min_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(0)
                >= cp["min_net_income"],
            )
        )
    if cp["require_positive_operating_cash_flow"]:
        steps.append(
            (
                "positive_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_free_cash_flow"]:
        steps.append(
            (
                "positive_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_ebit"]:
        steps.append(
            (
                "positive_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_operating_cash_flow"] is not None:
        steps.append(
            (
                "min_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-np.inf)
                >= cp["min_operating_cash_flow"],
            )
        )
    if cp["min_free_cash_flow"] is not None:
        steps.append(
            (
                "min_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-np.inf)
                >= cp["min_free_cash_flow"],
            )
        )
    if cp["min_ebit"] is not None:
        steps.append(
            (
                "min_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-np.inf) >= cp["min_ebit"],
            )
        )
    if cp["min_fcf_yield"] is not None:
        steps.append(
            (
                "min_fcf_yield",
                lambda frame: pd.to_numeric(frame["fcf_yield"], errors="coerce").fillna(-np.inf)
                >= cp["min_fcf_yield"],
            )
        )
    if cp["max_ev_to_ebit"] is not None:
        steps.append(
            (
                "max_ev_to_ebit",
                lambda frame: pd.to_numeric(frame["ev_to_ebit"], errors="coerce").fillna(np.inf)
                <= cp["max_ev_to_ebit"],
            )
        )
    if cp["min_revenue_yoy"] is not None:
        steps.append(
            (
                "min_revenue_yoy",
                lambda frame: pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(-np.inf)
                >= cp["min_revenue_yoy"],
            )
        )
    if cp["min_net_income_yoy"] is not None:
        steps.append(
            (
                "min_net_income_yoy",
                lambda frame: pd.to_numeric(frame[net_income_yoy_col], errors="coerce").fillna(-np.inf)
                >= cp["min_net_income_yoy"],
            )
        )
    if cp["min_net_margin"] is not None:
        steps.append(
            (
                "min_net_margin",
                lambda frame: pd.to_numeric(frame["net_margin"], errors="coerce").fillna(-np.inf)
                >= cp["min_net_margin"],
            )
        )
    if cp["max_ps"] is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= cp["max_ps"]))
    if cp["max_pe"] is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= cp["max_pe"]))
    if cp["min_drawdown_from_52w_high"] is not None:
        steps.append(
            (
                "min_drawdown_from_52w_high",
                lambda frame: frame["drawdown_from_52w_high"].fillna(-1) >= cp["min_drawdown_from_52w_high"],
            )
        )
    if cp["max_range_position_52w"] is not None:
        steps.append(
            (
                "max_range_position_52w",
                lambda frame: frame["range_position_52w"].fillna(np.inf) <= cp["max_range_position_52w"],
            )
        )
    if cp["min_range_position_52w"] is not None:
        steps.append(
            (
                "min_range_position_52w",
                lambda frame: frame["range_position_52w"].fillna(-np.inf) >= cp["min_range_position_52w"],
            )
        )
    if cp["max_price_to_sma200"] is not None:
        steps.append(
            (
                "max_price_to_sma200",
                lambda frame: frame["price_to_sma200"].fillna(np.inf) <= cp["max_price_to_sma200"],
            )
        )
    if cp["min_price_to_sma200"] is not None:
        steps.append(
            (
                "min_price_to_sma200",
                lambda frame: frame["price_to_sma200"].fillna(-np.inf) >= cp["min_price_to_sma200"],
            )
        )
    breaker_step = build_benchmark_trend_step(config)
    if breaker_step is not None:
        steps.append(breaker_step)
    if cp["min_days_below_sma200"] is not None:
        steps.append(
            (
                "min_days_below_sma200",
                lambda frame: frame["days_below_sma200"].fillna(-1) >= cp["min_days_below_sma200"],
            )
        )
    if cp["min_return_20d"] is not None:
        steps.append(
            (
                "min_return_20d",
                lambda frame: frame["return_20d"].fillna(-np.inf) >= cp["min_return_20d"],
            )
        )
    if cp["min_return_60d"] is not None:
        steps.append(
            (
                "min_return_60d",
                lambda frame: frame["return_60d"].fillna(-np.inf) >= cp["min_return_60d"],
            )
        )
    if cp["max_20d_return"] is not None:
        steps.append(
            (
                "max_20d_return",
                lambda frame: frame["return_20d"].fillna(np.inf) <= cp["max_20d_return"],
            )
        )
    if cp["max_60d_volatility"] is not None:
        steps.append(
            (
                "max_60d_volatility",
                lambda frame: frame["volatility_60d"].fillna(np.inf) <= cp["max_60d_volatility"],
            )
        )
    if cp["min_drawdown_percentile"] is not None:
        steps.append(
            (
                "min_drawdown_percentile",
                lambda frame: percentile_floor_mask(frame["drawdown_from_52w_high"], cp["min_drawdown_percentile"]),
            )
        )
    if cp["min_avg_dollar_volume_20d_percentile"] is not None:
        steps.append(
            (
                "min_avg_dollar_volume_20d_percentile",
                lambda frame: percentile_floor_mask(
                    frame["avg_dollar_volume_20d"], cp["min_avg_dollar_volume_20d_percentile"]
                ),
            )
        )
    if cp["max_60d_volatility_percentile"] is not None:
        steps.append(
            (
                "max_60d_volatility_percentile",
                lambda frame: percentile_cap_mask(
                    frame["volatility_60d"], cp["max_60d_volatility_percentile"]
                ),
            )
        )
    if cp["min_watchlist_etf_count"] > 1:
        steps.append(
            (
                "min_watchlist_etf_count",
                lambda frame: pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
                >= int(cp["min_watchlist_etf_count"]),
            )
        )
    if cp["min_avg_dollar_volume_20d"] is not None:
        steps.append(
            (
                "min_avg_dollar_volume_20d",
                lambda frame: pd.to_numeric(frame["avg_dollar_volume_20d"], errors="coerce").fillna(0)
                >= cp["min_avg_dollar_volume_20d"],
            )
        )

    steps = append_professional_filter_steps(steps, cp, config)
    steps.append(("watchlist_membership", watchlist_member_mask))
    if cp["require_channel_bucket_match"]:
        steps.append(
            (
                "channel_bucket_match",
                lambda frame: channel_bucket_mask(frame, channel_name),
            )
        )
    if cp["min_ai_link_score"] is not None:
        steps.append(
            (
                "min_ai_link_score",
                lambda frame: pd.to_numeric(frame["ai_link_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_ai_link_score"],
            )
        )

    steps.extend(
        [
            (
                "min_value_discount_any",
                lambda frame: (
                    pd.to_numeric(frame["ps_discount"], errors="coerce").fillna(-np.inf) >= cp["min_ps_discount"]
                )
                | (
                    pd.to_numeric(frame["pe_discount"], errors="coerce").fillna(-np.inf) >= cp["min_pe_discount"]
                ),
            ),
            (
                "max_ps_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["ps_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_ps_percentile_in_sic"]
                if cp["max_ps_percentile_in_sic"] is not None
                else pd.Series(True, index=frame.index),
            ),
            (
                "max_pe_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["pe_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_pe_percentile_in_sic"]
                if cp["max_pe_percentile_in_sic"] is not None
                else pd.Series(True, index=frame.index),
            ),
            (
                "sic_filter",
                lambda frame: frame["sic"].apply(
                    lambda x: passes_sic_filters(
                        x,
                        cp["exclude_sic_codes"],
                    )
                ),
            ),
        ]
    )
    return steps


def build_industry_trend_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> tuple[list[tuple[str, Any]], dict[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)
    net_income_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    net_income_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"
    trend_weights = channel_profile.get("trend_score_weights")
    trend_min_watchlist_etf_count = int(
        channel_profile.get("trend_min_watchlist_etf_count", cp["min_watchlist_etf_count"])
    )
    trend_min_return_60d = channel_profile.get("trend_min_return_60d", cp["min_return_60d"])
    trend_max_60d_volatility = channel_profile.get("trend_max_60d_volatility", cp["max_60d_volatility"])
    trend_min_avg_dollar_volume_20d = channel_profile.get(
        "trend_min_avg_dollar_volume_20d", cp["min_avg_dollar_volume_20d"]
    )
    if not isinstance(trend_weights, dict):
        if channel_name == "ai_enabler":
            trend_weights = {
                "liquidity": 0.20,
                "watchlist_etf_count": 0.30,
                "ai_link_score": 0.20,
                "return_20d": 0.30,
                "drawdown_from_52w_high": -0.10,
            }
        else:
            trend_weights = {
                "liquidity": 0.20,
                "watchlist_etf_count": 0.25,
                "ai_link_score": 0.20,
                "return_20d": 0.35,
                "drawdown_from_52w_high": -0.10,
            }
    trend_weights = merge_soft_score_weights(trend_weights, config.low_coverage_soft_score_weights)

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        ("min_dollar_volume", lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
        # Venture sleeve: max_market_cap is a definitional window gate and must
        # be a hard gate in the momentum/trend lists too (it already is in
        # build_filter_steps). Without it the quantum venture list filled with
        # mega-caps (AMD $992B vs the $3B window, 2026-09-28).
        *(
            [("max_market_cap", lambda frame: frame["market_cap"] <= config.max_market_cap)]
            if config.max_market_cap is not None
            else []
        ),
    ]
    if cp["require_positive_revenue"]:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if cp["require_positive_net_income"]:
        steps.append(
            (
                "positive_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_operating_cash_flow"]:
        steps.append(
            (
                "positive_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_free_cash_flow"]:
        steps.append(
            (
                "positive_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_ebit"]:
        steps.append(
            (
                "positive_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_revenue"] is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= cp["min_revenue"]))
    if cp["min_net_income"] is not None:
        steps.append(
            (
                "min_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(0)
                >= cp["min_net_income"],
            )
        )
    if cp["max_ps"] is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= cp["max_ps"]))
    if cp["max_pe"] is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= cp["max_pe"]))
    if cp["min_revenue_yoy"] is not None:
        steps.append(
            (
                "min_revenue_yoy",
                lambda frame: pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(-np.inf)
                >= cp["min_revenue_yoy"],
            )
        )
    if cp["min_net_income_yoy"] is not None:
        steps.append(
            (
                "min_net_income_yoy",
                lambda frame: pd.to_numeric(frame[net_income_yoy_col], errors="coerce").fillna(-np.inf)
                >= cp["min_net_income_yoy"],
            )
        )
    if cp["min_fcf_yield"] is not None:
        steps.append(
            (
                "min_fcf_yield",
                lambda frame: pd.to_numeric(frame["fcf_yield"], errors="coerce").fillna(-np.inf)
                >= cp["min_fcf_yield"],
            )
        )
    if cp["max_ev_to_ebit"] is not None:
        steps.append(
            (
                "max_ev_to_ebit",
                lambda frame: pd.to_numeric(frame["ev_to_ebit"], errors="coerce").fillna(np.inf)
                <= cp["max_ev_to_ebit"],
            )
        )
    if cp["max_ps_percentile_in_sic"] is not None:
        steps.append(
            (
                "max_ps_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["ps_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_ps_percentile_in_sic"],
            )
        )
    if cp["max_pe_percentile_in_sic"] is not None:
        steps.append(
            (
                "max_pe_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["pe_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_pe_percentile_in_sic"],
            )
        )
    if trend_min_return_60d is not None:
        steps.append(
            (
                "trend_min_return_60d",
                lambda frame: frame["return_60d"].fillna(-np.inf) >= float(trend_min_return_60d),
            )
        )
    if trend_max_60d_volatility is not None:
        steps.append(
            (
                "trend_max_60d_volatility",
                lambda frame: frame["volatility_60d"].fillna(np.inf) <= float(trend_max_60d_volatility),
            )
        )
    if trend_min_avg_dollar_volume_20d is not None:
        steps.append(
            (
                "trend_min_avg_dollar_volume_20d",
                lambda frame: pd.to_numeric(frame["avg_dollar_volume_20d"], errors="coerce").fillna(0)
                >= float(trend_min_avg_dollar_volume_20d),
            )
        )
    if trend_min_watchlist_etf_count > 1:
        steps.append(
            (
                "trend_min_watchlist_etf_count",
                lambda frame: pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
                >= trend_min_watchlist_etf_count,
            )
        )

    steps = append_professional_filter_steps(steps, cp, config)
    steps.append(("watchlist_membership", watchlist_member_mask))
    if cp["require_channel_bucket_match"]:
        steps.append(
            (
                "channel_bucket_match",
                lambda frame: channel_bucket_mask(frame, channel_name),
            )
        )
    if cp["min_ai_link_score"] is not None:
        steps.append(
            (
                "min_ai_link_score",
                lambda frame: pd.to_numeric(frame["ai_link_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_ai_link_score"],
            )
        )

    steps.append(
        (
            "sic_filter",
            lambda frame: frame["sic"].apply(
                lambda x: passes_sic_filters(
                    x,
                    cp["exclude_sic_codes"],
                )
            ),
        )
    )
    breaker_step = build_benchmark_trend_step(config)
    if breaker_step is not None:
        steps.append(breaker_step)
    return steps, trend_weights


def build_momentum_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> tuple[list[tuple[str, Any]], dict[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)
    net_income_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    net_income_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"
    momentum_min_return_20d = channel_profile.get("momentum_min_return_20d", 0.05)
    momentum_min_price_to_sma200 = channel_profile.get("momentum_min_price_to_sma200", 1.05)
    momentum_max_drawdown_from_52w_high = channel_profile.get(
        "momentum_max_drawdown_from_52w_high", 0.25
    )
    momentum_min_watchlist_etf_count = int(
        channel_profile.get("momentum_min_watchlist_etf_count", cp["min_watchlist_etf_count"])
    )
    momentum_min_return_60d = channel_profile.get("momentum_min_return_60d", cp["min_return_60d"])
    momentum_max_60d_volatility = channel_profile.get(
        "momentum_max_60d_volatility", cp["max_60d_volatility"]
    )
    momentum_min_avg_dollar_volume_20d = channel_profile.get(
        "momentum_min_avg_dollar_volume_20d", cp["min_avg_dollar_volume_20d"]
    )
    momentum_weights = channel_profile.get("momentum_score_weights")
    if not isinstance(momentum_weights, dict):
        momentum_weights = {
            "liquidity": 0.10,
            "return_20d": 0.50,
            "watchlist_etf_count": 0.20,
            "ai_link_score": 0.20,
            "drawdown_from_52w_high": -0.10,
        }
    momentum_weights = merge_soft_score_weights(
        momentum_weights, config.low_coverage_soft_score_weights
    )

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        ("min_dollar_volume", lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
        # Venture sleeve: max_market_cap is a definitional window gate and must
        # be a hard gate in the momentum/trend lists too (it already is in
        # build_filter_steps). Without it the quantum venture list filled with
        # mega-caps (AMD $992B vs the $3B window, 2026-09-28).
        *(
            [("max_market_cap", lambda frame: frame["market_cap"] <= config.max_market_cap)]
            if config.max_market_cap is not None
            else []
        ),
        (
            "min_fcf_yield",
            lambda frame: pd.to_numeric(frame["fcf_yield"], errors="coerce").fillna(-np.inf)
            >= float(cp["min_fcf_yield"])
            if cp["min_fcf_yield"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "max_ev_to_ebit",
            lambda frame: pd.to_numeric(frame["ev_to_ebit"], errors="coerce").fillna(np.inf)
            <= float(cp["max_ev_to_ebit"])
            if cp["max_ev_to_ebit"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "min_revenue_yoy",
            lambda frame: pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(-np.inf)
            >= float(cp["min_revenue_yoy"])
            if cp["min_revenue_yoy"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "min_net_income_yoy",
            lambda frame: pd.to_numeric(frame[net_income_yoy_col], errors="coerce").fillna(-np.inf)
            >= float(cp["min_net_income_yoy"])
            if cp["min_net_income_yoy"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "max_ps_percentile_in_sic",
            lambda frame: pd.to_numeric(frame["ps_percentile_in_sic"], errors="coerce").fillna(np.inf)
            <= float(cp["max_ps_percentile_in_sic"])
            if cp["max_ps_percentile_in_sic"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "max_pe_percentile_in_sic",
            lambda frame: pd.to_numeric(frame["pe_percentile_in_sic"], errors="coerce").fillna(np.inf)
            <= float(cp["max_pe_percentile_in_sic"])
            if cp["max_pe_percentile_in_sic"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "momentum_min_return_20d",
            lambda frame: frame["return_20d"].fillna(-np.inf) >= float(momentum_min_return_20d),
        ),
        (
            "momentum_min_price_to_sma200",
            lambda frame: frame["price_to_sma200"].fillna(-np.inf) >= float(momentum_min_price_to_sma200),
        ),
        (
            "momentum_max_drawdown_from_52w_high",
            lambda frame: frame["drawdown_from_52w_high"].fillna(np.inf)
            <= float(momentum_max_drawdown_from_52w_high),
        ),
    ]
    if cp["require_positive_revenue"]:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if cp["require_positive_net_income"]:
        steps.append(
            (
                "positive_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_operating_cash_flow"]:
        steps.append(
            (
                "positive_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_free_cash_flow"]:
        steps.append(
            (
                "positive_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_ebit"]:
        steps.append(
            (
                "positive_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_revenue"] is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= cp["min_revenue"]))
    if cp["min_net_income"] is not None:
        steps.append(
            (
                "min_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(0)
                >= cp["min_net_income"],
            )
        )
    if cp["max_ps"] is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= cp["max_ps"]))
    if cp["max_pe"] is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= cp["max_pe"]))
    if momentum_min_return_60d is not None:
        steps.append(
            (
                "momentum_min_return_60d",
                lambda frame: frame["return_60d"].fillna(-np.inf) >= float(momentum_min_return_60d),
            )
        )
    if momentum_max_60d_volatility is not None:
        steps.append(
            (
                "momentum_max_60d_volatility",
                lambda frame: frame["volatility_60d"].fillna(np.inf) <= float(momentum_max_60d_volatility),
            )
        )
    if momentum_min_avg_dollar_volume_20d is not None:
        steps.append(
            (
                "momentum_min_avg_dollar_volume_20d",
                lambda frame: pd.to_numeric(frame["avg_dollar_volume_20d"], errors="coerce").fillna(0)
                >= float(momentum_min_avg_dollar_volume_20d),
            )
        )
    if momentum_min_watchlist_etf_count > 1:
        steps.append(
            (
                "momentum_min_watchlist_etf_count",
                lambda frame: pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
                >= momentum_min_watchlist_etf_count,
            )
        )

    steps = append_professional_filter_steps(steps, cp, config)
    steps.append(("watchlist_membership", watchlist_member_mask))
    if cp["require_channel_bucket_match"]:
        steps.append(
            (
                "channel_bucket_match",
                lambda frame: channel_bucket_mask(frame, channel_name),
            )
        )
    if cp["min_ai_link_score"] is not None:
        steps.append(
            (
                "min_ai_link_score",
                lambda frame: pd.to_numeric(frame["ai_link_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_ai_link_score"],
            )
        )

    steps.append(
        (
            "sic_filter",
            lambda frame: frame["sic"].apply(
                lambda x: passes_sic_filters(
                    x,
                    cp["exclude_sic_codes"],
                )
            ),
        )
    )
    breaker_step = build_benchmark_trend_step(config)
    if breaker_step is not None:
        steps.append(breaker_step)
    return steps, momentum_weights
