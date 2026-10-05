#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import itertools
import json
import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.backtest import BacktestConfig, run_backtest


DEFAULT_HORIZONS = [20, 60, 120]
DEFAULT_LIST_TYPES = ["low_value", "industry_trend", "momentum", "research_pool"]
DEFAULT_PRIMARY_LIST_TYPES = ["low_value"]
DEFAULT_SCENARIO_WEIGHTS = {"base": 0.6, "loose": 0.2, "strict": 0.2}
DEFAULT_LIST_WEIGHTS = {
    "low_value": 0.35,
    "industry_trend": 0.20,
    "momentum": 0.25,
    "research_pool": 0.20,
}
DEFAULT_HORIZON_WEIGHTS = {20: 0.2, 60: 0.5, 120: 0.3}
DEFAULT_OBJECTIVE_WEIGHTS = {
    "avg_return": 1.0,
    "avg_excess_vs_qqq": 0.8,
    "win_rate_centered": 0.5,
    "std_return_penalty": 0.35,
}


@dataclass
class TuneWindow:
    label: str
    start_date: str
    end_date: str


@dataclass
class Candidate:
    cid: str
    config: dict[str, Any]
    deltas: dict[str, Any]


@dataclass
class CandidateScore:
    cid: str
    objective_score: float
    balanced_rank_score: float
    risk_on_rank_score: float
    risk_off_rank_score: float
    coverage_ratio: float
    avg_win_rate: float
    avg_return: float
    avg_excess_vs_qqq: float
    avg_std_return: float
    worst_max_drawdown: float
    window_stability_std: float
    min_window_valid_events: int
    total_valid_events: int
    positive_window_score_ratio: float
    positive_excess_window_ratio: float
    empty_window_ratio: float
    strict_coverage_ratio: float
    strict_total_valid_events: int
    strict_avg_return: float
    strict_avg_excess_vs_qqq: float
    research_pool_coverage_ratio: float
    research_pool_total_valid_events: int
    research_pool_avg_return: float
    research_pool_avg_excess_vs_qqq: float
    research_pool_avg_win_rate: float
    window_failure_summary: str
    window_metrics_json: str
    constraints_passed: bool
    failure_reason: str
    deltas_json: str


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[tuner {ts}] {msg}", flush=True)


def default_windows_tokens() -> list[str]:
    today = datetime.now(timezone.utc).date()
    y = today.year
    full_years = [y - 3, y - 2, y - 1]
    tokens = [f"{yy}:{yy}-01-01:{yy}-12-31" for yy in full_years]
    tokens.append(f"{y}YTD:{y}-01-01:{today.isoformat()}")
    return tokens


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Programmatic parameter tuning via walk-forward backtest and multi-objective scoring."
    )
    p.add_argument("--base-config", default="configs/config.risk_off.json")
    p.add_argument("--param-space", default="configs/tuner.param_space.json")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--output-prefix", default=None, help="Optional fixed prefix for tuning artifacts.")
    p.add_argument("--work-dir", default="outputs/tuner_work")
    p.add_argument("--windows", default=",".join(default_windows_tokens()))
    p.add_argument(
        "--selection-mode",
        default="walk_forward",
        choices=["walk_forward", "pooled"],
        help="walk_forward selects candidates using only prior windows; pooled is research-only and cannot promote.",
    )
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument("--list-types", default="low_value,industry_trend,momentum,research_pool")
    p.add_argument(
        "--primary-list-types",
        default="low_value",
        help="Comma-separated list types that drive objective scoring and production guardrails.",
    )
    p.add_argument("--search-mode", default="auto", choices=["auto", "grid", "random"])
    p.add_argument(
        "--executor",
        default="local",
        choices=["local", "modal"],
        help="local: run backtests in-process; modal: one cloud container per candidate.",
    )
    p.add_argument("--max-candidates", type=int, default=36)
    p.add_argument("--random-seed", type=int, default=42)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--no-per-channel-top-n", action="store_true")
    p.add_argument("--trading-cost-bps", type=float, default=15.0)
    p.add_argument("--rebalance-frequency", default="weekly", choices=["weekly", "monthly"])
    p.add_argument("--replay-max-symbols", type=int, default=800)
    p.add_argument("--replay-asset-status", default="all", choices=["all", "active", "inactive"])
    p.add_argument("--theme-source", default="rules_proxy", choices=["rules_proxy", "historical_news", "zero"])
    p.add_argument("--disclosure-lookback-days", type=int, default=720)
    p.add_argument("--allow-latest-watchlist-fallback", action="store_true", default=False)
    p.add_argument("--no-latest-watchlist-fallback", action="store_true")
    p.add_argument("--pre-snapshot-universe", default="union", choices=["union", "strict"],
                   help="Universe for replay dates before the first PIT snapshot (default union).")
    p.add_argument("--enable-perturbation", action="store_true", default=True)
    p.add_argument("--no-perturbation", action="store_true")
    p.add_argument(
        "--promote",
        action="store_true",
        default=False,
        help="Explicitly promote the winner for the style identified by --base-config.",
    )
    p.add_argument("--no-promote", action="store_true", help="Deprecated compatibility flag; promotion is off by default.")
    p.add_argument("--risk-on-config-path", default="configs/config.risk_on.json")
    p.add_argument("--balanced-config-path", default="configs/archive/config.balanced.json")  # archived; two-style promote uses risk_on/risk_off
    p.add_argument("--risk-off-config-path", default="configs/config.risk_off.json")
    p.add_argument("--min-total-valid-events", type=int, default=120)
    p.add_argument("--min-window-valid-events", type=int, default=20)
    p.add_argument("--min-avg-return", type=float, default=0.0)
    p.add_argument("--min-avg-excess-vs-qqq", type=float, default=0.0)
    p.add_argument("--min-avg-win-rate", type=float, default=0.52)
    p.add_argument("--min-positive-window-score-ratio", type=float, default=0.5)
    p.add_argument("--min-positive-excess-window-ratio", type=float, default=0.5)
    p.add_argument("--max-empty-window-ratio", type=float, default=0.25)
    p.add_argument("--max-acceptable-drawdown", type=float, default=0.42)
    p.add_argument("--coverage-ratio-floor", type=float, default=0.35)
    p.add_argument(
        "--min-strict-total-valid-events",
        type=int,
        default=0,
        help="Optional guardrail for strict-list events when research_pool is also evaluated.",
    )
    p.add_argument(
        "--strict-coverage-ratio-floor",
        type=float,
        default=0.0,
        help="Optional guardrail for strict-list coverage when research_pool is also evaluated.",
    )
    p.add_argument(
        "--min-strict-avg-win-rate",
        type=float,
        default=0.0,
        help="Optional guardrail for strict-list win rate when research_pool is also evaluated.",
    )
    p.add_argument("--stability-penalty-weight", type=float, default=0.35)
    p.add_argument("--drawdown-penalty-weight", type=float, default=0.6)
    p.add_argument("--negative-return-penalty-weight", type=float, default=0.8)
    p.add_argument("--negative-excess-penalty-weight", type=float, default=1.0)
    p.add_argument("--low-win-rate-penalty-weight", type=float, default=0.6)
    p.add_argument("--positive-window-penalty-weight", type=float, default=0.5)
    p.add_argument("--positive-excess-window-penalty-weight", type=float, default=0.5)
    p.add_argument("--empty-window-penalty-weight", type=float, default=0.7)
    p.add_argument("--prune-backtest-artifacts", action="store_true", default=True)
    p.add_argument("--no-prune-backtest-artifacts", action="store_true")
    return p.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def parse_csv_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_int_csv(raw: str) -> list[int]:
    out: list[int] = []
    for token in parse_csv_list(raw):
        out.append(int(token))
    return out


def parse_windows(raw: str) -> list[TuneWindow]:
    windows: list[TuneWindow] = []
    for item in parse_csv_list(raw):
        parts = item.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid window format: {item}. Use label:YYYY-MM-DD:YYYY-MM-DD")
        label, start_date, end_date = parts
        windows.append(TuneWindow(label=label, start_date=start_date, end_date=end_date))
    if not windows:
        raise ValueError("No windows configured.")
    return windows


def set_by_path(root: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cursor: dict[str, Any] = root
    for idx, part in enumerate(parts):
        is_leaf = idx == len(parts) - 1
        if is_leaf:
            cursor[part] = value
            return
        next_obj = cursor.get(part)
        if not isinstance(next_obj, dict):
            next_obj = {}
            cursor[part] = next_obj
        cursor = next_obj


def load_axes(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    axes = payload.get("axes")
    if not isinstance(axes, list) or not axes:
        raise ValueError("param-space must contain non-empty 'axes' list.")
    norm_axes: list[dict[str, Any]] = []
    for axis in axes:
        if not isinstance(axis, dict):
            raise ValueError("Each axis must be an object.")
        name = str(axis.get("name", "")).strip()
        param_path = str(axis.get("path", "")).strip()
        values = axis.get("values")
        if not name or not param_path:
            raise ValueError(f"Invalid axis (missing name/path): {axis}")
        if not isinstance(values, list) or not values:
            raise ValueError(f"Axis values must be non-empty list: {axis}")
        norm_axes.append({"name": name, "path": param_path, "values": values})
    return norm_axes


def generate_candidates(
    base_config: dict[str, Any],
    axes: list[dict[str, Any]],
    mode: str,
    max_candidates: int,
    seed: int,
) -> list[Candidate]:
    sizes = [len(axis["values"]) for axis in axes]
    total = int(np.prod(sizes, dtype=np.int64))
    if total <= 0:
        raise ValueError("No candidate combinations available.")

    if mode == "auto":
        actual_mode = "grid" if total <= max_candidates else "random"
    else:
        actual_mode = mode

    tuples: list[tuple[Any, ...]] = []
    if actual_mode == "grid":
        tuples = list(itertools.product(*[axis["values"] for axis in axes]))
    else:
        rnd = random.Random(seed)
        seen: set[tuple[str, ...]] = set()
        target = min(max_candidates, total)
        while len(tuples) < target:
            picked = tuple(rnd.choice(axis["values"]) for axis in axes)
            key = tuple(json.dumps(v, sort_keys=True) for v in picked)
            if key in seen:
                continue
            seen.add(key)
            tuples.append(picked)

    if max_candidates > 0 and len(tuples) > max_candidates:
        tuples = tuples[:max_candidates]

    out: list[Candidate] = []
    for idx, combo in enumerate(tuples, start=1):
        cfg = copy.deepcopy(base_config)
        deltas: dict[str, Any] = {}
        for axis, value in zip(axes, combo):
            set_by_path(cfg, axis["path"], value)
            deltas[axis["name"]] = value
        out.append(Candidate(cid=f"cand_{idx:03d}", config=cfg, deltas=deltas))
    return out


def safe_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if math.isnan(out) or math.isinf(out):
        return float("nan")
    return out


def normalize_weight_map(weights: dict[Any, float], keys: list[Any]) -> dict[Any, float]:
    vals = {k: max(0.0, float(weights.get(k, 0.0))) for k in keys}
    s = sum(vals.values())
    if s <= 0:
        uniform = 1.0 / float(len(keys)) if keys else 0.0
        return {k: uniform for k in keys}
    return {k: v / s for k, v in vals.items()}


def max_drawdown_for_series(returns: pd.Series) -> float:
    p = pd.to_numeric(returns, errors="coerce").dropna()
    if p.empty:
        return 0.0
    equity = (1.0 + p).cumprod()
    if equity.empty:
        return 0.0
    # C03: the peak must include the initial NAV of 1.0 — a first-period
    # loss is a drawdown from it, not from a later peak.
    peak = equity.cummax().clip(lower=1.0)
    dd = equity / peak - 1.0
    return float(dd.min())


def finite_nanmean(values: list[float]) -> float:
    finite = [float(x) for x in values if np.isfinite(x)]
    return float(np.mean(finite)) if finite else float("nan")


def mature_horizons_from_summary(
    summary: pd.DataFrame,
    list_types: list[str],
    horizons: list[int],
) -> list[int]:
    if summary.empty:
        return []
    rows = summary[
        summary["list_type"].isin(list_types) & summary["horizon_days"].isin(horizons)
    ].copy()
    if rows.empty:
        return []
    valid = pd.to_numeric(rows.get("n_events_valid"), errors="coerce").fillna(0)
    rows = rows.assign(_n_events_valid=valid)
    mature = (
        rows.groupby("horizon_days", dropna=False)["_n_events_valid"].sum()
        if not rows.empty
        else pd.Series(dtype=float)
    )
    out = [int(h) for h in horizons if float(mature.get(h, 0.0)) > 0.0]
    return out


def aggregate_window_evals(evals: list[dict[str, Any]]) -> dict[str, Any]:
    if not evals:
        return {
            "coverage_ratio": 0.0,
            "avg_win_rate": float("nan"),
            "avg_return": float("nan"),
            "avg_excess_vs_qqq": float("nan"),
            "avg_std_return": float("nan"),
            "total_valid_events": 0,
            "min_window_valid_events": 0,
            "empty_window_ratio": 1.0,
            "worst_max_drawdown": -1.0,
        }
    valid_counts = [int(e.get("total_valid_events", 0) or 0) for e in evals]
    drawdowns: list[float] = []
    for e in evals:
        raw_dd = e.get("max_drawdown", -1.0)
        dd = safe_float(raw_dd)
        drawdowns.append(dd if np.isfinite(dd) else -1.0)
    return {
        "coverage_ratio": finite_nanmean([float(e.get("coverage_ratio", 0.0) or 0.0) for e in evals]),
        "avg_win_rate": finite_nanmean([float(e.get("avg_win_rate", float("nan"))) for e in evals]),
        "avg_return": finite_nanmean([float(e.get("avg_return", float("nan"))) for e in evals]),
        "avg_excess_vs_qqq": finite_nanmean(
            [float(e.get("avg_excess_vs_qqq", float("nan"))) for e in evals]
        ),
        "avg_std_return": finite_nanmean([float(e.get("avg_std_return", float("nan"))) for e in evals]),
        "total_valid_events": int(sum(valid_counts)),
        "min_window_valid_events": min(valid_counts) if valid_counts else 0,
        "empty_window_ratio": float(sum(1 for x in valid_counts if x <= 0) / len(valid_counts))
        if valid_counts
        else 1.0,
        "worst_max_drawdown": float(min(drawdowns)) if drawdowns else -1.0,
    }


def validate_walk_forward_windows(windows: list[TuneWindow]) -> None:
    """Require chronological, non-overlapping windows for OOS selection."""
    if len(windows) < 2:
        raise ValueError("walk_forward selection requires at least two windows")
    previous_end: pd.Timestamp | None = None
    for window in windows:
        start = pd.Timestamp(window.start_date)
        end = pd.Timestamp(window.end_date)
        if start > end:
            raise ValueError(f"window {window.label} starts after it ends")
        if previous_end is not None and start <= previous_end:
            raise ValueError(
                f"walk_forward windows must be chronological and non-overlapping: "
                f"{window.label} starts {start.date()} <= prior end {previous_end.date()}"
            )
        previous_end = end


def _window_metrics(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def aggregate_regime_stats(stats: list[dict[str, Any]]) -> dict[str, Any]:
    # Empty regime windows carry sentinel drawdown=-1.0; exclude them from
    # aggregation rather than letting a no-event year look like a 100% loss.
    usable = [
        s for s in stats
        if isinstance(s, dict) and int(s.get("n_valid", 0) or 0) > 0
    ]
    n_valid = sum(int(s.get("n_valid", 0) or 0) for s in usable)
    n_periods = sum(int(s.get("n_periods", 0) or 0) for s in usable)

    def weighted(key: str) -> float:
        pairs: list[tuple[float, int]] = []
        for s in usable:
            val = safe_float(s.get(key))
            n = int(s.get("n_valid", 0) or 0)
            if np.isfinite(val) and n > 0:
                pairs.append((val, n))
        denom = sum(n for _, n in pairs)
        return float(sum(v * n for v, n in pairs) / denom) if denom else float("nan")

    dds = [
        safe_float(s.get("worst_dd"))
        for s in usable
        if np.isfinite(safe_float(s.get("worst_dd")))
    ]
    return {
        "n_valid": n_valid,
        "n_periods": n_periods,
        "participation": float(n_valid / n_periods) if n_periods else 0.0,
        "avg_ret": weighted("avg_ret"),
        "avg_ex": weighted("avg_ex"),
        "win_rate": weighted("win_rate"),
        "series_std": weighted("series_std"),
        "worst_dd": float(min(dds)) if dds else -1.0,
    }


def score_training_subset(
    row: pd.Series,
    train_labels: list[str],
    profile: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Score one candidate using ONLY the named training windows."""
    metrics = [
        m for m in _window_metrics(row.get("window_metrics_json"))
        if str(m.get("label")) in set(train_labels)
    ]
    if not metrics:
        return {"rank_score": float("-inf"), "constraints_passed": False, "failure_reason": "no_training_metrics"}

    primary_evals = [m.get("primary") or {} for m in metrics]
    strict_evals = [m.get("strict") or {} for m in metrics if m.get("strict") is not None]
    primary = aggregate_window_evals(primary_evals)
    strict = aggregate_window_evals(strict_evals)

    scores = [safe_float(e.get("score")) for e in primary_evals]
    scores = [x for x in scores if np.isfinite(x)]
    excesses = [safe_float(e.get("avg_excess_vs_qqq")) for e in primary_evals]
    excesses = [x for x in excesses if np.isfinite(x)]
    objective = float(np.mean(scores)) if scores else float("-inf")
    stability = float(statistics.pstdev(scores)) if len(scores) > 1 else 0.0
    positive_score_ratio = (
        float(sum(x > 0.0 for x in scores) / len(scores)) if scores else 0.0
    )
    positive_excess_ratio = (
        float(sum(x > 0.0 for x in excesses) / len(excesses)) if excesses else 0.0
    )

    penalty, failures = candidate_constraint_penalty(
        total_valid=int(primary.get("total_valid_events", 0) or 0),
        min_window_valid=int(primary.get("min_window_valid_events", 0) or 0),
        coverage_ratio=float(primary.get("coverage_ratio", 0.0) or 0.0),
        worst_dd=float(primary.get("worst_max_drawdown", -1.0) or -1.0),
        window_stability_std=stability,
        positive_window_score_ratio=positive_score_ratio,
        positive_excess_window_ratio=positive_excess_ratio,
        empty_window_ratio=float(primary.get("empty_window_ratio", 1.0) or 0.0),
        avg_ret=float(primary.get("avg_return", float("nan"))),
        avg_ex=float(primary.get("avg_excess_vs_qqq", float("nan"))),
        avg_win=float(primary.get("avg_win_rate", float("nan"))),
        args=args,
    )
    if strict_evals:
        if int(args.min_strict_total_valid_events) > 0 and int(strict["total_valid_events"]) < int(args.min_strict_total_valid_events):
            penalty += 0.6
            failures.append("strict_total_valid_events_too_low")
        if float(args.strict_coverage_ratio_floor) > 0.0 and float(strict["coverage_ratio"]) < float(args.strict_coverage_ratio_floor):
            penalty += 0.5
            failures.append("strict_coverage_ratio_too_low")
        strict_win = safe_float(strict.get("avg_win_rate"))
        if float(args.min_strict_avg_win_rate) > 0.0 and (
            not np.isfinite(strict_win) or strict_win < float(args.min_strict_avg_win_rate)
        ):
            penalty += 0.5
            failures.append("strict_avg_win_rate_too_low")

    objective_score = objective - penalty
    constraints_passed = len(failures) == 0 and np.isfinite(objective_score)

    up = aggregate_regime_stats([m.get("up_stats") or {} for m in metrics])
    down = aggregate_regime_stats([m.get("down_stats") or {} for m in metrics])
    coverage = float(primary.get("coverage_ratio", 0.0) or 0.0)
    avg_ret = safe_float(primary.get("avg_return"))
    avg_ex = safe_float(primary.get("avg_excess_vs_qqq"))
    avg_win = safe_float(primary.get("avg_win_rate"))
    avg_std = safe_float(primary.get("avg_std_return"))
    worst_dd = float(primary.get("worst_max_drawdown", -1.0) or -1.0)

    if profile == "risk_on" and up["n_valid"] > 0:
        rank_score = (
            0.45 * (up["avg_ex"] if np.isfinite(up["avg_ex"]) else 0.0)
            + 0.25 * (up["win_rate"] - 0.5)
            + 0.15 * up["participation"]
            - 0.15 * (up["series_std"] if np.isfinite(up["series_std"]) else 0.0)
        )
    elif profile == "risk_off" and down["n_valid"] > 0:
        rank_score = (
            0.45 * (down["avg_ex"] if np.isfinite(down["avg_ex"]) else 0.0)
            + 0.35 * (down["win_rate"] - 0.5)
            - 0.20 * max(0.0, abs(down["worst_dd"]) - 0.15)
        )
    elif profile == "risk_on":
        rank_score = (
            objective_score
            + 0.35 * coverage
            + 0.45 * (avg_ret if np.isfinite(avg_ret) else 0.0)
            + 0.20 * (avg_ex if np.isfinite(avg_ex) else 0.0)
        )
    elif profile == "risk_off":
        rank_score = (
            objective_score
            + 0.35 * (avg_win if np.isfinite(avg_win) else 0.0)
            - 0.45 * abs(min(0.0, worst_dd))
            - 0.20 * (avg_std if np.isfinite(avg_std) else 0.0)
        )
    else:
        rank_score = objective_score

    return {
        "rank_score": float(rank_score),
        "objective_score": float(objective_score),
        "constraints_passed": bool(constraints_passed),
        "failure_reason": ";".join(failures),
        "coverage_ratio": coverage,
        "avg_return": avg_ret,
        "avg_excess_vs_qqq": avg_ex,
        "avg_win_rate": avg_win,
        "drawdown_diagnostic": worst_dd,
    }


def heldout_validation(
    row: pd.Series,
    label: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Evaluate the already-selected candidate on one untouched window."""
    metrics = [
        m for m in _window_metrics(row.get("window_metrics_json"))
        if str(m.get("label")) == label
    ]
    if not metrics:
        return {"passed": False, "reason": "heldout_metrics_missing"}
    primary = metrics[0].get("primary") or {}
    score = safe_float(primary.get("score"))
    avg_ret = safe_float(primary.get("avg_return"))
    avg_ex = safe_float(primary.get("avg_excess_vs_qqq"))
    avg_win = safe_float(primary.get("avg_win_rate"))
    coverage = safe_float(primary.get("coverage_ratio"))
    valid = int(primary.get("total_valid_events", 0) or 0)
    reasons: list[str] = []
    if not np.isfinite(score):
        reasons.append("heldout_score_missing")
    if valid < int(args.min_window_valid_events):
        reasons.append("heldout_valid_events_too_low")
    if not np.isfinite(coverage) or coverage < float(args.coverage_ratio_floor):
        reasons.append("heldout_coverage_too_low")
    if not np.isfinite(avg_ret) or avg_ret < float(args.min_avg_return):
        reasons.append("heldout_avg_return_too_low")
    if not np.isfinite(avg_ex) or avg_ex < float(args.min_avg_excess_vs_qqq):
        reasons.append("heldout_avg_excess_too_low")
    if not np.isfinite(avg_win) or avg_win < float(args.min_avg_win_rate):
        reasons.append("heldout_avg_win_rate_too_low")
    return {
        "passed": not reasons,
        "reason": ";".join(reasons),
        "score": score,
        "avg_return": avg_ret,
        "avg_excess_vs_qqq": avg_ex,
        "avg_win_rate": avg_win,
        "coverage_ratio": coverage,
        "valid_events": valid,
    }


def walk_forward_profile_selection(
    scores_df: pd.DataFrame,
    windows: list[TuneWindow],
    profile: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Anchored walk-forward selection: prior windows select, next window validates."""
    validate_walk_forward_windows(windows)
    folds: list[dict[str, Any]] = []
    for idx in range(1, len(windows)):
        train_labels = [w.label for w in windows[:idx]]
        validation_label = windows[idx].label
        ranked: list[tuple[float, str, bool, str]] = []
        for _, row in scores_df.iterrows():
            train = score_training_subset(row, train_labels, profile, args)
            ranked.append(
                (
                    float(train["rank_score"]),
                    str(row["cid"]),
                    bool(train["constraints_passed"]),
                    str(train["failure_reason"]),
                )
            )
        eligible = [x for x in ranked if x[2] and np.isfinite(x[0])]
        pool = eligible if eligible else [x for x in ranked if np.isfinite(x[0])]
        if not pool:
            folds.append(
                {
                    "train_labels": train_labels,
                    "validation_label": validation_label,
                    "selected_cid": None,
                    "training_constraints_passed": False,
                    "training_failure_reason": "no_finite_candidate",
                    "validation": {"passed": False, "reason": "no_selected_candidate"},
                }
            )
            continue
        best = max(pool, key=lambda x: (x[0], x[1]))
        selected = scores_df[scores_df["cid"] == best[1]].iloc[0]
        validation = heldout_validation(selected, validation_label, args)
        folds.append(
            {
                "train_labels": train_labels,
                "validation_label": validation_label,
                "selected_cid": best[1],
                "training_rank_score": best[0],
                "training_constraints_passed": best[2],
                "training_failure_reason": best[3],
                "validation": validation,
            }
        )
    final = folds[-1] if folds else {}
    return {
        "profile": profile,
        "folds": folds,
        "final_candidate": final.get("selected_cid"),
        "promotion_eligible": bool(
            final.get("selected_cid")
            and final.get("training_constraints_passed")
            and (final.get("validation") or {}).get("passed")
        ),
    }


def evaluate_window(
    summary: pd.DataFrame,
    events: pd.DataFrame,
    list_types: list[str],
    horizons: list[int],
    objective_weights: dict[str, float],
    scenario_weights: dict[str, float],
    list_weights: dict[str, float],
    horizon_weights: dict[int, float],
) -> dict[str, Any]:
    if summary.empty:
        return {
            "score": float("-inf"),
            "coverage_ratio": 0.0,
            "avg_win_rate": float("nan"),
            "avg_return": float("nan"),
            "avg_excess_vs_qqq": float("nan"),
            "avg_std_return": float("nan"),
            "total_valid_events": 0,
            "total_events": 0,
            "max_drawdown": -1.0,
        }

    rows = summary.copy()
    rows = rows[rows["list_type"].isin(list_types) & rows["horizon_days"].isin(horizons)].copy()
    if rows.empty:
        return {
            "score": float("-inf"),
            "coverage_ratio": 0.0,
            "avg_win_rate": float("nan"),
            "avg_return": float("nan"),
            "avg_excess_vs_qqq": float("nan"),
            "avg_std_return": float("nan"),
            "total_valid_events": 0,
            "total_events": 0,
            "max_drawdown": -1.0,
        }

    scenario_keys = sorted(str(x) for x in rows["scenario"].dropna().unique().tolist())
    scenario_w = normalize_weight_map(scenario_weights, scenario_keys)
    list_w = normalize_weight_map(list_weights, list_types)
    horizon_w = normalize_weight_map(horizon_weights, horizons)

    weighted_components: list[float] = []
    weighted_returns: list[float] = []
    weighted_excess: list[float] = []
    weighted_win: list[float] = []
    weighted_std: list[float] = []
    weighted_valid = 0.0
    weighted_total = 0.0

    for row in rows.itertuples(index=False):
        scenario = str(getattr(row, "scenario"))
        list_type = str(getattr(row, "list_type"))
        horizon = int(getattr(row, "horizon_days"))
        w = scenario_w.get(scenario, 0.0) * list_w.get(list_type, 0.0) * horizon_w.get(horizon, 0.0)
        if w <= 0:
            continue
        avg_return = safe_float(getattr(row, "avg_return"))
        avg_excess = safe_float(getattr(row, "avg_excess_vs_QQQ"))
        win_rate = safe_float(getattr(row, "win_rate"))
        std_return = safe_float(getattr(row, "std_return"))
        n_valid = safe_float(getattr(row, "n_events_valid"))
        n_total = safe_float(getattr(row, "n_events_total"))

        if not math.isnan(n_valid):
            weighted_valid += w * n_valid
        if not math.isnan(n_total):
            weighted_total += w * n_total
        if not math.isnan(avg_return):
            weighted_returns.append(w * avg_return)
        if not math.isnan(avg_excess):
            weighted_excess.append(w * avg_excess)
        if not math.isnan(win_rate):
            weighted_win.append(w * win_rate)
        if not math.isnan(std_return):
            weighted_std.append(w * std_return)

        component = 0.0
        if not math.isnan(avg_return):
            component += objective_weights["avg_return"] * avg_return
        if not math.isnan(avg_excess):
            component += objective_weights["avg_excess_vs_qqq"] * avg_excess
        if not math.isnan(win_rate):
            component += objective_weights["win_rate_centered"] * (win_rate - 0.5)
        if not math.isnan(std_return):
            component -= objective_weights["std_return_penalty"] * std_return
        weighted_components.append(w * component)

    drawdown = -1.0
    if not events.empty:
        parts = events[
            events["list_type"].isin(list_types) & events["horizon_days"].isin(horizons)
        ].copy()
        if not parts.empty:
            from ai_value_scanner.backtest import non_overlapping_event_returns

            dds: list[float] = []
            for key, part in parts.groupby(["scenario", "list_type", "horizon_days"], dropna=False):
                # R05: overlapping holds reuse the same capital, so the old
                # sequential compounding of ALL events was not an account
                # drawdown. Use the non-overlapping selection (a sampling
                # diagnostic, not a rolling account equity curve).
                horizon = int(key[2]) if key[2] is not None and not pd.isna(key[2]) else 0
                rets = non_overlapping_event_returns(part, horizon) if horizon > 0 else []
                if rets:
                    dds.append(max_drawdown_for_series(pd.Series(rets)))
            if dds:
                drawdown = float(min(dds))

    if not weighted_components:
        score = float("-inf")
    else:
        score = float(sum(weighted_components))

    coverage_ratio = float(weighted_valid / weighted_total) if weighted_total > 0 else 0.0
    return {
        "score": score,
        "coverage_ratio": coverage_ratio,
        "avg_win_rate": float(sum(weighted_win)) if weighted_win else float("nan"),
        "avg_return": float(sum(weighted_returns)) if weighted_returns else float("nan"),
        "avg_excess_vs_qqq": float(sum(weighted_excess)) if weighted_excess else float("nan"),
        "avg_std_return": float(sum(weighted_std)) if weighted_std else float("nan"),
        "total_valid_events": int(round(weighted_valid)),
        "total_events": int(round(weighted_total)),
        "max_drawdown": drawdown,
    }


def load_backtest_frames(
    backtest_result: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_path = Path(backtest_result["summary_path"])
    events_path = Path(backtest_result["events_path"])
    benchmarks_path = Path(backtest_result.get("benchmarks_path", ""))
    summary = pd.read_csv(summary_path) if summary_path.exists() else pd.DataFrame()
    events = pd.read_csv(events_path) if events_path.exists() else pd.DataFrame()
    benchmarks = (
        pd.read_csv(benchmarks_path) if benchmarks_path and Path(benchmarks_path).exists() else pd.DataFrame()
    )
    return summary, events, benchmarks


def non_overlapping_rows(df: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    """Greedy non-overlapping event subsample.

    Monthly sampling with 60d holding overlaps adjacent windows; the raw
    event mean double-counts one market move up to three times. This picks
    a chronological subsample whose entries do not share holding days.
    """
    if df.empty:
        return df
    gap = max(1, int(horizon_days * 1.5))
    order = pd.to_datetime(df["signal_date"]).sort_values()
    keep_positions: list[int] = []
    last_date: pd.Timestamp | None = None
    for pos, dt in zip(order.index, order.tolist(), strict=False):
        if last_date is None or (dt - last_date).days >= gap:
            keep_positions.append(pos)
            last_date = dt
    return df.loc[sorted(keep_positions)]


def regime_stats(
    events: pd.DataFrame,
    benchmarks: pd.DataFrame,
    regime: str,
    list_types: list[str],
    horizons: list[int],
) -> dict[str, Any]:
    """Regime-conditional, overlap-corrected stats from raw events.

    regime: "up" (benchmark 60d trailing return >= 0 at the signal date),
    "down" (< 0), or "all". Missing regime column yields empty stats so the
    caller falls back to the unconditional formula.
    """
    empty = {
        "n_valid": 0,
        "n_periods": 0,
        "participation": 0.0,
        "avg_ret": math.nan,
        "avg_ex": math.nan,
        "win_rate": math.nan,
        "series_std": math.nan,
        "worst_dd": -1.0,
    }
    if events.empty or "regime" not in events.columns:
        return empty
    ev = events[events["regime"] == regime].copy()
    if ev.empty:
        return empty
    ev = ev[ev["list_type"].isin(list_types) & ev["horizon_days"].isin(horizons)]
    if ev.empty:
        return empty
    n_periods = len(ev)
    valid = ev[ev["event_status"].isin(["valid", "partial_valid"])].copy()
    if valid.empty:
        return {**empty, "n_periods": n_periods}
    if not benchmarks.empty and "benchmark" in benchmarks.columns:
        q = benchmarks[benchmarks["benchmark"] == "QQQ"][
            ["scenario", "signal_date", "horizon_days", "benchmark_return"]
        ].drop_duplicates(subset=["scenario", "signal_date", "horizon_days"], keep="last")
        valid = valid.merge(
            q,
            on=["scenario", "signal_date", "horizon_days"],
            how="left",
        )
        valid["excess"] = valid["portfolio_return"] - valid["benchmark_return"]
        avg_ex = float(valid["excess"].mean()) if valid["excess"].notna().any() else math.nan
    else:
        avg_ex = math.nan
    avg_ret = float(valid["portfolio_return"].mean())
    win = float((valid["portfolio_return"] > 0).mean())
    series: list[float] = []
    dds: list[float] = []
    for _, part in valid.groupby(["scenario", "list_type", "horizon_days"], dropna=False):
        horizon = int(part["horizon_days"].iloc[0])
        no = non_overlapping_rows(part, horizon)
        if no.empty:
            continue
        series.extend(float(x) for x in no["portfolio_return"].tolist())
        dds.append(max_drawdown_for_series(no["portfolio_return"]))
    series_std = float(np.std(series)) if len(series) >= 2 else math.nan
    worst_dd = float(min(dds)) if dds else -1.0
    return {
        "n_valid": int(len(valid)),
        "n_periods": int(n_periods),
        "participation": len(valid) / n_periods if n_periods else 0.0,
        "avg_ret": avg_ret,
        "avg_ex": avg_ex,
        "win_rate": win,
        "series_std": series_std,
        "worst_dd": worst_dd,
    }


def classify_window_failure(window_eval: dict[str, Any], events: pd.DataFrame) -> str:
    total_valid = int(window_eval.get("total_valid_events", 0) or 0)
    if total_valid > 0:
        avg_ex = safe_float(window_eval.get("avg_excess_vs_qqq"))
        avg_ret = safe_float(window_eval.get("avg_return"))
        if not math.isnan(avg_ex) and avg_ex < 0:
            return "negative_excess"
        if not math.isnan(avg_ret) and avg_ret < 0:
            return "negative_return"
        return "passed"
    if events.empty:
        return "no_events"
    if "n_selected" in events and pd.to_numeric(events["n_selected"], errors="coerce").fillna(0).sum() <= 0:
        return "no_signal"
    if "n_priced" in events and pd.to_numeric(events["n_priced"], errors="coerce").fillna(0).sum() <= 0:
        return "unpriced"
    return "no_valid_return"


def maybe_prune_backtest_artifacts(backtest_result: dict[str, Any]) -> None:
    for key in (
        "events_path",
        "summary_path",
        "benchmarks_path",
        "segments_path",
        "signal_diagnostics_path",
        "signal_channel_summary_path",
        "report_path",
        "network_path",
    ):
        p = backtest_result.get(key)
        if not p:
            continue
        path = Path(p)
        if path.exists():
            path.unlink()
        if key == "events_path":
            signals = path.with_name(f"{path.stem}_signals.csv")
            if signals.exists():
                signals.unlink()


def candidate_constraint_penalty(
    *,
    total_valid: int,
    min_window_valid: int,
    coverage_ratio: float,
    worst_dd: float,
    window_stability_std: float,
    positive_window_score_ratio: float,
    positive_excess_window_ratio: float,
    empty_window_ratio: float,
    avg_ret: float,
    avg_ex: float,
    avg_win: float,
    args: argparse.Namespace,
) -> tuple[float, list[str]]:
    penalty = 0.0
    failure_reasons: list[str] = []

    if total_valid < int(args.min_total_valid_events):
        penalty += 0.8
        failure_reasons.append("total_valid_events_too_low")
    if min_window_valid < int(args.min_window_valid_events):
        penalty += 0.7
        failure_reasons.append("window_valid_events_too_low")
    if coverage_ratio < float(args.coverage_ratio_floor):
        penalty += 0.7
        failure_reasons.append("coverage_ratio_too_low")
    if worst_dd < -abs(float(args.max_acceptable_drawdown)):
        penalty += abs(worst_dd) * float(args.drawdown_penalty_weight)
        failure_reasons.append("drawdown_too_deep")

    min_avg_ret = float(args.min_avg_return)
    if not np.isfinite(avg_ret) or avg_ret < min_avg_ret:
        gap = min_avg_ret - (avg_ret if np.isfinite(avg_ret) else -min_avg_ret)
        penalty += max(0.0, gap) * float(args.negative_return_penalty_weight)
        failure_reasons.append("avg_return_too_low")

    min_avg_ex = float(args.min_avg_excess_vs_qqq)
    if not np.isfinite(avg_ex) or avg_ex < min_avg_ex:
        gap = min_avg_ex - (avg_ex if np.isfinite(avg_ex) else -min_avg_ex)
        penalty += max(0.0, gap) * float(args.negative_excess_penalty_weight)
        failure_reasons.append("avg_excess_vs_qqq_too_low")

    min_avg_win = float(args.min_avg_win_rate)
    if not np.isfinite(avg_win) or avg_win < min_avg_win:
        gap = min_avg_win - (avg_win if np.isfinite(avg_win) else 0.0)
        penalty += max(0.0, gap) * float(args.low_win_rate_penalty_weight)
        failure_reasons.append("avg_win_rate_too_low")

    min_positive_window_ratio = float(args.min_positive_window_score_ratio)
    if positive_window_score_ratio < min_positive_window_ratio:
        penalty += (min_positive_window_ratio - positive_window_score_ratio) * float(
            args.positive_window_penalty_weight
        )
        failure_reasons.append("positive_window_score_ratio_too_low")

    min_positive_excess_ratio = float(args.min_positive_excess_window_ratio)
    if positive_excess_window_ratio < min_positive_excess_ratio:
        penalty += (min_positive_excess_ratio - positive_excess_window_ratio) * float(
            args.positive_excess_window_penalty_weight
        )
        failure_reasons.append("positive_excess_window_ratio_too_low")

    max_empty_ratio = float(args.max_empty_window_ratio)
    if empty_window_ratio > max_empty_ratio:
        penalty += (empty_window_ratio - max_empty_ratio) * float(args.empty_window_penalty_weight)
        failure_reasons.append("empty_window_ratio_too_high")

    penalty += window_stability_std * float(args.stability_penalty_weight)
    return penalty, failure_reasons


def run_candidate(
    candidate: Candidate,
    windows: list[TuneWindow],
    args: argparse.Namespace,
    output_stem: str,
    horizons: list[int],
    list_types: list[str],
    primary_list_types: list[str],
    objective_weights: dict[str, float],
    scenario_weights: dict[str, float],
    list_weights: dict[str, float],
    horizon_weights: dict[int, float],
    work_dir: Path,
) -> CandidateScore:
    candidate_config_path = work_dir / f"{output_stem}_{candidate.cid}.json"
    write_json(candidate_config_path, candidate.config)

    window_scores: list[float] = []
    regime_events_pool: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    window_valid_counts: list[int] = []
    coverage_values: list[float] = []
    win_values: list[float] = []
    return_values: list[float] = []
    excess_values: list[float] = []
    std_values: list[float] = []
    drawdowns: list[float] = []
    window_failure_reasons: list[str] = []
    strict_window_evals: list[dict[str, Any]] = []
    research_pool_window_evals: list[dict[str, Any]] = []
    primary_window_evals: list[dict[str, Any]] = []
    window_metrics: list[dict[str, Any]] = []
    strict_list_types = [t for t in list_types if t != "research_pool"]
    research_pool_list_types = [t for t in list_types if t == "research_pool"]

    for window in windows:
        prefix = f"{output_stem}_{candidate.cid}_{window.label}"
        cfg = BacktestConfig(
            mode="historical_replay",
            scan_config_path=str(candidate_config_path),
            outputs_dir=args.outputs_dir,
            output_prefix=prefix,
            list_types=list_types,
            top_n=args.top_n,
            per_channel_top_n=not bool(args.no_per_channel_top_n),
            horizons=horizons,
            start_date=window.start_date,
            end_date=window.end_date,
            trading_cost_bps=args.trading_cost_bps,
            rebalance_frequency=args.rebalance_frequency,
            replay_max_symbols=args.replay_max_symbols,
            replay_asset_status=args.replay_asset_status,
            theme_source=args.theme_source,
            disclosure_lookback_days=args.disclosure_lookback_days,
            allow_latest_watchlist_fallback=bool(
                args.allow_latest_watchlist_fallback and not args.no_latest_watchlist_fallback
            ),
            pre_snapshot_universe=args.pre_snapshot_universe,
            enable_perturbation=bool(args.enable_perturbation and not args.no_perturbation),
        )
        log(f"{candidate.cid} | window={window.label} | backtest start")
        bt_result = run_backtest(cfg)
        summary, events, window_benchmarks = load_backtest_frames(bt_result)
        regime_events_pool.append((events, window_benchmarks))
        window_horizons = mature_horizons_from_summary(summary, list_types, horizons) or horizons
        window_eval = evaluate_window(
            summary=summary,
            events=events,
            list_types=list_types,
            horizons=window_horizons,
            objective_weights=objective_weights,
            scenario_weights=scenario_weights,
            list_weights=list_weights,
            horizon_weights=horizon_weights,
        )
        primary_horizons = (
            mature_horizons_from_summary(summary, primary_list_types, horizons) or window_horizons
        )
        primary_eval = evaluate_window(
            summary=summary,
            events=events,
            list_types=primary_list_types,
            horizons=primary_horizons,
            objective_weights=objective_weights,
            scenario_weights=scenario_weights,
            list_weights={k: list_weights.get(k, 1.0) for k in primary_list_types},
            horizon_weights=horizon_weights,
        )
        primary_window_evals.append(primary_eval)
        strict_eval_for_window: dict[str, Any] | None = None
        research_eval_for_window: dict[str, Any] | None = None
        if strict_list_types:
            strict_horizons = (
                mature_horizons_from_summary(summary, strict_list_types, horizons) or window_horizons
            )
            strict_eval_for_window = evaluate_window(
                summary=summary,
                events=events,
                list_types=strict_list_types,
                horizons=strict_horizons,
                objective_weights=objective_weights,
                scenario_weights=scenario_weights,
                list_weights={k: list_weights.get(k, 0.0) for k in strict_list_types},
                horizon_weights=horizon_weights,
            )
            strict_window_evals.append(strict_eval_for_window)
        if research_pool_list_types:
            research_pool_horizons = (
                mature_horizons_from_summary(summary, research_pool_list_types, horizons)
                or window_horizons
            )
            research_eval_for_window = evaluate_window(
                summary=summary,
                events=events,
                list_types=research_pool_list_types,
                horizons=research_pool_horizons,
                objective_weights=objective_weights,
                scenario_weights=scenario_weights,
                list_weights={"research_pool": 1.0},
                horizon_weights=horizon_weights,
            )
            research_pool_window_evals.append(research_eval_for_window)

        up_for_window = regime_stats(events, window_benchmarks, "up", list_types, horizons)
        down_for_window = regime_stats(events, window_benchmarks, "down", list_types, horizons)
        window_failure = classify_window_failure(primary_eval, events)
        window_failure_reasons.append(window_failure)
        window_metrics.append(
            {
                "label": window.label,
                "start_date": window.start_date,
                "end_date": window.end_date,
                "primary": primary_eval,
                "strict": strict_eval_for_window,
                "research_pool": research_eval_for_window,
                "up_stats": up_for_window,
                "down_stats": down_for_window,
                "failure_reason": window_failure,
            }
        )
        if bool(args.prune_backtest_artifacts and not args.no_prune_backtest_artifacts):
            maybe_prune_backtest_artifacts(bt_result)

        window_scores.append(float(primary_eval["score"]))
        window_valid_counts.append(int(primary_eval["total_valid_events"]))
        coverage_values.append(float(primary_eval["coverage_ratio"]))
        win_values.append(float(primary_eval["avg_win_rate"]))
        return_values.append(float(primary_eval["avg_return"]))
        excess_values.append(float(primary_eval["avg_excess_vs_qqq"]))
        std_values.append(float(primary_eval["avg_std_return"]))
        drawdowns.append(float(primary_eval["max_drawdown"]))
        log(
            f"{candidate.cid} | window={window.label} | primary_score={primary_eval['score']:.4f} "
            f"primary_valid={primary_eval['total_valid_events']} primary_dd={primary_eval['max_drawdown']:.3f}"
        )

    finite_window_scores = [x for x in window_scores if np.isfinite(x)]
    objective = float(np.mean(finite_window_scores)) if finite_window_scores else float("-inf")
    window_stability_std = (
        float(statistics.pstdev(finite_window_scores)) if len(finite_window_scores) > 1 else 0.0
    )
    finite_window_excess = [x for x in excess_values if np.isfinite(x)]
    empty_window_ratio = (
        float(sum(1 for x in window_valid_counts if x <= 0) / len(window_valid_counts))
        if window_valid_counts
        else 1.0
    )
    min_window_valid = min(window_valid_counts) if window_valid_counts else 0
    total_valid = int(sum(window_valid_counts))
    coverage_ratio = finite_nanmean(coverage_values) if coverage_values else 0.0
    avg_win = finite_nanmean(win_values)
    avg_ret = finite_nanmean(return_values)
    avg_ex = finite_nanmean(excess_values)
    avg_std = finite_nanmean(std_values)
    worst_dd = float(min(drawdowns)) if drawdowns else -1.0
    strict_eval = aggregate_window_evals(strict_window_evals)
    research_pool_eval = aggregate_window_evals(research_pool_window_evals)
    primary_eval = aggregate_window_evals(primary_window_evals)
    primary_window_scores = finite_window_scores
    primary_window_excess = finite_window_excess
    constraint_window_stability_std = (
        float(statistics.pstdev(primary_window_scores)) if len(primary_window_scores) > 1 else 0.0
    )
    positive_window_score_ratio = (
        float(sum(1 for x in primary_window_scores if x > 0.0) / len(primary_window_scores))
        if primary_window_scores
        else 0.0
    )
    positive_excess_window_ratio = (
        float(sum(1 for x in primary_window_excess if x > 0.0) / len(primary_window_excess))
        if primary_window_excess
        else 0.0
    )
    primary_worst_dd = float(primary_eval.get("worst_max_drawdown", worst_dd) or worst_dd)

    penalty, failure_reasons = candidate_constraint_penalty(
        total_valid=int(primary_eval.get("total_valid_events", total_valid) or 0),
        min_window_valid=int(primary_eval.get("min_window_valid_events", min_window_valid) or 0),
        coverage_ratio=float(primary_eval.get("coverage_ratio", coverage_ratio) or 0.0),
        worst_dd=primary_worst_dd,
        window_stability_std=constraint_window_stability_std,
        positive_window_score_ratio=positive_window_score_ratio,
        positive_excess_window_ratio=positive_excess_window_ratio,
        empty_window_ratio=float(primary_eval.get("empty_window_ratio", empty_window_ratio) or 0.0),
        avg_ret=float(primary_eval.get("avg_return", avg_ret)),
        avg_ex=float(primary_eval.get("avg_excess_vs_qqq", avg_ex)),
        avg_win=float(primary_eval.get("avg_win_rate", avg_win)),
        args=args,
    )
    if strict_list_types:
        min_strict_total = int(args.min_strict_total_valid_events)
        if min_strict_total > 0 and int(strict_eval["total_valid_events"]) < min_strict_total:
            penalty += 0.6
            failure_reasons.append("strict_total_valid_events_too_low")

        strict_coverage_floor = float(args.strict_coverage_ratio_floor)
        if strict_coverage_floor > 0.0 and float(strict_eval["coverage_ratio"]) < strict_coverage_floor:
            penalty += 0.5
            failure_reasons.append("strict_coverage_ratio_too_low")

        min_strict_win = float(args.min_strict_avg_win_rate)
        strict_win = float(strict_eval["avg_win_rate"])
        if min_strict_win > 0.0 and (not np.isfinite(strict_win) or strict_win < min_strict_win):
            penalty += 0.5
            failure_reasons.append("strict_avg_win_rate_too_low")
    objective_score = objective - penalty

    constraints_passed = len(failure_reasons) == 0 and np.isfinite(objective_score)
    failure_reason = ";".join(failure_reasons)

    rank_coverage = float(coverage_ratio)
    rank_avg_ret = float(avg_ret)
    rank_avg_ex = float(avg_ex)
    rank_avg_win = float(avg_win)

    # Regime-conditional rank scores (Phase 2): each style is graded only on
    # the market regime it is built for, using overlap-corrected statistics.
    # risk_on -> up-regime: excess-first with participation (idle periods in a
    # rising benchmark are opportunity cost). risk_off -> down-regime: excess
    # + win rate, penalizing drawdown beyond 15%. Falls back to the legacy
    # unconditional formula when the replay lacked regime tags.
    regime_list_types = list(list_types)
    regime_horizons = list(horizons)
    pooled_events = pd.concat(
        [ev for ev, _ in regime_events_pool if not ev.empty], ignore_index=True
    ) if regime_events_pool else pd.DataFrame()
    pooled_benchmarks = pd.concat(
        [b for _, b in regime_events_pool if not b.empty], ignore_index=True
    ) if regime_events_pool else pd.DataFrame()

    up_stats = regime_stats(pooled_events, pooled_benchmarks, "up", regime_list_types, regime_horizons)
    down_stats = regime_stats(pooled_events, pooled_benchmarks, "down", regime_list_types, regime_horizons)

    if up_stats["n_valid"] > 0 and "regime" in pooled_events.columns:
        risk_on_rank_score = (
            0.45 * (up_stats["avg_ex"] if np.isfinite(up_stats["avg_ex"]) else 0.0)
            + 0.25 * (up_stats["win_rate"] - 0.5)
            + 0.15 * up_stats["participation"]
            - 0.15 * (up_stats["series_std"] if np.isfinite(up_stats["series_std"]) else 0.0)
        )
    else:
        risk_on_rank_score = (
            objective_score
            + (0.35 * rank_coverage)
            + (0.45 * (rank_avg_ret if np.isfinite(rank_avg_ret) else 0.0))
            + (0.20 * (rank_avg_ex if np.isfinite(rank_avg_ex) else 0.0))
        )
    if down_stats["n_valid"] > 0 and "regime" in pooled_events.columns:
        risk_off_rank_score = (
            0.45 * (down_stats["avg_ex"] if np.isfinite(down_stats["avg_ex"]) else 0.0)
            + 0.35 * (down_stats["win_rate"] - 0.5)
            - 0.20 * max(0.0, abs(down_stats["worst_dd"]) - 0.15)
        )
    else:
        risk_off_rank_score = (
            objective_score
            + (0.35 * (rank_avg_win if np.isfinite(rank_avg_win) else 0.0))
            - (0.45 * abs(min(0.0, primary_worst_dd)))
            - (0.20 * (avg_std if np.isfinite(avg_std) else 0.0))
        )
    balanced_rank_score = objective_score

    return CandidateScore(
        cid=candidate.cid,
        objective_score=float(objective_score),
        balanced_rank_score=float(balanced_rank_score),
        risk_on_rank_score=float(risk_on_rank_score),
        risk_off_rank_score=float(risk_off_rank_score),
        coverage_ratio=float(coverage_ratio),
        avg_win_rate=float(avg_win),
        avg_return=float(avg_ret),
        avg_excess_vs_qqq=float(avg_ex),
        avg_std_return=float(avg_std),
        worst_max_drawdown=float(worst_dd),
        window_stability_std=float(window_stability_std),
        min_window_valid_events=int(min_window_valid),
        total_valid_events=int(total_valid),
        positive_window_score_ratio=float(positive_window_score_ratio),
        positive_excess_window_ratio=float(positive_excess_window_ratio),
        empty_window_ratio=float(empty_window_ratio),
        strict_coverage_ratio=float(strict_eval["coverage_ratio"]),
        strict_total_valid_events=int(strict_eval["total_valid_events"]),
        strict_avg_return=float(strict_eval["avg_return"]),
        strict_avg_excess_vs_qqq=float(strict_eval["avg_excess_vs_qqq"]),
        research_pool_coverage_ratio=float(research_pool_eval["coverage_ratio"]),
        research_pool_total_valid_events=int(research_pool_eval["total_valid_events"]),
        research_pool_avg_return=float(research_pool_eval["avg_return"]),
        research_pool_avg_excess_vs_qqq=float(research_pool_eval["avg_excess_vs_qqq"]),
        research_pool_avg_win_rate=float(research_pool_eval["avg_win_rate"]),
        window_failure_summary=json.dumps(
            {k: window_failure_reasons.count(k) for k in sorted(set(window_failure_reasons))},
            ensure_ascii=False,
            sort_keys=True,
        ),
        window_metrics_json=json.dumps(window_metrics, ensure_ascii=False, sort_keys=True),
        constraints_passed=bool(constraints_passed),
        failure_reason=failure_reason,
        deltas_json=json.dumps(candidate.deltas, ensure_ascii=False, sort_keys=True),
    )


def promotion_profile_from_base_config(path: str) -> str | None:
    """Return the production style owned by this tuning run.

    A candidate family is a deep copy of one base config, so it is only valid
    for that same style. Cross-promoting a risk_off-derived candidate into
    risk_on (or vice versa) silently overwrites style-specific fields that are
    outside the tuning parameter space.
    """
    name = Path(path).name
    if name == "config.risk_on.json":
        return "risk_on"
    if name == "config.risk_off.json":
        return "risk_off"
    return None


def pick_profile_candidates(scores_df: pd.DataFrame) -> dict[str, str]:
    valid = scores_df[scores_df["constraints_passed"] == True].copy()
    if valid.empty:
        valid = scores_df.copy()

    picks: dict[str, str] = {}
    # Two-style: balanced_rank_score is kept in the DataFrame for ranking
    # context, but balanced is no longer a promote target (archived).
    order = [
        ("risk_on", "risk_on_rank_score"),
        ("risk_off", "risk_off_rank_score"),
    ]
    for profile, col in order:
        ranked = valid.sort_values(by=col, ascending=False).reset_index(drop=True)
        if ranked.empty:
            continue
        choice = str(ranked.iloc[0]["cid"])
        picks[profile] = choice
    return picks


def write_tuning_report(
    path: Path,
    stamp: str,
    args: argparse.Namespace,
    windows: list[TuneWindow],
    scores_df: pd.DataFrame,
    picks: dict[str, str],
    walk_forward: dict[str, Any] | None = None,
) -> None:
    lines: list[str] = []
    lines.append("# Parameter Tuning Report")
    lines.append("")
    lines.append(f"- generated_utc: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- tuning_run_id: `{stamp}`")
    lines.append(f"- base_config: `{args.base_config}`")
    lines.append(f"- param_space: `{args.param_space}`")
    lines.append(f"- list_types: `{args.list_types}`")
    lines.append(f"- primary_list_types: `{args.primary_list_types}`")
    lines.append(f"- windows: `{', '.join(f'{w.label}:{w.start_date}->{w.end_date}' for w in windows)}`")
    lines.append(f"- candidate_count: {len(scores_df)}")
    lines.append(f"- selection_mode: `{args.selection_mode}`")
    lines.append(f"- constraints_passed (pooled diagnostic): {int((scores_df['constraints_passed'] == True).sum())}")
    lines.append(
        "- guardrails: "
        f"min_avg_return={args.min_avg_return}, "
        f"min_avg_excess_vs_qqq={args.min_avg_excess_vs_qqq}, "
        f"min_avg_win_rate={args.min_avg_win_rate}, "
        f"min_positive_window_score_ratio={args.min_positive_window_score_ratio}, "
        f"min_positive_excess_window_ratio={args.min_positive_excess_window_ratio}, "
        f"max_empty_window_ratio={args.max_empty_window_ratio}"
    )
    if walk_forward:
        lines.append("")
        lines.append("## Anchored Walk-Forward OOS")
        lines.append("")
        lines.append(
            "Each fold selects a candidate using only the preceding windows; "
            "the next window is held out until after selection. The final candidate "
            "is the one selected before the last window, not a candidate re-ranked on that held-out data."
        )
        lines.append("")
        for profile in ("risk_on", "risk_off"):
            result = walk_forward.get(profile) or {}
            lines.append(f"### {profile}")
            lines.append("")
            for fold in result.get("folds", []):
                selected = fold.get("selected_cid") or "none"
                validation = fold.get("validation") or {}
                train = "+".join(fold.get("train_labels") or [])
                valid_label = fold.get("validation_label")
                lines.append(
                    f"- train=`{train}` → held-out=`{valid_label}` | selected=`{selected}` "
                    f"| train_pass={bool(fold.get('training_constraints_passed'))} "
                    f"| OOS_pass={bool(validation.get('passed'))} "
                    f"| OOS_score={safe_float(validation.get('score')):.4f} "
                    f"| OOS_excess={safe_float(validation.get('avg_excess_vs_qqq')):.4f}"
                )
                if fold.get("training_failure_reason"):
                    lines.append(f"  training_failure: `{fold['training_failure_reason']}`")
                if validation.get("reason"):
                    lines.append(f"  OOS_failure: `{validation['reason']}`")
            lines.append(
                f"- final_candidate: `{result.get('final_candidate') or 'none'}` "
                f"| promotion_eligible={bool(result.get('promotion_eligible'))}"
            )
            lines.append("")
    lines.append("")
    lines.append("## Profile Picks")
    lines.append("")
    for name in ("risk_on", "risk_off"):  # balanced archived
        cid = picks.get(name)
        if not cid:
            lines.append(f"- {name}: none")
            continue
        if walk_forward and (walk_forward.get(name) or {}).get("folds"):
            final_fold = walk_forward[name]["folds"][-1]
            validation = final_fold.get("validation") or {}
            lines.append(
                f"- {name}: `{cid}` | selected_on="
                f"`{'+'.join(final_fold.get('train_labels') or [])}` "
                f"| train_rank={safe_float(final_fold.get('training_rank_score')):.4f} "
                f"| held_out=`{final_fold.get('validation_label')}` "
                f"| OOS_pass={bool(validation.get('passed'))} "
                f"| OOS_score={safe_float(validation.get('score')):.4f} "
                f"| OOS_excess={safe_float(validation.get('avg_excess_vs_qqq')):.4f}"
            )
        else:
            row = scores_df[scores_df["cid"] == cid].iloc[0]
            lines.append(
                f"- {name}: `{cid}` | pooled_objective={row['objective_score']:.4f} "
                f"| pooled_coverage={row['coverage_ratio']:.3f} "
                f"| nonoverlap_dd_diagnostic={row['worst_max_drawdown']:.3f}"
            )
    lines.append("")
    lines.append(
        "## Top 10 Candidates (Pooled Diagnostic; not used for walk-forward selection)"
    )
    lines.append("")
    top = scores_df.sort_values(by="balanced_rank_score", ascending=False).head(10)
    for row in top.itertuples(index=False):
        lines.append(
            f"- `{row.cid}` | obj={row.objective_score:.4f} | cov={row.coverage_ratio:.3f} "
            f"| win={row.avg_win_rate:.3f} | dd={row.worst_max_drawdown:.3f} "
            f"| strict_valid={int(getattr(row, 'strict_total_valid_events', 0) or 0)} "
            f"| research_valid={int(getattr(row, 'research_pool_total_valid_events', 0) or 0)} "
            f"| research_excess={float(getattr(row, 'research_pool_avg_excess_vs_qqq', float('nan'))):.4f} "
            f"| pos_score_windows={row.positive_window_score_ratio:.3f} "
            f"| pos_excess_windows={row.positive_excess_window_ratio:.3f} "
            f"| empty_windows={row.empty_window_ratio:.3f} | pass={row.constraints_passed}"
        )
        if str(row.failure_reason or ""):
            lines.append(f"  failure_reason: `{row.failure_reason}`")
        if str(row.window_failure_summary or ""):
            lines.append(f"  window_failure_summary: `{row.window_failure_summary}`")
        lines.append(f"  deltas: `{row.deltas_json}`")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()

    base_path = Path(args.base_config)
    param_space_path = Path(args.param_space)
    outputs_dir = Path(args.outputs_dir)
    work_dir = Path(args.work_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    windows = parse_windows(args.windows)
    horizons = parse_int_csv(args.horizons)
    list_types = parse_csv_list(args.list_types)
    primary_list_types = parse_csv_list(args.primary_list_types)
    if not primary_list_types:
        primary_list_types = list(DEFAULT_PRIMARY_LIST_TYPES)
    missing_primary = sorted(set(primary_list_types) - set(list_types))
    if missing_primary:
        raise ValueError(
            "--primary-list-types must be a subset of --list-types; "
            f"missing from --list-types: {','.join(missing_primary)}"
        )
    stamp = args.output_prefix or datetime.now(timezone.utc).strftime("tuning_%Y%m%dT%H%M%SZ")

    if bool(args.allow_latest_watchlist_fallback and not args.no_latest_watchlist_fallback):
        log(
            "WARNING: --allow-latest-watchlist-fallback is ON: replay windows "
            "without PIT watchlist snapshots will use the latest (future) "
            "constituents — tuning scores contain lookahead bias. "
            "Research-only; do not promote these configs."
        )

    base_config = read_json(base_path)
    axes = load_axes(param_space_path)
    candidates = generate_candidates(
        base_config=base_config,
        axes=axes,
        mode=args.search_mode,
        max_candidates=args.max_candidates,
        seed=args.random_seed,
    )
    log(f"tuning_run_id={stamp}")
    log(f"search_mode={args.search_mode} candidates={len(candidates)}")
    log(f"selection_mode={args.selection_mode}")
    log(f"list_types={','.join(list_types)} primary_list_types={','.join(primary_list_types)}")

    objective_weights = dict(DEFAULT_OBJECTIVE_WEIGHTS)
    scenario_weights = dict(DEFAULT_SCENARIO_WEIGHTS)
    list_weights = dict(DEFAULT_LIST_WEIGHTS)
    horizon_weights = dict(DEFAULT_HORIZON_WEIGHTS)

    rows: list[dict[str, Any]] = []
    candidate_map = {c.cid: c for c in candidates}

    if getattr(args, "executor", "local") == "modal":
        # Candidate-level cloud parallelism: each candidate's full replay
        # runs inside its own Modal container; scoring logic is reused
        # verbatim on the remote side via run_candidate.
        from modal_executor import dispatch

        log("executor=modal: dispatching candidates to Modal (parallel)")
        remote_results = dispatch(
            candidates=candidates,
            windows=windows,
            args=args,
            output_stem=stamp,
        )
        for idx, res in enumerate(remote_results, start=1):
            if not res.get("ok"):
                log(f"[{idx}] {res.get('cid')} FAILED on Modal: {res.get('error')}")
                continue
            cid = res.get("cid")
            res.pop("ok", None)
            res.pop("traceback", None)
            log(f"[{idx}] {cid} objective={res.get('objective_score'):.4f} risk_on={res.get('risk_on_rank_score'):.4f} risk_off={res.get('risk_off_rank_score'):.4f}")
            rows.append(res)
    else:
        for idx, candidate in enumerate(candidates, start=1):
            log(f"[{idx}/{len(candidates)}] evaluating {candidate.cid}")
            score = run_candidate(
                candidate=candidate,
                windows=windows,
                args=args,
                output_stem=stamp,
                horizons=horizons,
                list_types=list_types,
                primary_list_types=primary_list_types,
                objective_weights=objective_weights,
                scenario_weights=scenario_weights,
                list_weights=list_weights,
                horizon_weights=horizon_weights,
                work_dir=work_dir,
            )
            rows.append(score.__dict__)

    scores_df = pd.DataFrame(rows)
    results_csv = outputs_dir / f"{stamp}_results.csv"
    scores_df.sort_values(by="balanced_rank_score", ascending=False).to_csv(results_csv, index=False)

    walk_forward: dict[str, Any] | None = None
    if args.selection_mode == "walk_forward":
        validate_walk_forward_windows(windows)
        walk_forward = {
            profile: walk_forward_profile_selection(scores_df, windows, profile, args)
            for profile in ("risk_on", "risk_off")
        }
        picks = {
            profile: str(result["final_candidate"])
            for profile, result in walk_forward.items()
            if result.get("final_candidate")
        }
    else:
        picks = pick_profile_candidates(scores_df)

    report_path = outputs_dir / f"{stamp}_report.md"
    write_tuning_report(
        path=report_path,
        stamp=stamp,
        args=args,
        windows=windows,
        scores_df=scores_df,
        picks=picks,
        walk_forward=walk_forward,
    )

    if bool(args.promote and not args.no_promote):
        if args.selection_mode != "walk_forward":
            raise SystemExit(
                "--promote requires --selection-mode walk_forward. "
                "Pooled ranking uses validation windows during selection and is research-only."
            )
        profile = promotion_profile_from_base_config(args.base_config)
        if profile is None:
            raise SystemExit(
                "--promote requires --base-config to be exactly "
                "configs/config.risk_on.json or configs/config.risk_off.json; "
                "a tuning run may only promote back into its own style."
            )
        wf_profile = (walk_forward or {}).get(profile) or {}
        cid = wf_profile.get("final_candidate")
        if not cid:
            log(f"skipped promotion for {profile}: no final walk-forward candidate")
        elif not bool(wf_profile.get("promotion_eligible")):
            log(
                f"skipped promotion for {profile}: {cid} was selected without the final held-out "
                "window, but its OOS validation did not pass"
            )
        else:
            target_path = Path(
                args.risk_on_config_path if profile == "risk_on" else args.risk_off_config_path
            )
            write_json(target_path, candidate_map[str(cid)].config)
            log(f"promoted {profile}: {cid} -> {target_path} (walk-forward OOS validated)")

    summary_json = outputs_dir / f"{stamp}_summary.json"
    payload = {
        "tuning_run_id": stamp,
        "base_config": args.base_config,
        "param_space": args.param_space,
        "list_types": list_types,
        "primary_list_types": primary_list_types,
        "selection_mode": args.selection_mode,
        "candidates": len(candidates),
        "picks": picks,
        "walk_forward": walk_forward,
        "results_csv": str(results_csv),
        "report_path": str(report_path),
    }
    write_json(summary_json, payload)
    log(f"results: {results_csv}")
    log(f"report: {report_path}")
    log(f"summary: {summary_json}")


if __name__ == "__main__":
    main()
