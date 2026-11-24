"""Validate the independent Short Research section of a decision snapshot."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from ai_value_scanner.fundamentals.provenance import sha256_hex
from ai_value_scanner.reporting.revisions import (
    DOWNSIDE_SCOPE_RENDERER_REVISION,
    GROUPED_RESEARCH_RENDERER_REVISIONS,
    REPORT_RENDERER_REVISION,
)
from ai_value_scanner.research.short_research_v1 import (
    MAX_SHORT_CANDIDATES,
    MAX_FUNDAMENTAL_ASOF_DAYS,
    SHORT_CSV_COLUMNS,
    SHORT_RESEARCH_CONTRACT_VERSION,
    SHORT_RESEARCH_RULE_VERSION,
    SHORT_RESEARCH_SCHEMA_VERSION,
    STATUS_CONFIRMED,
    STATUS_DISABLED,
    STATUS_NO_CANDIDATES,
    STATUS_READY,
    STATUS_UNAVAILABLE,
    ShortResearchResult,
    disabled_short_research_result,
    render_short_research_section,
    render_unavailable_short_research_section,
    short_candidates_csv,
)

SHORT_JSON = "short_research.json"
SHORT_CSV = "short_candidates.csv"
SHORT_CSV_LINK = f"./{SHORT_CSV}"


def render_short_snapshot_section(
    result: ShortResearchResult,
    *,
    csv_rel_path: str = SHORT_CSV_LINK,
    renderer_revision: str | None = REPORT_RENDERER_REVISION,
    body: list[str] | None = None,
) -> list[str]:
    if body is None:
        body = render_short_research_section(result, csv_rel_path=csv_rel_path)
    status = {
        STATUS_READY: f"{result.selected_count} " + ("candidate" if result.selected_count == 1 else "candidates"),
        STATUS_NO_CANDIDATES: "No candidates",
        STATUS_UNAVAILABLE: "Data unavailable",
        STATUS_DISABLED: "Not enabled",
    }[result.status]
    return _fold_short_section(body, status, renderer_revision)


def render_unavailable_short_snapshot_section(
    result: ShortResearchResult,
    *,
    csv_rel_path: str = SHORT_CSV_LINK,
    renderer_revision: str | None = REPORT_RENDERER_REVISION,
) -> list[str]:
    """Render an unavailable result without the candidate report formatter."""
    body = render_unavailable_short_research_section(result, csv_rel_path=csv_rel_path)
    return _fold_short_section(body, "Data unavailable", renderer_revision)


def _fold_short_section(
    body: list[str], status: str, renderer_revision: str | None,
) -> list[str]:
    if renderer_revision not in GROUPED_RESEARCH_RENDERER_REVISIONS:
        return body
    scope = []
    if renderer_revision == DOWNSIDE_SCOPE_RENDERER_REVISION:
        scope.append(
            "- **Scope** · For research only. This screen runs independently of Topic Screens. "
            "The long Action List selects and ranks its own candidates."
        )
    return [
        body[0],
        "<details>",
        f"<summary><strong>Downside Research</strong> · {status}</summary>",
        "",
        *scope,
        *(line for line in body[3:] if not line.startswith("- **Independence**:")),
        "</details>",
        "",
    ]


def short_snapshot_summary(
    result: ShortResearchResult, files: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "enabled": result.enabled,
        "status": result.status,
        "contract_version": result.contract_version,
        "rule_version": result.rule_version,
        "signal_date": result.signal_date,
        "market_data_feed": result.market_data_feed,
        "selected_count": result.selected_count,
        "reason_codes": list(result.reason_codes),
        "funnel": dict(result.funnel),
        "status_counts": dict(result.status_counts),
        "files": dict(files),
    }


def load_short_snapshot(
    root: Path, manifest: Mapping[str, Any]
) -> ShortResearchResult:
    """Validate the manifest, two short files and the short sections of both views."""
    summary = manifest.get("short_research")
    json_path, csv_path = root / SHORT_JSON, root / SHORT_CSV
    enabled = isinstance(summary, dict) and summary.get("enabled") is True
    if not enabled:
        disabled = disabled_short_research_result()
        if "short_research" in manifest and (
            not isinstance(summary, dict)
            or json.dumps(summary, sort_keys=True)
            != json.dumps(short_snapshot_summary(disabled, {}), sort_keys=True)
        ):
            raise ValueError("invalid disabled Short Research manifest")
        if json_path.exists() or csv_path.exists():
            raise ValueError("disabled Short Research snapshot contains short files")
        if any(
            '<a id="short-research"></a>' in (root / name).read_text(encoding="utf-8")
            for name in ("action_list.md", "weekly_review.md")
        ):
            raise ValueError("disabled Short Research snapshot contains a short section")
        return disabled

    if manifest.get("report_layout_version") != "v2":
        raise ValueError("enabled Short Research requires report layout v2")
    try:
        raw_json, raw_csv = json_path.read_bytes(), csv_path.read_bytes()
        payload = json.loads(raw_json)
        if not isinstance(payload, dict):
            raise ValueError("Short Research JSON must be an object")
        if (
            payload.get("schema_version") != SHORT_RESEARCH_SCHEMA_VERSION
            or payload.get("contract_version") != SHORT_RESEARCH_CONTRACT_VERSION
            or payload.get("rule_version") != SHORT_RESEARCH_RULE_VERSION
        ):
            raise ValueError("unknown Short Research schema, contract or rule version")
        result = ShortResearchResult.from_payload(payload)
        if json.dumps(result.to_payload(), sort_keys=True, allow_nan=False) != json.dumps(
            payload, sort_keys=True, allow_nan=False
        ):
            raise ValueError("Short Research JSON contains missing or invalid fields")
    except (AttributeError, TypeError, OverflowError) as exc:
        raise ValueError("malformed Short Research payload") from exc

    files = {
        "json": SHORT_JSON,
        "csv": SHORT_CSV,
        "json_sha256": sha256_hex(raw_json),
        "csv_sha256": sha256_hex(raw_csv),
    }
    if json.dumps(summary, sort_keys=True) != json.dumps(
        short_snapshot_summary(result, files), sort_keys=True
    ):
        raise ValueError("Short Research manifest does not match JSON and CSV")
    if result.signal_date != manifest.get("decision_date"):
        raise ValueError("Short Research signal date does not match the snapshot")
    provenance = manifest.get("input_provenance") or {}
    if not isinstance(provenance, dict):
        raise ValueError("invalid Short Research snapshot provenance")
    if (feed := provenance.get("market_data_feed")) and result.market_data_feed != feed:
        raise ValueError("Short Research feed does not match snapshot provenance")
    if result.status not in {STATUS_READY, STATUS_NO_CANDIDATES, STATUS_UNAVAILABLE}:
        raise ValueError("invalid enabled Short Research status")
    if result.status != STATUS_UNAVAILABLE and result.market_data_feed != "sip":
        raise ValueError("completed Short Research selection requires SIP")
    if (result.status == STATUS_READY) != bool(result.selected):
        raise ValueError("Short Research status conflicts with selected candidates")
    if result.status == STATUS_UNAVAILABLE and not result.reason_codes:
        raise ValueError("unavailable Short Research requires a reason")
    if result.selected_count > MAX_SHORT_CANDIDATES or result.funnel.get(
        "selected_rows", 0
    ) != result.selected_count:
        raise ValueError("invalid Short Research selected count")
    if result.status != STATUS_UNAVAILABLE:
        s2_rows = result.funnel.get("s2_rows")
        if s2_rows is None or min(s2_rows, MAX_SHORT_CANDIDATES) != result.selected_count:
            raise ValueError("completed Short Research selected count conflicts with S2 count")
    if any(
        count < 0
        for counts in (result.funnel, result.reason_counts, result.status_counts)
        for count in counts.values()
    ):
        raise ValueError("negative Short Research count")

    symbols = set()
    order = []
    for rank, candidate in enumerate(result.selected, start=1):
        if (
            not candidate.symbol
            or candidate.symbol in symbols
            or candidate.rank != rank
            or not candidate.selected
            or candidate.scope_excluded
            or candidate.status != STATUS_CONFIRMED
            or candidate.signal_groups != ("S0", "S1", "S2")
            or candidate.signal_date != result.signal_date
            or candidate.market_asof[:10] != result.signal_date
            or candidate.market_data_feed != result.market_data_feed
            or candidate.rs60_sic is None
        ):
            raise ValueError("invalid ranked Short Research candidate")
        try:
            filing_day = datetime.fromisoformat(candidate.fundamental_data_asof or "").date()
            signal_day = date.fromisoformat(candidate.signal_date)
        except ValueError as exc:
            raise ValueError("invalid Short Research filing date") from exc
        if not 0 <= (signal_day - filing_day).days <= MAX_FUNDAMENTAL_ASOF_DAYS:
            raise ValueError("Short Research filing date is outside the point-in-time window")
        symbols.add(candidate.symbol)
        order.append((candidate.rs60_sic, candidate.symbol))
    if order != sorted(order):
        raise ValueError("Short Research candidate order is invalid")
    expected_csv = short_candidates_csv(result) if result.selected else ",".join(SHORT_CSV_COLUMNS) + "\n"
    if raw_csv != expected_csv.encode("utf-8"):
        raise ValueError("Short Research CSV does not match its JSON")
    renderer = (
        render_unavailable_short_snapshot_section
        if result.status == STATUS_UNAVAILABLE
        else render_short_snapshot_section
    )
    suffix = "\n".join(renderer(
        result, renderer_revision=manifest.get("report_renderer_revision")
    ))
    for name in ("action_list.md", "weekly_review.md"):
        if not (root / name).read_text(encoding="utf-8").endswith(suffix):
            raise ValueError(f"Short Research section in {name} does not match its JSON")
    return result
