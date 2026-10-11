from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

from ai_value_scanner.config import ScanConfig
from ai_value_scanner.decision.discovery import (
    DISCOVERY_SCHEMA_VERSION,
    assert_memberships_asof,
    load_discovery_sources,
    validate_discovery_snapshot,
)
from ai_value_scanner.decision.universe import build_candidate_universe_summary
from ai_value_scanner.reporting.snapshot import write_decision_snapshot
from ai_value_scanner.scanner import watchlist_rows_to_scores

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
try:
    from test_candidate_universe_contract import _decision
finally:
    sys.path.pop(0)

SCRIPTS = TESTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    from validate_mvp_snapshot import validate_snapshot
finally:
    sys.path.pop(0)


HEADERS = (
    "symbol", "source_id", "source_asof", "security_type", "enabled",
    "theme_id", "legacy_bucket", "etfs", "research_note",
)


def _csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def _row(symbol, source_id, *, kind="common_stock", enabled="1",
         day="2026-10-09", theme="", bucket="", etfs="", note=""):
    return {
        "symbol": symbol, "source_id": source_id, "source_asof": day,
        "security_type": kind, "enabled": enabled, "theme_id": theme,
        "legacy_bucket": bucket, "etfs": etfs, "research_note": note,
    }


def _fixtures(root):
    paths = {
        "us_core": root / "core.csv",
        "thematic": root / "theme.csv",
        "manual": root / "manual.csv",
    }
    _csv(paths["us_core"], [
        _row("AAA", "core"),
        _row("BBB", "core"),
        _row("ETF1", "core", kind="etf"),
    ])
    _csv(paths["thematic"], [
        _row("AAA", "ai_etf", theme="ai", bucket="core_ai", etfs="AIQ"),
        _row("AAA", "ai_etf", theme="ai", bucket="core_ai", etfs="AIQ"),
    ])
    _csv(paths["manual"], [
        _row("AAA", "research", note="check earnings"),
        _row("CCC", "research", enabled="0", note="excluded by source"),
    ])
    return {kind: str(path) for kind, path in paths.items()}


class TestGeneralDiscoveryUnion(unittest.TestCase):
    def test_multi_source_union_and_legacy_etf_count_not_inflated(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixtures(Path(tmp))
            legacy_rows, members, rejects, summary = load_discovery_sources(paths)
            self.assertEqual(summary["schema_version"], DISCOVERY_SCHEMA_VERSION)
            self.assertEqual(summary["source_memberships"], 4)
            self.assertEqual(summary["unique_symbols"], 2)
            self.assertEqual(summary["multi_source_symbols"], 1)
            self.assertEqual(summary["rejected_rows"], 3)
            self.assertEqual(summary["rejection_reason_counts"], {
                "SOURCE_DISABLED": 1,
                "SOURCE_DUPLICATE_MEMBERSHIP": 1,
                "SOURCE_SECURITY_NOT_COMMON": 1,
            })
            self.assertEqual(len([m for m in members if m["symbol"] == "AAA"]), 3)
            self.assertEqual(
                {m["source_kind"] for m in members if m["symbol"] == "AAA"},
                {"us_core", "thematic", "manual"},
            )
            self.assertTrue(all(len(f["sha256"]) == 64 for f in summary["source_files"]))
            scores = watchlist_rows_to_scores(pd.DataFrame(legacy_rows))
            a = scores.set_index("symbol").loc["AAA"]
            b = scores.set_index("symbol").loc["BBB"]
            self.assertEqual(a["watchlist_bucket"], "core_ai")
            self.assertEqual(a["watchlist_etf_count"], 1)
            self.assertEqual(a["watchlist_etfs"], "AIQ")
            self.assertEqual(b["watchlist_etf_count"], 0)
            self.assertEqual(b["watchlist_bucket"], "")
            self.assertEqual(
                validate_discovery_snapshot(
                    memberships=members, rejected=rejects, summary=summary,
                    discovery_symbols={"AAA", "BBB"},
                    decision_date="2026-10-09",
                ), [],
            )

    def test_fail_closed_future_asof_identity_and_source_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _fixtures(root)
            _, members, _, _ = load_discovery_sources(paths)
            assert_memberships_asof(members, "2026-10-09")
            with self.assertRaisesRegex(ValueError, "future discovery"):
                assert_memberships_asof(members, "2026-10-08")
            self.assertEqual(ScanConfig().discovery_source_files, None)
            with self.assertRaisesRegex(ValueError, "unknown source kind"):
                ScanConfig.from_dict({"discovery_source_files": {"unexpected": "x.csv"}})
            with self.assertRaisesRegex(ValueError, "missing discovery source CSV"):
                load_discovery_sources({"manual": str(root / "missing.csv")})

            _csv(root / "aliases.csv", [
                _row("BRK-B", "manual", note="do not guess share class"),
                _row("brk.b", "manual", note="lowercase not canonical"),
                _row("BRK.B", "manual", note="explicit listed symbol"),
            ])
            _, alias_members, alias_rejects, _ = load_discovery_sources({
                "manual": str(root / "aliases.csv")
            })
            self.assertEqual([x["symbol"] for x in alias_members], ["BRK.B"])
            self.assertEqual(
                [x["reason_code"] for x in alias_rejects],
                ["SOURCE_SYMBOL_INVALID", "SOURCE_SYMBOL_INVALID"],
            )

    def test_source_snapshot_is_validated_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _fixtures(root)
            _, members, rejects, summary = load_discovery_sources(paths)
            dec = _decision("AAA")
            omitted = [{
                "symbol": "BBB",
                "status": "excluded",
                "exclusion_stage": "asset_eligibility",
                "reason_code": "ALPACA_ACTIVE_ASSET_MISSING",
                "asset_status": None, "tradable": None, "exchange": None,
                "price": None, "dollar_volume": None,
                "market_data_feed": None, "min_price": None,
                "min_dollar_volume": None,
                "watchlist_bucket": "", "watchlist_etf_count": 0,
                "watchlist_etfs": "",
            }]
            candidate = build_candidate_universe_summary(
                discovery_symbols={"AAA", "BBB"}, decision_symbols={"AAA"},
                exclusions=omitted,
                tradable_mapped_symbols=1, post_sample_symbols=1,
                market_data_feed="iex", min_price=1,
                min_dollar_volume=2000000,
            )
            output = write_decision_snapshot(
                output_root=root / "outputs",
                strategy_style="risk_off",
                decisions=(dec,), daily_attention=(dec,), weekly_attention=(dec,),
                generated_at_utc=dec.generated_at_utc, decision_date=dec.decision_date,
                config_fingerprint="cfg", code_sha="abc",
                universe_exclusions=omitted,
                candidate_universe_summary=candidate,
                discovery_memberships=members,
                discovery_source_rejections=rejects,
                discovery_source_summary=summary,
            )
            self.assertTrue(output.discovery_memberships_jsonl.exists())
            self.assertTrue(output.discovery_source_rejections_jsonl.exists())
            self.assertTrue(output.discovery_source_inputs_dir.is_dir())
            self.assertEqual(
                (output.discovery_source_inputs_dir / "us_core.csv").read_bytes(),
                Path(paths["us_core"]).read_bytes(),
            )
            self.assertTrue(validate_snapshot(output.root)["ok"])
            archive = output.discovery_source_inputs_dir / "us_core.csv"
            original_source = archive.read_bytes()
            archive.write_bytes(original_source + b"corruption")
            bad_hash = validate_snapshot(output.root)
            self.assertFalse(bad_hash["ok"])
            self.assertTrue(any("SHA256 mismatch" in e for e in bad_hash["errors"]))
            archive.write_bytes(original_source)
            self.assertTrue(validate_snapshot(output.root)["ok"])
            original = output.discovery_memberships_jsonl.read_bytes()
            with self.assertRaises(FileExistsError):
                write_decision_snapshot(
                    output_root=root / "outputs", strategy_style="risk_off",
                    decisions=(dec,), daily_attention=(dec,), weekly_attention=(dec,),
                    generated_at_utc=dec.generated_at_utc, decision_date=dec.decision_date,
                    config_fingerprint="cfg",
                )
            self.assertEqual(original, output.discovery_memberships_jsonl.read_bytes())

            output.discovery_memberships_jsonl.write_text("", encoding="utf-8")
            bad = validate_snapshot(output.root)
            self.assertFalse(bad["ok"])
            self.assertTrue(any("discovery" in err for err in bad["errors"]))

    def test_manifest_rejects_coverage_drift_and_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixtures(Path(tmp))
            _, members, rejects, summary = load_discovery_sources(paths)
            tampered = dict(summary, multi_source_symbols=0)
            self.assertIn(
                "discovery source overlap count mismatch",
                validate_discovery_snapshot(
                    memberships=members, rejected=rejects, summary=tampered,
                    discovery_symbols={"AAA", "BBB"}, decision_date="2026-10-09"
                )
            )


if __name__ == "__main__":
    unittest.main()
