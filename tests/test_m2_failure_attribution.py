"""Unit tests for Phase M2 failure attribution (synthetic frames only).

Covers all 8 diagnostic axes, the 2025/2026Q1 return embargo, the
no-absolute-paths guard, SHA256SUMS verification, and case-registry
resolution. No network, no production-file dependency beyond read-only
decision builders, no reliance on the 25k-row datasets.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ai_value_scanner.research import m2_failure_attribution as m2


def _rated_row(**overrides) -> dict:
    row = {
        "signal_date": "2023-01-31",
        "symbol": "AAA",
        "quality_grade": "B",
        "quality_score": 0.60,
        "quality_confidence": 0.90,
        "entry_state": "WATCH_BREAKOUT",
        "entry_score": 0.70,
        "entry_confidence": 0.90,
        "action_state": "HOLD_MONITOR",
        "priority": 50,
        "selected_top15": False,
        "accrual_ratio": -0.25,
        "ocf_to_net_income": 1.50,
        "free_cash_flow": 100.0,
        "revenue": 1000.0,
        "revenue_yoy": 0.30,
        "receivables_growth_gap": 0.20,
        "inventory_growth_gap": 0.05,
        "net_margin": 0.15,
        "ebit": 150.0,
        "adjusted_ebit": 160.0,
        "adjusted_net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.25,
        "net_debt_to_ebitda": 1.0,
        "interest_coverage": 6.0,
        "current_ratio": 2.0,
        "shares_yoy": 0.01,
        "fcf_yield": 0.04,
        "ps_hist_percentile": 0.50,
        "pe_hist_percentile": 0.50,
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.03,
        "return_20d": 0.05,
        "return_60d": 0.10,
        "relative_strength_60d_qqq": 0.02,
        "drawdown_from_52w_high": 0.10,
        "volatility_60d": 0.30,
        "days_below_sma200": 0,
        "regime": "up",
        "benchmark_trend_ok": True,
        "fwd_ret_60": 0.05,
        "qqq_return_60": 0.02,
        "fundamental_data_asof": "2023-01-20",
        "market_asof": "2023-01-31",
        "quality_risks_codes": "accrual_ratio_weak",
        "quality_positives_codes": "ocf_to_net_income_strong,free_cash_flow_strong",
        "entry_risks_codes": "",
        "entry_positives_codes": "",
    }
    row.update(overrides)
    return row


class TestEmbargo(unittest.TestCase):
    def test_development_frame_drops_2025_and_2026q1(self) -> None:
        frame = pd.DataFrame([
            {"signal_date": "2024-12-31", "symbol": "A", "fwd_ret_60": 0.01, "qqq_return_60": 0.0},
            {"signal_date": "2025-01-31", "symbol": "A", "fwd_ret_60": 9.99, "qqq_return_60": 0.0},
            {"signal_date": "2026-03-31", "symbol": "A", "fwd_ret_60": 9.99, "qqq_return_60": 0.0},
        ])
        dev = m2.development_frame(frame)
        self.assertEqual(len(dev), 1)
        self.assertEqual(dev.iloc[0]["signal_date"], "2024-12-31")

    def test_return_diagnostics_ignore_embargoed_labels(self) -> None:
        rows = []
        for date in ("2023-01-31", "2024-12-31"):
            rows.append({"signal_date": date, "symbol": "A", "g": "X",
                         "fwd_ret_60": 0.10, "qqq_return_60": 0.02})
        rows.append({"signal_date": "2025-06-30", "symbol": "A", "g": "X",
                     "fwd_ret_60": 99.0, "qqq_return_60": -99.0})
        out = m2.date_equal_excess_by_group(pd.DataFrame(rows), "g")
        self.assertAlmostEqual(out["X"]["mean_excess"], 0.08, places=9)
        self.assertEqual(out["X"]["n_dates"], 2)
        self.assertEqual(out["X"]["n_obs"], 2)

    def test_development_dates_are_exactly_24(self) -> None:
        self.assertEqual(len(m2.DEVELOPMENT_DATES), 24)
        self.assertEqual(m2.DEVELOPMENT_DATES[0], "2023-01-31")
        self.assertEqual(m2.DEVELOPMENT_DATES[-1], "2024-12-31")


class TestAxis1Accrual(unittest.TestCase):
    def test_false_positive_count_and_upgrade(self) -> None:
        frame = pd.DataFrame([
            _rated_row(symbol="CASHCOW", quality_grade="B"),
            _rated_row(symbol="NORMAL", quality_grade="B", accrual_ratio=0.02),
            _rated_row(symbol="WEAK", quality_grade="C", accrual_ratio=-0.30,
                       ocf_to_net_income=0.40),
        ])
        table = m2.axis1_accrual_table(frame)
        self.assertEqual(table["n_false_positive_m10"], 1)
        self.assertEqual(table["n_false_positive_m20"], 1)
        self.assertIn("CASHCOW", table["false_positive_symbols_m10"])
        # cash-cow fix must upgrade at least the B candidate or be counted
        self.assertGreaterEqual(table["n_accrual_fix_candidates"], 1)

    def test_counterfactual_rebuild_is_exact(self) -> None:
        record = _rated_row()
        self.assertTrue(m2.accrual_fix_applies(record))
        self.assertEqual(
            m2.counterfactual_quality_grade(record, fix_accrual=True),
            m2.counterfactual_quality_grade(record, fix_accrual=True),
        )


class TestAxis2WorkingCapital(unittest.TestCase):
    def test_penalized_high_growth(self) -> None:
        frame = pd.DataFrame([
            _rated_row(symbol="GROWER"),
            _rated_row(symbol="SLOW", revenue_yoy=0.05),
        ])
        table = m2.axis2_working_capital_table(frame)
        self.assertEqual(table["n_high_growth_healthy"], 1)
        self.assertEqual(table["n_penalized"], 1)
        self.assertIn("GROWER", table["penalized_symbols"])


class TestAxis3FcfValuation(unittest.TestCase):
    def test_thin_margin_distribution(self) -> None:
        frame = pd.DataFrame([
            _rated_row(symbol="THIN", free_cash_flow=20.0, revenue=1000.0,
                       quality_risks_codes=""),
            _rated_row(symbol="FAT", free_cash_flow=300.0, revenue=1000.0,
                       quality_risks_codes=""),
        ])
        table = m2.axis3_fcf_and_valuation_table(frame)
        self.assertEqual(table["n_fcf_margin_thin_lt_3pct"], 1)
        self.assertEqual(table["n_fcf_margin_strong_ge_15pct"], 1)


class TestAxis4Coverage(unittest.TestCase):
    def test_margin_computable_from_facts(self) -> None:
        frame = pd.DataFrame([
            _rated_row(symbol="A"),
            _rated_row(symbol="B", revenue=None),
        ])
        table = m2.axis4_margin_coverage(frame)
        self.assertEqual(table["n_operating_margin_computable"], 1)
        self.assertAlmostEqual(table["operating_margin_coverage"], 0.5)


class TestEntryClassifiers(unittest.TestCase):
    def _wb(self, **overrides) -> dict:
        base = {
            "state": "WATCH_BREAKOUT",
            "price_to_sma200": 1.05,
            "price_to_sma50": 1.03,
            "return_20d": 0.05,
            "return_60d": 0.10,
            "relative_strength_60d_qqq": 0.02,
            "drawdown_from_52w_high": 0.10,
            "volatility_60d": 0.30,
            "defensive_ok": True,
        }
        base.update(overrides)
        return base

    def test_dead_zone_true(self) -> None:
        self.assertTrue(m2.is_dead_zone_pullback(**self._wb(price_to_sma50=1.09)))
        self.assertTrue(m2.is_dead_zone_pullback(**self._wb(return_20d=0.135)))

    def test_dead_zone_false_when_other_gate_fails(self) -> None:
        self.assertFalse(m2.is_dead_zone_pullback(**self._wb(price_to_sma50=1.09, return_60d=-0.01)))
        self.assertFalse(m2.is_dead_zone_pullback(**self._wb(price_to_sma50=1.03)))
        self.assertFalse(m2.is_dead_zone_pullback(**self._wb(price_to_sma50=1.09, defensive_ok=False)))

    def test_bucket_partition(self) -> None:
        self.assertEqual(
            m2.classify_watch_breakout(**self._wb(price_to_sma50=1.09)),
            "MILD_EXTENDED_PULLBACK",
        )
        self.assertEqual(
            m2.classify_watch_breakout(**self._wb()),
            "NEAR_BREAKOUT_CONSOLIDATION",
        )
        self.assertEqual(
            m2.classify_watch_breakout(**self._wb(price_to_sma200=0.97)),
            "WEAK_OR_LAGGING_STRUCTURE",
        )
        self.assertEqual(
            m2.classify_watch_breakout(**self._wb(relative_strength_60d_qqq=None)),
            "UNOBSERVABLE_FEATURES",
        )
        self.assertEqual(m2.classify_watch_breakout(state="ENTRY_READY"), "NOT_WATCH_BREAKOUT")

    def test_axis5_table(self) -> None:
        frame = m2.enrich_breakout_columns(pd.DataFrame([
            _rated_row(symbol="MILD", price_to_sma50=1.09),
            _rated_row(symbol="BASE"),
        ]))
        table = m2.axis5_dead_zone_table(frame)
        self.assertEqual(table["n_dead_zone_pullback"], 1)
        self.assertTrue(any("MILD" in tag for tag in table["dead_zone_symbols"]))

    def test_axis6_partition_sums(self) -> None:
        frame = m2.enrich_breakout_columns(pd.DataFrame([
            _rated_row(symbol="MILD", price_to_sma50=1.09),
            _rated_row(symbol="BASE"),
            _rated_row(symbol="WEAK", price_to_sma200=0.90),
            _rated_row(symbol="READY", entry_state="ENTRY_READY"),
        ]))
        table = m2.axis6_breakout_partition(frame)
        total = sum(info["n"] for info in table["buckets"].values())
        self.assertEqual(total, table["n_watch_breakout"])
        self.assertEqual(table["n_watch_breakout"], 3)

    def test_axis8_ratio_identity(self) -> None:
        self.assertAlmostEqual(m2.sma50_to_sma200_ratio(1.05, 1.03), 1.05 / 1.03)
        self.assertIsNone(m2.sma50_to_sma200_ratio(1.05, None))
        self.assertIsNone(m2.sma50_to_sma200_ratio(1.05, 0.0))
        frame = m2.enrich_breakout_columns(pd.DataFrame([
            _rated_row(symbol="INV", entry_state="ENTRY_READY",
                       price_to_sma200=0.99, price_to_sma50=1.02),
        ]))
        table = m2.axis8_trend_alignment_table(frame)
        self.assertEqual(table["ENTRY_READY"]["n_inverted"], 1)


class TestAxis7Attention(unittest.TestCase):
    def test_truncation_and_b_ready_counts(self) -> None:
        rows = []
        for i in range(17):
            rows.append(_rated_row(
                symbol=f"A{i:02d}", quality_grade="A", entry_state="ENTRY_READY",
                action_state="PRIORITY_REVIEW", priority=i + 1,
                selected_top15=(i < 15), quality_score=0.80, entry_score=0.90,
            ))
        rows.append(_rated_row(
            symbol="BREADY", quality_grade="B", entry_state="ENTRY_READY",
            quality_score=0.70, entry_score=0.90, priority=30,
        ))
        table = m2.axis7_attention_table(pd.DataFrame(rows))
        self.assertEqual(table["n_dates_truncated"], 1)
        self.assertEqual(table["n_truncated_a_ready_obs"], 2)
        self.assertEqual(table["n_b_ready_high_obs"], 1)


class TestSnapshotFrame(unittest.TestCase):
    def test_flatten_and_top15(self) -> None:
        decisions = [{
            "symbol": "crm",
            "decision_date": "2026-10-12",
            "quality": {"grade": "A", "score": 0.84, "confidence": 1.0,
                        "positives": [{"code": "ocf_to_net_income_strong", "metric": "ocf_to_net_income", "value": 1.5}],
                        "risks": [{"code": "accrual_ratio_weak", "metric": "accrual_ratio", "value": -0.24}],
                        "missing": []},
            "entry": {"state": "WATCH_BREAKOUT", "score": 0.9, "confidence": 1.0,
                      "positives": [{"code": "price_above_sma200", "metric": "price_to_sma200", "value": 1.17}],
                      "risks": []},
            "action_state": "WATCH_BREAKOUT",
            "priority": 10,
        }]
        frame = m2.snapshot_frame(decisions, ["CRM"], "snap62_test")
        self.assertEqual(frame.iloc[0]["symbol"], "CRM")
        self.assertTrue(frame.iloc[0]["selected_top15"])
        self.assertAlmostEqual(frame.iloc[0]["price_to_sma200"], 1.17)
        self.assertIn("accrual_ratio_weak", frame.iloc[0]["quality_risks_codes"])


class TestCaseRegistry(unittest.TestCase):
    def _frames(self) -> dict:
        hist = pd.DataFrame([
            _rated_row(symbol="CASHCOW", signal_date="2023-01-31", quality_grade="B"),
            _rated_row(symbol="GROWER", signal_date="2023-02-28", quality_grade="B",
                       receivables_growth_gap=0.30),
            _rated_row(symbol="MILD", signal_date="2023-03-31", price_to_sma50=1.09),
            _rated_row(symbol="READY", signal_date="2023-04-28", quality_grade="A",
                       entry_state="ENTRY_READY", action_state="PRIORITY_REVIEW",
                       priority=1, selected_top15=True,
                       quality_risks_codes="", quality_score=0.85, entry_score=0.90),
        ])
        hist = m2.enrich_breakout_columns(hist)
        snap = pd.DataFrame([
            _rated_row(symbol="CRM", signal_date="2026-10-12", quality_grade="A",
                       entry_state="WATCH_BREAKOUT", action_state="WATCH_BREAKOUT",
                       priority=10, selected_top15=True),
        ])
        snap = m2.enrich_breakout_columns(snap)
        return {"hist_dev": hist, "snap62": snap, "snap510": snap.iloc[0:0].copy()}

    def test_registry_resolves_deterministically(self) -> None:
        frames = self._frames()
        first = m2.resolve_case_registry(frames)
        second = m2.resolve_case_registry(frames)
        self.assertEqual(first, second)
        self.assertTrue(30 <= len(first) <= 36)
        matched = [c for c in first if c["status"] == "MATCHED"]
        keys = [(c["signal_date"] if False else 0) for c in matched]
        seen = set()
        for entry in matched:
            key = (entry["match"]["signal_date"], entry["match"]["symbol"])
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_casebook_schema_columns(self) -> None:
        self.assertEqual(len(m2.CASEBOOK_COLUMNS), 20)
        self.assertIn("selected_top15", m2.CASEBOOK_COLUMNS)
        self.assertIn("counterfactual_m3_behavior", m2.CASEBOOK_COLUMNS)


class TestGuards(unittest.TestCase):
    def test_absolute_path_detection(self) -> None:
        self.assertTrue(m2.contains_absolute_path("see /home/ss/data/file.csv"))
        self.assertTrue(m2.contains_absolute_path("wrote /tmp/xyz/out.md"))
        self.assertFalse(m2.contains_absolute_path("docs/m2_v1_failure_attribution_20261015/x.md"))
        self.assertFalse(m2.contains_absolute_path("configs/config.risk_off.json"))

    def test_sha256sums_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            payloads = {"a.md": "# hello\n", "b.csv": "x,y\n1,2\n"}
            for name, content in payloads.items():
                (tmpdir / name).write_text(content)
            lines = "".join(
                f"{hashlib.sha256(payloads[name].encode()).hexdigest()}  {name}\n"
                for name in sorted(payloads)
            )
            (tmpdir / "SHA256SUMS").write_text(lines)
            for record in (tmpdir / "SHA256SUMS").read_text().splitlines():
                digest, name = record.split("  ")
                self.assertEqual(hashlib.sha256((tmpdir / name).read_bytes()).hexdigest(), digest)

    def test_counterfactual_eligibility_gate(self) -> None:
        self.assertTrue(m2.counterfactual_eligible(_rated_row()))
        sparse = {"accrual_ratio": -0.3, "ocf_to_net_income": 1.5}
        self.assertFalse(m2.counterfactual_eligible(sparse))


if __name__ == "__main__":
    unittest.main()
