"""Retry policy for the nightly SEC refresh (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_sec_cache import _circuit_pause_sec, _is_retryable, _load_with_retry


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    err = requests.HTTPError(f"{status} err")
    err.response = resp
    return err


class RetryPolicyTests(unittest.TestCase):
    def test_transient_statuses_retryable(self) -> None:
        for status in (403, 408, 429, 500, 502, 503, 504):
            self.assertTrue(_is_retryable(_http_error(status)), status)
        self.assertTrue(_is_retryable(requests.ConnectionError("x")))
        self.assertTrue(_is_retryable(requests.Timeout("x")))

    def test_data_bugs_fail_fast(self) -> None:
        self.assertFalse(_is_retryable(_http_error(404)))
        self.assertFalse(_is_retryable(ValueError("bad data")))
        self.assertFalse(_is_retryable(KeyError("k")))

    def test_retries_then_succeeds(self) -> None:
        calls: list[str] = []
        sleeps: list[float] = []

        def flaky(symbol, cik, cfg):
            calls.append(symbol)
            if len(calls) < 3:
                raise _http_error(403)
            return {"ok": True}

        ok, attempts = _load_with_retry(
            flaky, "AAA", "0001", None, sleep=sleeps.append)
        self.assertTrue(ok)
        self.assertEqual(attempts, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertLess(sleeps[0], sleeps[1])  # exponential growth

    def test_gives_up_after_max_attempts(self) -> None:
        calls: list[str] = []

        def down(symbol, cik, cfg):
            calls.append(symbol)
            raise _http_error(503)

        with self.assertRaises(requests.HTTPError):
            _load_with_retry(down, "AAA", "0001", None, sleep=lambda s: None)
        self.assertEqual(len(calls), 5)

    def test_non_retryable_raises_immediately(self) -> None:
        calls: list[str] = []

        def broken(symbol, cik, cfg):
            calls.append(symbol)
            raise ValueError("bad data")

        with self.assertRaises(ValueError):
            _load_with_retry(broken, "AAA", "0001", None, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_on_retry_hook_fires_per_retry(self) -> None:
        seen: list[str] = []

        def flaky(symbol, cik, cfg):
            if not seen:
                seen.append(symbol)
                raise _http_error(403)
            return {"ok": True}

        rotated: list[str] = []
        ok, attempts = _load_with_retry(
            flaky, "AAA", "0001", None, sleep=lambda s: None,
            on_retry=lambda exc: rotated.append(type(exc).__name__))
        self.assertTrue(ok)
        self.assertEqual(attempts, 2)
        self.assertEqual(rotated, ["HTTPError"])

    def test_on_retry_not_called_for_data_bugs(self) -> None:
        rotated: list[str] = []

        def broken(symbol, cik, cfg):
            raise ValueError("bad data")

        with self.assertRaises(ValueError):
            _load_with_retry(broken, "AAA", "0001", None,
                             sleep=lambda s: None,
                             on_retry=lambda exc: rotated.append("x"))
        self.assertEqual(rotated, [])

    def test_circuit_pause_escalates_with_cap(self) -> None:
        self.assertEqual(_circuit_pause_sec(0), 180.0)
        self.assertEqual(_circuit_pause_sec(1), 360.0)
        self.assertEqual(_circuit_pause_sec(2), 720.0)
        self.assertEqual(_circuit_pause_sec(99), 1800.0)


if __name__ == "__main__":
    unittest.main()
