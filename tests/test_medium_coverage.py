from __future__ import annotations

import json
from datetime import date
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from ai_value_scanner.decision.medium_term import build_medium_reviews, classifications_asof, market_profile
from ai_value_scanner.decision.model import StockDecision, stock_decision_from_dict, stock_decision_to_dict
from ai_value_scanner.fundamentals.coverage import audit_filing, business_context, translate_usd
from ai_value_scanner.research.coverage_audit import compare_financial_grades, discovery_audit
from ai_value_scanner.swing.events import timestamp
from ai_value_scanner.swing.setups import next_session

HERE = Path(__file__).parent
DAY = "2026-11-23"


def stock(symbol: str, cik: int, *, sic="3571") -> StockDecision:
    return stock_decision_from_dict({
        "schema_version": "1", "symbol":symbol, "decision_date":DAY, "generated_at_utc":DAY+"T22:00:00Z",
        "quality":{"grade":"A", "confidence":.9}, "entry":{"state":"ENTRY_READY", "confidence":.9},
        "action_state":"PRIORITY_REVIEW", "priority":1, "provenance":{"cik":str(cik), "sic":sic},
    })


def quote_pair(ret: float, start: str) -> dict:
    return {"start":start, "end":DAY, "return":ret}


def profile(ret: float) -> dict:
    return {"windows": {
        5: quote_pair(ret, "2026-11-16"), 20: quote_pair(ret, "2026-10-26"),
        60: quote_pair(ret, "2026-08-28"),
    }}


class MediumReviewTests(TestCase):
    def test_issuer_cohorts_missing_prices_thresholds_and_asof_reclassification(self):
        decisions = [stock("TARGET", 1), stock("TARGET.B", 1), stock("A",2), stock("B",2),
                     stock("C",3), stock("D",4), stock("E",5), stock("F",6), stock("G",7), stock("H",8)]
        at = timestamp(DAY+"T22:00:00Z")
        records = [{"cik": item.provenance["cik"], "sic":"3571", "known_at_utc":DAY+"T21:00:00Z"} for item in decisions if item.symbol != "H"]
        records.extend([
            {"cik":"6", "sic":"4813", "known_at_utc":"2026-11-24T21:00:00Z"},
            {"cik":"8", "sic":"4813", "known_at_utc":DAY+"T21:00:00Z"},
        ])
        groups = classifications_asof(records, at)
        prices = {symbol:profile(value) for symbol, value in (
            ("TARGET",.20), ("TARGET.B",9), ("A",.04), ("B",3), ("C",.08), ("D",0),
            ("E",-.02), ("F",.10), ("H",5),
        )}
        prices["F"]["windows"][20]["start"] = "2026-10-25"
        result = build_medium_reviews(decisions, prices, profile(.02), groups,
            session=DAY, classification_asof=at.isoformat(), classification_source="frozen SIC")
        target = result["TARGET"]
        five, twenty = [target["horizons"][window] for window in ("5","20")]
        self.assertEqual((five["effective_peers"], five["eligible_peers"]), (5,6))
        self.assertAlmostEqual(five["peer_return"], .04)
        self.assertAlmostEqual(five["stock_minus_peer"], .16)
        self.assertAlmostEqual(five["peer_minus_qqq"], .02)
        self.assertEqual(five["peer_positive_share"], .6)
        self.assertEqual(twenty["effective_peers"], 4)
        self.assertIsNone(twenty["stock_minus_peer"])
        self.assertAlmostEqual(target["relative_to_qqq_60d"], .18)
        self.assertNotEqual(groups["0000000006"], classifications_asof(records, timestamp("2026-11-24T22:00:00Z"))["0000000006"])
        wire = stock_decision_to_dict(decisions[0])
        wire["medium_review"] = target
        self.assertEqual(stock_decision_from_dict(wire).medium_review, target)

    def test_only_completed_weeks_enter_sma10_and_returns_are_contiguous(self):
        days = [date(2026,8,3)]
        while len(days) < 72:
            days.append(next_session(days[-1]))
        if days[-1].weekday() == 4:
            days.append(next_session(days[-1]))
        rows = [{"t":day.isoformat(), "o":100+i, "h":101+i, "l":99+i, "c":100+i, "v":100}
                for i,day in enumerate(days)]
        selected = market_profile(rows, days[-1])
        self.assertLess(selected["completed_week"]["last_week_end"], days[-1].isoformat())
        self.assertIn(60, selected["windows"])
        gapped = market_profile(rows[:-5]+rows[-4:], days[-1])
        self.assertEqual(gapped["windows"], {})
        self.assertIsNone(gapped["completed_week"])


class FilingCoverageTests(TestCase):
    def setUp(self):
        self.case = json.loads((HERE/"fixtures/phase6_duke_coverage.json").read_text())
        self.asof = date.fromisoformat(DAY)

    def test_duke_parent_consolidated_arithmetic_from_filing(self):
        result = audit_filing(self.case, asof=self.asof)
        self.assertEqual(result["status"], "recovered_candidate")
        self.assertEqual(result["values"]["revenue"], 33812e6)
        self.assertEqual(result["values"]["net_income"], 5391e6)
        self.assertEqual(result["values"]["operating_cash_flow"], 11547e6)
        self.assertEqual(result["metrics"]["free_cash_flow"], -5162e6)
        self.assertAlmostEqual(result["metrics"]["fcf_per_current_share"], -5162/780)
        self.assertAlmostEqual(result["metrics"]["dilution_yoy"], 780/778-1)
        self.assertIsNone(result["metrics"]["enterprise_value_to_normalized_ebitda"])

    def test_currency_units_and_amendments_fail_closed(self):
        target = self.case["accession"]
        for row in self.case["facts"]:
            if row["metric"] == "revenue" and row["accession"] == target:
                row["unit"] = "USD/shares"
                row["cik"] = "1234"
        self.assertEqual(audit_filing(self.case, asof=self.asof)["status"], "unrated")
        self.case["form"] = "10-Q/A"
        self.assertEqual(audit_filing(self.case, asof=self.asof)["reason"], "unsupported_form")
        with self.assertRaisesRegex(ValueError, "observation cutoff"):
            audit_filing(self.case, asof=date(2026,11,4))

    def test_dilution_does_not_substitute_a_cover_page_count(self):
        prior = next(row for row in self.case["facts"] if row["metric"] == "shares" and row["end"] == "2025-09-30")
        later = {**prior, "end": "2025-10-10", "value": 800e6, "filed": "2025-11-11"}
        self.case["facts"].append(later)
        result = audit_filing(self.case, asof=self.asof)
        self.assertAlmostEqual(result["metrics"]["dilution_yoy"], 780/778-1)
        operand = result["derived_operands"]["comparative_shares"]
        self.assertEqual((operand["end"], operand["amount"]), ("2025-09-30", 778e6))
        self.assertEqual(operand["tag"], prior["tag"])
        self.assertEqual(operand["sources"], [prior["source"]])
        self.case["facts"].remove(prior)
        result = audit_filing(self.case, asof=self.asof)
        self.assertIsNone(result["metrics"]["dilution_yoy"])
        self.assertIsNotNone(result["metrics"]["fcf_per_current_share"])

    def test_provenance_blocks_filing_spoofing_and_ambiguous_real_estate(self):
        names = {"accession":"accession", "filed":"filing_date", "form":"form", "period_end":"report_date"}
        canonical = {f"fundamental_latest_periodic_{key}": self.case[field] for field, key in names.items()}
        canonical.update(cik=self.case["cik"], sic="6510", fundamental_reporting_currency="USD")
        valid = audit_filing(self.case, asof=self.asof, provenance=canonical)
        self.assertEqual(valid["business_context"]["model"], "unknown")
        self.assertEqual(valid["status"], "unrated")
        self.assertIsNone(valid["metrics"]["enterprise_value_to_normalized_ebitda"])
        for field, value in (("filed", "2026-10-01"), ("form", "10-K"), ("currency", "CAD"), ("period_end", "2026-09-29")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"mismatch: {field}"):
                audit_filing({**self.case, field: value}, asof=self.asof, provenance=canonical)

    def test_fx_day_and_window_must_match_and_availability_cannot_be_future(self):
        start, end = date(2025,1,1), date(2025,12,31)
        average = {"currency":"CAD", "quote_currency":"USD", "basis":"period_average",
                   "start":"2025-01-01","end":"2025-12-31", "known_on":"2026-01-03",
                   "usd_per_unit":.75, "source":"archived provider"}
        self.assertEqual(translate_usd(10,"CAD",start=start,end=end,asof=self.asof,rates=[average]), 7.5)
        self.assertIsNone(translate_usd(10,"CAD",start=None,end=end,asof=self.asof,rates=[average]))
        self.assertIsNone(translate_usd(10,"CAD",start=start,end=end,asof=date(2026,1,2),rates=[average]))
        self.assertEqual([business_context(sic)["model"] for sic in (6021,6331,6798)], ["bank_broker","insurance","reit"])

    def test_original_annual_flows_and_scoped_normalized_valuation(self):
        annual = "0001326160-26-000014"
        self.case.update(accession=annual, form="10-K", filed="2026-02-26", period_end="2025-12-31")
        sample = next(row for row in self.case["facts"] if row["accession"] == annual)
        for metric, value in (("ebit", 100), ("depreciation", 20), ("nonrecurring_addback", 10), ("nonoperating_gain", 5)):
            self.case["facts"].append({**sample, "metric":metric, "tag":metric, "value":float(value)})
        # A revision from a different accession cannot alter the exact annual inputs.
        self.case["facts"].append({**sample, "value":0.0, "form":"10-K/A", "filed":"2026-10-02", "accession":"0001326160-26-000045"})
        result = audit_filing(self.case, asof=self.asof)
        self.assertEqual(result["values"]["revenue"], 32237e6)
        self.assertIsNone(result["metrics"]["normalized_ebitda"])
        self.case["ebit_includes_adjustment_operands"] = True
        self.case["valuation"] = {"enterprise_value_usd":1250, "asof":DAY, "source":"frozen observation"}
        result = audit_filing(self.case, asof=self.asof)
        self.assertEqual(result["metrics"]["normalized_ebitda"], 125)
        self.assertEqual(result["metrics"]["enterprise_value_to_normalized_ebitda"], 10)
        self.assertEqual(result["derived_operands"]["enterprise_value"], self.case["valuation"])
        self.case["currency"] = "CAD"
        for row in self.case["facts"]:
            if row["unit"] == "USD":
                row["unit"] = "CAD"
        rate = {"currency":"CAD", "quote_currency":"USD", "basis":"period_average",
                "start":"2025-01-01","end":"2025-12-31", "known_on":"2026-01-03",
                "usd_per_unit":.8, "source":"frozen provider"}
        self.case["fx_rates"] = [rate]
        result = audit_filing(self.case, asof=self.asof)
        self.assertEqual(result["metrics"]["enterprise_value_to_normalized_ebitda"], 12.5)
        self.assertEqual(result["derived_operands"]["valuation_fx"], [rate])


class DiscoveryCoverageTests(TestCase):
    def test_recovery_compares_only_the_same_known_filing(self):
        first, second = "0000000001-26-000003", "0000000001-26-000004"
        def decision(symbol, accession, covered):
            item = stock(symbol, 1)
            return replace(item, provenance={**item.provenance,
                "fundamental_latest_periodic_accession": accession,
                "fundamental_facts_cover_latest_periodic": covered})
        summary = compare_financial_grades(
            [decision("MATCH", first, False), decision("CHANGED", first, False), decision("UNKNOWN", None, False)],
            [decision("MATCH", first, True), decision("CHANGED", second, True), decision("UNKNOWN", first, True)],
        )
        self.assertEqual(summary["newly_covered"], 1)
        self.assertEqual([row["symbol"] for row in summary["filings_changed"]], ["CHANGED"])
        self.assertEqual([row["symbol"] for row in summary["unknown_filing_identity"]], ["UNKNOWN"])

    def test_source_and_issuer_overlap_partition(self):
        decisions = [stock("AAA",1), stock("AAB",1), stock("BBB",2)]
        memberships = [
            dict(symbol=symbol, source_kind=kind, source_asof=DAY)
            for symbol,kind in (("AAA","us_core"),("AAB","thematic"),("BBB","manual"),("MISS","thematic"),("AAA","manual"))
        ]
        manifest = {"decision_date":DAY, "daily_symbols":["AAA"],"weekly_symbols":["AAA","BBB"]}
        result = discovery_audit(decisions, manifest, memberships=memberships,
            exclusions=[{"symbol":"MISS"}], baseline={"AAA"}, ticker_rows=[])
        union = result["union"]
        self.assertEqual(union["security"]["discovered"], union["security"]["decisions"]+union["security"]["excluded"])
        self.assertEqual(union["issuer"]["known"], 2)
        self.assertEqual(union["issuer"]["symbols_with_unknown_cik"], 1)
        self.assertEqual(result["source_counts"]["manual"]["new_to_baseline"], 1)
        intersection = result["intersections"][0]
        self.assertEqual((intersection["securities"],intersection["issuers"]), (0,1))
        self.assertEqual(discovery_audit(decisions, manifest, memberships=None, exclusions=None)["universe_basis"],
                         "universe_approximation")
