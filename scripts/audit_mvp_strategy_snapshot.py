"""Read-only, cross-sectional audit of a frozen MVP StockDecision snapshot.

This is a strategy-research diagnostic, NOT a performance backtest, tuner, or
validator replacement. It does not modify the snapshot or production policy.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_value_scanner.decision.action import map_action_state


def _sorted_counts(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def audit_decisions(
    decisions: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    attention_cap: int = 15,
) -> dict[str, Any]:
    """Summarize observable v1 routing and attention compression, not alpha."""
    if attention_cap < 1:
        raise ValueError("attention_cap must be positive")
    if not decisions:
        raise ValueError("decisions.jsonl must be non-empty")

    records = sorted(decisions, key=lambda d: d["priority"])
    symbols = [str(d["symbol"]) for d in records]
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate symbol in decisions.jsonl")
    if [d["priority"] for d in records] != list(range(1, len(records) + 1)):
        raise ValueError("decision priority must be exactly 1..N")

    declared = manifest.get("counts", {}).get("decisions")
    if declared is not None and declared != len(records):
        raise ValueError("manifest decision count does not match JSONL")
    decision_date = manifest.get("decision_date")
    if any(d.get("decision_date") != decision_date for d in records):
        raise ValueError("decision date does not match manifest")
    if any(
        d.get("provenance", {}).get("code_sha") != manifest.get("code_sha")
        for d in records
    ):
        raise ValueError("code SHA does not match manifest")

    for d in records:
        actual = str(d["action_state"])
        expected = map_action_state(d["quality"]["grade"], d["entry"]["state"]).value
        if actual != expected:
            raise ValueError(f"{d['symbol']}: Action disagrees with v1 mapping")

    known = set(symbols)
    selected: dict[str, list[str]] = {}
    for name in ("daily", "weekly"):
        values = manifest.get(f"{name}_symbols")
        if not isinstance(values, list):
            raise ValueError(f"manifest missing {name}_symbols list")
        if len(values) > attention_cap or len(values) != len(set(values)):
            raise ValueError(f"{name} attention violates cap/uniqueness")
        if not set(values).issubset(known):
            raise ValueError(f"{name} attention contains unknown symbols")
        selected[name] = values

    quality = [str(d["quality"]["grade"]) for d in records]
    entry = [str(d["entry"]["state"]) for d in records]
    action = [str(d["action_state"]) for d in records]

    matrix: dict[str, dict[str, int]] = {}
    for grade in sorted(set(quality)):
        states = [d["entry"]["state"] for d in records if d["quality"]["grade"] == grade]
        matrix[grade] = _sorted_counts(states)

    priority = [d for d in records if d["action_state"] == "PRIORITY_REVIEW"]
    priority_symbols = [d["symbol"] for d in priority]
    priorities_by_list = {
        name: [s for s in priority_symbols if s in selected[name]]
        for name in ("daily", "weekly")
    }
    omitted_by_list = {
        name: [s for s in priority_symbols if s not in selected[name]]
        for name in ("daily", "weekly")
    }

    b_ready = [
        d["symbol"] for d in records
        if d["quality"]["grade"] == "B" and d["entry"]["state"] == "ENTRY_READY"
    ]
    a_damaged = [
        d["symbol"] for d in records
        if d["quality"]["grade"] == "A" and d["entry"]["state"] == "TREND_DAMAGED"
    ]
    fallback_breakout = [
        d for d in records if d["entry"]["state"] == "WATCH_BREAKOUT"
    ]

    # These are multi-label watchlist DISCOVERY BUCKETS, not industry classifications
    # or investment-quality/AI-relevance scores.
    discovery_buckets = Counter()
    for d in priority:
        raw = d.get("provenance", {}).get("watchlist_bucket") or ""
        discovery_buckets.update(
            token.strip() for token in raw.split(",") if token.strip()
        )

    return {
        "scope": "single_date_cross_section_not_performance_evidence",
        "decision_date": decision_date,
        "code_sha": manifest.get("code_sha"),
        "config_fingerprint": manifest.get("config_fingerprint"),
        "decisions": len(records),
        "attention_cap": attention_cap,
        "quality_counts": _sorted_counts(quality),
        "entry_counts": _sorted_counts(entry),
        "action_counts": _sorted_counts(action),
        "quality_entry_matrix": matrix,
        "priority_review_total": len(priority_symbols),
        "priority_review_symbols_by_rank": priority_symbols,
        "priority_review_selected": priorities_by_list,
        "priority_review_omitted": omitted_by_list,
        "b_entry_ready": {"count": len(b_ready), "symbols_by_rank": b_ready},
        "a_trend_damaged": {"count": len(a_damaged), "symbols_by_rank": a_damaged},
        "watch_breakout": {
            "count": len(fallback_breakout),
            "quality_counts": _sorted_counts(
                [d["quality"]["grade"] for d in fallback_breakout]
            ),
        },
        "priority_review_discovery_bucket_memberships": dict(
            sorted(discovery_buckets.items())
        ),
        "fallback_used": sum(
            d.get("provenance", {}).get("fundamental_edgartools_fallback_used") is True
            for d in records
        ),
    }


def audit_snapshot(root: Path, *, attention_cap: int = 15) -> dict[str, Any]:
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    decisions = [
        json.loads(line)
        for line in (root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return audit_decisions(decisions, manifest, attention_cap=attention_cap)


def render_markdown(audit: Mapping[str, Any]) -> str:
    lines = [
        "# MVP v1 snapshot strategy audit",
        "",
        "> Cross-sectional routing / research-attention diagnostic only. "
        "Not a historical performance comparison, OOS claim, or tuning result.",
        "",
        f"- Decision date: {audit['decision_date']}",
        f"- Code SHA: {audit['code_sha']}",
        f"- Config fingerprint: {audit['config_fingerprint']}",
        f"- Decisions: {audit['decisions']}; attention cap: {audit['attention_cap']}",
        f"- EdgarTools fallback used: {audit['fallback_used']}",
        "",
        "## Current routing counts",
        "",
        "| Dimension | State | Count |",
        "| --- | --- | ---: |",
    ]
    for dimension, key in (
        ("Quality", "quality_counts"),
        ("Entry", "entry_counts"),
        ("Action", "action_counts"),
    ):
        for state, count in audit[key].items():
            lines.append(f"| {dimension} | {state} | {count} |")

    lines += ["", "## Research bottlenecks", ""]
    lines += [
        f"- PRIORITY_REVIEW: {audit['priority_review_total']}.",
        "- Daily omitted PRIORITY_REVIEW names: "
        + (", ".join(audit["priority_review_omitted"]["daily"]) or "none") + ".",
        "- Weekly omitted PRIORITY_REVIEW names: "
        + (", ".join(audit["priority_review_omitted"]["weekly"]) or "none") + ".",
        f"- Quality B + ENTRY_READY: {audit['b_entry_ready']['count']} "
        "(fixed v1 mapping: HOLD_MONITOR).",
        f"- Quality A + TREND_DAMAGED: {audit['a_trend_damaged']['count']}.",
        f"- WATCH_BREAKOUT Entry bucket: {audit['watch_breakout']['count']} "
        "(v1 also uses this as a fallback state).",
        "",
        "## Interpretation boundary",
        "",
        "- Discovery-bucket memberships are multi-label provenance, not sectors.",
        "- A crowded attention list does not prove poor stock selection.",
        "- No forward labels are analyzed. Do not change thresholds based on this report.",
        "- Test v2 hypotheses on frozen PIT cohorts, then independent held-out or "
        "prospective samples before promotion.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Directory containing JSONL + manifest")
    parser.add_argument("--attention-cap", type=int, default=15)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    result = audit_snapshot(args.snapshot, attention_cap=args.attention_cap)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(render_markdown(result), end="")


if __name__ == "__main__":
    main()
