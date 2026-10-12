"""Phase 2 acceptance: Action List / Detailed Report clarity (no network).

All fixtures are synthetic StockDecision shapes (ABBV-like priority,
bank-C, UNRATED, state-change, stale/identity). They assert RENDER
behavior only — grades and states are taken as given, never recomputed.
"""

from __future__ import annotations

import unittest

from ai_value_scanner.decision.model import (
    ActionState,
    EntryDecision,
    EntryState,
    EvidenceItem,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)

BANNED = ("立即买入", "buy now", "price target", "目标价", "guaranteed",
          "保证收益", "bad balance sheet")


def _ev(code: str, polarity: str = "positive", metric: str | None = "x",
        value: object = 1.0) -> EvidenceItem:
    return EvidenceItem(code=code, label=f"label {code}", polarity=polarity,  # type: ignore[arg-type]
                        metric=metric, value=value, threshold="t",
                        message=f"message {code}")


def _decision(*, symbol: str = "ABBV", grade: QualityGrade = QualityGrade.A,
              state: EntryState = EntryState.ENTRY_READY,
              action: ActionState = ActionState.PRIORITY_REVIEW,
              missing: tuple = (), risks: tuple = (),
              previous: ActionState | None = None,
              change: str | None = None,
              fund_asof: str | None = "2026-08-03",
              mkt_asof: str | None = "2026-10-09",
              conf: float = 1.0) -> StockDecision:
    qpos = (_ev("free_cash_flow_strong"), _ev("revenue_yoy_strong"))
    epos = (_ev("trend_intact"),)
    quality = QualityDecision(grade=grade, score=0.75, confidence=conf,
                              component_scores={"profitability_cash": 0.8},
                              positives=qpos, risks=tuple(risks),
                              missing=tuple(missing), data_asof=fund_asof)
    entry = EntryDecision(state=state, score=0.6, confidence=0.9,
                          positives=epos, risks=(),
                          market_asof=mkt_asof)
    rationale = qpos + epos + tuple(risks) + tuple(missing)
    return StockDecision(schema_version="v1", symbol=symbol,
                         company_name=f"{symbol} Inc.",
                         decision_date="2026-10-09",
                         generated_at_utc="2026-10-11T00:00:00+00:00",
                         quality=quality, entry=entry, action_state=action,
                         priority=7, rationale=rationale,
                         review_trigger="Review now.",
                         source_lists=("research_pool",), provenance={},
                         previous_action_state=previous,
                         state_change_reason=change)


def _bank_c() -> StockDecision:
    return _decision(symbol="JPM", grade=QualityGrade.C,
                     state=EntryState.WATCH_BREAKOUT,
                     action=ActionState.AVOID,
                     risks=(_ev("net_debt_to_ebitda_weak", "negative"),))


def _unrated() -> StockDecision:
    return _decision(symbol="XOM", grade=QualityGrade.UNRATED,
                     state=EntryState.TREND_DAMAGED,
                     action=ActionState.AVOID, conf=0.17,
                     missing=(_ev("net_margin_missing", "missing"),
                              _ev("free_cash_flow_missing", "missing")),
                     fund_asof="2026-07-30")


def _stale_identity() -> StockDecision:
    return _decision(symbol="ZZZ", risks=(),
                     missing=(_ev("operating_entity_unverified", "missing"),
                              _ev("fundamental_data_severely_stale", "negative")))


class ReportClarityTests(unittest.TestCase):
    def assertConsistentPair(self, decision: StockDecision) -> None:
        listed = render_action_list([decision])
        detailed = render_detailed_report(decision)
        tokens = [decision.quality.grade.value, decision.entry.state.value,
                  decision.action_state.value, decision.decision_date,
                  str(decision.quality.data_asof), str(decision.entry.market_asof)]
        for rendered in (listed, detailed):
            for token in tokens:
                self.assertIn(token, rendered)
        for item in (*decision.quality.risks, *decision.quality.missing):
            self.assertIn(item.code, detailed)

    def test_abbv_priority_consistent_across_reports(self) -> None:
        decision = _decision(previous=ActionState.PRIORITY_REVIEW)
        self.assertConsistentPair(decision)
        detailed = render_detailed_report(decision)
        self.assertIn("PRIORITY_REVIEW", render_action_list([decision]))
        self.assertIn("detailed/ABBV.md", render_action_list([decision]))

    def test_bank_c_shows_grade_plus_unverified_applicability(self) -> None:
        decision = _bank_c()
        detailed = render_detailed_report(decision)
        self.assertIn("Company Quality: C", render_action_list([decision]))
        self.assertIn("UNVERIFIED", detailed)
        self.assertIn("must not be read as sector-relative quality", detailed)
        for bad in BANNED:
            self.assertNotIn(bad, detailed)

    def test_unrated_explains_missing_and_next_steps(self) -> None:
        decision = _unrated()
        detailed = render_detailed_report(decision)
        self.assertIn("UNRATED", detailed)
        self.assertIn("net_margin_missing", detailed)
        self.assertIn("Supplement:", detailed)
        self.assertIn("no reliable company judgement", detailed)

    def test_all_entry_states_have_named_structure(self) -> None:
        for state in EntryState:
            with self.subTest(state=state):
                decision = _decision(state=state)
                detailed = render_detailed_report(decision)
                self.assertIn(f"State: {state.value}", detailed)
                self.assertIn("Structure:", detailed)

    def test_state_change_reports_previous_and_reason(self) -> None:
        decision = _decision(state=EntryState.WATCH_BREAKOUT,
                             action=ActionState.HOLD_MONITOR,
                             previous=ActionState.PRIORITY_REVIEW,
                             change="Entry Quality ENTRY_READY→WATCH_BREAKOUT.")
        detailed = render_detailed_report(decision)
        self.assertIn("PRIORITY_REVIEW", detailed)
        self.assertIn("ENTRY_READY→WATCH_BREAKOUT", detailed)

    def test_stale_identity_banner_without_false_confidence(self) -> None:
        decision = _stale_identity()
        detailed = render_detailed_report(decision)
        self.assertIn("read before acting", detailed)
        self.assertIn("identity UNVERIFIED", detailed)
        for bad in BANNED + ("high confidence", "可靠"):
            self.assertNotIn(bad, detailed)

    def test_banned_trade_language_absent_everywhere(self) -> None:
        decisions = ([_decision(), _bank_c(), _unrated(), _stale_identity()]
                     + [_decision(state=s) for s in EntryState])
        for decision in decisions:
            with self.subTest(symbol=decision.symbol):
                blob = render_action_list([decision]) + render_detailed_report(decision)
                for bad in BANNED:
                    self.assertNotIn(bad, blob)
                self.assertIn("not automated trade instructions", render_action_list([decision]))


if __name__ == "__main__":
    unittest.main()
