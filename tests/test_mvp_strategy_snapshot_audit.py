from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from audit_mvp_strategy_snapshot import (
        audit_decisions,
        audit_snapshot,
        render_markdown,
    )
finally:
    sys.path.pop(0)


def _decision(symbol: str, priority: int, grade: str, entry: str, action: str):
    return {
        "symbol": symbol,
        "priority": priority,
        "decision_date": "2026-10-09",
        "quality": {"grade": grade},
        "entry": {"state": entry},
        "action_state": action,
        "provenance": {
            "code_sha": "fixedsha",
            "watchlist_bucket": "core_ai,ai_peripheral" if symbol == "AAA" else "ai_smallcap",
            "fundamental_edgartools_fallback_used": symbol == "FFF",
        },
    }


def _fixture():
    rows = [
        _decision("AAA", 1, "A", "ENTRY_READY", "PRIORITY_REVIEW"),
        _decision("BBB", 2, "A", "ENTRY_READY", "PRIORITY_REVIEW"),
        _decision("CCC", 3, "B", "ENTRY_READY", "HOLD_MONITOR"),
        _decision("DDD", 4, "A", "TREND_DAMAGED", "HOLD_MONITOR"),
        _decision("EEE", 5, "A", "WATCH_BREAKOUT", "WATCH_BREAKOUT"),
        _decision("FFF", 6, "A", "ENTRY_READY", "PRIORITY_REVIEW"),
    ]
    manifest = {
        "decision_date": "2026-10-09",
        "code_sha": "fixedsha",
        "config_fingerprint": "cfg",
        "counts": {"decisions": 6},
        "daily_symbols": ["AAA", "BBB"],
        "weekly_symbols": ["AAA", "BBB"],
    }
    return rows, manifest


class TestMvpStrategySnapshotAudit(unittest.TestCase):
    def test_exposes_routing_and_attention_compression_without_tuning(self):
        rows, manifest = _fixture()
        result = audit_decisions(rows, manifest, attention_cap=2)
        self.assertEqual(result["scope"], "single_date_cross_section_not_performance_evidence")
        self.assertEqual(result["priority_review_total"], 3)
        self.assertEqual(result["priority_review_omitted"]["daily"], ["FFF"])
        self.assertEqual(result["priority_review_omitted"]["weekly"], ["FFF"])
        self.assertEqual(result["b_entry_ready"]["symbols_by_rank"], ["CCC"])
        self.assertEqual(result["a_trend_damaged"]["count"], 1)
        self.assertEqual(result["watch_breakout"]["quality_counts"], {"A": 1})
        self.assertEqual(result["fallback_used"], 1)
        self.assertEqual(result["priority_review_discovery_bucket_memberships"],
                         {"ai_peripheral": 1, "ai_smallcap": 2, "core_ai": 1})
        report = render_markdown(result)
        self.assertIn("Cross-sectional", report)
        self.assertIn("FFF", report)

    def test_rejects_action_drift_and_provenance_mismatch(self):
        rows, manifest = _fixture()
        rows[0]["action_state"] = "WATCH_PULLBACK"
        with self.assertRaisesRegex(ValueError, "Action disagrees"):
            audit_decisions(rows, manifest, attention_cap=2)
        rows, manifest = _fixture()
        rows[0]["provenance"]["code_sha"] = "other"
        with self.assertRaisesRegex(ValueError, "code SHA"):
            audit_decisions(rows, manifest, attention_cap=2)

    def test_rejects_duplicate_symbols_and_invalid_attention(self):
        rows, manifest = _fixture()
        rows[1]["symbol"] = "AAA"
        with self.assertRaisesRegex(ValueError, "duplicate symbol"):
            audit_decisions(rows, manifest, attention_cap=2)
        rows, manifest = _fixture()
        manifest["daily_symbols"] = ["AAA", "unknown"]
        with self.assertRaisesRegex(ValueError, "unknown symbols"):
            audit_decisions(rows, manifest, attention_cap=2)
        rows, manifest = _fixture()
        with self.assertRaisesRegex(ValueError, "positive"):
            audit_decisions(rows, manifest, attention_cap=0)

    def test_read_only_snapshot_directory_entrypoint(self):
        rows, manifest = _fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (root / "decisions.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            before = (root / "decisions.jsonl").read_bytes()
            result = audit_snapshot(root, attention_cap=2)
            self.assertEqual(result["decisions"], 6)
            self.assertEqual(before, (root / "decisions.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
