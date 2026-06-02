from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path


def _load_tuner_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "tune_parameters.py"
    spec = importlib.util.spec_from_file_location("tune_parameters", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load tune_parameters.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: float | int) -> argparse.Namespace:
    base = {
        "min_total_valid_events": 10,
        "min_window_valid_events": 2,
        "coverage_ratio_floor": 0.2,
        "max_acceptable_drawdown": 0.5,
        "drawdown_penalty_weight": 0.6,
        "min_avg_return": 0.0,
        "min_avg_excess_vs_qqq": 0.0,
        "min_avg_win_rate": 0.52,
        "min_positive_window_score_ratio": 0.5,
        "negative_return_penalty_weight": 0.8,
        "negative_excess_penalty_weight": 1.0,
        "low_win_rate_penalty_weight": 0.6,
        "positive_window_penalty_weight": 0.5,
        "stability_penalty_weight": 0.35,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestTuneParameterConstraints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tuner = _load_tuner_module()

    def test_negative_excess_fails_candidate_constraints(self) -> None:
        penalty, reasons = self.tuner.candidate_constraint_penalty(
            total_valid=20,
            min_window_valid=3,
            coverage_ratio=0.4,
            worst_dd=-0.2,
            window_stability_std=0.0,
            positive_window_score_ratio=0.75,
            avg_ret=0.03,
            avg_ex=-0.01,
            avg_win=0.6,
            args=_args(),
        )
        self.assertGreater(penalty, 0)
        self.assertIn("avg_excess_vs_qqq_too_low", reasons)

    def test_low_win_rate_fails_candidate_constraints(self) -> None:
        _, reasons = self.tuner.candidate_constraint_penalty(
            total_valid=20,
            min_window_valid=3,
            coverage_ratio=0.4,
            worst_dd=-0.2,
            window_stability_std=0.0,
            positive_window_score_ratio=0.75,
            avg_ret=0.03,
            avg_ex=0.01,
            avg_win=0.49,
            args=_args(),
        )
        self.assertIn("avg_win_rate_too_low", reasons)

    def test_low_positive_window_ratio_fails_candidate_constraints(self) -> None:
        _, reasons = self.tuner.candidate_constraint_penalty(
            total_valid=20,
            min_window_valid=3,
            coverage_ratio=0.4,
            worst_dd=-0.2,
            window_stability_std=0.0,
            positive_window_score_ratio=0.25,
            avg_ret=0.03,
            avg_ex=0.01,
            avg_win=0.6,
            args=_args(),
        )
        self.assertIn("positive_window_score_ratio_too_low", reasons)

    def test_finite_nanmean_ignores_nan_and_handles_empty(self) -> None:
        self.assertAlmostEqual(self.tuner.finite_nanmean([0.1, float("nan"), 0.3]), 0.2)
        self.assertTrue(self.tuner.np.isnan(self.tuner.finite_nanmean([float("nan")])))


if __name__ == "__main__":
    unittest.main()
