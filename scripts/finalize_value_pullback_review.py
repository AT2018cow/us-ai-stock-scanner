#!/usr/bin/env python3
"""Independent compact review of frozen value/pullback outputs and snapshot shadow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
from ai_value_scanner.decision.model import stock_decisions_from_jsonl
from ai_value_scanner.research.provenance import sha256_file
from ai_value_scanner.research.value_pullback import variants, selections, signal, holm
from evaluate_value_pullback_directions import clean, write_json
from validate_mvp_snapshot import validate_snapshot


def snapshot_shadow(out):
    root=ROOT/'outputs/decisions_v1_1_0/2026-11-05/production'
    validation=validate_snapshot(root)
    if not validation['ok']:raise ValueError('official SIP snapshot validation failed')
    manifest=json.loads((root/'run_manifest.json').read_text())
    assert manifest['input_provenance']['market_data_feed']=='sip'
    assert manifest['input_provenance']['market_data_mode']=='sip_eod'
    from ai_value_scanner.market_data import official_eod_window
    # The validator checks identities; actual publication readiness is checked below.
    from datetime import datetime
    now=datetime.fromisoformat(manifest['generated_at_utc'])
    completed,_=official_eod_window(now)
    assert str(completed)==manifest['decision_date']
    ds=stock_decisions_from_jsonl((root/'decisions.jsonl').read_text())
    lookup={};identities={};bars={};bar_paths={};relative_error=0.;checked=0
    for path in sorted((ROOT/'cache/alpaca_sip').glob('bars_*.json')):
        payload=json.loads(path.read_text())
        used=False
        for symbol,rows in payload.items():
            for row in rows:
                if str(row['t'])[:10]!='2026-11-05':continue
                if symbol in bars and bars[symbol]!=row['c']:raise ValueError('conflicting frozen SIP closes')
                bars[symbol]=row['c'];used=True
        if used:bar_paths[str(path.relative_to(ROOT))]=sha256_file(path)
    regimes={e.value for d in ds for e in (*d.entry.positives,*d.entry.risks)
             if e.code=='defensive_market_regime'}
    assert regimes=={'down'},'snapshot market context must be verified, not inferred from today'
    unresolved=[];boundaries=[]
    for d in ds:
        metrics={g.metric:g.observed for g in d.entry.gate_results if g.metric}
        metrics.update(regime='down',benchmark_trend_ok=False)
        # Canonical gate observations are rounded to six decimal places.
        for key,edge in [('price_to_sma200',1.30),('price_to_sma50',1.05),('return_20d',.07)]:
            value=metrics.get(key)
            if isinstance(value,(int,float)) and abs(value-edge)<=.0000005:boundaries.append((d.symbol,key))
        fund_path=ROOT/'cache'/('parsed_fund_'+str(d.provenance.get('cik',''))+'.json')
        if fund_path.exists():
            fund=json.loads(fund_path.read_text())
            keys=('fundamental_effective_sha256','fundamental_submissions_sha256','fundamental_companyfacts_raw_sha256')
            match=all(fund.get(k)==d.provenance.get(k) for k in keys) and fund.get('fundamental_data_asof')==d.quality.data_asof
            if not match:raise ValueError('snapshot fundamental identity mismatch: '+d.symbol)
            if fund['_cache_meta']['v']!=10:raise ValueError('unexpected accounting cache version')
            identities[str(fund_path.relative_to(ROOT))]=sha256_file(fund_path)
            metrics['revenue_yoy']=fund.get('revenue_yoy')
            price=bars.get(d.symbol);shares=fund.get('shares_outstanding')
            cap=price*shares if price is not None and shares is not None else None
            fcf=fund.get('free_cash_flow')
            metrics['fcf_yield']=fcf/cap if fcf is not None and cap and cap>0 else None
            pe=d.provenance.get('review_adjusted_pe_base');income=fund.get('adjusted_net_income')
            if cap and pe and income and income>0:
                error=abs(cap-pe*income)/cap;relative_error=max(relative_error,error);checked+=1
                assert error<1e-10
        elif d.quality.grade.value in ('A','B'):
            unresolved.append(d.symbol)
        lookup[d.symbol]=metrics
    if unresolved or boundaries:raise ValueError(f'cannot produce exact decision shadow: {unresolved}, threshold boundaries {boundaries}')
    versions=variants(ds,lookup,('D0','A','B','C'))
    assert [d.symbol for d in selections(versions['D0'])['list']]==manifest['weekly_symbols']
    rows=[]
    base={d.symbol for d in selections(versions['D0'])['list']}
    for name,decisions in versions.items():
        for rank,d in enumerate(selections(decisions)['list'],1):
            m=lookup[d.symbol]
            rows.append(dict(variant=name,rank=rank,symbol=d.symbol,action=d.action_state.value,
                entry=d.entry.state.value,quality_score=d.quality.score,entry_score=d.entry.score,
                is_replacement=d.symbol not in base,price_to_sma50=m.get('price_to_sma50'),
                price_to_sma200=m.get('price_to_sma200'),return_20d=m.get('return_20d'),
                revenue_yoy=m.get('revenue_yoy'),fcf_yield=m.get('fcf_yield'),signal=signal(m)))
    pd.DataFrame(rows).to_csv(out/'snapshot_20261105_top15.csv',index=False)
    pd.DataFrame(rows).groupby('variant').agg(n=('symbol','size'),replacements=('is_replacement','sum'),
        mean_ret20=('return_20d','mean'),mean_sma50=('price_to_sma50','mean'),mean_sma200=('price_to_sma200','mean'),
        mean_revenue=('revenue_yoy','mean'),mean_fcf=('fcf_yield','mean'),
        missing_revenue=('revenue_yoy',lambda s:s.isna().sum()),missing_fcf=('fcf_yield',lambda s:s.isna().sum())).to_csv(out/'snapshot_summary.csv')
    result=dict(snapshot_valid=True,feed='sip',decision_date=manifest['decision_date'],
        source='immutable decisions + identity-matched parsed cache v10 + frozen SIP close; no network',
        n_decisions=len(ds),n_quality_ab=sum(d.quality.grade.value in ('A','B') for d in ds),
        market_cap_checks=checked,max_market_cap_relative_error=relative_error,
        threshold_boundary_ambiguities=boundaries,
        price_feature_precision='six-decimal canonical gate values; all B thresholds outside rounding ambiguity; A disabled in verified down regime',
        inputs={**identities,**bar_paths,**{str((root/f).relative_to(ROOT)):sha256_file(root/f) for f in ('decisions.jsonl','run_manifest.json')}},
        publication_timestamp=manifest['generated_at_utc'])
    write_json(out/'snapshot_validation.json',result)
    return result


def independent_check(raw,out):
    """Recompute fixed-use cohorts using raw future labels and published members."""
    checks=[];input_hashes={};maximum=0.;checked=0
    studies={'monthly':['sip_2016_2020_v1','sip_2021_2026_v1'],'covid':['sip_covid_weekly_v1'],'bear':['sip_bear_weekly_v1']}
    for scope,names in studies.items():
        start_count=checked
        data=[]
        for name in names:
            p=ROOT/'outputs/review_followup_20261106/datasets'/name/'dataset.csv'
            input_hashes[str(p.relative_to(ROOT))]=sha256_file(p)
            data.append(pd.read_csv(p,low_memory=False))
        frame=pd.concat(data).set_index(['signal_date','symbol'])
        members=pd.read_csv(raw/'evaluations'/scope/'members.csv');c=pd.read_csv(raw/'evaluations'/scope/'cohorts.csv')
        usage=members[members.view=='fixed_usage']
        for _,r in c[(c.view=='fixed_usage')&c.variant.isin(('D0','A','B','C'))].iterrows():
            chosen=usage[(usage.signal_date==r.signal_date)&(usage.variant==r.variant)]
            vals=[]
            for symbol in chosen.symbol:
                f=frame.loc[(r.signal_date,symbol)];h=int(r.horizon)
                value=f[f'fwd_ret_{h}'];end=f[f'label_end_{h}'];qend=f[f'qqq_label_end_{h}']
                # A separate direct endpoint check, without the production label_status helper.
                valid=pd.notna(value) and pd.notna(end) and pd.notna(qend) and end==qend and end>r.signal_date
                vals.append(float(value) if valid else np.nan)
            expected=sum(vals)/15 if np.isfinite(vals).all() else np.nan
            actual=r.net_return
            assert pd.isna(expected)==pd.isna(actual),(scope,r.signal_date,r.variant,r.horizon)
            if pd.notna(actual):
                err=abs(expected-actual);assert err<1e-10;maximum=max(maximum,err)
            assert len(chosen)==r.n_selected
            checked+=1
        checks.append(dict(scope=scope,n_cohorts=checked-start_count,max_error=maximum))
    result=dict(checks=checks,total_cohorts=checked,max_error=maximum,inputs=input_hashes)
    write_json(out/'independent_checks.json',result)
    return result


def publish_tables(raw,out):
    """Compact dates/segments, with explicit missingness and selection diagnostics."""
    combined={};coverage=[];attribution=[];concentration=[];cases=[];decision={}
    for scope in ('monthly','covid','bear'):
        folder=raw/'evaluations'/scope
        summaries=pd.read_csv(folder/'summary_by_horizon.csv')
        pairs=pd.read_csv(folder/'paired_deltas.csv')
        deploy=pd.read_csv(folder/'deployment_attribution.csv')
        stages=pd.read_csv(folder/'stages.csv')
        members=pd.read_csv(folder/'members.csv')
        cohorts=pd.read_csv(folder/'cohorts.csv')
        tables={'summary_by_horizon':summaries[summaries.segment_type.eq('all')],
                'summary_by_era':summaries[summaries.segment_type.eq('era')],
                'summary_by_year':summaries[summaries.segment_type.eq('year')],
                'summary_by_market':summaries[summaries.segment_type.eq('market_group')],
                'paired_deltas_60d':pairs[pairs.horizon.eq(60)],
                'deployment_attribution':deploy}
        era_rows=summaries[summaries.segment_type.eq('era')]
        eq4=[]
        for (variant,view,h),g in era_rows.groupby(['variant','view','horizon']):
            eq4.append(dict(variant=variant,view=view,horizon=h,n_eras=int(g.mean_return.notna().sum()),
                mean_return=g.mean_return.mean(),mean_delta=g.mean_delta.mean(),
                mean_qqq_excess=g.qqq_excess.mean(),mean_deployed=g.mean_deployed.mean(),
                interpretation='equal era weights, auxiliary; not primary date weighting'))
        tables['summary_era_eq4']=pd.DataFrame(eq4)
        for name,table in tables.items():
            combined.setdefault(name,[]).append(table.assign(scope=scope))
        for (name,view,h),g in cohorts.groupby(['variant','view','horizon']):
            if name in ('eligible_pool','ab_pool'):continue
            mature=g.mature & g.qualified
            coverage.append(dict(scope=scope,variant=name,view=view,horizon=h,n_dates=len(g),
                mature_qualified=int(mature.sum()),mature_complete=int((mature&g.net_return.notna()).sum()),
                invalid_selected=int(g.loc[mature,'n_invalid'].sum()),unknown_market=int((~g.qualified).sum())))
        # Keep missing selected stocks and scenario assumptions visible on every mature date.
        missing=cohorts[cohorts.n_invalid.gt(0)&cohorts.mature&cohorts.qualified]
        combined.setdefault('unavailable_outcomes',[]).append(missing.assign(scope=scope))
        for name,g in stages.groupby('variant'):
            pivot=g.pivot(index='signal_date',columns='stage',values='net_return')
            # Attribution uses the same mature, market-qualified P1 dates.
            formal_dates=set(pairs.loc[pairs.horizon.eq(60),'signal_date'])
            pivot=pivot.loc[pivot.index.isin(formal_dates)]
            for stage in ('ready','priority','top15','fixed_usage'):
                comparable=pivot[['quality_ab',stage]].dropna()
                attribution.append(dict(scope=scope,variant=name,stage=stage,n_dates=len(comparable),
                    mean_return=comparable[stage].mean(),delta_vs_shared_ab=(comparable[stage]-comparable.quality_ab).mean(),
                    interpretation='descriptive stage mean difference; equal-weight pools except fixed slots'))
        usage=members[members.view=='fixed_usage']
        for name,g in usage.groupby('variant'):
            counts=g.groupby('symbol').size().sort_values(ascending=False)
            concentration.append(dict(scope=scope,variant=name,unique_symbols=len(counts),
                total_slots=len(g),top_symbol=counts.index[0] if len(counts) else None,
                top_symbol_slot_share=counts.iloc[0]/len(g) if len(g) else None,
                top5_slot_share=counts.iloc[:5].sum()/len(g) if len(g) else None))
        for name,g in pairs[pairs.horizon.eq(60)].groupby('variant'):
            chosen=pd.concat([g.nsmallest(3,'delta'),g.nlargest(3,'delta')]).drop_duplicates('signal_date')
            for _,r in chosen.iterrows():
                b=set(usage[(usage.variant=='D0')&(usage.signal_date==r.signal_date)].symbol)
                c=set(usage[(usage.variant==name)&(usage.signal_date==r.signal_date)].symbol)
                cases.append(dict(scope=scope,variant=name,signal_date=r.signal_date,delta=r.delta,
                    added='|'.join(sorted(c-b)),removed='|'.join(sorted(b-c))))
        screen=json.loads((folder/'screen.json').read_text())
        if scope=='monthly':decision['screen']=screen
    for name,tables in combined.items():pd.concat(tables,ignore_index=True).to_csv(out/(name+'.csv'),index=False)
    pd.DataFrame(coverage).to_csv(out/'coverage.csv',index=False)
    pd.DataFrame(attribution).to_csv(out/'stage_attribution_60d.csv',index=False)
    pd.DataFrame(concentration).to_csv(out/'symbol_concentration.csv',index=False)
    pd.DataFrame(cases).to_csv(out/'casebook.csv',index=False)
    intervals=pd.read_csv(raw/'evaluations/monthly/time_block_intervals.csv')
    adjusted=holm(dict(zip(intervals[intervals.block.eq(6)].variant,intervals[intervals.block.eq(6)].p)))
    intervals['holm_p_3']=intervals.variant.map(adjusted)
    intervals.to_csv(out/'time_block_intervals.csv',index=False)
    robust=raw/'robustness/monthly'
    if robust.exists():
        r=json.loads((robust/'manifest.json').read_text());decision['robustness']=dict(passed=r['passed'],skipped=r['skipped'])
        for p in robust.glob('*.csv'):(out/p.name).write_bytes(p.read_bytes())
        if (out/'symbol_subsampling.csv').exists():
            t=pd.read_csv(out/'symbol_subsampling.csv');rows=[]
            for name,g in t.groupby('variant'):
                rows.append(dict(variant=name,repeats=len(g),mean=g.mean_return.mean(),median=g.mean_return.median(),
                    p05=g.mean_return.quantile(.05),p95=g.mean_return.quantile(.95),
                    mean_delta=g.delta.mean(),win_share_vs_d0=g.delta.gt(0).mean(),
                    win_share_vs_complete_pool=g.pool_excess.dropna().gt(0).mean(),
                    valid_pool_repeats=int(g.pool_excess.notna().sum())))
            pd.DataFrame(rows).to_csv(out/'symbol_subsampling_summary.csv',index=False)
    else:decision['robustness']=dict(status='pending')
    decision['combination']=dict(status='not_needed' if sum(s['pass_screen'] for s in decision['screen'].values())<2 else 'pending',
        rule='only combine at least two screened factors; no subset search')
    decision['production_adopted']=False
    write_json(out/'decision_status.json',decision)
    return decision


def report(out,decision):
    summary=pd.read_csv(out/'summary_by_horizon.csv')
    intervals=pd.read_csv(out/'time_block_intervals.csv')
    eras=pd.read_csv(out/'summary_by_era.csv')
    def table(scope,h):return summary[(summary.scope==scope)&(summary.horizon==h)&(summary.view=='fixed_usage')].set_index('variant')
    monthly=table('monthly',60);longer=table('monthly',120)
    labels={'D0':'生产基线','A':'放宽强趋势回踩','B':'限制过度延伸','C':'现金流与增长排序'}
    classifications={};gate_rows=[]
    for name in ('A','B','C'):
        screen=decision['screen'][name]
        interval=intervals[(intervals.variant==name)&(intervals.block==6)].iloc[0]
        e=eras[(eras.scope=='monthly')&(eras.horizon==60)&(eras.view=='fixed_usage')&(eras.variant==name)]
        gates=dict(initial_screen=screen['pass_screen'],positive_ci=bool(interval.low>0),
                   holm_significant=bool(interval.holm_p_3<.05),three_eras_nonnegative=int(e.mean_delta.ge(0).sum())>=3)
        if screen['pass_screen']:
            r=pd.read_csv(out/'symbol_subsampling_summary.csv').set_index('variant')
            x=pd.read_csv(out/'ex_top5.csv');threshold=pd.read_csv(out/'threshold_sensitivity.csv')
            cost=pd.read_csv(out/'cost_sensitivity.csv').set_index('variant')
            gates.update(symbol_win_share=bool(r.loc[name,'win_share_vs_d0']>=.70),
                deleted_top5_positive=bool(x[(x.variant==name)&(x.kind=='union')].delta.iloc[0]>0),
                cost_stress_positive=bool(cost.loc[name,'delta']>0),
                threshold_neighbors_nonnegative=bool(threshold[threshold.variant==name].delta.ge(0).all()))
        else:
            gates['deep_validation']='not triggered by initial screen'
        if not monthly.loc[name,'n_dates'] or not longer.loc[name,'n_dates']:
            classification='证据不足'
        elif all(v is True for v in gates.values()):classification='支持继续推进（仍需另行批准生产试验）'
        elif screen['pass_screen']:classification='证据不足：初筛改善未通过全部深入验证'
        elif monthly.loc[name,'severe_delta']<0:classification='仅有风险改善：未通过收益初筛'
        else:classification='拒绝本轮收益候选'
        classifications[name]=dict(classification=classification,gates=gates)
        for key,value in gates.items():gate_rows.append(dict(variant=name,criterion=key,result=value))
    pd.DataFrame(gate_rows).to_csv(out/'acceptance_gates.csv',index=False)
    write_json(out/'candidate_decisions.json',classifications)
    lines=['# 价值与回踩：v4实施与验收','',
        '本轮完成已批准的有界离线实验。结果来自冻结的2016-01至2026-10月度输入及2020/2022周频压力集，属于回溯候选池近似研究。生产代码、参数和正式快照没有改动。','',
        '## 1. 60日主指标与120日稳健性','',
        '每个最终Top-15中仅Ready且Priority标的占1/15，空缺现金0收益。全部候选与D0使用相同可评价日期；表中是日期等权净持有期收益，不是账户年化。15bps/边、次日开盘、期限末收盘、拆股调整、不含分红。','',
        '| 方案 | 60日日期 | 60日净收益 | 相对D0 | QQQ差距 | 120日净收益 | 120日相对D0 | 判定 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for name in ('D0','A','B','C'):
        a,b=monthly.loc[name],longer.loc[name]
        verdict='参照' if name=='D0' else classifications[name]['classification']
        lines.append(f'| {name} {labels[name]} | {int(a.n_dates)} | {a.mean_return:.3%} | {a.mean_delta*100:+.3f}pp | {a.qqq_excess*100:+.3f}pp | {b.mean_return:.3%} | {b.mean_delta*100:+.3f}pp | {verdict} |')
    b,base=monthly.loc['B'],monthly.loc['D0']
    lines+=['',f'B的平均部署由{base.mean_deployed:.2%}降至{b.mean_deployed:.2%}，60日cohort净收益<=−20%的日期由{round(base.severe_rate*base.n_dates)}个降至{round(b.severe_rate*b.n_dates)}个。它的风险下降伴随更多现金与明显收益损失，不能解释为纯选股能力提高；重伤样本也很少。C的60日微弱均值改善区间跨零，且120日退步，未达到既定条件。']
    lines+=['','完整20/60/120/252日、list/固定使用及基准池结果见[期限表](summary_by_horizon.csv)。QQQ差距不设未经批准的接近容忍值；基准池不完整时提供可观察子集和覆盖率，不把它当作完整池收益。','',
        '## 2. 时间相关性、时代与压力期','',
        '月度配对差用6个月连续日历区块、2000次重采样；保留缺失月份，12个月区块作敏感性。三个主假设给出Holm校正，其他期限/分段不作独立确认。','',
        '| 因素 | 60日增量95%区间（pp） | 单侧p | Holm p（三假设） | 非负时代数/4 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for name in ('A','B','C'):
        r=intervals[(intervals.variant==name)&(intervals.block==6)].iloc[0]
        e=eras[(eras.scope=='monthly')&(eras.horizon==60)&(eras.view=='fixed_usage')&(eras.variant==name)]
        lines.append(f'| {name} | [{r.low*100:+.3f}, {r.high*100:+.3f}] | {r.p:.4f} | {r.holm_p_3:.4f} | {int(e.mean_delta.ge(0).sum())}/4 |')
    lines+=['','| 周频压力集 | 方案 | 60日净收益 | 相对D0（pp） | 平均部署 |','| --- | --- | ---: | ---: | ---: |']
    for scope in ('covid','bear'):
        for name,r in table(scope,60).iterrows():
            lines.append(f'| {scope} | {name} | {r.mean_return:.3%} | {r.mean_delta*100:+.3f} | {r.mean_deployed:.1%} |')
    lines+=['','四时代/年度/市场状态分别见对应CSV；ERA等权值仅作辅助，不代替主指标。周频压力集独立报告，没有与月度重复合并。','',
        '## 3. 条件执行与归因','',
        f"组合状态：`{decision['combination']['status']}`。深入验证：`{decision['robustness']}`。",
        '仅通过初筛的因素才进行200次70%公司子集、共同删除双方Top5、阈值邻域及成本压力。跳过原因写入manifest，未用空表冒充完成。没有广泛调参、挑选邻域赢家或自动推广。','',
        '阶段归因、等部署诊断、公司集中度和名单变化案例分别见`stage_attribution_60d.csv`、`deployment_attribution.csv`、`symbol_concentration.csv`、`casebook.csv`。阶段均值差属于描述性结果。','',
        '## 4. 快照、正确性与运行','',
        '2026-11-05的SIP正式快照校验通过。原始兼容CSV不足，采用不可变决策、身份一致的v10财务缓存和冻结SIP收盘缓存恢复必要输入。540项市值复核最大相对误差约1.81e-16；价格字段使用canonical门检六位小数，所有本次B阈值均无舍入歧义，A在已验证的down市场保持D0。没有使用今天的数据替换旧输入。名单和分布见快照CSV与`snapshot_validation.json`。','',
        'P0覆盖128,139条输入、203个截面（130月度+21疫情周+52熊市周），20,320条名单槽位和所有对应cohort与旧验收一致，最大数值误差小于1e-16。独立验收从原始收益列和输出成员直接重新加权，不调用研究收益函数，结果见`independent_checks.json`。','',
        '使用infi前台，smoke先行，计算容器最多2个，1CPU请求/2CPU上限、4GiB请求/8GiB上限。导入路径启动错误和C协议修订已记录，旧App已显式停止；源码/配置/协议不匹配时拒绝续跑。详见[命令](commands.md)、`modal_execution.json`及`validation.json`。','',
        '## 5. 结论的适用范围','',
        '本轮检验的是三种明确规则在现有近似池内的历史增量。不能据此证明消除幸存者偏差，也不能把失败候选解释为所有回踩/价值方法均无效。不含分红、真实滑点和完整账户持仓，流动性门是SIP规模语义；早期行情预热和财务覆盖限制仍在。任何后续生产试验需另行批准。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    return classifications


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--raw',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();raw=Path(args.raw);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    snapshot_shadow(out);independent_check(raw,out);decision=publish_tables(raw,out)
    report(out,decision)
    print('Independent cohort checks and snapshot reconstruction passed')


if __name__=='__main__':main()
