"""Unit tests for Phase M0 read-only baseline inventory and human-review audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from ai_value_scanner.research.m0_baseline_review import (
    ATTRIBUTION_AXES,
    FROZEN_M0_CASE_SPECS,
    WORKSHEET_COLUMNS,
    build_worksheet_rows,
    scan_silent_entry_gates,
    sha256_file,
    write_m0_deliverables,
)


def _synthetic_decision(
    symbol: str,
    *,
    priority: int,
    action: str = "PRIORITY_REVIEW",
    grade: str = "A",
    q_score: float = 0.85,
    e_state: str = "ENTRY_READY",
    e_score: float = 0.90,
    e_risks: list[dict] | None = None,
    cik: str | None = "0000123456",
    decision_date: str = "2026-10-12",
) -> dict:
    return {
        "symbol": symbol,
        "decision_date": decision_date,
        "priority": priority,
        "action_state": action,
        "quality": {
            "grade": grade,
            "score": q_score,
            "confidence": 1.0,
            "data_asof": "2026-08-01",
            "positives": [{"code": "net_margin_strong", "value": 0.25}],
            "risks": [],
            "missing": [],
        },
        "entry": {
            "state": e_state,
            "score": e_score,
            "confidence": 1.0,
            "market_asof": decision_date,
            "positives": [{"code": "market_data_fresh", "value": 0}],
            "risks": e_risks if e_risks is not None else [],
        },
        "provenance": {"cik": cik} if cik else {},
    }


class TestM0BaselineReview(unittest.TestCase):
    def test_frozen_case_specs_are_unique_and_valid(self) -> None:
        self.assertEqual(len(FROZEN_M0_CASE_SPECS), 18)
        ids = [s.study_case_id for s in FROZEN_M0_CASE_SPECS]
        self.assertEqual(len(ids), len(set(ids)))
        for spec in FROZEN_M0_CASE_SPECS:
            self.assertIn(spec.primary_attribution_axis, ATTRIBUTION_AXES)
            self.assertIn(spec.worth_human_review_yn_unknown, {"Y", "N", "unknown"})
            self.assertIn(spec.snapshot_key, {"snap62", "snap510"})

    def test_scan_silent_entry_gates_detects_breakout_and_damaged_gaps(self) -> None:
        decisions = [
            _synthetic_decision("READY1", priority=1, e_state="ENTRY_READY", e_risks=[]),
            _synthetic_decision("WB_SILENT", priority=2, e_state="WATCH_BREAKOUT", e_risks=[]),
            _synthetic_decision(
                "WB_EXPLICIT",
                priority=3,
                e_state="WATCH_BREAKOUT",
                e_risks=[{"code": "relative_strength_60d_qqq_weak", "value": -0.12}],
            ),
            _synthetic_decision(
                "TD_SILENT_DAYS",
                priority=4,
                e_state="TREND_DAMAGED",
                e_risks=[{"code": "price_extended_above_sma50", "value": 1.11}],
            ),
            _synthetic_decision(
                "TD_EXPLICIT",
                priority=5,
                e_state="TREND_DAMAGED",
                e_risks=[{"code": "price_materially_below_sma200", "value": 0.91}],
            ),
        ]
        found = scan_silent_entry_gates(decisions)
        self.assertEqual(found["watch_breakout_zero_entry_risks"], ["WB_SILENT"])
        self.assertEqual(found["trend_damaged_without_damage_risk_item"], ["TD_SILENT_DAYS"])

    def test_write_m0_deliverables_end_to_end_on_synthetic_snapshots(self) -> None:
        snap62_syms = [s.symbol for s in FROZEN_M0_CASE_SPECS if s.snapshot_key == "snap62"]
        snap510_syms = [s.symbol for s in FROZEN_M0_CASE_SPECS if s.snapshot_key == "snap510"]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s62_dir = root / "snap62"
            s510_dir = root / "snap510"
            out_dir = root / "out"
            s62_dir.mkdir()
            s510_dir.mkdir()

            s62_rows = [
                _synthetic_decision(sym, priority=i + 1, decision_date="2026-10-12")
                for i, sym in enumerate(snap62_syms)
            ]
            s510_rows = [
                _synthetic_decision(sym, priority=i + 16, cik=None, decision_date="2026-10-09")
                for i, sym in enumerate(snap510_syms)
            ]

            (s62_dir / "decisions.jsonl").write_text(
                "\n".join(json.dumps(r) for r in s62_rows) + "\n", encoding="utf-8"
            )
            (s62_dir / "run_manifest.json").write_text(
                json.dumps({"daily_symbols": snap62_syms[:6]}), encoding="utf-8"
            )
            (s510_dir / "decisions.jsonl").write_text(
                "\n".join(json.dumps(r) for r in s510_rows) + "\n", encoding="utf-8"
            )
            (s510_dir / "run_manifest.json").write_text(
                json.dumps({"daily_symbols": []}), encoding="utf-8"
            )

            hashes = write_m0_deliverables(
                output_dir=out_dir,
                snap510_dir=s510_dir,
                snap62_dir=s62_dir,
                git_main_sha="a" * 40,
                evidence_branch_sha="b" * 40,
            )
            self.assertEqual(
                set(hashes.keys()),
                {
                    "attention_failure_cases.md",
                    "baseline_inventory.md",
                    "human_review_worksheet.csv",
                    "review_gate.json",
                },
            )
            with (out_dir / "human_review_worksheet.csv").open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(tuple(reader.fieldnames or ()), WORKSHEET_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 18)

            gate = json.loads((out_dir / "review_gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["verdict"], "GO_FOR_M1_CORRECTNESS_ENGINEERING")
            self.assertFalse(gate["forward_returns_inspected"])
            self.assertFalse(gate["production_v1_policy_modified"])
            self.assertEqual(gate["network_requests_made"], 0)
            self.assertTrue(gate["m1_entry_criteria_met"])

    def test_committed_m0_deliverables_match_sha256sums(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        m0_dir = repo_root / "docs" / "m0_baseline_review_20261014"
        sums_path = m0_dir / "SHA256SUMS"
        self.assertTrue(sums_path.is_file())
        lines = [
            line.strip()
            for line in sums_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 4)
        for line in lines:
            digest, filename = line.split("  ", 1)
            self.assertEqual(sha256_file(m0_dir / filename), digest)


if __name__ == "__main__":
    unittest.main()
