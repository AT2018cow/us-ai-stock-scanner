from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from typing import Any

import pandas as pd

from .action import map_action_state
from .entry import ENTRY_POLICY_VERSION, build_entry_quality_v1
from .model import (
    DECISION_SCHEMA_VERSION,
    ActionState,
    EvidenceItem,
    QualityGrade,
    StockDecision,
)
from .quality import QUALITY_POLICY_VERSION, build_company_quality_v1


DEFAULT_ATTENTION_CAP = 15

_ACTION_ORDER = {
    ActionState.PRIORITY_REVIEW: 0,
    ActionState.WATCH_PULLBACK: 1,
    ActionState.WATCH_BREAKOUT: 2,
    ActionState.HOLD_MONITOR: 3,
    ActionState.AVOID: 4,
}

_QUALITY_ORDER = {
    QualityGrade.A: 0,
    QualityGrade.B: 1,
    QualityGrade.C: 2,
    QualityGrade.UNRATED: 3,
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    if not token or token.lower() == "nan":
        return None
    return token


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def build_source_list_membership(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, tuple[str, ...]]:
    """Build deterministic compatibility-list provenance without affecting decisions."""
    by_symbol: dict[str, set[str]] = {}
    for list_name, frame in frames.items():
        if frame is None or frame.empty or "symbol" not in frame.columns:
            continue
        for symbol in frame["symbol"].dropna().astype(str):
            token = symbol.strip().upper()
            if token:
                by_symbol.setdefault(token, set()).add(str(list_name))
    return {
        symbol: tuple(sorted(names))
        for symbol, names in sorted(by_symbol.items())
    }


def _dedupe_evidence(items: Iterable[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    seen: set[str] = set()
    out: list[EvidenceItem] = []
    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        out.append(item)
    return tuple(out)


def _rationale(
    *,
    quality_positives: tuple[EvidenceItem, ...],
    quality_risks: tuple[EvidenceItem, ...],
    quality_missing: tuple[EvidenceItem, ...],
    entry_positives: tuple[EvidenceItem, ...],
    entry_risks: tuple[EvidenceItem, ...],
) -> tuple[EvidenceItem, ...]:
    """Compress canonical evidence to 2–4 positives and 1–3 counter-signals."""
    positive_candidates = [
        item
        for item in (*quality_positives, *entry_positives)
        if item.code not in {"fundamental_data_fresh", "market_data_fresh"}
    ]
    if len(positive_candidates) < 2:
        positive_candidates.extend(
            item
            for item in (*quality_positives, *entry_positives)
            if item not in positive_candidates
        )

    risk_candidates = [
        item
        for item in (*quality_risks, *entry_risks, *quality_missing)
        if item.code not in {"fundamental_data_fresh", "market_data_fresh"}
    ]

    positives = _dedupe_evidence(positive_candidates)[:4]
    risks = _dedupe_evidence(risk_candidates)[:3]
    return _dedupe_evidence((*positives, *risks))


def _review_trigger(action: ActionState) -> str:
    if action is ActionState.PRIORITY_REVIEW:
        return (
            "Review now; downgrade if Company Quality falls below A or "
            "Entry Quality leaves ENTRY_READY."
        )
    if action is ActionState.WATCH_PULLBACK:
        return (
            "Re-review when price normalizes toward the SMA50 readiness band "
            "without long-term trend damage."
        )
    if action is ActionState.WATCH_BREAKOUT:
        return (
            "Re-review when market structure confirms ENTRY_READY or "
            "deteriorates into TREND_DAMAGED."
        )
    if action is ActionState.HOLD_MONITOR:
        return (
            "Re-review on a Quality or Entry state change; prioritize only if "
            "Quality A reaches ENTRY_READY."
        )
    return (
        "Re-review after stale/missing evidence clears or Quality/Entry "
        "materially improves."
    )


def _state_change_reason(
    previous: StockDecision | None,
    *,
    quality_grade: QualityGrade,
    entry_state: Any,
    action_state: ActionState,
) -> str | None:
    if previous is None:
        return "New prospective decision snapshot."

    changes: list[str] = []
    if previous.quality.grade is not quality_grade:
        changes.append(
            f"Company Quality {previous.quality.grade.value}→{quality_grade.value}"
        )
    if previous.entry.state is not entry_state:
        changes.append(
            f"Entry Quality {previous.entry.state.value}→{entry_state.value}"
        )
    if previous.action_state is not action_state:
        changes.append(
            f"Action {previous.action_state.value}→{action_state.value}"
        )
    if not changes:
        return None
    return "; ".join(changes) + "."


def _priority_sort_key(decision: StockDecision) -> tuple[Any, ...]:
    quality_score = decision.quality.score
    entry_score = decision.entry.score
    return (
        _ACTION_ORDER[decision.action_state],
        _QUALITY_ORDER[decision.quality.grade],
        -(quality_score if quality_score is not None else -1.0),
        -(entry_score if entry_score is not None else -1.0),
        -float(decision.quality.confidence),
        -float(decision.entry.confidence),
        decision.symbol,
    )


def build_stock_decisions(
    frame: pd.DataFrame,
    *,
    decision_date: str | date,
    generated_at_utc: str,
    previous_by_symbol: Mapping[str, StockDecision] | None = None,
    source_lists_by_symbol: Mapping[str, tuple[str, ...]] | None = None,
    run_provenance: Mapping[str, str | int | float | bool | None] | None = None,
) -> tuple[StockDecision, ...]:
    """Build one canonical StockDecision per enriched scanner row."""
    previous_map = previous_by_symbol or {}
    source_map = source_lists_by_symbol or {}
    base_provenance = dict(run_provenance or {})
    decision_day = (
        decision_date.isoformat() if isinstance(decision_date, date) else str(decision_date)
    )

    provisional: list[StockDecision] = []
    for _, row in frame.iterrows():
        symbol = str(row.get("symbol", "") or "").strip().upper()
        if not symbol:
            continue

        quality = build_company_quality_v1(
            row,
            decision_date=decision_day,
            data_asof=_text(row.get("fundamental_data_asof")),
        )
        entry = build_entry_quality_v1(
            row,
            decision_date=decision_day,
            market_asof=_text(row.get("market_asof")),
        )
        action = map_action_state(quality.grade, entry.state)
        previous = previous_map.get(symbol)

        provenance = dict(base_provenance)
        provenance.update(
            {
                "quality_policy_version": QUALITY_POLICY_VERSION,
                "entry_policy_version": ENTRY_POLICY_VERSION,
            }
        )
        for key in ("watchlist_bucket", "watchlist_etfs"):
            value = _text(row.get(key))
            if value is not None:
                provenance[key] = value
        etf_count = _number(row.get("watchlist_etf_count"))
        if etf_count is not None:
            provenance["watchlist_etf_count"] = int(etf_count)

        provisional.append(
            StockDecision(
                schema_version=DECISION_SCHEMA_VERSION,
                symbol=symbol,
                company_name=_text(row.get("company_name") or row.get("name")),
                decision_date=decision_day,
                generated_at_utc=str(generated_at_utc),
                quality=quality,
                entry=entry,
                action_state=action,
                priority=0,
                rationale=_rationale(
                    quality_positives=quality.positives,
                    quality_risks=quality.risks,
                    quality_missing=quality.missing,
                    entry_positives=entry.positives,
                    entry_risks=entry.risks,
                ),
                review_trigger=_review_trigger(action),
                source_lists=tuple(source_map.get(symbol, ())),
                provenance=provenance,
                previous_action_state=(
                    previous.action_state if previous is not None else None
                ),
                state_change_reason=_state_change_reason(
                    previous,
                    quality_grade=quality.grade,
                    entry_state=entry.state,
                    action_state=action,
                ),
            )
        )

    ordered = sorted(provisional, key=_priority_sort_key)
    return tuple(
        replace(decision, priority=index)
        for index, decision in enumerate(ordered, start=1)
    )


def select_weekly_attention(
    decisions: Iterable[StockDecision],
    *,
    cap: int = DEFAULT_ATTENTION_CAP,
) -> tuple[StockDecision, ...]:
    """Weekly list: current actionable/watch states plus explicit downgrades to AVOID."""
    ordered = sorted(tuple(decisions), key=lambda d: (d.priority, d.symbol))
    selected = [
        decision
        for decision in ordered
        if decision.action_state is not ActionState.AVOID
        or (
            decision.previous_action_state is not None
            and decision.previous_action_state is not ActionState.AVOID
        )
    ]
    return tuple(selected[: max(1, int(cap))])


def select_daily_attention(
    decisions: Iterable[StockDecision],
    *,
    cap: int = DEFAULT_ATTENTION_CAP,
) -> tuple[StockDecision, ...]:
    """Daily list emphasizes state changes while keeping current priority reviews visible."""
    ordered = sorted(tuple(decisions), key=lambda d: (d.priority, d.symbol))
    has_history = any(d.previous_action_state is not None for d in ordered)
    if not has_history:
        return select_weekly_attention(ordered, cap=cap)

    selected = [
        decision
        for decision in ordered
        if decision.action_state is ActionState.PRIORITY_REVIEW
        or decision.state_change_reason is not None
    ]
    return tuple(selected[: max(1, int(cap))])


def decisions_by_symbol(
    decisions: Iterable[StockDecision],
) -> dict[str, StockDecision]:
    return {decision.symbol: decision for decision in decisions}
