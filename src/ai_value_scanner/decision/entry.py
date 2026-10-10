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
    """Build deterministic Entry Quality v1 from per-stock market features."""
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
        elif return_20d > 0.15:
            risks.append(
                _item(
                    code="return_20d_overextended",
                    label="20d return overextended",
                    polarity="negative",
                    metric="return_20d",
                    value=round(return_20d, 6),
                    threshold="<=15%",
                    message="Recent price appreciation is too extended for ENTRY_READY.",
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

    if relative_strength is not None:
        if relative_strength >= -0.03:
            positives.append(
                _item(
                    code="relative_strength_60d_qqq_ready",
                    label="60d relative strength acceptable",
                    polarity="positive",
                    metric="relative_strength_60d_qqq",
                    value=round(relative_strength, 6),
                    threshold=">=-3%",
                    message="The stock is keeping pace with QQQ over 60 trading days.",
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
            or (return_20d is not None and return_20d > 0.15)
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
            and relative_strength >= -0.03
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
