"""Foreground, version-bound extraction for the approved cross-cycle study."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import modal
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/root/scripts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0, '/root/src')
from modal_baseline_executor import cache_volume, research_volume, _modal_secrets
from ai_value_scanner.research.provenance import validate_config_identity

# Exclude interpreter caches: local validation must not mutate an image input.
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("pandas==2.3.0", "numpy==2.0.2", "scipy==1.15.3",
                      "requests==2.32.3", "python-dotenv==1.0.1", "urllib3==2.2.3")
         .add_local_dir("src", "/root/src", copy=True, ignore=["**/__pycache__/**", "**/*.pyc"])
         .add_local_dir("scripts", "/root/scripts", copy=True, ignore=["**/__pycache__/**", "**/*.pyc"])
         .add_local_dir("configs", "/root/configs", copy=True)
         .add_local_file("docs/review_20261106/same_day_backtest/protocol.json",
                         "/root/docs/review_20261106/same_day_backtest/protocol.json",copy=True)
         .add_local_file("docs/review_20261106/same_day_backtest/supplement_protocol.json",
                         "/root/docs/review_20261106/same_day_backtest/supplement_protocol.json",copy=True)
         .add_local_dir("data", "/root/data", copy=True))

app = modal.App("selection-cross-cycle-review")


def source_identity() -> dict[str, str]:
    files = sorted(Path("src").rglob("*.py")) + [
        Path("scripts/extract_weight_dataset.py"), Path("scripts/modal_selection_backtest.py"),
        Path("scripts/modal_baseline_executor.py"),
        Path("configs/config.risk_off.json"), Path("data/ai_watchlist.csv"),
    ] + sorted(Path("data/watchlist_history").glob("*.csv"))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


@app.function(image=image, volumes={"/root/cache": cache_volume, "/root/research": research_volume},
              secrets=_modal_secrets(), cpu=(1.0, 2.0), memory=(8192, 16384), timeout=12*3600,
              max_containers=2)
def extract_remote(spec: dict) -> dict:
    os.chdir("/root")
    for name, digest in spec["sources"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"image source mismatch: {name}")
    root = Path("/root/research/selection_review_20261106") / spec["run_id"]
    root.mkdir(parents=True, exist_ok=True)
    contract = root / "spec.json"
    if contract.exists() and json.loads(contract.read_text()) != spec:
        raise ValueError("run specification mismatch; choose a new run id")
    contract.write_text(json.dumps(spec, indent=2, sort_keys=True)+"\n")
    research_volume.commit()
    output = root / "dataset.csv"
    if not (root / "success.json").exists():
        cmd = ["python", "/root/scripts/extract_weight_dataset.py",
               "--dataset-kind", "company_quality", "--scan-config", "/root/configs/config.risk_off.json",
               "--start-date", spec["start"], "--end-date", spec["end"],
               "--rebalance-frequency", spec["frequency"], "--horizons", "20,60,120,252",
               "--market-data-feed", spec["feed"],
               "--bars-start-date", "2014-11-07",
               "--replay-max-symbols", "800", "--theme-source", "zero",
               "--output", str(output)]
        if spec.get('smoke'):
            cmd += ['--symbols','AAPL,MSFT,NVDA','--signal-dates','2016-11-30,2020-03-31,2022-06-30']
        result = subprocess.run(cmd, check=False)
        cache_volume.commit()
        research_volume.commit()
        if result.returncode:
            raise RuntimeError(f"extraction failed: {result.returncode}")
        summary = {"path": str(output.relative_to('/root/research')),
                   "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
        if spec.get('smoke'):
            import pandas as pd
            frame=pd.read_csv(output)
            summary.update(n_rows=len(frame),n_dates=frame.signal_date.nunique())
            if summary['n_dates']!=3 or summary['n_rows']<6 or frame.qqq_return_60.isna().any():
                raise ValueError('smoke failed: missing dates, rows, or mature benchmark labels')
        (root / "success.json").write_text(json.dumps(summary)+"\n")
        research_volume.commit()
    return json.loads((root / "success.json").read_text())


@app.function(image=image, volumes={"/root/research": research_volume},
              cpu=(1.0,2.0), memory=(4096,8192), timeout=2*3600,max_containers=2)
def evaluate_remote(payload: dict) -> dict:
    os.chdir('/root')
    root=Path('/root/research/selection_review_20261106')
    version=payload.get('study_version','v1')
    scopes={'smoke':[f'infi_smoke_{version}'], 'sip_monthly':[f'sip_2016_2020_{version}',f'sip_2021_2026_{version}'],
            'sip_covid_weekly':[f'sip_covid_weekly_{version}'],
            'sip_bear_weekly':[f'sip_bear_weekly_{version}'],
            'iex_monthly':[f'iex_2021_2026_{version}']}
    scope=payload['scope']
    cmd=['python','/root/scripts/evaluate_current_top15.py','--code-sha',payload['code_sha']]
    for study in scopes[scope]:
        base=root/study
        success=json.loads((base/'success.json').read_text())
        dataset=base/'dataset.csv'
        if hashlib.sha256(dataset.read_bytes()).hexdigest()!=success['sha256']:
            raise ValueError('dataset identity mismatch')
        cmd+=['--dataset',str(dataset)]
    suffix='' if version=='v1' else '_'+version
    out=root/('evaluation_'+scope+suffix+'_'+payload.get('evaluation_version','v2'))
    if not out.exists():
        subprocess.run(cmd+['--output',str(out)],check=True)
        research_volume.commit()
    manifest=json.loads((out/'manifest.json').read_text())
    validate_config_identity(manifest,'configs/config.production.json')
    if manifest['protocol_sha256'] != hashlib.sha256(Path('docs/review_20261106/same_day_backtest/protocol.json').read_bytes()).hexdigest():
        raise ValueError('evaluation protocol mismatch')
    for name,digest in manifest['sources'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
            raise ValueError('evaluation source mismatch; use a new result directory')
    for name,digest in manifest['inputs'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
            raise ValueError('evaluation input mismatch')
    return dict(scope=scope,path=str(out.relative_to('/root/research')),n_dates=manifest['n_dates'],paired=manifest['paired'])


@app.function(image=image,volumes={'/root/research':research_volume},cpu=(1.,2.),
              memory=(4096,8192),timeout=2*3600,max_containers=2)
def supplement_remote(scope: str, version: str = 'v1') -> dict:
    os.chdir('/root')
    root=Path('/root/research/selection_review_20261106')
    out=root/('completion_'+scope+'_'+version)
    if out.exists():
        manifest=json.loads((out/'manifest.json').read_text())
        validate_config_identity(manifest,'configs/config.production.json')
        for name,digest in {**manifest['inputs'],**manifest['sources']}.items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                raise ValueError('supplement identity mismatch; use a new completion version')
        protocol=Path('docs/review_20261106/same_day_backtest/supplement_protocol.json')
        if hashlib.sha256(protocol.read_bytes()).hexdigest()!=manifest['protocol_sha256'] or manifest['tolerance']!=.01:
            raise ValueError('supplement protocol mismatch')
        return dict(scope=scope,path=str(out.relative_to('/root/research')),elapsed_seconds=manifest['elapsed_seconds'],smoke=manifest['smoke'],reused=True)
    cmd=['python','/root/scripts/complete_selection_review.py','--output',str(out),
         '--frozen-root',str(root),'--evaluation-root',str(root),'--tolerance','0.01']
    cmd+=['--smoke'] if scope=='smoke' else ['--scope',scope]
    subprocess.run(cmd,check=True)
    research_volume.commit()
    manifest=json.loads((out/'manifest.json').read_text())
    validate_config_identity(manifest,'configs/config.production.json')
    return dict(scope=scope,path=str(out.relative_to('/root/research')),elapsed_seconds=manifest['elapsed_seconds'],smoke=manifest['smoke'])


@app.local_entrypoint()
def main(run_id: str = "monthly_v1", start: str = "2016-01-01",
         end: str = "2026-10-31", frequency: str = "monthly", feed: str = "sip", stage: str = "smoke",
         evaluation_scope: str = "all", study_version: str = "v1", evaluation_version: str = "v2",
         completion_version: str = 'v1'):
    if os.environ.get("MODAL_PROFILE") != "infi":
        raise ValueError("MODAL_PROFILE must explicitly be infi (user override)")
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in run_id):
        raise ValueError("invalid run id")
    for token in (study_version,evaluation_version,completion_version):
        if not token or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in token):
            raise ValueError('invalid study/evaluation version')
    if frequency not in {"monthly", "weekly"}:
        raise ValueError("invalid frequency")
    if feed not in {"iex", "sip"}: raise ValueError("invalid feed")
    spec = dict(run_id=run_id, start=start, end=end, frequency=frequency, feed=feed, sources=source_identity(),
                purpose="current feature repair + missing pre-2022 cross-cycle history",
                universe="archived snapshot or union approximation, not historical ETF reconstruction")
    if stage=='smoke':
        spec.update(run_id='infi_smoke_'+study_version,smoke=True,start='2016-01-01',end='2022-12-31',feed='sip')
        print(json.dumps(extract_remote.remote(spec),sort_keys=True))
    elif stage=='full':
        marker=Path('outputs/review_20261106')/('infi_smoke_pass.json' if study_version=='v1' else f'infi_smoke_{study_version}_pass.json')
        if not marker.exists(): raise ValueError('local smoke pass record required before long tasks')
        smoke=json.loads(marker.read_text())
        if smoke.get('n_dates')!=3 or smoke.get('n_rows',0)<6: raise ValueError('invalid smoke record')
        if smoke.get('path')!=f'selection_review_20261106/infi_smoke_{study_version}/dataset.csv':
            raise ValueError('smoke identity differs from requested study version')
        specs=[]
        for name,begin,finish,freq,market_feed in [
            ('sip_2016_2020','2016-01-01','2020-12-31','monthly','sip'),
            ('sip_2021_2026','2021-01-01','2026-10-31','monthly','sip'),
            ('sip_covid_weekly','2020-02-01','2020-06-30','weekly','sip'),
            ('sip_bear_weekly','2022-01-01','2022-12-31','weekly','sip'),
            ('iex_2021_2026','2021-01-01','2026-10-31','monthly','iex')]:
            specs.append(dict(spec,run_id=name+'_'+study_version,start=begin,end=finish,frequency=freq,feed=market_feed))
        for result in extract_remote.map(specs): print(json.dumps(result,sort_keys=True),flush=True)
    elif stage=='evaluate':
        code_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        identity=dict(code_sha=code_sha,study_version=study_version,evaluation_version=evaluation_version)
        smoke_result=evaluate_remote.remote(dict(scope='smoke',**identity))
        if smoke_result['n_dates']!=3: raise ValueError('remote evaluator smoke failed')
        print(json.dumps(dict(evaluator_smoke='PASS',**smoke_result),sort_keys=True),flush=True)
        scopes=['sip_monthly','sip_covid_weekly','sip_bear_weekly','iex_monthly']
        if evaluation_scope!='all':
            if evaluation_scope not in scopes: raise ValueError('invalid evaluation scope')
            scopes=[evaluation_scope]
        payloads=[dict(scope=s,**identity) for s in scopes]
        for result in evaluate_remote.map(payloads): print(json.dumps(result,sort_keys=True),flush=True)
    elif stage=='complete':
        smoke=supplement_remote.remote('smoke',completion_version)
        if not smoke['smoke']:raise ValueError('supplement smoke not passed')
        print(json.dumps(smoke),flush=True)
        args=[(scope,completion_version) for scope in ['sip_monthly','iex_monthly','sip_covid_weekly','sip_bear_weekly']]
        for result in supplement_remote.starmap(args):
            print(json.dumps(result),flush=True)
    else: raise ValueError('stage must be smoke, full, evaluate or complete')
