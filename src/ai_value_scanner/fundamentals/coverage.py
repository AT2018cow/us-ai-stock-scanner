"""Exact-filing research checks for financial coverage and valuation inputs.

Research evidence stays separate from the production Quality grade. A 10-Q
bridge can recover a period missed by the discrete four-quarter window if
both YTD columns were published in the same filing and the preceding fiscal
year is available.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
import re
from typing import Iterable, Mapping

from .accounting import compute_adjusted_metrics, finite_number, safe_yoy
from .facts import FactRecord, VisibilityCutoff, is_visible

FINANCIAL_COVERAGE_VERSION = "financial_coverage_shadow_v1"
CORE = ("revenue", "net_income", "operating_cash_flow")
FLOWS = (*CORE, "capex", "ebit", "depreciation", "nonoperating_gain", "nonrecurring_addback")
SHARES_BASIS = "whole_company_common_shares_outstanding"


def positive(value) -> float | None:
    numeric = finite_number(value)
    return numeric if numeric is not None and numeric > 0 else None


def _cik(value) -> str | None:
    token = str(value or "").strip().lstrip("0")
    return token.zfill(10) if token.isascii() and token.isdigit() and len(token) <= 10 else None


def business_context(sic) -> dict:
    token = str(sic or "").strip().removesuffix(".0")
    if token.isdigit():
        code = int(token)
        if 6000 <= code < 6100 or 6200 <= code < 6300:
            return {"model": "bank_broker", "review_metrics": ["CET1", "net interest income", "charge-offs", "price/tangible book"]}
        if 6300 <= code < 6500:
            return {"model": "insurance", "review_metrics": ["combined ratio where applicable", "reserve development", "regulatory capital"]}
        if code == 6798:
            return {"model": "reit", "review_metrics": ["FFO/AFFO", "net debt/EBITDAre", "fixed-charge coverage"]}
        if 6500 <= code < 6600 or 6700 <= code < 6800:
            return {"model": "unknown", "review_metrics": ["verify issuer business and REIT status", "FFO/AFFO if REIT"]}
    return {"model": "corporate" if token.isdigit() and 0 < int(token) < 9900 else "unknown", "review_metrics": []}


def _pick(rows: Iterable[FactRecord]) -> FactRecord | None:
    rows = list(rows)
    if not rows:
        return None
    best = max(rows, key=lambda item: item.revision_key)
    tied = [item for item in rows if item.revision_key == best.revision_key]
    keys = {(item.tag, item.period_start, item.period_end, item.value) for item in tied}
    return best if len(keys) == 1 else None


def exact_filing_flow(
    records: Iterable[FactRecord], *, accession: str, form: str, report_end: date,
    cutoff: VisibilityCutoff, unit: str,
) -> tuple[float, tuple[FactRecord, ...]] | None:
    rows = [
        item for item in records
        if item.unit == unit and item.period_start and item.filed and item.accession
        and item.period_end <= item.filed and is_visible(item, cutoff)
    ]
    exact = [item for item in rows if item.accession == accession and item.form == form]
    if form == "10-K":
        current = _pick(item for item in exact if item.period_end == report_end and 350 <= item.duration_days <= 380)
        return (current.value, (current,)) if current else None
    if form != "10-Q":
        return None

    candidates = []
    for current in exact:
        if current.period_end != report_end or not 70 <= current.duration_days <= 290:
            continue
        # Match fiscal geometry and vocabulary, and prefer the longest safe
        # YTD window. Never pair a third quarter with a comparative nine months.
        annual = _pick(
            item for item in rows
            if item.form == "10-K" and item.tag == current.tag and 350 <= item.duration_days <= 380
            and item.period_end + timedelta(days=1) == current.period_start
            and item.filed < current.filed and item.accession != current.accession
        )
        if annual is None:
            continue
        prior = _pick(
            item for item in exact
            if item.tag == current.tag and item.period_start == annual.period_start
            and item.period_end < annual.period_end
            and 350 <= (current.period_end - item.period_end).days <= 380
            and abs(item.duration_days - current.duration_days) <= 7
        )
        if prior is not None:
            candidates.append((annual, current, prior))
    if not candidates:
        return None
    longest = max(item[1].duration_days for item in candidates)
    selected = [item for item in candidates if item[1].duration_days == longest]
    if len(set(selected)) != 1:
        return None
    annual, current, prior = selected[0]
    value = annual.value + current.value - prior.value
    return (value, (annual, current, prior)) if math.isfinite(value) else None


def _valid_accession(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\d{10}-\d{2}-\d{6}", value) is not None


def _fact(row: Mapping, cik: str, cutoff: VisibilityCutoff) -> FactRecord | None:
    if (
        _cik(row.get("cik")) != cik or row.get("scope") != "consolidated"
        or not row.get("source") or not row.get("tag") or not _valid_accession(row.get("accession"))
        or row.get("form") not in ("10-Q", "10-K")
    ):
        return None
    number = finite_number(row.get("value"))
    if number is None:
        return None
    filed = date.fromisoformat(row["filed"])
    end = date.fromisoformat(row["end"])
    start = date.fromisoformat(row["start"]) if row.get("start") else None
    if end > filed or start and start > end:
        return None
    result = FactRecord(row["tag"], row["unit"], number, end, start, filed, row["accession"], row["form"])
    return result if is_visible(result, cutoff) else None


def _translate_usd(
    value: float | None, currency: str, *, start: date | None, end: date,
    asof: date, rates: Iterable[Mapping],
) -> tuple[float | None, list[dict]]:
    """Use a sourced period average for flows, exact dated spot for stocks."""
    if value is None or end > asof or (start is not None and start > end):
        return None, []
    if currency == "USD":
        return value, []
    basis = "period_average" if start else "spot"
    matched = [
        {key: row.get(key) for key in ("currency", "quote_currency", "basis", "start", "end", "known_on", "usd_per_unit", "source")}
        for row in rates
        if row.get("currency") == currency and row.get("quote_currency") == "USD"
        and row.get("basis") == basis and row.get("source")
        and row.get("start") == (start.isoformat() if start else None)
        and row.get("end") == end.isoformat() and row.get("known_on")
        and end <= date.fromisoformat(row["known_on"]) <= asof
    ]
    eligible = {positive(row["usd_per_unit"]) for row in matched}
    if len(eligible) != 1 or None in eligible:
        return None, []
    amount = finite_number(value * next(iter(eligible)))
    return amount, sorted(matched, key=lambda row: json.dumps(row, sort_keys=True)) if amount is not None else []


def translate_usd(value, currency, *, start, end, asof, rates) -> float | None:
    return _translate_usd(value, currency, start=start, end=end, asof=asof, rates=rates)[0]


def filing_identity_error(evidence: Mapping, provenance: Mapping) -> str | None:
    expected = {
        "cik": _cik(provenance.get("cik")),
        "accession": provenance.get("fundamental_latest_periodic_accession"),
        "filed": provenance.get("fundamental_latest_periodic_filing_date"),
        "form": provenance.get("fundamental_latest_periodic_raw_form") or provenance.get("fundamental_latest_periodic_form"),
    }
    for field, value in expected.items():
        actual = _cik(evidence.get(field)) if field == "cik" else evidence.get(field)
        if not value or actual != value:
            return field
    for field, name in (("currency", "fundamental_reporting_currency"), ("period_end", "fundamental_latest_periodic_report_date")):
        value = provenance.get(name)
        if value and evidence.get(field) != value:
            return field
    return None


def _market_share_bases(evidence, cik, asof, shares):
    """Retain explicit PIT split reconciliations without inferring an empty list."""
    proofs = evidence.get("market_share_bases")
    if not isinstance(proofs, list) or shares is None or len(shares["basis_ids"]) != 1:
        return []
    archived = []
    for proof in proofs:
        try:
            security = proof["security_id"]
            if not isinstance(security, str) or not re.fullmatch(r"[A-Z0-9.\-]+:" + cik, security):
                continue
            basis, source = proof["share_basis_id"], proof["source"]
            if basis != shares["basis_ids"][0] or not isinstance(source, str) or not source.strip():
                continue
            start, end = (date.fromisoformat(proof[k]) for k in ("share_period_end", "price_session"))
            stamp = proof["known_at_utc"]
            observed = datetime.fromisoformat(stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp)
            if (end != asof or start.isoformat() != shares["end"] or start > end
                or observed.utcoffset() is None or not isinstance(proof["splits"], list)):
                continue
            observed = observed.astimezone(timezone.utc)
            splits = {}
            for token, multiple in proof["splits"]:
                day = date.fromisoformat(token)
                ratio = positive(multiple) if type(multiple) in (float, int) else None
                if ratio is None or not start < day <= end or day in splits:
                    raise ValueError("invalid or duplicate split")
                splits[day] = ratio
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
        archived.append({"security_id": security, "share_basis_id": basis, "source": source,
                         "share_period_end": start.isoformat(), "price_session": end.isoformat(),
                         "known_at_utc": observed.isoformat(),
                         "splits": [[day.isoformat(), splits[day]] for day in sorted(splits)]})
    return archived


def audit_filing(evidence: Mapping, *, asof: date, provenance: Mapping | None = None) -> dict:
    """Run the exact-period recovery on frozen, issuer-scoped source extracts."""
    cik = _cik(evidence.get("cik"))
    if cik is None:
        raise ValueError("evidence requires issuer CIK")
    if provenance is not None and (mismatch := filing_identity_error(evidence, provenance)):
        raise ValueError(f"financial filing identity mismatch: {mismatch}")
    accession, form = evidence["accession"], evidence["form"]
    if not _valid_accession(accession):
        raise ValueError("invalid filing accession")
    report_end, filed = (date.fromisoformat(evidence[key]) for key in ("period_end", "filed"))
    if not report_end <= filed <= asof:
        raise ValueError("filing or period lies outside the observation cutoff")
    cutoff = VisibilityCutoff(asof)
    currency = evidence["currency"]
    if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("explicit three-letter reporting currency required")
    model = business_context(evidence.get("sic") if provenance is None else provenance.get("sic"))
    facts: dict[str, list[FactRecord]] = {}
    origins: dict[FactRecord, set[str]] = {}
    if form in ("10-Q", "10-K"):
        for row in evidence["facts"]:
            fact = _fact(row, cik, cutoff)
            if fact is not None:
                facts.setdefault(row["metric"], []).append(fact)
                origins.setdefault(fact, set()).add(row["source"])
    values, sources, start_dates = {}, {}, {}
    comparisons = set()
    for metric in FLOWS:
        group = [
            item for item in facts.get(metric, ())
            if item.accession != accession or item.filed == filed
        ]
        flow = exact_filing_flow(group, accession=accession, form=form, report_end=report_end, cutoff=cutoff, unit=currency)
        if flow is None:
            continue
        value, used = flow
        if metric in CORE:
            if len(used) == 3:
                comparisons.add(used[2].period_end)
            else:
                current = used[0]
                comparisons.update(
                    fact.period_end for fact in group
                    if fact.accession == accession and fact.form == form and fact.tag == current.tag
                    and fact.unit == currency and fact.period_start and 350 <= fact.duration_days <= 380
                    and fact.period_end + timedelta(days=1) == current.period_start
                )
        values[metric] = value
        start_dates[metric] = used[0].period_start if len(used) == 1 else used[2].period_end + timedelta(days=1)
        sources[metric] = [
            {"accession": item.accession, "filed": item.filed.isoformat(), "start": item.period_start.isoformat(),
             "end": item.period_end.isoformat(), "amount": item.value, "unit": item.unit, "tag": item.tag,
             "sources": sorted(origins[item])}
            for item in used
        ]

    paired = len({start_dates[metric] for metric in CORE if metric in start_dates}) == 1
    core_complete = all(metric in values for metric in CORE) and paired
    fcf = None
    if "capex" in values and "operating_cash_flow" in values and start_dates["capex"] == start_dates["operating_cash_flow"]:
        fcf = values["operating_cash_flow"] - abs(values["capex"])
    share_rows = []
    for row in evidence["facts"]:
        if row["metric"] != "shares" or row.get("basis") != SHARES_BASIS or not row.get("share_basis_id"):
            continue
        fact = _fact(row, cik, cutoff)
        if fact and fact.unit == "shares" and fact.period_start is None and fact.value > 0:
            share_rows.append((row, fact))
    current_shares = _pick(fact for _, fact in share_rows if (
        fact.accession == accession and fact.filed == filed and fact.period_end == report_end
    ))
    prior_shares = None
    comparison_end = next(iter(comparisons)) if len(comparisons) == 1 else None
    if current_shares:
        bases = {row["share_basis_id"] for row, item in share_rows if item == current_shares}
        if len(bases) == 1 and comparison_end is not None:
            prior_shares = _pick(item for row, item in share_rows if (
                row["share_basis_id"] in bases and item.period_end == comparison_end
                and item.tag == current_shares.tag
            ))
        elif len(bases) != 1:
            current_shares = None

    def share_operand(fact):
        if fact is None:
            return None
        rows = [row for row, item in share_rows if item == fact]
        return {
            "accession": fact.accession, "form": fact.form, "filed": fact.filed.isoformat(),
            "end": fact.period_end.isoformat(), "tag": fact.tag, "unit": fact.unit, "amount": fact.value,
            "basis": SHARES_BASIS, "basis_ids": sorted({row["share_basis_id"] for row in rows}),
            "sources": sorted({row["source"] for row in rows}),
        }
    metrics = {
        "free_cash_flow": fcf,
        "fcf_per_current_share": fcf / current_shares.value if fcf is not None and current_shares else None,
        "dilution_yoy": safe_yoy(current_shares.value, prior_shares.value) if current_shares and prior_shares else None,
        "nonoperating_gain": values.get("nonoperating_gain"),
        "normalized_ebitda": None,
        "enterprise_value_to_normalized_ebitda": None,
    }
    # Both adjustment series must be evidenced. A missing gain is not assumed zero.
    required = ("ebit", "depreciation", "nonrecurring_addback", "nonoperating_gain")
    ev_operand = None
    valuation_fx, fcf_fx = [], []
    if (
        evidence.get("ebit_includes_adjustment_operands") is True
        and all(key in values for key in required)
        and len({start_dates[key] for key in required}) == 1
        and model["model"] == "corporate"
    ):
        adjustments = compute_adjusted_metrics(
            values.get("net_income"), values["ebit"], values["depreciation"], values.get("revenue"),
            None, values["nonrecurring_addback"], values["nonoperating_gain"], None, None, None,
        )
        metrics["normalized_ebitda"] = adjustments["adjusted_ebitda"]
        quote = evidence.get("valuation") or {}
        ev = positive(quote.get("enterprise_value_usd"))
        multiple, rates_used = _translate_usd(
            metrics["normalized_ebitda"], currency, start=start_dates["ebit"], end=report_end,
            asof=asof, rates=evidence.get("fx_rates", ()),
        )
        if ev and multiple and multiple > 0 and quote.get("asof") == asof.isoformat() and quote.get("source"):
            metrics["enterprise_value_to_normalized_ebitda"] = ev / multiple
            ev_operand = {"enterprise_value_usd": ev, "asof": quote["asof"], "source": quote["source"]}
            valuation_fx = rates_used
    fx_fcf = None
    if fcf is not None:
        fx_fcf, fcf_fx = _translate_usd(fcf, currency, start=start_dates["capex"], end=report_end,
                                        asof=asof, rates=evidence.get("fx_rates", ()))
    current_share_operand = share_operand(current_shares)
    market_share_bases = _market_share_bases(evidence, cik, asof, current_share_operand)
    return {
        "version": FINANCIAL_COVERAGE_VERSION, "evidence_class": "exact_filing_shadow",
        "cik": cik, "accession": accession, "form": form,
        "period_end": report_end.isoformat(), "filed": filed.isoformat(), "asof": asof.isoformat(), "currency": currency,
        "status": "recovered_candidate" if core_complete and currency == "USD" and model["model"] == "corporate" else "unrated",
        "reason": "unsupported_form" if form not in ("10-Q","10-K") else
                  "model_requires_specialist_review" if model["model"] != "corporate" else
                  "reporting_currency_requires_validation" if currency != "USD" else
                  "core_same_period_facts_missing" if not core_complete else None,
        "business_context": model, "values": values, "operand_facts": sources,
        "share_basis": SHARES_BASIS if current_shares else None,
        "shares": current_shares.value if current_shares else None,
        "prior_shares": prior_shares.value if prior_shares else None,
        "share_accessions": [fact.accession for fact in (current_shares, prior_shares) if fact],
        "comparative_period_end": comparison_end.isoformat() if comparison_end else None,
        "derived_operands": {
            "current_shares": current_share_operand, "comparative_shares": share_operand(prior_shares),
            "enterprise_value": ev_operand, "valuation_fx": valuation_fx, "fcf_fx": fcf_fx,
        },
        **({"market_share_bases": market_share_bases} if market_share_bases else {}),
        "metrics": {**metrics, "translated_fcf_usd": fx_fcf},
    }
