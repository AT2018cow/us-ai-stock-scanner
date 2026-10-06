from __future__ import annotations

import unittest
from datetime import date

from ai_value_scanner.fundamentals.facts import FactRecord, VisibilityCutoff
from ai_value_scanner.fundamentals.reconstruction import (
    latest_and_year_ago_level,
    latest_and_year_ago_ttm,
    reconstruct_flow_periods,
    rolling_ttm_points,
    ttm_points_with_annual_fallback,
)


def fact(
    value: float,
    end: str,
    *,
    start: str | None = None,
    filed: str | None = None,
    accession: str | None = None,
    form: str = "10-Q",
    tag: str = "Revenue",
    unit: str = "USD",
    priority: int = 0,
) -> FactRecord:
    return FactRecord(
        tag=tag,
        unit=unit,
        value=value,
        period_start=date.fromisoformat(start) if start else None,
        period_end=date.fromisoformat(end),
        filed=date.fromisoformat(filed) if filed else None,
        accession=accession,
        form=form,
        tag_priority=priority,
    )


class TestFlowReconstructionGoldenValues(unittest.TestCase):
    def test_standard_quarters_build_ttm(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01"),
            fact(20, "2025-06-30", start="2025-04-01", filed="2025-08-01"),
            fact(30, "2025-09-30", start="2025-07-01", filed="2025-11-01"),
            fact(40, "2025-12-31", start="2025-10-01", filed="2026-02-15"),
        ]
        flows = reconstruct_flow_periods(rows)
        self.assertEqual([p.value for p in flows.quarters], [10, 20, 30, 40])
        ttm = rolling_ttm_points(flows.quarters)
        self.assertEqual(len(ttm), 1)
        self.assertEqual(ttm[0].value, 100)
        self.assertEqual(ttm[0].period_end, date(2025, 12, 31))
        self.assertEqual(ttm[0].available_on, date(2026, 2, 15))

    def test_ytd_facts_reconstruct_discrete_quarters(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01"),
            fact(30, "2025-06-30", start="2025-01-01", filed="2025-08-01"),
            fact(60, "2025-09-30", start="2025-01-01", filed="2025-11-01"),
        ]
        flows = reconstruct_flow_periods(rows)
        self.assertEqual(
            [(p.period_end.isoformat(), p.value) for p in flows.quarters],
            [("2025-03-31", 10), ("2025-06-30", 20), ("2025-09-30", 30)],
        )
        self.assertTrue(flows.quarters[1].derived)
        self.assertTrue(flows.quarters[2].derived)

    def test_annual_closure_derives_q4(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01"),
            fact(30, "2025-06-30", start="2025-01-01", filed="2025-08-01"),
            fact(60, "2025-09-30", start="2025-01-01", filed="2025-11-01"),
            fact(100, "2025-12-31", start="2025-01-01", filed="2026-02-15", form="10-K"),
        ]
        flows = reconstruct_flow_periods(rows)
        self.assertEqual(flows.quarters[-1].period_end, date(2025, 12, 31))
        self.assertEqual(flows.quarters[-1].value, 40)
        self.assertEqual(flows.quarters[-1].available_on, date(2026, 2, 15))
        self.assertEqual(flows.annuals[-1].value, 100)

    def test_53_week_fiscal_year_remains_valid(self) -> None:
        rows = [
            fact(10, "2024-12-28", start="2024-09-29", filed="2025-02-01"),
            fact(20, "2025-03-29", start="2024-12-29", filed="2025-05-01"),
            fact(30, "2025-06-28", start="2025-03-30", filed="2025-08-01"),
            fact(40, "2025-09-27", start="2025-06-29", filed="2025-11-01"),
        ]
        ttm = rolling_ttm_points(reconstruct_flow_periods(rows).quarters)
        self.assertEqual(len(ttm), 1)
        self.assertEqual(ttm[0].value, 100)

    def test_missing_quarter_does_not_create_false_ttm(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01"),
            fact(20, "2025-06-30", start="2025-04-01"),
            fact(40, "2025-12-31", start="2025-10-01"),
            fact(50, "2026-03-31", start="2026-01-01"),
        ]
        self.assertEqual(rolling_ttm_points(reconstruct_flow_periods(rows).quarters), ())

    def test_quarter_length_annual_mistag_is_reclassified(self) -> None:
        rows = [
            fact(60, "2025-09-30", start="2025-01-01", filed="2025-11-01"),
            fact(100, "2025-12-31", start="2025-10-01", filed="2026-02-15", form="10-K"),
        ]
        flows = reconstruct_flow_periods(rows)
        self.assertEqual(flows.quarters[-1].value, 40)
        self.assertEqual(flows.annuals[-1].value, 100)
        self.assertEqual(flows.annuals[-1].period_start, date(2025, 1, 1))


class TestRevisionAndPitSemantics(unittest.TestCase):
    def test_later_amended_filing_overrides_current_view(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01", accession="0001"),
            fact(12, "2025-03-31", start="2025-01-01", filed="2025-06-01", accession="0002", form="10-Q/A"),
        ]
        self.assertEqual(reconstruct_flow_periods(rows).quarters[0].value, 12)

    def test_future_restatement_is_invisible_before_filing(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01", accession="0001"),
            fact(12, "2025-03-31", start="2025-01-01", filed="2025-06-01", accession="0002"),
        ]
        before = reconstruct_flow_periods(rows, VisibilityCutoff(date(2025, 5, 15)))
        after = reconstruct_flow_periods(rows, VisibilityCutoff(date(2025, 6, 1)))
        self.assertEqual(before.quarters[0].value, 10)
        self.assertEqual(after.quarters[0].value, 12)

    def test_same_day_accession_cutoff_selects_filing_state(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01", accession="0001"),
            fact(11, "2025-03-31", start="2025-01-01", filed="2025-05-01", accession="0002"),
        ]
        first = reconstruct_flow_periods(
            rows, VisibilityCutoff(date(2025, 5, 1), accession_through="0001")
        )
        second = reconstruct_flow_periods(
            rows, VisibilityCutoff(date(2025, 5, 1), accession_through="0002")
        )
        self.assertEqual(first.quarters[0].value, 10)
        self.assertEqual(second.quarters[0].value, 11)

    def test_tag_priority_breaks_exact_version_tie(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01", filed="2025-05-01", accession="0001", tag="Preferred", priority=0),
            fact(99, "2025-03-31", start="2025-01-01", filed="2025-05-01", accession="0001", tag="Fallback", priority=1),
        ]
        self.assertEqual(reconstruct_flow_periods(rows).quarters[0].value, 10)


class TestYearAgoSelection(unittest.TestCase):
    def test_ttm_year_ago_uses_320_to_410_day_window(self) -> None:
        rows = []
        for end, value in [
            ("2024-03-31", 10), ("2024-06-30", 20), ("2024-09-30", 30), ("2024-12-31", 40),
            ("2025-03-31", 11), ("2025-06-30", 21), ("2025-09-30", 31), ("2025-12-31", 41),
        ]:
            end_date = date.fromisoformat(end)
            starts = {3: f"{end_date.year}-01-01", 6: f"{end_date.year}-04-01", 9: f"{end_date.year}-07-01", 12: f"{end_date.year}-10-01"}
            rows.append(fact(value, end, start=starts[end_date.month]))
        points = ttm_points_with_annual_fallback(reconstruct_flow_periods(rows))
        latest, prev = latest_and_year_ago_ttm(points)
        self.assertEqual(latest, 104)
        self.assertEqual(prev, 100)

    def test_missing_legal_ttm_yoy_base_returns_none(self) -> None:
        rows = [
            fact(10, "2025-03-31", start="2025-01-01"),
            fact(20, "2025-06-30", start="2025-04-01"),
            fact(30, "2025-09-30", start="2025-07-01"),
            fact(40, "2025-12-31", start="2025-10-01"),
            fact(50, "2026-03-31", start="2026-01-01"),
        ]
        latest, prev = latest_and_year_ago_ttm(
            rolling_ttm_points(reconstruct_flow_periods(rows).quarters)
        )
        self.assertEqual(latest, 140)
        self.assertIsNone(prev)

    def test_level_year_ago_requires_real_year_ago_period(self) -> None:
        rows = [
            fact(90, "2025-09-30", filed="2025-11-01", tag="Assets"),
            fact(100, "2025-12-31", filed="2026-02-15", tag="Assets"),
        ]
        latest, prev = latest_and_year_ago_level(rows)
        self.assertEqual(latest, 100)
        self.assertIsNone(prev)


if __name__ == "__main__":
    unittest.main()
