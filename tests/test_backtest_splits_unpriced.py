from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ai_value_scanner.backtest import (
    apply_split_adjustment_to_frame,
    build_price_frame_map,
    compute_price_features_asof,
    event_backtest,
)


def _frame(dates: list[str], closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(dates, utc=True))
    closes = list(closes)
    opens = list(opens) if opens is not None else list(closes)
    df = pd.DataFrame(
        {
            "open": opens,
            "close": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "volume": [1_000_000.0] * len(closes),
        },
        index=idx,
    )
    df["sma200"] = df["close"].rolling(window=200, min_periods=200).mean()
    return df


def _daily_dates(start: str, n: int) -> list[str]:
    return [(pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


class TestApplySplitAdjustmentToFrame(unittest.TestCase):
    def test_forward_split_continuity(self) -> None:
        dates = _daily_dates("2026-01-05", 30)
        closes = [1000.0] * 10 + [100.0] * 20
        out = apply_split_adjustment_to_frame(_frame(dates, closes), [("2026-01-15", 0.1)])
        self.assertTrue((out["close"].iloc[:10] - 100.0).abs().max() < 1e-9)
        self.assertTrue((out["close"].iloc[10:] - 100.0).abs().max() < 1e-9)
        # volume scaled inversely: dollar volume invariant per day
        self.assertAlmostEqual(out["volume"].iloc[0], 1_000_000.0 / 0.1, places=3)

    def test_sma_recomputed_from_adjusted_closes(self) -> None:
        dates = _daily_dates("2025-01-01", 250)
        closes = [1000.0] * 50 + [100.0] * 200
        out = apply_split_adjustment_to_frame(_frame(dates, closes), [("2025-02-20", 0.1)])
        # last 200 closes are all 100 post-adjustment -> sma200 == 100, not the raw-blended value
        self.assertAlmostEqual(float(out["sma200"].iloc[-1]), 100.0, places=6)

    def test_no_events_returns_frame_unchanged(self) -> None:
        f = _frame(_daily_dates("2026-01-05", 5), [10.0] * 5)
        self.assertTrue(apply_split_adjustment_to_frame(f, None).equals(f))
        self.assertTrue(apply_split_adjustment_to_frame(f, []).equals(f))

    def test_reverse_split(self) -> None:
        dates = _daily_dates("2026-03-01", 4)
        out = apply_split_adjustment_to_frame(_frame(dates, [10.0, 10.0, 40.0, 40.0]), [("2026-03-03", 4.0)])
        self.assertAlmostEqual(float(out["close"].iloc[0]), 40.0, places=6)
        self.assertAlmostEqual(float(out["close"].iloc[2]), 40.0, places=6)


class TestPriceFeaturesWithSplits(unittest.TestCase):
    def test_drawdown_corrected(self) -> None:
        # NFLX-style: raw pre-split high 1266, 10:1 split, last close 69.25
        pre = ["2025-08-%02d" % d for d in range(5, 30)]
        post = ["2025-12-%02d" % d for d in range(1, 20)]
        dates = pre + post
        closes = [1200.0] * len(pre) + [69.25] * len(post)
        asof = pd.Timestamp("2026-09-28", tz="UTC")
        full_dates = dates + [f"2026-{m:02d}-{d:02d}" for m in range(1, 9) for d in (5, 12, 19, 26)][:200]
        full_closes = closes + [69.25] * (len(full_dates) - len(closes))
        frame = _frame(full_dates, full_closes)
        raw = compute_price_features_asof(frame, asof, 420)
        adj = compute_price_features_asof(frame, asof, 420, [("2025-11-17", 0.1)])
        self.assertGreater(raw["drawdown_from_52w_high"], 0.9)
        self.assertLess(adj["drawdown_from_52w_high"], 0.5)
        # pre-split dollar volume unchanged by the adjustment
        self.assertAlmostEqual(
            float(frame["close"].iloc[0] * frame["volume"].iloc[0]),
            1200.0 * 1_000_000.0,
            places=3,
        )


class TestPriceFrameMapWithSplits(unittest.TestCase):
    def test_forward_return_across_split(self) -> None:
        bars = [
            {"t": "2026-01-05T00:00:00Z", "o": 1000.0, "c": 1000.0},
            {"t": "2026-01-06T00:00:00Z", "o": 100.0, "c": 110.0},
        ]
        raw = build_price_frame_map({"S": bars})
        adj = build_price_frame_map({"S": bars}, {"S": [("2026-01-06", 0.1)]})
        # raw: 110/1000-1 = -0.89 (split printed as a crash)
        r_raw = (raw["S"]["close"].iloc[-1] / raw["S"]["close"].iloc[0]) - 1.0
        r_adj = (adj["S"]["close"].iloc[-1] / adj["S"]["close"].iloc[0]) - 1.0
        self.assertAlmostEqual(r_raw, -0.89, places=6)
        self.assertAlmostEqual(r_adj, 0.10, places=6)


def _signals(symbols: list[str], signal_date: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "scenario": "s", "run_stem": "r", "run_ts_utc": "t",
        "signal_date": signal_date, "list_type": "low_value",
        "symbols": symbols, "n_selected": len(symbols),
    }])


def _live_frame(start: str, n: int, px: float = 100.0) -> pd.DataFrame:
    dates = _daily_dates(start, n)
    return _frame(dates, [px] * n)


class TestUnpricedDelistAssumption(unittest.TestCase):
    def test_missing_frame_mature_window_uses_assumption(self) -> None:
        sig = _signals(["AAA", "GHOST"], "2024-01-05")
        prices = {"AAA": _live_frame("2023-06-01", 500)}
        events, _ = event_backtest(
            signals=sig, prices_by_symbol=prices, horizons=[120],
            roundtrip_cost=0.003, benchmark_symbols=[],
            entry_price_mode="next_open", exit_price_mode="close",
            delist_return_assumption=-0.55, delist_detection_buffer_days=7,
        )
        row = events.iloc[0]
        self.assertEqual(row["n_assumed_delist"], 1)
        self.assertEqual(row["n_priced"], 2)
        # assumed-delist names count as priced (their assumed return IS in the
        # mean); n_assumed_delist carries the transparency.
        self.assertEqual(row["event_status"], "valid")

    def test_missing_frame_recent_signal_still_skipped(self) -> None:
        sig = _signals(["GHOST"], "2026-09-20")
        prices = {"QQQ": _live_frame("2026-01-01", 300)}
        events, _ = event_backtest(
            signals=sig, prices_by_symbol=prices, horizons=[120],
            roundtrip_cost=0.003, benchmark_symbols=[],
            entry_price_mode="next_open", exit_price_mode="close",
            delist_return_assumption=-0.55, delist_detection_buffer_days=7,
        )
        row = events.iloc[0]
        self.assertEqual(row["n_assumed_delist"], 0)
        self.assertEqual(row["event_status"], "unpriced")

    def test_no_assumption_configured_skips(self) -> None:
        sig = _signals(["GHOST"], "2024-01-05")
        events, _ = event_backtest(
            signals=sig, prices_by_symbol={}, horizons=[120],
            roundtrip_cost=0.003, benchmark_symbols=[],
            entry_price_mode="next_open", exit_price_mode="close",
            delist_return_assumption=None, delist_detection_buffer_days=7,
        )
        self.assertEqual(events.iloc[0]["event_status"], "unpriced")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
