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


def _norm_cik(value: Any) -> str | None:
    """Canonical CIK comparison form: digits only, no leading zeros.

    SEC payloads mix zero-padded strings ("0002115436") and bare numbers
    (2115436); comparing raw strings would false-positive a mismatch.
    Returns None for absent/non-numeric input (unknown, never equal).
    """
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if not digits:
        return None
    return digits.lstrip("0") or "0"


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
    4. Effective-facts SHAs both present and different -> UNCOMPARABLE,
       even when scoring inputs hash equally (equal scores from different
       measured facts prove nothing about economic identity).
    5. Both effective-facts and scoring-inputs SHAs are required;
       missing either -> PROVENANCE_MISSING.
    6. Equal scoring SHA -> SAME or RECONCILED based on raw SHA;
       differing scoring SHA -> UNCOMPARABLE.
    """
    if not old or not new:
        return PROVENANCE_MISSING
    old_cik = old.get("mapped_cik")
    new_cik = new.get("mapped_cik")
    if (_norm_cik(old_cik) is not None and _norm_cik(new_cik) is not None
            and _norm_cik(old_cik) != _norm_cik(new_cik)):
        return UNCOMPARABLE
    for key in ("symbol", "financial_asof"):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val is None or new_val is None:
            return PROVENANCE_MISSING
        if str(old_val) != str(new_val):
            return PROVENANCE_MISSING
    if _norm_cik(old_cik) is None or _norm_cik(new_cik) is None:
        return PROVENANCE_MISSING
    for key in ("code_version", "config_fingerprint"):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val is None or new_val is None:
            return PROVENANCE_MISSING
        if str(old_val) != str(new_val):
            return UNCOMPARABLE
    # Effective facts BEFORE scoring inputs: equal scores computed from
    # different measured facts prove nothing about economic identity.
    old_facts = old.get("effective_facts_sha")
    new_facts = new.get("effective_facts_sha")
    if (old_facts is not None and new_facts is not None
            and str(old_facts) != str(new_facts)):
        return UNCOMPARABLE
    # Require evidence in both measured layers for SAME/RECONCILED.
    if old_facts is None or new_facts is None:
        return PROVENANCE_MISSING
    old_score = old.get("scoring_inputs_sha")
    new_score = new.get("scoring_inputs_sha")
    if old_score is None or new_score is None:
        return PROVENANCE_MISSING
    if str(old_score) != str(new_score):
        return UNCOMPARABLE
    old_raw = old.get("raw_bytes_sha")
    new_raw = new.get("raw_bytes_sha")
    if old_raw is not None and new_raw is not None and str(old_raw) != str(new_raw):
        return RECONCILED
    return SAME

def decision_provenance_to_identity_record(
    decision: Mapping[str, Any] | None,
    *,
    config_fingerprint: str | None = None,
) -> dict[str, Any | None]:
    """Build a compare()-ready identity record from a real decision dict.

    Field mapping (all explicit; nothing inferred):
    - symbol <- decision.symbol
    - financial_asof <- quality.data_asof (NOT the market decision date)
    - mapped_cik <- provenance.cik
    - code_version <- code_sha + quality_policy_version + entry_policy_version
    - config_fingerprint <- provenance.config_fingerprint, else the
      explicit fallback (e.g. the run manifest's value)
    - effective_facts_sha <- provenance.fundamental_effective_sha256
    - scoring_inputs_sha <- provenance.identity_scoring_sha
    - raw_bytes_sha <- canonical composite of the SEC pre-patch facts SHA
      and the submissions SHA, None if either is missing.

    Old decisions lacking the identity keys map to records with None
    fingerprints, which compare() honestly reports as PROVENANCE_MISSING
    instead of a verdict.
    """
    decision = decision if isinstance(decision, Mapping) else {}
    provenance = decision.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    quality = decision.get("quality")
    quality = quality if isinstance(quality, Mapping) else {}
    quality_version = provenance.get("quality_policy_version")
    entry_version = provenance.get("entry_policy_version")
    code_sha = provenance.get("code_sha")
    code_version: Any = (
        f"{code_sha}|{quality_version}|{entry_version}"
        if code_sha and quality_version and entry_version else None
    )
    raw_facts_sha = provenance.get("fundamental_companyfacts_raw_sha256")
    raw_subs_sha = provenance.get("fundamental_submissions_sha256")
    raw_bytes_sha = (
        sha256_hex(canonical_json_bytes({
            "companyfacts": raw_facts_sha, "submissions": raw_subs_sha,
        }))
        if raw_facts_sha and raw_subs_sha else None
    )
    return {
        "symbol": decision.get("symbol"),
        "financial_asof": quality.get("data_asof"),
        "mapped_cik": provenance.get("cik"),
        "code_version": code_version,
        "config_fingerprint": provenance.get("config_fingerprint", config_fingerprint),
        "effective_facts_sha": provenance.get("fundamental_effective_sha256"),
        "scoring_inputs_sha": provenance.get("identity_scoring_sha"),
        "raw_bytes_sha": raw_bytes_sha,
    }


def check_entity_coherence(    *,
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
    want = _norm_cik(facts_queried_cik)
    got = _norm_cik(facts_response_cik)
    mapped = _norm_cik(mapped_cik)
    subs_cik = _norm_cik(subs.get("cik"))
    if mapped is not None and want is not None and mapped != want:
        findings.append("MAPPED_QUERY_CIK_MISMATCH")
    if mapped is not None and subs_cik is not None and mapped != subs_cik:
        findings.append("SUBMISSIONS_CIK_MISMATCH")
    if want is not None and got is None:
        findings.append("RESPONSE_CIK_MISSING")
    elif want is not None and got != want:
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
