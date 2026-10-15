from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import math
from typing import Any

from .model import EntryDecision, EntryState, EvidenceItem


ENTRY_POLICY_VERSION = "entry_quality_v1_2026-10-10"

ENTRY_V1_COMPONENT_WEIGHTS: dict[str, float] = {
    "trend": 0.35,
    "momentum": 0.25,
    "relative_strength": 0.20,
    "location": 0.20,
}

ENTRY_V1_CRITICAL_METRICS = (
    "price_to_sma200",
    "price_to_sma50",
    "return_20d",
    "return_60d",
    "drawdown_from_52w_high",
    "relative_strength_60d_qqq",
)

ENTRY_V1_MIN_CRITICAL_OBSERVED = 5
ENTRY_V1_MARKET_FRESH_DAYS = 3
ENTRY_V1_MARKET_STALE_MAX_DAYS = 7


def _finite_value(metrics: Mapping[str, Any], key: str) -> float | None:
    raw = metrics.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _parse_iso_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    token = str(value).strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token[:10])
    except ValueError:
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"true", "1", "yes"}:
        return True
    if token in {"false", "0", "no"}:
        return False
    return None


def _item(
    *,
    code: str,
    label: str,
    polarity: str,
    metric: str | None,
    value: float | str | None,
    threshold: float | str | None,
    message: str,
) -> EvidenceItem:
    return EvidenceItem(
        code=code,
        label=label,
        polarity=polarity,  # type: ignore[arg-type]
        metric=metric,
        value=value,
        threshold=threshold,
        message=message,
    )


def _component(
    scores: list[float | None],
) -> tuple[float | None, float]:
    observed = [float(score) for score in scores if score is not None]
    coverage = len(observed) / float(len(scores)) if scores else 0.0
    if not observed:
        return None, coverage
    return sum(observed) / len(observed), coverage


def _score_sma200(value: float) -> float:
    if value >= 1.05:
        return 1.0
    if value >= 1.00:
        return 0.90
    if value >= 0.95:
        return 0.50
    return 0.0


def _score_sma50(value: float) -> float:
    if 0.98 <= value <= 1.08:
        return 1.0
    if 0.95 <= value <= 1.10:
        return 0.60
    if 0.92 <= value <= 1.15:
        return 0.30
    return 0.0


def _score_days_below_sma200(value: float) -> float:
    if value <= 0:
        return 1.0
    if value <= 5:
        return 0.80
    if value < 15:
        return 0.40
    return 0.0


def _score_return_20d(value: float) -> float:
    if -0.03 <= value <= 0.12:
        return 1.0
    if -0.08 <= value <= 0.15:
        return 0.60
    return 0.20


def _score_return_60d(value: float) -> float:
    if value >= 0.10:
        return 1.0
    if value >= 0.0:
        return 0.80
    if value >= -0.08:
        return 0.40
    return 0.10


def _score_relative_strength(value: float) -> float:
    if value >= 0.05:
        return 1.0
    if value >= -0.03:
        return 0.75
    if value >= -0.10:
        return 0.40
    return 0.0


def _score_drawdown(value: float) -> float:
    if 0.03 <= value <= 0.18:
        return 1.0
    if 0.0 <= value <= 0.22:
        return 0.75
    if value <= 0.30:
        return 0.45
    return 0.10


def _score_range_position(value: float) -> float:
    if 0.50 <= value <= 0.90:
        return 1.0
    if 0.30 <= value < 0.50:
        return 0.60
    if 0.90 < value <= 0.95:
        return 0.70
    if value > 0.95:
        return 0.35
    return 0.25


def _entry_score_and_confidence(
    metrics: Mapping[str, Any],
) -> tuple[float, float]:
    component_inputs = {
        "trend": [
            None
            if _finite_value(metrics, "price_to_sma200") is None
            else _score_sma200(float(_finite_value(metrics, "price_to_sma200"))),
            None
            if _finite_value(metrics, "price_to_sma50") is None
            else _score_sma50(float(_finite_value(metrics, "price_to_sma50"))),
            None
            if _finite_value(metrics, "days_below_sma200") is None
            else _score_days_below_sma200(
                float(_finite_value(metrics, "days_below_sma200"))
            ),
        ],
        "momentum": [
            None
            if _finite_value(metrics, "return_20d") is None
            else _score_return_20d(float(_finite_value(metrics, "return_20d"))),
            None
            if _finite_value(metrics, "return_60d") is None
            else _score_return_60d(float(_finite_value(metrics, "return_60d"))),
        ],
        "relative_strength": [
            None
            if _finite_value(metrics, "relative_strength_60d_qqq") is None
            else _score_relative_strength(
                float(_finite_value(metrics, "relative_strength_60d_qqq"))
            )
        ],
        "location": [
            None
            if _finite_value(metrics, "drawdown_from_52w_high") is None
            else _score_drawdown(
                float(_finite_value(metrics, "drawdown_from_52w_high"))
            ),
            None
            if _finite_value(metrics, "range_position_52w") is None
            else _score_range_position(
                float(_finite_value(metrics, "range_position_52w"))
            ),
        ],
    }

    effective_score = 0.0
    confidence = 0.0
    for name, values in component_inputs.items():
        score, coverage = _component(values)
        weight = ENTRY_V1_COMPONENT_WEIGHTS[name]
        confidence += weight * coverage
        if score is not None:
            effective_score += weight * score * coverage
    return (
        round(max(0.0, min(1.0, effective_score)), 6),
        round(max(0.0, min(1.0, confidence)), 6),
    )


def build_entry_quality_v1(
    metrics: Mapping[str, Any],
    *,
    decision_date: str | date | None = None,
    market_asof: str | date | None = None,
) -> EntryDecision:
    """Canonical v1 stays fixed; thresholds are NOT changed by research."""
    return _build_entry_with_thresholds(
        metrics, decision_date=decision_date, market_asof=market_asof,
        ready_rs60_min=-0.03, overextended_return20_gt=0.15,
    )


def build_entry_quality_v11_offline(
    metrics: Mapping[str, Any],
    *,
    decision_date: str | date | None,
    market_asof: str | date | None,
    ready_rs60_min: float,
    overextended_return20_gt: float,
) -> EntryDecision:
    """Research-only Entry state recomputation via the SAME canonical logic."""
    if ready_rs60_min not in (-0.03, 0.0, 0.03):
        raise ValueError("unregistered ready_rs60_min")
    if overextended_return20_gt not in (0.12, 0.15, 0.18):
        raise ValueError("unregistered overextended_return20_gt")
    if ready_rs60_min != -0.03 and overextended_return20_gt != 0.15:
        raise ValueError("non-registered E grid combination")
    return _build_entry_with_thresholds(
        metrics, decision_date=decision_date, market_asof=market_asof,
        ready_rs60_min=ready_rs60_min,
        overextended_return20_gt=overextended_return20_gt,
    )


def _build_entry_with_thresholds(
    metrics: Mapping[str, Any],
    *,
    decision_date: str | date | None,
    market_asof: str | date | None,
    ready_rs60_min: float,
    overextended_return20_gt: float,
) -> EntryDecision:
    """Shared canonical Entry algorithm: score fixed, state thresholds versioned."""
    positives: list[EvidenceItem] = []
    risks: list[EvidenceItem] = []

    score, confidence = _entry_score_and_confidence(metrics)

    market_asof_value = market_asof
    if market_asof_value is None:
        raw_market_asof = metrics.get("market_asof")
        market_asof_value = None if raw_market_asof is None else str(raw_market_asof)

    decision_dt = _parse_iso_date(decision_date)
    market_dt = _parse_iso_date(market_asof_value)
    normalized_market_asof = market_dt.isoformat() if market_dt is not None else None

    insufficient_reason = False
    if market_dt is None:
        insufficient_reason = True
        confidence = min(confidence, 0.49)
        risks.append(
            _item(
                code="market_asof_missing",
                label="Market as-of missing",
                polarity="missing",
                metric="market_asof",
                value=None,
                threshold="required",
                message="Market-data freshness cannot be verified.",
            )
        )
    elif decision_dt is not None:
        if market_dt > decision_dt:
            raise ValueError(
                f"market_asof {market_dt.isoformat()} is after "
                f"decision_date {decision_dt.isoformat()}"
            )
        age_days = (decision_dt - market_dt).days
        if age_days > ENTRY_V1_MARKET_STALE_MAX_DAYS:
            insufficient_reason = True
            confidence = min(confidence, 0.49)
            risks.append(
                _item(
                    code="market_data_severely_stale",
                    label="Market data severely stale",
                    polarity="negative",
                    metric="market_data_age_days",
                    value=age_days,
                    threshold=f"<={ENTRY_V1_MARKET_STALE_MAX_DAYS}",
                    message="Market data is too stale for an Entry state.",
                )
            )
        elif age_days > ENTRY_V1_MARKET_FRESH_DAYS:
            confidence *= 0.90
            risks.append(
                _item(
                    code="market_data_stale",
                    label="Market data stale",
                    polarity="negative",
                    metric="market_data_age_days",
                    value=age_days,
                    threshold=f"<={ENTRY_V1_MARKET_FRESH_DAYS}",
                    message="Market data is older than the preferred freshness window.",
                )
            )
        else:
            positives.append(
                _item(
                    code="market_data_fresh",
                    label="Market data fresh",
                    polarity="positive",
                    metric="market_data_age_days",
                    value=age_days,
                    threshold=f"<={ENTRY_V1_MARKET_FRESH_DAYS}",
                    message="Market data is within the preferred freshness window.",
                )
            )

    observed_critical = 0
    for key in ENTRY_V1_CRITICAL_METRICS:
        value = _finite_value(metrics, key)
        if value is None:
            risks.append(
                _item(
                    code=f"{key}_missing",
                    label=f"{key} missing",
                    polarity="missing",
                    metric=key,
                    value=None,
                    threshold="required for full Entry confidence",
                    message=f"{key} is unavailable and reduces Entry confidence.",
                )
            )
        else:
            observed_critical += 1

    sma200 = _finite_value(metrics, "price_to_sma200")
    sma50 = _finite_value(metrics, "price_to_sma50")
    return_20d = _finite_value(metrics, "return_20d")
    return_60d = _finite_value(metrics, "return_60d")
    drawdown = _finite_value(metrics, "drawdown_from_52w_high")
    range_position = _finite_value(metrics, "range_position_52w")
    relative_strength = _finite_value(metrics, "relative_strength_60d_qqq")
    volatility = _finite_value(metrics, "volatility_60d")
    days_below = _finite_value(metrics, "days_below_sma200")

    if (
        observed_critical < ENTRY_V1_MIN_CRITICAL_OBSERVED
        or sma200 is None
        or sma50 is None
    ):
        insufficient_reason = True
        confidence = min(confidence, 0.74)

    if sma200 is not None:
        target = ">=1.00 healthy; <0.95 damaged"
        if sma200 >= 1.0:
            positives.append(
                _item(
                    code="price_above_sma200",
                    label="Price above SMA200",
                    polarity="positive",
                    metric="price_to_sma200",
                    value=round(sma200, 6),
                    threshold=target,
                    message="Long-term price structure is above its 200-day average.",
                )
            )
        elif sma200 < 0.95:
            risks.append(
                _item(
                    code="price_materially_below_sma200",
                    label="Price materially below SMA200",
                    polarity="negative",
                    metric="price_to_sma200",
                    value=round(sma200, 6),
                    threshold=target,
                    message="Long-term price structure is materially damaged.",
                )
            )
    # M1 evidence completeness: the [0.95, 1.00) band blocks ENTRY_READY
    # (which requires sma200 >= 1.00) but previously emitted no EvidenceItem.
    if sma200 is not None and 0.95 <= sma200 < 1.00:
        risks.append(
            _item(
                code="price_below_sma200_trend",
                label="Price below SMA200",
                polarity="negative",
                metric="price_to_sma200",
                value=round(sma200, 6),
                threshold=">=1.00 for ENTRY_READY",
                message="Price is slightly below its 200-day average and does not confirm ENTRY_READY.",
            )
        )

    # M1 evidence completeness: days_below_sma200 >= 15 triggers TREND_DAMAGED
    # but previously emitted no EvidenceItem (ISRG archetype).
    if days_below is not None and days_below >= 15:
        days_value = float(days_below)
        risks.append(
            _item(
                code="days_below_sma200_elevated",
                label="Persistent days below SMA200",
                polarity="negative",
                metric="days_below_sma200",
                value=int(days_value) if days_value.is_integer() else round(days_value, 2),
                threshold="<15 days",
                message="Stock has spent 15 or more recent sessions below SMA200, flagging trend damage.",
            )
        )

    if sma50 is not None:
        if 0.98 <= sma50 <= 1.08:
            positives.append(
                _item(
                    code="price_near_sma50_ready_band",
                    label="Price near SMA50",
                    polarity="positive",
                    metric="price_to_sma50",
                    value=round(sma50, 6),
                    threshold="0.98–1.08",
                    message="Price is in the pre-registered SMA50 readiness band.",
                )
            )
        elif sma50 > 1.10:
            risks.append(
                _item(
                    code="price_extended_above_sma50",
                    label="Price extended above SMA50",
                    polarity="negative",
                    metric="price_to_sma50",
                    value=round(sma50, 6),
                    threshold="<=1.10",
                    message="Price is extended enough to prefer a pullback.",
                )
            )
        elif sma50 < 0.97:
            risks.append(
                _item(
                    code="price_below_sma50",
                    label="Price below SMA50",
                    polarity="negative",
                    metric="price_to_sma50",
                    value=round(sma50, 6),
                    threshold=">=0.97",
                    message="Shorter-term trend confirmation is weak.",
                )
            )
    # M1 evidence completeness: the near-miss bands [0.97, 0.98) and
    # (1.08, 1.10] block ENTRY_READY (band 0.98-1.08) but were silent (CRM).
    if sma50 is not None and (
        (0.97 <= sma50 < 0.98) or (1.08 < sma50 <= 1.10)
    ):
        risks.append(
            _item(
                code="price_to_sma50_outside_ready_band",
                label="Price outside SMA50 readiness band",
                polarity="negative",
                metric="price_to_sma50",
                value=round(sma50, 6),
                threshold="0.98–1.08",
                message="Price is outside the 0.98–1.08 SMA50 readiness band.",
            )
        )

    if return_20d is not None:
        if -0.03 <= return_20d <= 0.12:
            positives.append(
                _item(
                    code="return_20d_ready_band",
                    label="20d return in readiness band",
                    polarity="positive",
                    metric="return_20d",
                    value=round(return_20d, 6),
                    threshold="-3% to +12%",
                    message="Recent momentum is positive/controlled rather than chased.",
                )
            )
        elif return_20d > overextended_return20_gt:
            risks.append(
                _item(
                    code="return_20d_overextended",
                    label="20d return overextended",
                    polarity="negative",
                    metric="return_20d",
                    value=round(return_20d, 6),
                    threshold=f"<={overextended_return20_gt:.0%}",
                    message=(
                        "Recent price appreciation is too extended for ENTRY_READY."
                        if overextended_return20_gt == 0.15
                        else "Recent price appreciation exceeds the configured overextension gate."
                    ),
                )
            )
    # M1 evidence completeness: 20d momentum outside -3%..+12% but not above
    # the overextension gate blocks ENTRY_READY yet was silent (CRM).
    if return_20d is not None and (
        return_20d < -0.03 or (0.12 < return_20d <= overextended_return20_gt)
    ):
        risks.append(
            _item(
                code="return_20d_outside_ready_band",
                label="20d return outside readiness band",
                polarity="negative",
                metric="return_20d",
                value=round(return_20d, 6),
                threshold="-3% to +12%",
                message="20d momentum is outside the -3% to +12% readiness band.",
            )
        )

    if return_60d is not None:
        if return_60d >= 0:
            positives.append(
                _item(
                    code="return_60d_nonnegative",
                    label="60d trend non-negative",
                    polarity="positive",
                    metric="return_60d",
                    value=round(return_60d, 6),
                    threshold=">=0%",
                    message="Medium-term momentum is non-negative.",
                )
            )
        elif return_60d <= -0.08:
            risks.append(
                _item(
                    code="return_60d_weak",
                    label="60d trend weak",
                    polarity="negative",
                    metric="return_60d",
                    value=round(return_60d, 6),
                    threshold=">-8% preferred",
                    message="Medium-term momentum is weak.",
                )
            )
    # M1 evidence completeness: mildly negative 60d returns block ENTRY_READY
    # (which requires return_60d >= 0) but were silent (TXN, EQIX).
    if return_60d is not None and -0.08 < return_60d < 0.0:
        risks.append(
            _item(
                code="return_60d_slightly_negative",
                label="60d trend slightly negative",
                polarity="negative",
                metric="return_60d",
                value=round(return_60d, 6),
                threshold=">=0% for ENTRY_READY",
                message="60d return is negative and blocks ENTRY_READY.",
            )
        )

    if relative_strength is not None:
        if relative_strength >= ready_rs60_min:
            positives.append(
                _item(
                    code="relative_strength_60d_qqq_ready",
                    label="60d relative strength acceptable",
                    polarity="positive",
                    metric="relative_strength_60d_qqq",
                    value=round(relative_strength, 6),
                    threshold=f">={ready_rs60_min:.0%}",
                    message=(
                        "The stock is keeping pace with QQQ over 60 trading days."
                        if ready_rs60_min == -0.03
                        else "60d QQQ relative strength meets the configured readiness threshold."
                    ),
                )
            )
        elif relative_strength <= -0.10:
            risks.append(
                _item(
                    code="relative_strength_60d_qqq_weak",
                    label="60d relative strength weak",
                    polarity="negative",
                    metric="relative_strength_60d_qqq",
                    value=round(relative_strength, 6),
                    threshold=">-10% preferred",
                    message="The stock is materially lagging QQQ.",
                )
            )
        if ready_rs60_min > -0.03 and relative_strength < ready_rs60_min:
            risks.append(
                _item(
                    code="relative_strength_60d_qqq_below_candidate_ready",
                    label="60d relative strength below candidate gate",
                    polarity="negative",
                    metric="relative_strength_60d_qqq",
                    value=round(relative_strength, 6),
                    threshold=f">={ready_rs60_min:.0%}",
                    message="60d QQQ relative strength is below the versioned ENTRY_READY gate.",
                )
            )
    # M1 evidence completeness: RS60 in (-10%, ready gate) blocks ENTRY_READY
    # but was silent under the canonical -3% gate (PG, GOOGL, TXN, AAPL).
    # Non-default candidate gates already emit below_candidate_ready above.
    if (
        ready_rs60_min == -0.03
        and relative_strength is not None
        and -0.10 < relative_strength < ready_rs60_min
    ):
        risks.append(
            _item(
                code="relative_strength_60d_qqq_below_ready",
                label="60d relative strength below readiness gate",
                polarity="negative",
                metric="relative_strength_60d_qqq",
                value=round(relative_strength, 6),
                threshold=">=-3%",
                message="60d QQQ relative strength is below the -3% ENTRY_READY gate.",
            )
        )

    if volatility is not None and volatility > 0.80:
        risks.append(
            _item(
                code="volatility_60d_high",
                label="60d volatility high",
                polarity="negative",
                metric="volatility_60d",
                value=round(volatility, 6),
                threshold="<=80% annualized for ENTRY_READY",
                message="Volatility is too high for the ENTRY_READY state.",
            )
        )

    # M1 evidence completeness: drawdown > 22% blocks ENTRY_READY but never
    # emitted an EvidenceItem (CRM archetype when drawdown is deep).
    if drawdown is not None and drawdown > 0.22:
        risks.append(
            _item(
                code="drawdown_from_52w_high_deep",
                label="52w drawdown exceeds readiness cap",
                polarity="negative",
                metric="drawdown_from_52w_high",
                value=round(drawdown, 6),
                threshold="<=22% for ENTRY_READY",
                message="Drawdown from 52-week high exceeds the 22% ENTRY_READY cap.",
            )
        )

    regime = str(metrics.get("regime", "") or "").strip().lower()
    benchmark_trend_ok = _optional_bool(metrics.get("benchmark_trend_ok"))
    defensive_regime = regime == "down" or benchmark_trend_ok is False
    if defensive_regime:
        risks.append(
            _item(
                code="defensive_market_regime",
                label="Defensive market regime",
                polarity="negative",
                metric="regime",
                value=regime or "benchmark_trend_down",
                threshold="extra relative-strength confirmation required",
                message="A weak benchmark regime raises the bar for ENTRY_READY.",
            )
        )
    elif regime == "up" or benchmark_trend_ok is True:
        positives.append(
            _item(
                code="supportive_market_regime",
                label="Supportive market regime",
                polarity="positive",
                metric="regime",
                value=regime or "benchmark_trend_up",
                threshold="supportive",
                message="Benchmark regime does not impose the defensive entry gate.",
            )
        )

    confidence = round(max(0.0, min(1.0, confidence)), 6)

    if insufficient_reason:
        state = EntryState.INSUFFICIENT_DATA
    else:
        damaged = bool(
            (sma200 is not None and sma200 < 0.95)
            or (days_below is not None and days_below >= 15)
            or (
                sma50 is not None
                and return_60d is not None
                and sma50 < 0.97
                and return_60d <= -0.08
            )
            or (
                return_60d is not None
                and relative_strength is not None
                and return_60d <= -0.15
                and relative_strength <= -0.10
            )
        )

        overextended = bool(
            (sma50 is not None and sma50 > 1.10)
            or (return_20d is not None and return_20d > overextended_return20_gt)
            or (
                range_position is not None
                and return_20d is not None
                and range_position >= 0.95
                and return_20d > 0.08
            )
        )

        volatility_ready = volatility is None or volatility <= 0.80
        base_ready = bool(
            sma200 is not None
            and sma200 >= 1.00
            and sma50 is not None
            and 0.98 <= sma50 <= 1.08
            and return_20d is not None
            and -0.03 <= return_20d <= 0.12
            and return_60d is not None
            and return_60d >= 0.0
            and relative_strength is not None
            and relative_strength >= ready_rs60_min
            and drawdown is not None
            and drawdown <= 0.22
            and volatility_ready
        )
        defensive_ready = bool(
            not defensive_regime
            or (
                relative_strength is not None
                and relative_strength >= 0.05
                and return_20d is not None
                and return_20d >= 0.0
            )
        )

        if damaged:
            state = EntryState.TREND_DAMAGED
        elif overextended:
            state = EntryState.WATCH_PULLBACK
        elif base_ready and defensive_ready:
            state = EntryState.ENTRY_READY
        else:
            state = EntryState.WATCH_BREAKOUT

    return EntryDecision(
        state=state,
        score=score,
        confidence=confidence,
        positives=tuple(positives),
        risks=tuple(risks),
        market_asof=normalized_market_asof,
    )


ENTRY_V2_POLICY_VERSION = "entry_quality_v2_2026-10-15"

ENTRY_V2_MA_ALIGNMENT_MIN = 0.98
ENTRY_V2_LAGGING_SCORE_PENALTY = 0.10


def _sma50_to_sma200_ratio(
    price_to_sma200: float | None, price_to_sma50: float | None
) -> float | None:
    """Exact identity: SMA50/SMA200 = price_to_sma200 / price_to_sma50."""
    if price_to_sma200 is None or price_to_sma50 is None:
        return None
    if price_to_sma50 <= 0:
        return None
    return price_to_sma200 / price_to_sma50


def _v2_core_uptrend_ready_except_extension(
    metrics: Mapping[str, Any],
    *,
    ready_rs60_min: float,
    overextended_return20_gt: float,
) -> bool:
    """H2 Fix 1 predicate: everything READY except mild high-side extension."""
    sma200 = _finite_value(metrics, "price_to_sma200")
    sma50 = _finite_value(metrics, "price_to_sma50")
    return_20d = _finite_value(metrics, "return_20d")
    return_60d = _finite_value(metrics, "return_60d")
    drawdown = _finite_value(metrics, "drawdown_from_52w_high")
    relative_strength = _finite_value(metrics, "relative_strength_60d_qqq")
    volatility = _finite_value(metrics, "volatility_60d")
    days_below = _finite_value(metrics, "days_below_sma200")
    ratio = _sma50_to_sma200_ratio(sma200, sma50)
    regime = str(metrics.get("regime", "") or "").strip().lower()
    benchmark_trend_ok = _optional_bool(metrics.get("benchmark_trend_ok"))
    defensive_regime = regime == "down" or benchmark_trend_ok is False
    defensive_entry_ok = (
        not defensive_regime
        or (
            relative_strength is not None
            and relative_strength >= 0.05
            and return_20d is not None
            and return_20d >= 0.0
        )
    )
    _ = overextended_return20_gt
    return bool(
        sma200 is not None
        and sma200 >= 1.00
        and ratio is not None
        and ratio >= ENTRY_V2_MA_ALIGNMENT_MIN
        and (days_below is None or days_below <= 3)
        and return_60d is not None
        and return_60d >= 0.0
        and relative_strength is not None
        and relative_strength >= ready_rs60_min
        and drawdown is not None
        and drawdown <= 0.22
        and (volatility is None or volatility <= 0.80)
        and defensive_entry_ok
        and sma50 is not None
        and sma50 >= 0.98
        and return_20d is not None
        and return_20d >= -0.03
        and (sma50 > 1.08 or return_20d > 0.12)
    )


def build_entry_quality_v2(
    metrics: Mapping[str, Any],
    *,
    decision_date: str | date | None = None,
    market_asof: str | date | None = None,
) -> EntryDecision:
    """Pre-registered H2 Entry candidate: v1 evidence plus 3 structure fixes.

    Wraps the frozen v1 builder (score, confidence, and all M1 silent-gate
    evidence are inherited unchanged), then applies: the pullback-seam
    close, the sma50_to_sma200 alignment gate + evidence, and the
    WATCH_BREAKOUT near-vs-lagging differentiation (0.10 score penalty for
    lagging structure only).
    """
    ready_rs60_min = -0.03
    overextended_return20_gt = 0.15
    base = _build_entry_with_thresholds(
        metrics,
        decision_date=decision_date,
        market_asof=market_asof,
        ready_rs60_min=ready_rs60_min,
        overextended_return20_gt=overextended_return20_gt,
    )
    positives: list[EvidenceItem] = list(base.positives)
    risks: list[EvidenceItem] = list(base.risks)
    state = base.state
    score = base.score

    sma200 = _finite_value(metrics, "price_to_sma200")
    sma50 = _finite_value(metrics, "price_to_sma50")
    ratio = _sma50_to_sma200_ratio(sma200, sma50)
    if ratio is not None:
        if ratio >= 1.0:
            positives.append(
                _item(
                    code="sma50_above_sma200_aligned",
                    label="SMA50 / SMA200 alignment",
                    polarity="positive",
                    metric="sma50_to_sma200",
                    value=ratio,
                    threshold=">=1.00 golden-cross alignment",
                    message=(
                        f"50d SMA is {ratio:.2f}x 200d SMA (aligned uptrend)."
                    ),
                )
            )
        elif ratio < 1.0:
            risks.append(
                _item(
                    code="sma50_below_sma200_inverted",
                    label="SMA50 / SMA200 alignment",
                    polarity="negative",
                    metric="sma50_to_sma200",
                    value=ratio,
                    threshold=">=0.98 required for ENTRY_READY",
                    message=(
                        f"50d SMA is {ratio:.2f}x 200d SMA "
                        "(inverted medium/long trend)."
                    ),
                )
            )

    ma_alignment_ok = ratio is not None and ratio >= ENTRY_V2_MA_ALIGNMENT_MIN
    if state is EntryState.WATCH_BREAKOUT and _v2_core_uptrend_ready_except_extension(
        metrics,
        ready_rs60_min=ready_rs60_min,
        overextended_return20_gt=overextended_return20_gt,
    ):
        state = EntryState.WATCH_PULLBACK
    elif state is EntryState.ENTRY_READY and not ma_alignment_ok:
        state = EntryState.WATCH_BREAKOUT

    if state is EntryState.WATCH_BREAKOUT:
        return_60d = _finite_value(metrics, "return_60d")
        relative_strength = _finite_value(metrics, "relative_strength_60d_qqq")
        near_breakout = bool(
            sma200 is not None
            and sma200 >= 1.0
            and return_60d is not None
            and return_60d >= -0.03
            and relative_strength is not None
            and relative_strength >= -0.06
            and (ratio is None or ratio >= ENTRY_V2_MA_ALIGNMENT_MIN)
        )
        if near_breakout:
            positives.append(
                _item(
                    code="watch_breakout_near_consolidation",
                    label="Near-breakout consolidation",
                    polarity="positive",
                    metric="entry_sub_bucket",
                    value="near-breakout consolidation",
                    threshold="trend/60d/RS/alignment within readiness reach",
                    message=(
                        "Near-breakout consolidation: price structure is within "
                        "readiness reach on trend, momentum, and relative strength."
                    ),
                )
            )
        else:
            score = max(0.0, round(score - ENTRY_V2_LAGGING_SCORE_PENALTY, 6))
            risks.append(
                _item(
                    code="watch_breakout_lagging_structure",
                    label="Lagging breakout structure",
                    polarity="negative",
                    metric="entry_sub_bucket",
                    value="lagging structure below breakout readiness",
                    threshold="near-breakout consolidation",
                    message=(
                        "Lagging structure below breakout readiness: trend, momentum, "
                        "relative strength, or MA alignment lags the near-breakout "
                        "consolidation bar."
                    ),
                )
            )

    return EntryDecision(
        state=state,
        score=score,
        confidence=base.confidence,
        positives=tuple(positives),
        risks=tuple(risks),
        market_asof=base.market_asof,
    )
