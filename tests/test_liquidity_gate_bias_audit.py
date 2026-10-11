from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_PATH))
try:
    from audit_liquidity_gate_bias import audit_frozen_evidence, render_markdown
finally:
    sys.path.pop(0)


def _make_evidence(root):
    members = [
        ("KEEP", "core_ai", "1"),
        ("KEEP", "ai_enabler", "1"),
        ("SMALL", "ai_smallcap", "1"),
        ("NOMAP", "core_ai", "1"),
        ("DISABLED", "ai_smallcap", "0"),
    ]
    with (root / "ai_watchlist.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("symbol", "bucket", "enabled"))
        writer.writerows(members)
    decisions = [{"symbol": "KEEP"}]
    exclusions = [
        {
            "symbol": "SMALL",
            "reason_code": "DOLLAR_VOLUME_BELOW_MIN",
            "dollar_volume": 1_400_000,
            "market_data_feed": "iex",
        },
        {"symbol": "NOMAP", "reason_code": "SEC_MAPPING_MISSING"},
    ]
    manifest = {
        "decision_date": "2026-10-09",
        "code_sha": "abc123",
        "candidate_universe": {
            "discovery_unique_symbols": 3,
            "decision_universe_symbols": 1,
            "excluded_symbols": 2,
            "exclusion_reason_counts": {
                "DOLLAR_VOLUME_BELOW_MIN": 1,
                "SEC_MAPPING_MISSING": 1,
            },
            "market_data_feed": "iex",
            "min_dollar_volume": 2_000_000,
        },
    }
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "decisions.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in decisions), encoding="utf-8"
    )
    (root / "universe_exclusions.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in exclusions), encoding="utf-8"
    )


class TestLiquidityGateAudit(unittest.TestCase):
    def test_counts_bucket_denominators_and_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_evidence(root)
            summary = audit_frozen_evidence(root)
            self.assertEqual(summary["discovery"], 3)
            self.assertEqual(summary["decisions"], 1)
            self.assertEqual(summary["excluded"], 2)
            self.assertEqual(
                summary["bucket_rates"]["ai_smallcap"],
                {
                    "discovered": 1,
                    "excluded": 1,
                    "below_min": 1,
                    "excluded_rate": 1.0,
                    "below_min_rate": 1.0,
                },
            )
            self.assertEqual(summary["bucket_rates"]["core_ai"]["discovered"], 2)
            self.assertEqual(summary["bucket_rates"]["core_ai"]["excluded"], 1)
            self.assertEqual(summary["bucket_rates"]["ai_enabler"]["excluded"], 0)
            self.assertEqual(summary["volume_histogram"]["1m_1_5m"], 1)
            self.assertIn("not a return study", render_markdown(summary))

    def test_uncovered_symbol_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_evidence(root)
            with (root / "ai_watchlist.csv").open("a", encoding="utf-8") as file:
                file.write("UNTRACKED,ai_smallcap,1\n")
            with self.assertRaisesRegex(ValueError, "conservation"):
                audit_frozen_evidence(root)

    def test_feed_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_evidence(root)
            path = root / "universe_exclusions.jsonl"
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            rows[0]["market_data_feed"] = "sip"
            path.write_text(
                "".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "feed mismatch"):
                audit_frozen_evidence(root)


if __name__ == "__main__":
    unittest.main()
