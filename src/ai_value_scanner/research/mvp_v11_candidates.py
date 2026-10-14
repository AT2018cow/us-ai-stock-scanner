"""Outcome-blind historical B0/R/E candidate replay (not production opt-in).

Quality always originates from canonical StockDecision. Entry candidates
re-run the same canonical Entry algorithm with frozen threshold overrides,
then recompute Action, rationale, triggers and canonical priorities. Return
labels are excluded *before* scoring. This is monthly historical proxy only.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import pandas as pd

from ai_value_scanner.decision.action import map_action_state
from ai_value_scanner.decision.entry import build_entry_quality_v11_offline
from ai_value_scanner.decision.integrated import (
    _rationale,
    _review_trigger,
    build_stock_decisions,
)
from ai_value_scanner.decision.model import StockDecision
from ai_value_scanner.research.mvp_v11 import R_CANDIDATES, rank_offline


# Only these pre-registered differences exist. All other Entry thresholds
# (e.g., READY return_20d <= 0.12 and defensive RS >= 0.05) stay canonical.
E_CANDIDATES = {
    "E1": (0.0, 0.15),
    "E2": (0.03, 0.15),
    "E3": (-0.03, 0.12),
    "E4": (-0.03, 0.18),
}
# Outcomes are never a candidate scoring input, even when present in v3.
# Exposure labels/continuity flags likewise may not affect selection.
FORBIDDEN_PREFIXES = (
    "fwd_", "qqq_return_", "forward_", "label_end_", "mae_", "mfe_",
    "equity_discontinuity_", "split_label_", "event_interval_",
)
FORBIDDEN_EXACT = frozenset({
    "future_return", "forward_excess", "label_valid",
    "future_event_mask", "realized_return", "return_label",
})


def scoring_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Create isolated scoring view without any future return/label inputs."""
    forbidden = [
        col for col in frame.columns
        if col.startswith(FORBIDDEN_PREFIXES) or col in FORBIDDEN_EXACT
    ]
    return frame.drop(columns=forbidden).copy()


def _iso(x: object) -> str | None:
    if x is None or pd.isna(x):
        return None
    token = str(x).strip()
    return token if token and token.lower() != "nan" else None


def replay_candidate_day(
    frame: pd.DataFrame,
    *,
    signal_date: str,
    candidate_id: str,
    baseline: Iterable[StockDecision] | None = None,
) -> tuple[StockDecision, ...]:
    """Recalculate exactly ONE month's canonical decision/Entry candidate.

    A supplied baseline must match every date×symbol in the unmodified input.
    Historical state migrations are a *comparison with B0*, not evidence
    of previous-day state transitions in the production Daily/Weekly product.
    """
    if candidate_id not in {"B0", *R_CANDIDATES, *E_CANDIDATES}:
        raise ValueError(f"unregistered candidate: {candidate_id}")
    if frame.empty or "symbol" not in frame or "signal_date" not in frame:
        raise ValueError("missing date×symbol history")
    if frame["signal_date"].astype(str).nunique() != 1:
        raise ValueError("run each historical signal date separately")
    if str(frame["signal_date"].iloc[0]) != signal_date:
        raise ValueError("signal_date does not match frame")
    data = scoring_features(frame)
    keys = data["symbol"].astype(str).str.strip().str.upper()
    if not keys.ne("").all() or keys.duplicated().any():
        raise ValueError("blank or duplicate normalized symbols")
    base = tuple(baseline) if baseline is not None else build_stock_decisions(
        data, decision_date=signal_date,
        generated_at_utc=f"{signal_date}T23:59:59+00:00",
    )
    if (
        len(base) != len(data)
        or {(d.decision_date, d.symbol) for d in base}
        != {(signal_date, sym) for sym in keys}
    ):
        raise ValueError("baseline date×symbol keys do not match frozen row keys")
    if candidate_id == "B0":
        return rank_offline(base, candidate_id="B0")
    if candidate_id in R_CANDIDATES:
        return rank_offline(base, candidate_id=candidate_id)

    ready_rs, overextended = E_CANDIDATES[candidate_id]
    by_symbol = {d.symbol: d for d in base}
    changes: list[StockDecision] = []
    for _, row in data.iterrows():
        sym = str(row["symbol"]).strip().upper()
        original = by_symbol[sym]
        entry = build_entry_quality_v11_offline(
            row, decision_date=signal_date,
            market_asof=_iso(row.get("market_asof")),
            ready_rs60_min=ready_rs,
            overextended_return20_gt=overextended,
        )
        if (entry.score, entry.confidence) != (
            original.entry.score, original.entry.confidence
        ):
            raise ValueError("E candidate must not alter Entry score or confidence")
        action = map_action_state(original.quality.grade, entry.state)
        candidate_provenance = dict(original.provenance)
        candidate_provenance["entry_policy_version"] = (
            f"entry_quality_v11_offline_{candidate_id}"
        )
        changes.append(replace(
            original, entry=entry, action_state=action,
            priority=0,
            rationale=_rationale(
                quality_positives=original.quality.positives,
                quality_risks=original.quality.risks,
                quality_missing=original.quality.missing,
                entry_positives=entry.positives,
                entry_risks=entry.risks,
            ),
            review_trigger=_review_trigger(action),
            state_change_reason=None,
            provenance=candidate_provenance,
        ))
    return rank_offline(changes, candidate_id="B0")


def migration_rows(
    baseline: Iterable[StockDecision],
    candidate: Iterable[StockDecision],
    *,
    candidate_id: str,
) -> list[dict[str, object]]:
    """Per-row B0 versus candidate migration, including changed explanation."""
    old, new = {d.symbol: d for d in baseline}, {d.symbol: d for d in candidate}
    if set(old) != set(new):
        raise ValueError("migration comparison needs the same fixed universe")
    if {d.decision_date for d in old.values()} != {d.decision_date for d in new.values()}:
        raise ValueError("mismatched signal dates")
    rows = []
    for sym in sorted(old):
        a, b = old[sym], new[sym]
        rows.append({
            "candidate_id": candidate_id,
            "signal_date": a.decision_date,
            "symbol": sym,
            "b0_priority": a.priority,
            "candidate_priority": b.priority,
            "b0_quality_grade": a.quality.grade.value,
            "candidate_quality_grade": b.quality.grade.value,
            "b0_entry_state": a.entry.state.value,
            "candidate_entry_state": b.entry.state.value,
            "b0_action_state": a.action_state.value,
            "candidate_action_state": b.action_state.value,
            "entry_state_changed": a.entry.state != b.entry.state,
            "action_changed": a.action_state != b.action_state,
            "priority_changed": a.priority != b.priority,
            "entry_score_unchanged": a.entry.score == b.entry.score,
            "b0_entry_evidence_codes": ",".join(
                e.code for e in (*a.entry.positives, *a.entry.risks)
            ),
            "candidate_entry_evidence_codes": ",".join(
                e.code for e in (*b.entry.positives, *b.entry.risks)
            ),
        })
    return rows
