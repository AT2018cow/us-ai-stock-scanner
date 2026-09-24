from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ai_value_scanner.backtest import (
    ai_disclosure_score_asof,
    build_flow_ttm_or_annual_series,
    build_cross_section_asof,
    build_level_series,
    build_signal_diagnostics,
    close_history_from_frame_asof,
    event_backtest,
    extract_metric_points,
    FundamentalPointInTime,
    forward_return,
    near_miss_concentration,
    pick_research_pool_symbols_with_diagnostics,
    parse_watchlist_snapshot_date,
    resolve_watchlist_asof,
    series_up_to_asof,
)
from ai_value_scanner.scanner import ScanConfig, SHARES_TAGS, QUARTERLY_FORMS, archive_watchlist_snapshot


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

    def test_benchmark_trailing_return_asof_is_pit(self) -> None:
        # Regression (Phase 4 audit): the regime symbol's bars must be fetched
        # even when the config has no benchmark trend filter — balanced ran
        # with regime="unknown" on all 1584 events because QQQ never entered
        # the bar-fetch list.
        from ai_value_scanner.backtest import benchmark_trailing_return_asof

        frame = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=130, freq="D", tz="UTC"),
                "close": np.linspace(100, 160, 130),
            }
        ).set_index("date")
        db = {"QQQ": frame}
        r = benchmark_trailing_return_asof(db, "QQQ", pd.Timestamp("2024-05-01", tz="UTC"), 60)
        self.assertIsNotNone(r)
        self.assertGreater(r, 0.0)  # rising series -> positive trailing return

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

    def test_extract_metric_points_merges_across_tags_pit(self) -> None:
        # Regression (PIT replay of the RTX bug): with the old first-tag-wins
        # loop, a stale us-gaap CommonStockSharesOutstanding (2009) hid the
        # current dei count. Points must merge across all tags, and at equal
        # visibility dates the earlier tag in SHARES_TAGS (dei) wins.
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "CommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                {"end": "2009-12-31", "val": 1_381_700, "form": "10-K", "filed": "2010-02-11"},
                            ]
                        }
                    },
                    "WeightedAverageNumberOfSharesOutstandingBasic": {
                        "units": {
                            "shares": [
                                {"end": "2026-06-30", "val": 1_350_700_000, "form": "10-Q", "filed": "2026-07-23"},
                            ]
                        }
                    },
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                {"end": "2026-06-30", "val": 1_347_758_144, "form": "10-Q", "filed": "2026-07-23"},
                            ]
                        }
                    },
                },
            }
        }
        points = extract_metric_points(companyfacts, SHARES_TAGS, "shares", QUARTERLY_FORMS)
        self.assertTrue(len(points) >= 3)
        series = build_level_series(points)
        at_filing = [v for t, v in series if t == pd.Timestamp("2026-07-23", tz="UTC")]
        self.assertEqual(at_filing, [1_347_758_144.0])
        # PIT at 2026-08-01 sees the fresh count, not the 2009 value.
        asof = pd.Timestamp("2026-08-01", tz="UTC")
        visible_up_to = [v for t, v in series if t <= asof]
        self.assertEqual(visible_up_to[-1], 1_347_758_144.0)

    def test_archive_watchlist_snapshot_writes_history_copy(self) -> None:
        import tempfile
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "ai_watchlist.csv"
            src.write_text("symbol,bucket,etf_count,etfs,enabled\nTEST,core_ai,1,AIQ,1\n")
            (tmp_path / "history").mkdir()
            # Point the archive helper at the temp tree by chdir.
            cwd = Path.cwd()
            (tmp_path / "data").mkdir(exist_ok=True)
            cfg = ScanConfig(watchlist_csv_path=str(src))
            try:
                import os

                os.chdir(tmp_path)
                started = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
                out = archive_watchlist_snapshot(cfg, started)
                self.assertIsNotNone(out)
                self.assertTrue(out.exists())
                self.assertEqual(out.name, "ai_watchlist_20260922T120000Z.csv")
                self.assertEqual(
                    parse_watchlist_snapshot_date(out),
                    pd.Timestamp("2026-09-22", tz="UTC"),
                )
                # Idempotent: second call returns the same path without error.
                self.assertEqual(archive_watchlist_snapshot(cfg, started), out)
            finally:
                os.chdir(cwd)

    def test_near_miss_concentration_finds_single_blocking_step(self) -> None:
        df = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "quality": [1.0, 1.0, 0.0],
                "value": [1.0, 0.0, 1.0],
            }
        )
        steps = [
            ("quality_gate", lambda frame: frame["quality"] > 0),
            ("value_gate", lambda frame: frame["value"] > 0),
        ]
        result = near_miss_concentration(df, steps)
        self.assertEqual(result["top_reason"], "quality_gate")
        reasons = {row["reason"]: row["count"] for row in result["reasons"]}
        self.assertEqual(reasons["quality_gate"], 1)
        self.assertEqual(reasons["value_gate"], 1)

    def test_research_pool_pick_uses_priority_before_score(self) -> None:
        cfg = ScanConfig()
        cfg.research_pool_min_score = 2.0
        cfg.research_pool_top_n = 5
        df = pd.DataFrame(
            [
                {
                    "symbol": "THEME",
                    "watchlist_bucket": "ai_enabler",
                    "watchlist_etfs": "PAVE",
                    "fundamental_quality_score": 0.9,
                    "ai_link_score": 0.5,
                    "ps_hist_percentile": 0.05,
                    "pe_hist_percentile": 0.05,
                    "ps_discount": 0.3,
                    "pe_discount": 0.3,
                    "fcf_yield": 0.1,
                    "ev_to_ebit": 8.0,
                    "revenue_yoy": -0.01,
                    "net_income_yoy": -0.05,
                    "return_20d": -0.08,
                    "return_60d": -0.02,
                    "drawdown_from_52w_high": 0.2,
                    "price_to_sma200": 0.9,
                },
                {
                    "symbol": "NOW",
                    "watchlist_bucket": "ai_enabler",
                    "watchlist_etfs": "PAVE",
                    "fundamental_quality_score": 0.86,
                    "ai_link_score": 0.5,
                    "ps_hist_percentile": 0.30,
                    "pe_hist_percentile": 0.30,
                    "ps_discount": 0.0,
                    "pe_discount": 0.0,
                    "fcf_yield": 0.07,
                    "ev_to_ebit": 11.0,
                    "revenue_yoy": 0.12,
                    "net_income_yoy": 0.2,
                    "return_20d": 0.01,
                    "return_60d": 0.03,
                    "drawdown_from_52w_high": 0.05,
                    "price_to_sma200": 1.0,
                },
            ]
        )
        picks, diag = pick_research_pool_symbols_with_diagnostics(
            df=df,
            scan_config=cfg,
            top_n=2,
            per_channel_top_n=False,
            include_channels=["ai_enabler"],
        )
        self.assertEqual(picks[0], "NOW")
        self.assertEqual(diag["priority_counts"].get("research_now"), 1)
        self.assertEqual(diag["priority_counts"].get("theme_only"), 1)

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

    def test_event_backtest_marks_no_signal_and_unpriced_events(self) -> None:
        signals = pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "run_stem": "r1",
                    "run_ts_utc": "2026-01-01T00:00:00+00:00",
                    "signal_date": "2026-01-01",
                    "list_type": "momentum",
                    "symbols": [],
                    "n_selected": 0,
                },
                {
                    "scenario": "base",
                    "run_stem": "r2",
                    "run_ts_utc": "2026-01-02T00:00:00+00:00",
                    "signal_date": "2026-01-02",
                    "list_type": "momentum",
                    "symbols": ["MISS"],
                    "n_selected": 1,
                },
            ]
        )
        events, _ = event_backtest(
            signals=signals,
            prices_by_symbol={},
            horizons=[20],
            roundtrip_cost=0.0,
            benchmark_symbols=[],
        )
        self.assertEqual(events.loc[0, "event_status"], "no_signal")
        self.assertEqual(events.loc[1, "event_status"], "unpriced")

    def test_build_signal_diagnostics_parses_channel_json(self) -> None:
        signals = pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "run_stem": "r1",
                    "signal_date": "2026-01-01",
                    "list_type": "momentum",
                    "watchlist_source": "latest_fallback",
                    "channel_counts": '{"core_ai": 2}',
                    "channel_symbols": '{"core_ai": ["A", "B"]}',
                    "filter_diagnostics": (
                        '{"core_ai": {"n_input": 5, "n_filtered": 3, "n_ranked": 2, '
                        '"first_fail": {"top_reason": "valuation", "top_pct": 0.4}, '
                        '"layer_summary": {"quality": {"before": 5, "remaining": 3, '
                        '"removed": 2, "pass_rate": 0.6}}}}'
                    ),
                }
            ]
        )
        diagnostics, channel_summary = build_signal_diagnostics(signals)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(len(channel_summary), 1)
        self.assertEqual(channel_summary.loc[0, "n_selected_channel"], 2)
        self.assertEqual(channel_summary.loc[0, "selected_symbols"], "A,B")
        self.assertEqual(diagnostics.loc[0, "layer"], "quality")
        self.assertAlmostEqual(float(diagnostics.loc[0, "pass_rate"]), 0.6)

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
