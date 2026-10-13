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

# Frozen value-field list for the L1 effective-facts fingerprint. These
# keys exist with identical names in both the live fundamentals result
# dict and the replay cross-section row, so L1 is comparable across runs
# of the same pipeline version. Values may be None/NaN/float — the
# canonical serializer distinguishes absent (null) from broken (NaN).
EFFECTIVE_VALUE_KEYS = (
    "revenue",
    "net_income",
    "operating_cash_flow",
    "free_cash_flow",
    "ebit",
    "cash_and_equivalents",
    "total_debt",
    "net_debt",
    "interest_expense",
    "depreciation_and_amortization",
    "current_assets",
    "current_liabilities",
    "receivables_current",
    "inventory_current",
    "shares_outstanding",
)


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


def fingerprint_effective_values(values: Mapping[str, Any] | None) -> str | None:
    """L1 fingerprint over the frozen effective-value key list.

    Only EFFECTIVE_VALUE_KEYS participate, so tag-vocabulary or column
    drift elsewhere cannot silently change the fingerprint. Missing keys
    are skipped (not defaulted): absence of a value is itself evidence
    state only insofar as present keys hash.
    """
    if values is None or not isinstance(values, Mapping):
        return None
    try:
        picked = {key: values[key] for key in EFFECTIVE_VALUE_KEYS if key in values}
    except (TypeError, ValueError):
        return None
    if not picked:
        return None
    try:
        return sha256_hex(canonical_json_bytes(picked))
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

    Required record fields for a valid comparison: ``symbol``,
    ``financial_asof``, ``mapped_cik``, ``code_version``,
    ``config_fingerprint``, ``effective_facts_sha``, ``scoring_inputs_sha``.
    Raw-bytes SHAs (``raw_bytes_sha``) are corroborating, never decisive
    alone.

    Precedence (first match wins):
    0. Either side missing/empty -> PROVENANCE_MISSING.
    1. Mapped CIKs both present and different -> UNCOMPARABLE
       (cross-entity; no score or fact equality can rehabilitate a
       different issuer — not even identical scoring inputs).
    2. Symbol/asof mismatched, or any required field (symbol,
       financial_asof, mapped_cik, code_version, config_fingerprint)
       absent on either side -> PROVENANCE_MISSING (not a valid pair).
    3. Code/config/scope versions differ -> UNCOMPARABLE (comparability
       unprovable across computation scopes without a dedicated proof).
    4. Scoring-inputs SHAs both present and equal -> SAME when raw SHAs
       also match (or either raw SHA is absent), else RECONCILED (same
       measured inputs through different raw bytes: a feed
       re-serialization, not an economic change). Different ->
       UNCOMPARABLE.
    5. Effective-facts SHAs both present (scoring SHAs absent on both
       sides): equal -> SAME, different -> UNCOMPARABLE.
    6. Anything else -> PROVENANCE_MISSING.
    """
    if not old or not new:
        return PROVENANCE_MISSING
    old_cik = old.get("mapped_cik")
    new_cik = new.get("mapped_cik")
    if (old_cik is not None and new_cik is not None
            and str(old_cik).strip().lower() != str(new_cik).strip().lower()):
        return UNCOMPARABLE
    for key in ("symbol", "financial_asof"):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val is None or new_val is None:
            return PROVENANCE_MISSING
        if str(old_val) != str(new_val):
            return PROVENANCE_MISSING
    if old_cik is None or new_cik is None:
        return PROVENANCE_MISSING
    for key in ("code_version", "config_fingerprint"):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val is None or new_val is None:
            return PROVENANCE_MISSING
        if str(old_val) != str(new_val):
            return UNCOMPARABLE
    for key in ("code_version", "config_fingerprint"):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val is None or new_val is None:
            return PROVENANCE_MISSING
        if str(old_val) != str(new_val):
            return UNCOMPARABLE
    old_score = old.get("scoring_inputs_sha")
    new_score = new.get("scoring_inputs_sha")
    old_has_score = old_score is not None
    new_has_score = new_score is not None
    if old_has_score and new_has_score:
        if str(old_score) != str(new_score):
            return UNCOMPARABLE
        old_raw = old.get("raw_bytes_sha")
        new_raw = new.get("raw_bytes_sha")
        if (old_raw is not None and new_raw is not None
                and str(old_raw) != str(new_raw)):
            return RECONCILED
        return SAME
    if old_has_score != new_has_score:
        # Asymmetric evidence layers: one side measured scoring inputs the
        # other never produced. Not a valid pair.
        return PROVENANCE_MISSING
    old_facts = old.get("effective_facts_sha")
    new_facts = new.get("effective_facts_sha")
    if old_facts is not None and new_facts is not None:
        return SAME if str(old_facts) == str(new_facts) else UNCOMPARABLE
    return PROVENANCE_MISSING


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
