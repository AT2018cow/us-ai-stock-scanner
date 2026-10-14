"""Freeze retrospective 52-event interval exposure flags BEFORE candidate returns.

Outcomes are not read. These flags are evaluation *sensitivity* masks only,
NEVER a historical stock-selection filter and NEVER grounds to label a true
price rally wrong. No changes to production, canonical B0 or original v3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_value_scanner.research.mvp_v11 import inspect_frozen_dataset


HORIZONS = (20, 60, 120)
EVENT_REQUIRED = frozenset({"symbol", "prev_date", "date", "reason", "null_labels"})
REQUIRED = frozenset({"signal_date", "symbol"})


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _verified(path: str, sha: str) -> Path:
    f = Path(path).expanduser().resolve()
    if not f.is_file() or _hash(f) != sha.lower():
        raise ValueError(f"reference missing or SHA256 mismatch: {f}")
    return f


def build_event_interval_flags(
    feature_rows: pd.DataFrame, event_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """Produce date×symbol×horizon exposure for retrospective label uncertainty.

    An event is only known to have occurred somewhere in the monthly detection
    interval (prev_date, date]. The selected holding interval starts after the
    signal and ends on label_end_{h}; intersect those intervals conservatively.
    Endpoints are intentionally *not* exact event timestamps. No returns used.
    """
    missing = REQUIRED - set(feature_rows)
    if missing:
        raise ValueError(f"missing source columns: {sorted(missing)}")
    missing = EVENT_REQUIRED - set(event_rows)
    if missing:
        raise ValueError(f"missing event columns: {sorted(missing)}")
    if len(event_rows) != 52:
        raise ValueError("frozen 52-event audit count mismatch")
    nil = event_rows["null_labels"].astype(str).str.lower() == "true"
    if nil.sum() != 1 or event_rows.loc[nil, "symbol"].tolist() != ["WOLF"]:
        raise ValueError("original WOLF-only nulling identity mismatch")
    expected_cols = {f"label_end_{h}" for h in HORIZONS}
    if expected_cols - set(feature_rows):
        raise ValueError(f"missing frozen label_end columns: {sorted(expected_cols - set(feature_rows))}")
    if feature_rows.duplicated(["signal_date", "symbol"]).any():
        raise ValueError("duplicate date×symbol source rows")
    frame = feature_rows.loc[:, ["signal_date", "symbol", *sorted(expected_cols)]].copy()
    if frame.empty:
        raise ValueError("empty feature rows")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    signal = pd.to_datetime(frame["signal_date"], errors="coerce")
    if signal.isna().any():
        raise ValueError("invalid signal_date")
    event = event_rows.copy()
    event["symbol"] = event["symbol"].astype(str).str.strip().str.upper()
    event["prev_dt"] = pd.to_datetime(event.prev_date, errors="coerce")
    event["event_dt"] = pd.to_datetime(event.date, errors="coerce")
    if (event.prev_dt.isna() | event.event_dt.isna()).any():
        raise ValueError("invalid event interval date")
    if (event.prev_dt >= event.event_dt).any():
        raise ValueError("event previous date must precede detection date")

    outputs = []
    for horizon in HORIZONS:
        label_end = pd.to_datetime(frame[f"label_end_{horizon}"], errors="coerce")
        work = pd.DataFrame({
            "signal_date": frame.signal_date.astype(str),
            "symbol": frame.symbol,
            "horizon": horizon,
            "label_end_missing": label_end.isna(),
            "event_interval_exposed": False,
            "event_count": 0,
        })
        matches = [
            (
                work.symbol.eq(e.symbol).to_numpy()
                & signal.lt(e.event_dt).to_numpy()
                & label_end.gt(e.prev_dt).to_numpy()
            )
            for e in event.itertuples(index=False)
        ]
        if matches:
            import numpy as np
            counts = np.sum(matches, axis=0)
            work["event_count"] = counts
            work["event_interval_exposed"] = counts > 0
        outputs.append(work)
    flags = pd.concat(outputs, ignore_index=True)
    summary = {
        "status": "PRE_REGISTERED_RETROSPECTIVE_EXPOSURE_ONLY",
        "ready_for_candidate_returns": False,
        "n_signal_rows": len(frame),
        "n_dates": frame.signal_date.nunique(),
        "n_events_in_input": len(event),
        "n_flag_rows": len(flags),
        "horizons": {},
        "rules": [
            "Event dates denote detection intervals, not exact corporate-action timestamps.",
            "Flag intersection of (signal_date, label_end_h] with (prev_date, event_date].",
            "Only the paired evaluation sensitivity can use future event intervals.",
            "No ranking, candidate selection, returns or exclusions performed here.",
            "Primary valid-label comparisons still require unmodified v3 and locked comparator.",
            "Unverified score-input contamination requires independent as-of audit.",
        ],
    }
    for h, g in flags.groupby("horizon"):
        summary["horizons"][str(h)] = {
            "n_event_exposed": int(g.event_interval_exposed.sum()),
            "n_missing_label_end": int(g.label_end_missing.sum()),
            "n_unique_symbols_exposed": int(g.loc[g.event_interval_exposed, "symbol"].nunique()),
            "n_unique_dates_exposed": int(g.loc[g.event_interval_exposed, "signal_date"].nunique()),
        }
    return flags, summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--entry-dataset", required=True)
    p.add_argument("--entry-meta", required=True)
    p.add_argument("--expected-dataset-sha256", required=True)
    p.add_argument("--events", required=True)
    p.add_argument("--expected-events-sha256", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    inv = inspect_frozen_dataset(
        args.entry_dataset, expected_kind="entry_quality", metadata=args.entry_meta
    )
    if inv["dataset_sha256"] != args.expected_dataset_sha256.lower():
        raise ValueError("v3 input SHA256 mismatch")
    events = _verified(args.events, args.expected_events_sha256)
    # Explicit usecols protects this preflight from accidental future outcome
    # inspection and keeps the user-visible report outcome-free.
    columns = ["signal_date", "symbol", *(f"label_end_{h}" for h in HORIZONS)]
    data = pd.read_csv(args.entry_dataset, usecols=columns)
    e = pd.read_csv(events)
    flags, summary = build_event_interval_flags(data, e)
    summary["input_sha256"] = inv["dataset_sha256"]
    summary["events_sha256"] = _hash(events)
    out = Path(args.output_dir)
    if out.exists():
        raise ValueError(f"refusing to overwrite: {out}")
    out.mkdir(parents=True)
    flags.to_csv(out / "event_interval_exposure_local_only.csv", index=False)
    (out / "event_interval_exposure_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{summary['status']}: produced local-only exposure flags and summary in {out}; "
        "no returns analyzed"
    )


if __name__ == "__main__":
    main()
