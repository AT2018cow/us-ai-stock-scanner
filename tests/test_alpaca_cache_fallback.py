from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.scanner import (
    AlpacaClient,
    NetworkMonitor,
    RequestRateLimiter,
    build_session,
)


class TestAlpacaBarsCacheFallback(unittest.TestCase):
    def _make_client(
        self,
        root: Path,
        *,
        monitor: NetworkMonitor | None = None,
        bars_ttl_sec: int = 3600,
    ) -> AlpacaClient:
        return AlpacaClient(
            session=build_session(),
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
            cache_ttl_bars_sec=bars_ttl_sec,
            monitor=monitor,
        )

    def test_any_cache_prefers_more_complete_symbol_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._make_client(Path(tmp))
            cache_dir = client.cache_dir

            # Short/incomplete cache appears first lexicographically.
            (cache_dir / "bars_a.json").write_text(
                json.dumps(
                    {
                        "ABC": [
                            {"t": "2026-01-02T00:00:00Z", "o": 10.0, "c": 10.0},
                        ]
                    }
                )
            )
            (cache_dir / "bars_b.json").write_text(
                json.dumps(
                    {
                        "ABC": [
                            {"t": "2024-01-02T00:00:00Z", "o": 8.0, "c": 8.0},
                            {"t": "2026-01-02T00:00:00Z", "o": 10.0, "c": 10.0},
                        ]
                    }
                )
            )

            out = client._load_bars_from_any_cache(["ABC"], "2024-01-01T00:00:00Z")
            self.assertIn("ABC", out)
            self.assertEqual(len(out["ABC"]), 2)
            self.assertEqual(out["ABC"][0]["t"], "2024-01-02T00:00:00Z")

    def test_stale_bars_fallback_preserves_original_cache_age_and_reports_provenance(self) -> None:
        import os
        import time
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            monitor = NetworkMonitor()
            client = self._make_client(
                Path(tmp),
                monitor=monitor,
                bars_ttl_sec=1,
            )
            start_iso = "2024-01-01T00:00:00Z"
            symbols = ["ABC"]
            key = {
                "data_endpoint": client.data_endpoint,
                "feed": client.feed,
                "start": start_iso,
                "symbols": sorted(symbols),
            }
            client._save_cache(
                "bars",
                key,
                {"ABC": [{"t": "2024-01-02T00:00:00Z", "o": 8.0, "c": 8.0}]},
            )
            path = client._cache_file("bars", key)
            stale_mtime = time.time() - 7200
            os.utime(path, (stale_mtime, stale_mtime))

            with mock.patch.object(client, "_get", side_effect=RuntimeError("network down")):
                out = client.get_daily_bars(symbols, start_iso=start_iso, chunk_size=100)

            self.assertIn("ABC", out)
            self.assertAlmostEqual(path.stat().st_mtime, stale_mtime, delta=1.0)
            report = monitor.to_dict()
            self.assertTrue(report["stale_market_data_fallback_used"])
            bars = report["data_provenance"]["alpaca"]["bars"]
            self.assertEqual(bars["counts"].get("stale_cache_fallback"), 1)
            self.assertGreater(float(bars["max_cache_age_sec"]), 7000.0)

    def test_fresh_cache_provenance_is_not_marked_stale(self) -> None:
        monitor = NetworkMonitor()
        with tempfile.TemporaryDirectory() as tmp:
            client = self._make_client(Path(tmp), monitor=monitor)
            key = {
                "data_endpoint": client.data_endpoint,
                "feed": client.feed,
                "symbols": ["ABC"],
            }
            client._save_cache("snapshots", key, {"ABC": {"latestTrade": {"p": 10.0}}})
            out = client.get_snapshots(["ABC"], chunk_size=100)
            self.assertIn("ABC", out)
            report = monitor.to_dict()
            self.assertFalse(report["stale_market_data_fallback_used"])
            snap = report["data_provenance"]["alpaca"]["snapshots"]
            self.assertEqual(snap["counts"].get("fresh_cache"), 1)

    def test_get_daily_bars_enriches_short_exact_cache_from_any_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._make_client(Path(tmp))
            cache_dir = client.cache_dir
            start_iso = "2024-01-01T00:00:00Z"
            symbols = ["ABC"]
            key = {
                "data_endpoint": client.data_endpoint,
                "feed": client.feed,
                "start": start_iso,
                "symbols": sorted(symbols),
            }

            # Exact-key cache contains only a short late history.
            client._save_cache(
                "bars",
                key,
                {
                    "ABC": [
                        {"t": "2026-01-02T00:00:00Z", "o": 10.0, "c": 10.0},
                    ]
                },
            )
            # Any-cache file has broader history for the same symbol.
            (cache_dir / "bars_extra.json").write_text(
                json.dumps(
                    {
                        "ABC": [
                            {"t": "2024-01-02T00:00:00Z", "o": 8.0, "c": 8.0},
                            {"t": "2026-01-02T00:00:00Z", "o": 10.0, "c": 10.0},
                        ]
                    }
                )
            )

            out = client.get_daily_bars(symbols, start_iso=start_iso, chunk_size=100)
            self.assertIn("ABC", out)
            self.assertEqual(len(out["ABC"]), 2)
            self.assertEqual(out["ABC"][0]["t"], "2024-01-02T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
