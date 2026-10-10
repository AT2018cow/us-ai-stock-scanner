from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_value_scanner.decision.action import map_action_state
from ai_value_scanner.decision.model import ActionState, EntryState, QualityGrade
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)
from ai_value_scanner.reporting.snapshot import load_snapshot_decisions


def validate_snapshot(
    root: str | Path,
    *,
    attention_cap: int = 15,
) -> dict[str, Any]:
    root_path = Path(root)
    errors: list[str] = []
    warnings: list[str] = []

    required = {
        "decisions": root_path / "decisions.jsonl",
        "daily": root_path / "action_list.md",
        "weekly": root_path / "weekly_review.md",
        "manifest": root_path / "run_manifest.json",
        "detailed": root_path / "detailed",
    }
    for name, path in required.items():
        if not path.exists():
            errors.append(f"missing {name}: {path}")

    if errors:
        return {
            "ok": False,
            "root": str(root_path),
            "errors": errors,
            "warnings": warnings,
        }

    try:
        manifest = json.loads(required["manifest"].read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid run_manifest.json: {type(exc).__name__}: {exc}")
        return {
            "ok": False,
            "root": str(root_path),
            "errors": errors,
            "warnings": warnings,
        }

    try:
        decisions = load_snapshot_decisions(root_path)
    except Exception as exc:
        errors.append(f"invalid decisions.jsonl: {type(exc).__name__}: {exc}")
        return {
            "ok": False,
            "root": str(root_path),
            "errors": errors,
            "warnings": warnings,
        }

    if not decisions:
        errors.append("decisions.jsonl contains no decisions")

    symbols = [decision.symbol for decision in decisions]
    if len(symbols) != len(set(symbols)):
        errors.append("decisions.jsonl contains duplicate symbols")

    priorities = sorted(decision.priority for decision in decisions)
    if priorities and priorities != list(range(1, len(priorities) + 1)):
        errors.append("decision priorities are not contiguous from 1..N")

    manifest_date = str(manifest.get("decision_date", ""))
    for decision in decisions:
        if decision.decision_date != manifest_date:
            errors.append(
                f"{decision.symbol}: decision_date {decision.decision_date} "
                f"!= manifest {manifest_date}"
            )
        expected_action = map_action_state(
            decision.quality.grade,
            decision.entry.state,
        )
        if decision.action_state is not expected_action:
            errors.append(
                f"{decision.symbol}: action {decision.action_state.value} "
                f"!= canonical mapping {expected_action.value}"
            )

    counts = manifest.get("counts", {}) or {}
    if int(counts.get("decisions", -1)) != len(decisions):
        errors.append(
            f"manifest decision count {counts.get('decisions')} "
            f"!= JSONL count {len(decisions)}"
        )

    daily_symbols = [str(x) for x in manifest.get("daily_symbols", [])]
    weekly_symbols = [str(x) for x in manifest.get("weekly_symbols", [])]
    if len(daily_symbols) > attention_cap:
        errors.append(
            f"daily attention count {len(daily_symbols)} exceeds cap {attention_cap}"
        )
    if len(weekly_symbols) > attention_cap:
        errors.append(
            f"weekly attention count {len(weekly_symbols)} exceeds cap {attention_cap}"
        )
    if len(daily_symbols) != len(set(daily_symbols)):
        errors.append("daily_symbols contains duplicates")
    if len(weekly_symbols) != len(set(weekly_symbols)):
        errors.append("weekly_symbols contains duplicates")

    decision_by_symbol = {decision.symbol: decision for decision in decisions}
    for label, selected in (("daily", daily_symbols), ("weekly", weekly_symbols)):
        unknown = sorted(set(selected) - set(decision_by_symbol))
        if unknown:
            errors.append(f"{label} contains unknown symbols: {unknown}")

    daily = tuple(
        decision_by_symbol[symbol]
        for symbol in daily_symbols
        if symbol in decision_by_symbol
    )
    weekly = tuple(
        decision_by_symbol[symbol]
        for symbol in weekly_symbols
        if symbol in decision_by_symbol
    )

    expected_daily = render_action_list(
        daily,
        title="Daily Action List",
        cadence="daily",
    )
    actual_daily = required["daily"].read_text(encoding="utf-8")
    if actual_daily != expected_daily:
        errors.append("action_list.md does not match canonical StockDecision rendering")

    expected_weekly = render_action_list(
        weekly,
        title="Weekly Review List",
        cadence="weekly",
    )
    actual_weekly = required["weekly"].read_text(encoding="utf-8")
    if actual_weekly != expected_weekly:
        errors.append("weekly_review.md does not match canonical StockDecision rendering")

    for symbol in sorted(set(daily_symbols + weekly_symbols)):
        path = required["detailed"] / f"{symbol}.md"
        if not path.exists():
            errors.append(f"missing detailed report for {symbol}: {path}")
            continue
        expected = render_detailed_report(decision_by_symbol[symbol])
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(
                f"detailed/{symbol}.md does not match canonical StockDecision rendering"
            )

    quality_counts = {
        grade.value: sum(decision.quality.grade is grade for decision in decisions)
        for grade in QualityGrade
    }
    entry_counts = {
        state.value: sum(decision.entry.state is state for decision in decisions)
        for state in EntryState
    }
    action_counts = {
        state.value: sum(decision.action_state is state for decision in decisions)
        for state in ActionState
    }

    n = len(decisions)
    if n > 0 and quality_counts[QualityGrade.UNRATED.value] / n > 0.50:
        warnings.append("more than 50% of decisions are Quality UNRATED")
    if n > 0 and entry_counts[EntryState.INSUFFICIENT_DATA.value] / n > 0.50:
        warnings.append("more than 50% of decisions are Entry INSUFFICIENT_DATA")
    if not daily_symbols:
        warnings.append("Daily Action List is empty")
    if not weekly_symbols:
        warnings.append("Weekly Review List is empty")
    if action_counts[ActionState.PRIORITY_REVIEW.value] == 0:
        warnings.append("no PRIORITY_REVIEW names in this snapshot")

    input_provenance = manifest.get("input_provenance", {}) or {}
    if input_provenance.get("network_issue_flag") is True:
        warnings.append("run manifest reports a network/rate-limit issue")
    if input_provenance.get("stale_market_data_fallback_used") is True:
        warnings.append("run manifest reports stale market-data fallback use")

    return {
        "ok": not errors,
        "root": str(root_path),
        "decision_date": manifest_date,
        "strategy_style": manifest.get("strategy_style"),
        "counts": {
            "decisions": n,
            "daily_attention": len(daily_symbols),
            "weekly_attention": len(weekly_symbols),
            "quality": quality_counts,
            "entry": entry_counts,
            "action": action_counts,
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an MVP decision snapshot structurally and semantically."
    )
    parser.add_argument("snapshot_root")
    parser.add_argument("--attention-cap", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = validate_snapshot(
        args.snapshot_root,
        attention_cap=max(1, int(args.attention_cap)),
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[{status}] {result['root']}")
        counts = result.get("counts", {})
        if counts:
            print(
                "decisions={decisions} daily={daily_attention} weekly={weekly_attention}".format(
                    **counts
                )
            )
            print(f"quality={counts['quality']}")
            print(f"entry={counts['entry']}")
            print(f"action={counts['action']}")
        for warning in result.get("warnings", []):
            print(f"[WARN] {warning}")
        for error in result.get("errors", []):
            print(f"[ERROR] {error}")

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
