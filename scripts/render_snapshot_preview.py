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
from dataclasses import replace
from datetime import date
from pathlib import Path

from ai_value_scanner.decision.action import (
    assign_action_priorities_v2,
    map_action_state_v2,
)
from ai_value_scanner.decision.entry import (
    ENTRY_V2_EXTENSION_MILD_PENALTY,
    ENTRY_V2_EXTENSION_SEVERE_PENALTY,
    ENTRY_V2_RET60_EXTENDED_SEVERE,
    ENTRY_V2_RET60_EXTENDED_WARN,
    ENTRY_V2_SMA200_EXTENDED_SEVERE,
    ENTRY_V2_SMA200_EXTENDED_WARN,
)
from ai_value_scanner.decision.integrated import (
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.decision.model import (
    EvidenceItem,
    StockDecision,
    stock_decisions_from_jsonl,
    stock_decisions_to_jsonl,
)
from ai_value_scanner.decision.quality import (
    QUALITY_V2_ORGANIC_SHARES_YOY_MAX,
    QUALITY_V2_ORGANIC_SHARES_YOY_MIN,
    QUALITY_V2_PRE_EARNINGS_WARN_DAYS,
    QUALITY_V1_STALE_WARN_DAYS,
)
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
    parser.add_argument(
        "--recompute-v2",
        action="store_true",
        default=False,
        help=(
            "Recompute v2 Quality/Entry/Action adjustments on the loaded "
            "decisions (read-only wrt --snapshot-dir) and write "
            "action_list_v2.md, weekly_review_v2.md, detailed_v2/*.md and "
            "decisions_recomputed_v2.jsonl into --output-dir."
        ),
    )
    return parser.parse_args()


def _evidence_number(decision: StockDecision, metric: str) -> float | None:
    """First finite numeric evidence value for a metric across quality sides."""
    items = (
        *decision.quality.risks,
        *decision.quality.positives,
        *decision.quality.missing,
        *decision.entry.risks,
        *decision.entry.positives,
    )
    for item in items:
        if (item.metric or "") != metric:
            continue
        value = item.value
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and abs(number) != float("inf"):
            return number
    return None


def _risk_codes(decision: StockDecision) -> set[str]:
    return {item.code for item in (*decision.quality.risks, *decision.entry.risks)}


def _filing_age_days(decision: StockDecision) -> int | None:
    """Age of the quality data_asof vs the decision date, in days."""
    try:
        asof = decision.quality.data_asof
        if not asof:
            return None
        return (date.fromisoformat(decision.decision_date[:10])
                - date.fromisoformat(str(asof)[:10])).days
    except (TypeError, ValueError):
        return None


def _with_quality_v2_adjustments(decision: StockDecision) -> StockDecision:
    """Overlay v2 quality guards (split/basis + pre-earnings) idempotently."""
    quality = decision.quality
    codes = {item.code for item in quality.risks}
    positives = list(quality.positives)
    risks = list(quality.risks)
    components = dict(quality.component_scores or {})
    new_score = quality.score
    changed = False
    shares_yoy = _evidence_number(decision, "shares_yoy")
    if (
        shares_yoy is not None
        and (
            shares_yoy < QUALITY_V2_ORGANIC_SHARES_YOY_MIN
            or shares_yoy > QUALITY_V2_ORGANIC_SHARES_YOY_MAX
        )
        and "shares_yoy_split_or_basis_discontinuity" not in codes
    ):
        positives = [i for i in positives if (i.metric or "") != "shares_yoy"]
        risks = [i for i in risks if (i.metric or "") != "shares_yoy"]
        old_dil = components.get("dilution")
        if isinstance(old_dil, (int, float)) and isinstance(new_score, (int, float)):
            new_score = round(
                max(0.0, min(1.0, float(new_score) + 0.10 * (0.50 - float(old_dil)))),
                6,
            )
        risks.append(
            EvidenceItem(
                code="shares_yoy_split_or_basis_discontinuity",
                label="Share-count split / basis discontinuity",
                polarity="negative",  # type: ignore[arg-type]
                metric="shares_yoy",
                value=round(shares_yoy, 6),
                threshold="-30% to +100% organic YoY range",
                message=(
                    f"Reported YoY share change ({shares_yoy * 100:+.1f}%) is outside "
                    "the organic buyback/issuance band and likely reflects a stock split "
                    "or share-basis discontinuity; dilution score neutralized to 0.50 and "
                    "per-share YoY metrics require manual verification."
                ),
            )
        )
        components["dilution"] = 0.50
        changed = True
    age_days = _filing_age_days(decision)
    if (
        age_days is not None
        and QUALITY_V2_PRE_EARNINGS_WARN_DAYS <= age_days <= QUALITY_V1_STALE_WARN_DAYS
        and "pre_earnings_window_risk" not in codes
    ):
        risks.append(
            EvidenceItem(
                code="pre_earnings_window_risk",
                label="Pre-earnings window (aging filing)",
                polarity="negative",  # type: ignore[arg-type]
                metric="fundamental_data_age_days",
                value=age_days,
                threshold=f"<{QUALITY_V2_PRE_EARNINGS_WARN_DAYS}d before next quarterly window",
                message=(
                    f"Latest periodic filing is {age_days}d old (~90d quarterly cycle); "
                    "next earnings release is likely imminent (binary event risk)."
                ),
            )
        )
        changed = True
    if not changed:
        return decision
    return replace(
        decision,
        quality=replace(
            decision.quality,
            score=new_score,
            positives=tuple(positives),
            risks=tuple(risks),
            component_scores=components,
        ),
    )


def _with_entry_v2_adjustments(decision: StockDecision) -> StockDecision:
    """Overlay v2 medium-term extension deductions idempotently (state kept)."""
    entry = decision.entry
    codes = {item.code for item in entry.risks}
    risks = list(entry.risks)
    score = entry.score if entry.score is not None else 0.0
    sma200 = _evidence_number(decision, "price_to_sma200")
    if (
        sma200 is not None
        and sma200 > ENTRY_V2_SMA200_EXTENDED_WARN
        and "price_extended_above_sma200" not in codes
    ):
        penalty = (
            ENTRY_V2_EXTENSION_SEVERE_PENALTY
            if sma200 > ENTRY_V2_SMA200_EXTENDED_SEVERE
            else ENTRY_V2_EXTENSION_MILD_PENALTY
        )
        score = max(0.0, round(score - penalty, 6))
        risks.append(
            EvidenceItem(
                code="price_extended_above_sma200",
                label="Extended above SMA200",
                polarity="negative",  # type: ignore[arg-type]
                metric="price_to_sma200",
                value=round(sma200, 6),
                threshold=f"<={ENTRY_V2_SMA200_EXTENDED_WARN:.2f}x preferred",
                message=(
                    f"Price is {sma200:.2f}x 200d SMA (>{ENTRY_V2_SMA200_EXTENDED_WARN:.2f}x medium-term extension); "
                    "entry score reduced to reflect thinner margin of safety vs long-term trend."
                ),
            )
        )
    return_60d = _evidence_number(decision, "return_60d")
    if (
        return_60d is not None
        and return_60d > ENTRY_V2_RET60_EXTENDED_WARN
        and "return_60d_extended" not in codes
    ):
        penalty = (
            ENTRY_V2_EXTENSION_SEVERE_PENALTY
            if return_60d > ENTRY_V2_RET60_EXTENDED_SEVERE
            else ENTRY_V2_EXTENSION_MILD_PENALTY
        )
        score = max(0.0, round(score - penalty, 6))
        risks.append(
            EvidenceItem(
                code="return_60d_extended",
                label="60d rally extended",
                polarity="negative",  # type: ignore[arg-type]
                metric="return_60d",
                value=round(return_60d, 6),
                threshold=f"<={ENTRY_V2_RET60_EXTENDED_WARN:.0%} preferred",
                message=(
                    f"60d return is {return_60d * 100:+.1f}% (>{ENTRY_V2_RET60_EXTENDED_WARN:.0%} quarterly surge); "
                    "entry score reduced to penalize medium-term momentum chasing."
                ),
            )
        )
    if len(risks) == len(entry.risks):
        return decision
    return replace(
        decision, entry=replace(entry, score=score, risks=tuple(risks))
    )


def recompute_v2_decisions(
    decisions: list[StockDecision],
) -> list[StockDecision]:
    """Apply v2 adjustments + mapping + ranking to loaded decisions.

    Pure and idempotent: re-running on its own output changes nothing.
    Entry/quality states and grades are preserved; only v2 evidence items,
    extension score deductions, action mapping, and priorities change.
    """
    remapped: list[StockDecision] = []
    for decision in decisions:
        adjusted = _with_entry_v2_adjustments(_with_quality_v2_adjustments(decision))
        action, notes = map_action_state_v2(adjusted.quality, adjusted.entry)
        rationale = adjusted.rationale
        if notes and not any(item.code == "h3_b_ready_promotion" for item in rationale):
            rationale = rationale + (
                EvidenceItem(
                    code="h3_b_ready_promotion",
                    label="High-conviction B+READY promotion",
                    polarity="positive",  # type: ignore[arg-type]
                    metric="action_state",
                    value=action.value,
                    threshold="B score>=0.68, conf>=0.80, READY score>=0.80",
                    message="; ".join(notes),
                ),
            )
        remapped.append(
            replace(adjusted, action_state=action, rationale=rationale)
        )
    return assign_action_priorities_v2(remapped)


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
    if args.recompute_v2:
        _write_recompute_preview(decisions, output_dir)
        return
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
            detailed_subdir="detailed_v2",
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
            detailed_subdir="detailed_v2",
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
            render_detailed_report(
                by_symbol[symbol],
                layout_version="v2",
                back_link="../action_list_v2.md",
            ),
            encoding="utf-8",
        )
    print(
        f"wrote action_list_v2.md + weekly_review_v2.md + "
        f"{len(symbols)} detailed_v2 files to {output_dir}"
    )


def _write_recompute_preview(
    decisions: list, output_dir: Path
) -> None:
    """Non-destructive v2 recompute preview (never touches --snapshot-dir)."""
    recomputed = recompute_v2_decisions(list(decisions))
    daily = select_daily_attention(recomputed, cap=15)
    weekly = select_weekly_attention(recomputed, cap=15)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "action_list_v2.md").write_text(
        render_action_list(
            daily,
            title="Daily Action List",
            cadence="daily",
            layout_version="v2",
            all_decisions=recomputed,
            detailed_subdir="detailed_v2",
        ),
        encoding="utf-8",
    )
    (output_dir / "weekly_review_v2.md").write_text(
        render_action_list(
            weekly,
            title="Weekly Review List",
            cadence="weekly",
            layout_version="v2",
            all_decisions=recomputed,
            detailed_subdir="detailed_v2",
        ),
        encoding="utf-8",
    )
    daily_view = build_snapshot_view_model(
        daily, recomputed, title="Daily Action List", cadence="daily"
    )
    weekly_view = build_snapshot_view_model(
        weekly, recomputed, title="Weekly Review List", cadence="weekly"
    )
    by_symbol = {decision.symbol: decision for decision in recomputed}
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
            render_detailed_report(
                by_symbol[symbol],
                layout_version="v2",
                back_link="../action_list_v2.md",
            ),
            encoding="utf-8",
        )
    (output_dir / "decisions_recomputed_v2.jsonl").write_text(
        stock_decisions_to_jsonl(recomputed),
        encoding="utf-8",
    )
    print(
        f"wrote action_list_v2.md + weekly_review_v2.md + "
        f"{len(symbols)} detailed_v2 files + decisions_recomputed_v2.jsonl "
        f"to {output_dir}"
    )


if __name__ == "__main__":
    main()
