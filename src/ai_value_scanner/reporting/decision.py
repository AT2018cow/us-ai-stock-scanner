from __future__ import annotations

from collections.abc import Iterable

from ai_value_scanner.decision.model import EvidenceItem, StockDecision


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


def render_action_list(decisions: Iterable[StockDecision]) -> str:
    """Render a minimal Action List without recomputing any decision state."""
    materialized = tuple(decisions)
    lines = ["# Action List", ""]
    if not materialized:
        lines.extend(["- no decisions", ""])
        return "\n".join(lines)

    for decision in materialized:
        lines.extend(_render_decision_summary(decision, heading_level=2))
        lines.extend(["", "### Rationale", ""])
        lines.extend(_render_evidence(decision.rationale))
        lines.append("")
    return "\n".join(lines)


def render_detailed_report(decision: StockDecision) -> str:
    """Render the evidence view for the same canonical StockDecision."""
    company = f" — {decision.company_name}" if decision.company_name else ""
    lines = [f"# Detailed Report — {decision.symbol}{company}", ""]
    lines.extend(_render_decision_summary(decision, heading_level=2))
    lines.extend(
        [
            "",
            "## Decision Rationale",
            "",
            *_render_evidence(decision.rationale),
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
    lines.extend(["", "### Risks", "", *_render_evidence(decision.quality.risks)])
    lines.extend(["", "### Missing Evidence", "", *_render_evidence(decision.quality.missing)])
    lines.extend(
        [
            "",
            "## Entry Quality",
            "",
            f"- State: {decision.entry.state.value}",
            f"- Score: {_display(decision.entry.score)}",
            f"- Confidence: {decision.entry.confidence}",
            f"- Market as-of: {_display(decision.entry.market_asof)}",
            "",
            "### Positives",
            "",
            *_render_evidence(decision.entry.positives),
            "",
            "### Risks",
            "",
            *_render_evidence(decision.entry.risks),
            "",
            "## Provenance",
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
