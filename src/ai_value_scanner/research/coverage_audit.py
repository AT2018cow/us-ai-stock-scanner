"""Read-only financial and three-source discovery acceptance diagnostics."""
from __future__ import annotations

from collections import Counter
from itertools import chain, combinations
from typing import Iterable, Mapping

from ai_value_scanner.decision.discovery import SOURCE_KINDS, assert_memberships_asof
from ai_value_scanner.decision.model import StockDecision
from ai_value_scanner.decision.review import issuer_cik
from ai_value_scanner.fundamentals.coverage import business_context


def financial_inventory(decisions: Iterable[StockDecision]) -> list[dict]:
    rows = []
    for decision in decisions:
        provenance = decision.provenance
        flag = provenance.get("fundamental_facts_cover_latest_periodic")
        supported = provenance.get("fundamental_currency_supported")
        if flag is True and supported is True and decision.quality.grade.value != "UNRATED":
            continue
        rows.append({
            "symbol": decision.symbol, "cik": issuer_cik(provenance.get("cik")),
            "form": provenance.get("fundamental_latest_periodic_form"),
            "accession": provenance.get("fundamental_latest_periodic_accession"),
            "filed": provenance.get("fundamental_latest_periodic_filing_date"),
            "currency": provenance.get("fundamental_reporting_currency"),
            "currency_supported": supported, "latest_periodic_covered": flag,
            "fallback_status": provenance.get("fundamental_edgartools_fallback_status"),
            "fallback_version": provenance.get("fundamental_edgartools_fallback_version"),
            "grade": decision.quality.grade.value, "business_model": business_context(provenance.get("sic"))["model"],
            "share_basis": provenance.get("share_count_basis"), "share_tag": provenance.get("share_count_tag"),
        })
    return rows


def _slice(symbols: set[str], decisions: set[str], excluded: set[str], daily: set[str], weekly: set[str], identities: Mapping) -> dict:
    resolved = {identities[symbol] for symbol in symbols if symbol in identities}
    included = {identities[symbol] for symbol in symbols & decisions if symbol in identities}
    excluded_issuers = {identities[symbol] for symbol in symbols & excluded if symbol in identities} - included
    return {
        "security": {
            "discovered": len(symbols), "decisions": len(symbols & decisions),
            "excluded": len(symbols & excluded), "undetermined": len(symbols - decisions - excluded),
            "daily": len(symbols & daily), "weekly": len(symbols & weekly),
            "daily_share": len(symbols & daily) / len(symbols) if symbols else None,
            "weekly_share": len(symbols & weekly) / len(symbols) if symbols else None,
        },
        "issuer": {
            "known": len(resolved), "decisions": len(included), "excluded_only": len(excluded_issuers),
            "undetermined": len(resolved - included - excluded_issuers),
            "daily": len({identities[sym] for sym in symbols & daily if sym in identities}),
            "weekly": len({identities[sym] for sym in symbols & weekly if sym in identities}),
            "symbols_with_unknown_cik": len(symbols - identities.keys()),
        },
    }


def discovery_identities(decisions: Iterable[StockDecision], ticker_rows: Iterable[Mapping]) -> dict[str, str]:
    candidates = chain(
        ((row["symbol"], issuer_cik(row.get("cik"))) for row in ticker_rows),
        ((decision.symbol, issuer_cik(decision.provenance.get("cik"))) for decision in decisions),
    )
    identities, conflicts = {}, set()
    for symbol, cik in candidates:
        if cik is not None:
            if symbol in identities and identities[symbol] != cik:
                conflicts.add(symbol)
            identities[symbol] = cik
    return {symbol: cik for symbol, cik in identities.items() if symbol not in conflicts}


def discovery_audit(
    decisions: Iterable[StockDecision], manifest: Mapping, *, memberships: Iterable[dict] | None,
    exclusions: Iterable[Mapping] | None, ticker_rows: Iterable[Mapping] = (),
    rejections: Iterable[Mapping] = (), baseline: set[str] | None = None,
    baseline_identities: Mapping[str, str] | None = None,
) -> dict:
    decisions = tuple(decisions)
    names = {decision.symbol for decision in decisions}
    exclusion_rows = tuple(exclusions or ())
    excluded = {row["symbol"] for row in exclusion_rows}
    if len(names) != len(decisions) or names & excluded or len(excluded) != len(exclusion_rows):
        raise ValueError("decision and exclusion symbols must form a disjoint partition")
    daily, weekly = set(manifest["daily_symbols"]), set(manifest["weekly_symbols"])
    if not daily <= names or not weekly <= names:
        raise ValueError("review symbols must be present in decisions")
    identities = discovery_identities(decisions, ticker_rows)
    groups = {source: set() for source in SOURCE_KINDS}
    repeats = Counter()
    basis = "archived_source_inputs"
    if memberships is None:
        basis = "archive_union_only" if exclusions is not None and manifest.get("candidate_universe") else "universe_approximation"
        union = names | excluded
    else:
        rows = tuple(memberships)
        assert_memberships_asof(list(rows), manifest["decision_date"])
        for row in rows:
            source, symbol = row["source_kind"], row["symbol"]
            repeats[source] += int(symbol in groups[source])
            groups[source].add(symbol)
        union = set().union(*groups.values())
        if union != names | excluded:
            raise ValueError("archived discoveries do not close against decisions and exclusions")
    rejected = Counter((row["source_kind"], row["reason_code"]) for row in rejections)
    source_summary = {}
    for kind, members in groups.items():
        if memberships is None:
            break
        source_summary[kind] = {
            **_slice(members, names, excluded, daily, weekly, identities),
            "valid_repeated_memberships": repeats[kind],
            "rejected_duplicate_memberships": rejected[kind, "SOURCE_DUPLICATE_MEMBERSHIP"],
            "new_to_baseline": len(members - baseline) if baseline is not None else None,
            "new_daily": len((members - baseline) & daily) if baseline is not None else None,
        }
    overlaps = []
    for first, second in combinations(SOURCE_KINDS, 2):
        if memberships is None:
            break
        shared = groups[first] & groups[second]
        left = {identities[name] for name in groups[first] if name in identities}
        right = {identities[name] for name in groups[second] if name in identities}
        overlaps.append({"sources": [first, second], "securities": len(shared), "issuers": len(left & right)})
    reference_ids = identities if baseline_identities is None else baseline_identities
    baseline_known = {reference_ids[sym] for sym in baseline if sym in reference_ids} if baseline is not None else None
    baseline_unknown = len(baseline - reference_ids.keys()) if baseline is not None else None
    new = sorted(union - baseline) if baseline is not None else None
    return {
        "session": manifest["decision_date"], "universe_basis": basis,
        "union": _slice(union, names, excluded, daily, weekly, identities),
        "source_counts": source_summary, "intersections": overlaps,
        "new_symbols": new, "removed_symbols": sorted(baseline - union) if baseline is not None else None,
        "new_known_issuers": len({identities[sym] for sym in union if sym in identities} - baseline_known)
        if baseline_known is not None and baseline_unknown == 0 else None,
        "baseline_symbols_with_unknown_cik": baseline_unknown,
        "scan_elapsed_seconds": (manifest.get("input_provenance") or {}).get("scan_elapsed_seconds"),
    }


def compare_financial_grades(baseline: Iterable[StockDecision], candidate: Iterable[StockDecision]) -> dict:
    earlier = {decision.symbol: decision for decision in baseline}
    changes, filings_changed, unknown = [], [], []
    for decision in candidate:
        prior = earlier.get(decision.symbol)
        if prior is None:
            continue
        cik = issuer_cik(decision.provenance.get("cik"))
        if cik is None or cik != issuer_cik(prior.provenance.get("cik")):
            continue
        previous_grade, current_grade = prior.quality.grade.value, decision.quality.grade.value
        old_coverage = prior.provenance.get("fundamental_facts_cover_latest_periodic")
        new_coverage = decision.provenance.get("fundamental_facts_cover_latest_periodic")
        old_accession = prior.provenance.get("fundamental_latest_periodic_accession")
        new_accession = decision.provenance.get("fundamental_latest_periodic_accession")
        comparison = {
            "symbol": decision.symbol, "cik": cik, "grade_before": previous_grade, "grade_after": current_grade,
            "coverage_before": old_coverage, "coverage_after": new_coverage,
            "accession_before": old_accession, "accession_after": new_accession,
        }
        if not old_accession or not new_accession:
            unknown.append(comparison)
            continue
        if old_accession != new_accession:
            filings_changed.append(comparison)
            continue
        if (previous_grade, old_coverage) != (current_grade, new_coverage):
            changes.append(comparison)
    return {
        "changed": changes,
        "filings_changed": filings_changed,
        "unknown_filing_identity": unknown,
        "newly_covered": sum(row["coverage_before"] is not True and row["coverage_after"] is True for row in changes),
        "coverage_regressions": sum(row["coverage_before"] is True and row["coverage_after"] is not True for row in changes),
    }
