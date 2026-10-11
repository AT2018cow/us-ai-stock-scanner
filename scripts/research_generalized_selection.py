"""Read-only generalized-universe Quality/Entry/Action/liquidity diagnosis.

Uses frozen CSV and an opt-in StockDecision snapshot. Optional PIT same-feed
daily bars offer *diagnostic* 20-session turnover and QQQ/SPY/sector proxy returns;
they are not the Alpaca snapshot gate, forward returns, or a changed Entry model.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path

COHORT = Path("data/research/generalized_v0")
KINDS = ("us_core", "thematic", "manual")
PROXY = {
    "asset_light_software": "XLK", "semiconductor_equipment": "SMH",
    "healthcare_pharma_medtech": "XLV", "industrials_machinery": "XLI",
    "consumer_staples": "XLP", "consumer_discretionary": "XLY",
    "energy_oil_gas": "XLE", "materials_chemicals_mining": "XLB",
    "regulated_utilities": "XLU", "communications_media": "XLC",
    "banks_brokers": "XLF", "reit_property": "XLRE",
}
SPECIAL = {"banks_brokers", "reit_property"}


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def frozen_cohort(root=COHORT):
    root = Path(root)
    paths = {kind: root / (kind + ".csv") for kind in KINDS}
    sources = {kind: read_csv(path) for kind, path in paths.items()}
    metadata = read_csv(root / "coverage_strata.csv")
    core = sources["us_core"]
    meta = {r["symbol"]: r for r in metadata}
    core_syms = {r["symbol"] for r in core}
    if len(core) != 60 or len(core_syms) != 60 or len(meta) != 60 or set(meta) != core_syms:
        raise ValueError("frozen v0 must have 60 unique US Core names and matching classifications")
    if Counter(r["coverage_stratum"] for r in metadata) != Counter({k: 5 for k in PROXY}):
        raise ValueError("expected five researched seeds in each of 12 coverage strata")
    if any(r["classification_status"] != "research_provisional" for r in metadata):
        raise ValueError("research classifications are unverified and must remain provisional")
    if len(sources["thematic"]) != 10 or len(sources["manual"]) != 5:
        raise ValueError("v0 expected 10 thematic and 5 research-manual memberships")
    for rows in sources.values():
        for r in rows:
            if (r["source_asof"] != "2026-10-11" or
                    r["security_type"] != "common_stock" or r["enabled"] != "1"):
                raise ValueError("v0 source date/type/enable status drift")
    symbols = {r["symbol"] for rows in sources.values() for r in rows}
    if len(symbols) != 62:
        raise ValueError("v0 union expected 62 unique securities")
    return {
        "symbols": symbols, "classifications": meta, "paths": paths,
        "source_hashes": {k: hash_file(v) for k, v in paths.items()},
        "metadata_sha256": hash_file(root / "coverage_strata.csv"),
        "raw_source_rows": sum(len(v) for v in sources.values()),
    }


def prepare(base_config, output_config, root=COHORT):
    cohort = frozen_cohort(root)
    config = json.loads(Path(base_config).read_text(encoding="utf-8"))
    if config.get("discovery_source_files") is not None or config.get("max_symbols") is not None:
        raise ValueError("base config must be legacy and max_symbols=null")
    config["discovery_source_files"] = {k: p.as_posix() for k,p in cohort["paths"].items()}
    destination = Path(output_config)
    if destination.exists():
        raise FileExistsError("refusing to overwrite previous experiment config")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return {
        "config_sha256": hash_file(destination),
        "source_hashes": cohort["source_hashes"],
        "metadata_sha256": cohort["metadata_sha256"],
        "unique_symbols": len(cohort["symbols"]),
        "source_rows": cohort["raw_source_rows"],
        "first_eligible_market_date": "2026-10-12",
        "mode": "experiment_only",
    }


def load_bars(path, asof, *, feed="iex"):
    if path is None:
        return {}
    out = defaultdict(dict)
    for r in read_csv(path):
        symbol, session, actual_feed = r["symbol"].strip().upper(), r["session"], r["feed"].lower()
        if not symbol or date.fromisoformat(session).isoformat() != session or session > asof:
            raise ValueError("invalid/lookahead bar symbol or session")
        if actual_feed != feed:
            raise ValueError("bar feed incompatible with scanner feed")
        close, volume = float(r["close"]), float(r["volume"])
        if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0:
            raise ValueError("invalid OHLCV close/volume")
        if session in out[symbol]:
            raise ValueError("duplicate bar session for "+symbol)
        out[symbol][session] = (close, volume)
    return out


def liquidity_diagnostic(symbol, bars, asof, threshold=2_000_000):
    obs = sorted((day,*values) for day, values in bars.get(symbol, {}).items() if day <= asof)
    result = {
        "symbol": symbol, "valid_sessions": len(obs),
        "last_bar_session": obs[-1][0] if obs else "",
        "last_bar_turnover": None, "mean_20session_turnover": None,
        "last_bar_pass": None, "mean_20session_pass": None,
        "disagreement": None, "coverage": "missing_asof_bar",
    }
    if not obs or obs[-1][0] != asof:
        return result
    last = obs[-1]
    result["last_bar_turnover"] = round(last[1]*last[2], 2)
    result["last_bar_pass"] = result["last_bar_turnover"] >= threshold
    result["coverage"] = "insufficient_20_sessions"
    if len(obs) < 20:
        return result
    recent = obs[-20:]
    if (date.fromisoformat(recent[-1][0])-date.fromisoformat(recent[0][0])).days > 35:
        result["coverage"] = "stale_20_session_span"
        return result
    result["mean_20session_turnover"] = round(sum(x[1]*x[2] for x in recent)/20,2)
    result["mean_20session_pass"] = result["mean_20session_turnover"] >= threshold
    result["disagreement"] = result["last_bar_pass"] != result["mean_20session_pass"]
    result["coverage"] = "20_session_valid"
    return result


def relative_trailing(symbol, benchmark, bars, asof):
    a,b=bars.get(symbol,{}),bars.get(benchmark,{})
    joint=sorted(x for x in set(a)&set(b) if x<=asof)
    row={"symbol":symbol,"benchmark":benchmark,"joint_sessions":len(joint),
         "asof_joint":joint[-1] if joint else ""}
    for window in (20,60):
        excess=None
        if len(joint)>=window+1 and joint[-1]==asof:
            start,end=joint[-window-1],joint[-1]
            if (date.fromisoformat(end)-date.fromisoformat(start)).days <= 2*window:
                excess=round((a[end][0]/a[start][0]-1)-(b[end][0]/b[start][0]-1),6)
        row["trailing_excess_"+str(window)] = excess
    return row


def audit(snapshot, root=COHORT, bars_csv=None):
    cohort=frozen_cohort(root)
    directory=Path(snapshot)
    manifest=json.loads((directory/"run_manifest.json").read_text(encoding="utf-8"))
    sources=manifest.get("discovery_sources")
    asof=manifest.get("decision_date","")
    if not isinstance(sources,dict) or asof<"2026-10-11":
        raise ValueError("snapshot is not a valid prospective generalized-v0 experiment")
    if manifest["candidate_universe"]["market_data_feed"]!="iex" or float(manifest["candidate_universe"]["min_dollar_volume"])!=2_000_000:
        raise ValueError("different feed or liquidity threshold: not frozen v1 comparator")
    members=jsonl(directory/"discovery_memberships.jsonl")
    rejected=jsonl(directory/"discovery_source_rejections.jsonl")
    decisions=jsonl(directory/"decisions.jsonl")
    exclusions=jsonl(directory/"universe_exclusions.jsonl")
    ds={x["symbol"]:x for x in decisions}
    xs={x["symbol"]:x for x in exclusions}
    observed={x["symbol"] for x in members}
    if (observed!=cohort["symbols"] or observed!=set(ds)|set(xs)
            or set(ds)&set(xs) or len(ds)!=len(decisions) or len(xs)!=len(exclusions)):
        raise ValueError("discovery, decision and exclusion universe do not conserve")
    if (sources["source_memberships"]!=len(members) or sources["rejected_rows"]!=len(rejected)
            or manifest["counts"]["decisions"]!=len(ds)):
        raise ValueError("manifest count mismatch")
    # v0 is a deliberately frozen 75-membership, zero-rejection research cohort;
    # accepting another pool with the same unique symbols would break parity.
    if len(members)!=75 or rejected:
        raise ValueError("v0 frozen memberships/rejected rows do not match contract")
    if {x["source_kind"] for x in sources["source_files"]}!=set(KINDS) or len(sources["source_files"])!=3:
        raise ValueError("v0 must archive all three independent source kinds")
    for source in sources["source_files"]:
        kind=source["source_kind"]
        if kind not in KINDS or source["sha256"]!=cohort["source_hashes"][kind]:
            raise ValueError("source does not match frozen research cohort")
        if hash_file(directory/source["archived_file"])!=source["sha256"]:
            raise ValueError("archived source CSV corrupted")
    if any(m["source_asof"]>asof for m in members):
        raise ValueError("source membership incorrectly backdated")
    if len(manifest.get("daily_symbols",[]))>15 or len(manifest.get("weekly_symbols",[]))>15:
        raise ValueError("v1 Attention cap exceeded")
    bars=load_bars(bars_csv,asof)
    per_symbol=[]
    for symbol in sorted(observed):
        decision=ds.get(symbol)
        group=cohort["classifications"].get(symbol,{}).get("coverage_stratum","manual_only_unknown")
        p=decision.get("provenance",{}) if decision else {}
        per_symbol.append({
            "symbol":symbol,"coverage_stratum":group,
            "classification_status":"research_provisional" if group!="manual_only_unknown" else "unknown",
            "quality_semantic_applicability":"specialized_accounting_review_required" if group in SPECIAL else "unverified",
            "status":"decision" if decision else "excluded",
            "reason":xs.get(symbol,{}).get("reason_code",""),
            "quality_grade":decision["quality"]["grade"] if decision else "",
            "quality_score":decision["quality"].get("score") if decision else None,
            "quality_confidence":decision["quality"].get("confidence") if decision else None,
            "quality_missing":len(decision["quality"].get("missing",[])) if decision else None,
            "quality_risk_codes":"|".join(x["code"] for x in decision["quality"].get("risks",[])) if decision else "",
            "latest_filing_covered":p.get("fundamental_facts_cover_latest_periodic"),
            "currency_supported":p.get("fundamental_currency_supported"),
            "entry_state":decision["entry"]["state"] if decision else "",
            "entry_score":decision["entry"].get("score") if decision else None,
            "entry_risk_codes":"|".join(x["code"] for x in decision["entry"].get("risks",[])) if decision else "",
            "action":decision["action_state"] if decision else "",
            "daily_attention":symbol in manifest["daily_symbols"],
            "weekly_attention":symbol in manifest["weekly_symbols"],
        })
    strata=[]
    for name in sorted(set(x["coverage_stratum"] for x in per_symbol)):
        group=[x for x in per_symbol if x["coverage_stratum"]==name]
        kept=[x for x in group if x["status"]=="decision"]
        strata.append({
            "group":name,"discovered":len(group),"decisions":len(kept),
            "excluded":len(group)-len(kept),
            "quality_grades":dict(sorted(Counter(x["quality_grade"] for x in kept).items())),
            "entry_states":dict(sorted(Counter(x["entry_state"] for x in kept).items())),
            "action_states":dict(sorted(Counter(x["action"] for x in kept).items())),
            "missing_quality_evidence":sum(x["quality_missing"] for x in kept),
            "latest_filing_uncovered":sum(x["latest_filing_covered"] is False for x in kept),
            "currency_unsupported":sum(x["currency_supported"] is False for x in kept),
            "daily_attention":sum(x["daily_attention"] for x in group),
            "specialized_accounting_review":name in SPECIAL,
        })
    liquidity=[dict(liquidity_diagnostic(x,bars,asof),
                    coverage_stratum=cohort["classifications"].get(x,{}).get("coverage_stratum","manual_only_unknown"),
                    scanner_exclusion=xs.get(x,{}).get("reason_code","")) for x in sorted(observed)]
    entry=[]
    for symbol in sorted(observed):
        group=cohort["classifications"].get(symbol,{}).get("coverage_stratum","manual_only_unknown")
        for ref in ("QQQ","SPY",PROXY.get(group)):
            if ref and ref!=symbol:
                entry.append(dict(relative_trailing(symbol,ref,bars,asof),
                    coverage_stratum=group,entry_v1=ds.get(symbol,{}).get("entry",{}).get("state","")))
    report={
        "study":"generalized_research_v0",
        "mode":"read_only_diagnostic_not_strategy_validation",
        "decision_date":asof,"scanner_sha":manifest.get("code_sha"),
        "cohort_metadata_sha256":cohort["metadata_sha256"],
        "cohort_source_hashes":cohort["source_hashes"],
        "discovered":len(observed),"decisions":len(ds),"exclusions":len(xs),
        "source_rejections":len(rejected),"source_memberships":len(members),
        "groups":strata,"daily_symbols":manifest["daily_symbols"],
        "weekly_symbols":manifest["weekly_symbols"],
        "same_feed_bars_sha256":hash_file(bars_csv) if bars_csv else None,
        "20session_turnover_coverage":sum(x["coverage"]=="20_session_valid" for x in liquidity),
        "60session_qqq_spy_comparison_coverage":sum(
            bool(bars) and
            relative_trailing(x,"QQQ",bars,asof)["trailing_excess_60"] is not None and
            relative_trailing(x,"SPY",bars,asof)["trailing_excess_60"] is not None
            for x in observed
        ),
        "limitations":[
            "Purposive 60+2 diagnostic sample; not statistically representative.",
            "Researcher business-model labels are provisional, not verified industry mappings.",
            "Bank/REIT Quality v1 labels require specialized accounting review.",
            "IEX daily-bar turnover is not the scanner's exact snapshot prefilter value.",
            "Sector ETFs are illustrative proxies, not proof of company membership.",
            "Trailing QQQ/SPY/sector comparisons are not Entry v2 or forward returns.",
            "Absent bars/facts remain missing; no silent imputation of zero.",
            "No retrospective PIT source membership, policy changes, or alpha claim.",
        ],
    }
    return report,per_symbol,liquidity,entry


def write_csv(path,rows):
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def markdown(report):
    out=["# Generalized Quality × Entry research", "",
         "**Diagnostic only. No new score, rule or live policy.**","",
         "Decision session: "+report["decision_date"],
         "Discovered / decisions / excluded: {} / {} / {}".format(
             report["discovered"],report["decisions"],report["exclusions"]),
         "Optional 20-session liquidity coverage: "+str(report["20session_turnover_coverage"]),
         "",
         "| Provisional group | Discovered | Decisions | Excluded | Quality | Entry | Daily attention | Accounting caveat |",
         "| --- | ---: | ---: | ---: | --- | --- | ---: | --- |"]
    for x in report["groups"]:
        out.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            x["group"],x["discovered"],x["decisions"],x["excluded"],
            json.dumps(x["quality_grades"],sort_keys=True),
            json.dumps(x["entry_states"],sort_keys=True),
            x["daily_attention"],"specialized review" if x["specialized_accounting_review"] else "unverified",
        ))
    out+=["","## Research limitations",""]
    out+=["- "+s for s in report["limitations"]]
    out+=["","See the accompanying machine-readable symbol-level quality/entry/action,",
          "liquidity and trailing benchmark comparison CSV files.",""]
    return "\n".join(out)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="cmd",required=True)
    pre=sub.add_parser("prepare")
    pre.add_argument("--base-config",default="configs/config.risk_off.json")
    pre.add_argument("--output-config",required=True)
    pre.add_argument("--cohort-dir",default=str(COHORT))
    au=sub.add_parser("audit")
    au.add_argument("--snapshot",required=True)
    au.add_argument("--cohort-dir",default=str(COHORT))
    au.add_argument("--bars-csv")
    au.add_argument("--out-dir",required=True)
    args=p.parse_args()
    if args.cmd=="prepare":
        print(json.dumps(prepare(args.base_config,args.output_config,args.cohort_dir),indent=2))
        return
    report,details,liquidity,entry=audit(args.snapshot,args.cohort_dir,args.bars_csv)
    dest=Path(args.out_dir)
    if dest.exists():
        raise FileExistsError("will not overwrite frozen research results")
    dest.mkdir(parents=True)
    (dest/"research_audit.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (dest/"research_review.md").write_text(markdown(report),encoding="utf-8")
    write_csv(dest/"quality_entry_action_by_symbol.csv",details)
    write_csv(dest/"liquidity_diagnostics.csv",liquidity)
    write_csv(dest/"entry_benchmark_diagnostics.csv",entry)
    print(dest)


if __name__=="__main__":
    main()
