"""Pure review summaries for pre-registered 2023–2024 date-paired returns.

No automatic candidate winner or statistical significance claims.  All
means are equal-weighted across valid signal dates, never over ticker rows.
A date excluded from one arm is excluded from the other simultaneously.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


COLUMNS = (
    "candidate_id", "signal_date", "horizon", "cap",
    "primary_paired_valid", "event_sensitivity_valid",
    "score_sensitivity_valid", "paired_delta_net_qqq_excess",
    "b0_net_qqq_excess", "candidate_net_qqq_excess",
    "n_topk_swaps",
)


def _positive(value: Any) -> bool:
    if pd.isna(value):
        raise ValueError("null boolean paired mask")
    if str(value).lower() not in ("true", "false"):
        raise ValueError("non-boolean paired mask")
    return str(value).lower() == "true"


def paired_metrics(paired: pd.DataFrame) -> pd.DataFrame:
    if not set(COLUMNS).issubset(paired):
        raise ValueError(f"paired data missing {sorted(set(COLUMNS) - set(paired))}")
    if paired.duplicated(["candidate_id", "signal_date", "horizon", "cap"]).any():
        raise ValueError("duplicate candidate×date×horizon×cap comparisons")
    if paired.empty:
        raise ValueError("empty date-paired metrics")
    rows: list[dict[str, Any]] = []
    for (candidate, horizon, cap), group in paired.groupby(
        ["candidate_id", "horizon", "cap"], sort=True
    ):
        valid = group.primary_paired_valid.map(_positive)
        event_valid = group.event_sensitivity_valid.map(_positive)
        score_valid = group.score_sensitivity_valid.map(_positive)
        if (event_valid & ~valid).any() or (score_valid & ~valid).any():
            raise ValueError("sensitivity cannot restore a missing-label pair")
        nonmissing = pd.to_numeric(
            group.loc[valid, "paired_delta_net_qqq_excess"], errors="coerce"
        )
        if not nonmissing.map(math.isfinite).all():
            raise ValueError("invalid or missing delta in supposedly valid pairs")
        if group.loc[~valid, "paired_delta_net_qqq_excess"].notna().any():
            raise ValueError("unpaired date has a return delta")
        subset = group.loc[valid].copy()
        subset["paired_delta_net_qqq_excess"] = nonmissing
        deltas = subset["paired_delta_net_qqq_excess"]
        ev_deltas = pd.to_numeric(
            group.loc[event_valid, "paired_delta_net_qqq_excess"], errors="raise"
        )
        sc_deltas = pd.to_numeric(
            group.loc[score_valid, "paired_delta_net_qqq_excess"], errors="raise"
        )
        primary_valid_count = int(valid.sum())
        row = {
            "candidate_id": str(candidate),
            "horizon": int(horizon), "cap": int(cap),
            "n_dates_total": len(group),
            "n_dates_valid": primary_valid_count,
            "n_dates_missing_label": int((~valid).sum()),
            "n_dates_event_sensitivity": int(event_valid.sum()),
            "n_dates_score_sensitivity": int(score_valid.sum()),
            "n_dates_event_excluded": int((valid & ~event_valid).sum()),
            "n_dates_score_excluded": int((valid & ~score_valid).sum()),
            "n_dates_topk_swapped": int((group.n_topk_swaps > 0).sum()),
            "n_total_topk_swaps": int(group.n_topk_swaps.sum()),
            "mean_paired_delta": float(deltas.mean()) if primary_valid_count else None,
            "mean_event_sensitive_delta": (
                float(ev_deltas.mean()) if len(ev_deltas) else None
            ),
            "mean_score_sensitive_delta": (
                float(sc_deltas.mean()) if len(sc_deltas) else None
            ),
            "worst_date": (
                str(subset.sort_values(
                    ["paired_delta_net_qqq_excess", "signal_date"]
                ).iloc[0].signal_date)
                if primary_valid_count else None
            ),
            "worst_date_delta": float(deltas.min()) if primary_valid_count else None,
            "research_effect": (
                "NO_EFFECT" if not group.n_topk_swaps.gt(0).any()
                else "MEMBERSHIP_CHANGE"
            ),
            "economic_reference_met": (
                bool(deltas.mean() >= 0.005)
                if primary_valid_count and int(horizon) == 60 and int(cap) == 15
                else None
            ),
        }
        if candidate == "B0" and primary_valid_count:
            if any(abs(float(delta)) > 1e-10 for delta in deltas):
                raise ValueError("B0 self-comparison has non-zero return delta")
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["candidate_id", "horizon", "cap"]
    ).reset_index(drop=True)


def date_quality_report(paired: pd.DataFrame, *, primary_cap: int = 15,
                        primary_horizon: int = 60) -> dict[str, Any]:
    main = paired[
        (paired["cap"] == primary_cap) &
        (paired["horizon"] == primary_horizon)
    ]
    result: dict[str, Any] = {}
    for name, grp in main.groupby("candidate_id", sort=True):
        valid = grp[grp["primary_paired_valid"].map(_positive)]
        bottom = valid.sort_values(
            ["paired_delta_net_qqq_excess", "signal_date"],
            kind="mergesort",
        ).head(3)
        positive = valid[
            pd.to_numeric(valid.paired_delta_net_qqq_excess, errors="coerce") > 0
        ]
        result[name] = {
            "primary_valid_dates": int(len(valid)),
            "n_positive_delta_dates": int(len(positive)),
            "n_zero_effect_dates": int((valid.n_topk_swaps == 0).sum()),
            "bottom_three": [
                {
                    "signal_date": str(row.signal_date),
                    "delta_net_excess": float(row.paired_delta_net_qqq_excess),
                    "n_top15_swaps": int(row.n_topk_swaps),
                } for row in bottom.itertuples(index=False)
            ],
        }
    return result
