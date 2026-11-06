#!/usr/bin/env python3
"""Thin offline entry point for canonical Top-15 cross-cycle evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_value_scanner.research.top15_backtest import evaluate, summarize, paired_report, random_distribution, baseline_evidence
from ai_value_scanner.config import load_config
from ai_value_scanner.research.provenance import provenance_path, sha256_file


def clean(value):
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [clean(v) for v in value]
    if isinstance(value, (float,np.floating)): return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.bool_): return bool(value)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',action='append',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--protocol',default='docs/review_20261106/same_day_backtest/protocol.json')
    parser.add_argument('--config',default='configs/config.production.json')
    parser.add_argument('--code-sha',default=None,help='Launcher identity when the worker has no Git checkout; source hashes remain authoritative.')
    args=parser.parse_args()
    out=Path(args.output).resolve()
    if out.exists(): raise ValueError('output must be a new directory')
    if (ROOT/'outputs/decisions').resolve() in (out,*out.parents): raise ValueError('canonical snapshot directory forbidden')
    protocol=json.loads(Path(args.protocol).read_text())
    if protocol['candidate']!='remove_age_proxy_priority_penalty': raise ValueError('unsupported registered candidate')
    # Resolve provenance before expensive evaluation or output creation.
    # absolute() preserves Modal's logical mount, unlike resolve().
    inputs={provenance_path(p,ROOT):sha256_file(p) for p in args.dataset}
    frames=[pd.read_csv(p,low_memory=False) for p in args.dataset]
    contracts=[]
    for path in args.dataset:
        meta_path=Path(path).with_suffix('.meta.json')
        if not meta_path.exists():
            contracts.append(dict(dataset=Path(path).name,status='unknown_metadata'))
            continue
        meta=json.loads(meta_path.read_text())
        inputs[provenance_path(meta_path,ROOT)]=sha256_file(meta_path)
        cost=meta.get('roundtrip_cost',2*float(meta.get('trading_cost_bps',float('nan')))/10000)
        if abs(cost-.003)>1e-12 or not np.isfinite(cost): raise ValueError('input labels must already include 15bps per side')
        if meta.get('entry_price_mode')!='next_open' or meta.get('exit_price_mode')!='close':
            raise ValueError('input entry/exit convention differs from registered protocol')
        contracts.append(dict(dataset=Path(path).name,status='verified_label_contract',
                              metadata_sha256=hashlib.sha256(meta_path.read_bytes()).hexdigest(),
                              feed=meta.get('market_data_feed','legacy_unspecified'),cost=cost))
    frame=pd.concat(frames,ignore_index=True)
    config=load_config(args.config)
    slots,cohorts,diagnostics=evaluate(frame,seed=protocol['random_seed'],
                                     min_price=config.min_price,min_dollar_volume=config.min_dollar_volume)
    summary=summarize(cohorts); paired=paired_report(cohorts,slots)
    random_summary=random_distribution(slots)
    tables=dict(slots=slots,cohorts=cohorts,diagnostics=diagnostics,summary=summary,random_distribution=random_summary)
    coverage=frame.assign(year=frame.signal_date.str[:4]).groupby('year').agg(n_rows=('symbol','size'),n_symbols=('symbol','nunique'),n_dates=('signal_date','nunique'))
    qualification=diagnostics.assign(year=diagnostics.signal_date.str[:4]).groupby('year').agg(
        n_dates=('signal_date','size'),n_market_qualified=('market_group',lambda x:x.ne('unknown').sum()),
        mean_prefilter_eligible=('n_prefilter_eligible','mean'),mean_list_size=('n_baseline','mean')
    )
    common = []
    for (view,h), part in cohorts.groupby(['view','horizon']):
        pivot=part.pivot(index='signal_date',columns='variant',values='net_return')
        comparators=['baseline','no_age_penalty','ab_pool','random_k'] if view=='list' else ['baseline','no_age_penalty']
        dates=pivot[comparators].dropna().index
        for variant in comparators:
            p=part[(part.variant==variant)&part.signal_date.isin(dates)&part.excess.notna()]
            common.append(dict(view=view,horizon=h,variant=variant,n_dates=len(p),mean_return=p.net_return.mean(),mean_excess=p.excess.mean()))
    tables['common_date_summary']=pd.DataFrame(common)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.py'))}
    sources[str(Path(__file__).relative_to(ROOT))]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest=dict(protocol=protocol,protocol_sha256=hashlib.sha256(Path(args.protocol).read_bytes()).hexdigest(),
                  config_sha256=hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
                  config_path=provenance_path(args.config,ROOT),
                  prefilter=dict(min_price=config.min_price,min_dollar_volume=config.min_dollar_volume,
                                 feed=frame.market_data_feed.iloc[0] if 'market_data_feed' in frame else 'iex'),
                  inputs=inputs,sources=sources,code_sha=args.code_sha or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  input_contracts=contracts,
                  n_rows=len(frame),n_dates=frame.signal_date.nunique(),start=frame.signal_date.min(),end=frame.signal_date.max(),
                  universe_sources=sorted(frame.watchlist_source.dropna().unique()) if 'watchlist_source' in frame else ['unknown'],
                  candidate_adopted=False,paired=paired,
                  baseline_evidence=baseline_evidence(cohorts),
                  caveats=['retrospective universe approximation','price returns, split adjusted; dividends excluded on both legs',
                           'monthly sampling does not validate daily S2 or previous-day downgrade alert slots',
                           'dates without benchmark SMA200/60d history remain logged but excluded from formal paired comparison',
                           'no annualized account return from overlapping cohorts','missing labels retained as unknown, not cash'])
    manifest['official_market_mode']=config.official_market_mode
    if manifest['prefilter']['feed']!='iex' and config.official_market_mode!='sip_eod':
        manifest['caveats'].append('SIP study: 2m dollar-volume threshold has different semantics from production IEX; no direct production promotion')
    elif config.official_market_mode=='sip_eod':
        manifest['caveats'].append('Official SIP EOD mode: 2m dollar-volume floor uses consolidated volume; historical IEX figures are not liquidity-equivalent')
    lines=['# Current Top-15 backtest','',f"Coverage: {manifest['start']} .. {manifest['end']}; {manifest['n_dates']} dates.",'',
           'Retrospective evidence; candidate adoption is gated, not automatic.','',
           '| View | Horizon | Dates valid/all | Mean net return | QQQ excess |','| --- | --- | --- | --- | --- |']
    for _,r in summary[(summary.variant=='baseline')&(summary.segment_type=='all')].iterrows():
        lines.append(f"| {r['view']} | {r.horizon} | {r.n_valid}/{r.n_dates} | {r.mean_return:.3%} | {r.mean_excess:.3%} |")
    lines+=['','See manifest.json for candidate gates and scope limitations.']
    manifest_text=json.dumps(clean(manifest),indent=2,allow_nan=False)+'\n'
    out.parent.mkdir(parents=True,exist_ok=True)
    # Publish a complete bundle. A failed write leaves no final directory that
    # would block a retry or look like a resumable checkpoint.
    with tempfile.TemporaryDirectory(prefix=f'.{out.name}.',dir=out.parent) as temporary:
        staging=Path(temporary)/'result';staging.mkdir()
        for name,data in tables.items():data.to_csv(staging/f'{name}.csv',index=False)
        coverage.to_csv(staging/'coverage_by_year.csv')
        qualification.to_csv(staging/'qualification_by_year.csv')
        (staging/'manifest.json').write_text(manifest_text)
        (staging/'report.md').write_text('\n'.join(lines)+'\n')
        if out.exists():raise ValueError('output must be a new directory')
        staging.rename(out)
    print(json.dumps(clean(dict(output=str(out),n_dates=manifest['n_dates'],paired=paired)),allow_nan=False))


if __name__=='__main__': main()
