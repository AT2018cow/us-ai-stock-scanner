from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ai_value_scanner.scanner import ScanConfig
import ai_value_scanner.scanner as scanner_mod
import ai_value_scanner.backtest as backtest_mod


def _load_script(filename: str):
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


daily = _load_script("daily_run.py")
theme = _load_script("theme_observation_scan.py")


class TestDailyRunBusinessCalendar(unittest.TestCase):
    def test_business_date_uses_new_york_not_utc(self) -> None:
        # 2026-10-05 01:00 UTC is still Sunday evening in New York.
        early_utc = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(daily.market_business_date(early_utc), date(2026, 10, 4))

        # Later the same UTC day is Monday in New York.
        later_utc = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(daily.market_business_date(later_utc), date(2026, 10, 5))

    def test_run_date_override_is_deterministic(self) -> None:
        self.assertEqual(
            daily.market_business_date(
                datetime(2030, 1, 1, tzinfo=timezone.utc),
                "2026-10-09",
            ),
            date(2026, 10, 9),
        )

    def test_only_friday_freezes_weekly_cohort(self) -> None:
        self.assertFalse(daily.should_archive_weekly_cohort(date(2026, 10, 8)))
        self.assertTrue(daily.should_archive_weekly_cohort(date(2026, 10, 9)))
        self.assertFalse(daily.should_archive_weekly_cohort(date(2026, 10, 12)))


class _FakeClient:
    def get_corporate_action_splits(self, symbols, start_iso):
        return {}


def _frame(entry_open: float, exit_close: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-02", periods=120, freq="B", tz="UTC")
    opens = [entry_open] * len(idx)
    closes = [entry_open] * len(idx)
    closes[-1] = exit_close
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1000.0] * len(idx),
        },
        index=idx,
    )


class TestThemePaperCohortEvaluation(unittest.TestCase):
    def test_evaluate_matured_records_absolute_and_relative_returns(self) -> None:
        bars = {
            "AAA": _frame(100.0, 120.0),
            "QQQ": _frame(100.0, 110.0),
            "NLR": _frame(100.0, 115.0),
            "URA": _frame(100.0, 105.0),
        }
        cohort = pd.DataFrame(
            [
                {
                    "theme": "nuclear",
                    "list_type": "low_value",
                    "symbol": "AAA",
                    "triage": "keep",
                    "research_priority": "research_now",
                    "composite_score": 0.7,
                    "entry_date": "2025-01-01",
                    "entry_price": 100.0,
                    "status": "open",
                    "exit_date": "",
                    "return_120d": "",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "theme_cohorts.csv"
            cohort.to_csv(path, index=False)
            with (
                patch.object(scanner_mod, "load_config", return_value=ScanConfig()),
                patch.object(
                    backtest_mod,
                    "load_alpaca_client",
                    return_value=(_FakeClient(), None),
                ),
                patch.object(backtest_mod, "build_bar_db", return_value=bars),
                patch.object(
                    theme,
                    "load_theme_benchmarks",
                    return_value={"nuclear": ["NLR", "URA"]},
                ),
            ):
                theme.evaluate_matured(path)

            out = pd.read_csv(path)
            row = out.iloc[0]

        # 15 bps/side = 30 bps round trip.
        self.assertEqual(row["status"], "matured")
        self.assertAlmostEqual(float(row["return_120d_gross"]), 0.20, places=6)
        self.assertAlmostEqual(float(row["return_120d"]), 0.197, places=6)
        self.assertAlmostEqual(float(row["qqq_return_120d"]), 0.097, places=6)
        self.assertAlmostEqual(float(row["excess_vs_qqq_120d"]), 0.10, places=6)

        # NLR net=14.7%, URA net=4.7%; median=9.7%.
        self.assertAlmostEqual(
            float(row["theme_benchmark_return_120d"]), 0.097, places=6
        )
        self.assertAlmostEqual(
            float(row["excess_vs_theme_benchmark_120d"]), 0.10, places=6
        )
        self.assertEqual(row["theme_benchmark_symbols"], "NLR,URA")

    def test_default_scan_is_observation_not_cohort_archive(self) -> None:
        args = theme.build_parser().parse_args([])
        self.assertFalse(args.archive_cohort)

    def test_weekly_cohort_first_freeze_wins(self) -> None:
        first = pd.DataFrame(
            [
                {
                    "theme": "nuclear",
                    "list_type": "low_value",
                    "symbol": "AAA",
                    "triage": "keep",
                    "research_priority": "research_now",
                    "composite_score": 0.7,
                    "entry_date": "2026-10-09",
                    "entry_price": 10.0,
                    "status": "open",
                    "exit_date": "",
                    "return_120d": "",
                }
            ]
        )
        second = first.copy()
        second.loc[0, "symbol"] = "BBB"

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "theme_cohorts.csv"
            theme.archive_cohort("nuclear", first, path)
            theme.archive_cohort("nuclear", second, path)
            out = pd.read_csv(path)

        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["symbol"], "AAA")
        self.assertEqual(out.iloc[0]["cohort_id"], "nuclear:2026-W41")


if __name__ == "__main__":
    unittest.main()
