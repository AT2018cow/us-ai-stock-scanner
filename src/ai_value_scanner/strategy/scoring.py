from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_SCORE_COLUMNS = (
    "ps_discount",
    "pe_discount",
    "dollar_volume",
    "return_20d",
    "return_60d",
    "watchlist_etf_count",
    "range_position_52w",
    "drawdown_from_52w_high",
    "days_below_sma200",
    "net_margin",
    "ev_to_ebit",
    "fcf_yield",
    "ps_percentile_in_sic",
    "pe_percentile_in_sic",
    "revenue_yoy",
    "net_income_yoy",
    "adjusted_net_income_yoy",
    "ebit_yoy",
    "operating_cash_flow_yoy",
    "fundamental_quality_score",
    "net_debt_to_ebitda",
    "interest_coverage",
    "ocf_to_net_income",
    "accrual_ratio",
    "shares_yoy",
    "ps_hist_percentile",
    "pe_hist_percentile",
    "expectation_proxy",
    "cycle_proxy",
    "adv_participation",
    "estimated_slippage_bps",
    "current_debt_ratio",
    "inventory_growth_gap",
    "ai_link_score",
)

DEFAULT_SCORE_WEIGHTS = {
    "ps_discount": 0.40,
    "pe_discount": 0.30,
    "liquidity": 0.05,
    "return_20d": 0.00,
    "return_60d": 0.00,
    "watchlist_etf_count": 0.00,
    "range_position_52w_low": 0.00,
    "drawdown_from_52w_high": 0.00,
    "days_below_sma200": 0.00,
    "net_margin": 0.00,
    "ev_to_ebit_low": 0.00,
    "fcf_yield": 0.00,
    "ps_percentile_low": 0.10,
    "pe_percentile_low": 0.10,
    "revenue_yoy": 0.00,
    "net_income_yoy": 0.00,
    "ebit_yoy": 0.00,
    "operating_cash_flow_yoy": 0.00,
    "fundamental_quality_score": 0.00,
    "net_debt_to_ebitda_low": 0.00,
    "interest_coverage": 0.00,
    "ocf_to_net_income": 0.00,
    "accrual_ratio_low": 0.00,
    "shares_yoy_low": 0.00,
    "ps_hist_percentile_low": 0.00,
    "pe_hist_percentile_low": 0.00,
    "expectation_proxy": 0.00,
    "cycle_proxy": 0.00,
    "adv_participation_low": 0.00,
    "estimated_slippage_bps_low": 0.00,
    "current_debt_ratio_low": 0.00,
    "inventory_growth_gap_low": 0.00,
    "ai_link_score": 0.00,
}


def robust_normalize_score(
    series: pd.Series,
    lower_q: float,
    upper_q: float,
) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce").astype(float)
    valid = x.dropna()
    if valid.empty:
        return pd.Series([0.5] * len(x), index=x.index, dtype="float64")
    lo = float(valid.quantile(lower_q))
    hi = float(valid.quantile(upper_q))
    if not np.isfinite(lo):
        lo = float(valid.min())
    if not np.isfinite(hi):
        hi = float(valid.max())
    if hi < lo:
        lo, hi = hi, lo
    clipped = x.clip(lower=lo, upper=hi)
    mean = float(clipped.mean())
    std = float(clipped.std(ddof=0))
    if not np.isfinite(std) or std <= 1e-12:
        return pd.Series([0.5] * len(x), index=x.index, dtype="float64")
    z = (clipped - mean) / std
    norm = 1.0 / (1.0 + np.exp(-z))
    return pd.to_numeric(norm, errors="coerce").fillna(0.5)


def _component_series(out: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "ps_discount": out["ps_discount"],
        "pe_discount": out["pe_discount"],
        "liquidity": np.log1p(
            pd.to_numeric(out["dollar_volume"], errors="coerce").fillna(0)
        ),
        "return_20d": out["return_20d"],
        "return_60d": out["return_60d"],
        "watchlist_etf_count": pd.to_numeric(
            out["watchlist_etf_count"], errors="coerce"
        ),
        "range_position_52w_low": 1
        - pd.to_numeric(out["range_position_52w"], errors="coerce"),
        "drawdown_from_52w_high": pd.to_numeric(
            out["drawdown_from_52w_high"], errors="coerce"
        ),
        "days_below_sma200": pd.to_numeric(
            out["days_below_sma200"], errors="coerce"
        ),
        "net_margin": pd.to_numeric(out["net_margin"], errors="coerce"),
        "ev_to_ebit_low": -pd.to_numeric(out["ev_to_ebit"], errors="coerce"),
        "fcf_yield": pd.to_numeric(out["fcf_yield"], errors="coerce"),
        "ps_percentile_low": 1
        - pd.to_numeric(out["ps_percentile_in_sic"], errors="coerce"),
        "pe_percentile_low": 1
        - pd.to_numeric(out["pe_percentile_in_sic"], errors="coerce"),
        "revenue_yoy": pd.to_numeric(out["revenue_yoy"], errors="coerce"),
        "net_income_yoy": pd.to_numeric(out["net_income_yoy"], errors="coerce"),
        "ebit_yoy": pd.to_numeric(out["ebit_yoy"], errors="coerce"),
        "operating_cash_flow_yoy": pd.to_numeric(
            out["operating_cash_flow_yoy"], errors="coerce"
        ),
        "fundamental_quality_score": pd.to_numeric(
            out["fundamental_quality_score"], errors="coerce"
        ),
        "net_debt_to_ebitda_low": -pd.to_numeric(
            out["net_debt_to_ebitda"], errors="coerce"
        ),
        "interest_coverage": pd.to_numeric(
            out["interest_coverage"], errors="coerce"
        ),
        "ocf_to_net_income": pd.to_numeric(
            out["ocf_to_net_income"], errors="coerce"
        ),
        "accrual_ratio_low": -pd.to_numeric(
            out["accrual_ratio"], errors="coerce"
        ).abs(),
        "shares_yoy_low": -pd.to_numeric(out["shares_yoy"], errors="coerce"),
        "ps_hist_percentile_low": 1
        - pd.to_numeric(out["ps_hist_percentile"], errors="coerce"),
        "pe_hist_percentile_low": 1
        - pd.to_numeric(out["pe_hist_percentile"], errors="coerce"),
        "expectation_proxy": pd.to_numeric(
            out["expectation_proxy"], errors="coerce"
        ),
        "cycle_proxy": pd.to_numeric(out["cycle_proxy"], errors="coerce"),
        "adv_participation_low": -pd.to_numeric(
            out["adv_participation"], errors="coerce"
        ),
        "estimated_slippage_bps_low": -pd.to_numeric(
            out["estimated_slippage_bps"], errors="coerce"
        ),
        "current_debt_ratio_low": -pd.to_numeric(
            out["current_debt_ratio"], errors="coerce"
        ),
        "inventory_growth_gap_low": -pd.to_numeric(
            out["inventory_growth_gap"], errors="coerce"
        ),
        "ai_link_score": pd.to_numeric(out["ai_link_score"], errors="coerce"),
    }


def score_and_rank(
    df: pd.DataFrame,
    weights: dict[str, float],
    score_winsor_lower_q: float,
    score_winsor_upper_q: float,
    overvaluation_penalty_weight: float = 0.20,
    deterioration_penalty_weight: float = 0.20,
    pe_cash_backing_haircut: float = 1.0,
) -> pd.DataFrame:
    """Normalize scoring components, apply penalties and rank by composite."""
    out = df.copy()
    for col in REQUIRED_SCORE_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    component_series = _component_series(out)
    out["composite_score"] = 0.0
    use_fallback_defaults = not isinstance(weights, dict) or len(weights) == 0

    haircut_strength = max(0.0, float(pe_cash_backing_haircut))
    pe_cash_keys = {"pe_discount", "pe_percentile_low", "pe_hist_percentile_low"}
    if haircut_strength > 0.0:
        ocf_ni = pd.to_numeric(out["ocf_to_net_income"], errors="coerce")
        raw_factor = ocf_ni.clip(lower=0.0, upper=1.0).fillna(1.0)
        cash_factor = (
            1.0 - haircut_strength * (1.0 - raw_factor)
        ).clip(lower=0.0, upper=1.0)

    for key, raw in component_series.items():
        norm_col = f"{key}_norm"
        out[norm_col] = robust_normalize_score(
            raw,
            score_winsor_lower_q,
            score_winsor_upper_q,
        )
        if haircut_strength > 0.0 and key in pe_cash_keys:
            cheap_side = out[norm_col] > 0.5
            if cheap_side.any():
                out.loc[cheap_side, norm_col] = 0.5 + (
                    out.loc[cheap_side, norm_col] - 0.5
                ) * cash_factor.loc[cheap_side]
        if use_fallback_defaults:
            weight = float(DEFAULT_SCORE_WEIGHTS.get(key, 0.0))
        else:
            weight = float(weights.get(key, 0.0))
        out["composite_score"] += weight * out[norm_col]

    if (
        "soft_pass_count" in out.columns
        and pd.to_numeric(
            out["soft_pass_count"], errors="coerce"
        ).notna().any()
    ):
        soft_total = (
            pd.to_numeric(out["soft_total"], errors="coerce")
            .fillna(1)
            .clip(lower=1)
        )
        soft_count = pd.to_numeric(
            out["soft_pass_count"], errors="coerce"
        ).fillna(0)
        out["soft_pass_rate"] = (
            soft_count / soft_total
        ).clip(lower=0.0, upper=1.0)
        soft_weight = (
            float(weights.get("soft_pass_rate", 0.30))
            if isinstance(weights, dict)
            else 0.30
        )
        out["composite_score"] += soft_weight * out["soft_pass_rate"]

    ps_pct = pd.to_numeric(
        out["ps_percentile_in_sic"], errors="coerce"
    ).fillna(1.0)
    pe_pct = pd.to_numeric(
        out["pe_percentile_in_sic"], errors="coerce"
    ).fillna(1.0)
    overvaluation_penalty = (
        (ps_pct - 0.5).clip(lower=0)
        + (pe_pct - 0.5).clip(lower=0)
    )

    rev_yoy = pd.to_numeric(out["revenue_yoy"], errors="coerce")
    adj_ni_yoy = pd.to_numeric(
        out["adjusted_net_income_yoy"], errors="coerce"
    )
    ni_yoy = adj_ni_yoy.where(
        adj_ni_yoy.notna(),
        pd.to_numeric(out["net_income_yoy"], errors="coerce"),
    )
    rev_decline = (-rev_yoy).clip(lower=0).fillna(0)
    ni_decline = (-ni_yoy).clip(lower=0).fillna(0)
    deterioration_penalty = (
        (rev_decline + ni_decline).clip(upper=1.5) / 1.5
    )

    out["overvaluation_penalty"] = overvaluation_penalty
    out["deterioration_penalty"] = deterioration_penalty
    out["composite_score"] = (
        out["composite_score"]
        - float(overvaluation_penalty_weight) * out["overvaluation_penalty"]
        - float(deterioration_penalty_weight) * out["deterioration_penalty"]
    )

    return out.sort_values("composite_score", ascending=False)
