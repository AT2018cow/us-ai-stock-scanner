"""Same-state single-gate ablation for risk_off low_value.

This experiment intentionally reuses the immutable PR28 expanded survivor
dataset. The canonical baseline is produced by the same production-parity
selector used by historical replay, while a research arm changes exactly one
structural condition from hard to soft:

    max_range_position_52w

The old PR28 replay-vs-extraction parity mismatch is *not* relaxed. Instead,
this script removes live-data timing from the comparison: both arms consume
the exact same frozen cross-section rows, and a second research reconstruction
of the baseline must match the canonical selector 100% before outcomes are
interpreted.

Retrospective research only. Never promotes production parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_value_scanner.backtest import (  # noqa: E402
    rank_and_pick_symbols_with_diagnostics,
)
from ai_value_scanner.config import ScanConfig, load_config  # noqa: E402
from ai_value_scanner.strategy.selection import (  # noqa: E402
    select_symbols_from_ranked_frames,
)

import low_value_gate_ablation as base  # noqa: E402


EXPECTED_DATASET_SHA256 = (
    "bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6"
)
EXPECTED_EXPANDED_SKIPS = {
    "max_range_position_52w",
    "min_drawdown_from_52w_high",
    "max_price_to_sma200",
}
TARGET_STEP = "max_range_position_52w"
ARMS = ("baseline", "hard_to_soft")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Fixed same-state risk_off low_value single range-gate ablation."
        )
    )
    p.add_argument("--dataset", required=True)
    p.add_argument("--scan-config", default="configs/config.risk_off.json")
    p.add_argument(
        "--include-channels",
        default="core_ai,ai_enabler,ai_peripheral",
    )
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument(
        "--output-prefix",
        default="outputs/pr30_single_range_gate/single_range_gate",
    )
    return p


def parse_tokens(raw: str) -> list[str]:
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def validate_canonical_dataset(dataset_path: Path) -> dict[str, Any]:
    actual_sha = sha256_file(dataset_path)
    if actual_sha != EXPECTED_DATASET_SHA256:
        raise ValueError(
            "PR30 is pre-registered against the committed PR28 expanded "
            f"dataset SHA256 {EXPECTED_DATASET_SHA256}; got {actual_sha}"
        )

    meta_path = dataset_path.with_suffix(".meta.json")
    if not meta_path.exists():
        raise FileNotFoundError(
            f"expanded dataset metadata required: {meta_path}"
        )
    meta = json.loads(meta_path.read_text())
    if str(meta.get("style", "")) != "risk_off":
        raise ValueError("canonical dataset must use style=risk_off")
    if list(meta.get("list_types") or []) != ["low_value"]:
        raise ValueError("canonical dataset must be low_value-only")
    if not bool(meta.get("research_expanded_survivor_dataset")):
        raise ValueError("dataset is not marked research-expanded")
    skipped = {
        str(x)
        for x in (meta.get("research_skipped_low_value_hard_steps") or [])
    }
    if skipped != EXPECTED_EXPANDED_SKIPS:
        raise ValueError(
            "canonical dataset skipped-step set changed: "
            f"expected={sorted(EXPECTED_EXPANDED_SKIPS)} "
            f"actual={sorted(skipped)}"
        )
    if bool(meta.get("allow_latest_watchlist_fallback")):
        raise ValueError("latest-watchlist fallback must remain disabled")
    return {
        "meta": meta,
        "dataset_sha256": actual_sha,
        "meta_sha256": sha256_file(meta_path),
        "meta_path": str(meta_path),
    }


def git_head_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def unique_cross_section(date_rows: pd.DataFrame) -> pd.DataFrame:
    """Recover the one-row-per-symbol production cross-section.

    The expanded survivor file repeats raw rows once per channel. Channel and
    extracted soft-pass counters are expected to differ; every other field
    must agree across duplicate symbol rows or the same-state oracle is not
    well-defined.
    """
    if date_rows.empty:
        return date_rows.copy()
    work = date_rows.copy()
    work["_symbol_key"] = (
        work["symbol"].astype(str).str.strip().str.upper()
    )
    ignored = {
        "channel",
        "soft_pass_count",
        "soft_total",
        "_symbol_key",
    }
    compare_cols = [
        col for col in work.columns if col not in ignored
    ]

    for symbol, group in work.groupby("_symbol_key", sort=False):
        if len(group) <= 1:
            continue
        first = group.iloc[0]
        for col in compare_cols:
            ref = first.get(col)
            series = group[col]
            if pd.isna(ref):
                mismatch = series.notna()
            elif isinstance(ref, float) and np.isfinite(ref):
                numeric = pd.to_numeric(series, errors="coerce")
                mismatch = ~np.isclose(
                    numeric.to_numpy(dtype=float),
                    float(ref),
                    rtol=0.0,
                    atol=1e-12,
                    equal_nan=True,
                )
                if bool(np.asarray(mismatch).any()):
                    raise ValueError(
                        "cross-channel raw-field disagreement for "
                        f"{symbol} column={col}"
                    )
                continue
            else:
                mismatch = (
                    series.fillna("").astype(str)
                    != str(ref)
                )
            if bool(np.asarray(mismatch).any()):
                raise ValueError(
                    "cross-channel raw-field disagreement for "
                    f"{symbol} column={col}"
                )

    out = (
        work.drop_duplicates(
            subset=["_symbol_key"],
            keep="first",
        )
        .drop(
            columns=[
                "_symbol_key",
                "channel",
                "soft_pass_count",
                "soft_total",
            ],
            errors="ignore",
        )
        .reset_index(drop=True)
    )
    return out


def canonical_baseline_select(
    date_rows: pd.DataFrame,
    *,
    config: ScanConfig,
    channels: list[str],
    top_n: int,
) -> tuple[list[str], dict[str, list[str]], dict[str, Any]]:
    cross_section = unique_cross_section(date_rows)
    picks, diagnostics = rank_and_pick_symbols_with_diagnostics(
        df=cross_section,
        scan_config=config,
        list_type="low_value",
        top_n=top_n,
        per_channel_top_n=True,
        include_channels=channels,
    )
    channel_symbols = {
        channel: [
            str(x).strip().upper()
            for x in diagnostics.get("channel_symbols", {}).get(
                channel,
                [],
            )
            if str(x).strip()
        ]
        for channel in channels
    }
    return picks, channel_symbols, diagnostics


def research_select(
    date_rows: pd.DataFrame,
    *,
    config: ScanConfig,
    channels: list[str],
    top_n: int,
    arm: str,
) -> tuple[list[str], dict[str, list[str]], dict[str, int], dict[str, list[str]]]:
    ranked_frames: list[pd.DataFrame] = []
    active_targets: dict[str, list[str]] = {}
    for channel in channels:
        part = date_rows[
            date_rows["channel"].astype(str) == channel
        ].copy()
        ranked, active = base.rank_channel(
            part,
            config,
            channel,
            arm,
            {TARGET_STEP},
        )
        active_targets[channel] = active
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
    for channel in channels:
        channel_symbols.setdefault(channel, [])
        channel_counts.setdefault(channel, 0)
    return picks, channel_symbols, channel_counts, active_targets


def _parity_row(
    *,
    signal_date: str,
    scope: str,
    canonical: list[str],
    research: list[str],
) -> dict[str, Any]:
    canonical_norm = [str(x).strip().upper() for x in canonical]
    research_norm = [str(x).strip().upper() for x in research]
    canonical_set = set(canonical_norm)
    research_set = set(research_norm)
    union = canonical_set | research_set
    return {
        "signal_date": signal_date,
        "scope": scope,
        "canonical_n": len(canonical_norm),
        "research_n": len(research_norm),
        "exact_match": canonical_norm == research_norm,
        "order_match": canonical_norm == research_norm,
        "jaccard": (
            float(len(canonical_set & research_set) / len(union))
            if union
            else 1.0
        ),
        "canonical_only": ",".join(
            sorted(canonical_set - research_set)
        ),
        "research_only": ",".join(
            sorted(research_set - canonical_set)
        ),
        "canonical_json": json.dumps(
            canonical_norm,
            separators=(",", ":"),
        ),
        "research_json": json.dumps(
            research_norm,
            separators=(",", ":"),
        ),
    }


def evaluate_same_state(
    dataset: pd.DataFrame,
    *,
    config: ScanConfig,
    channels: list[str],
    top_n: int,
    horizons: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_rows: list[dict[str, Any]] = []
    parity_rows: list[dict[str, Any]] = []

    for signal_date, date_rows in dataset.groupby(
        "signal_date",
        sort=True,
    ):
        signal_date = str(signal_date)
        regime = (
            str(date_rows["regime"].dropna().iloc[0])
            if "regime" in date_rows.columns
            and not date_rows["regime"].dropna().empty
            else "unknown"
        )
        return_maps = {
            h: base.returns_by_symbol(date_rows, h)
            for h in horizons
        }
        qqq = {
            h: base.qqq_return(date_rows, h)
            for h in horizons
        }

        canonical_picks, canonical_channels, _diag = (
            canonical_baseline_select(
                date_rows,
                config=config,
                channels=channels,
                top_n=top_n,
            )
        )
        research_picks, research_channels, _counts, active = (
            research_select(
                date_rows,
                config=config,
                channels=channels,
                top_n=top_n,
                arm="baseline",
            )
        )

        for channel in channels:
            if set(active.get(channel, [])) != {TARGET_STEP}:
                raise ValueError(
                    "single-gate target is not active in "
                    f"{channel}: {active.get(channel, [])}"
                )
            parity_rows.append(
                _parity_row(
                    signal_date=signal_date,
                    scope=channel,
                    canonical=canonical_channels.get(channel, []),
                    research=research_channels.get(channel, []),
                )
            )
        parity_rows.append(
            _parity_row(
                signal_date=signal_date,
                scope="ALL",
                canonical=canonical_picks,
                research=research_picks,
            )
        )

        arm_selections: dict[str, tuple[list[str], dict[str, list[str]]]] = {
            "baseline": (canonical_picks, canonical_channels)
        }
        b_picks, b_channels, _b_counts, b_active = research_select(
            date_rows,
            config=config,
            channels=channels,
            top_n=top_n,
            arm="hard_to_soft",
        )
        for channel in channels:
            if set(b_active.get(channel, [])) != {TARGET_STEP}:
                raise ValueError(
                    "single-gate target is not active in B arm "
                    f"{channel}: {b_active.get(channel, [])}"
                )
        arm_selections["hard_to_soft"] = (b_picks, b_channels)

        for arm in ARMS:
            picks, channel_symbols = arm_selections[arm]
            for horizon in horizons:
                selected_returns = [
                    return_maps[horizon][symbol]
                    for symbol in picks
                    if symbol in return_maps[horizon]
                ]
                avg_return = base.finite_mean(selected_returns)
                excess = (
                    float(avg_return - qqq[horizon])
                    if np.isfinite(avg_return)
                    and np.isfinite(qqq[horizon])
                    else float("nan")
                )
                event_rows.append(
                    {
                        "signal_date": signal_date,
                        "year": signal_date[:4],
                        "regime": regime,
                        "arm": arm,
                        "horizon_days": int(horizon),
                        "n_selected": int(len(picks)),
                        "n_mature_selected": int(
                            len(selected_returns)
                        ),
                        "avg_return": avg_return,
                        "qqq_return": qqq[horizon],
                        "excess_vs_qqq": excess,
                        "selected_symbols_json": json.dumps(
                            picks,
                            separators=(",", ":"),
                        ),
                        "channel_symbols_json": json.dumps(
                            channel_symbols,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )

    return pd.DataFrame(event_rows), pd.DataFrame(parity_rows)


def circular_block_bootstrap_mean_ci(
    values: np.ndarray,
    *,
    block_len: int,
    seed: int,
    n_boot: int = 5000,
    confidence: float = 0.90,
) -> tuple[float, float]:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    n = len(vals)
    if n < 2:
        return float("nan"), float("nan")
    block_len = max(1, min(int(block_len), n))
    rng = np.random.default_rng(int(seed))
    n_blocks = int(math.ceil(n / block_len))
    means = np.empty(int(n_boot), dtype=float)
    offsets = np.arange(block_len, dtype=int)
    for i in range(int(n_boot)):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (
            starts[:, None] + offsets[None, :]
        ) % n
        sample = vals[idx.ravel()[:n]]
        means[i] = float(sample.mean())
    alpha = 1.0 - float(confidence)
    return (
        float(np.quantile(means, alpha / 2.0)),
        float(np.quantile(means, 1.0 - alpha / 2.0)),
    )


def overlap_block_len(horizon_days: int) -> int:
    return max(1, int(math.ceil(int(horizon_days) / 21.0)))


