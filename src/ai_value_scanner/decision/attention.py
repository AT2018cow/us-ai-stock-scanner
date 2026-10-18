"""Shared attention policy: state-change alerts and the offense track.

Selection logic lives here rather than in the presentation layer (A01/R07):

- state-change alert selection (material downgrades that would otherwise be
  squeezed out of the compressed daily/weekly lists);
- the frozen growth-compounder offense-track eligibility/order rules.

Renderers consume the selected decisions; they never re-implement the
thresholds. Both policies are versioned and recorded in snapshot manifests.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
from typing import Any

from .model import ActionState, EntryState, QualityGrade, StockDecision

DEFAULT_ATTENTION_CAP = 15

OFFENSE_TRACK_POLICY_VERSION = "growth_compounder_offense_v1"
STATE_CHANGE_ALERTS_POLICY_VERSION = "state_change_alerts_v1"


_ACTION_RANK: dict[ActionState, int] = {
    ActionState.PRIORITY_REVIEW: 0,
    ActionState.WATCH_PULLBACK: 1,
    ActionState.WATCH_BREAKOUT: 2,
    ActionState.HOLD_MONITOR: 3,
    ActionState.AVOID: 4,
}


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def decision_metric_value(decision: StockDecision, metric: str) -> float | None:
    """First finite numeric evidence value for a metric across quality/entry."""
    for item in (
        *decision.quality.positives,
        *decision.quality.risks,
        *decision.entry.positives,
        *decision.entry.risks,
    ):
        if item.metric == metric:
            value = _as_float(item.value)
            if value is not None:
                return value
    return None


# ---------------------------------------------------------------------------
# State-change alerts (R07)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateChangeAlertSelection:
    alerts: tuple[StockDecision, ...]
    total: int
    truncated: bool


def downgrade_severity(decision: StockDecision) -> tuple[int, int]:
    """(action rank delta, quality rank delta); (0, 0) if not a downgrade."""
    previous = decision.previous_action_state
    if previous is None:
        return 0, 0
    action_delta = _ACTION_RANK.get(decision.action_state, 0) - _ACTION_RANK.get(
        previous, 0
    )
    return max(0, action_delta), 0


def is_material_downgrade(decision: StockDecision) -> bool:
    """A previously visible state that has worsened.

    New long-term-weak names (no previous state) are not alerts; unchanged
    names are not alerts. Material means the action rank worsened.
    """
    if decision.previous_action_state is None:
        return False
    action_delta, _ = downgrade_severity(decision)
    return action_delta > 0


def _alert_sort_key(decision: StockDecision) -> tuple[int, int, int, str]:
    action_delta, quality_delta = downgrade_severity(decision)
    return (
        -(action_delta + quality_delta),
        _ACTION_RANK.get(decision.action_state, 99),
        decision.priority,
        decision.symbol,
    )


def select_state_change_alerts(
    decisions: Iterable[StockDecision],
    *,
    exclude_symbols: Iterable[str] = (),
    cap: int = DEFAULT_ATTENTION_CAP,
) -> StateChangeAlertSelection:
    """Material downgrades not already visible in a compressed list.

    Deterministic ordering: severity, then current action rank, then the
    canonical decision priority, then symbol. ``total`` reports all eligible
    alerts so reports can state their own truncation explicitly.
    """
    excluded = {str(symbol) for symbol in exclude_symbols}
    eligible = [
        decision
        for decision in decisions
        if decision.symbol not in excluded and is_material_downgrade(decision)
    ]
    eligible.sort(key=_alert_sort_key)
    resolved_cap = max(1, int(cap))
    return StateChangeAlertSelection(
        alerts=tuple(eligible[:resolved_cap]),
        total=len(eligible),
        truncated=len(eligible) > resolved_cap,
    )


# ---------------------------------------------------------------------------
# Growth Compounder Leaders (Bull Offense Track) — A01
# ---------------------------------------------------------------------------

OFFENSE_COMPOUNDER_MIN_QUALITY_SCORE: float = 0.68
OFFENSE_COMPOUNDER_MIN_REV_YOY: float = 0.15
OFFENSE_COMPOUNDER_MIN_OCF_NI: float = 0.80
OFFENSE_COMPOUNDER_MIN_SMA200: float = 1.00
OFFENSE_COMPOUNDER_MAX_SMA200: float = 1.60
OFFENSE_COMPOUNDER_MIN_RS60: float = 0.0
OFFENSE_COMPOUNDER_PRE_EARNINGS_PENALTY: float = 0.06


def is_growth_compounder_offense_eligible(decision: StockDecision) -> bool:
    """Frozen 6-condition growth-compounder offense eligibility gate."""
    if decision.quality.grade not in {QualityGrade.A, QualityGrade.B}:
        return False
    if (
        decision.quality.score is None
        or float(decision.quality.score) < OFFENSE_COMPOUNDER_MIN_QUALITY_SCORE
    ):
        return False
    if any(
        item.code == "nonoperating_gain_inflation"
        for item in decision.quality.risks
    ):
        return False
    rev_yoy = decision_metric_value(decision, "revenue_yoy")
    if rev_yoy is None or rev_yoy < OFFENSE_COMPOUNDER_MIN_REV_YOY:
        return False
    ocf_ni = decision_metric_value(decision, "ocf_to_net_income")
    if ocf_ni is None or ocf_ni < OFFENSE_COMPOUNDER_MIN_OCF_NI:
        return False
    if decision.entry.state not in {
        EntryState.ENTRY_READY, EntryState.WATCH_PULLBACK,
    }:
        return False
    sma200 = decision_metric_value(decision, "price_to_sma200")
    if sma200 is None or not (
        OFFENSE_COMPOUNDER_MIN_SMA200 <= sma200 <= OFFENSE_COMPOUNDER_MAX_SMA200
    ):
        return False
    rs60 = decision_metric_value(decision, "relative_strength_60d_qqq")
    if rs60 is None or rs60 < OFFENSE_COMPOUNDER_MIN_RS60:
        return False
    return True


def growth_compounder_offense_order_key(
    decision: StockDecision,
) -> tuple[float, float, float, str]:
    """Descending offense score: quality + growth + RS60 minus pre-earnings."""
    q_score = float(decision.quality.score or 0.0)
    rev_yoy = decision_metric_value(decision, "revenue_yoy") or 0.0
    rs60 = decision_metric_value(decision, "relative_strength_60d_qqq") or 0.0
    penalty = (
        OFFENSE_COMPOUNDER_PRE_EARNINGS_PENALTY
        if any(
            item.code == "pre_earnings_window_risk"
            for item in decision.quality.risks
        )
        else 0.0
    )
    offense_score = (
        q_score
        + 0.50 * min(max(rev_yoy, 0.0), 1.0)
        + 0.50 * min(max(rs60, 0.0), 1.0)
        - penalty
    )
    e_score = float(decision.entry.score or 0.0)
    return (
        -round(offense_score, 6),
        -round(q_score, 6),
        -round(e_score, 6),
        decision.symbol,
    )


def select_growth_compounder_offense(
    decisions: Iterable[StockDecision],
    *,
    exclude_symbols: Iterable[str] = (),
    cap: int = 10,
) -> tuple[StockDecision, ...]:
    """Deterministic offense-track selection (A01): eligibility + order + cap."""
    excluded = {str(symbol) for symbol in exclude_symbols}
    eligible = (
        decision
        for decision in decisions
        if decision.symbol not in excluded
        and is_growth_compounder_offense_eligible(decision)
    )
    return tuple(
        sorted(eligible, key=growth_compounder_offense_order_key)[
            : max(1, int(cap))
        ]
    )
