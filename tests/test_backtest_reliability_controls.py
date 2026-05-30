from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from ai_value_scanner.backtest import (
    ai_disclosure_score_asof,
    build_flow_ttm_or_annual_series,
    build_cross_section_asof,
    close_history_from_frame_asof,
    FundamentalPointInTime,
    forward_return,
    parse_watchlist_snapshot_date,
    resolve_watchlist_asof,
    series_up_to_asof,
)
from ai_value_scanner.scanner import ScanConfig


class TestBacktestReliabilityControls(unittest.TestCase):
    def test_parse_watchlist_snapshot_date(self) -> None:
        self.assertEqual(
            parse_watchlist_snapshot_date(Path("ai_watchlist_20260529.csv")),
            pd.Timestamp("2026-05-29", tz="UTC"),
        )
        self.assertEqual(
            parse_watchlist_snapshot_date(Path("snapshot_2026-05-29.csv")),
            pd.Timestamp("2026-05-29", tz="UTC"),
        )
        self.assertEqual(
            parse_watchlist_snapshot_date(Path("watch_20260529T120000Z.csv")),
            pd.Timestamp("2026-05-29", tz="UTC"),
        )

    def test_resolve_watchlist_asof_prefers_latest_snapshot_before_asof(self) -> None:
        snapshots = [
            (pd.Timestamp("2024-01-01", tz="UTC"), {"A": ("core_ai", 1, "AIQ")}, "w1.csv"),
            (pd.Timestamp("2025-01-01", tz="UTC"), {"B": ("ai_enabler", 1, "XLI")}, "w2.csv"),
        ]
        mapping, source = resolve_watchlist_asof(
            asof=pd.Timestamp("2024-06-01", tz="UTC"),
            snapshots=snapshots,
            latest_map={"Z": ("core_ai", 1, "AIQ")},
            allow_latest_fallback=True,
        )
        self.assertTrue(source.startswith("snapshot:w1.csv"))
        self.assertEqual(set(mapping.keys()), {"A"})

    def test_ai_disclosure_score_asof_excludes_future_filings(self) -> None:
        disclosure = [
            (pd.Timestamp("2024-01-15", tz="UTC"), "artificial intelligence data center"),
            (pd.Timestamp("2025-01-15", tz="UTC"), "nuclear grid expansion"),
        ]
        s_2024 = ai_disclosure_score_asof(
            disclosure,
            asof=pd.Timestamp("2024-06-01", tz="UTC"),
            lookback_days=365,
            disclosure_keyword_cap=6,
        )
        s_2025_short = ai_disclosure_score_asof(
            disclosure,
            asof=pd.Timestamp("2025-06-01", tz="UTC"),
            lookback_days=120,
            disclosure_keyword_cap=6,
        )
        self.assertGreater(s_2024, 0)
        self.assertEqual(s_2025_short, 0)

    def test_build_flow_ttm_or_annual_series_prefers_quarterly_ttm(self) -> None:
        points = [
            {
                "end": pd.Timestamp("2024-03-31", tz="UTC"),
                "visible": pd.Timestamp("2024-05-01", tz="UTC"),
                "value": 10.0,
                "form": "10-Q",
            },
            {
                "end": pd.Timestamp("2024-06-30", tz="UTC"),
                "visible": pd.Timestamp("2024-08-01", tz="UTC"),
                "value": 11.0,
                "form": "10-Q",
            },
            {
                "end": pd.Timestamp("2024-09-30", tz="UTC"),
                "visible": pd.Timestamp("2024-11-01", tz="UTC"),
                "value": 12.0,
                "form": "10-Q",
            },
            {
                "end": pd.Timestamp("2024-12-31", tz="UTC"),
                "visible": pd.Timestamp("2025-02-15", tz="UTC"),
                "value": 13.0,
                "form": "10-Q",
            },
        ]
        series = build_flow_ttm_or_annual_series(points)
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0][1], 46.0)

    def test_forward_return_uses_next_open_when_configured(self) -> None:
        idx = pd.date_range("2026-01-01", "2026-01-10", freq="B", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": [10, 11, 12, 13, 14, 15, 16],
                "close": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5],
            },
            index=idx,
        )
        ret = forward_return(
            frame,
            signal_date="2025-12-31",
            horizon=3,
            roundtrip_cost=0.0,
            entry_price_mode="next_open",
            exit_price_mode="close",
        )
        self.assertIsNotNone(ret)
        self.assertEqual(round(float(ret), 6), 0.25)

    def test_series_up_to_asof_truncates_future_points(self) -> None:
        series = [
            (pd.Timestamp("2025-01-01", tz="UTC"), 1.0),
            (pd.Timestamp("2025-02-01", tz="UTC"), 2.0),
            (pd.Timestamp("2025-03-01", tz="UTC"), 3.0),
        ]
        out = series_up_to_asof(series, pd.Timestamp("2025-02-15", tz="UTC"))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[-1][1], 2.0)

    def test_close_history_from_frame_asof_truncates_future_prices(self) -> None:
        frame = pd.DataFrame(
            {
                "date": [
                    pd.Timestamp("2025-01-02", tz="UTC"),
                    pd.Timestamp("2025-01-03", tz="UTC"),
                    pd.Timestamp("2025-01-06", tz="UTC"),
                ],
                "close": [10.0, 11.0, 12.0],
            }
        )
        out = close_history_from_frame_asof(frame, pd.Timestamp("2025-01-03", tz="UTC"))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[-1][1], 11.0)

    def test_cross_section_computes_historical_valuation_percentiles(self) -> None:
        symbol = "TEST"
        universe = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "name": "Test Inc",
                    "exchange": "NASDAQ",
                    "company_name": "Test Incorporated",
                }
            ]
        )
        bars = pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-01-02", tz="UTC"), "open": 10.0, "close": 10.0, "high": 10.0, "low": 10.0, "volume": 1_000_000},
                {"date": pd.Timestamp("2026-01-05", tz="UTC"), "open": 12.0, "close": 12.0, "high": 12.0, "low": 12.0, "volume": 1_000_000},
                {"date": pd.Timestamp("2026-01-08", tz="UTC"), "open": 14.0, "close": 14.0, "high": 14.0, "low": 14.0, "volume": 1_000_000},
                {"date": pd.Timestamp("2026-01-11", tz="UTC"), "open": 16.0, "close": 16.0, "high": 16.0, "low": 16.0, "volume": 1_000_000},
                {"date": pd.Timestamp("2026-01-15", tz="UTC"), "open": 18.0, "close": 18.0, "high": 18.0, "low": 18.0, "volume": 1_000_000},
            ]
        )
        bars = bars.set_index("date")
        bars["sma200"] = bars["close"].rolling(window=200, min_periods=200).mean()
        fundamentals = {
            symbol: FundamentalPointInTime(
                sic="3571",
                sic_description="Electronic Computers",
                revenue_series=[
                    (pd.Timestamp("2026-01-02", tz="UTC"), 120.0),
                    (pd.Timestamp("2026-01-05", tz="UTC"), 140.0),
                    (pd.Timestamp("2026-01-08", tz="UTC"), 180.0),
                    (pd.Timestamp("2026-01-11", tz="UTC"), 260.0),
                    (pd.Timestamp("2026-01-15", tz="UTC"), 320.0),
                ],
                net_income_series=[
                    (pd.Timestamp("2026-01-02", tz="UTC"), 24.0),
                    (pd.Timestamp("2026-01-05", tz="UTC"), 26.0),
                    (pd.Timestamp("2026-01-08", tz="UTC"), 30.0),
                    (pd.Timestamp("2026-01-11", tz="UTC"), 36.0),
                    (pd.Timestamp("2026-01-15", tz="UTC"), 40.0),
                ],
                shares_series=[(pd.Timestamp("2026-01-02", tz="UTC"), 10.0)],
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
            )
        }
        cfg = ScanConfig(price_lookback_days=30, own_history_valuation_window_days=720)
        asof = pd.Timestamp("2026-01-15", tz="UTC")
        out = build_cross_section_asof(
            asof=asof,
            universe=universe,
            bar_db={symbol: bars},
            fundamentals=fundamentals,
            theme_scores={},
            watchlist_by_symbol={symbol: ("core_ai", 1, "AIQ")},
            benchmark_return_20d=None,
            benchmark_return_60d=None,
            disclosure_lookback_days=720,
            scan_config=cfg,
        )
        self.assertEqual(len(out), 1)
        self.assertTrue(pd.notna(out.iloc[0]["ps_hist_percentile"]))
        self.assertTrue(pd.notna(out.iloc[0]["pe_hist_percentile"]))
        self.assertGreaterEqual(float(out.iloc[0]["ps_hist_observation_count"]), 3.0)
        self.assertEqual(str(out.iloc[0]["ps_hist_percentile_source"]), "valuation_history")


if __name__ == "__main__":
    unittest.main()
