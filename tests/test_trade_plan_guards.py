from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
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


def _filings(rows: list[tuple]) -> "pd.DataFrame":
    import pandas as pd

    return pd.DataFrame(
        [{"form": f, "filed": pd.Timestamp(fd), "period": pd.Timestamp(p)} for f, fd, p in rows]
    )


class TestPredictEarningsWindow(unittest.TestCase):
    def _qtrs(self, year: int = 2026, q_lag: int = 35, a_lag: int = 70) -> list[tuple]:

        def dt(y: int, m: int, d: int, lag: int) -> tuple[str, str, str]:
            p = pd.Timestamp(y, m, d)
            return ("10-Q", str((p + pd.Timedelta(days=lag)).date()), str(p.date()))

        rows = [
            dt(year, 3, 31, q_lag), dt(year - 1, 12, 31, q_lag),  # placeholder, replaced below
        ]
        rows = [
            dt(2026, 3, 31, q_lag), ("10-K", "2026-03-10", "2025-12-31") if False else dt(2025, 12, 31, q_lag),
            dt(2025, 9, 30, q_lag), dt(2025, 6, 30, q_lag + 2),
            ("10-K", str((pd.Timestamp(2025, 12, 31) - pd.Timedelta(days=365 - a_lag)).date()), "2024-12-31"),
            dt(2024, 9, 30, q_lag - 2), dt(2024, 6, 30, q_lag), dt(2024, 3, 31, q_lag + 1),
        ]
        # fix the annual rows to carry the annual lag
        fixed = []
        for form, filed, period in rows:
            if form == "10-K":
                p = pd.Timestamp(period)
                fixed.append((form, str((p + pd.Timedelta(days=a_lag)).date()), period))
            else:
                fixed.append((form, filed, period))
        return fixed

    def test_quarterly_path_matches_legacy(self) -> None:

        df = _filings(self._qtrs())
        # today before next period end -> clear, quarterly lag
        out = plan_mod.predict_earnings_window(df, pd.Timestamp("2026-04-15"), 7)
        self.assertEqual(out["status"], "clear")
        self.assertEqual(out["predicted_form"], "quarterly")
        self.assertEqual(out["next_period"], "2026-06-30")
        self.assertEqual(out["lag_days"], 35)
        self.assertEqual(out["window"], "2026-07-25~2026-08-18")

    def test_q4_predicts_annual_window(self) -> None:

        # latest = Q3 10-Q (period 2026-09-30); next report is the FY 10-K
        rows = self._qtrs() + [("10-Q", "2026-11-04", "2026-09-30")]
        df = _filings(rows)
        out = plan_mod.predict_earnings_window(df, pd.Timestamp("2026-12-20"), 7)
        self.assertEqual(out["predicted_form"], "annual")
        self.assertEqual(out["next_period"], "2026-12-30")
        # annual lag (~70) covers the real 10-K; legacy median (~35) would have closed ~26d early
        self.assertGreaterEqual(out["lag_days"], 65)
        # Dec 20 is before the annual window -> clear (not a false imminent)
        self.assertEqual(out["status"], "clear")

    def test_imminent_inside_annual_window(self) -> None:

        rows = self._qtrs() + [("10-Q", "2026-11-04", "2026-09-30")]
        df = _filings(rows)
        # mid-March, 10-K not yet filed, inside predicted annual window
        out = plan_mod.predict_earnings_window(df, pd.Timestamp("2027-03-05"), 7)
        self.assertEqual(out["status"], "imminent")

    def test_foreign_annual_filer(self) -> None:

        df = _filings([
            ("20-F", "2026-04-28", "2025-12-31"),
            ("20-F", "2026-04-28", "2025-12-31"),
            ("20-F", "2025-04-25", "2024-12-31"),
        ])
        out = plan_mod.predict_earnings_window(df, pd.Timestamp("2026-06-01"), 7)
        self.assertEqual(out["predicted_form"], "annual")
        self.assertEqual(out["next_period"], "2026-12-31")

    def test_empty_reports_unknown(self) -> None:

        out = plan_mod.predict_earnings_window(
            pd.DataFrame(columns=["form", "filed", "period"]), pd.Timestamp("2026-06-01"), 7
        )
        self.assertEqual(out["status"], "unknown")


class TestEarningsAdvisoryRows(unittest.TestCase):
    def test_imminent_included_others_excluded(self) -> None:

        plan = pd.DataFrame([{"symbol": "MU"}, {"symbol": "CRM"}, {"symbol": "TXN"}])
        status = {
            "MU": {"status": "imminent", "window": "2026-09-22~2026-10-16", "note": "n"},
            "CRM": {"status": "clear", "window": "2026-11-11~2026-12-05"},
            "TXN": {"status": "unknown"},
        }
        rows = plan_mod.earnings_advisory_rows(plan, status)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "MU")
        self.assertEqual(rows[0]["window"], "2026-09-22~2026-10-16")

    def test_empty_plan_no_rows(self) -> None:

        self.assertEqual(plan_mod.earnings_advisory_rows(pd.DataFrame(columns=["symbol"]), {}), [])


class TestExcludeAuxiliaryChannels(unittest.TestCase):
    def test_drops_smallcap_rows_only(self) -> None:

        df = pd.DataFrame([
            {"symbol": "AAA", "channel": "core_ai"},
            {"symbol": "BBB", "channel": "ai_smallcap"},
            {"symbol": "CCC", "channel": "ai_peripheral"},
        ])
        out = plan_mod.exclude_auxiliary_channels(df)
        self.assertEqual(sorted(out["symbol"].tolist()), ["AAA", "CCC"])

    def test_include_flag_keeps_all(self) -> None:

        df = pd.DataFrame([{"symbol": "BBB", "channel": "ai_smallcap"}])
        out = plan_mod.exclude_auxiliary_channels(df, include_smallcap=True)
        self.assertEqual(len(out), 1)

    def test_empty_and_missing_channel_passthrough(self) -> None:

        self.assertTrue(plan_mod.exclude_auxiliary_channels(pd.DataFrame()).empty)
        df = pd.DataFrame([{"symbol": "AAA"}])
        self.assertEqual(len(plan_mod.exclude_auxiliary_channels(df)), 1)


class TestSleeveSmallcapFilter(unittest.TestCase):
    def _write_fixtures(self, root: str) -> None:

        outdir = Path(root) / "outputs"
        outdir.mkdir(parents=True, exist_ok=True)
        ranked = pd.DataFrame([
            {"symbol": "AAA", "triage_label": "keep", "channel": "core_ai", "composite_score": 1.10},
            {"symbol": "BBB", "triage_label": "watch", "channel": "ai_smallcap", "composite_score": 1.20},
            {"symbol": "CCC", "triage_label": "watch", "channel": "ai_smallcap", "composite_score": 0.90},
            {"symbol": "CCC", "triage_label": "watch", "channel": "ai_enabler", "composite_score": 0.80},
        ])
        ranked.to_csv(outdir / "ai_value_scan_TESTTS_full_ranked.csv", index=False)
        mo = pd.DataFrame([
            {"symbol": "DDD", "channel": "ai_smallcap", "composite_score": 1.00, "research_priority": "research_now"},
            {"symbol": "EEE", "channel": "core_ai", "composite_score": 0.95, "research_priority": "watch_for_pullback"},
        ])
        mo.to_csv(outdir / "ai_value_scan_TESTTS_full_ranked_momentum.csv", index=False)

    def test_smallcap_excluded_by_default(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            self._write_fixtures(tmp)
            prev = os.getcwd()
            try:
                os.chdir(tmp)
                pos = plan_mod.sleeve_positions("TESTTS", "risk_off")
            finally:
                os.chdir(prev)
        syms = pos["symbol"].tolist()
        # BBB (smallcap-only) and DDD (smallcap momentum) are gone;
        # CCC survives via its ai_enabler row; AAA/EEE untouched.
        self.assertNotIn("BBB", syms)
        self.assertNotIn("DDD", syms)
        self.assertIn("AAA", syms)
        self.assertIn("EEE", syms)
        ccc = pos[pos["symbol"] == "CCC"]
        self.assertEqual(len(ccc), 1)
        self.assertEqual(ccc.iloc[0]["channel"], "ai_enabler")

    def test_include_smallcap_restores(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            self._write_fixtures(tmp)
            prev = os.getcwd()
            try:
                os.chdir(tmp)
                pos = plan_mod.sleeve_positions("TESTTS", "risk_off", include_smallcap=True)
            finally:
                os.chdir(prev)
        syms = pos["symbol"].tolist()
        self.assertIn("BBB", syms)
        self.assertIn("DDD", syms)
