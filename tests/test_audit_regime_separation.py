"""E4a regime-separation audit tests (offline, synthetic fixtures).

Covers `scripts/audit_regime_separation.py` per the pre-registered spec
(`docs/agent_specs/regime_indicator_validation_spec.md`, section 5):
R1 labeling matrix incl. first-6-dates vol warm-up, merged-vs-base-only
sequence semantics, the S0 stop path, missing-data behavior, the
forward-label firewall, hand-computed aggregation math, output hygiene and
the anti-drift import of `build_scope_records`.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_regime_separation as ars  # noqa: E402
import run_extended_replay_evaluation as rex  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_row(**overrides):
    """Full scanner-like row; mirrors the extended-replay test fixture."""
    row = {
        "signal_date": "2023-01-31",
        "market_asof": "2023-01-31",
        "fundamental_data_asof": "2022-11-01",
        "regime": "up",
        "benchmark_trend_ok": True,
        "qqq_trailing_return_60d": 0.04,
        "revenue": 1000.0,
        "net_income": 100.0,
        "operating_cash_flow": 120.0,
        "free_cash_flow": 80.0,
        "ebit": 130.0,
        "adjusted_net_income": 100.0,
        "adjusted_ebit": 130.0,
        "net_margin": 0.10,
        "ocf_to_net_income": 1.2,
        "accrual_ratio": -0.02,
        "revenue_yoy": 0.10,
        "adjusted_net_income_yoy": 0.10,
        "operating_cash_flow_yoy": 0.10,
        "net_debt_to_ebitda": 1.0,
        "interest_coverage": 8.0,
        "current_ratio": 2.0,
        "shares_yoy": 0.01,
        "fcf_yield": 0.03,
        "ps_hist_percentile": 0.5,
        "pe_hist_percentile": 0.5,
        "receivables_growth_gap": 0.0,
        "inventory_growth_gap": 0.0,
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.02,
        "days_below_sma200": 0,
        "return_20d": 0.03,
        "return_60d": 0.08,
        "drawdown_from_52w_high": 0.05,
        "range_position_52w": 0.7,
        "relative_strength_60d_qqq": 0.02,
        "volatility_60d": 0.3,
        "watchlist_etf_count": 1,
        "watchlist_bucket": "core_ai",
        "watchlist_etfs": "XLK",
        "fwd_ret_20": 0.02,
        "fwd_ret_60": 0.05,
        "fwd_ret_120": 0.10,
        "qqq_return_20": 0.01,
        "qqq_return_60": 0.03,
        "qqq_return_120": 0.06,
    }
    row.update(overrides)
    return row


def _synthetic_group(
    date: str = "2023-01-31",
    *,
    qqq60: float = -0.05,
    qqq20: float = 0.01,
    regime: str = "down",
    trend_ok: bool = True,
    trailing60: float = 0.04,
    sma200: float = 1.05,
    vol60: float = 0.30,
) -> pd.DataFrame:
    from datetime import date as _date, timedelta

    signal_day = _date.fromisoformat(date)
    rows = []
    for index, symbol in enumerate(("AAA", "BBB", "CCC", "DDD")):
        row = _base_row(
            signal_date=date,
            market_asof=date,
            fundamental_data_asof=(
                signal_day - timedelta(days=60)
            ).isoformat(),
            regime=regime,
            benchmark_trend_ok=trend_ok,
            qqq_trailing_return_60d=trailing60,
            price_to_sma200=sma200,
            volatility_60d=vol60,
            qqq_return_60=qqq60,
            qqq_return_20=qqq20,
            fwd_ret_60=0.05 + 0.01 * index,
        )
        row["symbol"] = symbol
        if symbol == "AAA":
            row["watchlist_etf_count"] = 0
            row["watchlist_etfs"] = "SRC:NASDAQ_SCREEN"
        rows.append(row)
    return pd.DataFrame(rows)


def _market_rows(
    date: str,
    *,
    trailing60: float,
    sma200: float,
    vol60: float,
    regime: str,
    trend_ok: bool,
    n: int = 2,
) -> list[dict]:
    return [
        {
            "signal_date": date,
            "qqq_trailing_return_60d": trailing60,
            "price_to_sma200": sma200,
            "volatility_60d": vol60,
            "benchmark_trend_ok": trend_ok,
            "regime": regime,
        }
        for _ in range(n)
    ]


def _market_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


BEAR_SIX_DATES = [
    "2022-01-31", "2022-02-28", "2022-03-31",
    "2022-04-29", "2022-05-31", "2022-06-30",
]
BASE_SEVEN_DATES = [
    "2023-01-31", "2023-02-28", "2023-03-31", "2023-04-28",
    "2023-05-31", "2023-06-30", "2023-07-31",
]


def _rec(symbol: str, priority: int, exc60):
    return {"symbol": symbol, "priority": priority, "excess_60": exc60}


# ---------------------------------------------------------------------------
# 1+2. Indicator definitions
# ---------------------------------------------------------------------------


class TestIndicatorDefinitions(unittest.TestCase):
    def test_r1_label_matrix(self) -> None:
        stats = {
            "d1": {"trailing_return_60d": 0.05, "breadth": 0.60},
            "d2": {"trailing_return_60d": 0.05, "breadth": 0.48},
            "d3": {"trailing_return_60d": -0.05, "breadth": 0.40},
            "d4": {"trailing_return_60d": -0.05, "breadth": 0.48},
            "d5": {"trailing_return_60d": -0.05, "breadth": 0.60},
            "d6": {"trailing_return_60d": 0.05, "breadth": 0.50},
            "d7": {"trailing_return_60d": -0.05, "breadth": 0.45},
            "d8": {"trailing_return_60d": 0.00, "breadth": 0.60},
            "d9": {"trailing_return_60d": None, "breadth": 0.60},
            "d10": {"trailing_return_60d": 0.05, "breadth": 0.60},
        }
        vol_high = {"d5": True, "d10": True}
        labels = ars.compute_r1_labels(stats, vol_high)
        expected = {
            "d1": ars.UPTREND,
            "d2": ars.NEUTRAL,   # trend up but breadth < 0.50
            "d3": ars.DOWNTREND,  # trend down and breadth < 0.45
            "d4": ars.NEUTRAL,   # trend down, breadth >= 0.45, not vol_high
            "d5": ars.DOWNTREND,  # trend down + vol_high (breadth alone fails)
            "d6": ars.UPTREND,   # breadth exactly 0.50 counts as >=
            "d7": ars.NEUTRAL,   # breadth exactly 0.45 is NOT < 0.45
            "d8": ars.NEUTRAL,   # flat trend is neither up nor down
            "d9": ars.NEUTRAL,   # missing trailing return
            "d10": ars.NEUTRAL,  # trend up but vol_high blocks UPTREND
        }
        self.assertEqual(labels, expected)

    def test_vol_high_first_six_fallback_and_trailing_median(self) -> None:
        seq = [f"d{i}" for i in range(1, 9)]
        medians = [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.5, 0.3]
        stats = {
            f"d{i}": {"median_volatility_60d": median}
            for i, median in enumerate(medians, start=1)
        }
        flags = ars.compute_vol_high_flags(seq, stats)
        for i in range(1, 7):
            self.assertFalse(flags[f"d{i}"], f"d{i}")  # warm-up inherits False
        # d7: 0.5 > trailing median of six 0.3 values -> True
        self.assertTrue(flags["d7"])
        # d8: 0.3 vs median(0.3*6, 0.5) = 0.3 -> strict > fails
        self.assertFalse(flags["d8"])

    def test_merged_sequence_vs_base_only(self) -> None:
        bear = _market_frame([
            row
            for date in BEAR_SIX_DATES
            for row in _market_rows(
                date, trailing60=-0.10, sma200=0.90, vol60=0.40,
                regime="down", trend_ok=False,
            )
        ])
        base_rows = _market_rows(
            "2023-01-31", trailing60=0.05, sma200=1.10, vol60=0.60,
            regime="up", trend_ok=True,
        )
        for date in BASE_SEVEN_DATES[1:]:
            base_rows += _market_rows(
                date, trailing60=0.05, sma200=1.10, vol60=0.40,
                regime="up", trend_ok=True,
            )
        base = _market_frame(base_rows)

        bundle = ars.compute_regime_labels(base, bear)
        merged = bundle["merged_sequence"]
        self.assertEqual(len(merged), 13)
        self.assertEqual(merged[:6], BEAR_SIX_DATES)  # 2022 dates first
        self.assertEqual(merged[6], "2023-01-31")

        # Merged: first base date has 6 prior 2022 medians (0.40); its own
        # median 0.60 is above the trailing median -> vol_high -> NEUTRAL.
        self.assertTrue(bundle["vol_high_merged"]["2023-01-31"])
        self.assertEqual(
            bundle["labels"]["R1"]["2023-01-31"], ars.NEUTRAL)
        # Base-only sequence: first date is warm-up -> UPTREND.
        self.assertFalse(bundle["vol_high_base_only"]["2023-01-31"])
        self.assertEqual(
            bundle["labels"]["R1_BASE_ONLY"]["2023-01-31"], ars.UPTREND)
        # Second base date: median 0.40 vs trailing median 0.40 -> not high.
        self.assertFalse(bundle["vol_high_merged"]["2023-02-28"])
        self.assertEqual(
            bundle["labels"]["R1"]["2023-02-28"], ars.UPTREND)
        # Bear dates: trend down + breadth 0 -> DOWNTREND; vol warm-up False.
        self.assertEqual(
            bundle["labels"]["R1"]["2022-01-31"], ars.DOWNTREND)
        self.assertFalse(bundle["vol_high_merged"]["2022-01-31"])

        # Base-dataset-only run uses the base sequence for R1.
        base_only_bundle = ars.compute_regime_labels(base, None)
        self.assertEqual(len(base_only_bundle["merged_sequence"]), 7)
        self.assertEqual(
            base_only_bundle["labels"]["R1"],
            base_only_bundle["labels"]["R1_BASE_ONLY"],
        )

    def test_r2_missing_trend_ok_is_neutral(self) -> None:
        stats = {
            "d1": {"trend_ok": True},
            "d2": {"trend_ok": False},
            "d3": {"trend_ok": None},
            "d4": {},
        }
        labels = ars.compute_r2_labels(stats)
        self.assertEqual(labels["d1"], ars.UPTREND)
        self.assertEqual(labels["d2"], ars.DOWNTREND)
        self.assertEqual(labels["d3"], ars.NEUTRAL)
        self.assertEqual(labels["d4"], ars.NEUTRAL)

    def test_all_nan_volatility_column(self) -> None:
        frame = _market_frame([
            *_market_rows(
                "2023-01-31", trailing60=0.05, sma200=1.10, vol60=float("nan"),
                regime="up", trend_ok=True,
            ),
            *_market_rows(
                "2023-02-28", trailing60=0.05, sma200=1.10, vol60=float("nan"),
                regime="up", trend_ok=True,
            ),
        ])
        stats = ars.compute_date_cross_section_stats(frame)
        self.assertIsNone(stats["2023-01-31"]["median_volatility_60d"])
        flags = ars.compute_vol_high_flags(
            sorted(stats), stats)
        self.assertEqual(flags, {"2023-01-31": False, "2023-02-28": False})
        labels = ars.compute_r1_labels(stats, flags)
        # Volatility unavailability never blocks a would-be UPTREND.
        self.assertEqual(labels["2023-01-31"], ars.UPTREND)

    def test_cross_section_stats_parse_string_bools(self) -> None:
        frame = _market_frame([
            *_market_rows(
                "2023-01-31", trailing60=0.05, sma200=1.10, vol60=0.3,
                regime="up", trend_ok=True,
            ),
        ])
        frame["benchmark_trend_ok"] = "False"
        stats = ars.compute_date_cross_section_stats(frame)
        self.assertIs(stats["2023-01-31"]["trend_ok"], False)
        labels = ars.compute_r2_labels(stats)
        self.assertEqual(labels["2023-01-31"], ars.DOWNTREND)


# ---------------------------------------------------------------------------
# 6. Aggregation math
# ---------------------------------------------------------------------------


class TestAggregationMath(unittest.TestCase):
    def test_date_equal_means_exclude_missing_dates(self) -> None:
        records = {
            "d1": [{"excess_60": 0.05}, {"excess_60": 0.15}],  # mean 0.10
            "d2": [{"excess_60": None}],
            "d3": [{"excess_60": -0.20}],
            "d4": [{"excess_60": 0.00}],
        }
        labels = {
            "d1": ars.UPTREND, "d2": ars.UPTREND,
            "d3": ars.DOWNTREND, "d4": ars.DOWNTREND,
        }
        result = ars.t1_separation(records, ["d1", "d2", "d3", "d4"], labels)
        # d2 has no finite value -> excluded, never imputed as 0.
        self.assertEqual(result["n_up_dates"], 1)
        self.assertEqual(result["n_down_dates"], 2)
        self.assertAlmostEqual(result["mean_up"], 0.10)
        self.assertAlmostEqual(result["mean_down"], -0.10)
        self.assertAlmostEqual(result["diff"], 0.20)
        self.assertTrue(result["bar_met"])

    def test_bootstrap_ci_hand_computed_constant_case(self) -> None:
        low, high = ars.bootstrap_difference_ci([0.10, 0.10], [0.00, 0.00])
        # every resample yields exactly 0.10
        self.assertAlmostEqual(low, 0.10)
        self.assertAlmostEqual(high, 0.10)
        low, high = ars.bootstrap_difference_ci([], [0.00])
        self.assertIsNone(low)
        self.assertIsNone(high)

    def test_paired_t_stat_hand_computed(self) -> None:
        # mean 0.03, sample std 0.0141421..., t = 3.0
        self.assertAlmostEqual(
            ars.paired_t_stat([0.02, 0.04]), 3.0, places=6)
        self.assertIsNone(ars.paired_t_stat([0.02]))
        self.assertIsNone(ars.paired_t_stat([0.02, 0.02]))  # zero std

    def test_loo_difference_stats_hand_computed(self) -> None:
        # Case A: one removal flips the sign.
        stats = ars.loo_difference_stats(
            {"u1": 0.30, "u2": 0.10},
            {"d1": 0.20, "d2": 0.05, "d3": 0.15},
        )
        self.assertAlmostEqual(stats["full"], 0.20 - 0.40 / 3.0, places=9)
        self.assertAlmostEqual(stats["loo_min"], 0.10 - 0.40 / 3.0, places=9)
        self.assertEqual(stats["worst_dropped_date"], "u1")
        self.assertFalse(stats["loo_sign_kept"])
        self.assertAlmostEqual(
            stats["recomputed_without_worst"], 0.10 - 0.40 / 3.0, places=9)

        # Case B: all removals keep the sign.
        stats = ars.loo_difference_stats(
            {"u1": 0.30, "u2": 0.40},
            {"d1": 0.05, "d2": 0.10},
        )
        self.assertAlmostEqual(stats["full"], 0.275, places=9)
        self.assertAlmostEqual(stats["loo_min"], 0.225, places=9)
        self.assertAlmostEqual(stats["loo_max"], 0.325, places=9)
        self.assertEqual(stats["worst_dropped_date"], "u2")
        self.assertTrue(stats["loo_sign_kept"])

        # Size-1 regime: that side's removal is skipped, never imputed.
        stats = ars.loo_difference_stats(
            {"u1": 0.10}, {"d1": 0.05, "d2": 0.00})
        self.assertTrue(stats["up_single_date_skipped"])
        self.assertEqual(stats["n_candidate_dates"], 2)
        self.assertAlmostEqual(stats["loo_min"], 0.10 - 0.05, places=9)

        # Empty regime cannot score.
        stats = ars.loo_difference_stats({}, {"d1": 0.05})
        self.assertIsNone(stats["full"])
        self.assertIsNone(stats["loo_sign_kept"])

    def test_materiality_rule(self) -> None:
        self.assertTrue(ars.materially_differs(0.01, -0.01))  # sign differs
        self.assertTrue(ars.materially_differs(0.03, 0.005))  # 2.5pp > 2pp
        self.assertFalse(ars.materially_differs(0.03, 0.02))  # 1pp
        self.assertFalse(ars.materially_differs(None, 0.02))
        self.assertFalse(ars.materially_differs(-0.03, None))


# ---------------------------------------------------------------------------
# T1/T2/T3 toy hand-computed checks
# ---------------------------------------------------------------------------


class TestSeparationTests(unittest.TestCase):
    def test_t1_toy_hand_computed(self) -> None:
        records = {
            "d1": [{"excess_60": 0.10}, {"excess_60": 0.20}],  # mean 0.15
            "d2": [{"excess_60": -0.05}],                      # mean -0.05
            "d3": [{"excess_60": -0.10}, {"excess_60": -0.30}],  # mean -0.20
            "d4": [{"excess_60": 0.10}],                       # mean 0.10
        }
        labels = {
            "d1": ars.UPTREND, "d2": ars.UPTREND,
            "d3": ars.DOWNTREND, "d4": ars.DOWNTREND,
        }
        result = ars.t1_separation(records, sorted(records), labels)
        self.assertEqual(result["n_up_dates"], 2)
        self.assertEqual(result["n_down_dates"], 2)
        self.assertAlmostEqual(result["mean_up"], 0.05)
        self.assertAlmostEqual(result["mean_down"], -0.05)
        self.assertAlmostEqual(result["diff"], 0.10)
        self.assertTrue(result["bar_met"])
        # LOO: dropping d3 gives -0.05 -> sign flips.
        self.assertAlmostEqual(result["loo_min_across"], -0.05)
        self.assertEqual(result["loo_worst_date_dropped"], "d3")
        self.assertFalse(result["loo_sign_kept"])

    def test_t2_toy_hand_computed(self) -> None:
        records = {
            "v2_current": {
                "d1": [_rec("A", 3, 0.20), _rec("B", 10, 0.00),
                       _rec("C", 40, 0.90)],
                "d2": [_rec("A", 2, -0.10)],
            },
            "v1_current": {
                "d1": [_rec("A", 3, 0.00), _rec("B", 10, 0.00),
                       _rec("C", 40, 0.00)],
                "d2": [_rec("A", 2, 0.00)],
            },
        }
        labels = {"d1": ars.UPTREND, "d2": ars.DOWNTREND}
        result = ars.t2_separation(records, ["d1", "d2"], labels)
        # TOP15 means: v2 d1 = (0.20 + 0.00)/2 = 0.10; v1 d1 = 0.00
        self.assertAlmostEqual(result["mean_up"], 0.10)
        self.assertAlmostEqual(result["mean_down"], -0.10)
        self.assertAlmostEqual(result["diff"], 0.20)
        self.assertTrue(result["bar_met"])  # signs differ -> material
        self.assertAlmostEqual(result["positive_share_up"], 1.0)
        self.assertAlmostEqual(result["positive_share_down"], 0.0)

    def test_t3_toy_hand_computed(self) -> None:
        records = {
            "d1": [_rec("A", 10, 0.00), _rec("B", 20, 0.20)],
            "d2": [_rec("A", 10, 0.00), _rec("B", 20, -0.20)],
        }
        labels = {"d1": ars.UPTREND, "d2": ars.DOWNTREND}
        result = ars.t3_separation(records, ["d1", "d2"], labels)
        # gap d1 = 0.20 - 0.10 = +0.10; gap d2 = -0.20 - (-0.10) = -0.10
        self.assertAlmostEqual(result["mean_up"], 0.10)
        self.assertAlmostEqual(result["mean_down"], -0.10)
        self.assertAlmostEqual(result["diff"], 0.20)
        self.assertTrue(result["bar_met"])
        self.assertIsNone(result["t_stat_up"])  # single date, no t-stat


# ---------------------------------------------------------------------------
# 3. S0 safety check and the go rule
# ---------------------------------------------------------------------------


def _passing_t1() -> dict:
    return {
        "diff": 0.05,
        "loo_min_across": 0.02,
        "loo_max_across": 0.09,
        "loo_worst_date_dropped": "2022-11-30",
        "loo_recomputed_without_worst": 0.02,
        "loo_sign_kept": True,
    }


def _material_t2() -> dict:
    return {
        "bar_met": True,
        "diff": 0.03,
        "loo_min_across": 0.01,
        "loo_max_across": 0.05,
        "loo_worst_date_dropped": "2022-05-31",
        "loo_recomputed_without_worst": 0.01,
        "loo_sign_kept": True,
    }


def _non_material_t3() -> dict:
    return {
        "bar_met": False,
        "diff": 0.005,
        "loo_min_across": -0.01,
        "loo_max_across": 0.02,
        "loo_worst_date_dropped": "2023-04-28",
        "loo_recomputed_without_worst": -0.01,
        "loo_sign_kept": False,
    }


class TestS0AndGoRule(unittest.TestCase):
    def _bundle_with_bear(self, bear_frame: pd.DataFrame):
        base = _market_frame(
            _market_rows(
                "2023-01-31", trailing60=0.05, sma200=1.10, vol60=0.40,
                regime="up", trend_ok=True,
            )
        )
        return ars.compute_regime_labels(base, bear_frame)

    def test_s0_stop_path_with_synthetic_bear_uptrend(self) -> None:
        # A would-be UPTREND date inside the bear sample: trend up, breadth
        # full, vol warm-up -> UPTREND fires despite the bear context.
        bear = _market_frame(
            _market_rows(
                "2022-01-31", trailing60=0.05, sma200=1.10, vol60=0.40,
                regime="down", trend_ok=False,
            )
        )
        bundle = self._bundle_with_bear(bear)
        bear_dates = sorted(bundle["bear_stats"])
        bear_up = [
            date for date in bear_dates
            if bundle["labels"]["R1"].get(date) == ars.UPTREND
        ]
        self.assertEqual(bear_up, ["2022-01-31"])
        verdict = ars.evaluate_e4b_go(
            bear_uptrend_dates=bear_up,
            t1=_passing_t1(), t2=_material_t2(), t3=_non_material_t3(),
        )
        self.assertEqual(verdict["verdict"], "NO_GO")
        gates = {gate["id"]: gate for gate in verdict["gates"]}
        self.assertFalse(gates["S0"]["pass"])
        self.assertIn("2022-01-31", gates["S0"]["detail"])

    def test_clean_bear_sample_passes_s0(self) -> None:
        bear = _market_frame(
            _market_rows(
                "2022-01-31", trailing60=-0.10, sma200=0.90, vol60=0.40,
                regime="down", trend_ok=False,
            )
        )
        bundle = self._bundle_with_bear(bear)
        bear_up = [
            date for date in sorted(bundle["bear_stats"])
            if bundle["labels"]["R1"].get(date) == ars.UPTREND
        ]
        self.assertEqual(bear_up, [])
        verdict = ars.evaluate_e4b_go(
            bear_uptrend_dates=bear_up,
            t1=_passing_t1(), t2=_material_t2(), t3=_non_material_t3(),
        )
        self.assertEqual(verdict["verdict"], "GO")
        qualifying = {item["cell"] for item in verdict["qualifying_cells"]}
        self.assertEqual(qualifying, {"T1", "T2"})

    def test_each_gate_failure_flips_to_no_go(self) -> None:
        cases = [
            ("T1 bar not met", {"diff": 0.01}, "T1"),
            ("no material cell",
             None, "MATERIAL"),
            ("drop-worst fails",
             {"diff": 0.05, "loo_sign_kept": False}, "DROP-WORST"),
        ]
        for label, t1_override, failed_gate in cases:
            t1 = _passing_t1()
            t2 = _material_t2()
            if t1_override is not None:
                t1.update(t1_override)
            if failed_gate == "MATERIAL":
                t2 = dict(_material_t2(), bar_met=False)
            verdict = ars.evaluate_e4b_go(
                bear_uptrend_dates=[], t1=t1, t2=t2,
                t3=_non_material_t3(),
            )
            gates = {gate["id"]: gate["pass"] for gate in verdict["gates"]}
            self.assertEqual(verdict["verdict"], "NO_GO", label)
            self.assertFalse(gates[failed_gate], label)


# ---------------------------------------------------------------------------
# 5. Forward-label firewall
# ---------------------------------------------------------------------------


class TestFirewall(unittest.TestCase):
    def test_indicator_functions_never_reference_forward_columns(self) -> None:
        self.assertTrue(ars.INDICATOR_SOURCE_FUNCTIONS)
        for name in ars.INDICATOR_SOURCE_FUNCTIONS:
            function = getattr(ars, name, None)
            self.assertTrue(callable(function), name)
            self.assertEqual(function.__module__, ars.__name__, name)
            source = inspect.getsource(function)
            self.assertNotIn("fwd_", source, name)
            self.assertNotIn("qqq_return_", source, name)


# ---------------------------------------------------------------------------
# 8. Anti-drift: shared decision rebuild
# ---------------------------------------------------------------------------


class TestAntiDrift(unittest.TestCase):
    def test_build_scope_records_identity(self) -> None:
        self.assertIs(ars.build_scope_records, rex.build_scope_records)
        self.assertIs(ars.cohort_member, rex.cohort_member)
        self.assertIs(ars.validate_disjoint_dates, rex.validate_disjoint_dates)

    def test_rebuild_records_uses_shared_build_scope_records(self) -> None:
        frame = pd.concat([
            _synthetic_group("2023-01-31"),
            _synthetic_group("2023-03-31"),
        ], ignore_index=True)
        calls = []
        real = ars.build_scope_records

        def wrapper(group, scope, variant, signal_date):
            calls.append((scope, variant, signal_date))
            return real(group, scope, variant, signal_date)

        ars.build_scope_records = wrapper
        try:
            patched = ars.rebuild_records({"base": frame})
        finally:
            ars.build_scope_records = real
        unpatched = ars.rebuild_records({"base": frame})
        self.assertEqual(len(calls), 2 * len(ars.SCOPES) * len(ars.VARIANTS))
        self.assertEqual(patched, unpatched)
        self.assertEqual(
            sorted({scope for scope, _, _ in calls}),
            sorted(ars.SCOPES),
        )


# ---------------------------------------------------------------------------
# 7. Output hygiene
# ---------------------------------------------------------------------------


class TestOutputHygiene(unittest.TestCase):
    def test_write_outputs_rejects_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            with self.assertRaises(ValueError):
                ars.write_outputs(out, {"bad.md": "see /home/user/file"})
            with self.assertRaises(ValueError):
                ars.write_outputs(out, {"bad.csv": "/tmp/scratch/x"})

    def test_write_outputs_writes_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            files = {"a.md": "hello\n", "b.csv": "x\n"}
            ars.write_outputs(out, files)
            sums = (out / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("a.md", sums)
            self.assertIn("b.csv", sums)
            for line in sums.splitlines():
                digest, name = line.split("  ", 1)
                actual = hashlib.sha256(
                    (out / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, name)

    def test_report_renders_without_absolute_paths(self) -> None:
        context = {
            "spec_rel": ars.SPEC_REL,
            "runner_rel": ars.RUNNER_SCRIPT_REL,
            "runner_sha": "deadbeef",
            "command": (
                "python scripts/audit_regime_separation.py "
                "--base-dataset outputs/x.csv --bear-2022-dataset "
                "outputs/y.csv --out-dir docs/leave_me_alone"
            ),
            "base": {"name": "x.csv", "rows": 2, "dates": 1, "sha": "aa"},
            "bear": {"name": "y.csv", "rows": 2, "dates": 1, "sha": "bb"},
            "n_merged_dates": 2,
            "merged_sequence": ["2022-01-31", "2023-01-31"],
            "base_sequence": ["2023-01-31"],
            "summary_rows": [],
            "verdict": ars.evaluate_e4b_go(
                bear_uptrend_dates=[],
                t1=_passing_t1(), t2=_material_t2(),
                t3=_non_material_t3(),
            ),
            "label_counts": {
                ars.PRIMARY_SAMPLE: {
                    "R0": {ars.UPTREND: 1, ars.DOWNTREND: 1, ars.NEUTRAL: 0},
                    "R1": {ars.UPTREND: 1, ars.DOWNTREND: 1, ars.NEUTRAL: 0},
                    "R2": {ars.UPTREND: 1, ars.DOWNTREND: 1, ars.NEUTRAL: 0},
                    "R1_SENS_LO": {
                        ars.UPTREND: 1, ars.DOWNTREND: 1, ars.NEUTRAL: 0},
                    "R1_SENS_HI": {
                        ars.UPTREND: 1, ars.DOWNTREND: 1, ars.NEUTRAL: 0},
                },
                "BASE_39_ONLY": {
                    "R0": {ars.UPTREND: 1, ars.DOWNTREND: 0, ars.NEUTRAL: 0},
                    "R1": {ars.UPTREND: 1, ars.DOWNTREND: 0, ars.NEUTRAL: 0},
                    "R2": {ars.UPTREND: 1, ars.DOWNTREND: 0, ars.NEUTRAL: 0},
                },
            },
            "out_dir_rel": "docs/leave_me_alone",
        }
        report = ars.render_report(context)
        self.assertFalse(ars.contains_absolute_path(report))
        self.assertIn("go/no-go verdict", report)
        self.assertIn("loose descriptive screen", report)


# ---------------------------------------------------------------------------
# End-to-end CLI (synthetic datasets, temp dir)
# ---------------------------------------------------------------------------


class TestEndToEndCli(unittest.TestCase):
    def test_cli_writes_commit_safe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv = tmp_path / "base.csv"
            bear_csv = tmp_path / "bear.csv"
            base = pd.concat([
                _synthetic_group(
                    "2023-01-31", qqq60=0.05, qqq20=0.01, regime="up",
                    trend_ok=True, trailing60=0.05, sma200=1.08, vol60=0.30),
                _synthetic_group(
                    "2023-03-31", qqq60=-0.04, qqq20=-0.02, regime="down",
                    trend_ok=False, trailing60=-0.06, sma200=0.95,
                    vol60=0.35),
            ], ignore_index=True)
            bear = pd.concat([
                _synthetic_group(
                    "2022-01-31", qqq60=-0.10, qqq20=-0.05, regime="down",
                    trend_ok=False, trailing60=-0.10, sma200=0.92,
                    vol60=0.45),
                _synthetic_group(
                    "2022-02-28", qqq60=-0.08, qqq20=-0.03, regime="down",
                    trend_ok=False, trailing60=-0.08, sma200=0.90,
                    vol60=0.45),
            ], ignore_index=True)
            base.to_csv(base_csv, index=False)
            bear.to_csv(bear_csv, index=False)
            out_dir = tmp_path / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = ars.main([
                    "--base-dataset", str(base_csv),
                    "--bear-2022-dataset", str(bear_csv),
                    "--out-dir", str(out_dir),
                ])
            self.assertEqual(exit_code, 0)
            names = {path.name for path in out_dir.iterdir()}
            self.assertEqual(names, {
                "separation_summary.csv",
                "per_date_regimes.csv",
                "tier_by_regime.csv",
                "report.md",
                "SHA256SUMS",
            })
            total = sum(path.stat().st_size for path in out_dir.iterdir())
            self.assertLess(total, ars.MAX_DIR_BYTES)
            for path in out_dir.iterdir():
                if path.name == "SHA256SUMS":
                    continue
                text = path.read_text(encoding="utf-8")
                self.assertFalse(
                    ars.contains_absolute_path(text), path.name)
            for line in (out_dir / "SHA256SUMS").read_text(
                encoding="utf-8"
            ).splitlines():
                digest, name = line.split("  ", 1)
                actual = hashlib.sha256(
                    (out_dir / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, name)
            report = (out_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("E4b go/no-go verdict", report)
            self.assertIn("S0 safety check", report)
            self.assertIn("no policy change", report)
            per_date = (out_dir / "per_date_regimes.csv").read_text(
                encoding="utf-8")
            self.assertIn("2022-01-31", per_date)
            self.assertIn("2023-01-31", per_date)
            summary = (out_dir / "separation_summary.csv").read_text(
                encoding="utf-8")
            self.assertIn("S0", summary)
            self.assertIn("R1", summary)

    def test_cli_rejects_overlapping_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv = tmp_path / "base.csv"
            _synthetic_group("2023-01-31").to_csv(base_csv, index=False)
            args = ars.parse_args([
                "--base-dataset", str(base_csv),
                "--bear-2022-dataset", str(base_csv),  # overlap
                "--out-dir", str(tmp_path / "out"),
            ])
            with self.assertRaises(ValueError):
                with contextlib.redirect_stdout(io.StringIO()):
                    ars.run(args)


if __name__ == "__main__":
    unittest.main()
