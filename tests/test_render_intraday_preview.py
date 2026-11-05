"""Offline tests for the provisional intraday report preview."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_value_scanner.decision.action import ActionState
from ai_value_scanner.decision.entry import EntryState
from ai_value_scanner.decision.model import (
    QualityGrade,
    stock_decision_from_dict,
    stock_decisions_to_jsonl,
)


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "rip_" + name.replace(".py", ""), module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rip = _load_script("render_intraday_preview.py")


def _evidence(code: str, metric: str, value: float) -> dict:
    return {
        "code": code,
        "label": code,
        "polarity": "positive",
        "metric": metric,
        "value": value,
        "threshold": None,
        "message": code,
    }


def _decision(
    symbol: str,
    *,
    action: ActionState = ActionState.PRIORITY_REVIEW,
    entry: EntryState = EntryState.ENTRY_READY,
    priority: int = 1,
    previous: ActionState | None = ActionState.PRIORITY_REVIEW,
    grade: QualityGrade = QualityGrade.A,
    ret20: float = 0.02,
    sma50: float = 1.02,
):
    return stock_decision_from_dict(
        {
            "schema_version": "1",
            "symbol": symbol,
            "company_name": symbol,
            "decision_date": "2026-11-04",
            "generated_at_utc": "2026-11-05T00:00:00+00:00",
            "quality": {
                "grade": grade.value,
                "score": 0.8,
                "confidence": 0.9,
                "component_scores": {},
                "positives": [
                    _evidence("ret20", "return_20d", ret20),
                    _evidence("sma50", "price_to_sma50", sma50),
                ],
                "risks": [],
                "missing": [],
                "data_asof": "2026-10-30",
            },
            "entry": {
                "state": entry.value,
                "score": 0.9,
                "confidence": 0.9,
                "positives": [],
                "risks": [],
                "market_asof": "2026-11-04",
                "gate_results": [],
            },
            "action_state": action.value,
            "priority": priority,
            "rationale": [],
            "review_trigger": None,
            "source_lists": [],
            "provenance": {},
            "previous_action_state": None if previous is None else previous.value,
            "state_change_reason": None,
        }
    )


def _flat_bars(close: float = 100.0, sessions: int = 300) -> list[dict]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "t": (base + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00Z"),
            "o": close,
            "h": close,
            "l": close,
            "c": close,
            "v": 1000,
        }
        for i in range(sessions)
    ]


class FakeClient:
    def __init__(self, price: float = 103.0):
        self.price = price

    def get_snapshots(self, symbols, chunk_size):
        return {
            symbol: {
                "latestTrade": {"p": self.price, "t": "2026-11-05T15:00:00Z"},
                "dailyBar": {
                    "o": self.price,
                    "h": self.price,
                    "l": self.price,
                    "c": self.price,
                    "t": "2026-11-05T15:00:00Z",
                },
                "prevDailyBar": {"c": 100.0},
            }
            for symbol in symbols
        }

    def get_daily_bars(self, symbols, start_iso, chunk_size):
        return {symbol: _flat_bars() for symbol in symbols}


class TestDisplayPath(unittest.TestCase):
    def test_repo_relative_path_never_absolute(self) -> None:
        value = rip.display_path(Path("outputs/preview_intraday_2026-11-05"))
        self.assertFalse(value.startswith("/"))
        self.assertIn("preview_intraday_2026-11-05", value)


class TestCandidateSymbols(unittest.TestCase):
    def test_includes_incumbents_priority_ready_and_top(self) -> None:
        decisions = [
            _decision("INC", action=ActionState.HOLD_MONITOR, entry=EntryState.WATCH_BREAKOUT, priority=50),
            _decision("PRI", priority=1),
            _decision("RDY", action=ActionState.HOLD_MONITOR, entry=EntryState.ENTRY_READY, priority=2),
            _decision("TOP", action=ActionState.HOLD_MONITOR, entry=EntryState.WATCH_BREAKOUT, priority=3),
            _decision("OTHER", action=ActionState.HOLD_MONITOR, entry=EntryState.WATCH_BREAKOUT, priority=99),
        ]
        symbols = rip.candidate_symbols(decisions, ["INC"], top_n=3)
        self.assertEqual(symbols, ["INC", "PRI", "RDY", "TOP"])


class TestStabilitySelection(unittest.TestCase):
    def test_soft_breach_keeps_incumbent_for_one_day(self) -> None:
        incumbent = _decision(
            "AAA",
            action=ActionState.WATCH_BREAKOUT,
            entry=EntryState.WATCH_BREAKOUT,
            priority=5,
            previous=ActionState.PRIORITY_REVIEW,
            ret20=0.01,
            sma50=1.00,
        )
        entrant = _decision("BBB", priority=1)
        selected = rip.select_daily_attention(
            [incumbent, entrant], cap=5, previous_daily_symbols=["AAA"]
        )
        self.assertEqual([d.symbol for d in selected], ["BBB", "AAA"])

    def test_hard_damage_exits_immediately(self) -> None:
        damaged = _decision(
            "CCC",
            action=ActionState.HOLD_MONITOR,
            entry=EntryState.TREND_DAMAGED,
            priority=5,
            previous=ActionState.PRIORITY_REVIEW,
        )
        entrant = _decision("DDD", priority=1)
        selected = rip.select_daily_attention(
            [damaged, entrant], cap=5, previous_daily_symbols=["CCC"]
        )
        self.assertEqual([d.symbol for d in selected], ["DDD"])

    def test_overbought_incumbent_exits_immediately(self) -> None:
        overbought = _decision(
            "EEE",
            action=ActionState.WATCH_PULLBACK,
            entry=EntryState.WATCH_PULLBACK,
            priority=5,
            previous=ActionState.PRIORITY_REVIEW,
            ret20=0.20,
            sma50=1.20,
        )
        entrant = _decision("FFF", priority=1)
        selected = rip.select_daily_attention(
            [overbought, entrant], cap=5, previous_daily_symbols=["EEE"]
        )
        self.assertEqual([d.symbol for d in selected], ["FFF"])


class TestProvisionalBuild(unittest.TestCase):
    def test_uses_current_price_and_stamps_session(self) -> None:
        decision = _decision("AAA")
        provisional, skipped = rip.build_provisional_decisions(
            [decision],
            ["AAA"],
            FakeClient().get_snapshots(["AAA"], 10),
            FakeClient().get_daily_bars(["AAA"], "2025-01-01", 10),
            {"return_60d": 0.05, "regime": "up", "trend_ok": True},
        )
        self.assertEqual(skipped, [])
        self.assertIn("AAA", provisional)
        self.assertEqual(provisional["AAA"].entry.market_asof, "2026-11-05")
        stamped = rip.with_provisional_context([decision], provisional, "2026-11-05")
        self.assertEqual(stamped[0].decision_date, "2026-11-05")


class TestRenderPreview(unittest.TestCase):
    def test_writes_provisional_report_and_never_mutates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "decisions"
            snapshot = root / "2026-11-04" / "production"
            snapshot.mkdir(parents=True)
            decisions = [
                _decision("AAA", priority=1),
                _decision("BBB", priority=2),
                _decision("CCC", priority=3),
            ]
            decisions_path = snapshot / "decisions.jsonl"
            decisions_path.write_text(
                stock_decisions_to_jsonl(decisions), encoding="utf-8"
            )
            (snapshot / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "decision_date": "2026-11-04",
                        "daily_symbols": ["AAA", "BBB"],
                        "weekly_symbols": ["AAA", "BBB"],
                    }
                ),
                encoding="utf-8",
            )
            before = hashlib.sha256(decisions_path.read_bytes()).hexdigest()
            out = Path(tmp) / "out"
            metadata = rip.render_preview(
                snapshot_dir=snapshot,
                output_dir=out,
                snapshot_root=root,
                client=FakeClient(),
                cap=5,
                top_candidates=5,
            )
            after = hashlib.sha256(decisions_path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertFalse(metadata["is_official"])
            self.assertEqual(metadata["stability_policy_version"], "confirm_1_2_safe_v1")
            self.assertTrue((out / "action_list_v2.md").is_file())
            self.assertTrue((out / "weekly_review_v2.md").is_file())
            self.assertTrue((out / "preview_manifest.json").is_file())
            text = (out / "action_list_v2.md").read_text(encoding="utf-8")
            self.assertIn("PROVISIONAL INTRADAY PREVIEW", text)
            self.assertIn("confirm_1_2_safe_v1", json.dumps(metadata))


if __name__ == "__main__":
    unittest.main()
