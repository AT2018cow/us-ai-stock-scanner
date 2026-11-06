from datetime import datetime,date,timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from ai_value_scanner.market_data import official_eod_window,completed_bar
from ai_value_scanner.evaluation.backtest import forward_return_with_exit,holding_session_dates
from ai_value_scanner.config import ScanConfig
from ai_value_scanner.scanner import AlpacaClient,RequestRateLimiter,build_session


class SipMigrationTests(unittest.TestCase):
    def test_bounded_history_query_passes_end_and_rejects_future_rows(self):
        with tempfile.TemporaryDirectory() as root:
            client=AlpacaClient(build_session(),'x','x','key','secret','sip',2,RequestRateLimiter(100),Path(root),False,0,0,0)
            client.eod_session=date(2026,11,5);client.daily_end_iso='2026-11-06T03:00:00Z'
            from unittest.mock import Mock
            response=Mock();response.json.return_value={'bars':{'AAPL':[dict(t='2026-11-05T05:00:00Z',c=10),dict(t='2026-11-06T05:00:00Z',c=99)]}}
            with patch.object(client,'_get',return_value=response) as get:
                rows=client.get_daily_bars(['AAPL'],'2026-10-01',100)
            self.assertEqual(get.call_args.kwargs['params']['end'],client.daily_end_iso)
            self.assertEqual(len(rows['AAPL']),1)

    def test_candidate_collector_uses_only_complete_sip_bar(self):
        from types import SimpleNamespace
        from ai_value_scanner.scanner import collect_candidates_with_universe_audit
        class Client:
            eod_session=date(2026,11,5)
            def get_assets(self,status):return [dict(symbol='AAPL',name='Apple',exchange='NASDAQ',status='active',tradable=True)]
            def get_snapshots(self,*a):raise AssertionError('SIP latest endpoint forbidden')
            def get_daily_bars(self,*a):return {'AAPL':[dict(t='2026-11-05T05:00:00Z',c=100,v=30000)]}
        sec=SimpleNamespace(ticker_mapping=lambda:pd.DataFrame([dict(symbol='AAPL',cik='1',company_name='Apple')]))
        frame,_,_=collect_candidates_with_universe_audit(Client(),sec,ScanConfig(),symbol_allowlist={'AAPL'})
        self.assertEqual(frame.iloc[0].price,100)
        self.assertEqual(frame.iloc[0].dollar_volume,3_000_000)

    def test_after_close_delay_and_weekend(self):
        for hour,minute in [(15,0),(21,10)]:
            with self.assertRaises(ValueError):official_eod_window(datetime(2026,11,5,hour,minute,tzinfo=timezone.utc))
        session,end=official_eod_window(datetime(2026,11,5,21,21,tzinfo=timezone.utc))
        self.assertEqual(session,date(2026,11,5));self.assertEqual(end,'2026-11-05T21:01:00+00:00')
        self.assertEqual(official_eod_window(datetime(2026,11,7,12,tzinfo=timezone.utc))[0],date(2026,11,6))

    def test_completed_bar_rejects_stale_and_discards_future(self):
        rows=[dict(t='2026-11-04T05:00:00Z',c=10,v=2),dict(t='2026-11-05T05:00:00Z',c=11,v=3),dict(t='2026-11-06T05:00:00Z',c=999,v=999)]
        self.assertEqual(completed_bar(rows,date(2026,11,5))['c'],11)
        self.assertIsNone(completed_bar(rows[:1],date(2026,11,5)))

    def test_missing_internal_session_does_not_extend_exit(self):
        idx=pd.bdate_range('2024-01-02',periods=10,tz='UTC')
        frame=pd.DataFrame({'open':100.,'close':110.},index=idx)
        full,end=forward_return_with_exit(frame,'2024-01-02',5,.003)
        missing=frame.drop(idx[2])
        self.assertEqual(forward_return_with_exit(missing,'2024-01-02',5,.003),(full,end))
        self.assertEqual(end,pd.Timestamp('2024-01-09',tz='UTC'))
        self.assertEqual(forward_return_with_exit(frame.drop(end),'2024-01-02',5,.003),(None,None))
        self.assertEqual(forward_return_with_exit(frame.drop(idx[1]),'2024-01-02',5,.003),(None,None))

    def test_holiday_label_calendar_matches_all_symbols(self):
        entry,end=holding_session_dates('2024-03-28',2)
        self.assertEqual(entry.strftime('%Y-%m-%d'),'2024-04-01')
        self.assertEqual(end.strftime('%Y-%m-%d'),'2024-04-02')

    def test_sip_and_iex_cache_namespaces_are_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            clients=[AlpacaClient(build_session(),'x','x','key','secret',feed,2,RequestRateLimiter(100),Path(root),True,100,100,100) for feed in ['iex','sip']]
            self.assertNotEqual(clients[0].cache_dir,clients[1].cache_dir)
            (clients[0].cache_dir/'bars_fake.json').write_text('{"AAPL":[{"t":"2024-01-02T05:00:00Z","c":99}]}')
            self.assertEqual(clients[1]._load_bars_from_any_cache(['AAPL'],'2024-01-01'),{})

    def test_official_feed_overrides_environment_intraday_does_not(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('intraday_monitor',Path('scripts/intraday_watch.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.dict('os.environ',{'ALPACA_FEED':'sip','ALPACA_API_ENDPOINT':'https://paper-api.alpaca.markets','ALPACA_API_KEY':'k','ALPACA_API_SECRET':'s'}):
            client=module.build_alpaca_client(ScanConfig())
            self.assertEqual(client.feed,'iex')

    def test_production_sip_feed_overrides_iex_environment(self):
        from ai_value_scanner.scanner import load_runtime_settings
        with tempfile.TemporaryDirectory() as root, patch('ai_value_scanner.scanner.load_dotenv'), patch.dict('os.environ',{
            'ALPACA_FEED':'iex','ALPACA_API_ENDPOINT':'https://paper-api.alpaca.markets',
            'ALPACA_API_KEY':'k','ALPACA_API_SECRET':'s','SEC_USER_AGENT':'unit-test test@example.invalid'}):
            client,_,_=load_runtime_settings(ScanConfig(official_market_mode='sip_eod',cache_dir=root))
            self.assertEqual(client.feed,'sip')

    def test_monitor_never_relabels_legacy_snapshot_as_sip(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('intraday_source_label',Path('scripts/intraday_watch.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        old=module.snapshot_market_source([{'symbol':'AAA'}])
        self.assertIn('unspecified',old)
        self.assertNotIn('SIP',old)
        current=module.snapshot_market_source([{'provenance':{'market_data_feed':'sip','market_data_mode':'sip_eod'}}])
        self.assertEqual(current,'SIP completed-session daily bars')
        text=module.render_markdown([],decision_date='2026-11-05',scope='top',market_status='CLOSED',generated_utc='now',baseline_source=current)
        self.assertIn('IEX intraday',text)
        self.assertIn('SIP completed-session daily bars',text)

    def test_monitor_explicit_snapshot_uses_recorded_session_date(self):
        import importlib.util,json
        spec=importlib.util.spec_from_file_location('intraday_session_label',Path('scripts/intraday_watch.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'2026-11-05/production';target.mkdir(parents=True)
            (target/'decisions.jsonl').write_text(json.dumps({'symbol':'AAA','decision_date':'2026-11-05'})+'\n')
            self.assertEqual(module.load_snapshot(Path(root),target)['decision_date'],'2026-11-05')

    def test_early_close_waits_twenty_minutes(self):
        # Friday after Thanksgiving closes at 13:00 New York / 18:00 UTC.
        with self.assertRaises(ValueError):official_eod_window(datetime(2026,11,27,18,19,tzinfo=timezone.utc))
        self.assertEqual(official_eod_window(datetime(2026,11,27,18,20,tzinfo=timezone.utc))[0],date(2026,11,27))

    def test_immutable_snapshot_reuse_requires_sip_provenance(self):
        from dataclasses import replace
        import hashlib
        from ai_value_scanner.decision import build_stock_decisions
        from ai_value_scanner.reporting.snapshot import write_decision_snapshot
        from ai_value_scanner.scanner import _evaluate_existing_snapshot_reuse
        decisions=build_stock_decisions(pd.DataFrame([dict(symbol='AAA',market_asof='2026-11-05')]),
            decision_date='2026-11-05',generated_at_utc='2026-11-06T03:00:00+00:00',policy_version='v2')
        for mode in ['snapshot','sip_eod']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                records=[replace(d,provenance={**d.provenance,'market_data_mode':mode}) for d in decisions]
                paths=write_decision_snapshot(output_root=root,strategy_style='production',decisions=records,
                    daily_attention=(),weekly_attention=(),generated_at_utc='2026-11-06T03:00:00+00:00',
                    decision_date='2026-11-05',config_fingerprint='test',policy_version='v2',layout_version='v2')
                file=paths.root/'decisions.jsonl';before=hashlib.sha256(file.read_bytes()).hexdigest()
                status,error=_evaluate_existing_snapshot_reuse(paths.root,decision_date='2026-11-05',
                    strategy_style='production',policy_version='v2',layout_version='v2',market_mode='sip_eod')
                self.assertEqual(status,'reused' if mode=='sip_eod' else 'failed')
                if mode=='snapshot':self.assertIn('market-data mode',error)
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),before)

    def test_mode_validation(self):
        with self.assertRaises(ValueError):ScanConfig.from_dict({'official_market_mode':'auto'})

if __name__=='__main__':unittest.main()
