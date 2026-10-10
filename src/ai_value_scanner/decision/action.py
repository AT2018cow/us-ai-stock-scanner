from __future__ import annotations

from .model import ActionState, EntryState, QualityGrade


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
