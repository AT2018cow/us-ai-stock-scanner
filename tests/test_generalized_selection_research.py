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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from research_generalized_selection import (
        COHORT, FIRST_ELIGIBLE_MARKET_DATE, audit, config_fingerprint,
        frozen_cohort, hash_file, liquidity_diagnostic, load_bars, prepare,
        read_csv, relative_trailing, validate_bar_export_provenance,
        validate_experiment_config,
    )
finally:
    sys.path.pop(0)

from ai_value_scanner.config import load_config
from ai_value_scanner.decision.discovery import load_discovery_sources
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from export_generalized_pit_bars import export_bars
finally:
    sys.path.pop(0)


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
            base.write_text('{"max_symbols":null,"strategy_style":"risk_off","min_price":1.0,"min_dollar_volume":2000000}',encoding="utf-8")
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
            base.write_text('{"max_symbols":null,"strategy_style":"risk_off","min_price":1.0,"min_dollar_volume":1000000}',encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"frozen v1"):
                prepare(base,Path(tmp)/"wrong_gate.json",ROOT/COHORT)

    def test_experiment_config_parity_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = ROOT / "configs" / "config.risk_off.json"
            dest = Path(tmp) / "config.generalized.json"
            prepare(base, dest, ROOT / COHORT)
            review = validate_experiment_config(
                dest, base, root=ROOT / COHORT
            )
            self.assertEqual(
                review["config_fingerprint"],
                config_fingerprint(load_config(dest)),
            )
            raw = json.loads(dest.read_text(encoding="utf-8"))
            raw["min_price"] = 2.0
            drift = Path(tmp) / "config.drift.json"
            drift.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside discovery sources"):
                validate_experiment_config(
                    drift, base, root=ROOT / COHORT
                )

    def test_first_eligible_market_session_is_enforced(self):
        self.assertEqual(FIRST_ELIGIBLE_MARKET_DATE, "2026-10-12")
        cohort=frozen_cohort(ROOT/COHORT)
        paths={k:str(p) for k,p in cohort["paths"].items()}
        _,members,rejected,summary=load_discovery_sources(paths)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,rows):
                (root/name).write_text(
                    "".join(json.dumps(x)+"\n" for x in rows),encoding="utf-8"
                )
            decisions=[
                {
                    "symbol":symbol,
                    "quality":{"grade":"B","score":0.7,"confidence":0.8,
                               "risks":[],"missing":[]},
                    "entry":{"state":"WATCH_PULLBACK","score":0.6,"risks":[]},
                    "action_state":"WATCH_PULLBACK",
                    "provenance":{},
                }
                for symbol in sorted(cohort["symbols"])
            ]
            write("decisions.jsonl",decisions)
            write("universe_exclusions.jsonl",[])
            write("discovery_memberships.jsonl",members)
            write("discovery_source_rejections.jsonl",rejected)
            manifest={
                "decision_date":"2026-10-11",
                "code_sha":"frozen",
                "discovery_sources":summary,
                "counts":{"decisions":62},
                "candidate_universe":{
                    "market_data_feed":"iex",
                    "min_dollar_volume":2000000,
                },
                "daily_symbols":[],
                "weekly_symbols":[],
            }
            (root/"run_manifest.json").write_text(
                json.dumps(manifest),encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "decision date must be"):
                audit(root,ROOT/COHORT)

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

    def test_qqq_spy_comparison_uses_identical_common_sessions(self):
        asof = date(2026, 10, 12)
        sessions = []
        day = asof
        while len(sessions) < 63:
            if day.weekday() < 5:
                sessions.append(day.isoformat())
            day -= timedelta(days=1)
        sessions.reverse()
        bars = {
            "AAA": {d: (100.0 + i, 100.0) for i, d in enumerate(sessions)},
            "QQQ": {d: (100.0 + i / 2, 100.0) for i, d in enumerate(sessions)},
            "SPY": {d: (100.0 + i / 3, 100.0) for i, d in enumerate(sessions)},
        }
        # A missing SPY date creates different pair-only lookback windows.
        del bars["SPY"][sessions[5]]
        unpaired_qqq = relative_trailing("AAA", "QQQ", bars, asof.isoformat())
        unpaired_spy = relative_trailing("AAA", "SPY", bars, asof.isoformat())
        self.assertNotEqual(unpaired_qqq["joint_sessions"], unpaired_spy["joint_sessions"])
        aligned_qqq = relative_trailing(
            "AAA", "QQQ", bars, asof.isoformat(), shared_benchmarks=("QQQ", "SPY")
        )
        aligned_spy = relative_trailing(
            "AAA", "SPY", bars, asof.isoformat(), shared_benchmarks=("QQQ", "SPY")
        )
        self.assertEqual(aligned_qqq["joint_sessions"], aligned_spy["joint_sessions"])
        self.assertEqual(aligned_qqq["joint_sessions"], 62)
        self.assertIsNotNone(aligned_qqq["trailing_excess_60"])
        self.assertIsNotNone(aligned_spy["trailing_excess_60"])
        # Removing enough of a benchmark's sessions makes BOTH comparisons
        # unavailable, rather than comparing misaligned 60-day windows.
        for d in sessions[1:5]:
            del bars["SPY"][d]
        aligned_qqq = relative_trailing(
            "AAA", "QQQ", bars, asof.isoformat(), shared_benchmarks=("QQQ", "SPY")
        )
        aligned_spy = relative_trailing(
            "AAA", "SPY", bars, asof.isoformat(), shared_benchmarks=("QQQ", "SPY")
        )
        self.assertIsNone(aligned_qqq["trailing_excess_60"])
        self.assertIsNone(aligned_spy["trailing_excess_60"])

    def test_bars_export_rejects_stale_cache_and_excludes_future_sessions(self):
        cohort=frozen_cohort(ROOT/COHORT)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            snapshot=root/"snapshot"
            snapshot.mkdir()
            archive=snapshot/"discovery_source_inputs"
            archive.mkdir()
            for kind, path in cohort["paths"].items():
                shutil.copyfile(path, archive/(kind+".csv"))
            _, members, rejected, summary=load_discovery_sources(
                {k:str(v) for k,v in cohort["paths"].items()}
            )
            manifest={
                "code_sha":"test",
                "decision_date":"2026-10-12",
                "discovery_sources":summary,
                "candidate_universe":{"market_data_feed":"iex","min_dollar_volume":2000000},
            }
            config_path=root/"experiment.json"
            prepare(ROOT/"configs/config.risk_off.json", config_path, ROOT/COHORT)
            manifest["config_fingerprint"] = config_fingerprint(
                load_config(str(config_path))
            )
            (snapshot/"run_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            class FakeAlpaca:
                feed="iex"
                def get_daily_bars(self, symbols, start, chunks):
                    return {
                        symbol:[
                            {"t":"2026-10-09T04:00:00Z","c":10.0,"v":100.0},
                            {"t":"2026-10-12T04:00:00Z","c":11.0,"v":120.0},
                            {"t":"2026-10-13T04:00:00Z","c":999.0,"v":1000.0},
                        ]
                        for symbol in symbols
                    }
                def get_corporate_action_splits(self, symbols, begin, end):
                    return {}

            class FakeMonitor:
                def __init__(self, stale=False): self.stale=stale
                def to_dict(self):
                    return {"stale_market_data_fallback_used":self.stale}

            with patch(
                "export_generalized_pit_bars.load_runtime_settings",
                return_value=(FakeAlpaca(),None,FakeMonitor()),
            ):
                result=export_bars(
                    snapshot, config_path, root/"export",
                    cohort_dir=ROOT/COHORT
                )
            self.assertEqual(result["feed"],"iex")
            self.assertEqual(result["symbols_requested"]*2,result["rows"])
            exported=read_csv(root/"export"/"pit_iex_daily_bars.csv")
            self.assertEqual({r["session"] for r in exported},
                             {"2026-10-09","2026-10-12"})
            bar_file = root/"export"/"pit_iex_daily_bars.csv"
            valid_provenance = validate_bar_export_provenance(
                bar_file, asof="2026-10-12",
                scanner_manifest=manifest, cohort=cohort
            )
            self.assertEqual(valid_provenance["bar_dataset_sha256"], result["bar_dataset_sha256"])
            bad_manifest = dict(valid_provenance, snapshot_code_sha="wrong SHA")
            manifest_path = bar_file.with_name("pit_bars_manifest.json")
            original_manifest = manifest_path.read_bytes()
            manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "scanner SHA mismatch"):
                validate_bar_export_provenance(
                    bar_file, asof="2026-10-12",
                    scanner_manifest=manifest, cohort=cohort
                )
            manifest_path.write_bytes(original_manifest)
            with bar_file.open("a", encoding="utf-8") as modified:
                modified.write("EXTRA,2026-10-12,iex,11,120\\n")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                validate_bar_export_provenance(
                    bar_file, asof="2026-10-12",
                    scanner_manifest=manifest, cohort=cohort
                )
            with patch(
                "export_generalized_pit_bars.load_runtime_settings",
                return_value=(FakeAlpaca(),None,FakeMonitor(stale=True)),
            ):
                with self.assertRaisesRegex(ValueError,"stale market-data fallback"):
                    export_bars(
                        snapshot, config_path, root/"bad_export",
                        cohort_dir=ROOT/COHORT
                    )
            self.assertFalse((root/"bad_export").exists())

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
