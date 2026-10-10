from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import ai_value_scanner.scanner as scanner
from ai_value_scanner.decision import QualityGrade, build_stock_decisions
from ai_value_scanner.decision.quality import build_company_quality_v1


def _strong_metrics() -> dict[str, object]:
    return {
        "net_margin": 0.25,
        "free_cash_flow": 100.0,
        "ocf_to_net_income": 1.20,
        "accrual_ratio": 0.03,
        "revenue_yoy": 0.20,
        "adjusted_net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.20,
        "net_debt_to_ebitda": 0.0,
        "interest_coverage": 10.0,
        "current_ratio": 2.0,
        "shares_yoy": 0.0,
        "fcf_yield": 0.06,
        "ps_hist_percentile": 0.20,
        "pe_hist_percentile": 0.30,
        "receivables_growth_gap": 0.0,
        "inventory_growth_gap": 0.0,
        "shares_stale": False,
    }


def _ready_entry() -> dict[str, object]:
    return {
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.03,
        "days_below_sma200": 0,
        "return_20d": 0.05,
        "return_60d": 0.10,
        "drawdown_from_52w_high": 0.08,
        "range_position_52w": 0.82,
        "relative_strength_60d_qqq": 0.04,
        "volatility_60d": 0.35,
        "regime": "up",
        "benchmark_trend_ok": True,
        "market_asof": "2026-10-09",
    }


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _make_sec_client(tmp: Path) -> tuple[scanner.SecClient, list[str]]:
    client = scanner.SecClient.__new__(scanner.SecClient)
    client.cache_dir = tmp
    client.timeout_sec = 5
    client.headers = {"User-Agent": "test"}
    client.submissions_ttl_sec = 0
    client.monitor = None
    requested: list[str] = []

    def fake_get(url: str):
        requested.append(url)
        return _FakeResp(200, {"facts": {"unexpected": True}})

    client._get = fake_get  # type: ignore[assignment]
    return client, requested


class TestPeriodicFilingSemantics(unittest.TestCase):
    def test_latest_periodic_filing_ignores_nonperiodic_and_normalizes_amendment(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["8-K", "10-Q/A", "10-Q"],
                    "filingDate": ["2026-10-09", "2026-08-03", "2026-05-01"],
                    "accessionNumber": ["8k", "q2a", "q1"],
                }
            }
        }
        self.assertEqual(
            scanner.latest_periodic_filing(submissions),
            {"form": "10-Q", "filed": "2026-08-03", "accession": "q2a"},
        )

    def test_periodic_filing_diagnostic_is_separate_from_conservative_cache_refresh(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["8-K", "10-Q"],
                    "filingDate": ["2026-10-09", "2026-08-01"],
                    "accessionNumber": ["newer-8k", "periodic-q2"],
                }
            }
        }
        self.assertEqual(
            scanner.latest_periodic_filing(submissions),
            {"form": "10-Q", "filed": "2026-08-01", "accession": "periodic-q2"},
        )

    def test_latest_periodic_coverage_is_accession_specific(self) -> None:
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "end": "2026-03-31",
                                    "filed": "2026-05-01",
                                    "form": "10-Q",
                                    "accn": "q1",
                                }
                            ]
                        }
                    }
                }
            }
        }
        self.assertEqual(
            scanner.relevant_fundamental_fact_accessions(companyfacts),
            {"q1"},
        )
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-Q"],
                    "filingDate": ["2026-08-01"],
                    "accessionNumber": ["q2"],
                }
            }
        }
        latest = scanner.latest_periodic_filing(submissions)
        assert latest is not None
        self.assertNotIn(
            latest["accession"],
            scanner.relevant_fundamental_fact_accessions(companyfacts),
        )

    def test_noncore_fact_does_not_false_positive_latest_filing_coverage(self) -> None:
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "InventoryNet": {
                        "units": {
                            "USD": [
                                {
                                    "val": 10,
                                    "end": "2026-06-30",
                                    "filed": "2026-08-01",
                                    "form": "10-Q",
                                    "accn": "q2",
                                }
                            ]
                        }
                    }
                }
            }
        }
        self.assertEqual(
            scanner.relevant_fundamental_fact_accessions(companyfacts),
            set(),
        )


class TestFundamentalCurrencySafety(unittest.TestCase):
    def test_non_usd_core_facts_are_explicitly_unsupported(self) -> None:
        companyfacts = {
            "facts": {
                "ifrs-full": {
                    "Revenue": {
                        "units": {
                            "EUR": [
                                {
                                    "val": 100,
                                    "end": "2025-12-31",
                                    "filed": "2026-02-01",
                                    "form": "20-F",
                                }
                            ]
                        }
                    },
                    "ProfitLoss": {
                        "units": {
                            "EUR": [
                                {
                                    "val": 20,
                                    "end": "2025-12-31",
                                    "filed": "2026-02-01",
                                    "form": "20-F",
                                }
                            ]
                        }
                    },
                }
            }
        }
        self.assertEqual(
            scanner.fundamental_currency_support(companyfacts),
            ("EUR", False),
        )

    def test_usd_core_facts_remain_supported(self) -> None:
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "end": "2026-06-30",
                                    "filed": "2026-08-01",
                                    "form": "10-Q",
                                }
                            ]
                        }
                    }
                }
            }
        }
        self.assertEqual(
            scanner.fundamental_currency_support(companyfacts),
            ("USD", True),
        )

    def test_quality_fails_closed_when_latest_filing_is_not_covered(self) -> None:
        metrics = _strong_metrics()
        metrics.update(
            {
                "fundamental_facts_cover_latest_periodic": False,
                "fundamental_latest_periodic_filing_date": "2026-08-01",
            }
        )
        decision = build_company_quality_v1(
            metrics,
            decision_date="2026-10-09",
            data_asof="2026-05-01",
        )
        self.assertIs(decision.grade, QualityGrade.UNRATED)
        self.assertLess(decision.confidence, 0.50)
        self.assertTrue(
            any(
                item.code == "latest_periodic_filing_not_covered"
                for item in decision.missing
            )
        )
        self.assertFalse(
            any(item.code == "fundamental_data_fresh" for item in decision.positives)
        )

    def test_quality_fails_closed_for_non_usd_monetary_facts(self) -> None:
        metrics = _strong_metrics()
        metrics.update(
            {
                "fundamental_currency_supported": False,
                "fundamental_reporting_currency": "TWD",
            }
        )
        decision = build_company_quality_v1(
            metrics,
            decision_date="2026-10-09",
            data_asof="2026-04-16",
        )
        self.assertIs(decision.grade, QualityGrade.UNRATED)
        self.assertTrue(
            any(
                item.code == "fundamental_currency_unsupported"
                for item in decision.missing
            )
        )


class TestMarketDecisionDate(unittest.TestCase):
    def test_benchmark_market_session_wins_over_wall_clock_or_symbol_dates(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "market_asof": ["2026-10-08", "2026-10-09"],
            }
        )
        self.assertEqual(
            scanner.resolve_market_decision_date(
                frame,
                benchmark_market_asof="2026-10-09",
            ),
            "2026-10-09",
        )

    def test_symbol_market_date_is_fallback_and_missing_market_data_raises(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "market_asof": ["2026-10-08", "2026-10-09"],
            }
        )
        self.assertEqual(
            scanner.resolve_market_decision_date(frame),
            "2026-10-09",
        )
        with self.assertRaisesRegex(ValueError, "decision_date"):
            scanner.resolve_market_decision_date(pd.DataFrame({"symbol": ["AAA"]}))

    def test_integrated_decision_keeps_fundamental_integrity_provenance(self) -> None:
        row = {
            **_strong_metrics(),
            **_ready_entry(),
            "symbol": "AAA",
            "company_name": "AAA Corp",
            "fundamental_data_asof": "2026-08-01",
            "fundamental_latest_periodic_filing_date": "2026-08-01",
            "fundamental_latest_periodic_form": "10-Q",
            "fundamental_latest_periodic_accession": "q2",
            "fundamental_facts_cover_latest_periodic": True,
            "fundamental_reporting_currency": "USD",
            "fundamental_currency_supported": True,
        }
        decision = build_stock_decisions(
            pd.DataFrame([row]),
            decision_date="2026-10-09",
            generated_at_utc="2026-10-10T12:00:00+00:00",
        )[0]
        self.assertEqual(
            decision.provenance["fundamental_latest_periodic_filing_date"],
            "2026-08-01",
        )
        self.assertIs(
            decision.provenance["fundamental_facts_cover_latest_periodic"],
            True,
        )
        self.assertIs(
            decision.provenance["fundamental_currency_supported"],
            True,
        )


if __name__ == "__main__":
    unittest.main()
