from __future__ import annotations

import unittest

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner


class TestPreE01Characterization(unittest.TestCase):
    def test_fundamental_quality_score_contract(self) -> None:
        expected = 0.763333
        scan_value = scanner.fundamental_quality_score_from_metrics(
            net_debt_to_ebitda=2.0,
            interest_coverage=4.0,
            current_ratio=1.5,
            ocf_to_net_income=1.2,
            accrual_ratio=0.1,
        )
        backtest_value = backtest.fundamental_quality_score_from_metrics(
            net_debt_to_ebitda=2.0,
            interest_coverage=4.0,
            current_ratio=1.5,
            ocf_to_net_income=1.2,
            accrual_ratio=0.1,
        )
        self.assertEqual(scan_value, expected)
        self.assertEqual(backtest_value, expected)

    def test_missing_quality_inputs_remain_neutral(self) -> None:
        self.assertEqual(
            scanner.fundamental_quality_score_from_metrics(
                None, None, None, None, None
            ),
            0.5,
        )

    def test_adjusted_metric_contract(self) -> None:
        out = backtest.compute_adjusted_metrics(
            net_income=100.0,
            ebit=120.0,
            da=20.0,
            revenue=1000.0,
            revenue_prev=900.0,
            addback=100.0,
            gain=10.0,
            addback_prev=20.0,
            gain_prev=5.0,
            cap_ratio=0.05,
            net_income_prev=90.0,
            ebit_prev=110.0,
        )
        self.assertEqual(out["adjusted_net_income"], 140.0)
        self.assertEqual(out["adjusted_ebit"], 160.0)
        self.assertEqual(out["adjusted_ebitda"], 180.0)
        self.assertEqual(out["adjusted_net_income_prev"], 105.0)
        self.assertEqual(out["adjusted_ebit_prev"], 125.0)

    def test_ai_link_weight_contract(self) -> None:
        cfg = scanner.ScanConfig()
        cfg.ai_link_weight_etf_consensus = 0.1
        cfg.ai_link_weight_disclosure = 0.2
        cfg.ai_link_weight_market_link = 0.3
        cfg.ai_link_weight_backlog = 0.4
        score = backtest.compute_ai_link_score(
            cfg,
            ai_etf_score=0.2,
            ai_disclosure_score=0.4,
            ai_market_score=0.6,
            ai_backlog_signal=0.8,
        )
        self.assertAlmostEqual(score, 0.6, places=12)

    def test_robust_normalization_contract(self) -> None:
        values = pd.Series([1.0, 2.0, 3.0, None])
        out = scanner.robust_normalize_score(values, 0.0, 1.0)
        expected = [0.22710252, 0.5, 0.77289748, 0.5]
        for actual, exp in zip(out.tolist(), expected):
            self.assertAlmostEqual(actual, exp, places=7)

    def test_safe_yoy_contract(self) -> None:
        self.assertAlmostEqual(scanner.safe_yoy(120.0, 100.0), 0.2, places=12)
        self.assertIsNone(scanner.safe_yoy(120.0, 0.0))
        self.assertIsNone(scanner.safe_yoy(None, 100.0))


if __name__ == "__main__":
    unittest.main()
