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
    base = datetime.now(timezone.utc) - timedelta(days=320)
    return [
        {
            "t": (base + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00Z"),
            "o": close,
            "h": high,
            "l": low,
            "c": close,
            "v": 1000,
        }
        for i in range(sessions)
    ]


class FakeClient:
    def __init__(self, price=95.0, prev_close=105.0, bars=None):
        self.price = price
        self.prev_close = prev_close
        self.bars = bars if bars is not None else _flat_bars()

    def get_snapshots(self, symbols, chunk_size):
        return {
            s: {
                "latestTrade": {"p": self.price},
                "prevDailyBar": {"c": self.prev_close},
            }
            for s in symbols
        }

    def get_daily_bars(self, symbols, start_iso, chunk_size):
        return {s: list(self.bars) for s in symbols}


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


class TestRowComputation(unittest.TestCase):
    def test_flags_for_below_and_crossed_levels(self) -> None:
        row = iw.compute_row(
            "ADI",
            _decision("ADI", 1),
            {
                "latestTrade": {"p": 95.0},
                "prevDailyBar": {"c": 105.0},
            },
            _flat_bars(),
            latest_session=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
        )
        self.assertAlmostEqual(row["price"], 95.0)
        self.assertAlmostEqual(row["pct_change"], 95.0 / 105.0 - 1.0)
        self.assertAlmostEqual(row["vs50"], -0.05)
        self.assertAlmostEqual(row["vs200"], -0.05)
        self.assertIn("S50↓", row["flags"])
        self.assertIn("S50✖", row["flags"])
        self.assertIn("S200↓", row["flags"])
        self.assertIn("S200✖", row["flags"])
        self.assertIn("MOVE", row["flags"])
        self.assertIn("LO", row["flags"])

    def test_extended_and_near_high_flags(self) -> None:
        row = iw.compute_row(
            "ADI",
            _decision("ADI", 1),
            {"latestTrade": {"p": 165.0}, "prevDailyBar": {"c": 160.0}},
            _flat_bars(close=100.0, high=100.0, low=100.0),
            latest_session=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
        )
        self.assertIn("EXT", row["flags"])
        self.assertIn("HI", row["flags"])
        self.assertNotIn("S200↓", row["flags"])

    def test_missing_snapshot_and_bars_are_safe(self) -> None:
        row = iw.compute_row("ADI", None, None, None, latest_session=datetime.now(timezone.utc).date())
        self.assertIsNone(row["price"])
        self.assertEqual(row["flags"], [])

    def test_pre_earnings_carried_from_decision(self) -> None:
        row = iw.compute_row(
            "ADI",
            _decision(
                "ADI",
                1,
                risks=[{"code": "pre_earnings_window_risk", "message": "x"}],
            ),
            {"latestTrade": {"p": 100.0}, "prevDailyBar": {"c": 100.0}},
            _flat_bars(),
            latest_session=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
        )
        self.assertIn("PE", row["flags"])


class TestShadowReestimation(unittest.TestCase):
    def test_provisional_series_replaces_same_session_bar(self) -> None:
        bars = [
            {"t": "2026-10-18T20:00:00Z", "o": 1, "h": 1, "l": 1, "c": 100, "v": 1},
            {"t": "2026-10-19T20:00:00Z", "o": 1, "h": 1, "l": 1, "c": 101, "v": 1},
            {"t": "2026-10-20T20:00:00Z", "o": 1, "h": 1, "l": 1, "c": 102, "v": 1},
        ]
        snapshot = {
            "latestTrade": {"p": 103, "t": "2026-10-20T20:00:00Z"},
            "dailyBar": {
                "o": 101, "h": 104, "l": 100, "c": 103, "v": 5,
                "t": "2026-10-20T20:00:00Z",
            },
        }
        price, series, snapshot_date = iw._provisional_series(bars, snapshot)
        self.assertAlmostEqual(price, 103)
        self.assertEqual(snapshot_date.isoformat(), "2026-10-20")
        self.assertEqual(len(series), 3)  # replaced, not appended
        self.assertTrue(series[-1].get("provisional"))
        self.assertAlmostEqual(series[-1]["c"], 103)

    def _qqq_context(self):
        bars = _flat_bars(close=100.0, high=100.0, low=100.0)
        snapshot = {
            "latestTrade": {"p": 100, "t": "2026-10-20T20:00:00Z"},
            "dailyBar": {"o": 100, "h": 100, "l": 100, "c": 100, "v": 1,
                         "t": "2026-10-20T20:00:00Z"},
        }
        import types
        config = types.SimpleNamespace(benchmark_trend_filter_sma_days=200)
        return iw._qqq_context(snapshot, bars, config)

    def test_compute_shadow_reports_state_for_healthy_and_crash(self) -> None:
        decision = _decision("ADI", 1)
        qqq = self._qqq_context()
        self.assertIsNotNone(qqq)
        bars = _flat_bars(close=100.0, high=100.0, low=100.0)
        healthy = {
            "latestTrade": {"p": 120, "t": "2026-10-20T20:00:00Z"},
            "prevDailyBar": {"c": 118},
            "dailyBar": {"o": 118, "h": 121, "l": 117, "c": 120, "v": 5,
                         "t": "2026-10-20T20:00:00Z"},
        }
        crash = {
            "latestTrade": {"p": 70, "t": "2026-10-20T20:00:00Z"},
            "prevDailyBar": {"c": 118},
            "dailyBar": {"o": 118, "h": 118, "l": 69, "c": 70, "v": 9,
                         "t": "2026-10-20T20:00:00Z"},
        }
        healthy_row = iw.compute_shadow("ADI", decision, healthy, bars, qqq, None)
        crash_row = iw.compute_shadow("ADI", decision, crash, bars, qqq, None)
        self.assertIsNotNone(healthy_row)
        self.assertIsNotNone(crash_row)
        self.assertIn("shadow_state", healthy_row)
        self.assertNotEqual(healthy_row["shadow_state"], "ENTRY_READY")
        self.assertNotEqual(crash_row["shadow_state"], "ENTRY_READY")
        self.assertLess(crash_row["shadow_score"], healthy_row["shadow_score"])

    def test_compute_shadow_requires_decision_and_benchmark(self) -> None:
        qqq = self._qqq_context()
        bars = _flat_bars()
        snapshot = {"latestTrade": {"p": 100, "t": "2026-10-20T20:00:00Z"}}
        self.assertIsNone(iw.compute_shadow("ADI", None, snapshot, bars, qqq, None))
        self.assertIsNone(
            iw.compute_shadow("ADI", _decision("ADI", 1), snapshot, bars, None, None)
        )


class TestRenderingAndRunner(unittest.TestCase):
    def test_render_markdown_contains_rows(self) -> None:
        row = iw.compute_row(
            "ADI",
            _decision("ADI", 1),
            {"latestTrade": {"p": 95.0}, "prevDailyBar": {"c": 105.0}},
            _flat_bars(),
            latest_session=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
        )
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
            rows = iw.run_once(args, client=FakeClient())
            self.assertEqual([r["symbol"] for r in rows], ["ADI", "CTAS"])
            self.assertTrue(out.is_file())
            after = {p.name for p in snapshot.iterdir()}
            self.assertEqual(before, after)
            self.assertFalse((snapshot / "latest_production.json").exists())

    def test_session_status_closed_on_weekend(self) -> None:
        saturday = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
        self.assertIn("closed", iw._session_status(saturday))


if __name__ == "__main__":
    unittest.main()
