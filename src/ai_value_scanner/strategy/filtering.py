from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


CORE_FILTER_STEP_NAMES = frozenset({
    "price_notna",
    "min_price",
    "min_dollar_volume",
    "market_cap_notna",
    "min_market_cap",
    "max_market_cap",
    "watchlist_membership",
    "channel_bucket_match",
    "benchmark_trend_filter",
    "sic_filter",
    "max_adv_participation",
    "max_estimated_slippage_bps",
})

STYLE_STRUCTURAL_STEP_NAMES = {
    "risk_off": frozenset({
        "min_drawdown_from_52w_high",
        "max_price_to_sma200",
        "max_range_position_52w",
    }),
    "risk_on": frozenset({
        "min_price_to_sma200",
        "min_return_20d",
        "min_return_60d",
        "min_range_position_52w",
    }),
}


def classify_filter_step_layer(step_name: str) -> str:
    base_steps = {
        "price_notna",
        "min_price",
        "min_dollar_volume",
        "market_cap_notna",
        "min_market_cap",
        "max_market_cap",
        "watchlist_membership",
        "channel_bucket_match",
        "sic_filter",
        "min_watchlist_etf_count",
        "min_avg_dollar_volume_20d",
        "trend_min_watchlist_etf_count",
        "trend_min_avg_dollar_volume_20d",
        "momentum_min_watchlist_etf_count",
        "momentum_min_avg_dollar_volume_20d",
    }
    valuation_steps = {
        "min_value_discount_any",
        "max_ps_percentile_in_sic",
        "max_pe_percentile_in_sic",
        "max_ps",
        "max_pe",
        "max_ps_hist_percentile",
        "max_pe_hist_percentile",
        "min_drawdown_from_52w_high",
        "max_range_position_52w",
        "min_range_position_52w",
        "max_price_to_sma200",
        "min_price_to_sma200",
        "min_days_below_sma200",
        "min_drawdown_percentile",
        "min_return_20d",
        "min_return_60d",
        "max_20d_return",
        "max_60d_volatility",
        "max_60d_volatility_percentile",
        "trend_min_return_60d",
        "trend_max_60d_volatility",
        "momentum_min_return_20d",
        "momentum_min_return_60d",
        "momentum_min_price_to_sma200",
        "momentum_max_drawdown_from_52w_high",
        "momentum_max_60d_volatility",
    }
    if step_name in base_steps:
        return "base_hard"
    if step_name in valuation_steps:
        return "valuation_hard"
    return "quality_or_theme_hard"


def summarize_diagnostics_by_layer(
    diagnostics: list[dict[str, int | float | str]],
) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for row in diagnostics:
        step = str(row.get("step", ""))
        if step == "start":
            continue
        layer = str(row.get("layer", classify_filter_step_layer(step)))
        before = int(row.get("before", 0) or 0)
        remaining = int(row.get("remaining", 0) or 0)
        removed = int(row.get("removed", 0) or 0)
        if layer not in out:
            out[layer] = {
                "before": before,
                "remaining": remaining,
                "removed": removed,
            }
        else:
            out[layer]["remaining"] = remaining
            out[layer]["removed"] = int(out[layer]["removed"]) + removed
            if int(out[layer]["before"]) <= 0 and before > 0:
                out[layer]["before"] = before
    for payload in out.values():
        before = int(payload.get("before", 0) or 0)
        remaining = int(payload.get("remaining", 0) or 0)
        payload["pass_rate"] = (
            float(remaining / before) if before > 0 else 1.0
        )
    return out


def first_fail_concentration(first_fail_summary: pd.DataFrame) -> dict[str, Any]:
    if first_fail_summary.empty:
        return {"top_reason": "", "top_count": 0, "top_pct": 0.0}
    filtered = first_fail_summary[
        first_fail_summary["reason"] != "passed"
    ].copy()
    if filtered.empty:
        return {"top_reason": "passed", "top_count": 0, "top_pct": 0.0}
    top = filtered.sort_values("count", ascending=False).iloc[0]
    return {
        "top_reason": str(top.get("reason", "")),
        "top_count": int(top.get("count", 0) or 0),
        "top_pct": float(top.get("pct", 0.0) or 0.0),
    }


def apply_filters_with_diagnostics(
    df: pd.DataFrame,
    steps: list[tuple[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, int | float | str]]]:
    out = df.copy()
    diagnostics: list[dict[str, int | float | str]] = [
        {
            "step": "start",
            "before": int(len(out)),
            "remaining": int(len(out)),
            "removed": 0,
            "pass_rate": 1.0,
            "layer": "start",
        }
    ]
    for step_name, mask_fn in steps:
        before = len(out)
        out = out[mask_fn(out)]
        after = len(out)
        diagnostics.append(
            {
                "step": step_name,
                "before": int(before),
                "remaining": int(after),
                "removed": int(before - after),
                "pass_rate": float(after / before) if before > 0 else 1.0,
                "layer": classify_filter_step_layer(step_name),
            }
        )
    return out, diagnostics


def summarize_first_fail_reasons(
    df: pd.DataFrame,
    steps: list[tuple[str, Any]],
) -> pd.DataFrame:
    first_fail = pd.Series("passed", index=df.index, dtype="object")
    unresolved = pd.Series(True, index=df.index)
    for step_name, mask_fn in steps:
        raw_mask = mask_fn(df)
        mask = pd.Series(raw_mask, index=df.index).fillna(False).astype(bool)
        failed_now = unresolved & (~mask)
        first_fail.loc[failed_now] = step_name
        unresolved = unresolved & mask
    summary = (
        first_fail.value_counts(dropna=False)
        .rename_axis("reason")
        .reset_index(name="count")
    )
    total = max(1, len(df))
    summary["pct"] = (summary["count"] / total).round(4)
    return summary


def near_miss_concentration(
    df: pd.DataFrame,
    steps: list[tuple[str, Any]],
    top_n: int = 5,
) -> dict[str, Any]:
    if df.empty or not steps:
        return {
            "top_reason": "",
            "top_count": 0,
            "top_pct": 0.0,
            "reasons": [],
        }

    masks: list[tuple[str, pd.Series]] = []
    for step_name, mask_fn in steps:
        try:
            raw_mask = mask_fn(df)
            mask = pd.Series(
                raw_mask,
                index=df.index,
            ).fillna(False).astype(bool)
        except Exception:
            mask = pd.Series(False, index=df.index)
        masks.append((step_name, mask))

    rows: list[dict[str, Any]] = []
    total = int(len(df))
    for idx, (step_name, mask) in enumerate(masks):
        other = pd.Series(True, index=df.index)
        for j, (_, other_mask) in enumerate(masks):
            if j != idx:
                other &= other_mask
        near = other & ~mask
        count = int(near.sum())
        if count <= 0:
            continue
        rows.append(
            {
                "reason": step_name,
                "count": count,
                "pct": float(count / total) if total > 0 else 0.0,
                "layer": classify_filter_step_layer(step_name),
            }
        )
    rows = sorted(
        rows,
        key=lambda item: int(item["count"]),
        reverse=True,
    )[:top_n]
    if not rows:
        return {
            "top_reason": "",
            "top_count": 0,
            "top_pct": 0.0,
            "reasons": [],
        }
    top = rows[0]
    return {
        "top_reason": str(top["reason"]),
        "top_count": int(top["count"]),
        "top_pct": float(top["pct"]),
        "reasons": rows,
    }


def partition_filter_steps(
    steps: list[tuple[str, Any]],
    channel_name: str,
    strategy_style: str | None = None,
) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]]]:
    del channel_name
    style = strategy_style or "risk_off"
    if style not in STYLE_STRUCTURAL_STEP_NAMES:
        raise ValueError(
            f"Unsupported strategy_style for filter partition: {style!r}"
        )
    structural = STYLE_STRUCTURAL_STEP_NAMES[style]
    hard: list[tuple[str, Any]] = []
    soft: list[tuple[str, Any]] = []
    for name, fn in steps:
        if name in CORE_FILTER_STEP_NAMES or name in structural:
            hard.append((name, fn))
        else:
            soft.append((name, fn))
    return hard, soft


def apply_scored_or_hard_filters(
    df: pd.DataFrame,
    steps: list[tuple[str, Any]],
    channel_name: str,
    config: Any,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply canonical hard/soft filter semantics for all list types."""
    if str(getattr(config, "filter_mode", "scored")).lower() == "scored":
        hard_steps, soft_steps = partition_filter_steps(
            steps,
            channel_name,
            getattr(config, "strategy_style", None),
        )
        filtered, diagnostics = apply_filters_with_diagnostics(
            df,
            hard_steps,
        )
        if not filtered.empty and soft_steps:
            soft_matrix = pd.DataFrame(
                {
                    name: mask_fn(filtered)
                    for name, mask_fn in soft_steps
                },
                index=filtered.index,
            )
            filtered["soft_pass_count"] = soft_matrix.sum(axis=1)
            filtered["soft_total"] = len(soft_steps)
        else:
            filtered["soft_pass_count"] = 0
            filtered["soft_total"] = (
                len(soft_steps) if soft_steps else 1
            )
        return filtered, diagnostics

    filtered, diagnostics = apply_filters_with_diagnostics(df, steps)
    filtered["soft_pass_count"] = np.nan
    filtered["soft_total"] = np.nan
    return filtered, diagnostics
