"""Ticker-to-filing-entity identity verification (research + production).

A Quality grade is only meaningful if the financial facts came from the
right issuer. The SEC ticker map can point a symbol at a financing
subsidiary (observed: XOM -> 0002115436 "ExxonMobil Holdings Corp", 34
filings, no operating facts, while the operating company 0000034088 has
1001 filings). A silent binding then scores the wrong entity — or, when
facts are thin, hides behind generic missingness with no identity warning.

``verify_operating_entity`` answers one question with no magnitude
thresholds and no ticker hardcoding: does this filing entity verifiably
represent the symbol's operating issuer?
  - entity ticker list missing entirely -> (None, "no_submissions_info"):
    no claim either way; downstream treats it like any absent flag.
  - non-empty ticker list NOT containing the symbol -> (False,
    "ticker_not_listed"): positive evidence of a wrong binding.
  - zero filings -> (None, "no_filings_to_judge"): nothing to judge.
  - no core operating facts (revenue / net income / operating cash flow)
    despite filings -> (False, "core_facts_absent"): holding-company or
    extraction shell, not ratable operating economics.
  - EMPTY ticker list with core facts -> (False, "ticker_binding_unproven"):
    facts alone do not prove the CIK belongs to this symbol (observed:
    legacy filers with empty ticker lists). Pass auditable
    ``binding_evidence`` (e.g. how the symbol->CIK link was established)
    to return True instead; without it, conservatively unverified.
  - non-empty ticker list containing the symbol, with core facts ->
    (True, "ticker_listed_with_core_facts").

Callers must treat False as identity-unverified: cap confidence below the
rated threshold and surface an explicit missing code. Never silently bind.
An explicit None (checked but unconfirmable, e.g. submissions unavailable)
is treated conservatively the same way by the Quality gate; an ABSENT flag
(legacy data predating this check) keeps the old behavior so historical
frames are never retroactively penalized.
"""

from __future__ import annotations

from collections.abc import Iterable


def verify_operating_entity(
    symbol: str,
    entity_tickers: Iterable[str] | None,
    n_filings: int | None,
    has_core_facts: bool | None,
    binding_evidence: str | None = None,
) -> tuple[bool | None, str]:
    sym = str(symbol or "").strip().upper()
    if entity_tickers is None:
        return None, "no_submissions_info"
    tickers = [str(t).strip().upper() for t in entity_tickers if str(t).strip()]
    if tickers and sym not in tickers:
        return False, "ticker_not_listed"
    if n_filings is None or n_filings <= 0:
        return None, "no_filings_to_judge"
    if has_core_facts is False:
        return False, "core_facts_absent"
    if not tickers:
        # Empty ticker list: facts alone prove nothing about the binding.
        if binding_evidence is not None and str(binding_evidence).strip():
            return True, "facts_with_binding_evidence"
        return False, "ticker_binding_unproven"
    if has_core_facts is True:
        return True, "ticker_listed_with_core_facts"
    return None, "no_submissions_info"


#: Coherence findings that force identity False no matter what the
#: ticker-list/facts-presence check said.
HARD_COHERENCE_FINDINGS = frozenset({"RESPONSE_CIK_MISMATCH", "TICKER_NOT_LISTED"})


def downgrade_on_hard_findings(
    verified: bool | None,
    detail: str | None,
    findings: list[str] | tuple[str, ...] | None,
) -> tuple[bool | None, str | None]:
    """Apply hard coherence findings to a verify() verdict (pure).

    Any hard finding forces False and appends its code to the detail
    string (deduplicated case-insensitively, so TICKER_NOT_LISTED is not
    doubled when verify() already reported it). Non-hard findings leave
    the verdict untouched — they are audit disclosures, not verdicts.
    """
    hard = sorted({str(f) for f in (findings or ())} & HARD_COHERENCE_FINDINGS)
    if not hard:
        return verified, detail
    seen = {str(detail or "").lower()}
    extra = [code for code in hard if code.lower() not in seen]
    new_detail = "+".join([d for d in [detail, *extra] if d])
    return False, new_detail or "+".join(hard)
