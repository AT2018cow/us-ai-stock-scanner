"""Read-only, cache-only non-operating gain audit screen.

Re-runs the non-operating investment gain / tax distortion lenses over the
local SEC cache without any network access or scan/report side effects:

1. TTM margin-gap lens (Layer-1 Case A/B semantics);
2. latest-quarter non-operating spike lens (Layer-1 Case C);
3. disposal-gain strip marker (Layer 3 tag watch).

Run after each earnings season; new hits go to the review queue, never
directly to production thresholds (AGENTS.md: retrospective evidence cannot
auto-promote production behavior).

Example:
    python scripts/audit_nonop_gain_screen.py --cache-dir cache
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from ai_value_scanner.decision.quality import (
    QUALITY_V2_HEALTHY_OCF_MIN,
    QUALITY_V2_NONOP_MARGIN_GAP_MIN,
    QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI,
    QUALITY_V2_NONOP_NET_MARGIN_FLOOR,
    QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR,
    QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN,
)
from ai_value_scanner.scanner import extract_latest_quarterly_nonop_metrics


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _payload_margins(payload: dict[str, Any]) -> dict[str, float | None]:
    """Operating-basis margins from a parsed-fund payload (adjusted preferred)."""
    revenue = _number(payload.get("revenue"))
    earnings = _number(payload.get("adjusted_net_income"))
    if earnings is None:
        earnings = _number(payload.get("net_income"))
    ebit = _number(payload.get("adjusted_ebit"))
    if ebit is None:
        ebit = _number(payload.get("ebit"))
    fcf = _number(payload.get("free_cash_flow"))
    net_margin: float | None = None
    operating_margin: float | None = None
    fcf_margin: float | None = None
    if revenue is not None and revenue > 0.0:
        if earnings is not None:
            net_margin = earnings / revenue
        if ebit is not None:
            operating_margin = ebit / revenue
        if fcf is not None:
            fcf_margin = fcf / revenue
    return {
        "revenue": revenue,
        "net_margin": net_margin,
        "operating_margin": operating_margin,
        "fcf_margin": fcf_margin,
    }


def _ttm_margin_gap_hit(
    *,
    net_margin: float | None,
    operating_margin: float | None,
    fcf_margin: float | None,
    ocf_to_net_income: float | None,
    min_ttm_gap: float,
) -> bool:
    if (
        net_margin is not None
        and operating_margin is not None
        and net_margin >= QUALITY_V2_NONOP_NET_MARGIN_FLOOR
        and (net_margin - operating_margin) >= min_ttm_gap
        and (
            ocf_to_net_income is None
            or ocf_to_net_income < QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI
        )
    ):
        return True
    # Case B fallback (operating margin absent): FCF-margin proxy.
    return bool(
        net_margin is not None
        and operating_margin is None
        and net_margin >= 0.25
        and (
            ocf_to_net_income is None
            or ocf_to_net_income < QUALITY_V2_HEALTHY_OCF_MIN
        )
        and fcf_margin is not None
        and (net_margin - fcf_margin) >= 0.15
    )


def run_nonop_gain_audit(
    cache_dir: Path,
    *,
    min_ttm_gap: float = QUALITY_V2_NONOP_MARGIN_GAP_MIN,
    min_quarterly_ratio: float = QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN,
    min_quarterly_abs: float = QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR,
) -> list[dict[str, Any]]:
    """Evaluate every parsed-fund cache entry with all non-op gain lenses.

    Pure and read-only: never fetches, never writes. Returns one row per
    symbol with boolean `hit` = TTM gap / quarterly spike / disposal strip.
    """
    base = Path(cache_dir)
    rows: list[dict[str, Any]] = []
    try:
        paths = sorted(base.glob("parsed_fund_*.json"))
    except OSError:
        return rows
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        symbol = str(payload.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        margins = _payload_margins(payload)
        ocf = _number(payload.get("ocf_to_net_income"))
        disposal = _number(payload.get("nonrecurring_gain_subtraction"))
        q_income: float | None = None
        q_revenue: float | None = None
        q_ratio: float | None = None
        q_end: str | None = None
        cik = str(payload.get("cik") or "").strip()
        facts_path = base / f"facts_{cik}.json"
        if cik and facts_path.exists():
            try:
                companyfacts = json.loads(facts_path.read_text(encoding="utf-8"))
                (q_income, q_revenue, q_ratio, q_end) = (
                    extract_latest_quarterly_nonop_metrics(companyfacts)
                )
            except (OSError, ValueError, TypeError):
                pass
        if q_ratio is None and q_income is not None and q_revenue:
            q_ratio = q_income / q_revenue
        rows.append(
            {
                "symbol": symbol,
                "cik": cik or None,
                "fundamental_data_asof": payload.get("fundamental_data_asof"),
                "net_margin": margins["net_margin"],
                "operating_margin": margins["operating_margin"],
                "fcf_margin": margins["fcf_margin"],
                "ocf_to_net_income": ocf,
                "ttm_margin_gap_hit": _ttm_margin_gap_hit(
                    net_margin=margins["net_margin"],
                    operating_margin=margins["operating_margin"],
                    fcf_margin=margins["fcf_margin"],
                    ocf_to_net_income=ocf,
                    min_ttm_gap=min_ttm_gap,
                ),
                "quarterly_nonop_income": q_income,
                "quarterly_revenue": q_revenue,
                "quarterly_nonop_ratio": q_ratio,
                "quarterly_period_end": q_end,
                "quarterly_spike_hit": bool(
                    q_income is not None
                    and q_income >= min_quarterly_abs
                    and q_ratio is not None
                    and q_ratio >= min_quarterly_ratio
                ),
                "nonrecurring_gain_subtraction": disposal,
                "disposal_gain_stripped": bool(
                    disposal is not None and disposal > 0.0
                ),
            }
        )
    for row in rows:
        row["hit"] = bool(
            row["ttm_margin_gap_hit"]
            or row["quarterly_spike_hit"]
            or row["disposal_gain_stripped"]
        )
    rows.sort(key=lambda row: row["symbol"])
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only cache audit for non-operating gain / tax distortion "
            "candidates (no network, no scan/report side effects)."
        )
    )
    parser.add_argument(
        "--cache-dir", default="cache", help="SEC cache directory (default: cache)."
    )
    parser.add_argument(
        "--output-json", default=None, help="Optional path for a JSON hit report."
    )
    parser.add_argument(
        "--min-ttm-gap",
        type=float,
        default=QUALITY_V2_NONOP_MARGIN_GAP_MIN,
        help="Case A minimum TTM net-margin minus operating-margin gap.",
    )
    parser.add_argument(
        "--min-quarterly-ratio",
        type=float,
        default=QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN,
        help="Case C minimum quarterly nonop / revenue ratio.",
    )
    parser.add_argument(
        "--min-quarterly-abs",
        type=float,
        default=QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR,
        help="Case C minimum absolute quarterly non-operating income (USD).",
    )
    return parser.parse_args()


def _format_value(value: Any, digits: int = 3) -> str:
    number = _number(value)
    return "n/a" if number is None else f"{number:.{digits}f}"


def _format_dollars(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    if abs(number) >= 1e9:
        return f"${number / 1e9:.2f}B"
    if abs(number) >= 1e6:
        return f"${number / 1e6:.1f}M"
    return f"${number:,.0f}"


def main() -> None:
    args = _parse_args()
    rows = run_nonop_gain_audit(
        Path(args.cache_dir),
        min_ttm_gap=args.min_ttm_gap,
        min_quarterly_ratio=args.min_quarterly_ratio,
        min_quarterly_abs=args.min_quarterly_abs,
    )
    hits = [row for row in rows if row["hit"]]
    nonop_hits = [
        row for row in rows
        if row["ttm_margin_gap_hit"] or row["quarterly_spike_hit"]
    ]
    disposal_only = [
        row for row in rows
        if row["disposal_gain_stripped"]
        and not row["ttm_margin_gap_hit"]
        and not row["quarterly_spike_hit"]
    ]
    print(
        f"# Non-Op Gain Screen — {len(nonop_hits)} non-op hit(s), "
        f"{len(disposal_only)} disposal strip marker(s) / "
        f"{len(rows)} parsed-fund cache entries"
    )
    print()
    print(
        "| Symbol | TTM Gap | Qtr NonOp/Rev | Qtr NonOp | Disposal | "
        "Net Margin | Op Margin | OCF/NI |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for row in nonop_hits:
        q_ratio = _number(row.get("quarterly_nonop_ratio"))
        print(
            "| {symbol} | {ttm} | {q_ratio} | {q_income} | {disposal} | "
            "{nm} | {om} | {ocf} |".format(
                symbol=row["symbol"],
                ttm="yes" if row["ttm_margin_gap_hit"] else "-",
                q_ratio=(
                    f"{q_ratio * 100:.1f}%" if q_ratio is not None else "-"
                ),
                q_income=_format_dollars(row.get("quarterly_nonop_income")),
                disposal=_format_dollars(row.get("nonrecurring_gain_subtraction")),
                nm=_format_value(row.get("net_margin")),
                om=_format_value(row.get("operating_margin")),
                ocf=_format_value(row.get("ocf_to_net_income")),
            )
        )
    if disposal_only:
        disposal_only.sort(
            key=lambda row: abs(
                _number(row.get("nonrecurring_gain_subtraction")) or 0.0
            ),
            reverse=True,
        )
        print()
        print(
            f"**Disposal-gain strip markers (informational, {len(disposal_only)})**:"
        )
        for row in disposal_only[:20]:
            print(
                f"- {row['symbol']}: "
                f"{_format_dollars(row.get('nonrecurring_gain_subtraction'))}"
            )
        if len(disposal_only) > 20:
            print(f"- …and {len(disposal_only) - 20} more (see --output-json).")
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(hits, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print()
        print(f"wrote {len(hits)} hit rows to {output_path.name}")


if __name__ == "__main__":
    main()
