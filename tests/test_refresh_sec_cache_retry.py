"""Client cron SEC prewarm: pure retry logic and cache handoff (no network)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_sec_cache import (
    MAX_CONSECUTIVE_FAILURES,
    SecThrottleCircuitOpen,
    _is_retryable,
    _load_with_retry,
    collect_symbols,
    refresh_symbols,
)


def http_error(status: int, retry_after: str | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    error = requests.HTTPError(f"HTTP {status}")
    error.response = response
    return error


class RetryPolicyTests(unittest.TestCase):
    def test_retryable_statuses_and_transport(self) -> None:
        for status in (403, 408, 429, 500, 502, 503, 504):
            self.assertTrue(_is_retryable(http_error(status)), status)
        for status in (400, 401, 404, 422):
            self.assertFalse(_is_retryable(http_error(status)), status)
        self.assertTrue(_is_retryable(requests.ConnectionError("x")))
        self.assertTrue(_is_retryable(requests.Timeout("x")))
        self.assertFalse(_is_retryable(ValueError("bad data")))

    def test_transport_retries_and_rotates(self) -> None:
        attempts, rotations, sleeps = [], [], []

        def flaky(symbol, cik, cfg):
            attempts.append(cik)
            if len(attempts) < 3:
                raise requests.ConnectionError("broken socket")

        ok, n = _load_with_retry(
            flaky, "AAA", "1", None,
            sleep=sleeps.append, on_retry=lambda exc: rotations.append(exc),
        )
        self.assertTrue(ok)
        self.assertEqual(n, 3)
        self.assertEqual(len(rotations), 2)
        self.assertEqual(len(sleeps), 2)
        self.assertGreaterEqual(sleeps[0], 5)
        self.assertGreaterEqual(sleeps[1], 15)

    def test_transport_stops_after_three_attempts(self) -> None:
        attempts = []

        def broken(symbol, cik, cfg):
            attempts.append(cik)
            raise requests.Timeout("timed out")

        with self.assertRaises(requests.Timeout):
            _load_with_retry(broken, "AAA", "1", None, sleep=lambda _: None)
        self.assertEqual(len(attempts), 3)

    def test_http_5xx_retry_does_not_rotate(self) -> None:
        calls, rotations = [], []

        def intermittent(symbol, cik, cfg):
            calls.append(cik)
            if len(calls) == 1:
                raise http_error(503)

        self.assertEqual(
            _load_with_retry(
                intermittent, "AAA", "1", None, sleep=lambda _: None,
                on_retry=lambda exc: rotations.append(exc),
            ),
            (True, 2),
        )
        self.assertFalse(rotations)

    def test_http_403_global_cooldown_then_abort_without_rotation(self) -> None:
        calls, sleeps, rotations = [], [], []

        def blocked(symbol, cik, cfg):
            calls.append(cik)
            raise http_error(403)

        with self.assertRaises(SecThrottleCircuitOpen):
            _load_with_retry(
                blocked, "AAA", "1", None, sleep=sleeps.append,
                on_retry=lambda exc: rotations.append(exc),
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [180.0])
        self.assertEqual(rotations, [])

    def test_http_429_retry_after_observed(self) -> None:
        calls, sleeps = [], []

        def throttled_once(symbol, cik, cfg):
            calls.append(cik)
            if len(calls) == 1:
                raise http_error(429, "275")

        ok, n = _load_with_retry(
            throttled_once, "AAA", "1", None, sleep=sleeps.append,
        )
        self.assertTrue(ok)
        self.assertEqual(n, 2)
        self.assertEqual(sleeps, [275.0])

    def test_retry_after_oversized_or_unparseable_fails_closed(self) -> None:
        for delay in ("7200", "Wed, 21 Oct 2026 07:28:00 GMT"):
            with self.subTest(delay=delay):
                calls, sleeps = [], []

                def throttled(symbol, cik, cfg):
                    calls.append(cik)
                    raise http_error(429, delay)

                with self.assertRaises(SecThrottleCircuitOpen):
                    _load_with_retry(throttled, "AAA", "1", None, sleep=sleeps.append)
                self.assertEqual(len(calls), 1)
                self.assertEqual(sleeps, [])

    def test_non_retryable_data_error_fails_fast(self) -> None:
        calls, rotates = [], []

        def bad(symbol, cik, cfg):
            calls.append(cik)
            raise KeyError("financial-data bug")

        with self.assertRaises(KeyError):
            _load_with_retry(
                bad, "AAA", "1", None, sleep=lambda _: None,
                on_retry=lambda exc: rotates.append(exc),
            )
        self.assertEqual(calls, ["1"])
        self.assertFalse(rotates)


class RefreshHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = SimpleNamespace(cache_dir=str(self.root))
        self.sec = SimpleNamespace(
            session=MagicMock(),
            request_limiter=object(),
            _ticker_map_memo={"sha": "frozen-map"},
        )

    def test_old_parsed_file_is_preserved_when_refresh_fails(self) -> None:
        parsed = self.root / "parsed_fund_0001.json"
        parsed.write_text('{"valid_before":true}')
        original = parsed.read_bytes()

        def broken(sec, symbol, cik, cfg, *, force_refresh_parsed=False):
            self.assertTrue(force_refresh_parsed)
            self.assertTrue(parsed.exists(), "old parsed file must not be unlinked")
            raise ValueError("SEC JSON invalid")

        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", return_value=None), \
             patch("refresh_sec_cache.load_one_fundamental", side_effect=broken):
            result = refresh_symbols(
                ["AAA"], {"AAA": "0001"}, self.sec, self.cfg,
                max_age_sec=72000, sleep=lambda _: None,
            )
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["refreshed"], 0)
        self.assertEqual(parsed.read_bytes(), original)

    def test_loader_return_without_eligible_cache_is_incomplete(self) -> None:
        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", return_value=None), \
             patch("refresh_sec_cache.load_one_fundamental", return_value={"symbol": "AAA"}) as loader:
            result = refresh_symbols(
                ["AAA"], {"AAA": "0001"}, self.sec, self.cfg,
                max_age_sec=72000, sleep=lambda _: None,
            )
        self.assertEqual(result["incomplete"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["refreshed"], 0)
        self.assertTrue(loader.call_args.kwargs["force_refresh_parsed"])

    def test_only_valid_versioned_cache_skips_work(self) -> None:
        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", return_value={"symbol": "AAA"}) as valid, \
             patch("refresh_sec_cache.load_one_fundamental") as loader:
            result = refresh_symbols(
                ["AAA"], {"AAA": "0001"}, self.sec, self.cfg, max_age_sec=72000,
            )
        self.assertEqual(result["skipped_valid"], 1)
        self.assertEqual(result["failed"], 0)
        loader.assert_not_called()
        self.assertEqual(valid.call_args.kwargs["max_age_sec"], 72000)

    def test_success_must_be_verified_after_writing(self) -> None:
        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", side_effect=[None, {"symbol": "AAA"}]) as valid, \
             patch("refresh_sec_cache.load_one_fundamental", return_value={"symbol": "AAA"}) as loader:
            result = refresh_symbols(
                ["AAA"], {"AAA": "0001"}, self.sec, self.cfg, max_age_sec=72000,
            )
        self.assertEqual(valid.call_count, 2)
        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(loader.call_args.kwargs["force_refresh_parsed"])

    def test_throttle_aborts_before_next_symbol(self) -> None:
        calls = []

        def denied(sec, symbol, cik, cfg, *, force_refresh_parsed):
            calls.append(symbol)
            raise http_error(403)

        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", return_value=None), \
             patch("refresh_sec_cache.load_one_fundamental", side_effect=denied):
            result = refresh_symbols(
                ["AAA", "BBB"], {"AAA": "0001", "BBB": "0002"}, self.sec,
                self.cfg, max_age_sec=72000, sleep=lambda _: None,
            )
        self.assertEqual(calls, ["AAA", "AAA"])
        self.assertTrue(result["aborted"])
        self.assertEqual(result["failed"], 1)
        self.sec.session.close.assert_not_called()

    def test_transient_rotates_same_client_and_shared_limiter(self) -> None:
        original_limiter = self.sec.request_limiter
        same_client = []
        n = 0

        def flaky(sec, symbol, cik, cfg, *, force_refresh_parsed):
            nonlocal n
            same_client.append(sec)
            n += 1
            if n == 1:
                raise requests.ConnectionError("reset")

        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", side_effect=[None, {"symbol": "AAA"}]), \
             patch("refresh_sec_cache.load_one_fundamental", side_effect=flaky):
            result = refresh_symbols(
                ["AAA"], {"AAA": "0001"}, self.sec, self.cfg,
                max_age_sec=72000, sleep=lambda _: None,
            )
        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(result["retried_ok"], 1)
        self.assertTrue(all(s is self.sec for s in same_client))
        self.assertIs(self.sec.request_limiter, original_limiter)
        self.assertEqual(self.sec._ticker_map_memo, {"sha": "frozen-map"})

    def test_five_consecutive_failures_stop_job(self) -> None:
        calls = []

        def fail(sec, symbol, cik, cfg, *, force_refresh_parsed):
            calls.append(symbol)
            raise ValueError("bad data")

        symbols = [f"A{i}" for i in range(MAX_CONSECUTIVE_FAILURES + 2)]
        with patch("refresh_sec_cache.load_valid_parsed_fundamental_cache", return_value=None), \
             patch("refresh_sec_cache.load_one_fundamental", side_effect=fail):
            result = refresh_symbols(
                symbols, {s: str(i) for i, s in enumerate(symbols)}, self.sec,
                self.cfg, max_age_sec=72000,
            )
        self.assertTrue(result["aborted"])
        self.assertEqual(result["failed"], MAX_CONSECUTIVE_FAILURES)
        self.assertEqual(len(calls), MAX_CONSECUTIVE_FAILURES)

    def test_configured_manual_and_core_sources_are_included(self) -> None:
        data = self.root / "data"
        data.mkdir()
        (data / "ai_watchlist.csv").write_text("symbol\nAAPL\n")
        (data / "manual.csv").write_text("symbol\nMSFT\n")
        (data / "core.csv").write_text("symbol\nNVDA\n")
        config = SimpleNamespace(
            watchlist_csv_path="data/ai_watchlist.csv",
            discovery_source_files={
                "us_core": "data/core.csv", "manual": "data/manual.csv",
            },
        )
        symbols, paths = collect_symbols(self.root, config)
        self.assertEqual(symbols, ["AAPL", "MSFT", "NVDA"])
        self.assertEqual(len(paths), 3)


class CronEntrypointTests(unittest.TestCase):
    def test_missing_sec_user_agent_fails_before_network(self) -> None:
        import refresh_sec_cache

        with patch.dict(os.environ, {"SEC_USER_AGENT": ""}), \
             patch("refresh_sec_cache.load_dotenv"), \
             patch("sys.argv", ["refresh_sec_cache.py"]), \
             patch("refresh_sec_cache.SecClient") as client:
            with self.assertRaises(SystemExit) as caught:
                refresh_sec_cache.main()
        self.assertEqual(caught.exception.code, 2)
        client.assert_not_called()

    def test_partial_failure_exits_nonzero(self) -> None:
        import refresh_sec_cache

        client = MagicMock()
        client.ticker_map_snapshot.return_value = {
            "frame": __import__("pandas").DataFrame(
                [{"symbol": "AAA", "cik": "0001"}]
            ),
            "conflicts": {},
        }
        cfg = SimpleNamespace(
            sec_cache_ttl_submissions_sec=86400,
            request_timeout_sec=20, cache_dir="cache",
            sec_max_requests_per_sec=5,
        )
        partial = {
            "refreshed": 1, "skipped_valid": 0,
            "no_cik": [], "conflicted": [], "failed": 1,
            "incomplete": 1, "retried_ok": 0, "aborted": False,
        }
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Bot contact@example.org"}), \
             patch("refresh_sec_cache.load_dotenv"), \
             patch("refresh_sec_cache.load_config", return_value=cfg), \
             patch("refresh_sec_cache.SecClient", return_value=client), \
             patch("refresh_sec_cache.collect_symbols", return_value=(["AAA"], ["a.csv"])), \
             patch("refresh_sec_cache.refresh_symbols", return_value=partial), \
             patch("sys.argv", ["refresh_sec_cache.py"]):
            with self.assertRaises(SystemExit) as caught:
                refresh_sec_cache.main()
        self.assertEqual(caught.exception.code, 1)
        client.session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
