from __future__ import annotations

import unittest

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner


def _flow_entry(
    start: str,
    end: str,
    value: float,
    filed: str,
    *,
    accn: str,
    form: str = "10-Q",
) -> dict:
    return {
        "start": start,
        "end": end,
        "val": value,
        "filed": filed,
        "accn": accn,
        "form": form,
    }


def _companyfacts(tag: str, unit: str, entries: list[dict]) -> dict:
    return {"facts": {"us-gaap": {tag: {"units": {unit: entries}}}}}


class TestScannerReplayReconstructionParity(unittest.TestCase):
    def test_flow_ttm_and_year_ago_match_on_same_visible_facts(self) -> None:
        entries = [
            _flow_entry("2024-01-01", "2024-03-31", 10, "2024-05-01", accn="0001"),
            _flow_entry("2024-04-01", "2024-06-30", 20, "2024-08-01", accn="0002"),
            _flow_entry("2024-07-01", "2024-09-30", 30, "2024-11-01", accn="0003"),
            _flow_entry("2024-10-01", "2024-12-31", 40, "2025-02-15", accn="0004"),
            _flow_entry("2025-01-01", "2025-03-31", 11, "2025-05-01", accn="0005"),
            _flow_entry("2025-04-01", "2025-06-30", 21, "2025-08-01", accn="0006"),
            _flow_entry("2025-07-01", "2025-09-30", 31, "2025-11-01", accn="0007"),
            _flow_entry("2025-10-01", "2025-12-31", 41, "2026-02-15", accn="0008"),
        ]
        facts = _companyfacts("Revenues", "USD", entries)

        scan_pair = scanner.pick_latest_and_prev_ttm(facts, ["Revenues"], "USD")

        records = backtest.extract_metric_points(
            facts,
            ["Revenues"],
            "USD",
            scanner.QUARTERLY_FORMS,
        )
        replay_series = backtest.build_flow_ttm_or_annual_series(records)
        replay_pair = backtest.latest_and_year_ago_flow(
            replay_series,
            pd.Timestamp("2026-03-01", tz="UTC"),
        )

        self.assertEqual(scan_pair, (104.0, 100.0))
        self.assertEqual(replay_pair, scan_pair)

    def test_future_amendment_changes_only_post_filing_pit_state(self) -> None:
        entries = [
            _flow_entry("2024-01-01", "2024-03-31", 10, "2024-05-01", accn="0001"),
            _flow_entry("2024-04-01", "2024-06-30", 20, "2024-08-01", accn="0002"),
            _flow_entry("2024-07-01", "2024-09-30", 30, "2024-11-01", accn="0003"),
            _flow_entry("2024-10-01", "2024-12-31", 40, "2025-02-15", accn="0004"),
            _flow_entry(
                "2024-01-01",
                "2024-03-31",
                12,
                "2025-03-01",
                accn="0005",
                form="10-Q/A",
            ),
        ]
        facts = _companyfacts("Revenues", "USD", entries)
        records = backtest.extract_metric_points(
            facts,
            ["Revenues"],
            "USD",
            scanner.QUARTERLY_FORMS,
        )
        series = backtest.build_flow_ttm_or_annual_series(records)

        before = backtest.series_value_asof(
            series,
            pd.Timestamp("2025-02-20", tz="UTC"),
        )[0]
        after = backtest.series_value_asof(
            series,
            pd.Timestamp("2025-03-02", tz="UTC"),
        )[0]

        self.assertEqual(before, 100.0)
        self.assertEqual(after, 102.0)

    def test_level_year_ago_matches_and_rejects_adjacent_quarter(self) -> None:
        entries = [
            {
                "end": "2024-12-31",
                "val": 80,
                "filed": "2025-02-15",
                "accn": "0001",
                "form": "10-K",
            },
            {
                "end": "2025-09-30",
                "val": 90,
                "filed": "2025-11-01",
                "accn": "0002",
                "form": "10-Q",
            },
            {
                "end": "2025-12-31",
                "val": 100,
                "filed": "2026-02-15",
                "accn": "0003",
                "form": "10-K",
            },
        ]
        facts = _companyfacts("Assets", "USD", entries)

        scan_pair = scanner.pick_latest_and_year_ago_with_forms(
            facts,
            ["Assets"],
            "USD",
            scanner.QUARTERLY_FORMS,
        )
        records = backtest.extract_metric_points(
            facts,
            ["Assets"],
            "USD",
            scanner.QUARTERLY_FORMS,
        )
        series = backtest.build_level_series(records)
        replay_pair = backtest.latest_and_year_ago_level(
            series,
            pd.Timestamp("2026-03-01", tz="UTC"),
        )

        self.assertEqual(scan_pair, (100.0, 80.0))
        self.assertEqual(replay_pair, scan_pair)

        no_base_facts = _companyfacts(
            "Assets",
            "USD",
            entries[1:],
        )
        self.assertEqual(
            scanner.pick_latest_and_year_ago_with_forms(
                no_base_facts,
                ["Assets"],
                "USD",
                scanner.QUARTERLY_FORMS,
            ),
            (100.0, None),
        )


if __name__ == "__main__":
    unittest.main()
