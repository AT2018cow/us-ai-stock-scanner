"""Regression tests for the evaluation-harness bug classes found on 2026-09-26/27.

Each test pins a defect that produced wrong reported numbers at least once:

1. score_candidate horizon misalignment: precompute_groups() with
   [20, 60, 120] then score_candidate(..., [120]) silently reads the 20d
   column. Now guarded by a ValueError.
2. Cross-channel dedup: portfolio must equal-weight UNIQUE picked symbols
   (production normalize_symbol_list semantics), not double-count a symbol
   selected by two channels.
3. regime_stats benchmark merge: QQQ benchmark rows are duplicated once per
   list_type in the benchmarks CSV; merging without drop_duplicates inflates
   weights non-uniformly on partial dates.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sweep_score_weights import score_candidate  # noqa: E402


def _make_group(symbols: list[str], fwd: np.ndarray, n_axes: int = 2) -> dict:
    n = len(symbols)
    rng = np.random.default_rng(len(symbols))
    return {
        "axes": [f"a{i}" for i in range(n_axes)],
        "norm": rng.normal(size=(n, n_axes)),
        "soft_rate": rng.random(n),
        "ovp": np.zeros(n),
        "det": np.zeros(n),
        "fwd": fwd,
        "symbols": symbols,
    }


class HorizonMisalignmentGuardTest(unittest.TestCase):
    def test_mismatched_horizons_raise(self):
        groups = {("2023-01-31", "low_value", "core_ai"): _make_group(
            ["A", "B"], np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        )}
        with self.assertRaises(ValueError):
            # precomputed 3 horizons, caller claims 1 → must fail loudly
            score_candidate(groups, {"low_value": {"a0": 1.0, "a1": 1.0}},
                            {"low_value": 0.3}, [120], 10)

    def test_matching_horizons_pass(self):
        groups = {("2023-01-31", "low_value", "core_ai"): _make_group(
            ["A", "B"], np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        )}
        events = score_candidate(groups, {"low_value": {"a0": 1.0, "a1": 1.0}},
                                 {"low_value": 0.3}, [20, 60, 120], 10)
        self.assertEqual(len(events), 3)  # one row per horizon


class CrossChannelDedupTest(unittest.TestCase):
    def test_duplicate_symbol_counted_once(self):
        # Both channels rank SYM first; production dedups by symbol.
        fwd = np.array([[0.10, 0.20, 0.30]])  # SYM: 20d=10%, 60d=20%, 120d=30%
        groups = {
            ("2023-01-31", "low_value", "core_ai"): _make_group(["SYM", "A"], np.vstack([fwd, [[0.0, 0.0, 0.0]]])),
            ("2023-01-31", "low_value", "ai_enabler"): _make_group(["SYM", "B"], np.vstack([fwd, [[0.0, 0.0, 0.0]]])),
        }
        # Force SYM to rank first in both channels: zero out other rows' norms.
        for g in groups.values():
            g["norm"][1:] = -10.0
            g["norm"][0] = 10.0
        events = score_candidate(groups, {"low_value": {"a0": 1.0, "a1": 1.0}},
                                 {"low_value": 0.3}, [20, 60, 120], 1)
        ev20 = events[events["horizon_days"] == 20].iloc[0]
        # Without dedup: picks = [SYM, SYM] → double-counted weight; with
        # production dedup: picks = [SYM] → n_picked == 1.
        self.assertEqual(int(ev20["n_picked"]), 1)
        self.assertAlmostEqual(ev20["mean_ret"], 0.10, places=10)
        ev120 = events[events["horizon_days"] == 120].iloc[0]
        self.assertAlmostEqual(ev120["mean_ret"], 0.30, places=10)

    def test_unique_symbols_equal_weighted(self):
        # Two distinct symbols with different returns → mean is the average.
        groups = {("2023-01-31", "low_value", "core_ai"): _make_group(
            ["X", "Y"], np.array([[0.10, 0.10, 0.10], [0.30, 0.30, 0.30]])
        )}
        events = score_candidate(groups, {"low_value": {"a0": 1.0, "a1": 0.0}},
                                 {"low_value": 0.0}, [20, 60, 120], 10)
        ev20 = events[events["horizon_days"] == 20].iloc[0]
        self.assertAlmostEqual(ev20["mean_ret"], 0.20, places=10)


class RegimeStatsBenchmarkDedupTest(unittest.TestCase):
    def test_benchmark_merge_dedup(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tune_parameters import regime_stats  # noqa: E402

        events = pd.DataFrame({
            "scenario": ["base", "base"],
            "signal_date": ["2023-01-31", "2023-01-31"],
            "list_type": ["low_value", "momentum"],
            "horizon_days": [60, 60],
            "regime": ["up", "up"],
            "event_status": ["valid", "valid"],
            "portfolio_return": [0.10, 0.20],
        })
        # Benchmarks CSV duplicates each (scenario, date, horizon) once per list_type.
        benchmarks = pd.DataFrame({
            "scenario": ["base"] * 8,
            "signal_date": ["2023-01-31"] * 8,
            "horizon_days": [60] * 8,
            "benchmark": ["QQQ"] * 8,
            "benchmark_return": [0.05] * 8,
        })
        stats = regime_stats(events, benchmarks, "up", ["low_value", "momentum"], [60])
        # Without dedup the merge would produce 8 rows; excess mean must be
        # computed on the 2 real events: (5% + 15%) / 2 = 10%.
        self.assertAlmostEqual(stats["avg_ex"], 0.10, places=10)
        self.assertEqual(stats["n_valid"], 2)


if __name__ == "__main__":
    unittest.main()
