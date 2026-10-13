"""Rebuild canonical B0 from frozen historical rows and reconcile archived v1.

A strict, read-only historical priority/cap proxy check. Never claims to
reproduce prospective Daily/Weekly previous-state behaviour.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.research.mvp_v11 import inspect_frozen_dataset


RESULT_FIELDS = (
    "quality_grade", "quality_score", "quality_confidence",
    "entry_state", "entry_score", "entry_confidence", "action_state",
)
COUNT_FIELDS = {
    "PRIORITY_REVIEW": "priority_review_count",
    "WATCH_PULLBACK": "watch_pullback_count",
    "WATCH_BREAKOUT": "watch_breakout_count",
    "HOLD_MONITOR": "hold_monitor_count",
    "AVOID": "avoid_count",
}
FUTURE_PREFIXES = (
    "fwd_", "qqq_return_", "label_end_", "forward_", "mae_", "mfe_",
    "equity_discontinuity_", "split_label_",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _reference_frame(path: Path, columns: tuple[str, ...], *, name: str) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"{name} missing: {path}")
    frame = pd.read_csv(path, low_memory=False)
    absent = sorted(set(columns) - set(frame.columns))
    if absent:
        raise ValueError(f"{name} missing columns: {absent}")
    if frame.empty:
        raise ValueError(f"{name} empty")
    return frame


def _counts_row(day: str, decisions: tuple) -> dict[str, Any]:
    counts = Counter(d.action_state.value for d in decisions)
    ordered = [d.symbol for d in decisions]
    return {
        "signal_date": day,
        "n_eligible": len(decisions),
        "n_non_avoid": len(decisions) - counts["AVOID"],
        "n_pr_total": counts["PRIORITY_REVIEW"],
        "v1_top5": ";".join(ordered[:5]),
        "v1_top15": ";".join(ordered[:15]),
        **{column: counts[state] for state, column in COUNT_FIELDS.items()},
    }


def _decision_rows(decisions: tuple) -> list[dict[str, Any]]:
    return [
        {
            "signal_date": d.decision_date,
            "symbol": d.symbol,
            "priority": d.priority,
            "quality_grade": d.quality.grade.value,
            "quality_score": d.quality.score,
            "quality_confidence": d.quality.confidence,
            "entry_state": d.entry.state.value,
            "entry_score": d.entry.score,
            "entry_confidence": d.entry.confidence,
            "action_state": d.action_state.value,
            "quality_risk_codes": ",".join(x.code for x in d.quality.risks),
            "quality_missing_codes": ",".join(x.code for x in d.quality.missing),
            "entry_risk_codes": ",".join(x.code for x in d.entry.risks),
        }
        for d in decisions
    ]


def _equal(field: str, actual: Any, expected: Any) -> bool:
    if field.endswith("_codes"):
        return (
            "" if pd.isna(actual) else str(actual)
        ) == (
            "" if pd.isna(expected) else str(expected)
        )
    if pd.isna(actual) and pd.isna(expected):
        return True
    if pd.isna(actual) or pd.isna(expected):
        return False
    if field.endswith("_score") or field.endswith("_confidence"):
        try:
            return abs(float(actual) - float(expected)) <= 1e-6
        except (ValueError, TypeError):
            return False
    return str(actual) == str(expected)


def compare_b0(
    dataset: pd.DataFrame,
    archive_ranking: pd.DataFrame,
    archive_compactness: pd.DataFrame,
    *,
    reference_decisions: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Compute B0 only. No candidate ranks or future returns used.

    Full PASS requires frozen per-row historical reference decisions.
    Aggregate-only parity is explicitly insufficient for experimentation.
    """
    required = {"signal_date", "symbol"}
    if not required.issubset(dataset):
        raise ValueError("historical rows missing signal_date/symbol")
    if dataset.duplicated(subset=["signal_date", "symbol"]).any():
        raise ValueError("duplicate date×symbol")
    for name, reference in (("ranking", archive_ranking), ("compactness", archive_compactness)):
        if "signal_date" not in reference:
            raise ValueError(f"archived {name} lacks signal_date")
        if reference.signal_date.duplicated().any():
            raise ValueError(f"duplicate {name} signal_date")
    expected_ranking_fields = ("signal_date", "n_eligible", "n_non_avoid",
                               "n_pr_total", "v1_top5", "v1_top15")
    expected_compact_fields = ("signal_date", "n_decisions", "n_non_avoid",
                               *COUNT_FIELDS.values())
    for name, ref, fields in (("ranking", archive_ranking, expected_ranking_fields),
                              ("compactness", archive_compactness, expected_compact_fields)):
        absent = set(fields) - set(ref.columns)
        if absent:
            raise ValueError(f"archived {name} lacks columns: {sorted(absent)}")
    # The original archive uses the candidate-specific legacy H3 CSV as an
    # independent frozen reference. It must not be regenerated during this run.
    rank = archive_ranking.set_index("signal_date", verify_integrity=True)
    compact = archive_compactness.set_index("signal_date", verify_integrity=True)
    decisions_expected = None
    if reference_decisions is not None:
        req = {"signal_date", "symbol", *RESULT_FIELDS}
        absent = req - set(reference_decisions.columns)
        if absent:
            raise ValueError(f"historical decision reference lacks columns: {sorted(absent)}")
        if reference_decisions.duplicated(subset=["signal_date", "symbol"]).any():
            raise ValueError("duplicate archived date×symbol decision")
        decisions_expected = reference_decisions.set_index(
            ["signal_date", "symbol"], verify_integrity=True
        )

    days = sorted(dataset.signal_date.unique())
    mismatch_rows: list[dict[str, str]] = []
    aggregate_rows: list[dict[str, Any]] = []
    num_decisions = 0
    missing_asof_examples: list[dict[str, str]] = []
    for day, group in dataset.groupby("signal_date", sort=True):
        # FUTURE LABEL ISOLATION: scoring cannot access outcomes, future
        # corporate-action audit flags or label dates.
        score_cols = [
            c for c in group.columns
            if not c.startswith(FUTURE_PREFIXES)
        ]
        scored = build_stock_decisions(
            group.loc[:, score_cols],
            decision_date=day,
            generated_at_utc=f"{day}T23:59:59+00:00",
        )
        num_decisions += len(scored)
        result = _counts_row(day, scored)
        aggregate_rows.append(result)

        for name, ref, fields in (
            ("archived_ranking", rank, expected_ranking_fields[1:]),
            ("archived_compactness", compact, ("n_non_avoid", *COUNT_FIELDS.values())),
        ):
            if day not in ref.index:
                mismatch_rows.append({"signal_date": day, "symbol": "",
                                      "field": name, "actual": "present",
                                      "expected": "MISSING_DATE"})
                continue
            ref_row = ref.loc[day]
            if name == "archived_compactness":
                if int(ref_row["n_decisions"]) != len(scored):
                    mismatch_rows.append({"signal_date": day, "symbol": "",
                                          "field": "n_decisions", "actual": str(len(scored)),
                                          "expected": str(ref_row["n_decisions"])})
            for field in fields:
                if str(result[field]) != str(ref_row[field]):
                    mismatch_rows.append({
                        "signal_date": day, "symbol": "",
                        "field": field, "actual": str(result[field]),
                        "expected": str(ref_row[field]),
                    })
        if decisions_expected is not None:
            for row in _decision_rows(scored):
                key = (row["signal_date"], row["symbol"])
                if key not in decisions_expected.index:
                    mismatch_rows.append({"signal_date": day, "symbol": row["symbol"],
                                          "field": "historical_row",
                                          "actual": "present", "expected": "MISSING"})
                    continue
                old = decisions_expected.loc[key]
                for field in RESULT_FIELDS:
                    if not _equal(field, row[field], old[field]):
                        mismatch_rows.append({
                            "signal_date": day, "symbol": row["symbol"],
                            "field": field, "actual": str(row[field]),
                            "expected": str(old[field]),
                        })
                for field in ("quality_risk_codes", "quality_missing_codes", "entry_risk_codes"):
                    if field in decisions_expected and not _equal(field, row[field], old[field]):
                        mismatch_rows.append({
                            "signal_date": day, "symbol": row["symbol"],
                            "field": field, "actual": str(row[field]),
                            "expected": str(old[field]),
                        })
            missing = group[group.fundamental_data_asof.isna()] if "fundamental_data_asof" in group else pd.DataFrame()
            for symbol in missing.symbol.head(3):
                match = next((d for d in scored if d.symbol == symbol), None)
                if match is not None:
                    missing_asof_examples.append({
                        "signal_date": day, "symbol": match.symbol,
                        "quality_grade": match.quality.grade.value,
                        "quality_confidence": str(match.quality.confidence),
                    })
    for label, ref in (("archived_ranking", rank), ("archived_compactness", compact)):
        for extra in sorted(set(ref.index) - set(days)):
            mismatch_rows.append({"signal_date": str(extra), "symbol": "",
                                  "field": label, "actual": "MISSING_DATE",
                                  "expected": "present"})
    if decisions_expected is not None:
        idx = pd.MultiIndex.from_frame(dataset[["signal_date", "symbol"]])
        for day, symbol in decisions_expected.index.difference(idx).tolist():
            mismatch_rows.append({"signal_date": str(day), "symbol": str(symbol),
                                  "field": "historical_row",
                                  "actual": "MISSING", "expected": "present"})
    issues = pd.DataFrame(mismatch_rows, columns=[
        "signal_date", "symbol", "field", "actual", "expected"
    ])
    group_summary = pd.DataFrame(aggregate_rows)
    verdict = (
        "B0_MISMATCH_STOP" if not issues.empty else
        "B0_FULL_REFERENCE_PARITY_PASS" if decisions_expected is not None else
        "B0_AGGREGATE_ONLY_PARTIAL"
    )
    report = {
        "verdict": verdict,
        "ready_for_candidate_returns": verdict == "B0_FULL_REFERENCE_PARITY_PASS",
        "comparison": "monthly historical priority/cap proxy only; not prospective Daily/Weekly",
        "n_rows": num_decisions,
        "n_dates": len(days),
        "n_mismatches": int(len(issues)),
        "mismatch_by_field": (
            {str(k): int(v) for k, v in issues.field.value_counts().items()}
            if not issues.empty else {}
        ),
        "reference_decisions_available": decisions_expected is not None,
        "missing_fundamental_asof": int(dataset.fundamental_data_asof.isna().sum())
        if "fundamental_data_asof" in dataset else None,
        "missing_asof_decision_examples": missing_asof_examples[:15],
        "notes": [
            "CSV outcomes are explicitly stripped before canonical scoring.",
            "Archived ranking and compactness match alone never establish row-level parity.",
            "If mismatched, diagnose current scoring/SEC drift; do not tune candidate returns.",
            "No future returns, costs or candidate comparisons are calculated.",
        ],
    }
    return report, group_summary, issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-dataset", required=True)
    parser.add_argument("--entry-meta", required=True)
    parser.add_argument("--archived-ranking", required=True,
                        help="Frozen _03 evidence ranking_paired_by_date.csv")
    parser.add_argument("--archived-compactness", required=True,
                        help="Frozen _03 evidence action_v1_compactness.csv")
    parser.add_argument("--archived-decisions", default=None,
                        help="Original _03 action_v1_decisions.csv, optional; full parity requires it")
    parser.add_argument("--expected-dataset-sha256", required=True)
    parser.add_argument("--expected-decisions-sha256", default=None,
                        help="Required to recognize locally preserved original row decisions")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    inp = Path(args.entry_dataset)
    meta = Path(args.entry_meta)
    inventory = inspect_frozen_dataset(inp, expected_kind="entry_quality", metadata=meta)
    if inventory["dataset_sha256"] != args.expected_dataset_sha256.lower():
        raise ValueError("frozen input SHA mismatch; stop")
    arch_rank = Path(args.archived_ranking)
    arch_compact = Path(args.archived_compactness)
    archived_decisions = Path(args.archived_decisions) if args.archived_decisions else None
    if bool(archived_decisions) != bool(args.expected_decisions_sha256):
        raise ValueError("--archived-decisions requires --expected-decisions-sha256 and vice versa")
    if archived_decisions is not None and _sha256(archived_decisions) != args.expected_decisions_sha256.lower():
        raise ValueError("archived decisions SHA mismatch; stop")
    ranking = _reference_frame(arch_rank, (
        "signal_date", "n_eligible", "n_non_avoid", "n_pr_total",
        "v1_top5", "v1_top15"), name="archived ranking")
    compactness = _reference_frame(arch_compact, (
        "signal_date", "n_decisions", "n_non_avoid", *COUNT_FIELDS.values()
    ), name="archived compactness")
    decisions = (
        _reference_frame(archived_decisions, (
            "signal_date", "symbol", *RESULT_FIELDS
        ), name="archived decisions")
        if archived_decisions is not None else None
    )
    data = pd.read_csv(inp, low_memory=False)
    report, aggregate, issues = compare_b0(
        data, ranking, compactness, reference_decisions=decisions,
    )
    report["input_sha256"] = inventory["dataset_sha256"]
    report["input_metadata_sha256"] = inventory["metadata_sha256"]
    report["reference_sha256"] = {
        "archived_ranking": _sha256(arch_rank),
        "archived_compactness": _sha256(arch_compact),
        "archived_decisions": _sha256(archived_decisions) if archived_decisions else None,
    }
    report["historical_reference_caveat"] = (
        "Original row decisions are locally archived and their SHA is pinned by "
        "the operator before this B0 run; archival provenance still needs audit."
        if archived_decisions else
        "Frozen evidence supplies aggregate rankings/counts only, not original "
        "row-level decisions; full parity cannot be asserted."
    )
    out = Path(args.output_dir)
    if out.exists():
        raise ValueError(f"output directory exists, will not overwrite: {out}")
    out.mkdir(parents=True)
    (out / "baseline_parity.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    aggregate.to_csv(out / "baseline_parity_by_date.csv", index=False)
    issues.to_csv(out / "baseline_parity_mismatches.csv", index=False)
    print(f"{report['verdict']}: {report['n_mismatches']} mismatches; {out}")
    if report["verdict"] == "B0_MISMATCH_STOP":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
