"""Offline attribution for risk_on vs risk_off low_value selection.

This script consumes the already-extracted survivor datasets plus the compact
historical replay signal files. It does not call Alpaca, SEC, Modal, or the
historical replay engine.

Primary question:
    When risk_on selected a low_value stock that risk_off did not, where did
    that stock leave the risk_off production selection pipeline?

Stages are diagnosed in production order:
    hard_filter -> research_gate -> group_cap -> per-channel top-N

For names that survive risk_off hard filters but rank below top-N, the script
also records which risk_off soft conditions they failed. This matters because
scored mode does not hard-exclude most valuation/quality conditions; those
conditions affect the soft-pass term and therefore ranking.

The output is descriptive attribution, not a causal P&L counterfactual.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.backtest import build_steps_and_weights
from ai_value_scanner.config import ScanConfig, load_config
from ai_value_scanner.strategy.filtering import (
    classify_filter_step_layer,
    partition_filter_steps,
)
from ai_value_scanner.strategy.research import (
    apply_low_value_research_gate,
    apply_research_assessment,
)
from ai_value_scanner.strategy.scoring import score_and_rank
from ai_value_scanner.strategy.selection import apply_group_caps


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[low-value-attribution {stamp}] {message}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Attribute risk_on-only low_value selections to risk_off pipeline stages."
    )
    p.add_argument("--risk-on-dataset", required=True)
    p.add_argument("--risk-off-dataset", required=True)
    p.add_argument("--risk-on-signals", required=True)
    p.add_argument("--risk-off-signals", required=True)
    p.add_argument("--risk-on-config", default="configs/config.risk_on.json")
    p.add_argument("--risk-off-config", default="configs/config.risk_off.json")
    p.add_argument(
        "--years",
        default="2023,2025",
        help="Comma-separated years to audit (default: the two baseline edge years).",
    )
    p.add_argument("--horizon", type=int, default=120)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument(
        "--include-channels",
        default="core_ai,ai_enabler,ai_peripheral",
    )
    p.add_argument(
        "--output-prefix",
        default="outputs/low_value_gate_attribution",
    )
    return p


def parse_tokens(raw: str) -> list[str]:
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_channel_selections(
    path: str | Path,
    *,
    years: set[str],
    channels: set[str],
) -> dict[tuple[str, str], set[str]]:
    frame = pd.read_csv(path)
    frame = frame[
        (frame["scenario"].astype(str) == "base")
        & (frame["list_type"].astype(str) == "low_value")
    ].copy()
    if years:
        frame = frame[frame["signal_date"].astype(str).str[:4].isin(years)].copy()

    out: dict[tuple[str, str], set[str]] = {}
    for row in frame.itertuples(index=False):
        signal_date = str(getattr(row, "signal_date"))
        mapping = _json_dict(getattr(row, "channel_symbols", "{}"))
        for channel, symbols in mapping.items():
            channel = str(channel)
            if channels and channel not in channels:
                continue
            values = symbols if isinstance(symbols, list) else []
            out[(signal_date, channel)] = {
                str(symbol).strip().upper()
                for symbol in values
                if str(symbol).strip()
            }
    return out


def _single_row_first_fail(
    row: pd.Series,
    steps: list[tuple[str, Any]],
) -> str:
    frame = pd.DataFrame([row.to_dict()])
    for step_name, mask_fn in steps:
        try:
            raw = mask_fn(frame)
            passed = bool(pd.Series(raw, index=frame.index).fillna(False).iloc[0])
        except Exception:
            passed = False
        if not passed:
            return str(step_name)
    return ""


def _failed_steps(
    row: pd.Series,
    steps: list[tuple[str, Any]],
) -> list[str]:
    frame = pd.DataFrame([row.to_dict()])
    failures: list[str] = []
    for step_name, mask_fn in steps:
        try:
            raw = mask_fn(frame)
            passed = bool(pd.Series(raw, index=frame.index).fillna(False).iloc[0])
        except Exception:
            passed = False
        if not passed:
            failures.append(str(step_name))
    return failures


def _with_soft_pass_counts(
    frame: pd.DataFrame,
    soft_steps: list[tuple[str, Any]],
) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        return out
    if not soft_steps:
        out["soft_pass_count"] = 0
        out["soft_total"] = 1
        return out
    masks: dict[str, pd.Series] = {}
    for name, mask_fn in soft_steps:
        raw = mask_fn(out)
        masks[name] = pd.Series(raw, index=out.index).fillna(False).astype(bool)
    matrix = pd.DataFrame(masks, index=out.index)
    out["soft_pass_count"] = matrix.sum(axis=1)
    out["soft_total"] = len(soft_steps)
    return out


def build_risk_off_group_states(
    dataset: pd.DataFrame,
    config: ScanConfig,
    channels: list[str],
    *,
    top_n: int,
) -> dict[tuple[str, str], dict[str, Any]]:
    work = dataset[dataset["list_type"].astype(str) == "low_value"].copy()
    states: dict[tuple[str, str], dict[str, Any]] = {}
    profiles = config.channel_profiles or {}

    for channel in channels:
        if channel not in profiles:
            continue
        steps, weights = build_steps_and_weights(
            config,
            channel,
            profiles[channel],
            "low_value",
        )
        hard_steps, soft_steps = partition_filter_steps(
            steps,
            channel,
            config.strategy_style,
        )

        channel_rows = work[work["channel"].astype(str) == channel]
        for signal_date, group in channel_rows.groupby("signal_date", sort=False):
            group = group.drop_duplicates(subset=["symbol"], keep="first").copy()
            scored_input = _with_soft_pass_counts(group, soft_steps)
            ranked = score_and_rank(
                scored_input,
                weights,
                config.score_winsor_lower_q,
                config.score_winsor_upper_q,
                config.score_penalty_overvaluation,
                config.score_penalty_deterioration,
                config.pe_cash_backing_haircut,
            ).reset_index(drop=True)
            ranked["_rank_pre_research"] = np.arange(1, len(ranked) + 1)

            assessed = apply_research_assessment(ranked, "low_value")
            research_kept = apply_low_value_research_gate(
                assessed,
                config,
            ).reset_index(drop=True)
            research_kept["_rank_post_research"] = np.arange(
                1, len(research_kept) + 1
            )

            capped = apply_group_caps(
                research_kept,
                config.max_per_sector_per_list,
                config.max_per_watchlist_etf_source_per_list,
            ).reset_index(drop=True)
            capped["_rank_after_caps"] = np.arange(1, len(capped) + 1)

            states[(str(signal_date), channel)] = {
                "hard_steps": hard_steps,
                "soft_steps": soft_steps,
                "ranked": ranked,
                "assessed": assessed,
                "research_kept": research_kept,
                "capped": capped,
                "top_n": int(top_n),
            }
    return states


def _symbol_row(frame: pd.DataFrame, symbol: str) -> pd.Series | None:
    if frame.empty or "symbol" not in frame.columns:
        return None
    match = frame[frame["symbol"].astype(str).str.upper() == symbol]
    if match.empty:
        return None
    return match.iloc[0]


def diagnose_exclusion(
    *,
    source_row: pd.Series,
    signal_date: str,
    channel: str,
    symbol: str,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    if state is None:
        return {
            "exclusion_stage": "missing_risk_off_group",
            "exclusion_reason": "missing_risk_off_group",
            "hard_first_fail": "",
            "hard_fail_layer": "",
            "soft_failed_steps": "",
        }

    hard_steps = state["hard_steps"]
    soft_steps = state["soft_steps"]
    hard_first_fail = _single_row_first_fail(source_row, hard_steps)
    soft_failures = _failed_steps(source_row, soft_steps)

    base = {
        "hard_first_fail": hard_first_fail,
        "hard_fail_layer": (
            classify_filter_step_layer(hard_first_fail)
            if hard_first_fail
            else ""
        ),
        "soft_failed_steps": ",".join(soft_failures),
        "soft_fail_count": len(soft_failures),
        "risk_off_composite_score": np.nan,
        "risk_off_rank_pre_research": np.nan,
        "risk_off_rank_post_research": np.nan,
        "risk_off_rank_after_caps": np.nan,
        "risk_off_research_priority": "",
        "risk_off_research_score": np.nan,
        "risk_off_research_risks": "",
    }
    if hard_first_fail:
        base.update(
            {
                "exclusion_stage": "hard_filter",
                "exclusion_reason": f"hard:{hard_first_fail}",
            }
        )
        return base

    ranked_row = _symbol_row(state["ranked"], symbol)
    if ranked_row is None:
        base.update(
            {
                "exclusion_stage": "data_mismatch",
                "exclusion_reason": "hard_pass_but_missing_risk_off_survivor",
            }
        )
        return base

    assessed_row = _symbol_row(state["assessed"], symbol)
    base.update(
        {
            "risk_off_composite_score": ranked_row.get(
                "composite_score", np.nan
            ),
            "risk_off_rank_pre_research": ranked_row.get(
                "_rank_pre_research", np.nan
            ),
            "risk_off_research_priority": (
                assessed_row.get("research_priority", "")
                if assessed_row is not None
                else ""
            ),
            "risk_off_research_score": (
                assessed_row.get("research_score", np.nan)
                if assessed_row is not None
                else np.nan
            ),
            "risk_off_research_risks": (
                assessed_row.get("research_risks", "")
                if assessed_row is not None
                else ""
            ),
        }
    )

    research_row = _symbol_row(state["research_kept"], symbol)
    if research_row is None:
        base.update(
            {
                "exclusion_stage": "research_gate",
                "exclusion_reason": "research_gate",
            }
        )
        return base

    base["risk_off_rank_post_research"] = research_row.get(
        "_rank_post_research", np.nan
    )
    capped_row = _symbol_row(state["capped"], symbol)
    if capped_row is None:
        base.update(
            {
                "exclusion_stage": "group_cap",
                "exclusion_reason": "group_cap",
            }
        )
        return base

    rank_after_caps = int(capped_row.get("_rank_after_caps", 10**9))
    base["risk_off_rank_after_caps"] = rank_after_caps
    if rank_after_caps > int(state["top_n"]):
        base.update(
            {
                "exclusion_stage": "below_top_n",
                "exclusion_reason": "below_top_n",
            }
        )
        return base

    base.update(
        {
            "exclusion_stage": "selection_mismatch",
            "exclusion_reason": "would_select_under_reconstructed_risk_off",
        }
    )
    return base


def _first_finite(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce")
    vals = vals[np.isfinite(vals)]
    return float(vals.iloc[0]) if not vals.empty else float("nan")


def build_cases(
    *,
    risk_on_dataset: pd.DataFrame,
    risk_off_dataset: pd.DataFrame,
    risk_on_selected: dict[tuple[str, str], set[str]],
    risk_off_selected: dict[tuple[str, str], set[str]],
    risk_off_config: ScanConfig,
    channels: list[str],
    horizon: int,
    top_n: int,
) -> pd.DataFrame:
    states = build_risk_off_group_states(
        risk_off_dataset,
        risk_off_config,
        channels,
        top_n=top_n,
    )
    on_lv = risk_on_dataset[
        risk_on_dataset["list_type"].astype(str) == "low_value"
    ].copy()
    rows: list[dict[str, Any]] = []

    for key, on_symbols in sorted(risk_on_selected.items()):
        signal_date, channel = key
        off_symbols = risk_off_selected.get(key, set())
        for symbol in sorted(on_symbols - off_symbols):
            source = on_lv[
                (on_lv["signal_date"].astype(str) == signal_date)
                & (on_lv["channel"].astype(str) == channel)
                & (on_lv["symbol"].astype(str).str.upper() == symbol)
            ]
            if source.empty:
                rows.append(
                    {
                        "signal_date": signal_date,
                        "year": signal_date[:4],
                        "channel": channel,
                        "symbol": symbol,
                        "exclusion_stage": "missing_source_row",
                        "exclusion_reason": "missing_risk_on_survivor_row",
                    }
                )
                continue

            source_row = source.iloc[0]
            fwd = pd.to_numeric(
                pd.Series([source_row.get(f"fwd_ret_{horizon}")]),
                errors="coerce",
            ).iloc[0]
            qqq = pd.to_numeric(
                pd.Series([source_row.get(f"qqq_return_{horizon}")]),
                errors="coerce",
            ).iloc[0]
            excess = (
                float(fwd - qqq)
                if np.isfinite(fwd) and np.isfinite(qqq)
                else float("nan")
            )
            diagnosis = diagnose_exclusion(
                source_row=source_row,
                signal_date=signal_date,
                channel=channel,
                symbol=symbol,
                state=states.get((signal_date, channel)),
            )
            rows.append(
                {
                    "signal_date": signal_date,
                    "year": signal_date[:4],
                    "regime": source_row.get("regime", ""),
                    "channel": channel,
                    "symbol": symbol,
                    "horizon_days": int(horizon),
                    "forward_return": fwd,
                    "qqq_return": qqq,
                    "excess_vs_qqq": excess,
                    "winner_vs_qqq": bool(
                        np.isfinite(excess) and excess > 0.0
                    ),
                    **diagnosis,
                }
            )
    return pd.DataFrame(rows)


def summarize_cases(cases: pd.DataFrame) -> pd.DataFrame:
    if cases.empty:
        return pd.DataFrame(
            columns=[
                "year",
                "exclusion_reason",
                "n_cases",
                "n_mature",
                "n_winners_vs_qqq",
                "winner_rate",
                "avg_forward_return",
                "avg_excess_vs_qqq",
                "median_excess_vs_qqq",
            ]
        )

    rows: list[dict[str, Any]] = []
    for scope_year in ["ALL", *sorted(cases["year"].dropna().astype(str).unique())]:
        part_year = (
            cases
            if scope_year == "ALL"
            else cases[cases["year"].astype(str) == scope_year]
        )
        for reason, part in part_year.groupby("exclusion_reason", dropna=False):
            mature = part[np.isfinite(pd.to_numeric(part["excess_vs_qqq"], errors="coerce"))]
            winner_count = int(
                pd.to_numeric(mature["excess_vs_qqq"], errors="coerce").gt(0).sum()
            )
            rows.append(
                {
                    "year": scope_year,
                    "exclusion_reason": str(reason),
                    "n_cases": int(len(part)),
                    "n_mature": int(len(mature)),
                    "n_winners_vs_qqq": winner_count,
                    "winner_rate": (
                        float(winner_count / len(mature))
                        if len(mature)
                        else np.nan
                    ),
                    "avg_forward_return": _first_finite(
                        pd.Series([mature["forward_return"].mean()])
                    ),
                    "avg_excess_vs_qqq": _first_finite(
                        pd.Series([mature["excess_vs_qqq"].mean()])
                    ),
                    "median_excess_vs_qqq": _first_finite(
                        pd.Series([mature["excess_vs_qqq"].median()])
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["year", "n_cases", "exclusion_reason"],
        ascending=[True, False, True],
    )


def summarize_soft_failures(cases: pd.DataFrame) -> pd.DataFrame:
    """Explode soft failures, with winner-vs-QQQ counts for mechanism triage."""
    if cases.empty or "soft_failed_steps" not in cases.columns:
        return pd.DataFrame(
            columns=[
                "year",
                "soft_step",
                "n_cases",
                "n_mature",
                "n_winners_vs_qqq",
                "winner_rate",
                "avg_excess_vs_qqq",
            ]
        )

    work = cases.copy()
    work["soft_step"] = (
        work["soft_failed_steps"]
        .fillna("")
        .astype(str)
        .str.split(",")
    )
    work = work.explode("soft_step")
    work["soft_step"] = work["soft_step"].fillna("").astype(str).str.strip()
    work = work[work["soft_step"] != ""].copy()
    if work.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for scope_year in ["ALL", *sorted(work["year"].dropna().astype(str).unique())]:
        part_year = (
            work
            if scope_year == "ALL"
            else work[work["year"].astype(str) == scope_year]
        )
        for step, part in part_year.groupby("soft_step", dropna=False):
            excess = pd.to_numeric(part["excess_vs_qqq"], errors="coerce")
            mature_mask = np.isfinite(excess)
            mature = part[mature_mask]
            mature_excess = pd.to_numeric(
                mature["excess_vs_qqq"], errors="coerce"
            )
            winners = int(mature_excess.gt(0).sum())
            rows.append(
                {
                    "year": scope_year,
                    "soft_step": str(step),
                    "n_cases": int(len(part)),
                    "n_mature": int(len(mature)),
                    "n_winners_vs_qqq": winners,
                    "winner_rate": (
                        float(winners / len(mature))
                        if len(mature)
                        else np.nan
                    ),
                    "avg_excess_vs_qqq": (
                        float(mature_excess.mean())
                        if len(mature)
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["year", "n_winners_vs_qqq", "n_cases", "soft_step"],
        ascending=[True, False, False, True],
    )


def build_paired_selection_outcomes(
    *,
    risk_on_dataset: pd.DataFrame,
    risk_off_dataset: pd.DataFrame,
    risk_on_selected: dict[tuple[str, str], set[str]],
    risk_off_selected: dict[tuple[str, str], set[str]],
    horizons: list[int],
) -> pd.DataFrame:
    on_by_date: dict[str, set[str]] = {}
    off_by_date: dict[str, set[str]] = {}
    for (date, _channel), symbols in risk_on_selected.items():
        on_by_date.setdefault(date, set()).update(symbols)
    for (date, _channel), symbols in risk_off_selected.items():
        off_by_date.setdefault(date, set()).update(symbols)

    def returns_for(
        dataset: pd.DataFrame,
        date: str,
        symbols: set[str],
        horizon: int,
    ) -> list[float]:
        part = dataset[
            (dataset["list_type"].astype(str) == "low_value")
            & (dataset["signal_date"].astype(str) == date)
            & (dataset["symbol"].astype(str).str.upper().isin(symbols))
        ].drop_duplicates(subset=["symbol"], keep="first")
        vals = pd.to_numeric(part[f"fwd_ret_{horizon}"], errors="coerce")
        return [float(x) for x in vals if np.isfinite(x)]

    rows: list[dict[str, Any]] = []
    for date in sorted(set(on_by_date) | set(off_by_date)):
        on_only = on_by_date.get(date, set()) - off_by_date.get(date, set())
        off_only = off_by_date.get(date, set()) - on_by_date.get(date, set())
        for horizon in horizons:
            on_vals = returns_for(
                risk_on_dataset, date, on_only, horizon
            )
            off_vals = returns_for(
                risk_off_dataset, date, off_only, horizon
            )
            rows.append(
                {
                    "signal_date": date,
                    "year": date[:4],
                    "horizon_days": int(horizon),
                    "risk_on_only_n": len(on_only),
                    "risk_off_only_n": len(off_only),
                    "risk_on_only_n_mature": len(on_vals),
                    "risk_off_only_n_mature": len(off_vals),
                    "risk_on_only_avg_return": (
                        float(np.mean(on_vals)) if on_vals else np.nan
                    ),
                    "risk_off_only_avg_return": (
                        float(np.mean(off_vals)) if off_vals else np.nan
                    ),
                    "risk_on_minus_risk_off_only_return": (
                        float(np.mean(on_vals) - np.mean(off_vals))
                        if on_vals and off_vals
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def write_report(
    path: Path,
    cases: pd.DataFrame,
    summary: pd.DataFrame,
    soft_summary: pd.DataFrame,
    paired: pd.DataFrame,
    *,
    years: list[str],
    horizon: int,
) -> None:
    lines = [
        "# Low-value selection attribution",
        "",
        "This is descriptive offline attribution using frozen survivor datasets and replay selections.",
        "It does not rerun PIT data and does not establish causal P&L by itself.",
        "",
        f"- audited years: {', '.join(years)}",
        f"- primary outcome horizon: {horizon}d",
        f"- risk_on-only channel-selection cases: {len(cases)}",
        "",
        "## Exclusion reasons",
        "",
    ]
    if summary.empty:
        lines.append("No auditable cases.")
    else:
        all_rows = summary[summary["year"].astype(str) == "ALL"].copy()
        for row in all_rows.itertuples(index=False):
            lines.append(
                f"- {row.exclusion_reason}: n={int(row.n_cases)}, "
                f"mature={int(row.n_mature)}, "
                f"winner_vs_QQQ={int(row.n_winners_vs_qqq)}, "
                f"avg_excess={float(row.avg_excess_vs_qqq):+.4f}"
            )

    lines.extend(["", "## Repeated soft-condition failures", ""])
    if soft_summary.empty:
        lines.append("No soft-condition failures recorded.")
    else:
        top_soft = soft_summary[
            soft_summary["year"].astype(str) == "ALL"
        ].head(12)
        for row in top_soft.itertuples(index=False):
            lines.append(
                f"- {row.soft_step}: cases={int(row.n_cases)}, "
                f"winners_vs_QQQ={int(row.n_winners_vs_qqq)}, "
                f"avg_excess={float(row.avg_excess_vs_qqq):+.4f}"
            )

    lines.extend(["", "## Largest missed positive-excess cases", ""])
    if "excess_vs_qqq" in cases.columns:
        excess_series = pd.to_numeric(
            cases["excess_vs_qqq"], errors="coerce"
        )
        mature = cases[np.isfinite(excess_series)].copy()
    else:
        mature = cases.iloc[0:0].copy()
    mature = mature.sort_values("excess_vs_qqq", ascending=False).head(20)
    if mature.empty:
        lines.append("No mature cases.")
    else:
        for row in mature.itertuples(index=False):
            lines.append(
                f"- {row.signal_date} {row.channel} {row.symbol}: "
                f"excess={float(row.excess_vs_qqq):+.4f}, "
                f"reason={row.exclusion_reason}, "
                f"soft_fail={getattr(row, 'soft_failed_steps', '')}"
            )

    lines.extend(["", "## Paired selection-only diagnostic", ""])
    paired_h = paired[
        (paired["horizon_days"] == int(horizon))
        & paired["year"].astype(str).isin(years)
    ].copy()
    vals = pd.to_numeric(
        paired_h["risk_on_minus_risk_off_only_return"], errors="coerce"
    )
    vals = vals[np.isfinite(vals)]
    lines.append(
        "- mean of per-date (risk_on-only mean return - risk_off-only mean return): "
        + (f"{float(vals.mean()):+.4f}" if len(vals) else "n/a")
    )
    lines.append(
        "- This is a selection-substitution diagnostic, not an account-return estimate."
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = build_parser().parse_args()
    years = parse_tokens(args.years)
    year_set = set(years)
    channels = parse_tokens(args.include_channels)
    channel_set = set(channels)
    horizon = int(args.horizon)

    log("loading frozen survivor datasets")
    risk_on_dataset = pd.read_csv(args.risk_on_dataset)
    risk_off_dataset = pd.read_csv(args.risk_off_dataset)

    required = {
        "signal_date",
        "channel",
        "list_type",
        "symbol",
        f"fwd_ret_{horizon}",
        f"qqq_return_{horizon}",
    }
    for label, frame in (
        ("risk_on", risk_on_dataset),
        ("risk_off", risk_off_dataset),
    ):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{label} dataset missing columns: {','.join(missing)}")

    risk_on_config = load_config(args.risk_on_config)
    risk_off_config = load_config(args.risk_off_config)
    if str(risk_on_config.strategy_style) != "risk_on":
        raise ValueError("--risk-on-config must declare strategy_style=risk_on")
    if str(risk_off_config.strategy_style) != "risk_off":
        raise ValueError("--risk-off-config must declare strategy_style=risk_off")

    on_selected = load_channel_selections(
        args.risk_on_signals,
        years=year_set,
        channels=channel_set,
    )
    off_selected = load_channel_selections(
        args.risk_off_signals,
        years=year_set,
        channels=channel_set,
    )
    log("diagnosing risk_on-only low_value selections under risk_off pipeline")
    cases = build_cases(
        risk_on_dataset=risk_on_dataset,
        risk_off_dataset=risk_off_dataset,
        risk_on_selected=on_selected,
        risk_off_selected=off_selected,
        risk_off_config=risk_off_config,
        channels=channels,
        horizon=horizon,
        top_n=int(args.top_n),
    )
    summary = summarize_cases(cases)
    soft_summary = summarize_soft_failures(cases)
    paired = build_paired_selection_outcomes(
        risk_on_dataset=risk_on_dataset,
        risk_off_dataset=risk_off_dataset,
        risk_on_selected=on_selected,
        risk_off_selected=off_selected,
        horizons=[20, 60, 120],
    )

    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    cases_path = Path(f"{prefix}_cases.csv")
    summary_path = Path(f"{prefix}_summary.csv")
    soft_summary_path = Path(f"{prefix}_soft_failures.csv")
    paired_path = Path(f"{prefix}_paired_selection.csv")
    report_path = Path(f"{prefix}_report.md")
    cases.to_csv(cases_path, index=False)
    summary.to_csv(summary_path, index=False)
    soft_summary.to_csv(soft_summary_path, index=False)
    paired.to_csv(paired_path, index=False)
    write_report(
        report_path,
        cases,
        summary,
        soft_summary,
        paired,
        years=years,
        horizon=horizon,
    )
    log(
        f"done: cases={cases_path} summary={summary_path} "
        f"soft={soft_summary_path} paired={paired_path} report={report_path}"
    )


if __name__ == "__main__":
    main()
