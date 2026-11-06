"""Canonical weekly selection cohorts. Labels never participate in selection."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.decision.action import assign_action_priorities_v2
from ai_value_scanner.decision.integrated import build_stock_decisions, select_weekly_attention
from ai_value_scanner.decision.universe import apply_price_liquidity_prefilter
from ai_value_scanner.evaluation.backtest import fallback_label_end_date

HORIZONS = (20, 60, 120, 252)


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def market_group(ratio: Any, ret60: Any) -> str:
    ratio, ret60 = number(ratio), number(ret60)
    if ratio is None or ret60 is None:
        return "unknown"
    if ratio > 1 and ret60 > 0:
        return "up"
    if ratio < 1 and ret60 < 0:
        return "down"
    return "mixed"


def label_status(row: dict, horizon: int) -> str:
    """Missing and adverse assumptions are not converted to observed outcomes."""
    ret, qqq = number(row.get(f"fwd_ret_{horizon}")), number(row.get(f"qqq_return_{horizon}"))
    if qqq is None:
        return "benchmark_unavailable_or_immature"
    if ret is None:
        return "stock_unavailable"
    end = pd.to_datetime(row.get(f"label_end_{horizon}"), errors="coerce", utc=True)
    qend = pd.to_datetime(row.get(f"qqq_label_end_{horizon}"), errors="coerce", utc=True)
    signal = pd.Timestamp(row["signal_date"], tz="UTC")
    if pd.isna(end):
        return "undated_or_assumed_delisting"
    if pd.isna(qend) or end != qend or end <= signal:
        return "timing_mismatch"
    if end > fallback_label_end_date(row["signal_date"], horizon):
        return "horizon_overrun"
    return "observed"


def validate_inputs(frame: pd.DataFrame) -> None:
    required = {"signal_date", "symbol", "market_asof", "fundamental_data_asof"}
    if not required <= set(frame):
        raise ValueError(f"missing decision inputs: {sorted(required-set(frame))}")
    if frame.empty or frame.duplicated(["signal_date", "symbol"]).any():
        raise ValueError("empty data or duplicate date/symbol")
    signal = pd.to_datetime(frame.signal_date, errors="coerce", utc=True)
    if signal.isna().any() or frame.symbol.isna().any():
        raise ValueError("invalid signal date or symbol")
    for column in ("market_asof", "fundamental_data_asof"):
        evidence = pd.to_datetime(frame[column], errors="coerce", utc=True)
        if (evidence > signal).any():
            raise ValueError(f"future {column}")


def evaluate(frame: pd.DataFrame, *, seed: int = 61106, cap: int = 15,
             min_price: float = 1.0, min_dollar_volume: float = 2_000_000,
             horizons: tuple[int, ...] = HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    validate_inputs(frame)
    feeds = frame.market_data_feed.dropna().unique() if 'market_data_feed' in frame else ['iex']
    if len(feeds) != 1:
        raise ValueError('do not mix feeds in one economic comparison')
    slots, cohorts, diagnostics = [], [], []
    rng = np.random.default_rng(seed)
    for day, group in frame.groupby("signal_date", sort=True):
        day = str(day)
        lookup = {r["symbol"]: r for r in group.to_dict("records")}
        eligible_group, exclusions = apply_price_liquidity_prefilter(
            group, min_price=min_price, min_dollar_volume=min_dollar_volume, market_data_feed=str(feeds[0]))
        decisions = build_stock_decisions(eligible_group, decision_date=day,
                                         generated_at_utc=day+"T23:59:59Z", policy_version="v2")
        variants = {"baseline": decisions,
                    "no_age_penalty": assign_action_priorities_v2(decisions, pre_earnings_penalty=0.0)}
        pool = [d for d in decisions if d.quality.grade.value in {"A", "B"}
                and d.action_state.value != "AVOID"]
        base_top = select_weekly_attention(decisions, cap=cap)
        k = min(len(base_top), len(pool))
        random_symbols = set(rng.choice(sorted(d.symbol for d in pool), size=k, replace=False))
        random_pool = [d for d in pool if d.symbol in random_symbols]
        ratio_values = pd.to_numeric(group.get("qqq_price_to_sma200", pd.Series(dtype=float)), errors="coerce").dropna().unique()
        ret_values = pd.to_numeric(group.get("qqq_trailing_return_60d", pd.Series(dtype=float)), errors="coerce").dropna().unique()
        if len(ratio_values) > 1 or len(ret_values) > 1:
            raise ValueError("mixed market evidence on a single date")
        regime = market_group(ratio_values[0] if len(ratio_values) else None,
                              ret_values[0] if len(ret_values) else None)
        tops = {v: select_weekly_attention(ds, cap=cap) for v, ds in variants.items()}
        q_scores = pd.Series([d.quality.score for d in decisions], dtype=float)
        e_scores = pd.Series([d.entry.score for d in decisions], dtype=float)
        joint = {d.symbol: .6*(d.quality.score or 0)+.4*(d.entry.score or 0)
                 +(.04 if d.quality.grade.value=='A' else 0)
                 -.06*any(r.code=='pre_earnings_window_risk' for r in d.quality.risks)
                 -.06*any(r.code=='nonoperating_gain_inflation' for r in d.quality.risks)
                 for d in decisions}
        priority_rows = [d for d in decisions if d.action_state.value=='PRIORITY_REVIEW']
        cutoff_gap = (joint[priority_rows[cap-1].symbol]-joint[priority_rows[cap].symbol]
                      if len(priority_rows)>cap else None)
        diagnostics.append(dict(signal_date=day, n_inputs=len(group), n_ab_pool=len(pool),
                                n_prefilter_eligible=len(eligible_group), n_prefilter_excluded=len(exclusions),
                                n_baseline=len(base_top), n_changed=len({d.symbol for d in tops['no_age_penalty']}-{d.symbol for d in base_top}),
                                n_age_flag=sum(any(r.code == 'pre_earnings_window_risk' for r in d.quality.risks) for d in decisions),
                                n_age_flag_top=sum(any(r.code == 'pre_earnings_window_risk' for r in d.quality.risks) for d in base_top),
                                market_group=regime, quality_entry_correlation=q_scores.corr(e_scores)
                                if q_scores.nunique()>1 and e_scores.nunique()>1 else None,
                                priority_cutoff_joint_gap=cutoff_gap))
        selections = {(v, view): [d for d in tops[v] if view == "list" or
                      (d.action_state.value == "PRIORITY_REVIEW" and d.entry.state.value == "ENTRY_READY")]
                      for v in variants for view in ("list", "usage")}
        selections.update({("ab_pool", "list"): pool, ("random_k", "list"): random_pool})
        for (variant, view), chosen in selections.items():
            denominator = cap if view == "usage" else len(chosen)
            for h in horizons:
                if f"fwd_ret_{h}" not in group:
                    continue
                q_values = pd.to_numeric(group[f"qqq_return_{h}"], errors="coerce").dropna().unique()
                qe_values = group[f"qqq_label_end_{h}"].dropna().astype(str).unique()
                if len(q_values) > 1 or len(qe_values) > 1:
                    raise ValueError("mixed benchmark outcomes on a decision date")
                qqq = number(q_values[0]) if len(q_values) else None
                records = []
                for d in chosen:
                    raw = lookup[d.symbol]
                    status = label_status(raw, h)
                    ret = number(raw.get(f"fwd_ret_{h}")) if status == "observed" else None
                    records.append(dict(signal_date=day, variant=variant, view=view, horizon=h,
                                        symbol=d.symbol, rank=d.priority, grade=d.quality.grade.value,
                                        action=d.action_state.value, entry=d.entry.state.value,
                                        quality_score=d.quality.score, entry_score=d.entry.score,
                                        industry=str(raw.get('sic_description') or 'unknown'),
                                        weight=1/denominator if denominator else 0,
                                        label_status=status, net_return=ret))
                slots.extend(records)
                observed = [r for r in records if r['label_status'] == 'observed']
                complete = len(observed) == len(chosen)
                net = sum(r['net_return']*r['weight'] for r in observed) if complete and (chosen or view == 'usage') else None
                deployed = len(chosen)/cap if view == "usage" else (1 if chosen else 0)
                cohorts.append(dict(signal_date=day, year=day[:4], market_group=regime,
                                    research_qualified=regime!='unknown',
                                    variant=variant, view=view, horizon=h, n_selected=len(chosen),
                                    n_observed=len(observed), n_invalid=len(chosen)-len(observed),
                                    net_return=net, stress_return=net-deployed*.003 if net is not None else None,
                                    qqq_return=qqq,
                                    excess=net-qqq if net is not None and qqq is not None and regime!='unknown' else None,
                                    exposure_excess=net-deployed*qqq if net is not None and qqq is not None else None,
                                    severe_loss_rate=sum(r['net_return'] < -.20 for r in observed)/len(chosen) if chosen and complete else (0 if complete and view=='usage' else None),
                                    label_end=str(qe_values[0]) if len(qe_values) else None))
    slot_columns=['signal_date','variant','view','horizon','symbol','rank','grade','action','entry',
                  'quality_score','entry_score','industry','weight','label_status','net_return']
    return pd.DataFrame(slots,columns=slot_columns), pd.DataFrame(cohorts), pd.DataFrame(diagnostics)


def summarize(cohorts: pd.DataFrame) -> pd.DataFrame:
    output = []
    for (variant, view, h), part in cohorts.groupby(['variant', 'view', 'horizon']):
        segments = [('all', 'all', part)]
        for column in ('year', 'market_group'):
            segments += [(column, str(k), p) for k, p in part.groupby(column)]
        segments += [('pressure', 'covid_shock', part[part.signal_date.between('2020-02-01','2020-03-31')]),
                     ('pressure', 'covid_recovery', part[part.signal_date.between('2020-04-01','2020-06-30')])]
        for kind, key, p in segments:
            comparable = p[p.excess.notna()]
            output.append(dict(variant=variant, view=view, horizon=h, segment_type=kind, segment=key,
                               n_dates=len(p), n_valid=int(p.excess.notna().sum()),
                               mean_return=comparable.net_return.mean(), mean_excess=p.excess.mean(),
                               median_excess=p.excess.median(), positive_excess_share=p.excess.dropna().gt(0).mean(),
                               mean_severe_loss_rate=p.severe_loss_rate.mean(),
                               n_invalid_slots=int(p.n_invalid.sum())))
    return pd.DataFrame(output)


def random_distribution(slots: pd.DataFrame, *, repeats: int = 1000, seed: int = 61106) -> pd.DataFrame:
    """Random K draws keep missing labels; report their invalid-draw frequency."""
    rng = np.random.default_rng(seed)
    output = []
    pool = slots[(slots.variant=='ab_pool')&(slots.view=='list')]
    for (day,h), p in pool.groupby(['signal_date','horizon']):
        k = len(slots[(slots.signal_date==day)&(slots.horizon==h)&(slots.variant=='random_k')])
        if not k: continue
        returns = pd.to_numeric(p.net_return,errors='coerce').to_numpy()
        draws = np.array([returns[rng.choice(len(returns),k,replace=False)].mean() for _ in range(repeats)])
        finite = draws[np.isfinite(draws)]
        base=slots[(slots.signal_date==day)&(slots.horizon==h)&(slots.variant=='baseline')&(slots.view=='list')]
        base_value=base.net_return.mean() if len(base) and base.net_return.notna().all() else None
        output.append(dict(signal_date=day,horizon=h,k=k,n_pool=len(p),draws=repeats,
                           valid_draws=len(finite),invalid_draws=repeats-len(finite),
                           baseline_return=base_value,
                           baseline_percentile=float(np.mean(finite<=base_value)) if len(finite) and base_value is not None else None,
                           mean=float(finite.mean()) if len(finite) else None,
                           p05=float(np.quantile(finite,.05)) if len(finite) else None,
                           p95=float(np.quantile(finite,.95)) if len(finite) else None))
    return pd.DataFrame(output)


def baseline_evidence(cohorts: pd.DataFrame) -> dict:
    result={}
    for view in ('list','usage'):
        p=cohorts[(cohorts.variant=='baseline')&(cohorts.horizon==60)&(cohorts.view==view)&cohorts.excess.notna()]
        lo,hi,block=block_interval(p.excess.to_numpy(),p.signal_date,60)
        result[view]=dict(n_dates=len(p),mean_excess=p.excess.mean(),ci_low=lo,ci_high=hi,block_dates=block,
                          mean_exposure_matched_excess=p.exposure_excess.mean(),
                          interpretation='retrospective benchmark-relative selection evidence, not prospective alpha proof')
    return result


def block_interval(values: np.ndarray, dates: pd.Series, horizon: int, *, repeats: int = 2000,
                   seed: int = 61106) -> tuple[float | None, float | None, int]:
    if len(values) < 2:
        return None, None, len(values)
    gaps = pd.to_datetime(dates).sort_values().diff().dt.days.dropna()
    block = max(1, int(math.ceil(horizon*7/5/max(1,float(gaps.median())))))
    if len(values) < 2*block:
        return None, None, block
    rng = np.random.default_rng(seed)
    starts = rng.integers(len(values), size=(repeats, math.ceil(len(values)/block)))
    indices = ((starts[:,:,None] + np.arange(block)) % len(values)).reshape(repeats,-1)[:,:len(values)]
    means = values[indices].mean(axis=1)
    lo, hi = np.quantile(means, [.025,.975])
    return float(lo), float(hi), block


def paired_report(cohorts: pd.DataFrame, slots: pd.DataFrame) -> dict:
    report = {}
    for view in ('list','usage'):
        p = cohorts[(cohorts.horizon == 60) & (cohorts.view == view)]
        b = p[p.variant == 'baseline'].set_index('signal_date')
        c = p[p.variant == 'no_age_penalty'].set_index('signal_date')
        eligible = b.qqq_return.notna() & c.qqq_return.notna() & b.research_qualified & c.research_qualified
        valid = b.net_return.notna() & c.net_return.notna() & eligible
        delta = (c.net_return-b.net_return)[valid]
        lo,hi,block = block_interval(delta.to_numpy(), delta.index.to_series(),60)
        groups = {}
        for name, mask in [('bear2022', b.year.eq('2022')), ('down', b.market_group.eq('down')),
                           ('covid_shock', b.index.to_series().between('2020-02-01','2020-03-31'))]:
            m = valid & mask
            groups[name] = dict(n_dates=int(m.sum()), mean_delta=(c.net_return-b.net_return)[m].mean(),
                                severe_delta=(c.severe_loss_rate-b.severe_loss_rate)[m].mean())
        # Contribution deletion preserves the other selections and their weights.
        s = slots[(slots.horizon==60)&(slots.view==view)&slots.variant.isin(['baseline','no_age_penalty'])&slots.signal_date.isin(delta.index)].copy()
        s['contribution'] = s.net_return*s.weight*np.where(s.variant.eq('no_age_penalty'),1,-1)
        contributions = s.groupby('symbol').contribution.sum()/max(1,len(delta))
        top = contributions.idxmax() if len(contributions) else None
        loo = float(delta.mean()-contributions.max()) if len(contributions) else None
        checks = dict(mean_delta=bool(len(delta) and delta.mean() >= .005),
                      median_delta=bool(len(delta) and delta.median()>0),
                      stress_positive=bool(valid.any() and (c.stress_return-b.stress_return)[valid].mean()>0),
                      full_severe_noninferior=bool(valid.any() and (c.severe_loss_rate-b.severe_loss_rate)[valid].mean()<=0),
                      all_mature_dates_complete=bool(eligible.any() and valid[eligible].all()),
                      leave_top_contributor_positive=bool(loo is not None and loo>0),
                      ci_positive=bool(lo is not None and lo>0))
        for name,g in groups.items():
            checks[name] = bool(g['n_dates']>=2 and g['mean_delta']>=0 and g['severe_delta']<=0)
        nonoverlap, prev = [], ''
        for day in delta.index:
            if day>prev:
                nonoverlap.append(float(delta[day])); prev=str(b.loc[day,'label_end'])
        report[view] = dict(n_paired_dates=len(delta),n_mature_dates=int(eligible.sum()),
                            mean_delta=delta.mean(),median_delta=delta.median(),ci_low=lo,ci_high=hi,block_dates=block,
                            top_contributor=top,leave_top_contributor_delta=loo,
                            nonoverlap_n=len(nonoverlap),nonoverlap_delta=np.mean(nonoverlap) if nonoverlap else None,
                            pressure_groups=groups,checks=checks,adopt=all(checks.values()))
    return report
