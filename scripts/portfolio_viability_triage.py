"""Stage-1 list triage from canonical post-PR23 evidence; no replay/tuning."""
from __future__ import annotations
import argparse, ast, json
from pathlib import Path
import numpy as np
import pandas as pd

LISTS = ("momentum", "industry_trend")
COMBO = "momentum_industry_50_50_proxy"


def jaccard(a, b):
    u = a | b
    return len(a & b) / len(u) if u else 1.0


def symbol_sets(signals, list_type):
    x = signals[signals.list_type.eq(list_type)][["signal_date", "symbols"]].copy()
    x["signal_date"] = x.signal_date.astype(str)
    x["symbol_set"] = x.symbols.map(lambda v: frozenset(str(s).upper() for s in ast.literal_eval(v)))
    return x[["signal_date", "symbol_set"]].sort_values("signal_date")


def event_series(events, qqq, list_type, horizon):
    x = events[(events.list_type.eq(list_type)) & (events.horizon_days.eq(horizon)) & events.event_status.eq("valid")].copy()
    x["signal_date"] = x.signal_date.astype(str)
    x = x.merge(qqq[qqq.horizon_days.eq(horizon)], on="signal_date", validate="many_to_one")
    x["year"] = x.signal_date.str[:4]
    x["excess_vs_qqq"] = x.portfolio_return - x.qqq_return
    return x[["signal_date","year","regime","portfolio_return","qqq_return","excess_vs_qqq"]].sort_values("signal_date")


def combo_proxy(m, i):
    x = m.merge(i, on="signal_date", suffixes=("_m","_i"), validate="one_to_one")
    if len(x) and not np.allclose(x.qqq_return_m, x.qqq_return_i):
        raise ValueError("combo sleeves disagree on QQQ")
    return pd.DataFrame({
        "signal_date":x.signal_date,"year":x.year_m,"regime":x.regime_m,
        "portfolio_return":(x.portfolio_return_m+x.portfolio_return_i)/2,
        "qqq_return":x.qqq_return_m,"excess_vs_qqq":(x.excess_vs_qqq_m+x.excess_vs_qqq_i)/2,
        "momentum_excess":x.excess_vs_qqq_m,"industry_excess":x.excess_vs_qqq_i,
    })


def set_stats(x):
    x = x.sort_values("signal_date").reset_index(drop=True)
    turns = [1-jaccard(x.iloc[k-1].symbol_set, x.iloc[k].symbol_set) for k in range(1,len(x))]
    counts = {}; slots = 0
    for names in x.symbol_set:
        for name in names: counts[name] = counts.get(name,0)+1; slots += 1
    ranked = sorted(counts.items(), key=lambda z:(-z[1],z[0]))
    return {"avg_holdings":np.mean([len(s) for s in x.symbol_set]),"turnover_proxy":np.mean(turns),
            "selection_top1_symbol":ranked[0][0],"selection_top1_share":ranked[0][1]/slots,
            "selection_top3_share":sum(v for _,v in ranked[:3])/slots}


def return_stats(x):
    e = x.excess_vs_qqq.astype(float); total = e.sum()
    ys = x.groupby("year").excess_vs_qqq.sum().sort_values(ascending=False); top_year = str(ys.index[0])
    pos = x[x.excess_vs_qqq.gt(0)].sort_values("excess_vs_qqq",ascending=False)
    loo = [np.delete(e.to_numpy(),k).mean() for k in range(len(e))]
    def share(v): return v/total if total > 0 else np.nan
    down = x[x.regime.astype(str).eq("down")].excess_vs_qqq
    return {"n_valid":len(x),"avg_return":x.portfolio_return.mean(),"avg_excess_vs_qqq":e.mean(),
            "median_excess_vs_qqq":e.median(),"std_excess_vs_qqq":e.std(ddof=1),"positive_excess_rate":e.gt(0).mean(),
            "worst_excess_vs_qqq":e.min(),"avg_excess_down":down.mean(),"top_year":top_year,
            "top_year_share":share(ys.iloc[0]),"avg_excess_without_top_year":x[x.year.ne(top_year)].excess_vs_qqq.mean(),
            "top_date_share":share(pos.iloc[0].excess_vs_qqq),"top3_date_share":share(pos.head(3).excess_vs_qqq.sum()),
            "loo_avg_excess_min":min(loo),"loo_avg_excess_max":max(loo)}


def analyze(root):
    read=lambda n:pd.read_csv(root/n)
    events={"risk_off":read("post_pr23_baseline_202610_risk_off_events.csv"),"risk_on":read("post_pr23_baseline_202610_risk_on_events.csv")}
    signals={"risk_off":read("post_pr23_baseline_202610_risk_off_events_signals.csv"),"risk_on":read("post_pr23_baseline_202610_risk_on_events_signals.csv")}
    b=read("post_pr23_baseline_202610_risk_off_benchmarks.csv"); qqq=b[b.benchmark.eq("QQQ")][["signal_date","horizon_days","benchmark_return"]].rename(columns={"benchmark_return":"qqq_return"})
    # Benchmark rows are written once per evaluated list type; the copies are
    # value-identical, so keep one row per date/horizon (fail loudly if not).
    dup_check = qqq.groupby(["signal_date","horizon_days"]).qqq_return.nunique()
    if int((dup_check > 1).sum()):
        raise ValueError("benchmark rows disagree for the same date/horizon")
    qqq = qqq.drop_duplicates(["signal_date","horizon_days"])
    conc=read("selection_attribution_concentration.csv")
    rows=[]; segments=[]; overlap=[]; styles=[]; cache={}; sets={}
    for style in events:
        m=sets[style,"momentum"]=symbol_sets(signals[style],"momentum"); i=sets[style,"industry_trend"]=symbol_sets(signals[style],"industry_trend")
        p=m.merge(i,on="signal_date",suffixes=("_m","_i")); js=[jaccard(a,b) for a,b in zip(p.symbol_set_m,p.symbol_set_i)]
        overlap.append({"style":style,"mean_jaccard":np.mean(js),"avg_intersection":np.mean([len(a&b) for a,b in zip(p.symbol_set_m,p.symbol_set_i)]),"avg_union":np.mean([len(a|b) for a,b in zip(p.symbol_set_m,p.symbol_set_i)]),"avg_unique_industry":np.mean([len(b-a) for a,b in zip(p.symbol_set_m,p.symbol_set_i)])})
        union=p[["signal_date"]].copy(); union["symbol_set"]=[a|b for a,b in zip(p.symbol_set_m,p.symbol_set_i)]
        setmap={"momentum":m,"industry_trend":i,COMBO:union}
        for h in (20,60,120):
            me=cache[style,"momentum",h]=event_series(events[style],qqq,"momentum",h); ie=cache[style,"industry_trend",h]=event_series(events[style],qqq,"industry_trend",h); ce=combo_proxy(me,ie)
            for name,x in (("momentum",me),("industry_trend",ie),(COMBO,ce)):
                r={"style":style,"candidate":name,"horizon_days":h,**return_stats(x),**set_stats(setmap[name])}
                r["component_corr"]=ce.momentum_excess.corr(ce.industry_excess) if name==COMBO else np.nan
                r["std_ratio_vs_momentum"]=ce.excess_vs_qqq.std(ddof=1)/me.excess_vs_qqq.std(ddof=1) if name==COMBO else np.nan
                hit=conc[(conc.style.eq(style))&(conc.list_type.eq("momentum"))&(conc.horizon.eq(h))] if name=="momentum" else pd.DataFrame()
                r["return_top1_share"]=float(hit.iloc[0].top1_share) if len(hit)==1 else np.nan; r["return_top3_share"]=float(hit.iloc[0].top3_share) if len(hit)==1 else np.nan
                r["after_top1_positive"]=bool(hit.iloc[0].sum_after_removing_top1>0) if len(hit)==1 else ""
                rows.append(r)
                for kind,col in (("year","year"),("regime","regime")):
                    for seg,g in x.groupby(col): segments.append({"style":style,"candidate":name,"horizon_days":h,"segment_type":kind,"segment":seg,"n":len(g),"avg_excess_vs_qqq":g.excess_vs_qqq.mean()})
    for name in LISTS:
        sp=sets["risk_off",name].merge(sets["risk_on",name],on="signal_date",suffixes=("_off","_on")); sj=np.mean([jaccard(a,b) for a,b in zip(sp.symbol_set_off,sp.symbol_set_on)])
        for h in (20,60,120):
            p=cache["risk_off",name,h].merge(cache["risk_on",name,h],on="signal_date",suffixes=("_off","_on")); d=p.excess_vs_qqq_on-p.excess_vs_qqq_off
            styles.append({"list_type":name,"horizon_days":h,"selection_jaccard":sj,"excess_corr":p.excess_vs_qqq_off.corr(p.excess_vs_qqq_on),"avg_on_minus_off":d.mean(),"mean_abs_diff":d.abs().mean()})
    return map(pd.DataFrame,(rows,segments,overlap,styles))


def channel_concentration(root):
    x=pd.read_csv(root/"selection_attribution_channel.csv")
    rows=[]
    for style in ("risk_off","risk_on"):
        for list_type in LISTS:
            g=x[(x.style.eq(style))&(x.list_type.eq(list_type))]
            vals={r.channel:int(r.total_selected) for _,r in g.iterrows()}; total=sum(vals.values())
            rows.append({"style":style,"list_type":list_type,"core_ai_slots":vals.get("core_ai",0),"ai_enabler_slots":vals.get("ai_enabler",0),"ai_peripheral_slots":vals.get("ai_peripheral",0),"total_channel_slots":total,"max_channel_share":max(vals.values())/total})
    return pd.DataFrame(rows)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--evidence-dir",default="evidence/baselines/post_pr23_005b86c"); p.add_argument("--output-dir"); a=p.parse_args(); root=Path(a.evidence_dir); out=Path(a.output_dir) if a.output_dir else root/"portfolio_viability_stage1"
    c,s,o,st=analyze(root); ch=channel_concentration(root); out.mkdir(parents=True,exist_ok=True); c.to_csv(out/"candidate_summary.csv",index=False); s.to_csv(out/"candidate_segments.csv",index=False); o.to_csv(out/"overlap_summary.csv",index=False); st.to_csv(out/"style_incremental.csv",index=False); ch.to_csv(out/"channel_concentration.csv",index=False)
    manifest={"evidence_class":"retrospective signal-level screening; not NAV or fresh OOS","combo_proxy":"50/50 same-date already-cost-adjusted list returns","turnover_proxy":"1-Jaccard consecutive monthly selected sets","new_replay":False,"production_changes":False,"broad_tuning":False,"position_gate_reopened":False}
    (out/"analysis_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n"); return 0
if __name__=="__main__": raise SystemExit(main())
