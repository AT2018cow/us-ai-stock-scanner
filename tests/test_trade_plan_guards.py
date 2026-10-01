from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plan_mod = _load_script("generate_trade_plan.py")


class TestApplyPositionCaps(unittest.TestCase):
    def test_converged_book_matches_legacy_math(self) -> None:
        # convictions [2,1,1,0.5,0.5] (sum 5), cap 0.30:
        # iter1 caps 0.40->0.30, redistributes 0.10 -> [0.30, 0.2333, 0.2333, 0.1167, 0.1167]
        w, unallocated, converged = plan_mod.apply_position_caps(
            pd.Series([2.0, 1.0, 1.0, 0.5, 0.5]), 0.30
        )
        self.assertTrue(converged)
        self.assertAlmostEqual(unallocated, 0.0, places=9)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=9)
        self.assertTrue(bool((w <= 0.30 + 1e-9).all()))
        self.assertAlmostEqual(float(w.iloc[0]), 0.30, places=6)
        self.assertAlmostEqual(float(w.iloc[1]), 0.70 / 3.0, places=6)

    def test_all_pinned_book_leaves_reported_cash(self) -> None:
        # 5 equal names at 0.20 vs cap 0.1111: everything pinned, rest is cash.
        w, unallocated, converged = plan_mod.apply_position_caps(
            pd.Series([1.0] * 5), 0.10 / 0.90
        )
        self.assertFalse(converged)
        self.assertTrue(bool((w <= 0.10 / 0.90 + 1e-9).all()))
        self.assertAlmostEqual(float(w.sum()) + unallocated, 1.0, places=9)
        self.assertAlmostEqual(unallocated, 1.0 - 5.0 * (0.10 / 0.90), places=6)
        self.assertGreater(unallocated, 0.44)  # ~44% of deployable stays cash

    def test_single_name_pinned(self) -> None:
        w, unallocated, converged = plan_mod.apply_position_caps(pd.Series([3.0]), 0.25)
        self.assertAlmostEqual(float(w.iloc[0]), 0.25, places=9)
        self.assertAlmostEqual(unallocated, 0.75, places=9)

    def test_zero_conviction_fails_loud(self) -> None:
        with self.assertRaises(SystemExit):
            plan_mod.apply_position_caps(pd.Series([0.0, 0.0]), 0.5)

    def test_cap_never_breached_after_max_iter(self) -> None:
        rng = np.random.default_rng(7)
        w, unallocated, _ = plan_mod.apply_position_caps(
            pd.Series(rng.uniform(0.1, 5.0, size=23)), 0.05, max_iter=3
        )
        self.assertTrue(bool((w <= 0.05 * (1.0 + 1e-9)).all()))
        self.assertAlmostEqual(float(w.sum()) + unallocated, 1.0, places=9)


class TestCheckBreakerState(unittest.TestCase):
    def test_unknown_data_blocks(self) -> None:
        proceed, reason = plan_mod.check_breaker_state(
            {"ok": None, "close": None, "sma200": None, "asof": None}, date(2026, 9, 29)
        )
        self.assertFalse(proceed)
        self.assertIn("不可用", reason)

    def test_unparsable_asof_blocks(self) -> None:
        proceed, _ = plan_mod.check_breaker_state(
            {"ok": True, "close": 1.0, "sma200": 0.5, "asof": "not-a-date"}, date(2026, 9, 29)
        )
        self.assertFalse(proceed)

    def test_stale_data_blocks(self) -> None:
        proceed, reason = plan_mod.check_breaker_state(
            {"ok": True, "close": 700.0, "sma200": 600.0, "asof": "2026-09-19"}, date(2026, 9, 29)
        )
        self.assertFalse(proceed)
        self.assertIn("陈旧", reason)

    def test_boundary_stale_day_proceeds(self) -> None:
        proceed, _ = plan_mod.check_breaker_state(
            {"ok": True, "close": 700.0, "sma200": 600.0, "asof": "2026-09-25"},
            date(2026, 9, 29),
            max_stale_days=4,
        )
        self.assertTrue(proceed)

    def test_fresh_bull_and_bear_proceed(self) -> None:
        proceed, regime = plan_mod.check_breaker_state(
            {"ok": True, "close": 700.0, "sma200": 600.0, "asof": "2026-09-28"}, date(2026, 9, 29)
        )
        self.assertTrue(proceed)
        self.assertEqual(regime, "bull")
        proceed, regime = plan_mod.check_breaker_state(
            {"ok": False, "close": 600.0, "sma200": 700.0, "asof": "2026-09-28"}, date(2026, 9, 29)
        )
        self.assertTrue(proceed)
        self.assertEqual(regime, "bear")


class TestSafeDefaults(unittest.TestCase):
    def test_trade_plan_allows_no_breaker_override_flag(self) -> None:
        args = plan_mod.build_parser().parse_args(["--capital", "100"])
        self.assertFalse(args.allow_no_breaker)

    def test_tuner_fallback_defaults_off(self) -> None:
        import unittest.mock as mock

        tuner = _load_script("tune_parameters.py")
        with mock.patch.object(sys, "argv", ["tune_parameters.py"]):
            args = tuner.parse_args()
        self.assertFalse(args.allow_latest_watchlist_fallback)

    def test_extract_fallback_defaults_off(self) -> None:
        extract = _load_script("extract_weight_dataset.py")
        args = extract.build_parser().parse_args([])
        self.assertFalse(args.allow_latest_watchlist_fallback)


if __name__ == "__main__":
    unittest.main()
