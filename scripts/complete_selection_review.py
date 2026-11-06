#!/usr/bin/env python3
"""Complete bounded attribution using frozen data, without new price/SEC replay."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ai_value_scanner.config import load_config
from ai_value_scanner.research.provenance import provenance_path,sha256_file,validate_config_identity
from ai_value_scanner.research.selection_attribution import stage_attribution,concentration_and_costs,proximity
from evaluate_current_top15 import clean

SCOPES={'sip_monthly':['sip_2016_2020_v1','sip_2021_2026_v1'],
        'iex_monthly':['iex_2021_2026_v1'],
        'sip_covid_weekly':['sip_covid_weekly_v1'],
        'sip_bear_weekly':['sip_bear_weekly_v1']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--smoke',action='store_true')
    p.add_argument('--tolerance',type=float,default=.01)
    p.add_argument('--scope',choices=['all',*SCOPES],default='all')
    p.add_argument('--frozen-root',default=str(ROOT/'outputs/review_20261106/infi_results'))
    p.add_argument('--evaluation-root',default=str(ROOT/'outputs/review_20261106/infi_evaluations'))
    p.add_argument('--config',default=str(ROOT/'configs/config.production.json'))
    args=p.parse_args()
    if not 0<=args.tolerance<=1:raise ValueError('invalid tolerance')
    output=Path(args.output)
    if output.exists():raise ValueError('output must be new')
    config=load_config(args.config)
    inputs={};start=time.monotonic();proximity_rows=[]
    scopes=['sip_monthly'] if args.smoke else (list(SCOPES) if args.scope=='all' else [args.scope])
    # No partial output if an upstream evaluation used other thresholds.
    for scope in scopes:
        saved=Path(args.evaluation_root)/f'evaluation_{scope}_v2/manifest.json'
        validate_config_identity(json.loads(saved.read_text()),args.config)
    output.mkdir(parents=True)
    for scope in scopes:
        print(f'{scope}: loading frozen inputs',flush=True)
        frames=[]
        for name in SCOPES[scope]:
            base=Path(args.frozen_root)/name
            path=base/'dataset.csv';digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if digest!=json.loads((base/'success.json').read_text())['sha256']:raise ValueError('dataset hash mismatch')
            inputs[provenance_path(path,ROOT)]=digest;frames.append(pd.read_csv(path,low_memory=False))
        raw=pd.concat(frames,ignore_index=True)
        old=Path(args.evaluation_root)/f'evaluation_{scope}_v2'
        slots=pd.read_csv(old/'slots.csv',low_memory=False);cohorts=pd.read_csv(old/'cohorts.csv')
        for name in ['slots.csv','cohorts.csv','manifest.json']:
            path=old/name;inputs[provenance_path(path,ROOT)]=sha256_file(path)
        if args.smoke:
            days=['2016-11-30','2020-03-31','2022-06-30']
            raw=raw[raw.signal_date.isin(days)];slots=slots[slots.signal_date.isin(days)];cohorts=cohorts[cohorts.signal_date.isin(days)]
        stages,members,edges,cases=stage_attribution(raw,slots,cohorts,min_price=config.min_price,
                                                  min_dollar_volume=config.min_dollar_volume,
                                                  progress=lambda s:print(scope+': '+s,flush=True))
        concentrations,costs,sensitivity,contributions=concentration_and_costs(raw,slots,cohorts)
        folder=output/scope;folder.mkdir()
        for name,data in [('stages_by_date',stages),('stage_members',members),('stage_comparisons',edges),
                          ('concentration_by_date',concentrations),('costs',costs),
                          ('concentration_sensitivity',sensitivity),('symbol_contributions',contributions)]:
            data.to_csv(folder/(name+'.csv'),index=False)
        (folder/'casebook.json').write_text(json.dumps(clean(cases),indent=2,allow_nan=False)+'\n')
        summary=[]
        for (variant,view,classification),part in concentrations[concentrations.research_qualified].groupby(['variant','view','classification']):
            summary.append(dict(variant=variant,view=view,classification=classification,n_dates=len(part),
                                mean_known_coverage=part.known_coverage.mean(),mean_top_nav_share=part.top_group_nav_share.mean(),
                                max_top_nav_share=part.top_group_nav_share.max(),mean_top_stock_share=part.top_group_stock_share.mean(),
                                mean_hhi_known=part.hhi_known.mean(),mean_deployed=part.deployed.mean()))
        pd.DataFrame(summary).to_csv(folder/'concentration_summary.csv',index=False)
        for variant in ['baseline','no_age_penalty']:
            for view in ['list','usage']:
                subset=cohorts[cohorts.horizon.eq(60)&cohorts.variant.eq(variant)&cohorts.view.eq(view)]
                result=proximity(subset.set_index('signal_date').excess,args.tolerance)
                proximity_rows.append(dict(scope=scope,variant=variant,view=view,**result))
        print(f'{scope}: complete, {len(stages)} stage rows; elapsed {time.monotonic()-start:.1f}s',flush=True)
    pd.DataFrame(proximity_rows).to_csv(output/'qqq_proximity.csv',index=False)
    sources=[ROOT/'src/ai_value_scanner/research/selection_attribution.py',ROOT/'src/ai_value_scanner/research/provenance.py',Path(__file__),
             *[ROOT/'src/ai_value_scanner'/name for name in ['decision/quality.py','decision/entry.py','decision/action.py','decision/universe.py','research/top15_backtest.py']]]
    manifest=dict(inputs=inputs,sources={str(x.relative_to(ROOT)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sources},
                  config_path=provenance_path(args.config,ROOT),config_sha256=sha256_file(args.config),
                  protocol_sha256=hashlib.sha256((ROOT/'docs/review_20261106/same_day_backtest/supplement_protocol.json').read_bytes()).hexdigest(),
                  elapsed_seconds=time.monotonic()-start,smoke=args.smoke,tolerance=args.tolerance,
                  evidence_class='supplemental already-viewed retrospective diagnostics; original candidate result unchanged',
                  new_strategy_candidates=0,classification='current SIC descriptions / SIC 2-digit; not historical GICS',
                  weights='deletion sensitivity leaves cash; no renormalization; original complete common dates retained')
    (output/'manifest.json').write_text(json.dumps(clean(manifest),indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
