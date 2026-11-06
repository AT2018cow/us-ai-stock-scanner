from __future__ import annotations

import inspect
import itertools
import unittest

import numpy as np
import pandas as pd

from ai_value_scanner import scanner, backtest
from ai_value_scanner.fundamentals import accounting
from ai_value_scanner.decision.quality import build_company_quality_v1, build_company_quality_v2
from ai_value_scanner.decision.entry import build_entry_quality_v1, build_entry_quality_v2
from ai_value_scanner.features.price import compute_price_history_features


def accounting_inputs(**changes):
    values = dict.fromkeys(inspect.signature(accounting.derive_accounting_metrics).parameters)
    values.update(revenue=100, revenue_prev=80, adjusted_ebit=20, adjusted_net_income=15,
                  operating_cash_flow=25, capex_raw=-5, current_assets=50,
                  current_liabilities=25, interest_expense=2, debt_long_term=100,
                  debt_current=0, cash_and_equivalents=0, adjusted_ebitda=10)
    values.update(changes)
    return values


def ready_metrics():
    return dict(price_to_sma200=1.05, price_to_sma50=1.03, days_below_sma200=0,
                return_20d=.05, return_60d=.1, drawdown_from_52w_high=.08,
                range_position_52w=.8, relative_strength_60d_qqq=.04,
                volatility_60d=.35, regime='up', market_asof='2026-11-05')


class AccountingDomainTests(unittest.TestCase):
    def test_six_case_leverage_matrix_to_canonical_evidence(self):
        for cash, ebitda in itertools.product((0, 200), (10, 0, -10)):
            with self.subTest(cash=cash, ebitda=ebitda):
                inputs = accounting_inputs(cash_and_equivalents=cash, adjusted_ebitda=ebitda)
                self.assertIs(scanner.derive_accounting_metrics, accounting.derive_accounting_metrics)
                self.assertIs(backtest.derive_accounting_metrics, accounting.derive_accounting_metrics)
                metrics = accounting.derive_accounting_metrics(**inputs)
                metrics['adjusted_ebitda'] = ebitda
                expected = (100-cash)/ebitda if ebitda > 0 else None
                self.assertEqual(metrics['net_debt_to_ebitda'], expected)
                for builder in (build_company_quality_v1, build_company_quality_v2):
                    q = builder(metrics)
                    if ebitda <= 0:
                        self.assertNotIn('net_debt_to_ebitda_strong', [x.code for x in q.positives])
                    if cash == 0 and ebitda <= 0:
                        self.assertIn('net_debt_nonpositive_ebitda', [x.code for x in q.risks])

    def test_debt_without_earnings_suppresses_grade_a_even_if_other_metrics_strong(self):
        from test_company_quality_v1 import _strong_metrics
        metrics = _strong_metrics()
        metrics.update(net_debt=100, adjusted_ebitda=-10, net_debt_to_ebitda=-10)
        for builder in (build_company_quality_v1, build_company_quality_v2):
            quality = builder(metrics,decision_date='2026-11-05',data_asof='2026-11-01')
            self.assertNotEqual(quality.grade.value,'A')
            self.assertIn('net_debt_nonpositive_ebitda',[x.code for x in quality.risks])

    def test_nonfinite_missing_score_and_coverage(self):
        for values in itertools.product((None, float('nan'), float('inf'), -float('inf')), repeat=5):
            self.assertEqual(accounting.fundamental_quality_score_from_metrics(*values), .5)
        for invalid in (float('nan'), float('inf'), -float('inf')):
            out = accounting.derive_accounting_metrics(**accounting_inputs(debt_long_term=invalid))
            self.assertEqual(out['total_debt_source'], 'partial')
            self.assertIsNone(accounting.safe_yoy(invalid, 1))
            self.assertEqual(accounting.growth_direction(1, invalid), (None, None))
        self.assertEqual(accounting.clamp01(float('nan')), 0)

    def test_manual_normalization_golden(self):
        # GAAP NI 15, EBIT 20, D&A 5; addback 3, gain 8 -> NI10, EBIT15, EBITDA20.
        out = accounting.compute_adjusted_metrics(15, 20, 5, 100, 80, 3, 8, 0, 0, None)
        self.assertEqual([out[k] for k in ('adjusted_net_income','adjusted_ebit','adjusted_ebitda')], [10,15,20])
        metrics = accounting.derive_accounting_metrics(**accounting_inputs(
            adjusted_net_income=10, adjusted_ebit=15, adjusted_ebitda=20))
        self.assertEqual(metrics['free_cash_flow'], 20)
        self.assertEqual(metrics['net_debt_to_ebitda'], 5)
        self.assertEqual(metrics['interest_coverage'], 7.5)
        self.assertEqual(metrics['ocf_to_net_income'], 2.5)


class PriceWindowTests(unittest.TestCase):
    def test_bad_prices_do_not_become_zero_volatility(self):
        for slot, value in itertools.product((0,30,60), (None,float('nan'),float('inf'),0,-1)):
            closes = [100.0]*61
            closes[slot] = value
            out = compute_price_history_features(current_price=100,range_highs=[110],range_lows=[90],
                                                 closes=closes,dollar_volumes=[1000]*20)
            self.assertIsNone(out['volatility_60d'])
            self.assertIsNone(out['return_60d'])
            self.assertLess(out['volatility_60d_observations'], 60)

    def test_adapters_preserve_bad_slot_and_missing_session(self):
        from ai_value_scanner.market_calendar import is_session_day
        dates = [d for d in pd.bdate_range('2026-01-05', periods=220, tz='UTC') if is_session_day(d.date())]
        for missing_value in (True, False):
            records = [dict(t=d.isoformat(),o=100,h=101,l=99,c=100,v=1000) for d in dates]
            if missing_value:
                records[-30]['c'] = None
            else:
                records.pop(-30)
            frame = pd.DataFrame(records).rename(columns=dict(o='open',h='high',l='low',c='close',v='volume'))
            frame.index = pd.to_datetime(frame.pop('t'))
            scan = scanner.price_dimension_from_bars(100, records)
            replay = backtest.compute_price_features_asof(frame, frame.index[-1], 420)
            for key in scan:
                self.assertEqual(scan[key], replay[key], key)
            self.assertIsNone(scan['volatility_60d'])
            self.assertIsNone(scan['return_60d'])

    def test_invalid_volatility_blocks_both_policies(self):
        for builder, value in itertools.product((build_entry_quality_v1,build_entry_quality_v2),
                                                (None,float('nan'),float('inf'),-1)):
            metrics = ready_metrics(); metrics['volatility_60d'] = value
            entry = builder(metrics, decision_date='2026-11-05')
            self.assertEqual(entry.state.value, 'INSUFFICIENT_DATA')
            gate = next(g for g in entry.gate_results if g.gate_key == 'volatility_cap')
            self.assertTrue(gate.blocking)
            self.assertLess(entry.confidence,.5)


if __name__ == '__main__':
    unittest.main()
