from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from ai_value_scanner.decision import (
    DECISION_SCHEMA_VERSION,
    ActionState,
    EntryDecision,
    EntryState,
    EvidenceItem,
    QualityDecision,
    QualityGrade,
    StockDecision,
    map_action_state,
    stock_decision_from_json,
    stock_decision_to_dict,
    stock_decision_to_json,
    stock_decisions_from_jsonl,
    stock_decisions_to_jsonl,
)
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)


def _decision(
    *,
    quality: QualityGrade = QualityGrade.A,
    entry: EntryState = EntryState.ENTRY_READY,
    action: ActionState | None = None,
) -> StockDecision:
    positive = EvidenceItem(
        code="trend_above_sma200",
        label="Trend above SMA200",
        polarity="positive",
        metric="price_to_sma200",
        value=1.08,
        threshold=1.0,
        message="Price is above the long-term trend reference.",
    )
    missing = EvidenceItem(
        code="fundamental_data_missing",
        label="Fundamental data missing",
        polarity="missing",
        metric="filing_asof",
        value=None,
        threshold=None,
        message="A synthetic field is intentionally unavailable.",
    )
    return StockDecision(
        schema_version=DECISION_SCHEMA_VERSION,
        symbol="EXM",
        company_name="Example Corp",
        decision_date="2026-10-10",
        generated_at_utc="2026-10-10T10:00:00+00:00",
        quality=QualityDecision(
            grade=quality,
            score=None,
            confidence=0.8,
            component_scores={"cash_quality": None},
            positives=(),
            risks=(),
            missing=(missing,),
            data_asof=None,
        ),
        entry=EntryDecision(
            state=entry,
            score=None,
            confidence=0.7,
            positives=(positive,),
            risks=(),
            market_asof="2026-10-09",
        ),
        action_state=action or map_action_state(quality, entry),
        priority=1,
        rationale=(positive,),
        review_trigger=None,
        source_lists=("research_pool",),
        provenance={"code_sha": "abc123", "synthetic": True},
        previous_action_state=None,
        state_change_reason=None,
    )


class TestDecisionContract(unittest.TestCase):
    def test_decision_dataclasses_are_frozen(self) -> None:
        decision = _decision()
        with self.assertRaises(FrozenInstanceError):
            decision.priority = 2  # type: ignore[misc]

    def test_json_round_trip_preserves_nested_contract(self) -> None:
        decision = _decision()
        encoded = stock_decision_to_json(decision)
        decoded = stock_decision_from_json(encoded)
        self.assertEqual(decoded, decision)
        self.assertEqual(stock_decision_to_json(decoded), encoded)

    def test_jsonl_round_trip_is_deterministic(self) -> None:
        decisions = (
            _decision(),
            _decision(
                quality=QualityGrade.B,
                entry=EntryState.WATCH_BREAKOUT,
            ),
        )
        encoded = stock_decisions_to_jsonl(decisions)
        self.assertTrue(encoded.endswith("\n"))
        self.assertEqual(stock_decisions_from_jsonl(encoded), decisions)
        self.assertEqual(stock_decisions_to_jsonl(decisions), encoded)

    def test_schema_version_fixture_matches_serialized_shape(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "stock_decision_schema_v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture_decision = stock_decision_from_json(json.dumps(fixture))
        self.assertEqual(fixture["schema_version"], DECISION_SCHEMA_VERSION)
        self.assertEqual(stock_decision_to_dict(fixture_decision), fixture)

    def test_unknown_schema_version_is_rejected(self) -> None:
        payload = stock_decision_to_dict(_decision())
        payload["schema_version"] = "999"
        with self.assertRaisesRegex(ValueError, "unsupported StockDecision schema_version"):
            stock_decision_from_json(json.dumps(payload))

    def test_action_mapping_is_exhaustive_and_deterministic(self) -> None:
        expected = {
            (QualityGrade.A, EntryState.ENTRY_READY): ActionState.PRIORITY_REVIEW,
            (QualityGrade.A, EntryState.WATCH_PULLBACK): ActionState.WATCH_PULLBACK,
            (QualityGrade.A, EntryState.WATCH_BREAKOUT): ActionState.WATCH_BREAKOUT,
            (QualityGrade.A, EntryState.TREND_DAMAGED): ActionState.HOLD_MONITOR,
            (QualityGrade.A, EntryState.INSUFFICIENT_DATA): ActionState.AVOID,
            (QualityGrade.B, EntryState.ENTRY_READY): ActionState.HOLD_MONITOR,
            (QualityGrade.B, EntryState.WATCH_PULLBACK): ActionState.HOLD_MONITOR,
            (QualityGrade.B, EntryState.WATCH_BREAKOUT): ActionState.HOLD_MONITOR,
            (QualityGrade.B, EntryState.TREND_DAMAGED): ActionState.HOLD_MONITOR,
            (QualityGrade.B, EntryState.INSUFFICIENT_DATA): ActionState.AVOID,
        }
        for quality in (QualityGrade.C, QualityGrade.UNRATED):
            for entry in EntryState:
                expected[(quality, entry)] = ActionState.AVOID

        self.assertEqual(len(expected), len(QualityGrade) * len(EntryState))
        for combination, action in expected.items():
            with self.subTest(combination=combination):
                self.assertIs(map_action_state(*combination), action)
                self.assertIs(
                    map_action_state(combination[0].value, combination[1].value),
                    action,
                )

    def test_missing_data_behavior_is_explicit(self) -> None:
        for quality in QualityGrade:
            with self.subTest(quality=quality):
                self.assertIs(
                    map_action_state(quality, EntryState.INSUFFICIENT_DATA),
                    ActionState.AVOID,
                )
        decision = _decision(
            quality=QualityGrade.UNRATED,
            entry=EntryState.INSUFFICIENT_DATA,
        )
        payload = stock_decision_to_dict(decision)
        self.assertIsNone(payload["quality"]["data_asof"])
        self.assertEqual(payload["quality"]["missing"][0]["polarity"], "missing")
        self.assertEqual(payload["action_state"], "AVOID")

    def test_renderers_consume_canonical_action_without_recomputing(self) -> None:
        decision = _decision(action=ActionState.WATCH_PULLBACK)
        action_list = render_action_list([decision])
        detailed = render_detailed_report(decision)

        for rendered in (action_list, detailed):
            self.assertIn("Company Quality: A", rendered)
            self.assertIn("Entry Quality: ENTRY_READY", rendered)
            self.assertIn("Action State: WATCH_PULLBACK", rendered)
            self.assertNotIn("Action State: PRIORITY_REVIEW", rendered)
            self.assertIn("Fundamental data as-of: n/a", rendered)
            self.assertIn("Review trigger: n/a", rendered)

    def test_empty_action_list_has_stable_skeleton(self) -> None:
        self.assertEqual(render_action_list([]), "# Action List\n\n- no decisions\n")


if __name__ == "__main__":
    unittest.main()
