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
    QUALITY_V2_NONOP_YOY_GAP_MIN,
    build_company_quality_v1,
    build_company_quality_v2,
)
from ai_value_scanner.decision.view_model import (
    _compact_label,
    _inline_fragment,
    build_stock_card_view_model,
)
from ai_value_scanner.scanner import (
    NONRECURRING_GAIN_TAGS,
    PARSED_FUND_CACHE_VERSION,
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
    def _recompute(self, decisions):
        import sys
        sys.path.insert(0, "scripts")
        try:
            from render_snapshot_preview import recompute_v2_decisions
        finally:
            sys.path.pop(0)
        return recompute_v2_decisions(decisions)

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


if __name__ == "__main__":
    unittest.main()
