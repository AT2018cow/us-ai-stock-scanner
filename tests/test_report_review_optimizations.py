"""Report-review optimizations: pre-earnings, extension, split-guard, concentration.

Covers the 4 surgical v2/report enhancements while asserting v1 builders,
v1 renderers, and pre-existing M0-M5 behavior stay 100% untouched.
Synthetic fixtures only; no network calls.
"""

from __future__ import annotations

import unittest

from ai_value_scanner.decision.action import (
    H3_PRE_EARNINGS_PRIORITY_PENALTY,
    assign_action_priorities_v2,
)
from ai_value_scanner.decision.entry import (
    ENTRY_V2_EXTENSION_MILD_PENALTY,
    ENTRY_V2_EXTENSION_SEVERE_PENALTY,
    build_entry_quality_v1,
    build_entry_quality_v2,
)
from ai_value_scanner.decision.model import (
    ActionState,
    EntryDecision,
    EntryState,
    EvidenceItem,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.decision.quality import (
    QUALITY_V2_ORGANIC_SHARES_YOY_MAX,
    QUALITY_V2_ORGANIC_SHARES_YOY_MIN,
    QUALITY_V2_PRE_EARNINGS_WARN_DAYS,
    build_company_quality_v1,
    build_company_quality_v2,
)
from ai_value_scanner.decision.view_model import (
    _BUCKET_PRIORITY,
    _NON_BLOCKING_ENTRY_WARN_CODES,
    _format_bucket_tokens,
    _normalize_primary_bucket,
    build_snapshot_view_model,
    build_stock_card_view_model,
)
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_action_list_v2,
    render_detailed_report,
)


def _quality_metrics(**overrides):
    base = dict(
        net_margin=0.15,
        free_cash_flow=100.0,
        revenue=1000.0,
        ocf_to_net_income=1.2,
        accrual_ratio=-0.04,
        revenue_yoy=0.10,
        adjusted_net_income_yoy=0.10,
        operating_cash_flow_yoy=0.10,
        net_debt_to_ebitda=1.0,
        interest_coverage=6.0,
        current_ratio=2.0,
        shares_yoy=0.01,
        fcf_yield=0.04,
        ps_hist_percentile=0.50,
        pe_hist_percentile=0.50,
        receivables_growth_gap=0.0,
        inventory_growth_gap=0.0,
        ebit=150.0,
    )
    base.update(overrides)
    return base


def _entry_metrics(**overrides):
    base = dict(
        price_to_sma200=1.05,
        price_to_sma50=1.03,
        days_below_sma200=0,
        return_20d=0.05,
        return_60d=0.10,
        drawdown_from_52w_high=0.08,
        range_position_52w=0.82,
        relative_strength_60d_qqq=0.04,
        volatility_60d=0.30,
        regime="up",
        benchmark_trend_ok=True,
        market_asof="2026-10-15",
    )
    base.update(overrides)
    return base


def _ev(code, *, polarity="positive", metric="x", value=1.0, threshold="t"):
    return EvidenceItem(
        code=code,
        label=f"label {code}",
        polarity=polarity,  # type: ignore[arg-type]
        metric=metric,
        value=value,  # type: ignore[arg-type]
        threshold=threshold,  # type: ignore[arg-type]
        message=f"message {code}",
    )


def _ready_entry_positives():
    return (
        _ev("market_data_fresh", metric="market_data_age_days", value=0),
        _ev("price_above_sma200", metric="price_to_sma200", value=1.08),
        _ev("price_near_sma50_ready_band", metric="price_to_sma50", value=1.0),
        _ev("return_20d_ready_band", metric="return_20d", value=0.05),
        _ev("return_60d_nonnegative", metric="return_60d", value=0.06),
        _ev("relative_strength_60d_qqq_ready",
            metric="relative_strength_60d_qqq", value=0.01),
        _ev("supportive_market_regime", metric="regime", value="up"),
    )


def _decision(
    *,
    symbol="EXM",
    grade=QualityGrade.A,
    entry_state=EntryState.ENTRY_READY,
    action=ActionState.PRIORITY_REVIEW,
    priority=1,
    entry_risks=(),
    quality_risks=(),
    provenance=None,
    entry_score=0.9,
    quality_score=0.8,
):
    entry = EntryDecision(
        state=entry_state, score=entry_score, confidence=1.0,
        positives=_ready_entry_positives(), risks=tuple(entry_risks),
        market_asof="2026-10-12",
    )
    quality = QualityDecision(
        grade=grade, score=quality_score, confidence=0.9,
        component_scores={"profitability_cash": 0.8},
        positives=(_ev("net_margin_strong", metric="net_margin", value=0.2),),
        risks=tuple(quality_risks), missing=(),
        data_asof="2026-08-27",
    )
    return StockDecision(
        schema_version="1", symbol=symbol, company_name=symbol,
        decision_date="2026-10-15", generated_at_utc="x",
        quality=quality, entry=entry, action_state=action, priority=priority,
        rationale=(), review_trigger="r", source_lists=(),
        provenance=dict(provenance or {}),
        previous_action_state=None, state_change_reason=None,
    )


class TestQualityV2PreEarnings(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual(QUALITY_V2_PRE_EARNINGS_WARN_DAYS, 70)
        self.assertEqual(QUALITY_V2_ORGANIC_SHARES_YOY_MIN, -0.30)
        self.assertEqual(QUALITY_V2_ORGANIC_SHARES_YOY_MAX, 1.00)

    def test_window_boundaries(self) -> None:
        for age, expected in ((69, False), (70, True), (120, True), (400, True), (401, False)):
            with self.subTest(age=age):
                # data_asof back-dated by `age` days from decision date
                from datetime import date, timedelta
                asof = (date(2026, 10, 15) - timedelta(days=age)).isoformat()
                decision = build_company_quality_v2(
                    _quality_metrics(), decision_date="2026-10-15", data_asof=asof)
                codes = {item.code for item in decision.risks}
                self.assertEqual("pre_earnings_window_risk" in codes, expected)

    def test_informational_only(self) -> None:
        fresh = build_company_quality_v2(
            _quality_metrics(), decision_date="2026-10-15", data_asof="2026-10-01")
        aged = build_company_quality_v2(
            _quality_metrics(), decision_date="2026-10-15", data_asof="2026-07-29")
        self.assertEqual(fresh.grade, aged.grade)
        self.assertEqual(fresh.score, aged.score)
        self.assertEqual(fresh.confidence, aged.confidence)
        item = next(i for i in aged.risks if i.code == "pre_earnings_window_risk")
        self.assertEqual(item.value, 78)
        self.assertIn("<70d", str(item.threshold))

    def test_v1_has_no_pre_earnings_code(self) -> None:
        decision = build_company_quality_v1(
            _quality_metrics(), decision_date="2026-10-15", data_asof="2026-07-29")
        self.assertNotIn(
            "pre_earnings_window_risk", {i.code for i in decision.risks})


class TestQualityV2SplitGuard(unittest.TestCase):
    def test_reverse_split_neutralized(self) -> None:
        decision = build_company_quality_v2(
            _quality_metrics(shares_yoy=-0.799),
            decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertEqual(decision.component_scores["dilution"], 0.50)
        codes = {i.code for i in decision.risks}
        self.assertIn("shares_yoy_split_or_basis_discontinuity", codes)
        positives = {i.code for i in decision.positives}
        self.assertNotIn("shares_yoy_strong", positives)
        item = next(i for i in decision.risks
                    if i.code == "shares_yoy_split_or_basis_discontinuity")
        self.assertIn("-79.9%", item.message)

    def test_forward_split_no_severe_count(self) -> None:
        # A >+100% split-driven jump must not trip the organic severe gate.
        calm = _quality_metrics(shares_yoy=1.50)
        decision = build_company_quality_v2(
            calm, decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertEqual(decision.component_scores["dilution"], 0.50)
        # ...while genuine organic dilution still scores weakly/severely.
        organic = build_company_quality_v2(
            _quality_metrics(shares_yoy=0.20),
            decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertNotIn(
            "shares_yoy_split_or_basis_discontinuity",
            {i.code for i in organic.risks})

    def test_boundaries_use_normal_path(self) -> None:
        for value in (-0.30, 1.00, 0.01, None):
            with self.subTest(value=value):
                decision = build_company_quality_v2(
                    _quality_metrics(shares_yoy=value),
                    decision_date="2026-10-15", data_asof="2026-10-01")
                self.assertNotIn(
                    "shares_yoy_split_or_basis_discontinuity",
                    {i.code for i in decision.risks})

    def test_v1_untouched_by_guard(self) -> None:
        decision = build_company_quality_v1(
            _quality_metrics(shares_yoy=-0.799),
            decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertNotIn(
            "shares_yoy_split_or_basis_discontinuity",
            {i.code for i in decision.risks})
        # v1 still scores the distorted print as strong dilution
        self.assertIn("shares_yoy_strong", {i.code for i in decision.positives})


class TestEntryV2Extension(unittest.TestCase):
    def test_mild_and_severe_deductions(self) -> None:
        base = build_entry_quality_v2(_entry_metrics(), decision_date="2026-10-15")
        mild = build_entry_quality_v2(
            _entry_metrics(price_to_sma200=1.40), decision_date="2026-10-15")
        self.assertAlmostEqual(
            base.score - mild.score, ENTRY_V2_EXTENSION_MILD_PENALTY, places=9)
        self.assertIn("price_extended_above_sma200",
                      {i.code for i in mild.risks})
        severe = build_entry_quality_v2(
            _entry_metrics(price_to_sma200=1.50), decision_date="2026-10-15")
        self.assertAlmostEqual(
            base.score - severe.score, ENTRY_V2_EXTENSION_SEVERE_PENALTY, places=9)

    def test_ret60_bands_and_state_invariance(self) -> None:
        base = build_entry_quality_v2(_entry_metrics(), decision_date="2026-10-15")
        mild = build_entry_quality_v2(
            _entry_metrics(return_60d=0.40), decision_date="2026-10-15")
        severe = build_entry_quality_v2(
            _entry_metrics(return_60d=0.50), decision_date="2026-10-15")
        self.assertAlmostEqual(
            base.score - mild.score, ENTRY_V2_EXTENSION_MILD_PENALTY, places=9)
        self.assertAlmostEqual(
            base.score - severe.score, ENTRY_V2_EXTENSION_SEVERE_PENALTY, places=9)
        self.assertIn("return_60d_extended", {i.code for i in severe.risks})
        for decision in (base, mild, severe):
            self.assertIs(decision.state, EntryState.ENTRY_READY)

    def test_combined_penalties_stack_with_floor(self) -> None:
        from ai_value_scanner.decision.entry import build_entry_quality_v1
        metrics = _entry_metrics(price_to_sma200=1.50, return_60d=0.50)
        v1_same = build_entry_quality_v1(metrics, decision_date="2026-10-15")
        stacked = build_entry_quality_v2(metrics, decision_date="2026-10-15")
        self.assertAlmostEqual(
            stacked.score,
            max(0.0, round(v1_same.score - 2 * ENTRY_V2_EXTENSION_SEVERE_PENALTY, 6)),
            places=9)
        self.assertGreaterEqual(stacked.score, 0.0)

    def test_threshold_texts(self) -> None:
        decision = build_entry_quality_v2(
            _entry_metrics(price_to_sma200=1.47, return_60d=0.514),
            decision_date="2026-10-15")
        by_code = {i.code: i for i in decision.risks}
        self.assertEqual(by_code["price_extended_above_sma200"].threshold,
                         "<=1.35x preferred")
        self.assertEqual(by_code["return_60d_extended"].threshold,
                         "<=35% preferred")

    def test_v1_untouched_by_extension(self) -> None:
        v1 = build_entry_quality_v1(
            _entry_metrics(price_to_sma200=1.47, return_60d=0.514),
            decision_date="2026-10-15")
        v1_base = build_entry_quality_v1(_entry_metrics(), decision_date="2026-10-15")
        self.assertEqual(v1.score, v1_base.score)
        codes = {i.code for i in v1.risks}
        self.assertNotIn("price_extended_above_sma200", codes)
        self.assertNotIn("return_60d_extended", codes)


class TestActionV2PreEarningsPenalty(unittest.TestCase):
    def _pair(self):
        pre = _decision(
            symbol="AAA", quality_risks=(
                _ev("pre_earnings_window_risk", metric="fundamental_data_age_days",
                    value=78, polarity="negative"),))
        fresh = _decision(symbol="BBB")
        return pre, fresh

    def test_constant(self) -> None:
        self.assertEqual(H3_PRE_EARNINGS_PRIORITY_PENALTY, 0.06)

    def test_fresh_ranks_ahead_on_tie(self) -> None:
        pre, fresh = self._pair()
        ranked = assign_action_priorities_v2([pre, fresh])
        self.assertEqual([d.symbol for d in ranked], ["BBB", "AAA"])

    def test_penalty_applies_in_all_branches(self) -> None:
        # HOLD_MONITOR branch
        pre = _decision(symbol="AAA", action=ActionState.HOLD_MONITOR,
                        quality_risks=(_ev("pre_earnings_window_risk", polarity="negative"),))
        fresh = _decision(symbol="BBB", action=ActionState.HOLD_MONITOR)
        ranked = assign_action_priorities_v2([pre, fresh])
        self.assertEqual([d.symbol for d in ranked], ["BBB", "AAA"])
        # AVOID branch (grade ordering still dominates within same grade)
        pre_avoid = _decision(symbol="AAA", grade=QualityGrade.C,
                              action=ActionState.AVOID,
                              quality_risks=(_ev("pre_earnings_window_risk",
                                                polarity="negative"),))
        fresh_avoid = _decision(symbol="BBB", grade=QualityGrade.C,
                                action=ActionState.AVOID)
        ranked_avoid = assign_action_priorities_v2([pre_avoid, fresh_avoid])
        self.assertEqual([d.symbol for d in ranked_avoid], ["BBB", "AAA"])

    def test_no_penalty_without_risk_item(self) -> None:
        first = _decision(symbol="AAA")
        second = _decision(symbol="BBB")
        ranked = assign_action_priorities_v2([second, first])
        self.assertEqual([d.symbol for d in ranked], ["AAA", "BBB"])


class TestViewModelNonBlockingWarns(unittest.TestCase):
    def _extended_ready(self):
        return _decision(
            symbol="EXT",
            entry_risks=(
                _ev("price_extended_above_sma200", metric="price_to_sma200",
                    value=1.47, polarity="negative"),
                _ev("return_60d_extended", metric="return_60d",
                    value=0.514, polarity="negative"),
            ),
            provenance={"watchlist_bucket": "ai_core", "watchlist_etfs": "XLK, IGV"},
        )

    def test_warn_codes_constant(self) -> None:
        self.assertEqual(_NON_BLOCKING_ENTRY_WARN_CODES,
                         frozenset({"price_extended_above_sma200", "return_60d_extended"}))

    def test_passing_gates_not_flipped(self) -> None:
        card = build_stock_card_view_model(self._extended_ready())
        by_gate = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_gate["sma200_trend"].status, "PASS")
        self.assertEqual(by_gate["ret60_trend"].status, "PASS")

    def test_blockers_inline_variants(self) -> None:
        extended = build_stock_card_view_model(self._extended_ready())
        self.assertEqual(
            extended.entry_blockers_inline,
            "All 7 readiness gates passed (⚠️ Extended: SMA200 1.47x · 60d Ret +51.4%)")
        clean = build_stock_card_view_model(_decision())
        self.assertEqual(clean.entry_blockers_inline, "All 7 readiness gates passed")

    def test_inline_fragments(self) -> None:
        from ai_value_scanner.decision.view_model import _inline_fragment
        self.assertEqual(
            _inline_fragment(_ev("pre_earnings_window_risk",
                                 metric="fundamental_data_age_days", value=78,
                                 polarity="negative")),
            "⚠️ Pre-Earnings (78d filing)")
        self.assertEqual(
            _inline_fragment(_ev("shares_yoy_split_or_basis_discontinuity",
                                 metric="shares_yoy", value=-0.799,
                                 polarity="negative")),
            "⚠️ Share Split/Basis (-79.9%)")

    def test_badges_and_pool(self) -> None:
        card = build_stock_card_view_model(self._extended_ready())
        # 78d? No: synthetic fixture has no age value; add pre-earnings item.
        aged = _decision(
            symbol="AGED",
            quality_risks=(_ev("pre_earnings_window_risk",
                               metric="fundamental_data_age_days", value=78,
                               polarity="negative"),),
            provenance={"watchlist_bucket": "ai_core", "watchlist_etfs": "XLK, IGV"},
        )
        aged_card = build_stock_card_view_model(aged)
        self.assertIn("⚠️Pre-Earnings(78d)", aged_card.warning_badges_inline)
        self.assertIn("⚠️Extended(SMA200 1.47x, 60d +51.4%)",
                      card.warning_badges_inline)
        self.assertEqual(card.pool_display, "`ai_core` (XLK, IGV)")
        bare = build_stock_card_view_model(_decision())
        self.assertEqual(bare.warning_badges_inline, "")
        self.assertEqual(bare.pool_display, "")

    def test_concentration_line(self) -> None:
        cards = [
            _decision(symbol=f"S{i:02d}",
                      provenance={"watchlist_bucket": "ai_core" if i < 11 else "ai_peripheral",
                                  "watchlist_etfs": "XLK, IGV" if i % 2 else "SMH"})
            for i in range(15)
        ]
        snapshot = build_snapshot_view_model(cards, cards * 34 + cards[:1])
        line = snapshot.concentration_summary_line
        self.assertIn("Pool (511 names)", line)
        self.assertIn("ai_core 11/15", line)
        self.assertIn("ai_peripheral 4/15", line)
        self.assertIn("Top ETFs:", line)
        self.assertTrue(line.endswith("— diversify across sectors manually"))
        bare = build_snapshot_view_model([_decision()])
        self.assertEqual(bare.concentration_summary_line, "")


class TestReportingV2Surfaces(unittest.TestCase):
    def test_summary_badges_pool_and_concentration(self) -> None:
        decision = _decision(
            symbol="MSFT",
            entry_risks=(
                _ev("price_extended_above_sma200", metric="price_to_sma200",
                    value=1.47, polarity="negative"),),
            quality_risks=(
                _ev("pre_earnings_window_risk", metric="fundamental_data_age_days",
                    value=78, polarity="negative"),),
            provenance={"watchlist_bucket": "ai_core", "watchlist_etfs": "XLK"},
        )
        md = render_action_list_v2([decision], title="T", cadence="daily",
                                   all_decisions=[decision])
        summary = next(line for line in md.splitlines() if line.startswith("<summary>"))
        self.assertIn("⚠️Pre-Earnings(78d)", summary)
        self.assertIn("⚠️Extended(SMA200 1.47x)", summary)
        company = next(line for line in md.splitlines() if line.startswith("- **Company"))
        self.assertIn("**Pool**: `ai_core` (XLK)", company)
        lines = md.splitlines()
        date_idx = next(i for i, line in enumerate(lines) if line.startswith("- **Date**"))
        self.assertIn("**Pool & Concentration**", lines[date_idx + 1])

    def test_no_provenance_no_new_lines(self) -> None:
        md = render_action_list_v2([_decision()], title="T", cadence="daily")
        self.assertNotIn("Pool & Concentration", md)
        summary = next(line for line in md.splitlines() if line.startswith("<summary>"))
        self.assertNotIn("⚠️", summary)
        company = next(line for line in md.splitlines() if line.startswith("- **Company"))
        self.assertNotIn("**Pool**", company)

    def test_v1_renderers_untouched(self) -> None:
        decision = _decision(
            entry_risks=(_ev("price_extended_above_sma200", metric="price_to_sma200",
                             value=1.47, polarity="negative"),))
        v1_list = render_action_list([decision], title="T", cadence="daily")
        v1_detail = render_detailed_report(decision)
        self.assertNotIn("warning_badges_inline", v1_list + v1_detail)
        self.assertIsInstance(v1_list, str)
        self.assertIsInstance(v1_detail, str)


class TestPrimaryBucketNormalization(unittest.TestCase):
    def test_priority_constant(self) -> None:
        self.assertEqual(_BUCKET_PRIORITY,
                         ("core_ai", "ai_core", "ai_enabler",
                          "ai_peripheral", "ai_smallcap"))

    def test_normalize_primary_bucket(self) -> None:
        cases = {
            "ai_enabler,core_ai": "core_ai",
            "core_ai,ai_enabler": "core_ai",
            "ai_core": "ai_core",
            " ai_peripheral , ai_smallcap ": "ai_peripheral",
            "unknown_bucket": "unknown_bucket",
            "zzz,aaa": "zzz",
            "": "",
            None: "",
            " , ,": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(_normalize_primary_bucket(raw), expected)

    def test_format_bucket_tokens(self) -> None:
        self.assertEqual(_format_bucket_tokens("ai_enabler,core_ai"),
                         "core_ai/ai_enabler")
        self.assertEqual(_format_bucket_tokens("ai_core"), "ai_core")
        self.assertEqual(
            _format_bucket_tokens("ai_smallcap,ai_smallcap, ai_core "),
            "ai_core/ai_smallcap")
        self.assertEqual(_format_bucket_tokens("zzz,ai_core"), "ai_core/zzz")
        self.assertEqual(_format_bucket_tokens(""), "")
        self.assertEqual(_format_bucket_tokens(None), "")

    def test_pool_display_multi_bucket(self) -> None:
        card = build_stock_card_view_model(
            _decision(provenance={"watchlist_bucket": "ai_enabler,core_ai",
                                  "watchlist_etfs": "SMH"}))
        self.assertEqual(card.pool_display, "`core_ai/ai_enabler` (SMH)")

    def test_concentration_aggregates_primary_buckets(self) -> None:
        cards = (
            [_decision(symbol=f"M{i:02d}",
                       provenance={"watchlist_bucket": "ai_enabler,core_ai",
                                   "watchlist_etfs": "SMH"})
             for i in range(7)]
            + [_decision(symbol=f"P{i:02d}",
                         provenance={"watchlist_bucket": "ai_peripheral",
                                     "watchlist_etfs": "XLK"})
               for i in range(3)]
            + [_decision(symbol=f"S{i:02d}",
                         provenance={"watchlist_bucket": "ai_smallcap",
                                     "watchlist_etfs": "SOXX"})
               for i in range(3)]
            + [_decision(symbol=f"E{i:02d}",
                         provenance={"watchlist_bucket": "ai_enabler",
                                     "watchlist_etfs": "IGV"})
               for i in range(2)]
        )
        snapshot = build_snapshot_view_model(cards, cards * 34 + cards[:1])
        line = snapshot.concentration_summary_line
        self.assertIn("core_ai 7/15", line)
        self.assertIn("ai_peripheral 3/15", line)
        self.assertIn("ai_smallcap 3/15", line)
        self.assertIn("ai_enabler 2/15", line)
        self.assertNotIn("ai_enabler,core_ai", line)


class TestCapOmittedSlice15(unittest.TestCase):
    def _universe(self, n_omitted: int):
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i,
                      grade=QualityGrade.A,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.PRIORITY_REVIEW)
            for i in range(1, 16)
        )
        omitted = tuple(
            _decision(symbol=f"O{i:02d}", priority=15 + i,
                      grade=QualityGrade.A,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.PRIORITY_REVIEW)
            for i in range(1, n_omitted + 1)
        )
        return primaries, omitted

    def test_cap_omitted_shows_up_to_15(self) -> None:
        primaries, omitted = self._universe(20)
        snapshot = build_snapshot_view_model(
            primaries, primaries + omitted, title="T", cadence="daily")
        self.assertEqual(len(snapshot.cap_omitted_priority_cards), 15)
        self.assertEqual(snapshot.cap_omitted_priority_cards[0].symbol, "O01")
        self.assertEqual(snapshot.cap_omitted_priority_cards[-1].symbol, "O15")

    def test_secondary_b_ready_still_capped_at_5(self) -> None:
        primaries, _ = self._universe(0)
        b_ready = tuple(
            _decision(symbol=f"B{i:02d}", priority=100 + i,
                      grade=QualityGrade.B,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.HOLD_MONITOR)
            for i in range(7)
        )
        snapshot = build_snapshot_view_model(
            primaries, primaries + b_ready, title="T", cadence="daily")
        self.assertEqual(len(snapshot.secondary_b_ready_cards), 5)


class TestSecondaryRadarBadgesAndEntry(unittest.TestCase):
    def _badged_radar_decision(self, symbol="MSFT"):
        return _decision(
            symbol=symbol,
            action=ActionState.HOLD_MONITOR,
            grade=QualityGrade.B,
            entry_risks=(
                _ev("price_extended_above_sma200", metric="price_to_sma200",
                    value=1.47, polarity="negative"),),
            quality_risks=(
                _ev("pre_earnings_window_risk",
                    metric="fundamental_data_age_days", value=78,
                    polarity="negative"),),
        )

    def _radar_lines(self, cards, all_cards):
        md = render_action_list_v2(cards, title="T", cadence="daily",
                                   all_decisions=cards + all_cards)
        start = md.index("## Secondary Radar")
        return md[start:].splitlines()

    def test_cap_omitted_bullet_has_badges_and_entry(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        omitted = (self._badged_radar_decision("MSFT"),)
        lines = self._radar_lines(primaries, omitted)
        bullet = next(
            line for line in lines if line.startswith("- **#") and "MSFT" in line)
        self.assertIn("⚠️Pre-Earnings(78d)", bullet)
        self.assertIn("⚠️Extended(SMA200 1.47x)", bullet)
        self.assertIn("[Full Report →](./detailed/MSFT.md)", bullet)
        entry_idx = next(
            i for i, line in enumerate(lines) if "MSFT" in line
            and line.startswith("- **#"))
        entry_line = next(
            line for line in lines[entry_idx:] if line.startswith("  - **Entry**:"))
        self.assertIn("SMA200", entry_line)

    def test_secondary_b_ready_bullet_has_badges_and_entry(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        secondary = (self._badged_radar_decision("AMD"),)
        md = render_action_list_v2(primaries, title="T", cadence="daily",
                                   all_decisions=primaries + secondary)
        section = md[md.index("Secondary Watch: Top Quality B"):]
        self.assertIn("⚠️Pre-Earnings(78d)", section)
        self.assertIn("  - **Entry**:", section)

    def test_no_badges_no_clutter(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        plain = (_decision(symbol="ZZZ", priority=16,
                           grade=QualityGrade.B,
                           entry_state=EntryState.ENTRY_READY,
                           action=ActionState.HOLD_MONITOR),)
        md = render_action_list_v2(primaries, title="T", cadence="daily",
                                   all_decisions=primaries + plain)
        bullet = next(
            line for line in md.splitlines()
            if line.startswith("- **#") and "ZZZ" in line)
        self.assertNotIn("⚠️", bullet)
        self.assertTrue(bullet.rstrip().endswith("[Full Report →](./detailed/ZZZ.md)"))


class TestSnapshotAllDecisionsWiring(unittest.TestCase):
    def test_v2_populates_pool_and_radar_detailed(self) -> None:
        import tempfile
        from pathlib import Path

        from ai_value_scanner.reporting.snapshot import write_decision_snapshot

        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i,
                      provenance={"watchlist_bucket": "ai_core",
                                  "watchlist_etfs": "XLK"})
            for i in range(1, 16))
        radar = _decision(
            symbol="MSFT", priority=22, grade=QualityGrade.B,
            entry_state=EntryState.ENTRY_READY,
            action=ActionState.HOLD_MONITOR,
            provenance={"watchlist_bucket": "ai_core", "watchlist_etfs": "XLK"})
        universe = primaries + (radar,)
        with tempfile.TemporaryDirectory() as tmp:
            write_decision_snapshot(
                output_root=tmp, strategy_style="risk_off",
                decisions=universe, daily_attention=primaries,
                weekly_attention=primaries, generated_at_utc="x",
                decision_date="2026-10-15", config_fingerprint="fp",
                layout_version="v2",
            )
            root = Path(tmp) / "2026-10-15" / "risk_off"
            action_md = (root / "action_list.md").read_text(encoding="utf-8")
            self.assertIn("- **Pool & Concentration**:", action_md)
            self.assertIn("Pool (16 names)", action_md)
            self.assertIn("MSFT", action_md)
            self.assertTrue((root / "detailed" / "MSFT.md").exists())

    def test_v1_ignores_all_decisions_byte_identical(self) -> None:
        import tempfile
        from pathlib import Path

        from ai_value_scanner.reporting.snapshot import write_decision_snapshot

        primaries = tuple(_decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 4))
        extra = (_decision(symbol="ZZZ", priority=99,
                           grade=QualityGrade.B,
                           entry_state=EntryState.ENTRY_READY,
                           action=ActionState.HOLD_MONITOR),)
        with tempfile.TemporaryDirectory() as tmp:
            write_decision_snapshot(
                output_root=f"{tmp}/a", strategy_style="risk_off",
                decisions=primaries + extra, daily_attention=primaries,
                weekly_attention=primaries, generated_at_utc="x",
                decision_date="2026-10-15", config_fingerprint="fp",
                layout_version="v1",
            )
            baseline = (Path(tmp) / "a" / "2026-10-15" / "risk_off"
                        / "action_list.md").read_text(encoding="utf-8")
            md_direct = render_action_list(
                primaries, title="Daily Action List", cadence="daily",
                layout_version="v1")
            self.assertEqual(baseline, md_direct)
            # detailed dir contains only daily/weekly symbols, no radar extras
            self.assertFalse((Path(tmp) / "a" / "2026-10-15" / "risk_off"
                              / "detailed" / "ZZZ.md").exists())


class TestRecomputeV2Preview(unittest.TestCase):
    def _snapshot_dir(self, tmp, decisions, daily_symbols, weekly_symbols):
        import json
        from pathlib import Path

        from ai_value_scanner.decision.model import stock_decisions_to_jsonl

        root = Path(tmp) / "snap"
        root.mkdir(parents=True, exist_ok=True)
        before = {}
        decisions_text = stock_decisions_to_jsonl(decisions)
        (root / "decisions.jsonl").write_text(decisions_text, encoding="utf-8")
        manifest_text = json.dumps(
            {"daily_symbols": daily_symbols, "weekly_symbols": weekly_symbols},
            sort_keys=True)
        (root / "run_manifest.json").write_text(manifest_text, encoding="utf-8")
        for name in ("decisions.jsonl", "run_manifest.json"):
            data = (root / name).read_bytes()
            import hashlib
            before[name] = hashlib.sha256(data).hexdigest()
        return root, before

    def _adjustable_decision(self):
        # v1-shaped decision whose evidence triggers every v2 adjustment
        quality = QualityDecision(
            grade=QualityGrade.A, score=0.85, confidence=0.95,
            component_scores={"profitability_cash": 0.9, "dilution": 1.0},
            positives=(_ev("net_margin_strong", metric="net_margin", value=0.2),),
            risks=(_ev("shares_yoy_strong", metric="shares_yoy", value=-0.799),),
            missing=(), data_asof="2026-07-29",
        )
        entry = EntryDecision(
            state=EntryState.ENTRY_READY, score=0.95, confidence=1.0,
            positives=(
                _ev("price_above_sma200", metric="price_to_sma200", value=1.47),
                _ev("return_60d_nonnegative", metric="return_60d", value=0.514),
            ),
            risks=(), market_asof="2026-10-15",
        )
        return StockDecision(
            schema_version="1", symbol="ADJ", company_name="ADJ",
            decision_date="2026-10-15", generated_at_utc="x",
            quality=quality, entry=entry,
            action_state=ActionState.PRIORITY_REVIEW, priority=3,
            rationale=(), review_trigger="r", source_lists=(),
            provenance={}, previous_action_state=None,
            state_change_reason=None,
        )

    def test_recompute_applies_all_adjustments(self) -> None:
        import sys
        sys.path.insert(0, "scripts")
        try:
            from render_snapshot_preview import recompute_v2_decisions
        finally:
            sys.path.pop(0)
        (recomputed,) = recompute_v2_decisions([self._adjustable_decision()])
        quality_codes = {i.code for i in recomputed.quality.risks}
        self.assertIn("shares_yoy_split_or_basis_discontinuity", quality_codes)
        self.assertIn("pre_earnings_window_risk", quality_codes)
        self.assertEqual(recomputed.quality.component_scores["dilution"], 0.50)
        entry_codes = {i.code for i in recomputed.entry.risks}
        self.assertIn("price_extended_above_sma200", entry_codes)
        self.assertIn("return_60d_extended", entry_codes)
        self.assertLess(recomputed.entry.score, 0.95)
        # idempotent: second run changes nothing
        (twice,) = recompute_v2_decisions([recomputed])
        self.assertEqual(twice.quality.risks, recomputed.quality.risks)
        self.assertEqual(twice.entry.risks, recomputed.entry.risks)
        self.assertEqual(twice.entry.score, recomputed.entry.score)
        self.assertEqual(twice.priority, recomputed.priority)

    def test_recompute_cli_is_read_only_and_writes_preview(self) -> None:
        import hashlib
        import json
        import sys
        import tempfile
        from pathlib import Path

        sys.path.insert(0, "scripts")
        try:
            import render_snapshot_preview
        finally:
            sys.path.pop(0)
        decisions = [self._adjustable_decision(),
                     _decision(symbol="MSFT", priority=1)]
        with tempfile.TemporaryDirectory() as tmp:
            snap_dir, before = self._snapshot_dir(
                tmp, decisions, ["ADJ", "MSFT"], ["ADJ", "MSFT"])
            out_dir = Path(tmp) / "out"
            argv = ["render_snapshot_preview.py",
                    "--snapshot-dir", str(snap_dir),
                    "--output-dir", str(out_dir),
                    "--recompute-v2"]
            import unittest.mock as mock
            with mock.patch.object(sys, "argv", argv):
                render_snapshot_preview.main()
            for name, digest in before.items():
                self.assertEqual(
                    hashlib.sha256((snap_dir / name).read_bytes()).hexdigest(),
                    digest)
            self.assertTrue((out_dir / "action_list_v2.md").exists())
            self.assertTrue((out_dir / "weekly_review_v2.md").exists())
            self.assertTrue((out_dir / "decisions_recomputed_v2.jsonl").exists())
            self.assertGreater(len(list((out_dir / "detailed_v2").glob("*.md"))), 0)
            action_md = (out_dir / "action_list_v2.md").read_text(encoding="utf-8")
            self.assertIn("⚠️", action_md)
            for path in list(out_dir.rglob("*.md")) + list(out_dir.rglob("*.jsonl")):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/tmp/", text)
                self.assertNotIn("/home/", text)


if __name__ == "__main__":
    unittest.main()
