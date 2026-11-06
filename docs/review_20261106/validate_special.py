import hashlib,io,json,time,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
GROUPS={
 'sec_ttm_pit':['test_ttm_quarter_reconstruction','test_cumulative_cashflow_reconstruction','test_fundamental_reconstruction','test_fundamental_adapter_parity','test_capex_tag_fallbacks','test_identity_verification','test_share_count_integrity','test_nonoperating_gain_defense'],
 'corporate_actions_prices':['test_split_adjustment','test_backtest_splits_unpriced','test_corporate_action_label_integrity','test_historical_valuation_percentile','test_price_feature_core','test_review_20261106_repairs','test_review_special_validation.ForwardLabelValidation'],
 'cache_invalidation':['test_identity_provenance','test_companyfacts_cache_miss','test_parsed_cache_periodic_gate','test_sec_periodic_pending_hardening','test_daily_cron_scan_and_ttl','test_review_special_validation.CacheVersionValidation'],
 'snapshots_publication':['test_code_review_repair_r04_r08_contract_e2e','test_code_review_repair_r05_validator','test_integrated_mvp_outputs','test_io_safety','test_review_special_validation.AtomicSnapshotValidation'],
}
import sys
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
results={}
for group,names in GROUPS.items():
 start=time.monotonic();suite=unittest.TestLoader().loadTestsFromNames(names)
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
 results[group]=dict(tests=result.testsRun,passed=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),elapsed_seconds=round(time.monotonic()-start,3),test_modules=names)
 if not result.wasSuccessful(): print(stream.getvalue())
from scripts.validate_mvp_snapshot import validate_snapshot
snapshots=[]
for p in sorted((ROOT/'outputs/decisions').glob('????-??-??/*/run_manifest.json')):
 result=validate_snapshot(p.parent)
 snapshots.append(dict(snapshot=str(p.parent.relative_to(ROOT/'outputs/decisions')),ok=result['ok'],warnings=result.get('warnings',[]),errors=result['errors']))
results['existing_snapshots']=snapshots
# Local parsed-cache inputs, read only. Old arithmetic caches are never reused by v10.
from collections import Counter
counts=Counter();affected=[]
for p in sorted((ROOT/'cache').glob('parsed_fund_*.json')):
 try: data=json.loads(p.read_text())
 except (ValueError,OSError):counts['unreadable']+=1;continue
 counts['files']+=1
 counts['cache_version_'+str(data.get('_cache_meta',{}).get('v'))]+=1
 nd=data.get('net_debt'); eb=data.get('adjusted_ebitda');ratio=data.get('net_debt_to_ebitda')
 if isinstance(nd,(float,int)) and isinstance(eb,(float,int)) and nd>0 and eb<=0:
  counts['positive_net_debt_nonpositive_ebitda']+=1
  if isinstance(ratio,(float,int)) and ratio<0: counts['old_negative_ratio']+=1
 for key in ('net_debt_to_ebitda','interest_coverage','current_ratio','ocf_to_net_income','accrual_ratio'):
  value=data.get(key)
  import math
  if isinstance(value,(float,int)) and not math.isfinite(value):counts['nonfinite_'+key]+=1
results['local_parsed_cache_inventory']=dict(counts)
results['validation_scope']='Offline synthetic contract tests and local immutable snapshot/cache inventory; no provider refetch or full raw SEC population reparse.'
results['base_commit']='830702b73749c92be20f02a3463669f1b8e7dbd8'
results['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src/ai_value_scanner').rglob('*.py'))}
results['test_source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'tests').glob('test_*.py'))}
results['harness_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
out=ROOT/'outputs/review_20261106/special_validation.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:v for k,v in results.items() if k in GROUPS or k=='local_parsed_cache_inventory'},indent=2))
if not all(results[g]['passed'] for g in GROUPS) or not all(s['ok'] for s in snapshots):raise SystemExit(1)
