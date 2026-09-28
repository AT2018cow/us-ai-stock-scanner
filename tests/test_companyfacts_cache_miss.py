"""Regression test: get_companyfacts MUST fetch when the cache file is
missing.

Bug found 2026-09-28 via the biotech theme scan: the incremental-update
refactor (62fce89) accidentally dropped the cache-miss branch — for any
CIK without a cached facts file the function silently returned None
without a single network request. Consequences: every newly-added
watchlist company (and every new theme name) got market_cap=NaN and died
at the market_cap_notna hard gate (biotech: 51/53 names eliminated,
first-fail concentration 96%). Latent for the AI universe only because
the production watchlist predates the refactor — the next watchlist
refresh would have hit it too.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import SecClient  # noqa: E402


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _make_client(tmp: Path, responses: dict[str, _FakeResp]) -> tuple[SecClient, list[str]]:
    """SecClient with a stubbed _get that records requested URLs."""
    client = SecClient.__new__(SecClient)
    client.cache_dir = tmp
    client.timeout_sec = 5
    client.headers = {"User-Agent": "test"}
    client.submissions_ttl_sec = 0
    client.monitor = None
    requested: list[str] = []

    def fake_get(url: str):
        requested.append(url)
        if url in responses:
            return responses[url]
        return _FakeResp(404, {})

    client._get = fake_get  # type: ignore[assignment]
    return client, requested


class CompanyFactsCacheMissTest(unittest.TestCase):
    def test_missing_cache_file_triggers_fetch_and_caches(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = {"cik": 1, "facts": {"us-gaap": {"Revenues": {"units": {"USD": []}}}}}
            url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
            client, requested = _make_client(tmp, {url: _FakeResp(200, payload)})
            out = client.get_companyfacts("0000000001")
            self.assertEqual(requested, [url], "缓存缺失时必须发起抓取")
            self.assertIn("us-gaap", out.get("facts", {}))
            cached = json.loads((tmp / "facts_0000000001.json").read_text())
            self.assertIn("us-gaap", cached["facts"])

    def test_existing_cache_no_new_filing_uses_cache(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # 缓存文件 mtime=now，submissions 的最新 filing 比它旧 → 不抓
            (tmp / "facts_0000000002.json").write_text(json.dumps({"facts": {}}))
            recent = {"filings": {"recent": {"filingDate": ["2020-01-01"]}}}
            (tmp / "submissions_0000000002.json").write_text(json.dumps(recent))
            url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json"
            client, requested = _make_client(tmp, {url: _FakeResp(200, {"facts": {"new": True}})})
            out = client.get_companyfacts("0000000002")
            self.assertEqual(requested, [], "无新 filing 时必须命中缓存、不抓取")
            self.assertEqual(out, {"facts": {}})

    def test_existing_cache_new_filing_refetches(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            facts_path = tmp / "facts_0000000003.json"
            # mtime 设为很旧（pandas Timestamp(0)），submissions 有新 filing → 必须重抓
            facts_path.write_text(json.dumps({"facts": {"old": True}}))
            import os
            os.utime(facts_path, (0, 0))
            recent = {"filings": {"recent": {"filingDate": ["2026-01-01"]}}}
            (tmp / "submissions_0000000003.json").write_text(json.dumps(recent))
            url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000003.json"
            client, requested = _make_client(tmp, {url: _FakeResp(200, {"facts": {"fresh": True}})})
            out = client.get_companyfacts("0000000003")
            self.assertEqual(requested, [url], "新 filing 晚于缓存 mtime 时必须重抓")
            self.assertEqual(out["facts"], {"fresh": True})


if __name__ == "__main__":
    unittest.main()
