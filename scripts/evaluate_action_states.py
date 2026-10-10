"""Evaluate integrated Quality × Entry → Action states retrospectively.

Input must be an Entry Quality replay dataset so both frozen Company Quality and
Entry Quality policies can be reconstructed on the same pre-strategy PIT rows.
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
from ai_value_scanner.decision.integrated import DEFAULT_ATTENTION_CAP
from ai_value_scanner.decision.quality import QUALITY_POLICY_VERSION
from ai_value_scanner.evaluation.action import (
    build_action_evaluation_frame,
    summarize_action_cohorts,
    summarize_action_compactness,
    summarize_action_concentration,
    summarize_action_transitions,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate retrospective integrated Action states."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-prefix", default=None)
    parser.add_argument("--horizons", default="20,60,120")
    parser.add_argument(
        "--attention-cap",
        type=int,
        default=DEFAULT_ATTENTION_CAP,
    )
    return parser


def _fmt(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _table(frame: pd.DataFrame, columns: list[str]) -> list[str]:
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


def _report(
    action_frame: pd.DataFrame,
    cohorts: pd.DataFrame,
    compactness: pd.DataFrame,
    concentration: pd.DataFrame,
    *,
    dataset_path: Path,
    meta: dict[str, Any],
    attention_cap: int,
) -> str:
    lines = [
        "# Integrated Action-state retrospective evaluation",
        "",
        "> Retrospective diagnostic only. This is not OOS evidence and cannot",
        "> automatically promote thresholds or production behavior.",
        "",
        f"- Company Quality policy: {QUALITY_POLICY_VERSION}",
        f"- Entry Quality policy: {ENTRY_POLICY_VERSION}",
        f"- Input dataset: {dataset_path}",
        f"- Watchlist source: {meta.get('watchlist_source', 'unknown')}",
        f"- Pre-strategy cross-section: {meta.get('pre_strategy_cross_section', False)}",
        f"- Attention cap: {attention_cap}",
        "",
        "## Action counts",
        "",
    ]
    counts = (
        action_frame["action_state"]
        .value_counts()
        .rename_axis("action_state")
        .reset_index(name="count")
    )
    lines.extend(_table(counts, ["action_state", "count"]))

    lines.extend(["", "## Overall Action cohorts", ""])
    overall = cohorts[cohorts["segment_type"] == "overall"]
    lines.extend(
        _table(
            overall,
            [
                "action_state",
                "horizon_days",
                "n_valid_return",
                "n_dates",
                "mean_return",
                "mean_excess_vs_qqq",
                "hit_rate",
                "date_equal_weight_mean_return",
                "date_equal_weight_mean_excess_vs_qqq",
                "worst_date_mean_return",
            ],
        )
    )

    lines.extend(["", "## Attention compactness", ""])
    if compactness.empty:
        lines.append("- no rows")
    else:
        summary = pd.DataFrame(
            [
                {
                    "n_dates": int(len(compactness)),
                    "mean_non_avoid": float(compactness["n_non_avoid"].mean()),
                    "median_non_avoid": float(compactness["n_non_avoid"].median()),
                    "mean_capped_attention": float(
                        compactness["capped_attention_count"].mean()
                    ),
                    "max_capped_attention": int(
                        compactness["capped_attention_count"].max()
                    ),
                    "dates_over_cap": int(
                        (compactness["suppressed_by_cap"] > 0).sum()
                    ),
                }
            ]
        )
        lines.extend(
            _table(
                summary,
                [
                    "n_dates",
                    "mean_non_avoid",
                    "median_non_avoid",
                    "mean_capped_attention",
                    "max_capped_attention",
                    "dates_over_cap",
                ],
            )
        )

    lines.extend(["", "## Concentration", ""])
    lines.extend(
        _table(
            concentration,
            [
                "action_state",
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

    lines.extend(
        [
            "",
            "## Validation discipline",
            "",
            "- Quality and Entry policies remain the frozen v1 policies.",
            "- Action mapping is the canonical deterministic mapping.",
            "- Year and regime splits are stored in the cohort CSV.",
            "- Capped attention counts measure product compression, not portfolio sizing.",
            "- Overlapping long-horizon labels are not treated as independent significance.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset)
    meta_path = dataset_path.with_suffix(".meta.json")
    if not meta_path.exists():
        raise ValueError(f"missing dataset metadata: {meta_path}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("dataset_kind") != "entry_quality":
        raise ValueError(
            "integrated Action evaluation requires --dataset-kind entry_quality"
        )
    if meta.get("pre_strategy_cross_section") is not True:
        raise ValueError("integrated Action evaluation requires pre-strategy rows")

    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    cap = max(1, int(args.attention_cap))
    frame = pd.read_csv(dataset_path, low_memory=False)
    action_frame = build_action_evaluation_frame(frame)
    cohorts = summarize_action_cohorts(action_frame, horizons=horizons)
    compactness = summarize_action_compactness(action_frame, attention_cap=cap)
    concentration = summarize_action_concentration(action_frame)
    transitions = summarize_action_transitions(action_frame)

    prefix = (
        Path(args.output_prefix)
        if args.output_prefix
        else dataset_path.with_name(f"{dataset_path.stem}_action_v1")
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)

    outputs = {
        "decisions": prefix.with_name(f"{prefix.name}_decisions.csv"),
        "cohorts": prefix.with_name(f"{prefix.name}_cohorts.csv"),
        "compactness": prefix.with_name(f"{prefix.name}_compactness.csv"),
        "concentration": prefix.with_name(f"{prefix.name}_concentration.csv"),
        "transitions": prefix.with_name(f"{prefix.name}_transitions.csv"),
        "report": prefix.with_name(f"{prefix.name}_report.md"),
        "meta": prefix.with_name(f"{prefix.name}_meta.json"),
    }

    action_frame.to_csv(outputs["decisions"], index=False)
    cohorts.to_csv(outputs["cohorts"], index=False)
    compactness.to_csv(outputs["compactness"], index=False)
    concentration.to_csv(outputs["concentration"], index=False)
    transitions.to_csv(outputs["transitions"], index=False)
    outputs["report"].write_text(
        _report(
            action_frame,
            cohorts,
            compactness,
            concentration,
            dataset_path=dataset_path,
            meta=meta,
            attention_cap=cap,
        ),
        encoding="utf-8",
    )
    outputs["meta"].write_text(
        json.dumps(
            {
                "evaluation": "integrated_action_state_retrospective",
                "quality_policy_version": QUALITY_POLICY_VERSION,
                "entry_policy_version": ENTRY_POLICY_VERSION,
                "input_dataset": str(dataset_path),
                "attention_cap": cap,
                "horizons": horizons,
                "outputs": {key: str(value) for key, value in outputs.items() if key != "meta"},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Action decisions: {outputs['decisions']}")
    print(f"Action cohorts: {outputs['cohorts']}")
    print(f"Action compactness: {outputs['compactness']}")
    print(f"Report: {outputs['report']}")


if __name__ == "__main__":
    main()
