"""Tests for the bounded, frozen generalized Quality/Entry research workflow."""
from __future__ import annotations

import csv
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from research_generalized_selection import (
        COHORT, audit, frozen_cohort, hash_file, liquidity_diagnostic,
        load_bars, prepare, relative_trailing,
    )
finally:
    sys.path.pop(0)

from ai_value_scanner.decision.discovery import load_discovery_sources


class TestGeneralizedResearch(unittest.TestCase):
    def test_v0_stratified_static_cohort(self):
        result=frozen_cohort(ROOT/COHORT)
        self.assertEqual(len(result["symbols"]),62)
        self.assertEqual(len(result["classifications"]),60)
        self.assertEqual(result["raw_source_rows"],75)
        self.assertEqual(len(set(result["source_hashes"].values())),3)
        self.assertNotIn("AXP",result["classifications"])
        self.assertIn("AXP",result["symbols"])
        self.assertIn("ISRG",result["symbols"])
        self.assertEqual(
            {x["classification_status"] for x in result["classifications"].values()},
            {"research_provisional"},
        )

    def test_prepare_config_is_opt_in_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"out"/"config.json"
            base=Path(tmp)/"base.json"
            base.write_text('{"max_symbols":null,"strategy_style":"risk_off"}',encoding="utf-8")
            meta=prepare(base,dest,ROOT/COHORT)
            self.assertEqual(meta["unique_symbols"],62)
            config=json.loads(dest.read_text())
            self.assertEqual(set(config["discovery_source_files"]),{"us_core","thematic","manual"})
            self.assertEqual(hash_file(dest),meta["config_sha256"])
            with self.assertRaises(FileExistsError):
                prepare(base,dest,ROOT/COHORT)
            base.write_text('{"max_symbols":5}',encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"max_symbols"):
                prepare(base,Path(tmp)/"bad.json",ROOT/COHORT)

    def test_bar_gate_requires_pit_same_feed_complete_sessions(self):
        asof=date(2026,10,12)
        # deterministic weekday-only sessions, last date exactly decision session
        sessions=[]
        day=asof
        while len(sessions)<21:
            if day.weekday()<5:
                sessions.append(day.isoformat())
            day-=timedelta(days=1)
        sessions.reverse()
        bars={"AAA":{day:(10.0,100000.0) for day in sessions}}
        v=liquidity_diagnostic("AAA",bars,asof.isoformat())
        self.assertEqual(v["coverage"],"20_session_valid")
        self.assertEqual(v["last_bar_turnover"],1000000)
        self.assertEqual(v["mean_20session_turnover"],1000000)
        self.assertFalse(v["last_bar_pass"])
        self.assertFalse(v["mean_20session_pass"])
        bars["AAA"][sessions[-1]]=(10.0,500000.0)
        changed=liquidity_diagnostic("AAA",bars,asof.isoformat())
        self.assertTrue(changed["last_bar_pass"])
        self.assertFalse(changed["mean_20session_pass"])
        self.assertTrue(changed["disagreement"])
        missing=liquidity_diagnostic("BBB",bars,asof.isoformat())
        self.assertEqual(missing["coverage"],"missing_asof_bar")
        sparse=liquidity_diagnostic("AAA",{"AAA":{sessions[-1]: (10, 100)}},asof.isoformat())
        self.assertEqual(sparse["coverage"],"insufficient_20_sessions")

    def test_bar_input_fails_on_future_or_other_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bars.csv"
            def put(day,feed):
                path.write_text(
                    "symbol,session,feed,close,volume\nAAA,{}, {},10,100\n".format(day,feed).replace(", ",","),
                    encoding="utf-8",
                )
            put("2026-10-13","iex")
            with self.assertRaisesRegex(ValueError,"lookahead"):
                load_bars(path,"2026-10-12")
            put("2026-10-12","sip")
            with self.assertRaisesRegex(ValueError,"feed"):
                load_bars(path,"2026-10-12")

    def test_aligned_trailing_benchmark_not_forward_outcome(self):
        asof=date(2026,10,12)
        days=[]
        day=asof
        while len(days)<61:
            if day.weekday()<5:
                days.append(day.isoformat())
            day-=timedelta(days=1)
        days.reverse()
        bars={
            "AAA":{s:(100+i,1000) for i,s in enumerate(days)},
            "QQQ":{s:(100,1000) for s in days},
        }
        row=relative_trailing("AAA","QQQ",bars,asof.isoformat())
        self.assertEqual(row["joint_sessions"],61)
        self.assertAlmostEqual(row["trailing_excess_20"],20/140,places=6)
        self.assertAlmostEqual(row["trailing_excess_60"],0.6,places=6)
        self.assertIsNone(relative_trailing("AAA","SPY",bars,asof.isoformat())["trailing_excess_20"])

    def test_end_to_end_audit_and_source_hash_tamper(self):
        cohort=frozen_cohort(ROOT/COHORT)
        paths={k:str(p) for k,p in cohort["paths"].items()}
        _,members,rejected,summary=load_discovery_sources(paths)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,rows):
                (root/name).write_text(
                    "".join(json.dumps(x)+"\n" for x in rows),encoding="utf-8"
                )
            excluded={"AXP","ISRG"}
            decisions=[
                {"symbol":symbol,
                 "quality":{"grade":"B","score":0.7,"confidence":0.8,
                            "risks":[{"code":"v1_warning"}],"missing":[]},
                 "entry":{"state":"WATCH_PULLBACK","score":0.6,"risks":[]},
                 "action_state":"WATCH_PULLBACK",
                 "provenance":{"fundamental_currency_supported":True,
                               "fundamental_facts_cover_latest_periodic":True}}
                for symbol in sorted(cohort["symbols"]-excluded)
            ]
            write("decisions.jsonl",decisions)
            write("universe_exclusions.jsonl",[
                {"symbol":sym,"reason_code":"ALPACA_ACTIVE_ASSET_MISSING"}
                for sym in sorted(excluded)
            ])
            write("discovery_memberships.jsonl",members)
            write("discovery_source_rejections.jsonl",rejected)
            manifest={
                "decision_date":"2026-10-12",
                "code_sha":"frozen",
                "discovery_sources":summary,
                "counts":{"decisions":60},
                "candidate_universe":{
                    "market_data_feed":"iex",
                    "min_dollar_volume":2000000,
                },
                "daily_symbols":[s["symbol"] for s in decisions[:5]],
                "weekly_symbols":[s["symbol"] for s in decisions[:5]],
            }
            (root/"run_manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            archive=root/"discovery_source_inputs"
            archive.mkdir()
            for kind,path in cohort["paths"].items():
                shutil.copyfile(path,archive/(kind+".csv"))
            result,rows,liquidity,entry=audit(root,ROOT/COHORT)
            self.assertEqual((result["discovered"],result["decisions"],result["exclusions"]),(62,60,2))
            self.assertEqual(result["source_memberships"],75)
            self.assertEqual(len(rows),62)
            self.assertEqual(len(liquidity),62)
            self.assertEqual(result["20session_turnover_coverage"],0)
            self.assertEqual(sum(x["symbols"] for x in result["liquidity_by_group"]),62)
            self.assertEqual(sum(x["symbols"] for x in result["entry_reference_diagnostics"]),62)
            self.assertTrue(all(
                x["aligned_60session_qqq_spy"] == 0
                for x in result["entry_reference_diagnostics"]
            ))
            self.assertTrue(any(x["specialized_accounting_review"] for x in result["groups"]))
            self.assertTrue(all(x["trailing_excess_20"] is None for x in entry))
            # Same-sized, same-count membership corruption must not pass merely
            # because the source files and aggregate counts have valid SHA256.
            membership_file=root/"discovery_memberships.jsonl"
            original_membership=membership_file.read_bytes()
            corrupted=json.loads(original_membership.splitlines()[0])
            corrupted["source_id"]="fabricated_source_id"
            changed=[corrupted] + [json.loads(line) for line in original_membership.splitlines()[1:]]
            write("discovery_memberships.jsonl",changed)
            with self.assertRaisesRegex(ValueError,"diverge from frozen input CSV"):
                audit(root,ROOT/COHORT)
            membership_file.write_bytes(original_membership)
            result,_,_,_=audit(root,ROOT/COHORT)
            self.assertEqual(result["source_memberships"],75)

            archive_file=archive/"us_core.csv"
            archive_file.write_text("tampered",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"corrupted"):
                audit(root,ROOT/COHORT)


if __name__=="__main__":
    unittest.main()
