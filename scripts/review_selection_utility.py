#!/usr/bin/env python3
"""Offline review metrics and Entry increment diagnostics; writes a new evidence dir."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
import pandas as pd
from ai_value_scanner.research.review_utility import AttentionObservation, attention_utility, evaluate_entry_increment
from scripts.validate_mvp_snapshot import validate_snapshot


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    sub = parser.add_subparsers(dest='mode', required=True)
    att = sub.add_parser('attention')
    att.add_argument('--snapshots',type=Path,default=Path('outputs/decisions'))
    att.add_argument('--style',default='production')
    att.add_argument('--reviews',type=Path)
    entry = sub.add_parser('entry')
    entry.add_argument('--dataset',required=True,type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('output must be a new directory to preserve review evidence')
    # Never write diagnostics into the immutable decision history.
    if (ROOT/'outputs/decisions').resolve() in args.output.resolve().parents:
        parser.error('output cannot be inside immutable snapshots')
    files = {}; outputs = {}; metadata = {}
    if args.mode == 'attention':
        observations = []
        validation_warnings = {}
        for manifest in sorted(args.snapshots.glob('????-??-??/'+args.style+'/run_manifest.json')):
            result = validate_snapshot(manifest.parent)
            if not result['ok']:
                raise ValueError(f'invalid snapshot {manifest.parent.name}: {result["errors"]}')
            if result.get('warnings'):
                validation_warnings[str(manifest.relative_to(args.snapshots))] = result['warnings']
            raw = json.loads(manifest.read_text())
            decisions_path = manifest.with_name('decisions.jsonl')
            records = [json.loads(line) for line in decisions_path.read_text().splitlines() if line.strip()]
            observations.append(AttentionObservation(raw['decision_date'],tuple(raw['daily_symbols']),{r['symbol']:r['action_state'] for r in records}))
            files[str(manifest.relative_to(args.snapshots))] = sha(manifest)
            files[str(decisions_path.relative_to(args.snapshots))] = sha(decisions_path)
        if not observations: raise ValueError('no matching snapshots')
        reviews = pd.read_csv(args.reviews,dtype={'symbol':str,'decision_date':str}) if args.reviews else None
        if args.reviews: files[args.reviews.name] = sha(args.reviews)
        events,weekly,reasons = attention_utility(observations,reviews)
        outputs.update({'attention_events.csv':events,'weekly_utility.csv':weekly,'rejection_reasons.csv':reasons})
        outputs['human_review_template.csv'] = pd.DataFrame(columns=['decision_date','symbol','review_status','review_minutes','rejection_reason'])
        metadata = dict(evidence_class='observed_snapshot_diagnostic',style=args.style,n_snapshots=len(observations),
                        first_date=observations[0].decision_date,last_date=observations[-1].decision_date,
                        n_human_reviews=int(events.review_status.ne('unreviewed').sum()),
                        snapshot_validation_warnings=validation_warnings,
                        notes=['First observed snapshot has unknown new/repeated status.',
                               'Failed upgrade means a worse Action within five subsequent observed snapshots; incomplete follow-up is censored.',
                               'Missing snapshots are not inferred; this is observed cadence, not guaranteed trading-day persistence.',
                               'Review minutes and rejection reasons require actual human logs.'])
    else:
        dataset = pd.read_csv(args.dataset, low_memory=False)
        paired,summary,concentration,metadata = evaluate_entry_increment(dataset)
        files[args.dataset.name] = sha(args.dataset)
        meta = args.dataset.with_suffix('.meta.json')
        if meta.exists():
            files[meta.name] = sha(meta)
            raw_meta = json.loads(meta.read_text())
            metadata['input_contract'] = {key:raw_meta.get(key) for key in ('dataset_kind','n_rows','n_dates','watchlist_source','entry_price_mode','exit_price_mode','roundtrip_cost','pre_strategy_cross_section')}
        outputs.update({'paired_by_date.csv':paired,'entry_increment_summary.csv':summary,'concentration.csv':concentration})
    report = ['# Selection Review Diagnostics', '',
              'This report describes observed evidence; it does not promote a production policy.', '']
    if args.mode == 'attention':
        report.extend([f"Snapshots: {len(observations)}; human reviews: {metadata['n_human_reviews']}.", '',
                       'Review time and rejection reasons remain unavailable until real review logs are supplied.', '',
                       '| Week | Slots | New | Repeated | Upgrades | Downgraded after upgrade | Censored |',
                       '| --- | --- | --- | --- | --- | --- | --- |'])
        for r in weekly.to_dict('records'):
            report.append(f"| {r['iso_week']} | {r['n_slots']} | {r['n_new']} | {r['n_repeated']} | {r['n_upgrades']} | {r['n_failed_upgrades']} | {r['n_upgrade_outcomes_censored']} |")
    else:
        report.extend(['Same-date Quality A/B pool versus its Entry Ready subset, date-equal means.', '',
                       '| Horizon | Sample | Dates | Ready minus pool QQQ excess (pp) |',
                       '| --- | --- | --- | --- |'])
        for r in summary.to_dict('records'):
            if r['segment_type'] in ('overall','nonoverlapping'):
                report.append(f"| {r['horizon']}d | {r['segment_type']} | {r['n_dates']} | {r['delta_excess']*100:+.3f} |")
        report.extend(['', metadata['caveat'], '', 'See concentration.csv for symbol/date concentration and entry_increment_summary.csv for year/regime splits.'])
    metadata['input_sha256'] = files
    metadata['code_sha'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    metadata['working_tree_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    sources = ['src/ai_value_scanner/research/review_utility.py','src/ai_value_scanner/decision/quality.py',
               'src/ai_value_scanner/decision/entry.py','src/ai_value_scanner/fundamentals/accounting.py',
               'scripts/review_selection_utility.py']
    metadata['source_sha256'] = {p:sha(ROOT/p) for p in sources}
    args.output.mkdir(parents=True)
    for name,frame in outputs.items(): frame.to_csv(args.output/name,index=False)
    (args.output/'README.md').write_text('\n'.join(report)+'\n')
    (args.output/'manifest.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps({'mode':args.mode,'files':list(outputs),'metadata':'manifest.json'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
