#!/usr/bin/env python3
"""Audit frozen SEC coverage/discovery and replay as-of SIC and midterm evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.decision.medium_term import build_medium_reviews, classifications_asof, market_profile
from ai_value_scanner.decision.review import issuer_cik
from ai_value_scanner.fundamentals.coverage import audit_filing
from ai_value_scanner.research.coverage_audit import (
    compare_financial_grades, discovery_audit, discovery_identities, financial_inventory,
)
from ai_value_scanner.reporting.snapshot import load_snapshot_decisions, load_snapshot_manifest
from ai_value_scanner.swing.events import timestamp
from ai_value_scanner.validation.decision_snapshot import require_valid_snapshot


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _snapshot(path):
    manifest = load_snapshot_manifest(path)
    cap = max(1, *(len(manifest[key]) for key in ("daily_symbols", "weekly_symbols")))
    require_valid_snapshot(path, attention_cap=cap)
    return manifest, load_snapshot_decisions(path)


def _optional_rows(path):
    return _rows(path) if path.is_file() else None


def _audit(args):
    started = perf_counter()
    manifest, decisions = _snapshot(args.snapshot)
    baseline_symbols = None
    baseline_identities = None
    prior_decisions = None
    discovery_baseline_manifest = None
    if args.baseline:
        discovery_baseline_manifest, prior_decisions = _snapshot(args.baseline)
        if manifest["decision_date"] != discovery_baseline_manifest["decision_date"]:
            raise ValueError("comparison snapshots must be from the same session")
        settings = ("market_data_feed", "market_data_mode")
        left = manifest.get("input_provenance") or {}
        right = discovery_baseline_manifest.get("input_provenance") or {}
        if any(left.get(key) != right.get(key) for key in settings):
            raise ValueError("comparison snapshots must use the same market feed and mode")
        baseline_symbols = {item.symbol for item in prior_decisions}
        prior_exclusions = args.baseline / "universe_exclusions.jsonl"
        if prior_exclusions.is_file():
            baseline_symbols.update(item["symbol"] for item in _rows(prior_exclusions))
        prior_ticker = args.baseline / "ticker_map_rows.json"
        baseline_identities = discovery_identities(prior_decisions, _read(prior_ticker) if prior_ticker.is_file() else [])
    inputs = _optional_rows(args.snapshot / "discovery_memberships.jsonl") if manifest.get("discovery_sources") else None
    if args.source_baseline:
        if inputs is None:
            raise ValueError("the source comparison requires archived discovery memberships")
        baseline_symbols = {row["symbol"] for row in inputs if row["source_kind"] == args.source_baseline}
        if not baseline_symbols:
            raise ValueError("the requested source baseline is empty")
    ticker_path = args.snapshot / "ticker_map_rows.json"
    ticker = _read(ticker_path) if ticker_path.is_file() else []
    discovery = discovery_audit(
        decisions, manifest, memberships=inputs,
        exclusions=_optional_rows(args.snapshot / "universe_exclusions.jsonl"), ticker_rows=ticker,
        rejections=_optional_rows(args.snapshot / "discovery_source_rejections.jsonl") or (),
        baseline=baseline_symbols, baseline_identities=baseline_identities,
    )
    if discovery_baseline_manifest:
        discovery["baseline_kind"] = "same_session_snapshot"
        discovery["comparison_feed_verified"] = bool(
            (discovery_baseline_manifest.get("input_provenance") or {}).get("market_data_feed")
        )
        discovery["baseline_scan_elapsed_seconds"] = (
            discovery_baseline_manifest.get("input_provenance") or {}
        ).get("scan_elapsed_seconds")
    elif args.source_baseline:
        discovery["baseline_kind"] = "frozen_source_slice"
        discovery["baseline_source"] = args.source_baseline
    cases = financial_inventory(decisions)
    groups = Counter((row["form"], row["currency"], row["fallback_status"]) for row in cases if row["latest_periodic_covered"] is False)
    cutoff = date.fromisoformat(manifest["decision_date"])
    candidates = []
    for path in args.filing:
        evidence = path.read_bytes()
        supplied = json.loads(evidence)
        key = (issuer_cik(supplied.get("cik")), supplied.get("accession"))
        matching = [item for item in cases if (item["cik"], item["accession"]) == key]
        if not matching:
            raise ValueError(f"{path.name}: filing identity is absent from the financial inventory")
        by_symbol = {decision.symbol: decision.provenance for decision in decisions}
        audits = [audit_filing(supplied, asof=cutoff, provenance=by_symbol[item["symbol"]]) for item in matching]
        candidate = audits[0]
        if any(item != candidate for item in audits[1:]):
            raise ValueError(f"{path.name}: canonical issuer evidence conflicts across share classes")
        candidates.append({
            **candidate, "input_sha256": sha256(evidence).hexdigest(),
            "symbols": [row["symbol"] for row in matching],
            "grades_before": {row["symbol"]: row["grade"] for row in matching},
        })
    return {
        "snapshot_manifest_sha256": sha256((args.snapshot / "run_manifest.json").read_bytes()).hexdigest(),
        "audit_elapsed_seconds": perf_counter() - started,
        "discovery": discovery,
        "financial": {
            "cases": cases,
            "latest_periodic_uncovered": [{"form": form, "currency": currency, "fallback_status": status, "count": count}
                                           for (form, currency, status), count in groups.most_common()],
            "exact_filing_candidates": candidates,
            "recovered_candidate_accessions": len({(row["cik"], row["accession"]) for row in candidates if row["status"] == "recovered_candidate"}),
            "grade_comparison": compare_financial_grades(prior_decisions, decisions) if prior_decisions is not None else None,
        },
    }


def _replay(args):
    manifest, decisions = _snapshot(args.snapshot)
    frozen_bytes = args.input.read_bytes()
    evidence = json.loads(frozen_bytes)
    if evidence["session"] != manifest["decision_date"] or evidence["feed"] != "sip" or evidence["adjustment"] != "raw":
        raise ValueError("replay requires session-matched raw SIP bars")
    cutoff = timestamp(evidence["asof"])
    if cutoff != timestamp(manifest["generated_at_utc"]):
        raise ValueError("classification/market cutoff must match frozen snapshot generation")
    decision_day = date.fromisoformat(evidence["session"])
    groups = classifications_asof(evidence["classifications"], cutoff)
    configured = evidence.get("splits", {})
    profiles = {
        sym: market_profile(rows, decision_day, splits=configured[sym])
        for sym, rows in evidence["bars"].items() if sym in configured and isinstance(configured[sym], list)
    }
    review = build_medium_reviews(
        decisions, profiles, profiles.get("QQQ", {}), groups,
        session=evidence["session"], classification_asof=cutoff.isoformat(),
        classification_source=evidence.get("classification_source", "frozen_sic_sources"),
    )
    return {"input_sha256": sha256(frozen_bytes).hexdigest(), "reviews": review}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--snapshot", type=Path, required=True)
    baselines = audit.add_mutually_exclusive_group()
    baselines.add_argument("--baseline", type=Path)
    baselines.add_argument("--source-baseline", choices=("us_core", "thematic", "manual"))
    audit.add_argument("--filing", type=Path, action="append", default=[])
    replay = commands.add_parser("replay")
    replay.add_argument("--snapshot", type=Path, required=True)
    replay.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(_audit(args) if args.command == "audit" else _replay(args), indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"coverage review: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
