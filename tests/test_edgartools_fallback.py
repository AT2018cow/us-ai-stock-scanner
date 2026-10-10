from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import ai_value_scanner.scanner as scanner
from ai_value_scanner.config import ScanConfig
from ai_value_scanner.fundamentals.edgartools_fallback import (
    EdgarToolsFallbackResult,
    build_usd_10q_companyfacts_patch,
    fetch_usd_10q_companyfacts_patch,
    merge_companyfacts_patch,
    remove_companyfacts_patch,
)


class _FakeFactQuery:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame
        self.dimension_filter = object()

    def by_dimension(self, value):
        self.dimension_filter = value
        return self

    def to_dataframe(self):
        frame = self._frame.copy()
        if self.dimension_filter is None and "dimensions" in frame.columns:
            mask = frame["dimensions"].map(
                lambda value: value is None
                or value == {}
                or value == []
            )
            frame = frame[mask]
        return frame


class _FakeFacts:
    def __init__(self, rows: list[dict[str, object]]):
        self._frame = pd.DataFrame(rows)

    def query(self):
        return _FakeFactQuery(self._frame)


class _FakeXbrl:
    def __init__(self, rows: list[dict[str, object]]):
        self.facts = _FakeFacts(rows)


def _row(
    concept: str,
    value: float,
    *,
    start: str | None,
    end: str | None,
    currency: str | None = "USD",
    unit_ref: str | None = None,
    dimensions: object | None = None,
    period_instant: str | None = None,
) -> dict[str, object]:
    resolved_unit_ref = unit_ref
    if resolved_unit_ref is None and currency is not None:
        resolved_unit_ref = currency
    return {
        "concept": concept,
        "value": str(value),
        "numeric_value": value,
        "period_start": start,
        "period_end": end,
        "period_instant": period_instant,
        "unit_ref": resolved_unit_ref,
        "currency": currency,
        "dimensions": dimensions,
    }


def _latest_rows(
    *,
    currency: str | None = "USD",
    unit_ref: str | None = None,
    include_segment_noise: bool = True,
) -> list[dict[str, object]]:
    rows = [
        _row(
            "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
            140.0,
            start="2026-04-01",
            end="2026-06-30",
            currency=currency,
            unit_ref=unit_ref,
        ),
        _row(
            "us-gaap_NetIncomeLoss",
            28.0,
            start="2026-04-01",
            end="2026-06-30",
            currency=currency,
            unit_ref=unit_ref,
        ),
        _row(
            "us-gaap_NetCashProvidedByUsedInOperatingActivities",
            75.0,
            start="2026-01-01",
            end="2026-06-30",
            currency=currency,
            unit_ref=unit_ref,
        ),
    ]
    if include_segment_noise:
        rows.append(
            _row(
                "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
                9999.0,
                start="2026-04-01",
                end="2026-06-30",
                currency=currency,
                unit_ref=unit_ref,
                dimensions={"segment": "North America"},
            )
        )
    return rows

def _entry(start: str, end: str, value: float, filed: str, accn: str, form: str = "10-Q") -> dict[str, object]:
    return {
        "start": start,
        "end": end,
        "val": value,
        "filed": filed,
        "accn": accn,
        "form": form,
    }


def _old_companyfacts(*, enough_history: bool = True) -> dict:
    revenue = [
        _entry("2025-07-01", "2025-09-30", 100.0, "2025-10-30", "q3-25"),
        _entry("2025-10-01", "2025-12-31", 110.0, "2026-02-20", "q4-25", "10-K"),
        _entry("2026-01-01", "2026-03-31", 120.0, "2026-04-29", "q1-26"),
    ]
    net_income = [
        _entry("2025-07-01", "2025-09-30", 20.0, "2025-10-30", "q3-25"),
        _entry("2025-10-01", "2025-12-31", 22.0, "2026-02-20", "q4-25", "10-K"),
        _entry("2026-01-01", "2026-03-31", 24.0, "2026-04-29", "q1-26"),
    ]
    ocf = [
        _entry("2025-07-01", "2025-09-30", 25.0, "2025-10-30", "q3-25"),
        _entry("2025-10-01", "2025-12-31", 30.0, "2026-02-20", "q4-25", "10-K"),
        _entry("2026-01-01", "2026-03-31", 35.0, "2026-04-29", "q1-26"),
    ]
    if not enough_history:
        revenue = revenue[-1:]
        net_income = net_income[-1:]
        ocf = ocf[-1:]
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": revenue}
                },
                "NetIncomeLoss": {"units": {"USD": net_income}},
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": ocf}
                },
            }
        }
    }


def _core_groups() -> dict[str, tuple[str, ...]]:
    return {
        "revenue": tuple(scanner.REVENUE_TAGS),
        "net_income": tuple(scanner.NET_INCOME_TAGS),
        "operating_cash_flow": tuple(scanner.OPERATING_CASH_FLOW_TAGS),
    }


class TestEdgarToolsUsd10QFallback(unittest.TestCase):
    def test_build_patch_accepts_consolidated_standard_usd_and_drops_segment_rows(self) -> None:
        result = build_usd_10q_companyfacts_patch(
            _FakeXbrl(_latest_rows()),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )

        self.assertTrue(result.used)
        self.assertEqual(result.reporting_currency, "USD")
        patch_facts = result.patch["facts"]["us-gaap"]
        revenue_rows = patch_facts[
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ]["units"]["USD"]
        self.assertEqual(len(revenue_rows), 1)
        self.assertEqual(revenue_rows[0]["val"], 140.0)
        self.assertEqual(revenue_rows[0]["accn"], "q2-26")
        self.assertEqual(revenue_rows[0]["start"], "2026-04-01")
        self.assertEqual(revenue_rows[0]["end"], "2026-06-30")

    def test_fixture_matches_edgartools_5611_factquery_schema(self) -> None:
        row = _latest_rows(include_segment_noise=False)[0]
        self.assertNotIn("unit", row)
        self.assertTrue(
            {
                "concept",
                "value",
                "numeric_value",
                "period_start",
                "period_end",
                "period_instant",
                "unit_ref",
                "currency",
            }.issubset(row)
        )

    def test_unit_ref_is_used_only_for_supported_nonmonetary_units(self) -> None:
        rows = _latest_rows()
        rows.append(
            _row(
                "us-gaap_EntityCommonStockSharesOutstanding",
                123.0,
                start=None,
                end=None,
                currency=None,
                unit_ref="shares",
                period_instant="2026-06-30",
            )
        )
        result = build_usd_10q_companyfacts_patch(
            _FakeXbrl(rows),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )

        self.assertTrue(result.used)
        share_rows = result.patch["facts"]["us-gaap"][
            "EntityCommonStockSharesOutstanding"
        ]["units"]["shares"]
        self.assertEqual(len(share_rows), 1)
        self.assertEqual(share_rows[0]["end"], "2026-06-30")

    def test_missing_undimensioned_query_contract_fails_closed(self) -> None:
        class UnsafeFacts:
            def to_dataframe(self):
                return pd.DataFrame(_latest_rows())

        class UnsafeXbrl:
            facts = UnsafeFacts()

        result = build_usd_10q_companyfacts_patch(
            UnsafeXbrl(),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )
        self.assertFalse(result.used)
        self.assertEqual(result.status, "facts_unavailable")

    def test_non_usd_core_filing_is_rejected_using_currency_not_unit_ref(self) -> None:
        for currency in ("EUR", "CAD", "TWD"):
            with self.subTest(currency=currency):
                result = build_usd_10q_companyfacts_patch(
                    _FakeXbrl(_latest_rows(currency=currency, unit_ref="USD")),
                    accession="q2-26",
                    filed="2026-07-29",
                    form="10-Q",
                    allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
                    core_tag_groups=_core_groups(),
                )
                self.assertFalse(result.used)
                self.assertEqual(result.status, "non_usd_core")
                self.assertEqual(result.reporting_currency, currency)

    def test_missing_or_ambiguous_core_currency_fails_closed(self) -> None:
        cases = (
            (None, "USD"),
            ("USD/EUR", "USD"),
            ("", "arbitrary_USD_unit"),
        )
        for currency, unit_ref in cases:
            with self.subTest(currency=currency, unit_ref=unit_ref):
                result = build_usd_10q_companyfacts_patch(
                    _FakeXbrl(
                        _latest_rows(currency=currency, unit_ref=unit_ref)
                    ),
                    accession="q2-26",
                    filed="2026-07-29",
                    form="10-Q",
                    allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
                    core_tag_groups=_core_groups(),
                )
                self.assertFalse(result.used)
                self.assertEqual(result.status, "core_facts_incomplete")
                self.assertIsNone(result.reporting_currency)

    def test_non_10q_is_ineligible_without_fetching(self) -> None:
        called = False

        def resolver(accession: str):
            nonlocal called
            called = True
            raise AssertionError("must not fetch")

        result = fetch_usd_10q_companyfacts_patch(
            periodic_filing={
                "form": "20-F",
                "filed": "2026-04-16",
                "accession": "foreign",
            },
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
            get_filing=resolver,
        )
        self.assertEqual(result.status, "ineligible_form")
        self.assertFalse(called)

    def test_10qa_is_intentionally_fail_closed(self) -> None:
        called = False

        def resolver(accession: str):
            nonlocal called
            called = True
            raise AssertionError("10-Q/A must not fetch")

        result = fetch_usd_10q_companyfacts_patch(
            periodic_filing={
                "form": "10-Q/A",
                "filed": "2026-07-30",
                "accession": "q2a-26",
            },
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
            get_filing=resolver,
        )
        self.assertEqual(result.status, "ineligible_form")
        self.assertFalse(called)

    def test_edgartools_10qa_for_expected_10q_is_filing_mismatch(self) -> None:
        class AmendedFiling:
            form = "10-Q/A"

            def xbrl(self):
                raise AssertionError("mismatched amended filing must not parse XBRL")

        result = fetch_usd_10q_companyfacts_patch(
            periodic_filing={
                "form": "10-Q",
                "filed": "2026-07-29",
                "accession": "q2-26",
            },
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
            get_filing=lambda accession: AmendedFiling(),
        )
        self.assertEqual(result.status, "filing_mismatch")
        self.assertEqual(result.form, "10-Q/A")

    def test_merge_then_rollback_is_exact_and_idempotent(self) -> None:
        facts = _old_companyfacts()
        original = copy.deepcopy(facts)
        result = build_usd_10q_companyfacts_patch(
            _FakeXbrl(_latest_rows()),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )
        added = merge_companyfacts_patch(facts, result.patch)
        self.assertGreater(added, 0)
        self.assertEqual(merge_companyfacts_patch(facts, result.patch), 0)
        removed = remove_companyfacts_patch(facts, result.patch)
        self.assertEqual(removed, added)
        self.assertEqual(facts, original)

    def test_patch_flows_through_existing_ttm_reconstruction(self) -> None:
        facts = _old_companyfacts()
        result = build_usd_10q_companyfacts_patch(
            _FakeXbrl(_latest_rows()),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )
        merge_companyfacts_patch(facts, result.patch)

        self.assertTrue(
            scanner.latest_rolling_ttm_uses_accession(
                facts, scanner.REVENUE_TAGS, "USD", "q2-26"
            )
        )
        self.assertTrue(
            scanner.latest_rolling_ttm_uses_accession(
                facts, scanner.NET_INCOME_TAGS, "USD", "q2-26"
            )
        )
        self.assertTrue(
            scanner.latest_rolling_ttm_uses_accession(
                facts, scanner.OPERATING_CASH_FLOW_TAGS, "USD", "q2-26"
            )
        )
        revenue, _ = scanner.pick_latest_and_prev_ttm(
            facts, scanner.REVENUE_TAGS, "USD"
        )
        net_income, _ = scanner.pick_latest_and_prev_ttm(
            facts, scanner.NET_INCOME_TAGS, "USD"
        )
        ocf, _ = scanner.pick_latest_and_prev_ttm(
            facts, scanner.OPERATING_CASH_FLOW_TAGS, "USD"
        )
        self.assertEqual(revenue, 470.0)
        self.assertEqual(net_income, 94.0)
        # H1 OCF 75 with Q1 35 reconstructs Q2=40; TTM = 25+30+35+40.
        self.assertEqual(ocf, 130.0)

    def test_insufficient_history_cannot_clear_integrity_blocker(self) -> None:
        facts = _old_companyfacts(enough_history=False)
        result = build_usd_10q_companyfacts_patch(
            _FakeXbrl(_latest_rows()),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )
        merge_companyfacts_patch(facts, result.patch)
        self.assertFalse(
            scanner.latest_rolling_ttm_uses_accession(
                facts, scanner.REVENUE_TAGS, "USD", "q2-26"
            )
        )


class _FakeSec:
    def __init__(self, facts: dict, submissions: dict):
        self._facts = facts
        self._submissions = submissions

    def get_submissions(self, cik: str) -> dict:
        return self._submissions

    def get_companyfacts(self, cik: str) -> dict:
        return copy.deepcopy(self._facts)


class TestLoadOneFundamentalFallbackIntegration(unittest.TestCase):
    def _submissions(self) -> dict:
        return {
            "sic": "7372",
            "sicDescription": "Services",
            "filings": {
                "recent": {
                    "form": ["10-Q"],
                    "filingDate": ["2026-07-29"],
                    "accessionNumber": ["q2-26"],
                }
            },
        }

    def _fallback_result(self) -> EdgarToolsFallbackResult:
        return build_usd_10q_companyfacts_patch(
            _FakeXbrl(_latest_rows()),
            accession="q2-26",
            filed="2026-07-29",
            form="10-Q",
            allowed_tags=scanner.EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=_core_groups(),
        )

    def test_load_uses_fallback_only_when_latest_ttm_becomes_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = ScanConfig(
                cache_dir=td,
                sec_cache_ttl_submissions_sec=0,
                use_ttm_metrics=True,
            )
            sec = _FakeSec(_old_companyfacts(), self._submissions())
            with patch.object(
                scanner,
                "fetch_usd_10q_companyfacts_patch",
                return_value=self._fallback_result(),
            ):
                result = scanner.load_one_fundamental(
                    sec, "EXLS", "0000000001", cfg
                )

        self.assertTrue(result["fundamental_edgartools_fallback_used"])
        self.assertEqual(
            result["fundamental_source"],
            "companyfacts+edgartools_exact_10q",
        )
        self.assertTrue(result["fundamental_facts_cover_latest_periodic"])
        self.assertEqual(result["fundamental_data_asof"], "2026-07-29")
        self.assertEqual(result["fundamental_reporting_currency"], "USD")
        self.assertTrue(result["fundamental_currency_supported"])
        self.assertEqual(result["revenue"], 470.0)
        self.assertEqual(result["net_income"], 94.0)
        self.assertEqual(result["operating_cash_flow"], 130.0)

    def test_normal_companyfacts_path_does_not_invoke_fallback(self) -> None:
        facts = _old_companyfacts()
        fallback = self._fallback_result()
        merge_companyfacts_patch(facts, fallback.patch)

        with tempfile.TemporaryDirectory() as td:
            cfg = ScanConfig(
                cache_dir=td,
                sec_cache_ttl_submissions_sec=0,
                use_ttm_metrics=True,
            )
            sec = _FakeSec(facts, self._submissions())
            with patch.object(
                scanner,
                "fetch_usd_10q_companyfacts_patch",
                side_effect=AssertionError(
                    "covered Company Facts must not invoke EdgarTools fallback"
                ),
            ):
                result = scanner.load_one_fundamental(
                    sec, "EXLS", "0000000001", cfg
                )

        self.assertFalse(result["fundamental_edgartools_fallback_used"])
        self.assertEqual(result["fundamental_source"], "companyfacts")
        self.assertTrue(result["fundamental_facts_cover_latest_periodic"])

    def test_rejected_patch_preserves_preexisting_identical_fact(self) -> None:
        original = _old_companyfacts(enough_history=False)
        # A latest-accession revenue row can already exist in the raw source
        # while OCF history is insufficient to construct current TTM.
        original["facts"]["us-gaap"][
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ]["units"]["USD"].append(
            _entry("2026-04-01", "2026-06-30", 140.0, "2026-07-29", "q2-26")
        )
        pristine = copy.deepcopy(original)
        sec = _FakeSec(original, self._submissions())
        with tempfile.TemporaryDirectory() as td:
            cfg = ScanConfig(cache_dir=td, use_ttm_metrics=True)
            with patch.object(
                scanner,
                "fetch_usd_10q_companyfacts_patch",
                return_value=self._fallback_result(),
            ):
                scanner.load_one_fundamental(sec, "EXLS", "0000000001", cfg)
        self.assertEqual(original, pristine)

    def test_load_rolls_back_when_latest_ttm_cannot_be_built(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = ScanConfig(
                cache_dir=td,
                sec_cache_ttl_submissions_sec=0,
                use_ttm_metrics=True,
            )
            sec = _FakeSec(
                _old_companyfacts(enough_history=False),
                self._submissions(),
            )
            with patch.object(
                scanner,
                "fetch_usd_10q_companyfacts_patch",
                return_value=self._fallback_result(),
            ):
                result = scanner.load_one_fundamental(
                    sec, "EXLS", "0000000001", cfg
                )

        self.assertFalse(result["fundamental_edgartools_fallback_used"])
        self.assertEqual(
            result["fundamental_edgartools_fallback_status"],
            "ttm_not_fresh",
        )
        self.assertFalse(result["fundamental_facts_cover_latest_periodic"])
        self.assertEqual(result["fundamental_data_asof"], "2026-04-29")


if __name__ == "__main__":
    unittest.main()
