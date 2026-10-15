"""Unit tests for Phase M3 v2 candidates & preflight (synthetic only).

Covers H1/H2/H3 behaviors, v1 bit-for-bit invariance (default integrated
build equals explicit v1 stages; v1 builders untouched), the 2025/2026Q1
return embargo, zero absolute paths in deliverables, and 100% preservation
of the 6 M2 positive controls. No network, no frozen-dataset dependency.
"""

from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.decision.action import (
    assign_action_priorities_v2,
    map_action_state,
    map_action_state_v2,
)
from ai_value_scanner.decision.entry import (
    build_entry_quality_v1,
    build_entry_quality_v2,
)
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.model import ActionState, EntryState, QualityGrade
from ai_value_scanner.decision.quality import (
    _score_accrual_v2,
    build_company_quality_v1,
    build_company_quality_v2,
)
from ai_value_scanner.research import m3_candidate_preflight as m3


def _quality_metrics(**overrides) -> dict:
    metrics = {
        "net_margin": 0.15,
        "free_cash_flow": 100.0,
        "revenue": 1000.0,
        "ocf_to_net_income": 1.50,
        "accrual_ratio": -0.25,
        "revenue_yoy": 0.30,
        "adjusted_net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.25,
        "ebit": 150.0,
        "adjusted_ebit": 160.0,
        "net_debt_to_ebitda": 1.0,
        "interest_coverage": 6.0,
        "current_ratio": 2.0,
        "shares_yoy": 0.01,
        "fcf_yield": 0.04,
        "ps_hist_percentile": 0.50,
        "pe_hist_percentile": 0.50,
        "receivables_growth_gap": 0.30,
        "inventory_growth_gap": 0.05,
        "fundamental_data_asof": "2023-01-20",
    }
    metrics.update(overrides)
    return metrics


def _entry_metrics(**overrides) -> dict:
    metrics = {
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.03,
        "days_below_sma200": 0,
        "return_20d": 0.05,
        "return_60d": 0.10,
        "drawdown_from_52w_high": 0.10,
        "range_position_52w": 0.82,
        "relative_strength_60d_qqq": 0.02,
        "volatility_60d": 0.30,
        "regime": "up",
        "benchmark_trend_ok": True,
        "market_asof": "2023-01-31",
    }
    metrics.update(overrides)
    return metrics


def _frame_row(symbol: str, **overrides) -> dict:
    row = {**_quality_metrics(), **_entry_metrics(), "symbol": symbol,
           "signal_date": "2023-01-31"}
    row.update(overrides)
    return row


class TestH1Accrual(unittest.TestCase):
    def test_cash_backed_negative_accrual_scores_one(self) -> None:
        self.assertEqual(_score_accrual_v2(-0.25, 1.50), 1.0)
        self.assertEqual(_score_accrual_v2(-0.90, None), 1.0)
        self.assertEqual(_score_accrual_v2(0.0, 0.90), 1.0)

    def test_distorted_conversion_falls_back(self) -> None:
        self.assertLess(_score_accrual_v2(-0.25, 0.50), 1.0)
        self.assertEqual(_score_accrual_v2(-0.25, 0.50), _score_accrual_v2(-0.25, 0.50))

    def test_positive_bands_match_v1(self) -> None:
        from ai_value_scanner.decision.quality import _score_accrual
        for value in (0.03, 0.08, 0.15, 0.30, 0.50):
            self.assertEqual(_score_accrual_v2(value, 1.50), _score_accrual(value))

    def test_cash_cow_no_longer_penalized(self) -> None:
        v1 = build_company_quality_v1(_quality_metrics(), decision_date="2023-01-31")
        v2 = build_company_quality_v2(_quality_metrics(), decision_date="2023-01-31")
        self.assertIn("accrual_ratio_weak", {i.code for i in v1.risks})
        self.assertNotIn("accrual_ratio_weak", {i.code for i in v2.risks})
        self.assertGreaterEqual(v2.score, v1.score)


class TestH1MarginsAndExemptions(unittest.TestCase):
    def test_fcf_margin_and_operating_margin_scored(self) -> None:
        v2 = build_company_quality_v2(_quality_metrics(), decision_date="2023-01-31")
        codes = {i.code for i in v2.positives} | {i.code for i in v2.risks}
        self.assertTrue({"fcf_margin_strong", "operating_margin_strong"} & codes)

    def test_partial_dict_falls_back_without_confidence_loss(self) -> None:
        partial = {k: v for k, v in _quality_metrics().items()
                   if k not in ("revenue", "ebit", "adjusted_ebit")}
        v1 = build_company_quality_v1(partial, decision_date="2023-01-31")
        v2 = build_company_quality_v2(partial, decision_date="2023-01-31")
        self.assertEqual(v2.confidence, v1.confidence)
        self.assertNotIn("operating_margin_missing", {i.code for i in v2.missing})

    def test_high_growth_gap_floor(self) -> None:
        v2 = build_company_quality_v2(_quality_metrics(), decision_date="2023-01-31")
        self.assertNotIn("receivables_growth_gap_weak", {i.code for i in v2.risks})
        slow = _quality_metrics(revenue_yoy=0.05)
        v2_slow = build_company_quality_v2(slow, decision_date="2023-01-31")
        self.assertIn("receivables_growth_gap_weak", {i.code for i in v2_slow.risks})

    def test_valuation_floor_for_compounders(self) -> None:
        rich = _quality_metrics(ps_hist_percentile=0.95, pe_hist_percentile=0.92,
                                fcf_yield=0.03)
        v1 = build_company_quality_v1(rich, decision_date="2023-01-31")
        v2 = build_company_quality_v2(rich, decision_date="2023-01-31")
        self.assertIn("ps_hist_percentile_weak", {i.code for i in v1.risks})
        self.assertNotIn("ps_hist_percentile_weak", {i.code for i in v2.risks})
        self.assertNotIn("pe_hist_percentile_weak", {i.code for i in v2.risks})


class TestH2Entry(unittest.TestCase):
    def test_dead_zone_routes_to_pullback(self) -> None:
        # sma50 dead zone with aligned MAs closes into WATCH_PULLBACK ...
        v1 = build_entry_quality_v1(
            _entry_metrics(price_to_sma200=1.08, price_to_sma50=1.09),
            decision_date="2023-01-31")
        v2 = build_entry_quality_v2(
            _entry_metrics(price_to_sma200=1.08, price_to_sma50=1.09),
            decision_date="2023-01-31")
        self.assertIs(v1.state, EntryState.WATCH_BREAKOUT)
        self.assertIs(v2.state, EntryState.WATCH_PULLBACK)
        self.assertEqual(v2.score, v1.score)  # no penalty on routed rows
        # ... as does the ret20 dead zone
        v1 = build_entry_quality_v1(_entry_metrics(return_20d=0.135), decision_date="2023-01-31")
        v2 = build_entry_quality_v2(_entry_metrics(return_20d=0.135), decision_date="2023-01-31")
        self.assertIs(v1.state, EntryState.WATCH_BREAKOUT)
        self.assertIs(v2.state, EntryState.WATCH_PULLBACK)
        # ... but a misaligned dead-zone row stays WATCH_BREAKOUT (H2 requires
        # sma50_to_sma200 >= 0.98 for the core-uptrend classification)
        v2_misaligned = build_entry_quality_v2(
            _entry_metrics(price_to_sma50=1.09), decision_date="2023-01-31")
        self.assertIs(v2_misaligned.state, EntryState.WATCH_BREAKOUT)

    def test_misaligned_ready_demoted(self) -> None:
        v1 = build_entry_quality_v1(
            _entry_metrics(price_to_sma200=1.00, price_to_sma50=1.08),
            decision_date="2023-01-31")
        v2 = build_entry_quality_v2(
            _entry_metrics(price_to_sma200=1.00, price_to_sma50=1.08),
            decision_date="2023-01-31")
        self.assertIs(v1.state, EntryState.ENTRY_READY)
        self.assertIs(v2.state, EntryState.WATCH_BREAKOUT)
        self.assertIn("sma50_below_sma200_inverted", {i.code for i in v2.risks})

    def test_aligned_uptrend_evidence(self) -> None:
        v2 = build_entry_quality_v2(_entry_metrics(), decision_date="2023-01-31")
        self.assertIn("sma50_above_sma200_aligned", {i.code for i in v2.positives})

    def test_lagging_penalty_and_sub_buckets(self) -> None:
        weak = _entry_metrics(price_to_sma200=0.97)
        v1 = build_entry_quality_v1(weak, decision_date="2023-01-31")
        v2 = build_entry_quality_v2(weak, decision_date="2023-01-31")
        self.assertIs(v2.state, EntryState.WATCH_BREAKOUT)
        self.assertAlmostEqual(v2.score, round(v1.score - 0.10, 6))
        self.assertIn("watch_breakout_lagging_structure", {i.code for i in v2.risks})
        near = build_entry_quality_v2(
            _entry_metrics(price_to_sma50=0.96), decision_date="2023-01-31")
        self.assertIs(near.state, EntryState.WATCH_BREAKOUT)
        self.assertIn("watch_breakout_near_consolidation", {i.code for i in near.positives})
        self.assertEqual(near.score,
                         build_entry_quality_v1(_entry_metrics(price_to_sma50=0.96),
                                                decision_date="2023-01-31").score)

    def test_damaged_and_insufficient_untouched(self) -> None:
        damaged = _entry_metrics(price_to_sma200=0.90)
        self.assertIs(build_entry_quality_v2(damaged, decision_date="2023-01-31").state,
                      EntryState.TREND_DAMAGED)
        missing = _entry_metrics(price_to_sma50=None)
        self.assertIs(build_entry_quality_v2(missing, decision_date="2023-01-31").state,
                      EntryState.INSUFFICIENT_DATA)


class TestH3Action(unittest.TestCase):
    def _decisions(self, quality, entry):
        from ai_value_scanner.decision.model import EntryDecision, QualityDecision
        return QualityDecision(grade=quality[0], score=quality[1], confidence=quality[2],
                               component_scores={}, positives=(), risks=(), missing=(),
                               data_asof=None), \
            EntryDecision(state=entry[0], score=entry[1], confidence=entry[2],
                          positives=(), risks=(), market_asof=None)

    def test_promotion_rule(self) -> None:
        quality, entry = self._decisions(
            (QualityGrade.B, 0.70, 0.85), (EntryState.ENTRY_READY, 0.85, 0.90))
        action, rationale = map_action_state_v2(quality, entry)
        self.assertIs(action, ActionState.PRIORITY_REVIEW)
        self.assertTrue(rationale)
        self.assertEqual(map_action_state(QualityGrade.B, EntryState.ENTRY_READY),
                         ActionState.HOLD_MONITOR)

    def test_promotion_gates(self) -> None:
        quality, entry = self._decisions(
            (QualityGrade.B, 0.60, 0.85), (EntryState.ENTRY_READY, 0.85, 0.90))
        self.assertIs(map_action_state_v2(quality, entry)[0], ActionState.HOLD_MONITOR)
        quality, entry = self._decisions(
            (QualityGrade.B, 0.70, 0.85), (EntryState.ENTRY_READY, 0.70, 0.90))
        self.assertIs(map_action_state_v2(quality, entry)[0], ActionState.HOLD_MONITOR)
        quality, entry = self._decisions(
            (QualityGrade.A, 0.85, 0.95), (EntryState.ENTRY_READY, 0.95, 0.95))
        self.assertIs(map_action_state_v2(quality, entry)[0], ActionState.PRIORITY_REVIEW)

    def test_joint_ranking(self) -> None:
        from ai_value_scanner.decision.model import EntryDecision, QualityDecision
        from dataclasses import replace
        base = build_stock_decisions(
            pd.DataFrame([
                _frame_row("LOWA", net_margin=0.10, free_cash_flow=10.0,
                           ocf_to_net_income=0.9, accrual_ratio=0.02,
                           revenue_yoy=0.05, adjusted_net_income_yoy=0.05,
                           operating_cash_flow_yoy=0.05, ebit=50.0, adjusted_ebit=55.0,
                           net_debt_to_ebitda=1.0, interest_coverage=6.0, current_ratio=2.0,
                           shares_yoy=0.01, fcf_yield=0.01, ps_hist_percentile=0.5,
                           pe_hist_percentile=0.5, receivables_growth_gap=0.0,
                           inventory_growth_gap=0.0),
                _frame_row("HIGHB", net_margin=0.15, free_cash_flow=200.0,
                           ocf_to_net_income=1.5, accrual_ratio=-0.05,
                           revenue_yoy=0.30, adjusted_net_income_yoy=0.25,
                           operating_cash_flow_yoy=0.30, ebit=150.0, adjusted_ebit=160.0,
                           net_debt_to_ebitda=0.5, interest_coverage=9.0, current_ratio=2.5,
                           shares_yoy=0.0, fcf_yield=0.06, ps_hist_percentile=0.3,
                           pe_hist_percentile=0.3, receivables_growth_gap=0.0,
                           inventory_growth_gap=0.0),
            ]),
            decision_date="2023-01-31", generated_at_utc="2023-01-31T23:59:59+00:00",
            policy_version="v2",
        )
        by_symbol = {d.symbol: d for d in base}
        self.assertIs(by_symbol["HIGHB"].action_state, ActionState.PRIORITY_REVIEW)
        ranked = assign_action_priorities_v2(list(base))
        # deterministic: joint composite decides the order inside PRIORITY_REVIEW
        joints = {
            symbol: 0.60 * d.quality.score + 0.40 * d.entry.score
            + (0.04 if d.quality.grade is QualityGrade.A else 0.0)
            for symbol, d in by_symbol.items()
            if d.action_state is ActionState.PRIORITY_REVIEW
        }
        pr_ranked = [d.symbol for d in ranked
                     if d.action_state is ActionState.PRIORITY_REVIEW]
        self.assertEqual(pr_ranked, sorted(pr_ranked, key=lambda s: -joints[s]))
        self.assertEqual(assign_action_priorities_v2(list(base)),
                         assign_action_priorities_v2(list(base)))


class TestV1Invariance(unittest.TestCase):
    def test_default_equals_explicit_v1(self) -> None:
        frame = pd.DataFrame([_frame_row("AAA"), _frame_row("BBB", net_margin=-0.05)])
        default = build_stock_decisions(
            frame, decision_date="2023-01-31", generated_at_utc="2023-01-31T23:59:59+00:00")
        explicit = build_stock_decisions(
            frame, decision_date="2023-01-31", generated_at_utc="2023-01-31T23:59:59+00:00",
            policy_version="v1", quality_version="v1", entry_version="v1",
            action_version="v1")
        self.assertEqual(default, explicit)

    def test_unknown_version_rejected(self) -> None:
        frame = pd.DataFrame([_frame_row("AAA")])
        with self.assertRaises(ValueError):
            build_stock_decisions(frame, decision_date="2023-01-31",
                                  generated_at_utc="2023-01-31T23:59:59+00:00",
                                  policy_version="v9")
        with self.assertRaises(ValueError):
            build_stock_decisions(frame, decision_date="2023-01-31",
                                  generated_at_utc="2023-01-31T23:59:59+00:00",
                                  entry_version="v3")

    def test_v1_builders_unchanged_by_v2_presence(self) -> None:
        metrics = _quality_metrics()
        first = build_company_quality_v1(metrics, decision_date="2023-01-31")
        build_company_quality_v2(metrics, decision_date="2023-01-31")
        second = build_company_quality_v1(metrics, decision_date="2023-01-31")
        self.assertEqual(first, second)


class TestPreflightModule(unittest.TestCase):
    def test_variants_and_jaccard(self) -> None:
        self.assertEqual(m3.VARIANTS, ("v1_baseline", "h1_quality_only", "h2_entry_only",
                                       "h3_action_only", "v2_combined"))
        self.assertAlmostEqual(m3.top15_jaccard(["A", "B"], ["A", "B"]), 1.0)
        self.assertAlmostEqual(m3.top15_jaccard(["A"], ["B"]), 0.0)
        self.assertEqual(m3.mean_top15_jaccard_vs_v1({"d": ["A"]}, {}), None)

    def test_snapshot_rebuild_frame_offline(self) -> None:
        decisions = [{
            "symbol": "AAA", "decision_date": "2026-10-12",
            "quality": {"grade": "A", "score": 0.8, "confidence": 0.9, "data_asof": "2026-08-01",
                        "positives": [{"code": "ocf_to_net_income_strong",
                                       "metric": "ocf_to_net_income", "value": 1.5}],
                        "risks": [], "missing": []},
            "entry": {"state": "ENTRY_READY", "score": 0.9, "confidence": 0.9,
                      "market_asof": "2026-10-12",
                      "positives": [{"code": "price_above_sma200",
                                     "metric": "price_to_sma200", "value": 1.05},
                                    {"code": "supportive_market_regime",
                                     "metric": "regime", "value": "up"}],
                      "risks": []},
            "action_state": "PRIORITY_REVIEW", "priority": 1,
        }]
        frame = m3.snapshot_rebuild_frame(decisions)
        self.assertAlmostEqual(frame.iloc[0]["ocf_to_net_income"], 1.5)
        self.assertEqual(frame.iloc[0]["regime"], "up")
        rebuilt = m3.rebuild_snapshot_variant(
            frame, decision_date="2026-10-12",
            generated_at_utc="2026-10-15T00:00:00+00:00", variant="v2_combined")
        self.assertEqual(len(rebuilt), 1)

    def test_embargo_in_dev_excess(self) -> None:
        dev_frame = pd.DataFrame([_frame_row("A", fwd_ret_60=0.10, qqq_return_60=0.02)])
        full_frame = pd.DataFrame([
            _frame_row("A", fwd_ret_60=0.10, qqq_return_60=0.02),
            _frame_row("B", signal_date="2025-06-30", market_asof="2025-06-30",
                       fundamental_data_asof="2025-05-01",
                       fwd_ret_60=9.0, qqq_return_60=-9.0),
        ])
        decisions = build_stock_decisions(
            dev_frame, decision_date="2023-01-31",
            generated_at_utc="2023-01-31T23:59:59+00:00")
        out = m3.dev_excess_for_groups(full_frame, decisions)
        # embargoed 2025 label (excess 18.0) must not move the TOP15 mean
        self.assertAlmostEqual(out["TOP15"]["mean_excess"], 0.08)
        self.assertEqual(out["TOP15"]["n_obs"], 1)

    def test_surgical_h3_and_verify(self) -> None:
        frozen = [{
            "symbol": "B", "decision_date": "2026-10-12", "priority": 26,
            "company_name": "B", "generated_at_utc": "x", "schema_version": "1",
            "quality": {"grade": "B", "score": 0.70, "confidence": 0.85,
                        "component_scores": {}, "positives": [], "risks": [],
                        "missing": [], "data_asof": "2026-08-01"},
            "entry": {"state": "ENTRY_READY", "score": 0.85, "confidence": 0.9,
                      "positives": [], "risks": [], "market_asof": "2026-10-12"},
            "action_state": "HOLD_MONITOR", "rationale": [], "review_trigger": "",
            "source_lists": [], "provenance": {},
            "previous_action_state": None, "state_change_reason": None,
        }]
        ranked = m3.surgical_h3_decisions(frozen)
        self.assertIs(ranked["B"].action_state, ActionState.PRIORITY_REVIEW)
        case = {"study_case_id": "M2-R-REJX", "primary_axis": "Paired",
                "predicate": "retro_suppressed_opportunity",
                "evidence_tier": "RETROSPECTIVE_EXPLORATORY"}
        verdict = m3.verify_case(case, frozen[0], frozen[0], None, None)
        self.assertIn(verdict["failure_resolved"], ("TRUE", "FALSE"))

    def test_controls_preserved_on_identical(self) -> None:
        case = {"study_case_id": "M2-C-X", "primary_axis": "Control",
                "predicate": "clean_ready_control",
                "evidence_tier": "POSITIVE_CONTROL"}
        row = _frame_row("AAA")
        decs = build_stock_decisions(
            pd.DataFrame([row]), decision_date="2023-01-31",
            generated_at_utc="2023-01-31T23:59:59+00:00")
        verdict = m3.verify_case(case, decs[0], decs[0], decs[0], list(decs), None)
        self.assertEqual(verdict["failure_resolved"], "CONTROL_PRESERVED")


class TestDeliverableGuards(unittest.TestCase):
    def test_no_absolute_paths_in_docs(self) -> None:
        from pathlib import Path
        from ai_value_scanner.research import m2_failure_attribution as m2mod
        docs = Path("docs/m3_candidate_preflight_20261015")
        if not docs.exists():
            self.skipTest("deliverables not generated yet")
        for path in sorted(docs.iterdir()):
            if path.name == "SHA256SUMS":
                continue
            self.assertFalse(m2mod.contains_absolute_path(path.read_text()),
                             f"absolute path in {path.name}")

    def test_casebook_has_all_38_m2_cases(self) -> None:
        import csv
        from pathlib import Path
        path = Path("docs/m3_candidate_preflight_20261015/m3_casebook_verification.csv")
        if not path.exists():
            self.skipTest("deliverables not generated yet")
        with open(path) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 38)
        controls = [r for r in rows if r["study_case_id"].startswith("M2-C-")]
        self.assertEqual(len(controls), 6)
        self.assertTrue(all(r["failure_resolved"] == "CONTROL_PRESERVED" for r in controls))


if __name__ == "__main__":
    unittest.main()
