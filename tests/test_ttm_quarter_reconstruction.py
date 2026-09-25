from __future__ import annotations

import unittest

from ai_value_scanner.backtest import build_flow_ttm_or_annual_series
from ai_value_scanner.scanner import pick_latest_and_prev_ttm


def _acn_style_facts(with_tagged_q4: bool = True) -> dict:
    """Fiscal year Sep-Aug; 10-Q filings carry cumulative YTD columns that share
    the `end` of single quarters, and the 10-K shares the Q4 `end` with the
    annual column. Quarterly revenue: FY24 = 90/95/100/105, FY25 =
    100/110/120/130, FY26 Q1-Q3 = 140/150/160."""
    entries: list[dict] = [
        # FY24 10-K (filed 2024-10-11): annual only (no tagged Q4)
        {"start": "2023-09-01", "end": "2024-08-31", "val": 390, "form": "10-K", "filed": "2024-10-11"},
        # FY25 Q1 10-Q (filed 2024-12-18)
        {"start": "2024-09-01", "end": "2024-11-30", "val": 100, "form": "10-Q", "filed": "2024-12-18"},
        # FY25 Q2 10-Q (filed 2025-03-19): Q2 quarter + 6M YTD
        {"start": "2024-12-01", "end": "2025-02-28", "val": 110, "form": "10-Q", "filed": "2025-03-19"},
        {"start": "2024-09-01", "end": "2025-02-28", "val": 210, "form": "10-Q", "filed": "2025-03-19"},
        # FY25 10-K (filed 2025-10-10): annual column + tagged Q4
        {"start": "2024-09-01", "end": "2025-08-31", "val": 460, "form": "10-K", "filed": "2025-10-10"},
        # FY25 Q3 10-Q (filed 2025-06-17): Q3 quarter, 9M YTD, prior-year 9M comparative
        {"start": "2025-03-01", "end": "2025-05-31", "val": 120, "form": "10-Q", "filed": "2025-06-17"},
        {"start": "2024-09-01", "end": "2025-05-31", "val": 330, "form": "10-Q", "filed": "2025-06-17"},
        {"start": "2023-09-01", "end": "2024-05-31", "val": 285, "form": "10-Q", "filed": "2025-06-17"},
        # FY26 Q1 10-Q (filed 2025-12-18)
        {"start": "2025-09-01", "end": "2025-11-30", "val": 140, "form": "10-Q", "filed": "2025-12-18"},
        # FY26 Q2 10-Q (filed 2026-03-19): Q2 quarter + 6M YTD
        {"start": "2025-12-01", "end": "2026-02-28", "val": 150, "form": "10-Q", "filed": "2026-03-19"},
        {"start": "2025-09-01", "end": "2026-02-28", "val": 290, "form": "10-Q", "filed": "2026-03-19"},
        # FY26 Q3 10-Q (filed 2026-06-18): Q3 quarter, 9M YTD, prior-year 9M comparative
        {"start": "2026-03-01", "end": "2026-05-31", "val": 160, "form": "10-Q", "filed": "2026-06-18"},
        {"start": "2025-09-01", "end": "2026-05-31", "val": 450, "form": "10-Q", "filed": "2026-06-18"},
        {"start": "2024-09-01", "end": "2025-05-31", "val": 330, "form": "10-Q", "filed": "2026-06-18"},
    ]
    if with_tagged_q4:
        entries.insert(
            1,
            {"start": "2025-06-01", "end": "2025-08-31", "val": 130, "form": "10-K", "filed": "2025-10-10"},
        )
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}


class TestScannerTtmReconstruction(unittest.TestCase):
    def test_ttm_excludes_ytd_and_annual_overlap(self) -> None:
        facts = _acn_style_facts()
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # TTM ending 2026-05-31 = Q4FY25 + Q1FY26 + Q2FY26 + Q3FY26
        self.assertEqual(latest, 130.0 + 140.0 + 150.0 + 160.0)
        # Prev = the YoY base: TTM ending 2025-05-31 (Q4FY24..Q3FY25),
        # not the immediately preceding quarter window (540).
        self.assertEqual(prev, 105.0 + 100.0 + 110.0 + 120.0)

    def test_ttm_derives_q4_when_10k_has_no_quarter_column(self) -> None:
        facts = _acn_style_facts(with_tagged_q4=False)
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # Q4s derived: FY25 = 460 - 330 (9M comparative); FY24 = 390 - 285
        self.assertEqual(latest, 580.0)
        self.assertEqual(prev, 435.0)

    def test_buggy_end_only_sum_would_have_returned_garbage(self) -> None:
        # Documents the failure mode: the raw periods at the four latest end
        # dates (9M YTD 450 + 6M YTD 290 + Q1 140 + annual 460) would sum to a
        # nonsense 1340 under end-date-only collapsing.
        facts = _acn_style_facts()
        latest, _ = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        self.assertNotEqual(latest, 450.0 + 290.0 + 140.0 + 460.0)

    def test_pure_annual_filer_returns_none_for_annual_fallback(self) -> None:
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"start": "2024-01-01", "end": "2024-12-31", "val": 500, "form": "10-K", "filed": "2025-02-10"},
                                {"start": "2023-01-01", "end": "2023-12-31", "val": 450, "form": "10-K", "filed": "2024-02-10"},
                            ]
                        }
                    }
                }
            }
        }
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        self.assertIsNone(latest)
        self.assertIsNone(prev)

    def test_missing_middle_quarter_window_is_rejected(self) -> None:
        entries = [
            {"start": "2024-01-01", "end": "2024-03-31", "val": 10, "form": "10-Q", "filed": "2024-05-01"},
            {"start": "2024-04-01", "end": "2024-06-30", "val": 10, "form": "10-Q", "filed": "2024-08-01"},
            # Q3 missing; Q4 reported directly in the 10-K
            {"start": "2024-10-01", "end": "2024-12-31", "val": 10, "form": "10-K", "filed": "2025-02-15"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 10, "form": "10-Q", "filed": "2025-05-01"},
            {"start": "2025-04-01", "end": "2025-06-30", "val": 10, "form": "10-Q", "filed": "2025-08-01"},
            {"start": "2025-07-01", "end": "2025-09-30", "val": 10, "form": "10-Q", "filed": "2025-11-01"},
        ]
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # Only the contiguous recent window [2024-12-31..2025-09-30] is valid.
        self.assertEqual(latest, 40.0)
        self.assertIsNone(prev)

    def test_calendar_year_quarters_without_tagged_q4(self) -> None:
        entries = [
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1000, "form": "10-K", "filed": "2025-02-10"},
            {"start": "2024-01-01", "end": "2024-03-31", "val": 200, "form": "10-Q", "filed": "2024-05-01"},
            {"start": "2024-04-01", "end": "2024-06-30", "val": 250, "form": "10-Q", "filed": "2024-08-01"},
            {"start": "2024-01-01", "end": "2024-06-30", "val": 450, "form": "10-Q", "filed": "2024-08-01"},
            {"start": "2024-07-01", "end": "2024-09-30", "val": 260, "form": "10-Q", "filed": "2024-11-01"},
            {"start": "2024-01-01", "end": "2024-09-30", "val": 710, "form": "10-Q", "filed": "2024-11-01"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 300, "form": "10-Q", "filed": "2025-05-01"},
            {"start": "2025-04-01", "end": "2025-06-30", "val": 320, "form": "10-Q", "filed": "2025-08-01"},
            {"start": "2025-07-01", "end": "2025-09-30", "val": 340, "form": "10-Q", "filed": "2025-11-01"},
        ]
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # Q4 2024 derived: 1000 - 710 = 290; TTM = 290+300+320+340 = 1250
        self.assertEqual(latest, 1250.0)
        # No window ends ~one year before 2025-09-30 (no 2023 data) -> None
        self.assertIsNone(prev)


class TestBacktestFlowSeriesPit(unittest.TestCase):
    def _points(self, with_tagged_q4: bool = True) -> list[dict]:
        import pandas as pd

        raw = _acn_style_facts(with_tagged_q4)["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        points = []
        for e in raw:
            points.append(
                {
                    "end": pd.Timestamp(e["end"], tz="UTC").normalize(),
                    "start": pd.Timestamp(e["start"], tz="UTC").normalize(),
                    "visible": pd.Timestamp(e["filed"], tz="UTC").normalize(),
                    "value": float(e["val"]),
                    "form": e["form"],
                }
            )
        return points

    def test_series_excludes_ytd_overlap_and_is_pit_keyed(self) -> None:
        series = build_flow_ttm_or_annual_series(self._points())
        # PIT staircase: each window becomes available only once its last
        # input filing is visible; no window may be dropped to key collisions.
        staircase = [(d.strftime("%Y-%m-%d"), v) for d, v in series]
        self.assertEqual(
            staircase,
            [
                ("2025-06-17", 435.0),
                ("2025-10-10", 460.0),
                ("2025-12-18", 500.0),
                ("2026-03-19", 540.0),
                ("2026-06-18", 580.0),
            ],
        )

    def test_series_annual_supersedes_stale_window_pit(self) -> None:
        import pandas as pd

        points = [
            # four quarters ending 2025-06-30 (window visible 2025-08-01)
            {"end": pd.Timestamp("2024-09-30", tz="UTC"), "start": pd.Timestamp("2024-07-01", tz="UTC"),
             "visible": pd.Timestamp("2024-11-01", tz="UTC"), "value": 90.0, "form": "10-Q"},
            {"end": pd.Timestamp("2024-12-31", tz="UTC"), "start": pd.Timestamp("2024-10-01", tz="UTC"),
             "visible": pd.Timestamp("2025-02-01", tz="UTC"), "value": 95.0, "form": "10-Q"},
            {"end": pd.Timestamp("2025-03-31", tz="UTC"), "start": pd.Timestamp("2025-01-01", tz="UTC"),
             "visible": pd.Timestamp("2025-05-01", tz="UTC"), "value": 100.0, "form": "10-Q"},
            {"end": pd.Timestamp("2025-06-30", tz="UTC"), "start": pd.Timestamp("2025-04-01", tz="UTC"),
             "visible": pd.Timestamp("2025-08-01", tz="UTC"), "value": 105.0, "form": "10-Q"},
            # FY annual ending 2026-06-30 (no FY26 quarters in facts)
            {"end": pd.Timestamp("2026-06-30", tz="UTC"), "start": pd.Timestamp("2025-07-01", tz="UTC"),
             "visible": pd.Timestamp("2026-08-17", tz="UTC"), "value": 460.0, "form": "10-K"},
            {"end": pd.Timestamp("2025-06-30", tz="UTC"), "start": pd.Timestamp("2024-07-01", tz="UTC"),
             "visible": pd.Timestamp("2025-08-15", tz="UTC"), "value": 390.0, "form": "10-K"},
        ]
        series = build_flow_ttm_or_annual_series(points)
        staircase = [(d.strftime("%Y-%m-%d"), v) for d, v in series]
        self.assertEqual(
            staircase,
            [
                ("2025-08-01", 390.0),   # Q4'24..Q2'25 window
                ("2025-08-15", 390.0),   # FY2025 annual (same TTM, own filing)
                ("2026-08-17", 460.0),   # FY2026 annual supersedes stale windows
            ],
        )

    def test_series_mis_tagged_10k_q4_entry_derives_true_q4(self) -> None:
        import pandas as pd

        points = [
            {"end": pd.Timestamp("2025-03-31", tz="UTC"), "start": pd.Timestamp("2025-01-01", tz="UTC"),
             "visible": pd.Timestamp("2025-04-30", tz="UTC"), "value": 100.0, "form": "10-Q"},
            {"end": pd.Timestamp("2025-06-30", tz="UTC"), "start": pd.Timestamp("2025-04-01", tz="UTC"),
             "visible": pd.Timestamp("2025-07-30", tz="UTC"), "value": 110.0, "form": "10-Q"},
            {"end": pd.Timestamp("2025-09-30", tz="UTC"), "start": pd.Timestamp("2025-01-01", tz="UTC"),
             "visible": pd.Timestamp("2025-10-30", tz="UTC"), "value": 330.0, "form": "10-Q"},
            {"end": pd.Timestamp("2025-09-30", tz="UTC"), "start": pd.Timestamp("2025-07-01", tz="UTC"),
             "visible": pd.Timestamp("2025-10-30", tz="UTC"), "value": 120.0, "form": "10-Q"},
            # 10-K mis-tags the annual value 460 into a Q4-ish period, and no
            # proper annual entry exists (L3Harris pattern).
            {"end": pd.Timestamp("2025-12-31", tz="UTC"), "start": pd.Timestamp("2025-10-01", tz="UTC"),
             "visible": pd.Timestamp("2026-02-20", tz="UTC"), "value": 460.0, "form": "10-K"},
            {"end": pd.Timestamp("2026-03-31", tz="UTC"), "start": pd.Timestamp("2026-01-01", tz="UTC"),
             "visible": pd.Timestamp("2026-04-30", tz="UTC"), "value": 140.0, "form": "10-Q"},
            {"end": pd.Timestamp("2026-06-30", tz="UTC"), "start": pd.Timestamp("2026-04-01", tz="UTC"),
             "visible": pd.Timestamp("2026-07-30", tz="UTC"), "value": 150.0, "form": "10-Q"},
        ]
        series = build_flow_ttm_or_annual_series(points)
        values = [v for _, v in series]
        # Q4'25 = 460 - 330 = 130 (not the mis-tagged 460);
        # latest window = Q3'25 + Q4'25 + Q1'26 + Q2'26 = 120+130+140+150
        self.assertIn(120.0 + 130.0 + 140.0 + 150.0, values)
        # ...and the mis-tagged 460 must never appear as a window sum.
        self.assertNotIn(460.0 + 140.0 + 150.0 + 120.0, values)

    def test_series_falls_back_to_annual_when_quarters_insufficient(self) -> None:
        import pandas as pd

        points = [
            {
                "end": pd.Timestamp("2024-12-31", tz="UTC"),
                "start": pd.Timestamp("2024-01-01", tz="UTC"),
                "visible": pd.Timestamp("2025-02-10", tz="UTC"),
                "value": 500.0,
                "form": "10-K",
            },
            {
                "end": pd.Timestamp("2023-12-31", tz="UTC"),
                "start": pd.Timestamp("2023-01-01", tz="UTC"),
                "visible": pd.Timestamp("2024-02-10", tz="UTC"),
                "value": 450.0,
                "form": "10-K",
            },
        ]
        series = build_flow_ttm_or_annual_series(points)
        # Annual fallback preserves the full annual level series (old behavior).
        self.assertEqual(
            series,
            [
                (pd.Timestamp("2024-02-10", tz="UTC"), 450.0),
                (pd.Timestamp("2025-02-10", tz="UTC"), 500.0),
            ],
        )


class TestScannerTtmRobustness(unittest.TestCase):
    """Regressions for real-data pathologies found in the 2026-09 cache audit."""

    def _calendar_facts(self, bogus_q4: bool, proper_annual: bool) -> dict:
        """Calendar FY. Quarterly revenue 2025: 100/110/120/130, 2026: 140/150/160.
        The 10-K mis-tags the annual value 460 into a Q4-duration context."""
        entries = [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "form": "10-Q", "filed": "2025-04-30"},
            {"start": "2025-01-01", "end": "2025-06-30", "val": 210, "form": "10-Q", "filed": "2025-07-30"},
            {"start": "2025-04-01", "end": "2025-06-30", "val": 110, "form": "10-Q", "filed": "2025-07-30"},
            {"start": "2025-01-01", "end": "2025-09-30", "val": 330, "form": "10-Q", "filed": "2025-10-30"},
            {"start": "2025-07-01", "end": "2025-09-30", "val": 120, "form": "10-Q", "filed": "2025-10-30"},
            {"start": "2026-01-01", "end": "2026-03-31", "val": 140, "form": "10-Q", "filed": "2026-04-30"},
            {"start": "2026-01-01", "end": "2026-06-30", "val": 290, "form": "10-Q", "filed": "2026-07-30"},
            {"start": "2026-04-01", "end": "2026-06-30", "val": 150, "form": "10-Q", "filed": "2026-07-30"},
            # bogus Q4: annual value tagged with a ~90d period (frame CY2025Q4)
            {"start": "2025-10-01", "end": "2025-12-31", "val": 460, "form": "10-K", "filed": "2026-02-20"},
        ]
        if proper_annual:
            entries.append(
                {"start": "2025-01-01", "end": "2025-12-31", "val": 460, "form": "10-K", "filed": "2026-02-20"}
            )
        return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}

    def test_mis_tagged_q4_with_proper_annual_uses_annual_minus_9m(self) -> None:
        facts = self._calendar_facts(bogus_q4=True, proper_annual=True)
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # Q4 derived 460 - 330 = 130, not the mis-tagged 460
        self.assertEqual(latest, 120.0 + 130.0 + 140.0 + 150.0)
        self.assertEqual(latest, 540.0)
        # No window ends ~1y before 2026-06-30 (no 2024 quarters) -> None
        self.assertIsNone(prev)

    def test_mis_tagged_q4_without_annual_reclassifies_value(self) -> None:
        facts = self._calendar_facts(bogus_q4=True, proper_annual=False)
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # The mis-tagged value 460 becomes the FY annual; Q4 = 460 - 330 = 130
        self.assertEqual(latest, 540.0)

    def test_fresher_annual_supersedes_stale_window(self) -> None:
        # Lumentum-style: quarters end mid-2025 (stale windows), the latest
        # 10-K annual (fiscal year == trailing 12m at its end) is newer.
        entries = [
            {"start": "2024-07-01", "end": "2024-09-30", "val": 90, "form": "10-Q", "filed": "2024-11-01"},
            {"start": "2024-10-01", "end": "2024-12-31", "val": 95, "form": "10-Q", "filed": "2025-02-01"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "form": "10-Q", "filed": "2025-05-01"},
            {"start": "2025-04-01", "end": "2025-06-30", "val": 105, "form": "10-Q", "filed": "2025-08-01"},
            {"start": "2025-07-01", "end": "2026-06-30", "val": 460, "form": "10-K", "filed": "2026-08-17"},
            {"start": "2024-07-01", "end": "2025-06-30", "val": 390, "form": "10-K", "filed": "2025-08-15"},
        ]
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # FY ending 2026-06-30 IS the trailing 12 months -> annual supersedes
        self.assertEqual(latest, 460.0)
        # YoY base: TTM ending ~1y earlier = the FY2025 annual
        self.assertEqual(prev, 390.0)

    def test_missing_q1_derived_from_h1_minus_q2(self) -> None:
        # Alkami-style: Q1'26 has no direct entry, but the H1'26 10-Q carries
        # the 6M YTD and the direct Q2 quarter.
        entries = [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 97.8, "form": "10-Q", "filed": "2025-05-01"},
            {"start": "2025-04-01", "end": "2025-06-30", "val": 112.1, "form": "10-Q", "filed": "2025-07-30"},
            {"start": "2025-07-01", "end": "2025-09-30", "val": 113.0, "form": "10-Q", "filed": "2025-10-31"},
            {"start": "2025-01-01", "end": "2025-12-31", "val": 443.6, "form": "10-K", "filed": "2026-02-26"},
            {"start": "2026-01-01", "end": "2026-06-30", "val": 256.0, "form": "10-Q", "filed": "2026-07-30"},
            {"start": "2026-04-01", "end": "2026-06-30", "val": 129.8, "form": "10-Q", "filed": "2026-07-30"},
        ]
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}
        latest, prev = pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")
        # Q4'25 = 443.6 - 9M... no 9M here; Q4 = annual - H1'25? No: within==3
        # (Q1,Q2,Q3) -> Q4 = 443.6 - 322.9 = 120.7. Q1'26 = 256.0 - 129.8 = 126.2
        q4 = 443.6 - (97.8 + 112.1 + 113.0)
        q1_26 = 256.0 - 129.8
        self.assertAlmostEqual(latest, q4 + q1_26 + 129.8 + 113.0, places=6)
        # = TTM ending 2026-06-30 = 443.6 + 256.0 - (97.8 + 112.1)
        self.assertAlmostEqual(latest, 443.6 + 256.0 - 209.9, places=6)
        # prev = year-ago window unavailable (only 3 quarters before) -> None
        self.assertIsNone(prev)


if __name__ == "__main__":
    unittest.main()
