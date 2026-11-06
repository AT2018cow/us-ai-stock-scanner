"""Regression probes for calendar, EOD cache, and research identity review."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from ai_value_scanner.evaluation.backtest import (
    fallback_label_end_date, forward_return_with_exit, split_query_end_iso,
)
from ai_value_scanner.market_calendar import is_early_close, latest_completed_session, session_close_utc
from ai_value_scanner.market_data import official_eod_window
from ai_value_scanner.research.provenance import provenance_path, sha256_file, validate_config_identity
from ai_value_scanner.research.top15_backtest import label_status
from ai_value_scanner.scanner import AlpacaClient, NetworkMonitor, RequestRateLimiter, build_session
from test_current_top15_backtest import labeled

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location('followup_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CalendarReviewTests(unittest.TestCase):
    def test_complete_120_session_window_survives_holidays_and_mourning_day(self):
        # Independently specified closures, including the Bush mourning day.
        closed = pd.to_datetime(['2018-11-22', '2018-12-05', '2018-12-25',
                                 '2019-01-01', '2019-01-21', '2019-02-18'], utc=True)
        dates = pd.bdate_range('2018-09-04', '2019-02-26', tz='UTC').difference(closed)
        self.assertEqual(len(dates), 120)
        prices = pd.DataFrame({'open': 100., 'close': 110.}, index=dates)
        value, end = forward_return_with_exit(prices, '2018-08-31', 120, .003)
        self.assertAlmostEqual(value, .097)
        self.assertEqual(end, pd.Timestamp('2019-02-26', tz='UTC'))
        self.assertEqual(fallback_label_end_date('2018-08-31', 120), end)
        self.assertEqual(split_query_end_iso('2018-08-31', [20, 60, 120]), '2019-02-26')

    def test_all_six_rejected_windows_have_calendar_bounds(self):
        cases = {'2018-08-31': '2019-02-26', '2018-11-30': '2019-05-28',
                 '2024-08-30': '2025-02-25', '2024-10-31': '2025-04-28',
                 '2024-11-29': '2025-05-27', '2022-12-23': '2023-06-20'}
        for signal, expected in cases.items():
            with self.subTest(signal=signal):
                self.assertEqual(str(fallback_label_end_date(signal, 120).date()), expected)
        self.assertIsNone(fallback_label_end_date('not-a-date', 120))
        self.assertIsNone(fallback_label_end_date(None, 120))

    def test_top15_validation_accepts_actual_end_and_rejects_overrun(self):
        row = dict(signal_date='2018-08-31', fwd_ret_120=.097, qqq_return_120=.02,
                   label_end_120='2019-02-26', qqq_label_end_120='2019-02-26')
        self.assertEqual(label_status(row, 120), 'observed')
        row.update(label_end_120='2019-02-27', qqq_label_end_120='2019-02-27')
        self.assertEqual(label_status(row, 120), 'horizon_overrun')

    def test_friday_before_sunday_or_monday_independence_day_is_full_session(self):
        for day in [date(2021, 7, 2), date(2022, 7, 1), date(2027, 7, 2)]:
            with self.subTest(day=day):
                self.assertFalse(is_early_close(day))
                self.assertEqual(session_close_utc(day).hour, 20)
                premature = datetime(day.year, day.month, day.day, 17, 21, tzinfo=timezone.utc)
                self.assertLess(latest_completed_session(premature), day)
                with self.assertRaises(ValueError): official_eod_window(premature)
                self.assertEqual(official_eod_window(premature.replace(hour=20, minute=20))[0], day)

    def test_genuine_july3_early_closes_still_allow_delayed_publication(self):
        for year in [2023, 2024, 2025, 2028]:
            day = date(year, 7, 3)
            self.assertTrue(is_early_close(day))
            self.assertEqual(session_close_utc(day).hour, 17)
            self.assertEqual(official_eod_window(datetime(year, 7, 3, 17, 20, tzinfo=timezone.utc))[0], day)
        self.assertFalse(is_early_close(date(2026, 7, 2)))


class StableEodCacheTests(unittest.TestCase):
    def client(self, root):
        result = AlpacaClient(build_session(), 'https://paper.invalid', 'https://data.invalid',
                              'key', 'secret', 'sip', 2, RequestRateLimiter(100),
                              Path(root), True, 3600, 3600, 3600, NetworkMonitor())
        result.eod_session = date(2026, 11, 5)
        result.daily_end_iso = '2026-11-05T21:01:00Z'
        return result

    def response(self):
        result = Mock()
        result.json.return_value = {'bars': {'AAA': [dict(t='2026-11-05T05:00:00Z', o=10, c=11, v=1000)]}}
        return result

    def test_same_session_different_delayed_cutoffs_reuse_one_cache(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            with patch.object(client, '_get', return_value=self.response()) as get:
                expected = client.get_daily_bars(['AAA'], '2026-01-01', 100)
                self.assertEqual(get.call_args.kwargs['params']['end'], '2026-11-05T21:01:00Z')
                client.daily_end_iso = '2026-11-06T03:00:00Z'
                self.assertEqual(client.get_daily_bars(['AAA'], '2026-01-01', 100), expected)
                get.assert_called_once()
            self.assertEqual(len(list(client.cache_dir.glob('bars_*.json'))), 1)

    def test_same_session_outage_reuses_stale_cache_without_refreshing_mtime(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            with patch.object(client, '_get', return_value=self.response()):
                expected = client.get_daily_bars(['AAA'], '2026-01-01', 100)
            file = next(client.cache_dir.glob('bars_*.json'))
            old = time.time() - 8 * 3600
            os.utime(file, (old, old))
            client.daily_end_iso = '2026-11-06T03:00:00Z'
            with patch.object(client, '_get', side_effect=RuntimeError('temporary outage')):
                self.assertEqual(client.get_daily_bars(['AAA'], '2026-01-01', 100), expected)
            self.assertAlmostEqual(file.stat().st_mtime, old, delta=1.)
            self.assertTrue(client.monitor.to_dict()['stale_market_data_fallback_used'])

    def test_next_session_outage_cannot_reuse_prior_session_cache(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            with patch.object(client, '_get', return_value=self.response()):
                client.get_daily_bars(['AAA'], '2026-01-01', 100)
            client.eod_session = date(2026, 11, 6)
            client.daily_end_iso = '2026-11-06T21:01:00Z'
            with patch.object(client, '_get', side_effect=RuntimeError('outage')):
                with self.assertRaises(RuntimeError): client.get_daily_bars(['AAA'], '2026-01-01', 100)

    def test_request_cutoff_cannot_precede_actual_close(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            client.eod_session = date(2027, 7, 2)
            client.daily_end_iso = '2027-07-02T17:01:00Z'
            with patch.object(client, '_get') as get:
                with self.assertRaises(ValueError): client.get_daily_bars(['AAA'], '2027-01-01', 100)
                get.assert_not_called()


class CheckpointConfigurationTests(unittest.TestCase):
    def test_identity_accepts_same_config_and_rejects_changed_or_missing_identity(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'config.json';file.write_text('{"min_dollar_volume":2000000}')
            manifest = dict(config_sha256=sha256_file(file))
            validate_config_identity(manifest, file)
            file.write_text('{"min_dollar_volume":5000000}')
            for record in [manifest, {}]:
                with self.assertRaisesRegex(ValueError, 'configuration identity'):
                    validate_config_identity(record, file)

    def worker_module(self, root, config):
        # Exercise the actual resume functions without a Modal dependency in CI.
        class Image:
            @classmethod
            def debian_slim(cls, **kwargs): return cls()
            def __getattr__(self, name): return lambda *a, **kw: self
        class App:
            def __init__(self, *a): pass
            def function(self, **kwargs): return lambda function: function
            def local_entrypoint(self, **kwargs): return lambda function: function
        fake = SimpleNamespace(Image=Image, App=App)
        baseline = SimpleNamespace(cache_volume=Mock(), research_volume=Mock(), _modal_secrets=lambda: [])
        with patch.dict(sys.modules, {'modal': fake, 'modal_baseline_executor': baseline}):
            module = load_script('modal_selection_backtest')
        real_path = Path
        module.Path = lambda value: real_path(root) if str(value) == '/root/research/selection_review_20261106' else real_path(value)
        module.validate_config_identity = lambda manifest, path: validate_config_identity(manifest, config)
        return module

    def test_evaluation_resume_rejects_config_change_before_returning_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root);config = root / 'config.json';config.write_text('{}')
            original = sha256_file(config)
            for study in ['sip_2016_2020_v1', 'sip_2021_2026_v1']:
                p = root / study;p.mkdir();(p/'dataset.csv').write_text('frozen')
                (p/'success.json').write_text(json.dumps({'sha256': sha256_file(p/'dataset.csv')}))
            out = root / 'evaluation_sip_monthly_v2';out.mkdir()
            (out/'manifest.json').write_text(json.dumps({'config_sha256': original}))
            config.write_text('{"min_dollar_volume":5000000}')
            module = self.worker_module(root, config)
            with patch.object(module.os, 'chdir'):
                with self.assertRaisesRegex(ValueError, 'configuration identity'):
                    module.evaluate_remote({'scope': 'sip_monthly', 'code_sha': 'test'})

    def test_supplement_resume_rejects_changed_or_legacy_config_identity(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root);config = root / 'config.json';config.write_text('{}')
            out = root / 'completion_sip_monthly_v1';out.mkdir()
            module = self.worker_module(root, config)
            for record in [{'config_sha256': 'wrong'}, {}]:
                (out/'manifest.json').write_text(json.dumps(record))
                with patch.object(module.os, 'chdir'):
                    with self.assertRaisesRegex(ValueError, 'configuration identity'):
                        module.supplement_remote('sip_monthly')

    def test_fresh_supplement_rejects_upstream_config_before_output_creation(self):
        module = load_script('complete_selection_review')
        with tempfile.TemporaryDirectory() as root:
            root = Path(root);saved = root/'evaluation_sip_monthly_v2';saved.mkdir()
            (saved/'manifest.json').write_text(json.dumps({'config_sha256': 'different'}))
            out = root/'result'
            with patch.object(sys, 'argv', ['complete', '--scope', 'sip_monthly', '--evaluation-root', str(root), '--output', str(out)]):
                with self.assertRaisesRegex(ValueError, 'configuration identity'): module.main()
            self.assertFalse(out.exists())


class ExternalDatasetCliTests(unittest.TestCase):
    def dataset(self, root):
        rows = []
        for symbol in ['AAA', 'BBB']:
            item = labeled(symbol, market_data_feed='sip')
            for h, end in [(20, '2024-02-29'), (120, '2024-07-24'), (252, '2025-02-03')]:
                item.update({f'fwd_ret_{h}': .1, f'qqq_return_{h}': .04,
                             f'label_end_{h}': end, f'qqq_label_end_{h}': end})
            rows.append(item)
        file = Path(root)/'external.csv';pd.DataFrame(rows).to_csv(file,index=False)
        file.with_suffix('.meta.json').write_text(json.dumps(dict(roundtrip_cost=.003, entry_price_mode='next_open', exit_price_mode='close', market_data_feed='sip')))
        return file

    def test_external_dataset_cli_produces_complete_manifest_and_report(self):
        with tempfile.TemporaryDirectory() as root:
            file = self.dataset(root);out = Path(root)/'result'
            result = subprocess.run([sys.executable, str(ROOT/'scripts/evaluate_current_top15.py'),
                '--dataset', str(file), '--output', str(out), '--code-sha', 'fixture'], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((out/'manifest.json').read_text())
            self.assertEqual(manifest['inputs'][str(file)], sha256_file(file))
            self.assertIn(str(file.with_suffix('.meta.json')), manifest['inputs'])
            self.assertTrue((out/'report.md').exists())
            self.assertEqual(len(list(out.glob('*.csv'))), 8)

    def test_failed_bundle_write_leaves_output_retryable(self):
        module = load_script('evaluate_current_top15')
        with tempfile.TemporaryDirectory() as root:
            file = self.dataset(root);out = Path(root)/'result'
            argv = ['evaluate', '--dataset', str(file), '--output', str(out), '--code-sha', 'fixture']
            with patch.object(sys, 'argv', argv), patch.object(pd.DataFrame, 'to_csv', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'): module.main()
            self.assertFalse(out.exists())
            self.assertFalse(list(Path(root).glob('.result.*')))
            with patch.object(sys, 'argv', argv): module.main()
            self.assertTrue((out/'manifest.json').exists())

    def test_provenance_keeps_repo_relative_and_external_absolute_paths(self):
        self.assertEqual(provenance_path(ROOT/'configs/config.production.json', ROOT), 'configs/config.production.json')
        self.assertEqual(provenance_path('/tmp/external.csv', ROOT), '/tmp/external.csv')


class BoundedRelabelTests(unittest.TestCase):
    def test_text_of_features_and_unaffected_labels_is_preserved(self):
        module = load_script('relabel_market_history')
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/'source.csv';target = Path(root)/'target.csv'
            source.write_text('symbol,price,fwd_ret_60,fwd_ret_120\nAAPL,1000.123456789012345678901,0.1234567890123456789,\nMSFT,42.000,0.333,\n')
            module.write_changed_fields(source,target,{0,1},{0:{'fwd_ret_120':.097}})
            self.assertEqual(target.read_text(),'symbol,price,fwd_ret_60,fwd_ret_120\nAAPL,1000.123456789012345678901,0.1234567890123456789,0.097\nMSFT,42.000,0.333,\n')

    def test_raw_cache_hash_mismatch_stops_repair(self):
        module = load_script('relabel_market_history')
        with tempfile.TemporaryDirectory() as root:
            file = Path(root)/'bars_frozen.json';file.write_text('{}')
            with self.assertRaisesRegex(ValueError,'cache identity mismatch'):
                module.load_frozen_bars(root,{'QQQ'},{file.name:'wrong'})

    def test_bounded_repair_rebuilds_only_the_registered_120d_window(self):
        module = load_script('relabel_market_history')
        with tempfile.TemporaryDirectory() as root:
            root = Path(root);source = root/'source/study';source.mkdir(parents=True)
            cache = root/'cache';cache.mkdir()
            closed = pd.to_datetime(['2018-11-22','2018-12-05','2018-12-25','2019-01-01','2019-01-21','2019-02-18'],utc=True)
            days = pd.bdate_range('2018-09-04','2019-02-26',tz='UTC').difference(closed)
            rows = [dict(t=day.isoformat(),o=100,c=110,v=10) for day in days]
            raw = cache/'bars_frozen.json';raw.write_text(json.dumps(dict(AAPL=rows,QQQ=rows)))
            dataset = source/'dataset.csv'
            dataset.write_text('signal_date,symbol,price,fwd_ret_60,fwd_ret_120,label_end_120,qqq_return_120,qqq_label_end_120\n2018-08-31,AAPL,100.000,0.1234567890123456789,,,,\n')
            (source/'dataset.meta.json').write_text(json.dumps(dict(cache_hashes={raw.name:sha256_file(raw)})))
            (source/'dataset.splits.json').write_text(json.dumps({'events':{}}))
            (source/'success.json').write_text(json.dumps({'sha256':sha256_file(dataset)}))
            plan = root/'plan.json';plan.write_text(json.dumps(dict(cutoff='2019-02-26',studies={'study':dict(
                source_dataset_sha256=sha256_file(dataset),source_metadata_sha256=sha256_file(source/'dataset.meta.json'),
                source_splits_sha256=sha256_file(source/'dataset.splits.json'),windows=[dict(signal_date='2018-08-31',horizons=[120])])})))
            argv = ['relabel','--study','study','--source-root',str(root/'source'),'--output-root',str(root/'result'),
                    '--cache-dir',str(cache),'--cutoff','2019-02-26','--repair-plan',str(plan)]
            with patch.object(sys,'argv',argv): module.main()
            out = root/'result/study';repaired = pd.read_csv(out/'dataset.csv')
            self.assertAlmostEqual(repaired.fwd_ret_120.iloc[0],.097)
            self.assertEqual(repaired.label_end_120.iloc[0],'2019-02-26')
            self.assertIn('100.000,0.1234567890123456789,',(out/'dataset.csv').read_text())
            record = json.loads((out/'success.json').read_text())
            self.assertEqual(record['metadata_sha256'],sha256_file(out/'dataset.meta.json'))


if __name__ == '__main__': unittest.main()
