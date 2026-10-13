"""SEC periodic selection, cache cold-write/hit and pending-streak tests.

No live SEC network calls.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ai_value_scanner.scanner import (
    RequestRateLimiter, SecClient, ScanConfig, load_one_fundamental,
    _submissions_latest_relevant_filing,
)
from refresh_sec_cache import record_pending_streaks, _pending_accession


class PeriodicGateParityTests(unittest.TestCase):
    def test_unsorted_rows_choose_latest_filed_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cik = "0000320193"
            rows = {"filings": {"recent": {
                "form": ["10-Q", "4", "10-K"],
                "filingDate": ["2026-07-30", "2026-10-08", "2026-08-20"],
                "accessionNumber": ["OLD", "OWNERSHIP", "NEW"],
            }}}
            (root / f"submissions_{cik}.json").write_text(json.dumps(rows))
            (root / f"facts_{cik}.json").write_text('{"facts":{}}')
            (root / f"facts_meta_{cik}.json").write_text(
                '{"covered_accession":"NEW","pending_accession":null}'
            )
            self.assertEqual(
                _submissions_latest_relevant_filing(root / f"submissions_{cik}.json"),
                ("2026-08-20", "NEW"),
            )
            session = MagicMock()
            sec = SecClient(session=session, user_agent="test", timeout_sec=3,
                            cache_dir=root, request_limiter=RequestRateLimiter(500))
            self.assertEqual(sec.get_companyfacts(cik), {"facts": {}})
            session.get.assert_not_called()

    def test_missing_date_fallback_and_amendment(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "submissions.json"
            path.write_text(json.dumps({"filings": {"recent": {
                "form": ["10-Q", "4"], "filingDate": ["", "2026-10-08"],
                "accessionNumber": ["NEW", "OWNERSHIP"],
            }}}))
            self.assertEqual(_submissions_latest_relevant_filing(path), ("", "NEW"))
            path.write_text(json.dumps({"filings": {"recent": {
                "form": ["10-Q", "10-Q/A", "4"],
                "filingDate": ["2026-07-30", "2026-08-01", "2026-10-08"],
                "accessionNumber": ["OLD", "AMENDED", "OWNERSHIP"],
            }}}))
            self.assertEqual(
                _submissions_latest_relevant_filing(path),
                ("2026-08-01", "AMENDED"),
            )


class PendingDateTests(unittest.TestCase):
    def test_consecutive_days_idempotent_and_reset(self):
        with tempfile.TemporaryDirectory() as td:
            processed = ["0001"]
            pending = {"0001": {"symbol": "AAA", "accession": "Q1"}}
            def record(day):
                return record_pending_streaks(
                    td, on_date=date.fromisoformat(day),
                    processed_ciks=processed, pending_ciks=pending,
                )
            self.assertEqual(record("2026-10-14"), [])
            self.assertEqual(record("2026-10-14"), [])
            self.assertEqual(record("2026-10-15"), [])
            self.assertEqual(record("2026-10-16")[0]["streak"], 3)
            pending["0001"]["accession"] = "Q2"
            self.assertEqual(record("2026-10-17"), [])
            saved = json.loads((Path(td) / "sec_pending_streaks.json").read_text())
            self.assertEqual(saved["items"]["0001"]["streak"], 1)

    def test_only_genuine_pending_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root, cik = Path(td), "0001"
            (root / f"submissions_{cik}.json").write_text(
                '{"filings":{"recent":{"form":["10-Q"],"filingDate":["2026-10-01"],"accessionNumber":["Q1"]}}}'
            )
            factsmeta = root / f"facts_meta_{cik}.json"
            factsmeta.write_text('{"pending_accession":"Q1","covered_accession":null}')
            self.assertEqual(_pending_accession(root, cik), "Q1")
            factsmeta.write_text('{"pending_accession":"Q1","covered_accession":"Q1"}')
            self.assertIsNone(_pending_accession(root, cik))
            factsmeta.write_text('{"pending_accession":"OTHER","covered_accession":null}')
            self.assertIsNone(_pending_accession(root, cik))



class ColdWriteHitTests(unittest.TestCase):
    def test_actual_parser_cold_write_then_same_policy_cache_hit(self):
        """The first load writes; the second must not call SEC raw readers."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cik = "0000320193"
            periodic = "PERIODIC-1"
            subs = {"filings": {"recent": {
                "form": ["4", "10-Q"],
                "filingDate": ["2026-10-08", "2026-07-30"],
                "accessionNumber": ["FORM4-2", periodic],
            }}}
            (root / f"submissions_{cik}.json").write_text(json.dumps(subs))
            (root / f"facts_{cik}.json").write_text('{"facts":{}}')
            (root / f"facts_meta_{cik}.json").write_text(
                json.dumps({"covered_accession": periodic, "pending_accession": None})
            )
            parsed = root / f"parsed_fund_{cik}.json"
            cfg = ScanConfig(cache_dir=td)

            class FakeSec:
                def __init__(self):
                    self.calls = []

                def ticker_map_snapshot(self):
                    self.calls.append("map")
                    return {"sha256": "stable-map"}

                def get_submissions(self, cik):
                    self.calls.append("submissions")
                    return subs

                def get_companyfacts(self, cik):
                    self.calls.append("facts")
                    return {"facts": {}}

            sec = FakeSec()
            self.assertFalse(parsed.exists())
            # Synthetic facts do not contain a financial accession. Suppress
            # the unrelated EdgarTools network fallback for this unit test.
            with patch(
                "ai_value_scanner.scanner.fetch_usd_10q_companyfacts_patch",
                return_value=SimpleNamespace(status="not_needed", used=False),
            ):
                first = load_one_fundamental(sec, "AAPL", cik, cfg)
            self.assertEqual(first["symbol"], "AAPL")
            self.assertTrue(parsed.exists(), "cold parse should write a parsed cache")
            meta = json.loads(parsed.read_text())["_cache_meta"]
            self.assertEqual(meta["latest_accession"], periodic)
            self.assertEqual(meta["facts_covered_accession"], periodic)
            self.assertIn("submissions", sec.calls)
            self.assertIn("facts", sec.calls)

            sec.calls.clear()
            second = load_one_fundamental(sec, "AAPL", cik, cfg)
            self.assertEqual(second["symbol"], "AAPL")
            self.assertEqual(second["fundamental_operating_entity_verified"],
                             first["fundamental_operating_entity_verified"])
            self.assertEqual(sec.calls, ["map"])


if __name__ == "__main__":
    unittest.main()
