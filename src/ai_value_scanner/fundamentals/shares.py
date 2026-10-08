from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

from .facts import (
    FactRecord,
    VisibilityCutoff,
    collapse_fact_records_by_end,
)


@dataclass(frozen=True, slots=True)
class ShareCountIntegrity:
    """Usable share count plus provenance/diagnostics for market-cap features."""

    value: float | None
    period_end: date | None
    stale: bool
    scale_factor: float
    latest_metric_end: date | None


def latest_visible_fact_by_period_end(
    records: Iterable[FactRecord],
    cutoff: VisibilityCutoff | None = None,
) -> FactRecord | None:
    """Return the latest visible report period after revision collapsing."""
    collapsed = collapse_fact_records_by_end(records, cutoff)
    if not collapsed:
        return None
    return max(collapsed, key=lambda record: (record.period_end, record.revision_key))


def _record_by_period_end(
    records: Iterable[FactRecord],
    period_end: date,
    cutoff: VisibilityCutoff | None,
) -> FactRecord | None:
    for record in collapse_fact_records_by_end(records, cutoff):
        if record.period_end == period_end:
            return record
    return None


def _latest_metric_period_end(
    metric_record_groups: Sequence[Iterable[FactRecord]],
    cutoff: VisibilityCutoff | None,
) -> date | None:
    """Use the first metric group with a visible fact, matching scanner priority."""
    for records in metric_record_groups:
        latest = latest_visible_fact_by_period_end(records, cutoff)
        if latest is not None:
            return latest.period_end
    return None


def assess_share_count_integrity(
    *,
    share_records: Iterable[FactRecord],
    eps_records: Iterable[FactRecord],
    net_income_records: Iterable[FactRecord],
    metric_record_groups: Sequence[Iterable[FactRecord]],
    cutoff: VisibilityCutoff | None = None,
    stale_after_days: int = 400,
) -> ShareCountIntegrity:
    """Reconcile reported-share units and reject materially stale share counts.

    Unit reconciliation follows the established scanner contract. When EPS and
    net income for the same share-count report period imply roughly 1,000x or
    1,000,000x the reported count, the current count is scaled accordingly.

    Freshness compares the share-count report period with the first available
    latest-metric group (normally revenue, then net income). A lag greater than
    stale_after_days makes the share count unusable for market-cap-derived
    features while retaining its period and stale diagnostic.

    This intentionally reconciles the current share count only. Existing
    year-ago share-count semantics are preserved by callers for compatibility.
    """
    shares = latest_visible_fact_by_period_end(share_records, cutoff)
    if shares is None:
        return ShareCountIntegrity(
            value=None,
            period_end=None,
            stale=False,
            scale_factor=1.0,
            latest_metric_end=_latest_metric_period_end(metric_record_groups, cutoff),
        )

    value = float(shares.value)
    period_end = shares.period_end
    scale_factor = 1.0

    if value > 0:
        eps = _record_by_period_end(eps_records, period_end, cutoff)
        net_income = _record_by_period_end(net_income_records, period_end, cutoff)
        if (
            eps is not None
            and net_income is not None
            and float(eps.value) != 0.0
        ):
            implied = abs(float(net_income.value) / float(eps.value))
            if implied > 0:
                ratio = implied / value
                for factor, lo, hi in (
                    (1_000_000.0, 500_000.0, 2_000_000.0),
                    (1_000.0, 500.0, 2_000.0),
                ):
                    if lo <= ratio <= hi:
                        scale_factor = factor
                        value *= factor
                        break

    latest_metric_end = _latest_metric_period_end(metric_record_groups, cutoff)
    stale = False
    if latest_metric_end is not None:
        stale = (latest_metric_end - period_end).days > int(stale_after_days)

    return ShareCountIntegrity(
        value=None if stale else value,
        period_end=period_end,
        stale=stale,
        scale_factor=scale_factor,
        latest_metric_end=latest_metric_end,
    )
