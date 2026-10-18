"""R03 repair tests: market calendar and live runtime freshness semantics."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ai_value_scanner.decision.entry import (
    build_entry_quality_v1,
    build_entry_quality_v2,
)
from ai_value_scanner.market_calendar import (
    is_early_close,
    is_session_day,
    latest_completed_session,
)

BASE_ENTRY_METRICS = {
    "price_to_sma200": 1.05,
    "price_to_sma50": 1.03,
    "days_below_sma200": 0,
    "return_20d": 0.05,
    "return_60d": 0.10,
    "drawdown_from_52w_high": 0.08,
    "range_position_52w": 0.82,
    "relative_strength_60d_qqq": 0.04,
    "volatility_60d": 0.35,
    "regime": "up",
    "benchmark_trend_ok": True,
}


class MarketCalendarTests(unittest.TestCase):
    def test_known_2026_holidays(self) -> None:
        for day in (
            "2026-01-01",  # New Year's Day (Thursday)
            "2026-01-19",  # MLK
            "2026-02-16",  # Washington's Birthday
            "2026-04-03",  # Good Friday
            "2026-05-25",  # Memorial Day
            "2026-06-19",  # Juneteenth (Friday)
            "2026-07-03",  # July 4 observed (Saturday -> Friday)
            "2026-09-07",  # Labor Day
            "2026-11-26",  # Thanksgiving
            "2026-12-25",  # Christmas (Friday)
        ):
            with self.subTest(day=day):
                self.assertFalse(is_session_day(datetime.fromisoformat(day).date()))

    def test_new_year_saturday_is_not_observed_friday(self) -> None:
        # 2022-01-01 was a Saturday; NYSE did not observe Friday 2021-12-31.
        self.assertTrue(is_session_day(datetime.fromisoformat("2021-12-31").date()))

    def test_juneteenth_not_a_holiday_before_2022(self) -> None:
        self.assertTrue(is_session_day(datetime.fromisoformat("2021-06-18").date()))
        self.assertFalse(is_session_day(datetime.fromisoformat("2022-06-20").date()))

    def test_weekend_and_holiday_reference(self) -> None:
        saturday = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(latest_completed_session(saturday).isoformat(), "2026-10-16")
        sunday = datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(latest_completed_session(sunday).isoformat(), "2026-10-16")
        thanksgiving = datetime(2026, 11, 26, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(
            latest_completed_session(thanksgiving).isoformat(), "2026-11-25"
        )

    def test_intraday_vs_after_close(self) -> None:
        before_close = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(
            latest_completed_session(before_close).isoformat(), "2026-10-16"
        )
        after_close = datetime(2026, 10, 19, 21, 30, tzinfo=timezone.utc)
        self.assertEqual(
            latest_completed_session(after_close).isoformat(), "2026-10-19"
        )

    def test_early_close_days(self) -> None:
        self.assertTrue(is_early_close(datetime.fromisoformat("2026-11-27").date()))
        self.assertTrue(is_early_close(datetime.fromisoformat("2026-12-24").date()))
        # Christmas 2026 falls on Friday, so Dec 24 (Thursday) is early close.
        self.assertFalse(is_early_close(datetime.fromisoformat("2026-12-23").date()))


class RuntimeFreshnessTests(unittest.TestCase):
    def _decision(self, **changes):
        metrics = {**BASE_ENTRY_METRICS, **changes}
        return metrics

    def test_all_data_thirty_days_old_is_not_fresh_ready(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-09-18",
            market_asof="2026-09-18",
            runtime_reference_date="2026-10-18",
        )
        self.assertEqual(item.state.value, "INSUFFICIENT_DATA")
        codes = {risk.code for risk in item.risks}
        self.assertIn("market_data_severely_stale", codes)
        self.assertNotIn("market_data_fresh", {p.code for p in item.positives})

    def test_four_to_seven_day_window_still_allows_ready_with_warning(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-12",
            market_asof="2026-10-12",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "ENTRY_READY")
        codes = {risk.code for risk in item.risks}
        self.assertIn("market_data_stale", codes)

    def test_weekend_run_does_not_flag_friday_data(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-16",
            market_asof="2026-10-16",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "ENTRY_READY")
        self.assertIn("market_data_fresh", {p.code for p in item.positives})

    def test_symbol_lag_with_fresh_benchmark(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-16",
            market_asof="2026-10-07",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "INSUFFICIENT_DATA")
        codes = {risk.code for risk in item.risks}
        self.assertIn("market_data_severely_stale", codes)
        self.assertNotIn("benchmark_market_data_stale", codes)

    def test_stale_benchmark_with_fresh_symbols_is_explicit(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-02",
            market_asof="2026-10-16",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "INSUFFICIENT_DATA")
        codes = {risk.code for risk in item.risks}
        self.assertIn("benchmark_market_data_severely_stale", codes)
        self.assertIn("market_data_fresh", {p.code for p in item.positives})

    def test_stale_benchmark_five_days_warns_only(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-09",
            market_asof="2026-10-16",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "ENTRY_READY")
        codes = {risk.code for risk in item.risks}
        self.assertIn("benchmark_market_data_stale", codes)

    def test_replay_without_runtime_reference_is_unchanged(self) -> None:
        # Historical semantics: age is decision_date - market_asof.
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-09-18",
            market_asof="2026-09-18",
        )
        self.assertEqual(item.state.value, "ENTRY_READY")
        self.assertIn("market_data_fresh", {p.code for p in item.positives})

    def test_replay_future_market_asof_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_entry_quality_v1(
                self._decision(),
                decision_date="2026-10-01",
                market_asof="2026-10-16",
            )

    def test_live_mode_allows_symbol_newer_than_stale_benchmark(self) -> None:
        item = build_entry_quality_v1(
            self._decision(),
            decision_date="2026-10-09",
            market_asof="2026-10-16",
            runtime_reference_date="2026-10-16",
        )
        codes = {risk.code for risk in item.risks}
        self.assertIn("benchmark_market_data_stale", codes)
        self.assertIn("market_data_fresh", {p.code for p in item.positives})

    def test_market_asof_after_runtime_reference_fails_closed(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-16",
            market_asof="2026-10-19",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "INSUFFICIENT_DATA")
        codes = {risk.code for risk in item.risks}
        self.assertIn("market_data_ahead_of_reference", codes)
        self.assertNotIn("market_data_fresh", {p.code for p in item.positives})
        freshness = next(
            gate for gate in item.gate_results if gate.gate_key == "freshness"
        )
        self.assertEqual(freshness.status, "BLOCK")
        self.assertTrue(freshness.blocking)

    def test_benchmark_after_runtime_reference_fails_closed(self) -> None:
        item = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-10-19",
            market_asof="2026-10-16",
            runtime_reference_date="2026-10-16",
        )
        self.assertEqual(item.state.value, "INSUFFICIENT_DATA")
        codes = {risk.code for risk in item.risks}
        self.assertIn("benchmark_market_data_ahead_of_reference", codes)
        benchmark = next(
            gate for gate in item.gate_results if gate.gate_key == "benchmark_freshness"
        )
        self.assertEqual(benchmark.status, "BLOCK")
        self.assertTrue(benchmark.blocking)

    def test_v1_and_v2_share_runtime_semantics(self) -> None:
        v1 = build_entry_quality_v1(
            self._decision(),
            decision_date="2026-09-18",
            market_asof="2026-09-18",
            runtime_reference_date="2026-10-18",
        )
        v2 = build_entry_quality_v2(
            self._decision(),
            decision_date="2026-09-18",
            market_asof="2026-09-18",
            runtime_reference_date="2026-10-18",
        )
        self.assertEqual(v1.state, v2.state)
        self.assertEqual(
            {risk.code for risk in v1.risks},
            {risk.code for risk in v2.risks},
        )


if __name__ == "__main__":
    unittest.main()
