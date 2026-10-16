"""Three-layer non-operating investment gain & tax distortion defense tests.

Covers Layer 1/2 detection in ``build_company_quality_v2`` (GOOG / ZM / NTNX /
AMZN / WDC / SHOP / MSFT / BILL archetypes), the H3 priority penalty, view-model
labels and warning badges, the ``--recompute-v2`` overlay, the Layer 3 disposal
tag, and v1 invariance. Synthetic fixtures only; no network calls.
"""

from __future__ import annotations

import unittest

from ai_value_scanner.decision.action import (
    H3_NONOPERATING_GAIN_PRIORITY_PENALTY,
    H3_PRE_EARNINGS_PRIORITY_PENALTY,
    assign_action_priorities_v2,
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
    QUALITY_V2_HEALTHY_OCF_MIN,
    QUALITY_V2_HIGH_MARGIN_CONVERSION_WARN_MARGIN,
    QUALITY_V2_NONOP_MARGIN_GAP_MIN,
    QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI,
    QUALITY_V2_NONOP_NET_MARGIN_FLOOR,
    QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR,
    QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN,
    QUALITY_V2_NONOP_YOY_GAP_MIN,
    build_company_quality_v1,
    build_company_quality_v2,
)
from ai_value_scanner.decision.view_model import (
    _compact_label,
    _inline_fragment,
    build_snapshot_view_model,
    build_stock_card_view_model,
)
from ai_value_scanner.reporting.decision import render_action_list_v2
from ai_value_scanner.scanner import (
    INTEREST_INCOME_TAGS,
    NONOPERATING_INCOME_TAGS,
    NONRECURRING_GAIN_TAGS,
    PARSED_FUND_CACHE_VERSION,
    ScanConfig,
    extract_latest_quarterly_nonop_metrics,
    load_one_fundamental,
)


def _metrics(**overrides):
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


# Archetype metric dictionaries built from the 2026-10-16 audit tables.
# `revenue=1000` makes ebit numeric values equal operating-margin percentages.
_ARCHETYPES: dict[str, dict] = {
    # $99B Anthropic equity gain; OCF/NI 0.748 silent in the (0.5, 0.8) band.
    "GOOG": dict(
        net_margin=0.55653, revenue=1000.0, ebit=339.925,
        free_cash_flow=119.482, ocf_to_net_income=0.748,
        adjusted_net_income_yoy=1.147024, ebit_yoy=0.249,
    ),
    # $1.77B strategic investment gain; OCF/NI 0.614 silent band.
    "ZM": dict(
        net_margin=0.652, revenue=1000.0, ebit=237.0,
        free_cash_flow=150.0, ocf_to_net_income=0.614,
        adjusted_net_income_yoy=1.740, ebit_yoy=0.220,
    ),
    # $1.18B deferred-tax valuation allowance release; OCF/NI 0.608 silent band.
    "NTNX": dict(
        net_margin=0.528, revenue=1000.0, ebit=96.0,
        free_cash_flow=295.0, ocf_to_net_income=0.608,
        adjusted_net_income_yoy=7.0, ebit_yoy=0.588,
    ),
    # $53.4B Anthropic preferred upward adjustment; OCF/NI 1.182 (cash-backed
    # enough to skip the Layer 2 conversion warning, not the Layer 1 gap).
    "AMZN": dict(
        net_margin=0.176, revenue=1000.0, ebit=122.0,
        free_cash_flow=200.0, ocf_to_net_income=1.182,
        adjusted_net_income_yoy=0.933, ebit_yoy=0.246,
    ),
    # $2.73B SanDisk retained-interest remeasurement; OCF/NI 0.410 already weak
    # (must not duplicate the Layer 2 warning).
    "WDC": dict(
        net_margin=0.741, revenue=1000.0, ebit=357.0,
        free_cash_flow=250.0, ocf_to_net_income=0.410,
        adjusted_net_income_yoy=4.329, ebit_yoy=1.054,
    ),
    # Prior-year equity-gain base effect: margin gap is clean, but NI YoY
    # (-15.4%) diverges from clean EBIT YoY (+51.3%) and must be substituted.
    "SHOP": dict(
        net_margin=0.151, revenue=1000.0, ebit=145.0,
        free_cash_flow=80.0, ocf_to_net_income=1.183,
        adjusted_net_income_yoy=-0.154, ebit_yoy=0.513,
    ),
    # Small Anthropic gain ($3.2B vs $35B+ NI): metric gaps stay clean.
    "MSFT": dict(
        net_margin=0.35, revenue=1000.0, ebit=340.0,
        free_cash_flow=300.0, ocf_to_net_income=1.3506,
        adjusted_net_income_yoy=0.20, ebit_yoy=0.18,
    ),
    # Cash-backed high-margin control: big margin gap but OCF/NI >= 1.50, so
    # the gain is demonstrably converted to cash and must not be flagged.
    "BILL": dict(
        net_margin=0.30, revenue=1000.0, ebit=100.0,
        free_cash_flow=220.0, ocf_to_net_income=1.80,
        adjusted_net_income_yoy=0.25, ebit_yoy=0.22,
    ),
}


def _build(symbol: str):
    return build_company_quality_v2(
        _metrics(**_ARCHETYPES[symbol]),
        decision_date="2026-10-15",
        data_asof="2026-10-01",
    )


def _codes(decision) -> set[str]:
    return {item.code for item in decision.risks}


def _evidence_value(decision, metric: str, side: str = "positives"):
    items = getattr(decision, side)
    for item in items:
        if item.metric == metric:
            return item.value
    return None


def _ev(code, *, polarity="positive", metric="x", value=1.0, threshold="t",
        message=None):
    return EvidenceItem(
        code=code,
        label=f"label {code}",
        polarity=polarity,  # type: ignore[arg-type]
        metric=metric,
        value=value,  # type: ignore[arg-type]
        threshold=threshold,  # type: ignore[arg-type]
        message=message if message is not None else f"message {code}",
    )


def _decision(
    *,
    symbol="EXM",
    grade=QualityGrade.A,
    entry_state=EntryState.ENTRY_READY,
    action=ActionState.PRIORITY_REVIEW,
    priority=1,
    quality_risks=(),
    quality_positives=None,
    entry_score=0.9,
    quality_score=0.8,
):
    entry = EntryDecision(
        state=entry_state, score=entry_score, confidence=1.0,
        positives=(_ev("price_above_sma200", metric="price_to_sma200", value=1.05),),
        risks=(), market_asof="2026-10-12",
    )
    quality = QualityDecision(
        grade=grade, score=quality_score, confidence=0.9,
        component_scores={"profitability_cash": 0.8},
        positives=tuple(
            quality_positives
            if quality_positives is not None
            else (_ev("net_margin_strong", metric="net_margin", value=0.2),)
        ),
        risks=tuple(quality_risks), missing=(),
        data_asof="2026-10-01",
    )
    return StockDecision(
        schema_version="1", symbol=symbol, company_name=symbol,
        decision_date="2026-10-15", generated_at_utc="x",
        quality=quality, entry=entry, action_state=action, priority=priority,
        rationale=(), review_trigger="r", source_lists=(),
        provenance={}, previous_action_state=None, state_change_reason=None,
    )


class TestLayer3DisposalTag(unittest.TestCase):
    def test_disposal_variant_tag_registered(self) -> None:
        self.assertIn(
            "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
            NONRECURRING_GAIN_TAGS,
        )

    def test_below_the_line_gain_tags_not_stripped_from_ebit(self) -> None:
        # Critical accounting trap: these tags live BELOW OperatingIncomeLoss,
        # so adding them would falsely subtract investment gains from clean
        # EBIT. They must never enter NONRECURRING_GAIN_TAGS.
        for tag in (
            "EquitySecuritiesFvNiGainLoss",
            "EquitySecuritiesFvNiUnrealizedGainLoss",
            "UnrealizedGainLossOnInvestments",
            "GainLossOnSaleOfInvestments",
            "MarketableSecuritiesUnrealizedGainLoss",
            "EquitySecuritiesWithoutReadilyDeterminableFairValueUpwardPriceAdjustmentAnnualAmount",
        ):
            with self.subTest(tag=tag):
                self.assertNotIn(tag, NONRECURRING_GAIN_TAGS)

    def test_parsed_fund_cache_version_not_bumped(self) -> None:
        self.assertEqual(PARSED_FUND_CACHE_VERSION, 9)


class TestNonOpConstants(unittest.TestCase):
    def test_spec_thresholds(self) -> None:
        self.assertEqual(QUALITY_V2_NONOP_MARGIN_GAP_MIN, 0.05)
        self.assertEqual(QUALITY_V2_NONOP_NET_MARGIN_FLOOR, 0.12)
        self.assertEqual(QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI, 1.50)
        self.assertEqual(QUALITY_V2_NONOP_YOY_GAP_MIN, 0.40)
        self.assertEqual(QUALITY_V2_HIGH_MARGIN_CONVERSION_WARN_MARGIN, 0.20)
        self.assertEqual(QUALITY_V2_HEALTHY_OCF_MIN, 0.80)


class TestQualityV2Archetypes(unittest.TestCase):
    EXPECTED = {
        # symbol: (nonop risk, ocf-lag risk, expected gap, capped net margin)
        "GOOG": (True, True, 0.216605, 0.339925),
        "ZM": (True, True, 0.415, 0.237),
        "NTNX": (True, True, 0.432, 0.096),
        "AMZN": (True, False, 0.054, 0.122),
        "WDC": (True, False, 0.384, 0.357),
        "SHOP": (False, False, None, 0.151),
        "MSFT": (False, False, None, 0.35),
        "BILL": (False, False, None, 0.30),
    }

    def test_trigger_matrix(self) -> None:
        for symbol, (nonop, ocf_lag, _, _) in self.EXPECTED.items():
            with self.subTest(symbol=symbol):
                codes = _codes(_build(symbol))
                self.assertEqual(
                    "nonoperating_gain_inflation" in codes, nonop)
                self.assertEqual(
                    "ocf_conversion_lagging_high_margin" in codes, ocf_lag)

    def test_gap_values(self) -> None:
        for symbol, (nonop, _, gap, _) in self.EXPECTED.items():
            if not nonop:
                continue
            with self.subTest(symbol=symbol):
                decision = _build(symbol)
                item = next(
                    i for i in decision.risks
                    if i.code == "nonoperating_gain_inflation")
                self.assertEqual(item.metric, "net_margin")
                self.assertAlmostEqual(item.value, gap, places=6)
                self.assertIn("net_margin - operating_margin", str(item.threshold))
                self.assertIn("Non-operating gain", item.label)

    def test_net_margin_capped_to_operating_basis(self) -> None:
        for symbol, (_, _, _, capped) in self.EXPECTED.items():
            if symbol == "NTNX":
                continue
            with self.subTest(symbol=symbol):
                decision = _build(symbol)
                self.assertAlmostEqual(
                    _evidence_value(decision, "net_margin"), capped, places=6)
        # NTNX caps to 0.096 (neutral 0.25 < score < 0.80 band): the inflated
        # 0.528 strong item must disappear entirely rather than be re-labeled.
        ntnx = _build("NTNX")
        self.assertNotIn("net_margin_strong", {i.code for i in ntnx.positives})
        self.assertNotIn("net_margin_weak", {i.code for i in ntnx.risks})
        v1 = build_company_quality_v1(
            _metrics(**_ARCHETYPES["NTNX"]),
            decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertIn("net_margin_strong", {i.code for i in v1.positives})

    def test_earnings_growth_depolluted_to_clean_ebit_yoy(self) -> None:
        substituted = {
            "GOOG": 0.249, "ZM": 0.220, "NTNX": 0.588,
            "AMZN": 0.246, "WDC": 1.054, "SHOP": 0.513,
        }
        for symbol, expected in substituted.items():
            with self.subTest(symbol=symbol):
                decision = _build(symbol)
                self.assertAlmostEqual(
                    _evidence_value(decision, "adjusted_net_income_yoy"),
                    expected, places=6)
        # Controls keep the reported net-income growth untouched.
        self.assertAlmostEqual(
            _evidence_value(_build("MSFT"), "adjusted_net_income_yoy"),
            0.20, places=6)
        self.assertAlmostEqual(
            _evidence_value(_build("BILL"), "adjusted_net_income_yoy"),
            0.25, places=6)

    def test_wdc_weak_conversion_not_duplicated(self) -> None:
        codes = _codes(_build("WDC"))
        self.assertIn("ocf_to_net_income_weak", codes)
        self.assertNotIn("ocf_conversion_lagging_high_margin", codes)

    def test_amzn_cash_backed_skips_layer2(self) -> None:
        codes = _codes(_build("AMZN"))
        self.assertIn("nonoperating_gain_inflation", codes)
        self.assertNotIn("ocf_conversion_lagging_high_margin", codes)

    def test_shop_has_no_nonop_risk(self) -> None:
        decision = _build("SHOP")
        self.assertNotIn("nonoperating_gain_inflation", _codes(decision))
        self.assertNotIn("ocf_conversion_lagging_high_margin", _codes(decision))

    def test_bill_cash_backed_exemption(self) -> None:
        decision = _build("BILL")
        self.assertEqual(_codes(decision), set())
        self.assertAlmostEqual(
            _evidence_value(decision, "net_margin"), 0.30, places=6)

    def test_operating_margin_pillar_still_clean(self) -> None:
        decision = _build("GOOG")
        self.assertAlmostEqual(
            _evidence_value(decision, "operating_margin"), 0.339925, places=6)


class TestQualityV2Boundaries(unittest.TestCase):
    def _build(self, **overrides):
        return build_company_quality_v2(
            _metrics(**overrides),
            decision_date="2026-10-15", data_asof="2026-10-01",
        )

    def test_margin_gap_floor(self) -> None:
        # 0.55 - 0.50 == 0.05000000000000004: first representable case >= 0.05.
        at_floor = self._build(net_margin=0.55, ebit=500.0,
                               ocf_to_net_income=0.70)
        below = self._build(net_margin=0.50, ebit=451.0,
                            ocf_to_net_income=0.70)
        self.assertIn("nonoperating_gain_inflation", _codes(at_floor))
        self.assertNotIn("nonoperating_gain_inflation", _codes(below))

    def test_net_margin_floor(self) -> None:
        at_floor = self._build(net_margin=0.12, ebit=50.0,
                               ocf_to_net_income=0.70)
        below = self._build(net_margin=0.119, ebit=50.0,
                            ocf_to_net_income=0.70)
        self.assertIn("nonoperating_gain_inflation", _codes(at_floor))
        self.assertNotIn("nonoperating_gain_inflation", _codes(below))

    def test_cash_backed_ocf_exemption_boundary(self) -> None:
        exactly_max = self._build(net_margin=0.55, ebit=300.0,
                                  ocf_to_net_income=1.50)
        just_below = self._build(net_margin=0.55, ebit=300.0,
                                 ocf_to_net_income=1.499)
        self.assertNotIn("nonoperating_gain_inflation", _codes(exactly_max))
        self.assertIn("nonoperating_gain_inflation", _codes(just_below))

    def test_layer2_net_margin_and_ocf_boundaries(self) -> None:
        # Margin gap kept below 0.05 so only Layer 2 can fire.
        at_margin = self._build(net_margin=0.20, ebit=190.0,
                                ocf_to_net_income=0.75)
        below_margin = self._build(net_margin=0.19, ebit=180.0,
                                   ocf_to_net_income=0.75)
        at_ocf = self._build(net_margin=0.25, ebit=240.0,
                             ocf_to_net_income=0.80)
        self.assertIn("ocf_conversion_lagging_high_margin", _codes(at_margin))
        self.assertNotIn(
            "ocf_conversion_lagging_high_margin", _codes(below_margin))
        self.assertNotIn("ocf_conversion_lagging_high_margin", _codes(at_ocf))

    def test_nonop_inflated_forces_substitution_below_yoy_gap(self) -> None:
        decision = self._build(
            net_margin=0.30, ebit=200.0, ocf_to_net_income=0.65,
            adjusted_net_income_yoy=0.10, ebit_yoy=0.18,
        )
        self.assertIn("nonoperating_gain_inflation", _codes(decision))
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 0.18,
            places=6)

    def test_yoy_gap_substitution_without_margin_inflation(self) -> None:
        decision = self._build(
            net_margin=0.15, ebit=140.0, ocf_to_net_income=1.2,
            adjusted_net_income_yoy=-0.20, ebit_yoy=0.45,
        )
        self.assertNotIn("nonoperating_gain_inflation", _codes(decision))
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 0.45,
            places=6)

    def test_no_substitution_without_ebit_yoy(self) -> None:
        decision = self._build(
            net_margin=0.30, ebit=200.0, ocf_to_net_income=0.65,
            adjusted_net_income_yoy=1.0,
        )
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 1.0,
            places=6)

    def test_no_substitution_without_net_income_yoy(self) -> None:
        metrics = _metrics(net_margin=0.30, ebit=200.0, ocf_to_net_income=0.65)
        metrics.pop("adjusted_net_income_yoy")
        decision = build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertIn("nonoperating_gain_inflation", _codes(decision))
        self.assertNotIn(
            "adjusted_net_income_yoy_strong",
            {i.code for i in decision.positives})

    def test_case_b_fallback_without_operating_margin(self) -> None:
        metrics = _metrics(
            net_margin=0.50, free_cash_flow=250.0, ocf_to_net_income=0.60,
            adjusted_net_income_yoy=0.50, ebit_yoy=0.20,
        )
        metrics.pop("ebit")
        decision = build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")
        codes = _codes(decision)
        self.assertIn("nonoperating_gain_inflation", codes)
        self.assertIn("ocf_conversion_lagging_high_margin", codes)
        item = next(
            i for i in decision.risks
            if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(item.value, 0.25, places=6)
        self.assertIn("FCF margin", item.message)
        self.assertAlmostEqual(
            _evidence_value(decision, "net_margin"), 0.25, places=6)
        self.assertIsNone(_evidence_value(decision, "operating_margin"))
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 0.20,
            places=6)

    def test_case_b_requires_fcf_margin_gap(self) -> None:
        metrics = _metrics(
            net_margin=0.30, free_cash_flow=250.0, ocf_to_net_income=0.60)
        metrics.pop("ebit")
        decision = build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")
        # net margin 0.30, fcf margin 0.25 -> gap 0.05 < 0.15: no trigger.
        self.assertNotIn("nonoperating_gain_inflation", _codes(decision))

    def test_case_b_requires_weak_ocf(self) -> None:
        metrics = _metrics(
            net_margin=0.50, free_cash_flow=250.0, ocf_to_net_income=0.90)
        metrics.pop("ebit")
        decision = build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertNotIn("nonoperating_gain_inflation", _codes(decision))


class TestQualityV1Invariance(unittest.TestCase):
    def test_v1_goog_untouched(self) -> None:
        decision = build_company_quality_v1(
            _metrics(**_ARCHETYPES["GOOG"]),
            decision_date="2026-10-15", data_asof="2026-10-01",
        )
        codes = _codes(decision)
        self.assertNotIn("nonoperating_gain_inflation", codes)
        self.assertNotIn("ocf_conversion_lagging_high_margin", codes)
        self.assertAlmostEqual(
            _evidence_value(decision, "net_margin"), 0.55653, places=6)
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 1.147024,
            places=6)

    def test_v1_has_no_operating_basis_cap(self) -> None:
        v1 = build_company_quality_v1(
            _metrics(**_ARCHETYPES["ZM"]),
            decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertAlmostEqual(
            _evidence_value(v1, "net_margin"), 0.652, places=6)
        v2 = _build("ZM")
        self.assertAlmostEqual(
            _evidence_value(v2, "net_margin"), 0.237, places=6)


class TestNonOpActionPenalty(unittest.TestCase):
    def _flagged(self, symbol="AAA", risks=("nonoperating_gain_inflation",)):
        return _decision(
            symbol=symbol,
            quality_risks=tuple(
                _ev(code, polarity="negative", metric="net_margin", value=0.2)
                for code in risks
            ),
        )

    def test_constant(self) -> None:
        self.assertEqual(H3_NONOPERATING_GAIN_PRIORITY_PENALTY, 0.06)

    def test_flagged_ranks_behind_clean_on_tie(self) -> None:
        flagged = self._flagged("AAA")
        clean = _decision(symbol="BBB")
        ranked = assign_action_priorities_v2([flagged, clean])
        self.assertEqual([d.symbol for d in ranked], ["BBB", "AAA"])

    def test_penalty_stacks_with_pre_earnings(self) -> None:
        both = self._flagged(
            "AAA", risks=("nonoperating_gain_inflation",
                          "pre_earnings_window_risk"))
        only_pre = self._flagged("BBB", risks=("pre_earnings_window_risk",))
        clean = _decision(symbol="CCC")
        ranked = assign_action_priorities_v2([both, only_pre, clean])
        self.assertEqual([d.symbol for d in ranked], ["CCC", "BBB", "AAA"])
        self.assertEqual(
            H3_PRE_EARNINGS_PRIORITY_PENALTY
            + H3_NONOPERATING_GAIN_PRIORITY_PENALTY,
            0.12,
        )

    def test_penalty_applies_in_hold_monitor_branch(self) -> None:
        flagged = _decision(
            symbol="AAA", action=ActionState.HOLD_MONITOR,
            quality_risks=(_ev("nonoperating_gain_inflation",
                               polarity="negative", metric="net_margin",
                               value=0.2),))
        clean = _decision(symbol="BBB", action=ActionState.HOLD_MONITOR)
        ranked = assign_action_priorities_v2([flagged, clean])
        self.assertEqual([d.symbol for d in ranked], ["BBB", "AAA"])

    def test_penalty_applies_in_avoid_branch(self) -> None:
        flagged = _decision(
            symbol="AAA", grade=QualityGrade.C, action=ActionState.AVOID,
            quality_risks=(_ev("nonoperating_gain_inflation",
                               polarity="negative", metric="net_margin",
                               value=0.2),))
        clean = _decision(
            symbol="BBB", grade=QualityGrade.C, action=ActionState.AVOID)
        ranked = assign_action_priorities_v2([flagged, clean])
        self.assertEqual([d.symbol for d in ranked], ["BBB", "AAA"])

    def test_no_penalty_without_risk_item(self) -> None:
        first = _decision(symbol="AAA")
        second = _decision(symbol="BBB")
        ranked = assign_action_priorities_v2([second, first])
        self.assertEqual([d.symbol for d in ranked], ["AAA", "BBB"])


class TestNonOpViewModel(unittest.TestCase):
    def test_compact_labels(self) -> None:
        self.assertEqual(
            _compact_label(_ev("nonoperating_gain_inflation",
                               polarity="negative", metric="net_margin",
                               value=0.216605)),
            "Non-Op Gain Margin Gap",
        )
        self.assertEqual(
            _compact_label(_ev("ocf_conversion_lagging_high_margin",
                               polarity="negative",
                               metric="ocf_to_net_income", value=0.61)),
            "OCF/NI (Low vs Margin)",
        )

    def test_inline_fragments(self) -> None:
        self.assertEqual(
            _inline_fragment(_ev("nonoperating_gain_inflation",
                                 polarity="negative", metric="net_margin",
                                 value=0.216605)),
            "⚠️ Non-Op Gain (+21.7pp vs OpMargin)",
        )
        self.assertEqual(
            _inline_fragment(_ev("nonoperating_gain_inflation",
                                 polarity="negative", metric="net_margin",
                                 value=None)),
            "⚠️ Non-Op Gain",
        )
        self.assertEqual(
            _inline_fragment(_ev("ocf_conversion_lagging_high_margin",
                                 polarity="negative",
                                 metric="ocf_to_net_income", value=0.608)),
            "OCF/NI 0.61x (lagging margin)",
        )

    def test_warning_badge(self) -> None:
        decision = _decision(
            quality_risks=(_ev("nonoperating_gain_inflation",
                               polarity="negative", metric="net_margin",
                               value=0.216605),))
        card = build_stock_card_view_model(decision)
        self.assertEqual(card.warning_badges_inline,
                         "⚠️NonOp-Gain(+21.7pp)")

    def test_warning_badge_without_value(self) -> None:
        decision = _decision(
            quality_risks=(_ev("nonoperating_gain_inflation",
                               polarity="negative", metric="net_margin",
                               value=None),))
        card = build_stock_card_view_model(decision)
        self.assertEqual(card.warning_badges_inline, "⚠️NonOp-Gain")

    def test_badge_order_pre_earnings_then_nonop(self) -> None:
        decision = _decision(
            quality_risks=(
                _ev("pre_earnings_window_risk", polarity="negative",
                    metric="fundamental_data_age_days", value=78),
                _ev("nonoperating_gain_inflation", polarity="negative",
                    metric="net_margin", value=0.216605),
            ))
        card = build_stock_card_view_model(decision)
        self.assertEqual(
            card.warning_badges_inline,
            "⚠️Pre-Earnings(78d) · ⚠️NonOp-Gain(+21.7pp)",
        )

    def test_no_badge_for_clean_decision(self) -> None:
        card = build_stock_card_view_model(_decision())
        self.assertEqual(card.warning_badges_inline, "")


def _frozen_decision(symbol, positives, *, risks=(), grade=QualityGrade.A):
    quality = QualityDecision(
        grade=grade, score=0.85, confidence=0.95,
        component_scores={"profitability_cash": 0.9},
        positives=tuple(positives), risks=tuple(risks), missing=(),
        data_asof="2026-10-01",
    )
    entry = EntryDecision(
        state=EntryState.ENTRY_READY, score=0.9, confidence=1.0,
        positives=(_ev("price_above_sma200", metric="price_to_sma200",
                       value=1.05),),
        risks=(), market_asof="2026-10-15",
    )
    return StockDecision(
        schema_version="1", symbol=symbol, company_name=symbol,
        decision_date="2026-10-15", generated_at_utc="x",
        quality=quality, entry=entry, action_state=ActionState.PRIORITY_REVIEW,
        priority=1, rationale=(), review_trigger="r", source_lists=(),
        provenance={}, previous_action_state=None, state_change_reason=None,
    )


class TestRecomputeV2NonOpOverlay(unittest.TestCase):
    def _recompute(self, decisions, cache_dir=None):
        import sys
        import tempfile
        from pathlib import Path

        sys.path.insert(0, "scripts")
        try:
            from render_snapshot_preview import recompute_v2_decisions
        finally:
            sys.path.pop(0)
        if cache_dir is not None:
            return recompute_v2_decisions(decisions, cache_dir=cache_dir)
        # Isolated empty cache: never read the developer's real cache/ dir.
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty-cache"
            empty.mkdir()
            return recompute_v2_decisions(decisions, cache_dir=empty)

    def test_goog_style_overlay_trigger_and_idempotence(self) -> None:
        goog = _frozen_decision("GOOG", (
            _ev("net_margin_strong", metric="net_margin", value=0.55653),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.339925),
            _ev("fcf_margin_strong", metric="fcf_margin", value=0.119482),
        ))
        (out,) = self._recompute([goog])
        codes = {i.code for i in out.quality.risks}
        self.assertIn("nonoperating_gain_inflation", codes)
        # Frozen JSONL has no OCF/NI evidence (silent band), so the explicit
        # conversion overlay cannot fire; the gap risk still lands.
        self.assertNotIn("ocf_conversion_lagging_high_margin", codes)
        item = next(
            i for i in out.quality.risks
            if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(item.value, 0.216605, places=6)
        (twice,) = self._recompute([out])
        self.assertEqual(twice.quality.risks, out.quality.risks)

    def test_ntnx_style_fallback_without_operating_margin(self) -> None:
        ntnx = _frozen_decision("NTNX", (
            _ev("net_margin_strong", metric="net_margin", value=0.528),
            _ev("fcf_margin_strong", metric="fcf_margin", value=0.295),
            _ev("adjusted_net_income_yoy_strong",
                metric="adjusted_net_income_yoy", value=7.0),
        ))
        (out,) = self._recompute([ntnx])
        item = next(
            i for i in out.quality.risks
            if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(item.value, 0.233, places=6)
        self.assertIn("FCF margin", item.message)
        (twice,) = self._recompute([out])
        self.assertEqual(twice.quality.risks, out.quality.risks)

    def test_conversion_overlay_with_weak_ocf_evidence(self) -> None:
        lag = _frozen_decision("LAG", (
            _ev("net_margin_strong", metric="net_margin", value=0.30),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.10),
            _ev("ocf_to_net_income_weak", polarity="negative",
                metric="ocf_to_net_income", value=0.45),
        ))
        (out,) = self._recompute([lag])
        codes = {i.code for i in out.quality.risks}
        self.assertIn("nonoperating_gain_inflation", codes)
        self.assertIn("ocf_conversion_lagging_high_margin", codes)
        (twice,) = self._recompute([out])
        self.assertEqual(twice.quality.risks, out.quality.risks)

    def test_msft_style_control_unchanged(self) -> None:
        msft = _frozen_decision("MSFT", (
            _ev("net_margin_strong", metric="net_margin", value=0.15),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.14),
            _ev("ocf_to_net_income_strong", metric="ocf_to_net_income",
                value=1.3506),
        ))
        (out,) = self._recompute([msft])
        self.assertEqual(out.quality.risks, msft.quality.risks)

    def test_cash_backed_exemption_in_overlay(self) -> None:
        bill = _frozen_decision("BILL", (
            _ev("net_margin_strong", metric="net_margin", value=0.30),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.10),
            _ev("ocf_to_net_income_strong", metric="ocf_to_net_income",
                value=1.80),
        ))
        (out,) = self._recompute([bill])
        self.assertEqual(out.quality.risks, bill.quality.risks)

    def test_nonop_penalty_applies_in_recompute_ranking(self) -> None:
        flagged = _frozen_decision("GOOG", (
            _ev("net_margin_strong", metric="net_margin", value=0.55653),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.339925),
        ))
        clean = _frozen_decision("MSFT", (
            _ev("net_margin_strong", metric="net_margin", value=0.15),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.14),
        ))
        out = self._recompute([flagged, clean])
        self.assertEqual([d.symbol for d in out], ["MSFT", "GOOG"])

    def test_cli_end_to_end_read_only(self) -> None:
        import hashlib
        import json
        import sys
        import tempfile
        from pathlib import Path

        from ai_value_scanner.decision.model import stock_decisions_to_jsonl

        sys.path.insert(0, "scripts")
        try:
            import render_snapshot_preview
        finally:
            sys.path.pop(0)
        goog = _frozen_decision("GOOG", (
            _ev("net_margin_strong", metric="net_margin", value=0.55653),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.339925),
        ))
        msft = _frozen_decision("MSFT", (
            _ev("net_margin_strong", metric="net_margin", value=0.15),
        ))
        with tempfile.TemporaryDirectory() as tmp:
            snap_dir = Path(tmp) / "snap"
            snap_dir.mkdir(parents=True, exist_ok=True)
            (snap_dir / "decisions.jsonl").write_text(
                stock_decisions_to_jsonl([goog, msft]), encoding="utf-8")
            (snap_dir / "run_manifest.json").write_text(
                json.dumps({"daily_symbols": ["GOOG", "MSFT"],
                            "weekly_symbols": ["GOOG", "MSFT"]},
                           sort_keys=True),
                encoding="utf-8",
            )
            before = {
                name: hashlib.sha256(
                    (snap_dir / name).read_bytes()).hexdigest()
                for name in ("decisions.jsonl", "run_manifest.json")
            }
            out_dir = Path(tmp) / "out"
            render_snapshot_preview._DEFAULT_CACHE_DIR = Path(tmp) / "no-cache"
            render_snapshot_preview._CACHE_INDEX_BY_DIR.clear()
            argv = ["render_snapshot_preview.py",
                    "--snapshot-dir", str(snap_dir),
                    "--output-dir", str(out_dir),
                    "--recompute-v2"]
            import unittest.mock as mock
            with mock.patch.object(sys, "argv", argv):
                render_snapshot_preview.main()
            for name, digest in before.items():
                self.assertEqual(
                    hashlib.sha256(
                        (snap_dir / name).read_bytes()).hexdigest(),
                    digest,
                )
            self.assertTrue((out_dir / "action_list_v2.md").exists())
            self.assertTrue((out_dir / "weekly_review_v2.md").exists())
            self.assertTrue(
                (out_dir / "decisions_recomputed_v2.jsonl").exists())
            action_md = (out_dir / "action_list_v2.md").read_text(
                encoding="utf-8")
            self.assertIn("⚠️NonOp-Gain(+21.7pp)", action_md)
            for path in (list(out_dir.rglob("*.md"))
                         + list(out_dir.rglob("*.jsonl"))):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/tmp/", text)
                self.assertNotIn("/home/", text)


# ---------------------------------------------------------------------------
# PR #90 follow-up: P1-1 Case C quarterly spike, P2-3 traceable operating
# growth basis, P2-1/P2-2 preview synchronization, P1-3 audit screen.
# ---------------------------------------------------------------------------


def _quarter_row(start, end, value, filed, accn="acc"):
    return {
        "start": start,
        "end": end,
        "val": value,
        "form": "10-Q",
        "filed": filed,
        "accn": accn,
    }


def _facts_payload(cik, revenue_rows, nonop_rows):
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": revenue_rows}},
                "NonoperatingIncomeExpense": {"units": {"USD": nonop_rows}},
            }
        },
    }


class TestNonOpQuarterlyExtraction(unittest.TestCase):
    def test_tag_registered(self) -> None:
        self.assertEqual(NONOPERATING_INCOME_TAGS, ["NonoperatingIncomeExpense"])

    def test_matches_latest_revenue_quarter(self) -> None:
        companyfacts = _facts_payload(
            "0001234567",
            [
                _quarter_row("2026-01-01", "2026-03-31", 3.0e9, "2026-05-01"),
                _quarter_row("2026-04-01", "2026-06-30", 3.583e9, "2026-08-05"),
            ],
            [
                _quarter_row("2026-01-01", "2026-03-31", -1.016e9, "2026-05-01"),
                _quarter_row("2026-04-01", "2026-06-30", 1.287e9, "2026-08-05"),
            ],
        )
        income, revenue, ratio, end = extract_latest_quarterly_nonop_metrics(
            companyfacts)
        self.assertAlmostEqual(income, 1.287e9, places=2)
        self.assertAlmostEqual(revenue, 3.583e9, places=2)
        self.assertAlmostEqual(ratio, 1.287e9 / 3.583e9, places=9)
        self.assertEqual(end, "2026-06-30")

    def test_stale_nonop_period_silent(self) -> None:
        companyfacts = _facts_payload(
            "0001234567",
            [_quarter_row("2026-04-01", "2026-06-30", 3.583e9, "2026-08-05")],
            [_quarter_row("2022-04-01", "2022-06-30", 1.287e9, "2022-08-05")],
        )
        income, revenue, ratio, end = extract_latest_quarterly_nonop_metrics(
            companyfacts)
        self.assertIsNone(income)
        self.assertAlmostEqual(revenue, 3.583e9, places=2)
        self.assertIsNone(ratio)
        self.assertEqual(end, "2026-06-30")

    def test_missing_series_returns_all_none(self) -> None:
        self.assertEqual(
            extract_latest_quarterly_nonop_metrics({"facts": {}}),
            (None, None, None, None),
        )

    def test_zero_revenue_quarter_silent(self) -> None:
        companyfacts = _facts_payload(
            "0001234567",
            [_quarter_row("2026-04-01", "2026-06-30", 0.0, "2026-08-05")],
            [_quarter_row("2026-04-01", "2026-06-30", 1.0e9, "2026-08-05")],
        )
        income, revenue, ratio, end = extract_latest_quarterly_nonop_metrics(
            companyfacts)
        self.assertIsNone(income)
        self.assertEqual(revenue, 0.0)
        self.assertIsNone(ratio)
        self.assertEqual(end, "2026-06-30")


class TestQualityV2CaseC(unittest.TestCase):
    def _case_c(self, *, nonop, revenue, net_margin=0.30, ebit=290.0,
                fcf=200.0, ocf=1.2, **extra):
        metrics = _metrics(
            net_margin=net_margin, ebit=ebit, free_cash_flow=fcf,
            ocf_to_net_income=ocf, **extra)
        metrics["latest_quarterly_nonoperating_income"] = nonop
        metrics["latest_quarterly_revenue"] = revenue
        return build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")

    def test_constants(self) -> None:
        self.assertEqual(QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN, 0.25)
        self.assertEqual(QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR, 200_000_000.0)

    def test_shop_archetype_triggers(self) -> None:
        decision = build_company_quality_v2(
            _metrics(
                net_margin=0.151, ebit=145.0, adjusted_net_income_yoy=-0.154,
                ebit_yoy=0.513,
                latest_quarterly_nonoperating_income=1.287e9,
                latest_quarterly_revenue=3.583e9,
            ),
            decision_date="2026-10-15", data_asof="2026-10-01",
        )
        item = next(
            i for i in decision.risks
            if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(item.value, 0.359196, places=6)
        self.assertIn("quarterly revenue", item.message)
        self.assertIn("$1.29B", item.message)
        self.assertAlmostEqual(
            _evidence_value(decision, "net_margin"), 0.145, places=6)
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 0.513,
            places=6)
        self.assertNotIn("adjusted_net_income_yoy_weak", _codes(decision))
        self.assertNotIn(
            "operating_growth_basis_substituted", _codes(decision))

    def test_absolute_floor(self) -> None:
        # 150M / 375M = 40% but below the $200M floor: stays silent.
        silent = self._case_c(nonop=150e6, revenue=375e6)
        self.assertNotIn("nonoperating_gain_inflation", _codes(silent))
        fired = self._case_c(nonop=250e6, revenue=375e6)
        self.assertIn("nonoperating_gain_inflation", _codes(fired))
        item = next(
            i for i in fired.risks if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(item.value, 0.666667, places=6)

    def test_ratio_floor(self) -> None:
        silent = self._case_c(nonop=200e6, revenue=1000e6)
        self.assertNotIn("nonoperating_gain_inflation", _codes(silent))

    def test_income_without_matching_ratio_silent(self) -> None:
        # Period-mismatch cache: income present, no ratio -> stays silent.
        metrics = _metrics(
            net_margin=0.30, ebit=290.0, free_cash_flow=200.0)
        metrics["latest_quarterly_nonoperating_income"] = 1.0e9
        decision = build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")
        self.assertNotIn("nonoperating_gain_inflation", _codes(decision))

    def test_msft_bill_case_c_controls(self) -> None:
        msft = self._case_c(
            nonop=3.44e9, revenue=90e9, net_margin=0.35, ebit=340.0,
            fcf=300.0, ocf=1.3506)
        self.assertNotIn("nonoperating_gain_inflation", _codes(msft))
        bill = self._case_c(
            nonop=30e6, revenue=1000e6, net_margin=0.30, ebit=100.0,
            fcf=220.0, ocf=1.80)
        self.assertNotIn("nonoperating_gain_inflation", _codes(bill))

    def test_case_c_priority_penalty(self) -> None:
        metrics = _metrics(
            net_margin=0.151, ebit=145.0, adjusted_net_income_yoy=-0.154,
            ebit_yoy=0.513,
            latest_quarterly_nonoperating_income=1.287e9,
            latest_quarterly_revenue=3.583e9,
        )
        qualified = build_company_quality_v2(
            metrics, decision_date="2026-10-15", data_asof="2026-10-01")
        clean = build_company_quality_v2(
            _metrics(), decision_date="2026-10-15", data_asof="2026-10-01")
        flagged = _decision(
            symbol="SHOP", quality_risks=qualified.risks,
            quality_positives=qualified.positives)
        control = _decision(
            symbol="CTRL", quality_risks=clean.risks,
            quality_positives=clean.positives)
        ranked = assign_action_priorities_v2([flagged, control])
        self.assertEqual([d.symbol for d in ranked], ["CTRL", "SHOP"])
        self.assertEqual(H3_NONOPERATING_GAIN_PRIORITY_PENALTY, 0.06)


class TestCaseCBadgesAndFragments(unittest.TestCase):
    def _shop_risk(self):
        return _ev(
            "nonoperating_gain_inflation", polarity="negative",
            metric="net_margin", value=0.359196,
            message=(
                "Single-quarter non-operating income is $1.29B "
                "(35.9% of quarterly revenue); quarterly mark-to-market "
                "investment gains distort GAAP earnings."),
        )

    def test_badge_quarterly_variant(self) -> None:
        decision = _decision(quality_risks=(self._shop_risk(),))
        card = build_stock_card_view_model(decision)
        self.assertEqual(card.warning_badges_inline,
                         "⚠️NonOp-Gain(Qtr +36% rev)")

    def test_fragment_quarterly_variant(self) -> None:
        self.assertEqual(
            _inline_fragment(self._shop_risk()),
            "⚠️ Non-Op Gain (Qtr +35.9% of rev)")

    def test_pp_variant_unchanged(self) -> None:
        risk = _ev(
            "nonoperating_gain_inflation", polarity="negative",
            metric="net_margin", value=0.216605)
        decision = _decision(quality_risks=(risk,))
        card = build_stock_card_view_model(decision)
        self.assertEqual(card.warning_badges_inline,
                         "⚠️NonOp-Gain(+21.7pp)")
        self.assertEqual(_inline_fragment(risk),
                         "⚠️ Non-Op Gain (+21.7pp vs OpMargin)")


class TestOperatingGrowthBasisTrace(unittest.TestCase):
    def _standalone(self, **overrides):
        return build_company_quality_v2(
            _metrics(
                net_margin=0.151, ebit=145.0,
                adjusted_net_income_yoy=-0.154, ebit_yoy=0.513,
                **overrides,
            ),
            decision_date="2026-10-15", data_asof="2026-10-01",
        )

    def test_trace_item_emitted_without_nonop_risk(self) -> None:
        decision = self._standalone()
        codes = _codes(decision)
        self.assertNotIn("nonoperating_gain_inflation", codes)
        self.assertIn("operating_growth_basis_substituted", codes)
        item = next(
            i for i in decision.risks
            if i.code == "operating_growth_basis_substituted")
        self.assertAlmostEqual(item.value, 0.513, places=6)
        self.assertAlmostEqual(
            _evidence_value(decision, "adjusted_net_income_yoy"), 0.513,
            places=6)

    def test_trace_renders_in_watchouts_and_fragment(self) -> None:
        quality_decision = self._standalone()
        item = next(
            i for i in quality_decision.risks
            if i.code == "operating_growth_basis_substituted")
        decision = _decision(
            quality_risks=tuple(quality_decision.risks),
            quality_positives=tuple(quality_decision.positives),
        )
        card = build_stock_card_view_model(decision)
        self.assertIn(
            "Growth on OpInc basis", card.fundamental_watchouts_inline)
        self.assertEqual(
            _inline_fragment(item),
            "Growth on OpInc basis (+51.3% vs distorted NI YoY)")
        self.assertEqual(_compact_label(item), "OpInc YoY Basis")

    def test_trace_item_has_no_priority_penalty(self) -> None:
        trace_decision = _decision(
            symbol="AAA",
            quality_risks=(_ev(
                "operating_growth_basis_substituted", polarity="negative",
                metric="adjusted_net_income_yoy", value=0.513),),
        )
        clean = _decision(symbol="BBB")
        ranked = assign_action_priorities_v2([trace_decision, clean])
        # Alphabetical (no penalty): a penalty would push AAA behind BBB.
        self.assertEqual([d.symbol for d in ranked], ["AAA", "BBB"])

    def test_turnaround_guard_blocks_substitution(self) -> None:
        # Near-zero EBIT turnaround: op margin 0.03 and EBIT YoY +700% must
        # not be promoted as clean growth.
        decision = build_company_quality_v2(
            _metrics(
                net_margin=0.10, ebit=30.0,
                adjusted_net_income_yoy=-0.20, ebit_yoy=7.00,
            ),
            decision_date="2026-10-15", data_asof="2026-10-01",
        )
        codes = _codes(decision)
        self.assertNotIn("operating_growth_basis_substituted", codes)
        self.assertIn("adjusted_net_income_yoy_weak", codes)
        self.assertIsNone(
            _evidence_value(decision, "adjusted_net_income_yoy"))

    def test_low_operating_margin_floor_blocks_substitution(self) -> None:
        # op margin 0.05 < 0.10 -> no standalone substitution even with a
        # large YoY gap (and no Case A/B/C trigger).
        decision = build_company_quality_v2(
            _metrics(
                net_margin=0.09, ebit=50.0,
                adjusted_net_income_yoy=-0.30, ebit_yoy=0.50,
            ),
            decision_date="2026-10-15", data_asof="2026-10-01",
        )
        self.assertNotIn(
            "operating_growth_basis_substituted", _codes(decision))
        self.assertIn("adjusted_net_income_yoy_weak", _codes(decision))
        item = next(
            i for i in decision.risks if i.code == "adjusted_net_income_yoy_weak")
        self.assertAlmostEqual(item.value, -0.30, places=6)


class TestQualityIntegrityDeprioritizedNotes(unittest.TestCase):
    def _flagged(self, symbol, priority, action=ActionState.PRIORITY_REVIEW):
        return _decision(
            symbol=symbol, priority=priority, action=action,
            quality_risks=(_ev(
                "nonoperating_gain_inflation", polarity="negative",
                metric="net_margin", value=0.2),),
        )

    def test_notes_surface_off_top15_flagged_only(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        flagged_in = self._flagged("A03", 3)  # already primary -> not noted
        off_late = self._flagged("GOOG", 21)
        off_early = self._flagged("ZM", 19)
        non_priority = self._flagged("HOLD", 25, action=ActionState.AVOID)
        pool = primaries + (flagged_in, off_late, off_early, non_priority)
        view = build_snapshot_view_model(
            primaries, pool, title="T", cadence="daily")
        self.assertEqual(
            view.deprioritized_quality_integrity_notes,
            ("ZM (#19, Q:A 0.80)", "GOOG (#21, Q:A 0.80)"),
        )

    def test_notes_absent_without_pool(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        view = build_snapshot_view_model(
            primaries, title="T", cadence="daily")
        self.assertEqual(view.deprioritized_quality_integrity_notes, ())

    def test_action_list_renders_disclosure_line(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        pool = primaries + (self._flagged("ZM", 19),)
        md = render_action_list_v2(
            primaries, title="T", cadence="daily", all_decisions=pool)
        line = next(
            ln for ln in md.splitlines() if "Quality-Integrity" in ln)
        self.assertIn("Off Top-15 via Non-Op Gain Guard", line)
        self.assertIn("ZM (#19, Q:A 0.80)", line)

    def test_notes_capped_at_ten(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 16))
        flagged = tuple(
            self._flagged(f"F{i:02d}", 20 + i) for i in range(12))
        view = build_snapshot_view_model(
            primaries, primaries + flagged, title="T", cadence="daily")
        self.assertEqual(
            len(view.deprioritized_quality_integrity_notes), 10)


class TestRecomputeV2PositivesSync(unittest.TestCase):
    def _recompute(self, decisions, cache_dir):
        import sys
        sys.path.insert(0, "scripts")
        try:
            from render_snapshot_preview import recompute_v2_decisions
        finally:
            sys.path.pop(0)
        return recompute_v2_decisions(decisions, cache_dir=cache_dir)

    def _write_cache(self, base, cik, payload, facts=None):
        import json as _json

        base.mkdir(parents=True, exist_ok=True)
        (base / f"parsed_fund_{cik}.json").write_text(
            _json.dumps({"cik": cik, **payload}), encoding="utf-8")
        if facts is not None:
            (base / f"facts_{cik}.json").write_text(
                _json.dumps(facts), encoding="utf-8")
        return base

    def test_zm_margin_and_growth_synced(self) -> None:
        import tempfile
        from pathlib import Path

        zm = _frozen_decision("ZM", (
            _ev("net_margin_strong", metric="net_margin", value=0.652),
            _ev("adjusted_net_income_yoy_strong",
                metric="adjusted_net_income_yoy", value=1.740),
        ))
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_cache(Path(tmp) / "cache", "0001616707", {
                "symbol": "ZM",
                "revenue": 1000.0,
                "adjusted_net_income": 652.0,
                "adjusted_ebit": 237.0,
                "free_cash_flow": 300.0,
                "ocf_to_net_income": 0.614,
                "adjusted_net_income_yoy": 1.740,
                "ebit_yoy": 0.220,
            })
            (out,) = self._recompute([zm], cache)
            codes = {i.code for i in out.quality.risks}
            self.assertIn("nonoperating_gain_inflation", codes)
            positives = {i.code: i.value for i in out.quality.positives}
            self.assertAlmostEqual(
                positives["net_margin_strong"], 0.237, places=6)
            self.assertAlmostEqual(
                positives["adjusted_net_income_yoy_strong"], 0.220,
                places=6)
            (twice,) = self._recompute([out], cache)
            self.assertEqual(twice.quality.risks, out.quality.risks)
            self.assertEqual(twice.quality.positives, out.quality.positives)

    def test_ntnx_margin_strong_removed_below_floor(self) -> None:
        import tempfile
        from pathlib import Path

        ntnx = _frozen_decision("NTNX", (
            _ev("net_margin_strong", metric="net_margin", value=0.528),
            _ev("fcf_margin_strong", metric="fcf_margin", value=0.295),
            _ev("adjusted_net_income_yoy_strong",
                metric="adjusted_net_income_yoy", value=7.0),
        ))
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_cache(Path(tmp) / "cache", "0001373715", {
                "symbol": "NTNX",
                "revenue": 1000.0,
                "adjusted_net_income": 528.0,
                "adjusted_ebit": 96.0,
                "free_cash_flow": 295.0,
                "ocf_to_net_income": 0.608,
                "adjusted_net_income_yoy": 7.0,
                "ebit_yoy": 0.588,
            })
            (out,) = self._recompute([ntnx], cache)
            positives = {i.code: i.value for i in out.quality.positives}
            self.assertNotIn("net_margin_strong", positives)
            self.assertAlmostEqual(
                positives["adjusted_net_income_yoy_strong"], 0.588,
                places=6)
            item = next(
                i for i in out.quality.risks
                if i.code == "nonoperating_gain_inflation")
            self.assertAlmostEqual(item.value, 0.432, places=6)

    def test_shop_case_c_with_facts_cache(self) -> None:
        import tempfile
        from pathlib import Path

        shop = _frozen_decision("SHOP", (
            _ev("net_margin_strong", metric="net_margin", value=0.151),
        ), risks=(
            _ev("adjusted_net_income_yoy_weak",
                polarity="negative", metric="adjusted_net_income_yoy",
                value=-0.154),
        ))
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_cache(
                Path(tmp) / "cache", "001594805", {
                    "symbol": "SHOP",
                    "revenue": 3.583e9,
                    "adjusted_net_income": 0.541e9,
                    "adjusted_ebit": 0.519535e9,
                    "free_cash_flow": 0.30e9,
                    "ocf_to_net_income": 1.183,
                    "adjusted_net_income_yoy": -0.154,
                    "ebit_yoy": 0.513,
                },
                facts=_facts_payload(
                    "001594805",
                    [_quarter_row(
                        "2026-04-01", "2026-06-30", 3.583e9, "2026-08-05")],
                    [_quarter_row(
                        "2026-04-01", "2026-06-30", 1.287e9, "2026-08-05")],
                ),
            )
            (out,) = self._recompute([shop], cache)
            codes = {i.code for i in out.quality.risks}
            self.assertIn("nonoperating_gain_inflation", codes)
            self.assertNotIn("adjusted_net_income_yoy_weak", codes)
            item = next(
                i for i in out.quality.risks
                if i.code == "nonoperating_gain_inflation")
            self.assertAlmostEqual(item.value, 0.359196, places=6)
            self.assertIn("quarterly revenue", item.message)
            positives = {i.code: i.value for i in out.quality.positives}
            self.assertAlmostEqual(
                positives["net_margin_strong"], 0.145, places=6)
            self.assertAlmostEqual(
                positives["adjusted_net_income_yoy_strong"], 0.513,
                places=6)
            card = build_stock_card_view_model(out)
            self.assertIn("⚠️NonOp-Gain(Qtr +36% rev)",
                          card.warning_badges_inline)
            (twice,) = self._recompute([out], cache)
            self.assertEqual(twice.quality.risks, out.quality.risks)
            self.assertEqual(twice.quality.positives, out.quality.positives)

    def test_standalone_trace_without_nonop_in_cache(self) -> None:
        import tempfile
        from pathlib import Path

        shop = _frozen_decision("SHOP2", (
            _ev("net_margin_strong", metric="net_margin", value=0.151),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.145),
        ), risks=(
            _ev("adjusted_net_income_yoy_weak",
                polarity="negative", metric="adjusted_net_income_yoy",
                value=-0.154),
        ))
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_cache(Path(tmp) / "cache", "0000000001", {
                "symbol": "SHOP2",
                "revenue": 1000.0,
                "adjusted_net_income": 151.0,
                "adjusted_ebit": 145.0,
                "adjusted_net_income_yoy": -0.154,
                "ebit_yoy": 0.513,
            })
            (out,) = self._recompute([shop], cache)
            codes = {i.code for i in out.quality.risks}
            self.assertNotIn("nonoperating_gain_inflation", codes)
            self.assertIn("operating_growth_basis_substituted", codes)
            self.assertNotIn("adjusted_net_income_yoy_weak", codes)
            positives = {i.code: i.value for i in out.quality.positives}
            self.assertAlmostEqual(
                positives["adjusted_net_income_yoy_strong"], 0.513,
                places=6)


class TestNonopGainAuditScreen(unittest.TestCase):
    def _write_fund(self, base, cik, payload):
        import json as _json

        base.mkdir(parents=True, exist_ok=True)
        (base / f"parsed_fund_{cik}.json").write_text(
            _json.dumps({"cik": cik, **payload}), encoding="utf-8")

    def _write_facts(self, base, cik, revenue_rows, nonop_rows):
        import json as _json

        (base / f"facts_{cik}.json").write_text(
            _json.dumps(_facts_payload(cik, revenue_rows, nonop_rows)),
            encoding="utf-8")

    def _import_audit(self):
        import sys
        sys.path.insert(0, "scripts")
        try:
            import audit_nonop_gain_screen
        finally:
            sys.path.pop(0)
        return audit_nonop_gain_screen

    def test_run_nonop_gain_audit_hits_and_guards(self) -> None:
        import tempfile
        from pathlib import Path

        audit = self._import_audit()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "cache"
            self._write_fund(base, "0001652044", {
                "symbol": "GOOG",
                "revenue": 119.8e9,
                "adjusted_net_income": 66.7e9,
                "adjusted_ebit": 40.77e9,
                "free_cash_flow": 14.0e9,
                "ocf_to_net_income": 0.748,
                "nonrecurring_gain_subtraction": 0.0,
            })
            self._write_facts(
                base, "0001652044",
                [_quarter_row(
                    "2026-04-01", "2026-06-30", 119.8e9, "2026-07-30")],
                [_quarter_row(
                    "2026-04-01", "2026-06-30", 98.0e9, "2026-07-30")],
            )
            self._write_fund(base, "0001373715", {
                "symbol": "NTNX",
                "revenue": 0.6e9,
                "adjusted_net_income": 0.317e9,
                "adjusted_ebit": 0.058e9,
                "free_cash_flow": 0.177e9,
                "ocf_to_net_income": 0.608,
                "nonrecurring_gain_subtraction": 0.43e9,
            })
            self._write_facts(
                base, "0001373715",
                [_quarter_row(
                    "2026-04-01", "2026-06-30", 0.6e9, "2026-08-01")],
                [_quarter_row(
                    "2022-04-01", "2022-06-30", 1.18e9, "2022-08-01")],
            )
            self._write_fund(base, "0000789019", {
                "symbol": "MSFT",
                "revenue": 90e9,
                "adjusted_net_income": 31.5e9,
                "adjusted_ebit": 30.6e9,
                "free_cash_flow": 25e9,
                "ocf_to_net_income": 1.3506,
                "nonrecurring_gain_subtraction": 0.0,
            })
            rows = {row["symbol"]: row for row in audit.run_nonop_gain_audit(base)}
        goog = rows["GOOG"]
        self.assertTrue(goog["ttm_margin_gap_hit"])
        self.assertTrue(goog["quarterly_spike_hit"])
        self.assertTrue(goog["hit"])
        self.assertAlmostEqual(
            goog["quarterly_nonop_ratio"], 98.0 / 119.8, places=9)
        self.assertEqual(goog["quarterly_period_end"], "2026-06-30")
        ntnx = rows["NTNX"]
        self.assertTrue(ntnx["ttm_margin_gap_hit"])
        self.assertFalse(ntnx["quarterly_spike_hit"])  # stale 2022 period
        self.assertTrue(ntnx["disposal_gain_stripped"])
        self.assertTrue(ntnx["hit"])
        msft = rows["MSFT"]
        self.assertFalse(msft["hit"])
        self.assertFalse(msft["ttm_margin_gap_hit"])
        self.assertFalse(msft["quarterly_spike_hit"])

    def test_threshold_parameters(self) -> None:
        import tempfile
        from pathlib import Path

        audit = self._import_audit()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "cache"
            self._write_fund(base, "0001018724", {
                "symbol": "AMZN",
                "revenue": 1000.0,
                "adjusted_net_income": 176.0,
                "adjusted_ebit": 122.0,
                "free_cash_flow": 200.0,
                "ocf_to_net_income": 1.182,
                "nonrecurring_gain_subtraction": 0.0,
            })
            default_rows = {
                row["symbol"]: row
                for row in audit.run_nonop_gain_audit(base)
            }
            self.assertTrue(default_rows["AMZN"]["ttm_margin_gap_hit"])
            strict_rows = {
                row["symbol"]: row
                for row in audit.run_nonop_gain_audit(base, min_ttm_gap=0.10)
            }
            self.assertFalse(strict_rows["AMZN"]["ttm_margin_gap_hit"])
            # Quarterly sub-floor guard: 150M at 40% stays silent.
            self._write_fund(base, "0000000002", {
                "symbol": "SUBF",
                "revenue": 375.0,
                "adjusted_net_income": 112.5,
                "adjusted_ebit": 108.75,
                "free_cash_flow": 75.0,
                "ocf_to_net_income": 1.2,
                "nonrecurring_gain_subtraction": 0.0,
            })
            self._write_facts(
                base, "0000000002",
                [_quarter_row("2026-04-01", "2026-06-30", 375e6, "2026-08-01")],
                [_quarter_row("2026-04-01", "2026-06-30", 150e6, "2026-08-01")],
            )
            sub_rows = {
                row["symbol"]: row
                for row in audit.run_nonop_gain_audit(base)
            }
            self.assertFalse(sub_rows["SUBF"]["quarterly_spike_hit"])

    def test_cli_writes_markdown_and_json(self) -> None:
        import json as _json
        import sys
        import tempfile
        import unittest.mock as mock
        from pathlib import Path

        audit = self._import_audit()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "cache"
            self._write_fund(base, "0001652044", {
                "symbol": "GOOG",
                "revenue": 119.8e9,
                "adjusted_net_income": 66.7e9,
                "adjusted_ebit": 40.77e9,
                "free_cash_flow": 14.0e9,
                "ocf_to_net_income": 0.748,
                "nonrecurring_gain_subtraction": 0.0,
            })
            self._write_facts(
                base, "0001652044",
                [_quarter_row(
                    "2026-04-01", "2026-06-30", 119.8e9, "2026-07-30")],
                [_quarter_row(
                    "2026-04-01", "2026-06-30", 98.0e9, "2026-07-30")],
            )
            out_json = Path(tmp) / "report.json"
            argv = [
                "audit_nonop_gain_screen.py",
                "--cache-dir", str(base),
                "--output-json", str(out_json),
            ]
            import contextlib
            import io

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                with mock.patch.object(sys, "argv", argv):
                    audit.main()
            stdout = buffer.getvalue()
            self.assertIn("| GOOG |", stdout)
            self.assertIn("1 non-op hit(s)", stdout)
            self.assertTrue(out_json.exists())
            payload = _json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual([row["symbol"] for row in payload], ["GOOG"])
            text = out_json.read_text(encoding="utf-8")
            self.assertNotIn("/tmp/", text)
            self.assertNotIn("/home/", text)


class _FakeSecClient:
    """Minimal SecClient stand-in for interest-income extraction tests."""

    def __init__(self, companyfacts):
        self._facts = companyfacts

    def get_submissions(self, cik):
        return {"sic": "3571", "sicDescription": "Electronic Computers"}

    def get_companyfacts(self, cik):
        return self._facts


def _interest_income_facts(interest_quarters):
    """Companyfacts with a 4-quarter TTM interest-income series."""
    q_end = ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]

    def q_vals(values):
        return [
            {"end": end, "val": value, "form": "10-Q", "filed": "2026-02-15"}
            for end, value in zip(q_end, values)
        ]

    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": q_vals([130, 120, 110, 100])}},
                "NetIncomeLoss": {"units": {"USD": q_vals([46, 44, 42, 40])}},
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": q_vals([58, 55, 52, 45])}
                },
                "OperatingIncomeLoss": {
                    "units": {"USD": q_vals([70, 65, 60, 55])}
                },
                "InterestExpense": {
                    "units": {"USD": q_vals([-2, -2, -2, -2])}
                },
                "InvestmentIncomeInterest": {
                    "units": {"USD": q_vals(interest_quarters)}
                },
            }
        }
    }


def _pltr_interest_facts_rows():
    """InvestmentIncomeInterest quarters matching PLTR's TTM ~$266.4M."""
    return [
        _quarter_row("2025-07-01", "2025-09-30", 62.0, "2026-02-15"),
        _quarter_row("2025-10-01", "2025-12-31", 64.0, "2026-02-15"),
        _quarter_row("2026-01-01", "2026-03-31", 68.0, "2026-02-15"),
        _quarter_row("2026-04-01", "2026-06-30", 72.4, "2026-08-05"),
    ]


class TestNetInterestIncomeExemption(unittest.TestCase):
    """Layer-1 Case A net-interest-income exemption (PLTR / ALAB class)."""

    PLTR_METRICS = dict(
        revenue=5753.0,
        net_margin=0.490,
        ebit=2462.0,
        free_cash_flow=1500.0,
        ocf_to_net_income=1.127,
        interest_income=266.4,
        interest_expense=3.5,
    )

    def _build(self, **overrides):
        return build_company_quality_v2(
            _metrics(**overrides),
            decision_date="2026-10-15",
            data_asof="2026-10-01",
        )

    def test_tag_list_registered(self) -> None:
        self.assertEqual(
            INTEREST_INCOME_TAGS,
            [
                "InvestmentIncomeInterest",
                "InterestAndDividendIncomeOperating",
                "InvestmentIncomeInterestAndDividend",
                "InterestIncomeOther",
                "InvestmentIncomeNet",
            ],
        )

    def test_pltr_archetype_exempted(self) -> None:
        decision = self._build(**self.PLTR_METRICS)
        self.assertEqual(_codes(decision), set())
        # Net margin keeps the raw reported value (no operating-basis cap).
        self.assertAlmostEqual(
            _evidence_value(decision, "net_margin"), 0.490, places=6)

    def test_pltr_without_interest_inputs_would_trigger(self) -> None:
        metrics = {
            key: value
            for key, value in self.PLTR_METRICS.items()
            if key not in {"interest_income", "interest_expense"}
        }
        decision = self._build(**metrics)
        self.assertIn("nonoperating_gain_inflation", _codes(decision))

    def test_pltr_no_badge_and_no_priority_penalty(self) -> None:
        quality = self._build(**self.PLTR_METRICS)
        exempt = _decision(
            symbol="APLTR",
            quality_risks=tuple(quality.risks),
            quality_positives=tuple(quality.positives),
        )
        card = build_stock_card_view_model(exempt)
        self.assertEqual(card.warning_badges_inline, "")
        clean = _decision(symbol="ZZCLN")
        ranked = assign_action_priorities_v2([exempt, clean])
        # No -0.06 penalty: the exempt name keeps the alphabetical tie-break
        # (a penalty would push it behind the later-sorting clean peer).
        self.assertEqual([d.symbol for d in ranked], ["APLTR", "ZZCLN"])

    def test_confirmed_polluters_still_caught_with_interest_income(self) -> None:
        goog = self._build(
            net_margin=0.55653, revenue=1000.0, ebit=339.925,
            free_cash_flow=119.482, ocf_to_net_income=0.748,
            adjusted_net_income_yoy=1.147024, ebit_yoy=0.249,
            interest_income=11.0, interest_expense=0.5,
        )
        goog_item = next(
            i for i in goog.risks if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(goog_item.value, 0.216605, places=6)

        amzn = self._build(
            net_margin=0.176, revenue=775680.0, ebit=94632.96,
            free_cash_flow=80000.0, ocf_to_net_income=1.182,
            adjusted_net_income_yoy=0.933, ebit_yoy=0.246,
            interest_income=4660.0, interest_expense=3003.0,
        )
        amzn_item = next(
            i for i in amzn.risks if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(amzn_item.value, 0.054, places=5)

        zm = self._build(
            net_margin=0.652, ebit=237.0, free_cash_flow=150.0,
            ocf_to_net_income=0.614,
            adjusted_net_income_yoy=1.740, ebit_yoy=0.220,
            interest_income=20.0, interest_expense=5.0,
        )
        zm_item = next(
            i for i in zm.risks if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(zm_item.value, 0.415, places=6)

        ntnx = self._build(
            net_margin=0.528, ebit=96.0, free_cash_flow=295.0,
            ocf_to_net_income=0.608,
            adjusted_net_income_yoy=7.0, ebit_yoy=0.588,
            interest_income=5.0, interest_expense=1.0,
        )
        ntnx_item = next(
            i for i in ntnx.risks if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(ntnx_item.value, 0.432, places=6)

        wdc = self._build(
            net_margin=0.741, ebit=357.0, free_cash_flow=250.0,
            ocf_to_net_income=0.410,
            adjusted_net_income_yoy=4.329, ebit_yoy=1.054,
            interest_income=51.0, interest_expense=403.0,
        )
        wdc_item = next(
            i for i in wdc.risks if i.code == "nonoperating_gain_inflation")
        self.assertAlmostEqual(wdc_item.value, 0.384, places=6)

    def test_load_one_fundamental_extracts_ttm_interest_income(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            sec = _FakeSecClient(
                _interest_income_facts([8.0, 7.0, 6.0, 5.0]))
            cfg = ScanConfig(
                use_ttm_metrics=True,
                nonrecurring_addback_revenue_cap=0.25,
                cache_dir=tmp,
            )
            out = load_one_fundamental(sec, "TEST", "0000009099", cfg)
            self.assertAlmostEqual(out["interest_income"], 26.0, places=6)
            self.assertAlmostEqual(out["interest_expense"], 8.0, places=6)

    def test_load_one_fundamental_clamps_negative_interest_income(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sec = _FakeSecClient(
                _interest_income_facts([-3.0, -2.0, -2.0, -1.0]))
            cfg = ScanConfig(
                use_ttm_metrics=True,
                nonrecurring_addback_revenue_cap=0.25,
                cache_dir=tmp,
            )
            out = load_one_fundamental(sec, "NEGI", "0000009098", cfg)
            self.assertEqual(out["interest_income"], 0.0)

    def _pltr_frozen(self):
        return _frozen_decision("PLTR", (
            _ev("net_margin_strong", metric="net_margin", value=0.490),
            _ev("operating_margin_strong", metric="operating_margin",
                value=0.428),
            _ev("ocf_to_net_income_strong", metric="ocf_to_net_income",
                value=1.127),
        ))

    def _write_pltr_cache(self, base, *, include_payload_interest: bool,
                          include_facts: bool) -> Path:
        import json as _json

        base.mkdir(parents=True, exist_ok=True)
        payload = {
            "symbol": "PLTR",
            "cik": "001321655",
            "revenue": 5753.0,
            "adjusted_net_income": 2819.0,
            "adjusted_ebit": 2462.25,
            "free_cash_flow": 1500.0,
            "ocf_to_net_income": 1.127,
            "nonrecurring_gain_subtraction": 0.0,
        }
        if include_payload_interest:
            payload["interest_income"] = 266.4
            payload["interest_expense"] = 3.5
        (base / "parsed_fund_001321655.json").write_text(
            _json.dumps(payload), encoding="utf-8")
        if include_facts:
            (base / "facts_001321655.json").write_text(
                _json.dumps({
                    "cik": "1321655",
                    "facts": {"us-gaap": {
                        "InvestmentIncomeInterest": {
                            "units": {"USD": _pltr_interest_facts_rows()},
                        },
                    }},
                }),
                encoding="utf-8",
            )
        return base

    def _recompute_pltr(self, cache):
        import sys

        sys.path.insert(0, "scripts")
        try:
            from render_snapshot_preview import recompute_v2_decisions
        finally:
            sys.path.pop(0)
        return recompute_v2_decisions([self._pltr_frozen()], cache_dir=cache)

    def test_recompute_pltr_exempt_via_facts_interest_income(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_pltr_cache(
                Path(tmp) / "cache",
                include_payload_interest=False,
                include_facts=True,
            )
            (out,) = self._recompute_pltr(cache)
            self.assertNotIn(
                "nonoperating_gain_inflation",
                {i.code for i in out.quality.risks})
            self.assertAlmostEqual(
                _evidence_value(out.quality, "net_margin"), 0.490,
                places=6)
            (twice,) = self._recompute_pltr(cache)
            self.assertEqual(twice.quality.risks, out.quality.risks)

    def test_recompute_pltr_exempt_via_payload_interest_income(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_pltr_cache(
                Path(tmp) / "cache",
                include_payload_interest=True,
                include_facts=False,
            )
            (out,) = self._recompute_pltr(cache)
            self.assertNotIn(
                "nonoperating_gain_inflation",
                {i.code for i in out.quality.risks})

    def test_recompute_pltr_control_flagged_without_interest_data(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_pltr_cache(
                Path(tmp) / "cache",
                include_payload_interest=False,
                include_facts=False,
            )
            (out,) = self._recompute_pltr(cache)
            self.assertIn(
                "nonoperating_gain_inflation",
                {i.code for i in out.quality.risks})

    def test_audit_pltr_exempt_via_facts_interest_income(self) -> None:
        import tempfile

        import sys

        from pathlib import Path

        sys.path.insert(0, "scripts")
        try:
            from audit_nonop_gain_screen import run_nonop_gain_audit
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_pltr_cache(
                Path(tmp) / "cache",
                include_payload_interest=False,
                include_facts=True,
            )
            rows = run_nonop_gain_audit(cache)
        pltr = next(row for row in rows if row["symbol"] == "PLTR")
        self.assertFalse(pltr["ttm_margin_gap_hit"])
        self.assertFalse(pltr["hit"])
        self.assertAlmostEqual(
            pltr["net_interest_margin"], 266.4 / 5753.0, places=9)

    def test_audit_pltr_control_flagged_without_interest_data(self) -> None:
        import tempfile

        import sys

        from pathlib import Path

        sys.path.insert(0, "scripts")
        try:
            from audit_nonop_gain_screen import run_nonop_gain_audit
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._write_pltr_cache(
                Path(tmp) / "cache",
                include_payload_interest=False,
                include_facts=False,
            )
            rows = run_nonop_gain_audit(cache)
        pltr = next(row for row in rows if row["symbol"] == "PLTR")
        self.assertTrue(pltr["ttm_margin_gap_hit"])
        self.assertEqual(pltr["net_interest_margin"], 0.0)


if __name__ == "__main__":
    unittest.main()
