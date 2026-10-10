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
