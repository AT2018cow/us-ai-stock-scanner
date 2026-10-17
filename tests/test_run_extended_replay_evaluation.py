"""Extended replay evaluation runner tests (offline, synthetic fixtures).

Covers `scripts/run_extended_replay_evaluation.py`: forward-regime segment
partitioning (with stitched-dataset overlap rejection), FULL vs ETF_SLICE
rebuild/ranking, cohort economics and severe-loss math, the E0 reproduction
tolerance checker, and an end-to-end CLI run into a temporary directory
(no network, no writes to the repo `cache/`).
"""

from __future__ import annotations

import hashlib
import json
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


class TestWindowOverlapAndEpisodes(unittest.TestCase):
    """§6.3: 60d window-overlap disclosure and episode-cluster aggregation."""

    _META = {
        "2023-06-30": {"qqq_label_end_60": "2023-09-26", "regime": "up"},
        "2023-07-31": {"qqq_label_end_60": "2023-10-24", "regime": "up"},
        "2024-11-29": {"qqq_label_end_60": "2025-02-28", "regime": "up"},
        "2024-12-31": {"qqq_label_end_60": "2025-03-31", "regime": "up"},
        "2025-01-31": {"qqq_label_end_60": "2025-04-29", "regime": "up"},
        "2025-10-31": {"qqq_label_end_60": "2026-01-29", "regime": "up"},
        "2025-11-28": {"qqq_label_end_60": "2026-02-26", "regime": "up"},
        "2025-12-31": {"qqq_label_end_60": "2026-03-30", "regime": "up"},
    }

    def test_forward_window_overlap_flags(self) -> None:
        dates = sorted(self._META)
        flags = rex.forward_window_overlaps(dates, self._META)
        self.assertFalse(flags["2023-06-30"])
        self.assertTrue(flags["2023-07-31"])
        self.assertFalse(flags["2024-11-29"])
        self.assertTrue(flags["2024-12-31"])
        self.assertTrue(flags["2025-01-31"])
        self.assertFalse(flags["2025-10-31"])
        self.assertTrue(flags["2025-11-28"])
        self.assertTrue(flags["2025-12-31"])

    def test_missing_label_end_cannot_overlap(self) -> None:
        flags = rex.forward_window_overlaps(
            ["2023-01-31", "2023-02-28"], {"2023-01-31": {}})
        self.assertEqual(
            flags, {"2023-01-31": False, "2023-02-28": False})

    def test_episode_cluster_assignment_canonical_names(self) -> None:
        clusters, episodes = rex.assign_episode_clusters(
            sorted(self._META), self._META)
        self.assertEqual(clusters["2023-06-30"], "EP1_2023Q3")
        self.assertEqual(clusters["2023-07-31"], "EP1_2023Q3")
        self.assertEqual(clusters["2024-11-29"], "EP2_2024Q4_2025Q1")
        self.assertEqual(clusters["2024-12-31"], "EP2_2024Q4_2025Q1")
        self.assertEqual(clusters["2025-01-31"], "EP2_2024Q4_2025Q1")
        self.assertEqual(clusters["2025-10-31"], "EP3_2025Q4")
        self.assertEqual(clusters["2025-12-31"], "EP3_2025Q4")
        self.assertEqual(
            [name for name, _ in episodes],
            ["EP1_2023Q3", "EP2_2024Q4_2025Q1", "EP3_2025Q4"],
        )
        self.assertEqual([len(dates) for _, dates in episodes], [2, 3, 3])

    def test_bear_episode_single_cluster(self) -> None:
        dates = ["2022-01-31", "2022-02-28", "2022-06-30"]
        clusters, episodes = rex.assign_episode_clusters(
            dates, {}, bear=True)
        self.assertEqual(set(clusters.values()), {"EP0_BEAR_2022"})
        self.assertEqual(episodes, [("EP0_BEAR_2022", dates)])

    def _episode_records(self):
        def rec(symbol, exc60, fwd60):
            return {
                "symbol": symbol,
                "priority": 1,
                "action_state": "PRIORITY_REVIEW",
                "grade": "A",
                "entry_state": "ENTRY_READY",
                "price_to_sma200": 1.0,
                "fwd_ret_20": None,
                "excess_20": None,
                "fwd_ret_60": fwd60,
                "excess_60": exc60,
                "fwd_ret_120": None,
                "excess_120": None,
            }

        return {
            "FULL": {
                "v1_current": {
                    "d1": [rec("A", 0.2, -0.3), rec("B", -0.2, 0.1)],
                    "d2": [rec("C", 0.4, 0.2), rec("D", 0.2, 0.1)],
                    "d3": [rec("E", 0.6, 0.3), rec("F", 0.4, 0.2)],
                    "b1": [rec("G", -0.1, -0.25), rec("H", -0.3, -0.4)],
                },
                "v2_current": {},
            },
            "ETF_SLICE": {"v1_current": {}, "v2_current": {}},
        }

    def test_episode_equal_weight_math(self) -> None:
        summary = rex.compute_episode_cluster_summary(
            self._episode_records(),
            [("EPA", ["d1"]), ("EPB", ["d2", "d3"]),
             ("EP0_BEAR_2022", ["b1"])],
            fwd_episode_names=["EPA", "EPB"],
            all_episode_names=["EPA", "EPB", "EP0_BEAR_2022"],
        )
        row = next(
            row for row in summary["rows"]
            if row["universe_scope"] == "FULL"
            and row["variant"] == "v1_current"
            and row["cohort"] == "UNIVERSE"
        )
        values = row["episode_values"]
        # d1 mean = (0.2 + -0.2)/2 = 0.0; d2 mean = 0.3; d3 mean = 0.5
        self.assertAlmostEqual(values["EPA"]["mean_excess_60"], 0.0)
        self.assertAlmostEqual(values["EPB"]["mean_excess_60"], 0.4)
        self.assertAlmostEqual(
            values["EP0_BEAR_2022"]["mean_excess_60"], -0.2)
        # cluster-equal means: equal weight per episode, not per date
        self.assertAlmostEqual(
            row["fwd_drawdown_episode_equal_mean_excess_60"], 0.2)
        self.assertAlmostEqual(
            row["all_drawdown_episode_equal_mean_excess_60"],
            (0.0 + 0.4 - 0.2) / 3.0,
        )
        # severe loss: d1 = 1/2, b1 = 2/2 (both members <= -0.20)
        self.assertAlmostEqual(values["EPA"]["severe_loss_rate_60"], 0.5)
        self.assertAlmostEqual(values["EPB"]["severe_loss_rate_60"], 0.0)
        self.assertAlmostEqual(
            values["EP0_BEAR_2022"]["severe_loss_rate_60"], 1.0)
        self.assertAlmostEqual(
            row["fwd_drawdown_episode_equal_severe_loss_60"], 0.25)
        # date-equal over d1+d2+d3: means 0.0, 0.3, 0.5 -> 0.2667
        date_equal = summary["date_equal"][
            "FULL|v1_current|UNIVERSE"]["mean_excess_60"]
        self.assertAlmostEqual(date_equal, (0.0 + 0.3 + 0.5) / 3.0)


class TestBear2022Provenance(unittest.TestCase):
    """§6.1/§6.2: commit-safe 2022 provenance + split-repair audit artifacts."""

    def _write_bear_bundle(self, tmp: Path):
        run = tmp / "run"
        repaired = run / "repaired"
        modal = run / "modal_download" / "datasets"
        frozen = run / "frozen_inputs"
        for directory in (repaired, modal, frozen):
            directory.mkdir(parents=True, exist_ok=True)
        base_csv = tmp / "base.csv"
        _synthetic_dataset().to_csv(base_csv, index=False)
        bear = pd.concat([
            _synthetic_group(
                "2022-06-30", qqq60=-0.12, qqq20=-0.04, regime="down"),
            _synthetic_group(
                "2022-09-30", qqq60=0.05, qqq20=0.02, regime="down"),
        ], ignore_index=True)
        bear_csv = repaired / "company_quality_dataset_risk_off.repaired.csv"
        bear.to_csv(bear_csv, index=False)
        (repaired / "company_quality_discontinuities.csv").write_text(
            "symbol,prev_date,date,null_labels\n"
            "ABTC,2022-07-29,2022-08-31,True\n"
            "XYZ,2022-01-31,2022-02-28,False\n",
            encoding="utf-8",
        )
        (modal / "company_quality_dataset_risk_off.csv").write_text(
            "symbol\nAAA\n", encoding="utf-8")
        (modal / "company_quality_dataset_risk_off.meta.json").write_text(
            json.dumps({
                "scan_config": "/root/configs/config.risk_off.json",
                "watchlist_csv_path": "/root/data/ai_watchlist.csv",
                "generated_utc": "2026-10-17T07:17:06+00:00",
                "pre_snapshot_universe": "union",
                "allow_latest_watchlist_fallback": False,
            }),
            encoding="utf-8",
        )
        (modal / "company_quality_dataset_risk_off.SUCCESS.json").write_text(
            json.dumps({
                "output": (
                    "/root/research/run_x/datasets/"
                    "company_quality_dataset_risk_off.csv"
                ),
                "spec": {
                    "run_id": "run_x",
                    "code_sha": "abc123",
                    "start_date": "2022-01-01",
                    "end_date": "2022-12-31",
                    "style": "risk_off",
                    "dataset_kind": "company_quality",
                },
                "status": "success",
            }),
            encoding="utf-8",
        )
        (modal / "company_quality_dataset_risk_off.splits.json").write_text(
            '{"events": {}}', encoding="utf-8")
        (frozen / "ai_watchlist.csv").write_text(
            "symbol,bucket\nAAA,core_ai\n", encoding="utf-8")
        (frozen / "config.risk_off.json").write_text("{}", encoding="utf-8")
        return base_csv, bear_csv, modal, repaired

    def test_bear_provenance_files_generated_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv, bear_csv, modal, repaired = self._write_bear_bundle(
                tmp_path)
            out_dir = tmp_path / "out"
            exit_code = rex.main([
                "--base-dataset", str(base_csv),
                "--bear-2022-dataset", str(bear_csv),
                "--base-reference-dir", str(tmp_path / "no_reference"),
                "--output-dir", str(out_dir),
            ])
            self.assertEqual(exit_code, 0)
            prov_text = (
                out_dir / "bear_2022_provenance.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn("/root/", prov_text)
            self.assertFalse(rex.contains_absolute_path(prov_text))
            provenance = json.loads(prov_text)
            self.assertEqual(provenance["run_id"], "run_x")
            self.assertEqual(provenance["code_sha"], "abc123")
            self.assertEqual(
                provenance["generated_utc"], "2026-10-17T07:17:06+00:00")
            self.assertEqual(provenance["n_dates"], 2)
            self.assertEqual(provenance["n_rows"], 8)
            self.assertEqual(provenance["n_unique_symbols"], 4)
            self.assertEqual(
                provenance["meta_summary"]["scan_config"],
                "configs/config.risk_off.json",
            )
            self.assertEqual(
                provenance["sha256"]["repaired_csv"],
                hashlib.sha256(bear_csv.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                provenance["sha256"]["splits_json"],
                hashlib.sha256(
                    (modal / "company_quality_dataset_risk_off.splits.json")
                    .read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(provenance["discontinuities_rows"], 2)
            self.assertEqual(provenance["discontinuities_flagged"], 1)
            # discontinuities CSV is an exact copy
            self.assertEqual(
                (out_dir / "bear_2022_discontinuities.csv").read_bytes(),
                (repaired / "company_quality_discontinuities.csv")
                .read_bytes(),
            )
            # SHA256SUMS covers both new files and all digests verify
            sums = (out_dir / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("bear_2022_provenance.json", sums)
            self.assertIn("bear_2022_discontinuities.csv", sums)
            for line in sums.splitlines():
                digest, name = line.split("  ", 1)
                actual = hashlib.sha256(
                    (out_dir / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, name)
            # all outputs commit-safe
            for path in out_dir.iterdir():
                text = path.read_text(encoding="utf-8")
                self.assertFalse(rex.contains_absolute_path(text), path.name)
                self.assertNotIn("/root/", text, path.name)
            report = (out_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("## 2b.", report)
            self.assertIn("EP0_BEAR_2022", report)
            self.assertIn("run_id `run_x`", report)
            self.assertIn("bear_2022_provenance.json", report)


if __name__ == "__main__":
    unittest.main()
