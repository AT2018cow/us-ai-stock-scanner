from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .facts import (
    FactRecord,
    PeriodValue,
    VisibilityCutoff,
    collapse_fact_records_by_end,
    collapse_fact_revisions,
)

DEFAULT_ANNUAL_FORMS = frozenset({"10-K", "20-F", "40-F"})


@dataclass(frozen=True, slots=True)
class ReconstructedFlows:
    quarters: tuple[PeriodValue, ...]
    annuals: tuple[PeriodValue, ...]


def _period_from_fact(record: FactRecord) -> PeriodValue:
    return PeriodValue(
        value=float(record.value),
        period_end=record.period_end,
        period_start=record.period_start,
        available_on=record.visible_on,
        accession=record.accession,
        form=record.normalized_form,
        derived=False,
    )


def _latest_input(inputs: Iterable[PeriodValue]) -> PeriodValue:
    return max(inputs, key=lambda p: p.availability_key)


def _derived_period(
    *,
    value: float,
    period_end: date,
    period_start: date | None,
    inputs: Iterable[PeriodValue],
    form: str = "",
) -> PeriodValue:
    source = tuple(inputs)
    latest = _latest_input(source)
    return PeriodValue(
        value=float(value),
        period_end=period_end,
        period_start=period_start,
        available_on=latest.available_on,
        accession=latest.accession,
        form=form or latest.form,
        derived=True,
    )


def _prefer_period(candidate: PeriodValue, current: PeriodValue | None) -> bool:
    if current is None:
        return True
    return candidate.availability_key > current.availability_key


def reconstruct_flow_periods(
    records: Iterable[FactRecord],
    cutoff: VisibilityCutoff | None = None,
    *,
    annual_forms: frozenset[str] = DEFAULT_ANNUAL_FORMS,
) -> ReconstructedFlows:
    """Reconstruct discrete quarters and annual flows from visible fact rows.

    The algorithm is shared by current-view and historical PIT callers. The
    caller controls filing visibility through cutoff; within that visible
    state, the latest revision/accession for a logical period is used.
    """

    collapsed = collapse_fact_revisions(records, cutoff)
    quarters: dict[date, PeriodValue] = {}
    annuals: list[PeriodValue] = []
    ytd_by_end: dict[date, PeriodValue] = {}
    ytds_by_start: dict[date, list[PeriodValue]] = {}
    ytd_9m_by_start: dict[date, PeriodValue] = {}

    for record in collapsed:
        point = _period_from_fact(record)
        duration = record.duration_days
        is_quarter = (
            record.period_start is None and record.normalized_form not in annual_forms
        ) or (record.period_start is not None and 40 <= duration <= 120)
        if is_quarter:
            if _prefer_period(point, quarters.get(point.period_end)):
                quarters[point.period_end] = point
            continue
        if (
            record.period_start is not None
            and duration >= 300
            and record.normalized_form in annual_forms
        ):
            annuals.append(point)
            continue
        if record.period_start is None or not 150 <= duration <= 290:
            continue
        current_ytd = ytd_by_end.get(point.period_end)
        if current_ytd is None or point.duration_days > current_ytd.duration_days or (
            point.duration_days == current_ytd.duration_days
            and point.availability_key > current_ytd.availability_key
        ):
            ytd_by_end[point.period_end] = point
        ytds_by_start.setdefault(record.period_start, []).append(point)
        if 200 <= duration <= 290:
            current_9m = ytd_9m_by_start.get(record.period_start)
            if current_9m is None or point.availability_key > current_9m.availability_key:
                ytd_9m_by_start[record.period_start] = point

    # Fiscal-year-end values occasionally arrive as quarter-length facts. If
    # the magnitude and fiscal geometry show that the point is actually FY,
    # derive Q4 from FY - 9M and retain the FY value as an annual point.
    for q_end in sorted(quarters):
        q_point = quarters[q_end]
        ytd = next(
            (
                p
                for start, p in ytd_9m_by_start.items()
                if 80 <= (q_end - p.period_end).days <= 100
                and 300 <= (q_end - start).days <= 380
            ),
            None,
        )
        if ytd is None:
            continue
        if (
            ytd.value == 0
            or q_point.value * ytd.value <= 0
            or abs(q_point.value) < 0.85 * abs(ytd.value)
        ):
            continue
        annual_at_end = next(
            (a for a in annuals if a.period_end == q_end and a.duration_days >= 300),
            None,
        )
        if annual_at_end is not None:
            quarters[q_end] = _derived_period(
                value=annual_at_end.value - ytd.value,
                period_end=q_end,
                period_start=None,
                inputs=(annual_at_end, ytd),
                form=q_point.form,
            )
        else:
            quarters[q_end] = _derived_period(
                value=q_point.value - ytd.value,
                period_end=q_end,
                period_start=None,
                inputs=(q_point, ytd),
                form=q_point.form,
            )
            annuals.append(
                PeriodValue(
                    value=q_point.value,
                    period_end=q_end,
                    period_start=ytd.period_start,
                    available_on=q_point.available_on,
                    accession=q_point.accession,
                    form=q_point.form,
                    derived=True,
                )
            )

    # Same-end cumulative vs discrete: H1 - Q2 yields the prior quarter.
    for end, ytd in list(ytd_by_end.items()):
        q = quarters.get(end)
        if q is None or q.period_start is None or ytd.period_start is None:
            continue
        if not 60 <= ytd.duration_days - q.duration_days <= 120:
            continue
        implied_end = q.period_start - timedelta(days=1)
        if implied_end not in quarters:
            quarters[implied_end] = _derived_period(
                value=ytd.value - q.value,
                period_end=implied_end,
                period_start=None,
                inputs=(ytd, q),
            )

    # Same fiscal start: longer YTD - shorter YTD yields the intervening Q.
    for ytds in ytds_by_start.values():
        ordered = sorted(ytds, key=lambda p: p.duration_days)
        for index in range(1, len(ordered)):
            short, long = ordered[index - 1], ordered[index]
            if not 60 <= long.duration_days - short.duration_days <= 120:
                continue
            if long.period_end not in quarters:
                quarters[long.period_end] = _derived_period(
                    value=long.value - short.value,
                    period_end=long.period_end,
                    period_start=None,
                    inputs=(long, short),
                )

    # H1 - discrete Q1 yields Q2. This is required for cumulative-only cash
    # flow facts where no direct Q2 entry exists.
    for end, ytd in list(ytd_by_end.items()):
        if end in quarters or ytd.period_start is None:
            continue
        for q in list(quarters.values()):
            if q.period_start != ytd.period_start or q.period_end >= end:
                continue
            if not 60 <= ytd.duration_days - q.duration_days <= 120:
                continue
            quarters[end] = _derived_period(
                value=ytd.value - q.value,
                period_end=end,
                period_start=None,
                inputs=(ytd, q),
            )
            break

    # Fiscal-year closure: annual - 9M, or annual - the other three quarters.
    for annual in sorted(annuals, key=lambda p: p.period_end):
        if annual.period_start is None or annual.period_end in quarters:
            continue
        within = sorted(
            (p for end, p in quarters.items() if annual.period_start < end < annual.period_end),
            key=lambda p: p.period_end,
        )
        if len(within) == 3:
            quarters[annual.period_end] = _derived_period(
                value=annual.value - sum(p.value for p in within),
                period_end=annual.period_end,
                period_start=None,
                inputs=(annual, *within),
                form=annual.form,
            )
            continue
        ytd = ytd_9m_by_start.get(annual.period_start)
        if ytd is not None and ytd.period_end < annual.period_end:
            quarters[annual.period_end] = _derived_period(
                value=annual.value - ytd.value,
                period_end=annual.period_end,
                period_start=None,
                inputs=(annual, ytd),
                form=annual.form,
            )

    quarter_values = tuple(sorted(quarters.values(), key=lambda p: p.period_end))
    annual_by_end: dict[date, PeriodValue] = {}
    for point in annuals:
        current = annual_by_end.get(point.period_end)
        if _prefer_period(point, current):
            annual_by_end[point.period_end] = point
    annual_values = tuple(sorted(annual_by_end.values(), key=lambda p: p.period_end))
    return ReconstructedFlows(quarters=quarter_values, annuals=annual_values)


def rolling_ttm_points(quarters: Iterable[PeriodValue]) -> tuple[PeriodValue, ...]:
    ordered = sorted(quarters, key=lambda p: p.period_end)
    windows: list[PeriodValue] = []
    for index in range(3, len(ordered)):
        window = ordered[index - 3 : index + 1]
        span = (window[-1].period_end - window[0].period_end).days
        if not 240 <= span <= 310:
            continue
        windows.append(
            _derived_period(
                value=sum(p.value for p in window),
                period_end=window[-1].period_end,
                period_start=window[0].period_start,
                inputs=window,
            )
        )
    return tuple(windows)


def ttm_points_with_annual_fallback(flows: ReconstructedFlows) -> tuple[PeriodValue, ...]:
    points = list(rolling_ttm_points(flows.quarters))
    annuals = list(flows.annuals)
    if not points:
        return tuple(annuals)
    if annuals and annuals[-1].period_end > points[-1].period_end:
        points.append(annuals[-1])
        if len(annuals) >= 2:
            points.append(annuals[-2])
        points.sort(key=lambda p: p.period_end)
    return tuple(points)


def latest_and_year_ago_ttm(
    points: Iterable[PeriodValue],
    *,
    min_gap_days: int = 320,
    max_gap_days: int = 410,
) -> tuple[float | None, float | None]:
    ordered = sorted(points, key=lambda p: p.period_end)
    if not ordered:
        return None, None
    latest = ordered[-1]
    best: PeriodValue | None = None
    best_gap: int | None = None
    for point in ordered[:-1]:
        offset = (latest.period_end - point.period_end).days
        if not min_gap_days <= offset <= max_gap_days:
            continue
        gap = abs(offset - 365)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = point
    return latest.value, (best.value if best is not None else None)


def latest_and_year_ago_level(
    records: Iterable[FactRecord],
    cutoff: VisibilityCutoff | None = None,
    *,
    min_gap_days: int = 320,
    max_gap_days: int = 410,
) -> tuple[float | None, float | None]:
    """Return latest visible level fact and a genuine year-ago comparison.

    Unlike the legacy adapters, this does not substitute an adjacent quarter
    when no valid year-ago balance-sheet period exists.
    """

    points = [
        _period_from_fact(record)
        for record in collapse_fact_records_by_end(records, cutoff)
    ]
    if not points:
        return None, None
    latest = max(points, key=lambda p: p.period_end)
    best: PeriodValue | None = None
    best_gap: int | None = None
    for point in points:
        if point is latest:
            continue
        offset = (latest.period_end - point.period_end).days
        if not min_gap_days <= offset <= max_gap_days:
            continue
        gap = abs(offset - 365)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = point
    return latest.value, (best.value if best is not None else None)


def current_ttm_pair(
    records: Iterable[FactRecord],
    cutoff: VisibilityCutoff | None = None,
    *,
    require_rolling_window: bool = False,
) -> tuple[float | None, float | None]:
    """Return latest TTM and a genuine year-ago TTM from visible facts."""
    flows = reconstruct_flow_periods(records, cutoff)
    rolling = rolling_ttm_points(flows.quarters)
    if require_rolling_window and not rolling:
        return None, None
    points = ttm_points_with_annual_fallback(flows)
    return latest_and_year_ago_ttm(points)


def build_flow_visibility_series(
    records: Iterable[FactRecord],
) -> tuple[PeriodValue, ...]:
    """Build an end-of-filing-day PIT staircase using the canonical core.

    Facts are applied incrementally by filing date. The current logical-period
    map keeps only the newest visible revision, so each date reconstructs from
    the compact visible state rather than rescanning the full filing history.
    """
    by_date: dict[date, list[FactRecord]] = {}
    for record in records:
        if record.filed is None:
            continue
        by_date.setdefault(record.filed, []).append(record)

    current: dict[tuple[str, date | None, date], FactRecord] = {}
    out: list[PeriodValue] = []
    last_state: tuple[date, float] | None = None

    for visible_on in sorted(by_date):
        for record in by_date[visible_on]:
            key = (record.unit, record.period_start, record.period_end)
            prev = current.get(key)
            if prev is None or record.revision_key > prev.revision_key:
                current[key] = record

        flows = reconstruct_flow_periods(current.values())
        points = ttm_points_with_annual_fallback(flows)
        if not points:
            continue
        latest = max(points, key=lambda p: p.period_end)
        state = (latest.period_end, float(latest.value))
        if state == last_state:
            continue
        out.append(
            PeriodValue(
                value=float(latest.value),
                period_end=latest.period_end,
                period_start=latest.period_start,
                available_on=visible_on,
                accession=latest.accession,
                form=latest.form,
                derived=latest.derived,
            )
        )
        last_state = state
    return tuple(out)


def build_level_visibility_series(
    records: Iterable[FactRecord],
) -> tuple[PeriodValue, ...]:
    """Build an end-of-filing-day PIT staircase for level facts."""
    by_date: dict[date, list[FactRecord]] = {}
    for record in records:
        if record.filed is None:
            continue
        by_date.setdefault(record.filed, []).append(record)

    current: dict[tuple[str, date], FactRecord] = {}
    out: list[PeriodValue] = []
    last_state: tuple[date, float] | None = None

    for visible_on in sorted(by_date):
        for record in by_date[visible_on]:
            key = (record.unit, record.period_end)
            prev = current.get(key)
            if prev is None or record.revision_key > prev.revision_key:
                current[key] = record

        if not current:
            continue
        latest = max(
            current.values(),
            key=lambda record: (record.period_end, record.revision_key),
        )
        state = (latest.period_end, float(latest.value))
        if state == last_state:
            continue
        out.append(
            PeriodValue(
                value=float(latest.value),
                period_end=latest.period_end,
                period_start=latest.period_start,
                available_on=visible_on,
                accession=latest.accession,
                form=latest.normalized_form,
                derived=False,
            )
        )
        last_state = state
    return tuple(out)

