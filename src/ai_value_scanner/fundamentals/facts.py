from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Iterable


def normalize_form(form: str | None) -> str:
    """Normalize SEC form tokens such as 10-Q/A to their base form."""
    token = str(form or "").strip().upper()
    if not token:
        return ""
    if "/" in token:
        token = token.split("/", 1)[0]
    if token.endswith("A") and token[:-1] in {"10-K", "10-Q", "20-F", "40-F"}:
        token = token[:-1]
    return token


@dataclass(frozen=True, slots=True)
class VisibilityCutoff:
    """Point-in-time boundary for SEC facts.

    accession_through makes same-day filing state explicit. None means
    end-of-day visibility for filed_through.
    """

    filed_through: date
    accession_through: str | None = None


@dataclass(frozen=True, slots=True)
class FactRecord:
    """A parsed SEC fact with period and filing-version provenance."""

    tag: str
    unit: str
    value: float
    period_end: date
    period_start: date | None = None
    filed: date | None = None
    accession: str | None = None
    form: str = ""
    tag_priority: int = 0

    def __post_init__(self) -> None:
        if not isfinite(float(self.value)):
            raise ValueError("fact value must be finite")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start cannot be after period_end")

    @property
    def visible_on(self) -> date:
        return self.filed or self.period_end

    @property
    def normalized_form(self) -> str:
        return normalize_form(self.form)

    @property
    def duration_days(self) -> int:
        if self.period_start is None:
            return 0
        return (self.period_end - self.period_start).days

    @property
    def revision_key(self) -> tuple[date, str, int]:
        # Later filing/accession wins; lower tag_priority wins exact ties.
        return (self.visible_on, self.accession or "", -int(self.tag_priority))


@dataclass(frozen=True, slots=True)
class PeriodValue:
    """A reconstructed period value with availability provenance."""

    value: float
    period_end: date
    period_start: date | None
    available_on: date
    accession: str | None = None
    form: str = ""
    derived: bool = False

    @property
    def availability_key(self) -> tuple[date, str]:
        return (self.available_on, self.accession or "")

    @property
    def duration_days(self) -> int:
        if self.period_start is None:
            return 0
        return (self.period_end - self.period_start).days



STANDARD_TAXONOMIES = ("us-gaap", "ifrs-full", "dei")


def merged_standard_taxonomy_facts(companyfacts: dict) -> dict:
    """Merge the standard SEC taxonomies used by scanner and replay."""
    raw_facts = companyfacts.get("facts", {})
    merged: dict = {}
    for taxonomy in STANDARD_TAXONOMIES:
        facts = raw_facts.get(taxonomy, {})
        if not isinstance(facts, dict):
            continue
        for key, value in facts.items():
            if key not in merged:
                merged[key] = value
    return merged


def _parse_sec_date(value: object) -> date | None:
    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token[:10])
    except ValueError:
        return None


def extract_fact_records(
    companyfacts: dict,
    tags: Iterable[str],
    unit: str,
    allowed_forms: Iterable[str],
) -> list[FactRecord]:
    """Parse SEC companyfacts rows without discarding filing-version metadata."""
    facts = merged_standard_taxonomy_facts(companyfacts)
    allowed = {normalize_form(form) for form in allowed_forms}
    out: list[FactRecord] = []
    for tag_priority, tag in enumerate(tags):
        tag_obj = facts.get(tag, {})
        units = tag_obj.get("units", {}) if isinstance(tag_obj, dict) else {}
        entries = units.get(unit, []) if isinstance(units, dict) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            form = normalize_form(item.get("form"))
            if form not in allowed:
                continue
            period_end = _parse_sec_date(item.get("end"))
            if period_end is None or item.get("val") is None:
                continue
            try:
                value = float(item["val"])
            except (TypeError, ValueError):
                continue
            if not isfinite(value):
                continue
            period_start = _parse_sec_date(item.get("start"))
            filed = _parse_sec_date(item.get("filed"))
            accession_raw = item.get("accn") or item.get("accession")
            accession = str(accession_raw).strip() if accession_raw else None
            out.append(
                FactRecord(
                    tag=str(tag),
                    unit=unit,
                    value=value,
                    period_end=period_end,
                    period_start=period_start,
                    filed=filed,
                    accession=accession,
                    form=form,
                    tag_priority=tag_priority,
                )
            )
    return out

def is_visible(record: FactRecord, cutoff: VisibilityCutoff | None) -> bool:
    if cutoff is None:
        return True
    if record.visible_on < cutoff.filed_through:
        return True
    if record.visible_on > cutoff.filed_through:
        return False
    if cutoff.accession_through is None:
        return True
    # An intra-day accession cutoff represents a specific filing state.
    # A same-day fact without accession provenance cannot safely be ordered,
    # so treating it as visible would permit look-ahead.
    if record.accession is None:
        return False
    return record.accession <= cutoff.accession_through


def collapse_fact_revisions(
    records: Iterable[FactRecord],
    cutoff: VisibilityCutoff | None = None,
) -> list[FactRecord]:
    """Keep the latest visible version for each logical period.

    Synonymous tags are intentionally collapsed together when they describe
    the same unit/start/end period. Tag priority only breaks an exact filing
    version tie; a later visible filing supersedes an earlier one.
    """

    best: dict[tuple[str, date | None, date], FactRecord] = {}
    for record in records:
        if not is_visible(record, cutoff):
            continue
        key = (record.unit, record.period_start, record.period_end)
        prev = best.get(key)
        if prev is None or record.revision_key > prev.revision_key:
            best[key] = record
    return sorted(
        best.values(),
        key=lambda r: (r.period_end, r.period_start or date.min, r.tag_priority),
    )


def visibility_cutoffs(records: Iterable[FactRecord]) -> list[VisibilityCutoff]:
    """Return ordered filing/accession states represented by records."""

    keys = sorted({(r.visible_on, r.accession or "") for r in records})
    return [
        VisibilityCutoff(filed_through=day, accession_through=(accession or None))
        for day, accession in keys
    ]
