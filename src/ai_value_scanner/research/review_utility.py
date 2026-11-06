"""Observed attention utility and paired Entry diagnostics on frozen evidence.

No tuning or promotion. Missing human reviews and future outcomes remain missing.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
import math
from typing import Any

import pandas as pd

from ai_value_scanner.decision.entry import build_entry_quality_v2
from ai_value_scanner.decision.quality import build_company_quality_v2

_ACTION_RANK = dict(PRIORITY_REVIEW=0, WATCH_PULLBACK=1, WATCH_BREAKOUT=2, HOLD_MONITOR=3, AVOID=4)


@dataclass(frozen=True)
class AttentionObservation:
    decision_date: str
    daily_symbols: tuple[str, ...]
    actions: dict[str, str]


def attention_utility(
    observations: Sequence[AttentionObservation], reviews: pd.DataFrame | None = None,
    *, failure_observations: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if failure_observations < 1:
        raise ValueError('failure_observations must be positive')
    ordered = sorted(observations, key=lambda o: o.decision_date)
    if len({o.decision_date for o in ordered}) != len(ordered):
        raise ValueError('duplicate snapshot dates')
    for observation in ordered:
        date.fromisoformat(observation.decision_date)
        if len(set(observation.daily_symbols)) != len(observation.daily_symbols):
            raise ValueError('duplicate daily symbols')
        if not set(observation.daily_symbols) <= observation.actions.keys():
            raise ValueError('daily symbol absent from decisions')
        if any(state not in _ACTION_RANK for state in observation.actions.values()):
            raise ValueError('unknown action state')
    events: list[dict[str, Any]] = []
    previous: AttentionObservation | None = None
    for i, obs in enumerate(ordered):
        prior_symbols = set(previous.daily_symbols) if previous else set()
        for symbol in obs.daily_symbols:
            prior_action = previous.actions.get(symbol) if previous else None
            action = obs.actions[symbol]
            upgraded = prior_action is not None and _ACTION_RANK[action] < _ACTION_RANK[prior_action]
            future = ordered[i+1:i+1+failure_observations]
            future_actions = [o.actions[symbol] for o in future if symbol in o.actions]
            failed = any(_ACTION_RANK[state] > _ACTION_RANK[action] for state in future_actions)
            complete = len(future_actions) == failure_observations
            events.append(dict(decision_date=obs.decision_date, symbol=symbol,
                               iso_week=date.fromisoformat(obs.decision_date).strftime('%G-W%V'),
                               new_since_previous=symbol not in prior_symbols if previous else None,
                               repeated_slot=symbol in prior_symbols if previous else None,
                               upgraded=upgraded,
                               downgrade_within_window=(failed if failed or complete else None) if upgraded else None,
                               review_status='unreviewed', review_minutes=None, rejection_reason=''))
        previous = obs
    columns = ['decision_date','symbol','iso_week','new_since_previous','repeated_slot','upgraded',
               'downgrade_within_window','review_status','review_minutes','rejection_reason']
    frame = pd.DataFrame(events, columns=columns)
    if reviews is not None and not reviews.empty:
        required = {'decision_date','symbol','review_status','review_minutes','rejection_reason'}
        if not required <= set(reviews.columns):
            raise ValueError('review log missing required columns')
        review = reviews[list(sorted(required))].copy().fillna({'rejection_reason':''})
        if review.duplicated(['decision_date','symbol']).any():
            raise ValueError('duplicate human reviews')
        keys = set(zip(frame.decision_date,frame.symbol))
        if not set(zip(review.decision_date,review.symbol)) <= keys:
            raise ValueError('review refers to a non-shortlisted decision')
        minutes = pd.to_numeric(review.review_minutes, errors='coerce')
        if not minutes.map(lambda x: math.isfinite(x) and x >= 0).all():
            raise ValueError('review minutes must be finite and nonnegative')
        if not review.review_status.isin(['reviewed','rejected','follow_up']).all():
            raise ValueError('invalid review status')
        rejected = review.review_status.eq('rejected')
        if review.loc[rejected,'rejection_reason'].astype(str).str.strip().eq('').any():
            raise ValueError('rejected reviews require a reason')
        review['review_minutes'] = minutes
        frame = frame.drop(columns=['review_status','review_minutes','rejection_reason']).merge(
            review, on=['decision_date','symbol'], how='left', validate='one_to_one')
        frame['review_status'] = frame.review_status.fillna('unreviewed')
        frame['rejection_reason'] = frame.rejection_reason.fillna('')
    summaries = []
    for week, part in frame.groupby('iso_week'):
        logged = part.review_status.ne('unreviewed')
        failures = part.downgrade_within_window.dropna()
        summaries.append(dict(iso_week=week, n_slots=len(part), n_unique_symbols=part.symbol.nunique(),
                              n_new=int(part.new_since_previous.eq(True).sum()),
                              n_repeated=int(part.repeated_slot.eq(True).sum()),
                              n_first_snapshot_unknown=int(part.new_since_previous.isna().sum()),
                              n_upgrades=int(part.upgraded.sum()), n_upgrade_outcomes_observed=len(failures),
                              n_upgrade_outcomes_censored=int(part.upgraded.sum())-len(failures),
                              n_failed_upgrades=int(failures.sum()), n_human_reviews=int(logged.sum()),
                              review_minutes=float(part.loc[logged,'review_minutes'].sum()) if logged.any() else None,
                              n_rejections=int(part.review_status.eq('rejected').sum())))
    reasons = frame.loc[frame.review_status.eq('rejected'),'rejection_reason'].value_counts()
    return frame, pd.DataFrame(summaries), reasons.rename_axis('rejection_reason').reset_index(name='n')


def label_integrity(frame: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """Detect future-label timing mismatch without filling or repairing evidence."""
    required = [f'fwd_ret_{horizon}', f'qqq_return_{horizon}', f'label_end_{horizon}', f'qqq_label_end_{horizon}']
    if not set(required) <= set(frame.columns):
        raise ValueError(f'missing outcome contract columns for horizon {horizon}')
    returns = pd.to_numeric(frame[required[0]],errors='coerce')
    qqq = pd.to_numeric(frame[required[1]],errors='coerce')
    finite = returns.map(math.isfinite) & qqq.map(math.isfinite)
    end = pd.to_datetime(frame[required[2]],errors='coerce')
    qend = pd.to_datetime(frame[required[3]],errors='coerce')
    signal = pd.to_datetime(frame.signal_date,errors='coerce')
    paired = finite & end.notna() & qend.notna() & end.eq(qend) & end.gt(signal)
    return dict(horizon=horizon,n_rows=len(frame),n_valid_paired=int(paired.sum()),
                n_missing_or_nonfinite=int((~finite).sum()),
                n_timing_invalid=int((finite & ~paired).sum()), mask=paired)


def evaluate_entry_increment(
    frame: pd.DataFrame, *, horizons: Sequence[int] = (20,60,120),
) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,dict[str,Any]]:
    """Same A/B pool, date equal paired comparison; no independent-row t tests.

    Non-overlap diagnostics select the next signal strictly after every prior
    label end in that horizon. Selection never uses return magnitude.
    """
    work = frame.copy()
    if not {'symbol','signal_date','market_asof','fundamental_data_asof','regime'} <= set(work.columns):
        raise ValueError('missing decision inputs')
    if work.duplicated(['signal_date','symbol']).any():
        raise ValueError('duplicate decision rows')
    signal = pd.to_datetime(work.signal_date,errors='coerce')
    market = pd.to_datetime(work.market_asof,errors='coerce')
    fundamental = pd.to_datetime(work.fundamental_data_asof,errors='coerce')
    if signal.isna().any() or (market > signal).any() or (fundamental > signal).any():
        raise ValueError('invalid decision dates or future evidence')
    # Reuse shared builders; never use pre-attached grades of uncertain version.
    records = work.to_dict('records')
    work['quality_grade'] = [build_company_quality_v2(r,decision_date=r['signal_date'],data_asof=r['fundamental_data_asof']).grade.value for r in records]
    work['entry_state'] = [build_entry_quality_v2(r,decision_date=r['signal_date'],market_asof=r['market_asof']).state.value for r in records]
    pool = work[work.quality_grade.isin(['A','B'])].copy()
    rows = []; integrity = []
    full_integrity = []
    concentrations = []
    for cohort, subset in [('quality_ab',pool),('quality_ab_entry_ready',pool[pool.entry_state.eq('ENTRY_READY')])]:
        counts = subset.symbol.value_counts()
        dates = subset.signal_date.value_counts()
        concentrations.append(dict(cohort=cohort,n_decisions=len(subset),n_symbols=len(counts),n_dates=len(dates),
                                   top_symbol=counts.index[0] if len(counts) else '',
                                   top_symbol_share=float(counts.iloc[0]/len(subset)) if len(subset) else None,
                                   top_date_share=float(dates.iloc[0]/len(subset)) if len(subset) else None))
    for horizon in horizons:
        full_info = label_integrity(work, horizon)
        full_info.pop('mask')
        full_integrity.append(full_info)
        info = label_integrity(pool,horizon); mask = info.pop('mask'); integrity.append(info)
        if info['n_timing_invalid']:
            raise ValueError(f'invalid paired label timing at {horizon}d')
        valid = pool.loc[mask].copy()
        valid['_excess'] = pd.to_numeric(valid[f'fwd_ret_{horizon}']) - pd.to_numeric(valid[f'qqq_return_{horizon}'])
        for day, part in valid.groupby('signal_date',sort=True):
            ready = part[part.entry_state.eq('ENTRY_READY')]
            if ready.empty:
                continue
            if part.regime.nunique(dropna=False) != 1:
                raise ValueError('mixed benchmark regimes on a decision date')
            if part[f'qqq_return_{horizon}'].nunique() != 1:
                raise ValueError('mixed benchmark returns on a decision date')
            rows.append(dict(signal_date=day,horizon=horizon,year=str(day)[:4],regime=part.regime.iloc[0],
                             n_quality_ab=len(part),n_entry_ready=len(ready),
                             quality_ab_return=float(pd.to_numeric(part[f'fwd_ret_{horizon}']).mean()),
                             ready_return=float(pd.to_numeric(ready[f'fwd_ret_{horizon}']).mean()),
                             quality_ab_excess=float(part._excess.mean()),ready_excess=float(ready._excess.mean()),
                             delta_excess=float(ready._excess.mean()-part._excess.mean()),
                             label_end=str(part[f'label_end_{horizon}'].max())))
    paired = pd.DataFrame(rows)
    summary = []
    if not paired.empty:
        for horizon, part in paired.groupby('horizon'):
            def summarize(scope, kind, segment):
                summary.append(dict(horizon=horizon,segment_type=kind,segment=str(segment),n_dates=len(scope),
                                    quality_ab_excess=float(scope.quality_ab_excess.mean()),
                                    ready_excess=float(scope.ready_excess.mean()),delta_excess=float(scope.delta_excess.mean())))
            summarize(part,'overall','all')
            for column in ('year','regime'):
                for key, scope in part.groupby(column): summarize(scope,column,key)
            nonoverlap = []; previous_end = ''
            for row in part.sort_values('signal_date').to_dict('records'):
                if row['signal_date'] > previous_end:
                    nonoverlap.append(row); previous_end = row['label_end']
            summarize(pd.DataFrame(nonoverlap),'nonoverlapping','greedy_by_label_end')
    metadata = dict(evidence_class='retrospective_diagnostic',universe_sources=sorted(work.watchlist_source.dropna().unique()) if 'watchlist_source' in work else ['unknown'],
                    quality_policy='v2',entry_policy='v2',n_rows=len(work),n_quality_ab=len(pool),
                    outcome_integrity=integrity,full_dataset_outcome_integrity=full_integrity,
                    comparison='same-date A/B pool versus its ENTRY_READY subset',
                    caveat='Selection association, not causal timing alpha; historical inputs retain frozen coverage and universe approximations; no production promotion')
    return paired,pd.DataFrame(summary),pd.DataFrame(concentrations),metadata
