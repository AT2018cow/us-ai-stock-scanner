"""Intermediate presentation layer (IR) between canonical StockDecision and renderers.

Transforms canonical ``StockDecision`` objects into clean, analyst-grade,
mobile-first view models with human-readable numbers (`$15.15B`, `+23.6%`,
`1.03x`, `100th pctl`), cross-pillar highlight selection, and relative-only
paths—never leaking absolute filesystem paths or internal machine enums.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
import math
from pathlib import PurePath
from typing import Any

from ai_value_scanner.decision.model import (
    ActionState,
    EntryState,
    EvidenceItem,
    QualityGrade,
    StockDecision,
)

# ---------------------------------------------------------------------------
# Human-readable value formatting & compact analyst labels
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

_COMPACT_METRIC_LABELS: dict[str, str] = {
    "net_margin": "Margin",
    "free_cash_flow": "FCF",
    "operating_cash_flow": "OCF",
    "ocf_to_net_income": "OCF/NI",
    "accrual_ratio": "Accrual",
    "revenue_yoy": "Rev YoY",
    "adjusted_net_income_yoy": "EPS YoY",
    "net_income_yoy": "NI YoY",
    "operating_cash_flow_yoy": "OCF YoY",
    "net_debt_to_ebitda": "NetDebt/EBITDA",
    "interest_coverage": "IntCov",
    "current_ratio": "CurrRatio",
    "shares_yoy": "Shares YoY",
    "fcf_yield": "FCF Yield",
    "ps_hist_percentile": "P/S",
    "pe_hist_percentile": "P/E",
    "receivables_growth_gap": "AR Gap",
    "inventory_growth_gap": "Inv Gap",
    "price_to_sma200": "SMA200",
    "price_to_sma50": "SMA50",
    "days_below_sma200": "Below SMA200",
    "return_20d": "20d Ret",
    "return_60d": "60d Ret",
    "relative_strength_60d_qqq": "RS60",
    "drawdown_from_52w_high": "52w DD",
    "range_position_52w": "52w Range",
    "volatility_60d": "Vol60d",
    "fundamental_data_age_days": "Fund Age",
    "market_data_age_days": "Mkt Age",
    "regime": "Regime",
}

# Priority order for selecting cross-pillar fundamental highlights so cards
# show growth + cash/margin + valuation/balance-sheet rather than only the
# first 4 profitability metrics.
_HIGHLIGHT_METRIC_PRIORITY: tuple[str, ...] = (
    "revenue_yoy",
    "adjusted_net_income_yoy",
    "net_margin",
    "free_cash_flow",
    "fcf_yield",
    "ocf_to_net_income",
    "net_debt_to_ebitda",
    "shares_yoy",
    "pe_hist_percentile",
    "ps_hist_percentile",
    "operating_cash_flow_yoy",
    "interest_coverage",
    "current_ratio",
    "accrual_ratio",
)


def sanitize_relative_display(value: Any) -> str:
    """Ensure no absolute filesystem path (/home/..., /tmp/..., C:\\...) leaks into reports."""
    if value is None or value == "":
        return "n/a"
    text = str(value).replace("\n", " ").strip()
    if not text:
        return "n/a"
    if text.startswith(("/home/", "/tmp/", "/Users/", "/var/", "/opt/", "/root/")):
        parts = PurePath(text).parts
        if len(parts) >= 2:
            return "/".join(parts[-2:])
        return PurePath(text).name
    return text


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def format_metric_value(metric: str | None, value: Any) -> str:
    """Format an evidence value into a human-readable English string."""
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
            return sanitize_relative_display(token)
        return format_metric_value(metric, numeric)
    number = _as_float(value)
    if number is None:
        text = str(value).strip()
        return sanitize_relative_display(text) if text else "n/a"

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
    polarity: str
    metric: str | None
    formatted_value: str
    target_band: str
    summary_text: str


@dataclass(frozen=True)
class QualityPillarRow:
    pillar_key: str
    pillar_label: str
    score_display: str
    status_badge: str
    supporting_items: tuple[FormattedEvidenceRow, ...]
    risk_or_missing_items: tuple[FormattedEvidenceRow, ...]


@dataclass(frozen=True)
class EntryGateCheckRow:
    gate_key: str
    gate_label: str
    status: str  # "PASS" | "FAIL_BLOCKER" | "SILENT_OR_UNOBSERVED"
    human_status: str  # "PASS" | "WAIT" | "EXTENDED" | "DAMAGED"
    short_tag: str  # Ultra-short tag for summary header, e.g. "20d mom", "RS60"
    observed_display: str
    target_display: str
    human_summary: str
    note: str


@dataclass(frozen=True)
class DataTrustBadge:
    overall_status: str
    human_status: str
    entity_display: str
    share_basis_display: str
    freshness_display: str
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
    accordion_Tagline: str  # Ultra-concise 1-line hook for <summary> and Quick Index
    quality_highlights_inline: str
    entry_Snapshot_inline: str
    entry_blockers_inline: str
    fundamental_watchouts_inline: str
    top_positives_inline: str
    top_risks_or_blockers_inline: str
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
        "Profit & Cash",
        frozenset({"net_margin", "free_cash_flow", "ocf_to_net_income", "accrual_ratio"}),
    ),
    (
        "growth_stability",
        "Growth",
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
        "Balance Sheet",
        frozenset({"net_debt_to_ebitda", "interest_coverage", "current_ratio"}),
    ),
    (
        "dilution",
        "Dilution",
        frozenset({"shares_yoy", "shares_stale"}),
    ),
    (
        "valuation_context",
        "Valuation",
        frozenset({"fcf_yield", "ps_hist_percentile", "pe_hist_percentile"}),
    ),
    (
        "operating_red_flags",
        "Red Flags",
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


def _compact_label(item: EvidenceItem) -> str:
    if item.metric and item.metric in _COMPACT_METRIC_LABELS:
        return _COMPACT_METRIC_LABELS[item.metric]
    return _short_label(item.label)


def _format_evidence_row(item: EvidenceItem) -> FormattedEvidenceRow:
    formatted = format_metric_value(item.metric, item.value)
    target = "n/a" if item.threshold is None else str(item.threshold).replace("\n", " ")
    target = target.replace("|accrual|", "abs(accrual)")
    short = _compact_label(item)
    return FormattedEvidenceRow(
        code=item.code,
        label=item.label,
        polarity=item.polarity,
        metric=item.metric,
        formatted_value=formatted,
        target_band=target if target.strip() else "n/a",
        summary_text=f"{short}: {formatted}" if formatted != "n/a" else short,
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
        if item.code == "fundamental_data_fresh":
            continue
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
                score_display="n/a" if score is None else f"{float(score):.2f}",
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

_GATE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "gate_key": "freshness",
        "gate_label": "Data Age",
        "short_tag": "data age",
        "metrics": frozenset({"market_data_age_days", "market_asof"}),
        "positive_codes": frozenset({"market_data_fresh"}),
        "negative_codes": frozenset(
            {
                "market_asof_missing",
                "market_data_severely_stale",
                "market_data_stale",
            }
        ),
        "target_display": "<= 3d",
        "silent_summary": "Market data > 3d old",
    },
    {
        "gate_key": "sma200_trend",
        "gate_label": "SMA200 Trend",
        "short_tag": "SMA200",
        "metrics": frozenset({"price_to_sma200", "days_below_sma200"}),
        "positive_codes": frozenset({"price_above_sma200"}),
        "negative_codes": frozenset(
            {
                "price_materially_below_sma200",
                "price_below_sma200_trend",
                "days_below_sma200_elevated",
            }
        ),
        "target_display": ">= 1.00x",
        "silent_summary": "Slightly below SMA200 (0.95x–1.00x; need >= 1.00x)",
    },
    {
        "gate_key": "sma50_band",
        "gate_label": "SMA50 Band",
        "short_tag": "SMA50 band",
        "metrics": frozenset({"price_to_sma50"}),
        "positive_codes": frozenset({"price_near_sma50_ready_band"}),
        "negative_codes": frozenset(
            {
                "price_extended_above_sma50",
                "price_below_sma50",
                "price_to_sma50_outside_ready_band",
            }
        ),
        "target_display": "0.98x–1.08x",
        "silent_summary": "Outside SMA50 band (need 0.98x–1.08x)",
    },
    {
        "gate_key": "ret20_band",
        "gate_label": "20d Momentum",
        "short_tag": "20d mom",
        "metrics": frozenset({"return_20d"}),
        "positive_codes": frozenset({"return_20d_ready_band"}),
        "negative_codes": frozenset(
            {"return_20d_overextended", "return_20d_outside_ready_band"}
        ),
        "target_display": "-3% to +12%",
        "silent_summary": "20d return outside -3%..+12% band",
    },
    {
        "gate_key": "ret60_trend",
        "gate_label": "60d Momentum",
        "short_tag": "60d trend",
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
        "target_display": ">= 0%",
        "silent_summary": "60d return slightly negative (-8%..0%; need >= 0%)",
    },
    {
        "gate_key": "rs60_qqq",
        "gate_label": "60d RS vs QQQ",
        "short_tag": "RS60 vs QQQ",
        "metrics": frozenset({"relative_strength_60d_qqq"}),
        "positive_codes": frozenset({"relative_strength_60d_qqq_ready"}),
        "negative_codes": frozenset(
            {
                "relative_strength_60d_qqq_weak",
                "relative_strength_60d_qqq_below_candidate_ready",
                "relative_strength_60d_qqq_below_ready",
            }
        ),
        "target_display": ">= -3.0%",
        "silent_summary": "60d RS vs QQQ slightly below -3% gate",
    },
    {
        "gate_key": "regime",
        "gate_label": "Market Regime",
        "short_tag": "regime",
        "metrics": frozenset({"regime"}),
        "positive_codes": frozenset({"supportive_market_regime"}),
        "negative_codes": frozenset({"defensive_market_regime"}),
        "target_display": "Supportive",
        "silent_summary": "Market regime not supportive",
    },
)


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


def _human_gate_blocker_phrase(
    gate_key: str, item: EvidenceItem, formatted: str
) -> tuple[str, str, str]:
    """Return (human_status, short_tag_with_val, natural_english_phrase)."""
    code = item.code
    if code in {"price_extended_above_sma50", "return_20d_overextended"}:
        if gate_key == "sma50_band":
            return (
                "EXTENDED",
                f"SMA50 {formatted}",
                f"Extended above SMA50 ({formatted}; wait for 0.98x–1.08x)",
            )
        return (
            "EXTENDED",
            f"20d {formatted}",
            f"20d return overextended ({formatted}; wait for <= +12%)",
        )
    if code in {"price_materially_below_sma200", "days_below_sma200_elevated"}:
        if code == "days_below_sma200_elevated":
            return (
                "DAMAGED",
                f"{formatted} < SMA200",
                f"Spent {formatted} below SMA200 (need < 15d)",
            )
        return (
            "DAMAGED",
            f"SMA200 {formatted}",
            f"Below SMA200 ({formatted}; damaged < 0.95x)",
        )
    if gate_key == "sma200_trend":
        return ("WAIT", f"SMA200 {formatted}", f"Below SMA200 ({formatted}; need >= 1.00x)")
    if gate_key == "sma50_band":
        return ("WAIT", f"SMA50 {formatted}", f"SMA50 at {formatted} (need 0.98x–1.08x)")
    if gate_key == "ret20_band":
        return ("WAIT", f"20d {formatted}", f"20d return at {formatted} (need -3%..+12%)")
    if gate_key == "ret60_trend":
        if item.metric == "drawdown_from_52w_high":
            return ("WAIT", f"52w DD {formatted}", f"52w drawdown {formatted} (> 22% cap)")
        return ("WAIT", f"60d {formatted}", f"60d return weak at {formatted} (need >= 0%)")
    if gate_key == "rs60_qqq":
        return ("WAIT", f"RS60 {formatted}", f"60d RS vs QQQ at {formatted} (need >= -3%)")
    if gate_key == "regime":
        return ("WAIT", "Defensive regime", "Defensive regime (need RS >= +5%)")
    return ("WAIT", f"{_compact_label(item)} {formatted}", f"{_compact_label(item)} at {formatted}")


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
            formatted = format_metric_value(item.metric, item.value)
            h_status, s_tag, h_phrase = _human_gate_blocker_phrase(
                gate["gate_key"], item, formatted
            )
            rows.append(
                EntryGateCheckRow(
                    gate_key=gate["gate_key"],
                    gate_label=gate["gate_label"],
                    status="FAIL_BLOCKER",
                    human_status=h_status,
                    short_tag=s_tag,
                    observed_display=formatted,
                    target_display=gate["target_display"],
                    human_summary=h_phrase,
                    note=item.message.replace("\n", " "),
                )
            )
        elif pos:
            item = pos[0]
            formatted = format_metric_value(item.metric, item.value)
            rows.append(
                EntryGateCheckRow(
                    gate_key=gate["gate_key"],
                    gate_label=gate["gate_label"],
                    status="PASS",
                    human_status="PASS",
                    short_tag=gate["short_tag"],
                    observed_display=formatted,
                    target_display=gate["target_display"],
                    human_summary=f"{gate['gate_label']}: {formatted}",
                    note=item.message.replace("\n", " "),
                )
            )
        else:
            rows.append(
                EntryGateCheckRow(
                    gate_key=gate["gate_key"],
                    gate_label=gate["gate_label"],
                    status="SILENT_OR_UNOBSERVED",
                    human_status="WAIT",
                    short_tag=gate["short_tag"],
                    observed_display="Outside READY band (silent in v1)",
                    target_display=gate["target_display"],
                    human_summary=gate["silent_summary"],
                    note=gate["silent_summary"],
                )
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Cross-pillar analyst inline summaries
# ---------------------------------------------------------------------------

_FRESHNESS_POSITIVE_CODES = frozenset(
    {"fundamental_data_fresh", "market_data_fresh"}
)


def _inline_fragment(item: EvidenceItem) -> str:
    formatted = format_metric_value(item.metric, item.value)
    short = _compact_label(item)
    if formatted == "n/a":
        return short
    return f"{short} {formatted}"


def _select_cross_pillar_positives(
    decision: StockDecision, max_items: int = 4
) -> list[EvidenceItem]:
    """Select diverse fundamental highlights (growth + margin/FCF + valuation/debt)."""
    by_metric: dict[str, EvidenceItem] = {}
    fallback: list[EvidenceItem] = []
    for item in decision.quality.positives:
        if item.code in _FRESHNESS_POSITIVE_CODES:
            continue
        if item.metric and item.metric not in by_metric:
            by_metric[item.metric] = item
        else:
            fallback.append(item)

    selected: list[EvidenceItem] = []
    # 1. Pick top growth metric if available
    for m in ("revenue_yoy", "adjusted_net_income_yoy", "operating_cash_flow_yoy"):
        if m in by_metric:
            selected.append(by_metric.pop(m))
            break
    # 2. Pick top profitability/cash metric
    for m in ("net_margin", "free_cash_flow", "ocf_to_net_income"):
        if m in by_metric and len(selected) < max_items:
            selected.append(by_metric.pop(m))
    # 3. Fill remaining slots by priority order
    for m in _HIGHLIGHT_METRIC_PRIORITY:
        if len(selected) >= max_items:
            break
        if m in by_metric:
            selected.append(by_metric.pop(m))
    for item in fallback:
        if len(selected) >= max_items:
            break
        selected.append(item)
    return selected


def _build_quality_highlights_inline(decision: StockDecision, max_items: int = 4) -> str:
    selected = _select_cross_pillar_positives(decision, max_items=max_items)
    fragments = [_inline_fragment(item) for item in selected if _inline_fragment(item)]
    return " · ".join(fragments) if fragments else "None"


def _build_entry_snapshot_inline(decision: StockDecision) -> str:
    items = [
        item
        for item in decision.entry.positives
        if item.code not in {"market_data_fresh", "supportive_market_regime"}
    ]
    fragments = [_inline_fragment(item) for item in items[:4] if _inline_fragment(item)]
    return " · ".join(fragments) if fragments else "See 7-gate table in full report"


def _build_entry_blockers_inline(
    decision: StockDecision,
    checklist: tuple[EntryGateCheckRow, ...],
) -> str:
    if decision.entry.state is EntryState.ENTRY_READY:
        return "All 7 readiness gates passed"
    blockers = [row.human_summary for row in checklist if row.status != "PASS"]
    return "; ".join(blockers) if blockers else "See full report"


def _build_fundamental_watchouts_inline(decision: StockDecision) -> str:
    fragments = [_inline_fragment(item) for item in decision.quality.risks[:3]]
    if decision.quality.missing:
        miss_labels = [_compact_label(item) for item in decision.quality.missing[:2]]
        suffix = (
            f" (+{len(decision.quality.missing) - 2})"
            if len(decision.quality.missing) > 2
            else ""
        )
        fragments.append(f"Missing: {', '.join(miss_labels)}{suffix}")
    return " · ".join(fragments) if fragments else "None flagged"


def _build_accordion_tagline(
    decision: StockDecision,
    checklist: tuple[EntryGateCheckRow, ...],
) -> str:
    """Build a crisp <= 38-char one-line hook for mobile <summary> headers."""
    if decision.entry.state is EntryState.ENTRY_READY:
        top_q = _select_cross_pillar_positives(decision, max_items=2)
        q_part = ", ".join(_inline_fragment(item) for item in top_q) or "Quality " + decision.quality.grade.value
        return q_part
    open_gates = [row.short_tag for row in checklist if row.status != "PASS"]
    if open_gates:
        return f"Wait: {', '.join(open_gates[:2])}"
    return "See gate check"


def _build_top_positives_inline(decision: StockDecision) -> str:
    candidates = [
        item
        for item in (*decision.quality.positives, *decision.entry.positives)
        if item.code not in _FRESHNESS_POSITIVE_CODES
    ]
    fragments = [_inline_fragment(item) for item in candidates[:3] if _inline_fragment(item)]
    return "; ".join(fragments) if fragments else "none"


def _build_top_risks_inline(
    decision: StockDecision,
    checklist: tuple[EntryGateCheckRow, ...],
) -> str:
    candidates = (*decision.quality.risks, *decision.entry.risks)
    fragments = [_inline_fragment(item) for item in candidates[:2] if _inline_fragment(item)]
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
    ) or "point_in_time_default"
    explicit_scope_risk = (
        share_basis not in {"point_in_time_default", "point_in_time_outstanding"}
        and any(
            token in share_basis.lower()
            for token in ("unverified", "fallback", "scope")
        )
    )

    if identity_unverified or unrated or severely_stale or asof_missing or explicit_scope_risk:
        status = "UNVERIFIED_OR_SCOPE_RISK"
        human_status = "Unverified / Scope Warning"
    elif stale or fallback_used:
        status = "CAUTION_LAG_OR_FALLBACK"
        human_status = "Verified (SEC 10-Q fallback)" if fallback_used else "Ageing Data"
    else:
        status = "VERIFIED"
        human_status = "Verified"

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
        f"Filing {_freshness_token(decision.quality.data_asof, decision_day)}"
        f" · Market {_freshness_token(decision.entry.market_asof, decision_day)}"
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
        warnings.append("Exact-filing SEC 10-Q fallback used to supplement Company Facts.")
    if explicit_scope_risk:
        warnings.append("Share-count basis uses weighted-average fallback; verify multi-class scope.")
    return DataTrustBadge(
        overall_status=status,
        human_status=human_status,
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
    """Build the presentation view model for one canonical decision."""
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
        accordion_Tagline=_build_accordion_tagline(decision, checklist),
        quality_highlights_inline=_build_quality_highlights_inline(decision),
        entry_Snapshot_inline=_build_entry_snapshot_inline(decision),
        entry_blockers_inline=_build_entry_blockers_inline(decision, checklist),
        fundamental_watchouts_inline=_build_fundamental_watchouts_inline(decision),
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
    """Build the snapshot-level view model."""
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
