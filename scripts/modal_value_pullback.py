"""Foreground infi execution of the approved value/pullback study."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import modal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,'/root/src')
from ai_value_scanner.research.provenance import sha256_file

PLAN='docs/agent_specs/value_and_pullback_optimization_spec.md'
PROTOCOL='docs/value_pullback_optimization_20261106/protocol.json'
volume=modal.Volume.from_name('ai-scanner-research',create_if_missing=False)
image=(modal.Image.debian_slim(python_version='3.12')
       .pip_install('pandas==2.3.0','numpy==2.0.2','scipy==1.15.3','requests==2.32.3','python-dotenv==1.0.1')
       .add_local_dir('src','/root/src',copy=True,ignore=['**/__pycache__/**','**/*.pyc'])
       .add_local_dir('scripts','/root/scripts',copy=True,ignore=['**/__pycache__/**','**/*.pyc'])
       .add_local_file('configs/config.production.json','/root/configs/config.production.json',copy=True)
       .add_local_file(PLAN,'/root/'+PLAN,copy=True)
       .add_local_file(PROTOCOL,'/root/'+PROTOCOL,copy=True))
app=modal.App('value-pullback-v4')


def sources():
    files=sorted(Path('src').rglob('*.py'))+[Path(p) for p in [PLAN,PROTOCOL,
        'configs/config.production.json','scripts/evaluate_value_pullback_directions.py',
        'scripts/modal_value_pullback.py']]
    return {str(p):sha256_file(p) for p in files}


@app.function(image=image,volumes={'/root/research':volume},cpu=(1.,2.),
              memory=(4096,8192),timeout=7200,max_containers=2)
def run(stage,scope,run_id,identity,names,smoke=False):
    os.chdir('/root');volume.reload()
    if sources()!=identity['sources']:raise ValueError('worker source/protocol/config mismatch')
    base=Path('/root/research')/run_id
    if not base.exists():base.mkdir(parents=True)
    contract=base/'run_spec.json'
    if contract.exists() and json.loads(contract.read_text())!=identity:raise ValueError('run specification mismatch')
    contract.write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n');volume.commit()
    cmd=['python','scripts/evaluate_value_pullback_directions.py','--stage',stage,
         '--source-root','/root/research/review_followup_20261106_v1','--output-root',str(base),
         '--scope',scope,'--identity',str(contract),'--names',names]
    if smoke:cmd.append('--smoke')
    subprocess.run(cmd,check=True)
    volume.commit()
    directory=base/({'prepare':'prepared','evaluate':'evaluations','robustness':'robustness'}[stage])/scope
    m=json.loads((directory/'manifest.json').read_text())
    return {k:v for k,v in m.items() if k not in ('identity','files')}


@app.function(image=image,volumes={'/root/research':volume},cpu=1,memory=2048,timeout=600,max_containers=1)
def download(run_id,identity):
    os.chdir('/root');volume.reload();base=Path('/root/research')/run_id
    if json.loads((base/'run_spec.json').read_text())!=identity:raise ValueError('download identity mismatch')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(base.rglob('*')):
            if path.is_file() and path.suffix!='.pkl':archive.write(path,str(path.relative_to(base)))
    return output.getvalue()


@app.local_entrypoint()
def main(stage:str='smoke',run_id:str='value_pullback_20261106_v1',names:str='D0,A,B'):
    if os.environ.get('MODAL_PROFILE')!='infi':raise ValueError('explicit infi profile required')
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in run_id):raise ValueError('invalid run id')
    protocol=json.loads(Path(PROTOCOL).read_text())
    if names.split(',')!=protocol['variants']:raise ValueError('variant authorization differs from frozen protocol')
    identity=dict(base_git_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  sources=sources(),protocol=protocol)
    if stage=='smoke':
        smoke_id=run_id+'_smoke'
        print(run.remote('prepare','monthly',smoke_id,identity,names,True),flush=True)
        print(run.remote('evaluate','monthly',smoke_id,identity,names,True),flush=True)
        marker=Path('outputs/value_pullback_20261106/smoke_pass.json')
        marker.parent.mkdir(parents=True,exist_ok=True);marker.write_text(json.dumps(identity,indent=2)+'\n')
    elif stage in ('prepare','evaluate','robustness'):
        marker=Path('outputs/value_pullback_20261106/smoke_pass.json')
        if not marker.exists() or json.loads(marker.read_text())!=identity:raise ValueError('matching smoke pass required')
        scopes=['monthly'] if stage=='robustness' else ['monthly','covid','bear']
        if stage=='evaluate':
            # All P0 scopes must be verified before any candidate result is computed.
            for scope in scopes:print(run.remote('prepare',scope,run_id,identity,names),flush=True)
        for result in run.starmap([(stage,scope,run_id,identity,names) for scope in scopes]):print(result,flush=True)
    elif stage=='download':
        payload=download.remote(run_id,identity)
        target=Path('outputs/value_pullback_20261106')/run_id
        if target.exists():raise ValueError('download target already exists')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                if name.startswith('/') or '..' in Path(name).parts:raise ValueError('unsafe archive path')
            archive.extractall(target)
        print(json.dumps(dict(downloaded=str(target),bytes=len(payload))),flush=True)
    else:raise ValueError('unknown stage')
