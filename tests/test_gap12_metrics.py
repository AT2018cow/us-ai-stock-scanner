from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from ai_value_scanner.scanner import (
    ScanConfig,
    ai_backlog_signal_from_companyfacts,
    ai_disclosure_score_from_submissions,
    ai_etf_consensus_score,
    ai_market_link_score,
    compute_price_history_percentile,
    fundamental_quality_score_from_metrics,
    hard_filter_metric_enabled,
    load_one_fundamental,
    resolve_channel_profile,
)


def _entry(end: str, val: float, form: str = "10-Q", filed: str = "2026-02-15") -> dict[str, object]:
    return {"end": end, "val": val, "form": form, "filed": filed}


def _build_companyfacts_ttm_full() -> dict[str, object]:
    # Latest 8 quarters, newest first by end date after scanner sorting.
    q_end = [
        "2025-12-31",
        "2025-09-30",
        "2025-06-30",
        "2025-03-31",
        "2024-12-31",
        "2024-09-30",
        "2024-06-30",
        "2024-03-31",
    ]

    def q_vals(values: list[float], form: str = "10-Q") -> list[dict[str, object]]:
        return [_entry(end=e, val=v, form=form, filed="2026-02-15") for e, v in zip(q_end, values)]

    us_gaap = {
        "Revenues": {"units": {"USD": q_vals([130, 120, 110, 100, 90, 80, 70, 60])}},
        "NetIncomeLoss": {"units": {"USD": q_vals([46, 44, 42, 40, 34, 32, 30, 28])}},
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {"USD": q_vals([58, 55, 52, 45, 45, 42, 40, 38])}
        },
        "CapitalExpenditures": {"units": {"USD": q_vals([-18, -17, -17, -16, -14, -13, -12, -11])}},
        "OperatingIncomeLoss": {"units": {"USD": q_vals([70, 65, 60, 55, 45, 40, 35, 30])}},
        "InterestExpense": {"units": {"USD": q_vals([-10, -10, -10, -10, -8, -8, -8, -8])}},
        "DepreciationAndAmortization": {"units": {"USD": q_vals([15, 15, 14, 14, 12, 12, 11, 11])}},
        "BusinessCombinationAcquisitionRelatedCosts": {
            "units": {"USD": q_vals([8, 0, 0, 0, 0, 0, 0, 0])}
        },
        "GainLossOnDispositionOfAssets": {"units": {"USD": q_vals([2, 0, 0, 0, 0, 0, 0, 0])}},
        "EntityCommonStockSharesOutstanding": {
            "units": {
                "shares": [
                    _entry("2025-12-31", 100, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 90, "10-K", "2025-02-20"),
                ]
            }
        },
        "CashAndCashEquivalentsAtCarryingValue": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 300, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 280, "10-K", "2025-02-20"),
                ]
            }
        },
        "LongTermDebtNoncurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 400, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 380, "10-K", "2025-02-20"),
                ]
            }
        },
        "DebtCurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 200, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 180, "10-K", "2025-02-20"),
                ]
            }
        },
        "AssetsCurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 1000, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 900, "10-K", "2025-02-20"),
                ]
            }
        },
        "LiabilitiesCurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 500, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 450, "10-K", "2025-02-20"),
                ]
            }
        },
        "AccountsReceivableNetCurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 300, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 200, "10-K", "2025-02-20"),
                ]
            }
        },
        "InventoryNet": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 220, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 150, "10-K", "2025-02-20"),
                ]
            }
        },
    }
    return {"facts": {"us-gaap": us_gaap}}


def _build_companyfacts_annual_for_fallback() -> dict[str, object]:
    us_gaap = {
        "Revenues": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 100, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 80, "10-K", "2025-02-20"),
                ]
            }
        },
        "NetIncomeLoss": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 20, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 16, "10-K", "2025-02-20"),
                ]
            }
        },
        "EntityCommonStockSharesOutstanding": {
            "units": {
                "shares": [
                    _entry("2025-12-31", 10, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 9, "10-K", "2025-02-20"),
                ]
            }
        },
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 24, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 18, "10-K", "2025-02-20"),
                ]
            }
        },
        "CapitalExpenditures": {
            "units": {
                "USD": [
                    _entry("2025-12-31", -8, "10-K", "2026-02-20"),
                    _entry("2024-12-31", -7, "10-K", "2025-02-20"),
                ]
            }
        },
        "OperatingIncomeLoss": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 26, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 20, "10-K", "2025-02-20"),
                ]
            }
        },
        "BusinessCombinationAcquisitionRelatedCosts": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 40, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 0, "10-K", "2025-02-20"),
                ]
            }
        },
        "GainLossOnDispositionOfAssets": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 40, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 0, "10-K", "2025-02-20"),
                ]
            }
        },
    }
    return {"facts": {"us-gaap": us_gaap}}


def _build_companyfacts_for_low_coverage_inference() -> dict[str, object]:
    us_gaap = {
        "Revenues": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 100, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 80, "10-K", "2025-02-20"),
                ]
            }
        },
        "NetIncomeLoss": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 20, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 15, "10-K", "2025-02-20"),
                ]
            }
        },
        "OperatingIncomeLoss": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 30, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 24, "10-K", "2025-02-20"),
                ]
            }
        },
        "EntityCommonStockSharesOutstanding": {
            "units": {
                "shares": [
                    _entry("2025-12-31", 10, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 9, "10-K", "2025-02-20"),
                ]
            }
        },
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 24, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 19, "10-K", "2025-02-20"),
                ]
            }
        },
        "CapitalExpenditures": {
            "units": {
                "USD": [
                    _entry("2025-12-31", -8, "10-K", "2026-02-20"),
                    _entry("2024-12-31", -6, "10-K", "2025-02-20"),
                ]
            }
        },
        "CashAndCashEquivalentsAtCarryingValue": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 100, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 80, "10-K", "2025-02-20"),
                ]
            }
        },
        "LongTermDebtNoncurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 500, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 450, "10-K", "2025-02-20"),
                ]
            }
        },
        "AssetsCurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 1000, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 900, "10-K", "2025-02-20"),
                ]
            }
        },
        "LiabilitiesCurrent": {
            "units": {
                "USD": [
                    _entry("2025-12-31", 400, "10-K", "2026-02-20"),
                    _entry("2024-12-31", 380, "10-K", "2025-02-20"),
                ]
            }
        },
    }
    return {"facts": {"us-gaap": us_gaap}}


class _FakeSecClient:
    def __init__(self, submissions: dict[str, object], companyfacts: dict[str, object]) -> None:
        self._submissions = submissions
        self._facts = companyfacts

    def get_submissions(self, cik: str) -> dict[str, object]:
        return self._submissions

    def get_companyfacts(self, cik: str) -> dict[str, object]:
        return self._facts


class Gap12MetricTests(unittest.TestCase):
    def test_load_one_fundamental_computes_new_metrics(self) -> None:
        sec = _FakeSecClient(
            submissions={"sic": "3571", "sicDescription": "Electronic Computers"},
            companyfacts=_build_companyfacts_ttm_full(),
        )
        cfg = ScanConfig(use_ttm_metrics=True, nonrecurring_addback_revenue_cap=0.25)
        out = load_one_fundamental(sec, "TEST", "0000000001", cfg)

        self.assertEqual(out["revenue_form"], "ttm")
        self.assertAlmostEqual(out["revenue"], 460.0, places=6)
        self.assertAlmostEqual(out["adjusted_net_income"], 178.0, places=6)
        self.assertAlmostEqual(out["adjusted_ebit"], 256.0, places=6)
        self.assertAlmostEqual(out["adjusted_ebitda"], 320.0, places=6)
        self.assertAlmostEqual(out["interest_coverage"], 6.4, places=6)
        self.assertAlmostEqual(out["net_debt_to_ebitda"], 300.0 / 320.0, places=6)
        self.assertAlmostEqual(out["current_ratio"], 2.0, places=6)
        # 口径确认: current_debt_ratio = current_debt / current_assets
        self.assertAlmostEqual(out["current_debt_ratio"], 0.2, places=6)
        self.assertAlmostEqual(out["ocf_to_net_income"], 210.0 / 178.0, places=6)
        self.assertAlmostEqual(out["accrual_ratio"], (178.0 - 210.0) / 1000.0, places=6)
        self.assertAlmostEqual(out["receivables_growth_gap"], (300.0 / 200.0 - 1.0) - (460.0 / 300.0 - 1.0), places=6)
        self.assertAlmostEqual(out["inventory_growth_gap"], (220.0 / 150.0 - 1.0) - (460.0 / 300.0 - 1.0), places=6)
        self.assertAlmostEqual(out["shares_yoy"], 100.0 / 90.0 - 1.0, places=6)
        self.assertEqual(out["nonrecurring_expense_addback"], 8.0)
        self.assertEqual(out["nonrecurring_gain_subtraction"], 2.0)

        expected_qs = fundamental_quality_score_from_metrics(
            net_debt_to_ebitda=out["net_debt_to_ebitda"],
            interest_coverage=out["interest_coverage"],
            current_ratio=out["current_ratio"],
            ocf_to_net_income=out["ocf_to_net_income"],
            accrual_ratio=out["accrual_ratio"],
        )
        self.assertAlmostEqual(float(out["fundamental_quality_score"]), float(expected_qs), places=6)

    def test_addback_and_gain_are_capped_by_revenue_ratio(self) -> None:
        sec = _FakeSecClient(
            submissions={"sic": "7372", "sicDescription": "Prepackaged Software"},
            companyfacts=_build_companyfacts_annual_for_fallback(),
        )
        cfg = ScanConfig(use_ttm_metrics=True, nonrecurring_addback_revenue_cap=0.25)
        out = load_one_fundamental(sec, "CAP", "0000000002", cfg)

        # Revenue=100 => each non-recurring bucket capped at 25.
        self.assertAlmostEqual(out["nonrecurring_expense_addback"], 25.0, places=6)
        self.assertAlmostEqual(out["nonrecurring_gain_subtraction"], 25.0, places=6)
        self.assertAlmostEqual(out["adjusted_net_income"], out["net_income"], places=6)

    def test_ttm_missing_falls_back_to_annual(self) -> None:
        sec = _FakeSecClient(
            submissions={"sic": "3674", "sicDescription": "Semiconductors"},
            companyfacts=_build_companyfacts_annual_for_fallback(),
        )
        cfg = ScanConfig(use_ttm_metrics=True)
        out = load_one_fundamental(sec, "ANNUAL", "0000000003", cfg)
        self.assertEqual(out["revenue_form"], "annual")
        self.assertEqual(out["net_income_form"], "annual")
        self.assertEqual(out["operating_cash_flow_form"], "annual")
        self.assertEqual(out["ebit_form"], "annual")

    def test_price_history_percentile_is_monotonic_position(self) -> None:
        bars: list[dict[str, object]] = []
        for i in range(1, 61):
            bars.append({"t": f"2025-01-{i:02d}T00:00:00Z", "c": float(i)})
        pct = compute_price_history_percentile(bars, 60)
        self.assertIsNotNone(pct)
        self.assertTrue(math.isclose(float(pct), 1.0, rel_tol=1e-9))

    def test_runtime_derived_proxy_and_capacity_metrics(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "revenue_yoy": 0.20,
                    "adjusted_net_income_yoy": 0.10,
                    "adjusted_ebit_yoy": 0.15,
                    "ebit_yoy": 0.12,
                    "return_20d": 0.08,
                    "return_60d": 0.06,
                    "avg_dollar_volume_20d": 50_000_000.0,
                }
            ]
        )
        expectation_proxy = (
            0.5 * pd.to_numeric(df["revenue_yoy"], errors="coerce").fillna(0)
            + 0.5 * pd.to_numeric(df["adjusted_net_income_yoy"], errors="coerce").fillna(0)
            - 0.5 * pd.to_numeric(df["return_20d"], errors="coerce").fillna(0)
            - 0.5 * pd.to_numeric(df["return_60d"], errors="coerce").fillna(0)
        )
        cycle_proxy = pd.to_numeric(df["adjusted_ebit_yoy"], errors="coerce").fillna(
            pd.to_numeric(df["ebit_yoy"], errors="coerce")
        ) - pd.to_numeric(df["revenue_yoy"], errors="coerce")
        adv_participation = 250_000.0 / pd.to_numeric(df["avg_dollar_volume_20d"], errors="coerce")
        estimated_slippage_bps = 200.0 * np.sqrt(adv_participation.clip(lower=0))

        self.assertAlmostEqual(float(expectation_proxy.iloc[0]), 0.08, places=9)
        self.assertAlmostEqual(float(cycle_proxy.iloc[0]), -0.05, places=9)
        self.assertAlmostEqual(float(adv_participation.iloc[0]), 0.005, places=9)
        self.assertAlmostEqual(float(estimated_slippage_bps.iloc[0]), 14.1421356237, places=6)

    def test_low_coverage_metric_fallback_inference(self) -> None:
        sec = _FakeSecClient(
            submissions={"sic": "7372", "sicDescription": "Prepackaged Software"},
            companyfacts=_build_companyfacts_for_low_coverage_inference(),
        )
        cfg = ScanConfig(use_ttm_metrics=True)
        out = load_one_fundamental(sec, "INF", "0000000004", cfg)
        self.assertEqual(out["current_debt_ratio_source"], "inferred_total_debt_capped_by_current_liabilities")
        self.assertAlmostEqual(float(out["current_debt_ratio"]), 0.4, places=6)
        self.assertEqual(out["inventory_growth_gap_source"], "inferred_inventory_not_applicable")
        self.assertAlmostEqual(float(out["inventory_growth_gap"]), 0.0, places=6)

    def test_hard_filter_coverage_mode_and_low_coverage_override(self) -> None:
        cfg = ScanConfig(metric_hard_filter_coverage_mode="high_coverage_only")
        cp = resolve_channel_profile(cfg, "core_ai", {})
        self.assertFalse(hard_filter_metric_enabled("inventory_growth_gap", cfg, cp))
        self.assertTrue(hard_filter_metric_enabled("net_debt_to_ebitda", cfg, cp))
        cp_force = resolve_channel_profile(cfg, "core_ai", {"hard_filter_inventory_growth_gap": True})
        self.assertTrue(hard_filter_metric_enabled("inventory_growth_gap", cfg, cp_force))

    def test_ai_disclosure_and_market_link_components(self) -> None:
        submissions = {
            "name": "Test Grid Systems",
            "sicDescription": "Electric Services",
            "business": {"description": "Data center cooling and grid connection for AI workloads."},
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q"],
                    "primaryDocDescription": ["capacity expansion for AI inference clusters", "general update"],
                }
            },
        }
        score, group_hits, keyword_hits = ai_disclosure_score_from_submissions(
            submissions, disclosure_keyword_cap=6
        )
        self.assertGreater(score, 0.0)
        self.assertGreaterEqual(group_hits, 1)
        self.assertGreaterEqual(keyword_hits, 1)

        etf_score = ai_etf_consensus_score(3, etf_count_saturation=4)
        self.assertAlmostEqual(etf_score, 0.75, places=6)

        market_score = ai_market_link_score(
            symbol_return_20d=0.12,
            symbol_return_60d=0.18,
            benchmark_return_20d=0.10,
            benchmark_return_60d=0.20,
            tol_20d=0.25,
            tol_60d=0.40,
        )
        self.assertGreater(market_score, 0.8)

    def test_ai_backlog_signal_from_companyfacts(self) -> None:
        facts = {
            "facts": {
                "us-gaap": {
                    "RevenueRemainingPerformanceObligation": {
                        "units": {
                            "USD": [
                                _entry("2025-12-31", 120.0, "10-K", "2026-02-20"),
                                _entry("2024-12-31", 80.0, "10-K", "2025-02-20"),
                            ]
                        }
                    }
                }
            }
        }
        signal = ai_backlog_signal_from_companyfacts(facts, revenue=300.0, cap_ratio=0.20)
        self.assertAlmostEqual(signal, 1.0, places=6)

    def test_dei_share_tag_wins_over_stale_us_gaap(self) -> None:
        # Regression: _merged_standard_taxonomy_facts must include the "dei"
        # taxonomy, otherwise a stale us-gaap CommonStockSharesOutstanding
        # (e.g. RTX, last reported 2009) wins and market-cap-derived metrics
        # are distorted by orders of magnitude.
        from ai_value_scanner.scanner import SHARES_TAGS, _merged_standard_taxonomy_facts, pick_facts_with_forms

        facts = {
            "facts": {
                "us-gaap": {
                    "CommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                _entry("2009-12-31", 1_381_700, "10-K", "2010-02-11"),
                            ]
                        }
                    }
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                _entry("2026-06-30", 1_347_758_144, "10-Q", "2026-07-23"),
                                _entry("2026-03-31", 1_348_900_000, "10-Q", "2026-04-23"),
                            ]
                        }
                    }
                },
            }
        }
        merged = _merged_standard_taxonomy_facts(facts)
        self.assertIn("EntityCommonStockSharesOutstanding", merged)
        picks = pick_facts_with_forms(
            facts, SHARES_TAGS, "shares", {"10-K", "10-Q", "8-K"}
        )
        self.assertEqual(picks[0][0], "2026-06-30")
        self.assertEqual(picks[0][1], 1_347_758_144.0)

    def test_share_pick_prefers_latest_end_across_tags(self) -> None:
        # Regression: pick_facts_with_forms must not short-circuit on the
        # first tag that has any data. CMCSA/UPS/ACN report dei
        # EntityCommonStockSharesOutstanding only in stale years, while
        # us-gaap WeightedAverage* carries the current count; the merge must
        # pick the newest period-end across all tags.
        from ai_value_scanner.scanner import SHARES_TAGS, pick_facts_with_forms

        facts = {
            "facts": {
                "us-gaap": {
                    "CommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                _entry("2009-12-31", 1_381_700, "10-K", "2010-02-11"),
                            ]
                        }
                    },
                    "WeightedAverageNumberOfSharesOutstandingBasic": {
                        "units": {
                            "shares": [
                                _entry("2026-06-30", 3_580_000_000, "10-Q", "2026-07-23"),
                                _entry("2026-03-31", 3_579_000_000, "10-Q", "2026-04-23"),
                            ]
                        }
                    },
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                _entry("2009-12-31", 2_063_073_161, "10-K", "2010-02-17"),
                            ]
                        }
                    }
                },
            }
        }
        picks = pick_facts_with_forms(facts, SHARES_TAGS, "shares", {"10-K", "10-Q", "8-K"})
        self.assertEqual(picks[0][0], "2026-06-30")
        self.assertEqual(picks[0][1], 3_580_000_000.0)
        self.assertEqual(picks[1][0], "2026-03-31")

    def test_share_unit_scale_reconciliation_thousands(self) -> None:
        # Regression: some filers report share counts in thousands while EPS
        # and net income use full units (Tempus AI: ~179K reported vs ~179M
        # actual). EPS x shares must approximately equal net income for the
        # same period end; a consistent ~1000x gap triggers the correction.
        from ai_value_scanner.scanner import reconcile_share_unit_scale

        facts = {
            "facts": {
                "us-gaap": {
                    "WeightedAverageNumberOfSharesOutstandingBasic": {
                        "units": {
                            "shares": [
                                _entry("2026-06-30", 179_404.0, "10-Q", "2026-07-30"),
                                _entry("2026-03-31", 178_880.0, "10-Q", "2026-05-05"),
                            ]
                        }
                    },
                    "EarningsPerShareBasic": {
                        "units": {
                            "USD/shares": [
                                _entry("2026-06-30", -0.67, "10-Q", "2026-07-30"),
                                _entry("2026-03-31", -0.70, "10-Q", "2026-05-05"),
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                _entry("2026-06-30", -120_300_000.0, "10-Q", "2026-07-30"),
                                _entry("2026-03-31", -125_900_000.0, "10-Q", "2026-05-05"),
                            ]
                        }
                    },
                }
            }
        }
        shares, end = reconcile_share_unit_scale(facts, 179_404.0)
        self.assertEqual(shares, 179_404_000.0)
        self.assertEqual(end, "2026-06-30")

    def test_share_unit_scale_reconciliation_no_change(self) -> None:
        # A normal filer (shares in full units) must not be touched.
        from ai_value_scanner.scanner import reconcile_share_unit_scale

        facts = {
            "facts": {
                "us-gaap": {
                    "WeightedAverageNumberOfSharesOutstandingBasic": {
                        "units": {
                            "shares": [
                                _entry("2026-06-30", 293_688_378.0, "10-Q", "2026-08-26"),
                            ]
                        }
                    },
                    "EarningsPerShareBasic": {
                        "units": {
                            "USD/shares": [
                                _entry("2026-06-30", 0.41, "10-Q", "2026-08-26"),
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                _entry("2026-06-30", 120_400_000.0, "10-Q", "2026-08-26"),
                            ]
                        }
                    },
                }
            }
        }
        shares, end = reconcile_share_unit_scale(facts, 293_688_378.0)
        self.assertEqual(shares, 293_688_378.0)
        self.assertEqual(end, "2026-06-30")

    def test_share_unit_scale_reconciliation_no_eps_no_change(self) -> None:
        # No EPS data available: the heuristic must leave shares untouched.
        from ai_value_scanner.scanner import reconcile_share_unit_scale

        facts = {
            "facts": {
                "us-gaap": {
                    "WeightedAverageNumberOfSharesOutstandingBasic": {
                        "units": {
                            "shares": [
                                _entry("2026-06-30", 1_234_567.0, "10-Q", "2026-07-30"),
                            ]
                        }
                    }
                }
            }
        }
        shares, end = reconcile_share_unit_scale(facts, 1_234_567.0)
        self.assertEqual(shares, 1_234_567.0)
        self.assertEqual(end, "2026-06-30")

    def test_share_unit_scale_reconciliation_annual_filer_untouched(self) -> None:
        # 20-F filers (Baidu-like) with all metrics at the same (old) period
        # end: EPS*shares already matches net income, so no rescale happens
        # even though the cache is stale. Unit detection must not guess here.
        from ai_value_scanner.scanner import reconcile_share_unit_scale

        facts = {
            "facts": {
                "us-gaap": {
                    "WeightedAverageNumberOfSharesOutstandingBasic": {
                        "units": {
                            "shares": [
                                _entry("2010-12-31", 34_805_362.0, "20-F", "2011-03-15"),
                            ]
                        }
                    },
                    "EarningsPerShareBasic": {
                        "units": {
                            "USD/shares": [
                                _entry("2010-12-31", 15.35, "20-F", "2011-03-15"),
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                _entry("2010-12-31", 534_300_000.0, "20-F", "2011-03-15"),
                            ]
                        }
                    },
                }
            }
        }
        shares, end = reconcile_share_unit_scale(facts, 34_805_362.0)
        self.assertEqual(shares, 34_805_362.0)
        self.assertEqual(end, "2010-12-31")

    def test_stale_share_count_is_flagged(self) -> None:
        # BIDU-like: share counts stop being reported (2010) while revenue and
        # net income continue to 2026. load_one_fundamental must flag the
        # share count as stale so peer medians exclude it.
        sec = _FakeSecClient(
            submissions={"sic": "7370", "sicDescription": "Services-Computer Programming, Data Processing, Etc."},
            companyfacts={
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    _entry("2026-06-30", 7_358_500_000.0, "20-F", "2026-07-30"),
                                ]
                            }
                        },
                        "NetIncomeLoss": {
                            "units": {
                                "USD": [
                                    _entry("2026-06-30", 799_000_000.0, "20-F", "2026-07-30"),
                                ]
                            }
                        },
                        "WeightedAverageNumberOfSharesOutstandingBasic": {
                            "units": {
                                "shares": [
                                    _entry("2010-12-31", 34_805_362.0, "20-F", "2011-03-15"),
                                ]
                            }
                        },
                        "EarningsPerShareBasic": {
                            "units": {
                                "USD/shares": [
                                    _entry("2010-12-31", 15.35, "20-F", "2011-03-15"),
                                ]
                            }
                        },
                    }
                }
            },
        )
        cfg = ScanConfig(use_ttm_metrics=True)
        out = load_one_fundamental(sec, "BIDU", "0001329099", cfg)
        self.assertTrue(out["shares_stale"])
        self.assertEqual(out["shares_asof_end"], "2010-12-31")

    def test_fresh_share_count_not_flagged(self) -> None:
        sec = _FakeSecClient(
            submissions={"sic": "7370", "sicDescription": "Services-Computer Programming, Data Processing, Etc."},
            companyfacts={
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    _entry("2026-06-30", 100_000_000.0, "10-Q", "2026-07-30"),
                                ]
                            }
                        },
                        "NetIncomeLoss": {
                            "units": {
                                "USD": [
                                    _entry("2026-06-30", 20_000_000.0, "10-Q", "2026-07-30"),
                                ]
                            }
                        },
                        "WeightedAverageNumberOfSharesOutstandingBasic": {
                            "units": {
                                "shares": [
                                    _entry("2026-06-30", 50_000_000.0, "10-Q", "2026-07-30"),
                                ]
                            }
                        },
                        "EarningsPerShareBasic": {
                            "units": {
                                "USD/shares": [
                                    _entry("2026-06-30", 0.40, "10-Q", "2026-07-30"),
                                ]
                            }
                        },
                    }
                }
            },
        )
        cfg = ScanConfig(use_ttm_metrics=True)
        out = load_one_fundamental(sec, "FRESH", "0000000001", cfg)
        self.assertFalse(out["shares_stale"])
        self.assertEqual(out["shares_asof_end"], "2026-06-30")


if __name__ == "__main__":
    unittest.main()
