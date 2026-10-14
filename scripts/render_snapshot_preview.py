"""Render a read-only v2 preview of a frozen decision snapshot.

Reads ``decisions.jsonl`` and ``run_manifest.json`` from ``--snapshot-dir``
without modifying anything there, and writes ``action_list_v2.md``,
``weekly_review_v2.md``, and ``detailed_v2/{SYMBOL}.md`` (for daily/weekly
symbols plus any Secondary Radar symbols) into ``--output-dir``.

Example:
    python scripts/render_snapshot_preview.py \
      --snapshot-dir outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off \
      --output-dir outputs/report_v2_preview_20261014/snap62
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_value_scanner.decision.model import stock_decisions_from_jsonl
from ai_value_scanner.decision.view_model import build_snapshot_view_model
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render v2 report preview from a frozen decision snapshot."
    )
    parser.add_argument("--snapshot-dir", required=True, help="Frozen snapshot directory.")
    parser.add_argument("--output-dir", required=True, help="Preview output directory.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    snapshot_dir = Path(args.snapshot_dir)
    output_dir = Path(args.output_dir)

    decisions_path = snapshot_dir / "decisions.jsonl"
    manifest_path = snapshot_dir / "run_manifest.json"
    if not decisions_path.exists():
        raise FileNotFoundError(f"missing decisions file: {decisions_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing manifest file: {manifest_path}")

    decisions = stock_decisions_from_jsonl(
        decisions_path.read_text(encoding="utf-8")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_symbol = {decision.symbol: decision for decision in decisions}

    daily_symbols = list(manifest.get("daily_symbols", []))
    weekly_symbols = list(manifest.get("weekly_symbols", []))
    daily = tuple(by_symbol[s] for s in daily_symbols if s in by_symbol)
    weekly = tuple(by_symbol[s] for s in weekly_symbols if s in by_symbol)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "action_list_v2.md").write_text(
        render_action_list(
            daily,
            title="Daily Action List",
            cadence="daily",
            layout_version="v2",
            all_decisions=decisions,
        ),
        encoding="utf-8",
    )
    (output_dir / "weekly_review_v2.md").write_text(
        render_action_list(
            weekly,
            title="Weekly Review List",
            cadence="weekly",
            layout_version="v2",
            all_decisions=decisions,
        ),
        encoding="utf-8",
    )

    daily_view = build_snapshot_view_model(
        daily, decisions, title="Daily Action List", cadence="daily"
    )
    weekly_view = build_snapshot_view_model(
        weekly, decisions, title="Weekly Review List", cadence="weekly"
    )
    symbols = (
        {card.symbol for card in daily_view.primary_cards}
        | {card.symbol for card in weekly_view.primary_cards}
        | {card.symbol for card in daily_view.cap_omitted_priority_cards}
        | {card.symbol for card in weekly_view.cap_omitted_priority_cards}
        | {card.symbol for card in daily_view.secondary_b_ready_cards}
        | {card.symbol for card in weekly_view.secondary_b_ready_cards}
    )
    detailed_dir = output_dir / "detailed_v2"
    detailed_dir.mkdir(parents=True, exist_ok=True)
    for symbol in sorted(symbols):
        (detailed_dir / f"{symbol}.md").write_text(
            render_detailed_report(by_symbol[symbol], layout_version="v2"),
            encoding="utf-8",
        )
    print(
        f"wrote action_list_v2.md + weekly_review_v2.md + "
        f"{len(symbols)} detailed_v2 files to {output_dir}"
    )


if __name__ == "__main__":
    main()
