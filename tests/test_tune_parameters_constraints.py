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
        "min_positive_excess_window_ratio": 0.5,
        "max_empty_window_ratio": 0.25,
        "negative_return_penalty_weight": 0.8,
        "negative_excess_penalty_weight": 1.0,
        "low_win_rate_penalty_weight": 0.6,
        "positive_window_penalty_weight": 0.5,
        "positive_excess_window_penalty_weight": 0.5,
        "empty_window_penalty_weight": 0.7,
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
            positive_excess_window_ratio=0.75,
            empty_window_ratio=0.0,
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
            positive_excess_window_ratio=0.75,
            empty_window_ratio=0.0,
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
            positive_excess_window_ratio=0.75,
            empty_window_ratio=0.0,
            avg_ret=0.03,
            avg_ex=0.01,
            avg_win=0.6,
            args=_args(),
        )
        self.assertIn("positive_window_score_ratio_too_low", reasons)

    def test_low_positive_excess_window_ratio_fails_candidate_constraints(self) -> None:
        _, reasons = self.tuner.candidate_constraint_penalty(
            total_valid=20,
            min_window_valid=3,
            coverage_ratio=0.4,
            worst_dd=-0.2,
            window_stability_std=0.0,
            positive_window_score_ratio=0.75,
            positive_excess_window_ratio=0.25,
            empty_window_ratio=0.0,
            avg_ret=0.03,
            avg_ex=0.01,
            avg_win=0.6,
            args=_args(),
        )
        self.assertIn("positive_excess_window_ratio_too_low", reasons)

    def test_high_empty_window_ratio_fails_candidate_constraints(self) -> None:
        _, reasons = self.tuner.candidate_constraint_penalty(
            total_valid=20,
            min_window_valid=3,
            coverage_ratio=0.4,
            worst_dd=-0.2,
            window_stability_std=0.0,
            positive_window_score_ratio=0.75,
            positive_excess_window_ratio=0.75,
            empty_window_ratio=0.5,
            avg_ret=0.03,
            avg_ex=0.01,
            avg_win=0.6,
            args=_args(),
        )
        self.assertIn("empty_window_ratio_too_high", reasons)

    def test_classify_window_failure_distinguishes_empty_event_causes(self) -> None:
        no_signal_events = self.tuner.pd.DataFrame({"n_selected": [0], "n_priced": [0]})
        self.assertEqual(
            self.tuner.classify_window_failure({"total_valid_events": 0}, no_signal_events),
            "no_signal",
        )
        unpriced_events = self.tuner.pd.DataFrame({"n_selected": [3], "n_priced": [0]})
        self.assertEqual(
            self.tuner.classify_window_failure({"total_valid_events": 0}, unpriced_events),
            "unpriced",
        )

    def test_classify_window_failure_distinguishes_negative_excess(self) -> None:
        events = self.tuner.pd.DataFrame({"n_selected": [3], "n_priced": [3]})
        self.assertEqual(
            self.tuner.classify_window_failure(
                {"total_valid_events": 1, "avg_excess_vs_qqq": -0.01, "avg_return": 0.02},
                events,
            ),
            "negative_excess",
        )

    def test_profile_picks_are_independent_and_may_reuse_best_candidate(self) -> None:
        scores = self.tuner.pd.DataFrame(
            [
                {
                    "cid": "cand_a",
                    "constraints_passed": True,
                    "balanced_rank_score": 3.0,
                    "risk_on_rank_score": 3.0,
                    "risk_off_rank_score": 3.0,
                },
                {
                    "cid": "cand_b",
                    "constraints_passed": True,
                    "balanced_rank_score": 2.0,
                    "risk_on_rank_score": 2.0,
                    "risk_off_rank_score": 2.0,
                },
            ]
        )
        picks = self.tuner.pick_profile_candidates(scores)
        self.assertEqual(picks["balanced"], "cand_a")
        self.assertEqual(picks["risk_on"], "cand_a")
        self.assertEqual(picks["risk_off"], "cand_a")

    def test_finite_nanmean_ignores_nan_and_handles_empty(self) -> None:
        self.assertAlmostEqual(self.tuner.finite_nanmean([0.1, float("nan"), 0.3]), 0.2)
        self.assertTrue(self.tuner.np.isnan(self.tuner.finite_nanmean([float("nan")])))

    def test_aggregate_window_evals_tracks_coverage_and_empty_windows(self) -> None:
        out = self.tuner.aggregate_window_evals(
            [
                {
                    "coverage_ratio": 1.0,
                    "avg_win_rate": 0.6,
                    "avg_return": 0.04,
                    "avg_excess_vs_qqq": 0.01,
                    "avg_std_return": 0.05,
                    "total_valid_events": 4,
                    "max_drawdown": -0.10,
                },
                {
                    "coverage_ratio": 0.0,
                    "avg_win_rate": float("nan"),
                    "avg_return": float("nan"),
                    "avg_excess_vs_qqq": float("nan"),
                    "avg_std_return": float("nan"),
                    "total_valid_events": 0,
                    "max_drawdown": -0.20,
                },
            ]
        )
        self.assertEqual(out["total_valid_events"], 4)
        self.assertEqual(out["min_window_valid_events"], 0)
        self.assertAlmostEqual(out["coverage_ratio"], 0.5)
        self.assertAlmostEqual(out["empty_window_ratio"], 0.5)
        self.assertAlmostEqual(out["worst_max_drawdown"], -0.20)


if __name__ == "__main__":
    unittest.main()
