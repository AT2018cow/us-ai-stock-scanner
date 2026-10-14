"""PR-A outcome-blind B0/R/E historical membership and mask preflight.

Never inspects candidate forward returns. This CLI is NOT the optimizer
performance study. Keep historical v3/metadata and 52-event evidence intact.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.fundamentals.edgartools_diagnostic import resolve_git_sha
from ai_value_scanner.research.mvp_v11 import R_CANDIDATES, inspect_frozen_dataset, _hash
from ai_value_scanner.research.mvp_v11_candidates import (
    E_CANDIDATES, replay_candidate_day,
)
from ai_value_scanner.research.mvp_v11_score_masks import score_source_flags


EXPECTED_DATA_SHA = "2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e"
EXPECTED_EVENT_REVIEW_SHA = "3bf0844fce0e2df40e81eea69eb2445c24a6abeaff7922473ca315b88143204e"
IDS = ("B0", "R1", "R2", "R3", "R4", "R5", "E1", "E2", "E3", "E4")


def verify_registry(path: Path) -> str:
    registry = json.loads(path.read_text(encoding="utf-8"))
    entries = registry["candidates"]
    if tuple(x["id"] for x in entries) != (*IDS, "X1"):
        raise ValueError("candidate registry deviates from frozen eleven slots")
    for item in entries:
        candidate_id = item["id"]
        if candidate_id in R_CANDIDATES:
            a, b, c = R_CANDIDATES[candidate_id]
            if (float(item["wQ"]), float(item["c"]), float(item["r"])) != (a, b, c):
                raise ValueError("changed registered R semantics")
        if candidate_id in E_CANDIDATES:
            ready, over = E_CANDIDATES[candidate_id]
            if (
                float(item["ready_rs60_min"]), float(item["overextended_return20_gt"])
            ) != (ready, over):
                raise ValueError("changed registered E semantics")
    return _hash(path)


def _symbols(decisions: tuple, cap: int) -> tuple[str, ...]:
    if len(decisions) < cap:
        raise ValueError(f"frozen universe has fewer than Top-{cap} rows")
    return tuple(d.symbol for d in sorted(decisions, key=lambda d: d.priority)[:cap])


def run_preflight(
    data: pd.DataFrame, *,
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mask = score_source_flags(data, event_review=events)
    info = []
    migrations = []
    for day, group in data.groupby("signal_date", sort=True):
        signal_day = str(day)
        base = replay_candidate_day(group, signal_date=signal_day, candidate_id="B0")
        b_by_symbol = {d.symbol: d for d in base}
        for candidate_id in IDS:
            alt = (
                base if candidate_id == "B0"
                else replay_candidate_day(
                    group, signal_date=signal_day, candidate_id=candidate_id,
                    baseline=base,
                )
            )
            by_symbol = {d.symbol: d for d in alt}
            if by_symbol.keys() != b_by_symbol.keys():
                raise ValueError("candidate changed the fixed historical universe")
            a5, b5 = _symbols(alt, 5), _symbols(base, 5)
            a15, b15 = _symbols(alt, 15), _symbols(base, 15)
            n_entry = sum(
                d.entry.state != b_by_symbol[d.symbol].entry.state
                for d in alt
            )
            n_action = sum(
                d.action_state != b_by_symbol[d.symbol].action_state
                for d in alt
            )
            info.append({
                "signal_date": signal_day,
                "candidate_id": candidate_id,
                "n_eligible": len(alt),
                "n_entry_state_changed": n_entry,
                "n_action_changed": n_action,
                "n_priority_review_changed": sum(
                    (d.action_state.value == "PRIORITY_REVIEW") !=
                    (b_by_symbol[d.symbol].action_state.value == "PRIORITY_REVIEW")
                    for d in alt
                ),
                "n_top5_swaps": 5 - len(set(a5) & set(b5)),
                "n_top15_swaps": 15 - len(set(a15) & set(b15)),
                "b0_top5": ";".join(b5),
                "candidate_top5": ";".join(a5),
                "b0_top15": ";".join(b15),
                "candidate_top15": ";".join(a15),
                "added_top15": ";".join(sorted(set(a15) - set(b15))),
                "removed_top15": ";".join(sorted(set(b15) - set(a15))),
            })
            if candidate_id in E_CANDIDATES:
                counts = Counter(
                    (b_by_symbol[sym].entry.state.value, d.entry.state.value)
                    for sym, d in by_symbol.items()
                    if b_by_symbol[sym].entry.state != d.entry.state
                )
                for (old_state, new_state), n in sorted(counts.items()):
                    migrations.append({
                        "signal_date": signal_day,
                        "candidate_id": candidate_id,
                        "entry_state_before": old_state,
                        "entry_state_after": new_state,
                        "n_rows": n,
                    })
    return (
        pd.DataFrame(info),
        pd.DataFrame(migrations, columns=[
            "signal_date", "candidate_id",
            "entry_state_before", "entry_state_after", "n_rows",
        ]),
        mask,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--entry-dataset", required=True)
    p.add_argument("--entry-meta", required=True)
    p.add_argument("--event-review", required=True)
    p.add_argument("--registry", default="configs/mvp_v11_candidate_registry.json")
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    out = Path(args.output_dir)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    inv = inspect_frozen_dataset(
        args.entry_dataset, expected_kind="entry_quality", metadata=args.entry_meta,
    )
    if inv["dataset_sha256"] != EXPECTED_DATA_SHA:
        raise ValueError("frozen historical v3 SHA mismatch")
    events_path = Path(args.event_review)
    if _hash(events_path) != EXPECTED_EVENT_REVIEW_SHA:
        raise ValueError("frozen event review SHA mismatch")
    registry_sha = verify_registry(Path(args.registry))
    frame = pd.read_csv(args.entry_dataset, low_memory=False)
    events = pd.read_csv(events_path, low_memory=False)
    memberships, migrations, score_mask = run_preflight(frame, events=events)
    if len(memberships) != 39 * len(IDS):
        raise ValueError("expected 39 frozen dates × 10 candidates")
    out.mkdir(parents=True)
    outputs = {
        "membership_by_date.csv": memberships,
        "entry_migrations_by_date.csv": migrations,
        "score_source_flags_local_only.csv": score_mask,
    }
    output_sha = {}
    for filename, output in outputs.items():
        path = out / filename
        output.to_csv(path, index=False)
        output_sha[filename] = _hash(path)
    manifest = {
        "status": "MEMBERSHIP_ONLY_NO_CANDIDATE_RETURNS",
        "ready_for_candidate_returns": False,
        "signal_dates": 39,
        "n_rows": inv["n_rows"],
        "candidate_ids": list(IDS),
        "x1_executed": False,
        "dataset_sha256": inv["dataset_sha256"],
        "metadata_sha256": inv["metadata_sha256"],
        "event_review_sha256": EXPECTED_EVENT_REVIEW_SHA,
        "candidate_registry_sha256": registry_sha,
        "output_sha256": output_sha,
        "code_sha": resolve_git_sha(),
        "seed": 0,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Outcome-blind historical MONTHLY attention-cap proxy only.",
            "The HEI/all-event score flags are retrospective sensitivity, never selection.",
            "No entry fill, benchmark/stock forward returns or candidate alpha evaluated.",
            "2025 / 2026 Q1 cannot be used to choose a new candidate.",
            "CI and bounded SEC provenance review must precede experiment authorization.",
        ],
    }
    (out / "preflight_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{manifest['status']}: {len(memberships)} date×candidate rows, {out}")


if __name__ == "__main__":
    main()
