"""Bounded retrospective attribution; no new strategy or threshold search."""
from __future__ import annotations

import math
import pandas as pd

from ai_value_scanner.decision.quality import build_company_quality_v2
from ai_value_scanner.decision.entry import build_entry_quality_v2
from ai_value_scanner.decision.action import map_action_state_v2
from ai_value_scanner.decision.universe import apply_price_liquidity_prefilter
from .top15_backtest import label_status, number

STAGES = ('eligible_all','quality_ab','quality_ab_ready','priority_review',
          'priority_top15','action_eligible_ab','weekly_top15')
EDGES = tuple(zip(STAGES[:4],STAGES[1:5])) + (
    ('quality_ab','action_eligible_ab'),('action_eligible_ab','weekly_top15'),
    ('priority_top15','fixed_usage'))


def text(value):
    token=str(value).strip()
    return None if token.lower() in {'','nan','none','<na>','nat'} else token


def industry_key(value):
    return text(value) or 'UNKNOWN'


def sic2(value):
    x=number(value)
    return str(int(x)).zfill(4)[:2] if x is not None and 0<=x<=9999 else 'UNKNOWN'


def concentration(part, column):
    """Industry HHI conditional on known classifications, plus missing exposure."""
    total=float(part.weight.sum())
    unknown=part[column].eq('UNKNOWN')
    known=part.loc[~unknown].groupby(column).weight.sum()
    known_total=float(known.sum())
    return dict(n_symbols=part.symbol.nunique(),deployed=total,cash=max(0.,1-total),
                unknown_weight=float(part.loc[unknown,'weight'].sum()),
                known_coverage=known_total/total if total else None,
                top_group=known.idxmax() if len(known) else None,
                top_group_nav_share=float(known.max()) if len(known) else None,
                top_group_stock_share=float(known.max()/total) if len(known) and total else None,
                hhi_known=float(((known/known_total)**2).sum()) if known_total else None)


def proximity(excess, tolerance=.01):
    """Observed proximity and interval-supported noninferiority are distinct."""
    from .top15_backtest import block_interval
    valid=excess.dropna().sort_index()
    lo,hi,block=block_interval(valid.to_numpy(),valid.index.to_series(),60)
    mean=float(valid.mean()) if len(valid) else None
    return dict(n_dates=len(valid),tolerance=tolerance,mean_excess=mean,
                observed_close=bool(mean>=-tolerance) if mean is not None else None,
                ci_low=lo,ci_high=hi,block_dates=block,
                interval_supports_close=bool(lo>=-tolerance) if lo is not None else None)


def stage_attribution(raw, slots, cohorts, *, min_price=1.,min_dollar_volume=2_000_000,progress=None):
    slots=slots[slots.horizon.eq(60)]
    cohorts=cohorts[cohorts.horizon.eq(60)]
    rows=[]; members=[]
    for i,(day,group) in enumerate(raw.groupby('signal_date',sort=True),1):
        day=str(day)
        source=cohorts[cohorts.signal_date.eq(day)&cohorts.variant.eq('baseline')]
        base=source[source.view.eq('list')].iloc[0]
        usage=source[source.view.eq('usage')].iloc[0]
        p=slots[slots.signal_date.eq(day)]
        saved=p[p.variant.eq('ab_pool')&p.view.eq('list')].set_index('symbol')
        top=p[p.variant.eq('baseline')&p.view.eq('list')]
        frame,_=apply_price_liquidity_prefilter(group,min_price=min_price,
                            min_dollar_volume=min_dollar_volume,market_data_feed=str(group.market_data_feed.iloc[0]))
        evidence={}
        for r in frame.to_dict('records'):
            q=build_company_quality_v2(r,decision_date=day,data_asof=text(r.get('fundamental_data_asof')))
            e=build_entry_quality_v2(r,decision_date=day,market_asof=text(r.get('market_asof')))
            a,_=map_action_state_v2(q,e)
            if r['symbol'] in saved.index:
                old=saved.loc[r['symbol']]
                if old.grade!=q.grade.value or old.entry!=e.state.value or old.action!=a.value:
                    raise ValueError('frozen decision state parity failed')
            r.update(grade=q.grade.value,entry=e.state.value,action=a.value,
                     quality_score=q.score,quality_confidence=q.confidence,entry_score=e.score,
                     quality_risks='|'.join(x.code for x in q.risks),entry_risks='|'.join(x.code for x in e.risks))
            evidence[r['symbol']]=r
        all_names=set(evidence)
        ab={s for s,r in evidence.items() if r['grade'] in {'A','B'}}
        ready={s for s in ab if evidence[s]['entry']=='ENTRY_READY'}
        priority={s for s in ready if evidence[s]['action']=='PRIORITY_REVIEW'}
        eligible={s for s in ab if evidence[s]['action']!='AVOID'}
        if eligible!=set(saved.index):raise ValueError('frozen A/B pool membership parity failed')
        ordered=sorted(priority,key=lambda s:int(saved.loc[s,'rank']))
        capped=set(ordered[:15])
        actual=set(top.symbol)
        used=set(top[top.action.eq('PRIORITY_REVIEW')&top.entry.eq('ENTRY_READY')].symbol)
        if capped!=used or not actual<=eligible:raise ValueError('final selection parity failed')
        selections=dict(zip(STAGES,[all_names,ab,ready,priority,capped,eligible,actual]))
        for stage,names in selections.items():
            observed=[]
            for symbol in sorted(names):
                r=evidence[symbol];status=label_status(r,60)
                value=number(r.get('fwd_ret_60')) if status=='observed' else None
                observed.append(value)
                members.append(dict(signal_date=day,stage=stage,symbol=symbol,grade=r['grade'],entry=r['entry'],action=r['action'],
                                    quality_score=r['quality_score'],entry_score=r['entry_score'],net_return=value,
                                    industry=industry_key(r.get('sic_description')),revenue_yoy=r.get('revenue_yoy'),
                                    fcf_yield=r.get('fcf_yield'),return_20d=r.get('return_20d'),
                                    fundamental_data_asof=r.get('fundamental_data_asof'),market_asof=r.get('market_asof'),
                                    quality_risks=r['quality_risks'],entry_risks=r['entry_risks'],label_status=status))
            values=[v for v in observed if v is not None]
            complete=len(values)==len(names)
            net=sum(values)/len(values) if values and complete and bool(base.research_qualified) else None
            rows.append(dict(signal_date=day,stage=stage,n_members=len(names),n_observed=len(values),
                             n_invalid=len(names)-len(values),research_qualified=bool(base.research_qualified),
                             coverage=len(values)/len(names) if names else None,
                             observed_mean=sum(values)/len(values) if values and bool(base.research_qualified) else None,
                             net_return=net,qqq_return=base.qqq_return,
                             excess=net-base.qqq_return if net is not None and pd.notna(base.qqq_return) else None,
                             severe_loss_rate=sum(v<-.20 for v in values)/len(values) if values and complete else None))
        rows.append(dict(signal_date=day,stage='fixed_usage',n_members=int(usage.n_selected),n_observed=int(usage.n_observed),
                         n_invalid=int(usage.n_invalid),research_qualified=bool(base.research_qualified),
                         coverage=usage.n_observed/usage.n_selected if usage.n_selected else None,
                         observed_mean=usage.net_return if bool(base.research_qualified) else None,
                         net_return=usage.net_return if bool(base.research_qualified) else None,
                         qqq_return=base.qqq_return,excess=usage.excess,severe_loss_rate=usage.severe_loss_rate))
        if progress and (i==1 or i%20==0):progress(f'stages {i}: {day}')
    stage_rows=pd.DataFrame(rows);member_rows=pd.DataFrame(members)
    edge_rows=[];cases=[]
    for parent,child in EDGES:
        a=stage_rows[stage_rows.stage.eq(parent)].set_index('signal_date')
        b=stage_rows[stage_rows.stage.eq(child)].set_index('signal_date')
        mask=a.net_return.notna()&b.net_return.notna()&a.qqq_return.notna()
        delta=(b.net_return-a.net_return)[mask]
        conditional_mask=a.observed_mean.notna()&b.observed_mean.notna()&a.qqq_return.notna()
        conditional_delta=(b.observed_mean-a.observed_mean)[conditional_mask]
        edge_rows.append(dict(parent=parent,child=child,n_dates_total=len(a),n_dates_common=int(mask.sum()),
                              n_child_empty=int(b.n_members.eq(0).sum()),
                              parent_mean=float(a.net_return[mask].mean()),child_mean=float(b.net_return[mask].mean()),
                              mean_delta=float(delta.mean()),median_delta=float(delta.median()),
                              n_conditional_dates=int(conditional_mask.sum()),conditional_delta=float(conditional_delta.mean()),
                              mean_parent_coverage=a.coverage[conditional_mask].mean(),mean_child_coverage=b.coverage[conditional_mask].mean(),
                              severe_delta=float((b.severe_loss_rate-a.severe_loss_rate)[mask].mean())))
        case_delta=delta if len(delta) else conditional_delta
        if len(case_delta):
            for kind,day in [('worst',case_delta.idxmin()),('best',case_delta.idxmax())]:
                pa=member_rows[member_rows.signal_date.eq(day)&member_rows.stage.eq(parent)]
                ch=member_rows[member_rows.signal_date.eq(day)&member_rows.stage.eq(child)]
                # fixed_usage changes weights, not the names already capped.
                if child=='fixed_usage':ch=pa.copy()
                removed=pa[~pa.symbol.isin(ch.symbol)].sort_values('net_return',ascending=kind=='best')
                added=ch[~ch.symbol.isin(pa.symbol)].sort_values('net_return',ascending=kind=='worst')
                cases.append(dict(parent=parent,child=child,kind=kind,signal_date=day,delta=float(case_delta[day]),
                                  comparison_basis='complete_dates' if len(delta) else 'conditional_observed_outcomes',
                                  parent_count=int(a.loc[day,'n_members']),child_count=int(b.loc[day,'n_members']),
                                  removed=removed.head(3).to_dict('records'),added=added.head(3).to_dict('records'),
                                  interpretation='ex-post membership/weight association, not independent causal contribution'))
    return stage_rows,member_rows,pd.DataFrame(edge_rows),cases


def concentration_and_costs(raw,slots,cohorts):
    slots=slots[slots.horizon.eq(60)&slots.variant.isin(['baseline','no_age_penalty'])].copy()
    cohorts=cohorts[cohorts.horizon.eq(60)&cohorts.variant.isin(['baseline','no_age_penalty'])].copy()
    classes=raw[['signal_date','symbol','sic']].copy()
    classes['sic2']=classes.sic.map(sic2)
    slots=slots.merge(classes[['signal_date','symbol','sic2']],on=['signal_date','symbol'],validate='many_to_one')
    slots['industry']=slots.industry.map(industry_key)
    concentration_rows=[]
    for _,r in cohorts.iterrows():
        p=slots[slots.signal_date.eq(r.signal_date)&slots.variant.eq(r.variant)&slots.view.eq(r['view'])]
        for column in ['industry','sic2']:
            concentration_rows.append(dict(signal_date=r.signal_date,variant=r.variant,view=r['view'],classification=column,
                                           research_qualified=r.research_qualified,**concentration(p,column)))
    costs=[];sensitivities=[];contributions=[]
    for view in ['list','usage']:
        c=cohorts[cohorts.view.eq(view)].copy()
        a=c[c.variant.eq('baseline')].set_index('signal_date');b=c[c.variant.eq('no_age_penalty')].set_index('signal_date')
        valid=a.research_qualified&a.qqq_return.notna()&a.net_return.notna()&b.net_return.notna()
        days=a.index[valid]
        baseline=slots[slots.view.eq(view)&slots.variant.eq('baseline')&slots.signal_date.isin(days)].copy()
        baseline['contribution']=baseline.net_return*baseline.weight/max(1,len(days))
        totals=baseline.groupby('symbol').contribution.sum().sort_values(ascending=False)
        exposures=baseline[baseline.industry.ne('UNKNOWN')].groupby('industry').weight.sum()
        largest=exposures.idxmax() if len(exposures) else None
        removed_sets={'original':set(),'drop_top_symbol':set(totals.head(1).index),'drop_top3_symbols':set(totals.head(3).index)}
        for symbol,value in totals.items():
            contributions.append(dict(view=view,symbol=symbol,n_dates=int(baseline.symbol.eq(symbol).sum()),
                                      contribution_to_mean=float(value),mean_nav_weight=float(baseline.loc[baseline.symbol.eq(symbol),'weight'].sum()/max(1,len(days)))))
        for variant in ['baseline','no_age_penalty']:
            p=slots[slots.view.eq(view)&slots.variant.eq(variant)&slots.signal_date.isin(days)]
            for scenario in [*removed_sets,'drop_top_industry']:
                kept=p[~p.industry.eq(largest)] if scenario=='drop_top_industry' else p[~p.symbol.isin(removed_sets[scenario])]
                if scenario=='drop_top_industry' and largest is None:continue
                ret=(kept.net_return*kept.weight).groupby(kept.signal_date).sum().reindex(days,fill_value=0.)
                deployed=kept.groupby('signal_date').weight.sum().reindex(days,fill_value=0.)
                sensitivities.append(dict(view=view,variant=variant,scenario=scenario,n_dates=len(days),mean_return=ret.mean(),
                                          mean_excess=(ret-a.qqq_return.reindex(days)).mean(),
                                          exposure_excess=(ret-deployed*a.qqq_return.reindex(days)).mean(),
                                          removed_symbols='|'.join(sorted(removed_sets.get(scenario,set()))),
                                          removed_industry=largest if scenario=='drop_top_industry' else None))
            part=c[c.variant.eq(variant)&c.signal_date.isin(days)].set_index('signal_date')
            for bps in [15,30]:
                deployed=part.n_selected/15 if view=='usage' else part.n_selected.gt(0).astype(float)
                extra=2*(bps-15)/10000
                stock=part.net_return-deployed*extra
                benchmark=part.qqq_return-extra
                costs.append(dict(view=view,variant=variant,per_side_bps=bps,n_dates=len(part),
                                  mean_deployed=deployed.mean(),mean_return=stock.mean(),mean_qqq=benchmark.mean(),
                                  mean_excess=(stock-benchmark).mean(),exposure_excess=(stock-deployed*benchmark).mean()))
    return pd.DataFrame(concentration_rows),pd.DataFrame(costs),pd.DataFrame(sensitivities),pd.DataFrame(contributions)
