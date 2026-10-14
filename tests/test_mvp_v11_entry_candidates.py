"""Frozen offline E thresholds reuse canonical Entry and Action; no outcome reads."""
from __future__ import annotations

from dataclasses import replace
import unittest

import pandas as pd

from ai_value_scanner.decision.action import map_action_state
from ai_value_scanner.decision.entry import (
    build_entry_quality_v1, build_entry_quality_v11_offline,
)
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.model import EntryState, QualityGrade, ActionState
from ai_value_scanner.research.mvp_v11_candidates import (
    replay_candidate_day, scoring_features, migration_rows,
)


def row(symbol: str, *, rs: float, ret20: float, defensive: bool = False) -> dict:
    return {
        "signal_date": "2024-01-31", "symbol": symbol,
        "fundamental_data_asof": "2024-01-20", "market_asof": "2024-01-31",
        "price_to_sma200": 1.04, "price_to_sma50": 1.02,
        "return_20d": ret20, "return_60d": 0.10,
        "relative_strength_60d_qqq": rs,
        "drawdown_from_52w_high": .12, "range_position_52w": .6,
        "regime": "down" if defensive else "up",
        "fwd_ret_20": 9999, "qqq_return_60": -9999,
        "label_end_60": "2024-05-01",
    }


class TestMvpV11EntryCandidates(unittest.TestCase):
    def test_v1_shared_scoring_exact_evidence_parity(self):
        r = row("AAA", rs=-.02, ret20=.16)
        a = build_entry_quality_v1(r, decision_date="2024-01-31")
        b = build_entry_quality_v11_offline(
            r, decision_date="2024-01-31", market_asof=None,
            ready_rs60_min=-.03, overextended_return20_gt=.15,
        )
        self.assertEqual(a, b)
        self.assertEqual(a.state, EntryState.WATCH_PULLBACK)
        old = {e.code: e for e in a.risks}
        self.assertEqual(
            old["return_20d_overextended"].message,
            "Recent price appreciation is too extended for ENTRY_READY.",
        )

    def test_e1_e2_rs_gate_changes_entry_but_not_score(self):
        r = row("AAA", rs=-.01, ret20=.05)
        baseline = build_entry_quality_v1(r, decision_date="2024-01-31")
        self.assertEqual(baseline.state, EntryState.ENTRY_READY)
        e1 = build_entry_quality_v11_offline(
            r, decision_date="2024-01-31", market_asof=None,
            ready_rs60_min=0, overextended_return20_gt=.15,
        )
        self.assertEqual(e1.state, EntryState.WATCH_BREAKOUT)
        self.assertEqual((e1.score, e1.confidence), (baseline.score, baseline.confidence))
        bad = [e for e in e1.risks if e.code == "relative_strength_60d_qqq_below_candidate_ready"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].threshold, ">=0%")
        # defensive gate already requires >=5%; raising the base threshold has no effect
        r2 = row("BBB", rs=.02, ret20=.05, defensive=True)
        b2 = build_entry_quality_v1(r2, decision_date="2024-01-31")
        e2 = build_entry_quality_v11_offline(
            r2, decision_date="2024-01-31", market_asof=None,
            ready_rs60_min=.03, overextended_return20_gt=.15,
        )
        self.assertEqual(b2.state, e2.state)

    def test_e3_e4_overextension_does_not_relax_ready_return_gate(self):
        for ret, cid, expected in (
            (.14, "E3", EntryState.WATCH_PULLBACK),
            (.16, "E4", EntryState.WATCH_BREAKOUT),
        ):
            with self.subTest(cid=cid):
                frame = pd.DataFrame([row("AAA", rs=.10, ret20=ret)])
                result = replay_candidate_day(frame, signal_date="2024-01-31",
                                              candidate_id=cid)
                self.assertEqual(result[0].entry.state, expected)
                self.assertNotEqual(result[0].entry.state, EntryState.ENTRY_READY)
                self.assertEqual(
                    result[0].entry.score,
                    build_entry_quality_v1(frame.iloc[0], decision_date="2024-01-31").score,
                )
        e3 = replay_candidate_day(
            pd.DataFrame([row("AAA", rs=.10, ret20=.14)]),
            signal_date="2024-01-31", candidate_id="E3",
        )[0]
        evidence = {e.code: e for e in e3.entry.risks}
        self.assertEqual(evidence["return_20d_overextended"].threshold, "<=12%")

    def test_e_candidate_rebuilds_action_rationale_and_quality_unchanged(self):
        df = pd.DataFrame([row("AAA", rs=-.01, ret20=.05)])
        base = build_stock_decisions(scoring_features(df),
                                     decision_date="2024-01-31",
                                     generated_at_utc="2024-01-31T23:59:59+00:00")
        # Inject a grade A fixture without changing canonical Quality calculations.
        original = replace(
            base[0],
            quality=replace(base[0].quality, grade=QualityGrade.A),
            action_state=ActionState.PRIORITY_REVIEW,
        )
        e1 = replay_candidate_day(
            df, signal_date="2024-01-31", candidate_id="E1", baseline=(original,)
        )
        self.assertEqual(e1[0].action_state, ActionState.WATCH_BREAKOUT)
        self.assertEqual(e1[0].quality, original.quality)
        self.assertTrue(any(
            e.code == "relative_strength_60d_qqq_below_candidate_ready"
            for e in e1[0].rationale
        ))
        self.assertIn("entry_quality_v11_offline_E1", e1[0].provenance["entry_policy_version"])
        migrations = migration_rows((original,), e1, candidate_id="E1")
        self.assertTrue(migrations[0]["entry_state_changed"])
        self.assertTrue(migrations[0]["action_changed"])

    def test_b0_ranks_ignore_future_outcomes_and_reject_unregistered(self):
        df = pd.DataFrame([
            row("AAA", rs=.10, ret20=.04),
            row("BBB", rs=-.01, ret20=.06),
        ])
        baseline = replay_candidate_day(
            df, signal_date="2024-01-31", candidate_id="B0"
        )
        changed = df.copy()
        changed["fwd_ret_20"] = [-999999, 999999]
        changed["qqq_return_60"] = [123, -123]
        changed["label_end_60"] = "2035-01-01"
        again = replay_candidate_day(
            changed, signal_date="2024-01-31", candidate_id="B0"
        )
        self.assertEqual([(d.symbol, d.quality, d.entry, d.action_state)
                          for d in baseline],
                         [(d.symbol, d.quality, d.entry, d.action_state)
                          for d in again])
        with self.assertRaisesRegex(ValueError, "unregistered"):
            replay_candidate_day(df, signal_date="2024-01-31", candidate_id="X1")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            build_entry_quality_v11_offline(
                df.iloc[0], decision_date="2024-01-31", market_asof=None,
                ready_rs60_min=.05, overextended_return20_gt=.15,
            )


if __name__ == "__main__":
    unittest.main()
