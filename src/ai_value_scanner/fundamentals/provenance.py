"""Provenance hashing, fingerprints, and cross-run comparison states.

Hash algorithm (frozen, documented here so reviewers can reimplement it):
canonical JSON = ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=True, default=str)`` encoded UTF-8; SHA-256 over those bytes,
hex digest. Floats use Python repr (deterministic for equal inputs);
NaN serializes as the NaN token — equal inputs always give equal hashes,
which is the only property the comparisons below rely on.

Layered fingerprints (a single SHA cannot distinguish these layers):
- L0 raw bytes: ticker map / submissions / companyfacts as fetched.
- L1 effective facts: PIT-filtered, tag-processed, EdgarTools-patched
  fact structure actually used for measurement.
- L2 scoring inputs: the exact metrics mapping entering
  ``build_company_quality_v1``.

Audit comparison states (NOT production Quality grades — they live in a
disjoint namespace precisely so they can never be mistaken for one):
- SAME: identical scoring inputs (raw bytes may differ irrelevantly).
- RECONCILED: raw bytes differ but effective facts AND scoring inputs
  match deterministically — a feed re-serialization, not an economic change.
- UNCOMPARABLE: same (symbol, asof) with unexplained effective-facts
  difference — must be investigated, never silently picked.
- PROVENANCE_MISSING: either side lacks the provenance to compare.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SAME = "SAME"
UNCOMPARABLE = "UNCOMPARABLE"
PROVENANCE_MISSING = "PROVENANCE_MISSING"
RECONCILED = "RECONCILED"

AUDIT_COMPARISON_STATES = frozenset({SAME, UNCOMPARABLE, PROVENANCE_MISSING, RECONCILED})


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_facts(effective_facts: Mapping[str, Any] | None) -> str | None:
    if effective_facts is None:
        return None
    try:
        return sha256_hex(canonical_json_bytes(dict(effective_facts)))
    except (TypeError, ValueError):
        return None


def fingerprint_scoring_inputs(metrics: Mapping[str, Any] | None) -> str | None:
    if metrics is None:
        return None
    try:
        return sha256_hex(canonical_json_bytes(dict(metrics)))
    except (TypeError, ValueError):
        return None


def _dig(record: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(record, Mapping):
        return None
    node: Any = record
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def compare_identity_records(
    old: Mapping[str, Any] | None,
    new: Mapping[str, Any] | None,
) -> str:
    """Compare two per-symbol identity records from different runs.

    Precedence (first match wins):
    1. Either side missing/empty, or either side lacking scoring-inputs
       AND effective-facts fingerprints -> PROVENANCE_MISSING.
    2. Scoring-inputs fingerprints equal (both present) -> SAME when the
       raw bytes SHAs also match, else RECONCILED.
    3. Effective-facts fingerprints both present but different ->
       UNCOMPARABLE.
    4. Anything else (e.g. only one layer available on both sides and
       equal) -> SAME if all mutually present fingerprints match, else
       PROVENANCE_MISSING.
    """
    if not old or not new:
        return PROVENANCE_MISSING
    old_score = old.get("scoring_inputs_sha")
    new_score = new.get("scoring_inputs_sha")
    if old_score is None or new_score is None:
        old_facts = old.get("effective_facts_sha")
        new_facts = new.get("effective_facts_sha")
        if old_facts is None or new_facts is None:
            return PROVENANCE_MISSING
        return SAME if old_facts == new_facts else UNCOMPARABLE
    if old_score != new_score:
        return UNCOMPARABLE
    old_raw = old.get("raw_bytes_sha")
    new_raw = new.get("raw_bytes_sha")
    if old_raw is not None and new_raw is not None and old_raw != new_raw:
        return RECONCILED
    return SAME


def check_entity_coherence(
    *,
    symbol: str,
    mapped_cik: str | None,
    submissions: Mapping[str, Any] | None,
    facts_queried_cik: str | None,
    facts_response_cik: str | None,
    relevant_accessions: list[str] | None = None,
) -> dict[str, Any]:
    """Audit the ticker->CIK->facts chain without auto-failing on prefixes.

    Returns findings; callers decide severity. Hard mismatch (response CIK
    differs from queried CIK, ticker absent from a non-empty entity ticker
    list) is reported as such. Accession filer prefixes that match neither
    the entity CIK are reported as UNRESOLVED audit findings — filing-agent
    prefixes (e.g. 0001193125) make prefix-alone verdicts unsound, so they
    never fail by themselves.
    """
    sym = str(symbol or "").strip().upper()
    findings: list[str] = []
    subs = submissions if isinstance(submissions, Mapping) else {}
    tickers = subs.get("tickers")
    ticker_list = [str(t).strip().upper() for t in tickers] if isinstance(tickers, list) else None
    if facts_queried_cik is not None and facts_response_cik is not None:
        if str(facts_queried_cik).strip().lower() != str(facts_response_cik).strip().lower():
            findings.append("RESPONSE_CIK_MISMATCH")
    ticker_listed: bool | None = None
    if ticker_list is not None and ticker_list:
        ticker_listed = sym in ticker_list
        if not ticker_listed:
            findings.append("TICKER_NOT_LISTED")
    prefixes: list[str] = []
    unresolved_prefixes: list[str] = []
    for accn in relevant_accessions or []:
        stem = str(accn or "").replace("-", "")
        prefix = stem[:10] if len(stem) >= 10 else ""
        if prefix:
            prefixes.append(prefix)
    entity_cik_norm = str(mapped_cik or "").strip().lstrip("0")
    for prefix in sorted(set(prefixes)):
        if entity_cik_norm and prefix.lstrip("0") == entity_cik_norm:
            continue
        unresolved_prefixes.append(prefix)
    if unresolved_prefixes:
        findings.append("ACCESSION_FILER_UNRESOLVED")
    return {
        "symbol": sym,
        "mapped_cik": mapped_cik,
        "ticker_listed": ticker_listed,
        "accession_filer_prefixes": sorted(set(prefixes)),
        "unresolved_prefixes": unresolved_prefixes,
        "findings": findings,
    }
