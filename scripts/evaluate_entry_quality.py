"""Evaluate retrospective Entry Quality v1 states conditional on Quality A/B.

Input must come from:
    scripts/extract_weight_dataset.py --dataset-kind entry_quality

The evaluator does not tune Entry thresholds. It applies the frozen Company
Quality v1 policy first, keeps Quality A/B observations, then applies the frozen
Entry Quality v1 state machine and reports retrospective state diagnostics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.decision.entry import ENTRY_POLICY_VERSION
from ai_value_scanner.decision.quality import QUALITY_POLICY_VERSION
from ai_value_scanner.evaluation.entry_quality import (
    build_entry_quality_evaluation_frame,
    build_entry_state_transitions,
    summarize_entry_state_cohorts,
    summarize_entry_state_concentration,
    summarize_entry_state_persistence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate retrospective Entry Quality v1 state cohorts."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Default: dataset stem with _entry_v1 suffix in the same directory.",
    )
    parser.add_argument("--horizons", default="20,60,120")
    return parser


def _fmt(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    if frame.empty:
        return ["- no rows"]
    cols = [column for column in columns if column in frame.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in frame.loc[:, cols].iterrows():
        lines.append("| " + " | ".join(_fmt(row[col]) for col in cols) + " |")
    return lines


def _render_report(
    decisions: pd.DataFrame,
    cohorts: pd.DataFrame,
    concentration: pd.DataFrame,
    persistence: pd.DataFrame,
    *,
    dataset_path: Path,
    dataset_meta: dict[str, Any],
) -> str:
    lines = [
        "# Entry Quality v1 — Retrospective State Evaluation",
        "",
        "> Retrospective diagnostic only. This is not OOS evidence and does not",
        "> auto-promote Entry thresholds or production behavior.",
        "",
        f"- Entry policy version: {ENTRY_POLICY_VERSION}",
        f"- Company Quality policy version: {QUALITY_POLICY_VERSION}",
        f"- Input dataset: {dataset_path}",
        f"- Dataset kind: {dataset_meta.get('dataset_kind', 'unknown')}",
        f"- Watchlist source: {dataset_meta.get('watchlist_source', 'unknown')}",
        f"- Pre-strategy cross-section: {dataset_meta.get('pre_strategy_cross_section', False)}",
        f"- Quality A/B decision rows: {len(decisions)}",
        "",
        "## Entry state counts",
        "",
    ]

    counts = (
        decisions["entry_state"].value_counts(dropna=False)
        .rename_axis("entry_state")
        .reset_index(name="count")
    )
    lines.extend(_markdown_table(counts, ["entry_state", "count"]))

    lines.extend(["", "## Overall state cohorts", ""])
    overall = cohorts[cohorts["segment_type"] == "overall"].copy()
    lines.extend(
        _markdown_table(
            overall,
            [
                "entry_state",
                "horizon_days",
                "n_valid_return",
                "n_dates",
                "mean_return",
                "mean_excess_vs_qqq",
                "hit_rate",
                "date_equal_weight_mean_return",
                "date_equal_weight_mean_excess_vs_qqq",
                "worst_date_mean_return",
                "worst_date_mean_excess_vs_qqq",
            ],
        )
    )

    lines.extend(["", "## Concentration", ""])
    lines.extend(
        _markdown_table(
            concentration,
            [
                "entry_state",
                "n_decisions",
                "n_symbols",
                "n_dates",
                "top_symbol",
                "top_symbol_share",
                "top_date",
                "top_date_share",
            ],
        )
    )

    lines.extend(["", "## State persistence", ""])
    lines.extend(
        _markdown_table(
            persistence,
            [
                "from_state",
                "n_transitions",
                "same_state_rate",
                "median_gap_days",
            ],
        )
    )

    lines.extend(
        [
            "",
            "## Validation discipline",
            "",
            "- Entry thresholds are frozen in docs/entry_quality_v1_policy.md before final outcome inspection.",
            "- Entry evaluation is conditioned on Company Quality A/B.",
            "- The dataset is drawn before legacy list-specific hard gates.",
            "- ENTRY_READY explicitly excludes extreme recent-return / SMA50-extension cases.",
            "- Year, regime and Quality-grade splits are stored in the cohort CSV.",
            "- Transition diagnostics describe consecutive Quality-eligible observations for each symbol.",
            "- Long-horizon overlapping observations are not presented as independent statistical significance.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset)
    meta_path = dataset_path.with_suffix(".meta.json")
    if not meta_path.exists():
        raise ValueError(
            f"missing dataset provenance metadata: {meta_path}; "
            "Entry Quality evaluation requires replay provenance"
        )

    dataset_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if dataset_meta.get("dataset_kind") != "entry_quality":
        raise ValueError(
            "dataset_kind must be 'entry_quality'; regenerate the pre-strategy "
            "dataset with the Entry Quality feature contract"
        )
    if dataset_meta.get("pre_strategy_cross_section") is not True:
        raise ValueError(
            "Entry Quality evaluation requires a pre-strategy cross-section"
        )

    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    frame = pd.read_csv(dataset_path, low_memory=False)
    decisions = build_entry_quality_evaluation_frame(frame)
    if decisions.empty:
        raise ValueError(
            "no Quality A/B observations available for Entry Quality evaluation"
        )

    cohorts = summarize_entry_state_cohorts(decisions, horizons=horizons)
    concentration = summarize_entry_state_concentration(decisions)
    transitions = build_entry_state_transitions(decisions)
    persistence = summarize_entry_state_persistence(decisions)

    prefix = (
        Path(args.output_prefix)
        if args.output_prefix
        else dataset_path.with_name(f"{dataset_path.stem}_entry_v1")
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)

    decisions_path = prefix.with_name(f"{prefix.name}_decisions.csv")
    cohorts_path = prefix.with_name(f"{prefix.name}_cohorts.csv")
    concentration_path = prefix.with_name(f"{prefix.name}_concentration.csv")
    transitions_path = prefix.with_name(f"{prefix.name}_transitions.csv")
    persistence_path = prefix.with_name(f"{prefix.name}_persistence.csv")
    report_path = prefix.with_name(f"{prefix.name}_report.md")
    output_meta_path = prefix.with_name(f"{prefix.name}_meta.json")

    decisions.to_csv(decisions_path, index=False)
    cohorts.to_csv(cohorts_path, index=False)
    concentration.to_csv(concentration_path, index=False)
    transitions.to_csv(transitions_path, index=False)
    persistence.to_csv(persistence_path, index=False)
    report_path.write_text(
        _render_report(
            decisions,
            cohorts,
            concentration,
            persistence,
            dataset_path=dataset_path,
            dataset_meta=dataset_meta,
        ),
        encoding="utf-8",
    )

    output_meta = {
        "evaluation": "entry_quality_v1_retrospective",
        "entry_policy_version": ENTRY_POLICY_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "input_dataset": str(dataset_path),
        "input_dataset_meta": dataset_meta,
        "horizons": horizons,
        "quality_condition": ["A", "B"],
        "n_decisions": int(len(decisions)),
        "outputs": {
            "decisions": str(decisions_path),
            "cohorts": str(cohorts_path),
            "concentration": str(concentration_path),
            "transitions": str(transitions_path),
            "persistence": str(persistence_path),
            "report": str(report_path),
        },
    }
    output_meta_path.write_text(
        json.dumps(
            output_meta,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Entry Quality v1 decisions: {decisions_path}")
    print(f"State cohort diagnostics: {cohorts_path}")
    print(f"State transitions: {transitions_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
