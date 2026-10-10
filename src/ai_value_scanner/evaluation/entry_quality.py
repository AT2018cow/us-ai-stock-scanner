from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.decision.entry import (
    ENTRY_POLICY_VERSION,
    build_entry_quality_v1,
)
from ai_value_scanner.decision.model import EntryState
from ai_value_scanner.evaluation.company_quality import apply_company_quality_v1


ENTRY_DECISION_COLUMNS = (
    "entry_policy_version",
    "entry_state",
    "entry_score",
    "entry_confidence",
    "entry_positive_codes",
    "entry_risk_codes",
    "entry_market_asof",
)


def _codes(items: Iterable[Any]) -> str:
    return ",".join(item.code for item in items)


def validate_entry_replay_frame(
    frame: pd.DataFrame,
    *,
    decision_date_col: str = "signal_date",
    market_asof_col: str = "market_asof",
) -> None:
    required = {"symbol", decision_date_col, market_asof_col}
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise ValueError(
            f"entry replay dataset missing required columns: {missing_columns}"
        )

    decision_dates = pd.to_datetime(frame[decision_date_col], errors="coerce")
    market_dates = pd.to_datetime(frame[market_asof_col], errors="coerce")
    future_mask = market_dates.notna() & decision_dates.notna() & (
        market_dates > decision_dates
    )
    if future_mask.any():
        example = frame.loc[
            future_mask,
            ["symbol", decision_date_col, market_asof_col],
        ].iloc[0]
        raise ValueError(
            "entry replay contains future market data: "
            f"symbol={example['symbol']} "
            f"decision_date={example[decision_date_col]} "
            f"market_asof={example[market_asof_col]}"
        )


def apply_entry_quality_v1(
    frame: pd.DataFrame,
    *,
    decision_date_col: str = "signal_date",
    market_asof_col: str = "market_asof",
) -> pd.DataFrame:
    """Attach deterministic Entry Quality v1 decisions to a market feature frame."""
    validate_entry_replay_frame(
        frame,
        decision_date_col=decision_date_col,
        market_asof_col=market_asof_col,
    )
    out = frame.copy()
    if out.empty:
        for column in ENTRY_DECISION_COLUMNS:
            out[column] = pd.Series(dtype="object")
        return out

    records: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        decision = build_entry_quality_v1(
            row,
            decision_date=row.get(decision_date_col),
            market_asof=row.get(market_asof_col),
        )
        records.append(
            {
                "entry_policy_version": ENTRY_POLICY_VERSION,
                "entry_state": decision.state.value,
                "entry_score": decision.score,
                "entry_confidence": decision.confidence,
                "entry_positive_codes": _codes(decision.positives),
                "entry_risk_codes": _codes(decision.risks),
                "entry_market_asof": decision.market_asof,
            }
        )

    decisions = pd.DataFrame(records, index=out.index)
    for column in ENTRY_DECISION_COLUMNS:
        out[column] = decisions[column]
    return out


def build_entry_quality_evaluation_frame(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Apply Company Quality first, then evaluate Entry only for A/B companies."""
    quality_frame = apply_company_quality_v1(frame)
    eligible = quality_frame[
        quality_frame["quality_grade"].isin({"A", "B"})
    ].copy()
    if eligible.empty:
        return apply_entry_quality_v1(eligible)
    return apply_entry_quality_v1(eligible)


def _state_cohort_row(
    subset: pd.DataFrame,
    *,
    state: str,
    horizon: int,
    segment_type: str,
    segment: str,
) -> dict[str, Any]:
    ret_col = f"fwd_ret_{horizon}"
    qqq_col = f"qqq_return_{horizon}"
    if ret_col in subset.columns:
        returns = pd.to_numeric(subset[ret_col], errors="coerce")
    else:
        returns = pd.Series(np.nan, index=subset.index, dtype="float64")
    if qqq_col in subset.columns:
        qqq = pd.to_numeric(subset[qqq_col], errors="coerce")
    else:
        qqq = pd.Series(np.nan, index=subset.index, dtype="float64")

    valid_return = returns.notna()
    excess = returns - qqq
    valid_excess = excess.notna()

    per_date_ret = pd.Series(dtype="float64")
    per_date_excess = pd.Series(dtype="float64")
    if "signal_date" in subset.columns:
        temp = pd.DataFrame(
            {
                "signal_date": subset["signal_date"].astype(str),
                "ret": returns,
                "excess": excess,
            },
            index=subset.index,
        )
        per_date_ret = (
            temp.loc[temp["ret"].notna()]
            .groupby("signal_date")["ret"]
            .mean()
        )
        per_date_excess = (
            temp.loc[temp["excess"].notna()]
            .groupby("signal_date")["excess"]
            .mean()
        )

    worst_date_return = np.nan
    worst_date_return_date = ""
    if not per_date_ret.empty:
        worst_date_return_date = str(per_date_ret.idxmin())
        worst_date_return = float(per_date_ret.min())

    worst_date_excess = np.nan
    worst_date_excess_date = ""
    if not per_date_excess.empty:
        worst_date_excess_date = str(per_date_excess.idxmin())
        worst_date_excess = float(per_date_excess.min())

    return {
        "segment_type": segment_type,
        "segment": segment,
        "entry_state": state,
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
            float(returns[valid_return].median()) if valid_return.any() else np.nan
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
            float(excess[valid_excess].median()) if valid_excess.any() else np.nan
        ),
        "excess_hit_rate": (
            float((excess[valid_excess] > 0).mean())
            if valid_excess.any()
            else np.nan
        ),
        "date_equal_weight_mean_return": (
            float(per_date_ret.mean()) if not per_date_ret.empty else np.nan
        ),
        "date_equal_weight_mean_excess_vs_qqq": (
            float(per_date_excess.mean()) if not per_date_excess.empty else np.nan
        ),
        "worst_date_mean_return": worst_date_return,
        "worst_date_mean_return_date": worst_date_return_date,
        "worst_date_mean_excess_vs_qqq": worst_date_excess,
        "worst_date_mean_excess_date": worst_date_excess_date,
    }


def summarize_entry_state_cohorts(
    frame: pd.DataFrame,
    *,
    horizons: Iterable[int] = (20, 60, 120),
) -> pd.DataFrame:
    if "entry_state" not in frame.columns:
        raise ValueError(
            "entry_state is required; call build_entry_quality_evaluation_frame first"
        )

    work = frame.copy()
    if "signal_date" in work.columns:
        work["signal_year"] = pd.to_datetime(
            work["signal_date"],
            errors="coerce",
        ).dt.year.astype("Int64")

    rows: list[dict[str, Any]] = []
    states = [state.value for state in EntryState]

    def append_scope(scope: pd.DataFrame, segment_type: str, segment: str) -> None:
        for state in states:
            state_rows = scope[scope["entry_state"] == state]
            if state_rows.empty:
                continue
            for horizon in horizons:
                rows.append(
                    _state_cohort_row(
                        state_rows,
                        state=state,
                        horizon=int(horizon),
                        segment_type=segment_type,
                        segment=segment,
                    )
                )

    append_scope(work, "overall", "all")

    if "signal_year" in work.columns:
        for year in sorted(x for x in work["signal_year"].dropna().unique()):
            append_scope(
                work[work["signal_year"] == year],
                "year",
                str(int(year)),
            )

    if "regime" in work.columns:
        for regime in sorted(str(x) for x in work["regime"].dropna().unique()):
            append_scope(
                work[work["regime"].astype(str) == regime],
                "regime",
                regime,
            )

    if "quality_grade" in work.columns:
        for grade in ("A", "B"):
            append_scope(
                work[work["quality_grade"] == grade],
                "quality_grade",
                grade,
            )

    return pd.DataFrame(rows)


def summarize_entry_state_concentration(frame: pd.DataFrame) -> pd.DataFrame:
    if "entry_state" not in frame.columns:
        raise ValueError("entry_state is required")

    rows: list[dict[str, Any]] = []
    for state in [state.value for state in EntryState]:
        subset = frame[frame["entry_state"] == state]
        if subset.empty:
            continue
        symbol_counts = subset["symbol"].astype(str).value_counts()
        date_counts = subset["signal_date"].astype(str).value_counts()
        total = float(len(subset))
        rows.append(
            {
                "entry_state": state,
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
                "top_date": (
                    str(date_counts.index[0]) if not date_counts.empty else ""
                ),
                "top_date_share": (
                    float(date_counts.iloc[0] / total)
                    if not date_counts.empty
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _entry_transition_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "signal_date", "entry_state"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"entry transition frame missing columns: {missing}")
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "from_state",
                "to_state",
                "from_date",
                "to_date",
                "gap_days",
            ]
        )

    work = frame.loc[:, ["symbol", "signal_date", "entry_state"]].copy()
    work["_signal_dt"] = pd.to_datetime(work["signal_date"], errors="coerce")
    work = work.dropna(subset=["_signal_dt"]).sort_values(
        ["symbol", "_signal_dt", "entry_state"]
    )
    work["_prev_state"] = work.groupby("symbol")["entry_state"].shift(1)
    work["_prev_dt"] = work.groupby("symbol")["_signal_dt"].shift(1)
    pairs = work.dropna(subset=["_prev_state", "_prev_dt"]).copy()
    if pairs.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "from_state",
                "to_state",
                "from_date",
                "to_date",
                "gap_days",
            ]
        )

    return pd.DataFrame(
        {
            "symbol": pairs["symbol"].astype(str),
            "from_state": pairs["_prev_state"].astype(str),
            "to_state": pairs["entry_state"].astype(str),
            "from_date": pairs["_prev_dt"].dt.date.astype(str),
            "to_date": pairs["_signal_dt"].dt.date.astype(str),
            "gap_days": (
                pairs["_signal_dt"] - pairs["_prev_dt"]
            ).dt.days.astype(int),
        }
    ).reset_index(drop=True)


def build_entry_state_transitions(frame: pd.DataFrame) -> pd.DataFrame:
    pairs = _entry_transition_pairs(frame)
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
        pairs.groupby(["from_state", "to_state"], dropna=False)
        .agg(
            n_transitions=("symbol", "size"),
            median_gap_days=("gap_days", "median"),
        )
        .reset_index()
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


def summarize_entry_state_persistence(frame: pd.DataFrame) -> pd.DataFrame:
    pairs = _entry_transition_pairs(frame)
    if pairs.empty:
        return pd.DataFrame(
            columns=[
                "from_state",
                "n_transitions",
                "same_state_rate",
                "median_gap_days",
            ]
        )

    rows: list[dict[str, Any]] = []
    for state, part in pairs.groupby("from_state", sort=True):
        n = int(len(part))
        same = int((part["to_state"] == state).sum())
        rows.append(
            {
                "from_state": str(state),
                "n_transitions": n,
                "same_state_rate": float(same / n) if n > 0 else np.nan,
                "median_gap_days": float(
                    pd.to_numeric(part["gap_days"], errors="coerce").median()
                ),
            }
        )

    total_n = int(len(pairs))
    total_same = int((pairs["from_state"] == pairs["to_state"]).sum())
    rows.append(
        {
            "from_state": "ALL",
            "n_transitions": total_n,
            "same_state_rate": (
                float(total_same / total_n) if total_n > 0 else np.nan
            ),
            "median_gap_days": float(
                pd.to_numeric(pairs["gap_days"], errors="coerce").median()
            ),
        }
    )
    return pd.DataFrame(rows)

def serialize_entry_evidence(frame: pd.DataFrame) -> pd.Series:
    """Compact deterministic evidence payload for downstream audit artifacts."""
    required = {
        "entry_positive_codes",
        "entry_risk_codes",
        "entry_market_asof",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"entry evidence frame missing columns: {missing}")

    return frame.apply(
        lambda row: json.dumps(
            {
                "positive_codes": [
                    code
                    for code in str(row.get("entry_positive_codes", "")).split(",")
                    if code
                ],
                "risk_codes": [
                    code
                    for code in str(row.get("entry_risk_codes", "")).split(",")
                    if code
                ],
                "market_asof": row.get("entry_market_asof"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        axis=1,
    )
