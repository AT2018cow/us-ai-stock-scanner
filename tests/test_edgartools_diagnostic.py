from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ai_value_scanner.fundamentals.edgartools_diagnostic import (
    classify_case,
    diagnose_accession,
    load_snapshot_cases,
    render_summary_markdown,
    summarize_results,
)


class _FakeStatement:
    def __init__(self, rows: list[dict[str, object]]):
        self._frame = pd.DataFrame(rows)

    def to_dataframe(self, include_unit: bool = False):
        return self._frame.copy()


class _FakeFacts:
    def __init__(self, rows: list[dict[str, object]]):
        self._frame = pd.DataFrame(rows)

    def to_dataframe(self):
        return self._frame.copy()


class _FakeStatements:
    def __init__(
        self,
        *,
        income: _FakeStatement | None = None,
        cash_flow: _FakeStatement | None = None,
        balance: _FakeStatement | None = None,
    ):
        self._income = income
        self._cash_flow = cash_flow
        self._balance = balance

    def income_statement(self):
        return self._income

    def cash_flow_statement(self):
        return self._cash_flow

    def balance_sheet(self):
        return self._balance


class _FakeXbrl:
    def __init__(self, statements: _FakeStatements, facts: _FakeFacts):
        self.statements = statements
        self.facts = facts


class _FakeFiling:
    form = "10-Q"
    filing_date = "2026-07-28"
    company = "Example Corp"

    def __init__(self, xbrl: _FakeXbrl | None):
        self._xbrl = xbrl

    def xbrl(self):
        return self._xbrl


def _gap_case(symbol: str = "EXLS") -> dict[str, object]:
    return {
        "symbol": symbol,
        "current_integrity_codes": ["latest_periodic_filing_not_covered"],
        "current_latest_periodic_accession": "0000000000-26-000001",
        "current_latest_periodic_form": "10-Q",
        "current_latest_periodic_filing_date": "2026-07-28",
    }


class TestEdgarToolsDiagnostic(unittest.TestCase):
    def test_diagnose_accession_finds_standardized_core_concepts(self) -> None:
        income = _FakeStatement(
            [
                {
                    "concept": "us-gaap_Revenues",
                    "standard_concept": "Revenue",
                    "label": "Revenue",
                    "unit": "USD",
                    "2026-06-30 (Q2)": 100.0,
                },
                {
                    "concept": "us-gaap_NetIncomeLoss",
                    "standard_concept": "NetIncome",
                    "label": "Net income",
                    "unit": "USD",
                    "2026-06-30 (Q2)": 20.0,
                },
            ]
        )
        cash = _FakeStatement(
            [
                {
                    "concept": "us-gaap_NetCashProvidedByUsedInOperatingActivities",
                    "standard_concept": "OperatingCashFlow",
                    "label": "Operating cash flow",
                    "unit": "USD",
                    "2026-06-30 (YTD)": 30.0,
                }
            ]
        )
        xbrl = _FakeXbrl(
            _FakeStatements(income=income, cash_flow=cash),
            _FakeFacts(
                [
                    {"concept": "us-gaap_Revenues", "unit": "USD"},
                    {"concept": "us-gaap_NetIncomeLoss", "unit": "USD"},
                ]
            ),
        )

        diagnostic = diagnose_accession(
            symbol="EXLS",
            accession="0000000000-26-000001",
            get_filing=lambda accession: _FakeFiling(xbrl),
        )

        self.assertTrue(diagnostic["edgartools_fetch_ok"])
        self.assertTrue(diagnostic["xbrl_available"])
        self.assertEqual(
            diagnostic["core_presence"],
            {
                "revenue": True,
                "net_income": True,
                "operating_cash_flow": True,
            },
        )
        self.assertEqual(diagnostic["core_taxonomies"], ["us-gaap"])
        self.assertFalse(diagnostic["custom_core_taxonomy_present"])
        self.assertEqual(
            classify_case(_gap_case(), diagnostic),
            "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND",
        )

    def test_custom_extension_standardized_to_revenue_is_visible(self) -> None:
        income = _FakeStatement(
            [
                {
                    "concept": "demo_CustomCloudRevenue",
                    "standard_concept": "Revenue",
                    "label": "Cloud revenue",
                    "unit": "USD",
                    "2026-06-30 (Q2)": 100.0,
                }
            ]
        )
        diagnostic = diagnose_accession(
            symbol="DEMO",
            accession="0000000000-26-000002",
            get_filing=lambda accession: _FakeFiling(
                _FakeXbrl(
                    _FakeStatements(income=income),
                    _FakeFacts(
                        [{"concept": "demo_CustomCloudRevenue", "unit": "USD"}]
                    ),
                )
            ),
        )
        self.assertTrue(diagnostic["core_presence"]["revenue"])
        self.assertTrue(diagnostic["custom_core_taxonomy_present"])
        self.assertEqual(
            classify_case(_gap_case("DEMO"), diagnostic),
            "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND_CUSTOM",
        )

    def test_no_xbrl_is_explicit(self) -> None:
        diagnostic = diagnose_accession(
            symbol="AAA",
            accession="0000000000-26-000003",
            get_filing=lambda accession: _FakeFiling(None),
        )
        self.assertFalse(diagnostic["xbrl_available"])
        self.assertEqual(
            classify_case(_gap_case("AAA"), diagnostic),
            "EDGARTOOLS_XBRL_UNAVAILABLE",
        )

    def test_non_usd_case_is_classified_without_production_semantics(self) -> None:
        case = {
            "symbol": "ASML",
            "current_integrity_codes": ["fundamental_currency_unsupported"],
        }
        diagnostic = {
            "edgartools_fetch_ok": True,
            "xbrl_available": True,
            "core_presence": {"revenue": True},
            "fact_units": ["EUR", "shares"],
        }
        self.assertEqual(
            classify_case(case, diagnostic),
            "CURRENT_PATH_NON_USD_EDGARTOOLS_NON_USD_ONLY",
        )

    def test_snapshot_selection_unions_explicit_and_flagged_cases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions = [
                {
                    "symbol": "EXLS",
                    "company_name": "EXLS",
                    "decision_date": "2026-10-09",
                    "quality": {
                        "grade": "UNRATED",
                        "confidence": 0.49,
                        "data_asof": "2026-04-28",
                        "missing": [
                            {"code": "latest_periodic_filing_not_covered"}
                        ],
                        "risks": [],
                    },
                    "provenance": {
                        "fundamental_latest_periodic_accession": "accn-exls",
                        "fundamental_latest_periodic_form": "10-Q",
                        "fundamental_latest_periodic_filing_date": "2026-07-28",
                    },
                },
                {
                    "symbol": "SAP",
                    "company_name": "SAP",
                    "decision_date": "2026-10-09",
                    "quality": {
                        "grade": "UNRATED",
                        "confidence": 0.1,
                        "data_asof": "2026-02-26",
                        "missing": [{"code": "revenue_yoy_missing"}],
                        "risks": [],
                    },
                    "provenance": {
                        "fundamental_latest_periodic_accession": "accn-sap",
                        "fundamental_latest_periodic_form": "20-F",
                        "fundamental_latest_periodic_filing_date": "2026-02-26",
                    },
                },
            ]
            (root / "decisions.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in decisions),
                encoding="utf-8",
            )
            cases, path = load_snapshot_cases(
                root,
                symbols=("SAP",),
                all_flagged=True,
            )
            self.assertEqual(path, root / "decisions.jsonl")
            self.assertEqual([case["symbol"] for case in cases], ["EXLS", "SAP"])

    def test_summary_reports_gap_resolution_rate(self) -> None:
        rows = [
            {
                **_gap_case("AAA"),
                "classification": "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND",
                "edgartools": {
                    "edgartools_fetch_ok": True,
                    "xbrl_available": True,
                    "custom_core_taxonomy_present": False,
                    "core_presence": {"revenue": True},
                    "core_taxonomies": ["us-gaap"],
                },
            },
            {
                **_gap_case("BBB"),
                "classification": "CURRENT_PATH_GAP_EDGARTOOLS_CORE_NOT_FOUND",
                "edgartools": {
                    "edgartools_fetch_ok": True,
                    "xbrl_available": True,
                    "custom_core_taxonomy_present": False,
                    "core_presence": {},
                    "core_taxonomies": [],
                },
            },
        ]
        summary = summarize_results(rows)
        self.assertEqual(summary["current_path_gap_cases"], 2)
        self.assertEqual(summary["current_path_gap_edgartools_core_found"], 1)
        self.assertEqual(summary["current_path_gap_core_found_rate"], 0.5)
        rendered = render_summary_markdown(rows, summary)
        self.assertIn("Filing-gap EdgarTools core-found rate: 0.5", rendered)
        self.assertIn("CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND", rendered)


if __name__ == "__main__":
    unittest.main()
