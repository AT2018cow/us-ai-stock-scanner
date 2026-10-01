from __future__ import annotations

import unittest
from pathlib import Path

from ai_value_scanner.scanner import (
    AlpacaClient,
    RequestRateLimiter,
    apply_split_adjustment,
    build_session,
    price_dimension_from_bars,
)


def _bar(day: str, close: float, high: float | None = None, low: float | None = None, volume: float = 1_000_000.0) -> dict:
    return {
        "t": f"{day}T04:00:00Z",
        "o": close,
        "h": high if high is not None else close * 1.01,
        "l": low if low is not None else close * 0.99,
        "c": close,
        "v": volume,
    }


class TestApplySplitAdjustment(unittest.TestCase):
    def test_forward_split_makes_series_continuous(self) -> None:
        bars = [_bar(f"2026-01-{d:02d}", 1000.0) for d in range(1, 6)]
        bars += [_bar(f"2026-01-{d:02d}", 100.0) for d in range(11, 16)]
        events = [("2026-01-10", 0.1)]
        out = apply_split_adjustment(bars, events)
        closes = [b["c"] for b in out]
        self.assertTrue(all(abs(c - 100.0) < 1e-9 for c in closes[:5]))
        self.assertTrue(all(abs(c - 100.0) < 1e-9 for c in closes[5:]))
        # volume scaled inversely so dollar volume is invariant (10x here)
        self.assertAlmostEqual(out[0]["v"], bars[0]["v"] / 0.1, places=6)
        self.assertEqual(out[-1]["c"], bars[-1]["c"])

    def test_reverse_split(self) -> None:
        bars = [_bar("2026-02-02", 10.0), _bar("2026-02-03", 40.0)]
        out = apply_split_adjustment(bars, [("2026-02-03", 4.0)])
        self.assertAlmostEqual(out[0]["c"], 40.0)
        self.assertAlmostEqual(out[1]["c"], 40.0)

    def test_multiple_splits_cumulative(self) -> None:
        bars = [
            _bar("2026-01-02", 1000.0),
            _bar("2026-02-02", 100.0),
            _bar("2026-03-02", 50.0),
        ]
        events = [("2026-02-02", 0.1), ("2026-03-02", 0.5)]
        out = apply_split_adjustment(bars, events)
        # first bar crosses both splits: 1000 * 0.1 * 0.5 = 50
        self.assertAlmostEqual(out[0]["c"], 50.0)
        # second bar crosses only the second split: 100 * 0.5 = 50
        self.assertAlmostEqual(out[1]["c"], 50.0)
        self.assertAlmostEqual(out[2]["c"], 50.0)

    def test_no_events_returns_input_unchanged(self) -> None:
        bars = [_bar("2026-01-02", 42.0)]
        self.assertIs(apply_split_adjustment(bars, None), bars)
        self.assertIs(apply_split_adjustment(bars, []), bars)

    def test_dollar_volume_invariance(self) -> None:
        # >= 20 bars so avg_dollar_volume_20d is actually computed
        bars = [_bar(f"2026-01-{d:02d}", 1000.0, volume=1_000.0) for d in range(1, 11)]
        bars += [_bar(f"2026-01-{d:02d}", 100.0, volume=10_000.0) for d in range(11, 25)]
        out = apply_split_adjustment(bars, [("2026-01-10", 0.1)])
        dims_raw = price_dimension_from_bars(100.0, bars)
        dims_adj = price_dimension_from_bars(100.0, out)
        self.assertIsNotNone(dims_raw["avg_dollar_volume_20d"])
        self.assertIsNotNone(dims_adj["avg_dollar_volume_20d"])
        self.assertAlmostEqual(
            dims_raw["avg_dollar_volume_20d"], dims_adj["avg_dollar_volume_20d"], places=4
        )
        # adjusted volume is scaled inversely to price (10x here)
        self.assertAlmostEqual(out[0]["v"], bars[0]["v"] / 0.1, places=6)
        # post-split bars pass through untouched
        self.assertAlmostEqual(out[-1]["v"], bars[-1]["v"], places=6)

    def test_price_dimensions_split_corrected(self) -> None:
        # NFLX-style: pre-split raw high 1266, 10:1 split, last close 69.25.
        bars = [_bar("2026-01-05", 1200.0, high=1266.01, low=1190.0, volume=500_000.0)]
        bars += [_bar("2026-02-20", 69.25, high=70.0, low=68.0, volume=5_000_000.0)]
        split_bars = apply_split_adjustment(bars, [("2026-01-10", 0.1)])
        raw_dims = price_dimension_from_bars(69.25, bars)
        adj_dims = price_dimension_from_bars(69.25, split_bars)
        # raw drawdown is the corrupted 94.5%-style figure
        self.assertGreater(raw_dims["drawdown_from_52w_high"], 0.9)
        # adjusted drawdown is the honest ~45%
        self.assertAlmostEqual(adj_dims["drawdown_from_52w_high"], 1 - 69.25 / 126.601, places=3)
        # range position recovers from a fake ~0.001 to a sane (higher) value
        self.assertGreater(adj_dims["range_position_52w"], raw_dims["range_position_52w"] * 10)


class TestGetCorporateActionSplits(unittest.TestCase):
    def _client(self, root: Path, payload: dict) -> tuple[AlpacaClient, list]:
        calls: list = []

        class FakeResponse:
            status_code = 200

            def __init__(self, data: dict) -> None:
                self._data = data

            def json(self) -> dict:
                return self._data

            def raise_for_status(self) -> None:
                return None

        class FakeSession:
            def get(self, url, headers=None, params=None, timeout=None):  # noqa: ANN001
                calls.append(params)
                return FakeResponse(payload)

        client = AlpacaClient(
            session=FakeSession(),
            api_endpoint="https://paper-api.alpaca.markets",
            data_endpoint="https://data.alpaca.markets",
            api_key="k",
            api_secret="s",
            feed="iex",
            timeout_sec=10,
            request_limiter=RequestRateLimiter(1000.0),
            cache_dir=root,
            cache_enabled=True,
            cache_ttl_assets_sec=3600,
            cache_ttl_snapshots_sec=3600,
            cache_ttl_bars_sec=3600,
            monitor=None,
        )
        return client, calls

    def test_parses_forward_and_reverse_splits(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "corporate_actions": {
                    "forward_splits": [
                        {"symbol": "NFLX", "ex_date": "2025-11-17", "old_rate": 1, "new_rate": 10},
                        {"symbol": "BAD", "ex_date": "2025-11-17", "old_rate": None, "new_rate": 10},
                    ],
                    "reverse_splits": [
                        {"symbol": "MQ", "ex_date": "2026-07-01", "old_rate": 4, "new_rate": 1},
                    ],
                },
                "next_page_token": None,
            }
            client, calls = self._client(Path(tmp), payload)
            events = client.get_corporate_action_splits(["nflx", "mq", "bad"], "2025-08-05")
            self.assertEqual(events["NFLX"], [("2025-11-17", 0.1)])
            self.assertEqual(events["MQ"], [("2026-07-01", 4.0)])
            self.assertNotIn("BAD", events)
            self.assertEqual(calls[0]["types"], "forward_split,reverse_split")
            self.assertEqual(calls[0]["start"], "2025-08-05")

    def test_empty_symbols_short_circuits(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, calls = self._client(Path(tmp), {"corporate_actions": {}})
            self.assertEqual(client.get_corporate_action_splits([], "2025-08-05"), {})
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
