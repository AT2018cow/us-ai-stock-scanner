"""Synthetic only: paired label masks, no candidate outperformance study."""
from __future__ import annotations

from dataclasses import replace
import unittest

import pandas as pd

from ai_value_scanner.decision.model import (
    StockDecision, EntryDecision, QualityDecision, EntryState,
    ActionState, QualityGrade,
)
from ai_value_scanner.research.mvp_v11_comparison import paired_topk_day
from ai_value_scanner.research.mvp_v11_score_masks import score_source_flags


DAY = "2024-01-31"


def decisions() -> tuple[StockDecision, ...]:
    return tuple(
        StockDecision(
            schema_version="1", symbol=f"A{i:02d}", company_name=None,
            decision_date=DAY, generated_at_utc="2024-02-01T00:00:00Z",
            quality=QualityDecision(
                grade=QualityGrade.A, score=0.80, confidence=.90,
                component_scores={}, positives=(), risks=(),
                missing=(), data_asof="2024-01-20",
            ),
            entry=EntryDecision(
                state=EntryState.ENTRY_READY, score=.80,
                confidence=.90, positives=(), risks=(), market_asof=DAY,
            ),
            action_state=ActionState.PRIORITY_REVIEW, priority=i,
            rationale=(), review_trigger=None, source_lists=(), provenance={},
        )
        for i in range(1, 17)
    )


def inputs():
    base = decisions()
    alternate = tuple(
        replace(d, priority=(16 if d.symbol == "A01" else 1 if d.symbol == "A16" else d.priority))
        for d in base
    )
    labels = pd.DataFrame([
        {
            "signal_date": DAY, "symbol": d.symbol,
            "fwd_ret_60": .20 if d.symbol == "A16"
            else .01 if d.symbol == "A01" else .04,
            "qqq_return_60": .03,
        }
        for d in base
    ])
    events = pd.DataFrame([
        {
            "signal_date": DAY, "symbol": d.symbol,
            "horizon": 60, "event_interval_exposed": False,
            "label_end_missing": False,
        } for d in base
    ])
    scores = pd.DataFrame([
        {
            "signal_date": DAY, "symbol": d.symbol,
            "score_source_uncertain": False
        } for d in base
    ])
    return base, alternate, labels, events, scores


def compare(*, cap=15, **overrides):
    base, alt, labels, events, scores = inputs()
    return paired_topk_day(
        signal_date=DAY, candidate_id="SYNTHETIC_TEST", horizon=60, cap=cap,
        baseline=overrides.get("baseline", base),
        candidate=overrides.get("candidate", alt),
        labels=overrides.get("labels", labels),
        event_flags=overrides.get("event_flags", events),
        score_flags=overrides.get("score_flags", scores),
    )


class TestHistoricalPairing(unittest.TestCase):
    def test_selected_swaps_paired_excess_is_date_equal_weight(self):
        result = compare()
        self.assertTrue(result["primary_paired_valid"])
        self.assertEqual(result["n_topk_swaps"], 1)
        self.assertEqual(result["removed_symbols"], "A01")
        self.assertEqual(result["added_symbols"], "A16")
        self.assertAlmostEqual(result["paired_delta_net_qqq_excess"], .19 / 15)
        self.assertTrue(result["event_sensitivity_valid"])
        self.assertTrue(result["score_sensitivity_valid"])

    def test_reordering_with_same_topk_has_no_net_gain(self):
        base, _, labels, events, scores = inputs()
        shuffled = tuple(replace(d, priority=16 - d.priority) for d in base[:15]) + base[15:]
        result = compare(candidate=shuffled)
        self.assertEqual(result["n_topk_swaps"], 0)
        self.assertAlmostEqual(result["paired_delta_net_qqq_excess"], 0)

    def test_any_missing_stock_label_masks_entire_paired_date(self):
        base, alt, labels, events, scores = inputs()
        labels.loc[labels.symbol == "A16", "fwd_ret_60"] = float("nan")
        result = compare(labels=labels)
        self.assertFalse(result["primary_paired_valid"])
        self.assertIsNone(result["paired_delta_net_qqq_excess"])
        self.assertEqual(result["missing_label_symbols"], "A16")

    def test_event_flags_are_retrospective_sensitivity_only(self):
        base, alt, labels, events, scores = inputs()
        events.loc[events.symbol == "A16", "event_interval_exposed"] = True
        baseline = compare()
        flagged = compare(event_flags=events)
        self.assertEqual(baseline["paired_delta_net_qqq_excess"],
                         flagged["paired_delta_net_qqq_excess"])
        self.assertFalse(flagged["event_sensitivity_valid"])
        self.assertEqual(flagged["event_exposed_symbols"], "A16")
        scores.loc[scores.symbol == "A01", "score_source_uncertain"] = True
        flagged = compare(score_flags=scores)
        self.assertFalse(flagged["score_sensitivity_valid"])

    def test_missing_label_end_is_a_whole_pair_invalidity(self):
        _, _, _, events, _ = inputs()
        events.loc[events.symbol == "A16", "label_end_missing"] = True
        outcome = compare(event_flags=events)
        self.assertFalse(outcome["primary_paired_valid"])
        self.assertIsNone(outcome["paired_delta_net_qqq_excess"])
        self.assertEqual(outcome["missing_label_symbols"], "A16")

    def test_missing_uncertainty_mask_fails_closed(self):
        base, alt, labels, events, scores = inputs()
        with self.assertRaisesRegex(ValueError, "missing uncertainty mask"):
            compare(score_flags=scores[scores.symbol != "A01"])
        with self.assertRaisesRegex(ValueError, "non-boolean"):
            scores.loc[scores.symbol == "A01", "score_source_uncertain"] = "unknown"
            compare(score_flags=scores)

    def test_different_universe_does_not_pair(self):
        base, alt, labels, events, scores = inputs()
        with self.assertRaisesRegex(ValueError, "different candidate"):
            compare(candidate=alt[:-1])


class TestScoreSourceSidecar(unittest.TestCase):
    def test_hei_is_review_only_not_lookahead_stock_filter(self):
        df = pd.DataFrame([
            {"signal_date": "2024-12-31", "symbol": "HEI",
             "fundamental_data_asof": "2024-12-19", "fwd_ret_60": -999},
            {"signal_date": "2024-11-29", "symbol": "HEI",
             "fundamental_data_asof": "2024-11-25", "fwd_ret_60": 999},
            {"signal_date": "2024-12-31", "symbol": "BBB",
             "fundamental_data_asof": None, "fwd_ret_60": -999},
        ])
        flagged = score_source_flags(df)
        self.assertEqual(len(flagged), 3)
        self.assertNotIn("fwd_ret_60", flagged)
        hei = flagged[flagged.symbol == "HEI"]
        self.assertTrue(hei.score_source_uncertain.all())
        self.assertEqual(hei.hei_source_confirmed_date.sum(), 1)
        self.assertTrue(flagged.loc[flagged.symbol == "BBB",
                                    "missing_fundamental_asof"].iloc[0])
        df.fwd_ret_60 = [5, 6, 7]
        pd.testing.assert_frame_equal(flagged, score_source_flags(df))

    def test_severe_share_event_only_flagged_on_detection_date(self):
        df = pd.DataFrame([
            {"signal_date": "2024-01-31", "symbol": "HXL", "fundamental_data_asof": "2024-01-10"},
            {"signal_date": "2024-02-29", "symbol": "HXL", "fundamental_data_asof": "2024-02-10"},
        ])
        events = pd.DataFrame([{
            "symbol": "HXL", "event_date": "2024-02-29",
            "severe_shares_change": True, "null_labels": False,
        }])
        flags = score_source_flags(df, event_review=events)
        self.assertFalse(flags.loc[flags.signal_date == "2024-01-31",
                                   "score_source_uncertain"].iloc[0])
        self.assertTrue(flags.loc[flags.signal_date == "2024-02-29",
                                  "severe_share_event_on_date"].iloc[0])


if __name__ == "__main__":
    unittest.main()
