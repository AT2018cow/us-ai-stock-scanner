from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_value_scanner.decision.action import map_action_state_v2
from ai_value_scanner.decision.entry import ENTRY_V2_POLICY_VERSION
from ai_value_scanner.decision.integrated import select_daily_attention
from ai_value_scanner.decision.model import (
    DECISION_SCHEMA_VERSION, ActionState, EntryDecision, EntryState, QualityDecision,
    QualityGrade, ReadyAge, StockDecision, stock_decision_from_json, stock_decision_to_json,
)
from ai_value_scanner.decision.quality import QUALITY_V2_POLICY_VERSION
from ai_value_scanner.decision.review import (
    FollowedSecurity, build_followed_rows, build_ready_ages, freeze_followed_prior, load_followed_securities,
    with_review_evidence,
)
from ai_value_scanner.reporting.decision import render_action_list, render_detailed_report
from ai_value_scanner.reporting.snapshot import iter_ready_history, write_decision_snapshot


def _stock(symbol="EXM", day="2026-11-23", *, state=EntryState.ENTRY_READY,
           grade=QualityGrade.A, score=0.80, cik="0000000123", rank=1):
    quality = QualityDecision(grade, 0.68, 0.80, {}, (), (), (), day)
    entry = EntryDecision(state, score, 0.9, (), (), day)
    action, _ = map_action_state_v2(quality, entry)
    return StockDecision(
        DECISION_SCHEMA_VERSION, symbol, symbol, day, day + "T22:00:00+00:00",
        quality, entry, action, rank, (), None, (),
        {"cik": cik, "market_data_feed": "sip", "market_data_mode": "sip_eod",
         "entry_policy_version": ENTRY_V2_POLICY_VERSION, "quality_policy_version": QUALITY_V2_POLICY_VERSION,
         "decision_policy_version": "q=v2,e=v2,a=v2"},
    )


class TestDecisionReview(unittest.TestCase):
    def test_offline_recompute_drops_review_evidence_from_the_original_policy(self):
        from scripts.render_snapshot_preview import recompute_v2_decisions

        archived = with_review_evidence(_stock(), ReadyAge(1, "2026-11-23", None, "missing_prior_session"))
        (preview,) = recompute_v2_decisions([archived])
        self.assertEqual(preview.review_conditions, ())
        self.assertIsNone(preview.ready_age)

    def test_grade_b_boundary_is_shared_by_reports_and_json(self):
        for score, action, status, margin in (
            (0.79, ActionState.HOLD_MONITOR, "BLOCK", -0.01),
            (0.80, ActionState.PRIORITY_REVIEW, "PASS", 0.0),
        ):
            with self.subTest(score=score):
                decision = _stock(grade=QualityGrade.B, score=score)
                age = ReadyAge(2, "2026-11-20", "2026-11-20", "observed_transition")
                decision = with_review_evidence(decision, age)
                self.assertEqual(decision.action_state, action)
                conditions = {item.metric: item for item in decision.review_conditions}
                self.assertEqual(conditions["quality_score"].margin, 0.0)
                self.assertEqual(conditions["quality_confidence"].margin, 0.0)
                self.assertEqual((conditions["entry_score"].status, conditions["entry_score"].margin), (status, margin))
                self.assertEqual(stock_decision_from_json(stock_decision_to_json(decision)), decision)
                for layout in ("v1", "v2"):
                    for cadence in ("daily", "weekly"):
                        report = render_action_list([decision], layout_version=layout, cadence=cadence)
                        self.assertIn("confirmed 2026-11-20", report)
                        self.assertIn(f"B Entry score** · {score:g} / >= 0.80 · {status}", report)
                    detailed = render_detailed_report(decision, layout_version=layout)
                    self.assertIn(f"B Entry score | ", detailed)
                    self.assertIn(f"| {score:g} | >= | >= 0.80 | {margin:+g} | {status}", detailed)

    def test_ready_age_requires_a_compatible_observed_transition(self):
        current = _stock()
        prior = _stock(day="2026-11-20")
        watch = _stock(day="2026-11-19", state=EntryState.WATCH_PULLBACK)
        for older, reason, first_day in (
            ({"EXM": watch}, "observed_transition", "2026-11-20"),
            (None, "missing_prior_session", None),
            ({}, "security_missing_in_prior_snapshot", None),
            ({"EXM": replace(watch, provenance={**watch.provenance, "cik": "4444"})},
             "security_identity_unverified_or_changed", None),
            ({"EXM": replace(watch, provenance={**watch.provenance, "market_data_feed": "iex"})},
             "feed_or_policy_changed", None),
            ({"EXM": replace(watch, provenance={**watch.provenance, "entry_policy_version": "old"})},
             "feed_or_policy_changed", None),
            ({"EXM": replace(watch, entry=replace(watch.entry, state=EntryState.INSUFFICIENT_DATA))},
             "prior_entry_data_unavailable", None),
        ):
            with self.subTest(reason=reason):
                age = build_ready_ages((current,), ((prior.decision_date, {"EXM": prior}), (watch.decision_date, older)))
                self.assertEqual(age["EXM"], ReadyAge(2, "2026-11-20", first_day, reason))
        reset = _stock(state=EntryState.WATCH_PULLBACK)
        ages = build_ready_ages((reset,), ((prior.decision_date, {"EXM": prior}),))
        self.assertEqual(ages["EXM"].reason, "ready_reset_to_watch_pullback")
        for broken in (replace(reset.entry, market_asof=None), replace(reset.entry, state=EntryState.INSUFFICIENT_DATA)):
            ages = build_ready_ages((replace(reset, entry=broken),), ((prior.decision_date, {"EXM": prior}),))
            self.assertEqual(ages["EXM"].reason, "current_entry_data_unavailable")
        reentry = _stock(day="2026-11-24")
        ages = build_ready_ages((reentry,), ((reset.decision_date, {"EXM": reset}),))
        self.assertEqual(ages["EXM"], ReadyAge(1, "2026-11-24", "2026-11-24", "observed_transition"))

    def test_history_uses_exchange_calendar_and_refuses_late_backfill(self):
        prior = _stock(day="2026-11-25")  # Wednesday before Thanksgiving.
        observed_at = datetime(2026, 11, 28, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_decision_snapshot(
                output_root=root, strategy_style="production", decisions=[prior],
                daily_attention=[prior], weekly_attention=[prior], decision_date=prior.decision_date,
                generated_at_utc=prior.generated_at_utc, config_fingerprint="fixture", policy_version="v2",
            )
            self.assertTrue(paths.root.is_dir())
            day, decisions = next(iter(iter_ready_history(root, "2026-11-27", "production", observed_at=observed_at)))
            self.assertEqual((day, decisions), ("2026-11-25", {"EXM": prior}))
            too_early = datetime(2026, 11, 25, 21, 0, tzinfo=timezone.utc)
            self.assertEqual(list(iter_ready_history(root, "2026-11-27", "production", observed_at=too_early)),
                             [("2026-11-25", None)])
            paths.action_list_md.unlink()
            self.assertEqual(list(iter_ready_history(root, "2026-11-27", "production", observed_at=observed_at)),
                             [("2026-11-25", None)])

    def test_followed_stock_changes_include_grace_cutoff_and_same_action_weakness(self):
        cut = _stock("CUT", rank=2)
        grace = replace(_stock("GRACE", state=EntryState.WATCH_BREAKOUT, rank=3),
                        previous_action_state=ActionState.PRIORITY_REVIEW)
        weak = _stock("WEAK", grade=QualityGrade.B)
        damaged = _stock("HARD", state=EntryState.TREND_DAMAGED, rank=4)
        already_monitor = _stock("HARD", day="2026-11-20", state=EntryState.WATCH_PULLBACK, grade=QualityGrade.B)
        self.assertEqual(already_monitor.action_state, damaged.action_state)
        prior = {"WEAK": _stock("WEAK", day="2026-11-20"), "HARD": already_monitor,
                 "CUT": _stock("CUT", day="2026-11-20"), "GRACE": _stock("GRACE", day="2026-11-20")}
        entries = [FollowedSecurity(symbol, "0000000123", "2026-10-30T20:00:00+00:00", "research")
                   for symbol in ("CUT", "GRACE", "WEAK", "HARD", "EXCL", "OLD", "MISSING")]
        names = ("CUT", "GRACE", "WEAK", "HARD")
        decisions = (weak, cut, grace, damaged, _stock("OLD", cik="0000000002"), _stock("NEW"))
        selected = select_daily_attention(decisions, cap=3, previous_daily_symbols=names)
        frozen = freeze_followed_prior(entries, prior, names)
        rows = build_followed_rows(entries, decisions, frozen, (item.symbol for item in selected),
                                   [{"symbol": "EXCL", "reason_code": "ACTIVE_ASSET_MISSING"}])
        by_symbol = {row["symbol"]: row for row in rows}
        self.assertEqual(by_symbol["GRACE"]["changes"], ["grace_retained"])
        self.assertEqual(by_symbol["WEAK"]["changes"], ["quality_weakened"])
        self.assertEqual(by_symbol["WEAK"]["action"], "PRIORITY_REVIEW")
        self.assertEqual(by_symbol["HARD"]["changes"], ["trend_damaged", "left_daily_hard_damage"])
        self.assertEqual(by_symbol["EXCL"]["exclusion_reason"], "ACTIVE_ASSET_MISSING")
        self.assertEqual(by_symbol["OLD"]["status"], "security_identity_unverified_or_changed")
        self.assertIn("NEW", by_symbol["OLD"]["same_issuer_symbols"])
        self.assertEqual(by_symbol["MISSING"]["status"], "missing_from_scan")
        selected = select_daily_attention(decisions, cap=1, previous_daily_symbols=names)
        cut_rows = build_followed_rows(entries[:1], decisions, frozen, (item.symbol for item in selected), ())
        self.assertEqual(cut_rows[0]["changes"], ["left_daily_ranking_cutoff"])
        old_weak = prior["WEAK"]
        prior["WEAK"] = replace(old_weak, provenance={**old_weak.provenance, "quality_policy_version": "old"})
        weak_rows = build_followed_rows(entries[2:3], decisions, freeze_followed_prior(entries, prior, names), ["WEAK"], ())
        self.assertEqual(weak_rows[0]["changes"], [])
        prior["GRACE"] = replace(prior["GRACE"], provenance={**prior["GRACE"].provenance, "cik": "42"})
        replacement = freeze_followed_prior(entries, prior, names)
        self.assertEqual(build_followed_rows(entries[1:2], decisions, replacement, ["GRACE"], ())[0]["changes"], [])

    def test_followed_input_freezes_only_known_additions(self):
        with TemporaryDirectory() as tmp:
            csv = Path(tmp) / "watched.csv"
            csv.write_text("symbol,cik,added_at_utc,reason\nexm,123,2026-11-23T14:00:00Z,review\n"
                           "future,124,2026-11-24T00:00:00Z,review\n", encoding="utf-8")
            now = datetime(2026, 11, 23, 21, tzinfo=timezone.utc)
            rows, digest = load_followed_securities(csv, asof=now)
            self.assertEqual(rows, [FollowedSecurity("EXM", "0000000123", "2026-11-23T14:00:00+00:00", "review")])
            self.assertEqual(len(digest), 64)
            csv.write_text("symbol,cik,added_at_utc,reason\nEXM,123,2026-11-23T14:00:00,review\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid or repeated security"):
                load_followed_securities(csv, asof=now)
