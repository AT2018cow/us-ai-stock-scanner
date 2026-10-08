from __future__ import annotations

import unittest

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.features.price import compute_price_history_features


def _scanner_bar(ts: pd.Timestamp, close: float, high: float, low: float, volume: float) -> dict:
    return {
        "t": ts.isoformat().replace("+00:00", "Z"),
        "o": close,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
    }


def _frame(index: pd.DatetimeIndex, closes: list[float], highs: list[float], lows: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        },
        index=index,
    )
    frame["sma200"] = frame["close"].rolling(window=200, min_periods=200).mean()
    return frame


class TestPriceHistoryFeatureCore(unittest.TestCase):
    def test_requires_complete_sma200_window(self) -> None:
        short = compute_price_history_features(
            current_price=110.0,
            range_highs=[120.0],
            range_lows=[80.0],
            closes=[100.0] * 199,
            dollar_volumes=[1_000_000.0] * 20,
        )
        self.assertIsNone(short["price_to_sma200"])
        self.assertIsNone(short["days_below_sma200"])

        full = compute_price_history_features(
            current_price=110.0,
            range_highs=[120.0],
            range_lows=[80.0],
            closes=[100.0] * 200,
            dollar_volumes=[1_000_000.0] * 20,
        )
        self.assertEqual(full["price_to_sma200"], 1.1)
        self.assertEqual(full["days_below_sma200"], 0)

    def test_golden_range_returns_volatility_and_liquidity(self) -> None:
        out = compute_price_history_features(
            current_price=90.0,
            range_highs=[100.0, 120.0, 110.0],
            range_lows=[60.0, 80.0, 70.0],
            closes=[100.0] * 200 + [90.0],
            dollar_volumes=[2_000_000.0] * 20,
        )
        self.assertEqual(out["drawdown_from_52w_high"], 0.25)
        self.assertEqual(out["range_position_52w"], 0.5)
        self.assertEqual(out["days_below_sma200"], 1)
        self.assertEqual(out["return_20d"], -0.1)
        self.assertEqual(out["return_60d"], -0.1)
        self.assertGreater(float(out["volatility_60d"]), 0.0)
        self.assertEqual(out["avg_dollar_volume_20d"], 2_000_000.0)

    def test_recent_listing_scanner_no_longer_uses_short_average_as_sma200(self) -> None:
        idx = pd.date_range("2026-01-02", periods=100, freq="B", tz="UTC")
        bars = [_scanner_bar(ts, 100.0, 101.0, 99.0, 1_000_000.0) for ts in idx]
        out = scanner.price_dimension_from_bars(100.0, bars)
        self.assertIsNone(out["price_to_sma200"])
        self.assertIsNone(out["days_below_sma200"])


class TestScannerReplayPriceParity(unittest.TestCase):
    def test_same_visible_history_matches_shared_features(self) -> None:
        idx = pd.date_range("2025-01-02", periods=260, freq="B", tz="UTC")
        closes = [100.0 + i * 0.1 for i in range(len(idx))]
        highs = [value + 1.0 for value in closes]
        lows = [value - 1.0 for value in closes]
        bars = [
            _scanner_bar(ts, close, high, low, 1_000_000.0)
            for ts, close, high, low in zip(idx, closes, highs, lows)
        ]
        frame = _frame(idx, closes, highs, lows)

        scan = scanner.price_dimension_from_bars(closes[-1], bars)
        replay = backtest.compute_price_features_asof(
            frame,
            asof=idx[-1],
            lookback_days=420,
        )
        self.assertIsNotNone(replay)
        for key, value in scan.items():
            self.assertEqual(replay[key], value, key)

    def test_replay_lookback_is_calendar_days_not_trading_row_count(self) -> None:
        idx = pd.date_range("2024-01-02", periods=450, freq="B", tz="UTC")
        closes = [100.0] * len(idx)
        highs = [101.0] * len(idx)
        lows = [99.0] * len(idx)
        # This spike is inside the old tail(420 rows) window but more than
        # 420 calendar days before the final asof.
        highs[50] = 1000.0
        frame = _frame(idx, closes, highs, lows)

        out = backtest.compute_price_features_asof(
            frame,
            asof=idx[-1],
            lookback_days=420,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["drawdown_from_52w_high"], round(1.0 - 100.0 / 101.0, 6))
        self.assertLess(float(out["drawdown_from_52w_high"]), 0.02)


if __name__ == "__main__":
    unittest.main()
