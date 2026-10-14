"""Intermediate presentation layer (IR) between canonical StockDecision and renderers.

Track A owns this file. Track B owns selection/data-correctness files. The two
tracks meet only through the canonical ``StockDecision`` (schema_version="1")
consumed here via pure functions.

Nothing in this module recomputes Quality, Entry, or Action states. It only
formats evidence values into human-readable English strings, groups quality
evidence into the six canonical pillars, expands entry evidence into a fixed
seven-gate readiness checklist, and derives attention-focused inline summaries.

Forward compatibility with Track B (M1): entry-gate matching is metric-based
in addition to code-based, so new Track B ``EvidenceItem`` codes (e.g.
``relative_strength_60d_qqq_below_ready``, ``days_below_sma200_elevated``,
``price_to_sma50_outside_ready_band``) and ``share_count_basis`` provenance
keys are picked up with zero code changes here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
import math
from typing import Any

from ai_value_scanner.decision.model import (
    ActionState,
    EntryState,
    EvidenceItem,
    QualityGrade,
    StockDecision,
)

# ---------------------------------------------------------------------------
# Human-readable value formatting
# ---------------------------------------------------------------------------

_MONEY_METRICS = frozenset(
    {
        "free_cash_flow",
        "operating_cash_flow",
        "revenue",
        "net_income",
        "total_debt",
        "net_debt",
        "cash_and_equivalents",
        "market_cap",
    }
)

_SIGNED_PCT_METRICS = frozenset(
    {
        "revenue_yoy",
        "adjusted_net_income_yoy",
        "net_income_yoy",
        "operating_cash_flow_yoy",
        "shares_yoy",
        "return_20d",
        "return_60d",
        "relative_strength_60d_qqq",
        "receivables_growth_gap",
        "inventory_growth_gap",
    }
)

_LEVEL_PCT_METRICS = frozenset(
    {
        "net_margin",
        "accrual_ratio",
        "fcf_yield",
        "drawdown_from_52w_high",
        "volatility_60d",
    }
)

_HIST_PERCENTILE_METRICS = frozenset({"ps_hist_percentile", "pe_hist_percentile"})

_MULTIPLE_METRICS = frozenset(
    {
        "price_to_sma200",
        "price_to_sma50",
        "ocf_to_net_income",
        "net_debt_to_ebitda",
        "interest_coverage",
        "current_ratio",
    }
)

_DAY_COUNT_METRICS = frozenset(
    {"fundamental_data_age_days", "market_data_age_days", "days_below_sma200"}
)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def format_metric_value(metric: str | None, value: Any) -> str:
    """Format an evidence value into a human-readable English string.

    Returns ``"n/a"`` for ``None``/empty/non-finite values. String values for
    non-numeric metrics (e.g. regime ``"up"``) pass through stripped.
    """
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return "n/a"
        numeric = _as_float(token)
        if numeric is None:
            return token.replace("\n", " ")
        return format_metric_value(metric, numeric)
    number = _as_float(value)
    if number is None:
        text = str(value).strip()
        return text.replace("\n", " ") if text else "n/a"

    if metric in _MONEY_METRICS:
        magnitude = abs(number)
        if magnitude >= 1e9:
            scaled = magnitude / 1e9
            return f"-${scaled:,.2f}B" if number < 0 else f"${scaled:,.2f}B"
        if magnitude >= 1e6:
            scaled = magnitude / 1e6
            return f"-${scaled:,.1f}M" if number < 0 else f"${scaled:,.1f}M"
        if number < 0:
            return f"-${magnitude:,.0f}"
        return f"${magnitude:,.0f}"
    if metric in _SIGNED_PCT_METRICS:
        return f"{number * 100:+.1f}%"
    if metric in _LEVEL_PCT_METRICS:
        return f"{number * 100:.1f}%"
    if metric in _HIST_PERCENTILE_METRICS:
        return f"{number * 100:.0f}th pctl"
    if metric == "range_position_52w":
        return f"{number * 100:.0f}% of 52w range"
    if metric in _MULTIPLE_METRICS:
        return f"{number:.2f}x"
    if metric in _DAY_COUNT_METRICS:
        return f"{int(round(number))}d"
    # Fallback for metrics outside the contract: compact, deterministic, and
    # never a long raw float.
    magnitude = abs(number)
    if magnitude >= 1000:
        return f"{number:,.0f}"
    if magnitude >= 1:
        return f"{number:.2f}"
    if magnitude == 0:
        return "0"
    return f"{number:.4f}"


# ---------------------------------------------------------------------------
# Presentation IR dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormattedEvidenceRow:
    code: str
    label: str
    polarity: str  # "positive" | "negative" | "neutral" | "missing"
    metric: str | None
    formatted_value: str  # e.g. "$15.15B", "+23.9%", "1.03x", "n/a"
    target_band: str  # e.g. ">=10% supportive; <0% weak"
    summary_text: str  # Concise English phrase, e.g. "Free cash flow: $15.15B"


@dataclass(frozen=True)
class QualityPillarRow:
    pillar_key: str  # e.g. "profitability_cash"
    pillar_label: str  # e.g. "Profitability & Cash Conversion"
    score_display: str  # e.g. "0.80" or "MISSING"
    status_badge: str  # "STRONG" | "MIXED" | "WEAK" | "MISSING"
    supporting_items: tuple[FormattedEvidenceRow, ...]
    risk_or_missing_items: tuple[FormattedEvidenceRow, ...]


@dataclass(frozen=True)
class EntryGateCheckRow:
    gate_key: str  # "freshness", "sma200_trend", "sma50_band", ...
    gate_label: str  # e.g. "Long-Term Trend (Price / SMA200)"
    status: str  # "PASS" | "FAIL_BLOCKER" | "SILENT_OR_UNOBSERVED"
    observed_display: str  # e.g. "1.17x" or "Not in READY band (silent in v1)"
    target_display: str  # e.g. ">= 1.00x (Damaged < 0.95x)"
    note: str


@dataclass(frozen=True)
class DataTrustBadge:
    overall_status: str  # "VERIFIED" | "CAUTION_LAG_OR_FALLBACK" | "UNVERIFIED_OR_SCOPE_RISK"
    entity_display: str  # e.g. "Salesforce, Inc. (CIK 0001108524)" or "UNVERIFIED"
    share_basis_display: str  # e.g. "point_in_time_outstanding" or "legacy_unspecified"
    freshness_display: str  # e.g. "Fund: 2026-08-27 (46d) | Mkt: 2026-10-12 (0d)"
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StockCardViewModel:
    decision: StockDecision
    rank: int
    symbol: str
    company_name: str
    action_state: str
    quality_grade: str
    quality_score_display: str
    quality_confidence_display: str
    entry_state: str
    entry_score_display: str
    entry_confidence_display: str
    top_positives_inline: str  # 2-3 concise formatted bullets for summary table
    top_risks_or_blockers_inline: str  # 1-2 concise risks or silent-gate note
    next_trigger_inline: str
    data_trust: DataTrustBadge
    quality_pillars: tuple[QualityPillarRow, ...]
    entry_checklist: tuple[EntryGateCheckRow, ...]
    all_counter_evidence: tuple[FormattedEvidenceRow, ...]
    all_missing_evidence: tuple[FormattedEvidenceRow, ...]


@dataclass(frozen=True)
class SnapshotViewModel:
    title: str
    cadence: str | None
    decision_date: str
    primary_cards: tuple[StockCardViewModel, ...]
    cap_omitted_priority_cards: tuple[StockCardViewModel, ...]
    secondary_b_ready_cards: tuple[StockCardViewModel, ...]


# ---------------------------------------------------------------------------
# Quality pillars
# ---------------------------------------------------------------------------

_PILLAR_ORDER: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "profitability_cash",
        "Profitability & Cash Conversion",
        frozenset({"net_margin", "free_cash_flow", "ocf_to_net_income", "accrual_ratio"}),
    ),
    (
        "growth_stability",
        "Growth & Stability",
        frozenset(
            {
                "revenue_yoy",
                "adjusted_net_income_yoy",
                "net_income_yoy",
                "operating_cash_flow_yoy",
            }
        ),
    ),
    (
        "balance_sheet",
        "Balance Sheet & Solvency",
        frozenset({"net_debt_to_ebitda", "interest_coverage", "current_ratio"}),
    ),
    (
        "dilution",
        "Share Count & Dilution",
        frozenset({"shares_yoy", "shares_stale"}),
    ),
    (
        "valuation_context",
        "Valuation Context",
        frozenset({"fcf_yield", "ps_hist_percentile", "pe_hist_percentile"}),
    ),
    (
        "operating_red_flags",
        "Operating & Accounting Red Flags",
        frozenset(
            {
                "receivables_growth_gap",
                "inventory_growth_gap",
                "fundamental_data_age_days",
                "fundamental_data_asof",
                "fundamental_latest_periodic_filing_date",
                "fundamental_operating_entity_detail",
                "fundamental_reporting_currency",
                "shares_stale",
            }
        ),
    ),
)

_PILLAR_METRIC_TO_KEY: dict[str, str] = {}
for _key, _label, _metrics in _PILLAR_ORDER:
    for _metric in _metrics:
        _PILLAR_METRIC_TO_KEY.setdefault(_metric, _key)


def _short_label(label: str) -> str:
    text = (label or "").strip().replace("\n", " ")
    for suffix in (" supportive", " weak", " missing"):
        if text.endswith(suffix):
            return text[: -len(suffix)].strip() or text
    return text


def _format_evidence_row(item: EvidenceItem) -> FormattedEvidenceRow:
    formatted = format_metric_value(item.metric, item.value)
    target = "n/a" if item.threshold is None else str(item.threshold).replace("\n", " ")
    short = _short_label(item.label)
    return FormattedEvidenceRow(
        code=item.code,
        label=item.label,
        polarity=item.polarity,
        metric=item.metric,
        formatted_value=formatted,
        target_band=target if target.strip() else "n/a",
        summary_text=f"{short}: {formatted}",
    )


def _pillar_status_badge(score: float | None) -> str:
    if score is None:
        return "MISSING"
    if score >= 0.70:
        return "STRONG"
    if score >= 0.40:
        return "MIXED"
    return "WEAK"


def _build_quality_pillars(decision: StockDecision) -> tuple[QualityPillarRow, ...]:
    by_pillar_support: dict[str, list[FormattedEvidenceRow]] = {
        key: [] for key, _, _ in _PILLAR_ORDER
    }
    by_pillar_risk: dict[str, list[FormattedEvidenceRow]] = {
        key: [] for key, _, _ in _PILLAR_ORDER
    }
    for item in decision.quality.positives:
        pillar = _PILLAR_METRIC_TO_KEY.get(item.metric or "", "operating_red_flags")
        by_pillar_support[pillar].append(_format_evidence_row(item))
    for item in (*decision.quality.risks, *decision.quality.missing):
        pillar = _PILLAR_METRIC_TO_KEY.get(item.metric or "", "operating_red_flags")
        by_pillar_risk[pillar].append(_format_evidence_row(item))
    rows: list[QualityPillarRow] = []
    for key, label, _metrics in _PILLAR_ORDER:
        score = decision.quality.component_scores.get(key)
        rows.append(
            QualityPillarRow(
                pillar_key=key,
                pillar_label=label,
                score_display="MISSING" if score is None else f"{float(score):.2f}",
                status_badge=_pillar_status_badge(
                    None if score is None else float(score)
                ),
                supporting_items=tuple(by_pillar_support[key]),
                risk_or_missing_items=tuple(by_pillar_risk[key]),
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Entry readiness gate checklist
# ---------------------------------------------------------------------------

# Each gate lists the canonical v1 positive/negative codes plus the Track B M1
# codes known at contract time. Matching ALSO falls back to the evidence
# metric, so future codes with the same metric are picked up with zero changes.
_GATE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "gate_key": "freshness",
        "gate_label": "Data Freshness (Market As-Of)",
        "metrics": frozenset({"market_data_age_days", "market_asof"}),
        "positive_codes": frozenset({"market_data_fresh"}),
        "negative_codes": frozenset(
            {
                "market_asof_missing",
                "market_data_severely_stale",
                "market_data_stale",
            }
        ),
        "target_display": "<=3d fresh; >7d insufficient",
    },
    {
        "gate_key": "sma200_trend",
        "gate_label": "Long-Term Trend (Price / SMA200)",
        "metrics": frozenset({"price_to_sma200", "days_below_sma200"}),
        "positive_codes": frozenset({"price_above_sma200"}),
        "negative_codes": frozenset(
            {
                "price_materially_below_sma200",
                "price_below_sma200_trend",
                "days_below_sma200_elevated",
            }
        ),
        "target_display": ">= 1.00x (Damaged < 0.95x)",
    },
    {
        "gate_key": "sma50_band",
        "gate_label": "Short-Term Band (Price / SMA50)",
        "metrics": frozenset({"price_to_sma50"}),
        "positive_codes": frozenset({"price_near_sma50_ready_band"}),
        "negative_codes": frozenset(
            {
                "price_extended_above_sma50",
                "price_below_sma50",
                "price_to_sma50_outside_ready_band",
            }
        ),
        "target_display": "0.98-1.08 READY band",
    },
    {
        "gate_key": "ret20_band",
        "gate_label": "Recent Momentum (20d Return)",
        "metrics": frozenset({"return_20d"}),
        "positive_codes": frozenset({"return_20d_ready_band"}),
        "negative_codes": frozenset(
            {"return_20d_overextended", "return_20d_outside_ready_band"}
        ),
        "target_display": "-3% to +12% READY band",
    },
    {
        "gate_key": "ret60_trend",
        "gate_label": "Medium-Term Momentum (60d Return)",
        "metrics": frozenset(
            {"return_60d", "drawdown_from_52w_high", "range_position_52w"}
        ),
        "positive_codes": frozenset({"return_60d_nonnegative"}),
        "negative_codes": frozenset(
            {
                "return_60d_weak",
                "return_60d_slightly_negative",
                "drawdown_from_52w_high_deep",
            }
        ),
        "target_display": ">= 0% READY",
    },
    {
        "gate_key": "rs60_qqq",
        "gate_label": "Relative Strength (60d vs QQQ)",
        "metrics": frozenset({"relative_strength_60d_qqq"}),
        "positive_codes": frozenset({"relative_strength_60d_qqq_ready"}),
        "negative_codes": frozenset(
            {
                "relative_strength_60d_qqq_weak",
                "relative_strength_60d_qqq_below_candidate_ready",
                "relative_strength_60d_qqq_below_ready",
            }
        ),
        "target_display": ">= -3% READY",
    },
    {
        "gate_key": "regime",
        "gate_label": "Market Regime",
        "metrics": frozenset({"regime"}),
        "positive_codes": frozenset({"supportive_market_regime"}),
        "negative_codes": frozenset({"defensive_market_regime"}),
        "target_display": "Supportive (not defensive)",
    },
)

_SILENT_OBSERVED_DISPLAY = "Not in READY band (silent in v1)"


def _gate_matches(
    items: tuple[EvidenceItem, ...],
    *,
    codes: frozenset[str],
    metrics: frozenset[str],
) -> list[EvidenceItem]:
    matched: list[EvidenceItem] = []
    for item in items:
        if item.code in codes or (item.metric or "") in metrics:
            matched.append(item)
    return matched


def _build_entry_checklist(decision: StockDecision) -> tuple[EntryGateCheckRow, ...]:
    rows: list[EntryGateCheckRow] = []
    for gate in _GATE_DEFS:
        metrics: frozenset[str] = gate["metrics"]
        pos = _gate_matches(
            decision.entry.positives,
            codes=gate["positive_codes"],
            metrics=metrics,
        )
        neg = _gate_matches(
            decision.entry.risks,
            codes=gate["negative_codes"],
            metrics=metrics,
        )
        if neg:
            item = neg[0]
            rows.append(
                EntryGateCheckRow(
                    gate_key=gate["gate_key"],
                    gate_label=gate["gate_label"],
                    status="FAIL_BLOCKER",
                    observed_display=format_metric_value(item.metric, item.value),
                    target_display=gate["target_display"],
                    note=item.message.replace("\n", " "),
                )
            )
        elif pos:
            item = pos[0]
            rows.append(
                EntryGateCheckRow(
                    gate_key=gate["gate_key"],
                    gate_label=gate["gate_label"],
                    status="PASS",
                    observed_display=format_metric_value(item.metric, item.value),
                    target_display=gate["target_display"],
                    note=item.message.replace("\n", " "),
                )
            )
        else:
            rows.append(
                EntryGateCheckRow(
                    gate_key=gate["gate_key"],
                    gate_label=gate["gate_label"],
                    status="SILENT_OR_UNOBSERVED",
                    observed_display=_SILENT_OBSERVED_DISPLAY,
                    target_display=gate["target_display"],
                    note=(
                        f"{gate['gate_label']} did not confirm ENTRY_READY in "
                        "this snapshot; treat as an unmet gate."
                    ),
                )
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Inline summaries
# ---------------------------------------------------------------------------

_FRESHNESS_POSITIVE_CODES = frozenset(
    {"fundamental_data_fresh", "market_data_fresh"}
)


def _inline_fragment(item: EvidenceItem) -> str:
    formatted = format_metric_value(item.metric, item.value)
    short = _short_label(item.label)
    if formatted == "n/a":
        return short
    return f"{short} {formatted}"


def _build_top_positives_inline(decision: StockDecision) -> str:
    candidates = [
        item
        for item in (*decision.quality.positives, *decision.entry.positives)
        if item.code not in _FRESHNESS_POSITIVE_CODES
    ]
    fragments = [_inline_fragment(item) for item in candidates[:3]]
    fragments = [fragment for fragment in fragments if fragment.strip()]
    return "; ".join(fragments) if fragments else "none"


def _build_top_risks_inline(
    decision: StockDecision,
    checklist: tuple[EntryGateCheckRow, ...],
) -> str:
    candidates = (*decision.quality.risks, *decision.entry.risks)
    fragments = [_inline_fragment(item) for item in candidates[:2]]
    fragments = [fragment for fragment in fragments if fragment.strip()]
    if (
        decision.entry.state is not EntryState.ENTRY_READY
        and not decision.entry.risks
    ):
        unmet = [row.gate_key for row in checklist if row.status != "PASS"]
        if unmet:
            fragments.append(f"Unmet READY gate(s): {', '.join(unmet)}")
    if fragments:
        return "; ".join(fragments)
    if decision.action_state is not ActionState.PRIORITY_REVIEW:
        unmet = [row.gate_key for row in checklist if row.status != "PASS"]
        if unmet:
            return f"Unmet READY gate(s): {', '.join(unmet)}"
        return "See detailed evidence."
    return "none"


# ---------------------------------------------------------------------------
# Data trust badge
# ---------------------------------------------------------------------------

_SEVERE_STALE_CODES = frozenset(
    {"fundamental_data_severely_stale", "market_data_severely_stale"}
)
_STALE_CODES = frozenset(
    {
        "fundamental_data_severely_stale",
        "fundamental_data_stale",
        "market_data_severely_stale",
        "market_data_stale",
    }
)


def _parse_iso_day(value: str | None) -> date | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token[:10])
    except ValueError:
        return None


def _freshness_token(asof: str | None, decision_day: date | None) -> str:
    if asof is None:
        return "n/a"
    asof_day = _parse_iso_day(asof)
    if asof_day is None or decision_day is None:
        return asof
    return f"{asof} ({(decision_day - asof_day).days}d)"


def _build_data_trust_badge(decision: StockDecision) -> DataTrustBadge:
    quality_codes = {item.code for item in decision.quality.missing}
    risk_codes = {
        item.code for item in (*decision.quality.risks, *decision.entry.risks)
    }
    identity_unverified = "operating_entity_unverified" in quality_codes
    severely_stale = bool(risk_codes & _SEVERE_STALE_CODES)
    stale = bool(risk_codes & _STALE_CODES)
    asof_missing = (
        decision.quality.data_asof is None or decision.entry.market_asof is None
    )
    unrated = decision.quality.grade is QualityGrade.UNRATED
    fallback_used = decision.provenance.get("fundamental_edgartools_fallback_used") is True
    share_basis_raw = decision.provenance.get("share_count_basis")
    if share_basis_raw is None:
        share_basis_raw = decision.provenance.get("share_basis")
    share_basis = (
        str(share_basis_raw).strip() if share_basis_raw is not None else ""
    ) or "legacy_unspecified"
    explicit_scope_risk = share_basis != "legacy_unspecified" and any(
        token in share_basis.lower()
        for token in ("unverified", "legacy", "unspecified", "fallback", "scope")
    ) and "point_in_time" not in share_basis.lower()

    if identity_unverified or unrated or severely_stale or asof_missing or explicit_scope_risk:
        status = "UNVERIFIED_OR_SCOPE_RISK"
    elif stale or fallback_used:
        status = "CAUTION_LAG_OR_FALLBACK"
    else:
        status = "VERIFIED"

    if identity_unverified:
        entity_display = "UNVERIFIED"
    else:
        cik = decision.provenance.get("cik")
        cik_text = str(cik).strip() if cik is not None else ""
        name = (decision.company_name or "").strip()
        if name and cik_text:
            entity_display = f"{name} (CIK {cik_text})"
        elif name:
            entity_display = name
        elif cik_text:
            entity_display = f"CIK {cik_text}"
        else:
            entity_display = "n/a"

    decision_day = _parse_iso_day(decision.decision_date)
    freshness_display = (
        f"Fund: {_freshness_token(decision.quality.data_asof, decision_day)}"
        f" | Mkt: {_freshness_token(decision.entry.market_asof, decision_day)}"
    )

    warnings: list[str] = []
    if identity_unverified:
        warnings.append(
            "Filing-entity identity UNVERIFIED: ticker->CIK binding does not "
            "verifiably represent the operating issuer."
        )
    if severely_stale:
        warnings.append("Severely stale data: levels are indicative, not current.")
    elif stale:
        warnings.append("Data ageing: check as-of dates before acting on this review.")
    if asof_missing:
        warnings.append(
            "Data as-of MISSING: freshness cannot be verified; "
            "do not read this review as current."
        )
    if unrated:
        warnings.append("Company Quality UNRATED: no reliable company judgement exists.")
    if fallback_used:
        warnings.append("SEC fallback facts used for fundamentals; verify coverage.")
    if explicit_scope_risk:
        warnings.append(f"Share-count basis scope risk: {share_basis}.")
    return DataTrustBadge(
        overall_status=status,
        entity_display=entity_display,
        share_basis_display=share_basis,
        freshness_display=freshness_display,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Card + snapshot builders
# ---------------------------------------------------------------------------


def _confidence_display(confidence: float) -> str:
    return f"{float(confidence) * 100:.0f}%"


def _score_display(score: float | None) -> str:
    return "n/a" if score is None else f"{float(score):.2f}"


def build_stock_card_view_model(
    decision: StockDecision,
    rank: int | None = None,
) -> StockCardViewModel:
    """Build the presentation view model for one canonical decision.

    ``rank`` defaults to the decision's global ``priority`` so callers that
    only have the decision still render a meaningful rank.
    """
    checklist = _build_entry_checklist(decision)
    counter = tuple(
        _format_evidence_row(item)
        for item in (
            *decision.quality.risks,
            *(
                item
                for item in decision.entry.risks
                if item.polarity in ("negative", "neutral")
            ),
        )
    )
    missing = tuple(
        _format_evidence_row(item)
        for item in (
            *decision.quality.missing,
            *(
                item
                for item in decision.entry.risks
                if item.polarity == "missing"
            ),
        )
    )
    # Entry risks with any other polarity (defensive: should not occur in v1)
    # are still surfaced rather than dropped.
    other_entry = tuple(
        item
        for item in decision.entry.risks
        if item.polarity not in ("negative", "neutral", "missing")
    )
    if other_entry:
        counter = counter + tuple(_format_evidence_row(item) for item in other_entry)
    trigger = (decision.review_trigger or "n/a").replace("\n", " ").strip() or "n/a"
    return StockCardViewModel(
        decision=decision,
        rank=decision.priority if rank is None else int(rank),
        symbol=decision.symbol,
        company_name=(decision.company_name or "").strip() or decision.symbol,
        action_state=decision.action_state.value,
        quality_grade=decision.quality.grade.value,
        quality_score_display=_score_display(decision.quality.score),
        quality_confidence_display=_confidence_display(decision.quality.confidence),
        entry_state=decision.entry.state.value,
        entry_score_display=_score_display(decision.entry.score),
        entry_confidence_display=_confidence_display(decision.entry.confidence),
        top_positives_inline=_build_top_positives_inline(decision),
        top_risks_or_blockers_inline=_build_top_risks_inline(decision, checklist),
        next_trigger_inline=trigger,
        data_trust=_build_data_trust_badge(decision),
        quality_pillars=_build_quality_pillars(decision),
        entry_checklist=checklist,
        all_counter_evidence=counter,
        all_missing_evidence=missing,
    )


def _priority_order_key(decision: StockDecision) -> tuple[Any, ...]:
    return (decision.priority, decision.symbol)


def build_snapshot_view_model(
    primary_decisions: Iterable[StockDecision],
    all_decisions: Iterable[StockDecision] | None = None,
    title: str = "Action List",
    cadence: str | None = None,
    attention_cap: int = 15,
) -> SnapshotViewModel:
    """Build the snapshot-level view model.

    ``primary_decisions`` is the capped shortlist (daily/weekly attention) in
    display order. When ``all_decisions`` is provided, the Secondary Radar is
    populated: cap-omitted ``PRIORITY_REVIEW`` names plus top ``Quality B +
    ENTRY_READY`` names, each up to 5, ordered by priority and excluding
    primary symbols. ``attention_cap`` documents the attention cap behind the
    primary list; the caller passes the already-capped list.
    """
    _ = attention_cap
    primary = tuple(primary_decisions)
    primary_symbols = {decision.symbol for decision in primary}
    primary_cards = tuple(
        build_stock_card_view_model(decision) for decision in primary
    )
    if primary:
        decision_day = primary[0].decision_date
    elif all_decisions is not None:
        materialized = tuple(all_decisions)
        decision_day = materialized[0].decision_date if materialized else "n/a"
        all_decisions = materialized
    else:
        decision_day = "n/a"
    cap_omitted: tuple[StockCardViewModel, ...] = ()
    secondary_b: tuple[StockCardViewModel, ...] = ()
    if all_decisions is not None:
        ordered = sorted(tuple(all_decisions), key=_priority_order_key)
        cap_omitted = tuple(
            build_stock_card_view_model(decision)
            for decision in ordered
            if decision.action_state is ActionState.PRIORITY_REVIEW
            and decision.symbol not in primary_symbols
        )[:5]
        secondary_b = tuple(
            build_stock_card_view_model(decision)
            for decision in ordered
            if decision.quality.grade is QualityGrade.B
            and decision.entry.state is EntryState.ENTRY_READY
            and decision.symbol not in primary_symbols
        )[:5]
    return SnapshotViewModel(
        title=title,
        cadence=cadence,
        decision_date=decision_day,
        primary_cards=primary_cards,
        cap_omitted_priority_cards=cap_omitted,
        secondary_b_ready_cards=secondary_b,
    )
