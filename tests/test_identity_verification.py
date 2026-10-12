"""Ticker-to-filing-entity identity verification (no network)."""

from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.quality import build_company_quality_v1
from ai_value_scanner.fundamentals.identity import verify_operating_entity


def _metrics(**overrides):
    base = {
        "net_margin": 0.14,
        "free_cash_flow": 1e9,
        "ocf_to_net_income": 1.2,
        "accrual_ratio": -0.05,
        "revenue_yoy": 0.10,
        "net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.18,
        "net_debt_to_ebitda": 0.5,
        "interest_coverage": 12.0,
        "current_ratio": 1.8,
        "shares_yoy": 0.01,
        "shares_stale": False,
        "fcf_yield": 0.04,
        "ps_hist_percentile": 0.5,
        "pe_hist_percentile": 0.5,
        "receivables_growth_gap": 0.0,
        "inventory_growth_gap": 0.0,
        "fundamental_data_asof": "2026-08-03",
    }
    base.update(overrides)
    return base


class IdentityHelperTests(unittest.TestCase):
    def test_xom_class_subsidiary_without_core_facts_fails(self) -> None:
        ok, detail = verify_operating_entity("XOM", ["XOM"], 34, False)
        self.assertFalse(ok)
        self.assertEqual(detail, "core_facts_absent")

    def test_ticker_absent_from_entity_fails_despite_filings(self) -> None:
        ok, detail = verify_operating_entity("XOM", ["AAPL"], 100, True)
        self.assertFalse(ok)
        self.assertEqual(detail, "ticker_not_listed")

    def test_healthy_binding_passes(self) -> None:
        ok, detail = verify_operating_entity(
            "GS", ["GS", "GS-PA"], 16457, True)
        self.assertTrue(ok)
        self.assertEqual(detail, "ticker_listed_with_core_facts")

    def test_empty_ticker_list_falls_back_to_facts(self) -> None:
        # Real-Exxon class: submissions carry no ticker list; facts decide.
        ok, _ = verify_operating_entity("XOM", [], 1001, True)
        self.assertTrue(ok)

    def test_no_submissions_info_makes_no_claim(self) -> None:
        ok, detail = verify_operating_entity("SYM", None, 100, True)
        self.assertIsNone(ok)
        self.assertEqual(detail, "no_submissions_info")

    def test_no_filings_makes_no_claim(self) -> None:
        ok, detail = verify_operating_entity("SYM", ["SYM"], 0, False)
        self.assertIsNone(ok)
        self.assertEqual(detail, "no_filings_to_judge")


class IdentityQualityGateTests(unittest.TestCase):
    def test_absent_flag_is_byte_identical_to_verified(self) -> None:
        # No behavior change for rows without the key (all legacy rows).
        a = build_company_quality_v1(_metrics(), decision_date="2026-10-09")
        b = build_company_quality_v1(
            _metrics(fundamental_operating_entity_verified=True,
                     fundamental_operating_entity_detail="ticker_listed_with_core_facts"),
            decision_date="2026-10-09")
        self.assertEqual(a.grade, b.grade)
        self.assertEqual(a.confidence, b.confidence)
        self.assertEqual(a.score, b.score)
        self.assertEqual([e.code for e in a.missing], [e.code for e in b.missing])

    def test_unverified_caps_confidence_and_marks_code(self) -> None:
        d = build_company_quality_v1(
            _metrics(fundamental_operating_entity_verified=False,
                     fundamental_operating_entity_detail="core_facts_absent"),
            decision_date="2026-10-09")
        codes = [e.code for e in d.missing]
        self.assertIn("operating_entity_unverified", codes)
        self.assertLessEqual(d.confidence, 0.49)
        self.assertEqual(d.grade.value, "UNRATED")

    def test_unverified_never_claims_reliable_grade(self) -> None:
        # Even superb metrics cannot outrank an unverified entity.
        d = build_company_quality_v1(
            _metrics(net_margin=0.40, free_cash_flow=9e9,
                     fundamental_operating_entity_verified=False,
                     fundamental_operating_entity_detail="ticker_not_listed"),
            decision_date="2026-10-09")
        self.assertEqual(d.grade.value, "UNRATED")

    def test_explicit_unknown_is_conservative_not_silent(self) -> None:
        # Checked-but-unconfirmable bindings cap like False ...
        d = build_company_quality_v1(
            _metrics(fundamental_operating_entity_verified=None,
                     fundamental_operating_entity_detail="no_submissions_info"),
            decision_date="2026-10-09")
        codes = [e.code for e in d.missing]
        self.assertIn("operating_entity_unverified", codes)
        self.assertLessEqual(d.confidence, 0.49)
        self.assertEqual(d.grade.value, "UNRATED")

    def test_absent_flag_keeps_legacy_behavior(self) -> None:
        # ... while legacy rows without the key are untouched.
        d = build_company_quality_v1(_metrics(), decision_date="2026-10-09")
        codes = [e.code for e in d.missing]
        self.assertNotIn("operating_entity_unverified", codes)


class IdentityProvenanceTests(unittest.TestCase):
    def test_cik_and_filing_entity_reach_decision_provenance(self) -> None:
        frame = pd.DataFrame([{
            "symbol": "XOM",
            "company_name": "ExxonMobil Holdings Corp",
            "cik": "0002115436",
            "filing_entity_name": "ExxonMobil Holdings Corp",
            "fundamental_operating_entity_verified": False,
            "fundamental_operating_entity_detail": "core_facts_absent",
        }])
        decisions = build_stock_decisions(
            frame, decision_date="2026-10-09",
            generated_at_utc="2026-10-11T00:00:00+00:00")
        self.assertEqual(len(decisions), 1)
        prov = decisions[0].provenance
        self.assertEqual(prov.get("cik"), "0002115436")
        self.assertEqual(prov.get("filing_entity_name"), "ExxonMobil Holdings Corp")
        self.assertEqual(decisions[0].quality.grade.value, "UNRATED")
        self.assertIn("operating_entity_unverified",
                      [e.code for e in decisions[0].quality.missing])


if __name__ == "__main__":
    unittest.main()
