"""No-network tests for frozen historical SEC audit and fail-closed cases."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import pandas as pd

from scripts.mvp_v11_sec_pit_audit import (
    build_cases, header_accepted_utc, assess_filing_timing,
    inspect_case, _share_facts, make_case_lookup, MAX_CASES,
)


class FakeFiling:
    def __init__(self, accession, accepted, cik=46619, xbrl=None):
        self.accession_no = accession
        self.header = SimpleNamespace(acceptance_datetime=accepted)
        self.cik = cik
        self.filing_date = str(accepted)[:10] if accepted else None
        self.form = "10-K"
        self._xbrl = xbrl

    def xbrl(self):
        return self._xbrl


class TestMvpV11SecPitAudit(unittest.TestCase):
    def _case_inputs(self):
        dates = (
            "2023-12-29", "2024-12-31", "2025-08-29", "2025-12-31",
            "2023-01-31", "2024-01-31",
        )
        data = pd.DataFrame([
            {
                "signal_date": day, "symbol": symbol,
                "fundamental_data_asof": "2022-12-01",
                "shares_outstanding": 123,
                "shares_asof_end": "2022-12-01",
                "market_cap": 999, "fwd_ret_60": 1234567,
            }
            for day in dates
            for symbol in ("HEI", "AAA", "BBB", "CCC", "DDD")
        ])
        rank = pd.DataFrame([
            {
                "signal_date": day,
                "v1_top15": ";".join(["AAA"] * 7 + ["BBB"] * 7 + ["CCC"]),
            }
            for day in ("2023-01-31", "2024-01-31", "2024-12-31")
        ]).set_index("signal_date")
        return data, rank

    def test_fixed_hei_cases_first_and_controls_are_outcome_blind(self):
        data, ranking = self._case_inputs()
        cases = build_cases(data, ranking)
        self.assertEqual(len(cases), 13)
        self.assertEqual(cases.iloc[:4].symbol.tolist(), ["HEI"] * 4)
        self.assertEqual(cases.iloc[:4].case_type.tolist(), ["HEI_CLASS_SCOPE"] * 4)
        self.assertNotIn("fwd_ret_60", cases)
        self.assertTrue(cases.historical_cik.eq("").all())
        data.fwd_ret_60 = -9999
        pd.testing.assert_frame_equal(cases, build_cases(data, ranking))
        self.assertLessEqual(len(cases), MAX_CASES)

    def test_naive_sgml_header_is_eastern_not_utc(self):
        accepted = header_accepted_utc("2025-12-19 16:30:00")
        self.assertEqual(
            accepted, datetime(2025, 12, 19, 21, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(
            assess_filing_timing(accepted, "2025-12-31"),
            "FILING_PUBLIC_BEFORE_SIGNAL_DATE",
        )
        self.assertEqual(
            assess_filing_timing(accepted, "2025-12-19"),
            "UNVERIFIED_SAME_DAY_MARKET_CLOSE",
        )
        self.assertEqual(assess_filing_timing(None, "2025-12-31"),
                         "UNVERIFIED_HEADER_TIME")

    def test_later_filing_cannot_be_selected_and_never_claim_full_pit(self):
        case = {"signal_date": "2025-12-31", "symbol": "HEI",
                "case_type": "HEI_CLASS_SCOPE"}
        filings = [
            FakeFiling("0000046619-26-000001", "2026-01-01 10:00:00"),
            FakeFiling("0000046619-25-000082", "2025-12-19 16:30:00"),
        ]
        result = inspect_case(case, find_filings=lambda sym, day: filings,
                              inspect_shares=False)
        self.assertEqual(result["accession"], "0000046619-25-000082")
        self.assertEqual(result["filing_timing"],
                         "FILING_PUBLIC_BEFORE_SIGNAL_DATE")
        self.assertEqual(result["accepted_utc"], "2025-12-19T21:30:00+00:00")
        self.assertFalse(result["historical_cik_verified"])
        self.assertFalse(result["historical_scoring_accession_verified"])
        self.assertEqual(result["case_verdict"], "UNVERIFIED")

    def test_same_day_or_missing_header_fails_closed(self):
        case = {"signal_date": "2024-12-31", "symbol": "HEI",
                "case_type": "HEI_CLASS_SCOPE"}
        for accepted, expected in (
            ("2024-12-31 08:00:00", "UNVERIFIED_SAME_DAY_MARKET_CLOSE"),
            (None, "UNVERIFIED_HEADER_TIME"),
        ):
            result = inspect_case(
                case,
                find_filings=lambda sym, day: [
                    FakeFiling("0000046619-24-000111", accepted)
                ],
                inspect_shares=False,
            )
            self.assertEqual(result["filing_timing"], expected)
            self.assertEqual(result["case_verdict"], "UNVERIFIED")

    def test_xbrl_share_facts_without_class_dimension_are_unverified(self):
        query = SimpleNamespace(to_dataframe=lambda: pd.DataFrame([
            {
                "concept": "dei:EntityCommonStockSharesOutstanding",
                "numeric_value": 55000000,
                "unit_ref": "shares",
            }
        ]))
        xb = SimpleNamespace(
            facts=SimpleNamespace(
                query=lambda: SimpleNamespace(by_concept=lambda pattern: query)
            )
        )
        rows, status = _share_facts(
            FakeFiling("0000046619-25-000082", "2025-12-19", xbrl=xb)
        )
        self.assertEqual(status, "SHARE_FACTS_DIMENSIONS_UNVERIFIED")
        self.assertEqual(len(rows), 1)

    def test_ticker_lookup_is_cached_but_date_query_scoped(self):
        companies = []

        class FakeCompany:
            def get_filings(self, **kwargs):
                self.last_filter = kwargs
                return SimpleNamespace(head=lambda n: [])

        def factory(symbol):
            companies.append(symbol)
            return FakeCompany()

        lookup = make_case_lookup(factory)
        lookup("HEI", "2025-12-31")
        lookup("HEI", "2024-12-31")
        self.assertEqual(companies, ["HEI"])

    def test_bad_rows_fail_closed(self):
        data, rank = self._case_inputs()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_cases(pd.concat([data, data.head(1)]), rank)
        with self.assertRaisesRegex(ValueError, "case absent"):
            build_cases(data[data.symbol != "HEI"], rank)


if __name__ == "__main__":
    unittest.main()
