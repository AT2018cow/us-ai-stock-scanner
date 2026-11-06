"""Foreground, checkpoint-bound completion of the five follow-up review fixes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, '/root/scripts')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0, '/root/src')
from modal_selection_backtest import image, cache_volume, research_volume
from ai_value_scanner.research.provenance import sha256_file, validate_config_identity

PLAN = 'docs/review_followup_20261106/repair_plan.json'
PROTOCOL = 'docs/review_20261106/same_day_backtest/protocol.json'
CONFIG = 'configs/config.production.json'
STUDIES = ['sip_2016_2020_v1', 'sip_2021_2026_v1', 'sip_covid_weekly_v1', 'sip_bear_weekly_v1']
SCOPES = {'sip_monthly': STUDIES[:2], 'sip_covid_weekly': [STUDIES[2]], 'sip_bear_weekly': [STUDIES[3]]}
image = image.add_local_file(PLAN, '/root/'+PLAN, copy=True)
app = modal.App('selection-review-five-fixes')


def source_identity():
    files = sorted(Path('src').rglob('*.py')) + [Path(p) for p in [
        'scripts/relabel_market_history.py', 'scripts/evaluate_current_top15.py',
        'scripts/complete_selection_review.py', 'scripts/modal_selection_backtest.py',
        'scripts/modal_review_fixes.py', CONFIG, PLAN, PROTOCOL,
        'docs/review_20261106/same_day_backtest/supplement_protocol.json']]
    return {str(p): sha256_file(p) for p in files}


def verify_evaluation(out):
    manifest = json.loads((out/'manifest.json').read_text())
    validate_config_identity(manifest, CONFIG)
    if manifest['protocol_sha256'] != sha256_file(PROTOCOL):
        raise ValueError('evaluation protocol mismatch')
    for name, digest in {**manifest['sources'], **manifest['inputs']}.items():
        if sha256_file(name) != digest:
            raise ValueError('evaluation input/source mismatch: '+name)
    return manifest


def verify_attribution(out):
    manifest = json.loads((out/'manifest.json').read_text())
    validate_config_identity(manifest, CONFIG)
    if manifest['protocol_sha256'] != sha256_file('docs/review_20261106/same_day_backtest/supplement_protocol.json'):
        raise ValueError('attribution protocol mismatch')
    for name, digest in {**manifest['sources'], **manifest['inputs']}.items():
        if sha256_file(name) != digest:
            raise ValueError('attribution input/source mismatch: '+name)
    return manifest


@app.function(image=image, volumes={'/root/cache': cache_volume, '/root/research': research_volume},
              cpu=(1., 2.), memory=(4096, 12288), timeout=2*3600, max_containers=2)
def run_remote(stage, scope, run_id, spec):
    os.chdir('/root')
    research_volume.reload()
    if source_identity() != spec['sources']:
        raise ValueError('worker source/config/plan mismatch')
    base = Path('/root/research')/run_id
    base.mkdir(exist_ok=True)
    contract = base/'run_spec.json'
    if contract.exists() and json.loads(contract.read_text()) != spec:
        raise ValueError('run specification mismatch; use a new run id')
    contract.write_text(json.dumps(spec, indent=2, sort_keys=True)+'\n')
    research_volume.commit()
    if stage in ['repair', 'repair_smoke']:
        output = base/('label_smoke' if stage=='repair_smoke' else 'datasets')
        folder = output/scope
        if not folder.exists():
            cmd = ['python', 'scripts/relabel_market_history.py', '--study', scope,
                '--source-root', '/root/research/sip_migration_20261106_v1/datasets',
                '--output-root', str(output), '--cache-dir', '/root/cache/alpaca_sip_research',
                '--repair-plan', PLAN]
            if stage=='repair_smoke': cmd.append('--smoke')
            subprocess.run(cmd, check=True)
            research_volume.commit()
        success = json.loads((folder/'success.json').read_text())
        meta = json.loads((folder/'dataset.meta.json').read_text())
        source = json.loads(Path(PLAN).read_text())['studies'][scope]
        if success['sha256'] != sha256_file(folder/'dataset.csv') or success['metadata_sha256'] != sha256_file(folder/'dataset.meta.json'):
            raise ValueError('repaired checkpoint payload mismatch')
        if meta['repair_plan_sha256'] != sha256_file(PLAN) or meta['source_dataset_sha256'] != source['source_dataset_sha256']:
            raise ValueError('repaired checkpoint specification mismatch')
        for name, digest in meta['processors'].items():
            if sha256_file(name) != digest: raise ValueError('repair processor mismatch')
        if stage=='repair_smoke':
            import pandas as pd
            frame = pd.read_csv(folder/'dataset.csv')
            if len(frame)!=3 or not frame.label_end_120.eq('2019-02-26').all() or frame.fwd_ret_120.isna().any():
                raise ValueError('valid 120d label smoke failed')
        return dict(stage=stage, scope=scope, **success)
    if stage in ['evaluate', 'evaluate_smoke']:
        out = base/'evaluation_smoke' if stage=='evaluate_smoke' else base/'evaluations'/f'evaluation_{scope}_v2'
        if not out.exists():
            cmd = ['python', 'scripts/evaluate_current_top15.py', '--output', str(out), '--code-sha', spec['base_git_sha']]
            for study in ([STUDIES[0]] if stage=='evaluate_smoke' else SCOPES[scope]):
                cmd += ['--dataset', str(base/('label_smoke' if stage=='evaluate_smoke' else 'datasets')/study/'dataset.csv')]
            subprocess.run(cmd, check=True)
            research_volume.commit()
        manifest = verify_evaluation(out)
        return dict(stage=stage, scope=scope, dates=manifest['n_dates'], candidate_adopted=manifest['candidate_adopted'])
    if stage in ['attribute', 'attribute_smoke']:
        out = base/'attribution_smoke' if stage=='attribute_smoke' else base/'attribution'/scope
        if not out.exists():
            cmd = ['python', 'scripts/complete_selection_review.py', '--scope', scope, '--output', str(out),
                   '--frozen-root', str(base/'datasets'), '--evaluation-root', str(base/'evaluations')]
            if stage=='attribute_smoke': cmd.append('--smoke')
            subprocess.run(cmd, check=True)
            research_volume.commit()
        manifest = verify_attribution(out)
        return dict(stage=stage, scope=scope, elapsed_seconds=manifest['elapsed_seconds'])
    if stage=='resume_check':
        results = {}
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp)/'changed_config.json'
            payload = json.loads(Path(CONFIG).read_text())
            payload['min_dollar_volume'] += 1
            changed.write_text(json.dumps(payload))
            for name in SCOPES:
                manifest = verify_evaluation(base/'evaluations'/f'evaluation_{name}_v2')
                try:
                    validate_config_identity(manifest, changed)
                except ValueError:
                    results[name] = 'same configuration accepted; changed threshold rejected'
                else: raise ValueError('changed configuration was accepted')
        (base/'checkpoint_guard_smoke.json').write_text(json.dumps(results, indent=2)+'\n')
        research_volume.commit()
        return dict(stage=stage, checks=results)
    raise ValueError('unknown stage')


@app.local_entrypoint()
def main(stage: str='repair', run_id: str='review_followup_20261106_v1'):
    if os.environ.get('MODAL_PROFILE')!='infi': raise ValueError('explicit infi profile required')
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in run_id):
        raise ValueError('invalid run id')
    spec = dict(base_git_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                sources=source_identity(), work='five follow-up correctness fixes; bounded frozen label repair; no tuning')
    if stage=='repair':
        print(run_remote.remote('repair_smoke', STUDIES[0], run_id, spec), flush=True)
        for result in run_remote.starmap([('repair', name, run_id, spec) for name in STUDIES]): print(result, flush=True)
    elif stage in ['evaluate', 'attribute']:
        print(run_remote.remote(stage+'_smoke', 'sip_monthly', run_id, spec), flush=True)
        for result in run_remote.starmap([(stage, name, run_id, spec) for name in SCOPES]): print(result, flush=True)
        if stage=='evaluate': print(run_remote.remote('resume_check', '', run_id, spec), flush=True)
    else: raise ValueError('unknown stage')
