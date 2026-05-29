from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from ai_value_scanner.scanner import (
    ScanConfig,
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


if __name__ == "__main__":
    unittest.main()
