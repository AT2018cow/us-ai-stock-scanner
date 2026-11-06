"""Failure injection at cache and immutable publication boundaries."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import ai_value_scanner.reporting.snapshot as snapshots
from ai_value_scanner import scanner
from test_code_review_repair_r04_r08_contract_e2e import _write_pipeline_snapshot
from test_parsed_cache_periodic_gate import _seed, FakeSec, CIK


class CacheVersionValidation(unittest.TestCase):
    def test_old_arithmetic_cache_is_invalidated_even_with_matching_raw_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); config=scanner.ScanConfig(cache_dir=tmp)
            _seed(root,config)
            sec=FakeSec()
            self.assertIsNotNone(scanner.load_valid_parsed_fundamental_cache(sec,'TEST',CIK,config))
            target=root/f'parsed_fund_{CIK}.json'
            payload=json.loads(target.read_text());payload['_cache_meta']['v']=9
            target.write_text(json.dumps(payload))
            self.assertIsNone(scanner.load_valid_parsed_fundamental_cache(sec,'TEST',CIK,config))


class AtomicSnapshotValidation(unittest.TestCase):
    def test_render_failure_leaves_no_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(snapshots,'render_detailed_report',side_effect=OSError('injected failure')):
                with self.assertRaises(OSError): _write_pipeline_snapshot(root)
            self.assertFalse((root/'2026-10-09/risk_off').exists())
            self.assertFalse(list(root.glob('**/*.tmp')))

    def test_concurrent_writers_publish_one_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); barrier=threading.Barrier(2)
            render=snapshots.render_action_list
            local=threading.local()
            def synchronized_render(*args,**kwargs):
                if not getattr(local,'arrived',False):
                    local.arrived=True;barrier.wait(timeout=10)
                return render(*args,**kwargs)
            def write():
                try:
                    _write_pipeline_snapshot(root)
                    return 'published'
                except OSError:
                    return 'exists'
            with patch.object(snapshots,'render_action_list',side_effect=synchronized_render):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(lambda _:write(),range(2)))
            self.assertEqual(results.count('published'),1)
            from scripts.validate_mvp_snapshot import validate_snapshot
            result=validate_snapshot(root/'2026-10-09/risk_off')
            self.assertTrue(result['ok'],result['errors'])
            self.assertFalse(list(root.glob('**/*.tmp')))

    def test_concurrent_pointer_publication_never_moves_backwards(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);decisions,_=_write_pipeline_snapshot(root)
            newer=tuple(replace(d,decision_date='2026-10-12') for d in decisions)
            snapshots.write_decision_snapshot(output_root=root,strategy_style='risk_off',
                decisions=newer,daily_attention=newer,weekly_attention=newer,
                generated_at_utc='2026-10-12T22:00:00Z',decision_date='2026-10-12',
                config_fingerprint='synthetic-audit',policy_version='v2',layout_version='v2')
            # Pause the old writer on entering the publication lock, publish the
            # newer snapshot, then let the old writer re-check under the lock.
            entered=threading.Event();release=threading.Event()
            flock=scanner.fcntl.flock
            def delayed_lock(fd,operation):
                if threading.current_thread().name == 'older':
                    entered.set()
                    if not release.wait(5): raise TimeoutError('test barrier')
                return flock(fd,operation)
            failures=[]
            def old_write():
                try: scanner.write_latest_decision_pointer(root,decision_date='2026-10-09',strategy_style='risk_off')
                except ValueError: failures.append('rejected regression')
            with patch.object(scanner.fcntl,'flock',side_effect=delayed_lock):
                thread=threading.Thread(target=old_write,name='older');thread.start()
                self.assertTrue(entered.wait(5))
                scanner.write_latest_decision_pointer(root,decision_date='2026-10-12',strategy_style='risk_off')
                release.set();thread.join(5)
            self.assertEqual(failures,['rejected regression'])
            self.assertEqual(json.loads((root/'latest_risk_off.json').read_text())['decision_date'],'2026-10-12')

    def test_pointer_replace_failure_preserves_old_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_write_pipeline_snapshot(root)
            path=scanner.write_latest_decision_pointer(root,decision_date='2026-10-09',strategy_style='risk_off')
            before=path.read_bytes()
            with patch.object(scanner.os,'replace',side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    scanner.write_latest_decision_pointer(root,decision_date='2026-10-09',strategy_style='risk_off')
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(list(root.glob('*.tmp')))


class ForwardLabelValidation(unittest.TestCase):
    def test_future_relisting_cannot_supply_historical_entry(self):
        import pandas as pd
        from ai_value_scanner.evaluation.backtest import forward_return_with_exit
        frame=pd.DataFrame({'open':[10]*21,'close':[12]*21},
                           index=pd.bdate_range('2025-01-01',periods=21,tz='UTC'))
        self.assertEqual(forward_return_with_exit(frame,'2023-01-31',20,.003),(None,None))

    def test_long_suspension_and_nonfinite_prices_cannot_form_labels(self):
        import pandas as pd
        from ai_value_scanner.evaluation.backtest import forward_return_with_exit
        index=pd.DatetimeIndex(pd.to_datetime(['2024-01-02','2025-01-02'],utc=True))
        frame=pd.DataFrame({'open':[10,10],'close':[12,12]},index=index)
        self.assertEqual(forward_return_with_exit(frame,'2024-01-01',2,.003),(None,None))
        frame.index=pd.bdate_range('2024-01-02',periods=2,tz='UTC')
        for column in ('open','close'):
            bad=frame.copy();bad[column]=float('nan')
            self.assertEqual(forward_return_with_exit(bad,'2024-01-01',2,.003),(None,None))


if __name__=='__main__': unittest.main()
