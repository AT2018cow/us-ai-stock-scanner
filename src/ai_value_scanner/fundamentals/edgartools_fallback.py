from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import math
import os
import re
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


EDGARTOOLS_FALLBACK_VERSION = "usd_10q_v1"
_SUPPORTED_FORM = "10-Q"
_STANDARD_TAXONOMY = "us-gaap"

_STATUS_USED = "used"
_STATUS_NOT_NEEDED = "not_needed"
_STATUS_INELIGIBLE_FORM = "ineligible_form"
_STATUS_MISSING_ACCESSION = "missing_accession"
_STATUS_IDENTITY_MISSING = "identity_missing"
_STATUS_FETCH_FAILED = "fetch_failed"
_STATUS_FILING_MISMATCH = "filing_mismatch"
_STATUS_XBRL_UNAVAILABLE = "xbrl_unavailable"
_STATUS_FACTS_UNAVAILABLE = "facts_unavailable"
_STATUS_CORE_FACTS_INCOMPLETE = "core_facts_incomplete"
_STATUS_NON_USD_CORE = "non_usd_core"
_STATUS_NO_USABLE_FACTS = "no_usable_facts"


@dataclass(frozen=True, slots=True)
class EdgarToolsFallbackResult:
    """Result of the deliberately narrow live 10-Q fallback.

    The patch uses SEC Company Facts-compatible JSON shape so the repository's
    existing FactRecord / PIT reconstruction / accounting path remains the sole
    source of investment semantics.
    """

    status: str
    patch: dict[str, Any] | None = None
    accession: str | None = None
    filing_date: str | None = None
    form: str | None = None
    reporting_currency: str | None = None
    accepted_fact_count: int = 0
    core_groups_found: tuple[str, ...] = ()
    error: str | None = None

    @property
    def used(self) -> bool:
        return self.status == _STATUS_USED and self.patch is not None


def _clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _date_token(value: object) -> str | None:
    token = _clean(value)
    if not token:
        return None
    token = token[:10]
    try:
        return date.fromisoformat(token).isoformat()
    except ValueError:
        return None


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(resolved):
        return None
    return resolved


def _split_concept(value: object) -> tuple[str | None, str | None]:
    token = _clean(value)
    if not token:
        return None, None
    if ":" in token:
        taxonomy, tag = token.split(":", 1)
        return taxonomy.strip().lower(), tag.strip()
    if "_" in token:
        taxonomy, tag = token.split("_", 1)
        return taxonomy.strip().lower(), tag.strip()
    return None, token


def _has_dimensions(row: Mapping[str, object]) -> bool:
    """Return True for segment/dimensional facts."""

    for key in ("dimensions", "dimension"):
        if key not in row:
            continue
        value = row.get(key)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, Mapping):
            if value:
                return True
            continue
        if isinstance(value, (list, tuple, set)):
            if value:
                return True
            continue
        token = str(value).strip()
        if token and token not in {"{}", "[]", "None", "nan", "<NA>"}:
            return True
    return False


def _normalize_currency_unit(value: object) -> str | None:
    token = _clean(value)
    if not token:
        return None
    upper = token.upper()

    if any(
        marker in upper
        for marker in (
            "PERSHARE",
            "PER_SHARE",
            "/SHARE",
            "DIVIDE_",
            "PERBBL",
            "PER_BBL",
            "PERLB",
            "PER_LB",
            "PERMMBTU",
            "PER_MMBTU",
            "PERMWH",
            "PER_MWH",
        )
    ):
        return None

    if re.fullmatch(r"[A-Z]{3}", upper):
        return upper
    match = re.fullmatch(r"U_([A-Z]{3})", upper)
    if match:
        return match.group(1)
    match = re.match(r"UNIT_STANDARD_([A-Z]{3})(?:_|$)", upper)
    if match:
        return match.group(1)
    return None


def _normalize_scanner_unit(value: object) -> str | None:
    token = _clean(value)
    if not token:
        return None
    upper = token.upper()

    if upper in {"SHARES", "U_SHARES"} or upper.startswith("UNIT_STANDARD_SHARES_"):
        return "shares"

    compact = re.sub(r"[^A-Z0-9]", "", upper)
    if (
        compact in {"USDSHARES", "USDPERSHARE"}
        or upper.startswith("UNIT_DIVIDE_USD_SHARES_")
    ):
        return "USD/shares"

    currency = _normalize_currency_unit(token)
    if currency == "USD":
        return "USD"
    return None


def _facts_dataframe(xbrl: object) -> pd.DataFrame:
    facts = getattr(xbrl, "facts", None)
    converter = getattr(facts, "to_dataframe", None)
    if not callable(converter):
        return pd.DataFrame()
    frame = converter()
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    return pd.DataFrame(frame)


def _row_value(row: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in row:
            value = row.get(key)
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass
            return value
    return None


def _sec_like_entry(
    row: Mapping[str, object],
    *,
    accession: str,
    filed: str,
    form: str,
) -> tuple[str, str, dict[str, Any]] | None:
    taxonomy, tag = _split_concept(row.get("concept"))
    if taxonomy != _STANDARD_TAXONOMY or not tag:
        return None
    if _has_dimensions(row):
        return None

    unit = _normalize_scanner_unit(row.get("unit"))
    if unit is None:
        return None

    value = _finite_float(_row_value(row, "numeric_value", "value", "val"))
    if value is None:
        return None

    period_end = _date_token(
        _row_value(
            row,
            "period_end",
            "period_instant",
            "end",
            "instant",
        )
    )
    if period_end is None:
        return None
    period_start = _date_token(_row_value(row, "period_start", "start"))

    entry: dict[str, Any] = {
        "val": value,
        "end": period_end,
        "filed": filed,
        "accn": accession,
        "form": form,
    }
    if period_start is not None:
        entry["start"] = period_start
    return tag, unit, entry


def _core_currency_sets(
    frame: pd.DataFrame,
    *,
    core_tag_groups: Mapping[str, Iterable[str]],
) -> dict[str, set[str]]:
    tag_to_groups: dict[str, set[str]] = {}
    for group, tags in core_tag_groups.items():
        for tag in tags:
            tag_to_groups.setdefault(str(tag), set()).add(str(group))

    out = {str(group): set() for group in core_tag_groups}
    for raw in frame.to_dict(orient="records"):
        taxonomy, tag = _split_concept(raw.get("concept"))
        if taxonomy != _STANDARD_TAXONOMY or not tag:
            continue
        groups = tag_to_groups.get(tag)
        if not groups or _has_dimensions(raw):
            continue
        if _finite_float(_row_value(raw, "numeric_value", "value", "val")) is None:
            continue
        if _date_token(
            _row_value(raw, "period_end", "period_instant", "end", "instant")
        ) is None:
            continue
        currency = _normalize_currency_unit(raw.get("unit"))
        if currency is None:
            continue
        for group in groups:
            out[group].add(currency)
    return out


def build_usd_10q_companyfacts_patch(
    xbrl: object,
    *,
    accession: str,
    filed: str,
    form: str,
    allowed_tags: Iterable[str],
    core_tag_groups: Mapping[str, Iterable[str]],
) -> EdgarToolsFallbackResult:
    """Convert one exact 10-Q XBRL filing into a safe Company Facts patch.

    Only consolidated standard us-gaap facts in units understood by the
    existing scanner are admitted. All configured core monetary groups must
    contain USD facts before the patch is considered usable.
    """

    if str(form).strip().upper() != _SUPPORTED_FORM:
        return EdgarToolsFallbackResult(
            status=_STATUS_INELIGIBLE_FORM,
            accession=accession or None,
            filing_date=filed or None,
            form=form or None,
        )
    if not str(accession).strip():
        return EdgarToolsFallbackResult(
            status=_STATUS_MISSING_ACCESSION,
            filing_date=filed or None,
            form=form or None,
        )

    try:
        frame = _facts_dataframe(xbrl)
    except Exception as exc:
        return EdgarToolsFallbackResult(
            status=_STATUS_FACTS_UNAVAILABLE,
            accession=accession,
            filing_date=filed,
            form=form,
            error=f"{type(exc).__name__}: {exc}",
        )
    if frame.empty:
        return EdgarToolsFallbackResult(
            status=_STATUS_FACTS_UNAVAILABLE,
            accession=accession,
            filing_date=filed,
            form=form,
        )

    currency_sets = _core_currency_sets(frame, core_tag_groups=core_tag_groups)
    groups_with_usd = tuple(
        str(group)
        for group in core_tag_groups
        if "USD" in currency_sets.get(str(group), set())
    )
    observed = sorted(
        {
            currency
            for currencies in currency_sets.values()
            for currency in currencies
        }
    )
    if len(groups_with_usd) != len(core_tag_groups):
        if observed and "USD" not in observed:
            return EdgarToolsFallbackResult(
                status=_STATUS_NON_USD_CORE,
                accession=accession,
                filing_date=filed,
                form=form,
                reporting_currency=",".join(observed),
                core_groups_found=groups_with_usd,
            )
        return EdgarToolsFallbackResult(
            status=_STATUS_CORE_FACTS_INCOMPLETE,
            accession=accession,
            filing_date=filed,
            form=form,
            reporting_currency=",".join(observed) if observed else None,
            core_groups_found=groups_with_usd,
        )

    allowed = {str(tag) for tag in allowed_tags}
    facts: dict[str, dict[str, Any]] = {}
    seen: set[tuple[Any, ...]] = set()
    accepted = 0
    for raw in frame.to_dict(orient="records"):
        resolved = _sec_like_entry(
            raw,
            accession=accession,
            filed=filed,
            form=form,
        )
        if resolved is None:
            continue
        tag, unit, entry = resolved
        if tag not in allowed:
            continue
        identity = (
            tag,
            unit,
            entry.get("start"),
            entry.get("end"),
            entry.get("val"),
            accession,
        )
        if identity in seen:
            continue
        seen.add(identity)
        tag_obj = facts.setdefault(
            tag,
            {
                "label": tag,
                "description": "EdgarTools exact-filing fallback",
                "units": {},
            },
        )
        tag_obj["units"].setdefault(unit, []).append(entry)
        accepted += 1

    if accepted == 0:
        return EdgarToolsFallbackResult(
            status=_STATUS_NO_USABLE_FACTS,
            accession=accession,
            filing_date=filed,
            form=form,
            reporting_currency="USD",
            core_groups_found=groups_with_usd,
        )

    return EdgarToolsFallbackResult(
        status=_STATUS_USED,
        patch={"facts": {_STANDARD_TAXONOMY: facts}},
        accession=accession,
        filing_date=filed,
        form=form,
        reporting_currency="USD",
        accepted_fact_count=accepted,
        core_groups_found=groups_with_usd,
    )


@lru_cache(maxsize=1)
def _edgartools_api() -> tuple[Callable[[str], object], str]:
    try:
        from edgar import get_by_accession_number, set_identity
    except ImportError as exc:
        raise RuntimeError("edgartools_not_installed") from exc

    identity = (
        os.getenv("EDGAR_IDENTITY")
        or os.getenv("SEC_USER_AGENT")
        or ""
    ).strip()
    if not identity:
        raise RuntimeError("sec_identity_missing")
    set_identity(identity)
    source = (
        "EDGAR_IDENTITY"
        if os.getenv("EDGAR_IDENTITY")
        else "SEC_USER_AGENT"
    )
    return get_by_accession_number, source


def fetch_usd_10q_companyfacts_patch(
    *,
    periodic_filing: Mapping[str, object] | None,
    allowed_tags: Iterable[str],
    core_tag_groups: Mapping[str, Iterable[str]],
    get_filing: Callable[[str], object] | None = None,
) -> EdgarToolsFallbackResult:
    """Fetch and convert the exact latest ordinary USD 10-Q.

    Any operational or semantic failure is contained in the return status so
    the caller can preserve the existing fail-closed UNRATED behavior.
    """

    if periodic_filing is None:
        return EdgarToolsFallbackResult(status=_STATUS_NOT_NEEDED)

    form = _clean(periodic_filing.get("form")).upper()
    accession = _clean(periodic_filing.get("accession"))
    filed = _date_token(periodic_filing.get("filed")) or ""
    if form != _SUPPORTED_FORM:
        return EdgarToolsFallbackResult(
            status=_STATUS_INELIGIBLE_FORM,
            accession=accession or None,
            filing_date=filed or None,
            form=form or None,
        )
    if not accession:
        return EdgarToolsFallbackResult(
            status=_STATUS_MISSING_ACCESSION,
            filing_date=filed or None,
            form=form,
        )

    resolver = get_filing
    if resolver is None:
        try:
            resolver, _identity_source = _edgartools_api()
        except RuntimeError as exc:
            status = (
                _STATUS_IDENTITY_MISSING
                if "identity" in str(exc)
                else _STATUS_FETCH_FAILED
            )
            return EdgarToolsFallbackResult(
                status=status,
                accession=accession,
                filing_date=filed or None,
                form=form,
                error=str(exc),
            )

    try:
        filing = resolver(accession)
    except Exception as exc:
        return EdgarToolsFallbackResult(
            status=_STATUS_FETCH_FAILED,
            accession=accession,
            filing_date=filed or None,
            form=form,
            error=f"{type(exc).__name__}: {exc}",
        )
    if filing is None:
        return EdgarToolsFallbackResult(
            status=_STATUS_FETCH_FAILED,
            accession=accession,
            filing_date=filed or None,
            form=form,
            error="filing_not_found",
        )

    raw_form = _clean(getattr(filing, "form", None)).upper()
    if raw_form and raw_form != _SUPPORTED_FORM:
        return EdgarToolsFallbackResult(
            status=_STATUS_FILING_MISMATCH,
            accession=accession,
            filing_date=filed or None,
            form=raw_form,
            error=f"expected 10-Q, got {raw_form}",
        )

    try:
        xbrl = filing.xbrl()
    except Exception as exc:
        return EdgarToolsFallbackResult(
            status=_STATUS_XBRL_UNAVAILABLE,
            accession=accession,
            filing_date=filed or None,
            form=form,
            error=f"{type(exc).__name__}: {exc}",
        )
    if xbrl is None:
        return EdgarToolsFallbackResult(
            status=_STATUS_XBRL_UNAVAILABLE,
            accession=accession,
            filing_date=filed or None,
            form=form,
        )

    return build_usd_10q_companyfacts_patch(
        xbrl,
        accession=accession,
        filed=filed,
        form=form,
        allowed_tags=allowed_tags,
        core_tag_groups=core_tag_groups,
    )


def merge_companyfacts_patch(
    companyfacts: dict[str, Any],
    patch: Mapping[str, Any] | None,
) -> int:
    """Merge a small exact-filing patch into the in-memory Company Facts dict."""

    if not patch:
        return 0
    raw_patch = patch.get("facts", {}) if isinstance(patch, Mapping) else {}
    patch_taxonomy = raw_patch.get(_STANDARD_TAXONOMY, {})
    if not isinstance(patch_taxonomy, Mapping):
        return 0

    root = companyfacts.setdefault("facts", {})
    taxonomy = root.setdefault(_STANDARD_TAXONOMY, {})
    appended = 0
    for tag, incoming_obj in patch_taxonomy.items():
        if not isinstance(incoming_obj, Mapping):
            continue
        target_obj = taxonomy.setdefault(
            tag,
            {
                "label": incoming_obj.get("label") or tag,
                "description": incoming_obj.get("description"),
                "units": {},
            },
        )
        target_units = target_obj.setdefault("units", {})
        incoming_units = incoming_obj.get("units", {})
        if not isinstance(incoming_units, Mapping):
            continue
        for unit, incoming_entries in incoming_units.items():
            if not isinstance(incoming_entries, list):
                continue
            target_entries = target_units.setdefault(unit, [])
            existing = {
                (
                    str(item.get("accn") or ""),
                    str(item.get("start") or ""),
                    str(item.get("end") or ""),
                    item.get("val"),
                    str(item.get("form") or ""),
                    str(item.get("filed") or ""),
                )
                for item in target_entries
                if isinstance(item, Mapping)
            }
            for item in incoming_entries:
                if not isinstance(item, Mapping):
                    continue
                identity = (
                    str(item.get("accn") or ""),
                    str(item.get("start") or ""),
                    str(item.get("end") or ""),
                    item.get("val"),
                    str(item.get("form") or ""),
                    str(item.get("filed") or ""),
                )
                if identity in existing:
                    continue
                target_entries.append(dict(item))
                existing.add(identity)
                appended += 1
    return appended


def remove_companyfacts_patch(
    companyfacts: dict[str, Any],
    patch: Mapping[str, Any] | None,
) -> int:
    """Remove only exact rows previously injected by merge_companyfacts_patch."""

    if not patch:
        return 0
    raw_patch = patch.get("facts", {}) if isinstance(patch, Mapping) else {}
    patch_taxonomy = raw_patch.get(_STANDARD_TAXONOMY, {})
    if not isinstance(patch_taxonomy, Mapping):
        return 0
    taxonomy = companyfacts.get("facts", {}).get(_STANDARD_TAXONOMY, {})
    if not isinstance(taxonomy, Mapping):
        return 0

    removed = 0
    for tag, incoming_obj in patch_taxonomy.items():
        target_obj = taxonomy.get(tag)
        if not isinstance(target_obj, dict) or not isinstance(incoming_obj, Mapping):
            continue
        target_units = target_obj.get("units", {})
        incoming_units = incoming_obj.get("units", {})
        if not isinstance(target_units, dict) or not isinstance(incoming_units, Mapping):
            continue
        for unit, incoming_entries in incoming_units.items():
            target_entries = target_units.get(unit)
            if not isinstance(target_entries, list) or not isinstance(incoming_entries, list):
                continue
            identities = {
                (
                    str(item.get("accn") or ""),
                    str(item.get("start") or ""),
                    str(item.get("end") or ""),
                    item.get("val"),
                    str(item.get("form") or ""),
                    str(item.get("filed") or ""),
                )
                for item in incoming_entries
                if isinstance(item, Mapping)
            }
            kept = []
            for item in target_entries:
                if not isinstance(item, Mapping):
                    kept.append(item)
                    continue
                identity = (
                    str(item.get("accn") or ""),
                    str(item.get("start") or ""),
                    str(item.get("end") or ""),
                    item.get("val"),
                    str(item.get("form") or ""),
                    str(item.get("filed") or ""),
                )
                if identity in identities:
                    removed += 1
                    continue
                kept.append(item)
            target_units[unit] = kept
    return removed
