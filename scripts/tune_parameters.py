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
    p.add_argument("--base-config", default="configs/config.balanced.json")
    p.add_argument("--param-space", default="configs/tuner.param_space.json")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--output-prefix", default=None, help="Optional fixed prefix for tuning artifacts.")
    p.add_argument("--work-dir", default="outputs/tuner_work")
    p.add_argument("--windows", default=",".join(default_windows_tokens()))
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument("--list-types", default="low_value,industry_trend,momentum,research_pool")
    p.add_argument("--search-mode", default="auto", choices=["auto", "grid", "random"])
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
    p.add_argument("--allow-latest-watchlist-fallback", action="store_true", default=True)
    p.add_argument("--no-latest-watchlist-fallback", action="store_true")
    p.add_argument("--enable-perturbation", action="store_true", default=True)
    p.add_argument("--no-perturbation", action="store_true")
    p.add_argument("--promote", action="store_true", default=True)
    p.add_argument("--no-promote", action="store_true")
    p.add_argument("--risk-on-config-path", default="configs/config.risk_on.json")
    p.add_argument("--balanced-config-path", default="configs/config.balanced.json")
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
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def finite_nanmean(values: list[float]) -> float:
    finite = [float(x) for x in values if np.isfinite(x)]
    return float(np.mean(finite)) if finite else float("nan")


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
    drawdowns = [float(e.get("max_drawdown", -1.0) or -1.0) for e in evals]
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
            dds: list[float] = []
            for _, part in parts.groupby(["scenario", "list_type", "horizon_days"], dropna=False):
                dds.append(max_drawdown_for_series(part["portfolio_return"]))
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


def load_backtest_frames(backtest_result: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_path = Path(backtest_result["summary_path"])
    events_path = Path(backtest_result["events_path"])
    summary = pd.read_csv(summary_path) if summary_path.exists() else pd.DataFrame()
    events = pd.read_csv(events_path) if events_path.exists() else pd.DataFrame()
    return summary, events


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
    objective_weights: dict[str, float],
    scenario_weights: dict[str, float],
    list_weights: dict[str, float],
    horizon_weights: dict[int, float],
    work_dir: Path,
) -> CandidateScore:
    candidate_config_path = work_dir / f"{output_stem}_{candidate.cid}.json"
    write_json(candidate_config_path, candidate.config)

    window_scores: list[float] = []
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
            enable_perturbation=bool(args.enable_perturbation and not args.no_perturbation),
        )
        log(f"{candidate.cid} | window={window.label} | backtest start")
        bt_result = run_backtest(cfg)
        summary, events = load_backtest_frames(bt_result)
        window_eval = evaluate_window(
            summary=summary,
            events=events,
            list_types=list_types,
            horizons=horizons,
            objective_weights=objective_weights,
            scenario_weights=scenario_weights,
            list_weights=list_weights,
            horizon_weights=horizon_weights,
        )
        if strict_list_types:
            strict_window_evals.append(
                evaluate_window(
                    summary=summary,
                    events=events,
                    list_types=strict_list_types,
                    horizons=horizons,
                    objective_weights=objective_weights,
                    scenario_weights=scenario_weights,
                    list_weights={k: list_weights.get(k, 0.0) for k in strict_list_types},
                    horizon_weights=horizon_weights,
                )
            )
        if research_pool_list_types:
            research_pool_window_evals.append(
                evaluate_window(
                    summary=summary,
                    events=events,
                    list_types=research_pool_list_types,
                    horizons=horizons,
                    objective_weights=objective_weights,
                    scenario_weights=scenario_weights,
                    list_weights={"research_pool": 1.0},
                    horizon_weights=horizon_weights,
                )
            )
        window_failure_reasons.append(classify_window_failure(window_eval, events))
        if bool(args.prune_backtest_artifacts and not args.no_prune_backtest_artifacts):
            maybe_prune_backtest_artifacts(bt_result)

        window_scores.append(float(window_eval["score"]))
        window_valid_counts.append(int(window_eval["total_valid_events"]))
        coverage_values.append(float(window_eval["coverage_ratio"]))
        win_values.append(float(window_eval["avg_win_rate"]))
        return_values.append(float(window_eval["avg_return"]))
        excess_values.append(float(window_eval["avg_excess_vs_qqq"]))
        std_values.append(float(window_eval["avg_std_return"]))
        drawdowns.append(float(window_eval["max_drawdown"]))
        log(
            f"{candidate.cid} | window={window.label} | score={window_eval['score']:.4f} "
            f"valid={window_eval['total_valid_events']} dd={window_eval['max_drawdown']:.3f}"
        )

    finite_window_scores = [x for x in window_scores if np.isfinite(x)]
    objective = float(np.mean(finite_window_scores)) if finite_window_scores else float("-inf")
    finite_research_scores = [
        float(e.get("score", float("nan")))
        for e in research_pool_window_evals
        if np.isfinite(float(e.get("score", float("nan"))))
    ]
    if finite_research_scores:
        research_objective = float(np.mean(finite_research_scores))
        if np.isfinite(objective):
            objective = (0.65 * research_objective) + (0.35 * objective)
        else:
            objective = research_objective
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
    primary_eval = research_pool_eval if research_pool_list_types else {
        "total_valid_events": total_valid,
        "min_window_valid_events": min_window_valid,
        "coverage_ratio": coverage_ratio,
        "worst_max_drawdown": worst_dd,
        "empty_window_ratio": empty_window_ratio,
        "avg_return": avg_ret,
        "avg_excess_vs_qqq": avg_ex,
        "avg_win_rate": avg_win,
    }
    primary_window_scores = (
        [
            float(e.get("score", float("nan")))
            for e in research_pool_window_evals
            if np.isfinite(float(e.get("score", float("nan"))))
        ]
        if research_pool_list_types
        else finite_window_scores
    )
    primary_window_excess = (
        [
            float(e.get("avg_excess_vs_qqq", float("nan")))
            for e in research_pool_window_evals
            if np.isfinite(float(e.get("avg_excess_vs_qqq", float("nan"))))
        ]
        if research_pool_list_types
        else finite_window_excess
    )
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
    objective_score = objective - penalty

    constraints_passed = len(failure_reasons) == 0 and np.isfinite(objective_score)
    failure_reason = ";".join(failure_reasons)

    rank_coverage = (
        float(research_pool_eval["coverage_ratio"]) if research_pool_list_types else float(coverage_ratio)
    )
    rank_avg_ret = (
        float(research_pool_eval["avg_return"]) if research_pool_list_types else float(avg_ret)
    )
    rank_avg_ex = (
        float(research_pool_eval["avg_excess_vs_qqq"]) if research_pool_list_types else float(avg_ex)
    )
    rank_avg_win = (
        float(research_pool_eval["avg_win_rate"]) if research_pool_list_types else float(avg_win)
    )
    risk_on_rank_score = (
        objective_score
        + (0.35 * rank_coverage)
        + (0.45 * (rank_avg_ret if np.isfinite(rank_avg_ret) else 0.0))
        + (0.20 * (rank_avg_ex if np.isfinite(rank_avg_ex) else 0.0))
    )
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
        constraints_passed=bool(constraints_passed),
        failure_reason=failure_reason,
        deltas_json=json.dumps(candidate.deltas, ensure_ascii=False, sort_keys=True),
    )


def pick_profile_candidates(scores_df: pd.DataFrame) -> dict[str, str]:
    valid = scores_df[scores_df["constraints_passed"] == True].copy()
    if valid.empty:
        valid = scores_df.copy()

    picks: dict[str, str] = {}
    order = [
        ("balanced", "balanced_rank_score"),
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
) -> None:
    lines: list[str] = []
    lines.append("# Parameter Tuning Report")
    lines.append("")
    lines.append(f"- generated_utc: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- tuning_run_id: `{stamp}`")
    lines.append(f"- base_config: `{args.base_config}`")
    lines.append(f"- param_space: `{args.param_space}`")
    lines.append(f"- windows: `{', '.join(f'{w.label}:{w.start_date}->{w.end_date}' for w in windows)}`")
    lines.append(f"- candidate_count: {len(scores_df)}")
    lines.append(f"- constraints_passed: {int((scores_df['constraints_passed'] == True).sum())}")
    lines.append(
        "- guardrails: "
        f"min_avg_return={args.min_avg_return}, "
        f"min_avg_excess_vs_qqq={args.min_avg_excess_vs_qqq}, "
        f"min_avg_win_rate={args.min_avg_win_rate}, "
        f"min_positive_window_score_ratio={args.min_positive_window_score_ratio}, "
        f"min_positive_excess_window_ratio={args.min_positive_excess_window_ratio}, "
        f"max_empty_window_ratio={args.max_empty_window_ratio}"
    )
    lines.append("")
    lines.append("## Profile Picks")
    lines.append("")
    for name in ("balanced", "risk_on", "risk_off"):
        cid = picks.get(name)
        if not cid:
            lines.append(f"- {name}: none")
            continue
        row = scores_df[scores_df["cid"] == cid].iloc[0]
        lines.append(
            f"- {name}: `{cid}` | objective={row['objective_score']:.4f} "
            f"| coverage={row['coverage_ratio']:.3f} | dd={row['worst_max_drawdown']:.3f} "
            f"| strict_valid={int(row.get('strict_total_valid_events', 0) or 0)} "
            f"| research_valid={int(row.get('research_pool_total_valid_events', 0) or 0)} "
            f"| pos_excess_windows={row['positive_excess_window_ratio']:.3f} "
            f"| empty_windows={row['empty_window_ratio']:.3f}"
        )
    lines.append("")
    lines.append("## Top 10 Candidates (Balanced Rank)")
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
    stamp = args.output_prefix or datetime.now(timezone.utc).strftime("tuning_%Y%m%dT%H%M%SZ")

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

    objective_weights = dict(DEFAULT_OBJECTIVE_WEIGHTS)
    scenario_weights = dict(DEFAULT_SCENARIO_WEIGHTS)
    list_weights = dict(DEFAULT_LIST_WEIGHTS)
    horizon_weights = dict(DEFAULT_HORIZON_WEIGHTS)

    rows: list[dict[str, Any]] = []
    candidate_map = {c.cid: c for c in candidates}
    for idx, candidate in enumerate(candidates, start=1):
        log(f"[{idx}/{len(candidates)}] evaluating {candidate.cid}")
        score = run_candidate(
            candidate=candidate,
            windows=windows,
            args=args,
            output_stem=stamp,
            horizons=horizons,
            list_types=list_types,
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

    picks = pick_profile_candidates(scores_df)
    report_path = outputs_dir / f"{stamp}_report.md"
    write_tuning_report(
        path=report_path,
        stamp=stamp,
        args=args,
        windows=windows,
        scores_df=scores_df,
        picks=picks,
    )

    if bool(args.promote and not args.no_promote):
        mapping = {
            "balanced": Path(args.balanced_config_path),
            "risk_on": Path(args.risk_on_config_path),
            "risk_off": Path(args.risk_off_config_path),
        }
        for profile, target_path in mapping.items():
            cid = picks.get(profile)
            if not cid:
                continue
            picked = scores_df[scores_df["cid"] == cid]
            if picked.empty or not bool(picked.iloc[0]["constraints_passed"]):
                log(f"skipped promotion for {profile}: {cid} did not pass constraints")
                continue
            write_json(target_path, candidate_map[cid].config)
            log(f"promoted {profile}: {cid} -> {target_path}")

    summary_json = outputs_dir / f"{stamp}_summary.json"
    payload = {
        "tuning_run_id": stamp,
        "base_config": args.base_config,
        "param_space": args.param_space,
        "candidates": len(candidates),
        "picks": picks,
        "results_csv": str(results_csv),
        "report_path": str(report_path),
    }
    write_json(summary_json, payload)
    log(f"results: {results_csv}")
    log(f"report: {report_path}")
    log(f"summary: {summary_json}")


if __name__ == "__main__":
    main()
