"""Evaluate pre-strategy historical Company Quality v1 decisions.

Input must come from:
    scripts/extract_weight_dataset.py --dataset-kind company_quality

The evaluator does not tune thresholds. It applies the pre-registered policy,
attaches the resulting Quality decision fields, and reports retrospective
cohort diagnostics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.decision.quality import QUALITY_POLICY_VERSION
from ai_value_scanner.evaluation.company_quality import (
    apply_company_quality_v1,
    summarize_quality_cohorts,
    summarize_quality_concentration,
    summarize_quality_rank_correlation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate retrospective Company Quality v1 cohorts."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Default: dataset stem with _quality_v1 suffix in the same directory.",
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
    rank_ic: pd.DataFrame,
    *,
    dataset_path: Path,
    dataset_meta: dict[str, Any],
) -> str:
    lines = [
        "# Company Quality v1 — Retrospective Cohort Evaluation",
        "",
        "> Retrospective diagnostic only. This is not OOS evidence and does not",
        "> auto-promote thresholds or production behavior.",
        "",
        f"- Policy version: {QUALITY_POLICY_VERSION}",
        f"- Input dataset: {dataset_path}",
        f"- Dataset kind: {dataset_meta.get('dataset_kind', 'unknown')}",
        f"- Watchlist source: {dataset_meta.get('watchlist_source', 'unknown')}",
        f"- Pre-strategy cross-section: {dataset_meta.get('pre_strategy_cross_section', False)}",
        f"- Decision rows: {len(decisions)}",
        "",
        "## Grade counts",
        "",
    ]
    counts = (
        decisions["quality_grade"].value_counts(dropna=False)
        .rename_axis("quality_grade")
        .reset_index(name="count")
    )
    lines.extend(_markdown_table(counts, ["quality_grade", "count"]))

    lines.extend(["", "## Overall cohorts", ""])
    overall = cohorts[cohorts["segment_type"] == "overall"].copy()
    lines.extend(
        _markdown_table(
            overall,
            [
                "quality_grade",
                "horizon_days",
                "n_valid_return",
                "n_dates",
                "mean_return",
                "mean_excess_vs_qqq",
                "hit_rate",
                "date_equal_weight_mean_return",
                "date_equal_weight_mean_excess_vs_qqq",
            ],
        )
    )

    lines.extend(["", "## Concentration", ""])
    lines.extend(
        _markdown_table(
            concentration,
            [
                "quality_grade",
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

    lines.extend(["", "## Cross-sectional rank correlation", ""])
    lines.extend(
        _markdown_table(
            rank_ic,
            [
                "horizon_days",
                "n_dates_return_ic",
                "mean_spearman_return",
                "n_dates_excess_ic",
                "mean_spearman_excess_vs_qqq",
            ],
        )
    )

    lines.extend(
        [
            "",
            "## Validation discipline",
            "",
            "- Thresholds are defined in docs/company_quality_v1_policy.md before outcome inspection.",
            "- The dataset is drawn before legacy list-specific hard gates.",
            "- Historical watchlist provenance is preserved; union/frozen approximations remain labelled.",
            "- Date-equal-weight cohort fields are reported so symbol rows are not treated as independent evidence.",
            "- Year and regime splits are stored in the cohort CSV even when not expanded in this compact report.",
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
            "Company Quality evaluation requires replay provenance"
        )
    dataset_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if dataset_meta.get("dataset_kind") != "company_quality":
        raise ValueError(
            "dataset_kind must be 'company_quality'; do not evaluate a legacy "
            "hard-gate survivor dataset as Company Quality evidence"
        )
    if dataset_meta.get("pre_strategy_cross_section") is not True:
        raise ValueError("Company Quality evaluation requires a pre-strategy cross-section")

    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    frame = pd.read_csv(dataset_path, low_memory=False)
    decisions = apply_company_quality_v1(frame)
    cohorts = summarize_quality_cohorts(decisions, horizons=horizons)
    concentration = summarize_quality_concentration(decisions)
    rank_ic = summarize_quality_rank_correlation(decisions, horizons=horizons)

    prefix = (
        Path(args.output_prefix)
        if args.output_prefix
        else dataset_path.with_name(f"{dataset_path.stem}_quality_v1")
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)
    decisions_path = prefix.with_name(f"{prefix.name}_decisions.csv")
    cohorts_path = prefix.with_name(f"{prefix.name}_cohorts.csv")
    concentration_path = prefix.with_name(f"{prefix.name}_concentration.csv")
    rank_ic_path = prefix.with_name(f"{prefix.name}_rank_ic.csv")
    report_path = prefix.with_name(f"{prefix.name}_report.md")
    output_meta_path = prefix.with_name(f"{prefix.name}_meta.json")

    decisions.to_csv(decisions_path, index=False)
    cohorts.to_csv(cohorts_path, index=False)
    concentration.to_csv(concentration_path, index=False)
    rank_ic.to_csv(rank_ic_path, index=False)
    report_path.write_text(
        _render_report(
            decisions,
            cohorts,
            concentration,
            rank_ic,
            dataset_path=dataset_path,
            dataset_meta=dataset_meta,
        ),
        encoding="utf-8",
    )
    output_meta = {
        "evaluation": "company_quality_v1_retrospective",
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "input_dataset": str(dataset_path),
        "input_dataset_meta": dataset_meta,
        "horizons": horizons,
        "n_decisions": int(len(decisions)),
        "outputs": {
            "decisions": str(decisions_path),
            "cohorts": str(cohorts_path),
            "concentration": str(concentration_path),
            "rank_ic": str(rank_ic_path),
            "report": str(report_path),
        },
    }
    output_meta_path.write_text(
        json.dumps(output_meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Company Quality v1 decisions: {decisions_path}")
    print(f"Cohort diagnostics: {cohorts_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
