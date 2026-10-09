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


def load_replay_channel_symbols(
    path: str | Path,
) -> dict[tuple[str, str], list[str]]:
    frame = pd.read_csv(path)
    frame = frame[
        (frame["scenario"].astype(str) == "base")
        & (frame["list_type"].astype(str) == "low_value")
    ].copy()
    out: dict[tuple[str, str], list[str]] = {}
    for row in frame.itertuples(index=False):
        mapping = json.loads(
            str(getattr(row, "channel_symbols", "{}") or "{}")
        )
        signal_date = str(getattr(row, "signal_date"))
        if not isinstance(mapping, dict):
            continue
        for channel, symbols in mapping.items():
            vals = symbols if isinstance(symbols, list) else []
            out[(signal_date, str(channel))] = [
                str(x).strip().upper()
                for x in vals
                if str(x).strip()
            ]
    return out


def build_baseline_parity(
    events: pd.DataFrame,
    replay_symbols: dict[tuple[str, str], list[str]],
    channels: list[str],
) -> pd.DataFrame:
    base = events[
        (events["arm"] == "baseline")
        & (
            events["horizon_days"]
            == int(events["horizon_days"].min())
        )
    ].copy()
    actual_map: dict[tuple[str, str], list[str]] = {}
    for row in base.itertuples(index=False):
        mapping = json.loads(str(row.channel_symbols_json))
        for channel in channels:
            actual_map[(str(row.signal_date), channel)] = [
                str(x).upper()
                for x in mapping.get(channel, [])
            ]

    keys = set(actual_map)
    keys.update(
        key
        for key, symbols in replay_symbols.items()
        if key[1] in channels and symbols
    )

    rows: list[dict[str, Any]] = []
    for signal_date, channel in sorted(keys):
        actual = actual_map.get((signal_date, channel), [])
        expected = replay_symbols.get(
            (signal_date, channel),
            [],
        )
        actual_set = set(actual)
        expected_set = set(expected)
        union = actual_set | expected_set
        rows.append(
            {
                "signal_date": signal_date,
                "channel": channel,
                "actual_n": len(actual),
                "expected_n": len(expected),
                "exact_match": actual == expected,
                "order_match": actual == expected,
                "jaccard": (
                    float(len(actual_set & expected_set) / len(union))
                    if union
                    else 1.0
                ),
                "actual_only": ",".join(
                    sorted(actual_set - expected_set)
                ),
                "expected_only": ",".join(
                    sorted(expected_set - actual_set)
                ),
            }
        )
    return pd.DataFrame(rows)


def build_paired(
    events: pd.DataFrame,
    dataset: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = events[events["arm"] == "baseline"].copy()
    alt = events[events["arm"] == "hard_to_soft"].copy()
    joined = base.merge(
        alt,
        on=["signal_date", "year", "regime", "horizon_days"],
        suffixes=("_baseline", "_ablation"),
        how="inner",
    )
    switch_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    date_groups = {
        str(date): group.copy()
        for date, group in dataset.groupby("signal_date", sort=False)
    }

    for row in joined.itertuples(index=False):
        baseline_symbols = set(
            json.loads(str(row.selected_symbols_json_baseline))
        )
        ablation_symbols = set(
            json.loads(str(row.selected_symbols_json_ablation))
        )
        added = sorted(ablation_symbols - baseline_symbols)
        removed = sorted(baseline_symbols - ablation_symbols)
        union = baseline_symbols | ablation_symbols
        overlap = baseline_symbols & ablation_symbols
        horizon = int(row.horizon_days)
        returns = returns_by_symbol(
            date_groups[str(row.signal_date)],
            horizon,
        )
        qqq = qqq_return(
            date_groups[str(row.signal_date)],
            horizon,
        )
        added_returns = [
            returns[s] for s in added if s in returns
        ]
        removed_returns = [
            returns[s] for s in removed if s in returns
        ]
        delta = (
            float(
                row.avg_return_ablation
                - row.avg_return_baseline
            )
            if np.isfinite(row.avg_return_ablation)
            and np.isfinite(row.avg_return_baseline)
            else float("nan")
        )
        pair_rows.append(
            {
                "signal_date": str(row.signal_date),
                "year": str(row.year),
                "regime": str(row.regime),
                "horizon_days": horizon,
                "baseline_return": row.avg_return_baseline,
                "ablation_return": row.avg_return_ablation,
                "delta_return": delta,
                "baseline_excess": row.excess_vs_qqq_baseline,
                "ablation_excess": row.excess_vs_qqq_ablation,
                "delta_excess": delta,
                "selection_jaccard": (
                    float(len(overlap) / len(union))
                    if union
                    else 1.0
                ),
                "n_added": len(added),
                "n_removed": len(removed),
                "added_symbols": ",".join(added),
                "removed_symbols": ",".join(removed),
                "added_avg_return": finite_mean(added_returns),
                "removed_avg_return": finite_mean(removed_returns),
                "added_minus_removed_return": (
                    float(
                        finite_mean(added_returns)
                        - finite_mean(removed_returns)
                    )
                    if added_returns and removed_returns
                    else float("nan")
                ),
            }
        )
        for side, symbols in (("added", added), ("removed", removed)):
            for symbol in symbols:
                ret = returns.get(symbol, float("nan"))
                switch_rows.append(
                    {
                        "signal_date": str(row.signal_date),
                        "year": str(row.year),
                        "regime": str(row.regime),
                        "horizon_days": horizon,
                        "side": side,
                        "symbol": symbol,
                        "forward_return": ret,
                        "qqq_return": qqq,
                        "excess_vs_qqq": (
                            float(ret - qqq)
                            if np.isfinite(ret)
                            and np.isfinite(qqq)
                            else float("nan")
                        ),
                    }
                )
    return pd.DataFrame(pair_rows), pd.DataFrame(switch_rows)


def summarize_switch_symbols(
    switch_cases: pd.DataFrame,
) -> pd.DataFrame:
    if switch_cases.empty:
        return pd.DataFrame(
            columns=[
                "horizon_days",
                "side",
                "symbol",
                "n_dates",
                "avg_excess_vs_qqq",
                "total_excess_vs_qqq",
                "positive_excess_sum",
                "positive_excess_share",
            ]
        )
    rows: list[dict[str, Any]] = []
    for (horizon, side), scope in switch_cases.groupby(
        ["horizon_days", "side"],
        sort=False,
    ):
        excess_all = pd.to_numeric(
            scope["excess_vs_qqq"],
            errors="coerce",
        )
        positive_total = float(
            excess_all[excess_all > 0.0].sum()
        )
        for symbol, group in scope.groupby("symbol", sort=False):
            excess = pd.to_numeric(
                group["excess_vs_qqq"],
                errors="coerce",
            )
            finite = excess[np.isfinite(excess)]
            positive_sum = float(
                finite[finite > 0.0].sum()
            )
            rows.append(
                {
                    "horizon_days": int(horizon),
                    "side": str(side),
                    "symbol": str(symbol),
                    "n_dates": int(
                        group["signal_date"].astype(str).nunique()
                    ),
                    "avg_excess_vs_qqq": (
                        float(finite.mean())
                        if len(finite)
                        else np.nan
                    ),
                    "total_excess_vs_qqq": (
                        float(finite.sum())
                        if len(finite)
                        else np.nan
                    ),
                    "positive_excess_sum": positive_sum,
                    "positive_excess_share": (
                        float(positive_sum / positive_total)
                        if positive_total > 0.0
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        [
            "horizon_days",
            "side",
            "positive_excess_share",
            "n_dates",
        ],
        ascending=[True, True, False, False],
    )


def summarize_arms(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, pd.DataFrame]] = [
        ("all", "ALL", events)
    ]
    scopes.extend(
        ("year", str(year), part)
        for year, part in events.groupby("year", sort=True)
    )
    scopes.extend(
        ("regime", str(regime), part)
        for regime, part in events.groupby("regime", sort=True)
    )
    for scope, value, frame in scopes:
        for (arm, horizon), group in frame.groupby(
            ["arm", "horizon_days"],
            sort=False,
        ):
            ret = pd.to_numeric(
                group["avg_return"], errors="coerce"
            )
            excess = pd.to_numeric(
                group["excess_vs_qqq"], errors="coerce"
            )
            valid = np.isfinite(ret) & np.isfinite(excess)
            rows.append(
                {
                    "scope": scope,
                    "scope_value": value,
                    "arm": str(arm),
                    "horizon_days": int(horizon),
                    "n_dates": int(valid.sum()),
                    "avg_return": (
                        float(ret[valid].mean())
                        if valid.any()
                        else np.nan
                    ),
                    "avg_excess_vs_qqq": (
                        float(excess[valid].mean())
                        if valid.any()
                        else np.nan
                    ),
                    "positive_return_ratio": (
                        float(ret[valid].gt(0).mean())
                        if valid.any()
                        else np.nan
                    ),
                    "qqq_win_ratio": (
                        float(excess[valid].gt(0).mean())
                        if valid.any()
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def leave_one_out_mean_range(
    values: np.ndarray,
) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return float("nan"), float("nan")
    total = float(values.sum())
    means = (total - values) / (len(values) - 1)
    return float(means.min()), float(means.max())


def summarize_paired(paired: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, pd.DataFrame]] = [
        ("all", "ALL", paired)
    ]
    scopes.extend(
        ("year", str(year), part)
        for year, part in paired.groupby("year", sort=True)
    )
    scopes.extend(
        ("regime", str(regime), part)
        for regime, part in paired.groupby("regime", sort=True)
    )
    for scope, value, frame in scopes:
        for horizon, group in frame.groupby(
            "horizon_days", sort=False
        ):
            delta = pd.to_numeric(
                group["delta_return"],
                errors="coerce",
            ).to_numpy(dtype=float)
            valid = delta[np.isfinite(delta)]
            jaccard = pd.to_numeric(
                group["selection_jaccard"],
                errors="coerce",
            )
            loo_min, loo_max = leave_one_out_mean_range(valid)
            abs_sum = (
                float(np.abs(valid).sum()) if len(valid) else 0.0
            )
            rows.append(
                {
                    "scope": scope,
                    "scope_value": value,
                    "horizon_days": int(horizon),
                    "n_dates": int(len(valid)),
                    "avg_delta_return": (
                        float(np.mean(valid))
                        if len(valid)
                        else np.nan
                    ),
                    "median_delta_return": (
                        float(np.median(valid))
                        if len(valid)
                        else np.nan
                    ),
                    "positive_delta_ratio": (
                        float(np.mean(valid > 0.0))
                        if len(valid)
                        else np.nan
                    ),
                    "worst_delta_return": (
                        float(np.min(valid))
                        if len(valid)
                        else np.nan
                    ),
                    "best_delta_return": (
                        float(np.max(valid))
                        if len(valid)
                        else np.nan
                    ),
                    "mean_selection_jaccard": float(jaccard.mean()),
                    "median_selection_jaccard": float(
                        jaccard.median()
                    ),
                    "top_abs_date_share": (
                        float(
                            np.max(np.abs(valid)) / abs_sum
                        )
                        if len(valid) and abs_sum > 0.0
                        else np.nan
                    ),
                    "loo_mean_min": loo_min,
                    "loo_mean_max": loo_max,
                }
            )
    return pd.DataFrame(rows)


def retrospective_gate(
    parity: pd.DataFrame,
    paired_summary: pd.DataFrame,
    switch_symbol_summary: pd.DataFrame | None = None,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if parity.empty or not bool(parity["exact_match"].all()):
        failures.append("baseline_selection_parity_failed")

    primary = paired_summary[
        paired_summary["horizon_days"] == 120
    ]
    by_year = {
        str(row.scope_value): row
        for row in primary[
            primary["scope"] == "year"
        ].itertuples(index=False)
    }
    for year in ("2023", "2024", "2025"):
        row = by_year.get(year)
        if row is None or int(row.n_dates) < 8:
            failures.append(f"{year}_120d_sample_too_low")
        elif not (
            np.isfinite(row.avg_delta_return)
            and float(row.avg_delta_return) > 0.0
        ):
            failures.append(
                f"{year}_120d_delta_not_positive"
            )

    all_rows = primary[
        (primary["scope"] == "all")
        & (primary["scope_value"] == "ALL")
    ]
    if all_rows.empty:
        failures.append("all_120d_missing")
    else:
        row = all_rows.iloc[0]
        if float(row["positive_delta_ratio"]) <= 0.50:
            failures.append(
                "all_120d_positive_date_ratio_not_above_half"
            )
        if float(row["top_abs_date_share"]) >= 0.35:
            failures.append(
                "all_120d_too_concentrated_by_date"
            )
        if float(row["median_selection_jaccard"]) < 0.50:
            failures.append("selection_overlap_too_low")

    if switch_symbol_summary is not None and not switch_symbol_summary.empty:
        added_120 = switch_symbol_summary[
            (switch_symbol_summary["horizon_days"] == 120)
            & (switch_symbol_summary["side"] == "added")
        ]
        if not added_120.empty:
            top_share = pd.to_numeric(
                added_120["positive_excess_share"],
                errors="coerce",
            ).max()
            if np.isfinite(top_share) and float(top_share) >= 0.35:
                failures.append(
                    "added_120d_positive_excess_too_concentrated_by_symbol"
                )

    down_rows = primary[
        (primary["scope"] == "regime")
        & (primary["scope_value"] == "down")
    ]
    if down_rows.empty or not np.isfinite(
        float(down_rows.iloc[0]["avg_delta_return"])
    ):
        failures.append("down_regime_120d_missing")
    elif float(down_rows.iloc[0]["avg_delta_return"]) < 0.0:
        failures.append("down_regime_120d_degraded")

    return not failures, failures


def write_report(
    path: Path,
    meta: dict[str, Any],
    active_by_channel: dict[str, list[str]],
    parity: pd.DataFrame,
    paired_summary: pd.DataFrame,
    gate_pass: bool,
    failures: list[str],
) -> None:
    lines = [
        "# PR28 risk_off low_value position-gate ablation",
        "",
        "Retrospective mechanism validation only. "
        "This is not OOS and cannot promote production parameters.",
        "",
        "## Contract",
        "",
        "- A: current risk_off low_value pipeline.",
        "- B: move the pre-registered position/range hard gates "
        "to soft; thresholds and all other rules stay unchanged.",
        f"- expanded rows: {int(meta.get('n_rows', 0) or 0)}",
        f"- expanded dates: {int(meta.get('n_dates', 0) or 0)}",
        "- active targets by channel: "
        + json.dumps(active_by_channel, sort_keys=True),
        "",
        "## Baseline replay parity",
        "",
        "- channel-date exact matches: "
        f"{int(parity['exact_match'].sum())}/{len(parity)}",
        "- exact parity: "
        f"{bool(not parity.empty and parity['exact_match'].all())}",
        "",
        "## 120d paired A/B",
        "",
    ]
    primary = paired_summary[
        paired_summary["horizon_days"] == 120
    ]
    for row in primary.itertuples(index=False):
        lines.append(
            f"- {row.scope}:{row.scope_value}: "
            f"n={int(row.n_dates)}, "
            f"mean_delta={float(row.avg_delta_return):+.4f}, "
            f"median_delta={float(row.median_delta_return):+.4f}, "
            f"positive_dates={float(row.positive_delta_ratio):.0%}, "
            f"median_jaccard={float(row.median_selection_jaccard):.2f}, "
            f"top_abs_date_share={float(row.top_abs_date_share):.1%}"
        )

    lines.extend(
        [
            "",
            "## Retrospective robustness gate",
            "",
            f"- pass: **{gate_pass}**",
        ]
    )
    if failures:
        lines.append(
            "- failures: " + ";".join(failures)
        )
    else:
        lines.append(
            "- Pre-registered retrospective checks passed. "
            "This only justifies a later narrow validation PR."
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- 2023 and 2025 are hypothesis-forming years.",
            "- 2024 is the key full-year stress check.",
            "- 2026YTD is diagnostic because 120d labels are immature.",
            "- Down-regime degradation is a stop condition because "
            "risk_off has a defensive role.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset)
    target_steps = parse_tokens(args.target_steps)
    if set(target_steps) != set(DEFAULT_TARGET_STEPS):
        raise ValueError(
            "canonical PR28 run requires exactly: "
            + ",".join(DEFAULT_TARGET_STEPS)
        )
    channels = parse_tokens(args.include_channels)
    horizons = [int(x) for x in parse_tokens(args.horizons)]
    if int(args.top_n) != 10:
        raise ValueError("canonical PR28 run requires top_n=10")

    meta = validate_expanded_dataset(
        dataset_path,
        target_steps,
    )
    dataset = pd.read_csv(dataset_path)
    required = {
        "signal_date",
        "channel",
        "list_type",
        "symbol",
        "regime",
    }
    required.update(f"fwd_ret_{h}" for h in horizons)
    required.update(f"qqq_return_{h}" for h in horizons)
    missing = sorted(required - set(dataset.columns))
    if missing:
        raise ValueError(
            "expanded dataset missing columns: "
            + ",".join(missing)
        )
    if set(dataset["list_type"].astype(str).unique()) != {
        "low_value"
    }:
        raise ValueError(
            "expanded dataset must contain only low_value rows"
        )

    config = load_config(args.scan_config)
    if str(config.strategy_style) != "risk_off":
        raise ValueError("PR28 requires risk_off config")
    config_channels = list((config.channel_profiles or {}).keys())
    channels = [x for x in config_channels if x in channels]
    if not channels:
        raise ValueError("no requested channels present in config")

    events, active_by_channel = evaluate_arms(
        dataset,
        config,
        channels,
        set(target_steps),
        int(args.top_n),
        horizons,
    )
    for channel in channels:
        if set(active_by_channel.get(channel, [])) != set(
            target_steps
        ):
            raise ValueError(
                "target block not fully active in "
                f"{channel}: {active_by_channel.get(channel, [])}"
            )

    replay_symbols = load_replay_channel_symbols(
        args.baseline_signals
    )
    parity = build_baseline_parity(
        events,
        replay_symbols,
        channels,
    )
    paired, switch_cases = build_paired(events, dataset)
    switch_symbol_summary = summarize_switch_symbols(
        switch_cases
    )
    arm_summary = summarize_arms(events)
    paired_summary = summarize_paired(paired)
    gate_pass, failures = retrospective_gate(
        parity,
        paired_summary,
        switch_symbol_summary,
    )

    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    outputs = {
        "events": Path(f"{prefix}_events.csv"),
        "baseline_parity": Path(
            f"{prefix}_baseline_parity.csv"
        ),
        "paired": Path(f"{prefix}_paired.csv"),
        "switch_cases": Path(f"{prefix}_switch_cases.csv"),
        "switch_symbol_summary": Path(
            f"{prefix}_switch_symbol_summary.csv"
        ),
        "arm_summary": Path(f"{prefix}_arm_summary.csv"),
        "paired_summary": Path(
            f"{prefix}_paired_summary.csv"
        ),
        "report": Path(f"{prefix}_report.md"),
    }
    events.to_csv(outputs["events"], index=False)
    parity.to_csv(outputs["baseline_parity"], index=False)
    paired.to_csv(outputs["paired"], index=False)
    switch_cases.to_csv(outputs["switch_cases"], index=False)
    switch_symbol_summary.to_csv(
        outputs["switch_symbol_summary"],
        index=False,
    )
    arm_summary.to_csv(outputs["arm_summary"], index=False)
    paired_summary.to_csv(
        outputs["paired_summary"], index=False
    )
    write_report(
        outputs["report"],
        meta,
        active_by_channel,
        parity,
        paired_summary,
        gate_pass,
        failures,
    )
    summary = {
        "mode": "retrospective_mechanism_ablation",
        "production_promotion_allowed": False,
        "dataset": str(dataset_path),
        "dataset_meta": str(dataset_meta_path(dataset_path)),
        "scan_config": str(args.scan_config),
        "baseline_signals": str(args.baseline_signals),
        "target_steps": target_steps,
        "arms": list(ARMS),
        "retrospective_gate_pass": gate_pass,
        "retrospective_gate_failures": failures,
        "outputs": {
            key: str(value) for key, value in outputs.items()
        },
    }
    Path(f"{prefix}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(
        "PR28 ablation complete: "
        f"gate_pass={gate_pass} failures={failures} "
        f"report={outputs['report']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
