from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.model import EntryState, ActionState
from ai_value_scanner.research.top15_backtest import evaluate
from ai_value_scanner.research.value_pullback import (
    variants, signal, conviction, outcomes, block_stats, holm, selections,
    evaluate_cache, common_dates, adapted_entry,
)
from test_current_top15_backtest import labeled


def fixture(**changes):
    row=labeled(**changes)
    ds=build_stock_decisions(pd.DataFrame([row]),decision_date=row['signal_date'],generated_at_utc='x',policy_version='v2')
    return row, ds


class ValuePullbackTests(unittest.TestCase):
    def test_baseline_members_weights_and_returns_match_canonical(self):
        row,ds=fixture()
        slots,_,_=evaluate(pd.DataFrame([row]),horizons=(60,))
        base=variants(ds,{row['symbol']:row},('D0',))['D0']
        self.assertEqual(ds,base)
        chosen=selections(base)['fixed_usage']
        actual=outcomes(chosen,{row['symbol']:row},60,view='fixed_usage')
        expected=slots[(slots.variant=='baseline')&(slots.view=='usage')]
        self.assertEqual(list(expected.symbol),[d.symbol for d in chosen])
        self.assertAlmostEqual(actual['net_return'],.1/15)

    def test_a_only_relaxes_bands_preserves_quality_and_score(self):
        row,ds=fixture(price_to_sma50=.95,return_20d=-.07,price_to_sma200=1.1,
                       regime='up',benchmark_trend_ok=True,relative_strength_60d_qqq=.1)
        d=ds[0];self.assertNotEqual(d.entry.state,EntryState.ENTRY_READY)
        candidate=variants(ds,{d.symbol:row},('A',))['A'][0]
        self.assertEqual(candidate.entry.state,EntryState.ENTRY_READY)
        self.assertEqual(candidate.quality,d.quality)
        self.assertEqual(candidate.entry.score,d.entry.score)
        self.assertEqual(ds[0],d)

    def test_a_rejects_below_boundary_and_defensive_or_unknown(self):
        for changes in [dict(price_to_sma50=.949),dict(return_20d=-.071),
                        dict(regime='down'),dict(benchmark_trend_ok=False),dict(benchmark_trend_ok=None)]:
            fields=dict(price_to_sma50=.96,return_20d=-.05,price_to_sma200=1.1,
                        regime='up',benchmark_trend_ok=True,relative_strength_60d_qqq=.1)
            fields.update(changes);row,ds=fixture(**fields)
            self.assertNotEqual(adapted_entry(ds[0],row,relax=True).state,EntryState.ENTRY_READY)

    def test_a_cannot_bypass_missing_volatility_or_deep_drawdown(self):
        for changes in [dict(volatility_60d=None),dict(drawdown_from_52w_high=.4),dict(return_60d=-.1)]:
            row,ds=fixture(price_to_sma50=.96,return_20d=-.05,**changes)
            self.assertNotEqual(adapted_entry(ds[0],row,relax=True).state,EntryState.ENTRY_READY)

    def test_b_excludes_extension_without_changing_score(self):
        row,ds=fixture(price_to_sma50=1.06,return_20d=.04)
        d=ds[0];self.assertEqual(d.entry.state,EntryState.ENTRY_READY)
        b=variants(ds,{d.symbol:row},('B',))['B'][0]
        self.assertEqual(b.entry.state,EntryState.WATCH_PULLBACK)
        self.assertEqual(b.entry.score,d.entry.score)
        self.assertEqual(b.quality,d.quality)

    def test_b_boundary_equal_allowed(self):
        row,ds=fixture(price_to_sma50=1.05,return_20d=.07,price_to_sma200=1.3)
        self.assertEqual(adapted_entry(ds[0],row,restrict=True).state,EntryState.ENTRY_READY)

    def test_signal_negative_cashflow_or_missing_gets_no_reward(self):
        for cash,growth in [(-.05,.4),(None,.4),(np.inf,.2),(.08,None)]:
            self.assertEqual(signal(dict(fcf_yield=cash,revenue_yoy=growth)),0)
        self.assertAlmostEqual(signal(dict(fcf_yield=.08,revenue_yoy=.2)),1)

    def test_conviction_is_score_not_ordinal_rank(self):
        _,ds=fixture();d=ds[0]
        p=conviction(d)
        self.assertEqual(p,conviction(replace(d,priority=999)))
        self.assertTrue(-.12<=p<=1.04)

    def test_c_keeps_action_and_ready_layers(self):
        row,ds=fixture();d=ds[0]
        watch=replace(d,symbol='WATCH',entry=replace(d.entry,state=EntryState.WATCH_PULLBACK),action_state=ActionState.WATCH_PULLBACK)
        lookup={d.symbol:row,'WATCH':dict(row,fcf_yield=.08,revenue_yoy=.4)}
        c=variants((d,watch),lookup,('C',))['C']
        self.assertEqual(c[0].symbol,d.symbol)
        self.assertEqual({x.symbol:x.entry for x in c},{x.symbol:x.entry for x in (d,watch)})

    def test_c_reorders_by_actual_score_and_ignores_arbitrary_rank_numbers(self):
        row,ds=fixture();first=replace(ds[0],symbol='AAA',priority=1)
        second=replace(ds[0],symbol='ZZZ',priority=999)
        lookup={'AAA':dict(row,fcf_yield=.001,revenue_yoy=0),
                'ZZZ':dict(row,fcf_yield=.08,revenue_yoy=.2)}
        ranked=variants((first,second),lookup,('C',))['C']
        self.assertEqual([d.symbol for d in ranked],['ZZZ','AAA'])
        # Large ordinal rank is never multiplied into the candidate score.
        ranked2=variants((replace(first,priority=9999),replace(second,priority=1)),lookup,('C',))['C']
        self.assertEqual([d.symbol for d in ranked2],['ZZZ','AAA'])

    def test_b_cannot_make_missing_or_damaged_data_ready(self):
        for changes in (dict(volatility_60d=None),dict(price_to_sma200=.8)):
            row,ds=fixture(**changes)
            before=ds[0].entry.state
            result=variants(ds,{ds[0].symbol:row},('B',))['B'][0]
            self.assertEqual(result.entry.state,before)

    def test_missing_outcome_does_not_become_cash_or_reweight(self):
        row,ds=fixture(fwd_ret_60=None)
        r=outcomes(ds,{ds[0].symbol:row},60,view='fixed_usage')
        self.assertIsNone(r['net_return']);self.assertEqual(r['n_invalid'],1)
        self.assertAlmostEqual(r['scenario_low'],-1/15)
        self.assertAlmostEqual(r['scenario_high'],1/15)

    def test_empty_usage_is_zero_not_missing(self):
        r=outcomes((),{},60,view='fixed_usage')
        self.assertEqual(r['net_return'],0);self.assertEqual(r['deployed'],0)

    def test_future_labels_do_not_affect_selection(self):
        row,ds=fixture();before=variants(ds,{ds[0].symbol:row})
        row.update(fwd_ret_60=999,qqq_return_60=-999)
        self.assertEqual(before,variants(ds,{ds[0].symbol:row}))

    def test_common_dates_use_all_candidates_not_pairwise_deletion(self):
        rows=[dict(signal_date=day,variant=v,view='fixed_usage',horizon=60,net_return=(None if day=='2020-02-28' and v=='B' else .1),mature=True,qualified=True)
              for day in ['2020-01-31','2020-02-28'] for v in ['D0','A','B']]
        self.assertEqual(list(common_dates(pd.DataFrame(rows),('D0','A','B'),60)),['2020-01-31'])

    def test_calendar_block_keeps_missing_month_and_is_reproducible(self):
        values=pd.Series([.02]*12,index=pd.date_range('2020-01-31',periods=12,freq='ME').astype(str)).drop('2020-06-30')
        a=block_stats(values);self.assertEqual(a,block_stats(values))
        self.assertEqual(a['calendar_months'],12);self.assertEqual(a['n'],11)
        self.assertAlmostEqual(a['low'],.02);self.assertAlmostEqual(a['high'],.02)
        self.assertLess(a['p'],.01)

    def test_holm_known_adjustment(self):
        self.assertEqual(holm({'A':.01,'B':.03,'C':.9}),{'A':.03,'B':.06,'C':.9})

    def test_bundle_rejects_identity_and_payload_tampering(self):
        path=Path(__file__).resolve().parents[1]/'scripts/evaluate_value_pullback_directions.py'
        spec=importlib.util.spec_from_file_location('vp_runner',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data.txt').write_text('valid');module.finish_bundle(root,{'config_sha256':'a'})
            module.verify_bundle(root,{'config_sha256':'a'})
            with self.assertRaisesRegex(ValueError,'specification'):module.verify_bundle(root,{'config_sha256':'b'})
            (root/'data.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError,'payload'):module.verify_bundle(root,{'config_sha256':'a'})


if __name__=='__main__':unittest.main()
