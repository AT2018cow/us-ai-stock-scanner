"""Frozen, research-only value/pullback adapters and paired cohort evaluation.

Production decisions are immutable inputs. Future outcomes enter only outcomes(),
after the canonical attention list has been selected.
"""
from __future__ import annotations

from dataclasses import replace
import math
from typing import Iterable

import numpy as np
import pandas as pd

from ai_value_scanner.decision import action as action_policy
from ai_value_scanner.decision.action import assign_action_priorities_v2, map_action_state_v2
from ai_value_scanner.decision.integrated import select_weekly_attention
from ai_value_scanner.decision.model import ActionState, EntryState, QualityGrade
from ai_value_scanner.research.top15_backtest import label_status, number

VARIANTS = ('D0', 'A', 'B', 'C')
CAP = 15
SEED = 61106


def conviction(d):
    """Actual production score, not the integer ordinal StockDecision.priority."""
    joint = action_policy._joint_conviction_score(d.quality, d.entry)
    if d.action_state is ActionState.PRIORITY_REVIEW and d.quality.grade is QualityGrade.A:
        joint += action_policy.H3_GRADE_A_BONUS
    if action_policy._has_pre_earnings_risk(d):
        joint -= action_policy.H3_PRE_EARNINGS_PRIORITY_PENALTY
    if action_policy._has_nonoperating_gain_risk(d):
        joint -= action_policy.H3_NONOPERATING_GAIN_PRIORITY_PENALTY
    if not math.isfinite(joint) or not -.12 <= joint <= 1.04:
        raise ValueError('production conviction outside frozen formula range')
    return joint


def signal(metrics):
    cash, growth = number(metrics.get('fcf_yield')), number(metrics.get('revenue_yoy'))
    if cash is None or growth is None or cash <= 0:
        return 0.0
    return .70 * min(cash/.08, 1.) + .30 * min(max(growth/.20, 0.), 1.)


def adapted_entry(d, metrics, *, relax=False, restrict=False, a_lower=.95, b_upper=1.05):
    entry = d.entry
    if entry.state in (EntryState.INSUFFICIENT_DATA, EntryState.TREND_DAMAGED):
        return entry
    s200 = number(metrics.get('price_to_sma200'))
    s50 = number(metrics.get('price_to_sma50'))
    ret = number(metrics.get('return_20d'))
    rs = number(metrics.get('relative_strength_60d_qqq'))
    regime = str(metrics.get('regime', 'unknown')).strip().lower()
    # The canonical builder reads regime and benchmark_trend_ok.
    benchmark = metrics.get('benchmark_trend_ok')
    benchmark_true = isinstance(benchmark, (bool, np.bool_)) and bool(benchmark)
    strong = (s200 is not None and s50 is not None and s50 > 0 and rs is not None
              and s200 >= 1.02 and s200/s50 >= 1 and rs >= 0
              and regime != 'down' and benchmark_true)
    result = entry
    if relax and strong and ret is not None and a_lower <= s50 <= 1.08 and -.07 <= ret <= .12:
        # Retain every canonical gate except the two explicitly relaxed bands.
        gates = entry.gate_results
        expected = {'sma50_band', 'ret20_band', 'ma_alignment', 'freshness', 'volatility_cap'}
        if expected <= {g.gate_key for g in gates} and not any(
            g.blocking for g in gates if g.gate_key not in {'sma50_band', 'ret20_band'}
        ):
            result = replace(entry, state=EntryState.ENTRY_READY)
    if restrict and result.state is EntryState.ENTRY_READY and (
        s200 is None or s50 is None or ret is None
        or s200 > 1.30 or s50 > b_upper or ret > .07
    ):
        result = replace(result, state=EntryState.WATCH_PULLBACK)
    return result


def layer(d):
    """Preserve production lexicographic layers as well as action ordering."""
    order = action_policy._ACTION_ORDER_V2[d.action_state]
    if d.action_state is ActionState.PRIORITY_REVIEW:
        return (order, 0)
    if d.action_state is ActionState.HOLD_MONITOR:
        return (order, 0 if d.entry.state is EntryState.ENTRY_READY else 1)
    return (order, action_policy._QUALITY_ORDER_V2[d.quality.grade])


def variants(decisions, lookup, names=VARIANTS, *, a_lower=.95, b_upper=1.05,
             c_weight=.10, combination=()):
    output = {}
    for name in names:
        factors = set(combination if name == 'COMBO' else (name,))
        if name == 'D0':
            output[name] = tuple(decisions)
            continue
        changed = []
        for d in decisions:
            entry = adapted_entry(d, lookup[d.symbol], relax='A' in factors,
                                  restrict='B' in factors, a_lower=a_lower, b_upper=b_upper)
            state, _ = map_action_state_v2(d.quality, entry)
            changed.append(replace(d, entry=entry, action_state=state))
        ordered = assign_action_priorities_v2(changed)
        if 'C' in factors:
            def key(d):
                p = conviction(d)
                s = signal(lookup[d.symbol]) if d.quality.grade in (QualityGrade.A, QualityGrade.B) else 0.
                return (*layer(d), -((1-c_weight)*p+c_weight*s), d.symbol)
            ordered = [replace(d, priority=i) for i, d in enumerate(sorted(ordered, key=key), 1)]
        output[name] = tuple(ordered)
    return output


def selections(decisions):
    top = select_weekly_attention(decisions, cap=CAP)
    return {'list': top, 'fixed_usage': tuple(d for d in top
            if d.action_state is ActionState.PRIORITY_REVIEW and d.entry.state is EntryState.ENTRY_READY)}


def outcomes(chosen, lookup, horizon, *, view):
    """Never reweight an unavailable selected outcome or treat it as cash."""
    denom = CAP if view == 'fixed_usage' else len(chosen)
    weights = [1/denom] * len(chosen) if denom else []
    returns = [number(lookup[d.symbol].get(f'fwd_ret_{horizon}'))
               if label_status(lookup[d.symbol], horizon) == 'observed' else None for d in chosen]
    missing = [d.symbol for d, r in zip(chosen, returns) if r is None]
    observed = sum(w*r for w, r in zip(weights, returns) if r is not None)
    net = observed if not missing and (chosen or view == 'fixed_usage') else None
    deployed = len(chosen)/CAP if view == 'fixed_usage' else float(bool(chosen))
    unknown_weight = sum(w for w, r in zip(weights, returns) if r is None)
    return dict(net_return=net, deployed=deployed, n_selected=len(chosen),
                n_invalid=len(missing), missing_symbols='|'.join(missing),
                scenario_low=observed-unknown_weight, scenario_high=observed+unknown_weight,
                stress_return=None if net is None else net-.003*deployed,
                severe=None if net is None else float(net <= -.20),
                stock_severe=None if missing or not chosen else sum(r <= -.20 for r in returns)/len(chosen))


def era(day):
    year = int(str(day)[:4])
    return '2016_2019' if year <= 2019 else '2020_2021' if year <= 2021 else '2022' if year == 2022 else '2023_2026'


def evaluate_cache(cache, names=VARIANTS, *, horizons=(20,60,120,252),
                   symbols=None, combination=(), a_lower=.95, b_upper=1.05, c_weight=.10):
    cohorts, members, stages = [], [], []
    previous = {}
    for item in cache:
        day, lookup, original = item['day'], item['lookup'], item['decisions']
        base = tuple(d for d in original if symbols is None or d.symbol in symbols)
        versions = variants(base, lookup, names, combination=combination,
                            a_lower=a_lower, b_upper=b_upper, c_weight=c_weight)
        # Slice-dependent D0 and comparators share exactly the same eligible set.
        pools = {'eligible_pool': base, 'ab_pool': tuple(d for d in base
                 if d.quality.grade in (QualityGrade.A, QualityGrade.B))}
        for name, ds in versions.items():
            chosen_views = selections(ds)
            for view, chosen in chosen_views.items():
                syms = {d.symbol for d in chosen}
                prev = previous.get((name,view), set())
                retained = len(syms & prev)/len(prev) if prev else None
                previous[(name,view)] = syms
                for h in horizons:
                    result = outcomes(chosen, lookup, h, view=view)
                    cohorts.append(dict(signal_date=day, variant=name, view=view, horizon=h,
                        year=day[:4], era=era(day), market_group=item['market_group'],
                        qualified=item['qualified'], qqq_return=item['qqq'][h],
                        mature=item['qqq'][h] is not None, retention=retained, **result))
                for d in chosen:
                    members.append(dict(signal_date=day, variant=name, view=view, symbol=d.symbol,
                        priority=d.priority, action=d.action_state.value, entry=d.entry.state.value,
                        quality_grade=d.quality.grade.value, quality_score=d.quality.score,
                        entry_score=d.entry.score, production_conviction=conviction(d),
                        signal=signal(lookup[d.symbol]), weight=1/(CAP if view=='fixed_usage' else len(chosen))))
            ab = pools['ab_pool']
            for stage, chosen in [('quality_ab',ab), ('ready',tuple(d for d in ds if
                d.quality.grade in (QualityGrade.A, QualityGrade.B) and d.entry.state is EntryState.ENTRY_READY)),
                ('priority',tuple(d for d in ds if d.action_state is ActionState.PRIORITY_REVIEW)),
                ('top15',chosen_views['list']),('fixed_usage',chosen_views['fixed_usage'])]:
                stages.append(dict(signal_date=day, variant=name, stage=stage,
                    **outcomes(chosen,lookup,60,view='fixed_usage' if stage=='fixed_usage' else 'list')))
        for pool, ds in pools.items():
            for h in horizons:
                result = outcomes(ds,lookup,h,view='list')
                valid = [number(lookup[d.symbol].get(f'fwd_ret_{h}')) for d in ds
                         if label_status(lookup[d.symbol],h)=='observed']
                cohorts.append(dict(signal_date=day, variant=pool, view='list',horizon=h,
                    year=day[:4],era=era(day),market_group=item['market_group'],qualified=item['qualified'],
                    qqq_return=item['qqq'][h],mature=item['qqq'][h] is not None,retention=None,
                    observable_mean=np.mean(valid) if valid else None,
                    coverage=len(valid)/len(ds) if ds else None,**result))
    return pd.DataFrame(cohorts), pd.DataFrame(members), pd.DataFrame(stages)


def common_dates(cohorts, names, horizon, view='fixed_usage'):
    part = cohorts[(cohorts.horizon==horizon)&(cohorts.view==view)&cohorts.variant.isin(names)]
    pivot = part.pivot(index='signal_date',columns='variant',values='net_return').reindex(columns=names)
    good = part.groupby('signal_date').apply(lambda x: bool(x.mature.all() and x.qualified.all()),include_groups=False)
    return pivot.index[pivot.notna().all(axis=1) & good.reindex(pivot.index,fill_value=False)]


def block_stats(deltas, *, block=6, repeats=2000, seed=SEED):
    """Calendar months remain in the sequence, including unavailable months."""
    if not len(deltas):
        return dict(n=0,mean=None,low=None,high=None,p=None)
    s = pd.Series(deltas.to_numpy(dtype=float),index=pd.to_datetime(deltas.index).to_period('M'))
    if s.index.duplicated().any():
        raise ValueError('block inference requires monthly observations')
    s=s.reindex(pd.period_range(s.index.min(),s.index.max(),freq='M'))
    values=s.to_numpy(); rng=np.random.default_rng(seed)
    starts=rng.integers(len(values),size=(repeats,math.ceil(len(values)/block)))
    indices=((starts[:,:,None]+np.arange(block))%len(values)).reshape(repeats,-1)[:,:len(values)]
    draws=values[indices]
    counts=np.isfinite(draws).sum(axis=1)
    means=np.nansum(draws,axis=1)/np.where(counts,counts,np.nan)
    mean=float(np.nanmean(values)); finite=means[np.isfinite(means)]
    if not len(finite):
        return dict(n=int(np.isfinite(values).sum()),mean=mean,low=None,high=None,p=None)
    return dict(n=int(np.isfinite(values).sum()),calendar_months=len(values),block=block,
                mean=mean,low=float(np.quantile(finite,.025)),high=float(np.quantile(finite,.975)),
                p=float((1+np.sum(finite-mean>=mean))/(1+len(finite))))


def holm(pvalues):
    ordered=sorted(pvalues,key=lambda k:pvalues[k]); maximum=0.; result={}
    for i,key in enumerate(ordered):
        maximum=max(maximum,min(1.,(len(ordered)-i)*pvalues[key])); result[key]=maximum
    return result


def paired_tables(cohorts,names):
    summaries, pairs, deployment, intervals=[],[],[],[]
    for view in ('list','fixed_usage'):
        for h in (20,60,120,252):
            dates=common_dates(cohorts,names,h,view)
            by={v:cohorts[(cohorts.variant==v)&(cohorts.horizon==h)&(cohorts.view==view)].set_index('signal_date') for v in names}
            base=by['D0'].reindex(dates)
            pools={v:cohorts[(cohorts.variant==v)&(cohorts.horizon==h)].set_index('signal_date') for v in ('eligible_pool','ab_pool')}
            for name in names:
                part=by[name].reindex(dates); delta=part.net_return-base.net_return
                segments=[('all','all',pd.Series(True,index=dates))]
                for col in ('year','era','market_group'):
                    segments += [(col,str(k),part[col].eq(k)) for k in part[col].unique()]
                for kind,key,mask in segments:
                    p=part[mask]; b=base[mask]
                    row=dict(variant=name,view=view,horizon=h,segment_type=kind,segment=key,
                        n_dates=len(p),mean_return=p.net_return.mean(),mean_delta=(p.net_return-b.net_return).mean(),
                        qqq_return=p.qqq_return.mean(),qqq_excess=(p.net_return-p.qqq_return).mean(),
                        qqq_win_share=(p.net_return>p.qqq_return).mean(),severe_rate=p.severe.mean(),
                        severe_delta=(p.severe-b.severe).mean(),mean_deployed=p.deployed.mean(),
                        mean_retention=p.retention.mean(),stock_severe_rate=p.stock_severe.mean())
                    for pool,all_p in pools.items():
                        q=all_p.reindex(p.index)
                        complete=q.net_return.notna()
                        row[pool+'_excess']=(p.net_return-q.net_return)[complete].mean()
                        row[pool+'_complete_dates']=int(complete.sum())
                        row[pool+'_coverage']=q.coverage.mean()
                        row[pool+'_observable_excess']=(p.net_return-q.observable_mean).mean()
                    summaries.append(row)
                if name!='D0' and view=='fixed_usage':
                    for day in dates:
                        p,b=part.loc[day],base.loc[day]
                        pairs.append(dict(signal_date=day,variant=name,horizon=h,base=b.net_return,
                            candidate=p.net_return,delta=p.net_return-b.net_return,
                            stress_delta=p.stress_return-b.stress_return))
                        if h==60:
                            both=p.deployed>0 and b.deployed>0
                            matched=min(p.deployed,b.deployed)*(p.net_return/p.deployed-b.net_return/b.deployed) if both else None
                            deployment.append(dict(signal_date=day,variant=name,base_deployed=b.deployed,
                                candidate_deployed=p.deployed,both_deployed=both,matched_delta=matched,
                                actual_delta=p.net_return-b.net_return))
                    if h==60 and not pd.to_datetime(delta.index).to_period('M').duplicated().any():
                        for block in (6,12):
                            intervals.append(dict(variant=name,**block_stats(delta,block=block)))
    return tuple(pd.DataFrame(x) for x in (summaries,pairs,deployment,intervals))


def initial_screen(summary,names):
    s=summary[(summary.view=='fixed_usage')&(summary.segment_type=='all')]
    result={}
    for name in names:
        if name=='D0':continue
        def row(h):return s[(s.variant==name)&(s.horizon==h)].iloc[0]
        a,b=row(60),row(120)
        result[name]=dict(pass_screen=bool(a.n_dates>0 and b.n_dates>0 and a.mean_delta>0
            and b.mean_delta>=0 and a.severe_delta<=.01),delta60=number(a.mean_delta),
            delta120=number(b.mean_delta),severe_delta=number(a.severe_delta))
    return result
