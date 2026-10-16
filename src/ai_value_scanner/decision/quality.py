from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
import math
from typing import Any

from .model import EvidenceItem, QualityDecision, QualityGrade


QUALITY_POLICY_VERSION = "company_quality_v1_2026-10-10"

QUALITY_V1_COMPONENT_WEIGHTS: dict[str, float] = {
    "profitability_cash": 0.30,
    "growth_stability": 0.20,
    "balance_sheet": 0.20,
    "dilution": 0.10,
    "valuation_context": 0.10,
    "operating_red_flags": 0.10,
}

QUALITY_V1_GRADE_A_MIN_SCORE = 0.72
QUALITY_V1_GRADE_A_MIN_CONFIDENCE = 0.80
QUALITY_V1_GRADE_B_MIN_SCORE = 0.50
QUALITY_V1_GRADE_B_MIN_CONFIDENCE = 0.65
QUALITY_V1_MIN_CONFIDENCE_RATED = 0.50
QUALITY_V1_STALE_WARN_DAYS = 400
QUALITY_V1_STALE_UNRATED_DAYS = 550


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


def _metric_item(
    *,
    code: str,
    label: str,
    polarity: str,
    metric: str,
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


def _assess_numeric_metric(
    metrics: Mapping[str, Any],
    *,
    key: str,
    label: str,
    score_fn: Callable[[float], float],
    strong_score: float,
    weak_score: float,
    threshold_text: str,
    positives: list[EvidenceItem],
    risks: list[EvidenceItem],
    missing: list[EvidenceItem],
) -> float | None:
    value = _finite_value(metrics, key)
    if value is None:
        missing.append(
            _metric_item(
                code=f"{key}_missing",
                label=f"{label} missing",
                polarity="missing",
                metric=key,
                value=None,
                threshold=threshold_text,
                message=f"{label} is unavailable, so it cannot support Company Quality.",
            )
        )
        return None

    score = max(0.0, min(1.0, float(score_fn(value))))
    if score >= strong_score:
        positives.append(
            _metric_item(
                code=f"{key}_strong",
                label=f"{label} supportive",
                polarity="positive",
                metric=key,
                value=round(value, 6),
                threshold=threshold_text,
                message=f"{label} supports the quality assessment.",
            )
        )
    elif score <= weak_score:
        risks.append(
            _metric_item(
                code=f"{key}_weak",
                label=f"{label} weak",
                polarity="negative",
                metric=key,
                value=round(value, 6),
                threshold=threshold_text,
                message=f"{label} is a material counter-signal for Company Quality.",
            )
        )
    return score


def _component(
    metric_scores: list[float | None],
) -> tuple[float | None, float]:
    observed = [float(score) for score in metric_scores if score is not None]
    coverage = len(observed) / float(len(metric_scores)) if metric_scores else 0.0
    if not observed:
        return None, coverage
    return sum(observed) / len(observed), coverage


def _score_net_margin(value: float) -> float:
    if value >= 0.20:
        return 1.0
    if value >= 0.10:
        return 0.80
    if value >= 0.03:
        return 0.60
    if value >= 0.0:
        return 0.40
    return 0.0


def _score_fcf(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value == 0.0:
        return 0.50
    return 0.0


def _score_ocf_conversion(value: float) -> float:
    if value >= 1.0:
        return 1.0
    if value >= 0.80:
        return 0.80
    if value >= 0.50:
        return 0.50
    if value >= 0.0:
        return 0.25
    return 0.0


def _score_accrual(value: float) -> float:
    magnitude = abs(value)
    if magnitude <= 0.05:
        return 1.0
    if magnitude <= 0.10:
        return 0.80
    if magnitude <= 0.20:
        return 0.50
    if magnitude <= 0.35:
        return 0.20
    return 0.0


def _score_revenue_growth(value: float) -> float:
    if value >= 0.15:
        return 1.0
    if value >= 0.08:
        return 0.80
    if value >= 0.0:
        return 0.50
    if value >= -0.10:
        return 0.25
    return 0.0


def _score_earnings_growth(value: float) -> float:
    if value >= 0.15:
        return 1.0
    if value >= 0.0:
        return 0.65
    if value >= -0.10:
        return 0.35
    return 0.0


def _score_ocf_growth(value: float) -> float:
    if value >= 0.15:
        return 1.0
    if value >= 0.0:
        return 0.65
    if value >= -0.10:
        return 0.35
    return 0.0


def _score_net_debt(value: float) -> float:
    if value <= 0.0:
        return 1.0
    if value <= 1.5:
        return 0.80
    if value <= 3.0:
        return 0.55
    if value <= 4.0:
        return 0.30
    return 0.0


def _score_interest_coverage(value: float) -> float:
    if value >= 8.0:
        return 1.0
    if value >= 4.0:
        return 0.80
    if value >= 2.0:
        return 0.50
    if value >= 1.0:
        return 0.25
    return 0.0


def _score_current_ratio(value: float) -> float:
    if value >= 1.5:
        return 1.0
    if value >= 1.0:
        return 0.75
    if value >= 0.75:
        return 0.40
    return 0.10


def _score_dilution(value: float) -> float:
    if value <= 0.0:
        return 1.0
    if value <= 0.03:
        return 0.80
    if value <= 0.07:
        return 0.50
    if value <= 0.12:
        return 0.25
    return 0.0


def _score_fcf_yield(value: float) -> float:
    if value >= 0.05:
        return 1.0
    if value >= 0.02:
        return 0.75
    if value >= 0.0:
        return 0.50
    if value >= -0.02:
        return 0.25
    return 0.0


def _score_valuation_percentile(value: float) -> float:
    if value <= 0.35:
        return 1.0
    if value <= 0.60:
        return 0.70
    if value <= 0.80:
        return 0.40
    return 0.10


def _score_receivables_gap(value: float) -> float:
    if value <= 0.05:
        return 1.0
    if value <= 0.15:
        return 0.60
    if value <= 0.25:
        return 0.30
    return 0.0


def _score_inventory_gap(value: float) -> float:
    if value <= 0.10:
        return 1.0
    if value <= 0.20:
        return 0.60
    if value <= 0.30:
        return 0.30
    return 0.0


def build_company_quality_v1(
    metrics: Mapping[str, Any],
    *,
    decision_date: str | date | None = None,
    data_asof: str | date | None = None,
) -> QualityDecision:
    """Build the pre-registered, explainable Company Quality v1 decision.

    Missing inputs lower both the effective score and confidence. They are
    never filled with a neutral/positive default.
    """
    positives: list[EvidenceItem] = []
    risks: list[EvidenceItem] = []
    missing: list[EvidenceItem] = []

    profitability_cash_scores = [
        _assess_numeric_metric(
            metrics,
            key="net_margin",
            label="Net margin",
            score_fn=_score_net_margin,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=10% supportive; <0% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="free_cash_flow",
            label="Free cash flow",
            score_fn=_score_fcf,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">0 supportive; <0 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="ocf_to_net_income",
            label="Operating cash-flow conversion",
            score_fn=_score_ocf_conversion,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=0.8 supportive; <0.5 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="accrual_ratio",
            label="Accrual quality",
            score_fn=_score_accrual,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="|accrual|<=0.10 supportive; >0.35 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    earnings_growth_key = (
        "adjusted_net_income_yoy"
        if _finite_value(metrics, "adjusted_net_income_yoy") is not None
        else "net_income_yoy"
    )
    growth_scores = [
        _assess_numeric_metric(
            metrics,
            key="revenue_yoy",
            label="Revenue growth",
            score_fn=_score_revenue_growth,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=8% supportive; <-10% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key=earnings_growth_key,
            label="Earnings growth",
            score_fn=_score_earnings_growth,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=15% strong; <-10% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="operating_cash_flow_yoy",
            label="Operating cash-flow growth",
            score_fn=_score_ocf_growth,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=15% strong; <-10% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    balance_scores = [
        _assess_numeric_metric(
            metrics,
            key="net_debt_to_ebitda",
            label="Net debt / EBITDA",
            score_fn=_score_net_debt,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=1.5 supportive; >4 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="interest_coverage",
            label="Interest coverage",
            score_fn=_score_interest_coverage,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=4 supportive; <1 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="current_ratio",
            label="Current ratio",
            score_fn=_score_current_ratio,
            strong_score=0.75,
            weak_score=0.25,
            threshold_text=">=1 supportive; <0.75 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    dilution_scores = [
        _assess_numeric_metric(
            metrics,
            key="shares_yoy",
            label="Share-count change",
            score_fn=_score_dilution,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=3% supportive; >12% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        )
    ]

    valuation_scores = [
        _assess_numeric_metric(
            metrics,
            key="fcf_yield",
            label="FCF yield",
            score_fn=_score_fcf_yield,
            strong_score=0.75,
            weak_score=0.25,
            threshold_text=">=2% supportive; <-2% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="ps_hist_percentile",
            label="Historical P/S percentile",
            score_fn=_score_valuation_percentile,
            strong_score=0.70,
            weak_score=0.25,
            threshold_text="<=60% supportive; >80% expensive",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="pe_hist_percentile",
            label="Historical P/E percentile",
            score_fn=_score_valuation_percentile,
            strong_score=0.70,
            weak_score=0.25,
            threshold_text="<=60% supportive; >80% expensive",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    red_flag_scores = [
        _assess_numeric_metric(
            metrics,
            key="receivables_growth_gap",
            label="Receivables growth gap",
            score_fn=_score_receivables_gap,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=5pp supportive; >25pp weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            metrics,
            key="inventory_growth_gap",
            label="Inventory growth gap",
            score_fn=_score_inventory_gap,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=10pp supportive; >30pp weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    component_inputs = {
        "profitability_cash": profitability_cash_scores,
        "growth_stability": growth_scores,
        "balance_sheet": balance_scores,
        "dilution": dilution_scores,
        "valuation_context": valuation_scores,
        "operating_red_flags": red_flag_scores,
    }
    component_scores: dict[str, float | None] = {}
    component_coverage: dict[str, float] = {}
    effective_score = 0.0
    confidence = 0.0
    for name, scores in component_inputs.items():
        score, coverage = _component(scores)
        component_scores[name] = None if score is None else round(score, 6)
        component_coverage[name] = coverage
        weight = QUALITY_V1_COMPONENT_WEIGHTS[name]
        confidence += weight * coverage
        if score is not None:
            effective_score += weight * score * coverage

    shares_stale = metrics.get("shares_stale")
    if shares_stale is True:
        risks.append(
            _metric_item(
                code="shares_data_stale",
                label="Share-count data stale",
                polarity="negative",
                metric="shares_stale",
                value="true",
                threshold="false",
                message="Share-count provenance is stale and weakens dilution confidence.",
            )
        )

    decision_dt = _parse_iso_date(decision_date)
    data_dt = _parse_iso_date(data_asof)
    stale_unrated = False
    data_integrity_blocked = False
    normalized_data_asof = data_dt.isoformat() if data_dt is not None else None

    if metrics.get("fundamental_facts_cover_latest_periodic") is False:
        data_integrity_blocked = True
        confidence = min(confidence, 0.49)
        missing.append(
            _metric_item(
                code="latest_periodic_filing_not_covered",
                label="Latest periodic filing not covered",
                polarity="missing",
                metric="fundamental_latest_periodic_filing_date",
                value=metrics.get("fundamental_latest_periodic_filing_date"),
                threshold="latest periodic filing must be represented in recognized Company Facts",
                message=(
                    "SEC submissions show a newer periodic filing than the recognized "
                    "Company Facts used for Quality; stale metrics are not promoted."
                ),
            )
        )

    if metrics.get("fundamental_currency_supported") is False:
        data_integrity_blocked = True
        confidence = min(confidence, 0.49)
        missing.append(
            _metric_item(
                code="fundamental_currency_unsupported",
                label="Fundamental reporting currency unsupported",
                polarity="missing",
                metric="fundamental_reporting_currency",
                value=metrics.get("fundamental_reporting_currency"),
                threshold="USD monetary facts required by live valuation path",
                message=(
                    "Core monetary facts are available only in a non-USD reporting "
                    "currency; the live scanner will not mix them with USD market cap "
                    "without an explicit FX normalization layer."
                ),
            )
        )
    # Filing-entity identity: False means positively unverified; an
    # explicitly-None flag means the binding was checked but cannot be
    # confirmed (e.g. submissions unavailable) and is treated conservatively
    # the same way. An ABSENT key is legacy data predating the check and
    # keeps the old behavior, so historical frames are never retroactively
    # penalized.
    _entity_flag_present = "fundamental_operating_entity_verified" in metrics
    _entity_flag = metrics.get("fundamental_operating_entity_verified")
    if _entity_flag is False or (_entity_flag_present and _entity_flag is None):
        data_integrity_blocked = True
        confidence = min(confidence, 0.49)
        missing.append(
            _metric_item(
                code="operating_entity_unverified",
                label="Operating filing entity unverified",
                polarity="missing",
                metric="fundamental_operating_entity_detail",
                value=metrics.get("fundamental_operating_entity_detail"),
                threshold="ticker must map to the operating issuer with core facts",
                message=(
                    "The ticker->CIK binding does not verifiably represent the "
                    "operating issuer (ticker absent from the entity filing "
                    "record, an entity with filings but no revenue, net "
                    "income or operating-cash-flow facts, or an unchecked "
                    "binding). No reliable grade can be claimed; verify the "
                    "filing entity before use."
                ),
            )
        )
    if decision_dt is not None and data_dt is not None:
        if data_dt > decision_dt:
            raise ValueError(
                f"fundamental data_asof {data_dt.isoformat()} is after "
                f"decision_date {decision_dt.isoformat()}"
            )
        age_days = (decision_dt - data_dt).days
        if age_days > QUALITY_V1_STALE_UNRATED_DAYS:
            stale_unrated = True
            confidence = min(confidence, 0.49)
            risks.append(
                _metric_item(
                    code="fundamental_data_severely_stale",
                    label="Fundamental data severely stale",
                    polarity="negative",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<={QUALITY_V1_STALE_UNRATED_DAYS}",
                    message="Fundamental evidence is too stale to assign a rated Company Quality grade.",
                )
            )
        elif age_days > QUALITY_V1_STALE_WARN_DAYS:
            confidence *= 0.90
            risks.append(
                _metric_item(
                    code="fundamental_data_stale",
                    label="Fundamental data stale",
                    polarity="negative",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<={QUALITY_V1_STALE_WARN_DAYS}",
                    message="Fundamental evidence is older than the preferred freshness window.",
                )
            )
        elif not data_integrity_blocked:
            positives.append(
                _metric_item(
                    code="fundamental_data_fresh",
                    label="Fundamental data freshness",
                    polarity="positive",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<={QUALITY_V1_STALE_WARN_DAYS}",
                    message="Fundamental evidence is within the pre-registered freshness window.",
                )
            )
    elif data_dt is None:
        confidence = min(confidence, 0.79)
        missing.append(
            _metric_item(
                code="fundamental_data_asof_missing",
                label="Fundamental data as-of missing",
                polarity="missing",
                metric="fundamental_data_asof",
                value=None,
                threshold="required for Quality A",
                message="Filing freshness cannot be verified, so Quality A is suppressed.",
            )
        )

    severe_risks = 0
    severe_checks = (
        (_finite_value(metrics, "net_debt_to_ebitda"), lambda x: x > 5.0),
        (_finite_value(metrics, "interest_coverage"), lambda x: x < 1.0),
        (_finite_value(metrics, "shares_yoy"), lambda x: x > 0.15),
        (_finite_value(metrics, "receivables_growth_gap"), lambda x: x > 0.30),
        (_finite_value(metrics, "inventory_growth_gap"), lambda x: x > 0.35),
    )
    severe_risks += sum(
        1 for value, predicate in severe_checks if value is not None and predicate(value)
    )
    if (
        (_finite_value(metrics, "net_margin") or 0.0) < 0.0
        and (_finite_value(metrics, "free_cash_flow") or 0.0) < 0.0
    ):
        severe_risks += 1

    score = round(max(0.0, min(1.0, effective_score)), 6)
    confidence = round(max(0.0, min(1.0, confidence)), 6)
    profitability_score = component_scores["profitability_cash"]
    balance_score = component_scores["balance_sheet"]

    if stale_unrated or confidence < QUALITY_V1_MIN_CONFIDENCE_RATED:
        grade = QualityGrade.UNRATED
    elif (
        score >= QUALITY_V1_GRADE_A_MIN_SCORE
        and confidence >= QUALITY_V1_GRADE_A_MIN_CONFIDENCE
        and profitability_score is not None
        and profitability_score >= 0.60
        and balance_score is not None
        and balance_score >= 0.50
        and component_coverage["profitability_cash"] >= 0.75
        and component_coverage["balance_sheet"] >= (2.0 / 3.0)
        and severe_risks == 0
    ):
        grade = QualityGrade.A
    elif (
        score >= QUALITY_V1_GRADE_B_MIN_SCORE
        and confidence >= QUALITY_V1_GRADE_B_MIN_CONFIDENCE
        and severe_risks < 2
    ):
        grade = QualityGrade.B
    else:
        grade = QualityGrade.C

    return QualityDecision(
        grade=grade,
        score=score,
        confidence=confidence,
        component_scores=component_scores,
        positives=tuple(positives),
        risks=tuple(risks),
        missing=tuple(missing),
        data_asof=normalized_data_asof,
    )


QUALITY_V2_POLICY_VERSION = "company_quality_v2_2026-10-15"

QUALITY_V2_PRE_EARNINGS_WARN_DAYS = 70
QUALITY_V2_ORGANIC_SHARES_YOY_MIN = -0.30
QUALITY_V2_ORGANIC_SHARES_YOY_MAX = 1.00

QUALITY_V2_HIGH_GROWTH_MIN = 0.25
QUALITY_V2_HEALTHY_OCF_MIN = 0.80
QUALITY_V2_GAP_FLOOR = 0.75
QUALITY_V2_VALUATION_FLOOR = 0.35

# Tag-agnostic non-operating investment gain / tax distortion defense
# (three-layer architecture, 2026-10-16 audit): catches below-the-line
# investment gains and one-time tax benefits that inflate GAAP net income
# without changing operating income or operating cash flow.
QUALITY_V2_NONOP_MARGIN_GAP_MIN = 0.05
QUALITY_V2_NONOP_NET_MARGIN_FLOOR = 0.12
QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI = 1.50
QUALITY_V2_NONOP_YOY_GAP_MIN = 0.40
QUALITY_V2_HIGH_MARGIN_CONVERSION_WARN_MARGIN = 0.20
# Single-quarter non-operating spike trigger (Layer-1 Case C, SHOP class):
# a huge mark-to-market gain can hide behind a sub-threshold TTM margin gap,
# so screen the latest reconstructed quarter as well.
QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN: float = 0.25
QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR: float = 200_000_000.0


def _score_accrual_v2(value: float, ocf_to_ni: float | None = None) -> float:
    """Sign-aware accrual scoring (H1 Fix 1).

    Negative accruals (OCF exceeds accounting net income) score 1.0 whenever
    cash conversion is healthy or unknown; only a negative accrual combined
    with weak conversion falls back to the v1 magnitude penalty. Positive
    accruals keep the exact v1 bands.
    """
    if value <= 0.0:
        if ocf_to_ni is None or ocf_to_ni >= QUALITY_V2_HEALTHY_OCF_MIN:
            return 1.0
        return _score_accrual(value)
    if value <= 0.05:
        return 1.0
    if value <= 0.10:
        return 0.80
    if value <= 0.20:
        return 0.50
    if value <= 0.35:
        return 0.20
    return 0.0


def _score_fcf_margin(margin: float) -> float:
    """Scale-normalized FCF margin scoring (H1 Fix 2)."""
    if margin >= 0.15:
        return 1.0
    if margin >= 0.08:
        return 0.85
    if margin >= 0.03:
        return 0.65
    if margin > 0.0:
        return 0.25
    if margin > -0.05:
        return 0.15
    return 0.0


def _score_operating_margin(margin: float) -> float:
    """Operating margin scoring (H1 Fix 2)."""
    if margin >= 0.20:
        return 1.0
    if margin >= 0.12:
        return 0.80
    if margin >= 0.05:
        return 0.55
    if margin >= 0.0:
        return 0.30
    return 0.0


def _is_high_growth_cash_generative(metrics: Mapping[str, Any]) -> bool:
    """H1 Fix 3 exemption condition (mirrors M2 attribution definition)."""
    revenue_yoy = _finite_value(metrics, "revenue_yoy")
    ocf = _finite_value(metrics, "ocf_to_net_income")
    return (
        revenue_yoy is not None
        and revenue_yoy >= QUALITY_V2_HIGH_GROWTH_MIN
        and ocf is not None
        and ocf >= QUALITY_V2_HEALTHY_OCF_MIN
    )


def build_company_quality_v2(
    metrics: Mapping[str, Any],
    *,
    decision_date: str | date | None = None,
    data_asof: str | date | None = None,
) -> QualityDecision:
    """Pre-registered H1 Quality candidate: v1 pillars with 4 metric fixes.

    Grade thresholds, pillar weights, confidence mechanics, severe-risk
    gates, and UNRATED guards are identical to v1 (same constants). Only
    the four M2-proven metric defects change: sign-aware accruals,
    fcf_margin + operating_margin pillars, high-growth gap exemption, and
    the valuation-percentile floor for cash-generative compounders.
    """
    positives: list[EvidenceItem] = []
    risks: list[EvidenceItem] = []
    missing: list[EvidenceItem] = []

    work: dict[str, Any] = dict(metrics)
    ocf_value = _finite_value(work, "ocf_to_net_income")
    revenue_value = _finite_value(work, "revenue")
    fcf_value = _finite_value(work, "free_cash_flow")
    high_growth = _is_high_growth_cash_generative(work)

    if revenue_value is not None and revenue_value > 0.0 and fcf_value is not None:
        work["fcf_margin"] = fcf_value / revenue_value
        fcf_assessment = ("fcf_margin", "FCF margin", _score_fcf_margin, 0.80, 0.25,
                          ">=8% supportive; <=0% weak")
    else:
        # Graceful fallback for partial dicts (e.g. snapshot evidence maps
        # without revenue): identical v1 binary-FCF assessment, so confidence
        # is not artificially reduced.
        fcf_assessment = ("free_cash_flow", "Free cash flow", _score_fcf, 0.80, 0.25,
                          ">0 supportive; <0 weak")

    ebit_value = _finite_value(work, "adjusted_ebit")
    if ebit_value is None:
        ebit_value = _finite_value(work, "ebit")
    operating_margin_computable = (
        revenue_value is not None and revenue_value > 0.0 and ebit_value is not None
    )
    if operating_margin_computable:
        work["operating_margin"] = ebit_value / revenue_value  # type: ignore[operator]

    # --- Three-layer non-operating gain defense (tag-agnostic) --------------
    # Layer 1: below-the-line investment gains / one-time tax items inflate
    # GAAP net margin (and often net-income YoY) without touching operating
    # income or operating cash flow. Detect the margin gap, score the clean
    # operating basis, and de-pollute earnings growth.
    raw_net_margin = _finite_value(work, "net_margin")
    operating_margin_val = _finite_value(work, "operating_margin")
    fcf_margin_val = _finite_value(work, "fcf_margin")
    ani_yoy_val = _finite_value(work, "adjusted_net_income_yoy")
    if ani_yoy_val is None:
        ani_yoy_val = _finite_value(work, "net_income_yoy")
    ebit_yoy_val = _finite_value(work, "adjusted_ebit_yoy")
    if ebit_yoy_val is None:
        ebit_yoy_val = _finite_value(work, "ebit_yoy")
    q_nonop_income = _finite_value(work, "latest_quarterly_nonoperating_income")
    q_nonop_ratio = _finite_value(work, "latest_quarterly_nonop_to_revenue")
    if q_nonop_ratio is None:
        q_rev = _finite_value(work, "latest_quarterly_revenue")
        if q_nonop_income is not None and q_rev is not None and q_rev > 0.0:
            q_nonop_ratio = q_nonop_income / q_rev

    # Net interest income exemption (PLTR / ALAB class): recurring Treasury /
    # cash interest income on net-cash companies sits below EBIT but is fully
    # cash-backed; it is structural, not non-operating gain pollution.
    interest_income_val = _finite_value(work, "interest_income")
    interest_expense_val = _finite_value(work, "interest_expense")
    net_interest_margin = 0.0
    if (
        revenue_value is not None
        and revenue_value > 0.0
        and interest_income_val is not None
        and interest_income_val > 0.0
    ):
        exp_abs = (
            abs(interest_expense_val)
            if interest_expense_val is not None
            else 0.0
        )
        net_interest_margin = max(
            0.0, (interest_income_val - exp_abs) / revenue_value
        )

    nonop_inflated = False
    if (
        operating_margin_val is not None
        and raw_net_margin is not None
        and raw_net_margin >= QUALITY_V2_NONOP_NET_MARGIN_FLOOR
        and (raw_net_margin - operating_margin_val - net_interest_margin)
        >= QUALITY_V2_NONOP_MARGIN_GAP_MIN
        and (ocf_value is None or ocf_value < QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI)
    ):
        margin_gap = round(raw_net_margin - operating_margin_val, 6)
        nonop_inflated = True
        work["net_margin"] = operating_margin_val
        risks.append(
            _metric_item(
                code="nonoperating_gain_inflation",
                label="Non-operating gain / tax distortion",
                polarity="negative",
                metric="net_margin",
                value=margin_gap,
                threshold=(
                    "net_margin - operating_margin "
                    f"< +{QUALITY_V2_NONOP_MARGIN_GAP_MIN * 100:.0f}pp"
                ),
                message=(
                    f"Reported net margin ({raw_net_margin * 100:.1f}%) exceeds "
                    f"operating margin ({operating_margin_val * 100:.1f}%) by "
                    f"+{margin_gap * 100:.1f}pp; non-operating gains or tax items "
                    "inflated GAAP earnings — net margin capped at operating margin."
                ),
            )
        )
    elif (
        operating_margin_val is None
        and raw_net_margin is not None
        and raw_net_margin >= 0.25
        and (ocf_value is None or ocf_value < QUALITY_V2_HEALTHY_OCF_MIN)
        and fcf_margin_val is not None
        and (raw_net_margin - fcf_margin_val) >= 0.15
    ):
        margin_gap = round(raw_net_margin - fcf_margin_val, 6)
        nonop_inflated = True
        work["net_margin"] = max(0.0, fcf_margin_val)
        risks.append(
            _metric_item(
                code="nonoperating_gain_inflation",
                label="Non-operating gain / tax distortion",
                polarity="negative",
                metric="net_margin",
                value=margin_gap,
                threshold="net_margin - fcf_margin < +15pp (operating margin unavailable)",
                message=(
                    f"Reported net margin ({raw_net_margin * 100:.1f}%) exceeds "
                    f"FCF margin ({fcf_margin_val * 100:.1f}%) by "
                    f"+{margin_gap * 100:.1f}pp with no operating-margin evidence; "
                    "non-operating gains or tax items inflated GAAP earnings — "
                    "net margin capped at FCF margin."
                ),
            )
        )
    elif (
        q_nonop_income is not None
        and q_nonop_income >= QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR
        and q_nonop_ratio is not None
        and q_nonop_ratio >= QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN
    ):
        # Case C: single-quarter non-operating spike (SHOP class). A huge
        # mark-to-market gain in the latest quarter can hide behind a
        # sub-threshold TTM margin gap; the absolute floor keeps stale cache
        # entries and small denominators silent.
        nonop_inflated = True
        if (
            operating_margin_val is not None
            and raw_net_margin is not None
            and raw_net_margin > operating_margin_val
        ):
            work["net_margin"] = operating_margin_val
        risks.append(
            _metric_item(
                code="nonoperating_gain_inflation",
                label="Non-operating gain / tax distortion",
                polarity="negative",
                metric="net_margin",
                value=round(q_nonop_ratio, 6),
                threshold=(
                    "quarterly nonop / revenue "
                    f"< +{QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN * 100:.0f}% "
                    f"(>=${QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR / 1e6:.0f}M)"
                ),
                message=(
                    f"Single-quarter non-operating income is "
                    f"${q_nonop_income / 1e9:.2f}B "
                    f"({q_nonop_ratio * 100:.1f}% of quarterly revenue); "
                    "quarterly mark-to-market investment gains distort GAAP earnings."
                ),
            )
        )

    earnings_growth_key = (
        "adjusted_net_income_yoy"
        if _finite_value(work, "adjusted_net_income_yoy") is not None
        else "net_income_yoy"
    )
    yoy_gap_triggered = (
        not nonop_inflated
        and operating_margin_val is not None
        and operating_margin_val >= 0.10
        and ebit_yoy_val is not None
        and abs(ebit_yoy_val) <= 2.00
        and ani_yoy_val is not None
        and abs(ani_yoy_val - ebit_yoy_val) >= QUALITY_V2_NONOP_YOY_GAP_MIN
    )
    if (
        ebit_yoy_val is not None
        and ani_yoy_val is not None
        and (nonop_inflated or yoy_gap_triggered)
    ):
        # Score clean operating income growth instead of the investment-gain
        # distorted net-income YoY (fixes both upward inflation and
        # base-effect drag distortions).
        work[earnings_growth_key] = ebit_yoy_val
        if yoy_gap_triggered:
            # Trace/watchout only (no priority penalty): explain why the
            # report shows operating-income growth instead of GAAP NI YoY.
            risks.append(
                _metric_item(
                    code="operating_growth_basis_substituted",
                    label="Growth scored on operating-income basis",
                    polarity="negative",
                    metric=earnings_growth_key,
                    value=round(ebit_yoy_val, 6),
                    threshold=(
                        "|NI YoY - EBIT YoY| < "
                        f"{QUALITY_V2_NONOP_YOY_GAP_MIN * 100:.0f}pp"
                    ),
                    message=(
                        f"Growth scored on operating-income basis "
                        f"({ebit_yoy_val * 100:+.1f}%) because GAAP net-income YoY "
                        f"({ani_yoy_val * 100:+.1f}%) diverged by "
                        f"{abs(ani_yoy_val - ebit_yoy_val) * 100:.1f}pp due to "
                        "prior-period non-operating or tax base effects."
                    ),
                )
            )

    def _gap_score_fn(base_fn: Any) -> Any:
        if high_growth:
            return lambda value: max(float(base_fn(value)), QUALITY_V2_GAP_FLOOR)
        return base_fn

    fcf_yield_value = _finite_value(work, "fcf_yield")
    valuation_floor = (
        fcf_yield_value is not None and fcf_yield_value >= 0.02
    ) or high_growth

    def _valuation_score_fn(value: float) -> float:
        scored = float(_score_valuation_percentile(value))
        if valuation_floor:
            return max(scored, QUALITY_V2_VALUATION_FLOOR)
        return scored

    profitability_cash_scores = [
        _assess_numeric_metric(
            work,
            key="net_margin",
            label="Net margin",
            score_fn=_score_net_margin,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=10% supportive; <0% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key=fcf_assessment[0],
            label=fcf_assessment[1],
            score_fn=fcf_assessment[2],
            strong_score=fcf_assessment[3],
            weak_score=fcf_assessment[4],
            threshold_text=fcf_assessment[5],
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="ocf_to_net_income",
            label="Operating cash-flow conversion",
            score_fn=_score_ocf_conversion,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=0.8 supportive; <0.5 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="accrual_ratio",
            label="Accrual quality",
            score_fn=lambda value: _score_accrual_v2(value, ocf_value),
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=0 (with OCF/NI>=0.8) or <=0.10 supportive; >0.35 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]
    if operating_margin_computable:
        profitability_cash_scores.append(
            _assess_numeric_metric(
                work,
                key="operating_margin",
                label="Operating margin",
                score_fn=_score_operating_margin,
                strong_score=0.80,
                weak_score=0.25,
                threshold_text=">=12% supportive; <0% weak",
                positives=positives,
                risks=risks,
                missing=missing,
            )
        )

    # Layer 2: high-margin companies whose cash conversion sits in the silent
    # (0.5, 0.8) OCF/NI band get an explicit review flag instead of a pass.
    if (
        raw_net_margin is not None
        and raw_net_margin >= QUALITY_V2_HIGH_MARGIN_CONVERSION_WARN_MARGIN
        and ocf_value is not None
        and ocf_value < QUALITY_V2_HEALTHY_OCF_MIN
        and not any(r.code == "ocf_to_net_income_weak" for r in risks)
    ):
        risks.append(
            _metric_item(
                code="ocf_conversion_lagging_high_margin",
                label="Cash conversion lagging high net margin",
                polarity="negative",
                metric="ocf_to_net_income",
                value=round(ocf_value, 6),
                threshold=">=0.80x expected when net margin >=20%",
                message=(
                    f"OCF/NI is {ocf_value:.2f}x despite "
                    f"{raw_net_margin * 100:.1f}% reported net margin; "
                    "earnings include non-cash or non-operating components."
                ),
            )
        )

    growth_scores = [
        _assess_numeric_metric(
            work,
            key="revenue_yoy",
            label="Revenue growth",
            score_fn=_score_revenue_growth,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=8% supportive; <-10% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key=earnings_growth_key,
            label="Earnings growth",
            score_fn=_score_earnings_growth,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=15% strong; <-10% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="operating_cash_flow_yoy",
            label="Operating cash-flow growth",
            score_fn=_score_ocf_growth,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=15% strong; <-10% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    balance_scores = [
        _assess_numeric_metric(
            work,
            key="net_debt_to_ebitda",
            label="Net debt / EBITDA",
            score_fn=_score_net_debt,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=1.5 supportive; >4 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="interest_coverage",
            label="Interest coverage",
            score_fn=_score_interest_coverage,
            strong_score=0.80,
            weak_score=0.25,
            threshold_text=">=4 supportive; <1 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="current_ratio",
            label="Current ratio",
            score_fn=_score_current_ratio,
            strong_score=0.75,
            weak_score=0.25,
            threshold_text=">=1 supportive; <0.75 weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    shares_yoy_val = _finite_value(work, "shares_yoy")
    if shares_yoy_val is not None and (
        shares_yoy_val < QUALITY_V2_ORGANIC_SHARES_YOY_MIN
        or shares_yoy_val > QUALITY_V2_ORGANIC_SHARES_YOY_MAX
    ):
        # Reverse-split / share-basis discontinuity (e.g. AMCR -79.9% on a
        # 1-for-5 reverse split): neutralize dilution to 0.50 with full
        # coverage instead of a false strong/weak score.
        dilution_scores = [0.50]
        risks.append(
            _metric_item(
                code="shares_yoy_split_or_basis_discontinuity",
                label="Share-count split / basis discontinuity",
                polarity="negative",
                metric="shares_yoy",
                value=round(shares_yoy_val, 6),
                threshold="-30% to +100% organic YoY range",
                message=(
                    f"Reported YoY share change ({shares_yoy_val * 100:+.1f}%) is outside "
                    "the organic buyback/issuance band and likely reflects a stock split "
                    "or share-basis discontinuity; dilution score neutralized to 0.50 and "
                    "per-share YoY metrics require manual verification."
                ),
            )
        )
    else:
        dilution_scores = [
            _assess_numeric_metric(
                work,
                key="shares_yoy",
                label="Share-count change",
                score_fn=_score_dilution,
                strong_score=0.80,
                weak_score=0.25,
                threshold_text="<=3% supportive; >12% weak",
                positives=positives,
                risks=risks,
                missing=missing,
            )
        ]

    valuation_scores = [
        _assess_numeric_metric(
            work,
            key="fcf_yield",
            label="FCF yield",
            score_fn=_score_fcf_yield,
            strong_score=0.75,
            weak_score=0.25,
            threshold_text=">=2% supportive; <-2% weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="ps_hist_percentile",
            label="Historical P/S percentile",
            score_fn=_valuation_score_fn,
            strong_score=0.70,
            weak_score=0.25,
            threshold_text="<=60% supportive; >80% expensive",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="pe_hist_percentile",
            label="Historical P/E percentile",
            score_fn=_valuation_score_fn,
            strong_score=0.70,
            weak_score=0.25,
            threshold_text="<=60% supportive; >80% expensive",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    red_flag_scores = [
        _assess_numeric_metric(
            work,
            key="receivables_growth_gap",
            label="Receivables growth gap",
            score_fn=_gap_score_fn(_score_receivables_gap),
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=5pp supportive; >25pp weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
        _assess_numeric_metric(
            work,
            key="inventory_growth_gap",
            label="Inventory growth gap",
            score_fn=_gap_score_fn(_score_inventory_gap),
            strong_score=0.80,
            weak_score=0.25,
            threshold_text="<=10pp supportive; >30pp weak",
            positives=positives,
            risks=risks,
            missing=missing,
        ),
    ]

    component_inputs = {
        "profitability_cash": profitability_cash_scores,
        "growth_stability": growth_scores,
        "balance_sheet": balance_scores,
        "dilution": dilution_scores,
        "valuation_context": valuation_scores,
        "operating_red_flags": red_flag_scores,
    }
    component_scores: dict[str, float | None] = {}
    component_coverage: dict[str, float] = {}
    effective_score = 0.0
    confidence = 0.0
    for name, scores in component_inputs.items():
        score, coverage = _component(scores)
        component_scores[name] = None if score is None else round(score, 6)
        component_coverage[name] = coverage
        weight = QUALITY_V1_COMPONENT_WEIGHTS[name]
        confidence += weight * coverage
        if score is not None:
            effective_score += weight * score * coverage

    shares_stale = work.get("shares_stale")
    if shares_stale is True:
        risks.append(
            _metric_item(
                code="shares_data_stale",
                label="Share-count data stale",
                polarity="negative",
                metric="shares_stale",
                value="true",
                threshold="false",
                message="Share-count provenance is stale and weakens dilution confidence.",
            )
        )

    decision_dt = _parse_iso_date(decision_date)
    data_dt = _parse_iso_date(data_asof)
    stale_unrated = False
    data_integrity_blocked = False
    normalized_data_asof = data_dt.isoformat() if data_dt is not None else None

    if work.get("fundamental_facts_cover_latest_periodic") is False:
        data_integrity_blocked = True
        confidence = min(confidence, 0.49)
        missing.append(
            _metric_item(
                code="latest_periodic_filing_not_covered",
                label="Latest periodic filing not covered",
                polarity="missing",
                metric="fundamental_latest_periodic_filing_date",
                value=work.get("fundamental_latest_periodic_filing_date"),
                threshold="latest periodic filing must be represented in recognized Company Facts",
                message=(
                    "SEC submissions show a newer periodic filing than the recognized "
                    "Company Facts used for Quality; stale metrics are not promoted."
                ),
            )
        )

    if work.get("fundamental_currency_supported") is False:
        data_integrity_blocked = True
        confidence = min(confidence, 0.49)
        missing.append(
            _metric_item(
                code="fundamental_currency_unsupported",
                label="Fundamental reporting currency unsupported",
                polarity="missing",
                metric="fundamental_reporting_currency",
                value=work.get("fundamental_reporting_currency"),
                threshold="USD monetary facts required by live valuation path",
                message=(
                    "Core monetary facts are available only in a non-USD reporting "
                    "currency; the live scanner will not mix them with USD market cap "
                    "without an explicit FX normalization layer."
                ),
            )
        )
    _entity_flag_present = "fundamental_operating_entity_verified" in work
    _entity_flag = work.get("fundamental_operating_entity_verified")
    if _entity_flag is False or (_entity_flag_present and _entity_flag is None):
        data_integrity_blocked = True
        confidence = min(confidence, 0.49)
        missing.append(
            _metric_item(
                code="operating_entity_unverified",
                label="Operating filing entity unverified",
                polarity="missing",
                metric="fundamental_operating_entity_detail",
                value=work.get("fundamental_operating_entity_detail"),
                threshold="ticker must map to the operating issuer with core facts",
                message=(
                    "The ticker->CIK binding does not verifiably represent the "
                    "operating issuer (ticker absent from the entity filing "
                    "record, an entity with filings but no revenue, net "
                    "income or operating-cash-flow facts, or an unchecked "
                    "binding). No reliable grade can be claimed; verify the "
                    "filing entity before use."
                ),
            )
        )
    if decision_dt is not None and data_dt is not None:
        if data_dt > decision_dt:
            raise ValueError(
                f"fundamental data_asof {data_dt.isoformat()} is after "
                f"decision_date {decision_dt.isoformat()}"
            )
        age_days = (decision_dt - data_dt).days
        if QUALITY_V2_PRE_EARNINGS_WARN_DAYS <= age_days <= QUALITY_V1_STALE_WARN_DAYS:
            # Pre-earnings window warning: informational only — it never
            # reduces score, confidence, or grade (priority ranking reads it).
            risks.append(
                _metric_item(
                    code="pre_earnings_window_risk",
                    label="Pre-earnings window (aging filing)",
                    polarity="negative",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<{QUALITY_V2_PRE_EARNINGS_WARN_DAYS}d before next quarterly window",
                    message=(
                        f"Latest periodic filing is {age_days}d old (~90d quarterly cycle); "
                        "next earnings release is likely imminent (binary event risk)."
                    ),
                )
            )
        if age_days > QUALITY_V1_STALE_UNRATED_DAYS:
            stale_unrated = True
            confidence = min(confidence, 0.49)
            risks.append(
                _metric_item(
                    code="fundamental_data_severely_stale",
                    label="Fundamental data severely stale",
                    polarity="negative",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<={QUALITY_V1_STALE_UNRATED_DAYS}",
                    message="Fundamental evidence is too stale to assign a rated Company Quality grade.",
                )
            )
        elif age_days > QUALITY_V1_STALE_WARN_DAYS:
            confidence *= 0.90
            risks.append(
                _metric_item(
                    code="fundamental_data_stale",
                    label="Fundamental data stale",
                    polarity="negative",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<={QUALITY_V1_STALE_WARN_DAYS}",
                    message="Fundamental evidence is older than the preferred freshness window.",
                )
            )
        elif not data_integrity_blocked:
            positives.append(
                _metric_item(
                    code="fundamental_data_fresh",
                    label="Fundamental data freshness",
                    polarity="positive",
                    metric="fundamental_data_age_days",
                    value=age_days,
                    threshold=f"<={QUALITY_V1_STALE_WARN_DAYS}",
                    message="Fundamental evidence is within the pre-registered freshness window.",
                )
            )
    elif data_dt is None:
        confidence = min(confidence, 0.79)
        missing.append(
            _metric_item(
                code="fundamental_data_asof_missing",
                label="Fundamental data as-of missing",
                polarity="missing",
                metric="fundamental_data_asof",
                value=None,
                threshold="required for Quality A",
                message="Filing freshness cannot be verified, so Quality A is suppressed.",
            )
        )

    severe_risks = 0
    severe_checks: list[tuple[float | None, Any]] = [
        (_finite_value(work, "net_debt_to_ebitda"), lambda x: x > 5.0),
        (_finite_value(work, "interest_coverage"), lambda x: x < 1.0),
        # Organic severe dilution only: a split/basis discontinuity above the
        # organic band must not count as a severe risk.
        (
            _finite_value(work, "shares_yoy"),
            lambda x: 0.15 < x <= QUALITY_V2_ORGANIC_SHARES_YOY_MAX,
        ),
    ]
    if not high_growth:
        severe_checks.extend(
            [
                (_finite_value(work, "receivables_growth_gap"), lambda x: x > 0.30),
                (_finite_value(work, "inventory_growth_gap"), lambda x: x > 0.35),
            ]
        )
    severe_risks += sum(
        1 for value, predicate in severe_checks if value is not None and predicate(value)
    )
    if (
        (_finite_value(work, "net_margin") or 0.0) < 0.0
        and (_finite_value(work, "free_cash_flow") or 0.0) < 0.0
    ):
        severe_risks += 1

    score = round(max(0.0, min(1.0, effective_score)), 6)
    confidence = round(max(0.0, min(1.0, confidence)), 6)
    profitability_score = component_scores["profitability_cash"]
    balance_score = component_scores["balance_sheet"]

    if stale_unrated or confidence < QUALITY_V1_MIN_CONFIDENCE_RATED:
        grade = QualityGrade.UNRATED
    elif (
        score >= QUALITY_V1_GRADE_A_MIN_SCORE
        and confidence >= QUALITY_V1_GRADE_A_MIN_CONFIDENCE
        and profitability_score is not None
        and profitability_score >= 0.60
        and balance_score is not None
        and balance_score >= 0.50
        and component_coverage["profitability_cash"] >= 0.75
        and component_coverage["balance_sheet"] >= (2.0 / 3.0)
        and severe_risks == 0
    ):
        grade = QualityGrade.A
    elif (
        score >= QUALITY_V1_GRADE_B_MIN_SCORE
        and confidence >= QUALITY_V1_GRADE_B_MIN_CONFIDENCE
        and severe_risks < 2
    ):
        grade = QualityGrade.B
    else:
        grade = QualityGrade.C

    return QualityDecision(
        grade=grade,
        score=score,
        confidence=confidence,
        component_scores=component_scores,
        positives=tuple(positives),
        risks=tuple(risks),
        missing=tuple(missing),
        data_asof=normalized_data_asof,
    )
