from __future__ import annotations

from collections.abc import Iterable

from ai_value_scanner.decision.model import EvidenceItem, StockDecision
from ai_value_scanner.decision.view_model import (
    StockCardViewModel,
    build_snapshot_view_model,
    build_stock_card_view_model,
)


def _display(value: object | None) -> str:
    if value is None or value == "":
        return "n/a"
    return str(value).replace("\n", " ")


def _render_decision_summary(decision: StockDecision, *, heading_level: int) -> list[str]:
    heading = "#" * heading_level
    company = f" — {decision.company_name}" if decision.company_name else ""
    lines = [f"{heading} {decision.symbol}{company}", ""]
    lines.extend(
        [
            f"- Decision date: {decision.decision_date}",
            f"- Company Quality: {decision.quality.grade.value}",
            f"- Entry Quality: {decision.entry.state.value}",
            f"- Action State: {decision.action_state.value}",
            f"- Priority: {decision.priority}",
            f"- Fundamental data as-of: {_display(decision.quality.data_asof)}",
            f"- Market data as-of: {_display(decision.entry.market_asof)}",
            f"- Review trigger: {_display(decision.review_trigger)}",
            f"- Previous action: {_display(decision.previous_action_state.value if decision.previous_action_state else None)}",
            f"- State change reason: {_display(decision.state_change_reason)}",
        ]
    )
    return lines


def _render_evidence(items: Iterable[EvidenceItem]) -> list[str]:
    rendered: list[str] = []
    for item in items:
        details: list[str] = [f"polarity={item.polarity}"]
        if item.metric is not None:
            details.append(f"metric={item.metric}")
        if item.value is not None:
            details.append(f"value={item.value}")
        if item.threshold is not None:
            details.append(f"threshold={item.threshold}")
        rendered.append(
            f"- `{item.code}` — {item.label}: {item.message} ({'; '.join(details)})"
        )
    if not rendered:
        rendered.append("- none")
    return rendered


def _rationale_by_polarity(
    decision: StockDecision,
) -> tuple[tuple[EvidenceItem, ...], tuple[EvidenceItem, ...]]:
    positives = tuple(
        item for item in decision.rationale if item.polarity == "positive"
    )
    counter = tuple(
        item
        for item in decision.rationale
        if item.polarity in {"negative", "missing", "neutral"}
    )
    return positives, counter


# Static, policy-derived one-line structural meanings. They name metrics,
# never numbers: concrete values always come from the decision's own
# evidence, so these lines cannot drift when thresholds change.
_ENTRY_STATE_ONE_LINERS = {
    "ENTRY_READY": (
        "Price holds above its long-term trend inside the readiness band "
        "with non-negative momentum — a healthy structure that is not "
        "overextended."
    ),
    "WATCH_PULLBACK": (
        "Price is extended above trend after a strong run — healthy, but "
        "chasing it here means paying up; wait for normalization toward "
        "the band."
    ),
    "WATCH_BREAKOUT": (
        "A mixed remainder, not a single chart story: not damaged and not "
        "overextended, but missing at least one readiness condition — read "
        "the unmet conditions below instead of assuming a basing pattern."
    ),
    "TREND_DAMAGED": (
        "Price is below its long-term trend with weak momentum — the "
        "structure is damaged; do not time an entry on price alone."
    ),
    "INSUFFICIENT_DATA": (
        "Market evidence is insufficient to judge structure — no timing "
        "call can be made from this state."
    ),
}

_ENTRY_STATE_WATCH = {
    "ENTRY_READY": "Watch for loss of the readiness band or momentum breakdown.",
    "WATCH_PULLBACK": "Watch for normalization toward the band without trend damage.",
    "WATCH_BREAKOUT": "Watch for confirmation into ENTRY_READY or deterioration into TREND_DAMAGED.",
    "TREND_DAMAGED": "Watch for trend repair (reclaim of long-term average with momentum).",
    "INSUFFICIENT_DATA": "Watch for market-data coverage to be restored.",
}

_IDENTITY_CODE = "operating_entity_unverified"
_SEVERE_STALE_CODES = {"fundamental_data_severely_stale", "market_data_severely_stale"}
_STALE_CODES = {
    "fundamental_data_severely_stale",
    "fundamental_data_stale",
    "market_data_severely_stale",
    "market_data_stale",
}

# Generic applicability caveat. It names model FAMILIES from the research
# protocol, never individual tickers, and never assigns a business model:
# the decision object carries no verified classification to do so.
_APPLICABILITY_CAVEAT = (
    "Company Quality v1 is one common financial-quality core. Specialist "
    "accounting semantics (banks, brokers, insurers, REITs, foreign or "
    "unsupported reporting models) are pending independent review; until "
    "then, cross-model comparability is UNVERIFIED for every decision, "
    "and this grade must not be read as sector-relative quality."
)


def _top(items: tuple[EvidenceItem, ...], n: int) -> tuple[EvidenceItem, ...]:
    return tuple(items[: max(0, n)])


def _codes(items: tuple[EvidenceItem, ...]) -> set[str]:
    return {item.code for item in items}


def _attention_flags(decision: StockDecision) -> list[str]:
    """Human-review warnings derived ONLY from the decision's own evidence."""
    flags: list[str] = []
    if _IDENTITY_CODE in _codes(decision.quality.missing):
        flags.append(
            "Filing-entity identity UNVERIFIED: the ticker->CIK binding does "
            "not verifiably represent the operating issuer. Do not treat "
            "this grade as a reliable company judgement."
        )
    severe = sorted(
        (_codes(decision.quality.risks) | _codes(decision.entry.risks))
        & _SEVERE_STALE_CODES
    )
    if severe:
        flags.append(
            "Data severely stale (" + ", ".join(severe) + "): treat all "
            "levels below as indicative, not current."
        )
    elif any(
        c in _STALE_CODES
        for c in (_codes(decision.quality.risks) | _codes(decision.entry.risks))
    ):
        flags.append("Data ageing: check as-of dates before acting on this review.")
    if decision.quality.grade.value == "UNRATED":
        flags.append(
            "Company Quality UNRATED: no reliable company judgement exists; "
            "see Missing Evidence for what to supplement."
        )
    if decision.entry.state.value == "INSUFFICIENT_DATA":
        flags.append("Entry evidence insufficient: no timing call can be made.")
    if "market_asof_missing" in _codes(decision.entry.risks) or (
        "fundamental_data_asof_missing" in _codes(decision.quality.missing)
    ):
        flags.append(
            "Data as-of MISSING: a required date is absent, so freshness "
            "cannot be verified — do not read this review as current."
        )
    return flags


def _next_review_lines(decision: StockDecision) -> list[str]:
    lines = [f"- Trigger: {_display(decision.review_trigger)}"]
    for item in decision.quality.missing[:3]:
        lines.append(f"- Supplement: {item.label} ({item.code}).")
    if any(
        c in _STALE_CODES
        for c in (_codes(decision.quality.risks) | _codes(decision.entry.risks))
    ):
        lines.append("- Refresh after the next periodic filing / market session.")
    watch = _ENTRY_STATE_WATCH.get(decision.entry.state.value)
    if watch:
        lines.append(f"- Structure: {watch}")
    return lines


def _applicability_lines(decision: StockDecision) -> list[str]:
    lines = ["- " + _APPLICABILITY_CAVEAT]
    unverified = (
        _IDENTITY_CODE in _codes(decision.quality.missing)
        or decision.quality.grade.value == "UNRATED"
        or float(decision.quality.confidence or 0.0) < 0.5
    )
    if unverified:
        lines.append(
            "- Applicability for THIS decision: UNVERIFIED — do not compare "
            "this grade across business models or against sector peers."
        )
    else:
        lines.append(
            "- Applicability for THIS decision: not disproven, but still "
            "unverified across business models — compare with caution."
        )
    return lines


def _data_state_lines(decision: StockDecision) -> list[str]:
    if decision.quality.data_asof is None or decision.entry.market_asof is None:
        state = "as-of MISSING"
    elif _codes(decision.quality.risks) & _SEVERE_STALE_CODES or _codes(
        decision.entry.risks
    ) & _SEVERE_STALE_CODES:
        state = "SEVERELY STALE"
    elif any(
        c in _STALE_CODES
        for c in (_codes(decision.quality.risks) | _codes(decision.entry.risks))
    ):
        state = "ageing"
    else:
        state = "fresh"
    if decision.quality.missing:
        state += f"; {len(decision.quality.missing)} missing evidence items"
    return [
        f"- Fundamental as-of: {_display(decision.quality.data_asof)}",
        f"- Market as-of: {_display(decision.entry.market_asof)}",
        f"- Data state: {state}",
        f"- Detailed report: detailed/{decision.symbol}.md",
    ]


def render_action_list(
    decisions: Iterable[StockDecision],
    *,
    title: str = "Action List",
    cadence: str | None = None,
    layout_version: str = "v1",
    all_decisions: Iterable[StockDecision] | None = None,
) -> str:
    """Render the compact attention surface from canonical StockDecision objects."""
    if layout_version == "v2":
        return render_action_list_v2(
            decisions, title=title, cadence=cadence, all_decisions=all_decisions
        )
    if layout_version != "v1":
        raise ValueError(f"unsupported layout_version={layout_version!r}")
    materialized = tuple(decisions)
    lines = [f"# {title}", ""]
    if cadence:
        lines.extend(
            [
                f"- Cadence: {cadence}",
                "- States are research priorities, not automated trade instructions.",
                "",
            ]
        )
    if not materialized:
        lines.extend(["- no decisions", ""])
        return "\n".join(lines)
    if not cadence:
        lines.extend(
            [
                "- States are research priorities, not automated trade instructions.",
                "",
            ]
        )

    for decision in materialized:
        lines.extend(_render_decision_summary(decision, heading_level=2))
        positives, counter = _rationale_by_polarity(decision)
        flags = _attention_flags(decision)
        lines.extend(["", "### Attention", ""])
        lines.extend([f"- {flag}" for flag in flags] if flags else ["- none"])
        lines.extend(["", "### Why notable", ""])
        lines.extend(
            _render_evidence(_top(positives, 2))
            + ["", "- (first two in rationale order)", ""]
            if positives
            else ["- none", ""]
        )
        lines.extend(["### Key risks", ""])
        lines.extend(
            _render_evidence(_top(counter, 2))
            + ["", "- (first two in rationale order)", ""]
            if counter
            else ["- none", ""]
        )
        lines.extend(["### Entry structure", ""])
        lines.append(
            "- "
            + _ENTRY_STATE_ONE_LINERS.get(
                decision.entry.state.value, "No structural reading available."
            )
        )
        lines.extend(["", "### Next review", ""])
        lines.extend(_next_review_lines(decision))
        lines.extend(["", "### Data & detail", ""])
        lines.extend(_data_state_lines(decision))
        lines.append("")
    return "\n".join(lines)


def render_detailed_report(
    decision: StockDecision, *, layout_version: str = "v1"
) -> str:
    """Render the evidence view for the same canonical StockDecision.

    Fixed seven-section structure (Phase 2): summary, Company Quality,
    Quality applicability, Entry Quality, counter-evidence, missing
    evidence, next-review conditions, provenance. Every line derives from
    the decision object; nothing is inferred, modelled, or invented.
    """
    if layout_version == "v2":
        return render_detailed_report_v2(decision)
    if layout_version != "v1":
        raise ValueError(f"unsupported layout_version={layout_version!r}")
    company = f" — {decision.company_name}" if decision.company_name else ""
    lines = [f"# Detailed Report — {decision.symbol}{company}", ""]
    lines.extend(_render_decision_summary(decision, heading_level=2))
    flags = _attention_flags(decision)
    if flags:
        lines.extend(["", "## Attention — read before acting", ""])
        lines.extend([f"- {flag}" for flag in flags])
    lines.extend(
        [
            "",
            "## Company Quality",
            "",
            f"- Grade: {decision.quality.grade.value}",
            f"- Score: {_display(decision.quality.score)}",
            f"- Confidence: {decision.quality.confidence}",
            f"- Data as-of: {_display(decision.quality.data_asof)}",
            "",
            "### Component Scores",
            "",
        ]
    )
    if decision.quality.component_scores:
        for name in sorted(decision.quality.component_scores):
            lines.append(f"- {name}: {_display(decision.quality.component_scores[name])}")
    else:
        lines.append("- none")
    lines.extend(["", "### Positives", "", *_render_evidence(decision.quality.positives)])
    lines.extend(
        [
            "",
            "## Quality Applicability",
            "",
            *_applicability_lines(decision),
        ]
    )
    lines.extend(
        [
            "",
            "## Entry Quality",
            "",
            f"- State: {decision.entry.state.value}",
            f"- Structure: {_ENTRY_STATE_ONE_LINERS.get(decision.entry.state.value, 'n/a')}",
            f"- Score: {_display(decision.entry.score)}",
            f"- Confidence: {decision.entry.confidence}",
            f"- Market as-of: {_display(decision.entry.market_asof)}",
            "",
            "### Positives",
            "",
            *_render_evidence(decision.entry.positives),
        ]
    )
    lines.extend(
        [
            "",
            "## Counter-Evidence",
            "",
            *_render_evidence(
                (*decision.quality.risks, *decision.entry.risks)
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## Missing Evidence",
            "",
            *_render_evidence(decision.quality.missing),
        ]
    )
    if decision.entry.state.value == "INSUFFICIENT_DATA":
        lines.append("- Entry market evidence is itself insufficient (see Entry state).")
    lines.extend(["", "## Next Review Conditions", "", *_next_review_lines(decision)])
    lines.extend(
        [
            "",
            "## Decision History",
            "",
            f"- Previous action: {_display(decision.previous_action_state.value if decision.previous_action_state else None)}",
            f"- State change: {_display(decision.state_change_reason)}",
            "",
            "## Evidence & Provenance",
            "",
            f"- Schema version: {decision.schema_version}",
            f"- Generated at UTC: {decision.generated_at_utc}",
            f"- Source lists: {', '.join(decision.source_lists) if decision.source_lists else 'n/a'}",
        ]
    )
    if decision.provenance:
        for key in sorted(decision.provenance):
            lines.append(f"- {key}: {_display(decision.provenance[key])}")
    else:
        lines.append("- provenance: n/a")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v2 human-readable layouts (backed by decision/view_model.py).
# The v1 functions above are untouched; v2 renderers consume canonical
# StockDecision objects through the presentation IR only.
# ---------------------------------------------------------------------------


def _cell(text: object | None) -> str:
    if text is None:
        return "n/a"
    return str(text).replace("\n", " ").replace("|", "\\|").strip() or "n/a"


def _v2_counts_line(decisions: tuple[StockDecision, ...]) -> str:
    counts: dict[str, int] = {}
    for decision in decisions:
        key = decision.action_state.value
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{state} {counts.get(state, 0)}" for state in sorted(counts)]
    return "; ".join(parts) if parts else "no decisions"


def _v2_shortlist_row(card: StockCardViewModel) -> str:
    return (
        f"| {card.rank} | {card.symbol} | {_cell(card.company_name)} "
        f"| {card.action_state} | {card.quality_grade} "
        f"({card.quality_score_display}, {card.quality_confidence_display}) "
        f"| {card.entry_state} "
        f"({card.entry_score_display}, {card.entry_confidence_display}) "
        f"| {_cell(card.top_positives_inline)} "
        f"| {_cell(card.top_risks_or_blockers_inline)} "
        f"| {_cell(card.next_trigger_inline)} |"
    )


def _v2_stock_card_block(card: StockCardViewModel) -> list[str]:
    lines = [
        f"### {card.rank}. {card.symbol} — {_cell(card.company_name)}",
        "",
        f"- Action: {card.action_state} | Quality: {card.quality_grade} "
        f"({card.quality_score_display}, conf {card.quality_confidence_display}) "
        f"| Entry: {card.entry_state} "
        f"({card.entry_score_display}, conf {card.entry_confidence_display})",
        f"- Key bullish: {_cell(card.top_positives_inline)}",
        f"- Key risk / blocker: {_cell(card.top_risks_or_blockers_inline)}",
        f"- Next trigger: {_cell(card.next_trigger_inline)}",
        f"- Data trust: {card.data_trust.overall_status} "
        f"({card.data_trust.freshness_display}; {card.data_trust.share_basis_display})",
    ]
    blockers = [row for row in card.entry_checklist if row.status != "PASS"]
    if blockers:
        lines.append("- Entry blockers:")
        for row in blockers:
            lines.append(
                f"  - {row.gate_key} [{row.status}]: observed "
                f"{_cell(row.observed_display)}; required {_cell(row.target_display)}."
            )
    else:
        lines.append("- Entry gates: all 7 PASS.")
    if card.data_trust.warnings:
        for warning in card.data_trust.warnings:
            lines.append(f"- Trust note: {_cell(warning)}")
    lines.extend([f"- Detailed: detailed/{card.symbol}.md", ""])
    return lines


def render_action_list_v2(
    decisions: Iterable[StockDecision],
    *,
    title: str = "Action List",
    cadence: str | None = None,
    all_decisions: Iterable[StockDecision] | None = None,
) -> str:
    """Human-readable English tabular dashboard (v2) for the attention list."""
    primary = tuple(decisions)
    snapshot = build_snapshot_view_model(
        primary, all_decisions, title=title, cadence=cadence
    )
    lines = [f"# {snapshot.title} (v2)", ""]
    lines.append(f"- Decision date: {snapshot.decision_date}")
    lines.append(f"- Cadence: {cadence or 'n/a'}")
    lines.append("- States are research priorities, not automated trade instructions.")
    lines.append(f"- Coverage: {len(primary)} names ({_v2_counts_line(primary)})")
    lines.extend(["", "## Executive Shortlist", ""])
    if not snapshot.primary_cards:
        lines.extend(["- no decisions", ""])
    else:
        lines.extend(
            [
                "| Rank | Symbol | Company | Action | Quality | Entry "
                "| Key Bullish Evidence | Key Risk / Readiness Blocker "
                "| Next Review Trigger |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for card in snapshot.primary_cards:
            lines.append(_v2_shortlist_row(card))
        lines.append("")
    lines.extend(["## Secondary Radar (Off-List Watch)", ""])
    if (
        not snapshot.cap_omitted_priority_cards
        and not snapshot.secondary_b_ready_cards
    ):
        lines.extend(["- No off-list radar names for this snapshot.", ""])
    else:
        if snapshot.cap_omitted_priority_cards:
            lines.extend(
                [
                    "### Cap-Omitted PRIORITY_REVIEW "
                    "(Quality A + ENTRY_READY beyond Top-15 cap)",
                    "",
                    "| Rank | Symbol | Company | Quality | Entry "
                    "| Key Bullish Evidence | Key Risk / Readiness Blocker |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for card in snapshot.cap_omitted_priority_cards:
                lines.append(
                    f"| {card.rank} | {card.symbol} | {_cell(card.company_name)} "
                    f"| {card.quality_grade} ({card.quality_score_display}) "
                    f"| {card.entry_state} | {_cell(card.top_positives_inline)} "
                    f"| {_cell(card.top_risks_or_blockers_inline)} |"
                )
            lines.append("")
        if snapshot.secondary_b_ready_cards:
            lines.extend(
                [
                    "### Top Quality B + ENTRY_READY Candidates "
                    "(Currently mapped to HOLD_MONITOR)",
                    "",
                    "| Rank | Symbol | Company | Quality | Entry "
                    "| Key Bullish Evidence | Key Risk / Readiness Blocker |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for card in snapshot.secondary_b_ready_cards:
                lines.append(
                    f"| {card.rank} | {card.symbol} | {_cell(card.company_name)} "
                    f"| {card.quality_grade} ({card.quality_score_display}) "
                    f"| {card.entry_state} | {_cell(card.top_positives_inline)} "
                    f"| {_cell(card.top_risks_or_blockers_inline)} |"
                )
            lines.append("")
    lines.extend(["## Stock Cards", ""])
    if not snapshot.primary_cards:
        lines.extend(["- no decisions", ""])
    else:
        for card in snapshot.primary_cards:
            lines.extend(_v2_stock_card_block(card))
    return "\n".join(lines)


def render_detailed_report_v2(decision: StockDecision) -> str:
    """Human-readable evidence dashboard (v2) for one canonical decision."""
    card = build_stock_card_view_model(decision)
    company = f" — {decision.company_name}" if decision.company_name else ""
    lines = [f"# Detailed Report — {decision.symbol}{company} (v2)", ""]
    lines.extend(
        [
            "## Executive Decision",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Symbol | {card.symbol} |",
            f"| Company | {_cell(card.company_name)} |",
            f"| Action State | {card.action_state} |",
            f"| Priority Rank | {card.rank} |",
            f"| Company Quality (Grade / Score / Confidence) "
            f"| {card.quality_grade} / {card.quality_score_display} "
            f"/ {card.quality_confidence_display} |",
            f"| Entry Quality (State / Score / Confidence) "
            f"| {card.entry_state} / {card.entry_score_display} "
            f"/ {card.entry_confidence_display} |",
            f"| Data As-Of (Fund / Mkt) "
            f"| {_cell(decision.quality.data_asof)} "
            f"/ {_cell(decision.entry.market_asof)} |",
            f"| Filing Entity & CIK | {_cell(card.data_trust.entity_display)} |",
            f"| Data Trust Badge | {card.data_trust.overall_status} "
            f"({_cell(card.data_trust.freshness_display)}; "
            f"{_cell(card.data_trust.share_basis_display)}) |",
            "",
            "## Attention Alerts & Next Review Trigger",
            "",
        ]
    )
    flags = _attention_flags(decision)
    if flags:
        lines.extend([f"- {_cell(flag)}" for flag in flags])
    else:
        lines.append("- No attention flags.")
    lines.extend(
        [
            f"- Next trigger: {_cell(card.next_trigger_inline)}",
            f"- Structure watch: "
            f"{_cell(_ENTRY_STATE_WATCH.get(decision.entry.state.value, 'n/a'))}",
            "",
            "## Company Quality — 6-Pillar Scorecard",
            "",
            "| Pillar | Score | Status | Supporting Evidence (Formatted) "
            "| Risks & Missing Metrics (Formatted) |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for pillar in card.quality_pillars:
        support = (
            "; ".join(item.summary_text for item in pillar.supporting_items)
            or "none"
        )
        risks = (
            "; ".join(item.summary_text for item in pillar.risk_or_missing_items)
            or "none"
        )
        lines.append(
            f"| {_cell(pillar.pillar_label)} | {pillar.score_display} "
            f"| {pillar.status_badge} | {_cell(support)} | {_cell(risks)} |"
        )
    lines.extend(
        [
            "",
            "## Entry Quality — Readiness Gate Checklist",
            "",
            "| Readiness Gate | Status | Observed Value | Required Band "
            "for ENTRY_READY | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in card.entry_checklist:
        lines.append(
            f"| {_cell(row.gate_label)} | {row.status} "
            f"| {_cell(row.observed_display)} | {_cell(row.target_display)} "
            f"| {_cell(row.note)} |"
        )
    lines.extend(
        [
            "",
            "## Complete Counter-Evidence & Missing Data Inventory",
            "",
            "| Type | Code | Metric | Value | Target Band | Note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if card.all_counter_evidence:
        for item in card.all_counter_evidence:
            lines.append(
                f"| counter | `{item.code}` | {_cell(item.metric)} "
                f"| {_cell(item.formatted_value)} | {_cell(item.target_band)} "
                f"| {_cell(item.label)} |"
            )
    else:
        lines.append("| counter | none | n/a | n/a | n/a | No counter-evidence. |")
    if card.all_missing_evidence:
        for item in card.all_missing_evidence:
            lines.append(
                f"| missing | `{item.code}` | {_cell(item.metric)} "
                f"| {_cell(item.formatted_value)} | {_cell(item.target_band)} "
                f"| {_cell(item.label)} |"
            )
    else:
        lines.append("| missing | none | n/a | n/a | n/a | No missing evidence. |")
    if decision.entry.state.value == "INSUFFICIENT_DATA":
        lines.append(
            "| missing | entry_insufficient | n/a | n/a | n/a "
            "| Entry market evidence is itself insufficient (see Entry state). |"
        )
    lines.extend(
        [
            "",
            "## Quality Applicability, Decision History & Provenance",
            "",
            *_applicability_lines(decision),
            f"- Previous action: "
            f"{_display(decision.previous_action_state.value if decision.previous_action_state else None)}",
            f"- State change: {_display(decision.state_change_reason)}",
            f"- Schema version: {decision.schema_version}",
            f"- Generated at UTC: {decision.generated_at_utc}",
            f"- Source lists: "
            f"{', '.join(decision.source_lists) if decision.source_lists else 'n/a'}",
        ]
    )
    if decision.provenance:
        for key in sorted(decision.provenance):
            lines.append(f"- {key}: {_display(decision.provenance[key])}")
    else:
        lines.append("- provenance: n/a")
    lines.append("")
    return "\n".join(lines)
