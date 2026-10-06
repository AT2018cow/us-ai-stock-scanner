from __future__ import annotations

import unittest

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.fundamentals import accounting


class TestSharedAccountingFacade(unittest.TestCase):
    def test_scanner_and_backtest_use_canonical_primitives(self) -> None:
        self.assertIs(scanner.safe_yoy, accounting.safe_yoy)
        self.assertIs(
            scanner.fundamental_quality_score_from_metrics,
            accounting.fundamental_quality_score_from_metrics,
        )
        self.assertIs(backtest.safe_yoy, accounting.safe_yoy)
        self.assertIs(
            backtest.fundamental_quality_score_from_metrics,
            accounting.fundamental_quality_score_from_metrics,
        )
        self.assertIs(
            backtest.compute_adjusted_metrics,
            accounting.compute_adjusted_metrics,
        )


class TestAccountingGoldenValues(unittest.TestCase):
    def test_adjustments_and_derived_metrics_have_independent_golden_answers(self) -> None:
        adjusted = accounting.compute_adjusted_metrics(
            net_income=30.0,
            ebit=40.0,
            da=5.0,
            revenue=120.0,
            revenue_prev=100.0,
            addback=8.0,
            gain=3.0,
            addback_prev=4.0,
            gain_prev=1.0,
            cap_ratio=None,
            net_income_prev=20.0,
            ebit_prev=32.0,
        )
        self.assertEqual(adjusted["adjusted_net_income"], 35.0)
        self.assertEqual(adjusted["adjusted_ebit"], 45.0)
        self.assertEqual(adjusted["adjusted_ebitda"], 50.0)
        self.assertEqual(adjusted["adjusted_net_income_prev"], 23.0)
        self.assertEqual(adjusted["adjusted_ebit_prev"], 35.0)

        out = accounting.derive_accounting_metrics(
            revenue=120.0,
            revenue_prev=100.0,
            net_income=30.0,
            net_income_prev=20.0,
            operating_cash_flow=36.0,
            operating_cash_flow_prev=30.0,
            capex_raw=-6.0,
            ebit=40.0,
            ebit_prev=32.0,
            shares=10.0,
            shares_prev=9.0,
            cash_and_equivalents=15.0,
            debt_long_term=20.0,
            debt_current=5.0,
            current_assets=50.0,
            current_liabilities=25.0,
            receivables_current=12.0,
            receivables_prev=10.0,
            inventory_current=None,
            inventory_prev=None,
            interest_expense=-4.0,
            depreciation_and_amortization=5.0,
            depreciation_and_amortization_prev=4.0,
            adjusted_net_income=adjusted["adjusted_net_income"],
            adjusted_net_income_prev=adjusted["adjusted_net_income_prev"],
            adjusted_ebit=adjusted["adjusted_ebit"],
            adjusted_ebit_prev=adjusted["adjusted_ebit_prev"],
            adjusted_ebitda=adjusted["adjusted_ebitda"],
        )

        self.assertEqual(out["capex"], 6.0)
        self.assertEqual(out["free_cash_flow"], 30.0)
        self.assertEqual(out["total_debt"], 25.0)
        self.assertEqual(out["net_debt"], 10.0)
        self.assertAlmostEqual(out["revenue_yoy"], 0.2, places=12)
        self.assertAlmostEqual(out["net_income_yoy"], 0.5, places=12)
        self.assertAlmostEqual(
            out["adjusted_net_income_yoy"],
            35.0 / 23.0 - 1.0,
            places=12,
        )
        self.assertAlmostEqual(out["ebit_yoy"], 0.25, places=12)
        self.assertAlmostEqual(
            out["adjusted_ebit_yoy"],
            45.0 / 35.0 - 1.0,
            places=12,
        )
        self.assertAlmostEqual(out["operating_cash_flow_yoy"], 0.2, places=12)
        self.assertAlmostEqual(out["shares_yoy"], 10.0 / 9.0 - 1.0, places=12)
        self.assertAlmostEqual(out["receivables_yoy"], 0.2, places=12)
        self.assertIsNone(out["inventory_yoy"])
        self.assertAlmostEqual(out["da_yoy"], 0.25, places=12)

        self.assertEqual(out["interest_expense"], 4.0)
        self.assertEqual(out["interest_coverage"], 11.25)
        self.assertEqual(out["net_debt_to_ebitda"], 0.2)
        self.assertEqual(out["current_ratio"], 2.0)
        self.assertEqual(out["current_debt_ratio_reported"], 0.1)
        self.assertIsNone(out["current_debt_ratio_inferred"])
        self.assertEqual(out["current_debt_ratio"], 0.1)
        self.assertEqual(out["current_debt_ratio_source"], "reported")
        self.assertAlmostEqual(out["ocf_to_net_income"], 36.0 / 35.0, places=12)
        self.assertEqual(out["accrual_ratio"], -0.02)
        self.assertAlmostEqual(out["receivables_growth_gap"], 0.0, places=12)
        self.assertEqual(out["inventory_growth_gap"], 0.0)
        self.assertIsNone(out["inventory_growth_gap_reported"])
        self.assertEqual(out["inventory_growth_gap_inferred"], 0.0)
        self.assertEqual(
            out["inventory_growth_gap_source"],
            "inferred_inventory_not_applicable",
        )
        self.assertEqual(out["fundamental_quality_score"], 0.960762)

    def test_current_debt_inference_contract(self) -> None:
        out = accounting.derive_accounting_metrics(
            revenue=100.0,
            revenue_prev=100.0,
            net_income=10.0,
            net_income_prev=10.0,
            operating_cash_flow=10.0,
            operating_cash_flow_prev=10.0,
            capex_raw=0.0,
            ebit=12.0,
            ebit_prev=12.0,
            shares=10.0,
            shares_prev=10.0,
            cash_and_equivalents=0.0,
            debt_long_term=30.0,
            debt_current=None,
            current_assets=100.0,
            current_liabilities=20.0,
            receivables_current=None,
            receivables_prev=None,
            inventory_current=0.0,
            inventory_prev=0.0,
            interest_expense=2.0,
            depreciation_and_amortization=0.0,
            depreciation_and_amortization_prev=0.0,
            adjusted_net_income=10.0,
            adjusted_net_income_prev=10.0,
            adjusted_ebit=12.0,
            adjusted_ebit_prev=12.0,
            adjusted_ebitda=12.0,
        )
        # Legacy inference caps current debt by current liabilities:
        # min(total_debt=30, current_liabilities=20) / current_assets=100.
        self.assertEqual(out["current_debt_ratio_reported"], None)
        self.assertEqual(out["current_debt_ratio_inferred"], 0.2)
        self.assertEqual(out["current_debt_ratio"], 0.2)
        self.assertEqual(
            out["current_debt_ratio_source"],
            "inferred_total_debt_capped_by_current_liabilities",
        )

    def test_replay_addback_cap_semantics_remain_unchanged(self) -> None:
        out = accounting.compute_adjusted_metrics(
            net_income=100.0,
            ebit=250.0,
            da=58.0,
            revenue=120.0,
            revenue_prev=100.0,
            addback=50.0,
            gain=2.0,
            addback_prev=30.0,
            gain_prev=1.0,
            cap_ratio=0.25,
            net_income_prev=90.0,
            ebit_prev=220.0,
        )
        # Existing replay behavior caps addback at 25% of revenue.
        self.assertEqual(out["adjusted_net_income"], 128.0)
        self.assertEqual(out["adjusted_ebit"], 278.0)
        self.assertEqual(out["adjusted_ebitda"], 336.0)
        self.assertEqual(out["adjusted_net_income_prev"], 114.0)
        self.assertEqual(out["adjusted_ebit_prev"], 244.0)


if __name__ == "__main__":
    unittest.main()
