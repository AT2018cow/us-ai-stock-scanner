"""Official publication readback, using only temporary snapshots."""
from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ai_value_scanner.decision import build_stock_decisions
from ai_value_scanner.market_data import official_eod_window, sip_publication_window
from ai_value_scanner.reporting.publication import latest_list_status, write_publication_attempt
from ai_value_scanner.reporting.snapshot import write_decision_snapshot
from ai_value_scanner.scanner import write_latest_decision_pointer
from ai_value_scanner.validation.decision_snapshot import validate_snapshot


def clock(token: str) -> datetime:
    return datetime.fromisoformat(token).replace(tzinfo=timezone.utc)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def _snapshot(self, day, *, mode="sip_eod", feed="sip", validate=False):
        provenance = {"market_data_mode": mode, "market_data_feed": feed}
        decisions = build_stock_decisions(
            pd.DataFrame([{"symbol": "AAA", "market_asof": day}]),
            decision_date=day, generated_at_utc=f"{day}T23:00:00+00:00",
            run_provenance=provenance, policy_version="v2",
        )
        return write_decision_snapshot(
            output_root=self.root, strategy_style="production", decisions=decisions,
            daily_attention=decisions, weekly_attention=decisions, decision_date=day,
            generated_at_utc=f"{day}T23:00:00+00:00", config_fingerprint="test",
            code_sha="fixture", input_provenance=provenance, policy_version="v2",
            layout_version="v2", validate_attention_cap=15 if validate else None,
        )

    def _publish(self, day):
        return write_latest_decision_pointer(self.root, decision_date=day, strategy_style="production")

    def _status(self, when):
        return latest_list_status(self.root, "production", clock(when))

    def test_calendar_window_uses_previous_session_during_market_and_holiday(self):
        self._snapshot("2026-11-25")
        self._publish("2026-11-25")
        for when in ("2026-11-26T21:30:00", "2026-11-27T17:00:00"):
            with self.subTest(when=when):
                self.assertEqual(self._status(when)["status"], "current")
        self.assertEqual(self._status("2026-11-27T18:19:59")["status"], "awaiting_sip")
        self.assertEqual(self._status("2026-11-27T18:20:00")["status"], "overdue")

    def test_calendar_dst_and_utc_rollover(self):
        for when, expected, phase in (
            ("2026-11-02T20:00:00", "2026-10-30", "market_open"),
            ("2026-11-02T21:19:59", "2026-11-02", "awaiting_sip"),
            ("2026-11-03T01:00:00", "2026-11-02", "available"),
            ("2026-10-30T20:20:00", "2026-10-30", "available"),
        ):
            with self.subTest(when=when):
                now = clock(when)
                day, window = sip_publication_window(now)
                self.assertEqual((str(day), window), (expected, phase))
                if phase == "available":
                    self.assertEqual(official_eod_window(now)[0], day)
                else:
                    with self.assertRaises(ValueError):
                        official_eod_window(now)

    def test_concurrent_publication_preserves_first_timestamp(self):
        self._snapshot("2026-11-23")
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(self._publish, "2026-11-23")
            b = pool.submit(self._publish, "2026-11-23")
            path = a.result()
            self.assertEqual(path, b.result())
        before = json.loads(path.read_bytes())
        self.assertIsNotNone(before["first_readable_at_utc"])
        self._publish("2026-11-23")
        self.assertEqual(json.loads(path.read_bytes()), before)

    def test_legacy_first_publication_time_stays_unknown(self):
        self._snapshot("2026-11-23")
        path = self._publish("2026-11-23")
        legacy = json.loads(path.read_bytes())
        legacy.pop("first_readable_at_utc")
        legacy.pop("manifest_sha256")
        path.write_text(json.dumps(legacy))
        self._publish("2026-11-23")
        result = self._status("2026-11-24T03:00:00")
        self.assertEqual(result["status"], "current")
        self.assertIsNone(result["first_readable_at_utc"])

    def test_bad_manifest_cannot_be_treated_as_current_or_republished(self):
        snapshot = self._snapshot("2026-11-23")
        self._publish("2026-11-23")
        manifest = snapshot.run_manifest_json
        manifest.write_text(manifest.read_text() + "\n")
        self.assertEqual(self._status("2026-11-24T03:00:00")["status"], "invalid")
        with self.assertRaisesRegex(ValueError, "manifest SHA256 changed"):
            self._publish("2026-11-23")

    def test_stale_readback_reports_current_session_failure(self):
        self._snapshot("2026-11-23")
        self._publish("2026-11-23")
        path = self.root / "publication_attempts" / "production" / "formal" / "1.json"
        write_publication_attempt(path, {"expected_session": "2026-11-24", "status": "running"})
        now = "2026-11-24T21:30:00"
        self.assertEqual(self._status(now)["reason_code"], "unfinished_publication_attempt")
        write_publication_attempt(path, {
            "expected_session": "2026-11-24", "status": "failed",
            "reason_code": "missing_alpaca_credentials",
        })
        result = self._status(now)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_code"], "missing_alpaca_credentials")
        self.assertEqual(result["published_session"], "2026-11-23")

    def test_render_validation_failure_allows_same_session_retry(self):
        with patch("ai_value_scanner.reporting.snapshot.render_detailed_report", return_value="broken"):
            with self.assertRaisesRegex(ValueError, "official snapshot failed validation"):
                self._snapshot("2026-11-23", validate=True)
        for path in self.root.glob("2026-11-23/*"):
            self.fail(f"Rejected staging left {path}")
        self._snapshot("2026-11-23", validate=True)
        self._publish("2026-11-23")
        self.assertEqual(self._status("2026-11-24T03:00:00")["status"], "current")

    def test_frozen_streaks_survive_archive_backfill(self):
        self._snapshot("2026-11-19")
        current = self._snapshot("2026-11-23", validate=True)
        self._publish("2026-11-23")
        self._snapshot("2026-11-20")
        manifest = json.loads(current.run_manifest_json.read_text())
        self.assertEqual(manifest["in_list_streaks"], {"AAA": 2})
        self.assertEqual(self._status("2026-11-24T03:00:00")["status"], "current")
        manifest.pop("in_list_streaks")
        current.run_manifest_json.write_text(json.dumps(manifest))
        legacy_result = validate_snapshot(current.root)
        self.assertTrue(legacy_result["ok"], legacy_result["errors"])

    def test_missing_detail_fails_readback_with_unchanged_manifest(self):
        snapshot = self._snapshot("2026-11-23")
        self._publish("2026-11-23")
        (snapshot.detailed_dir / "AAA.md").unlink()
        result = self._status("2026-11-24T03:00:00")
        self.assertEqual(result["status"], "invalid")
        self.assertIn("missing detailed report", result["error"])

    def test_same_date_non_sip_snapshot_is_not_current(self):
        self._snapshot("2026-11-23", mode="snapshot", feed="iex")
        self._publish("2026-11-23")
        result = self._status("2026-11-24T03:00:00")
        self.assertEqual(result["status"], "invalid")
        self.assertIn("SIP end-of-day provenance", result["error"])


if __name__ == "__main__":
    unittest.main()
