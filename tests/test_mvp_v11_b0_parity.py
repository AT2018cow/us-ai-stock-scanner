"""B0 reconciliation tests: only frozen rows, no API calls or outcomes."""
from __future__ import annotations

import unittest

import pandas as pd

from scripts.mvp_v11_b0_parity import compare_b0, _counts_row, _decision_rows
from ai_value_scanner.decision.integrated import build_stock_decisions


def _rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "symbol": sym,
            "signal_date": "2024-01-31",
            "fundamental_data_asof": "2024-01-20",
            "market_asof": "2024-01-31",
            "price_to_sma200": 1.05,
            "price_to_sma50": 1.03,
            "return_20d": 0.05,
            "return_60d": 0.10,
            "relative_strength_60d_qqq": 0.05,
            "drawdown_from_52w_high": 0.10,
            "fwd_ret_60": ret,
            "qqq_return_60": 0.02,
            "label_end_60": "2024-04-25",
        }
        for sym, ret in [("AAA", 0.50), ("BBB", -0.50)]
    ])


def _reference(rows: pd.DataFrame):
    no_labels = rows.drop(columns=["fwd_ret_60", "qqq_return_60", "label_end_60"])
    decisions = build_stock_decisions(
        no_labels, decision_date="2024-01-31",
        generated_at_utc="2024-01-31T23:59:59+00:00",
    )
    counted = _counts_row("2024-01-31", decisions)
    archive_rank = pd.DataFrame([{
        key: counted[key] for key in
        ("signal_date", "n_eligible", "n_non_avoid",
         "n_pr_total", "v1_top5", "v1_top15")
    }])
    archive_compact = pd.DataFrame([{
        "signal_date": "2024-01-31",
        "n_decisions": len(decisions),
        "n_non_avoid": counted["n_non_avoid"],
        **{key: counted[key] for key in (
            "priority_review_count", "watch_pullback_count",
            "watch_breakout_count", "hold_monitor_count", "avoid_count"
        )},
    }])
    archive_rows = pd.DataFrame(_decision_rows(decisions))
    return archive_rank, archive_compact, archive_rows


class TestB0ArchivedReconciliation(unittest.TestCase):
    def test_full_parity_compares_rows_and_aggregate(self) -> None:
        dataset = _rows()
        ranking, compact, rows = _reference(dataset)
        verdict, aggregates, issues = compare_b0(
            dataset, ranking, compact, reference_decisions=rows
        )
        self.assertEqual(verdict["verdict"], "B0_FULL_REFERENCE_PARITY_PASS")
        self.assertTrue(verdict["ready_for_candidate_returns"])
        self.assertTrue(issues.empty)
        self.assertEqual(aggregates.iloc[0]["n_eligible"], 2)

    def test_aggregate_only_does_not_claim_full_parity(self) -> None:
        dataset = _rows()
        ranking, compact, _ = _reference(dataset)
        report, _, issues = compare_b0(dataset, ranking, compact)
        self.assertEqual(report["verdict"], "B0_AGGREGATE_ONLY_PARTIAL")
        self.assertFalse(report["ready_for_candidate_returns"])
        self.assertTrue(issues.empty)

    def test_reference_score_mismatch_blocks(self) -> None:
        dataset = _rows()
        ranking, compact, rows = _reference(dataset)
        rows.loc[0, "entry_score"] = 0.001
        report, _, issues = compare_b0(
            dataset, ranking, compact, reference_decisions=rows
        )
        self.assertEqual(report["verdict"], "B0_MISMATCH_STOP")
        self.assertFalse(report["ready_for_candidate_returns"])
        self.assertIn("entry_score", set(issues["field"]))

    def test_reference_missing_date_blocks(self) -> None:
        dataset = _rows()
        ranking, compact, rows = _reference(dataset)
        ranking.loc[0, "signal_date"] = "2024-02-29"
        report, _, issues = compare_b0(
            dataset, ranking, compact, reference_decisions=rows
        )
        self.assertEqual(report["verdict"], "B0_MISMATCH_STOP")
        self.assertIn("archived_ranking", set(issues["field"]))

    def test_changing_future_returns_cannot_change_b0(self) -> None:
        dataset = _rows()
        ranking, compact, rows = _reference(dataset)
        changed = dataset.copy()
        changed["fwd_ret_60"] = [-999.0, 999.0]
        changed["qqq_return_60"] = [100.0, -100.0]
        changed["label_end_60"] = "2035-12-31"
        report, _, issues = compare_b0(
            changed, ranking, compact, reference_decisions=rows
        )
        self.assertEqual(report["verdict"], "B0_FULL_REFERENCE_PARITY_PASS")
        self.assertTrue(issues.empty)


if __name__ == "__main__":
    unittest.main()
