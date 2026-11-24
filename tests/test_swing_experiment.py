from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ai_value_scanner.forward.ledger import Ledger, append, utc
from ai_value_scanner.fundamentals.coverage import SHARES_BASIS
from ai_value_scanner.market_calendar import session_close_utc
from ai_value_scanner.research.swing_cohorts import (
    INTEGRITY, ENTRY_GATES, PROTOCOL, day_shift, execution_day, freeze, freeze_cohorts,
    implementation_sha256, register, sha, _peers,
)
from ai_value_scanner.research.swing_experiment import _episode_paths, _pair, evaluate
from ai_value_scanner.research.swing_paths import PriceBook, barrier_order, cash, settle
from ai_value_scanner.research.swing_statistics import summarize
from ai_value_scanner.swing.setups import BREAKOUT_VERSION, PULLBACK_VERSION, previous_session

ORIGIN = date(2025, 11, 3)
PREVIOUS = previous_session(ORIGIN)
CONFIRM = day_shift(ORIGIN, 1)
ENTER = day_shift(CONFIRM, 1)
EXIT = day_shift(ENTER, 2)
ASOF = datetime(2026, 6, 1, tzinfo=timezone.utc)
SEC = "AAA:0000000001"


def bar(day, o=100, h=106, l=96, c=104, *, observed=None):
    return {"session": str(day), "o": o, "h": h, "l": l, "c": c,
            **({"close_known_at_utc": observed} if observed else {})}


def evidence(rows, **overrides):
    return {"feed": "sip", "price_basis": "raw", "source": "engineered fixture",
            "asof_utc": ASOF.isoformat(), "securities": {
                SEC: {"security_id": SEC, "verified_from": str(PREVIOUS), "verified_through": "2026-05-29",
                      "identity_source": "test identity", "corporate_actions_source": "test action inventory",
                      "bars": rows, "splits": [], "distributions": [], **overrides}}}


def row(day, symbol, cik, state="WORK", *, priority=1, setup=BREAKOUT_VERSION, vol=.34, fcf=None):
    shape, watch = ("breakout", "WATCH_BREAKOUT") if setup == BREAKOUT_VERSION else ("pullback", "WATCH_PULLBACK")
    wait = state == "WATCH"
    fresh = state == "CONF"
    gates = [{"gate_key": g, "status": "PASS"} for g in sorted(ENTRY_GATES | INTEGRITY)]
    return {
        "symbol": symbol, "security_id": f"{symbol}:{cik:010d}", "quality": "A", "quality_asof": str(day),
        "entry": watch if wait else "ENTRY_READY", "market_asof": str(day), "industry": "3571", "priority": priority,
        "action": "WATCH_BREAKOUT" if wait else "PRIORITY_REVIEW", "official_close": 100,
        "entry_gates": gates + [{"gate_key": "volatility_cap", "status": "PASS", "metric": "volatility_60d", "observed": vol}],
        "financial_review": ({"status": "recovered_candidate", "currency": "USD", "asof": str(day),
                              "metrics": {"fcf_per_current_share": fcf},
                              "derived_operands": {"current_shares": {"sources": ["fixture"], "basis": SHARES_BASIS,
                                                                      "end": str(day), "basis_ids": ["common"]}}}
                             if fcf is not None else None),
        "swing_review": {"close": 100, "patterns": {shape: {
            "new_confirmation": fresh, "state": {"version": setup, "status": "confirmed" if fresh else "watching",
                                                 "origin": str(day) if wait else None, "stop": 99, "confirmed": str(day) if fresh else None}}}}
    }


def frame(day, rows, *, available=None):
    return {"available": available or session_close_utc(day).replace(minute=30).isoformat(),
            "rows": rows, "meta": {"daily": [item["symbol"] for item in rows[:15]]}}


def _spec(mode="retrospective", setup=BREAKOUT_VERSION):
    return {"name": "example", "mode": mode, "pattern": setup, "start": str(ORIGIN), "through": str(CONFIRM),
            "style": "production", "report_renderer": "frozen-test", "decision_policy": "v2", "config_fingerprint": "fixture"}


def _cohort(frames, *, coverage=None, setup=BREAKOUT_VERSION, mode="retrospective"):
    return freeze_cohorts({**_spec(mode, setup), "rules": PROTOCOL, "implementation_sha256": implementation_sha256()},
                          frames, coverage=coverage or {},
                          protocol_id="synthetic-protocol", asof=ASOF)


def _confirmed(day, symbol="AAA", cik=1, *, available=None):
    return {"id": f"{symbol}-{day}", "symbol": symbol, "security_id": f"{symbol}:{cik:010d}", "cik": f"{cik:010d}",
            "status": "confirmed", "session": str(previous_session(day)), "resolution_session": str(day), "level": 99,
            "available": frame(previous_session(day), [])["available"],
            "confirmation_available": available or frame(day, [])["available"]}


class PaperPathTest(TestCase):
    def test_preopen_plan_fills_even_if_the_open_gaps_below_anchor(self):
        one = settle(PriceBook(evidence([bar(ENTER, o=92, l=90)])), SEC, ENTER, ENTER,
                     signal=CONFIRM, locked=99, avoid_invalidated=True)
        self.assertEqual(one["status"], "settled")
        self.assertEqual(one["price_denominator"], 92)
        delayed = day_shift(ENTER, 1)
        book = PriceBook(evidence([bar(ENTER, c=98), bar(delayed)]))
        two = settle(book, SEC, delayed, delayed, signal=CONFIRM, locked=99, avoid_invalidated=True)
        self.assertEqual(two["reason"], "invalidation_known_before_open")
        self.assertEqual(two["status"], "cash")
        self.assertNotIn("entry_session", two)

    def test_independent_cost_and_cash_contract(self):
        book = PriceBook(evidence([bar(ENTER)]))
        path = settle(book, SEC, ENTER, ENTER)
        self.assertAlmostEqual(path["gross"], .04)
        self.assertAlmostEqual(path["net_15"], .037)
        self.assertAlmostEqual(path["net_30"], .034)
        self.assertEqual(path["costs_by_side"]["15"], {"entry": .15, "exit": .15})
        self.assertEqual(cash(book, ENTER, "expired")["net_15"], 0)

    def test_next_open_gap_and_exit_day_excursion(self):
        between = day_shift(ENTER, 1)
        book = PriceBook(evidence([
            bar(ENTER, h=103, l=99, c=100), bar(between, h=102, l=97, c=98),
            bar(EXIT, o=92, h=130, l=60, c=104),
        ]))
        kwargs = {"signal": CONFIRM, "locked": 99}
        fixed = settle(book, SEC, ENTER, EXIT, **kwargs)
        early = settle(book, SEC, ENTER, EXIT, exit_on_break=True, **kwargs)
        self.assertEqual(early["exit_price_entry_share_basis"], 92)
        self.assertAlmostEqual(early["net_15"], -.083)
        self.assertAlmostEqual(early["mae"], -.08)
        self.assertAlmostEqual(early["mfe"], .03)
        self.assertAlmostEqual(fixed["mae"], -.40)
        self.assertEqual(early["close_signal_session"], str(between))
        self.assertAlmostEqual(fixed["net_15"], .037)

    def test_two_barriers_in_a_single_bar_report_both_paths(self):
        book = PriceBook(evidence([bar(ENTER, h=112, l=93)]))
        resolution = barrier_order(book, SEC, CONFIRM, ENTER, ENTER, 95, 110)
        self.assertEqual(resolution["status"], "same_bar_order_unknown")
        self.assertEqual((resolution["conservative"], resolution["optimistic"]), (95, 110))

    def test_split_and_cash_distributions_use_one_share_basis(self):
        next_day = day_shift(ENTER, 1)
        book = PriceBook(evidence([
            bar(ENTER, h=103, l=99, c=101), bar(next_day, o=51, h=54, l=50, c=52)],
            splits=[[str(next_day), .5]], distributions=[[str(next_day), 1.]],
        ))
        path = settle(book, SEC, ENTER, next_day, signal=CONFIRM, locked=98, exit_on_break=True)
        self.assertAlmostEqual(path["net_15"], .057)
        self.assertAlmostEqual(path["cash_distributions_entry_share_basis"], 2.)
        self.assertEqual(path["reason"], "fixed_horizon_close")

    def test_maturity_gaps_and_continuity_are_distinct(self):
        self.assertEqual(settle(PriceBook(evidence([])), SEC, ENTER, ENTER)["status"], "mature_missing")
        book = PriceBook(evidence([bar(ENTER)], events={str(EXIT): "merger"}))
        before = day_shift(ENTER, 1)
        self.assertEqual(settle(book, SEC, ENTER, before)["status"], "mature_missing")
        self.assertEqual(settle(book, SEC, EXIT, EXIT)["status"], "merger")
        after = date(2026, 7, 1)
        self.assertEqual(settle(book, SEC, ENTER, after)["status"], "future_unmatured")
        book = PriceBook(evidence([bar(EXIT)], events={str(ENTER): "suspended", str(before): "halted_all_session"}))
        self.assertEqual(settle(book, SEC, ENTER, EXIT)["entry_session"], str(EXIT))

    def test_missing_or_late_close_cannot_trigger_an_earlier_forward_exit(self):
        rows = [bar(ENTER, c=98), bar(day_shift(ENTER, 1), o=100, c=104), bar(EXIT, o=92, l=90)]
        path = settle(PriceBook(evidence(rows), forward=True), SEC, ENTER, EXIT,
                      signal=CONFIRM, locked=99, exit_on_break=True)
        self.assertEqual(path["status"], "close_timestamp_unknown")
        rows[0]["close_known_at_utc"] = f"{day_shift(ENTER, 1)}T16:00:00Z"
        path = settle(PriceBook(evidence(rows), forward=True), SEC, ENTER, EXIT,
                      signal=CONFIRM, locked=99, exit_on_break=True)
        self.assertEqual(path["exit_session"], str(EXIT))
        self.assertEqual(path["exit_price_entry_share_basis"], 92)

    def test_open_timing_respects_release_and_nyse_calendar(self):
        self.assertEqual(str(execution_day("2025-11-05T14:29:00Z")), "2025-11-05")
        self.assertEqual(str(execution_day("2025-11-05T14:30:00Z")), "2025-11-06")
        self.assertEqual(str(execution_day("2025-11-26T21:30:00Z")), "2025-11-28")


class FreezeAndEvaluateTest(TestCase):
    def test_future_label_cutoff_rejected_before_simulation(self):
        cohort = _cohort({}, mode="forward")
        with self.assertRaisesRegex(ValueError, "cutoff cannot be in the future"):
            evaluate(cohort, evidence([]), cohort_sha256=sha(cohort), now=utc("2026-05-31T23:59:59Z"))
        self.assertEqual(evaluate(cohort, evidence([]), cohort_sha256=sha(cohort), now=ASOF)["price_cutoff_utc"],
                         ASOF.isoformat())

    def test_implementation_changes_invalidate_registration_and_frozen_cohort(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            ledger = Ledger(base/"evidence.db", snapshot_root=base/"archives")
            at = utc("2025-11-02T20:00:00Z")
            key = register(ledger, _spec("forward"), now=at)
            cohort = freeze(ledger, key, asof=at)
            pinned = cohort["spec"]["implementation_sha256"]
            self.assertEqual(pinned, implementation_sha256())
            read_source = Path.read_bytes
            def changed(path):
                data = read_source(path)
                return data + b"# revised execution\n" if path.name == "swing_paths.py" else data
            with patch.object(Path, "read_bytes", changed):
                self.assertNotEqual(implementation_sha256(), pinned)
                with self.assertRaisesRegex(ValueError, "implementation differs"):
                    freeze(ledger, key, asof=at)
                with self.assertRaisesRegex(ValueError, "implementation differs"):
                    evaluate(cohort, evidence([]), cohort_sha256=sha(cohort))

    def test_five_day_false_breakout_rate_excludes_all_pending_windows(self):
        episodes = [_confirmed(CONFIRM), _confirmed(CONFIRM, "BBB", 2)]
        cohort = {**_cohort({}), "episodes": episodes}
        for complete in (False, True):
            window = [day_shift(CONFIRM, n) for n in range(1, 6 if complete else 3)]
            cutoff = session_close_utc(window[-1]).isoformat()
            labels = evidence([bar(day, c=98 if i == 0 else 104) for i, day in enumerate(window)],
                              verified_through=str(window[-1]))
            labels["asof_utc"] = cutoff
            other = episodes[1]["security_id"]
            labels["securities"][other] = {**labels["securities"][SEC], "security_id": other,
                                            "bars": [bar(day) for day in window]}
            report = evaluate(cohort, labels, cohort_sha256=sha(cohort))["false_breakout_5d"]
            self.assertEqual(report["rate"], .5 if complete else None)
            self.assertEqual(report["mature_windows"], 2 if complete else 0)
            self.assertEqual(report["early_breaches"], 0 if complete else 1)

    def test_cash_paths_remain_in_coverage_but_do_not_count_as_exit_trials(self):
        canceled = _confirmed(CONFIRM, available=frame(ENTER, [])["available"])
        cohort = {**_cohort({}), "episodes": [canceled]}
        labels = evidence([bar(ENTER, c=98), bar(day_shift(ENTER, 1))])
        report = evaluate(cohort, labels, cohort_sha256=sha(cohort))
        summary = report["comparisons"]["structure_exit_vs_fixed/10"]
        self.assertEqual(summary["dates"], 0)
        self.assertEqual(summary["event_count"], 0)
        self.assertEqual(summary["distinct_issuers"], 0)
        self.assertEqual(summary["excluded_before_comparison"], {"cash|cash": 1})
        horizon = next(pair for pair in report["paired_paths"] if
                       pair["family"] == "structure_exit_vs_fixed" and pair["horizon"] == 10)
        self.assertFalse(horizon["comparison_eligible"])
        self.assertEqual(horizon["baseline"]["reason"], "invalidation_known_before_open")
        cohort = {**cohort, "episodes": [_confirmed(CONFIRM)]}
        report = evaluate(cohort, evidence([bar(ENTER)]), cohort_sha256=sha(cohort))
        summary = report["comparisons"]["structure_exit_vs_fixed/10"]
        self.assertEqual(summary["mature_or_explicitly_unavailable"], 1)
        self.assertEqual(summary["excluded_before_comparison"], {})

    def test_sic_controls_pad_legacy_codes_and_ignore_placeholders(self):
        candidates = [row(ORIGIN, sym, index) for index, sym in enumerate(("A", "B", "C", "D"), 1)]
        for item, sic in zip(candidates, ("100", "0100", "1040", "9999")):
            item["industry"] = sic
        self.assertEqual([item["symbol"] for item in _peers(candidates[0], candidates[1:])], ["B"])
        other = {**candidates[0], "industry": "9999"}
        self.assertFalse(_peers(other, candidates[1:]))

    def test_fcf_yield_needs_complete_split_basis_at_snapshot_time(self):
        items = [row(ORIGIN, f"A{i:02d}", i, priority=i, fcf=5.) for i in range(1, 17)]
        target = items[-1]
        item = target["financial_review"]
        item["metrics"]["fcf_per_current_share"] = 8.
        item["derived_operands"]["current_shares"]["end"] = str(PREVIOUS)
        base_frame = frame(ORIGIN, items)
        base_frame["meta"]["generated_at_utc"] = session_close_utc(ORIGIN).replace(minute=20).isoformat()
        def ranking():
            result, = _cohort({str(ORIGIN): base_frame})["ranking"]
            return result
        self.assertIsNone(ranking()["candidate_scores"][target["security_id"]])
        proof = {"security_id": target["security_id"], "share_basis_id": "common", "source": "frozen source",
                 "share_period_end": str(PREVIOUS), "price_session": str(ORIGIN),
                 "known_at_utc": session_close_utc(ORIGIN).replace(minute=10).isoformat(),
                 "splits": [[str(ORIGIN), .5]]}
        item["market_share_bases"] = [proof]
        result = ranking()
        self.assertAlmostEqual(result["candidate_scores"][target["security_id"]], .04)
        self.assertFalse(result["financial_additions"])  # 4%, not 8%, loses to the 5% names.
        proof["splits"] = []
        self.assertTrue(ranking()["financial_additions"])  # Sourced proof of no split is different from missing.
        proof["known_at_utc"] = session_close_utc(ORIGIN).replace(minute=25).isoformat()
        self.assertIsNone(ranking()["candidate_scores"][target["security_id"]])

    def test_mixed_ranking_keeps_missing_absolute_returns_as_known_zero_delta(self):
        left = [row(ORIGIN, f"A{i:02d}", i, priority=i, fcf=i) for i in range(1, 17)]
        right = [row(CONFIRM, f"A{i:02d}", i, priority=i) for i in range(1, 17)]
        cohort = _cohort({str(ORIGIN): frame(ORIGIN, left), str(CONFIRM): frame(CONFIRM, right)})
        dates = [day_shift(ORIGIN, i) for i in range(1, 12)]
        prices = evidence([])
        template = prices["securities"].pop(SEC)
        for j, item in enumerate(left, 1):
            key = item["security_id"]
            prices["securities"][key] = {**template, "security_id": key, "bars": [
                bar(day, h=120, c=115 if j == 16 else 100) for day in dates if j != 2 or day != dates[-1]]}
        outcome = evaluate(cohort, prices, cohort_sha256=sha(cohort))
        comparison = outcome["comparisons"]["financial_candidate_vs_top15/10"]
        self.assertEqual(comparison["dates"], 2)
        self.assertEqual(comparison["dates_with_paired_absolute_returns"], 1)
        self.assertEqual(comparison["matched_settled"], 1)
        self.assertEqual(comparison["scorable_delta_rows"], 2)
        self.assertEqual(comparison["known_zero_rows_missing_absolute"], 1)
        self.assertAlmostEqual(comparison["paired_delta_net_15"]["mean"], .005)
        self.assertAlmostEqual(comparison["missing_adverse"], .005)
        self.assertAlmostEqual(comparison["missing_favorable"], .005)
        self.assertEqual(set(comparison["issuer_attribution_date_weighted_net_15"]) - {
            cik for cik, amount in comparison["issuer_attribution_date_weighted_net_15"].items() if amount == 0.
        }, {"0000000001", "0000000016"})

    def test_delay_equal_hold_slices_use_joint_actual_exposure(self):
        confirmations = [day_shift(CONFIRM, n) for n in (0, 10, 15)]
        prices = [bar(day_shift(CONFIRM, n)) for n in range(1, 45)]
        book = PriceBook(evidence(prices))
        rows = []
        for day in confirmations:
            _episode_paths(book, _confirmed(day), rows)
        delays = [r for r in rows if r["family"] == "delay_5_equal_hold" and r["horizon"] == 10]
        self.assertEqual(len(delays), 3)
        self.assertEqual(delays[0]["exposure_window"], [str(ENTER), str(day_shift(ENTER, 14))])
        summary = summarize(delays, horizon=10, calendar_start=str(CONFIRM), calendar_end=str(confirmations[-1]),
                            main=False)
        self.assertEqual([[win["session"] for win in part["windows"]] for part in summary["nonoverlapping_partitions"]],
                         [[str(confirmations[0]), str(confirmations[2])], [str(confirmations[1])]])

    def test_matched_issuer_is_credited_only_for_its_own_leg(self):
        path = lambda value: {"net_15": value, "net_30": value, "status": "settled"}
        pairs = []
        for day, benchmark, ret in [(ORIGIN, "B", .10), (CONFIRM, "C", .01)]:
            pairs.append(_pair("confirmation_vs_matched", 10,
                               {"session": str(day), "available": frame(day, [])["available"],
                                "target": {"cik": "A", "security_id": "A:1"}},
                               path(0.), path(ret), counterpart={"cik": benchmark}))
        result = summarize(pairs, horizon=10, calendar_start=str(ORIGIN), calendar_end=str(CONFIRM), main=True)
        self.assertEqual(result["largest_absolute_contributor"], "B")
        self.assertEqual(result["issuer_attribution_date_weighted_net_15"], {"A": 0., "B": -.05, "C": -.005})
        self.assertAlmostEqual(result["without_largest_contributor"]["mean"], -.01)

    def test_expired_episode_is_in_waiting_intent_to_treat(self):
        frames = {str(PREVIOUS): frame(PREVIOUS, [row(PREVIOUS, "AAA", 1)])}
        for count in range(6):
            day = day_shift(ORIGIN, count)
            frames[str(day)] = frame(day, [row(day, "AAA", 1, "WATCH")])
        cohort = _cohort(frames)
        episode, = cohort["episodes"]
        self.assertEqual(episode["status"], "expired")
        planned = day_shift(ORIGIN, 1)
        dates = [day_shift(planned, d) for d in range(10)]
        report = evaluate(cohort, evidence([bar(day) for day in dates]), cohort_sha256=sha(cohort))
        pair, = (r for r in report["paired_paths"] if r["horizon"] == 10 and r["family"] == "wait_vs_immediate")
        self.assertEqual(pair["candidate"]["status"], "cash")
        self.assertAlmostEqual(pair["baseline"]["net_15"], .037)
        self.assertAlmostEqual(report["opportunity_cost_when_waiting_stays_cash"]["10"]["mean"], .037)

    def test_medium_comparison_keeps_four_distinct_cohorts(self):
        rows = [row(ORIGIN, f"A{i}", i) for i in range(1, 5)]
        for item, conditions in zip(rows, ((False, False), (False, True), (True, False), (True, True))):
            item["medium_review"] = {"short_confirmed": conditions[0], "medium_trend_damaged": conditions[1],
                                     "completed_week": {"sma10": 100}}
        cohort = _cohort({str(ORIGIN): frame(ORIGIN, rows)})
        self.assertEqual(len(cohort["medium"]), 4)
        report = evaluate(cohort, evidence([]), cohort_sha256=sha(cohort))
        self.assertEqual(len(report["medium_summary"]), 8)
        self.assertTrue(all(item["rows"] == 1 for item in report["medium_summary"].values()))
        self.assertFalse(report["medium_held_despite_short_break_60d"])

    def test_freeze_both_protocols_and_choose_independent_same_day_controls(self):
        for variant in (BREAKOUT_VERSION, PULLBACK_VERSION):
            def on(day, states):
                return [row(day, symbol, i, state, setup=variant) for i, (symbol, state) in enumerate(states, 1)]
            frames = {
                str(PREVIOUS): frame(PREVIOUS, on(PREVIOUS, [("AAA", "WORK"), ("BBB", "WORK"), ("CCC", "WORK")])),
                str(ORIGIN): frame(ORIGIN, on(ORIGIN, [("AAA", "WATCH"), ("BBB", "WATCH"), ("CCC", "WATCH")])),
                str(CONFIRM): frame(CONFIRM, on(CONFIRM, [("AAA", "CONF"), ("BBB", "WATCH"), ("CCC", "WATCH")])),
            }
            cohort = _cohort(frames, setup=variant)
            self.assertEqual([item["status"] for item in cohort["episodes"]], ["confirmed", "unknown_continuity", "unknown_continuity"])
            pair, = cohort["confirmation_pairs"]
            self.assertEqual(pair["peer"]["symbol"], "BBB")
            self.assertEqual(pair["unconfirmed_pool_size"], 2)
            again = _cohort({key: {**value, "rows": list(reversed(value["rows"]))} for key, value in frames.items()}, setup=variant)
            self.assertEqual(pair, again["confirmation_pairs"][0])
            report = evaluate(cohort, evidence([]), cohort_sha256=sha(cohort))
            self.assertFalse(report["production_promotion"])
            self.assertEqual(report["comparisons"]["wait_vs_immediate/10"]["verdict"], "insufficient_evidence")
            self.assertEqual(report["false_breakout_5d"] is not None, variant == BREAKOUT_VERSION)
            with self.assertRaisesRegex(ValueError, "cohort hash"):
                evaluate(cohort, evidence([]), cohort_sha256="0" * 64)

    def test_registered_scope_and_receipt_requirements(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            ledger = Ledger(base/"evidence.db", snapshot_root=base/"archives")
            before = utc("2025-11-02T20:00:00Z")
            now = utc("2025-11-07T22:00:00Z")
            with self.assertRaisesRegex(ValueError, "before"):
                register(ledger, _spec("forward"), now=now)
            key = register(ledger, _spec("forward"), now=before)
            meta = {**_spec("forward"), "session": str(ORIGIN), "decision_bytes_pinned": True,
                    "generated_at_utc": "2025-11-03T21:25:00Z", "manifest_sha256": "fixture", "daily": []}
            with ledger.transaction() as db:
                append(db, "snapshot", "snapshot", None, meta, now)
            frozen = freeze(ledger, key, asof=now)
            self.assertEqual(frozen["session_coverage"][str(ORIGIN)]["status"], "publication_proof_unavailable")
            with ledger.transaction() as db:
                append(db, "receipt", "receipt", "snapshot", {
                    "style": "production", "session": str(ORIGIN), "first_readable_at_utc": "2025-11-04T15:00:00Z",
                    "receipt_sha256": "fixture", "status": "published"}, now)
            frozen = freeze(ledger, key, asof=now)
            self.assertEqual(frozen["session_coverage"][str(ORIGIN)]["timing"], "first_readable")
            self.assertEqual(execution_day(frozen["ranking"][0]["available"]), ENTER)

    def test_rank_swaps_only_evidenced_contiguous_risk_blocks(self):
        rows = [row(ORIGIN, f"A{i:02d}", i, priority=i, fcf=i) for i in range(1, 17)]
        rows[0]["s2_reason"] = "soft_exit_grace"
        cohort = _cohort({str(ORIGIN): frame(ORIGIN, rows)})
        ranks, = cohort["ranking"]
        self.assertEqual(ranks["financial_additions"], ["A16:0000000016"])
        self.assertEqual(ranks["financial_removals"], ["A01:0000000001"])
        self.assertEqual([item["symbol"] for item in ranks["groups"]["daily_grace"]], ["A01"])
        rows[-1]["financial_review"] = None
        cohort = _cohort({str(ORIGIN): frame(ORIGIN, rows)})
        report = evaluate(cohort, evidence([]), cohort_sha256=sha(cohort))
        verdict = report["comparisons"]["financial_candidate_vs_top15/10"]
        self.assertEqual(verdict["selection_delta"], 0)
        self.assertEqual(verdict["verdict"], "no_membership_change")

    def test_date_weights_not_row_weights_and_calendar_gaps(self):
        valid = lambda value: {"net_15": value, "net_30": value, "status": "settled"}
        rows = [{"session": str(day), "event_id": event, "issuer_keys": [event],
                 "candidate": valid(p), "baseline": valid(0)}
                for day, p, event in [(ORIGIN, .03, "1"), (ORIGIN, .05, "2"), (day_shift(ORIGIN, 12), -.02, "3")]]
        result = summarize(rows, horizon=10, calendar_start=str(ORIGIN), calendar_end=str(day_shift(ORIGIN, 25)), main=True)
        self.assertAlmostEqual(result["paired_delta_net_15"]["mean"], .01)
        self.assertEqual(result["occupied_calendar_blocks"], 2)
        self.assertEqual(result["verdict"], "insufficient_evidence")
