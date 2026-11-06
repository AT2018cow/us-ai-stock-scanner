"""Rebuild forward labels using frozen raw bars and an optional bounded repair plan."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_value_scanner.backtest import apply_split_adjustment_to_frame
from ai_value_scanner.evaluation.backtest import forward_return_with_exit
from ai_value_scanner.research.provenance import sha256_file


def load_frozen_bars(cache_dir, symbols, declared_hashes=None):
    raw, used = {}, {}
    files = [Path(cache_dir)/name for name in sorted(declared_hashes)] if declared_hashes is not None else sorted(Path(cache_dir).glob('bars_*.json'))
    for file in files:
        digest = sha256_file(file)
        if declared_hashes is not None and digest != declared_hashes[file.name]:
            raise ValueError('frozen raw cache identity mismatch: ' + file.name)
        payload = json.loads(file.read_text())
        selected = False
        for symbol in symbols:
            rows = payload.get(symbol, [])
            if rows and len(rows) > len(raw.get(symbol, [])):
                raw[symbol] = rows
                selected = True
        if selected:
            used[file.name] = digest
    if 'QQQ' not in raw:
        raise ValueError('benchmark cache absent')
    return raw, used


def write_changed_fields(source, target, included_indexes, updates):
    """Keep original text for every feature and every unaffected label."""
    with source.open(newline='') as src, target.open('w', newline='') as dst:
        reader = csv.reader(src)
        header = next(reader)
        positions = {name: i for i, name in enumerate(header)}
        writer = csv.writer(dst, lineterminator='\n')
        writer.writerow(header)
        for index, fields in enumerate(reader):
            if index not in included_indexes:
                continue
            for name, value in updates.get(index, {}).items():
                if not name.startswith(('fwd_ret_', 'label_end_', 'qqq_return_', 'qqq_label_end_')):
                    raise ValueError('repair attempted to change a feature column')
                fields[positions[name]] = '' if value is None else str(value)
            writer.writerow(fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--cache-dir', required=True)
    parser.add_argument('--cutoff', default='2026-11-05')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--repair-plan', help='Frozen source hashes and only the affected date/horizon pairs')
    args = parser.parse_args()
    source = Path(args.source_root)/args.study
    out = Path(args.output_root)/args.study
    if out.exists():
        raise ValueError('immutable output exists')
    dataset = source/'dataset.csv'
    digest = sha256_file(dataset)
    if digest != json.loads((source/'success.json').read_text())['sha256']:
        raise ValueError('source hash mismatch')
    meta = json.loads((source/'dataset.meta.json').read_text())
    frame = pd.read_csv(dataset, low_memory=False)
    repair = None
    if args.repair_plan:
        plan = json.loads(Path(args.repair_plan).read_text())
        repair = plan['studies'][args.study]
        if repair['source_dataset_sha256'] != digest or plan['cutoff'] != args.cutoff:
            raise ValueError('repair plan/source contract mismatch')
        if repair.get('source_metadata_sha256') != sha256_file(source/'dataset.meta.json') or repair.get('source_splits_sha256') != sha256_file(source/'dataset.splits.json'):
            raise ValueError('repair metadata/splits identity mismatch')
        windows = {r['signal_date']: r['horizons'] for r in repair['windows']}
    else:
        windows = {day: [20, 60, 120, 252] for day in frame.signal_date.unique()}
    if args.smoke:
        if repair is not None:
            if not windows:
                raise ValueError('repair smoke requires an affected window')
            frame = frame[frame.signal_date.eq(min(windows)) & frame.symbol.isin(['AAPL', 'MSFT', 'NVDA'])].copy()
        else:
            frame = frame[frame.symbol.isin(['AAPL', 'KMI', 'SCCO', 'EOG']) & frame.signal_date.isin(['2016-11-30', '2020-03-31', '2022-02-28', '2022-06-30'])].copy()
        if frame.empty:
            raise ValueError('empty smoke input')
    target = frame[frame.signal_date.isin(windows)]
    bars, cache_hashes = {}, {}
    splits_path = source/'dataset.splits.json'
    splits = json.loads(splits_path.read_text())['events']
    if not target.empty:
        declared = meta.get('cache_hashes') if repair is not None else None
        if repair is not None and not declared:
            raise ValueError('bounded repair requires frozen raw cache hashes')
        raw, cache_hashes = load_frozen_bars(args.cache_dir, set(target.symbol) | {'QQQ'}, declared)
        for symbol, rows in raw.items():
            prices = pd.DataFrame(rows)
            prices['date'] = pd.to_datetime(prices.t, utc=True).dt.normalize()
            prices = prices[prices.date <= pd.Timestamp(args.cutoff, tz='UTC')].drop_duplicates('date').set_index('date').sort_index()
            prices = prices.rename(columns={'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 'v': 'volume'})
            bars[symbol] = apply_split_adjustment_to_frame(prices, splits.get(symbol))
    updates = {}
    for i, (day, group) in enumerate(target.groupby('signal_date', sort=True), 1):
        print(f'{args.study}: labels {i}/{target.signal_date.nunique()} {day}', flush=True)
        for horizon in windows[day]:
            qqq, qend = forward_return_with_exit(bars['QQQ'], day, horizon, .003, global_end_date=pd.Timestamp(args.cutoff, tz='UTC'))
            for index, row in group.iterrows():
                value, end = forward_return_with_exit(bars.get(row.symbol), day, horizon, .003,
                    global_end_date=pd.Timestamp(args.cutoff, tz='UTC'), delist_return_assumption=-.55)
                updates.setdefault(index, {}).update({f'fwd_ret_{horizon}': value,
                    f'label_end_{horizon}': end.date().isoformat() if end is not None else None,
                    f'qqq_return_{horizon}': qqq,
                    f'qqq_label_end_{horizon}': qend.date().isoformat() if qend is not None else None})
    meta.update(label_contract='exchange_calendar_endpoints_v3', label_cutoff=args.cutoff,
        n_rows=len(frame), n_dates=int(frame.signal_date.nunique()), features_recomputed=False,
        source_dataset_sha256=digest, source_splits_sha256=sha256_file(splits_path),
        cache_hashes=cache_hashes or meta.get('cache_hashes', {}),
        repaired_windows=repair['windows'] if repair is not None else 'all requested horizons',
        repair_plan_sha256=sha256_file(args.repair_plan) if args.repair_plan else None,
        processors={str(p.relative_to(ROOT)): sha256_file(p) for p in [Path(__file__),
            ROOT/'src/ai_value_scanner/evaluation/backtest.py', ROOT/'src/ai_value_scanner/market_calendar.py',
            ROOT/'src/ai_value_scanner/research/provenance.py']})
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{args.study}.', dir=out.parent) as temporary:
        staging = Path(temporary)/'result';staging.mkdir()
        if not updates and not args.smoke:
            (staging/'dataset.csv').write_bytes(dataset.read_bytes())
        else:
            write_changed_fields(dataset, staging/'dataset.csv', set(frame.index), updates)
        (staging/'dataset.meta.json').write_text(json.dumps(meta, indent=2)+'\n')
        (staging/'dataset.splits.json').write_bytes(splits_path.read_bytes())
        summary = dict(path=str(out.relative_to(Path(args.output_root).parent)),
            sha256=sha256_file(staging/'dataset.csv'), metadata_sha256=sha256_file(staging/'dataset.meta.json'),
            rows=len(frame), dates=int(frame.signal_date.nunique()), repaired_rows=len(updates))
        (staging/'success.json').write_text(json.dumps(summary)+'\n')
        if out.exists(): raise ValueError('immutable output exists')
        staging.rename(out)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__': main()
