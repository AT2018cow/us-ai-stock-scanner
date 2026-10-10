from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.decision import (
    ActionState,
    EntryDecision,
    EntryState,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.reporting.snapshot import write_decision_snapshot


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from run_mvp_full_scan import build_parser as build_full_scan_parser
    from validate_mvp_snapshot import validate_snapshot
finally:
    sys.path.pop(0)


def _decision() -> StockDecision:
    return StockDecision(
        schema_version="1",
        symbol="AAA",
        company_name="AAA Corp",
        decision_date="2026-10-10",
        generated_at_utc="2026-10-10T12:00:00+00:00",
        quality=QualityDecision(
            grade=QualityGrade.A,
            score=0.85,
            confidence=0.95,
            component_scores={"profitability_cash": 0.9},
            positives=(),
            risks=(),
            missing=(),
            data_asof="2026-08-01",
        ),
        entry=EntryDecision(
            state=EntryState.ENTRY_READY,
            score=0.80,
            confidence=0.95,
            positives=(),
            risks=(),
            market_asof="2026-10-09",
        ),
        action_state=ActionState.PRIORITY_REVIEW,
        priority=1,
        rationale=(),
        review_trigger="Review now.",
        source_lists=(),
        provenance={"synthetic": True},
    )


class TestMvpSnapshotValidator(unittest.TestCase):
    def test_valid_snapshot_passes(self) -> None:
        decision = _decision()
        with tempfile.TemporaryDirectory() as td:
            paths = write_decision_snapshot(
                output_root=td,
                strategy_style="risk_off",
                decisions=(decision,),
                daily_attention=(decision,),
                weekly_attention=(decision,),
                generated_at_utc=decision.generated_at_utc,
                decision_date=decision.decision_date,
                config_fingerprint="cfg",
                code_sha="abc",
            )

            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["decisions"], 1)
            self.assertEqual(result["counts"]["daily_attention"], 1)
            self.assertEqual(
                result["counts"]["action"]["PRIORITY_REVIEW"],
                1,
            )

    def test_renderer_drift_is_a_hard_failure(self) -> None:
        decision = _decision()
        with tempfile.TemporaryDirectory() as td:
            paths = write_decision_snapshot(
                output_root=td,
                strategy_style="risk_off",
                decisions=(decision,),
                daily_attention=(decision,),
                weekly_attention=(decision,),
                generated_at_utc=decision.generated_at_utc,
                decision_date=decision.decision_date,
                config_fingerprint="cfg",
            )
            paths.action_list_md.write_text(
                "# tampered\n",
                encoding="utf-8",
            )

            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any(
                    "action_list.md does not match" in error
                    for error in result["errors"]
                )
            )


class TestMvpFullScanRunnerCli(unittest.TestCase):
    def test_default_is_repeatable_experiment_on_compatibility_base(self) -> None:
        args = build_full_scan_parser().parse_args([])
        self.assertEqual(args.config, "configs/config.risk_off.json")
        self.assertFalse(args.formal)
        self.assertEqual(args.attention_cap, 15)
        self.assertFalse(args.skip_unit_tests)

    def test_formal_mode_is_explicit(self) -> None:
        args = build_full_scan_parser().parse_args(["--formal"])
        self.assertTrue(args.formal)


if __name__ == "__main__":
    unittest.main()
