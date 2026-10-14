"""Frozen outcome-blind score-source uncertainty sidecar.

Never change stock membership, entry/quality scores, Action or forward
labels. Retrospective sensitivity masks are NOT data repairs and must
never be used to decide historical ranks.
"""
from __future__ import annotations

import pandas as pd


def score_source_flags(
    frozen_rows: pd.DataFrame,
    *,
    event_review: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build conservative date×symbol flags without any future-return fields.

    HEI: all dates marked class-scope uncertain (only 4 directly audited).
    Missing fundamental asof: conservative, already unrated by canonical v1.
    Severe audit-only share anomaly: only the EVENT DATE, not older signals.
    Every other company retains UNVERIFIED globally, but this focused
    score-source sensitivity flag does not assert their data are correct.
    """
    if not {"signal_date", "symbol", "fundamental_data_asof"}.issubset(frozen_rows):
        raise ValueError("score sidecar missing date/symbol/asof")
    data = frozen_rows[["signal_date", "symbol", "fundamental_data_asof"]].copy()
    data["signal_date"] = data["signal_date"].astype(str)
    data["symbol"] = data["symbol"].astype(str).str.strip().str.upper()
    if data[["signal_date", "symbol"]].duplicated().any() or data.symbol.eq("").any():
        raise ValueError("duplicate or blank date×symbol in score sidecar")
    data["hei_scope_uncertain"] = data.symbol.eq("HEI")
    data["hei_source_confirmed_date"] = (
        data["hei_scope_uncertain"]
        & data.signal_date.isin({
            "2023-12-29", "2024-12-31", "2025-08-29", "2025-12-31"
        })
    )
    data["missing_fundamental_asof"] = (
        data.fundamental_data_asof.isna()
        | data.fundamental_data_asof.astype(str).str.strip().isin(["", "nan", "NaT"])
    )
    data["severe_share_event_on_date"] = False
    if event_review is not None:
        required = {"symbol", "event_date", "severe_shares_change", "null_labels"}
        if not required.issubset(event_review):
            raise ValueError(f"event sidecar missing {sorted(required - set(event_review))}")
        events = event_review.copy()
        if events[["symbol", "event_date"]].duplicated().any():
            raise ValueError("duplicate original audit event date×symbol")
        is_severe = events["severe_shares_change"].astype(str).str.lower().eq("true")
        is_null = events["null_labels"].astype(str).str.lower().eq("true")
        incidents = {
            (str(d), str(s).strip().upper())
            for d, s in events.loc[is_severe & ~is_null, ["event_date", "symbol"]].itertuples(index=False, name=None)
        }
        data["severe_share_event_on_date"] = [
            (d, s) in incidents
            for d, s in data[["signal_date", "symbol"]].itertuples(index=False, name=None)
        ]
    data["score_source_uncertain"] = (
        data.hei_scope_uncertain | data.missing_fundamental_asof
        | data.severe_share_event_on_date
    )
    flags = data.drop(columns=["fundamental_data_asof"])
    return flags.sort_values(["signal_date", "symbol"], kind="mergesort").reset_index(drop=True)
