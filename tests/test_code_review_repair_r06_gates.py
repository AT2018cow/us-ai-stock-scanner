"""R06 repair tests: canonical entry gate results and report consistency."""

from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.decision import (
    ActionState,
    build_stock_decisions,
)
from ai_value_scanner.decision.entry import build_entry_quality_v2
from ai_value_scanner.decision.integrated import _review_trigger
from ai_value_scanner.decision.model import (
    EntryDecision,
    EntryState,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.decision.view_model import build_stock_card_view_model
from ai_value_scanner.reporting.decision import render_detailed_report_v2

ENTRY_METRICS = {
    "price_to_sma200": 1.05,
    "price_to_sma50": 1.03,
    "days_below_sma200": 0,
    "return_20d": 0.05,
    "return_60d": 0.10,
    "drawdown_from_52w_high": 0.08,
    "range_position_52w": 0.82,
    "relative_strength_60d_qqq": 0.04,
    "volatility_60d": 0.35,
    "regime": "up",
    "benchmark_trend_ok": True,
}

QUALITY_FRAME = dict(
    symbol="AAA",
    company_name="Synthetic AAA",
    fundamental_data_asof="2026-08-01",
    market_asof="2026-10-09",
    revenue=1000.0,
    net_margin=0.25,
    free_cash_flow=200.0,
    adjusted_ebit=250.0,
    ocf_to_net_income=1.2,
    accrual_ratio=-0.05,
    revenue_yoy=0.20,
    adjusted_net_income_yoy=0.20,
    operating_cash_flow_yoy=0.20,
    net_debt_to_ebitda=0.0,
    net_debt_to_ebitda_source="reported",
    interest_coverage=10.0,
    current_ratio=2.0,
    shares_yoy=0.0,
    fcf_yield=0.06,
    ps_hist_percentile=0.20,
    pe_hist_percentile=0.30,
    receivables_growth_gap=0.0,
    inventory_growth_gap=0.0,
    **ENTRY_METRICS,
)


def _entry(**changes):
    metrics = {**ENTRY_METRICS, **changes}
    return build_entry_quality_v2(
        metrics, decision_date="2026-10-09", market_asof="2026-10-09"
    )


def _card(entry):
    decision = StockDecision(
        schema_version="1",
        symbol="AAA",
        company_name="Synthetic AAA",
        decision_date="2026-10-09",
        generated_at_utc="2026-10-18T12:00:00+00:00",
        quality=QualityDecision(
            grade=QualityGrade.A,
            score=0.9,
            confidence=0.9,
            component_scores={},
            positives=(),
            risks=(),
            missing=(),
            data_asof="2026-08-01",
        ),
        entry=entry,
        action_state=ActionState.PRIORITY_REVIEW,
        priority=1,
        rationale=(),
        review_trigger="r",
        source_lists=(),
        provenance={},
    )
    return build_stock_card_view_model(decision)


class GateResultCoverageTests(unittest.TestCase):
    def test_ready_implies_no_blocking_gate(self) -> None:
        scenarios = {
            "ready": {},
            "ma_alignment": {"price_to_sma200": 1.01, "price_to_sma50": 1.04},
            "volatility": {"volatility_60d": 0.90},
            "below_sma200": {"price_to_sma200": 0.97},
            "sma50_extended": {"price_to_sma50": 1.12},
            "ret20_low": {"return_20d": -0.05},
            "ret60_negative": {"return_60d": -0.02},
            "rs_weak": {"relative_strength_60d_qqq": -0.05},
            "deep_drawdown": {"drawdown_from_52w_high": 0.30},
            "damaged": {"days_below_sma200": 20},
            "range_extension": {"range_position_52w": 0.96, "return_20d": 0.09},
        }
        for name, changes in scenarios.items():
            with self.subTest(scenario=name):
                entry = _entry(**changes)
                blocking = [gate for gate in entry.gate_results if gate.blocking]
                self.assertEqual(
                    entry.state is EntryState.ENTRY_READY,
                    not blocking,
                    f"{name}: state={entry.state.value} blocking={[g.gate_key for g in blocking]}",
                )

    def test_non_ready_state_explains_itself(self) -> None:
        scenarios = {
            "ma_alignment": ({
                "price_to_sma200": 1.01, "price_to_sma50": 1.04,
            }, "ma_alignment"),
            "volatility": ({"volatility_60d": 0.90}, "volatility_cap"),
            "range_extension": (
                {"range_position_52w": 0.96, "return_20d": 0.09},
                "overextension",
            ),
            "damaged": ({"days_below_sma200": 20}, "trend_damage"),
        }
        for name, (changes, expected_gate) in scenarios.items():
            with self.subTest(scenario=name):
                entry = _entry(**changes)
                self.assertNotEqual(entry.state, EntryState.ENTRY_READY)
                blocking_keys = {
                    gate.gate_key for gate in entry.gate_results if gate.blocking
                }
                self.assertIn(expected_gate, blocking_keys)

    def test_ma_alignment_block_is_rendered(self) -> None:
        card = _card(_entry(price_to_sma200=1.01, price_to_sma50=1.04))
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["ma_alignment"].status, "FAIL_BLOCKER")
        self.assertIn("0.97", str(by_key["ma_alignment"].observed_display))
        self.assertIn("SMA50 is 0.97x SMA200", card.entry_blockers_inline)
        self.assertNotIn("All", card.entry_blockers_inline)

    def test_volatility_block_is_rendered(self) -> None:
        card = _card(_entry(volatility_60d=0.90))
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["volatility_cap"].status, "FAIL_BLOCKER")
        self.assertIn("volatility", card.entry_blockers_inline)

    def test_range_extension_block_is_rendered(self) -> None:
        card = _card(_entry(range_position_52w=0.96, return_20d=0.09))
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["overextension"].status, "FAIL_BLOCKER")
        self.assertIn("52w range position", by_key["overextension"].note)

    def test_defensive_regime_confirmation_paths(self) -> None:
        confirmed = _entry(
            regime="down",
            benchmark_trend_ok=False,
            relative_strength_60d_qqq=0.06,
            return_20d=0.05,
        )
        self.assertEqual(confirmed.state, EntryState.ENTRY_READY)
        regime_gate = next(g for g in confirmed.gate_results if g.gate_key == "market_regime")
        self.assertEqual(regime_gate.status, "PASS")
        confirmed_card = _card(confirmed)
        self.assertIn("All", confirmed_card.entry_blockers_inline)

        unconfirmed = _entry(
            regime="down",
            benchmark_trend_ok=False,
            relative_strength_60d_qqq=0.01,
        )
        self.assertNotEqual(unconfirmed.state, EntryState.ENTRY_READY)
        regime_gate = next(g for g in unconfirmed.gate_results if g.gate_key == "market_regime")
        self.assertEqual(regime_gate.status, "BLOCK")
        unconfirmed_card = _card(unconfirmed)
        self.assertIn("Defensive regime", unconfirmed_card.entry_blockers_inline)

    def test_non_blocking_extension_is_warn_not_block(self) -> None:
        entry = _entry(price_to_sma200=1.47, return_60d=0.514)
        self.assertEqual(entry.state, EntryState.ENTRY_READY)
        ext = next(g for g in entry.gate_results if g.gate_key == "extension_watch")
        self.assertEqual(ext.status, "WARN")
        self.assertFalse(ext.blocking)
        card = _card(entry)
        self.assertEqual(card.entry_checklist[0].status, "PASS")
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["extension_watch"].status, "WARN")

    def test_insufficient_data_has_unknown_gate(self) -> None:
        entry = build_entry_quality_v2(
            {k: v for k, v in ENTRY_METRICS.items() if k != "return_20d"},
            decision_date="2026-10-09",
            market_asof="2026-10-09",
        )
        self.assertNotEqual(entry.state, EntryState.ENTRY_READY)
        unknown = [g for g in entry.gate_results if g.status == "UNKNOWN"]
        self.assertTrue(unknown)
        self.assertTrue(any(g.blocking for g in unknown))

    def test_severe_runtime_staleness_blocks_with_gate(self) -> None:
        entry = build_entry_quality_v2(
            ENTRY_METRICS,
            decision_date="2026-09-18",
            market_asof="2026-09-18",
            runtime_reference_date="2026-10-18",
        )
        self.assertEqual(entry.state, EntryState.INSUFFICIENT_DATA)
        freshness = next(g for g in entry.gate_results if g.gate_key == "freshness")
        self.assertEqual(freshness.status, "BLOCK")
        self.assertTrue(freshness.blocking)


class OldSnapshotHonestyTests(unittest.TestCase):
    def _legacy_decision(self):
        return StockDecision(
            schema_version="1",
            symbol="OLD",
            company_name="Old Corp",
            decision_date="2026-10-09",
            generated_at_utc="2026-10-10T00:00:00+00:00",
            quality=QualityDecision(
                grade=QualityGrade.A,
                score=0.9,
                confidence=0.9,
                component_scores={},
                positives=(),
                risks=(),
                missing=(),
                data_asof="2026-08-01",
            ),
            entry=EntryDecision(
                state=EntryState.WATCH_PULLBACK,
                score=0.8,
                confidence=0.9,
                positives=(),
                risks=(),
                market_asof="2026-10-09",
            ),
            action_state=ActionState.WATCH_PULLBACK,
            priority=1,
            rationale=(),
            review_trigger="r",
            source_lists=(),
            provenance={},
        )

    def test_gate_rows_are_unknown_not_fake_pass(self) -> None:
        card = build_stock_card_view_model(self._legacy_decision())
        self.assertTrue(all(row.status == "UNKNOWN" for row in card.entry_checklist))
        self.assertTrue(
            all("not recorded" in row.observed_display for row in card.entry_checklist)
        )
        self.assertNotIn("All", card.entry_blockers_inline)
        self.assertIn("not recorded", card.entry_blockers_inline)

    def test_detailed_report_does_not_claim_all_passed(self) -> None:
        rendered = render_detailed_report_v2(self._legacy_decision())
        self.assertNotIn("All 7 readiness gates passed", rendered)
        self.assertNotIn("All 14 readiness gates passed", rendered)
        self.assertIn("not recorded", rendered)


class ReviewTriggerConsistencyTests(unittest.TestCase):
    def test_b_promotion_trigger_uses_promotion_conditions(self) -> None:
        quality = QualityDecision(
            grade=QualityGrade.B,
            score=0.75,
            confidence=0.85,
            component_scores={},
            positives=(),
            risks=(),
            missing=(),
            data_asof="2026-08-01",
        )
        trigger = _review_trigger(
            ActionState.PRIORITY_REVIEW, quality=quality, action_version="v2"
        )
        self.assertNotIn("falls below A", trigger)
        self.assertIn("0.68", trigger)
        self.assertIn("ENTRY_READY", trigger)

    def test_a_priority_trigger_unchanged(self) -> None:
        trigger = _review_trigger(ActionState.PRIORITY_REVIEW, action_version="v2")
        self.assertIn("falls below A", trigger)

    def test_end_to_end_b_promotion_decision_is_self_consistent(self) -> None:
        row = {
            **QUALITY_FRAME,
            "shares_yoy": 0.20,
        }
        decisions = build_stock_decisions(
            pd.DataFrame([row]),
            decision_date="2026-10-09",
            generated_at_utc="2026-10-18T12:00:00+00:00",
            policy_version="v2",
        )
        decision = decisions[0]
        self.assertEqual(decision.quality.grade.value, "B")
        self.assertEqual(decision.action_state.value, "PRIORITY_REVIEW")
        self.assertNotIn("falls below A", decision.review_trigger or "")
        card = build_stock_card_view_model(decision)
        self.assertEqual(
            {row.gate_key for row in card.entry_checklist if row.status != "PASS"},
            set(),
        )

    def test_end_to_end_a_ready_stays_consistent(self) -> None:
        decisions = build_stock_decisions(
            pd.DataFrame([QUALITY_FRAME]),
            decision_date="2026-10-09",
            generated_at_utc="2026-10-18T12:00:00+00:00",
            policy_version="v2",
        )
        decision = decisions[0]
        self.assertEqual(decision.quality.grade.value, "A")
        self.assertEqual(decision.action_state.value, "PRIORITY_REVIEW")
        card = build_stock_card_view_model(decision)
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["overextension"].status, "PASS")
        self.assertEqual(by_key["trend_damage"].status, "PASS")


if __name__ == "__main__":
    unittest.main()
