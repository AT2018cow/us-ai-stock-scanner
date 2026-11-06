"""Foreground SIP migration: frozen-cache relabel, smoke, then derived evidence."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
import modal
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,'/root/scripts')
from modal_selection_backtest import image,cache_volume,research_volume
from modal_baseline_executor import _modal_secrets
image=image.add_local_dir('outputs/decisions/2026-11-04/production','/root/previous_prod/2026-11-04/production',copy=True)

app=modal.App('sip-eod-calendar-migration')
STUDIES=['sip_2016_2020_v1','sip_2021_2026_v1','sip_covid_weekly_v1','sip_bear_weekly_v1']


@app.function(image=image,volumes={'/root/cache':cache_volume,'/root/research':research_volume},
              secrets=_modal_secrets(),cpu=(1.,2.),memory=(4096,12288),timeout=2*3600,max_containers=2)
def run_remote(stage,scope):
    os.chdir('/root');base=Path('/root/research/sip_migration_20261106_v1');base.mkdir(exist_ok=True)
    if stage in ['smoke','relabel']:
        cmd=['python','scripts/relabel_market_history.py','--study',scope,
             '--source-root','/root/research/selection_review_20261106','--output-root',str(base/('smoke' if stage=='smoke' else 'datasets')),
             '--cache-dir','/root/cache/alpaca_sip_research']
        if stage=='smoke':cmd+=['--smoke']
        subprocess.run(cmd,check=True);research_volume.commit()
        return dict(stage=stage,scope=scope,path=str(base),status='complete')
    datasets={'sip_monthly':STUDIES[:2],'sip_covid_weekly':[STUDIES[2]],'sip_bear_weekly':[STUDIES[3]]}
    if stage=='official_validate':
        snapshot=base/'official_decisions/2026-11-05/production'
        records=[json.loads(line) for line in (snapshot/'decisions.jsonl').read_text().splitlines() if line.strip()]
        if not records or any(r.get('provenance',{}).get('market_data_feed')!='sip' or r.get('provenance',{}).get('market_data_mode')!='sip_eod' for r in records):
            raise ValueError('completed official checkpoint is absent or has a different feed contract')
        subprocess.run(['python','scripts/validate_mvp_snapshot.py',str(snapshot)],
                       env={**os.environ,'PYTHONPATH':'/root/src'},check=True)
        research_volume.commit();cache_volume.commit()
        return dict(stage=stage,status='complete',snapshot=str(snapshot),decisions=len(records),reused=True)
    if stage in ['evaluate','evaluate_smoke']:
        out=base/'evaluation_smoke' if stage=='evaluate_smoke' else base/'evaluations'/('evaluation_'+scope+'_v2')
        cmd=['python','scripts/evaluate_current_top15.py','--output',str(out),'--code-sha','830702b73749c92be20f02a3463669f1b8e7dbd8']
        for study in (['sip_2021_2026_v1'] if stage=='evaluate_smoke' else datasets[scope]):
            cmd+=['--dataset',str(base/('smoke' if stage=='evaluate_smoke' else 'datasets')/study/'dataset.csv')]
        subprocess.run(cmd,check=True);research_volume.commit()
        return dict(stage=stage,scope=scope,status='complete')
    if stage in ['attribute','attribute_smoke']:
        out=base/'attribution_smoke' if stage=='attribute_smoke' else base/'attribution'/scope
        cmd=['python','scripts/complete_selection_review.py','--scope',scope,'--output',str(out),
             '--frozen-root',str(base/'datasets'),'--evaluation-root',str(base/'evaluations')]
        if stage=='attribute_smoke':cmd+=['--smoke']
        subprocess.run(cmd,check=True)
        research_volume.commit();return dict(stage=stage,scope=scope,status='complete')
    if stage=='official':
        import shutil
        sys.path.insert(0,'/root/src')
        from ai_value_scanner.config import load_config
        from ai_value_scanner.scanner import run_scan_with_status
        cfg=load_config('configs/config.production.json');cfg.output_dir=str(base/'official_outputs')
        previous=base/'official_decisions/2026-11-04/production'
        if not previous.exists():
            previous.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree('/root/previous_prod/2026-11-04/production',previous)
        result=run_scan_with_status(cfg,scan_config_path='configs/config.production.json',
                                    decision_output_root=str(base/'official_decisions'),allow_existing_decision_snapshot=False)
        if result.core_failed:raise RuntimeError(result.decision_output_error or result.latest_pointer_error)
        research_volume.commit();cache_volume.commit()
        subprocess.run(['python','scripts/validate_mvp_snapshot.py',str(result.decision_snapshot_root)],
                       env={**os.environ,'PYTHONPATH':'/root/src'},check=True)
        return dict(stage=stage,status='complete',snapshot=str(result.decision_snapshot_root),legacy_output=str(result.output_path))
    raise ValueError(stage)


@app.local_entrypoint()
def main(stage: str='relabel'):
    if os.environ.get('MODAL_PROFILE')!='infi':raise ValueError('infi profile required')
    if stage=='relabel':
        print(run_remote.remote('smoke','sip_2021_2026_v1'),flush=True)
        for r in run_remote.starmap([('relabel',s) for s in STUDIES]):print(r,flush=True)
    elif stage in ['evaluate','attribute']:
        print(run_remote.remote(stage+'_smoke','sip_monthly'),flush=True)
        for r in run_remote.starmap([(stage,s) for s in ['sip_monthly','sip_covid_weekly','sip_bear_weekly']]):print(r,flush=True)
    elif stage in ['official','official_validate']:print(run_remote.remote(stage,'production'),flush=True)
    else:raise ValueError('unknown stage')
