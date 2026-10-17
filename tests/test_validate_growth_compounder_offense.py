"""Growth-compounder offense validation tests (offline, synthetic fixtures).

Covers `scripts/validate_growth_compounder_offense.py`: C1 slow-growth
deduction / compounder bonus, the C2 six-condition offense gate with backfill,
C3 barbell 8+7 construction, top-5 contributor exclusion math, and an
end-to-end CLI run into a temporary directory (no network, no repo cache
writes).
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

import validate_growth_compounder_offense as val  # noqa: E402
from ai_value_scanner.decision.integrated import build_stock_decisions  # noqa: E402
from ai_value_scanner.decision.model import stock_decisions_to_jsonl  # noqa: E402


def _rec(
    symbol: str,
    *,
    q=0.80,
    e=0.90,
    grade="A",
    action="PRIORITY_REVIEW",
    entry_state="ENTRY_READY",
    rev=0.20,
    ocf=1.0,
    sma=1.05,
    rs=0.05,
    nonop=False,
    pre=False,
    priority=1,
) -> dict:
    return {
        "symbol": symbol,
        "priority": priority,
        "action_state": action,
        "grade": grade,
        "quality_score": q,
        "entry_score": e,
        "entry_state": entry_state,
        "pre_earnings": pre,
        "nonop": nonop,
        "price_to_sma200": sma,
        "revenue_yoy": rev,
        "ocf_to_net_income": ocf,
        "relative_strength_60d_qqq": rs,
        "fwd_ret_20": None,
        "excess_20": None,
        "fwd_ret_60": None,
        "excess_60": None,
        "fwd_ret_120": None,
        "excess_120": None,
    }


def _row(**overrides) -> dict:
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


def _group(date: str, qqq60: float, qqq20: float, regime: str) -> pd.DataFrame:
    from datetime import date as _date, timedelta

    signal_day = _date.fromisoformat(date)
    rows = []
    for index, symbol in enumerate(("AAA", "BBB", "CCC", "DDD")):
        row = _row(
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


def _dataset() -> pd.DataFrame:
    return pd.concat([
        _group("2023-01-31", -0.05, 0.01, "down"),
        _group("2023-03-31", 0.04, -0.02, "up"),
    ], ignore_index=True)


def _bear_dataset() -> pd.DataFrame:
    return _group("2022-06-30", -0.12, -0.04, "down")


class TestC1SlowGrowthDeCrowding(unittest.TestCase):
    def test_slow_growth_deduction_exact(self) -> None:
        fast = _rec("FAST", rev=0.20)
        slow = _rec("SLOW", rev=0.05)
        # base = 0.60*0.80 + 0.40*0.90 = 0.84; fast +0.05, slow -0.08
        self.assertAlmostEqual(val.c1_priority_score(fast), 0.89, places=9)
        self.assertAlmostEqual(val.c1_priority_score(slow), 0.76, places=9)
        self.assertEqual(val.c1_ranking([slow, fast]), ["FAST", "SLOW"])

    def test_missing_revenue_counts_as_slow(self) -> None:
        record = _rec("MISS", rev=None)
        self.assertAlmostEqual(
            val.c1_priority_score(record), 0.76, places=9)

    def test_compounder_bonus_blocked_by_nonop(self) -> None:
        plain = _rec("PLN", rev=0.20, ocf=1.0)
        blocked = _rec("BLK", rev=0.20, ocf=1.0, nonop=True)
        # blocked also loses the -0.06 nonoperating penalty
        self.assertAlmostEqual(
            val.c1_priority_score(plain), 0.89, places=9)
        self.assertAlmostEqual(
            val.c1_priority_score(blocked), 0.78, places=9)

    def test_bonus_requires_ocf_and_revenue_floor(self) -> None:
        weak_ocf = _rec("OCF", rev=0.20, ocf=0.79)
        low_rev = _rec("REV", rev=0.14)
        self.assertAlmostEqual(
            val.c1_priority_score(weak_ocf), 0.84, places=9)
        self.assertAlmostEqual(
            val.c1_priority_score(low_rev), 0.84, places=9)

    def test_penalties_applied(self) -> None:
        pre = _rec("PRE", rev=0.20, pre=True)
        self.assertAlmostEqual(val.c1_priority_score(pre), 0.83, places=9)


class TestC2OffenseGate(unittest.TestCase):
    def test_ready_and_watch_pullback_eligible(self) -> None:
        self.assertTrue(val.is_offense_compounder(_rec("R")))
        self.assertTrue(val.is_offense_compounder(
            _rec("W", entry_state="WATCH_PULLBACK")))

    def test_each_condition_can_reject(self) -> None:
        cases = {
            "grade C": _rec("G", grade="C"),
            "score floor": _rec("Q", q=0.67),
            "nonop": _rec("N", nonop=True),
            "revenue": _rec("V", rev=0.14),
            "ocf": _rec("O", ocf=0.79),
            "entry state": _rec("S", entry_state="TREND_DAMAGED"),
            "sma floor": _rec("L", sma=0.99),
            "sma cap": _rec("H", sma=1.61),
            "missing sma": _rec("M", sma=None),
            "rs": _rec("Z", rs=-0.01),
            "missing rs": _rec("Y", rs=None),
        }
        for label, record in cases.items():
            with self.subTest(label=label):
                self.assertFalse(val.is_offense_compounder(record))

    def test_backfill_when_fewer_than_15_qualify(self) -> None:
        records = [
            _rec("OFF1", rev=0.30, rs=0.20),
            _rec("OFF2", rev=0.25, rs=0.10),
            _rec("SLOW1", rev=0.05),
            _rec("SLOW2", rev=0.05),
            _rec("SLOW3", rev=0.05),
        ]
        c1_order = val.c1_ranking(records)
        c2_order = val.c2_ranking(records, c1_order)
        # eligible compounders first, then C1-order backfill (no dupes)
        self.assertEqual(c2_order[:2], ["OFF1", "OFF2"])
        self.assertEqual(sorted(c2_order), sorted(
            ["OFF1", "OFF2", "SLOW1", "SLOW2", "SLOW3"]))
        self.assertEqual(len(set(c2_order)), len(c2_order))

    def test_offense_score_clips_and_penalty(self) -> None:
        record = _rec("X", q=0.80, rev=0.50, rs=0.30)
        # 0.80 + 0.5*0.5 + 0.5*0.3 = 1.20
        self.assertAlmostEqual(val.offense_score(record), 1.20, places=9)
        pre = _rec("P", q=0.80, rev=0.50, rs=0.30, pre=True)
        self.assertAlmostEqual(val.offense_score(pre), 1.14, places=9)


class TestC3Barbell(unittest.TestCase):
    def _universe(self):
        return (
            [_rec(f"OFF{i}", rev=0.30, rs=0.20, q=0.75) for i in range(10)]
            + [_rec(f"DEF{i}", rev=0.05) for i in range(10)]
        )

    def test_barbell_8_plus_7_dedup(self) -> None:
        records = self._universe()
        c1_order = val.c1_ranking(records)
        eligible = [
            str(r["symbol"]) for r in records
            if val.is_offense_compounder(r)
        ]
        c3 = val.c3_components(records, c1_order, eligible)
        self.assertEqual(len(set(c3["ranked"][:15])), 15)
        self.assertTrue(all(s not in c3["anchors"] for s in c3["offense"]))
        self.assertEqual(len(c3["anchors"]), 8)
        self.assertLessEqual(len(c3["offense"]), 7)

    def test_top5_is_three_plus_two_non_overlapping(self) -> None:
        records = self._universe()
        c1_order = val.c1_ranking(records)
        eligible = [
            str(r["symbol"]) for r in records
            if val.is_offense_compounder(r)
        ]
        c3 = val.c3_components(records, c1_order, eligible)
        self.assertEqual(len(c3["top5"]), 5)
        self.assertEqual(c3["top5"][:3], c1_order[:3])
        self.assertTrue(
            all(s not in c3["top5"][:3] for s in c3["top5"][3:]))

    def test_top15_sets_via_public_helper(self) -> None:
        records = self._universe()
        rankings = val.candidate_rankings(records)
        top5, top15 = val.top5_top15(
            "C3_barbell_top15", rankings["C3_barbell_top15"])
        self.assertEqual(len(top5), 5)
        self.assertEqual(len(top15), 15)
        self.assertTrue(top5.issubset(top15))


class TestContributorExclusion(unittest.TestCase):
    def _records(self):
        def rec(symbol, exc60, fwd60):
            record = _rec(symbol)
            record["excess_60"] = exc60
            record["fwd_ret_60"] = fwd60
            return record

        return {
            "d1": [
                rec("A", 0.20, -0.10),
                rec("B", 0.10, 0.10),
                rec("C", 0.05, 0.05),
            ],
            "d2": [
                rec("A", 0.30, 0.00),
                rec("B", -0.40, -0.30),
                rec("C", 0.02, 0.02),
            ],
        }

    def test_top_contributors_by_positive_cumulative_excess(self) -> None:
        records = self._records()
        dates = ["d1", "d2"]
        sets = {date: {"A", "B", "C"} for date in dates}
        self.assertEqual(
            val.top_contributors(records, dates, sets, k=2), ["A", "B"])
        self.assertEqual(
            val.top_contributors(records, dates, sets, k=5),
            ["A", "B", "C"])

    def test_exclusion_changes_date_equal_stats(self) -> None:
        records = self._records()
        dates = ["d1", "d2"]
        sets = {date: {"A", "B", "C"} for date in dates}
        full = val.set_stats(records, dates, sets)
        # d1 mean 0.1167, d2 mean -0.0267 -> date-equal -0.045
        self.assertAlmostEqual(
            full["mean_excess_60"], (0.35 / 3 + -0.08 / 3) / 2, places=9)
        excluded = val.set_stats(records, dates, sets, exclude={"A"})
        # d1 (0.10+0.05)/2 = 0.075; d2 (-0.40+0.02)/2 = -0.19
        self.assertAlmostEqual(
            excluded["mean_excess_60"], (0.075 - 0.19) / 2, places=9)
        # severe loss (fwd <= -0.2): d1 no member -> 0.0, d2 B -0.30 -> 0.5
        self.assertAlmostEqual(excluded["severe_loss_rate_60"], 0.25, places=9)


class TestEndToEndCli(unittest.TestCase):
    def test_cli_writes_six_files_without_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_csv = tmp_path / "base.csv"
            bear_csv = tmp_path / "bear.csv"
            snapshot = tmp_path / "snapshot.jsonl"
            _dataset().to_csv(base_csv, index=False)
            _bear_dataset().to_csv(bear_csv, index=False)
            sample = _group("2023-01-31", -0.05, 0.01, "down")
            decisions = build_stock_decisions(
                sample,
                decision_date="2023-01-31",
                generated_at_utc="2023-01-31T00:00:00Z",
                policy_version="v2",
            )
            snapshot.write_text(
                stock_decisions_to_jsonl(decisions), encoding="utf-8")
            out_dir = tmp_path / "out"
            exit_code = val.main([
                "--base-dataset", str(base_csv),
                "--bear-2022-dataset", str(bear_csv),
                "--snapshot-jsonl", str(snapshot),
                "--cache-dir", str(tmp_path / "empty-cache"),
                "--output-dir", str(out_dir),
            ])
            self.assertEqual(exit_code, 0)
            names = {path.name for path in out_dir.iterdir()}
            self.assertEqual(names, {
                "candidate_cohort_economics.csv",
                "paired_deltas_vs_v2.csv",
                "robustness_ex_top5_and_episodes.csv",
                "snap_20261015_top15_comparison.csv",
                "report.md",
                "SHA256SUMS",
            })
            total = sum(path.stat().st_size for path in out_dir.iterdir())
            self.assertLess(total, 160 * 1024)
            for path in out_dir.iterdir():
                text = path.read_text(encoding="utf-8")
                self.assertFalse(
                    val.replay.contains_absolute_path(text), path.name)
            for line in (out_dir / "SHA256SUMS").read_text().splitlines():
                digest, name = line.split("  ", 1)
                actual = hashlib.sha256(
                    (out_dir / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, name)
            report = (out_dir / "report.md").read_text(encoding="utf-8")
            for header in (
                "## Gate 1", "## Gate 2", "## Gate 3", "## Gate 4",
                "## Verdict inputs", "## Explicit recommendation",
            ):
                self.assertIn(header, report)
            snapshot_csv = (
                out_dir / "snap_20261015_top15_comparison.csv"
            ).read_text(encoding="utf-8")
            self.assertIn("v2_baseline", snapshot_csv)
            self.assertIn("C3_barbell_top15", snapshot_csv)
            economics = (
                out_dir / "candidate_cohort_economics.csv"
            ).read_text(encoding="utf-8")
            for candidate in val.CANDIDATES:
                self.assertIn(candidate, economics)


if __name__ == "__main__":
    unittest.main()
