from __future__ import annotations
import unittest
import pandas as pd
from test_current_top15_backtest import labeled
from ai_value_scanner.research.top15_backtest import evaluate
from ai_value_scanner.research.selection_attribution import concentration,proximity,sic2,stage_attribution,concentration_and_costs


class AttributionTests(unittest.TestCase):
    def test_known_classification_and_missing_coverage(self):
        p=pd.DataFrame(dict(symbol=['A','B','C'],industry=['SOFTWARE','SOFTWARE','UNKNOWN'],weight=[.2,.3,.1]))
        r=concentration(p,'industry')
        self.assertAlmostEqual(r['deployed'],.6)
        self.assertAlmostEqual(r['cash'],.4)
        self.assertAlmostEqual(r['known_coverage'],5/6)
        self.assertAlmostEqual(r['top_group_stock_share'],5/6)
        self.assertEqual(r['hhi_known'],1.)
        self.assertEqual(sic2(3571.),'35')
        self.assertEqual(sic2(float('nan')),'UNKNOWN')

    def test_proximity_point_pass_can_have_insufficient_interval(self):
        r=proximity(pd.Series([-.005],index=['2024-01-31']),.01)
        self.assertTrue(r['observed_close'])
        self.assertIsNone(r['interval_supports_close'])
        r=proximity(pd.Series([-.02]*24,index=pd.date_range('2020-01-31',periods=24,freq='ME').strftime('%Y-%m-%d')),.01)
        self.assertFalse(r['observed_close']);self.assertFalse(r['interval_supports_close'])

    def test_stages_reuse_canonical_states_and_preserve_watch_branch(self):
        raw=pd.DataFrame([labeled('READY',market_data_feed='sip',sic=3571),
                          labeled('WATCH',market_data_feed='sip',sic=3571,return_20d=.3)])
        slots,cohorts,_=evaluate(raw,horizons=(60,))
        stages,_,edges,_=stage_attribution(raw,slots,cohorts)
        counts=stages.set_index('stage').n_members
        self.assertEqual(counts['quality_ab'],2)
        self.assertEqual(counts['quality_ab_ready'],1)
        self.assertEqual(counts['weekly_top15'],2)
        self.assertEqual(counts['priority_top15'],1)
        self.assertAlmostEqual(stages[stages.stage.eq('fixed_usage')].iloc[0].net_return,.1/15)

    def test_costs_stress_both_stock_and_benchmark_and_sensitivity_keeps_cash(self):
        raw=pd.DataFrame([labeled('READY',market_data_feed='sip',sic=3571,sic_description='SOFTWARE')])
        slots,cohorts,_=evaluate(raw,horizons=(60,))
        concentrations,costs,sensitivity,_=concentration_and_costs(raw,slots,cohorts)
        self.assertEqual(set(concentrations['view']),{'list','usage'})
        self.assertTrue(concentrations.n_symbols.eq(1).all())
        r=costs[costs.view.eq('usage')&costs.variant.eq('baseline')&costs.per_side_bps.eq(30)].iloc[0]
        self.assertAlmostEqual(r.mean_return,.097/15)
        self.assertAlmostEqual(r.mean_qqq,.037)
        self.assertAlmostEqual(r.mean_excess,.097/15-.037)
        s=sensitivity[sensitivity.view.eq('usage')&sensitivity.variant.eq('baseline')&sensitivity.scenario.eq('drop_top_symbol')].iloc[0]
        self.assertEqual(s.mean_return,0)
        self.assertAlmostEqual(s.mean_excess,-.04)

    def test_frozen_membership_mismatch_fails_closed(self):
        raw=pd.DataFrame([labeled('READY',market_data_feed='sip',sic=3571)])
        slots,cohorts,_=evaluate(raw,horizons=(60,))
        slots.loc[slots.variant.eq('ab_pool'),'grade']='C'
        with self.assertRaisesRegex(ValueError,'parity'):stage_attribution(raw,slots,cohorts)


if __name__=='__main__':unittest.main()
