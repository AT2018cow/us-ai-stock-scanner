"""Offline score_weights sweep on the extracted survivor dataset.

Works on the CSV produced by scripts/extract_weight_dataset.py. Because hard
gates are weight-independent, every weight candidate only changes the ranking
WITHIN survivors. robust_normalize_score is also weight-independent (pure
cross-sectional quantile normalization), so we precompute the normalized
component matrix once per (signal_date, list_type, channel) group and each
candidate is a single matrix-vector product.

Candidate generation: log-uniform multipliers around each channel's CURRENT
weight vector (shared multiplier per axis across channels, preserving each
channel's relative structure), plus an absolute soft_pass_rate weight. The
current configuration is always candidate #0 (baseline).

Objective mirrors scripts/tune_parameters.py evaluate_window (base scenario):
    component = 1.0*avg_return + 0.8*avg_excess_vs_qqq
               + 0.5*(win_rate - 0.5) - 0.35*std_return
    score = sum over (list_type, horizon) of list_w * horizon_w * component
with horizon weights {20: 0.2, 60: 0.5, 120: 0.3} and list weights
{low_value: 0.35, momentum: 0.25} normalized. Candidates are ranked on the
TRAIN split (<= --split-date) and the top-K are reported with VALIDATION
split, regime (up/down) and per-year breakdowns to fight overfitting.

Usage:
    python scripts/sweep_score_weights.py \
        --dataset outputs/weight_dataset_risk_off.csv \
        --scan-config configs/config.risk_off.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.backtest import build_steps_and_weights
from ai_value_scanner.scanner import load_config

DEFAULT_HORIZON_WEIGHTS: dict[int, float] = {20: 0.2, 60: 0.5, 120: 0.3}
DEFAULT_LIST_WEIGHTS: dict[str, float] = {"low_value": 0.35, "momentum": 0.25}
DEFAULT_OBJECTIVE_WEIGHTS: dict[str, float] = {
    "avg_return": 1.0,
    "avg_excess_vs_qqq": 0.8,
    "win_rate_centered": 0.5,
    "std_return_penalty": 0.35,
}


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[sweep {stamp}] {msg}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sweep score_weights offline on survivor dataset.")
    p.add_argument("--dataset", required=True, help="CSV from scripts/extract_weight_dataset.py")
    p.add_argument("--scan-config", required=True)
    p.add_argument("--n-candidates", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--split-date", default="2026-01-01", help="Train <= split < Validate (YYYY-MM-DD)")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--include-channels", default="core_ai,ai_enabler,ai_peripheral")
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument("--list-types", default="low_value,momentum")
    p.add_argument("--p-zero", type=float, default=0.15, help="Probability of zeroing an axis multiplier")
    p.add_argument("--mult-range", type=float, default=3.0, help="Log-uniform multiplier range [1/x, x]")
    p.add_argument("--soft-rate-min", type=float, default=0.05)
    p.add_argument("--soft-rate-max", type=float, default=0.50)
    p.add_argument("--output-prefix", default=None)
    return p


def component_objective(avg_return: float, avg_excess: float, win_rate: float, std_return: float) -> float:
    ow = DEFAULT_OBJECTIVE_WEIGHTS
    return (
        ow["avg_return"] * avg_return
        + ow["avg_excess_vs_qqq"] * avg_excess
        + ow["win_rate_centered"] * (win_rate - 0.5)
        - ow["std_return_penalty"] * std_return
    )


def load_base_weights(scan_config: Any, channels: list[str], list_types: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    """base_weights[list_type][channel] = effective weight dict (soft_pass_rate resolved)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    profiles = scan_config.channel_profiles or {}
    for lt in list_types:
        out[lt] = {}
        for ch in channels:
            profile = profiles.get(ch, {})
            _steps, weights = build_steps_and_weights(scan_config, ch, profile, lt)
            eff = dict(weights)
            eff["soft_pass_rate"] = float(eff.get("soft_pass_rate", 0.30))
            out[lt][ch] = eff
    return out


def precompute_groups(
    dataset: pd.DataFrame,
    base_weights: dict[str, dict[str, dict[str, float]]],
    horizons: list[int],
    pe_cash_backing_haircut: float = 1.0,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Per (signal_date, list_type, channel): normalized axis matrix + penalties + fwd returns.

    Uses score_and_rank once (with base weights) to harvest the *_norm columns,
    which are weight-independent. Candidate scoring is then pure linear algebra.
    """
    from ai_value_scanner.scanner import score_and_rank

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (signal_date, list_type, channel), part in dataset.groupby(
        ["signal_date", "list_type", "channel"], sort=True
    ):
        base = base_weights.get(str(list_type), {}).get(str(channel), {})
        if not base:
            continue
        ranked = score_and_rank(
            part,
            base,
            winsor_lower_q,
            winsor_upper_q,
            penalty_over,
            penalty_det,
            pe_cash_backing_haircut,
        )
        axes = [k for k in base.keys() if k != "soft_pass_rate"]
        norm_cols = [f"{a}_norm" for a in axes]
        missing = [c for c in norm_cols if c not in ranked.columns]
        for c in missing:
            ranked[c] = 0.0
        mat = ranked[norm_cols].to_numpy(dtype="float64")
        soft_rate = pd.to_numeric(ranked.get("soft_pass_rate"), errors="coerce").fillna(0.0).to_numpy(dtype="float64")
        ovp = penalty_over * pd.to_numeric(ranked.get("overvaluation_penalty"), errors="coerce").fillna(0.0).to_numpy(dtype="float64")
        det = penalty_det * pd.to_numeric(ranked.get("deterioration_penalty"), errors="coerce").fillna(0.0).to_numpy(dtype="float64")
        fwd = ranked[[f"fwd_ret_{h}" for h in horizons]].to_numpy(dtype="float64")
        symbols = ranked["symbol"].astype(str).tolist()
        groups[(str(signal_date), str(list_type), str(channel))] = {
            "axes": axes,
            "norm": mat,
            "soft_rate": soft_rate,
            "ovp": ovp,
            "det": det,
            "fwd": fwd,
            "symbols": symbols,
        }
    return groups


def score_candidate(
    groups: dict[tuple[str, str, str], dict[str, Any]],
    mult_by_axis: dict[str, dict[str, float]],
    soft_weight_by_list: dict[str, float] | dict[tuple[str, str], float],
    horizons: list[int],
    top_n: int,
) -> pd.DataFrame:
    """Returns DataFrame of portfolio events per (signal_date, list_type, horizon).

    Mirrors production rank_and_pick_symbols_with_diagnostics EXACTLY:
    - top_n per channel, channels iterated in group insertion order
    - cross-channel DEDUP keeping first occurrence (normalize_symbol_list)
    - portfolio = equal-weighted mean over UNIQUE picked symbols

    soft_weight_by_list may be per-list ({list: w}) or per-channel
    ({(list, channel): w}); the latter reproduces production exactly when
    channels carry different soft_pass_rate weights.

    Guard: the fwd matrix width in each group MUST match len(horizons).
    A mismatch means the caller passed different horizons to
    precompute_groups() than to score_candidate() — a silent column
    misalignment bug class observed on 2026-09-26 (20d returns read as
    120d). Fail loudly instead of returning wrong numbers.
    """
    if groups:
        sample = next(iter(groups.values()))
        if sample["fwd"].shape[1] != len(horizons):
            raise ValueError(
                f"horizon mismatch: groups were precomputed with {sample['fwd'].shape[1]} "
                f"horizons but score_candidate received {len(horizons)}: {horizons}. "
                "precompute_groups() and score_candidate() must use the SAME horizons list."
            )
    # Stage 1: per (date, list, channel) ranked picks (ordered symbol lists)
    picks: dict[tuple[str, str], list[str]] = {}
    fwd_by_key: dict[tuple[str, str, str], np.ndarray] = {}
    syms_by_key: dict[tuple[str, str, str], list[str]] = {}

    def _soft_w(list_type: str, channel: str) -> float:
        if isinstance(soft_weight_by_list, dict) and soft_weight_by_list:
            key = next(iter(soft_weight_by_list))
            if isinstance(key, tuple):
                return float(soft_weight_by_list.get((list_type, channel), 0.30))  # type: ignore[union-attr]
        return float(soft_weight_by_list[list_type])  # type: ignore[index]

    for (signal_date, list_type, channel), g in groups.items():
        mult = mult_by_axis[list_type]
        weights = np.array([mult.get(a, 1.0) for a in g["axes"]], dtype="float64")
        base_soft = _soft_w(list_type, channel)
        scores = g["norm"] @ weights + base_soft * g["soft_rate"] - g["ovp"] - g["det"]
        order = np.argsort(-scores, kind="stable")
        picked = order[:top_n]
        key = (signal_date, list_type)
        picks.setdefault(key, [])
        for j in picked:
            picks[key].append(g["symbols"][int(j)])
        fwd_by_key[(signal_date, list_type, channel)] = g["fwd"][picked]
        syms_by_key[(signal_date, list_type, channel)] = [g["symbols"][int(j)] for j in picked]

    # Stage 2: dedup + equal-weighted portfolio over unique symbols
    events: list[dict[str, Any]] = []
    for (signal_date, list_type), ordered in picks.items():
        seen: set[str] = set()
        uniq: list[str] = []
        for s in ordered:
            u = str(s).strip().upper()
            if not u or u in seen:
                continue
            seen.add(u)
            uniq.append(u)
        # map unique symbol -> first occurrence fwd vector
        fwd_lookup: dict[str, np.ndarray] = {}
        for ch in [k[2] for k in fwd_by_key if k[0] == signal_date and k[1] == list_type]:
            fw = fwd_by_key[(signal_date, list_type, ch)]
            sy = syms_by_key[(signal_date, list_type, ch)]
            for s, f in zip(sy, fw):
                u = str(s).strip().upper()
                if u not in fwd_lookup:
                    fwd_lookup[u] = np.asarray(f, dtype="float64")
        for h_idx, h in enumerate(horizons):
            rets = np.array([fwd_lookup[u][h_idx] for u in uniq], dtype="float64")
            valid = rets[np.isfinite(rets)]
            events.append(
                {
                    "signal_date": signal_date,
                    "list_type": list_type,
                    "horizon_days": h,
                    "n_picked": int(len(uniq)),
                    "n_valid": int(len(valid)),
                    "mean_ret": float(valid.mean()) if len(valid) else np.nan,
                }
            )
    return pd.DataFrame(events)


def summarize(events: pd.DataFrame, dataset: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Aggregate per (list_type, horizon): avg return / win rate / std / excess vs QQQ."""
    qqq_cols = {h: f"qqq_return_{h}" for h in horizons}
    qqq_map = (
        dataset[["signal_date"] + list(qqq_cols.values())]
        .drop_duplicates(subset=["signal_date"])
        .set_index("signal_date")
    )
    regime_map = (
        dataset[["signal_date", "regime", "benchmark_trailing_60d"]]
        .drop_duplicates(subset=["signal_date"])
        .set_index("signal_date")
    )
    rows: list[dict[str, Any]] = []
    for (lt, h), part in events.groupby(["list_type", "horizon_days"]):
        by_date = part.groupby("signal_date")["mean_ret"].mean()
        by_date = by_date.dropna()
        if by_date.empty:
            continue
        qqq = qqq_map[qqq_cols[int(h)]].reindex(by_date.index)
        excess = by_date - qqq
        rows.append(
            {
                "list_type": lt,
                "horizon_days": int(h),
                "n_dates": int(len(by_date)),
                "avg_return": float(by_date.mean()),
                "win_rate": float((by_date > 0).mean()),
                "std_return": float(by_date.std(ddof=1)) if len(by_date) > 1 else 0.0,
                "avg_excess_vs_qqq": float(excess.mean()),
            }
        )
    return pd.DataFrame(rows)


def objective_from_summary(summary: pd.DataFrame, list_types: list[str], horizons: list[int]) -> float:
    lw = {k: v for k, v in DEFAULT_LIST_WEIGHTS.items() if k in list_types}
    lw_total = sum(lw.values()) or 1.0
    hw = {k: v for k, v in DEFAULT_HORIZON_WEIGHTS.items() if k in horizons}
    hw_total = sum(hw.values()) or 1.0
    score = 0.0
    for row in summary.itertuples(index=False):
        w = (lw.get(str(row.list_type), 0.0) / lw_total) * (hw.get(int(row.horizon_days), 0.0) / hw_total)
        if w <= 0:
            continue
        score += w * component_objective(
            float(row.avg_return),
            float(row.avg_excess_vs_qqq),
            float(row.win_rate),
            float(row.std_return),
        )
    return score


def breakdown_by_year(events: pd.DataFrame, dataset: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    e = events.copy()
    e["year"] = e["signal_date"].str[:4]
    return summarize_with_keys(e, dataset, horizons, ["list_type", "horizon_days", "year"])


def breakdown_by_regime(events: pd.DataFrame, dataset: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    e = events.merge(
        dataset[["signal_date", "regime"]].drop_duplicates(subset=["signal_date"]),
        on="signal_date",
        how="left",
    )
    return summarize_with_keys(e, dataset, horizons, ["list_type", "horizon_days", "regime"])


def summarize_with_keys(
    events: pd.DataFrame, dataset: pd.DataFrame, horizons: list[int], keys: list[str]
) -> pd.DataFrame:
    qqq_cols = {h: f"qqq_return_{h}" for h in horizons}
    qqq_map = (
        dataset[["signal_date"] + list(qqq_cols.values())]
        .drop_duplicates(subset=["signal_date"])
        .set_index("signal_date")
    )
    rows: list[dict[str, Any]] = []
    for key_vals, part in events.groupby(keys, dropna=False):
        if not isinstance(key_vals, tuple):
            key_vals = (key_vals,)
        by_date = part.groupby("signal_date")["mean_ret"].mean().dropna()
        if by_date.empty:
            continue
        h = int(part["horizon_days"].iloc[0])
        qqq = qqq_map[qqq_cols[h]].reindex(by_date.index)
        excess = by_date - qqq
        row = dict(zip(keys, key_vals))
        row.update(
            {
                "n_dates": int(len(by_date)),
                "avg_return": float(by_date.mean()),
                "win_rate": float((by_date > 0).mean()),
                "avg_excess_vs_qqq": float(excess.mean()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    global winsor_lower_q, winsor_upper_q, penalty_over, penalty_det
    global pe_cash_backing_haircut

    args = build_parser().parse_args()
    started = time.monotonic()

    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    list_types = [x.strip() for x in str(args.list_types).split(",") if x.strip()]
    channels = [x.strip() for x in str(args.include_channels).split(",") if x.strip()]
    split_date = str(args.split_date)

    dataset = pd.read_csv(args.dataset)
    dataset = dataset[dataset["channel"].isin(channels) & dataset["list_type"].isin(list_types)].copy()
    if dataset.empty:
        raise ValueError("Dataset empty after channel/list filtering.")
    log(f"dataset: {len(dataset)} rows | {dataset['signal_date'].nunique()} dates | channels={channels}")

    scan_config = load_config(args.scan_config)
    winsor_lower_q = scan_config.score_winsor_lower_q
    winsor_upper_q = scan_config.score_winsor_upper_q
    penalty_over = scan_config.score_penalty_overvaluation
    penalty_det = scan_config.score_penalty_deterioration
    pe_cash_backing_haircut = scan_config.pe_cash_backing_haircut

    base_weights = load_base_weights(scan_config, channels, list_types)
    for lt in list_types:
        for ch in channels:
            log(f"base weights {lt}/{ch}: " + json.dumps({k: round(v, 3) for k, v in sorted(base_weights[lt][ch].items(), key=lambda x: -x[1])}))

    log("precomputing normalized matrices per (date, list, channel) ...")
    groups = precompute_groups(dataset, base_weights, horizons, pe_cash_backing_haircut)
    log(f"groups: {len(groups)}")

    rng = np.random.default_rng(args.seed)

    def axis_universe(lt: str) -> list[str]:
        axes: set[str] = set()
        for ch in channels:
            axes.update(a for a in base_weights[lt][ch] if a != "soft_pass_rate")
        return sorted(axes)

    axes_by_list = {lt: axis_universe(lt) for lt in list_types}

    def baseline_mult(lt: str) -> dict[str, float]:
        return {a: 1.0 for a in axes_by_list[lt]}

    def random_mult(lt: str) -> dict[str, float]:
        m: dict[str, float] = {}
        for a in axes_by_list[lt]:
            if rng.random() < args.p_zero:
                m[a] = 0.0
            else:
                m[a] = float(np.exp(rng.uniform(-np.log(args.mult_range), np.log(args.mult_range))))
        return m

    train_mask_dates = set(dataset[dataset["signal_date"] < split_date]["signal_date"].unique())
    valid_mask_dates = set(dataset[dataset["signal_date"] >= split_date]["signal_date"].unique())

    def evaluate(mults: dict[str, dict[str, float]], soft_w: dict[str, float]) -> dict[str, Any]:
        events = score_candidate(groups, mults, soft_w, horizons, args.top_n)
        full = summarize(events, dataset, horizons)
        score_full = objective_from_summary(full, list_types, horizons)
        ev_tr = events[events["signal_date"].isin(train_mask_dates)]
        ev_va = events[events["signal_date"].isin(valid_mask_dates)]
        s_tr = objective_from_summary(summarize(ev_tr, dataset, horizons), list_types, horizons)
        s_va = objective_from_summary(summarize(ev_va, dataset, horizons), list_types, horizons)
        return {
            "score": score_full,
            "score_train": s_tr,
            "score_valid": s_va,
            "per_year": breakdown_by_year(events, dataset, horizons),
            "per_regime": breakdown_by_regime(events, dataset, horizons),
        }

    def evaluate_light(mults: dict[str, dict[str, float]], soft_w: dict[str, float]) -> tuple[float, float, float]:
        events = score_candidate(groups, mults, soft_w, horizons, args.top_n)
        score_full = objective_from_summary(summarize(events, dataset, horizons), list_types, horizons)
        ev_tr = events[events["signal_date"].isin(train_mask_dates)]
        ev_va = events[events["signal_date"].isin(valid_mask_dates)]
        s_tr = objective_from_summary(summarize(ev_tr, dataset, horizons), list_types, horizons)
        s_va = objective_from_summary(summarize(ev_va, dataset, horizons), list_types, horizons)
        return score_full, s_tr, s_va

    # Candidate 0 = current production config
    mult0 = {lt: baseline_mult(lt) for lt in list_types}
    soft0 = {lt: float(base_weights[lt][channels[0]].get("soft_pass_rate", 0.30)) for lt in list_types}
    base_eval = evaluate(mult0, soft0)
    log(f"baseline (current config): score={base_eval['score']:.4f} train={base_eval['score_train']:.4f} valid={base_eval['score_valid']:.4f}")

    results: list[dict[str, Any]] = []
    t0 = time.monotonic()
    for cid in range(args.n_candidates):
        mults = {lt: (baseline_mult(lt) if cid == 0 else random_mult(lt)) for lt in list_types}
        soft = {}
        for lt in list_types:
            if cid == 0:
                soft[lt] = float(base_weights[lt][channels[0]].get("soft_pass_rate", 0.30))
            else:
                soft[lt] = float(rng.uniform(args.soft_rate_min, args.soft_rate_max))
        s_full, s_tr, s_va = evaluate_light(mults, soft)
        results.append(
            {
                "cid": cid,
                "is_baseline": cid == 0,
                "score_full": s_full,
                "score_train": s_tr,
                "score_valid": s_va,
                "mults": mults,
                "soft_weight": soft,
            }
        )
        if (cid + 1) % 100 == 0:
            rate = (cid + 1) / (time.monotonic() - t0)
            log(f"candidates {cid + 1}/{args.n_candidates} ({rate:.1f}/s)")

    df = pd.DataFrame(
        [
            {
                "cid": r["cid"],
                "is_baseline": r["is_baseline"],
                "score_full": r["score_full"],
                "score_train": r["score_train"],
                "score_valid": r["score_valid"],
                "soft_weight": json.dumps(r["soft_weight"]),
                "mults": json.dumps(r["mults"]),
            }
            for r in results
        ]
    )
    df = df.sort_values("score_train", ascending=False).reset_index(drop=True)

    style = "risk_on" if "risk_on" in str(args.scan_config) else "risk_off"
    prefix = args.output_prefix or f"outputs/weightsweep_{style}"
    Path("outputs").mkdir(parents=True, exist_ok=True)
    df.to_csv(f"{prefix}_results.csv", index=False)

    lines: list[str] = [f"# score_weights sweep ({style})", ""]
    lines.append(f"- dataset: {args.dataset}")
    lines.append(f"- candidates: {args.n_candidates} (+baseline) | seed={args.seed}")
    lines.append(f"- split: train <= {split_date} < validate")
    lines.append(f"- channels: {channels} | top_n per channel: {args.top_n}")
    lines.append(
        f"- baseline score: full={base_eval['score']:.4f} train={base_eval['score_train']:.4f} valid={base_eval['score_valid']:.4f}"
    )
    lines.append("")
    lines.append("## Top 20 by TRAIN score")
    lines.append("")
    lines.append("| rank | cid | train | valid | full | soft_w (lv/mo) |")
    lines.append("|---|---|---|---|---|---|")
    for rank, row in enumerate(df.head(20).itertuples(index=False), start=1):
        soft = json.loads(row.soft_weight)
        soft_str = "/".join(f"{soft[k]:.2f}" for k in sorted(soft))
        lines.append(
            f"| {rank} | {row.cid} | {row.score_train:.4f} | {row.score_valid:.4f} | {row.score_full:.4f} | {soft_str} |"
        )
    lines.append("")

    best = next(r for r in results if int(r["cid"]) == int(df.iloc[0]["cid"]))
    best_eval = evaluate(best["mults"], best["soft_weight"])
    lines.append("## Best candidate details")
    lines.append("")
    lines.append("### Multipliers per list type (applied to each channel's current weights)")
    for lt in list_types:
        lines.append(f"- {lt}: " + json.dumps({k: round(v, 3) for k, v in sorted(best["mults"][lt].items())}))
    lines.append(f"- soft_pass_rate weights: {json.dumps(best['soft_weight'])}")
    lines.append("")
    lines.append("### Resulting effective weights per channel")
    for lt in list_types:
        for ch in channels:
            eff = {
                a: base_weights[lt][ch].get(a, 0.0) * best["mults"][lt].get(a, 1.0)
                for a in base_weights[lt][ch]
                if a != "soft_pass_rate"
            }
            eff["soft_pass_rate"] = best["soft_weight"][lt]
            eff = {k: round(v, 4) for k, v in sorted(eff.items(), key=lambda x: -x[1])}
            lines.append(f"- {lt}/{ch}: {json.dumps(eff)}")
    lines.append("")
    lines.append("### Per-year breakdown (best candidate)")
    lines.append(best_eval["per_year"].to_markdown(index=False))
    lines.append("")
    lines.append("### Per-regime breakdown (best candidate)")
    lines.append(best_eval["per_regime"].to_markdown(index=False))
    lines.append("")
    lines.append("### Baseline per-year breakdown (current config)")
    lines.append(base_eval["per_year"].to_markdown(index=False))
    lines.append("")
    lines.append("### Baseline per-regime breakdown (current config)")
    lines.append(base_eval["per_regime"].to_markdown(index=False))

    report_path = Path(f"{prefix}_report.md")
    report_path.write_text("\n".join(lines))
    log(f"done in {(time.monotonic() - started) / 60:.1f}m | results: {prefix}_results.csv | report: {report_path}")


if __name__ == "__main__":
    main()
