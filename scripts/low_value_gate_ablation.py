"""Offline A/B ablation of risk_off low_value position hard gates.

A = current risk_off production semantics.
B = move a pre-registered block of structural hard gates to the soft-pass
layer, leaving every other production rule and score weight unchanged.

The input must be a research-expanded survivor dataset created with the same
hard steps omitted during extraction. This is retrospective mechanism
validation only; it is not promotion evidence and not true OOS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.backtest import build_steps_and_weights
from ai_value_scanner.config import ScanConfig, load_config
from ai_value_scanner.strategy.filtering import (
    apply_filters_with_diagnostics,
    partition_filter_steps,
)
from ai_value_scanner.strategy.research import (
    apply_low_value_research_gate,
    apply_research_assessment,
)
from ai_value_scanner.strategy.scoring import score_and_rank
from ai_value_scanner.strategy.selection import (
    apply_group_caps,
    select_symbols_from_ranked_frames,
)

DEFAULT_TARGET_STEPS = (
    "max_range_position_52w",
    "min_drawdown_from_52w_high",
    "max_price_to_sma200",
)
ARMS = ("baseline", "hard_to_soft")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Retrospective risk_off low_value structural-gate A/B."
    )
    p.add_argument("--dataset", required=True)
    p.add_argument("--scan-config", default="configs/config.risk_off.json")
    p.add_argument("--baseline-signals", required=True)
    p.add_argument(
        "--target-steps",
        default=",".join(DEFAULT_TARGET_STEPS),
    )
    p.add_argument(
        "--include-channels",
        default="core_ai,ai_enabler,ai_peripheral",
    )
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument(
        "--output-prefix",
        default="outputs/risk_off_low_value_position_ablation",
    )
    return p


def parse_tokens(raw: str) -> list[str]:
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def dataset_meta_path(dataset_path: Path) -> Path:
    return dataset_path.with_suffix(".meta.json")


def validate_expanded_dataset(
    dataset_path: Path,
    target_steps: list[str],
) -> dict[str, Any]:
    meta_path = dataset_meta_path(dataset_path)
    if not meta_path.exists():
        raise FileNotFoundError(
            f"expanded dataset metadata required: {meta_path}"
        )
    meta = json.loads(meta_path.read_text())
    if str(meta.get("style", "")) != "risk_off":
        raise ValueError("PR28 dataset must use style=risk_off")
    if list(meta.get("list_types") or []) != ["low_value"]:
        raise ValueError("PR28 dataset must be low_value-only")
    if not bool(meta.get("research_expanded_survivor_dataset")):
        raise ValueError("dataset is not marked research-expanded")
    skipped = {
        str(x)
        for x in (meta.get("research_skipped_low_value_hard_steps") or [])
    }
    missing = sorted(set(target_steps) - skipped)
    if missing:
        raise ValueError(
            "expanded dataset did not skip every target: "
            + ",".join(missing)
        )
    return meta


def compute_soft_pass(
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
    matrix = pd.DataFrame(
        {
            name: pd.Series(mask_fn(out), index=out.index)
            .fillna(False)
            .astype(bool)
            for name, mask_fn in soft_steps
        },
        index=out.index,
    )
    out["soft_pass_count"] = matrix.sum(axis=1)
    out["soft_total"] = len(soft_steps)
    return out


def arm_filter_steps(
    config: ScanConfig,
    channel: str,
    profile: dict[str, Any],
    arm: str,
    target_steps: set[str],
) -> tuple[
    list[tuple[str, Any]],
    list[tuple[str, Any]],
    dict[str, float],
    list[str],
]:
    steps, weights = build_steps_and_weights(
        config,
        channel,
        profile,
        "low_value",
    )
    hard_steps, soft_steps = partition_filter_steps(
        steps,
        channel,
        config.strategy_style,
    )
    active_targets = [
        name for name, _fn in hard_steps if name in target_steps
    ]
    if arm == "baseline":
        return hard_steps, soft_steps, weights, active_targets
    if arm != "hard_to_soft":
        raise ValueError(f"unsupported arm: {arm}")
    target_pairs = [
        (name, fn)
        for name, fn in hard_steps
        if name in target_steps
    ]
    ablated_hard = [
        (name, fn)
        for name, fn in hard_steps
        if name not in target_steps
    ]
    return (
        ablated_hard,
        [*soft_steps, *target_pairs],
        weights,
        active_targets,
    )


def rank_channel(
    group: pd.DataFrame,
    config: ScanConfig,
    channel: str,
    arm: str,
    target_steps: set[str],
) -> tuple[pd.DataFrame, list[str]]:
    profile = (config.channel_profiles or {}).get(channel, {})
    hard_steps, soft_steps, weights, active_targets = arm_filter_steps(
        config,
        channel,
        profile,
        arm,
        target_steps,
    )
    filtered, _diag = apply_filters_with_diagnostics(group, hard_steps)
    if filtered.empty:
        return filtered.copy(), active_targets
    scored_input = compute_soft_pass(filtered, soft_steps)
    ranked = score_and_rank(
        scored_input,
        weights,
        config.score_winsor_lower_q,
        config.score_winsor_upper_q,
        config.score_penalty_overvaluation,
        config.score_penalty_deterioration,
        config.pe_cash_backing_haircut,
    )
    if not ranked.empty:
        ranked = apply_research_assessment(ranked, "low_value")
        ranked = apply_low_value_research_gate(ranked, config)
    ranked = apply_group_caps(
        ranked,
        config.max_per_sector_per_list,
        config.max_per_watchlist_etf_source_per_list,
    )
    if not ranked.empty:
        ranked = ranked.copy()
        ranked["channel"] = channel
    return ranked, active_targets


def finite_mean(values: list[float]) -> float:
    vals = np.asarray([x for x in values if np.isfinite(x)], dtype=float)
    return float(vals.mean()) if len(vals) else float("nan")


def returns_by_symbol(
    date_rows: pd.DataFrame,
    horizon: int,
) -> dict[str, float]:
    out: dict[str, float] = {}
    keyed = date_rows.copy()
    keyed["_symbol_key"] = keyed["symbol"].astype(str).str.upper()
    for symbol, group in keyed.groupby("_symbol_key", sort=False):
        vals = pd.to_numeric(
            group[f"fwd_ret_{horizon}"],
            errors="coerce",
        )
        vals = vals[np.isfinite(vals)]
        if vals.empty:
            continue
        if float(vals.max() - vals.min()) > 1e-10:
            raise ValueError(
                f"inconsistent returns for {symbol} h={horizon}"
            )
        out[str(symbol)] = float(vals.iloc[0])
    return out


def qqq_return(date_rows: pd.DataFrame, horizon: int) -> float:
    vals = pd.to_numeric(
        date_rows[f"qqq_return_{horizon}"],
        errors="coerce",
    )
    vals = vals[np.isfinite(vals)]
    if vals.empty:
        return float("nan")
    if float(vals.max() - vals.min()) > 1e-10:
        raise ValueError(f"inconsistent QQQ return h={horizon}")
    return float(vals.iloc[0])


def evaluate_arms(
    dataset: pd.DataFrame,
    config: ScanConfig,
    channels: list[str],
    target_steps: set[str],
    top_n: int,
    horizons: list[int],
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    rows: list[dict[str, Any]] = []
    active_by_channel: dict[str, list[str]] = {}
    for signal_date, date_rows in dataset.groupby("signal_date", sort=True):
        regime = (
            str(date_rows["regime"].dropna().iloc[0])
            if "regime" in date_rows.columns
            and not date_rows["regime"].dropna().empty
            else "unknown"
        )
        return_maps = {
            h: returns_by_symbol(date_rows, h) for h in horizons
        }
        qqq = {h: qqq_return(date_rows, h) for h in horizons}
        for arm in ARMS:
            ranked_frames: list[pd.DataFrame] = []
            for channel in channels:
                part = date_rows[
                    date_rows["channel"].astype(str) == channel
                ].copy()
                ranked, active_targets = rank_channel(
                    part,
                    config,
                    channel,
                    arm,
                    target_steps,
                )
                active_by_channel.setdefault(channel, active_targets)
                if not ranked.empty:
                    ranked_frames.append(ranked)
            picks, channel_symbols, channel_counts = (
                select_symbols_from_ranked_frames(
                    ranked_frames,
                    top_n=top_n,
                    per_channel_top_n=True,
                    dedupe_best_channel=bool(
                        config.enforce_unique_symbol_per_list
                    ),
                )
            )
            for horizon in horizons:
                selected_returns = [
                    return_maps[horizon][symbol]
                    for symbol in picks
                    if symbol in return_maps[horizon]
                ]
                avg_return = finite_mean(selected_returns)
                excess = (
                    float(avg_return - qqq[horizon])
                    if np.isfinite(avg_return)
                    and np.isfinite(qqq[horizon])
                    else float("nan")
                )
                rows.append(
                    {
                        "signal_date": str(signal_date),
                        "year": str(signal_date)[:4],
                        "regime": regime,
                        "arm": arm,
                        "horizon_days": int(horizon),
                        "n_selected": len(picks),
                        "n_mature_selected": len(selected_returns),
                        "avg_return": avg_return,
                        "qqq_return": qqq[horizon],
                        "excess_vs_qqq": excess,
                        "selected_symbols_json": json.dumps(
                            picks, separators=(",", ":")
                        ),
                        "channel_symbols_json": json.dumps(
                            channel_symbols,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "channel_counts_json": json.dumps(
                            channel_counts,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )
    return pd.DataFrame(rows), active_by_channel


