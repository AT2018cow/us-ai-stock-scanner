"""Shared attention policy: state-change alerts and the offense track.

Selection logic lives here rather than in the presentation layer (A01/R07):

- state-change alert selection (material downgrades that would otherwise be
  squeezed out of the compressed daily/weekly lists);
- the frozen growth-compounder offense-track eligibility/order rules;
- the daily Top-15 stability policy (N=1 entry, M=2 soft exit, M=1 hard damage).

Renderers consume the selected decisions; they never re-implement the
thresholds. All policies are versioned and recorded in snapshot manifests.
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
DAILY_ATTENTION_STABILITY_POLICY_VERSION = "confirm_1_2_safe_v1"
HARD_OVERBOUGHT_SMA50_FOR_RETENTION = 1.12
HARD_OVERBOUGHT_RET20_FOR_RETENTION = 0.15


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


def is_hard_damage_for_retention(decision: StockDecision) -> bool:
    """True when an incumbent must leave the daily list immediately (M=1).

    Hard damage is structural or an overextension breach: trend damage,
    insufficient entry data, Quality C/UNRATED, or a hard overbought reading
    (SMA50 band / 20d return). Such names never receive the soft-exit grace.
    """
    if decision.entry.state in {
        EntryState.TREND_DAMAGED,
        EntryState.INSUFFICIENT_DATA,
    }:
        return True
    if decision.quality.grade in {QualityGrade.C, QualityGrade.UNRATED}:
        return True
    price_to_sma50 = decision_metric_value(decision, "price_to_sma50")
    if (
        price_to_sma50 is not None
        and price_to_sma50 > HARD_OVERBOUGHT_SMA50_FOR_RETENTION
    ):
        return True
    return_20d = decision_metric_value(decision, "return_20d")
    if (
        return_20d is not None
        and return_20d > HARD_OVERBOUGHT_RET20_FOR_RETENTION
    ):
        return True
    return False


def is_soft_exit_grace_eligible(
    decision: StockDecision,
    previous_daily_symbols: Iterable[str],
) -> bool:
    """One-day grace hold for an incumbent that just left PRIORITY_REVIEW.

    The M=2 semantics rely on canonical history: on day 1 of a soft breach
    ``previous_action_state`` is still PRIORITY_REVIEW, so the name stays one
    more day; on day 2 that field is the (non-PRIORITY) state from day 1 and
    the name exits automatically. Hard damage always bypasses the grace.
    """
    incumbents = {
        str(symbol).strip().upper()
        for symbol in previous_daily_symbols
        if str(symbol).strip()
    }
    if decision.symbol not in incumbents:
        return False
    if decision.action_state is ActionState.PRIORITY_REVIEW:
        return False
    if decision.previous_action_state is not ActionState.PRIORITY_REVIEW:
        return False
    return not is_hard_damage_for_retention(decision)


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
