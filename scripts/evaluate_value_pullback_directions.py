#!/usr/bin/env python3
"""Approved v4 value/pullback research; no market/SEC requests or production writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
import tempfile
import time

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ai_value_scanner.config import load_config
from ai_value_scanner.decision.integrated import build_stock_decisions, select_weekly_attention
from ai_value_scanner.decision.universe import apply_price_liquidity_prefilter
from ai_value_scanner.research.provenance import sha256_file
from ai_value_scanner.research.top15_backtest import label_status, market_group, number, validate_inputs
from ai_value_scanner.research.value_pullback import (
    CAP, SEED, conviction, evaluate_cache, initial_screen, selections, outcomes,
    paired_tables, common_dates, holm, variants, signal,
)

STUDIES={'monthly':['sip_2016_2020_v1','sip_2021_2026_v1'],
         'covid':['sip_covid_weekly_v1'],'bear':['sip_bear_weekly_v1']}
LEGACY={'monthly':'sip_monthly','covid':'sip_covid_weekly','bear':'sip_bear_weekly'}


def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,(np.bool_,)):return bool(x)
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
    return x


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(data),indent=2,allow_nan=False)+'\n')


def atomic_bundle(out, writer):
    if out.exists():raise ValueError('output already exists; validate identity before reuse')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.'+out.name,dir=out.parent) as temp:
        staging=Path(temp)/'bundle';staging.mkdir()
        writer(staging)
        staging.rename(out)


def verify_bundle(out,identity):
    m=json.loads((out/'manifest.json').read_text())
    if m['identity']!=identity:raise ValueError('run specification mismatch')
    for name,digest in m['files'].items():
        if sha256_file(out/name)!=digest:raise ValueError('checkpoint payload mismatch: '+name)
    return m


def finish_bundle(path,identity,**extra):
    files={str(p.relative_to(path)):sha256_file(p) for p in sorted(path.rglob('*')) if p.is_file()}
    write_json(path/'manifest.json',dict(identity=identity,files=files,**extra))


def prepare(source,out,scope,identity,*,smoke=False):
    """P0: canonical reconstruction and independent old-slot/old-cohort parity."""
    if out.exists():return verify_bundle(out,identity)
    started=time.monotonic();config=load_config(ROOT/'configs/config.production.json')
    input_ids={};frames=[];contracts=[]
    for study in STUDIES[scope]:
        folder=source/'datasets'/study
        success=json.loads((folder/'success.json').read_text())
        if sha256_file(folder/'dataset.csv')!=success['sha256'] or sha256_file(folder/'dataset.meta.json')!=success['metadata_sha256']:
            raise ValueError('frozen dataset identity mismatch')
        meta=json.loads((folder/'dataset.meta.json').read_text())
        assert meta['market_data_feed']=='sip' and meta['entry_price_mode']=='next_open' and meta['exit_price_mode']=='close'
        assert abs(meta['roundtrip_cost']-.003)<1e-12
        frames.append(pd.read_csv(folder/'dataset.csv',low_memory=False))
        for name in ('dataset.csv','dataset.meta.json','success.json'):
            input_ids[str((folder/name).relative_to(source))]=sha256_file(folder/name)
        contracts.append(dict(study=study,feed='sip',cost=.003,entry='next_open',exit='close'))
    frame=pd.concat(frames,ignore_index=True);validate_inputs(frame)
    if set(frame.market_data_feed.dropna())!={'sip'}:raise ValueError('mixed or unspecified feed')
    if smoke:
        wanted={'2016-01-29','2019-02-28','2020-03-31','2022-06-30','2024-08-30'}
        frame=frame[frame.signal_date.isin(wanted)]
    old=source/'evaluations'/f'evaluation_{LEGACY[scope]}_v2'
    for name in ('manifest.json','slots.csv','cohorts.csv'):
        input_ids[str((old/name).relative_to(source))]=sha256_file(old/name)
    reference=pd.read_csv(old/'slots.csv',low_memory=False)
    reference=reference[reference.variant.eq('baseline')]
    previous=pd.read_csv(old/'cohorts.csv',low_memory=False)
    previous=previous[previous.variant.eq('baseline')].set_index(['signal_date','view','horizon'])
    cache=[];checks=0;max_error=0.;coverage=[];score_range=[]
    for day,g in frame.groupby('signal_date',sort=True):
        lookup={r['symbol']:r for r in g.to_dict('records')}
        eligible,excluded=apply_price_liquidity_prefilter(g,min_price=config.min_price,
            min_dollar_volume=config.min_dollar_volume,market_data_feed='sip')
        decisions=build_stock_decisions(eligible,decision_date=day,generated_at_utc=day+'T23:59:59Z',policy_version='v2')
        for d in decisions:score_range.append(conviction(d))
        def unique(column):
            vals=pd.to_numeric(g[column],errors='coerce').dropna().unique()
            if len(vals)>1:raise ValueError('mixed benchmark evidence')
            return number(vals[0]) if len(vals) else None
        regime=market_group(unique('qqq_price_to_sma200'),unique('qqq_trailing_return_60d'))
        qqq={h:unique(f'qqq_return_{h}') for h in (20,60,120,252)}
        item=dict(day=str(day),lookup=lookup,decisions=decisions,market_group=regime,qualified=regime!='unknown',qqq=qqq)
        cache.append(item)
        coverage.append(dict(signal_date=day,n_inputs=len(g),eligible=len(eligible),excluded=len(excluded),
            market_group=regime,unknown_fundamental_asof=int(g.fundamental_data_asof.isna().sum()),
            future_evidence=0,feature_missing_fcf=int(g.fcf_yield.isna().sum()),feature_missing_revenue=int(g.revenue_yoy.isna().sum())))
        for view,chosen in selections(decisions).items():
            old_view='usage' if view=='fixed_usage' else view
            for h in (20,60,120,252):
                ref=reference[(reference.signal_date==day)&(reference.view==old_view)&(reference.horizon==h)]
                assert list(ref.symbol)==[d.symbol for d in chosen],('membership parity',day,view,h)
                for d,(_,r) in zip(chosen,ref.iterrows()):
                    assert (d.priority,d.quality.grade.value,d.action_state.value,d.entry.state.value)==(r['rank'],r.grade,r.action,r.entry)
                    for a,b in [(d.quality.score,r.quality_score),(d.entry.score,r.entry_score),
                                (1/(CAP if view=='fixed_usage' else len(chosen)),r.weight)]:
                        if number(a) is None and number(b) is None:continue
                        error=abs(a-b);assert error<=1e-10;max_error=max(max_error,error)
                    assert label_status(lookup[d.symbol],h)==r.label_status
                    checks+=1
                fresh=outcomes(chosen,lookup,h,view=view);prior=previous.loc[(day,old_view,h)]
                for key in ('net_return','stress_return','n_selected','n_observed','n_invalid'):
                    value=(fresh['n_selected']-fresh['n_invalid']) if key=='n_observed' else fresh[key]
                    a,b=number(value),number(prior[key])
                    if a is None and b is None:continue
                    assert a is not None and b is not None and abs(a-b)<=1e-10,('cohort parity',day,view,h,key,a,b)
                    max_error=max(max_error,abs(a-b))
        print(json.dumps(dict(stage='P0',scope=scope,date=day,eligible=len(decisions),elapsed=round(time.monotonic()-started,1))),flush=True)
    parity=dict(pass_parity=True,scope=scope,dates=len(cache),rows=len(frame),slot_checks=checks,
        max_error=max_error,production_conviction_min=min(score_range,default=None),
        production_conviction_max=max(score_range,default=None),
        c_integer_priority_unsuitable=True,contracts=contracts,
        market_warmup_excluded_from_formal_comparison=True,
        inputs=input_ids,elapsed_seconds=time.monotonic()-started)
    def publish(path):
        with (path/'cache.pkl').open('wb') as f:pickle.dump(cache,f,pickle.HIGHEST_PROTOCOL)
        pd.DataFrame(coverage).to_csv(path/'coverage.csv',index=False)
        write_json(path/'baseline_parity.json',parity)
        finish_bundle(path,identity,scope=scope,parity=parity)
    atomic_bundle(out,publish)
    return verify_bundle(out,identity)


def load_cache(folder,identity):
    verify_bundle(folder,identity)
    with (folder/'cache.pkl').open('rb') as f:return pickle.load(f)


def run_evaluation(prepared,out,scope,identity,names,*,combination=()):
    if out.exists():return verify_bundle(out,identity)
    cache=load_cache(prepared,identity)
    cohorts,members,stages=evaluate_cache(cache,names,combination=combination)
    summary,pairs,deployment,intervals=paired_tables(cohorts,names)
    if scope!='monthly':
        # Weekly cohorts are pressure diagnostics; monthly block inference is not applicable.
        intervals=pd.DataFrame()
    screen=initial_screen(summary,names)
    def publish(path):
        for name,table in dict(cohorts=cohorts,members=members,stages=stages,
            summary_by_horizon=summary,paired_deltas=pairs,deployment_attribution=deployment,
            time_block_intervals=intervals).items():table.to_csv(path/(name+'.csv'),index=False)
        write_json(path/'screen.json',screen)
        finish_bundle(path,identity,scope=scope,names=list(names),combination=list(combination),screen=screen)
    atomic_bundle(out,publish)
    return verify_bundle(out,identity)


def robustness(prepared,evaluation,out,identity,names,*,combination=()):
    if out.exists():return verify_bundle(out,identity)
    cache=load_cache(prepared,identity);verify_bundle(evaluation,identity)
    cohorts=pd.read_csv(evaluation/'cohorts.csv');summary=pd.read_csv(evaluation/'summary_by_horizon.csv')
    screen=initial_screen(summary,names);passed=[n for n in names if n!='D0' and screen[n]['pass_screen']]
    rows=[];ex_rows=[];threshold=[];cost=[]
    rng=np.random.default_rng(SEED);symbols=sorted({d.symbol for i in cache for d in i['decisions']})
    # Cache candidate decisions once: pure score/state rules don't depend on the future outcome or subset.
    decision_maps={}
    eligible_returns={}
    for item in cache:
        decision_maps[item['day']]=variants(item['decisions'],item['lookup'],names,combination=combination)
        eligible_returns[item['day']]={d.symbol:(number(item['lookup'][d.symbol].get('fwd_ret_60'))
            if label_status(item['lookup'][d.symbol],60)=='observed' else None) for d in item['decisions']}
    def fast_subset(subset,name):
        records=[]
        for item in cache:
            ds=decision_maps[item['day']][name]
            chosen=selections(tuple(d for d in ds if d.symbol in subset))['fixed_usage']
            valid_returns=eligible_returns[item['day']]
            values=[valid_returns[d.symbol] for d in chosen]
            r=dict(net_return=sum(values)/CAP if all(v is not None for v in values) else None)
            pool=[v for s,v in valid_returns.items() if s in subset]
            pool_returns=[v for v in pool if v is not None]
            records.append(dict(signal_date=item['day'],qualified=item['qualified'],mature=item['qqq'][60] is not None,
                pool_return=float(np.mean(pool_returns)) if len(pool_returns)==len(pool) and pool else None,**r))
        return pd.DataFrame(records).set_index('signal_date')
    if passed:
        for repeat in range(200):
            subset=set(rng.choice(symbols,size=math.floor(.70*len(symbols)),replace=False))
            base=fast_subset(subset,'D0')
            for name in passed:
                p=fast_subset(subset,name)
                valid=base.net_return.notna()&p.net_return.notna()&p.qualified&p.mature
                rows.append(dict(repeat=repeat,variant=name,n_dates=int(valid.sum()),
                    delta=(p.net_return-base.net_return)[valid].mean(),mean_return=p.net_return[valid].mean(),
                    pool_excess=(p.net_return-p.pool_return)[valid].mean()))
            if repeat%20==0:print(json.dumps(dict(stage='P3_subsets',completed=repeat+1,total=200)),flush=True)
        for name in passed:
            dates=common_dates(cohorts,names,60)
            def top5(which):
                contributions={}
                for item in cache:
                    if item['day'] not in dates:continue
                    chosen=selections(decision_maps[item['day']][which])['fixed_usage']
                    for d in chosen:
                        r=item['lookup'][d.symbol]['fwd_ret_60']
                        contributions[d.symbol]=contributions.get(d.symbol,0)+(r-item['qqq'][60])/CAP/len(dates)
                return sorted(contributions,key=lambda s:(-contributions[s],s))[:5]
            own,bt=top5(name),top5('D0')
            for kind,deleted in [('union',sorted(set(own+bt))),('candidate_top5',own),('baseline_top5',bt)]:
                subset=set(symbols)-set(deleted);b=fast_subset(subset,'D0');p=fast_subset(subset,name)
                valid=b.net_return.notna()&p.net_return.notna()&p.qualified&p.mature
                ex_rows.append(dict(variant=name,kind=kind,deleted='|'.join(deleted),n_dates=int(valid.sum()),
                    delta=(p.net_return-b.net_return)[valid].mean(),mean_return=p.net_return[valid].mean()))
            if name in ('A','B','C'):
                values={'A':(.94,.96),'B':(1.04,1.06),'C':(.05,.15)}[name]
                for value in values:
                    kwargs={dict(A='a_lower',B='b_upper',C='c_weight')[name]:value}
                    c,_,_=evaluate_cache(cache,('D0',name),horizons=(60,),**kwargs)
                    dates2=common_dates(c,('D0',name),60)
                    pivot=c[(c.view=='fixed_usage')&c.variant.isin(('D0',name))].pivot(index='signal_date',columns='variant',values='net_return')
                    threshold.append(dict(variant=name,value=value,n_dates=len(dates2),delta=(pivot[name]-pivot.D0).reindex(dates2).mean()))
            dates3=common_dates(cohorts,names,60)
            p=cohorts[(cohorts.variant==name)&(cohorts.view=='fixed_usage')&(cohorts.horizon==60)].set_index('signal_date')
            b=cohorts[(cohorts.variant=='D0')&(cohorts.view=='fixed_usage')&(cohorts.horizon==60)].set_index('signal_date')
            cost.append(dict(variant=name,bps_per_side=30,n_dates=len(dates3),
                delta=(p.stress_return-b.stress_return).reindex(dates3).mean()))
    def publish(path):
        for key,table in [('symbol_subsampling',rows),('ex_top5',ex_rows),('threshold_sensitivity',threshold),('cost_sensitivity',cost)]:
            if table:pd.DataFrame(table).to_csv(path/(key+'.csv'),index=False)
        finish_bundle(path,identity,passed=passed,skipped=None if passed else 'no candidate passes initial screen')
    atomic_bundle(out,publish)
    return verify_bundle(out,identity)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('prepare','evaluate','robustness'),required=True)
    parser.add_argument('--source-root',required=True);parser.add_argument('--output-root',required=True)
    parser.add_argument('--scope',choices=tuple(STUDIES),default='monthly')
    parser.add_argument('--identity',required=True);parser.add_argument('--names',default='D0,A,B')
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args();identity=json.loads(Path(args.identity).read_text());base=Path(args.output_root)
    if any(p.startswith('decisions') for p in base.parts):raise ValueError('formal decision roots forbidden')
    names=tuple(args.names.split(','));scope=args.scope
    if args.stage=='prepare':r=prepare(Path(args.source_root),base/'prepared'/scope,scope,identity,smoke=args.smoke)
    elif args.stage=='evaluate':r=run_evaluation(base/'prepared'/scope,base/'evaluations'/scope,scope,identity,names)
    else:r=robustness(base/'prepared'/scope,base/'evaluations'/scope,base/'robustness'/scope,identity,names)
    print(json.dumps(clean({k:v for k,v in r.items() if k not in ('files','identity')})),flush=True)


if __name__=='__main__':main()
