"""Offline rank-IC and score-decile analysis on survivor datasets.

This script answers a narrow precondition for any future weight tuning:

    Does the CURRENT production composite score rank hard-gate survivors in a
    way that is monotone with future returns?

It uses the exact production score weights for each channel/list and the
style-specific soft-pass counts already stored by extract_weight_dataset.py.
It does not call Alpaca, SEC, Modal, or historical replay.

Outputs are compact CSV/Markdown evidence:
- per-date/channel cross-sectional Spearman IC
- IC summaries with overlap-aware Newey-West t-statistics
- score-decile forward-return/excess summaries
- monotonicity diagnostics (top-bottom spread, adjacent-step ratio, decile IC)

QQQ excess is a constant shift within a signal-date cross-section, so rank IC
against forward return and forward excess are identical. Decile tables include
explicit excess vs QQQ because level spreads do change.
"""

from __future__ import annotations

import argparse
import math
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
    apply_filters_with_diagnostics,
    partition_filter_steps,
)
from ai_value_scanner.strategy.scoring import score_and_rank


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[ic {stamp}] {message}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Production-score IC and decile monotonicity on survivor datasets."
    )
    p.add_argument("--dataset", required=True)
    p.add_argument("--scan-config", required=True)
    p.add_argument("--output-prefix", default=None)
    p.add_argument("--list-types", default="low_value,momentum")
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument(
        "--include-channels",
        default="core_ai,ai_enabler,ai_peripheral",
    )
    p.add_argument(
        "--min-cross-section",
        type=int,
        default=20,
        help="Minimum finite names in a date/list/channel cross-section.",
    )
    p.add_argument("--deciles", type=int, default=10)
    return p


def parse_tokens(raw: str) -> list[str]:
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def spearman(
    a: np.ndarray,
    b: np.ndarray,
    *,
    min_n: int = 3,
) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if int(ok.sum()) < int(min_n):
        return np.nan
    ra = pd.Series(a[ok]).rank(method="average").to_numpy(dtype=float)
    rb = pd.Series(b[ok]).rank(method="average").to_numpy(dtype=float)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = float(np.sqrt((ra**2).sum() * (rb**2).sum()))
    if denom <= 0.0:
        return np.nan
    return float((ra * rb).sum() / denom)


def tstat(values: list[float]) -> float:
    x = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if len(x) < 3:
        return np.nan
    sd = float(x.std(ddof=1))
    if sd <= 0.0:
        return np.nan
    return float(x.mean() / sd * np.sqrt(len(x)))


def overlap_lags(dates: list[str], horizon_days: int) -> int:
    if len(dates) < 2:
        return 1
    ts = sorted(pd.to_datetime(pd.Series(dates), errors="coerce").dropna())
    if len(ts) < 2:
        return 1
    steps = [
        int((b - a).days)
        for a, b in zip(ts, ts[1:])
        if int((b - a).days) > 0
    ]
    if not steps:
        return 1
    median_step = float(np.median(steps))
    return max(1, int(round(float(horizon_days) / median_step)))


def tstat_nw(values: list[float], lags: int) -> float:
    """Mean divided by Newey-West standard error, Bartlett kernel."""
    x = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    n = len(x)
    if n < 3:
        return np.nan
    xc = x - x.mean()
    gamma0 = float((xc**2).sum() / n)
    variance = gamma0
    use_lags = min(max(1, int(lags)), n - 1)
    for lag in range(1, use_lags + 1):
        weight = 1.0 - lag / (use_lags + 1)
        variance += (
            2.0
            * weight
            * float((xc[lag:] * xc[:-lag]).sum() / n)
        )
    if not np.isfinite(variance) or variance <= 0.0:
        return np.nan
    return float(x.mean() / np.sqrt(variance / n))


def score_survivors(
    dataset: pd.DataFrame,
    config: ScanConfig,
    *,
    list_types: list[str],
    channels: list[str],
    horizons: list[int],
) -> pd.DataFrame:
    required = {
        "signal_date",
        "list_type",
        "channel",
        "symbol",
        "soft_pass_count",
        "soft_total",
        "regime",
    }
    required.update(f"fwd_ret_{h}" for h in horizons)
    required.update(f"qqq_return_{h}" for h in horizons)
    missing = sorted(required - set(dataset.columns))
    if missing:
        raise ValueError(
            "survivor dataset missing required columns: "
            + ",".join(missing)
        )

    work = dataset[
        dataset["list_type"].astype(str).isin(list_types)
        & dataset["channel"].astype(str).isin(channels)
    ].copy()
    profiles = config.channel_profiles or {}
    rows: list[pd.DataFrame] = []

    for (signal_date, list_type, channel), group in work.groupby(
        ["signal_date", "list_type", "channel"],
        sort=False,
    ):
        channel = str(channel)
        list_type = str(list_type)
        if channel not in profiles:
            continue
        steps, weights = build_steps_and_weights(
            config,
            channel,
            profiles[channel],
            list_type,
        )
        hard_steps, soft_steps = partition_filter_steps(
            steps,
            channel,
            config.strategy_style,
        )
        filtered, _ = apply_filters_with_diagnostics(group, hard_steps)
        if filtered.empty:
            continue
        filtered = filtered.copy()
        if soft_steps:
            soft_matrix = pd.DataFrame(
                {
                    name: pd.Series(
                        mask_fn(filtered),
                        index=filtered.index,
                    ).fillna(False).astype(bool)
                    for name, mask_fn in soft_steps
                },
                index=filtered.index,
            )
            filtered["soft_pass_count"] = soft_matrix.sum(axis=1)
            filtered["soft_total"] = len(soft_steps)
        else:
            filtered["soft_pass_count"] = 0
            filtered["soft_total"] = 1

        ranked = score_and_rank(
            filtered,
            weights,
            config.score_winsor_lower_q,
            config.score_winsor_upper_q,
            config.score_penalty_overvaluation,
            config.score_penalty_deterioration,
            config.pe_cash_backing_haircut,
        ).copy()
        keep = [
            "signal_date",
            "list_type",
            "channel",
            "symbol",
            "regime",
            "composite_score",
        ]
        keep.extend(f"fwd_ret_{h}" for h in horizons)
        keep.extend(f"qqq_return_{h}" for h in horizons)
        rows.append(ranked[keep])

    if not rows:
        return pd.DataFrame()
    scored = pd.concat(rows, ignore_index=True)
    scored["signal_date"] = scored["signal_date"].astype(str)
    scored["year"] = scored["signal_date"].str[:4]
    return scored


def build_ic_by_date(
    scored: pd.DataFrame,
    *,
    horizons: list[int],
    min_cross_section: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (signal_date, list_type, channel), group in scored.groupby(
        ["signal_date", "list_type", "channel"],
        sort=False,
    ):
        x = pd.to_numeric(
            group["composite_score"], errors="coerce"
        ).to_numpy(dtype=float)
        regime = str(group["regime"].iloc[0]) if len(group) else "unknown"
        for horizon in horizons:
            y = pd.to_numeric(
                group[f"fwd_ret_{horizon}"], errors="coerce"
            ).to_numpy(dtype=float)
            ok = np.isfinite(x) & np.isfinite(y)
            if int(ok.sum()) < int(min_cross_section):
                continue
            ic = spearman(x, y, min_n=min_cross_section)
            if not np.isfinite(ic):
                continue
            rows.append(
                {
                    "signal_date": str(signal_date),
                    "year": str(signal_date)[:4],
                    "regime": regime,
                    "list_type": str(list_type),
                    "channel": str(channel),
                    "horizon_days": int(horizon),
                    "n_names": int(ok.sum()),
                    "ic": float(ic),
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # Style-level IC: average channel ICs on the same date so one symbol that
    # appears in multiple channels cannot receive multiple row-level weight.
    all_channel = (
        out.groupby(
            [
                "signal_date",
                "year",
                "regime",
                "list_type",
                "horizon_days",
            ],
            as_index=False,
        )
        .agg(
            n_names=("n_names", "sum"),
            ic=("ic", "mean"),
        )
    )
    all_channel["channel"] = "ALL"
    return pd.concat([out, all_channel[out.columns]], ignore_index=True)


def summarize_ic(ic_by_date: pd.DataFrame) -> pd.DataFrame:
    if ic_by_date.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    base_keys = ["list_type", "channel", "horizon_days"]

    def add_scope(
        frame: pd.DataFrame,
        *,
        scope: str,
        scope_value: str,
    ) -> None:
        for keys, group in frame.groupby(base_keys, sort=False):
            list_type, channel, horizon = keys
            values = pd.to_numeric(group["ic"], errors="coerce")
            vals = [float(x) for x in values if np.isfinite(x)]
            dates = group.loc[np.isfinite(values), "signal_date"].astype(str).tolist()
            if not vals:
                continue
            rows.append(
                {
                    "scope": scope,
                    "scope_value": scope_value,
                    "list_type": str(list_type),
                    "channel": str(channel),
                    "horizon_days": int(horizon),
                    "n_dates": len(vals),
                    "mean_ic": float(np.mean(vals)),
                    "median_ic": float(np.median(vals)),
                    "positive_ic_ratio": float(
                        np.mean([v > 0.0 for v in vals])
                    ),
                    "t_stat": tstat(vals),
                    "t_stat_nw": tstat_nw(
                        vals,
                        overlap_lags(dates, int(horizon)),
                    ),
                }
            )

    add_scope(ic_by_date, scope="all", scope_value="ALL")
    for year, part in ic_by_date.groupby("year", sort=True):
        add_scope(part, scope="year", scope_value=str(year))
    for regime, part in ic_by_date.groupby("regime", sort=True):
        add_scope(part, scope="regime", scope_value=str(regime))
    return pd.DataFrame(rows)


def build_decile_by_date(
    scored: pd.DataFrame,
    *,
    horizons: list[int],
    min_cross_section: int,
    deciles: int,
) -> pd.DataFrame:
    if deciles < 3:
        raise ValueError("--deciles must be >= 3")
    rows: list[dict[str, Any]] = []

    for (signal_date, list_type, channel), group in scored.groupby(
        ["signal_date", "list_type", "channel"],
        sort=False,
    ):
        regime = str(group["regime"].iloc[0]) if len(group) else "unknown"
        score = pd.to_numeric(group["composite_score"], errors="coerce")
        for horizon in horizons:
            fwd = pd.to_numeric(
                group[f"fwd_ret_{horizon}"], errors="coerce"
            )
            qqq = pd.to_numeric(
                group[f"qqq_return_{horizon}"], errors="coerce"
            )
            valid = score.notna() & fwd.notna() & qqq.notna()
            part = group.loc[valid].copy()
            if len(part) < int(min_cross_section):
                continue
            part["_score"] = score.loc[valid].astype(float)
            part["_fwd"] = fwd.loc[valid].astype(float)
            part["_excess"] = (
                fwd.loc[valid].astype(float) - qqq.loc[valid].astype(float)
            )
            percentile = part["_score"].rank(
                method="first",
                pct=True,
            )
            part["_decile"] = (
                np.ceil(percentile * int(deciles))
                .clip(lower=1, upper=int(deciles))
                .astype(int)
            )
            for decile, decile_part in part.groupby("_decile"):
                rows.append(
                    {
                        "signal_date": str(signal_date),
                        "year": str(signal_date)[:4],
                        "regime": regime,
                        "list_type": str(list_type),
                        "channel": str(channel),
                        "horizon_days": int(horizon),
                        "decile": int(decile),
                        "n_names": int(len(decile_part)),
                        "mean_return": float(decile_part["_fwd"].mean()),
                        "mean_excess_vs_qqq": float(
                            decile_part["_excess"].mean()
                        ),
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # Equal-weight channel decile means within each date for style-level view.
    all_channel = (
        out.groupby(
            [
                "signal_date",
                "year",
                "regime",
                "list_type",
                "horizon_days",
                "decile",
            ],
            as_index=False,
        )
        .agg(
            n_names=("n_names", "sum"),
            mean_return=("mean_return", "mean"),
            mean_excess_vs_qqq=("mean_excess_vs_qqq", "mean"),
        )
    )
    all_channel["channel"] = "ALL"
    return pd.concat([out, all_channel[out.columns]], ignore_index=True)


def summarize_deciles(decile_by_date: pd.DataFrame) -> pd.DataFrame:
    if decile_by_date.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    base_keys = ["list_type", "channel", "horizon_days", "decile"]

    def add_scope(
        frame: pd.DataFrame,
        *,
        scope: str,
        scope_value: str,
    ) -> None:
        for keys, group in frame.groupby(base_keys, sort=False):
            list_type, channel, horizon, decile = keys
            ret = pd.to_numeric(group["mean_return"], errors="coerce")
            excess = pd.to_numeric(
                group["mean_excess_vs_qqq"], errors="coerce"
            )
            rows.append(
                {
                    "scope": scope,
                    "scope_value": scope_value,
                    "list_type": str(list_type),
                    "channel": str(channel),
                    "horizon_days": int(horizon),
                    "decile": int(decile),
                    "n_group_dates": int(excess.notna().sum()),
                    "mean_return": float(ret.mean()),
                    "mean_excess_vs_qqq": float(excess.mean()),
                    "positive_excess_ratio": float(
                        excess.gt(0).mean()
                    ),
                }
            )

    add_scope(decile_by_date, scope="all", scope_value="ALL")
    for year, part in decile_by_date.groupby("year", sort=True):
        add_scope(part, scope="year", scope_value=str(year))
    for regime, part in decile_by_date.groupby("regime", sort=True):
        add_scope(part, scope="regime", scope_value=str(regime))
    return pd.DataFrame(rows)


def build_monotonicity(
    decile_summary: pd.DataFrame,
) -> pd.DataFrame:
    if decile_summary.empty:
        return pd.DataFrame()

    keys = [
        "scope",
        "scope_value",
        "list_type",
        "channel",
        "horizon_days",
    ]
    rows: list[dict[str, Any]] = []
    for key_values, group in decile_summary.groupby(keys, sort=False):
        group = group.sort_values("decile")
        dec = pd.to_numeric(group["decile"], errors="coerce").to_numpy(
            dtype=float
        )
        ret = pd.to_numeric(
            group["mean_return"], errors="coerce"
        ).to_numpy(dtype=float)
        excess = pd.to_numeric(
            group["mean_excess_vs_qqq"], errors="coerce"
        ).to_numpy(dtype=float)
        valid = np.isfinite(dec) & np.isfinite(excess)
        if int(valid.sum()) < 3:
            continue
        dec_v = dec[valid]
        ret_v = ret[valid]
        ex_v = excess[valid]
        order = np.argsort(dec_v)
        dec_v = dec_v[order]
        ret_v = ret_v[order]
        ex_v = ex_v[order]
        top_n = min(3, len(ex_v))
        adjacent = np.diff(ex_v)
        rows.append(
            {
                **dict(zip(keys, key_values)),
                "n_deciles": int(len(ex_v)),
                "decile_spearman_return": spearman(
                    dec_v, ret_v, min_n=3
                ),
                "decile_spearman_excess": spearman(
                    dec_v, ex_v, min_n=3
                ),
                "top_minus_bottom_return": float(
                    ret_v[-1] - ret_v[0]
                ),
                "top_minus_bottom_excess": float(
                    ex_v[-1] - ex_v[0]
                ),
                "top3_minus_bottom3_excess": float(
                    np.mean(ex_v[-top_n:]) - np.mean(ex_v[:top_n])
                ),
                "adjacent_up_ratio": (
                    float(np.mean(adjacent > 0.0))
                    if len(adjacent)
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def write_report(
    path: Path,
    *,
    style: str,
    ic_summary: pd.DataFrame,
    monotonicity: pd.DataFrame,
) -> None:
    lines = [
        f"# Production-score ranking diagnostics — {style}",
        "",
        "Hard-gate survivors are scored with the current production weights.",
        "These are descriptive forward-return labels, not account NAV.",
        "",
        "## All-channel headline",
        "",
    ]
    headline_ic = ic_summary[
        (ic_summary["scope"] == "all")
        & (ic_summary["scope_value"] == "ALL")
        & (ic_summary["channel"] == "ALL")
    ].copy()
    headline_mono = monotonicity[
        (monotonicity["scope"] == "all")
        & (monotonicity["scope_value"] == "ALL")
        & (monotonicity["channel"] == "ALL")
    ].copy()

    for row in headline_ic.sort_values(
        ["list_type", "horizon_days"]
    ).itertuples(index=False):
        match = headline_mono[
            (headline_mono["list_type"] == row.list_type)
            & (headline_mono["horizon_days"] == row.horizon_days)
        ]
        mono = match.iloc[0] if not match.empty else None
        spread = (
            float(mono["top_minus_bottom_excess"])
            if mono is not None
            else np.nan
        )
        adjacent = (
            float(mono["adjacent_up_ratio"])
            if mono is not None
            else np.nan
        )
        lines.append(
            f"- {row.list_type} {int(row.horizon_days)}d: "
            f"mean_IC={float(row.mean_ic):+.4f}, "
            f"t_NW={float(row.t_stat_nw):+.2f}, "
            f"top-bottom excess={spread:+.4f}, "
            f"adjacent-up={adjacent:.0%}"
        )

    lines.extend(
        [
            "",
            "## Interpretation gate",
            "",
            "- Continue weight/threshold research only if the score has a positive, reasonably stable rank relationship and the upper deciles outperform the lower deciles across more than one year/regime/channel.",
            "- A single strong year or a non-monotone decile curve is not evidence to tune production weights.",
            "- QQQ excess is shown for level comparisons; within-date rank IC is unchanged by subtracting the same QQQ return from every stock.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = build_parser().parse_args()
    horizons = [int(x) for x in parse_tokens(args.horizons)]
    list_types = parse_tokens(args.list_types)
    requested_channels = parse_tokens(args.include_channels)
    if int(args.min_cross_section) < 3:
        raise ValueError("--min-cross-section must be >= 3")
    if int(args.deciles) < 3:
        raise ValueError("--deciles must be >= 3")

    dataset = pd.read_csv(args.dataset)
    config = load_config(args.scan_config)
    config_channels = list((config.channel_profiles or {}).keys())
    channels = [c for c in config_channels if c in requested_channels]
    if not channels:
        raise ValueError("no requested channels are present in scan config")

    style = str(config.strategy_style or "unknown")
    prefix = Path(
        args.output_prefix
        or f"outputs/ic_analysis_{style}"
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)

    log(
        f"{style}: scoring {len(dataset)} survivor rows with production weights"
    )
    scored = score_survivors(
        dataset,
        config,
        list_types=list_types,
        channels=channels,
        horizons=horizons,
    )
    if scored.empty:
        raise ValueError("no scored survivor rows after filters")

    ic_by_date = build_ic_by_date(
        scored,
        horizons=horizons,
        min_cross_section=int(args.min_cross_section),
    )
    ic_summary = summarize_ic(ic_by_date)
    decile_by_date = build_decile_by_date(
        scored,
        horizons=horizons,
        min_cross_section=int(args.min_cross_section),
        deciles=int(args.deciles),
    )
    decile_summary = summarize_deciles(decile_by_date)
    monotonicity = build_monotonicity(decile_summary)

    ic_by_date_path = Path(f"{prefix}_ic_by_date.csv")
    ic_summary_path = Path(f"{prefix}_ic_summary.csv")
    deciles_path = Path(f"{prefix}_deciles.csv")
    monotonicity_path = Path(f"{prefix}_monotonicity.csv")
    report_path = Path(f"{prefix}_report.md")

    ic_by_date.to_csv(ic_by_date_path, index=False)
    ic_summary.to_csv(ic_summary_path, index=False)
    decile_summary.to_csv(deciles_path, index=False)
    monotonicity.to_csv(monotonicity_path, index=False)
    write_report(
        report_path,
        style=style,
        ic_summary=ic_summary,
        monotonicity=monotonicity,
    )
    log(
        "done: "
        f"{ic_summary_path}, {deciles_path}, "
        f"{monotonicity_path}, {report_path}"
    )


if __name__ == "__main__":
    main()
