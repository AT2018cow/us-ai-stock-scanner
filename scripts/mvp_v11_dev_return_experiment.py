"""PR-A 2023–2024 paired dev-only executor. DO NOT run without owner approval.

Offline, same frozen B0/R/E groups, fixed net-forward labels, complete
date-paired masks and prespecified sensitivity. Never computes 2025/2026
candidate outputs, X1, or product/production decisions. No network.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.fundamentals.edgartools_diagnostic import resolve_git_sha
from ai_value_scanner.research.mvp_v11 import _hash, inspect_frozen_dataset
from ai_value_scanner.research.mvp_v11_candidates import replay_candidate_day
from ai_value_scanner.research.mvp_v11_comparison import paired_topk_day
from ai_value_scanner.research.mvp_v11_dev_reports import paired_metrics, date_quality_report
from ai_value_scanner.research.mvp_v11_score_masks import score_source_flags
from scripts.mvp_v11_candidate_preflight import (
    EXPECTED_DATA_SHA, EXPECTED_EVENT_REVIEW_SHA, IDS, verify_registry,
)
from scripts.mvp_v11_event_exposure_preflight import build_event_interval_flags


EXPECTED_MEMBERSHIP_SHA = "bc9130edcb62c362d893166d69b7c363087f254ed91bca4127322faac93f6f60"
EXPECTED_AUDIT_SHA = "20dc8670c8de44781355c51d6381821b6cc64b00bab9162445af628cac3f9e31"
APPROVAL_PHRASE = "I_APPROVE_FROZEN_2023_2024_DEV_ONLY"
DATE_START = "2023-01-01"
DATE_END = "2024-12-31"
HORIZONS = (20, 60, 120)
CAPS = (5, 15)


def _expected(path: Path, digest: str, *, what: str) -> None:
    if not path.is_file() or _hash(path) != digest:
        raise ValueError(f"{what} absent or SHA mismatch; stop: {path}")


def _read_protocol(path: Path) -> tuple[dict, str]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if (
        content.get("schema_version") != "mvp_v11_dev_return_protocol_v1"
        or content.get("status") != "FROZEN_PROTOCOL_OWNER_APPROVAL_REQUIRED"
        or content.get("candidates") != list(IDS)
        or content.get("primary") != {
            "horizon_trading_days": 60,
            "topk": 15,
            "metric": "candidate minus B0 date-equal mean net QQQ-excess",
            "economic_reference_pp": 0.5,
            "selection": "human review only",
        }
        or content.get("periods", {}).get("development") != {
            "first": DATE_START, "last": DATE_END, "expected_dates": 24
        }
        or content.get("execution", {}).get("additional_transaction_cost_bps") != 0
    ):
        raise ValueError("unapproved or modified development return protocol")
    if content.get("periods", {}).get("temporal_2025") != "EMBARGOED":
        raise ValueError("2025 embargo removed")
    if content.get("periods", {}).get("temporal_2026_q1") != "EMBARGOED":
        raise ValueError("2026 Q1 embargo removed")
    return content, _hash(path)


def _net_return(labels: pd.DataFrame, day: str, symbol: str, horizon: int) -> float | None:
    row = labels.loc[(day, symbol)]
    a = pd.to_numeric(row[f"fwd_ret_{horizon}"], errors="coerce")
    b = pd.to_numeric(row[f"qqq_return_{horizon}"], errors="coerce")
    if pd.isna(a) or pd.isna(b):
        return None
    return float(a) - float(b)


def evaluate_development(
    frozen: pd.DataFrame,
    *,
    events: pd.DataFrame,
    event_review: pd.DataFrame,
    frozen_membership: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Only 24 development dates. Evaluation masks never modify scoring.

    Result is a research summary, not an auto-selected candidate.
    """
    required = {
        "signal_date", "symbol", "fundamental_data_asof",
        *(f"fwd_ret_{h}" for h in HORIZONS),
        *(f"qqq_return_{h}" for h in HORIZONS),
        *(f"label_end_{h}" for h in HORIZONS),
    }
    if not required.issubset(frozen):
        raise ValueError(f"missing frozen v3 fields: {sorted(required-set(frozen))}")
    data = frozen.loc[
        frozen.signal_date.astype(str).between(DATE_START, DATE_END)
    ].copy()
    days = sorted(data.signal_date.astype(str).unique())
    if len(days) != 24:
        raise ValueError(f"development period should contain 24 dates, found {len(days)}")
    if data.duplicated(["signal_date", "symbol"]).any():
        raise ValueError("duplicate source date×symbol")
    if len(frozen_membership) != 24 * len(IDS):
        raise ValueError("frozen membership should contain 240 rows")
    preflight = frozen_membership.set_index(
        ["signal_date", "candidate_id"], verify_integrity=True
    )
    labels = data.loc[:, [
        "signal_date", "symbol",
        *(f"fwd_ret_{h}" for h in HORIZONS),
        *(f"qqq_return_{h}" for h in HORIZONS),
    ]]
    # Both uncertainty sources independently pinned by CLI.
    score_flags = score_source_flags(data, event_review=event_review)
    event_flags, event_summary = build_event_interval_flags(
        data.loc[:, [
            "signal_date", "symbol", *(f"label_end_{h}" for h in HORIZONS)
        ]],
        events,
    )

    comparison_rows: list[dict] = []
    change_rows: list[dict] = []
    migrations: list[dict] = []
    for day in days:
        group = data[data.signal_date == day]
        group_labels = labels[labels.signal_date == day]
        group_events = event_flags[event_flags.signal_date == day]
        group_scores = score_flags[score_flags.signal_date == day]
        labels_index = group_labels.set_index(
            ["signal_date", "symbol"], verify_integrity=True
        )
        b0 = replay_candidate_day(group, signal_date=day, candidate_id="B0")
        original = {d.symbol: d for d in b0}
        for name in IDS:
            alt = (
                b0 if name == "B0" else replay_candidate_day(
                    group, signal_date=day, candidate_id=name, baseline=b0
                )
            )
            current = preflight.loc[(day, name)]
            for cap in CAPS:
                tag = "top5" if cap == 5 else "top15"
                actual = ";".join(d.symbol for d in alt[:cap])
                expected = str(current[f"candidate_{tag}"])
                if actual != expected:
                    raise ValueError(f"replay differs from frozen preflight {day} {name} {tag}")
                b0_str = ";".join(d.symbol for d in b0[:cap])
                if b0_str != str(current[f"b0_{tag}"]):
                    raise ValueError(f"B0 differs from frozen preflight {day} {tag}")
            n_entry = sum(
                d.entry.state != original[d.symbol].entry.state for d in alt
            )
            n_action = sum(
                d.action_state != original[d.symbol].action_state for d in alt
            )
            if n_entry != int(current.n_entry_state_changed) or n_action != int(current.n_action_changed):
                raise ValueError(f"migration differs from preflight {day} {name}")
            if name.startswith("E"):
                transition_counts = {}
                for d in alt:
                    old = original[d.symbol]
                    if d.entry.state != old.entry.state:
                        key = (old.entry.state.value, d.entry.state.value)
                        transition_counts[key] = transition_counts.get(key, 0) + 1
                for (before, after), count in sorted(transition_counts.items()):
                    migrations.append({
                        "signal_date": day, "candidate_id": name,
                        "entry_state_before": before,
                        "entry_state_after": after, "n_rows": count,
                    })

            for h in HORIZONS:
                for cap in CAPS:
                    compared = paired_topk_day(
                        signal_date=day, candidate_id=name, horizon=h, cap=cap,
                        baseline=b0, candidate=alt,
                        labels=group_labels, event_flags=group_events,
                        score_flags=group_scores,
                    )
                    comparison_rows.append(compared)
                    if h == 60 and cap == 15:
                        for direction, symbols, sign in (
                            ("added", compared["added_symbols"], 1),
                            ("removed", compared["removed_symbols"], -1),
                        ):
                            for symbol in filter(None, symbols.split(";")):
                                is_valid = bool(compared["primary_paired_valid"])
                                ret = (_net_return(labels_index, day, symbol, 60)
                                       if is_valid else None)
                                change_rows.append({
                                    "signal_date": day, "candidate_id": name,
                                    "direction": direction, "symbol": symbol,
                                    "b0_priority": original[symbol].priority,
                                    "candidate_priority": next(
                                        d.priority for d in alt if d.symbol == symbol
                                    ),
                                    "net_qqq_excess_h60": ret,
                                    "delta_contribution_to_top15": (
                                        sign * ret / 15 if ret is not None else None
                                    ),
                                    "date_pair_label_valid": is_valid,
                                    "score_source_uncertain": bool(
                                        group_scores.loc[
                                            group_scores.symbol == symbol,
                                            "score_source_uncertain",
                                        ].iloc[0]
                                    ),
                                })
    paired = pd.DataFrame(comparison_rows)
    if len(paired) != 24 * len(IDS) * len(HORIZONS) * len(CAPS):
        raise ValueError("expected 1440 paired candidate/date/horizon/cap rows")
    metrics = paired_metrics(paired)
    bottom = date_quality_report(paired)
    diff = pd.DataFrame(change_rows, columns=[
        "signal_date", "candidate_id", "direction", "symbol",
        "b0_priority", "candidate_priority", "net_qqq_excess_h60",
        "delta_contribution_to_top15", "date_pair_label_valid",
        "score_source_uncertain",
    ])
    migrations_frame = pd.DataFrame(migrations, columns=[
        "signal_date", "candidate_id", "entry_state_before",
        "entry_state_after", "n_rows",
    ])
    return paired, diff, migrations_frame, metrics, {
        "event_interval_summary": event_summary,
        "score_flag_counts_dev": {
            name: int(score_flags[name].sum()) for name in (
                "hei_scope_uncertain", "hei_source_confirmed_date",
                "missing_fundamental_asof", "severe_share_event_on_date",
                "score_source_uncertain",
            )
        },
        "bottom_three_primary_dates": bottom,
        "expected_date_count": 24,
        "candidate_count": len(IDS),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--authorize-2023-2024-dev-returns", required=True)
    p.add_argument("--expected-code-sha", required=True)
    p.add_argument("--entry-dataset", required=True)
    p.add_argument("--entry-meta", required=True)
    p.add_argument("--event-audit", required=True)
    p.add_argument("--event-review", required=True)
    p.add_argument("--frozen-membership", required=True)
    p.add_argument("--registry", default="configs/mvp_v11_candidate_registry.json")
    p.add_argument("--protocol", default="configs/mvp_v11_dev_return_protocol.json")
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    if args.authorize_2023_2024_dev_returns != APPROVAL_PHRASE:
        raise ValueError("explicit project-owner approval for fixed DEV-only returns required")
    sha = resolve_git_sha()
    if not sha or len(sha) != 40 or sha != args.expected_code_sha:
        raise ValueError("code SHA not pinned to exact current Git HEAD")
    out = Path(args.output_dir)
    if out.exists():
        raise ValueError("will not overwrite existing experiment: " + str(out))
    protocol, protocol_sha = _read_protocol(Path(args.protocol))
    inventory = inspect_frozen_dataset(
        args.entry_dataset, expected_kind="entry_quality", metadata=args.entry_meta
    )
    if inventory["dataset_sha256"] != EXPECTED_DATA_SHA:
        raise ValueError("v3 dataset SHA mismatch")
    for path, digest, name in (
        (Path(args.event_audit), EXPECTED_AUDIT_SHA, "52-event original audit"),
        (Path(args.event_review), EXPECTED_EVENT_REVIEW_SHA, "52-event review"),
        (Path(args.frozen_membership), EXPECTED_MEMBERSHIP_SHA, "frozen 240 membership"),
    ):
        _expected(path, digest, what=name)
    registry_sha = verify_registry(Path(args.registry))
    if protocol["candidate_registry_sha256"] != registry_sha:
        raise ValueError("changed frozen registry")
    if protocol["dataset_sha256"] != inventory["dataset_sha256"]:
        raise ValueError("protocol dataset reference mismatch")
    if protocol["risk_event_audit_sha256"] != EXPECTED_AUDIT_SHA:
        raise ValueError("protocol audit reference mismatch")
    data = pd.read_csv(args.entry_dataset, low_memory=False)
    events = pd.read_csv(args.event_audit, low_memory=False)
    review = pd.read_csv(args.event_review, low_memory=False)
    membership = pd.read_csv(args.frozen_membership, low_memory=False)
    paired, diff, migrations, metrics, diagnostics = evaluate_development(
        data, events=events, event_review=review, frozen_membership=membership,
    )
    out.mkdir(parents=True)
    outputs = {
        "paired_by_date.csv": paired,
        "top15_diff_cases.csv": diff,
        "entry_state_migrations.csv": migrations,
        "metrics_by_period.csv": metrics,
    }
    hashes = {}
    for filename, frame in outputs.items():
        destination = out / filename
        frame.to_csv(destination, index=False)
        hashes[filename] = _hash(destination)
    main_metrics = metrics[
        (metrics.horizon == 60) & (metrics.cap == 15)
    ]
    warning = [
        "# Risk and missingness — retrospective monthly attention-cap proxy",
        "",
        "The v3 stock and QQQ forward return legs are already net of estimated",
        "15bps entry + 15bps exit per leg. No second cost was applied.",
        "This is NOT an executed portfolio NAV or a fresh independent OOS.",
        "Data universe is retrospective / union_superset_approx.",
        "",
        "Known risk: HEI mixed share-class and weighted-average denominators;",
        "51 unresolved audit-only events, incomplete historical SEC CIK/accession",
        "source binding; WOLF already nulled labels; possible true rallies.",
        "Masks never changed historical ranks; sensitivity drops entire",
        "paired dates when *either* B0 or candidate contains a flagged name.",
        "",
        "## Primary Top-15 60d paired date coverage",
        "",
        "| ID | Valid / 24 | Event sensitivity | Score sensitivity |",
        "|---|---:|---:|---:|",
    ]
    for row in main_metrics.itertuples(index=False):
        warning.append(
            f"| {row.candidate_id} | {row.n_dates_valid} / 24 | "
            f"{row.n_dates_event_sensitivity} | "
            f"{row.n_dates_score_sensitivity} |"
        )
    (out / "risk_and_missingness.md").write_text(
        "\n".join(warning) + "\n", encoding="utf-8",
    )
    recommendation = [
        "# PR-A dev-only return results — pending human interpretation",
        "",
        "**Status: AWAITING_REVIEW / NO AUTOMATIC GO**.",
        "Economic reference: mean 60d Top-15 B0-paired net QQQ-excess",
        "improvement of at least +0.5 percentage points (=0.005 in label",
        "decimal units) is only an initial screen, NOT statistical evidence.",
        "Any winning candidate needs 2025 direction check *after it is locked*",
        "and review of concentration, three worst dates, missingness, and",
        "source-PIT/HEI sensitivity. X1 was not executed.",
        "",
        "## Pre-registered 60d Top-15 development summary",
        "",
        "| ID | Paired dates | Delta (pp) | Event sensitivity (pp) | Score sensitivity (pp) | Swaps |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    def display(x: object) -> str:
        return "NA" if pd.isna(x) else f"{float(x)*100:+.3f}"
    for row in main_metrics.itertuples(index=False):
        recommendation.append(
            f"| {row.candidate_id} | {row.n_dates_valid} | "
            f"{display(row.mean_paired_delta)} | "
            f"{display(row.mean_event_sensitive_delta)} | "
            f"{display(row.mean_score_sensitive_delta)} | "
            f"{row.n_total_topk_swaps} |"
        )
    recommendation.extend([
        "",
        "No winner automatically selected. Read paired_by_date.csv,",
        "top15_diff_cases.csv and full 20/60/120 Top-5/15 metrics before",
        "GO/INCONCLUSIVE/KEEP_V1. Never fit to 2025 or 2026Q1.",
        "",
    ])
    (out / "decision_recommendation.md").write_text(
        "\n".join(recommendation), encoding="utf-8"
    )
    inventory_file = out / "dataset_inventory.csv"
    pd.DataFrame([{
        "n_rows": inventory["n_rows"], "n_symbols": inventory["n_symbols"],
        "n_signal_dates": inventory["n_signal_dates"],
        "dataset_sha256": inventory["dataset_sha256"],
        "metadata_sha256": inventory["metadata_sha256"],
        "universe": "retrospective/union_superset_approx",
    }]).to_csv(inventory_file, index=False)
    # Preserve evidence manifest and hash exact output files.
    for name in ("risk_and_missingness.md", "decision_recommendation.md", "dataset_inventory.csv"):
        hashes[name] = _hash(out / name)
    manifest = {
        "status": "DEV_RETURNS_ONLY_AWAITING_REVIEW",
        "candidate_ids": list(IDS),
        "x1_executed": False,
        "temporal_2025_2026_embargoed": True,
        "ready_for_candidate_promotion": False,
        "code_sha": sha, "protocol_sha256": protocol_sha,
        "dataset_sha256": inventory["dataset_sha256"],
        "metadata_sha256": inventory["metadata_sha256"],
        "candidate_registry_sha256": registry_sha,
        "frozen_membership_sha256": EXPECTED_MEMBERSHIP_SHA,
        "risk_audit_sha256": EXPECTED_AUDIT_SHA,
        "risk_review_sha256": EXPECTED_EVENT_REVIEW_SHA,
        "output_sha256": hashes,
        "label_cost_convention": "both stock and QQQ 30bps roundtrip included",
        "seed": 0,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "24 dates 2023–2024; no 2025/2026 outcomes; monthly proxy",
        "diagnostics": diagnostics,
    }
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hashes["run_manifest.json"] = _hash(out / "run_manifest.json")
    (out / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())),
        encoding="utf-8",
    )
    print(f"DEV_RETURNS_ONLY_AWAITING_REVIEW: {len(paired)} paired date rows; {out}")


if __name__ == "__main__":
    main()
