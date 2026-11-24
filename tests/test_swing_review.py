from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from ai_value_scanner.swing.events import known_events, load_calendar, timestamp
from ai_value_scanner.swing.opening import opening_review, render_opening_cards
from ai_value_scanner.swing.setups import evaluate_close, next_session, price_space, validate_close_context


def sessions(count, first=date(2025, 1, 2)):
    series = [first]
    while len(series) < count:
        series.append(next_session(series[-1]))
    return series


def bar(day, close=103, *, opening=None, high=105, low=100, volume=100):
    return dict(t=day.isoformat(), o=close if opening is None else opening, h=high, l=low, c=close, v=volume)


def setup(case, kind="breakout"):
    return case["patterns"][kind]["state"]


def fixture():
    days = sessions(28)
    rows = [bar(day) for day in days[:26]]
    rows[2].update(h=114)
    rows[3].update(h=114)
    rows[-1] = bar(days[25], 106, high=109, volume=150)
    return days, rows


class SwingCloseTests(TestCase):
    def test_breakout_strict_close_inclusive_volume_and_signal_bar_exclusion(self):
        days, rows = fixture()
        signal_day = days[25]
        state = evaluate_close(rows, signal_day)
        mark = setup(state)
        self.assertEqual(mark["status"], "confirmed")
        self.assertEqual(mark["confirmed"], signal_day.isoformat())
        self.assertEqual(mark["stop"], 105)
        self.assertEqual(mark["evidence"]["prior_volume_median"], 100)
        self.assertEqual(mark["evidence"]["volume_ratio"], 1.5)
        self.assertEqual(mark["resistance"]["price"], 114)
        self.assertEqual(mark["resistance"]["formed_session"], days[3].isoformat())
        self.assertEqual(mark["resistance"]["confirmed_session"], days[5].isoformat())
        validate_close_context(json.loads(json.dumps(state)), signal_day.isoformat())
        for updates in (dict(c=105, o=105), dict(v=149.99)):
            altered = [*rows[:-1], {**rows[-1], **updates}]
            self.assertEqual(setup(evaluate_close(altered, signal_day))["status"], "watching")
        no_resistance = [bar(day) for day in days[:25]] + [rows[25]]
        missing = evaluate_close(no_resistance, signal_day)["patterns"]["breakout"]
        self.assertIsNone(missing["state"]["resistance"])
        self.assertEqual(missing["space"]["status"], "resistance_unknown")

    def test_complete_twenty_day_window_boundaries_and_zero_median(self):
        days = sessions(21)
        rows = [bar(day, high=115) for day in days[:-1]] + [bar(days[-1], 116, high=117, volume=150)]
        self.assertEqual(setup(evaluate_close(rows, days[-1]))["status"], "confirmed")
        wide = [{**r, "h": 115.01} for r in rows[:-1]] + rows[-1:]
        self.assertEqual(setup(evaluate_close(wide, days[-1]))["reason"], "platform_too_wide")
        self.assertEqual(setup(evaluate_close(rows[1:], days[-1]))["status"], "insufficient")
        self.assertEqual(setup(evaluate_close(rows[:12] + rows[13:], days[-1]))["status"], "insufficient")
        zero = [{**r, "v": 0} for r in rows[:-1]] + rows[-1:]
        self.assertEqual(setup(evaluate_close(zero, days[-1]))["reason"], "nonpositive_volume_baseline")
        decimal = [bar(day, 13, high=14.03, low=12.20) for day in days[:-1]]
        decimal += [bar(days[-1], 14.10, high=14.20, low=14, volume=150)]
        self.assertEqual(setup(evaluate_close(decimal, days[-1]))["status"], "confirmed")
        decimal[0]["h"] = 14.04
        self.assertEqual(setup(evaluate_close(decimal, days[-1]))["reason"], "platform_too_wide")

    def test_resistance_plateau_can_start_before_the_lookback(self):
        days = sessions(146)
        rows = [bar(day) for day in days[:-1]]
        for index in (3, 4, 5, 6):
            rows[index]["h"] = 114
        rows.append(bar(days[-1], 106, high=109, volume=150))
        resistance = setup(evaluate_close(rows, days[-1]))["resistance"]
        self.assertEqual(resistance["formed_session"], days[6].isoformat())
        self.assertEqual(resistance["confirmed_session"], days[8].isoformat())

    def test_split_rebase_and_completed_week(self):
        days, rows = fixture()
        first = evaluate_close(rows, days[25])
        case = evaluate_close(
            rows + [bar(days[26], close=54, high=55, low=52, volume=200)], days[26],
            splits=[(days[26].isoformat(), .5), (days[27].isoformat(), .1)], prior=first,
        )
        self.assertEqual(setup(case)["stop"], 52.5)
        self.assertEqual(setup(case)["resistance"]["price"], 57)
        self.assertEqual(setup(case)["confirmed"], days[25].isoformat())
        self.assertFalse(case["patterns"]["breakout"]["new_confirmation"])
        self.assertNotEqual(case["weekly"]["completed_week_end"], days[26].isoformat())
        without_seed = evaluate_close(rows + [bar(days[26], close=54, high=55, low=52, volume=200)], days[26],
                                      splits=[(days[26].isoformat(), .5)])
        self.assertEqual(case["patterns"], without_seed["patterns"])

    def test_breakout_expires_and_cooldown_uses_twenty_full_new_sessions(self):
        days, rows = fixture()
        following = sessions(42, days[25])[1:]
        rows += [bar(day, 108, high=109, low=107, volume=100) for day in following]
        expired = setup(evaluate_close(rows, following[19]))
        self.assertEqual(expired["reason"], "breakout_expired")
        check = following[39]
        override = [*rows[:-2], bar(check, 110, high=111, low=107, volume=150), rows[-1]]
        self.assertEqual(setup(evaluate_close(override, check))["status"], "invalidated")
        reset = rows[:-1] + [bar(following[-1], 110, high=111, low=107, volume=150)]
        self.assertEqual(setup(evaluate_close(reset, following[-1]))["confirmed"], following[-1].isoformat())

    def test_pullback_wait_first_reclaim_and_failure_priority(self):
        days = sessions(207)
        rows = [bar(day, p, high=p+1, low=p-1) for day, p in zip(days[:199], (80+i*.1 for i in range(199)))]
        rows.append(bar(days[199], 95, high=96, low=94, volume=50))
        waiting = evaluate_close(rows, days[199])
        self.assertEqual(setup(waiting, "pullback")["reason"], "pullback_observed_waiting_reclaim")
        for close, reason in ((100, "first_close_back_above_sma50"), (93, "pullback_low_breached_before_reclaim")):
            new = rows + [bar(days[200], close, high=101, low=92)]
            mark = setup(evaluate_close(new, days[200], prior=waiting), "pullback")
            self.assertEqual(mark["reason"], reason)
            self.assertEqual(mark["stop"], 94)
        waiting_rows = rows + [bar(day, 95, high=96, low=94, volume=50) for day in days[200:205]]
        timeout = waiting_rows + [bar(days[205], 100, high=101, low=95)]
        self.assertEqual(setup(evaluate_close(timeout, days[205]), "pullback")["reason"], "reclaim_window_expired")

    def test_price_space_distinguishes_absent_and_crossed_levels(self):
        self.assertEqual(price_space(100, 96, 110)["reward_risk"], 2.5)
        self.assertEqual(price_space(106, 96, 110)["reward_risk"], .4)
        self.assertEqual(price_space(96, 96, 110)["status"], "stop_breached")
        self.assertEqual(price_space(112, 96, 110)["status"], "target_passed")
        self.assertIsNone(price_space(100, 96, None)["reward_risk"])

    def test_pullback_tail_after_archive_gap_is_unknown(self):
        days = sessions(406)
        rows = [bar(day, p, high=p+1, low=p-1) for day, p in zip(days[:199], (80+i*.1 for i in range(199)))]
        rows.extend([bar(days[199], 95, high=96, low=94, volume=50),
                     bar(days[200], 100, high=101, low=92)])
        rows.extend(bar(day, 102, high=103, low=101) for day in days[201:])
        before = evaluate_close(rows, days[-2])
        seeded = setup(evaluate_close(rows[-205:], days[-1], prior=before), "pullback")
        self.assertEqual(seeded["status"], "confirmed")
        without_prior = setup(evaluate_close(rows[-205:], days[-1]), "pullback")
        self.assertEqual(without_prior["reason"], "pullback_continuity_unknown")


class SwingOpeningTests(TestCase):
    def test_pre_post_market_quotes_and_actual_open_are_independent(self):
        days, rows = fixture()
        close = evaluate_close(rows, days[25])
        text = days[26].isoformat()
        pre = timestamp(text + "T13:59:10Z")
        qshot = dict(quote=dict(kind="quote", timestamp=text+"T13:59:00Z", received_at=text+"T13:59:01Z",
                                price=53, bid=52.9, ask=53.1, bid_at=text+"T13:59:00Z", ask_at=text+"T13:59:00Z",
                                feed="iex", source="quote archive"),
                     split_status="verified", split_checked_at=text+"T13:55:00Z",
                     split_source="issuer split archive", splits=[(text,.5)])
        card = opening_review(close, qshot, asof=pre)
        self.assertEqual(card["quote"]["phase"], "pre_open_indication")
        self.assertEqual(card["quote_gap"], 0)
        self.assertIsNotNone(card["quote"]["spread_bps"])
        self.assertEqual(card["patterns"]["breakout"]["stop"], 52.5)
        self.assertIn("IEX", render_opening_cards({"EXM": card}))
        post = timestamp(text+"T14:31:01Z")
        actual = dict(price=53.1, kind="daily_bar", session=text, received_at=text+"T14:30:05Z",
                      source="SIP daily bar", feed="sip")
        after = opening_review(close, {**qshot, "quote": {"kind": "daily_bar"}, "actual_open": actual}, asof=post)
        self.assertEqual(after["quote_issue"], "daily_bar_has_no_executable_timestamp")
        self.assertIsNone(after["actual_open"]["timestamp"])
        self.assertIsNone(after["paper_entry_price"])
        self.assertIsNone(after["patterns"]["breakout"]["space"])
        future = {**qshot, "quote": {**qshot["quote"], "received_at":text+"T14:00:00Z"}}
        self.assertEqual(opening_review(close, future, asof=pre)["quote_issue"], "quote_not_yet_observable")
        unverified = {key: value for key, value in qshot.items() if key != "split_checked_at"}
        self.assertIsNone(opening_review(close, unverified, asof=pre)["quote_gap"])
        omitted = {key: value for key, value in qshot.items() if key != "splits"}
        card = opening_review(close, omitted, asof=pre)
        self.assertIsNone(card["quote_gap"])
        self.assertIsNone(card["patterns"]["breakout"]["space"])
        self.assertEqual(opening_review(close, {**omitted, "splits": []}, asof=pre)["split"]["factor"], 1)
        delayed = dict(price=54, kind="opening_trade", session=text, timestamp=text+"T14:30:02Z",
                       received_at=text+"T14:30:03Z", source="SIP opening trade", feed="sip")
        self.assertAlmostEqual(opening_review(close, {**qshot, "actual_open": delayed}, asof=post)["actual_open_gap"], 54/53-1)
        self.assertIsNone(opening_review(close, {**qshot, "actual_open": {**delayed, "kind": "trade"}}, asof=post)["actual_open"])


class CalendarTests(TestCase):
    def test_unsourced_revision_and_elapsed_premarket_do_not_hide_upcoming(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.csv"
            path.write_text(
                "event_id,symbol,cik,event_type,event_date,session,known_at_utc,certainty,source\n"
                "resched,EXM,123,earnings,2026-11-26,postmarket,2026-11-19T16:00:00Z,confirmed,IR\n"
                "resched,EXM,123,earnings,2026-11-27,postmarket,2026-11-23T16:00:00Z,confirmed,\n"
                "morning,EXM,123,conference,2026-11-23,premarket,2026-11-19T16:00:00Z,confirmed,IR\n"
                "future,EXM,123,earnings,2026-11-24,premarket,2026-11-19T16:00:00Z,confirmed,IR\n"
            )
            rows, _ = load_calendar(path)
            result = known_events(rows, "EXM", 123, decision_day=date(2026,11,23), asof=timestamp("2026-11-23T22:00:00Z"))
            self.assertEqual([event["event_id"] for event in result["events"]], ["future", "resched"])
            self.assertEqual(result["elapsed_events"][0]["event_id"], "morning")
            rescheduled = result["events"][1]
            self.assertIsNone(rescheduled["event_date"])
            self.assertIsNone(rescheduled["revisions"][-1]["event_date"])
            self.assertEqual(rescheduled["certainty"], "unknown")
    def test_only_known_issuer_revisions_and_archived_bytes_are_preserved(self):
        header = "event_id,symbol,cik,event_type,event_date,session,known_at_utc,certainty,source\n"
        earlier = "ec,EXM,123,earnings,2026-11-24,premarket,2026-11-19T16:00:00Z,estimated,issuer IR\n"
        later = "ec,EXM,123,earnings,2026-11-30,postmarket,2026-11-25T16:00:00Z,confirmed,issuer IR\n"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.csv"
            path.write_text(header + earlier)
            rows, original_digest = load_calendar(path)
            asof = timestamp("2026-11-23T22:00:00Z")
            frozen = known_events(rows, "EXM", 123, decision_day=date(2026,11,23), asof=asof)
            path.write_text(header + earlier + later)
            rows, revised_digest = load_calendar(path)
            self.assertNotEqual(original_digest, revised_digest)
            self.assertEqual(frozen, known_events(rows, "EXM", 123, decision_day=date(2026,11,23), asof=asof))
            update = known_events(rows, "EXM", 123, decision_day=date(2026,11,25), asof=timestamp("2026-11-25T22:00:00Z"))
            self.assertEqual(update["events"][0]["event_date"], "2026-11-30")
            self.assertEqual(len(update["events"][0]["revisions"]), 2)
            self.assertEqual(known_events(rows, "EXM", 321, decision_day=date(2026,11,23), asof=asof)["status"], "unknown")
