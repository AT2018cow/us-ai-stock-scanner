"""Null forward labels spanning an equity discontinuity (research repair).

Reads an extract_weight_dataset CSV plus its {stem}.splits.json (frozen
split events), applies the share-count continuity guard from
ai_value_scanner.evaluation.equity_continuity, and writes a patched CSV
(+2 columns) plus a discontinuity audit CSV. Deterministic, offline, no
network. Exit nonzero on missing inputs; never edits in place.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ai_value_scanner.evaluation.equity_continuity import repair_labels


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="extract CSV to repair")
    p.add_argument("--splits-json", required=True,
                   help="{stem}.splits.json frozen with the extract")
    p.add_argument("--output", required=True, help="patched CSV destination")
    p.add_argument("--audit-out", required=True, help="audit CSV destination")
    p.add_argument("--horizons", default="20,60,120")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.input)
    splits_path = Path(args.splits_json)
    if not src.is_file():
        raise SystemExit(f"missing input CSV: {src}")
    if not splits_path.is_file():
        raise SystemExit(f"missing splits JSON: {splits_path}")
    horizons = tuple(int(x) for x in str(args.horizons).split(",") if x.strip())
    df = pd.read_csv(src)
    spec = json.loads(splits_path.read_text(encoding="utf-8"))
    splits = {s: [(d, float(m)) for d, m in evts]
              for s, evts in (spec.get("events") or {}).items()}
    patched, audit = repair_labels(df, splits, horizons)
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refuse to overwrite: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    patched.to_csv(out, index=False)
    audit.to_csv(Path(args.audit_out), index=False)
    print(f"repair: rows={len(patched)} flagged={int(patched['equity_discontinuity_flag'].sum())} "
          f"discontinuities={len(audit)} -> {out}")


if __name__ == "__main__":
    main()
