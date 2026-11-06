from __future__ import annotations

import unittest
import pandas as pd
from ai_value_scanner.research.review_utility import AttentionObservation, attention_utility, evaluate_entry_increment, label_integrity
from ai_value_scanner.decision.review_context import build_review_context
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.reporting.decision import render_detailed_report,render_action_list


def row(symbol='A', day='2024-01-31', **changes):
    result=dict(symbol=symbol,signal_date=day,fundamental_data_asof=day,market_asof=day,
        net_margin=.25, revenue=1000, net_income=200, adjusted_net_income=250, market_cap=5000,
        free_cash_flow=200, adjusted_ebit=250, ocf_to_net_income=1.2,accrual_ratio=-.05,
        revenue_yoy=.2, adjusted_net_income_yoy=.2, operating_cash_flow_yoy=.2,
        net_debt_to_ebitda=0,interest_coverage=10,current_ratio=2, shares_yoy=0,
        fcf_yield=.06,ps_hist_percentile=.2,pe_hist_percentile=.3,
        receivables_growth_gap=0,inventory_growth_gap=0,
        price_to_sma200=1.05,price_to_sma50=1.03,days_below_sma200=0,
        return_20d=.05,return_60d=.10,drawdown_from_52w_high=.08,
        range_position_52w=.8,relative_strength_60d_qqq=.04,volatility_60d=.35,regime='up')
    result.update(changes)
    return result


class UtilityTests(unittest.TestCase):
    def test_attention_repeat_upgrade_failure_and_censoring(self):
        obs=[AttentionObservation('2026-11-02',('A',),{'A':'WATCH_BREAKOUT','B':'HOLD_MONITOR'}),
             AttentionObservation('2026-11-03',('A','B'),{'A':'PRIORITY_REVIEW','B':'WATCH_BREAKOUT'}),
             AttentionObservation('2026-11-04',('A',),{'A':'AVOID','B':'HOLD_MONITOR'})]
        events,weekly,_=attention_utility(obs,failure_observations=2)
        self.assertTrue(pd.isna(events.iloc[0].new_since_previous))
        self.assertEqual(int(events.repeated_slot.eq(True).sum()),2)
        self.assertEqual(int(events.downgrade_within_window.eq(True).sum()),2)
        self.assertEqual(weekly.n_human_reviews.iloc[0],0)
        self.assertTrue(pd.isna(weekly.review_minutes.iloc[0]))
        reviews=pd.DataFrame([dict(decision_date='2026-11-03',symbol='A',review_status='rejected',review_minutes=12,rejection_reason='valuation')])
        _,weekly,reasons=attention_utility(obs,reviews,failure_observations=2)
        self.assertEqual(weekly.review_minutes.iloc[0],12)
        self.assertEqual(reasons.iloc[0]['rejection_reason'],'valuation')
        with self.assertRaises(ValueError): attention_utility(obs,pd.concat([reviews,reviews]))
        events,_,_=attention_utility(obs[:2],failure_observations=2)
        self.assertTrue(events.loc[events.upgraded,'downgrade_within_window'].isna().all())

    def test_paired_dates_and_overlap_without_row_weight_bias(self):
        rows=[]
        for day,end in [('2024-01-31','2024-04-30'),('2024-02-29','2024-05-31'),('2024-06-28','2024-09-30')]:
            for symbol,ret,sma in [('A',.2,1.05),('B',0,.90)]:
                rows.append(row(symbol,day,price_to_sma200=sma,fwd_ret_60=ret,qqq_return_60=.02,
                                label_end_60=end,qqq_label_end_60=end,watchlist_source='frozen_approx'))
        paired,summary,_,meta=evaluate_entry_increment(pd.DataFrame(rows),horizons=(60,))
        self.assertEqual(len(paired),3)
        self.assertAlmostEqual(summary.loc[summary.segment_type.eq('overall'),'delta_excess'].iloc[0],.10)
        self.assertEqual(summary.loc[summary.segment_type.eq('nonoverlapping'),'n_dates'].iloc[0],2)
        self.assertEqual(meta['n_quality_ab'],6)
        rows[0]['qqq_label_end_60']='2024-05-01'
        with self.assertRaises(ValueError): evaluate_entry_increment(pd.DataFrame(rows),horizons=(60,))

    def test_future_and_nonfinite_outcomes(self):
        frame=pd.DataFrame([row(fwd_ret_20=float('inf'),qqq_return_20=.1,label_end_20='2024-02-29',qqq_label_end_20='2024-02-29')])
        info=label_integrity(frame,20)
        self.assertEqual(info['n_valid_paired'],0)
        frame['market_asof']='2025-01-01'
        with self.assertRaises(ValueError): evaluate_entry_increment(frame,horizons=(20,))

    def test_valuation_sensitivity_never_serializes_nonfinite_values(self):
        import json
        context=build_review_context({'market_cap':1e308,'net_income':1e-308,'adjusted_net_income':1e-308})
        self.assertIsNone(context['review_gaap_pe'])
        self.assertIsNone(context['review_adjusted_pe_base'])
        json.dumps(context,allow_nan=False)

    def test_canonical_context_arithmetic_and_report_counter_evidence(self):
        context=build_review_context(row())
        self.assertEqual(context['review_gaap_pe'],25)
        self.assertEqual(context['review_adjusted_pe_lower'],25)
        self.assertEqual(context['review_adjusted_pe_base'],20)
        self.assertAlmostEqual(context['review_adjusted_pe_higher'],5000/300)
        base=build_stock_decisions(pd.DataFrame([row()]),decision_date='2024-01-31',generated_at_utc='2024-01-31T22:00:00Z',policy_version='v2')
        hotter=build_stock_decisions(pd.DataFrame([row(return_20d=.20,sector='Software',watchlist_bucket='core_ai')]),decision_date='2024-01-31',generated_at_utc='2024-01-31T22:00:00Z',policy_version='v2')
        self.assertEqual(base[0].quality,hotter[0].quality)
        report=render_detailed_report(hotter[0],layout_version='v2')
        self.assertIn('Adjusted income -20%',report)
        self.assertIn('Unverified: filing age',report)
        self.assertIn('Counter-evidence to review',report)
        action=render_action_list(hotter,layout_version='v2',all_decisions=hotter)
        self.assertIn('Industry exposure: Software 1/1',action)


if __name__=='__main__': unittest.main()
