#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RunSummary:
    run_stem: str
    report_path: Path
    low_value_rows: int
    trend_rows: int
    momentum_rows: int
    elapsed_seconds: float | None


CHANNELS = ("core_ai", "ai_enabler", "ai_peripheral")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Systematic threshold calibration helper. Reads latest scan diagnostics and "
            "generates conservative/production/aggressive config profiles."
        )
    )
    p.add_argument("--base-config", default="config.production.json")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--run-stem", default=None, help="Optional run stem, e.g. _post_relax_next_tier_full")
    p.add_argument("--target-low-min", type=int, default=8)
    p.add_argument("--target-low-max", type=int, default=15)
    p.add_argument("--target-trend-min", type=int, default=8)
    p.add_argument("--target-trend-max", type=int, default=15)
    p.add_argument("--target-momo-min", type=int, default=8)
    p.add_argument("--target-momo-max", type=int, default=15)
    p.add_argument("--profiles-dir", default="configs")
    p.add_argument("--report-path", default=None, help="Optional markdown output path")
    return p.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _extract_int(label: str, text: str) -> int:
    m = re.search(rf"- {re.escape(label)}: (\d+)", text)
    return int(m.group(1)) if m else 0


def _extract_float(label: str, text: str) -> float | None:
    m = re.search(rf"- {re.escape(label)}: ([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


def detect_run_summary(outputs_dir: Path, run_stem: str | None) -> RunSummary:
    if run_stem:
        report_path = outputs_dir / f"{run_stem}_report.md"
        if not report_path.exists():
            raise FileNotFoundError(f"Report not found: {report_path}")
    else:
        candidates = sorted(outputs_dir.glob("*_report.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError(f"No report files found under {outputs_dir}")
        report_path = candidates[0]
        run_stem = report_path.name[: -len("_report.md")]

    text = report_path.read_text()
    return RunSummary(
        run_stem=run_stem,
        report_path=report_path,
        low_value_rows=_extract_int("final ranked rows", text),
        trend_rows=_extract_int("industry trend rows", text),
        momentum_rows=_extract_int("momentum rows", text),
        elapsed_seconds=_extract_float("Elapsed seconds", text),
    )


def load_first_fail(outputs_dir: Path, run_stem: str, channel: str) -> dict[str, int]:
    path = outputs_dir / f"{run_stem}_diagnostics_{channel}_first_fail.csv"
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            reason = str(row.get("reason", "")).strip()
            if not reason:
                continue
            out[reason] = int(float(row.get("count", 0) or 0))
    return out


def load_blockers(outputs_dir: Path, run_stem: str) -> dict[str, dict[str, int]]:
    return {channel: load_first_fail(outputs_dir, run_stem, channel) for channel in CHANNELS}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def shift_min(value: Any, delta: float, floor: float | None = None, ceil: float | None = None) -> Any:
    if value is None:
        return value
    out = float(value) + delta
    if floor is not None:
        out = max(floor, out)
    if ceil is not None:
        out = min(ceil, out)
    return round(out, 6)


def shift_max(value: Any, delta: float, floor: float | None = None, ceil: float | None = None) -> Any:
    if value is None:
        return value
    out = float(value) + delta
    if floor is not None:
        out = max(floor, out)
    if ceil is not None:
        out = min(ceil, out)
    return round(out, 6)


def tune_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    ch = cfg.get("channel_profiles", {})

    if profile_name == "production":
        return cfg

    if profile_name == "conservative":
        cfg["min_fundamental_quality_score"] = shift_min(
            cfg.get("min_fundamental_quality_score"), +0.03, floor=0.0, ceil=1.0
        )
        cfg["max_net_debt_to_ebitda"] = shift_max(cfg.get("max_net_debt_to_ebitda"), -0.4, floor=0.5)
        cfg["max_accrual_ratio"] = shift_max(cfg.get("max_accrual_ratio"), -0.03, floor=0.05)
        cfg["min_current_ratio"] = shift_min(cfg.get("min_current_ratio"), +0.05, floor=0.5)

        for name, prof in ch.items():
            prof["require_channel_bucket_match"] = True
            prof["min_ai_link_score"] = shift_min(prof.get("min_ai_link_score"), +0.05, floor=0.0, ceil=1.0)
            prof["min_ps_discount"] = shift_min(prof.get("min_ps_discount"), +0.02, floor=-1.0, ceil=1.0)
            prof["min_pe_discount"] = shift_min(prof.get("min_pe_discount"), +0.02, floor=-1.0, ceil=1.0)
            prof["max_ev_to_ebit"] = shift_max(prof.get("max_ev_to_ebit"), -4.0, floor=8.0)
            prof["min_net_income_yoy"] = shift_min(prof.get("min_net_income_yoy"), +0.03, floor=-1.0, ceil=1.0)
            prof["momentum_min_return_20d"] = shift_min(
                prof.get("momentum_min_return_20d"), +0.02, floor=-1.0, ceil=1.0
            )
            prof["momentum_min_return_60d"] = shift_min(
                prof.get("momentum_min_return_60d"), +0.02, floor=-1.0, ceil=1.0
            )
            prof["momentum_min_price_to_sma200"] = shift_min(
                prof.get("momentum_min_price_to_sma200"), +0.02, floor=0.5, ceil=2.0
            )
            prof["momentum_max_60d_volatility"] = shift_max(
                prof.get("momentum_max_60d_volatility"), -0.05, floor=0.2, ceil=2.0
            )
        return cfg

    if profile_name == "aggressive":
        cfg["min_fundamental_quality_score"] = shift_min(
            cfg.get("min_fundamental_quality_score"), -0.03, floor=0.45, ceil=1.0
        )
        cfg["max_net_debt_to_ebitda"] = shift_max(cfg.get("max_net_debt_to_ebitda"), +0.8, floor=0.5)
        cfg["max_accrual_ratio"] = shift_max(cfg.get("max_accrual_ratio"), +0.05, floor=0.05)
        cfg["min_current_ratio"] = shift_min(cfg.get("min_current_ratio"), -0.05, floor=0.80)

        for name, prof in ch.items():
            prof["min_ai_link_score"] = shift_min(prof.get("min_ai_link_score"), -0.08, floor=0.15, ceil=1.0)
            prof["min_ps_discount"] = shift_min(prof.get("min_ps_discount"), -0.03, floor=-1.0, ceil=1.0)
            prof["min_pe_discount"] = shift_min(prof.get("min_pe_discount"), -0.03, floor=-1.0, ceil=1.0)
            prof["max_ev_to_ebit"] = shift_max(prof.get("max_ev_to_ebit"), +8.0, floor=8.0)
            prof["min_fcf_yield"] = shift_min(prof.get("min_fcf_yield"), -0.004, floor=-0.10, ceil=1.0)
            prof["min_net_income_yoy"] = shift_min(prof.get("min_net_income_yoy"), -0.05, floor=-1.0, ceil=1.0)
            prof["max_ps_percentile_in_sic"] = shift_max(
                prof.get("max_ps_percentile_in_sic"), +0.10, floor=0.0, ceil=0.95
            )
            prof["max_pe_percentile_in_sic"] = shift_max(
                prof.get("max_pe_percentile_in_sic"), +0.10, floor=0.0, ceil=0.95
            )
            prof["max_ps_hist_percentile"] = shift_max(
                prof.get("max_ps_hist_percentile", cfg.get("max_ps_hist_percentile")), +0.10, floor=0.0, ceil=0.95
            )
            prof["max_pe_hist_percentile"] = shift_max(
                prof.get("max_pe_hist_percentile", cfg.get("max_pe_hist_percentile")), +0.10, floor=0.0, ceil=0.95
            )
            prof["min_drawdown_percentile"] = shift_min(
                prof.get("min_drawdown_percentile"), -0.08, floor=0.0, ceil=1.0
            )
            prof["max_range_position_52w"] = shift_max(
                prof.get("max_range_position_52w"), +0.06, floor=0.0, ceil=1.0
            )
            prof["max_price_to_sma200"] = shift_max(
                prof.get("max_price_to_sma200"), +0.06, floor=0.5, ceil=2.0
            )
            prof["min_days_below_sma200"] = 0
            prof["momentum_min_return_20d"] = shift_min(
                prof.get("momentum_min_return_20d"), -0.03, floor=0.0, ceil=1.0
            )
            prof["momentum_min_return_60d"] = shift_min(
                prof.get("momentum_min_return_60d"), -0.02, floor=-1.0, ceil=1.0
            )
            prof["momentum_min_price_to_sma200"] = shift_min(
                prof.get("momentum_min_price_to_sma200"), -0.03, floor=1.0, ceil=2.0
            )
            prof["momentum_max_drawdown_from_52w_high"] = shift_max(
                prof.get("momentum_max_drawdown_from_52w_high"), +0.10, floor=0.05, ceil=0.60
            )
            prof["momentum_max_60d_volatility"] = shift_max(
                prof.get("momentum_max_60d_volatility"), +0.10, floor=0.2, ceil=1.2
            )
            if prof.get("momentum_min_avg_dollar_volume_20d") is not None:
                prof["momentum_min_avg_dollar_volume_20d"] = max(
                    10_000_000.0, float(prof["momentum_min_avg_dollar_volume_20d"]) * 0.80
                )
            if name == "ai_enabler":
                prof["require_channel_bucket_match"] = False
        return cfg

    raise ValueError(f"Unknown profile: {profile_name}")


def pick_recommended_profile(summary: RunSummary, args: argparse.Namespace) -> str:
    goals = [
        summary.low_value_rows >= args.target_low_min,
        summary.trend_rows >= args.target_trend_min,
        summary.momentum_rows >= args.target_momo_min,
    ]
    if all(goals):
        return "production"
    if summary.momentum_rows == 0:
        return "aggressive"
    return "production"


def top_reasons(blockers: dict[str, dict[str, int]], top_n: int = 6) -> list[tuple[str, int]]:
    combined: dict[str, int] = {}
    for by_reason in blockers.values():
        for reason, count in by_reason.items():
            combined[reason] = combined.get(reason, 0) + int(count)
    ranked = sorted(combined.items(), key=lambda x: (-x[1], x[0]))
    return ranked[:top_n]


def render_report(
    summary: RunSummary,
    blockers: dict[str, dict[str, int]],
    recommended: str,
    args: argparse.Namespace,
    profile_paths: dict[str, Path],
) -> str:
    lines: list[str] = []
    lines.append("# Threshold Calibration Report")
    lines.append("")
    lines.append(f"- Generated UTC: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Base config: `{args.base_config}`")
    lines.append(f"- Source run stem: `{summary.run_stem}`")
    lines.append(f"- Source report: `{summary.report_path}`")
    if summary.elapsed_seconds is not None:
        lines.append(f"- Source run elapsed: {summary.elapsed_seconds:.2f}s")
    lines.append("")
    lines.append("## Current vs Targets")
    lines.append("")
    lines.append(f"- Low-Value rows: {summary.low_value_rows} (target {args.target_low_min}-{args.target_low_max})")
    lines.append(f"- Industry-Trend rows: {summary.trend_rows} (target {args.target_trend_min}-{args.target_trend_max})")
    lines.append(f"- Momentum rows: {summary.momentum_rows} (target {args.target_momo_min}-{args.target_momo_max})")
    lines.append("")
    lines.append("## Top First-Fail Blockers (Low-Value Funnel)")
    lines.append("")
    for reason, count in top_reasons(blockers, top_n=10):
        lines.append(f"- `{reason}`: {count}")
    lines.append("")
    lines.append("## Profile Strategy")
    lines.append("")
    lines.append("- `conservative`: tighten quality/valuation/momentum thresholds for risk-first selection.")
    lines.append("- `production`: current stable baseline (no auto change).")
    lines.append("- `aggressive`: keep quality floor, loosen structure/style/momentum to improve candidate recall.")
    lines.append(f"- Recommended profile from current output: `{recommended}`")
    lines.append("")
    lines.append("## Generated Files")
    lines.append("")
    for name, path in profile_paths.items():
        lines.append(f"- {name}: `{path}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    base_config_path = Path(args.base_config)
    outputs_dir = Path(args.outputs_dir)
    profiles_dir = Path(args.profiles_dir)

    base = read_json(base_config_path)
    summary = detect_run_summary(outputs_dir, args.run_stem)
    blockers = load_blockers(outputs_dir, summary.run_stem)

    profiles = {
        "conservative": tune_profile(base, "conservative"),
        "production": tune_profile(base, "production"),
        "aggressive": tune_profile(base, "aggressive"),
    }

    profile_paths = {
        name: profiles_dir / f"config.{name}.json" for name in ("conservative", "production", "aggressive")
    }
    for name, path in profile_paths.items():
        write_json(path, profiles[name])

    recommended = pick_recommended_profile(summary, args)

    report_path = Path(args.report_path) if args.report_path else outputs_dir / f"{summary.run_stem}_calibration.md"
    report_text = render_report(summary, blockers, recommended, args, profile_paths)
    report_path.write_text(report_text)

    print(f"[calibrate] source run: {summary.run_stem}")
    print(f"[calibrate] low/trend/momo: {summary.low_value_rows}/{summary.trend_rows}/{summary.momentum_rows}")
    print(f"[calibrate] recommended profile: {recommended}")
    for name, path in profile_paths.items():
        print(f"[calibrate] wrote {name}: {path}")
    print(f"[calibrate] report: {report_path}")


if __name__ == "__main__":
    main()
