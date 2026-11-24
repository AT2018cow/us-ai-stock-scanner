from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any

from ai_value_scanner.decision.action import map_action_state, map_action_state_v2
from ai_value_scanner.decision.discovery import validate_discovery_snapshot
from ai_value_scanner.decision.entry import (
    ENTRY_POLICY_VERSION,
    ENTRY_V2_POLICY_VERSION,
)
from ai_value_scanner.decision.quality import (
    QUALITY_POLICY_VERSION,
    QUALITY_V2_POLICY_VERSION,
)
from ai_value_scanner.decision.model import ActionState, EntryState, QualityGrade
from ai_value_scanner.decision.review import (
    REVIEW_EVIDENCE_VERSION,
    FollowedPrior,
    FollowedSecurity,
    build_followed_rows,
    with_review_evidence,
)
from ai_value_scanner.market_calendar import latest_completed_session, session_open_utc
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
    SEC_TICKER_CIK_CONFLICT,
)

# validator reason registry (module-level so tests can pin it): every
# exclusion reason_code produced anywhere must map to its stage here,
# or snapshots carrying it fail closed. Keep in sync with
# decision/universe.py reason constants.
EXCLUSION_REASON_TO_STAGE = {
    ACTIVE_ASSET_MISSING: ASSET_STAGE,
    NOT_TRADABLE: ASSET_STAGE,
    EXCHANGE_NOT_ENABLED: ASSET_STAGE,
    SEC_MAPPING_MISSING: SEC_MAPPING_STAGE,
    SEC_TICKER_CIK_CONFLICT: SEC_MAPPING_STAGE,
    SAMPLE_MAX_SYMBOLS_LIMIT: SAMPLE_STAGE,
    PRICE_MISSING: PRICE_LIQUIDITY_STAGE,
    PRICE_BELOW_MIN: PRICE_LIQUIDITY_STAGE,
    DOLLAR_VOLUME_MISSING: PRICE_LIQUIDITY_STAGE,
    DOLLAR_VOLUME_BELOW_MIN: PRICE_LIQUIDITY_STAGE,
}
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)
from ai_value_scanner.reporting.snapshot import (
    REPORT_RENDERER_REVISION,
    COMPATIBLE_RENDERER_REVISIONS,
    LIST_CONTEXT_RENDERER_REVISIONS,
    build_state_change_alert_records,
    collect_detailed_report_symbols,
    load_snapshot_decisions,
)
from ai_value_scanner.reporting.short_research import load_short_snapshot

SUPPORTED_POLICY_VERSIONS = {"v1", "v2"}
SUPPORTED_LAYOUT_VERSIONS = {"v1", "v2"}
KNOWN_QUALITY_POLICY_VERSIONS = {
    "company_quality_v1_2026-10-18",
    "company_quality_v2_2026-10-18",
    QUALITY_POLICY_VERSION,
    QUALITY_V2_POLICY_VERSION,
}
KNOWN_ENTRY_POLICY_VERSIONS = {
    "entry_quality_v1_2026-10-18",
    "entry_quality_v2_2026-10-18",
    ENTRY_POLICY_VERSION,
    ENTRY_V2_POLICY_VERSION,
}


@cache
def _ready_age_interval_matches(sessions: int, observed_since: str, decision_date: str) -> bool:
    first = date.fromisoformat(observed_since)
    last = date.fromisoformat(decision_date)
    if sessions < 1 or sessions > (last - first).days + 1:
        return False
    for _ in range(sessions - 1):
        last = latest_completed_session(session_open_utc(last))
        if last < first:
            return False
    return last == first


def _parse_stage_versions(token: str) -> tuple[str, str, str] | None:
    """Parse the integrated-builder token ``q=v2,e=v2,a=v2``."""
    parts: dict[str, str] = {}
    for chunk in str(token).split(","):
        if "=" not in chunk:
            return None
        key, value = chunk.split("=", 1)
        parts[key.strip()] = value.strip()
    if set(parts) != {"q", "e", "a"}:
        return None
    if any(value not in SUPPORTED_POLICY_VERSIONS for value in parts.values()):
        return None
    return parts["q"], parts["e"], parts["a"]


def _decision_stage_versions(
    decision,
    *,
    manifest_policy: str,
) -> tuple[str, str, str] | None:
    """Resolve per-decision stage versions, validating manifest consistency."""
    provenance = decision.provenance or {}
    token = provenance.get("decision_policy_version")
    if token is None:
        if manifest_policy == "v2":
            raise ValueError(
                f"{decision.symbol}: manifest declares policy v2 but the "
                "decision provenance has no stage versions"
            )
        return ("v1", "v1", "v1")
    stages = _parse_stage_versions(str(token))
    if stages is None:
        raise ValueError(
            f"{decision.symbol}: malformed decision_policy_version provenance "
            f"{token!r}"
        )
    expected = (manifest_policy, manifest_policy, manifest_policy)
    if stages != expected:
        raise ValueError(
            f"{decision.symbol}: stage versions {stages} do not match manifest "
            f"policy {manifest_policy!r}"
        )
    return stages


def check_ticker_map_rows(root_path: str | Path, manifest: dict[str, Any]) -> list[str]:
    """Verify the frozen ticker-map row set referenced by the manifest.

    Returns error strings (empty when valid or when the manifest carries no
    reference, keeping pre-rows snapshots valid). Checks file presence, SHA
    match against the manifest value, non-empty row list, and per-row
    symbol/cik presence.
    """
    errors: list[str] = []
    provenance = manifest.get("input_provenance")
    if not isinstance(provenance, dict):
        return errors
    filename = provenance.get("ticker_map_rows_file")
    if not filename:
        return errors
    path = Path(root_path) / str(filename)
    if not path.is_file():
        errors.append(f"ticker_map_rows file missing: {filename}")
        return errors
    try:
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception as exc:
        errors.append(f"ticker_map_rows unreadable: {type(exc).__name__}")
        return errors
    expected_sha = provenance.get("ticker_map_rows_sha256")
    if expected_sha and actual_sha != str(expected_sha):
        errors.append("ticker_map_rows sha256 mismatch vs manifest")
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"ticker_map_rows invalid JSON: {type(exc).__name__}")
        return errors
    if not isinstance(rows, list) or not rows:
        errors.append("ticker_map_rows is empty")
        return errors
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not str(row.get("symbol") or "").strip():
            errors.append(f"ticker_map_rows row {index} has empty symbol")
            break
        if not str(row.get("cik") or "").strip():
            errors.append(f"ticker_map_rows row {index} has empty cik")
            break
    return errors


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
    if not isinstance(manifest, dict):
        errors.append("run_manifest.json must decode to a JSON object")
        return {
            "ok": False,
            "root": str(root_path),
            "errors": errors,
            "warnings": warnings,
        }

    try:
        if "decisions_sha256" in manifest and (
            hashlib.sha256(required["decisions"].read_bytes()).hexdigest() != manifest["decisions_sha256"]
        ):
            errors.append("decisions.jsonl SHA256 differs from run_manifest.json")
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

    run_inputs = manifest.get("input_provenance")
    run_inputs = run_inputs if isinstance(run_inputs, dict) else {}
    from ai_value_scanner.decision.medium_term import MEDIUM_REVIEW_VERSION

    medium_version = run_inputs.get("medium_review_version")
    if medium_version not in (None, MEDIUM_REVIEW_VERSION):
        errors.append(f"unsupported medium_review_version {medium_version!r}")
    if any((decision.medium_review is not None) != (medium_version == MEDIUM_REVIEW_VERSION) for decision in decisions):
        errors.append("medium review evidence does not match the manifest feature version")
    from ai_value_scanner.fundamentals.coverage import FINANCIAL_COVERAGE_VERSION, business_context, filing_identity_error
    from ai_value_scanner.reporting.revisions import MEDIUM_FINANCIAL_RENDERER_REVISION

    coverage_version = run_inputs.get("financial_coverage_version")
    if coverage_version not in (None, FINANCIAL_COVERAGE_VERSION):
        errors.append(f"unsupported financial_coverage_version {coverage_version!r}")
    if (medium_version or coverage_version) and manifest.get("report_renderer_revision") != MEDIUM_FINANCIAL_RENDERER_REVISION:
        errors.append("medium or financial review requires its versioned renderer")
    for decision in decisions:
        coverage = decision.financial_review
        if coverage is None:
            continue
        if not isinstance(coverage, dict) or (
            coverage.get("version") != coverage_version or coverage_version != FINANCIAL_COVERAGE_VERSION
            or filing_identity_error(coverage, decision.provenance) is not None
            or coverage.get("business_context") != business_context(decision.provenance.get("sic"))
            or coverage.get("asof") != decision.decision_date
        ):
            errors.append(f"{decision.symbol}: financial coverage evidence does not match the archived filing")
    review_version = run_inputs.get("review_evidence_version")
    if review_version not in (None, REVIEW_EVIDENCE_VERSION):
        errors.append(f"unsupported review_evidence_version {review_version!r}")
    if review_version is None and any(decision.review_conditions or decision.ready_age is not None for decision in decisions):
        errors.append("decision review fields require a review_evidence_version")
    if review_version == REVIEW_EVIDENCE_VERSION:
        for decision in decisions:
            previous_daily = [decision.symbol] if any(
                item.route == "daily_retention" for item in decision.review_conditions
            ) else ()
            expected = with_review_evidence(decision, decision.ready_age, previous_daily=previous_daily)
            if decision.review_conditions != expected.review_conditions or decision.review_trigger != expected.review_trigger:
                errors.append(f"{decision.symbol}: review conditions do not match canonical decision evidence")
            age = decision.ready_age
            if run_inputs.get("market_data_mode") == "sip_eod" and age is None:
                errors.append(f"{decision.symbol}: missing Ready age for SIP review")
            if age is None:
                continue
            entry_unavailable = (
                decision.entry.state is EntryState.INSUFFICIENT_DATA
                or decision.entry.market_asof != decision.decision_date
            )
            should_count = decision.entry.state is EntryState.ENTRY_READY and not entry_unavailable
            try:
                valid_dates = age.observed_since is None or (
                    _ready_age_interval_matches(age.sessions, age.observed_since, decision.decision_date)
                )
            except (TypeError, ValueError):
                valid_dates = False
            if (
                bool(age.sessions) != should_count or not valid_dates
                or (age.reason == "current_entry_data_unavailable") != entry_unavailable
            ):
                errors.append(f"{decision.symbol}: Ready age conflicts with Entry state or observation date")

    manifest_date = str(manifest.get("decision_date", ""))
    policy_version = str(manifest.get("decision_policy_version", "v1"))
    layout_version = str(manifest.get("report_layout_version", "v1"))
    if policy_version not in SUPPORTED_POLICY_VERSIONS:
        errors.append(
            f"unsupported decision_policy_version {policy_version!r} "
            "(no silent v1 fallback)"
        )
    if layout_version not in SUPPORTED_LAYOUT_VERSIONS:
        errors.append(
            f"unsupported report_layout_version {layout_version!r} "
            "(no silent v1 fallback)"
        )
    versions_supported = (
        policy_version in SUPPORTED_POLICY_VERSIONS
        and layout_version in SUPPORTED_LAYOUT_VERSIONS
    )
    renderer_revision = manifest.get("report_renderer_revision")
    if renderer_revision is None:
        render_mode = "legacy"
        warnings.append(
            "legacy snapshot (no report_renderer_revision): byte-level render "
            "comparison is skipped; structural checks still run"
        )
    elif str(renderer_revision) not in COMPATIBLE_RENDERER_REVISIONS:
        if str(renderer_revision) == "mvp_report_renderer_2026-10-18b":
            render_mode = "legacy"
            warnings.append("Known historical renderer 2026-10-18b: structural validation only; current report bytes differ.")
        else:
            errors.append(
                f"unsupported report_renderer_revision {renderer_revision!r}"
            )
            render_mode = "unsupported"
    else:
        render_mode = "exact"

    manifest_quality_version = manifest.get("quality_policy_version")
    manifest_entry_version = manifest.get("entry_policy_version")
    if (
        manifest_quality_version is not None
        and str(manifest_quality_version) not in KNOWN_QUALITY_POLICY_VERSIONS
    ):
        errors.append(
            f"unsupported quality_policy_version {manifest_quality_version!r}"
        )
    if (
        manifest_entry_version is not None
        and str(manifest_entry_version) not in KNOWN_ENTRY_POLICY_VERSIONS
    ):
        errors.append(f"unsupported entry_policy_version {manifest_entry_version!r}")

    short_result = None
    try:
        archived_short = load_short_snapshot(root_path, manifest)
        if archived_short.enabled:
            short_result = archived_short
    except (OSError, ValueError) as exc:
        errors.append(f"invalid Short Research snapshot: {exc}")
    errors.extend(check_ticker_map_rows(root_path, manifest))
    for decision in decisions:
        if decision.decision_date != manifest_date:
            errors.append(
                f"{decision.symbol}: decision_date {decision.decision_date} "
                f"!= manifest {manifest_date}"
            )
        provenance = decision.provenance or {}
        if manifest_quality_version is not None:
            provenance_quality = provenance.get("quality_policy_version")
            if provenance_quality is None:
                errors.append(
                    f"{decision.symbol}: manifest records quality_policy_version "
                    "but the decision provenance is missing it"
                )
            elif str(provenance_quality) != str(manifest_quality_version):
                errors.append(
                    f"{decision.symbol}: quality_policy_version "
                    f"{provenance_quality!r} != manifest {manifest_quality_version!r}"
                )
        if manifest_entry_version is not None:
            provenance_entry = provenance.get("entry_policy_version")
            if provenance_entry is None:
                errors.append(
                    f"{decision.symbol}: manifest records entry_policy_version "
                    "but the decision provenance is missing it"
                )
            elif str(provenance_entry) != str(manifest_entry_version):
                errors.append(
                    f"{decision.symbol}: entry_policy_version "
                    f"{provenance_entry!r} != manifest {manifest_entry_version!r}"
                )
        if not versions_supported:
            continue
        try:
            stages = _decision_stage_versions(decision, manifest_policy=policy_version)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        action_version = "v1" if stages is None else stages[2]
        if action_version == "v2":
            expected_action, _ = map_action_state_v2(decision.quality, decision.entry)
        else:
            expected_action = map_action_state(
                decision.quality.grade,
                decision.entry.state,
            )
        if decision.action_state is not expected_action:
            errors.append(
                f"{decision.symbol}: action {decision.action_state.value} "
                f"!= canonical mapping {expected_action.value} "
                f"(action_version={action_version})"
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
            for item in discovery_sources.get("source_files", []):
                kind = item["source_kind"]
                if kind not in {"us_core", "thematic", "manual"}:
                    errors.append("unknown archived discovery source kind")
                    continue
                expected = "discovery_source_inputs/" + kind + ".csv"
                if item.get("archived_file") != expected:
                    errors.append("discovery source archive path mismatch: " + kind)
                actual_bytes = (root_path / expected).read_bytes()
                if hashlib.sha256(actual_bytes).hexdigest() != item["sha256"]:
                    errors.append("discovery source archive SHA256 mismatch: " + kind)
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
        # New exclusion reasons must be registered here AND in
        # decision/universe.py, or snapshots carrying them fail closed.
        reason_to_stage = EXCLUSION_REASON_TO_STAGE

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

    followed_stocks = None
    followed_error = run_inputs.get("review_watchlist_error")
    if followed_error is not None and (
        followed_error not in ("watchlist_unreadable", "watchlist_invalid")
        or "followed_stocks" in manifest or "review_watchlist_sha256" in run_inputs
    ):
        errors.append("invalid unavailable review watchlist evidence")
        followed_error = None
    if "followed_stocks" in manifest:
        try:
            rows = manifest["followed_stocks"]
            if not isinstance(rows, list) or not re.fullmatch(r"[a-f0-9]{64}", run_inputs.get("review_watchlist_sha256", "")):
                raise ValueError("expected followed rows and an input SHA256")
            entries = [FollowedSecurity(**{key: row[key] for key in FollowedSecurity.__dataclass_fields__}) for row in rows]
            generated = datetime.fromisoformat(manifest["generated_at_utc"])
            if len({entry.symbol for entry in entries}) != len(entries) or any(
                datetime.fromisoformat(entry.added_at_utc) > generated for entry in entries
            ):
                raise ValueError("followed securities must be unique and known as of generation")
            frozen_exclusions = universe_exclusions
            if candidate_universe is None:
                frozen_exclusions = [json.loads(line) for line in (root_path / "universe_exclusions.jsonl").read_text(
                    encoding="utf-8",
                ).splitlines() if line.strip()]
            prior_rows = manifest["followed_prior"]
            prior_session = run_inputs.get("review_watchlist_prior_session")
            prior_sha = run_inputs.get("review_watchlist_prior_manifest_sha256")
            if not isinstance(prior_rows, dict) or not set(prior_rows).issubset(entry.symbol for entry in entries):
                raise ValueError("unexpected followed prior evidence")
            if prior_session is None:
                if prior_rows or prior_sha is not None:
                    raise ValueError("prior observations require a prior session and manifest SHA256")
            elif (
                prior_session != latest_completed_session(session_open_utc(date.fromisoformat(manifest_date))).isoformat()
                or not re.fullmatch(r"[a-f0-9]{64}", prior_sha or "")
            ):
                raise ValueError("expected prior trading session and manifest SHA256")
            previous = {symbol: FollowedPrior(**prior) for symbol, prior in prior_rows.items()}
            expected_rows = build_followed_rows(entries, decisions, previous, daily_symbols, frozen_exclusions)
            for row, expected_row in zip(rows, expected_rows, strict=True):
                if row != expected_row:
                    raise ValueError(f"{row['symbol']}: followed-stock outcome conflicts with snapshot evidence")
            followed_stocks = rows
        except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
            errors.append(f"invalid followed_stocks: {exc}")
    elif "review_watchlist_sha256" in run_inputs or "followed_prior" in manifest:
        errors.append("snapshot is missing followed_stocks for the archived review watchlist")

    if versions_supported and render_mode == "exact":
        actual_daily = required["daily"].read_text(encoding="utf-8")
        actual_weekly = required["weekly"].read_text(encoding="utf-8")
        streaks_by_symbol = manifest.get("in_list_streaks")
        if "in_list_streaks" not in manifest:
            # Older manifests did not freeze this presentation field. Recover
            # the archived badges and validate the rest of each report normally.
            warnings.append("legacy snapshot: in-list streaks recovered from report badges")
            streaks_by_symbol = {}
            for report, symbols_in_list in (
                (actual_daily, set(daily_symbols)), (actual_weekly, set(weekly_symbols))
            ):
                for symbol, days in re.findall(
                    r"^<summary><b>#\d+ ([^<> ]+)</b> \[(?:NEW|LIST (\d+)d(?: · GRACE 1/2)?)\]",
                    report, re.MULTILINE,
                ):
                    if symbol not in symbols_in_list:
                        continue
                    value = int(days or 1)
                    if streaks_by_symbol.setdefault(symbol, value) != value:
                        errors.append(f"{symbol}: inconsistent archived in-list streaks")
        elif streaks_by_symbol is not None and (
            not isinstance(streaks_by_symbol, dict)
            or set(streaks_by_symbol) != set(daily_symbols)
            or any(type(days) is not int or days < 1 for days in streaks_by_symbol.values())
        ):
            errors.append("in_list_streaks must contain one positive integer per daily symbol")
            streaks_by_symbol = None
        legacy_lists_paused = None
        if renderer_revision in LIST_CONTEXT_RENDERER_REVISIONS:
            provenance = manifest.get("input_provenance")
            legacy_lists_paused = (
                isinstance(provenance, dict) and provenance.get("legacy_lists_paused") is True
            )
        expected_daily = render_action_list(
            daily,
            title="Daily Action List",
            cadence="daily",
            layout_version=layout_version,
            all_decisions=decisions,
            streaks_by_symbol=streaks_by_symbol,
            legacy_lists_paused=legacy_lists_paused,
            renderer_revision=renderer_revision,
            followed_stocks=followed_stocks,
            followed_unavailable=followed_error,
            short_research=short_result,
            short_csv_rel=(
                "./short_candidates.csv" if short_result is not None else None
            ),
        )
        if actual_daily != expected_daily:
            errors.append("action_list.md does not match canonical StockDecision rendering")

        expected_weekly = render_action_list(
            weekly,
            title="Weekly Review List",
            cadence="weekly",
            layout_version=layout_version,
            all_decisions=decisions,
            streaks_by_symbol=streaks_by_symbol,
            legacy_lists_paused=legacy_lists_paused,
            renderer_revision=renderer_revision,
            followed_stocks=followed_stocks,
            followed_unavailable=followed_error,
            short_research=short_result,
            short_csv_rel=(
                "./short_candidates.csv" if short_result is not None else None
            ),
        )
        if actual_weekly != expected_weekly:
            errors.append("weekly_review.md does not match canonical StockDecision rendering")

        detail_symbols = collect_detailed_report_symbols(
            daily=daily,
            weekly=weekly,
            decisions=decisions,
            layout_version=layout_version,
            followed_stocks=followed_stocks,
        )
        for symbol in sorted(detail_symbols):
            path = required["detailed"] / f"{symbol}.md"
            if not path.exists():
                errors.append(f"missing detailed report for {symbol}: {path}")
                continue
            decision = decision_by_symbol.get(symbol)
            if decision is None:
                errors.append(f"detailed report for unknown symbol: {symbol}")
                continue
            expected = render_detailed_report(decision, layout_version=layout_version, renderer_revision=renderer_revision)
            actual = path.read_text(encoding="utf-8")
            if actual != expected:
                errors.append(
                    f"detailed/{symbol}.md does not match canonical StockDecision rendering"
                )
    elif versions_supported and render_mode == "legacy":
        # Legacy snapshots were written by an earlier renderer revision;
        # byte-exact comparison is impossible by construction. Run structural
        # membership checks instead and keep the explicit warning recorded
        # above. Current-format snapshots never take this path.
        daily_text = required["daily"].read_text(encoding="utf-8")
        missing_daily = [
            symbol for symbol in daily_symbols if symbol not in daily_text
        ]
        if missing_daily:
            errors.append(
                "legacy action_list.md does not mention daily symbols: "
                f"{missing_daily[:10]}"
            )
        weekly_text = required["weekly"].read_text(encoding="utf-8")
        missing_weekly = [
            symbol for symbol in weekly_symbols if symbol not in weekly_text
        ]
        if missing_weekly:
            errors.append(
                "legacy weekly_review.md does not mention weekly symbols: "
                f"{missing_weekly[:10]}"
            )
        legacy_detail_symbols = set(daily_symbols) | set(weekly_symbols)
        for symbol in sorted(legacy_detail_symbols):
            path = required["detailed"] / f"{symbol}.md"
            if not path.exists():
                errors.append(f"missing detailed report for {symbol}: {path}")

    for report_name in ("daily", "weekly"):
        report = required[report_name].read_text(encoding="utf-8")
        for filename in set(re.findall(r"\./detailed/([\w.-]+\.md)\)", report)):
            if not (required["detailed"] / filename).is_file():
                errors.append(f"missing linked detailed report: {filename}")

    # State-change alerts (R07): manifest, JSONL, and report membership must
    # describe the same canonical selection.
    manifest_alerts = manifest.get("state_change_alerts")
    if manifest_alerts is None:
        warnings.append("run manifest has no state_change_alerts summary")
    elif not isinstance(manifest_alerts, dict):
        errors.append("state_change_alerts manifest section must be an object")
    else:
        alert_rows, expected_alert_summary = build_state_change_alert_records(
            daily=daily,
            weekly=weekly,
            decisions=decisions,
        )
        if manifest_alerts.get("policy") != expected_alert_summary["policy"]:
            errors.append("state_change_alerts policy version mismatch")
        for scope in ("daily", "weekly"):
            expected_scope = expected_alert_summary[scope]
            actual_scope = manifest_alerts.get(scope)
            if not isinstance(actual_scope, dict):
                errors.append(f"state_change_alerts.{scope} must be an object")
                continue
            if actual_scope.get("total") != expected_scope["total"]:
                errors.append(
                    f"state_change_alerts.{scope}.total "
                    f"{actual_scope.get('total')} != {expected_scope['total']}"
                )
            if list(actual_scope.get("shown_symbols") or []) != expected_scope[
                "shown_symbols"
            ]:
                errors.append(
                    f"state_change_alerts.{scope}.shown_symbols do not match "
                    "the canonical downgrade selection"
                )
            if bool(actual_scope.get("truncated")) != expected_scope["truncated"]:
                errors.append(f"state_change_alerts.{scope}.truncated mismatch")
        alerts_path = root_path / "state_change_alerts.jsonl"
        if not alerts_path.exists():
            errors.append("manifest declares state_change_alerts but JSONL is missing")
        else:
            try:
                actual_rows = [
                    json.loads(line)
                    for line in alerts_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except (ValueError, TypeError) as exc:
                errors.append(
                    f"invalid state_change_alerts.jsonl: {type(exc).__name__}: {exc}"
                )
                actual_rows = []
            if actual_rows != alert_rows:
                errors.append(
                    "state_change_alerts.jsonl does not match the canonical "
                    "downgrade selection"
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


class SnapshotValidationError(ValueError):
    pass


def require_valid_snapshot(root: Path, *, attention_cap: int) -> None:
    try:
        result = validate_snapshot(root, attention_cap=attention_cap)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SnapshotValidationError(f"official snapshot failed validation: {exc}") from exc
    if not result["ok"]:
        raise SnapshotValidationError(
            "official snapshot failed validation: " + "; ".join(result["errors"])
        )
