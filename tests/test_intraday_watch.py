"""Intraday watch monitor tests (offline, synthetic fixtures).

Covers symbol scopes (report/top/attention/all/custom), row computation and
flags against completed daily bars, pre-earnings carry-over, markdown
rendering, and the read-only runner contract (no decision-snapshot writes).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd

from ai_value_scanner import intraday_market as market
from ai_value_scanner.decision import build_stock_decisions
from ai_value_scanner.market_calendar import is_session_day
from ai_value_scanner.scanner import AlpacaClient
from pathlib import Path


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "iw_" + name.replace(".py", ""), module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


iw = _load_script("intraday_watch.py")
preview = _load_script("render_intraday_preview.py")
NOW = datetime(2026, 11, 24, 16, 0, tzinfo=timezone.utc)
POLICY = market.IntradayPolicy()


def _decision(symbol, priority, action="PRIORITY_REVIEW", risks=None):
    return {
        "symbol": symbol,
        "priority": priority,
        "action_state": action,
        "quality": {
            "grade": "A",
            "score": 0.8,
            "risks": risks or [],
        },
        "entry": {"state": "ENTRY_READY", "score": 0.9, "risks": []},
    }


def _flat_bars(close=100.0, high=100.0, low=100.0, sessions=250):
    before = NOW.date() - timedelta(days=1)
    result = []
    while len(result) < sessions:
        if is_session_day(before):
            result.append({
                "t": f"{before.isoformat()}T05:00:00Z",
                "o": close, "h": high, "l": low, "c": close, "v": 1000,
            })
        before -= timedelta(days=1)
    return list(reversed(result))


def _snapshot(price=100.0, *, age=5, session_open=100.0):
    return {
        "latestTrade": {"p": price, "t": (NOW - timedelta(seconds=age)).isoformat()},
        "dailyBar": {
            "t": "2026-11-24T05:00:00Z", "o": session_open, "h": max(price, session_open),
            "l": min(price, session_open), "c": session_open, "v": 1000,
        },
    }


def _observation(snapshot=None, bars=None, splits=(), now=NOW):
    return market.prepare_observation(
        snapshot if snapshot is not None else _snapshot(), bars if bars is not None else _flat_bars(),
        splits, received_at=now, now=now, policy=POLICY,
    )


class FakeClient:
    def get_snapshots(self, symbols, chunk_size):
        return {symbol: _snapshot() for symbol in symbols}

    def get_daily_bars(self, symbols, start_iso, chunk_size):
        return {symbol: _flat_bars() for symbol in symbols}

    def get_corporate_action_splits(self, symbols, start_iso, end_iso, *, invalid_events=None):
        return {}


class TestSymbolScopes(unittest.TestCase):
    def test_report_scope_preserves_report_order(self) -> None:
        decisions = [_decision("ADI", 1), _decision("CTAS", 2), _decision("WDAY", 3)]
        report = (
            "- [Full Report →](./detailed/CTAS.md)\n"
            "- [Full Report →](./detailed/ADI.md)\n"
            "- [Full Report →](./detailed/WDAY.md)\n"
            "- [Full Report →](./detailed/ADI.md)\n"
        )
        symbols = iw.select_symbols(
            decisions, scope="report", action_list_text=report
        )
        self.assertEqual(symbols, ["CTAS", "ADI", "WDAY"])

    def test_report_scope_can_union_weekly(self) -> None:
        report = "- [Full Report →](./detailed/ADI.md)\n"
        weekly = "- [Full Report →](./detailed/MSFT.md)\n"
        symbols = iw.select_symbols(
            [_decision("ADI", 1)],
            scope="report",
            action_list_text=report,
            weekly_review_text=weekly,
            include_weekly=True,
        )
        self.assertEqual(symbols, ["ADI", "MSFT"])

    def test_attention_scope_filters_and_sorts(self) -> None:
        decisions = [
            _decision("A", 2, "PRIORITY_REVIEW"),
            _decision("B", 1, "WATCH_PULLBACK"),
            _decision("C", 3, "HOLD_MONITOR"),
            _decision("D", 4, "WATCH_BREAKOUT"),
            _decision("E", 5, "AVOID"),
        ]
        symbols = iw.select_symbols(decisions, scope="attention")
        self.assertEqual(symbols, ["B", "A", "D"])

    def test_top_scope_limits_to_fifteen(self) -> None:
        decisions = [_decision(f"S{i}", i) for i in range(1, 21)]
        symbols = iw.select_symbols(decisions, scope="top")
        self.assertEqual(len(symbols), 15)
        self.assertEqual(symbols[0], "S1")

    def test_custom_symbols_override_scope(self) -> None:
        symbols = iw.select_symbols(
            [_decision("ADI", 1)], scope="report", custom=" adi, ctas  msft "
        )
        self.assertEqual(symbols, ["ADI", "CTAS", "MSFT"])


class TestQuoteSelection(unittest.TestCase):
    def test_fresh_trade_beats_completed_minute_that_failed_age_gate(self):
        now = datetime(2026, 11, 24, 16, 2, 30, tzinfo=timezone.utc)
        snapshot = _snapshot(109, age=15)
        snapshot["minuteBar"] = {"c": 110, "t": "2026-11-24T15:59:00Z"}
        obs = _observation(snapshot, now=now)
        self.assertEqual(obs.quote_status, "fresh")
        self.assertEqual((obs.quote.source, obs.quote.price), ("latestTrade", 109))

    def test_new_minute_keeps_its_own_price_and_interval(self):
        snapshot = _snapshot()
        snapshot["latestTrade"] = {"p": 100, "t": "2026-11-23T20:59:00Z"}
        snapshot["minuteBar"] = {"c": 110, "t": "2026-11-24T15:59:00Z"}
        obs = _observation(snapshot)
        self.assertEqual(obs.quote.price, 110)
        self.assertEqual(obs.quote.source, "minuteBar")
        self.assertEqual(obs.quote.session.isoformat(), "2026-11-24")
        self.assertEqual(obs.quote.timestamp.isoformat(), "2026-11-24T15:59:00+00:00")
        self.assertEqual(obs.quote.interval_end, NOW)
        self.assertEqual(obs.provisional_bars[-1]["c"], 110)

    def test_latest_valid_trade_wins_when_after_a_completed_minute(self):
        snapshot = _snapshot(109)
        snapshot["minuteBar"] = {"c": 110, "t": "2026-11-24T15:58:00Z"}
        self.assertEqual(_observation(snapshot).quote.source, "latestTrade")

    def test_prior_session_and_stale_quote_have_no_price_signals(self):
        previous = _snapshot()
        previous["latestTrade"]["t"] = "2026-11-23T20:59:00Z"
        for snapshot, reason in ((previous, "prior_session_quote"), (_snapshot(age=300), "stale_quote")):
            with self.subTest(reason=reason):
                row = iw.compute_row("ADI", None, _observation(snapshot))
                self.assertEqual(row["quote_status"], reason)
                self.assertIsNone(row["pct_change"])
                self.assertEqual(row["flags"], [])

    def test_future_and_missing_timestamps_are_distinguished(self):
        for trade, status in (
            ({"p": 500, "t": "2026-11-24T16:00:01Z"}, "future_quote"),
            ({"p": 500}, "missing_quote_timestamp"),
            ({"p": 500, "t": "2026-11-24T15:59:55"}, "missing_quote_timestamp"),
        ):
            with self.subTest(status=status):
                obs = _observation({"latestTrade": trade})
                self.assertIsNone(obs.quote)
                self.assertEqual(obs.quote_status, status)

    def test_daily_denotes_session_and_has_no_quote_age(self):
        obs = _observation({"dailyBar": _snapshot()["dailyBar"]})
        row = iw.compute_row("ADI", None, obs)
        self.assertEqual(row["price"], 100)
        self.assertEqual(row["quote_status"], "daily_price_without_tick_time")
        self.assertIsNone(row["quote_age_seconds"])

    def test_pre_post_and_half_day_periods(self):
        for when, status in (
            ("2026-11-24T14:00:00+00:00", "pre_market"),
            ("2026-11-24T21:00:00+00:00", "post_market"),
            ("2026-11-27T18:00:00+00:00", "post_market"),
            ("2026-11-28T16:00:00+00:00", "market_closed"),
        ):
            with self.subTest(when=when):
                self.assertEqual(market.market_period(datetime.fromisoformat(when)), status)


class TestRowComputation(unittest.TestCase):
    def test_flags_for_below_and_crossed_levels(self):
        bars = _flat_bars()
        bars[-1].update(c=105.0, h=105.0)
        row = iw.compute_row("ADI", _decision("ADI", 1), _observation(_snapshot(90.0), bars))
        self.assertAlmostEqual(row["price"], 90)
        self.assertAlmostEqual(row["pct_change"], 90.0 / 105.0 - 1.0)
        self.assertAlmostEqual(row["vs50"], 90.0 / 100.1 - 1.0)
        for flag in ("S50↓", "S50✖", "S200↓", "S200✖", "MOVE", "LO"):
            self.assertIn(flag, row["flags"])

    def test_extended_and_near_high_flags(self):
        row = iw.compute_row("ADI", _decision("ADI", 1), _observation(_snapshot(165.0)))
        self.assertIn("EXT", row["flags"])
        self.assertIn("HI", row["flags"])

    def test_missing_snapshot_and_bars_are_safe(self):
        row = iw.compute_row("ADI", None, _observation({}, []))
        self.assertIsNone(row["price"])
        self.assertEqual(row["flags"], [])

    def test_pre_earnings_carried_from_decision(self):
        decision = _decision("ADI", 1, risks=[{"code": "pre_earnings_window_risk"}])
        self.assertIn("PE", iw.compute_row("ADI", decision, _observation())["flags"])

    def test_forward_and_reverse_splits_preserve_returns_and_raw_input(self):
        for factor in (0.5, 2):
            with self.subTest(factor=factor):
                bars = _flat_bars()
                obs = _observation(_snapshot(100 * factor, session_open=100 * factor), bars, [
                    ("2026-11-24", factor), ("2026-11-24", factor), ("2026-12-01", 0.1)
                ])
                row = iw.compute_row("ADI", None, obs)
                self.assertEqual(row["pct_change"], 0)
                self.assertEqual(row["ret60"], 0)
                self.assertEqual(row["vs50"], 0)
                self.assertNotIn("MOVE", row["flags"])
                self.assertEqual(obs.completed_bars[-1]["v"], 1000 / factor)
                self.assertEqual(bars[-1]["c"], 100)
                self.assertEqual(bars[-1]["v"], 1000)

    def test_split_fetch_failure_keeps_quote_only(self):
        obs = _observation(_snapshot(50), splits=None)
        row = iw.compute_row("ADI", None, obs)
        self.assertEqual(row["price"], 50)
        self.assertIsNone(row["pct_change"])
        self.assertEqual(row["history_issue"], "split_data_unavailable")

    def test_previous_bar_uses_exact_session_and_is_split_adjusted(self):
        snapshot = _snapshot(50, session_open=50)
        snapshot["prevDailyBar"] = {**_flat_bars(sessions=1)[0]}
        obs = _observation(snapshot, [], [("2026-11-24", 0.5)])
        self.assertEqual(iw.compute_row("ADI", None, obs)["pct_change"], 0)
        snapshot["prevDailyBar"]["t"] = "2026-11-21T05:00:00Z"
        obs = _observation(snapshot, [])
        self.assertEqual(obs.history_issue, "previous_session_bar_missing")


class TestFetchObservations(unittest.TestCase):
    def test_split_query_uses_processing_window_and_parser_preserves_invalid_records(self):
        class Client(FakeClient):
            data_endpoint = "http://fixture"
            get_corporate_action_splits = AlpacaClient.get_corporate_action_splits

            def get_snapshots(self, symbols, chunk_size):
                return {symbol: _snapshot(50, session_open=50) for symbol in symbols}

            def _get(self, url, params):
                self.params = params
                records = [
                    {"symbol": "GOOD", "ex_date": "2026-11-24", "old_rate": 1, "new_rate": 2},
                    {"symbol": "GOOD", "ex_date": "2026-11-26", "old_rate": None, "new_rate": 5},
                    {"symbol": "BAD", "ex_date": "2026-11-24", "old_rate": None, "new_rate": 2},
                    {"symbol": "UNKNOWN", "old_rate": 1, "new_rate": 2},
                ]
                data = records if params["end"] >= "2026-11-25" else []
                return Mock(json=Mock(return_value={"corporate_actions": {"forward_splits": data}}))

        client = Client()
        clock = Mock(wraps=datetime)
        clock.now.return_value = NOW
        with patch.object(market, "datetime", clock):
            observations = market.fetch_observations(client, ["GOOD", "BAD", "UNKNOWN"], 10, 400, POLICY)
        self.assertEqual(client.params["end"], "2026-12-24")
        self.assertEqual(client.params["data_quality"], "all")
        self.assertEqual(iw.compute_row("GOOD", None, observations["GOOD"])["pct_change"], 0)
        for symbol in ("BAD", "UNKNOWN"):
            row = iw.compute_row(symbol, None, observations[symbol])
            self.assertIsNone(row["pct_change"])
            self.assertEqual(row["history_issue"], "invalid_split_event")
            self.assertNotIn("MOVE", row["flags"])

    def test_each_batch_has_its_own_receipt_time(self):
        class Client(FakeClient):
            def get_snapshots(self, symbols, chunk_size):
                return {
                    symbol: {"latestTrade": {"p": 105, "t": "2026-11-24T16:00:05Z"}}
                    for symbol in symbols
                }

        clock = Mock(wraps=datetime)
        clock.now.side_effect = [NOW, NOW + timedelta(seconds=10), NOW + timedelta(seconds=15)]
        with patch.object(market, "datetime", clock):
            observations = market.fetch_observations(Client(), ["FIRST", "SECOND"], 1, 400, POLICY)
        self.assertEqual(observations["FIRST"].quote_status, "future_quote")
        self.assertEqual(observations["SECOND"].quote_status, "fresh")
        self.assertEqual(observations["SECOND"].quote.received_at, NOW + timedelta(seconds=10))


class TestShadowReestimation(unittest.TestCase):
    def test_provisional_series_replaces_incomplete_daily_bar(self):
        snapshot = _snapshot(120)
        obs = _observation(snapshot, [*_flat_bars(), snapshot["dailyBar"]])
        self.assertEqual(len(obs.provisional_bars), len(obs.completed_bars) + 1)
        self.assertEqual(obs.provisional_bars[-1]["c"], 120)
        self.assertEqual(obs.provisional_bars[-1]["t"], "2026-11-24")

    def test_compute_shadow_reports_state_for_healthy_and_crash(self):
        decision = _decision("ADI", 1)
        benchmark = market.build_benchmark(_observation(), 200)
        healthy = iw.compute_shadow(decision, _observation(_snapshot(105)), benchmark, POLICY)
        crash = iw.compute_shadow(decision, _observation(_snapshot(70)), benchmark, POLICY)
        self.assertIn("shadow_state", healthy)
        self.assertIn("shadow_state", crash)
        self.assertLess(crash["shadow_score"], healthy["shadow_score"])

    def test_shadow_suppresses_cross_session_and_over_limit_skew(self):
        qqq = _snapshot()
        qqq["latestTrade"]["t"] = "2026-11-23T20:59:00Z"
        for snap, reason in (
            (qqq, "qqq_prior_session_quote"), (_snapshot(age=171), "benchmark_quote_skew"),
            ({}, "qqq_no_regular_session_price"),
        ):
            with self.subTest(reason=reason):
                benchmark = market.build_benchmark(_observation(snap), 200)
                result = iw.compute_shadow(_decision("ADI", 1), _observation(), benchmark, POLICY)
                self.assertEqual(result, {"shadow_reason": reason})

    def test_qqq_history_gap_suppresses_shadow(self):
        bars = _flat_bars()
        del bars[-21]
        benchmark = market.build_benchmark(_observation(bars=bars), 200)
        result = iw.compute_shadow(_decision("ADI", 1), _observation(), benchmark, POLICY)
        self.assertEqual(result, {"shadow_reason": "qqq_history_incomplete"})

    def test_preview_uses_same_skew_gate_as_monitor(self):
        decisions = build_stock_decisions(
            pd.DataFrame([{"symbol": "ADI", "market_asof": "2026-11-23"}]),
            decision_date="2026-11-23", generated_at_utc=NOW.isoformat(), policy_version="v2",
        )
        benchmark = market.build_benchmark(_observation(_snapshot(age=171)), 200)
        updated, skipped = preview.build_provisional_decisions(
            decisions, ["ADI"], {"ADI": _observation()}, benchmark, POLICY
        )
        self.assertFalse(updated)
        self.assertEqual(skipped, ["ADI:benchmark_quote_skew"])


class TestRenderingAndRunner(unittest.TestCase):
    def test_render_markdown_contains_rows(self) -> None:
        row = iw.compute_row("ADI", _decision("ADI", 1), _observation(_snapshot(95)))
        text = iw.render_markdown(
            [row],
            decision_date="2026-10-19",
            scope="report",
            market_status="closed",
            generated_utc="2026-10-22T00:00:00Z",
        )
        self.assertIn("| ADI |", text)
        self.assertIn("S50✖", text)

    def test_run_once_is_read_only_and_writes_only_monitor_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / "2026-10-19" / "production"
            snapshot.mkdir(parents=True)
            decisions = [_decision("ADI", 1), _decision("CTAS", 2)]
            (snapshot / "decisions.jsonl").write_text(
                "\n".join(json.dumps(r) for r in decisions) + "\n",
                encoding="utf-8",
            )
            (snapshot / "action_list.md").write_text(
                "- [Full Report →](./detailed/ADI.md)\n"
                "- [Full Report →](./detailed/CTAS.md)\n",
                encoding="utf-8",
            )
            before = {p.name for p in snapshot.iterdir()}
            out = Path(td) / "monitor.md"
            args = iw.parse_args(
                [
                    "--snapshot-dir", str(snapshot),
                    "--out", str(out),
                    "--config", "configs/config.production.json",
                ]
            )
            test_clock = Mock(wraps=datetime)
            test_clock.now.return_value = NOW
            with patch.object(market, "datetime", test_clock):
                rows = iw.run_once(args, client=FakeClient())
            self.assertEqual([r["symbol"] for r in rows], ["ADI", "CTAS"])
            self.assertTrue(out.is_file())
            self.assertIn("Publication: historical snapshot", out.read_text(encoding="utf-8"))
            after = {p.name for p in snapshot.iterdir()}
            self.assertEqual(before, after)
            self.assertTrue(all(row["quote_status"] == "fresh" for row in rows))
            self.assertTrue(all("shadow_state" in row for row in rows))
            self.assertFalse((snapshot / "latest_production.json").exists())

    def test_session_status_closed_on_weekend(self) -> None:
        saturday = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
        self.assertIn("closed", iw._session_status(saturday))


if __name__ == "__main__":
    unittest.main()
