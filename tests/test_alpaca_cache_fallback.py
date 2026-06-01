from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.scanner import AlpacaClient, RequestRateLimiter, build_session


class TestAlpacaBarsCacheFallback(unittest.TestCase):
    def _make_client(self, root: Path) -> AlpacaClient:
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
            cache_ttl_bars_sec=3600,
            monitor=None,
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
