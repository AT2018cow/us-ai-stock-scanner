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

from ai_value_scanner.config import load_config
from ai_value_scanner.decision.discovery import (
    load_discovery_sources,
    validate_discovery_snapshot,
)

COHORT = Path("data/research/generalized_v0")
FIRST_ELIGIBLE_MARKET_DATE = "2026-10-12"
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
    if any(r.get("theme_id") != "ai" for r in sources["thematic"]):
        raise ValueError("v0 frozen thematic diagnostic is AI-only")
    if not {r["symbol"] for r in sources["thematic"]} <= core_syms:
        raise ValueError("v0 theme sources must overlap the frozen core")
    if len({r["symbol"] for r in sources["manual"]} - core_syms) != 2:
        raise ValueError("v0 manual cohort must add exactly two independent probes")
    _, parsed_memberships, parsed_rejections, parsed_summary = load_discovery_sources(
        {kind: str(path) for kind, path in paths.items()}
    )
    if (parsed_rejections or len(parsed_memberships) != 75 or
            parsed_summary["unique_symbols"] != 62):
        raise ValueError("frozen source parser rejects rows or yields different membership counts")
    symbols = {r["symbol"] for rows in sources.values() for r in rows}
    if len(symbols) != 62:
        raise ValueError("v0 union expected 62 unique securities")
    return {
        "symbols": symbols, "classifications": meta, "paths": paths,
        "source_hashes": {k: hash_file(v) for k, v in paths.items()},
        "metadata_sha256": hash_file(root / "coverage_strata.csv"),
        "raw_source_rows": sum(len(v) for v in sources.values()),
    }


def _config_identity(config):
    payload = vars(config).copy()
    if payload.get("discovery_source_files") is None:
        payload.pop("discovery_source_files", None)
    return payload


def config_fingerprint(config):
    payload = json.dumps(
        _config_identity(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_experiment_config(config_path, base_config, *, root=COHORT):
    cohort = frozen_cohort(root)
    raw_experiment = json.loads(Path(config_path).read_text(encoding="utf-8"))
    raw_baseline = json.loads(Path(base_config).read_text(encoding="utf-8"))
    if not isinstance(raw_experiment, dict) or not isinstance(raw_baseline, dict):
        raise ValueError("experiment/base configs must be JSON objects")
    expected_sources = {k: p.as_posix() for k, p in cohort["paths"].items()}
    if raw_experiment.get("discovery_source_files") != expected_sources:
        raise ValueError("experiment discovery_source_files do not match frozen v0")
    comparable = dict(raw_experiment)
    comparable.pop("discovery_source_files", None)
    if comparable != raw_baseline:
        changed = sorted(
            key for key in set(comparable) | set(raw_baseline)
            if comparable.get(key) != raw_baseline.get(key)
        )
        raise ValueError(
            "experiment config changed frozen v1 policy outside discovery sources: "
            + ", ".join(changed)
        )
    experiment = load_config(str(config_path))
    for kind, source_path in expected_sources.items():
        if hash_file(source_path) != cohort["source_hashes"][kind]:
            raise ValueError("experiment source file hash drift: " + kind)
    return {
        "config_fingerprint": config_fingerprint(experiment),
        "raw_config_sha256": hash_file(config_path),
        "base_config_sha256": hash_file(base_config),
    }


def prepare(base_config, output_config, root=COHORT):
    cohort = frozen_cohort(root)
    config = json.loads(Path(base_config).read_text(encoding="utf-8"))
    if config.get("discovery_source_files") is not None or config.get("max_symbols") is not None:
        raise ValueError("base config must be legacy and max_symbols=null")
    if (config.get("strategy_style") != "risk_off" or
            config.get("min_dollar_volume") != 2_000_000 or
            config.get("min_price") != 1.0):
        raise ValueError("base must use frozen v1 risk_off, $2m dollar volume, $1 price floor")
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
        "first_eligible_market_date": FIRST_ELIGIBLE_MARKET_DATE,
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


def relative_trailing(symbol, benchmark, bars, asof, *, shared_benchmarks=()):
    a,b=bars.get(symbol,{}),bars.get(benchmark,{})
    # QQQ and SPY must use the exact same stock/benchmark sessions for
    # a fair sign/rank comparison; otherwise differing provider gaps
    # quietly shift the start observation.
    common = set(a) & set(b)
    for peer in shared_benchmarks:
        common &= set(bars.get(peer, {}))
    joint=sorted(x for x in common if x<=asof)
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


def audit(
    snapshot,
    root=COHORT,
    bars_csv=None,
    *,
    config_path=None,
    base_config="configs/config.risk_off.json",
):
    cohort=frozen_cohort(root)
    directory=Path(snapshot)
    manifest=json.loads((directory/"run_manifest.json").read_text(encoding="utf-8"))
    sources=manifest.get("discovery_sources")
    asof=manifest.get("decision_date","")
    if not isinstance(sources,dict) or asof < FIRST_ELIGIBLE_MARKET_DATE:
        raise ValueError(
            "snapshot is not a valid prospective generalized-v0 experiment; "
            "decision date must be >= " + FIRST_ELIGIBLE_MARKET_DATE
        )
    config_review = None
    if config_path is not None:
        config_review = validate_experiment_config(
            config_path, base_config, root=root
        )
        if manifest.get("config_fingerprint") != config_review["config_fingerprint"]:
            raise ValueError("snapshot config fingerprint does not match experiment config")
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
    # Independent reconstruction: source hashes and aggregate counts are not
    # sufficient. Reject a same-count edit of source_id, theme, legacy bucket,
    # symbol provenance or the manual research reason in the snapshot.
    archived_paths = {}
    original_paths = {}
    for source in sources["source_files"]:
        kind = source["source_kind"]
        archived_paths[kind] = str(directory / source["archived_file"])
        original_paths[kind] = source["source_file"]
    _, reconstructed, reconstructed_rejects, _ = load_discovery_sources(archived_paths)
    def identity(row):
        item = dict(row)
        item["source_file"] = original_paths[item["source_kind"]]
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    if any(m.get("source_file") != original_paths.get(m.get("source_kind"))
           for m in members):
        raise ValueError("discovery membership source file provenance mismatch")
    if any(r.get("source_file") != original_paths.get(r.get("source_kind"))
           for r in rejected):
        raise ValueError("discovery source rejection file provenance mismatch")
    if sorted(map(identity, members)) != sorted(map(identity, reconstructed)):
        raise ValueError("discovery membership rows diverge from frozen input CSV")
    if sorted(map(identity, rejected)) != sorted(map(identity, reconstructed_rejects)):
        raise ValueError("discovery source rejections diverge from frozen input CSV")
    errors = validate_discovery_snapshot(
        memberships=members, rejected=rejected, summary=sources,
        discovery_symbols=set(ds) | set(xs), decision_date=asof,
    )
    if errors:
        raise ValueError("invalid discovery snapshot: " + "; ".join(errors))
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
                entry.append(dict(
                    relative_trailing(
                        symbol, ref, bars, asof,
                        shared_benchmarks=("QQQ", "SPY") if ref in {"QQQ", "SPY"} else (),
                    ),
                    coverage_stratum=group,
                    entry_v1=ds.get(symbol,{}).get("entry",{}).get("state",""),
                ))
    # Observe whether the same IEX bar series behaves differently as a
    # one-session gate versus a 20-session proxy. Neither is the snapshot gate.
    liquidity_by_group = []
    for group in sorted({x["coverage_stratum"] for x in liquidity}):
        rows = [x for x in liquidity if x["coverage_stratum"] == group]
        valid = [x for x in rows if x["coverage"] == "20_session_valid"]
        liquidity_by_group.append({
            "group": group,
            "symbols": len(rows),
            "valid_20session": len(valid),
            "bar_gate_disagreements": sum(x["disagreement"] is True for x in valid),
            "last_bar_fails": sum(x["last_bar_pass"] is False for x in valid),
            "mean_20session_fails": sum(x["mean_20session_pass"] is False for x in valid),
        })
    # Do not force sector-proxy equivalence. QQQ and SPY must be available
    # on the SAME stock/benchmark as-of date before their rankings can differ.
    entry_reference_diagnostics = []
    for group in sorted({x["coverage_stratum"] for x in per_symbol}):
        symbols = {x["symbol"] for x in per_symbol if x["coverage_stratum"] == group}
        examples = []
        for sym in sorted(symbols):
            refs = {x["benchmark"]: x for x in entry if x["symbol"] == sym}
            qqq = refs.get("QQQ", {})
            spy = refs.get("SPY", {})
            x = qqq.get("trailing_excess_60")
            y = spy.get("trailing_excess_60")
            if x is not None and y is not None:
                examples.append((sym, x, y))
        entry_reference_diagnostics.append({
            "group": group,
            "symbols": len(symbols),
            "aligned_60session_qqq_spy": len(examples),
            "sign_disagreement": sum((x > 0) != (y > 0) for _, x, y in examples),
            "opposite_sign_examples": [
                sym for sym, x, y in examples if (x > 0) != (y > 0)
            ],
        })
    report={
        "study":"generalized_research_v0",
        "mode":"read_only_diagnostic_not_strategy_validation",
        "decision_date":asof,"scanner_sha":manifest.get("code_sha"),
        "cohort_metadata_sha256":cohort["metadata_sha256"],
        "cohort_source_hashes":cohort["source_hashes"],
        "discovered":len(observed),"decisions":len(ds),"exclusions":len(xs),
        "source_rejections":len(rejected),"source_memberships":len(members),
        "groups":strata,
        "liquidity_by_group": liquidity_by_group,
        "entry_reference_diagnostics": entry_reference_diagnostics,
        "daily_symbols":manifest["daily_symbols"],
        "weekly_symbols":manifest["weekly_symbols"],
        "same_feed_bars_sha256":hash_file(bars_csv) if bars_csv else None,
        "experiment_config_review":config_review,
        "20session_turnover_coverage":sum(x["coverage"]=="20_session_valid" for x in liquidity),
        "60session_qqq_spy_comparison_coverage":sum(
            bool(bars) and
            relative_trailing(
                x, "QQQ", bars, asof, shared_benchmarks=("QQQ", "SPY")
            )["trailing_excess_60"] is not None and
            relative_trailing(
                x, "SPY", bars, asof, shared_benchmarks=("QQQ", "SPY")
            )["trailing_excess_60"] is not None
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
    out+=["","## IEX bar-only liquidity comparison by provisional group", "",
          "| Group | Symbols | 20-session valid | Bar proxy threshold disagreements |",
          "| --- | ---: | ---: | ---: |"]
    for x in report["liquidity_by_group"]:
        out.append("| {} | {} | {} | {} |".format(
            x["group"], x["symbols"], x["valid_20session"],
            x["bar_gate_disagreements"]))
    out+=["","## QQQ vs SPY trailing 60-session comparison", "",
          "| Group | Symbols | Comparable observations | Excess-return sign disagreements |",
          "| --- | ---: | ---: | ---: |"]
    for x in report["entry_reference_diagnostics"]:
        out.append("| {} | {} | {} | {} |".format(
            x["group"], x["symbols"], x["aligned_60session_qqq_spy"],
            x["sign_disagreement"]))
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
    au.add_argument("--config",required=True)
    au.add_argument("--base-config",default="configs/config.risk_off.json")
    au.add_argument("--out-dir",required=True)
    args=p.parse_args()
    if args.cmd=="prepare":
        print(json.dumps(prepare(args.base_config,args.output_config,args.cohort_dir),indent=2))
        return
    report,details,liquidity,entry=audit(
        args.snapshot,
        args.cohort_dir,
        args.bars_csv,
        config_path=args.config,
        base_config=args.base_config,
    )
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
