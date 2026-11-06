from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from ai_value_scanner.decision.action import assign_action_priorities_v2
from ai_value_scanner.decision.integrated import build_stock_decisions, select_weekly_attention
from ai_value_scanner.research.top15_backtest import evaluate, label_status, market_group, block_interval, random_distribution, baseline_evidence
from test_review_selection_utility import row


def labeled(symbol='AAA', **changes):
    r = row(symbol=symbol, signal_date='2024-01-31', market_asof='2024-01-31',price=100,dollar_volume=10_000_000,
            fundamental_data_asof='2023-12-20', qqq_price_to_sma200=1.1,
            qqq_trailing_return_60d=.05, fwd_ret_60=.10, qqq_return_60=.04,
            label_end_60='2024-04-26', qqq_label_end_60='2024-04-26')
    r.update(changes)
    return r


class CurrentTop15Tests(unittest.TestCase):
    def test_empty_prefilter_result_preserves_cash_cohorts(self):
        from ai_value_scanner.research.top15_backtest import paired_report
        slots,cohorts,_=evaluate(pd.DataFrame([labeled(dollar_volume=1)]),horizons=(60,))
        self.assertTrue(slots.empty)
        self.assertEqual(cohorts[(cohorts.variant=='baseline')&(cohorts.view=='usage')].iloc[0].net_return,0)
        self.assertFalse(paired_report(cohorts,slots)['usage']['adopt'])

    def test_baseline_benchmark_interval_has_independent_known_answer(self):
        rows=[dict(variant='baseline',view=view,horizon=60,signal_date=str(day.date()),excess=-.02,exposure_excess=.01)
              for view in ['list','usage'] for day in pd.date_range('2021-01-31',periods=24,freq='ME')]
        result=baseline_evidence(pd.DataFrame(rows))
        for view in ['list','usage']:
            self.assertAlmostEqual(result[view]['ci_low'],-.02)
            self.assertAlmostEqual(result[view]['ci_high'],-.02)
            self.assertAlmostEqual(result[view]['mean_exposure_matched_excess'],.01)

    def test_market_warmup_is_logged_but_not_formal_comparison(self):
        _,cohorts,_=evaluate(pd.DataFrame([labeled(qqq_price_to_sma200=None)]),horizons=(60,))
        p=cohorts[(cohorts.variant=='baseline')&(cohorts.view=='usage')].iloc[0]
        self.assertFalse(p.research_qualified)
        self.assertTrue(pd.isna(p.excess))
        self.assertEqual(p.n_selected,1)

    def test_mixed_feed_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'mix feeds'):
            evaluate(pd.DataFrame([labeled('A',market_data_feed='iex'),labeled('B',market_data_feed='sip')]),horizons=(60,))

    def test_random_distribution_retains_failed_draw_count(self):
        frame=pd.DataFrame([dict(signal_date='2024-01-31',horizon=60,view='list',variant='ab_pool',net_return=.1),
                            dict(signal_date='2024-01-31',horizon=60,view='list',variant='ab_pool',net_return=None),
                            dict(signal_date='2024-01-31',horizon=60,view='list',variant='random_k',net_return=.1)])
        result=random_distribution(frame,repeats=1000).iloc[0]
        self.assertEqual(result.draws,1000)
        self.assertGreater(result.invalid_draws,400)
        self.assertGreater(result.valid_draws,400)
        self.assertAlmostEqual(result['mean'],.1)

    def test_annual_labels_allow_exchange_holidays(self):
        from ai_value_scanner.evaluation.backtest import forward_return_with_exit, split_query_end_iso
        from ai_value_scanner.market_calendar import is_session_day
        dates=pd.date_range('2023-01-03','2024-01-10',tz='UTC')
        dates=pd.DatetimeIndex([d for d in dates if is_session_day(d.date())])
        frame=pd.DataFrame({'open':100.,'close':110.},index=dates)
        value,end=forward_return_with_exit(frame,'2023-01-03',252,.003)
        self.assertAlmostEqual(value,.097)
        self.assertGreaterEqual(split_query_end_iso('2023-01-03',[252]),str(end.date()))

    def test_special_closures_do_not_look_like_missing_bars(self):
        from datetime import date
        from ai_value_scanner.market_calendar import is_session_day
        from ai_value_scanner.features.price import _missing_sessions
        for closed in [date(2018,12,5),date(2025,1,9)]:
            self.assertFalse(is_session_day(closed))
            self.assertEqual(_missing_sessions([pd.Timestamp(closed)-pd.Timedelta(days=1),pd.Timestamp(closed)+pd.Timedelta(days=1)]),0)

    def test_replay_schedule_uses_last_actual_session(self):
        from datetime import datetime, timezone
        from ai_value_scanner.backtest import build_rebalance_dates
        start=datetime(2024,3,1,tzinfo=timezone.utc)
        end=datetime(2024,3,31,tzinfo=timezone.utc)
        self.assertEqual([d.strftime('%Y-%m-%d') for d in build_rebalance_dates(start,end,'monthly')],['2024-03-28'])
        self.assertEqual(build_rebalance_dates(start,end,'weekly')[-1].strftime('%Y-%m-%d'),'2024-03-28')

    def test_production_prefilter_is_not_bypassed(self):
        slots,cohorts,diag=evaluate(pd.DataFrame([labeled('GOOD'),labeled('THIN',dollar_volume=100)]),horizons=(60,))
        self.assertNotIn('THIN',slots.symbol.tolist())
        self.assertEqual(diag.iloc[0].n_prefilter_excluded,1)

    def test_usage_keeps_cash_and_costs_only_deployed_slots(self):
        _, cohorts, _ = evaluate(pd.DataFrame([labeled()]), horizons=(60,))
        p=cohorts[(cohorts.variant=='baseline') & (cohorts.view=='usage')].iloc[0]
        self.assertEqual(p.n_selected,1)
        self.assertAlmostEqual(p.net_return,.10/15)
        self.assertAlmostEqual(p.stress_return,(.10-.003)/15)
        self.assertAlmostEqual(p.exposure_excess,(.10-.04)/15)
        self.assertAlmostEqual(p.excess,.10/15-.04)

    def test_missing_result_does_not_disappear_or_become_cash(self):
        slots,cohorts,_=evaluate(pd.DataFrame([labeled(fwd_ret_60=None)]),horizons=(60,))
        p=cohorts[(cohorts.variant=='baseline') & (cohorts.view=='usage')].iloc[0]
        self.assertEqual(p.n_selected,1)
        self.assertEqual(p.n_invalid,1)
        self.assertTrue(pd.isna(p.net_return))
        self.assertEqual(slots.iloc[0].label_status,'stock_unavailable')

    def test_real_weekly_membership_and_order(self):
        frame=pd.DataFrame([labeled('BBB'),labeled('AAA'),labeled('BAD',net_margin=-.5,free_cash_flow=-100)])
        expected=select_weekly_attention(build_stock_decisions(frame,decision_date='2024-01-31',generated_at_utc='x',policy_version='v2'))
        slots,_,_=evaluate(frame,horizons=(60,))
        observed=slots[(slots.variant=='baseline')&(slots.view=='list')]
        self.assertEqual(observed.symbol.tolist(),[d.symbol for d in expected])

    def test_future_evidence_rejected(self):
        with self.assertRaisesRegex(ValueError,'future'):
            evaluate(pd.DataFrame([labeled(market_asof='2024-02-01')]),horizons=(60,))

    def test_duplicate_decision_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            evaluate(pd.DataFrame([labeled(),labeled()]),horizons=(60,))

    def test_labels_cannot_change_selection(self):
        frame=pd.DataFrame([labeled('AAA'),labeled('BBB')])
        a,_,_=evaluate(frame,horizons=(60,))
        frame['fwd_ret_60']=[-100,100]
        b,_,_=evaluate(frame,horizons=(60,))
        self.assertEqual(a[['symbol','variant','rank']].to_dict('records'), b[['symbol','variant','rank']].to_dict('records'))

    def test_mismatched_and_undated_outcomes_retained_invalid(self):
        self.assertEqual(label_status(labeled(label_end_60='2024-04-25'),60),'timing_mismatch')
        self.assertEqual(label_status(labeled(label_end_60=None,fwd_ret_60=-.553),60),'undated_or_assumed_delisting')
        self.assertEqual(label_status(labeled(label_end_60='2025-04-26',qqq_label_end_60='2025-04-26'),60),'horizon_overrun')

    def test_zero_investable_names_produces_cash_usage(self):
        _,p,_=evaluate(pd.DataFrame([labeled(return_20d=.30)]),horizons=(60,))
        r=p[(p.variant=='baseline')&(p.view=='usage')].iloc[0]
        self.assertEqual(r.n_selected,0)
        self.assertEqual(r.net_return,0)
        self.assertAlmostEqual(r.excess,-.04)

    def test_market_group_is_ex_ante_and_unknown_is_not_up(self):
        self.assertEqual(market_group(1.1,.1),'up')
        self.assertEqual(market_group(.9,-.1),'down')
        self.assertEqual(market_group(.9,.1),'mixed')
        self.assertEqual(market_group(None,.1),'unknown')

    def test_candidate_only_reranks_preserves_decision_evidence(self):
        ds=build_stock_decisions(pd.DataFrame([labeled('AAA'),labeled('BBB')]),decision_date='2024-01-31',generated_at_utc='x',policy_version='v2')
        ranked=assign_action_priorities_v2(ds,pre_earnings_penalty=0)
        self.assertEqual({d.symbol:replace(d,priority=0) for d in ds}, {d.symbol:replace(d,priority=0) for d in ranked})
        for bad in [float('nan'),float('inf'),-.1,1.1]:
            with self.assertRaises(ValueError): assign_action_priorities_v2(ds,pre_earnings_penalty=bad)

    def test_block_interval_constant_known_difference(self):
        lo,hi,block=block_interval(np.repeat(.02,24),pd.Series(pd.date_range('2020-01-31',periods=24,freq='ME')),60)
        self.assertAlmostEqual(lo,.02)
        self.assertAlmostEqual(hi,.02)
        self.assertEqual(block,3)
        self.assertEqual(block_interval(np.repeat(.02,3),pd.Series(pd.date_range('2020-01-31',periods=3,freq='ME')),60)[:2],(None,None))


if __name__=='__main__': unittest.main()
