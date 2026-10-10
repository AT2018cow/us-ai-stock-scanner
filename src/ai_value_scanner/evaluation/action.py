from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.decision.action import map_action_state
from ai_value_scanner.decision.integrated import DEFAULT_ATTENTION_CAP
from ai_value_scanner.decision.model import ActionState
from ai_value_scanner.evaluation.company_quality import apply_company_quality_v1
from ai_value_scanner.evaluation.entry_quality import apply_entry_quality_v1


def build_action_evaluation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply frozen Quality + Entry policies and attach canonical Action states."""
    quality = apply_company_quality_v1(frame)
    decisions = apply_entry_quality_v1(quality)
    out = decisions.copy()
    out["action_state"] = [
        map_action_state(quality_grade, entry_state).value
        for quality_grade, entry_state in zip(
            out["quality_grade"],
            out["entry_state"],
        )
    ]
    return out


def _cohort_row(
    subset: pd.DataFrame,
    *,
    action_state: str,
    horizon: int,
    segment_type: str,
    segment: str,
) -> dict[str, Any]:
    ret_col = f"fwd_ret_{horizon}"
    qqq_col = f"qqq_return_{horizon}"
    returns = (
        pd.to_numeric(subset[ret_col], errors="coerce")
        if ret_col in subset.columns
        else pd.Series(np.nan, index=subset.index, dtype="float64")
    )
    qqq = (
        pd.to_numeric(subset[qqq_col], errors="coerce")
        if qqq_col in subset.columns
        else pd.Series(np.nan, index=subset.index, dtype="float64")
    )
    excess = returns - qqq
    valid_return = returns.notna()
    valid_excess = excess.notna()

    per_date_return = pd.Series(dtype="float64")
    per_date_excess = pd.Series(dtype="float64")
    if "signal_date" in subset.columns:
        temp = pd.DataFrame(
            {
                "signal_date": subset["signal_date"].astype(str),
                "return": returns,
                "excess": excess,
            },
            index=subset.index,
        )
        per_date_return = (
            temp.loc[temp["return"].notna()]
            .groupby("signal_date")["return"]
            .mean()
        )
        per_date_excess = (
            temp.loc[temp["excess"].notna()]
            .groupby("signal_date")["excess"]
            .mean()
        )

    return {
        "segment_type": segment_type,
        "segment": segment,
        "action_state": action_state,
        "horizon_days": int(horizon),
        "n_decisions": int(len(subset)),
        "n_valid_return": int(valid_return.sum()),
        "n_valid_excess": int(valid_excess.sum()),
        "n_dates": (
            int(subset["signal_date"].nunique())
            if "signal_date" in subset.columns
            else 0
        ),
        "mean_return": (
            float(returns[valid_return].mean()) if valid_return.any() else np.nan
        ),
        "median_return": (
            float(returns[valid_return].median())
            if valid_return.any()
            else np.nan
        ),
        "hit_rate": (
            float((returns[valid_return] > 0).mean())
            if valid_return.any()
            else np.nan
        ),
        "mean_excess_vs_qqq": (
            float(excess[valid_excess].mean()) if valid_excess.any() else np.nan
        ),
        "median_excess_vs_qqq": (
            float(excess[valid_excess].median())
            if valid_excess.any()
            else np.nan
        ),
        "excess_hit_rate": (
            float((excess[valid_excess] > 0).mean())
            if valid_excess.any()
            else np.nan
        ),
        "date_equal_weight_mean_return": (
            float(per_date_return.mean()) if not per_date_return.empty else np.nan
        ),
        "date_equal_weight_mean_excess_vs_qqq": (
            float(per_date_excess.mean()) if not per_date_excess.empty else np.nan
        ),
        "worst_date_mean_return": (
            float(per_date_return.min()) if not per_date_return.empty else np.nan
        ),
        "worst_date_mean_excess_vs_qqq": (
            float(per_date_excess.min()) if not per_date_excess.empty else np.nan
        ),
    }


def summarize_action_cohorts(
    frame: pd.DataFrame,
    *,
    horizons: Iterable[int] = (20, 60, 120),
) -> pd.DataFrame:
    if "action_state" not in frame.columns:
        raise ValueError("action_state is required")

    work = frame.copy()
    if "signal_date" in work.columns:
        work["signal_year"] = pd.to_datetime(
            work["signal_date"],
            errors="coerce",
        ).dt.year.astype("Int64")

    rows: list[dict[str, Any]] = []
    states = [state.value for state in ActionState]

    def append_scope(scope: pd.DataFrame, segment_type: str, segment: str) -> None:
        for state in states:
            part = scope[scope["action_state"] == state]
            if part.empty:
                continue
            for horizon in horizons:
                rows.append(
                    _cohort_row(
                        part,
                        action_state=state,
                        horizon=int(horizon),
                        segment_type=segment_type,
                        segment=segment,
                    )
                )

    append_scope(work, "overall", "all")

    if "signal_year" in work.columns:
        for year in sorted(x for x in work["signal_year"].dropna().unique()):
            append_scope(work[work["signal_year"] == year], "year", str(int(year)))

    if "regime" in work.columns:
        for regime in sorted(str(x) for x in work["regime"].dropna().unique()):
            append_scope(
                work[work["regime"].astype(str) == regime],
                "regime",
                regime,
            )

    return pd.DataFrame(rows)


def summarize_action_compactness(
    frame: pd.DataFrame,
    *,
    attention_cap: int = DEFAULT_ATTENTION_CAP,
) -> pd.DataFrame:
    required = {"signal_date", "action_state"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"action compactness frame missing columns: {missing}")

    cap = max(1, int(attention_cap))
    rows: list[dict[str, Any]] = []
    for signal_date, group in frame.groupby("signal_date", sort=True):
        counts = group["action_state"].value_counts().to_dict()
        non_avoid = int((group["action_state"] != ActionState.AVOID.value).sum())
        attention = min(non_avoid, cap)
        rows.append(
            {
                "signal_date": str(signal_date),
                "n_decisions": int(len(group)),
                "n_non_avoid": non_avoid,
                "attention_cap": cap,
                "capped_attention_count": attention,
                "suppressed_by_cap": max(0, non_avoid - cap),
                "priority_review_count": int(
                    counts.get(ActionState.PRIORITY_REVIEW.value, 0)
                ),
                "watch_pullback_count": int(
                    counts.get(ActionState.WATCH_PULLBACK.value, 0)
                ),
                "watch_breakout_count": int(
                    counts.get(ActionState.WATCH_BREAKOUT.value, 0)
                ),
                "hold_monitor_count": int(
                    counts.get(ActionState.HOLD_MONITOR.value, 0)
                ),
                "avoid_count": int(counts.get(ActionState.AVOID.value, 0)),
            }
        )
    return pd.DataFrame(rows)


def summarize_action_concentration(frame: pd.DataFrame) -> pd.DataFrame:
    if "action_state" not in frame.columns:
        raise ValueError("action_state is required")

    rows: list[dict[str, Any]] = []
    for state in [state.value for state in ActionState]:
        subset = frame[frame["action_state"] == state]
        if subset.empty:
            continue
        symbol_counts = subset["symbol"].astype(str).value_counts()
        date_counts = subset["signal_date"].astype(str).value_counts()
        total = float(len(subset))
        rows.append(
            {
                "action_state": state,
                "n_decisions": int(len(subset)),
                "n_symbols": int(symbol_counts.size),
                "n_dates": int(date_counts.size),
                "top_symbol": (
                    str(symbol_counts.index[0]) if not symbol_counts.empty else ""
                ),
                "top_symbol_share": (
                    float(symbol_counts.iloc[0] / total)
                    if not symbol_counts.empty
                    else np.nan
                ),
                "top_date": str(date_counts.index[0]) if not date_counts.empty else "",
                "top_date_share": (
                    float(date_counts.iloc[0] / total)
                    if not date_counts.empty
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_action_transitions(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "signal_date", "action_state"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"action transition frame missing columns: {missing}")

    work = frame.loc[:, ["symbol", "signal_date", "action_state"]].copy()
    work["_signal_dt"] = pd.to_datetime(work["signal_date"], errors="coerce")
    work = work.dropna(subset=["_signal_dt"]).sort_values(
        ["symbol", "_signal_dt", "action_state"]
    )
    work["from_state"] = work.groupby("symbol")["action_state"].shift(1)
    work["from_date"] = work.groupby("symbol")["_signal_dt"].shift(1)
    work["gap_days"] = (work["_signal_dt"] - work["from_date"]).dt.days
    pairs = work.dropna(subset=["from_state", "from_date"]).copy()
    if pairs.empty:
        return pd.DataFrame(
            columns=[
                "from_state",
                "to_state",
                "n_transitions",
                "share_from_state",
                "median_gap_days",
            ]
        )

    grouped = (
        pairs.groupby(["from_state", "action_state"], dropna=False)
        .agg(
            n_transitions=("symbol", "size"),
            median_gap_days=("gap_days", "median"),
        )
        .reset_index()
        .rename(columns={"action_state": "to_state"})
    )
    totals = grouped.groupby("from_state")["n_transitions"].transform("sum")
    grouped["share_from_state"] = grouped["n_transitions"] / totals
    return grouped[
        [
            "from_state",
            "to_state",
            "n_transitions",
            "share_from_state",
            "median_gap_days",
        ]
    ].sort_values(
        ["from_state", "n_transitions", "to_state"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
