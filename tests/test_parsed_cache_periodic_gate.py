"""Parsed-cache gate tracks the newest PERIODIC filing, not raw newest.

A Form 4 / S-3ASR filed after the last 10-Q carries no fundamental facts
and must not veto a cache whose periodic basis is unchanged (production
2026-10-13: AAPL stuck 'incomplete' behind a Form 4).
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import (  # noqa: E402
    PARSED_FUND_CACHE_VERSION,
    ScanConfig,
    _parsed_fund_cache_meta,
    _parsed_fund_config_fingerprint,
    load_one_fundamental,
)

CIK = "0000320193"
Q_ACCN = "0000320193-26-000020"
Q_DATE = "2026-07-30"
F4_ACCN = "0001140361-26-039158"
F4_DATE = "2026-10-08"


class FakeSec:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ticker_map_snapshot(self):
        self.calls.append("snapshot")
        return {"sha256": "testmap"}

    def get_submissions(self, cik: str):
        self.calls.append("submissions")
        return {
            "sic": "3571",
            "filings": {
                "recent": {
                    "form": ["4", "10-Q"],
                    "filingDate": [F4_DATE, Q_DATE],
                    "accessionNumber": [F4_ACCN, Q_ACCN],
                }
            },
        }

    def get_companyfacts(self, cik: str):
        self.calls.append("facts")
        return {"facts": {}}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(cache: Path, config: ScanConfig) -> None:
    (cache / f"submissions_{CIK}.json").write_text(json.dumps({
        "filings": {"recent": {
            "form": ["4", "10-Q"],
            "filingDate": [F4_DATE, Q_DATE],
            "accessionNumber": [F4_ACCN, Q_ACCN],
        }}
    }))
    (cache / f"facts_{CIK}.json").write_text(json.dumps({"facts": {}}))
    (cache / f"facts_meta_{CIK}.json").write_text(json.dumps(
        {"covered_accession": Q_ACCN, "pending_accession": None}))
    payload = {
        "symbol": "OLD",
        "revenue": 120.0,
        "fundamental_operating_entity_verified": True,
        "fundamental_operating_entity_detail": "test",
        "_cache_meta": {
            "v": PARSED_FUND_CACHE_VERSION,
            "cfg": _parsed_fund_config_fingerprint(config),
            "latest_filing": Q_DATE,
            "latest_accession": Q_ACCN,
            "facts_covered_accession": Q_ACCN,
            "ticker_map_sha": "testmap",
            "facts_content_sha": _sha(cache / f"facts_{CIK}.json"),
            "submissions_content_sha": _sha(cache / f"submissions_{CIK}.json"),
        },
    }
    (cache / f"parsed_fund_{CIK}.json").write_text(json.dumps(payload))


class PeriodicGateTests(unittest.TestCase):
    def test_newer_form4_does_not_veto_periodic_cache(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)
            config = ScanConfig(cache_dir=td)
            _seed(cache, config)
            sec = FakeSec()
            result = load_one_fundamental(sec, "AAPL", CIK, config)
            self.assertEqual(result["revenue"], 120.0)
            self.assertNotIn("_cache_meta", result)
            # Cache hit: no raw SEC fetch, only the ticker-map snapshot.
            self.assertEqual(sec.calls, ["snapshot"])

    def test_new_periodic_filing_still_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)
            config = ScanConfig(cache_dir=td)
            _seed(cache, config)
            # A newer 10-Q arrives: the cached periodic basis is now stale.
            (cache / f"submissions_{CIK}.json").write_text(json.dumps({
                "filings": {"recent": {
                    "form": ["10-Q", "4", "10-Q"],
                    "filingDate": ["2026-10-10", F4_DATE, Q_DATE],
                    "accessionNumber": ["0000320193-26-000031", F4_ACCN, Q_ACCN],
                }}
            }))
            sec = FakeSec()
            load_one_fundamental(sec, "AAPL", CIK, config)
            self.assertIn("submissions", sec.calls)
            self.assertIn("facts", sec.calls)

    def test_meta_builder_marks_periodic_basis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = ScanConfig(cache_dir=td)
            meta = _parsed_fund_cache_meta(config, Q_DATE, Q_ACCN, Q_ACCN)
            self.assertEqual(meta["latest_filing"], Q_DATE)
            self.assertEqual(meta["latest_accession"], Q_ACCN)


if __name__ == "__main__":
    unittest.main()
