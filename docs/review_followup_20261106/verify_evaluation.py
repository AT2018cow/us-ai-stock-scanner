"""Stream original/new slots and independently re-sum complete cohorts."""
from collections import defaultdict
import csv
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    if value in ('', None): return None
    result = float(value)
    return result if math.isfinite(result) else None


def local_input(name):
    prefix = 'research/review_followup_20261106_v1/'
    return Path('outputs/review_followup_20261106')/name[len(prefix):] if name.startswith(prefix) else Path(name)


def main():
    output = Path('docs/review_followup_20261106')
    checks = []
    for scope in ['sip_monthly', 'sip_covid_weekly', 'sip_bear_weekly']:
        new = Path('outputs/review_followup_20261106/evaluations')/f'evaluation_{scope}_v2'
        old = Path('outputs/sip_eod_migration/evaluations')/new.name
        sums, counts, outcomes = defaultdict(float), defaultdict(int), defaultdict(list)
        slot_count = changed_slots = 0
        with (old/'slots.csv').open(newline='') as a, (new/'slots.csv').open(newline='') as b:
            left, right = csv.DictReader(a), csv.DictReader(b)
            assert left.fieldnames == right.fieldnames
            for x,y in zip_longest(left,right):
                assert x is not None and y is not None
                changed = {name for name in x if x[name] != y[name]}
                assert changed <= {'label_status', 'net_return'}
                if changed:
                    assert int(y['horizon']) == 120
                    changed_slots += 1
                key = (y['signal_date'], y['variant'], y['view'], int(y['horizon']))
                value = number(y['net_return'])
                if value is not None: sums[key] += value*float(y['weight'])
                slot_count += 1
        with (new/'cohorts.csv').open(newline='') as f:
            rows = list(csv.DictReader(f))
        errors = []
        for row in rows:
            key = (row['signal_date'], row['variant'], row['view'], int(row['horizon']))
            group = key[1:]
            counts[group] += 1
            value, qqq = number(row['net_return']), number(row['qqq_return'])
            if int(row['n_invalid']) == 0 and value is not None:
                errors.append(abs(value-sums[key]))
            if row['research_qualified']=='True' and value is not None and qqq is not None:
                assert abs(value-qqq-float(row['excess'])) < 1e-12
                outcomes[group].append((value, value-qqq))
        assert max(errors, default=0.) < 1e-12
        with (new/'summary.csv').open(newline='') as f:
            for row in csv.DictReader(f):
                if row['segment_type']!='all': continue
                key = (row['variant'], row['view'], int(row['horizon']))
                values = outcomes[key]
                assert int(row['n_dates']) == counts[key]
                assert int(row['n_valid']) == len(values)
                for index,name in enumerate(['mean_return','mean_excess']):
                    if values:
                        assert abs(float(row[name])-sum(v[index] for v in values)/len(values)) < 1e-12
                    else: assert number(row[name]) is None
        manifest = json.loads((new/'manifest.json').read_text())
        assert manifest['config_sha256'] == digest('configs/config.production.json')
        for name,sha in {**manifest['sources'], **manifest['inputs']}.items():
            assert digest(local_input(name)) == sha, name
        target = output/'evaluations'/scope
        target.mkdir(parents=True, exist_ok=True)
        for name in ['manifest.json','report.md','summary.csv','diagnostics.csv','coverage_by_year.csv',
                     'qualification_by_year.csv','common_date_summary.csv']:
            shutil.copyfile(new/name,target/name)
        for horizon in [60,120]:
            with (target/f'cohorts_{horizon}d.csv').open('w',newline='') as f:
                writer = csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
                writer.writerows(row for row in rows if int(row['horizon'])==horizon)
        with (new/'random_distribution.csv').open(newline='') as f:
            random = list(csv.DictReader(f))
        with (target/'random_120d.csv').open('w',newline='') as f:
            writer = csv.DictWriter(f,fieldnames=list(random[0]));writer.writeheader()
            writer.writerows(row for row in random if int(row['horizon'])==120)
        checks.append(dict(scope=scope,slot_identities_and_order_checked=slot_count,
            changed_outcome_slots_120d_only=changed_slots,cohort_weighted_sums_checked=len(errors),
            max_weighted_return_error=max(errors, default=0.),configuration_and_all_sources_inputs_verified=True,
            all_overall_counts_and_mean_returns_recomputed=True))
        print(scope,checks[-1],flush=True)
    (output/'independent_evaluation_checks.json').write_text(json.dumps(checks,indent=2)+'\n')


if __name__=='__main__':main()
