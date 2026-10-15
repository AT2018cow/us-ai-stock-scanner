from __future__ import annotations

from collections.abc import Iterable

from .model import (
    ActionState,
    EntryDecision,
    EntryState,
    QualityDecision,
    QualityGrade,
    StockDecision,
)


def map_action_state(
    quality_grade: QualityGrade | str,
    entry_state: EntryState | str,
) -> ActionState:
    """Map Company Quality × Entry Quality to the canonical MVP action state."""
    quality = QualityGrade(quality_grade)
    entry = EntryState(entry_state)

    if quality in {QualityGrade.C, QualityGrade.UNRATED}:
        return ActionState.AVOID
    if entry is EntryState.INSUFFICIENT_DATA:
        return ActionState.AVOID

    if quality is QualityGrade.B:
        return ActionState.HOLD_MONITOR

    if entry is EntryState.ENTRY_READY:
        return ActionState.PRIORITY_REVIEW
    if entry is EntryState.WATCH_PULLBACK:
        return ActionState.WATCH_PULLBACK
    if entry is EntryState.WATCH_BREAKOUT:
        return ActionState.WATCH_BREAKOUT
    if entry is EntryState.TREND_DAMAGED:
        return ActionState.HOLD_MONITOR

    raise ValueError(f"unmapped Quality × Entry combination: {quality.value} × {entry.value}")


H3_B_MIN_QUALITY_SCORE = 0.68
H3_B_MIN_QUALITY_CONFIDENCE = 0.80
H3_READY_MIN_ENTRY_SCORE = 0.80

H3_PROMOTION_RATIONALE = (
    "High-conviction Company Quality B (score >= 0.68, confidence >= 0.80) "
    "with confirmed Entry Ready setup qualifies for Priority Review."
)

H3_JOINT_QUALITY_WEIGHT = 0.60
H3_JOINT_ENTRY_WEIGHT = 0.40
H3_GRADE_A_BONUS = 0.04


def _joint_conviction_score(quality: QualityDecision, entry: EntryDecision) -> float:
    """H3 joint composite: 0.60*quality + 0.40*entry (+0.04 Grade-A bonus in PR)."""
    quality_score = quality.score if quality.score is not None else 0.0
    entry_score = entry.score if entry.score is not None else 0.0
    return (
        H3_JOINT_QUALITY_WEIGHT * float(quality_score)
        + H3_JOINT_ENTRY_WEIGHT * float(entry_score)
    )


def map_action_state_v2(
    quality: QualityDecision,
    entry: EntryDecision,
) -> tuple[ActionState, list[str]]:
    """Map Quality x Entry to the H3 candidate action state + rationale.

    Identical to v1 except one pre-registered rule: high-conviction
    Quality B (score >= 0.68, confidence >= 0.80) with a confirmed
    ENTRY_READY (score >= 0.80) setup promotes to PRIORITY_REVIEW.
    """
    base = map_action_state(quality.grade, entry.state)
    if (
        quality.grade is QualityGrade.B
        and (quality.score or 0.0) >= H3_B_MIN_QUALITY_SCORE
        and quality.confidence >= H3_B_MIN_QUALITY_CONFIDENCE
        and entry.state is EntryState.ENTRY_READY
        and (entry.score or 0.0) >= H3_READY_MIN_ENTRY_SCORE
    ):
        return ActionState.PRIORITY_REVIEW, [H3_PROMOTION_RATIONALE]
    return base, []


def assign_action_priorities_v2(
    decisions: Iterable[StockDecision],
) -> list[StockDecision]:
    """Rank decisions under H3: joint composite inside action states.

    PRIORITY_REVIEW ranks by descending joint score with a +0.04 Grade-A
    bonus; HOLD_MONITOR ranks remaining ENTRY_READY ahead of TREND_DAMAGED,
    then by joint score; all other states rank by quality grade, then joint
    score, then symbol (deterministic).
    """
    from dataclasses import replace

    def _sort_key(decision: StockDecision) -> tuple:
        joint = _joint_conviction_score(decision.quality, decision.entry)
        action_order = _ACTION_ORDER_V2[decision.action_state]
        if decision.action_state is ActionState.PRIORITY_REVIEW:
            bonus = H3_GRADE_A_BONUS if decision.quality.grade is QualityGrade.A else 0.0
            return (action_order, -(joint + bonus), decision.symbol)
        if decision.action_state is ActionState.HOLD_MONITOR:
            ready_first = 0 if decision.entry.state is EntryState.ENTRY_READY else 1
            return (action_order, ready_first, -joint, decision.symbol)
        return (
            action_order,
            _QUALITY_ORDER_V2[decision.quality.grade],
            -joint,
            decision.symbol,
        )

    ordered = sorted(decisions, key=_sort_key)
    return [
        replace(decision, priority=index)
        for index, decision in enumerate(ordered, start=1)
    ]


_ACTION_ORDER_V2 = {
    ActionState.PRIORITY_REVIEW: 0,
    ActionState.WATCH_PULLBACK: 1,
    ActionState.WATCH_BREAKOUT: 2,
    ActionState.HOLD_MONITOR: 3,
    ActionState.AVOID: 4,
}

_QUALITY_ORDER_V2 = {
    QualityGrade.A: 0,
    QualityGrade.B: 1,
    QualityGrade.C: 2,
    QualityGrade.UNRATED: 3,
}
