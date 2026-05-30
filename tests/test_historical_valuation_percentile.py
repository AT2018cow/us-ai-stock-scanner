from __future__ import annotations

import unittest

from ai_value_scanner.scanner import (
    compute_historical_valuation_percentile,
    extract_close_history_from_bars,
    parse_history_pairs,
)


class TestHistoricalValuationPercentile(unittest.TestCase):
    def test_valuation_percentile_uses_valuation_series_not_raw_price(self) -> None:
        bars = []
        for day, close in enumerate([10, 11, 12, 13, 14, 15, 16, 17, 18, 19], start=1):
            bars.append({"t": f"2026-01-{day:02d}T00:00:00Z", "c": close})
        closes = extract_close_history_from_bars(bars)

        revenue_hist = parse_history_pairs(
            [
                {"end": "2026-01-03", "value": 100},
                {"end": "2026-01-05", "value": 150},
                {"end": "2026-01-07", "value": 220},
                {"end": "2026-01-09", "value": 300},
            ]
        )
        shares_hist = parse_history_pairs([{"end": "2026-01-01", "value": 10}])

        # Current multiple is low relative to historical valuation points even though
        # price trend itself is rising.
        pct, obs = compute_historical_valuation_percentile(
            current_multiple=0.70,
            closes=closes,
            denominator_history=revenue_hist,
            shares_history=shares_hist,
            current_shares=10.0,
            window_days=365,
            min_observations=3,
        )
        self.assertEqual(obs, 4)
        self.assertIsNotNone(pct)
        self.assertAlmostEqual(float(pct), 0.25, places=6)

    def test_insufficient_history_returns_none(self) -> None:
        bars = [
            {"t": "2026-01-01T00:00:00Z", "c": 10},
            {"t": "2026-01-02T00:00:00Z", "c": 11},
        ]
        closes = extract_close_history_from_bars(bars)
        revenue_hist = parse_history_pairs([{"end": "2026-01-02", "value": 100}])
        shares_hist = parse_history_pairs([{"end": "2026-01-01", "value": 10}])
        pct, obs = compute_historical_valuation_percentile(
            current_multiple=1.0,
            closes=closes,
            denominator_history=revenue_hist,
            shares_history=shares_hist,
            current_shares=10.0,
            window_days=365,
            min_observations=3,
        )
        self.assertEqual(obs, 1)
        self.assertIsNone(pct)


if __name__ == "__main__":
    unittest.main()
