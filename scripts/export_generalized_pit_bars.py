"""Bounded, credentialed, same-IEX-feed research bar export for a frozen v0 snapshot.

Raw Alpaca bars are split-adjusted with documented corporate actions, preserving
turnover. Never query future bars, rewrite a snapshot, or silently accept a
failed split request. Run only after the PR has merged and the user approves.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta, timezone, datetime
import hashlib
import json
import math
from pathlib import Path
import sys

from ai_value_scanner.config import load_config
from ai_value_scanner.scanner import load_runtime_settings, apply_split_adjustment
from research_generalized_selection import (
    FIRST_ELIGIBLE_MARKET_DATE,
    PROXY,
    frozen_cohort,
    validate_experiment_config,
)


def export_bars(snapshot, config_path, out_dir, *, cohort_dir):
    cohort=frozen_cohort(cohort_dir)
    root=Path(snapshot)
    manifest=json.loads((root/"run_manifest.json").read_text(encoding="utf-8"))
    asof=manifest["decision_date"]
    if asof < FIRST_ELIGIBLE_MARKET_DATE:
        raise ValueError(
            "frozen v0 decision date must be >= " + FIRST_ELIGIBLE_MARKET_DATE
        )
    discovery=manifest.get("discovery_sources")
    if not isinstance(discovery,dict):
        raise ValueError("requires generalized opt-in snapshot")
    if (discovery.get("unique_symbols")!=len(cohort["symbols"]) or
            discovery.get("source_memberships")!=75):
        raise ValueError("snapshot is not the frozen generalized-v0 research cohort")
    if manifest["candidate_universe"]["market_data_feed"]!="iex":
        raise ValueError("study must use the identical IEX market-data feed")
    config_review = validate_experiment_config(
        config_path,
        "configs/config.risk_off.json",
        root=cohort_dir,
    )
    if manifest.get("config_fingerprint") != config_review["config_fingerprint"]:
        raise ValueError("snapshot config fingerprint does not match experiment config")
    config=load_config(config_path)
    archived={row.get("source_kind"):row for row in discovery.get("source_files",[])}
    if set(archived)!=set(cohort["paths"]):
        raise ValueError("snapshot source file manifest is not the v0 cohort")
    for kind in cohort["paths"]:
        row=archived[kind]
        if row.get("sha256")!=cohort["source_hashes"][kind]:
            raise ValueError("snapshot source file SHA does not match frozen cohort")
        if hashlib.sha256((root/row["archived_file"]).read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError("snapshot archived source file has changed")
    base=config_path
    symbols=sorted(cohort["symbols"]|{"QQQ","SPY"}|set(PROXY.values()))
    if len(symbols)>90:
        raise ValueError("bars request exceeds pre-registered 90-symbol budget")
    output=Path(out_dir)
    if output.exists():
        raise FileExistsError("will not overwrite market-data research evidence")
    # Fetch up to ~120-130 sessions to cover 60 common-session observations.
    begin=(date.fromisoformat(asof)-timedelta(days=185)).isoformat()
    alpaca,_,monitor=load_runtime_settings(config)
    if alpaca.feed.lower()!="iex":
        raise ValueError("ALPACA_FEED must be iex")
    bars=alpaca.get_daily_bars(
        symbols,begin+"T00:00:00Z",min(config.chunk_size,90)
    )
    # Fail closed: an unavailable splits endpoint must not generate misleading
    # unadjusted QQQ/SPY/sector-relative returns.
    splits=alpaca.get_corporate_action_splits(
        symbols,begin,asof
    )
    network_state=monitor.to_dict()
    if network_state.get("stale_market_data_fallback_used"):
        raise ValueError("stale market-data fallback: bar research must not use it")
    rows=[]
    for symbol in symbols:
        adjusted=apply_split_adjustment(bars.get(symbol,[]),splits.get(symbol))
        for item in adjusted:
            session=str(item.get("t",""))[:10]
            if not session or session>asof or session<begin:
                continue
            try:
                close=float(item["c"])
                volume=float(item["v"])
            except (ValueError,TypeError,KeyError):
                continue
            if not math.isfinite(close) or not math.isfinite(volume) or close<=0 or volume<0:
                continue
            rows.append((symbol,session,"iex",close,volume))
    rows.sort()
    if len(rows)!=len({(row[0],row[1]) for row in rows}):
        raise ValueError("duplicate OHLCV symbol/session after split normalization")
    output.mkdir(parents=True,exist_ok=False)
    csv_path=output/"pit_iex_daily_bars.csv"
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(("symbol","session","feed","close","volume"))
        writer.writerows(rows)
    bar_sha=hashlib.sha256(csv_path.read_bytes()).hexdigest()
    coverage={s:sum(row[0]==s for row in rows) for s in symbols}
    info={
        "session":asof,"first_session_requested":begin,
        "exported_at_utc":datetime.now(timezone.utc).isoformat(),
        "snapshot_code_sha":manifest["code_sha"],
        "input_config_sha256":hashlib.sha256(Path(base).read_bytes()).hexdigest(),
        "config_fingerprint":config_review["config_fingerprint"],
        "base_config_sha256":config_review["base_config_sha256"],
        "source_cohort_hashes":cohort["source_hashes"],
        "feed":"iex",
        "adjustment":"split_adjusted_close_and_volume_alpaca_corporate_actions",
        "bar_dataset_sha256":bar_sha,
        "symbols_requested":len(symbols),"symbols_exported_with_bars":sum(v>0 for v in coverage.values()),
        "rows":len(rows),
        "coverage_by_symbol":coverage,
        "network_monitor":network_state,
        "limitations":[
            "Split adjustment preserves dollar turnover but not dividend-adjusted returns.",
            "ETF proxies are research approximations, not verified sector group assignments.",
            "Single-day daily bars are not identical to Alpaca snapshot hard gate.",
            "The existing Alpaca client may fetch later bars; any bars after the decision session are discarded BEFORE analysis.",
            "No post-decision bars are exported; no forward returns or v2 policy promotion.",
        ],
    }
    (output/"pit_bars_manifest.json").write_text(
        json.dumps(info,indent=2,sort_keys=True)+"\n",encoding="utf-8"
    )
    return info


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot",required=True)
    parser.add_argument("--config",required=True)
    parser.add_argument("--out-dir",required=True)
    parser.add_argument("--cohort-dir",default="data/research/generalized_v0")
    args=parser.parse_args()
    summary=export_bars(args.snapshot,args.config,args.out_dir,
                        cohort_dir=args.cohort_dir)
    print(json.dumps({
        "dataset_sha256":summary["bar_dataset_sha256"],
        "symbols_requested":summary["symbols_requested"],
        "symbols_with_bars":summary["symbols_exported_with_bars"],
        "rows":summary["rows"],
        "out_dir":args.out_dir,
    },indent=2))


if __name__=="__main__":
    main()
