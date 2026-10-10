from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ai_value_scanner.decision import QualityGrade
from ai_value_scanner.decision.quality import (
    QUALITY_POLICY_VERSION,
    build_company_quality_v1,
)
from ai_value_scanner.evaluation.company_quality import (
    apply_company_quality_v1,
    summarize_quality_cohorts,
    summarize_quality_concentration,
    summarize_quality_rank_correlation,
    validate_quality_replay_frame,
)


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


def _weak_metrics() -> dict[str, object]:
    return {
        "net_margin": -0.10,
        "free_cash_flow": -100.0,
        "ocf_to_net_income": 0.10,
        "accrual_ratio": 0.50,
        "revenue_yoy": -0.20,
        "adjusted_net_income_yoy": -0.30,
        "operating_cash_flow_yoy": -0.20,
        "net_debt_to_ebitda": 6.0,
        "interest_coverage": 0.5,
        "current_ratio": 0.5,
        "shares_yoy": 0.20,
        "fcf_yield": -0.05,
        "ps_hist_percentile": 0.95,
        "pe_hist_percentile": 0.95,
        "receivables_growth_gap": 0.40,
        "inventory_growth_gap": 0.45,
        "shares_stale": False,
    }


class TestCompanyQualityV1(unittest.TestCase):
    def test_policy_is_pre_registered_and_strong_company_is_a(self) -> None:
        decision = build_company_quality_v1(
            _strong_metrics(),
            decision_date="2026-10-10",
            data_asof="2026-08-01",
        )
        self.assertEqual(QUALITY_POLICY_VERSION, "company_quality_v1_2026-10-10")
        self.assertIs(decision.grade, QualityGrade.A)
        self.assertEqual(decision.score, 1.0)
        self.assertEqual(decision.confidence, 1.0)
        self.assertTrue(any(item.code == "fundamental_data_fresh" for item in decision.positives))

    def test_weak_company_is_c_and_severe_risks_block_higher_grades(self) -> None:
        decision = build_company_quality_v1(
            _weak_metrics(),
            decision_date="2026-10-10",
            data_asof="2026-08-01",
        )
        self.assertIs(decision.grade, QualityGrade.C)
        risk_codes = {item.code for item in decision.risks}
        self.assertIn("net_margin_weak", risk_codes)
        self.assertIn("shares_yoy_weak", risk_codes)
        self.assertIn("net_debt_to_ebitda_weak", risk_codes)

    def test_missing_data_cannot_create_false_a(self) -> None:
        metrics = _strong_metrics()
        for key in (
            "free_cash_flow",
            "ocf_to_net_income",
            "accrual_ratio",
            "interest_coverage",
            "current_ratio",
            "shares_yoy",
            "ps_hist_percentile",
            "pe_hist_percentile",
            "receivables_growth_gap",
            "inventory_growth_gap",
        ):
            metrics[key] = None
        decision = build_company_quality_v1(
            metrics,
            decision_date="2026-10-10",
            data_asof="2026-08-01",
        )
        self.assertIs(decision.grade, QualityGrade.UNRATED)
        self.assertLess(decision.confidence, 0.50)
        self.assertGreater(len(decision.missing), 0)

    def test_removing_observed_metric_does_not_raise_effective_score(self) -> None:
        complete = _strong_metrics()
        complete["net_margin"] = 0.01
        with_metric = build_company_quality_v1(
            complete,
            decision_date="2026-10-10",
            data_asof="2026-08-01",
        )
        complete["net_margin"] = None
        without_metric = build_company_quality_v1(
            complete,
            decision_date="2026-10-10",
            data_asof="2026-08-01",
        )
        self.assertLessEqual(without_metric.score or 0.0, with_metric.score or 0.0)
        self.assertLess(without_metric.confidence, with_metric.confidence)

    def test_stale_and_future_fundamental_dates_are_explicit(self) -> None:
        stale = build_company_quality_v1(
            _strong_metrics(),
            decision_date="2026-10-10",
            data_asof="2025-01-01",
        )
        self.assertIs(stale.grade, QualityGrade.UNRATED)
        self.assertTrue(
            any(item.code == "fundamental_data_severely_stale" for item in stale.risks)
        )
        with self.assertRaisesRegex(ValueError, "after decision_date"):
            build_company_quality_v1(
                _strong_metrics(),
                decision_date="2026-10-10",
                data_asof="2026-10-11",
            )

    def test_historical_frame_rejects_future_fundamentals(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA"],
                "signal_date": ["2025-01-01"],
                "fundamental_data_asof": ["2025-01-02"],
            }
        )
        with self.assertRaisesRegex(ValueError, "future fundamental data"):
            validate_quality_replay_frame(frame)

    def test_cohort_evaluation_reports_date_equal_weight_year_regime_and_concentration(self) -> None:
        rows = []
        for signal_date, symbol, grade, score, regime, ret, qqq in (
            ("2025-01-31", "AAA", "A", 0.90, "up", 0.20, 0.05),
            ("2025-01-31", "BBB", "A", 0.80, "up", 0.10, 0.05),
            ("2025-02-28", "CCC", "B", 0.60, "down", -0.05, 0.01),
            ("2026-01-30", "DDD", "C", 0.30, "up", -0.10, 0.02),
        ):
            rows.append(
                {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "quality_grade": grade,
                    "quality_score": score,
                    "regime": regime,
                    "fwd_ret_20": ret,
                    "qqq_return_20": qqq,
                }
            )
        frame = pd.DataFrame(rows)
        cohorts = summarize_quality_cohorts(frame, horizons=(20,))
        overall_a = cohorts[
            (cohorts["segment_type"] == "overall")
            & (cohorts["quality_grade"] == "A")
        ].iloc[0]
        self.assertAlmostEqual(float(overall_a["mean_return"]), 0.15, places=12)
        self.assertAlmostEqual(
            float(overall_a["date_equal_weight_mean_return"]), 0.15, places=12
        )
        self.assertIn("year", set(cohorts["segment_type"]))
        self.assertIn("regime", set(cohorts["segment_type"]))

        concentration = summarize_quality_concentration(frame)
        a_conc = concentration[concentration["quality_grade"] == "A"].iloc[0]
        self.assertEqual(int(a_conc["n_symbols"]), 2)
        self.assertAlmostEqual(float(a_conc["top_date_share"]), 1.0, places=12)

    def test_apply_decisions_and_rank_ic_use_numeric_quality_score(self) -> None:
        base = _strong_metrics()
        rows = []
        for idx, (symbol, margin, ret) in enumerate(
            (("AAA", 0.25, 0.20), ("BBB", 0.12, 0.10), ("CCC", -0.05, -0.10))
        ):
            metrics = dict(base)
            metrics["net_margin"] = margin
            metrics.update(
                {
                    "symbol": symbol,
                    "signal_date": "2026-01-30",
                    "fundamental_data_asof": "2025-12-31",
                    "regime": "up",
                    "fwd_ret_20": ret,
                    "qqq_return_20": 0.02,
                }
            )
            rows.append(metrics)
        decisions = apply_company_quality_v1(pd.DataFrame(rows))
        self.assertTrue(set(("quality_grade", "quality_score", "quality_confidence")).issubset(decisions.columns))
        rank_ic = summarize_quality_rank_correlation(decisions, horizons=(20,))
        self.assertEqual(int(rank_ic.iloc[0]["n_dates_return_ic"]), 1)
        self.assertGreater(float(rank_ic.iloc[0]["mean_spearman_return"]), 0.0)

    def test_extract_dataset_parser_preserves_default_and_adds_quality_mode(self) -> None:
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(scripts_dir))
        try:
            from extract_weight_dataset import build_parser
        finally:
            sys.path.pop(0)
        parser = build_parser()
        self.assertEqual(parser.parse_args([]).dataset_kind, "weight")
        self.assertEqual(
            parser.parse_args(["--dataset-kind", "company_quality"]).dataset_kind,
            "company_quality",
        )


if __name__ == "__main__":
    unittest.main()
