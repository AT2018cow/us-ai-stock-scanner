"""Top-15 stability / turnover tests (offline, synthetic fixtures).

Covers the Plan-D report readability helpers (streak computation and card
rendering), the five candidate schemes (hard-damage circuit breaker, buffer
bands, N=2 confirmation, regime confirmation), and byte-level CLI
reproduction of the Part A evidence.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.decision.attention import (
    DAILY_ATTENTION_STABILITY_POLICY_VERSION,
    HARD_OVERBOUGHT_RET20_FOR_RETENTION,
    HARD_OVERBOUGHT_SMA50_FOR_RETENTION,
    is_hard_damage_for_retention,
    is_soft_exit_grace_eligible,
)
from ai_value_scanner.decision.integrated import select_daily_attention
from ai_value_scanner.decision.model import (
    ActionState,
    EntryDecision,
    EntryState,
    EvidenceItem,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.decision.view_model import build_snapshot_view_model
from ai_value_scanner.reporting.decision import render_action_list_v2
from ai_value_scanner.reporting.snapshot import (
    compute_in_list_streaks,
    load_previous_daily_symbols,
    write_decision_snapshot,
)


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "turnover_" + name.replace(".py", ""), module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ev = _load_script("evaluate_top15_turnover_stability.py")


def _ev(
    code: str,
    polarity: str = "positive",
    *,
    metric: str = "x",
    value: object = 1.0,
) -> EvidenceItem:
    return EvidenceItem(
        code=code, label=f"label {code}", polarity=polarity,  # type: ignore[arg-type]
        metric=metric, value=value, threshold="t", message=f"message {code}",
    )


def _decision(
    *,
    symbol: str = "AAA",
    grade: QualityGrade = QualityGrade.A,
    state: EntryState = EntryState.ENTRY_READY,
    action: ActionState = ActionState.PRIORITY_REVIEW,
    previous: ActionState | None = None,
    priority: int = 1,
    quality_positives: tuple[EvidenceItem, ...] = (),
    entry_positives: tuple[EvidenceItem, ...] = (),
) -> StockDecision:
    quality = QualityDecision(
        grade=grade,
        score=0.80,
        confidence=0.95,
        component_scores={"profitability_cash": 0.8},
        positives=(_ev("free_cash_flow_strong"), *quality_positives),
        risks=(),
        missing=(),
        data_asof="2026-10-31",
    )
    entry = EntryDecision(
        state=state,
        score=0.90,
        confidence=0.90,
        positives=(_ev("trend_intact"), *entry_positives),
        risks=(),
        market_asof="2026-11-04",
    )
    return StockDecision(
        schema_version="1",
        symbol=symbol,
        company_name=f"{symbol} Inc.",
        decision_date="2026-11-04",
        generated_at_utc="2026-11-04T00:00:00+00:00",
        quality=quality,
        entry=entry,
        action_state=action,
        priority=priority,
        rationale=quality.positives + entry.positives,
        review_trigger="Review now.",
        source_lists=("research_pool",),
        provenance={},
        previous_action_state=previous,
        state_change_reason=None,
    )


class TestStreakComputation(unittest.TestCase):
    def _write_manifest(self, root: Path, date: str, style: str, symbols: list[str]):
        target = root / date / style
        target.mkdir(parents=True)
        (target / "run_manifest.json").write_text(
            json.dumps({"daily_symbols": symbols}), encoding="utf-8"
        )

    def test_streaks_count_backwards_across_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(root, "2026-10-01", "production", ["AAA", "BBB", "EEE"])
            self._write_manifest(root, "2026-10-02", "production", ["AAA", "BBB"])
            streaks = compute_in_list_streaks(
                root, "2026-10-03", "production", ["AAA", "BBB", "CCC", "EEE"]
            )
            self.assertEqual(
                streaks, {"AAA": 3, "BBB": 3, "CCC": 1, "EEE": 1}
            )

    def test_no_prior_same_style_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(root, "2026-10-02", "risk_off", ["AAA"])
            self.assertIsNone(
                compute_in_list_streaks(
                    root, "2026-10-03", "production", ["AAA"]
                )
            )

    def test_empty_current_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(
                compute_in_list_streaks(td, "2026-10-03", "production", []),
                {},
            )

    def test_validator_accepts_consecutive_snapshots_with_streaks(self) -> None:
        validator = _load_script("validate_mvp_snapshot.py")
        from ai_value_scanner.decision.entry import ENTRY_V2_POLICY_VERSION
        from ai_value_scanner.decision.quality import QUALITY_V2_POLICY_VERSION
        from dataclasses import replace

        with tempfile.TemporaryDirectory() as td:
            for day in ("2026-11-03", "2026-11-04"):
                decision = replace(
                    _decision(symbol="AAA"),
                    decision_date=day,
                    generated_at_utc=f"{day}T12:00:00+00:00",
                    provenance={
                        "quality_policy_version": QUALITY_V2_POLICY_VERSION,
                        "entry_policy_version": ENTRY_V2_POLICY_VERSION,
                        "decision_policy_version": "q=v2,e=v2,a=v2",
                    },
                )
                paths = write_decision_snapshot(
                    output_root=td,
                    strategy_style="production",
                    decisions=(decision,),
                    daily_attention=(decision,),
                    weekly_attention=(decision,),
                    generated_at_utc=decision.generated_at_utc,
                    decision_date=day,
                    config_fingerprint="fp",
                    policy_version="v2",
                    layout_version="v2",
                )
            result = validator.validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])


class TestCardStreakRendering(unittest.TestCase):
    def test_new_and_incumbent_labels(self) -> None:
        decision = _decision(symbol="AAA")
        new_text = render_action_list_v2(
            [decision], streaks_by_symbol={"AAA": 1}
        )
        self.assertIn("[NEW]", new_text)
        held_text = render_action_list_v2(
            [decision], streaks_by_symbol={"AAA": 5}
        )
        self.assertIn("[LIST 5d]", held_text)

    def test_fallback_continuation_without_streak_map(self) -> None:
        decision = _decision(
            symbol="AAA",
            previous=ActionState.PRIORITY_REVIEW,
        )
        text = render_action_list_v2([decision])
        self.assertIn("[LIST 2d]", text)

    def test_no_label_without_history(self) -> None:
        text = render_action_list_v2([_decision(symbol="AAA")])
        self.assertNotIn("[NEW]", text)
        self.assertNotIn("[LIST ", text)

    def test_view_model_exposes_optional_field(self) -> None:
        view = build_snapshot_view_model(
            [_decision(symbol="AAA")],
            streaks_by_symbol={"AAA": 4},
        )
        self.assertEqual(view.primary_cards[0].in_list_streak_days, 4)


class TestRetentionPolicyFunctions(unittest.TestCase):
    def test_hard_damage_entry_states_and_quality_grades(self) -> None:
        for state in (
            EntryState.TREND_DAMAGED,
            EntryState.INSUFFICIENT_DATA,
        ):
            with self.subTest(state=state):
                self.assertTrue(
                    is_hard_damage_for_retention(_decision(state=state))
                )
        for grade in (QualityGrade.C, QualityGrade.UNRATED):
            with self.subTest(grade=grade):
                self.assertTrue(
                    is_hard_damage_for_retention(_decision(grade=grade))
                )
        self.assertFalse(is_hard_damage_for_retention(_decision()))

    def test_hard_damage_overbought_metrics_and_boundaries(self) -> None:
        hard_sma = _decision(
            entry_positives=(
                _ev(
                    "extended",
                    metric="price_to_sma50",
                    value=HARD_OVERBOUGHT_SMA50_FOR_RETENTION + 1e-9,
                ),
            )
        )
        self.assertTrue(is_hard_damage_for_retention(hard_sma))
        edge_sma = _decision(
            entry_positives=(
                _ev(
                    "extended",
                    metric="price_to_sma50",
                    value=HARD_OVERBOUGHT_SMA50_FOR_RETENTION,
                ),
            )
        )
        self.assertFalse(is_hard_damage_for_retention(edge_sma))

        hard_ret20 = _decision(
            entry_positives=(
                _ev(
                    "hot",
                    metric="return_20d",
                    value=HARD_OVERBOUGHT_RET20_FOR_RETENTION + 1e-9,
                ),
            )
        )
        self.assertTrue(is_hard_damage_for_retention(hard_ret20))
        edge_ret20 = _decision(
            entry_positives=(
                _ev(
                    "hot",
                    metric="return_20d",
                    value=HARD_OVERBOUGHT_RET20_FOR_RETENTION,
                ),
            )
        )
        self.assertFalse(is_hard_damage_for_retention(edge_ret20))

    def test_soft_grace_requires_all_conditions(self) -> None:
        soft = _decision(
            action=ActionState.WATCH_BREAKOUT,
            previous=ActionState.PRIORITY_REVIEW,
        )
        self.assertTrue(is_soft_exit_grace_eligible(soft, ["AAA"]))
        self.assertTrue(is_soft_exit_grace_eligible(soft, [" aaa "]))
        self.assertFalse(is_soft_exit_grace_eligible(soft, ["BBB"]))
        self.assertFalse(
            is_soft_exit_grace_eligible(soft, [])
        )
        self.assertFalse(
            is_soft_exit_grace_eligible(
                _decision(
                    action=ActionState.WATCH_BREAKOUT,
                    previous=None,
                ),
                ["AAA"],
            )
        )
        self.assertFalse(
            is_soft_exit_grace_eligible(
                _decision(
                    action=ActionState.PRIORITY_REVIEW,
                    previous=ActionState.PRIORITY_REVIEW,
                ),
                ["AAA"],
            )
        )
        self.assertFalse(
            is_soft_exit_grace_eligible(
                _decision(
                    action=ActionState.WATCH_BREAKOUT,
                    previous=ActionState.PRIORITY_REVIEW,
                    state=EntryState.TREND_DAMAGED,
                ),
                ["AAA"],
            )
        )


class TestSelectDailyAttentionStability(unittest.TestCase):
    def test_none_preserves_legacy_behavior(self) -> None:
        decisions = (
            _decision(
                symbol="AAA",
                priority=1,
                action=ActionState.PRIORITY_REVIEW,
                previous=ActionState.WATCH_BREAKOUT,
            ),
            _decision(
                symbol="BBB",
                priority=2,
                action=ActionState.WATCH_BREAKOUT,
                previous=ActionState.PRIORITY_REVIEW,
            ),
        )
        legacy = select_daily_attention(decisions)
        self.assertEqual([d.symbol for d in legacy], ["AAA"])

    def test_empty_previous_list_uses_weekly_fallback(self) -> None:
        decisions = (
            _decision(symbol="AAA", priority=2),
            _decision(
                symbol="BBB",
                priority=1,
                action=ActionState.WATCH_BREAKOUT,
                previous=ActionState.PRIORITY_REVIEW,
            ),
        )
        selected = select_daily_attention(
            decisions,
            previous_daily_symbols=(),
        )
        self.assertEqual([d.symbol for d in selected], ["BBB", "AAA"])

    def test_first_soft_breach_is_held_for_one_day(self) -> None:
        soft = _decision(
            symbol="AAA",
            action=ActionState.WATCH_BREAKOUT,
            previous=ActionState.PRIORITY_REVIEW,
        )
        selected = select_daily_attention(
            (soft,),
            previous_daily_symbols=("AAA",),
        )
        self.assertEqual([d.symbol for d in selected], ["AAA"])

    def test_second_consecutive_soft_breach_exits(self) -> None:
        soft = _decision(
            symbol="AAA",
            action=ActionState.WATCH_BREAKOUT,
            previous=ActionState.WATCH_BREAKOUT,
        )
        selected = select_daily_attention(
            (soft,),
            previous_daily_symbols=("AAA",),
        )
        self.assertEqual(selected, ())

    def test_hard_damage_exits_on_the_same_day(self) -> None:
        for damaged in (
            _decision(
                symbol="AAA",
                action=ActionState.WATCH_BREAKOUT,
                previous=ActionState.PRIORITY_REVIEW,
                state=EntryState.TREND_DAMAGED,
            ),
            _decision(
                symbol="AAA",
                action=ActionState.WATCH_BREAKOUT,
                previous=ActionState.PRIORITY_REVIEW,
                entry_positives=(
                    _ev(
                        "extended",
                        metric="price_to_sma50",
                        value=HARD_OVERBOUGHT_SMA50_FOR_RETENTION + 0.01,
                    ),
                ),
            ),
            _decision(
                symbol="AAA",
                action=ActionState.WATCH_BREAKOUT,
                previous=ActionState.PRIORITY_REVIEW,
                grade=QualityGrade.C,
            ),
        ):
            with self.subTest(damaged=damaged.entry.state.value):
                selected = select_daily_attention(
                    (damaged,),
                    previous_daily_symbols=("AAA",),
                )
                self.assertEqual(selected, ())

    def test_slot_filling_and_priority_order(self) -> None:
        grace = _decision(
            symbol="GRC",
            priority=1,
            action=ActionState.WATCH_BREAKOUT,
            previous=ActionState.PRIORITY_REVIEW,
        )
        priority_late = _decision(symbol="AAA", priority=2)
        priority_early = _decision(symbol="BBB", priority=1)
        non_priority_new = _decision(
            symbol="CCC",
            priority=0,
            action=ActionState.WATCH_BREAKOUT,
            previous=None,
        )
        decisions = (grace, priority_late, priority_early, non_priority_new)

        selected = select_daily_attention(
            decisions,
            cap=3,
            previous_daily_symbols=("GRC",),
        )
        self.assertEqual(
            [d.symbol for d in selected], ["BBB", "AAA", "GRC"]
        )

        capped = select_daily_attention(
            decisions,
            cap=2,
            previous_daily_symbols=("GRC",),
        )
        self.assertEqual([d.symbol for d in capped], ["BBB", "GRC"])
        self.assertNotIn("CCC", [d.symbol for d in capped])


class TestLoadPreviousDailySymbols(unittest.TestCase):
    def _write_manifest(
        self,
        root: Path,
        day: str,
        style: str,
        payload: object,
    ) -> None:
        target = root / day / style
        target.mkdir(parents=True)
        (target / "run_manifest.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_returns_latest_prior_same_style(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(
                root, "2026-10-01", "production", {"daily_symbols": ["aaa"]}
            )
            self._write_manifest(
                root,
                "2026-10-02",
                "production",
                {"daily_symbols": ["bbb", "CCC"]},
            )
            self._write_manifest(
                root,
                "2026-10-03",
                "risk_off",
                {"daily_symbols": ["DDD"]},
            )
            self._write_manifest(
                root,
                "2026-10-04",
                "production",
                {"daily_symbols": ["EEE"]},
            )
            result = load_previous_daily_symbols(
                root,
                "2026-10-03",
                strategy_style="production",
            )
            self.assertEqual(result, ("BBB", "CCC"))

    def test_none_without_prior_same_style(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(
                root, "2026-10-03", "risk_off", {"daily_symbols": ["AAA"]}
            )
            self.assertIsNone(
                load_previous_daily_symbols(
                    root,
                    "2026-10-04",
                    strategy_style="production",
                )
            )
            self.assertIsNone(
                load_previous_daily_symbols(
                    root,
                    "2026-10-01",
                    strategy_style="production",
                )
            )

    def test_unreadable_manifest_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(
                root, "2026-10-01", "production", {"daily_symbols": ["AAA"]}
            )
            broken = root / "2026-10-02" / "production"
            broken.mkdir(parents=True)
            (broken / "run_manifest.json").write_text("{", encoding="utf-8")
            result = load_previous_daily_symbols(
                root,
                "2026-10-03",
                strategy_style="production",
            )
            self.assertEqual(result, ("AAA",))

    def test_empty_prior_list_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(
                root, "2026-10-01", "production", {"daily_symbols": []}
            )
            self.assertEqual(
                load_previous_daily_symbols(
                    root,
                    "2026-10-02",
                    strategy_style="production",
                ),
                (),
            )


class TestGraceRendering(unittest.TestCase):
    def test_grace_label_for_incumbent_soft_exit(self) -> None:
        decision = _decision(
            symbol="AAA",
            action=ActionState.WATCH_BREAKOUT,
            previous=ActionState.PRIORITY_REVIEW,
        )
        text = render_action_list_v2(
            [decision], streaks_by_symbol={"AAA": 4}
        )
        self.assertIn("[LIST 4d · GRACE 1/2]", text)

    def test_priority_review_keeps_plain_list_label(self) -> None:
        text = render_action_list_v2(
            [_decision(symbol="AAA")], streaks_by_symbol={"AAA": 4}
        )
        self.assertIn("[LIST 4d]", text)
        self.assertNotIn("GRACE", text)

    def test_new_name_has_no_grace_label(self) -> None:
        decision = _decision(
            symbol="AAA",
            action=ActionState.WATCH_BREAKOUT,
            previous=ActionState.PRIORITY_REVIEW,
        )
        text = render_action_list_v2(
            [decision], streaks_by_symbol={"AAA": 1}
        )
        self.assertIn("[NEW]", text)
        self.assertNotIn("GRACE", text)


class TestGraceSnapshotEndToEnd(unittest.TestCase):
    def test_validator_accepts_grace_hold_snapshot(self) -> None:
        validator = _load_script("validate_mvp_snapshot.py")
        from dataclasses import replace

        from ai_value_scanner.decision.entry import ENTRY_V2_POLICY_VERSION
        from ai_value_scanner.decision.quality import QUALITY_V2_POLICY_VERSION

        def _as_day(decision: StockDecision, day: str) -> StockDecision:
            return replace(
                decision,
                decision_date=day,
                generated_at_utc=f"{day}T12:00:00+00:00",
                provenance={
                    "quality_policy_version": QUALITY_V2_POLICY_VERSION,
                    "entry_policy_version": ENTRY_V2_POLICY_VERSION,
                    "decision_policy_version": "q=v2,e=v2,a=v2",
                },
            )

        with tempfile.TemporaryDirectory() as td:
            prior = _as_day(_decision(symbol="AAA"), "2026-11-03")
            write_decision_snapshot(
                output_root=td,
                strategy_style="production",
                decisions=(prior,),
                daily_attention=(prior,),
                weekly_attention=(prior,),
                generated_at_utc=prior.generated_at_utc,
                decision_date="2026-11-03",
                config_fingerprint="fp",
                policy_version="v2",
                layout_version="v2",
            )
            previous_symbols = load_previous_daily_symbols(
                td,
                "2026-11-04",
                strategy_style="production",
            )
            self.assertEqual(previous_symbols, ("AAA",))

            grace = _as_day(
                _decision(
                    symbol="AAA",
                    state=EntryState.WATCH_BREAKOUT,
                    action=ActionState.WATCH_BREAKOUT,
                    previous=ActionState.PRIORITY_REVIEW,
                ),
                "2026-11-04",
            )
            new = _as_day(_decision(symbol="BBB", priority=2), "2026-11-04")
            decisions = (grace, new)
            daily = select_daily_attention(
                decisions,
                previous_daily_symbols=previous_symbols,
            )
            self.assertEqual([d.symbol for d in daily], ["BBB", "AAA"])

            paths = write_decision_snapshot(
                output_root=td,
                strategy_style="production",
                decisions=decisions,
                daily_attention=daily,
                weekly_attention=decisions,
                generated_at_utc="2026-11-04T12:00:00+00:00",
                decision_date="2026-11-04",
                config_fingerprint="fp",
                policy_version="v2",
                layout_version="v2",
            )
            result = validator.validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])
            self.assertIn(
                "[LIST 2d · GRACE 1/2]",
                paths.action_list_md.read_text(encoding="utf-8"),
            )
            manifest = json.loads(
                paths.run_manifest_json.read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["stability_policy_version"],
                DAILY_ATTENTION_STABILITY_POLICY_VERSION,
            )
            self.assertEqual(manifest["daily_symbols"], ["BBB", "AAA"])


def _metric(
    symbol: str = "AAA",
    *,
    priority: int = 1,
    action: str = "PRIORITY_REVIEW",
    grade: str = "A",
    entry_state: str = "ENTRY_READY",
    entry_score: float = 0.90,
    quality_score: float = 0.80,
    sma50: float = 1.00,
    ret20: float = 0.00,
    rs60: float = 0.10,
) -> dict:
    return {
        "symbol": symbol,
        "priority": priority,
        "action_state": action,
        "quality_grade": grade,
        "quality_score": quality_score,
        "quality_confidence": 0.95,
        "entry_state": entry_state,
        "entry_score": entry_score,
        "price_to_sma200": 1.10,
        "price_to_sma50": sma50,
        "return_20d": ret20,
        "return_60d": 0.10,
        "rs60": rs60,
        "drawdown": 0.05,
        "volatility": 0.30,
        "sma50_to_sma200": 1.10,
        "days_below_sma200": 0,
        "gate_status": {},
        "gate_blocking": {},
        "pre_earnings": False,
        "nonop": False,
        "qqq60": 0.05,
    }


def _day(
    symbols: list[str],
    metrics: dict[str, dict],
    regime: str = "up",
) -> dict:
    return {
        "metrics": metrics,
        "daily_symbols": symbols,
        "regime": regime,
        "dataset": "test",
    }


class TestCandidateSchemes(unittest.TestCase):
    def test_hard_damage_never_retained(self) -> None:
        dates = ["d1", "d2"]
        good = _metric("AAA")
        damaged = _metric(
            "AAA", action="HOLD_MONITOR", entry_state="TREND_DAMAGED"
        )
        data = {
            "d1": _day(["AAA"], {"AAA": good}),
            "d2": _day([], {"AAA": damaged}),
        }
        for scheme in (
            "S1_confirm_2_2_safe",
            "S2_confirm_1_2_safe",
            "S3_hysteresis_buffer",
            "S4_hybrid_hysteresis_regime",
        ):
            lists = ev.run_scheme(scheme, dates, data)
            self.assertNotIn("AAA", lists["d2"], scheme)

    def test_b0_passthrough_and_damage_detection(self) -> None:
        damaged = _metric(
            "AAA", action="HOLD_MONITOR", entry_state="TREND_DAMAGED"
        )
        data = {"d1": _day(["AAA"], {"AAA": damaged})}
        lists = ev.run_scheme("B0_baseline", ["d1"], data)
        self.assertEqual(lists["d1"], ["AAA"])
        summary = ev.summarize_lists(lists, ["d1"], data)
        self.assertEqual(summary["damaged_leaked_count"], 1)

    def test_s3_buffer_keeps_incumbent_outside_new_band(self) -> None:
        dates = ["d1", "d2", "d3"]
        good = _metric("AAA")
        soft = _metric(
            "AAA", action="WATCH_BREAKOUT", entry_state="WATCH_BREAKOUT",
            sma50=0.97,
        )
        data = {
            "d1": _day(["AAA"], {"AAA": good}),
            "d2": _day([], {"AAA": soft}),
            "d3": _day([], {"AAA": soft}),
        }
        s3 = ev.run_scheme("S3_hysteresis_buffer", dates, data)
        self.assertIn("AAA", s3["d2"])
        self.assertIn("AAA", s3["d3"])
        self.assertFalse(
            ev.scheme_eligible(soft, incumbent=False, regime="up")
        )

    def test_s2_soft_exit_waits_two_days(self) -> None:
        dates = ["d1", "d2", "d3"]
        good = _metric("AAA")
        soft = _metric(
            "AAA", action="WATCH_BREAKOUT", entry_state="WATCH_BREAKOUT",
            sma50=0.90,
        )
        data = {
            "d1": _day(["AAA"], {"AAA": good}),
            "d2": _day([], {"AAA": soft}),
            "d3": _day([], {"AAA": soft}),
        }
        s2 = ev.run_scheme("S2_confirm_1_2_safe", dates, data)
        self.assertIn("AAA", s2["d2"])
        self.assertNotIn("AAA", s2["d3"])

    def test_s1_requires_two_day_confirmation(self) -> None:
        dates = ["d1", "d2", "d3"]
        eligible = _metric("AAA")
        data = {
            "d1": _day(["BBB"], {"AAA": eligible, "BBB": _metric("BBB", priority=2)}),
            "d2": _day(["BBB"], {"AAA": eligible, "BBB": _metric("BBB", priority=2)}),
            "d3": _day(["BBB"], {"AAA": eligible, "BBB": _metric("BBB", priority=2)}),
        }
        s1 = ev.run_scheme("S1_confirm_2_2_safe", dates, data)
        s2 = ev.run_scheme("S2_confirm_1_2_safe", dates, data)
        self.assertNotIn("AAA", s1["d1"])
        self.assertIn("AAA", s1["d2"])
        self.assertIn("AAA", s2["d1"])

    def test_s4_regime_confirmation_three_days(self) -> None:
        dates = ["d1", "d2", "d3", "d4"]
        good = _metric("AAA", rs60=0.01)
        data = {
            "d1": _day(["AAA"], {"AAA": good}, regime="up"),
            "d2": _day(["AAA"], {"AAA": good}, regime="down"),
            "d3": _day(["AAA"], {"AAA": good}, regime="down"),
            "d4": _day(["AAA"], {"AAA": good}, regime="down"),
        }
        s3 = ev.run_scheme("S3_hysteresis_buffer", dates, data)
        s4 = ev.run_scheme("S4_hybrid_hysteresis_regime", dates, data)
        self.assertNotIn("AAA", s3["d2"])
        self.assertIn("AAA", s4["d2"])
        self.assertIn("AAA", s4["d3"])
        self.assertNotIn("AAA", s4["d4"])


class TestCliReproduction(unittest.TestCase):
    def test_part_a_outputs_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions_root = root / "decisions"
            for day in ev.LIVE_DATES:
                snap = decisions_root / day / "production"
                snap.mkdir(parents=True, exist_ok=True)
                (snap / "run_manifest.json").write_text(
                    json.dumps({"daily_symbols": ["AAA", "BBB"]}),
                    encoding="utf-8",
                )
                records = [
                    {
                        "symbol": sym,
                        "priority": idx,
                        "action_state": "PRIORITY_REVIEW",
                        "quality": {
                            "grade": "A",
                            "score": 0.85,
                            "confidence": 0.95,
                            "risks": [],
                        },
                        "entry": {
                            "state": "ENTRY_READY",
                            "score": 0.90,
                            "gate_results": [],
                            "positives": [
                                {"metric": "price_to_sma50", "value": 1.02},
                                {"metric": "return_20d", "value": 0.03},
                                {"metric": "return_60d", "value": 0.08},
                                {
                                    "metric": "relative_strength_60d_qqq",
                                    "value": 0.04,
                                },
                            ],
                            "risks": [],
                        },
                    }
                    for idx, sym in enumerate(("AAA", "BBB"), start=1)
                ]
                (snap / "decisions.jsonl").write_text(
                    "\n".join(json.dumps(r) for r in records) + "\n",
                    encoding="utf-8",
                )
            base_csv = root / "base.csv"
            bear_csv = root / "bear.csv"
            base_csv.write_text("signal_date,symbol\n2025-01-31,AAA\n", encoding="utf-8")
            bear_csv.write_text("signal_date,symbol\n2022-01-31,AAA\n", encoding="utf-8")
            out_dir = root / "out"
            cli_args = [
                "--part",
                "a",
                "--decisions-root",
                str(decisions_root),
                "--base-dataset",
                str(base_csv),
                "--bear-dataset",
                str(bear_csv),
                "--output-dir",
                str(out_dir),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                ev.main(cli_args)
            first = {
                path.name: path.read_bytes()
                for path in sorted(out_dir.iterdir())
            }
            self.assertEqual(
                set(first),
                {
                    "daily_turnover_comparison.csv",
                    "scheme_summary_metrics.csv",
                    "report.md",
                    "SHA256SUMS",
                },
            )
            for name, content in first.items():
                if name == "SHA256SUMS":
                    continue
                self.assertFalse(
                    ev.contains_absolute_path(content.decode("utf-8")), name
                )
            for path in out_dir.iterdir():
                path.unlink()
            with contextlib.redirect_stdout(io.StringIO()):
                ev.main(cli_args)
            second = {
                path.name: path.read_bytes()
                for path in sorted(out_dir.iterdir())
            }
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
