"""Offline A0/B0 follow-up: triage PIT provenance and corporate-action risks.

This script does NOT certify SEC filing public-times, split correctness, or
security identity. It never changes/overwrites labels, snapshots, or strategy
decisions. All event dispositions require independent human review.
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
EXPECTED_EVENTS = 52
EXPECTED_NULLING = 1
PIT_HINTS = (
    "filing", "accession", "cik", "identity", "entity", "period",
    "asof", "as_of", "source", "currency", "restat",
)


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _verify_sha(path: Path, expected: str) -> str:
    actual = _file_sha(path)
    if actual != str(expected).lower():
        raise ValueError(f"SHA256 mismatch for {path}")
    return actual


def _symbol_list(token: object) -> set[str]:
    if pd.isna(token):
        return set()
    return {s.strip().upper() for s in str(token).split(";") if s.strip()}


def prepare_review_queue(
    data: pd.DataFrame,
    events: pd.DataFrame,
    frozen_ranking: pd.DataFrame,
) -> tuple[dict, pd.DataFrame]:
    required_data = {"signal_date", "symbol", "fundamental_data_asof"}
    required_event = {"symbol", "date", "prev_date", "reason", "null_labels",
                      "nulled_h20", "nulled_h60", "nulled_h120", "ratio", "price_ratio"}
    required_ranks = {"signal_date", "v1_top5", "v1_top15"}
    for name, frame, required in (
        ("v3", data, required_data),
        ("event", events, required_event),
        ("ranking", frozen_ranking, required_ranks),
    ):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} missing columns: {missing}")
    if len(events) != EXPECTED_EVENTS:
        raise ValueError(f"expect {EXPECTED_EVENTS} original audit events, got {len(events)}")
    is_null = events["null_labels"].astype(str).str.lower() == "true"
    if int(is_null.sum()) != EXPECTED_NULLING:
        raise ValueError("original audit must contain exactly one WOLF-style nulling event")
    if (events.loc[is_null, "symbol"] != "WOLF").any():
        raise ValueError("expected WOLF nulling identity changed")
    if frozen_ranking.signal_date.duplicated().any():
        raise ValueError("ranking duplicate dates")
    if data.duplicated(subset=["signal_date", "symbol"]).any():
        raise ValueError("v3 duplicate signal_date×symbol")
    by_date = frozen_ranking.set_index("signal_date")
    data_ix = data.set_index(["signal_date", "symbol"], verify_integrity=True)
    queue = []
    for _, e in events.iterrows():
        symbol = str(e.symbol).strip().upper()
        day = str(e.date)
        old_day = str(e.prev_date)
        top5 = _symbol_list(by_date.at[day, "v1_top5"]) if day in by_date.index else set()
        top15 = _symbol_list(by_date.at[day, "v1_top15"]) if day in by_date.index else set()
        prev_top15 = (_symbol_list(by_date.at[old_day, "v1_top15"])
                      if old_day in by_date.index else set())
        key = (day, symbol)
        shares = float(e.ratio) if pd.notna(e.ratio) else float("nan")
        price = float(e.price_ratio) if pd.notna(e.price_ratio) else float("nan")
        severe_shares = bool(pd.notna(shares) and (shares > 10 or shares < 0.1))
        sharp_price = bool(pd.notna(price) and (price > 3 or price < (1 / 3)))
        row = data_ix.loc[key] if key in data_ix.index else None
        q_asof = None if row is None else row.get("fundamental_data_asof")
        q_asof_missing = row is not None and pd.isna(q_asof)
        queue.append({
            "symbol": symbol,
            "prev_date": old_day,
            "event_date": day,
            "reason": str(e.reason),
            "null_labels": bool(is_null.loc[e.name]),
            "nulled_h20": int(e.nulled_h20),
            "nulled_h60": int(e.nulled_h60),
            "nulled_h120": int(e.nulled_h120),
            "shares_ratio": shares,
            "price_ratio": price,
            "severe_shares_change": severe_shares,
            "sharp_price_move": sharp_price,
            "in_v3_on_event_date": row is not None,
            "missing_fundamental_asof_on_event_date": bool(q_asof_missing),
            "top5_at_event": symbol in top5,
            "top15_at_event": symbol in top15,
            "top15_at_previous_date": symbol in prev_top15,
            "human_disposition": "UNREVIEWED",
            "evidence_reference": "",
            "reviewer_note": "",
        })
    audit = pd.DataFrame(queue)
    audit = audit.sort_values(
        ["null_labels", "top15_at_event", "top15_at_previous_date",
         "severe_shares_change", "sharp_price_move", "symbol", "event_date"],
        ascending=[False, False, False, False, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    relevant_columns = sorted(
        name for name in data.columns if any(hint in name.lower() for hint in PIT_HINTS)
    )
    # This is deliberately NOT a PIT certification; at most it identifies
    # missing as-of and what provenance columns exist for further audit.
    summary = {
        "verdict": "DATA_RISK_REVIEW_REQUIRED",
        "ready_for_candidate_returns": False,
        "n_input_rows": len(data),
        "n_dates": int(data.signal_date.nunique()),
        "n_missing_fundamental_asof": int(data.fundamental_data_asof.isna().sum()),
        "n_51_audit_only": int((~is_null).sum()),
        "n_label_nulling_events": int(is_null.sum()),
        "n_event_records": len(audit),
        "n_top5_event_date": int(audit.top5_at_event.sum()),
        "n_top15_event_date": int(audit.top15_at_event.sum()),
        "n_top15_previous_date": int(audit.top15_at_previous_date.sum()),
        "n_severe_share_ratio_events": int(audit.severe_shares_change.sum()),
        "n_sharp_price_events": int(audit.sharp_price_move.sum()),
        "available_pit_provenance_columns": relevant_columns,
        "required_before_candidate_returns": [
            "Check date AND actual public filing availability (not just period end).",
            "Audit identity/CIK/operating entity/currency and subsequent restatement drift.",
            "Review 51 audit-only events; retain real winners, flag uncertain labels or score inputs.",
            "Freeze event handling and a single paired valid-mask protocol before outcomes.",
            "Obtain explicit approval of unchanged pre-registered B0/R1-R5/E1-E4.",
        ],
        "notes": [
            "Exposure on archived Top-k is a triage priority, not proof an event influenced ranking.",
            "Never use later price movements as decision-date evidence.",
            "No source SEC filings or corporate-action event facts independently retrieved.",
            "No future outcomes/return statistics computed; no v3 inputs modified.",
            "No action can pass the manual gate from this automated report alone.",
        ],
    }
    return summary, audit


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--entry-dataset", required=True)
    p.add_argument("--entry-meta", required=True)
    p.add_argument("--expected-dataset-sha256", required=True)
    p.add_argument("--events", required=True, help="Original corrected _03 discontinuities CSV")
    p.add_argument("--expected-events-sha256", required=True)
    p.add_argument("--archived-ranking", required=True)
    p.add_argument("--expected-ranking-sha256", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    dataset, meta = Path(args.entry_dataset), Path(args.entry_meta)
    inv = inspect_frozen_dataset(dataset, expected_kind="entry_quality", metadata=meta)
    if inv["dataset_sha256"] != args.expected_dataset_sha256.lower():
        raise ValueError("frozen dataset SHA mismatch")
    events_path, ranking_path = Path(args.events), Path(args.archived_ranking)
    event_sha = _verify_sha(events_path, args.expected_events_sha256)
    ranking_sha = _verify_sha(ranking_path, args.expected_ranking_sha256)
    summary, queue = prepare_review_queue(
        pd.read_csv(dataset, low_memory=False),
        pd.read_csv(events_path),
        pd.read_csv(ranking_path),
    )
    summary["dataset_sha256"] = inv["dataset_sha256"]
    summary["metadata_sha256"] = inv["metadata_sha256"]
    summary["events_sha256"] = event_sha
    summary["ranking_sha256"] = ranking_sha
    out = Path(args.output_dir)
    if out.exists():
        raise ValueError(f"refusing to overwrite existing output: {out}")
    out.mkdir(parents=True)
    (out / "data_risk_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    queue.to_csv(out / "event_review_queue.csv", index=False)
    print(f"{summary['verdict']}: {len(queue)} events in {out}; manual review required")


if __name__ == "__main__":
    main()
