"""Extended replay evaluation runner tests (offline, synthetic fixtures).

Covers `scripts/run_extended_replay_evaluation.py`: forward-regime segment
partitioning (with stitched-dataset overlap rejection), FULL vs ETF_SLICE
rebuild/ranking, cohort economics and severe-loss math, the E0 reproduction
tolerance checker, and an end-to-end CLI run into a temporary directory
(no network, no writes to the repo `cache/`).
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_extended_replay_evaluation as rex  # noqa: E402


def _base_row(**overrides):
    row = {
        "signal_date": "2023-01-31",
        "market_asof": "2023-01-31",
        "fundamental_data_asof": "2022-11-01",
        "regime": "up",
        "benchmark_trend_ok": True,
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
    qqq60: float = -0.05,
    qqq20: float = 0.01,
    regime: str = "down",
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


def _synthetic_dataset() -> pd.DataFrame:
    frames = [
        _synthetic_group("2023-01-31", qqq60=-0.05, qqq20=0.01, regime="down"),
        _synthetic_group("2023-03-31", qqq60=0.04, qqq20=-0.02, regime="up"),
    ]
    return pd.concat(frames, ignore_index=True)


def _rec(
    symbol: str,
    *,
    priority: int = 1,
    action: str = "PRIORITY_REVIEW",
    grade: str = "A",
    state: str = "ENTRY_READY",
    fwd60: float | None = None,
    exc60: float | None = None,
    fwd20: float | None = None,
    exc20: float | None = None,
    fwd120: float | None = None,
    exc120: float | None = None,
    sma: float | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "priority": priority,
        "action_state": action,
        "grade": grade,
        "entry_state": state,
        "price_to_sma200": sma,
        "fwd_ret_20": fwd20,
        "excess_20": exc20,
        "fwd_ret_60": fwd60,
        "excess_60": exc60,
        "fwd_ret_120": fwd120,
        "excess_120": exc120,
    }


class TestSegmentPartitioning(unittest.TestCase):
    def test_forward_and_trailing_segments(self) -> None:
        meta = {
            "2023-01-31": {"qqq_return_60": -0.10, "qqq_return_20": 0.02,
                           "regime": "down"},
            "2023-02-28": {"qqq_return_60": 0.05, "qqq_return_20": -0.03,
                           "regime": "up"},
            "2023-03-31": {"qqq_return_60": 0.0, "qqq_return_20": 0.0,
                           "regime": "up"},
        }
        segments = rex.build_segments(meta)
        self.assertEqual(segments["FWD_DRAWDOWN_60D"], ["2023-01-31"])
        self.assertEqual(segments["FWD_BULL_60D"], ["2023-02-28", "2023-03-31"])
        self.assertEqual(segments["FWD_DRAWDOWN_20D"], ["2023-02-28"])
        self.assertEqual(segments["FWD_BULL_20D"], ["2023-01-31", "2023-03-31"])
        self.assertEqual(segments["TRAILING_DOWN"], ["2023-01-31"])
        self.assertEqual(segments["TRAILING_UP"], ["2023-02-28", "2023-03-31"])
        self.assertEqual(segments["BASE_ALL_39"],
                         ["2023-01-31", "2023-02-28", "2023-03-31"])

    def test_bear_2022_stitching(self) -> None:
        base_meta = {
            "2023-06-30": {"qqq_return_60": -0.08, "qqq_return_20": 0.01,
                           "regime": "down"},
        }
        bear_meta = {
            "2022-01-31": {"qqq_return_60": -0.12, "qqq_return_20": -0.09,
                           "regime": "down"},
            "2022-03-31": {"qqq_return_60": 0.06, "qqq_return_20": 0.04,
                           "regime": "up"},
        }
        segments = rex.build_segments(base_meta, bear_meta)
        self.assertEqual(segments["BEAR_2022"], ["2022-01-31", "2022-03-31"])
        self.assertEqual(segments["BEAR_2022_FWD_DRAWDOWN_60D"], ["2022-01-31"])
        self.assertEqual(
            segments["COMBINED_DRAWDOWN_60D"], ["2022-01-31", "2023-06-30"])

    def test_overlap_rejection(self) -> None:
        with self.assertRaises(ValueError):
            rex.validate_disjoint_dates({
                "base": ["2023-01-31", "2023-02-28"],
                "bear": ["2022-12-30", "2023-01-31"],
            })
        rex.validate_disjoint_dates({
            "base": ["2023-01-31"],
            "bear": ["2022-12-30"],
        })

    def test_date_meta_extraction(self) -> None:
        frame = _synthetic_dataset()
        meta = rex.dataset_date_meta(frame)
        self.assertEqual(meta["2023-01-31"]["qqq_return_60"], -0.05)
        self.assertEqual(meta["2023-01-31"]["regime"], "down")
        self.assertEqual(meta["2023-03-31"]["qqq_return_20"], -0.02)


class TestFullVsEtfSlice(unittest.TestCase):
    def test_slice_filtering_and_reranking(self) -> None:
        group = _synthetic_group()
        full = rex.build_scope_records(group, "FULL", "v1_current", "2023-01-31")
        slice_ = rex.build_scope_records(
            group, "ETF_SLICE", "v1_current", "2023-01-31")
        full_by_symbol = {record["symbol"]: record for record in full}
        slice_by_symbol = {record["symbol"]: record for record in slice_}
        # count-0 (NASDAQ-screen-only) row: present in FULL, absent in SLICE
        self.assertIn("AAA", full_by_symbol)
        self.assertNotIn("AAA", slice_by_symbol)
        self.assertEqual(len(full), 4)
        self.assertEqual(len(slice_), 3)
        # priorities re-ranked within the slice: BBB is 2 in FULL, 1 in SLICE
        self.assertEqual(full_by_symbol["BBB"]["priority"], 2)
        self.assertEqual(slice_by_symbol["BBB"]["priority"], 1)
        self.assertEqual(
            sorted(record["priority"] for record in slice_),
            [1, 2, 3],
        )
        # forward excess attached: BBB fwd_ret_60 = 0.06 vs qqq_60 = -0.05
        self.assertAlmostEqual(
            full_by_symbol["BBB"]["excess_60"], 0.06 - (-0.05)
        )

    def test_v2_variant_uses_production_policy(self) -> None:
        group = _synthetic_group()
        records = rex.build_scope_records(
            group, "ETF_SLICE", "v2_current", "2023-01-31")
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r["grade"] == "A" for r in records))


class TestCohortEconomicsMath(unittest.TestCase):
    def _records_by_date(self):
        return {
            "d1": [
                _rec("A", fwd60=0.20, exc60=0.00),
                _rec("B", fwd60=-0.25, exc60=-0.30),
            ],
            "d2": [
                _rec("C", fwd60=0.10, exc60=0.20),
                _rec("D", fwd60=None, exc60=None),
            ],
        }

    def test_date_equal_means_and_matured_counts(self) -> None:
        summary = rex.segment_cohort_summary(
            self._records_by_date(), ["d1", "d2"], lambda record: True)
        self.assertEqual(summary["n_dates_60"], 2)
        self.assertEqual(summary["obs_60"], 3)
        self.assertAlmostEqual(summary["mean_excess_60"], 0.025)
        self.assertAlmostEqual(summary["median_excess_60"], 0.025)
        self.assertAlmostEqual(summary["worst_date_excess_60"], -0.15)
        self.assertAlmostEqual(summary["win_rate_vs_qqq_60"], 0.5)
        self.assertAlmostEqual(summary["mean_raw_ret_60"], 0.0375)

    def test_severe_loss_and_underperform_rates(self) -> None:
        summary = rex.segment_cohort_summary(
            self._records_by_date(), ["d1", "d2"], lambda record: True)
        # d1 share = 1/2 (fwd -0.25), d2 share = 0/1 (NaN excluded) -> 0.25
        self.assertAlmostEqual(summary["severe_loss_rate_60"], 0.25)
        # excess <= -0.20: d1 = 1/2, d2 = 0/1 -> 0.25
        self.assertAlmostEqual(summary["severe_underperform_rate_60"], 0.25)

    def test_missing_labels_do_not_count_as_matured(self) -> None:
        summary = rex.segment_cohort_summary(
            self._records_by_date(), ["d2"], lambda record: True)
        self.assertEqual(summary["n_dates_60"], 1)
        self.assertEqual(summary["obs_60"], 1)
        self.assertAlmostEqual(summary["severe_loss_rate_60"], 0.0)

    def test_cohort_member_predicates(self) -> None:
        self.assertTrue(rex.cohort_member(_rec("A", priority=5), "TOP5"))
        self.assertFalse(rex.cohort_member(_rec("A", priority=6), "TOP5"))
        self.assertTrue(rex.cohort_member(_rec("A", priority=15), "TOP15"))
        self.assertTrue(rex.cohort_member(
            _rec("A", action="PRIORITY_REVIEW"), "PRIORITY_REVIEW"))
        self.assertTrue(rex.cohort_member(_rec("A", grade="A"), "QUALITY_A"))
        self.assertTrue(rex.cohort_member(
            _rec("A", state="ENTRY_READY"), "ENTRY_READY"))
        self.assertTrue(rex.cohort_member(_rec("A"), "UNIVERSE"))

    def test_sma200_bucket_boundaries(self) -> None:
        self.assertTrue(rex.sma200_bucket_match(0.99, None, 1.00))
        self.assertFalse(rex.sma200_bucket_match(1.00, None, 1.00))
        self.assertTrue(rex.sma200_bucket_match(1.00, 1.00, 1.25))
        self.assertTrue(rex.sma200_bucket_match(1.44, 1.35, 1.45))
        self.assertFalse(rex.sma200_bucket_match(1.45, 1.35, 1.45))
        self.assertTrue(rex.sma200_bucket_match(1.46, 1.45, None))
        self.assertFalse(rex.sma200_bucket_match(1.45, 1.45, None))
        self.assertFalse(rex.sma200_bucket_match(None, 1.00, 1.25))


class TestReproductionCheck(unittest.TestCase):
    def _computed_row(self, **overrides):
        row = {
            "universe_scope": "FULL",
            "segment": "BASE_ALL_39",
            "variant": "v1_current",
            "cohort": "TOP5",
            "n_dates_60": 39,
            "obs_60": 195,
            "mean_excess_60": "-0.024323",
            "median_excess_60": "-0.047257",
            "worst_date_excess_60": "-0.235891",
            "mean_excess_20": "-0.006203",
            "mean_excess_120": "-0.027414",
        }
        row.update(overrides)
        return row

    def _reference_row(self, **overrides):
        row = {
            "period": "ALL_39_DATES",
            "variant": "v1_current",
            "cohort": "TOP5",
            "n_dates_60": "39",
            "obs_60": "195",
            "mean_excess_60": "-0.024323",
            "median_excess_60": "-0.047257",
            "worst_excess_60": "-0.235891",
            "mean_excess_20": "-0.006203",
            "mean_excess_120": "-0.027414",
        }
        row.update(overrides)
        return row

    def test_pass_within_tolerance(self) -> None:
        result = rex.reproduction_check(
            [self._computed_row()],
            [self._reference_row(mean_excess_60="-0.024328")],
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["n_checked"], 1)
        self.assertEqual(result["n_mismatches"], 0)

    def test_fail_beyond_tolerance_reports_mismatch(self) -> None:
        result = rex.reproduction_check(
            [self._computed_row()],
            [self._reference_row(mean_excess_60="-0.030000")],
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["n_mismatches"], 1)
        self.assertIn("mean_excess_60", result["mismatches"][0])

    def test_count_mismatch_fails(self) -> None:
        result = rex.reproduction_check(
            [self._computed_row()],
            [self._reference_row(obs_60="196")],
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("obs_60", result["mismatches"][0])

    def test_missing_reference(self) -> None:
        result = rex.reproduction_check([self._computed_row()], [])
        self.assertEqual(result["status"], "MISSING_REFERENCE")

    def test_extra_cohorts_skipped_not_mismatched(self) -> None:
        extra = self._computed_row(cohort="UNIVERSE")
        result = rex.reproduction_check(
            [self._computed_row(), extra],
            [self._reference_row()],
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["n_checked"], 1)
        self.assertEqual(result["n_skipped_extra"], 1)

    def test_load_reference_rows_reads_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e0_current_cohorts.csv"
            pd.DataFrame([self._reference_row()]).to_csv(path, index=False)
            rows = rex.load_reference_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["period"], "ALL_39_DATES")
        self.assertEqual(rex.load_reference_rows(path), [])


class TestEndToEndCli(unittest.TestCase):
    def _cache_snapshot(self):
        cache_dir = Path("cache")
        if not cache_dir.exists():
            return []
        return sorted(
            (str(path.relative_to(cache_dir)), path.stat().st_mtime_ns)
            for path in cache_dir.rglob("*")
            if path.is_file()
        )

    def test_cli_writes_deterministic_outputs(self) -> None:
        base_csv = None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv = tmp_path / "company_quality_dataset.csv"
            _synthetic_dataset().to_csv(base_csv, index=False)
            out_dir = tmp_path / "out"
            reference_dir = tmp_path / "no_reference"
            before = self._cache_snapshot()
            exit_code = rex.main([
                "--base-dataset", str(base_csv),
                "--base-reference-dir", str(reference_dir),
                "--output-dir", str(out_dir),
            ])
            after = self._cache_snapshot()
            self.assertEqual(exit_code, 0)
            self.assertEqual(before, after)
            names = {path.name for path in out_dir.iterdir()}
            self.assertEqual(names, {
                "cohort_economics_by_regime.csv",
                "paired_deltas_by_regime.csv",
                "rank_tiers_by_regime.csv",
                "entry_and_extension_crosscut.csv",
                "report.md",
                "SHA256SUMS",
            })
            total = sum(path.stat().st_size for path in out_dir.iterdir())
            self.assertLess(total, rex.MAX_DIR_BYTES)
            for path in out_dir.iterdir():
                if path.name == "SHA256SUMS":
                    continue
                text = path.read_text(encoding="utf-8")
                self.assertFalse(rex.contains_absolute_path(text), path.name)
            # SHA256SUMS digests verify
            for line in (out_dir / "SHA256SUMS").read_text().splitlines():
                digest, name = line.split("  ", 1)
                actual = hashlib.sha256(
                    (out_dir / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, name)
            report = (out_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("MISSING_REFERENCE", report)
            self.assertIn("FWD_DRAWDOWN_60D", report)

    def test_cli_rejects_overlapping_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv = tmp_path / "base.csv"
            bear_csv = tmp_path / "bear.csv"
            base = _synthetic_dataset()
            base.to_csv(base_csv, index=False)
            (base[base["signal_date"] == "2023-03-31"]
             .assign(signal_date="2022-12-30")).to_csv(bear_csv, index=False)
            args = rex.parse_args([
                "--base-dataset", str(base_csv),
                "--bear-2022-dataset", str(base_csv),  # same dates -> overlap
                "--output-dir", str(tmp_path / "out"),
            ])
            with self.assertRaises(ValueError):
                rex.run(args)

    def test_cli_with_bear_dataset_adds_bear_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv = tmp_path / "base.csv"
            bear_csv = tmp_path / "bear.csv"
            _synthetic_dataset().to_csv(base_csv, index=False)
            bear = _synthetic_group(
                "2022-06-30", qqq60=-0.12, qqq20=-0.04, regime="down")
            bear.to_csv(bear_csv, index=False)
            out_dir = tmp_path / "out"
            exit_code = rex.main([
                "--base-dataset", str(base_csv),
                "--bear-2022-dataset", str(bear_csv),
                "--base-reference-dir", str(tmp_path / "nope"),
                "--output-dir", str(out_dir),
            ])
            self.assertEqual(exit_code, 0)
            cohort_text = (
                out_dir / "cohort_economics_by_regime.csv"
            ).read_text(encoding="utf-8")
            self.assertIn("BEAR_2022", cohort_text)
            self.assertIn("COMBINED_DRAWDOWN_60D", cohort_text)
            self.assertIn("BEAR_2022", (out_dir / "report.md").read_text(
                encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
