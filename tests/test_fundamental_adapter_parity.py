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
        replay_pair = backtest.flow_pair_asof(
            records,
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

    def test_amendment_can_update_only_year_ago_base_after_filing(self) -> None:
        entries = [
            _flow_entry("2024-01-01", "2024-03-31", 10, "2024-05-01", accn="0001"),
            _flow_entry("2024-04-01", "2024-06-30", 20, "2024-08-01", accn="0002"),
            _flow_entry("2024-07-01", "2024-09-30", 30, "2024-11-01", accn="0003"),
            _flow_entry("2024-10-01", "2024-12-31", 40, "2025-02-15", accn="0004"),
            _flow_entry("2025-01-01", "2025-03-31", 11, "2025-05-01", accn="0005"),
            _flow_entry("2025-04-01", "2025-06-30", 21, "2025-08-01", accn="0006"),
            _flow_entry("2025-07-01", "2025-09-30", 31, "2025-11-01", accn="0007"),
            _flow_entry("2025-10-01", "2025-12-31", 41, "2026-02-15", accn="0008"),
            # Filed after the latest 2025 TTM is already known. This revision
            # changes only the year-ago TTM base (100 -> 102), not latest=104.
            _flow_entry(
                "2024-01-01",
                "2024-03-31",
                12,
                "2026-03-01",
                accn="0009",
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

        before = backtest.flow_pair_asof(
            records,
            series,
            pd.Timestamp("2026-02-20", tz="UTC"),
        )
        after = backtest.flow_pair_asof(
            records,
            series,
            pd.Timestamp("2026-03-02", tz="UTC"),
        )

        self.assertEqual(before, (104.0, 100.0))
        self.assertEqual(after, (104.0, 102.0))

    def test_cross_section_prefers_raw_fact_state_over_legacy_series(self) -> None:
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
        records = backtest.extract_metric_points(
            facts,
            ["Revenues"],
            "USD",
            scanner.QUARTERLY_FORMS,
        )
        stale_series = [
            (
                pd.Timestamp("2026-02-15", tz="UTC"),
                999.0,
                pd.Timestamp("2025-12-31", tz="UTC"),
            )
        ]
        fundamental = backtest.FundamentalPointInTime(
            sic=None,
            sic_description=None,
            revenue_series=stale_series,
            net_income_series=[],
            shares_series=[],
            operating_cash_flow_series=[],
            capex_series=[],
            ebit_series=[],
            cash_series=[],
            long_term_debt_series=[],
            current_debt_series=[],
            current_assets_series=[],
            current_liabilities_series=[],
            receivables_series=[],
            inventory_series=[],
            interest_expense_series=[],
            da_series=[],
            backlog_series=[],
            disclosure_series=[],
            ai_disclosure_score=0.0,
            ai_backlog_signal=0.0,
            fact_records={"revenue": records},
        )
        asof = pd.Timestamp("2026-03-01", tz="UTC")
        bars = pd.DataFrame(
            [
                {
                    "date": asof,
                    "open": 10.0,
                    "close": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "volume": 1_000_000.0,
                }
            ]
        ).set_index("date")
        bars["sma200"] = float("nan")
        universe = pd.DataFrame(
            [
                {
                    "symbol": "TEST",
                    "name": "Test",
                    "exchange": "NASDAQ",
                    "company_name": "Test",
                }
            ]
        )

        out = backtest.build_cross_section_asof(
            asof=asof,
            universe=universe,
            bar_db={"TEST": bars},
            fundamentals={"TEST": fundamental},
            theme_scores={},
            watchlist_by_symbol={"TEST": ("", 0, "")},
            benchmark_return_20d=None,
            benchmark_return_60d=None,
            disclosure_lookback_days=720,
            scan_config=scanner.ScanConfig(price_lookback_days=30),
        )

        self.assertEqual(len(out), 1)
        self.assertEqual(float(out.iloc[0]["revenue"]), 104.0)
        self.assertAlmostEqual(float(out.iloc[0]["revenue_yoy"]), 0.04, places=12)

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
        replay_pair = backtest.level_pair_asof(
            records,
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
