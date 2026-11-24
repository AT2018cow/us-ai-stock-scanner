from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from ai_value_scanner.decision.model import (
    DECISION_SCHEMA_VERSION, ActionState, EntryDecision, EntryState, QualityDecision,
    QualityGrade, StockDecision,
)
from ai_value_scanner.forward import ledger as ledger_module
from ai_value_scanner.forward.ledger import Ledger, evidence_id, file_sha, utc
from ai_value_scanner.forward.study import (
    freeze_protocol, record_exit, record_fill, record_outcome, record_paper, record_review, record_setup, study_summary,
)
from ai_value_scanner.reporting.snapshot import REPORT_RENDERER_REVISION, write_decision_snapshot


def stamp(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def at(day, hour):
    return stamp(day + "T" + hour + ":00+00:00")


def build_archive(root, session, *, config="config-fixture"):
    generated = at(session, "22:00")
    decisions = []
    for rank, symbol in enumerate(("AAA", "BBB", "CCC"), start=1):
        decisions.append(StockDecision(
            DECISION_SCHEMA_VERSION, symbol, symbol, session, generated.isoformat(),
            QualityDecision(QualityGrade.A, .80, .90, {}, (), (), (), session),
            EntryDecision(EntryState.ENTRY_READY, .85, .90, (), (), session),
            ActionState.PRIORITY_REVIEW, rank, (), None, (),
            {"cik": str(rank), "sic": "1234", "market_data_mode": "sip_eod",
             "market_data_feed": "sip", "official_sip_close": 100.0},
        ))
    paths = write_decision_snapshot(
        output_root=root, strategy_style="production", decisions=decisions,
        daily_attention=decisions[:2], weekly_attention=decisions[:2], decision_date=session,
        generated_at_utc=generated.isoformat(), config_fingerprint=config, code_sha="source-fixture",
        input_provenance={"market_data_feed": "sip", "market_data_mode": "sip_eod"},
        validate_attention_cap=15,
    )
    receipt = dict(
        schema_version=1, mode="formal", run_id=session, strategy_style="production",
        expected_session=session, published_session=session, status="published", exit_code=0,
        started_at_utc=at(session, "21:30").isoformat(), finished_at_utc=at(session, "22:04").isoformat(),
        publication={
            "decision_date": session, "strategy_style": "production",
            "snapshot_dir": f"{session}/production", "manifest_sha256": file_sha(paths.run_manifest_json),
            "decisions_sha256": file_sha(paths.decisions_jsonl),
            "first_readable_at_utc": at(session, "22:01").isoformat(),
        },
    )
    return paths, receipt


class TestForwardObservations(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "decisions"
        self.ledger = Ledger(self.root.parent / "ledger.db", snapshot_root=self.root)
        self.day = "2026-11-23"
        self.now = at(self.day, "22:20")
        self.paths, self.receipt = build_archive(self.root, self.day)
        self.protocol = freeze_protocol(self.ledger, {
            "style": "production", "version": "test-v1", "fee_bps_per_side": 15,
            "horizons": [1, 2], "setup_versions": ["fixture-v1"], "paper_rules": ["fixed-open-v1"],
            "decision_policy": "v1", "config_fingerprint": "config-fixture", "description": "Frozen test protocol",
            "report_renderer": REPORT_RENDERER_REVISION,
        }, now=at("2026-11-20", "23:00"))

    def capture(self, receipt=None, now=None):
        receipt = receipt or self.receipt
        self.ledger.import_attempt(receipt, now=now or self.now)
        manifest = receipt["publication"]["manifest_sha256"]
        return evidence_id("snapshot", "production", receipt["published_session"], manifest)

    def observe(self, symbol="AAA"):
        return evidence_id("observation", self.capture(), symbol)

    def test_atomic_concurrent_receipt_capture_and_recovery(self):
        actual = ledger_module.append
        def fail_observation(db, key, kind, *args):
            if kind == "observation":
                raise OSError("simulated crash")
            return actual(db, key, kind, *args)

        with patch("ai_value_scanner.forward.ledger.append", side_effect=fail_observation):
            with self.assertRaises(OSError):
                self.capture()
        self.assertEqual(self.ledger.records("snapshot"), [])
        self.assertEqual(self.ledger.records("receipt"), [])
        retry = {**self.receipt, "run_id": "retry", "status": "reused"}
        with ThreadPoolExecutor(max_workers=4) as workers:
            ids = list(workers.map(lambda _: self.capture(retry), range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.ledger.records("receipt")), 1)
        frozen = self.ledger.records("observation")
        self.assertEqual(len(frozen), 3)
        self.assertIsNone(frozen[2]["payload"]["daily_rank"])
        self.assertTrue(frozen[2]["payload"]["candidate"])
        self.assertEqual(frozen[0]["payload"]["official_close"], 100.0)
        main = self.ledger.records("snapshot")[0]["payload"]
        self.assertEqual(main["daily"], ["AAA", "BBB"])
        self.assertEqual(main["sha256"]["action_list.md"], file_sha(self.paths.action_list_md))
        self.assertEqual(self.ledger.records("receipt")[0]["payload"]["first_readable_at_utc"],
                         self.receipt["publication"]["first_readable_at_utc"])
        with sqlite3.connect(self.ledger.path) as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM evidence")

    def test_altered_archive_and_failure_receipts(self):
        failed = {**self.receipt, "run_id": "failed", "status": "failed", "exit_code": 1,
                  "reason_code": "sip_benchmark_missing", "publication": None}
        self.ledger.import_attempt(failed, now=self.now)
        self.assertIsNone(self.ledger.records("receipt")[0]["parent"])
        self.paths.action_list_md.write_text("truncated")
        with self.assertRaises(ValueError):
            self.capture()
        self.assertEqual(self.ledger.records("snapshot"), [])

    def test_original_receipt_rejects_altered_off_list_close(self):
        raw = self.paths.decisions_jsonl.read_text()
        lines = raw.splitlines(keepends=True)
        self.assertIn('"symbol":"CCC"', lines[-1].replace(" ", ""))
        lines[-1] = lines[-1].replace("100.0", "999.0")
        delta = "".join(lines)
        self.assertNotEqual(delta, raw)
        self.paths.decisions_jsonl.write_text(delta)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.capture()

    def test_protocol_coverage_uses_linked_snapshot_and_renderer(self):
        self.capture()
        _, receipt = build_archive(self.root, "2026-11-24", config="other")
        self.capture(receipt, at("2026-11-24", "22:10"))
        with patch("ai_value_scanner.reporting.snapshot.REPORT_RENDERER_REVISION", "mvp_report_renderer_2026-11-22b"):
            _, receipt = build_archive(self.root, "2026-11-25")
        self.capture(receipt, at("2026-11-25", "22:10"))
        summary = study_summary(self.ledger, self.protocol, now=at("2026-11-25", "22:12"))
        self.assertEqual(summary["eligible_forward_snapshots"], 1)
        self.assertEqual(summary["other_version_attempts"], {"published": 2})
        self.assertEqual([row["status"] for row in summary["sessions"]], ["published", "missing_receipt", "missing_receipt"])

    def test_unknown_release_and_same_day_vs_late_reviews(self):
        sid = self.ledger.import_archive(self.paths.root, now=self.now)
        oid_a = evidence_id("observation", sid, "AAA")
        oid_b = evidence_id("observation", sid, "BBB")
        base = {
            "protocol_id": self.protocol, "surface": "daily", "choice": "deep_dive",
            "workflow": "new", "reason": "check cash flow", "budget_minutes": 10, "review_minutes": 3,
            "displayed_at": at(self.day, "22:05").isoformat(), "read_at": at(self.day, "22:06").isoformat(),
            "decided_at": at(self.day, "22:10").isoformat(),
        }
        original = record_review(self.ledger, {**base, "observation_id": oid_a}, now=self.now)
        self.assertEqual(self.ledger.records("review")[0]["payload"]["evidence_class"], "publication_time_unknown")
        self.capture()
        self.assertEqual(record_review(self.ledger, {**base, "observation_id": oid_a}, now=self.now), original)
        late = record_review(self.ledger, {**base, "observation_id": oid_b}, now=at("2026-11-24", "18:00"))
        self.assertEqual(self.ledger.records("review")[1]["id"], late)
        self.assertEqual(self.ledger.records("review")[1]["payload"]["evidence_class"], "backfill")
        summary = study_summary(self.ledger, self.protocol, now=at("2026-11-24", "18:01"))
        self.assertEqual(summary["review_utility"]["new"]["unreviewed"], 2)
        self.assertEqual(summary["review_utility"]["new"]["utility_status"], "undetermined")

    def test_declared_preclose_review_recorded_after_close_is_backfill(self):
        review = {
            "protocol_id": self.protocol, "observation_id": self.observe(), "surface": "daily", "workflow": "new",
            "choice": "wait", "reason": "wait", "budget_minutes": 5, "review_minutes": 3,
            "displayed_at": "2026-11-24T20:45:00Z", "read_at": "2026-11-24T20:46:00Z",
            "decided_at": "2026-11-24T20:55:00Z",
        }
        self.assertEqual(utc(review["decided_at"]), at("2026-11-24", "20:55"))
        record_review(self.ledger, review, now=at("2026-11-24", "22:00"))
        self.assertEqual(self.ledger.records("review")[0]["payload"]["evidence_class"], "backfill")

    def test_pair_uses_distinct_same_week_same_industry_cases(self):
        first = self.observe()
        second = self.observe("BBB")
        base = {
            "protocol_id": self.protocol, "surface": "daily", "choice": "wait",
            "reason": "observe", "budget_minutes": 10, "review_minutes": 3, "pair_id": "block-1",
            "displayed_at": at(self.day, "22:05").isoformat(), "read_at": at(self.day, "22:06").isoformat(),
            "decided_at": at(self.day, "22:10").isoformat(),
        }
        record_review(self.ledger, {**base, "observation_id": first, "workflow": "baseline",
            "displayed_report_sha256": "d"*64, "displayed_version": "original"}, now=self.now)
        wrong = {**base, "observation_id": first, "workflow": "new"}
        with self.assertRaisesRegex(ValueError, "distinct securities"):
            record_review(self.ledger, wrong, now=self.now)
        record_review(self.ledger, {**wrong, "observation_id": second, "choice": "deep_dive",
                      "risk_codes": ["concentration"], "review_minutes": 2}, now=self.now)
        summary = study_summary(self.ledger, self.protocol, now=self.now)
        self.assertEqual(summary["review_utility"]["new"]["coverage"], .5)
        self.assertEqual(summary["matched_pairs"][0]["review_minutes_delta"], -1)
        self.assertEqual(summary["matched_pairs"][0]["risk_identification_delta"], 1)

    def test_one_setup_event_across_sessions_and_retry(self):
        first = self.observe()
        base = dict(protocol_id=self.protocol, setup_version="fixture-v1", source="controlled fixture",
                    evidence={"criterion": "example"})
        initial = {**base, "observation_id": first, "state": "confirmed", "observed_at": self.now.isoformat()}
        key = record_setup(self.ledger, initial, now=self.now)
        day2 = "2026-11-24"
        _, receipt = build_archive(self.root, day2)
        then = at(day2, "22:10")
        second = evidence_id("observation", self.capture(receipt, then), "AAA")
        record_setup(self.ledger, {**initial, "state": "active", "observation_id": second,
                                   "observed_at": then.isoformat()}, now=then)
        self.assertEqual(record_setup(self.ledger, initial, now=then), key)
        setups = self.ledger.records("setup")
        self.assertEqual(setups[0]["payload"]["event_id"], setups[1]["payload"]["event_id"])
        self.assertEqual(setups[1]["payload"]["first_confirmed_session"], self.day)
        summary = study_summary(self.ledger, self.protocol, now=then)
        self.assertEqual(summary["confirmed_events"], 1)
        self.assertEqual(summary["setup_episodes"][0]["latest_seen_at"], then.isoformat())

    def test_missing_setup_session_breaks_continuity(self):
        initial = dict(protocol_id=self.protocol, setup_version="fixture-v1", source="test",
                       evidence={"close": 100}, observation_id=self.observe(), state="confirmed", observed_at=self.now.isoformat())
        record_setup(self.ledger, initial, now=self.now)
        _, receipt = build_archive(self.root, "2026-11-25")
        then = at("2026-11-25", "22:10")
        later = evidence_id("observation", self.capture(receipt, then), "AAA")
        record_setup(self.ledger, {**initial, "state": "active", "observation_id": later, "observed_at": then.isoformat()}, now=then)
        payload = self.ledger.records("setup")[-1]["payload"]
        self.assertIsNone(payload["event_id"])
        self.assertEqual(payload["continuity"], "unknown")
        self.assertEqual(study_summary(self.ledger, self.protocol, now=then)["setup_episodes"][0]["latest_state"], "continuity_unknown")

    def test_next_open_early_settlement_fees_and_append_only_revision(self):
        base = dict(protocol_id=self.protocol, observation_id=self.observe(), path="fixed",
                    rule_version="fixed-open-v1", status="planned", decision_at=self.now.isoformat())
        path = record_paper(self.ledger, base, now=self.now)
        day2 = "2026-11-24"
        open_time = at(day2, "14:30")
        fill = dict(paper_id=path, status="entered", entry_at=open_time.isoformat(), entry_price=100,
                    entry_source="historical fixture SIP open", price_basis="entry-session shares")
        with self.assertRaisesRegex(ValueError, "executable window"):
            record_fill(self.ledger, {**fill, "entry_at": self.now.isoformat()}, now=open_time)
        record_fill(self.ledger, fill, now=open_time)
        self.assertEqual(self.ledger.records("paper_fill")[0]["payload"]["evidence_class"], "forward")
        outcome = dict(paper_id=path, horizon=1, asof=at(day2, "21:01").isoformat(), exit_price=104,
                       exit_source="historical fixture SIP close", exit_at=at(day2, "21:00").isoformat(),
                       price_basis="entry-session shares", equity_continuity="verified")
        with self.assertRaisesRegex(ValueError, "not mature"):
            record_outcome(self.ledger, outcome, now=at(day2, "20:59"))
        first = record_outcome(self.ledger, outcome, now=at(day2, "21:05"))
        self.assertAlmostEqual(self.ledger.records("outcome")[0]["payload"]["net_return"], .037)
        changed = {**outcome, "exit_price": 103, "supersedes": first, "revision": "correction-1",
                   "revision_reason": "corrected source"}
        record_outcome(self.ledger, changed, now=at(day2, "21:09"))
        again = record_outcome(self.ledger, outcome, now=at(day2, "21:10"))
        self.assertEqual(again, first)
        ledger_rows = self.ledger.records("outcome")
        self.assertEqual(len(ledger_rows), 2)
        self.assertAlmostEqual(ledger_rows[1]["payload"]["net_return"], .027)
        summary = study_summary(self.ledger, self.protocol, now=at(day2, "21:11"))
        self.assertEqual([(row["horizon"], row["status"]) for row in summary["paper_maturity"]],
                         [(1, "mature"), (2, "unmatured")])

    def test_early_gap_exit_and_wait_at_a_common_terminal(self):
        base = dict(protocol_id=self.protocol, observation_id=self.observe(), path="fixed",
                    rule_version="fixed-open-v1", status="planned", decision_at=self.now.isoformat())
        active = record_paper(self.ledger, base, now=self.now)
        cash = record_paper(self.ledger, {**base, "observation_id": self.observe("BBB"), "status": "cash",
                                       "reason": "wait at the same endpoint"}, now=self.now)
        entry = at("2026-11-24", "14:30")
        record_fill(self.ledger, dict(paper_id=active, status="entered", entry_at=entry.isoformat(),
                    entry_price=100, entry_source="SIP open", price_basis="entry units"), now=entry)
        terminal = at("2026-11-25", "21:00")
        original = record_outcome(self.ledger, dict(paper_id=active, horizon=2, asof=terminal.isoformat(),
            exit_price=92, exit_at=at("2026-11-25", "14:30").isoformat(), exit_reason="yesterday's invalidation",
            exit_source="SIP open", equity_continuity="verified", price_basis="entry units"), now=terminal)
        record_outcome(self.ledger, dict(paper_id=cash, horizon=2, asof=terminal.isoformat()), now=terminal)
        active_outcome, cash_outcome = (row["payload"] for row in self.ledger.records("outcome"))
        self.assertAlmostEqual(active_outcome["net_return"], -.083)
        self.assertEqual(active_outcome["evidence_class"], "backfill")
        self.assertEqual(cash_outcome["net_return"], 0)
        self.assertEqual(active_outcome["maturity_at"], cash_outcome["maturity_at"])
        summary = study_summary(self.ledger, self.protocol, now=at("2026-11-25", "21:25"))
        self.assertEqual(summary["sessions"][-1]["status"], "missing_receipt")

    def test_exit_commitment_and_late_fill_revision(self):
        oid = self.observe()
        planned = dict(protocol_id=self.protocol, observation_id=oid, path="fixed",
                       rule_version="fixed-open-v1", status="planned", decision_at=self.now.isoformat())
        paper = record_paper(self.ledger, planned, now=self.now)
        open_at = at("2026-11-24", "14:30")
        terminal = at("2026-11-24", "21:00")
        missing = dict(paper_id=paper, horizon=1, asof=terminal.isoformat(), missing_reason="feed missed")
        first = record_outcome(self.ledger, missing, now=terminal)
        record_fill(self.ledger, dict(paper_id=paper, status="entered", entry_at=open_at.isoformat(),
                    entry_price=100, entry_source="SIP opening bar", price_basis="entry units"),
                    now=at("2026-11-24", "21:05"))
        self.assertEqual(record_outcome(self.ledger, missing, now=at("2026-11-24", "21:06")), first)
        decided = at("2026-11-24", "21:10")
        exit_id = record_exit(self.ledger, dict(paper_id=paper, decided_at=decided.isoformat(), reason="test"), now=decided)
        next_day = at("2026-11-25", "21:00")
        record_outcome(self.ledger, dict(paper_id=paper, exit_id=exit_id, horizon=2, asof=next_day.isoformat(),
                       exit_at=at("2026-11-25", "14:30").isoformat(), exit_price=95, exit_source="SIP opening bar",
                       exit_reason="test", price_basis="entry units", equity_continuity="verified"), now=next_day)
        self.assertEqual(self.ledger.records("outcome")[-1]["payload"]["evidence_class"], "forward")

    def test_discretionary_time_stamped_fill_is_backfill(self):
        path = record_paper(self.ledger, dict(protocol_id=self.protocol, observation_id=self.observe(),
            path="fixed", execution_basis="time_stamped", rule_version="fixed-open-v1", status="planned",
            decision_at=self.now.isoformat()), now=self.now)
        timestamp = at("2026-11-25", "15:00")
        record_fill(self.ledger, dict(paper_id=path, status="entered", entry_at=timestamp.isoformat(),
                    entry_price=77, entry_source="selected quote", price_basis="entry units"), now=timestamp)
        self.assertEqual(self.ledger.records("paper_fill")[0]["payload"]["evidence_class"], "backfill")
