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
        "min_total_valid_event_ratio": 0.80,
        "min_window_valid_event_ratio": 0.80,
        "min_oos_folds": 2,
        "min_oos_pass_ratio": 2.0 / 3.0,
        "min_oos_positive_excess_ratio": 2.0 / 3.0,
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
        "min_strict_total_valid_events": 0,
        "strict_coverage_ratio_floor": 0.0,
        "min_strict_avg_win_rate": 0.0,
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
        self.assertEqual(picks["risk_on"], "cand_a")
        self.assertEqual(picks["risk_off"], "cand_a")
        self.assertNotIn("balanced", picks)  # archived, no longer a promote target

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
                    "max_drawdown": 0.0,
                },
            ]
        )
        self.assertEqual(out["total_valid_events"], 4)
        self.assertEqual(out["min_window_valid_events"], 0)
        self.assertAlmostEqual(out["coverage_ratio"], 0.5)
        self.assertAlmostEqual(out["empty_window_ratio"], 0.5)
        self.assertAlmostEqual(out["worst_max_drawdown"], -0.10)

    @staticmethod
    def _window_metric(
        label: str,
        score: float,
        excess: float,
        *,
        purged_score: float | None = None,
        valid_events: int = 20,
        total_events: int = 20,
    ) -> dict:
        def ev(s: float, ex: float) -> dict:
            return {
                "score": s,
                "coverage_ratio": (
                    float(valid_events / total_events) if total_events else 0.0
                ),
                "avg_win_rate": 0.60,
                "avg_return": 0.05,
                "avg_excess_vs_qqq": ex,
                "avg_std_return": 0.02,
                "total_valid_events": valid_events,
                "total_events": total_events,
                "max_drawdown": -0.10,
            }

        primary = ev(score, excess)
        purged = ev(purged_score, excess) if purged_score is not None else None
        empty_regime = {
            "n_valid": 0,
            "n_periods": 0,
            "participation": 0.0,
            "avg_ret": float("nan"),
            "avg_ex": float("nan"),
            "win_rate": float("nan"),
            "series_std": float("nan"),
            "worst_dd": -1.0,
        }
        return {
            "label": label,
            "primary": primary,
            "strict": primary,
            "purged_primary": purged,
            "purged_strict": purged,
            "up_stats": empty_regime,
            "down_stats": empty_regime,
            "purged_up_stats": empty_regime if purged is not None else None,
            "purged_down_stats": empty_regime if purged is not None else None,
        }

    def test_monthly_valid_event_requirement_is_attainable_but_strict(self) -> None:
        self.assertEqual(
            self.tuner.effective_valid_event_requirement(20, 12, 0.80),
            10,
        )
        self.assertEqual(
            self.tuner.effective_valid_event_requirement(20, 52, 0.80),
            20,
        )
        self.assertEqual(
            self.tuner.effective_valid_event_requirement(120, 24, 0.80),
            20,
        )

    def test_heldout_monthly_window_uses_available_event_ratio(self) -> None:
        import json

        row = self.tuner.pd.Series(
            {
                "window_metrics_json": json.dumps(
                    [
                        self._window_metric(
                            "2025",
                            score=0.2,
                            excess=0.03,
                            valid_events=10,
                            total_events=12,
                        )
                    ]
                )
            }
        )
        out = self.tuner.heldout_validation(
            row,
            "2025",
            _args(min_window_valid_events=20),
        )
        self.assertEqual(out["required_valid_events"], 10)
        self.assertTrue(out["passed"])

    def test_heldout_immature_ytd_still_fails_sample_guardrail(self) -> None:
        import json

        row = self.tuner.pd.Series(
            {
                "window_metrics_json": json.dumps(
                    [
                        self._window_metric(
                            "2026YTD",
                            score=0.2,
                            excess=0.03,
                            valid_events=4,
                            total_events=9,
                        )
                    ]
                )
            }
        )
        out = self.tuner.heldout_validation(
            row,
            "2026YTD",
            _args(min_window_valid_events=20),
        )
        self.assertEqual(out["required_valid_events"], 8)
        self.assertFalse(out["passed"])
        self.assertIn("heldout_valid_events_too_low", out["reason"])

    def test_promotion_requires_oos_sequence_not_only_final_fold(self) -> None:
        import json

        windows = [
            self.tuner.TuneWindow("2023", "2023-01-01", "2023-12-31"),
            self.tuner.TuneWindow("2024", "2024-01-01", "2024-12-31"),
            self.tuner.TuneWindow("2025", "2025-01-01", "2025-12-31"),
            self.tuner.TuneWindow("2026YTD", "2026-01-01", "2026-09-30"),
        ]
        scores = self.tuner.pd.DataFrame(
            [
                {
                    "cid": "A",
                    "window_metrics_json": json.dumps(
                        [
                            self._window_metric(
                                "2023", 0.20, 0.03, purged_score=0.20,
                                valid_events=12, total_events=12,
                            ),
                            self._window_metric(
                                "2024", -0.10, -0.03, purged_score=-0.10,
                                valid_events=12, total_events=12,
                            ),
                            self._window_metric(
                                "2025", -0.05, -0.02, purged_score=-0.05,
                                valid_events=12, total_events=12,
                            ),
                            self._window_metric(
                                "2026YTD", 0.15, 0.04,
                                valid_events=9, total_events=9,
                            ),
                        ]
                    ),
                }
            ]
        )
        out = self.tuner.walk_forward_profile_selection(
            scores,
            windows,
            "risk_on",
            _args(
                min_total_valid_events=120,
                min_window_valid_events=20,
                min_positive_window_score_ratio=0.0,
                min_positive_excess_window_ratio=0.0,
            ),
        )
        self.assertTrue(out["folds"][-1]["validation"]["passed"])
        self.assertLess(out["oos_pass_ratio"], 2.0 / 3.0)
        self.assertFalse(out["promotion_eligible"])
        self.assertIn(
            "oos_pass_ratio_too_low",
            out["promotion_failure_reasons"],
        )

    def test_walk_forward_heldout_window_cannot_change_selection(self) -> None:
        import json

        windows = [
            self.tuner.TuneWindow("2023", "2023-01-01", "2023-12-31"),
            self.tuner.TuneWindow("2024", "2024-01-01", "2024-12-31"),
        ]
        # A wins 2023 training. B is spectacular in held-out 2024, but that
        # future result must not affect which candidate enters validation.
        scores = self.tuner.pd.DataFrame(
            [
                {
                    "cid": "A",
                    "window_metrics_json": json.dumps(
                        [
                            self._window_metric("2023", 0.20, 0.05, purged_score=0.20),
                            self._window_metric("2024", -0.50, -0.20),
                        ]
                    ),
                },
                {
                    "cid": "B",
                    "window_metrics_json": json.dumps(
                        [
                            self._window_metric("2023", 0.05, 0.01, purged_score=0.05),
                            self._window_metric("2024", 5.00, 1.00),
                        ]
                    ),
                },
            ]
        )
        out = self.tuner.walk_forward_profile_selection(scores, windows, "risk_on", _args())
        self.assertEqual(out["folds"][0]["selected_cid"], "A")

    def test_training_score_prefers_purged_metrics_over_leaky_full_window(self) -> None:
        import json

        row = self.tuner.pd.Series(
            {
                "window_metrics_json": json.dumps(
                    [
                        self._window_metric(
                            "2025",
                            score=9.0,       # leaky full-window diagnostic
                            excess=0.05,
                            purged_score=0.10,
                        )
                    ]
                )
            }
        )
        out = self.tuner.score_training_subset(row, ["2025"], "risk_on", _args())
        # With no regime stats, fallback rank is objective + coverage/return/excess.
        # The result must be based on purged 0.10, not the full-window 9.0.
        self.assertLess(out["rank_score"], 1.0)

    def test_walk_forward_windows_must_be_non_overlapping(self) -> None:
        windows = [
            self.tuner.TuneWindow("a", "2023-01-01", "2023-12-31"),
            self.tuner.TuneWindow("b", "2023-12-31", "2024-12-31"),
        ]
        with self.assertRaises(ValueError):
            self.tuner.validate_walk_forward_windows(windows)

    def test_mature_horizons_from_summary_excludes_unmatured_horizon(self) -> None:
        summary = self.tuner.pd.DataFrame(
            [
                {
                    "list_type": "low_value",
                    "horizon_days": 20,
                    "n_events_valid": 2,
                },
                {
                    "list_type": "low_value",
                    "horizon_days": 60,
                    "n_events_valid": 1,
                },
                {
                    "list_type": "low_value",
                    "horizon_days": 120,
                    "n_events_valid": 0,
                },
                {
                    "list_type": "research_pool",
                    "horizon_days": 120,
                    "n_events_valid": 5,
                },
            ]
        )
        out = self.tuner.mature_horizons_from_summary(
            summary,
            list_types=["low_value"],
            horizons=[20, 60, 120],
        )
        self.assertEqual(out, [20, 60])


if __name__ == "__main__":
    unittest.main()
