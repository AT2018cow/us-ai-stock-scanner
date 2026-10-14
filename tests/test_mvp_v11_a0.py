from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ai_value_scanner.decision.model import (
    ActionState, EntryDecision, EntryState, QualityDecision,
    QualityGrade, StockDecision, EvidenceItem,
)
from ai_value_scanner.research.mvp_v11 import (
    R_CANDIDATES, RISK_CODES, inspect_frozen_dataset, rank_offline,
)


def _decision(
    symbol: str, quality_score: float | None, entry_score: float,
    *, grade: QualityGrade = QualityGrade.A, risk: bool = False,
) -> StockDecision:
    risk_items = (EvidenceItem(
        code="free_cash_flow_weak", label="weak FCF", polarity="negative",
        metric=None, value=None, threshold=None, message="weak FCF",
    ),) if risk else ()
    return StockDecision(
        schema_version="1", symbol=symbol, company_name=None,
        decision_date="2024-01-31", generated_at_utc="2024-02-01T00:00:00Z",
        quality=QualityDecision(
            grade=grade, score=quality_score, confidence=0.9,
            component_scores={}, positives=(), risks=risk_items,
            missing=(), data_asof="2024-01-30",
        ),
        entry=EntryDecision(
            state=EntryState.ENTRY_READY, score=entry_score,
            confidence=0.95, positives=(), risks=(), market_asof="2024-01-31",
        ),
        action_state=ActionState.PRIORITY_REVIEW,
        priority=0, rationale=(), review_trigger=None,
        source_lists=(), provenance={},
    )


class TestHistoricalV11Ranking(unittest.TestCase):
    def test_b0_matches_canonical_quality_first(self) -> None:
        decisions = [_decision("AAA", .9, .1), _decision("BBB", .7, .9)]
        self.assertEqual(
            [x.symbol for x in rank_offline(decisions, candidate_id="B0")],
            ["AAA", "BBB"],
        )
        self.assertEqual(
            [x.priority for x in rank_offline(decisions, candidate_id="B0")],
            [1, 2],
        )

    def test_r2_can_change_order_without_changing_state_or_grade(self) -> None:
        decisions = [_decision("AAA", .9, .1), _decision("BBB", .7, .9)]
        result = rank_offline(decisions, candidate_id="R2")
        self.assertEqual([x.symbol for x in result], ["BBB", "AAA"])
        self.assertTrue(all(x.action_state is ActionState.PRIORITY_REVIEW for x in result))

    def test_missing_score_falls_back_not_imputed(self) -> None:
        decisions = [_decision("AAA", None, .99), _decision("BBB", .2, .2)]
        result = rank_offline(decisions, candidate_id="R3")
        self.assertEqual([x.symbol for x in result], ["BBB", "AAA"])

    def test_risk_code_can_change_order_but_only_within_grade(self) -> None:
        self.assertIn("free_cash_flow_weak", RISK_CODES)
        decisions = [
            _decision("AAA", .75, .75, risk=True),
            _decision("BBB", .74, .75),
            _decision("CCC", 1.0, 1.0, grade=QualityGrade.B),
        ]
        ranked = rank_offline(decisions, candidate_id="R5")
        self.assertEqual([x.symbol for x in ranked], ["BBB", "AAA", "CCC"])

    def test_rejects_unregistered_or_cross_date(self) -> None:
        with self.assertRaises(ValueError):
            rank_offline([], candidate_id="R99")
        with self.assertRaises(ValueError):
            rank_offline(
                [_decision("AAA", .8, .8),
                 replace(_decision("BBB", .8, .8), decision_date="2024-02-29")],
                candidate_id="R1",
            )

    def test_candidate_registry_has_fixed_non_cartesian_count(self) -> None:
        self.assertEqual(len(R_CANDIDATES), 5)
        registry = json.loads((
            Path(__file__).resolve().parents[1]
            / "configs/mvp_v11_candidate_registry.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(
            [x["id"] for x in registry["candidates"]],
            ["B0", "R1", "R2", "R3", "R4", "R5",
             "E1", "E2", "E3", "E4", "X1"],
        )


class TestHistoricalV11DatasetGate(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "entry_quality_v3.csv"
        self.meta = self.path.with_suffix(".meta.json")
        self.frame = pd.DataFrame([{
            "symbol": "AAA", "signal_date": "2024-01-31",
            "fundamental_data_asof": "2024-01-20",
            "market_asof": "2024-01-31",
            "fwd_ret_20": .10, "qqq_return_20": .03,
        }])
        self.meta.write_text(json.dumps({
            "dataset_kind": "entry_quality", "pre_strategy_cross_section": True,
            "n_rows": 1,
        }), encoding="utf-8")

    def inspect(self) -> dict:
        self.frame.to_csv(self.path, index=False)
        return inspect_frozen_dataset(self.path, expected_kind="entry_quality")

    def test_structural_pass_not_misrepresented_as_parity(self) -> None:
        report = self.inspect()
        self.assertEqual(report["n_rows"], 1)
        self.assertEqual(report["label_coverage"]["20"]["n_paired_valid"], 1)
        self.assertEqual(report["label_coverage"]["120"]["n_paired_valid"], 0)
        self.assertIn("UNVERIFIED", report["status"])
        self.assertEqual(len(report["dataset_sha256"]), 64)

    def test_v3_csv_accepts_explicit_original_metadata_path(self) -> None:
        self.frame.to_csv(self.path, index=False)
        v3 = self.path.with_name("entry_quality_dataset_risk_off.v3.csv")
        self.path.rename(v3)
        result = inspect_frozen_dataset(
            v3, expected_kind="entry_quality", metadata=self.meta
        )
        self.assertEqual(result["n_rows"], 1)
        self.assertEqual(result["metadata_path"], str(self.meta.resolve()))
        with self.assertRaisesRegex(ValueError, "missing dataset or sibling metadata"):
            inspect_frozen_dataset(v3, expected_kind="entry_quality")

    def test_future_data_is_rejected(self) -> None:
        self.frame.loc[0, "market_asof"] = "2024-02-01"
        with self.assertRaisesRegex(ValueError, "future"):
            self.inspect()

    def test_same_day_duplicate_rejected(self) -> None:
        self.frame = pd.concat([self.frame, self.frame], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.inspect()

    def test_missing_dataset_kind_rejected(self) -> None:
        self.meta.write_text(json.dumps({
            "pre_strategy_cross_section": True,
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dataset_kind"):
            self.inspect()


if __name__ == "__main__":
    unittest.main()
