from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from ai_value_scanner.decision.action import map_action_state
from ai_value_scanner.decision.discovery import validate_discovery_snapshot
from ai_value_scanner.decision.model import ActionState, EntryState, QualityGrade
from ai_value_scanner.decision.universe import (
    ACTIVE_ASSET_MISSING,
    ASSET_STAGE,
    CANDIDATE_UNIVERSE_CONTRACT_VERSION,
    DOLLAR_VOLUME_BELOW_MIN,
    DOLLAR_VOLUME_MISSING,
    EXCHANGE_NOT_ENABLED,
    NOT_TRADABLE,
    PRICE_BELOW_MIN,
    PRICE_LIQUIDITY_STAGE,
    PRICE_MISSING,
    SAMPLE_MAX_SYMBOLS_LIMIT,
    SAMPLE_STAGE,
    SEC_MAPPING_MISSING,
    SEC_MAPPING_STAGE,
)
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

    candidate_universe = manifest.get("candidate_universe")
    discovery_sources = manifest.get("discovery_sources")
    if discovery_sources is not None:
        if not isinstance(discovery_sources, dict):
            errors.append("discovery_sources manifest must be an object")
            discovery_sources = {}
        try:
            membership_path = root_path / "discovery_memberships.jsonl"
            rejected_path = root_path / "discovery_source_rejections.jsonl"
            memberships = [
                json.loads(line)
                for line in membership_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            source_rejections = [
                json.loads(line)
                for line in rejected_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            excluded_path = root_path / "universe_exclusions.jsonl"
            excluded_members = [
                json.loads(line)
                for line in excluded_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            errors.extend(validate_discovery_snapshot(
                memberships=memberships,
                rejected=source_rejections,
                summary=discovery_sources,
                discovery_symbols=set(symbols).union(
                    row["symbol"] for row in excluded_members
                ),
                decision_date=manifest_date,
            ))
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append(
                "invalid discovery source snapshot: " +
                type(exc).__name__ + ": " + str(exc)
            )
    universe_exclusions: list[dict[str, Any]] = []
    if candidate_universe is not None:
        if not isinstance(candidate_universe, dict):
            errors.append("candidate_universe manifest section must be an object")
            candidate_universe = {}
        universe_path = root_path / "universe_exclusions.jsonl"
        if not universe_path.exists():
            errors.append(
                "manifest declares candidate_universe but universe_exclusions.jsonl is missing"
            )
        else:
            try:
                universe_exclusions = [
                    json.loads(line)
                    for line in universe_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except Exception as exc:
                errors.append(
                    "invalid universe_exclusions.jsonl: "
                    f"{type(exc).__name__}: {exc}"
                )
                universe_exclusions = []

        if candidate_universe.get("contract_version") != CANDIDATE_UNIVERSE_CONTRACT_VERSION:
            errors.append(
                "candidate_universe contract_version does not match current contract"
            )
        reason_to_stage = {
            ACTIVE_ASSET_MISSING: ASSET_STAGE,
            NOT_TRADABLE: ASSET_STAGE,
            EXCHANGE_NOT_ENABLED: ASSET_STAGE,
            SEC_MAPPING_MISSING: SEC_MAPPING_STAGE,
            SAMPLE_MAX_SYMBOLS_LIMIT: SAMPLE_STAGE,
            PRICE_MISSING: PRICE_LIQUIDITY_STAGE,
            PRICE_BELOW_MIN: PRICE_LIQUIDITY_STAGE,
            DOLLAR_VOLUME_MISSING: PRICE_LIQUIDITY_STAGE,
            DOLLAR_VOLUME_BELOW_MIN: PRICE_LIQUIDITY_STAGE,
        }

        exclusion_symbols: list[str] = []
        for index, item in enumerate(universe_exclusions, start=1):
            if not isinstance(item, dict):
                errors.append(f"universe exclusion row {index} is not an object")
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            stage = str(item.get("exclusion_stage") or "").strip()
            reason = str(item.get("reason_code") or "").strip()
            if not symbol:
                errors.append(f"universe exclusion row {index} has empty symbol")
            else:
                exclusion_symbols.append(symbol)
            if item.get("status") != "excluded":
                errors.append(f"{symbol or index}: universe exclusion status must be excluded")
            if not stage:
                errors.append(f"{symbol or index}: exclusion_stage is missing")
            if not reason:
                errors.append(f"{symbol or index}: reason_code is missing")
            elif reason not in reason_to_stage:
                errors.append(f"{symbol or index}: unknown exclusion reason {reason}")
            elif stage != reason_to_stage[reason]:
                errors.append(
                    f"{symbol or index}: exclusion stage {stage} "
                    f"does not match reason {reason}"
                )

            if stage == PRICE_LIQUIDITY_STAGE:
                if str(item.get("market_data_feed") or "") != str(
                    candidate_universe.get("market_data_feed") or ""
                ):
                    errors.append(
                        f"{symbol}: price/liquidity exclusion feed does not match manifest"
                    )
                try:
                    if float(item.get("min_price")) != float(
                        candidate_universe.get("min_price")
                    ):
                        errors.append(f"{symbol}: min_price does not match manifest")
                    if float(item.get("min_dollar_volume")) != float(
                        candidate_universe.get("min_dollar_volume")
                    ):
                        errors.append(
                            f"{symbol}: min_dollar_volume does not match manifest"
                        )
                except (TypeError, ValueError):
                    errors.append(
                        f"{symbol}: invalid price/liquidity threshold provenance"
                    )

            if reason in {DOLLAR_VOLUME_BELOW_MIN, DOLLAR_VOLUME_MISSING}:
                if str(item.get("market_data_feed") or "") != str(
                    candidate_universe.get("market_data_feed") or ""
                ):
                    errors.append(
                        f"{symbol}: liquidity exclusion feed does not match manifest"
                    )
                try:
                    row_threshold = float(item.get("min_dollar_volume"))
                    manifest_threshold = float(
                        candidate_universe.get("min_dollar_volume")
                    )
                    if row_threshold != manifest_threshold:
                        errors.append(
                            f"{symbol}: min_dollar_volume does not match manifest"
                        )
                except (TypeError, ValueError):
                    errors.append(f"{symbol}: invalid min_dollar_volume provenance")
                if reason == DOLLAR_VOLUME_BELOW_MIN:
                    try:
                        if float(item.get("dollar_volume")) >= float(
                            item.get("min_dollar_volume")
                        ):
                            errors.append(
                                f"{symbol}: DOLLAR_VOLUME_BELOW_MIN value is not below threshold"
                            )
                    except (TypeError, ValueError):
                        errors.append(f"{symbol}: invalid dollar_volume provenance")

            if reason == PRICE_BELOW_MIN:
                try:
                    if float(item.get("price")) >= float(item.get("min_price")):
                        errors.append(
                            f"{symbol}: PRICE_BELOW_MIN value is not below threshold"
                        )
                    if float(item.get("min_price")) != float(
                        candidate_universe.get("min_price")
                    ):
                        errors.append(f"{symbol}: min_price does not match manifest")
                except (TypeError, ValueError):
                    errors.append(f"{symbol}: invalid price threshold provenance")

        if len(exclusion_symbols) != len(set(exclusion_symbols)):
            errors.append("universe_exclusions.jsonl contains duplicate symbols")
        decision_symbol_set = set(symbols)
        exclusion_symbol_set = set(exclusion_symbols)
        overlap = sorted(decision_symbol_set.intersection(exclusion_symbol_set))
        if overlap:
            errors.append(f"decision/exclusion symbol overlap: {overlap[:10]}")

        reason_counts = dict(
            sorted(
                Counter(
                    str(item.get("reason_code") or "")
                    for item in universe_exclusions
                    if isinstance(item, dict)
                ).items()
            )
        )
        stage_counts = dict(
            sorted(
                Counter(
                    str(item.get("exclusion_stage") or "")
                    for item in universe_exclusions
                    if isinstance(item, dict)
                ).items()
            )
        )
        expected_reason_counts = dict(
            sorted((candidate_universe.get("exclusion_reason_counts") or {}).items())
        )
        expected_stage_counts = dict(
            sorted((candidate_universe.get("exclusion_stage_counts") or {}).items())
        )
        if reason_counts != expected_reason_counts:
            errors.append(
                "candidate_universe exclusion_reason_counts do not match JSONL"
            )
        if stage_counts != expected_stage_counts:
            errors.append(
                "candidate_universe exclusion_stage_counts do not match JSONL"
            )

        try:
            discovery_n = int(candidate_universe.get("discovery_unique_symbols"))
            decision_n = int(candidate_universe.get("decision_universe_symbols"))
            excluded_n = int(candidate_universe.get("excluded_symbols"))
            mapped_n = int(candidate_universe.get("tradable_mapped_symbols"))
            post_sample_n = int(candidate_universe.get("post_sample_symbols"))
        except (TypeError, ValueError):
            errors.append("candidate_universe count fields must be integers")
        else:
            if decision_n != len(decisions):
                errors.append(
                    f"candidate_universe decision count {decision_n} != JSONL {len(decisions)}"
                )
            if excluded_n != len(universe_exclusions):
                errors.append(
                    "candidate_universe excluded count "
                    f"{excluded_n} != exclusions JSONL {len(universe_exclusions)}"
                )
            if discovery_n != decision_n + excluded_n:
                errors.append(
                    "candidate-universe conservation failed: discovery != decisions + exclusions"
                )
            sample_excluded = stage_counts.get("sample_limit", 0)
            price_liquidity_excluded = stage_counts.get(
                "price_liquidity_prefilter", 0
            )
            if mapped_n != post_sample_n + sample_excluded:
                errors.append(
                    "candidate-universe mapped/sample conservation failed"
                )
            if post_sample_n != decision_n + price_liquidity_excluded:
                errors.append(
                    "candidate-universe prefilter conservation failed"
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
    integrity_counts = {
        "latest_periodic_filing_not_covered": sum(
            any(
                item.code == "latest_periodic_filing_not_covered"
                for item in decision.quality.missing
            )
            for decision in decisions
        ),
        "fundamental_currency_unsupported": sum(
            any(
                item.code == "fundamental_currency_unsupported"
                for item in decision.quality.missing
            )
            for decision in decisions
        ),
    }
    fallback_status_counts: dict[str, int] = {}
    fallback_used_count = 0
    for decision in decisions:
        status = decision.provenance.get("fundamental_edgartools_fallback_status")
        if status:
            token = str(status)
            fallback_status_counts[token] = fallback_status_counts.get(token, 0) + 1
        if decision.provenance.get("fundamental_edgartools_fallback_used") is True:
            fallback_used_count += 1
    fallback_counts = {
        "edgartools_10q_used": fallback_used_count,
        "status": dict(sorted(fallback_status_counts.items())),
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
    if integrity_counts["latest_periodic_filing_not_covered"] > 0:
        warnings.append(
            "latest periodic filing is not covered by recognized Company Facts for "
            f"{integrity_counts['latest_periodic_filing_not_covered']} decision(s)"
        )
    if integrity_counts["fundamental_currency_unsupported"] > 0:
        warnings.append(
            "non-USD core monetary facts are unsupported for "
            f"{integrity_counts['fundamental_currency_unsupported']} decision(s)"
        )

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
            "fundamental_integrity": integrity_counts,
            "fundamental_fallback": fallback_counts,
            "candidate_universe": (
                dict(candidate_universe)
                if isinstance(candidate_universe, dict)
                else None
            ),
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
            if counts.get("candidate_universe"):
                print(f"candidate_universe={counts['candidate_universe']}")
            print(f"fundamental_integrity={counts.get('fundamental_integrity', {})}")
            print(f"fundamental_fallback={counts.get('fundamental_fallback', {})}")
        for warning in result.get("warnings", []):
            print(f"[WARN] {warning}")
        for error in result.get("errors", []):
            print(f"[ERROR] {error}")

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
