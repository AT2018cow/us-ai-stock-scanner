"""Independent streaming check: only registered outcome fields may change."""
from pathlib import Path
import argparse
import csv
import hashlib
from itertools import zip_longest
import json
import math


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed(value, end):
    return bool(value and end and math.isfinite(float(value)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-root', default='outputs/sip_eod_migration/relabelled')
    parser.add_argument('--new-root', default='outputs/review_followup_20261106/datasets')
    parser.add_argument('--plan', default='docs/review_followup_20261106/repair_plan.json')
    parser.add_argument('--output', default='docs/review_followup_20261106/label_repair_checks.json')
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    results, windows = {}, []
    for study, contract in plan['studies'].items():
        old = Path(args.old_root)/study
        new = Path(args.new_root)/study
        assert digest(old/'dataset.csv') == contract['source_dataset_sha256']
        success = json.loads((new/'success.json').read_text())
        assert digest(new/'dataset.csv') == success['sha256']
        assert digest(new/'dataset.meta.json') == success['metadata_sha256']
        targets = {r['signal_date']: r for r in contract['windows']}
        counts = {day: dict(study=study, signal_date=day, expected_exit=r['expected_exit']['120'],
                           rows=0, old_observed_stock=0, new_observed_stock=0,
                           old_observed_qqq=0, new_observed_qqq=0) for day, r in targets.items()}
        changed_fields = changed_rows = total = paired = 0
        coverage = {h: dict(old_observed=0,new_observed=0) for h in [20,60,120,252]}
        with (old/'dataset.csv').open(newline='') as a, (new/'dataset.csv').open(newline='') as b:
            before, after = csv.reader(a), csv.reader(b)
            header = next(before)
            assert header == next(after)
            positions = {name:i for i,name in enumerate(header)}
            for x,y in zip_longest(before,after):
                assert x is not None and y is not None
                assert len(x) == len(y) == len(header)
                day = x[positions['signal_date']]
                allowed = {f'{prefix}{h}' for h in targets.get(day,{}).get('horizons',[]) for prefix in ['fwd_ret_','label_end_','qqq_return_','qqq_label_end_']}
                changed = [name for name,left,right in zip(header,x,y) if left != right]
                assert set(changed) <= allowed, (study,day,changed)
                changed_fields += len(changed)
                changed_rows += bool(changed)
                total += 1
                for h in coverage:
                    oi,ei,qi,qei = [positions[f'{prefix}{h}'] for prefix in ['fwd_ret_','label_end_','qqq_return_','qqq_label_end_']]
                    coverage[h]['old_observed'] += observed(x[oi],x[ei])
                    coverage[h]['new_observed'] += observed(y[oi],y[ei])
                    if observed(y[oi],y[ei]) and observed(y[qi],y[qei]):
                        assert y[ei] == y[qei], (study,day,h,'exit mismatch')
                        paired += 1
                if day in counts:
                    item = counts[day];item['rows'] += 1
                    for label, values in [('old',x),('new',y)]:
                        item[label+'_observed_stock'] += observed(values[positions['fwd_ret_120']],values[positions['label_end_120']])
                        item[label+'_observed_qqq'] += observed(values[positions['qqq_return_120']],values[positions['qqq_label_end_120']])
                    assert y[positions['qqq_label_end_120']] == item['expected_exit']
                    if y[positions['label_end_120']]:
                        assert y[positions['label_end_120']] == item['expected_exit']
        assert total == success['rows']
        assert all(c['new_observed_qqq']==c['rows'] and c['old_observed_qqq']==0 for c in counts.values())
        results[study] = dict(rows=total, changed_rows=changed_rows, changed_fields=changed_fields,
            all_feature_text_unchanged=True, all_unregistered_label_text_unchanged=True,
            paired_exits_checked=paired, paired_exit_mismatches=0, horizon_coverage=coverage,
            sha256=success['sha256'], metadata_sha256=success['metadata_sha256'])
        windows.extend(counts.values())
        print(study, total, 'rows;', changed_rows, 'changed outcome rows', flush=True)
    out = Path(args.output)
    out.write_text(json.dumps(results,indent=2)+'\n')
    with out.with_name('repaired_windows.csv').open('w',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(windows[0]));writer.writeheader();writer.writerows(windows)


if __name__=='__main__':main()
