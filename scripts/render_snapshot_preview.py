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
from typing import Any

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
    QUALITY_V2_HEALTHY_OCF_MIN,
    QUALITY_V2_NONOP_MARGIN_GAP_MIN,
    QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI,
    QUALITY_V2_NONOP_NET_MARGIN_FLOOR,
    QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR,
    QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN,
    QUALITY_V2_NONOP_YOY_GAP_MIN,
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
from ai_value_scanner.scanner import (
    INTEREST_INCOME_TAGS,
    extract_latest_quarterly_nonop_metrics,
    pick_latest_and_prev_ttm,
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


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


_CACHE_INDEX_BY_DIR: dict[str, dict[str, dict[str, Any]]] = {}
_DEFAULT_CACHE_DIR = Path("cache")


def _build_cache_index(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Read-only symbol -> parsed-fund payload index (one pass per cache dir)."""
    index: dict[str, dict[str, Any]] = {}
    try:
        paths = sorted(cache_dir.glob("parsed_fund_*.json"))
    except OSError:
        return index
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        symbol = str(payload.get("symbol") or "").strip().upper()
        if symbol:
            index[symbol] = payload
    return index


def _load_local_cache_enrichment(
    symbol: str, cache_dir: Path | None = None
) -> dict[str, Any]:
    """Read-only local `cache/` enrichment for --recompute-v2 (no network).

    Supplies the clean operating-basis fields the frozen decisions.jsonl
    evidence cannot expose (neutral scoring bands) and, when
    ``facts_{cik}.json`` is present, the Layer-1 Case C quarterly spike
    inputs via ``extract_latest_quarterly_nonop_metrics``.
    """
    base = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    key = str(base)
    index = _CACHE_INDEX_BY_DIR.get(key)
    if index is None:
        index = _build_cache_index(base)
        _CACHE_INDEX_BY_DIR[key] = index
    payload = index.get(str(symbol or "").strip().upper())
    if payload is None:
        return {}
    revenue = _as_number(payload.get("revenue"))
    earnings = _as_number(payload.get("adjusted_net_income"))
    if earnings is None:
        earnings = _as_number(payload.get("net_income"))
    ebit = _as_number(payload.get("adjusted_ebit"))
    if ebit is None:
        ebit = _as_number(payload.get("ebit"))
    fcf = _as_number(payload.get("free_cash_flow"))
    interest_income = _as_number(payload.get("interest_income"))
    interest_expense = _as_number(payload.get("interest_expense"))
    enrichment: dict[str, Any] = {
        "net_margin": None,
        "operating_margin": None,
        "fcf_margin": None,
        "net_interest_margin": None,
        "ocf_to_net_income": _as_number(payload.get("ocf_to_net_income")),
        "adjusted_net_income_yoy": _as_number(
            payload.get("adjusted_net_income_yoy")
        ),
        "net_income_yoy": _as_number(payload.get("net_income_yoy")),
        "adjusted_ebit_yoy": _as_number(payload.get("adjusted_ebit_yoy")),
        "ebit_yoy": _as_number(payload.get("ebit_yoy")),
    }
    if revenue is not None and revenue > 0.0:
        if earnings is not None:
            enrichment["net_margin"] = earnings / revenue
        if ebit is not None:
            enrichment["operating_margin"] = ebit / revenue
        if fcf is not None:
            enrichment["fcf_margin"] = fcf / revenue
        if interest_income is not None:
            enrichment["net_interest_margin"] = max(
                0.0,
                (max(0.0, interest_income) - abs(interest_expense or 0.0))
                / revenue,
            )
    cik = str(payload.get("cik") or "").strip()
    facts_path = base / f"facts_{cik}.json"
    if cik and facts_path.exists():
        try:
            companyfacts = json.loads(facts_path.read_text(encoding="utf-8"))
            (
                q_nonop_income,
                q_revenue,
                q_ratio,
                q_end,
            ) = extract_latest_quarterly_nonop_metrics(companyfacts)
            enrichment.update(
                {
                    "latest_quarterly_nonoperating_income": q_nonop_income,
                    "latest_quarterly_revenue": q_revenue,
                    "latest_quarterly_nonop_to_revenue": q_ratio,
                    "latest_quarterly_period_end": q_end,
                }
            )
            if interest_income is None:
                ttm_int_income, _ = pick_latest_and_prev_ttm(
                    companyfacts, INTEREST_INCOME_TAGS, "USD"
                )
                if ttm_int_income is not None:
                    interest_income = max(0.0, float(ttm_int_income))
                    if revenue is not None and revenue > 0.0:
                        enrichment["net_interest_margin"] = max(
                            0.0,
                            (
                                interest_income
                                - abs(interest_expense or 0.0)
                            )
                            / revenue,
                        )
        except (OSError, ValueError, TypeError):
            pass
    return enrichment


def _with_quality_v2_adjustments(
    decision: StockDecision, cache_dir: Path | None = None
) -> StockDecision:
    """Overlay v2 quality guards idempotently.

    Covers split/basis, pre-earnings, non-operating gain margin gap, Case C
    quarterly spike (with read-only local cache enrichment), and traceable
    operating-basis growth substitution.
    """
    quality = decision.quality
    codes = {item.code for item in quality.risks}
    positives = list(quality.positives)
    risks = list(quality.risks)
    components = dict(quality.component_scores or {})
    new_score = quality.score
    changed = False
    enrichment = _load_local_cache_enrichment(decision.symbol, cache_dir)
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
    # Non-operating investment gain / tax distortion overlay. Pulls clean
    # operating-basis fields from evidence first, then from the read-only
    # local `cache/` enrichment when the frozen JSONL bands were silent.
    positive_codes = {item.code for item in positives}

    def _evidence_or_enrichment(metric: str) -> float | None:
        value = _evidence_number(decision, metric)
        if value is None:
            value = _as_number(enrichment.get(metric))
        return value

    net_margin = _evidence_or_enrichment("net_margin")
    op_margin = _evidence_or_enrichment("operating_margin")
    fcf_margin = _evidence_or_enrichment("fcf_margin")
    ocf_ni = _evidence_or_enrichment("ocf_to_net_income")
    net_interest_margin = (
        _evidence_or_enrichment("net_interest_margin") or 0.0
    )
    ani_yoy = _evidence_or_enrichment("adjusted_net_income_yoy")
    if ani_yoy is None:
        ani_yoy = _evidence_or_enrichment("net_income_yoy")
    ebit_yoy = _evidence_or_enrichment("adjusted_ebit_yoy")
    if ebit_yoy is None:
        ebit_yoy = _evidence_or_enrichment("ebit_yoy")
    q_nonop_income = _evidence_or_enrichment(
        "latest_quarterly_nonoperating_income"
    )
    q_nonop_ratio = _evidence_or_enrichment("latest_quarterly_nonop_to_revenue")
    if q_nonop_ratio is None:
        q_revenue = _evidence_or_enrichment("latest_quarterly_revenue")
        if q_nonop_income is not None and q_revenue is not None and q_revenue > 0.0:
            q_nonop_ratio = q_nonop_income / q_revenue
    if "nonoperating_gain_inflation" not in {item.code for item in risks}:
        nonop_case: str | None = None
        capped_margin: float | None = None
        item_value: float | None = None
        basis_text = ""
        threshold_text = ""
        if (
            net_margin is not None
            and op_margin is not None
            and net_margin >= QUALITY_V2_NONOP_NET_MARGIN_FLOOR
            and (net_margin - op_margin - net_interest_margin)
            >= QUALITY_V2_NONOP_MARGIN_GAP_MIN
            and (ocf_ni is None or ocf_ni < QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI)
        ):
            nonop_case = "margin_gap"
            capped_margin = op_margin
            basis_text = f"operating margin ({op_margin * 100:.1f}%)"
            threshold_text = (
                "net_margin - operating_margin "
                f"< +{QUALITY_V2_NONOP_MARGIN_GAP_MIN * 100:.0f}pp"
            )
            item_value = round(net_margin - op_margin, 6)
        elif (
            net_margin is not None
            and op_margin is None
            and net_margin >= 0.40
            and "ocf_to_net_income_strong" not in positive_codes
            and fcf_margin is not None
            and (net_margin - fcf_margin) >= 0.15
        ):
            nonop_case = "fcf_gap"
            capped_margin = max(0.0, fcf_margin)
            basis_text = f"FCF margin ({fcf_margin * 100:.1f}%)"
            threshold_text = (
                "net_margin - fcf_margin < +15pp (operating margin unavailable)"
            )
            item_value = round(net_margin - fcf_margin, 6)
        elif (
            q_nonop_income is not None
            and q_nonop_income >= QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR
            and q_nonop_ratio is not None
            and q_nonop_ratio >= QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN
        ):
            nonop_case = "quarterly"
            if (
                net_margin is not None
                and op_margin is not None
                and net_margin > op_margin
            ):
                capped_margin = op_margin
            threshold_text = (
                "quarterly nonop / revenue "
                f"< +{QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN * 100:.0f}% "
                f"(>=${QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR / 1e6:.0f}M)"
            )
            item_value = round(q_nonop_ratio, 6)
        if nonop_case is not None:
            if nonop_case == "quarterly":
                message = (
                    f"Single-quarter non-operating income is "
                    f"${q_nonop_income / 1e9:.2f}B "
                    f"({q_nonop_ratio * 100:.1f}% of quarterly revenue); "
                    "quarterly mark-to-market investment gains distort GAAP "
                    "earnings (recompute overlay)."
                )
            else:
                message = (
                    f"Reported net margin ({net_margin * 100:.1f}%) exceeds "
                    f"{basis_text} by +{item_value * 100:.1f}pp; non-operating "
                    "gains or tax items inflated GAAP earnings (recompute "
                    "overlay); verify the adjusted basis manually."
                )
            risks.append(
                EvidenceItem(
                    code="nonoperating_gain_inflation",
                    label="Non-operating gain / tax distortion",
                    polarity="negative",  # type: ignore[arg-type]
                    metric="net_margin",
                    value=item_value,
                    threshold=threshold_text,
                    message=message,
                )
            )
            # Keep the preview Highlights consistent with the live clean
            # operating basis (P2-2): update or drop net_margin_strong.
            if capped_margin is not None:
                if capped_margin >= QUALITY_V2_NONOP_NET_MARGIN_FLOOR:
                    new_margin = round(capped_margin, 6)
                    updated_positives = []
                    for item in positives:
                        if item.code == "net_margin_strong" and item.value != new_margin:
                            item = replace(item, value=new_margin)
                        updated_positives.append(item)
                    positives = updated_positives
                else:
                    positives = [
                        item for item in positives
                        if item.code != "net_margin_strong"
                    ]
            if (ocf_ni is not None and ocf_ni < QUALITY_V2_HEALTHY_OCF_MIN) or (
                net_margin is not None
                and net_margin >= 0.20
                and ocf_ni is not None
                and "ocf_to_net_income_strong" not in positive_codes
            ):
                if "ocf_conversion_lagging_high_margin" not in {
                    item.code for item in risks
                }:
                    risks.append(
                        EvidenceItem(
                            code="ocf_conversion_lagging_high_margin",
                            label="Cash conversion lagging high net margin",
                            polarity="negative",  # type: ignore[arg-type]
                            metric="ocf_to_net_income",
                            value=round(ocf_ni, 6),
                            threshold=">=0.80x expected when net margin >=20%",
                            message=(
                                f"OCF/NI is {ocf_ni:.2f}x despite "
                                f"{net_margin * 100:.1f}% reported net margin; "
                                "earnings include non-cash or non-operating components "
                                "(recompute overlay)."
                            ),
                        )
                    )
            changed = True

        # Traceable operating-basis growth substitution (P2-3): covers both
        # non-op-inflated cases and the standalone YoY divergence (SHOP).
        nonop_inflated = nonop_case is not None
        yoy_gap_triggered = (
            not nonop_inflated
            and op_margin is not None
            and op_margin >= 0.10
            and ebit_yoy is not None
            and abs(ebit_yoy) <= 2.00
            and ani_yoy is not None
            and abs(ani_yoy - ebit_yoy) >= QUALITY_V2_NONOP_YOY_GAP_MIN
        )
        if (
            ebit_yoy is not None
            and ani_yoy is not None
            and (nonop_inflated or yoy_gap_triggered)
        ):
            growth_key = (
                "adjusted_net_income_yoy"
                if _evidence_or_enrichment("adjusted_net_income_yoy") is not None
                else "net_income_yoy"
            )
            weak_code = f"{growth_key}_weak"
            filtered = [item for item in risks if item.code != weak_code]
            if len(filtered) != len(risks):
                risks = filtered
                changed = True
            if ebit_yoy >= 0.15:
                strong_code = f"{growth_key}_strong"
                new_value = round(ebit_yoy, 6)
                updated_positives = []
                found = False
                touched = False
                for item in positives:
                    if item.code == strong_code:
                        found = True
                        if item.value != new_value:
                            item = replace(item, value=new_value)
                            touched = True
                    updated_positives.append(item)
                if not found:
                    updated_positives.append(
                        EvidenceItem(
                            code=strong_code,
                            label="Earnings growth supportive",
                            polarity="positive",  # type: ignore[arg-type]
                            metric=growth_key,
                            value=new_value,
                            threshold=">=15% strong; <-10% weak",
                            message=(
                                "Earnings growth supports the quality "
                                "assessment (operating-income basis)."
                            ),
                        )
                    )
                    touched = True
                if touched:
                    positives = updated_positives
                    changed = True
            if yoy_gap_triggered and "operating_growth_basis_substituted" not in {
                item.code for item in risks
            }:
                risks.append(
                    EvidenceItem(
                        code="operating_growth_basis_substituted",
                        label="Growth scored on operating-income basis",
                        polarity="negative",  # type: ignore[arg-type]
                        metric=growth_key,
                        value=round(ebit_yoy, 6),
                        threshold=(
                            "|NI YoY - EBIT YoY| < "
                            f"{QUALITY_V2_NONOP_YOY_GAP_MIN * 100:.0f}pp"
                        ),
                        message=(
                            f"Growth scored on operating-income basis "
                            f"({ebit_yoy * 100:+.1f}%) because GAAP net-income "
                            f"YoY ({ani_yoy * 100:+.1f}%) diverged by "
                            f"{abs(ani_yoy - ebit_yoy) * 100:.1f}pp due to "
                            "prior-period non-operating or tax base effects "
                            "(recompute overlay)."
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
    cache_dir: Path | None = None,
) -> list[StockDecision]:
    """Apply v2 adjustments + mapping + ranking to loaded decisions.

    Pure and idempotent: re-running on its own output changes nothing.
    Entry/quality states and grades are preserved; quality positives/risks
    (clean operating margin and growth basis), v2 evidence items, extension
    score deductions, action mapping, and priorities change.
    """
    remapped: list[StockDecision] = []
    for decision in decisions:
        adjusted = _with_entry_v2_adjustments(
            _with_quality_v2_adjustments(decision, cache_dir=cache_dir)
        )
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
