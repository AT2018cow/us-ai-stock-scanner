#!/usr/bin/env python3
"""E4a: trailing regime-indicator separation audit (diagnostic only).

Pre-registered specification:
``docs/agent_specs/regime_indicator_validation_spec.md`` (v2,
architect-revised). This runner is fully offline and deterministic: it reads
the two frozen datasets, rebuilds v1/v2 decisions through the shared
``build_scope_records`` path (anti-drift requirement), computes the three
pre-registered trailing-only regime labels (R0/R1/R2), runs the
pre-registered separation tests (S0 hard safety check; T1/T2/T3), and writes
compact commit-safe evidence.

The output is a go/no-go for a *future* pre-registered E4b experiment ticket
only. No policy, threshold, weight, or production behavior change is
proposed, implied, or promoted (AGENTS.md section 8: retrospective evidence
cannot auto-promote).

Example:
    .venv/bin/python scripts/audit_regime_separation.py \\
      --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \\
      --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \\
      --out-dir docs/regime_indicator_validation_20261017
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd

from ai_value_scanner.research.m4_paired_validation import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    contains_absolute_path,
    paired_delta_stats,
)

import run_extended_replay_evaluation as extended_replay  # noqa: E402
from run_extended_replay_evaluation import (  # noqa: E402
    RANK_TIERS,
    build_scope_records,
    cohort_member,
    date_metric_means,
    segment_cohort_summary,
    summarize_date_means,
    tier_member,
    validate_disjoint_dates,
)

RUNNER_SCRIPT_REL = "scripts/audit_regime_separation.py"
SPEC_REL = "docs/agent_specs/regime_indicator_validation_spec.md"
DEFAULT_OUT_DIR = "docs/regime_indicator_validation_20261017"
MAX_DIR_BYTES = 140 * 1024

HORIZON_KEY = "excess_60"
VARIANTS: tuple[str, ...] = ("v1_current", "v2_current")
SCOPES: tuple[str, ...] = ("ETF_SLICE", "FULL")  # primary scope first
SAMPLES: tuple[str, ...] = ("MERGED_51", "BASE_39_ONLY")
CONTEXT_INDICATORS: tuple[str, ...] = ("R0", "R1", "R2")
MERGED_INDICATORS: tuple[str, ...] = (
    "R0", "R1", "R2", "R1_SENS_LO", "R1_SENS_HI",
)
INDICATOR_ROLES: dict[str, str] = {
    "R0": "context",
    "R1": "primary",
    "R2": "context",
    "R1_SENS_LO": "sensitivity",
    "R1_SENS_HI": "sensitivity",
}
PRIMARY_SAMPLE = "MERGED_51"
PRIMARY_SCOPE = "ETF_SLICE"
PRIMARY_INDICATOR = "R1"

UPTREND = "UPTREND"
DOWNTREND = "DOWNTREND"
NEUTRAL = "NEUTRAL"

# Pre-registered constants (spec section 3; changing these after seeing
# results is forbidden):
R1_BREADTH_UPTREND_MIN = 0.50
R1_BREADTH_DOWNTREND_MAX = 0.45
R1_SENSITIVITY_OFFSET = 0.05
VOL_HIGH_MIN_PRIOR_DATES = 6
# Pre-registered bars (spec section 4):
T1_SEPARATION_BAR = 0.02
MATERIALITY_BAR = 0.02

SUMMARY_COLUMNS: tuple[str, ...] = (
    "sample", "universe_scope", "indicator", "role", "test", "metric",
    "n_up_dates", "n_down_dates",
    "mean_up", "mean_down", "diff_up_minus_down",
    "diff_ci95_low", "diff_ci95_high",
    "regime_ci95_low_up", "regime_ci95_high_up",
    "regime_ci95_low_down", "regime_ci95_high_down",
    "metric_loo_min_up", "metric_loo_min_down",
    "loo_min_across", "loo_max_across", "loo_worst_date_dropped",
    "loo_sign_kept",
    "positive_share_up", "positive_share_down",
    "t_stat_up", "t_stat_down",
    "bar_met",
)
PER_DATE_COLUMNS: tuple[str, ...] = (
    "signal_date", "dataset", "regime_raw",
    "r0_label", "r2_label", "r1_merged_label", "r1_base_only_label",
    "r1_sens_lo_label", "r1_sens_hi_label",
    "qqq_trailing_return_60d", "breadth", "median_volatility_60d",
    "vol_high_merged", "vol_high_base_only", "is_bear_2022",
)
TIER_COLUMNS: tuple[str, ...] = (
    "sample", "universe_scope", "indicator", "regime", "tier",
    "n_dates_60", "obs_60", "mean_excess_60", "diff_vs_universe_60",
)


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is None:
        return ""
    return f"{number:.6f}"


def _pct(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:+.1f}%"


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[Any]) -> float | None:
    ordered = sorted(float(v) for v in values if _num(v) is not None)
    n = len(ordered)
    if n == 0:
        return None
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"true", "1", "yes"}:
        return True
    if token in {"false", "0", "no"}:
        return False
    return None


# ---------------------------------------------------------------------------
# Pre-registered indicator definitions (trailing-only; firewall-scanned)
# ---------------------------------------------------------------------------


def compute_date_cross_section_stats(
    frame: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Per signal-date trailing market context (indicator inputs only).

    Consumed columns: ``qqq_trailing_return_60d`` (trend), ``price_to_sma200``
    (breadth), ``volatility_60d`` (volatility level), ``benchmark_trend_ok``
    (R2), ``regime`` (R0). Forward-looking label columns are never read here
    (enforced by the firewall test in tests/test_audit_regime_separation.py).

    ``breadth`` = rows with finite ``price_to_sma200`` > 1.0 divided by all
    rows on the date; dates with no finite values get breadth 0.0 (no
    breadth evidence), never an imputed UPTREND.
    """
    stats: dict[str, dict[str, Any]] = {}
    if frame is None or frame.empty:
        return stats
    for date, group in frame.groupby("signal_date", sort=True):
        trailing = None
        trend_ok = None
        regime = ""
        row_count = 0
        sma_above = 0
        vol_values: list[float] = []
        for record in group.to_dict(orient="records"):
            row_count += 1
            if trailing is None:
                trailing = _num(record.get("qqq_trailing_return_60d"))
            if trend_ok is None:
                trend_ok = _parse_optional_bool(record.get("benchmark_trend_ok"))
            if not regime:
                token = str(record.get("regime") or "").strip().lower()
                if token and token != "nan":
                    regime = token
            sma = _num(record.get("price_to_sma200"))
            if sma is not None and sma > 1.0:
                sma_above += 1
            vol = _num(record.get("volatility_60d"))
            if vol is not None:
                vol_values.append(vol)
        stats[str(date)] = {
            "trailing_return_60d": trailing,
            "trend_ok": trend_ok,
            "regime": regime,
            "breadth": (sma_above / row_count) if row_count else None,
            "median_volatility_60d": _median(vol_values),
        }
    return stats


def compute_vol_high_flags(
    date_sequence: Sequence[str],
    date_stats: Mapping[str, Mapping[str, Any]],
    min_prior_dates: int = VOL_HIGH_MIN_PRIOR_DATES,
) -> dict[str, bool]:
    """vol_high per date: cross-sectional median ``volatility_60d`` above its
    own expanding trailing median over the given chronological sequence.

    Needs at least ``min_prior_dates`` prior dates; the first
    ``min_prior_dates`` dates of the sequence inherit ``False`` (warm-up,
    disclosed in the report). A date with no computable cross-sectional
    median inherits ``False`` (never imputed as high).
    """
    ordered = sorted(str(date) for date in date_sequence)
    flags: dict[str, bool] = {date: False for date in ordered}
    prior_medians: list[float] = []
    for index, date in enumerate(ordered):
        median_value = _num(
            date_stats.get(date, {}).get("median_volatility_60d")
        )
        if (
            index >= min_prior_dates
            and len(prior_medians) >= min_prior_dates
            and median_value is not None
        ):
            trailing = _median(prior_medians)
            flags[date] = trailing is not None and median_value > trailing
        if median_value is not None:
            prior_medians.append(median_value)
    return flags


def compute_r1_labels(
    date_stats: Mapping[str, Mapping[str, Any]],
    vol_high: Mapping[str, bool],
    *,
    breadth_up_min: float = R1_BREADTH_UPTREND_MIN,
    breadth_down_max: float = R1_BREADTH_DOWNTREND_MAX,
) -> dict[str, str]:
    """R1 composite: trend + breadth + volatility (spec section 3).

    UPTREND iff trend_up AND breadth >= ``breadth_up_min`` AND NOT vol_high;
    DOWNTREND iff trend_down AND (breadth < ``breadth_down_max`` OR vol_high);
    else NEUTRAL. Cutoffs are majority-rule constants, never tuned.
    """
    labels: dict[str, str] = {}
    for date, stats in date_stats.items():
        trend = _num(stats.get("trailing_return_60d"))
        breadth = _num(stats.get("breadth"))
        high = bool(vol_high.get(date, False))
        trend_up = trend is not None and trend > 0
        trend_down = trend is not None and trend < 0
        if (
            trend_up
            and breadth is not None
            and breadth >= breadth_up_min
            and not high
        ):
            labels[str(date)] = UPTREND
        elif trend_down and (
            (breadth is not None and breadth < breadth_down_max) or high
        ):
            labels[str(date)] = DOWNTREND
        else:
            labels[str(date)] = NEUTRAL
    return labels


def compute_r2_labels(
    date_stats: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """R2 simplicity challenger: ``benchmark_trend_ok`` as-is."""
    labels: dict[str, str] = {}
    for date, stats in date_stats.items():
        trend_ok = stats.get("trend_ok")
        if trend_ok is True:
            labels[str(date)] = UPTREND
        elif trend_ok is False:
            labels[str(date)] = DOWNTREND
        else:
            labels[str(date)] = NEUTRAL
    return labels


def compute_r0_labels(
    date_stats: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """R0 status-quo reference: the datasets' ``regime`` column as-is."""
    labels: dict[str, str] = {}
    for date, stats in date_stats.items():
        regime = str(stats.get("regime") or "")
        if regime == "up":
            labels[str(date)] = UPTREND
        elif regime == "down":
            labels[str(date)] = DOWNTREND
        else:
            labels[str(date)] = NEUTRAL
    return labels


def compute_regime_labels(
    base_frame: pd.DataFrame,
    bear_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """All pre-registered labels for one merged/base-only date sequence.

    Primary labels (R0/R1/R2, plus the +-0.05 R1 sensitivity variants) are
    computed over the merged, deduplicated, chronologically sorted date
    sequence (bear-2022 dates first). ``R1_BASE_ONLY`` recomputes R1 over the
    39 base dates alone (secondary context; spec section 3).
    """
    base_stats = compute_date_cross_section_stats(base_frame)
    bear_stats = (
        compute_date_cross_section_stats(bear_frame)
        if bear_frame is not None
        else {}
    )
    all_stats: dict[str, dict[str, Any]] = {**bear_stats, **base_stats}
    merged_sequence = sorted(all_stats)
    base_sequence = sorted(base_stats)
    vol_high_merged = compute_vol_high_flags(merged_sequence, all_stats)
    vol_high_base = compute_vol_high_flags(base_sequence, base_stats)
    labels = {
        "R0": compute_r0_labels(all_stats),
        "R2": compute_r2_labels(all_stats),
        "R1": compute_r1_labels(all_stats, vol_high_merged),
        "R1_SENS_LO": compute_r1_labels(
            all_stats,
            vol_high_merged,
            breadth_up_min=R1_BREADTH_UPTREND_MIN - R1_SENSITIVITY_OFFSET,
            breadth_down_max=R1_BREADTH_DOWNTREND_MAX - R1_SENSITIVITY_OFFSET,
        ),
        "R1_SENS_HI": compute_r1_labels(
            all_stats,
            vol_high_merged,
            breadth_up_min=R1_BREADTH_UPTREND_MIN + R1_SENSITIVITY_OFFSET,
            breadth_down_max=R1_BREADTH_DOWNTREND_MAX + R1_SENSITIVITY_OFFSET,
        ),
        "R1_BASE_ONLY": compute_r1_labels(base_stats, vol_high_base),
    }
    return {
        "base_stats": base_stats,
        "bear_stats": bear_stats,
        "all_stats": all_stats,
        "merged_sequence": merged_sequence,
        "base_sequence": base_sequence,
        "vol_high_merged": vol_high_merged,
        "vol_high_base_only": vol_high_base,
        "labels": labels,
    }


# Names in the indicator-definition code path; the firewall test asserts none
# of these functions ever references a forward-label column (spec section 5).
INDICATOR_SOURCE_FUNCTIONS: tuple[str, ...] = (
    "compute_date_cross_section_stats",
    "compute_vol_high_flags",
    "compute_r1_labels",
    "compute_r2_labels",
    "compute_r0_labels",
    "compute_regime_labels",
)


# ---------------------------------------------------------------------------
# Aggregation primitives (forward labels enter ONLY from here on)
# ---------------------------------------------------------------------------


def bootstrap_difference_ci(
    up_values: Sequence[float],
    down_values: Sequence[float],
    *,
    seed: int = BOOTSTRAP_SEED,
    n_boot: int = BOOTSTRAP_DRAWS,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI of mean(up) - mean(down), independent groups.

    Same seed / draw count / percentile indexing convention as the E0
    ``paired_delta_stats`` bootstrap.
    """
    up = [float(v) for v in up_values if _num(v) is not None]
    down = [float(v) for v in down_values if _num(v) is not None]
    if not up or not down:
        return None, None
    rng = random.Random(seed)
    n_up, n_down = len(up), len(down)
    draws = sorted(
        sum(rng.choices(up, k=n_up)) / n_up
        - sum(rng.choices(down, k=n_down)) / n_down
        for _ in range(n_boot)
    )
    low = draws[int(0.025 * n_boot)]
    high = draws[min(n_boot - 1, int(0.975 * n_boot))]
    return low, high


def paired_t_stat(values: Sequence[Any]) -> float | None:
    """t = mean / (sample std ddof=1 / sqrt(n)); None for n < 2 or zero std."""
    ordered = [float(v) for v in values if _num(v) is not None]
    n = len(ordered)
    if n < 2:
        return None
    mean = sum(ordered) / n
    variance = sum((value - mean) ** 2 for value in ordered) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return mean / (std / math.sqrt(n))


def materially_differs(
    mean_up: Any,
    mean_down: Any,
    bar: float = MATERIALITY_BAR,
) -> bool:
    """Pre-registered 'differs materially' rule (spec section 4)."""
    up = _num(mean_up)
    down = _num(mean_down)
    if up is None or down is None:
        return False
    sign_differs = (up > 0 > down) or (down > 0 > up)
    return bool(sign_differs or abs(up - down) > bar)


def loo_min_of_values(values: Sequence[Any]) -> float | None:
    """min over removing one entry of the remaining mean (n >= 2 required)."""
    ordered = [float(v) for v in values if _num(v) is not None]
    n = len(ordered)
    if n < 2:
        return None
    total = sum(ordered)
    return min((total - value) / (n - 1) for value in ordered)


def loo_difference_stats(
    up_by_date: Mapping[str, Any],
    down_by_date: Mapping[str, Any],
) -> dict[str, Any]:
    """Drop-one-date robustness of mean(up) - mean(down).

    Candidates drop one date from its own regime and recompute the
    difference; dropping the single date of a size-1 regime is undefined and
    skipped (never imputed). "Drop-worst-date" for a positive full value is
    the removal minimizing the recomputed value (kept sign = LOO-min stays
    positive); for a negative full value it is the maximizing removal.
    """
    up = {
        str(d): float(v) for d, v in up_by_date.items() if _num(v) is not None
    }
    down = {
        str(d): float(v) for d, v in down_by_date.items() if _num(v) is not None
    }
    result: dict[str, Any] = {
        "full": None,
        "loo_min": None,
        "loo_max": None,
        "loo_sign_kept": None,
        "worst_dropped_side": None,
        "worst_dropped_date": None,
        "recomputed_without_worst": None,
        "n_candidate_dates": 0,
        "up_single_date_skipped": bool(up) and len(up) < 2,
        "down_single_date_skipped": bool(down) and len(down) < 2,
    }
    if not up or not down:
        return result
    total_up = sum(up[d] for d in sorted(up))
    total_down = sum(down[d] for d in sorted(down))
    mean_up = total_up / len(up)
    mean_down = total_down / len(down)
    full = mean_up - mean_down
    candidates: list[tuple[str, str, float]] = []
    if len(up) >= 2:
        for date in sorted(up):
            reduced = (total_up - up[date]) / (len(up) - 1)
            candidates.append(("up", date, reduced - mean_down))
    if len(down) >= 2:
        for date in sorted(down):
            reduced = (total_down - down[date]) / (len(down) - 1)
            candidates.append(("down", date, mean_up - reduced))
    result["full"] = full
    result["n_candidate_dates"] = len(candidates)
    if not candidates:
        return result
    result["loo_min"] = min(value for _, _, value in candidates)
    result["loo_max"] = max(value for _, _, value in candidates)
    if full > 0:
        worst = min(candidates, key=lambda item: item[2])
        result["loo_sign_kept"] = result["loo_min"] > 0
    elif full < 0:
        worst = max(candidates, key=lambda item: item[2])
        result["loo_sign_kept"] = result["loo_max"] < 0
    else:
        worst = None
        result["loo_sign_kept"] = False
    if worst is not None:
        result["worst_dropped_side"] = worst[0]
        result["worst_dropped_date"] = worst[1]
        result["recomputed_without_worst"] = worst[2]
    return result


def _empty_result(test: str, metric: str) -> dict[str, Any]:
    return {
        "test": test,
        "metric": metric,
        "n_up_dates": 0,
        "n_down_dates": 0,
        "mean_up": None,
        "mean_down": None,
        "diff": None,
        "diff_ci95_low": None,
        "diff_ci95_high": None,
        "regime_ci95_low_up": None,
        "regime_ci95_high_up": None,
        "regime_ci95_low_down": None,
        "regime_ci95_high_down": None,
        "metric_loo_min_up": None,
        "metric_loo_min_down": None,
        "loo_min_across": None,
        "loo_max_across": None,
        "loo_worst_date_dropped": None,
        "loo_recomputed_without_worst": None,
        "loo_sign_kept": None,
        "positive_share_up": None,
        "positive_share_down": None,
        "t_stat_up": None,
        "t_stat_down": None,
        "bar_met": False,
    }


def _apply_across_stats(result: dict[str, Any], across: Mapping[str, Any]) -> None:
    result["diff"] = across["full"]
    result["loo_min_across"] = across["loo_min"]
    result["loo_max_across"] = across["loo_max"]
    result["loo_worst_date_dropped"] = across["worst_dropped_date"]
    result["loo_recomputed_without_worst"] = across["recomputed_without_worst"]
    result["loo_sign_kept"] = across["loo_sign_kept"]


# ---------------------------------------------------------------------------
# Pre-registered separation tests (T1/T2/T3)
# ---------------------------------------------------------------------------


def t1_separation(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    """T1: date-equal universe 60d net-QQQ excess, UPTREND vs DOWNTREND dates.

    Universe excess is scope-level (all members); for a fixed scope it does
    not depend on the decision variant, so v2 records are used as carrier.
    """
    means, _ = date_metric_means(
        records_by_date, dates, lambda record: True, HORIZON_KEY
    )
    up = {d: means[d] for d in dates if labels.get(d) == UPTREND and d in means}
    down = {
        d: means[d] for d in dates if labels.get(d) == DOWNTREND and d in means
    }
    result = _empty_result("T1", "universe_mean_excess_60_up_vs_down")
    result["n_up_dates"] = len(up)
    result["n_down_dates"] = len(down)
    if up:
        result["mean_up"] = _mean([up[d] for d in sorted(up)])
    if down:
        result["mean_down"] = _mean([down[d] for d in sorted(down)])
    _apply_across_stats(result, loo_difference_stats(up, down))
    ci_low, ci_high = bootstrap_difference_ci(
        [up[d] for d in sorted(up)], [down[d] for d in sorted(down)]
    )
    result["diff_ci95_low"] = ci_low
    result["diff_ci95_high"] = ci_high
    result["bar_met"] = (
        result["diff"] is not None
        and abs(result["diff"]) > T1_SEPARATION_BAR
    )
    return result


def t2_separation(
    records_by_variant: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    dates: Sequence[str],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    """T2: date-paired v2-minus-v1 TOP15 60d delta per regime (E0 stats)."""
    member_fn = lambda record: cohort_member(record, "TOP15")  # noqa: E731
    v2_means, _ = date_metric_means(
        records_by_variant["v2_current"], dates, member_fn, HORIZON_KEY
    )
    v1_means, _ = date_metric_means(
        records_by_variant["v1_current"], dates, member_fn, HORIZON_KEY
    )
    delta_by_date = {
        d: v2_means[d] - v1_means[d] for d in v2_means if d in v1_means
    }
    up = {
        d: delta_by_date[d]
        for d in dates
        if labels.get(d) == UPTREND and d in delta_by_date
    }
    down = {
        d: delta_by_date[d]
        for d in dates
        if labels.get(d) == DOWNTREND and d in delta_by_date
    }

    def _paired(delta_dates: Mapping[str, float]) -> dict[str, Any] | None:
        if not delta_dates:
            return None
        keys = sorted(delta_dates)
        return paired_delta_stats(
            {d: v2_means[d] for d in keys}, {d: v1_means[d] for d in keys}
        )

    up_paired = _paired(up)
    down_paired = _paired(down)
    result = _empty_result("T2", "v2_minus_v1_top15_excess_60_delta")
    result["n_up_dates"] = len(up)
    result["n_down_dates"] = len(down)
    if up:
        result["mean_up"] = _mean([up[d] for d in sorted(up)])
    if down:
        result["mean_down"] = _mean([down[d] for d in sorted(down)])
    if up_paired is not None:
        result["regime_ci95_low_up"] = up_paired["ci95_low_60d"]
        result["regime_ci95_high_up"] = up_paired["ci95_high_60d"]
        result["positive_share_up"] = up_paired["positive_delta_date_share"]
    if down_paired is not None:
        result["regime_ci95_low_down"] = down_paired["ci95_low_60d"]
        result["regime_ci95_high_down"] = down_paired["ci95_high_60d"]
        result["positive_share_down"] = down_paired[
            "positive_delta_date_share"
        ]
    result["metric_loo_min_up"] = loo_min_of_values(list(up.values()))
    result["metric_loo_min_down"] = loo_min_of_values(list(down.values()))
    _apply_across_stats(result, loo_difference_stats(up, down))
    result["bar_met"] = materially_differs(
        result["mean_up"], result["mean_down"]
    )
    return result


def t3_separation(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    """T3: tier-16-30-minus-universe gap per regime (the E1 headline cell)."""
    tier_fn = lambda record: tier_member(record, 16, 30)  # noqa: E731
    tier_means, _ = date_metric_means(
        records_by_date, dates, tier_fn, HORIZON_KEY
    )
    universe_means, _ = date_metric_means(
        records_by_date, dates, lambda record: True, HORIZON_KEY
    )
    gap = {
        d: tier_means[d] - universe_means[d]
        for d in tier_means
        if d in universe_means
    }
    up = {
        d: gap[d] for d in dates if labels.get(d) == UPTREND and d in gap
    }
    down = {
        d: gap[d] for d in dates if labels.get(d) == DOWNTREND and d in gap
    }
    result = _empty_result("T3", "tier_16_30_minus_universe_gap_60")
    result["n_up_dates"] = len(up)
    result["n_down_dates"] = len(down)
    if up:
        result["mean_up"] = _mean([up[d] for d in sorted(up)])
        result["t_stat_up"] = paired_t_stat([up[d] for d in sorted(up)])
    if down:
        result["mean_down"] = _mean([down[d] for d in sorted(down)])
        result["t_stat_down"] = paired_t_stat([down[d] for d in sorted(down)])
    result["metric_loo_min_up"] = loo_min_of_values(list(up.values()))
    result["metric_loo_min_down"] = loo_min_of_values(list(down.values()))
    _apply_across_stats(result, loo_difference_stats(up, down))
    result["bar_met"] = materially_differs(
        result["mean_up"], result["mean_down"]
    )
    return result


def compute_indicator_tests(
    records_by_scope: Mapping[
        str, Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
    ],
    dates: Sequence[str],
    label_map: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """T1/T2/T3 for one indicator label map, both universe scopes."""
    cells: dict[str, dict[str, Any]] = {}
    for scope in SCOPES:
        records_v2 = records_by_scope[scope]["v2_current"]
        cells[scope] = {
            "T1": t1_separation(records_v2, dates, label_map),
            "T2": t2_separation(records_by_scope[scope], dates, label_map),
            "T3": t3_separation(records_v2, dates, label_map),
        }
    return cells


# ---------------------------------------------------------------------------
# S0 safety check + pre-registered go rule
# ---------------------------------------------------------------------------


def evaluate_e4b_go(
    *,
    bear_uptrend_dates: Sequence[str],
    t1: Mapping[str, Any],
    t2: Mapping[str, Any],
    t3: Mapping[str, Any],
) -> dict[str, Any]:
    """Pre-registered E4b-go rule (spec section 4); pure gate evaluation."""
    s0_pass = len(bear_uptrend_dates) == 0
    t1_diff = _num(t1.get("diff"))
    t1_pass = t1_diff is not None and abs(t1_diff) > T1_SEPARATION_BAR
    t2_material = bool(t2.get("bar_met"))
    t3_material = bool(t3.get("bar_met"))
    material_pass = t2_material or t3_material

    qualifying: list[dict[str, Any]] = []
    if t1_pass:
        qualifying.append({
            "cell": "T1",
            "full": t1.get("diff"),
            "loo_min": t1.get("loo_min_across"),
            "loo_max": t1.get("loo_max_across"),
            "worst_date": t1.get("loo_worst_date_dropped"),
            "recomputed": t1.get("loo_recomputed_without_worst"),
            "sign_kept": bool(t1.get("loo_sign_kept")),
        })
    if t2_material:
        qualifying.append({
            "cell": "T2",
            "full": t2.get("diff"),
            "loo_min": t2.get("loo_min_across"),
            "loo_max": t2.get("loo_max_across"),
            "worst_date": t2.get("loo_worst_date_dropped"),
            "recomputed": t2.get("loo_recomputed_without_worst"),
            "sign_kept": bool(t2.get("loo_sign_kept")),
        })
    if t3_material:
        qualifying.append({
            "cell": "T3",
            "full": t3.get("diff"),
            "loo_min": t3.get("loo_min_across"),
            "loo_max": t3.get("loo_max_across"),
            "worst_date": t3.get("loo_worst_date_dropped"),
            "recomputed": t3.get("loo_recomputed_without_worst"),
            "sign_kept": bool(t3.get("loo_sign_kept")),
        })
    drop_pass = bool(qualifying) and all(
        item["sign_kept"] for item in qualifying
    )
    gates = [
        {
            "id": "S0",
            "name": "bear-2022 safety check (0 R1 UPTREND dates)",
            "pass": s0_pass,
            "detail": (
                f"{len(bear_uptrend_dates)} R1 UPTREND date(s) in BEAR_2022: "
                + (", ".join(bear_uptrend_dates) if bear_uptrend_dates else "-")
            ),
        },
        {
            "id": "T1",
            "name": (
                f"abs(UP - DOWN) > {T1_SEPARATION_BAR:g} on primary R1 cell"
            ),
            "pass": t1_pass,
            "detail": (
                f"diff={_fmt(t1_diff)} "
                f"(bar met: {t1_pass})"
            ),
        },
        {
            "id": "MATERIAL",
            "name": "T2 or T3 differs materially between UP and DOWN",
            "pass": material_pass,
            "detail": f"T2 material={t2_material}, T3 material={t3_material}",
        },
        {
            "id": "DROP-WORST",
            "name": "drop-worst-date re-check keeps the sign",
            "pass": drop_pass,
            "detail": (
                "qualifying cells: "
                + (
                    ", ".join(
                        f"{item['cell']} (sign kept={item['sign_kept']})"
                        for item in qualifying
                    )
                    if qualifying
                    else "none"
                )
            ),
        },
    ]
    verdict = "GO" if all(gate["pass"] for gate in gates) else "NO_GO"
    return {
        "verdict": verdict,
        "gates": gates,
        "qualifying_cells": qualifying,
        "fail_reasons": [
            f"{gate['id']}: {gate['detail']}"
            for gate in gates
            if not gate["pass"]
        ],
    }


# ---------------------------------------------------------------------------
# Decision rebuild (shared anti-drift path)
# ---------------------------------------------------------------------------


def rebuild_records(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, dict[str, dict[str, dict[str, list[dict[str, Any]]]]]]:
    """Per dataset/scope/variant/date records via shared build_scope_records."""
    records: dict[
        str, dict[str, dict[str, dict[str, list[dict[str, Any]]]]]
    ] = {}
    for dataset_name, frame in frames.items():
        records[dataset_name] = {
            scope: {variant: {} for variant in VARIANTS} for scope in SCOPES
        }
        for date, group in frame.groupby("signal_date", sort=True):
            token = str(date)
            for scope in SCOPES:
                for variant in VARIANTS:
                    records[dataset_name][scope][variant][token] = (
                        build_scope_records(group, scope, variant, token)
                    )
    return records


def merge_records(
    dataset_records: Mapping[
        str, Mapping[str, Mapping[str, Mapping[str, Sequence[Any]]]]
    ],
    order: Sequence[str] = ("bear", "base"),
) -> dict[str, dict[str, dict[str, list[dict[str, Any]]]]]:
    """Merge disjoint datasets into one scope/variant/date record store."""
    merged = {scope: {variant: {} for variant in VARIANTS} for scope in SCOPES}
    for name in order:
        for scope in SCOPES:
            for variant in VARIANTS:
                merged[scope][variant].update(dataset_records[name][scope][variant])
    return merged


# ---------------------------------------------------------------------------
# Output tables
# ---------------------------------------------------------------------------


def count_labels(
    labels: Mapping[str, str], dates: Sequence[str]
) -> dict[str, int]:
    counts = {UPTREND: 0, DOWNTREND: 0, NEUTRAL: 0}
    for date in dates:
        label = labels.get(date, NEUTRAL)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _summary_row(
    sample: str,
    scope: str,
    indicator: str,
    role: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "sample": sample,
        "universe_scope": scope,
        "indicator": indicator,
        "role": role,
        "test": result["test"],
        "metric": result["metric"],
        "n_up_dates": result["n_up_dates"],
        "n_down_dates": result["n_down_dates"],
        "mean_up": _fmt(result["mean_up"]),
        "mean_down": _fmt(result["mean_down"]),
        "diff_up_minus_down": _fmt(result["diff"]),
        "diff_ci95_low": _fmt(result["diff_ci95_low"]),
        "diff_ci95_high": _fmt(result["diff_ci95_high"]),
        "regime_ci95_low_up": _fmt(result["regime_ci95_low_up"]),
        "regime_ci95_high_up": _fmt(result["regime_ci95_high_up"]),
        "regime_ci95_low_down": _fmt(result["regime_ci95_low_down"]),
        "regime_ci95_high_down": _fmt(result["regime_ci95_high_down"]),
        "metric_loo_min_up": _fmt(result["metric_loo_min_up"]),
        "metric_loo_min_down": _fmt(result["metric_loo_min_down"]),
        "loo_min_across": _fmt(result["loo_min_across"]),
        "loo_max_across": _fmt(result["loo_max_across"]),
        "loo_worst_date_dropped": result["loo_worst_date_dropped"] or "",
        "loo_sign_kept": result["loo_sign_kept"],
        "positive_share_up": _fmt(result["positive_share_up"]),
        "positive_share_down": _fmt(result["positive_share_down"]),
        "t_stat_up": _fmt(result["t_stat_up"]),
        "t_stat_down": _fmt(result["t_stat_down"]),
        "bar_met": result["bar_met"],
    }


def build_per_date_rows(labels_bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    all_stats = labels_bundle["all_stats"]
    labels = labels_bundle["labels"]
    vol_high_merged = labels_bundle["vol_high_merged"]
    vol_high_base = labels_bundle["vol_high_base_only"]
    rows: list[dict[str, Any]] = []
    for date in labels_bundle["merged_sequence"]:
        stats = all_stats[date]
        in_base = date in labels_bundle["base_stats"]
        in_bear = date in labels_bundle["bear_stats"]
        rows.append({
            "signal_date": date,
            "dataset": "bear_2022" if in_bear else "base_39",
            "regime_raw": stats.get("regime") or "",
            "r0_label": labels["R0"].get(date, ""),
            "r2_label": labels["R2"].get(date, ""),
            "r1_merged_label": labels["R1"].get(date, ""),
            "r1_base_only_label": (
                labels["R1_BASE_ONLY"].get(date, "") if in_base else ""
            ),
            "r1_sens_lo_label": labels["R1_SENS_LO"].get(date, ""),
            "r1_sens_hi_label": labels["R1_SENS_HI"].get(date, ""),
            "qqq_trailing_return_60d": _fmt(stats.get("trailing_return_60d")),
            "breadth": _fmt(stats.get("breadth")),
            "median_volatility_60d": _fmt(stats.get("median_volatility_60d")),
            "vol_high_merged": vol_high_merged.get(date, False),
            "vol_high_base_only": (
                vol_high_base.get(date, "") if in_base else ""
            ),
            "is_bear_2022": in_bear,
        })
    return rows


def build_tier_rows(
    records_by_scope: Mapping[
        str, Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
    ],
    sample: str,
    dates: Sequence[str],
    label_map: Mapping[str, str],
    indicator: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in SCOPES:
        by_date = records_by_scope[scope]["v2_current"]
        for regime in (UPTREND, DOWNTREND, NEUTRAL):
            regime_dates = [d for d in dates if label_map.get(d) == regime]
            if not regime_dates:
                continue
            universe_summary = segment_cohort_summary(
                by_date, regime_dates, lambda record: True
            )
            universe_mean = universe_summary["mean_excess_60"]
            for tier_label, low, high in RANK_TIERS:
                if tier_label == "universe":
                    member_fn = lambda record: True  # noqa: E731
                else:
                    member_fn = (
                        lambda record, lo=low, hi=high: tier_member(
                            record, lo, hi
                        )
                    )
                summary = segment_cohort_summary(
                    by_date, regime_dates, member_fn
                )
                diff = None
                if (
                    summary["mean_excess_60"] is not None
                    and universe_mean is not None
                ):
                    diff = summary["mean_excess_60"] - universe_mean
                rows.append({
                    "sample": sample,
                    "universe_scope": scope,
                    "indicator": indicator,
                    "regime": regime,
                    "tier": tier_label,
                    "n_dates_60": summary["n_dates_60"],
                    "obs_60": summary["obs_60"],
                    "mean_excess_60": _fmt(summary["mean_excess_60"]),
                    "diff_vs_universe_60": _fmt(diff),
                })
    return rows


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _select(
    rows: Sequence[Mapping[str, Any]], **filters: Any
) -> list[Mapping[str, Any]]:
    selected = []
    for row in rows:
        if all(str(row.get(key)) == str(value) for key, value in filters.items()):
            selected.append(row)
    return selected


def _counts_row(counts: Mapping[str, int]) -> str:
    return (
        f"UP {counts.get(UPTREND, 0)} / DOWN {counts.get(DOWNTREND, 0)} / "
        f"NEUTRAL {counts.get(NEUTRAL, 0)}"
    )


def _sample_label(sample: str) -> str:
    return "MERGED_51 (primary)" if sample == PRIMARY_SAMPLE else "BASE_39_ONLY (secondary)"


def render_report(context: Mapping[str, Any]) -> str:
    summary_rows = context["summary_rows"]
    verdict = context["verdict"]
    label_counts = context["label_counts"]
    merged_sequence = context["merged_sequence"]
    base_sequence = context["base_sequence"]

    lines: list[str] = []
    lines.append("# E4a — Trailing Regime-Indicator Separation Audit (Diagnostic Only)")
    lines.append("")
    lines.append(
        f"- Pre-registered spec: `{context['spec_rel']}` (v2, architect-revised)."
    )
    lines.append(
        f"- Runner: `{context['runner_rel']}` SHA256 `{context['runner_sha']}`."
    )
    lines.append(
        "- Fully offline and deterministic; frozen datasets read-only; zero "
        "network calls; no production code or config changes."
    )
    lines.append(
        "- **This audit proposes no policy change.** Its only output is a "
        "go/no-go for a *future* pre-registered E4b experiment ticket "
        "(AGENTS.md §8: retrospective results cannot auto-promote)."
    )
    lines.append("")

    lines.append("## 0. E4b go/no-go verdict (up front)")
    lines.append("")
    if verdict["verdict"] == "GO":
        lines.append(
            "**GO** — E4a licenses only a new pre-registered E4b experiment "
            "ticket with prospective/shadow evidence. It does not license any "
            "production or default-policy change."
        )
    else:
        lines.append(
            "**NO-GO / STOP** — on this frozen evidence there is no "
            "pre-registered separation to condition a future E4b policy on. "
            "**No E4b ticket will be opened and no policy change follows.** "
            "The pre-registered spec treats this outcome as a full result, "
            "not a failure to hide."
        )
    lines.append("")
    lines.append(_md_table(
        ["gate", "requirement", "result", "detail"],
        [
            [
                gate["id"], gate["name"],
                "PASS" if gate["pass"] else "FAIL",
                gate["detail"],
            ]
            for gate in verdict["gates"]
        ],
    ))
    lines.append("")
    if verdict["fail_reasons"]:
        lines.append("Failed gates: " + "; ".join(verdict["fail_reasons"]) + ".")
        lines.append("")
    lines.append(
        "> Warning: T1 is a loose descriptive screen only — it can be passed "
        "by sample-specific rebound artifacts and is **not** predictive-"
        "validity evidence; T1 alone can never pass the go rule."
    )
    lines.append("")

    lines.append("## 1. Provenance")
    lines.append("")
    base = context["base"]
    bear = context["bear"]
    lines.append(
        f"- Base dataset: `{base['name']}` ({base['rows']} rows, "
        f"{base['dates']} signal dates, SHA256 `{base['sha']}`)."
    )
    lines.append(
        f"- 2022 bear dataset: `{bear['name']}` ({bear['rows']} rows, "
        f"{bear['dates']} signal dates, SHA256 `{bear['sha']}`)."
    )
    lines.append(
        f"- Merged primary sample: {context['n_merged_dates']} dates "
        "(disjoint, deduplicated, chronologically sorted; 2022 dates first, "
        "vol_high sequence computed over this merged order)."
    )
    lines.append(f"- Reproduction command: `{context['command']}`.")
    lines.append(
        "- Primary scope: `ETF_SLICE` (`watchlist_etf_count >= 1`); `FULL` "
        "and `BASE_39_ONLY` tables are secondary context and cannot trigger "
        "a go."
    )
    lines.append(
        "- Decisions rebuilt per date via shared `build_scope_records` "
        "(`scripts/run_extended_replay_evaluation.py`), v1_current and "
        "v2_current; R0/R2/R1 labels use trailing-only inputs."
    )
    lines.append(
        "- Universe approximation: the current watchlist is applied to all "
        "historical dates (`union_superset_approx`); the ETF-slice cut is "
        "the bias-reduced read (AGENTS.md §4)."
    )
    lines.append(
        "- Retrospective replay only, not OOS; overlapping 60d windows are "
        "not independent samples (AGENTS.md §8)."
    )
    lines.append("")

    s0_gate = next(
        (gate for gate in verdict["gates"] if gate["id"] == "S0"), None
    )
    lines.append("## 2. S0 safety check (hard gate, primary indicator R1)")
    lines.append("")
    if s0_gate is not None:
        lines.append(
            f"Result: **{'PASS' if s0_gate['pass'] else 'FAIL'}** — "
            f"{s0_gate['detail']}."
        )
    lines.append("")
    s0_context = []
    for row in _select(summary_rows, test="S0"):
        s0_context.append([
            row["indicator"], row["role"], row["n_up_dates"],
            row["n_down_dates"],
        ])
    lines.append(_md_table(
        ["indicator", "role", "UPTREND dates in BEAR_2022",
         "DOWNTREND dates in BEAR_2022"],
        s0_context,
    ))
    lines.append("")
    lines.append(
        "Only R1 is the primary indicator; R0/R2 UPTREND counts in the 2022 "
        "bear sample are context only."
    )
    lines.append("")

    lines.append("## 3. Indicator label counts (dates)")
    lines.append("")
    count_rows = []
    for indicator in CONTEXT_INDICATORS:
        merged_counts = label_counts[PRIMARY_SAMPLE].get(indicator, {})
        base_counts = label_counts["BASE_39_ONLY"].get(indicator, {})
        count_rows.append([
            indicator, INDICATOR_ROLES[indicator],
            _counts_row(merged_counts), _counts_row(base_counts),
        ])
    lines.append(_md_table(
        ["indicator", "role", "MERGED_51 (primary sample)",
         "BASE_39_ONLY (secondary)"],
        count_rows,
    ))
    lines.append("")

    lines.append("## 4. Separation tests T1–T3 (all three indicators)")
    lines.append("")
    lines.append(
        "Rows are ordered primary first: MERGED_51 / ETF_SLICE, then "
        "MERGED_51 / FULL, then BASE_39_ONLY / ETF_SLICE and "
        "BASE_39_ONLY / FULL. Sensitivity rows are excluded here (section 6)."
    )
    lines.append("")
    for test, title, note in (
        (
            "T1",
            "T1 — universe 60d net-QQQ excess: UPTREND vs DOWNTREND dates",
            "date-equal means; diff = mean(UP) - mean(DOWN); bootstrap 95% "
            "CI of the difference; bar met = |diff| > 2pp.",
        ),
        (
            "T2",
            "T2 — date-paired v2-minus-v1 TOP15 60d delta per regime",
            "per-regime mean / bootstrap CI / LOO-min / positive-date share "
            "(E0 paired_delta_stats); material = regimes differ in sign or "
            "|diff| > 2pp.",
        ),
        (
            "T3",
            "T3 — tier-16–30-minus-universe gap per regime",
            "per-regime mean gap and paired t-stat over dates; material = "
            "regimes differ in sign or |diff| > 2pp.",
        ),
    ):
        lines.append(f"### {title}")
        lines.append("")
        rows = [
            row for row in summary_rows
            if row["test"] == test and row["role"] != "sensitivity"
        ]
        table_rows = []
        for row in rows:
            tag = f"{_sample_label(row['sample'])} / {row['universe_scope']}"
            if test == "T1":
                table_rows.append([
                    tag, row["indicator"], row["role"],
                    row["n_up_dates"], row["n_down_dates"],
                    _pct(_num(row["mean_up"])), _pct(_num(row["mean_down"])),
                    _pct(_num(row["diff_up_minus_down"])),
                    row["bar_met"],
                ])
            elif test == "T2":
                table_rows.append([
                    tag, row["indicator"], row["role"],
                    row["n_up_dates"], row["n_down_dates"],
                    f"{_pct(_num(row['mean_up']))} "
                    f"[{_pct(_num(row['regime_ci95_low_up']))},"
                    f"{_pct(_num(row['regime_ci95_high_up']))}]",
                    f"{_pct(_num(row['mean_down']))} "
                    f"[{_pct(_num(row['regime_ci95_low_down']))},"
                    f"{_pct(_num(row['regime_ci95_high_down']))}]",
                    _pct(_num(row["diff_up_minus_down"])),
                    f"{_pct(_num(row['positive_share_up']))} / "
                    f"{_pct(_num(row['positive_share_down']))}",
                    row["bar_met"],
                ])
            else:
                table_rows.append([
                    tag, row["indicator"], row["role"],
                    row["n_up_dates"], row["n_down_dates"],
                    f"{_pct(_num(row['mean_up']))} "
                    f"(t={_fmt(row['t_stat_up']) or 'n/a'})",
                    f"{_pct(_num(row['mean_down']))} "
                    f"(t={_fmt(row['t_stat_down']) or 'n/a'})",
                    _pct(_num(row["diff_up_minus_down"])),
                    row["bar_met"],
                ])
        if test == "T1":
            headers = ["sample / scope", "ind", "role", "n_up", "n_down",
                       "mean UP", "mean DOWN", "diff", "bar met"]
        elif test == "T2":
            headers = ["sample / scope", "ind", "role", "n_up", "n_down",
                       "mean delta UP [CI95]", "mean delta DOWN [CI95]",
                       "diff", "pos share UP/DOWN", "material"]
        else:
            headers = ["sample / scope", "ind", "role", "n_up", "n_down",
                       "gap UP (t)", "gap DOWN (t)", "diff", "material"]
        lines.append(_md_table(headers, table_rows))
        lines.append("")
        lines.append(note)
        lines.append("")

    lines.append("## 5. E4b go/no-go — drop-worst-date re-check detail")
    lines.append("")
    qualifying = verdict.get("qualifying_cells") or []
    if qualifying:
        lines.append(_md_table(
            ["cell", "full", "LOO-min", "LOO-max", "worst date dropped",
             "recomputed without worst", "sign kept"],
            [
                [
                    item["cell"], _pct(_num(item["full"])),
                    _pct(_num(item["loo_min"])), _pct(_num(item["loo_max"])),
                    item["worst_date"] or "-",
                    _pct(_num(item["recomputed"])),
                    item["sign_kept"],
                ]
                for item in qualifying
            ],
        ))
    else:
        lines.append(
            "No qualifying cells exist (T1 bar not met and T2/T3 not "
            "material), so the drop-worst-date check has nothing to keep."
        )
    lines.append("")
    lines.append(
        "Reminder (equal prominence for the stop path): the pre-registered "
        "spec states that if any gate fails, there is **no E4b follow-up** — "
        "a NO-GO closes this line of work rather than deferring it."
    )
    lines.append("")

    lines.append("## 6. R1 ±0.05 breadth-cutoff sensitivity (diagnostic only)")
    lines.append("")
    sens_rows = []
    for indicator in ("R1_SENS_LO", "R1_SENS_HI"):
        counts = label_counts[PRIMARY_SAMPLE].get(indicator, {})
        t1_row = next(
            (
                row for row in summary_rows
                if row["test"] == "T1"
                and row["indicator"] == indicator
                and row["sample"] == PRIMARY_SAMPLE
                and row["universe_scope"] == PRIMARY_SCOPE
            ),
            None,
        )
        sens_rows.append([
            indicator, _counts_row(counts),
            _pct(_num(t1_row["diff_up_minus_down"])) if t1_row else "n/a",
        ])
    lines.append(_md_table(
        ["indicator", "MERGED_51 label counts", "T1 diff (ETF_SLICE)"],
        sens_rows,
    ))
    lines.append("")
    lines.append(
        "Per spec, the ±0.05 variants are reported for transparency only: "
        "they cannot select the indicator and cannot trigger a go."
    )
    lines.append("")

    r1_merged_counts = label_counts[PRIMARY_SAMPLE].get("R1", {})
    r0_merged_counts = label_counts[PRIMARY_SAMPLE].get("R0", {})
    lines.append("## 7. Honest limitations")
    lines.append("")
    lines.append(
        f"- Merged sample is {context['n_merged_dates']} monthly dates "
        f"({base['dates']} base 2023-01..2026-03 / {bear['dates']} "
        f"bear-2022); the R1 primary split has "
        f"{r1_merged_counts.get(UPTREND, 0)} UPTREND / "
        f"{r1_merged_counts.get(DOWNTREND, 0)} DOWNTREND / "
        f"{r1_merged_counts.get(NEUTRAL, 0)} NEUTRAL dates "
        f"(status-quo R0 trailing-down dates: "
        f"{r0_merged_counts.get(DOWNTREND, 0)}). Regime cells are small and "
        "every aggregate is date-equal."
    )
    lines.append(
        "- Attack evidence base = a single bull regime (2023-01..2026-03); "
        "defense has two eras (2023-2026 dips + 2022 bear). Even a GO "
        "licenses only a pre-registered E4b with prospective/shadow "
        "evidence; retrospective results can never auto-promote."
    )
    lines.append(
        "- Merged-sequence vol_high warm-up: the first 6 merged dates "
        f"({', '.join(merged_sequence[:6])}) inherit vol_high=False by the "
        "min-6-prior-dates rule; the BASE_39-only sequence has its own "
        f"warm-up over its first 6 dates ({', '.join(base_sequence[:6])})."
    )
    lines.append(
        "- Forward labels (`fwd_ret_*`, `qqq_return_*`) are used strictly as "
        "scored outcomes in T1–T3; the indicator definitions never read "
        "them (firewall-tested)."
    )
    lines.append(
        "- Overlapping 60d label windows are not independent samples; "
        "LOO / sign-keep checks are robustness probes, not significance "
        "tests; the sample is small."
    )
    lines.append(
        "- Universe drift caveat inherited from both frozen datasets "
        "(union approximation; ETF_SLICE is the bias-reduced read)."
    )
    lines.append("")

    lines.append("## 8. Reproduction")
    lines.append("")
    lines.append(
        f"1. Delete `{context['out_dir_rel']}` and re-run the documented "
        "command below; outputs are deterministic (seed-stable bootstrap, "
        "chronological sort, no wall-clock use)."
    )
    lines.append(f"2. Command: `{context['command']}`")
    lines.append(
        "3. Verify every file against `SHA256SUMS` (this directory)."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File IO
# ---------------------------------------------------------------------------


def _csv_text(
    rows: Sequence[Mapping[str, Any]], columns: Sequence[str]
) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(raw: str | Path | None) -> str:
    """Repo-relative path when inside the repo, else basename (commit-safe)."""
    if raw is None:
        return ""
    path = Path(raw)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _reproduction_command(args: argparse.Namespace) -> str:
    parts = [
        "python", RUNNER_SCRIPT_REL,
        "--base-dataset", _portable_path(args.base_dataset),
        "--bear-2022-dataset", _portable_path(args.bear_2022_dataset),
        "--out-dir", _portable_path(args.out_dir),
    ]
    return " ".join(parts)


def write_outputs(out_dir: Path, files: Mapping[str, str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if contains_absolute_path(content):
            raise ValueError(f"absolute path leaked into {name}")
        (out_dir / name).write_text(content, encoding="utf-8")
    checksums = "".join(
        f"{_sha256_text(files[name])}  {name}\n" for name in sorted(files)
    )
    (out_dir / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    total = sum(path.stat().st_size for path in out_dir.iterdir())
    if total >= MAX_DIR_BYTES:
        raise ValueError(
            f"output directory exceeds {MAX_DIR_BYTES} bytes (got {total})"
        )
    return out_dir


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _load_dataset(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    if "signal_date" not in frame.columns or "symbol" not in frame.columns:
        raise ValueError(
            f"dataset missing signal_date/symbol: {Path(path).name}"
        )
    return frame


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_frame = _load_dataset(args.base_dataset)
    bear_frame = _load_dataset(args.bear_2022_dataset)
    n_base_dates = int(base_frame["signal_date"].nunique())
    n_bear_dates = int(bear_frame["signal_date"].nunique())
    validate_disjoint_dates({
        "base": sorted(base_frame["signal_date"].astype(str).unique()),
        "bear": sorted(bear_frame["signal_date"].astype(str).unique()),
    })
    print(
        f"[E4a] datasets: base={len(base_frame)}rows/{n_base_dates}dates, "
        f"bear={len(bear_frame)}rows/{n_bear_dates}dates",
        flush=True,
    )

    labels_bundle = compute_regime_labels(base_frame, bear_frame)
    merged_sequence = labels_bundle["merged_sequence"]
    base_sequence = labels_bundle["base_sequence"]
    bear_dates = sorted(labels_bundle["bear_stats"])
    r1_merged = labels_bundle["labels"]["R1"]
    merged_counts = count_labels(r1_merged, merged_sequence)
    bear_r1_up = [d for d in bear_dates if r1_merged.get(d) == UPTREND]
    print(
        f"[E4a] R1 merged labels: UP={merged_counts[UPTREND]} "
        f"DOWN={merged_counts[DOWNTREND]} NEUTRAL={merged_counts[NEUTRAL]}",
        flush=True,
    )
    print(
        f"[E4a] S0: R1 UPTREND dates in BEAR_2022 = {len(bear_r1_up)} "
        + (f"({', '.join(bear_r1_up)})" if bear_r1_up else "(clean)"),
        flush=True,
    )

    print(
        "[E4a] rebuilding decisions via shared build_scope_records "
        f"({n_base_dates + n_bear_dates} dates x {len(SCOPES)} scopes x "
        f"{len(VARIANTS)} variants) ...",
        flush=True,
    )
    dataset_records = rebuild_records({"base": base_frame, "bear": bear_frame})
    merged_records = merge_records(dataset_records, order=("bear", "base"))
    merged_dates = sorted(merged_records["FULL"]["v2_current"])
    base_dates = sorted(dataset_records["base"]["FULL"]["v2_current"])
    if len(merged_dates) != n_base_dates + n_bear_dates:
        raise ValueError(
            "merged record date count "
            f"{len(merged_dates)} != {n_base_dates + n_bear_dates}"
        )
    print(
        f"[E4a] records rebuilt: merged={len(merged_dates)} dates, "
        f"base-only={len(base_dates)} dates",
        flush=True,
    )

    sample_defs: dict[str, dict[str, Any]] = {
        PRIMARY_SAMPLE: {
            "dates": merged_dates,
            "records": merged_records,
            "indicator_order": MERGED_INDICATORS,
            "label_maps": {
                indicator: labels_bundle["labels"][indicator]
                for indicator in MERGED_INDICATORS
            },
        },
        "BASE_39_ONLY": {
            "dates": base_dates,
            "records": dataset_records["base"],
            "indicator_order": CONTEXT_INDICATORS,
            "label_maps": {
                "R0": labels_bundle["labels"]["R0"],
                "R1": labels_bundle["labels"]["R1_BASE_ONLY"],
                "R2": labels_bundle["labels"]["R2"],
            },
        },
    }

    cell_results: dict[tuple[str, str, str], dict[str, Any]] = {}
    summary_rows: list[dict[str, Any]] = []
    for sample_name in SAMPLES:
        spec = sample_defs[sample_name]
        for scope in SCOPES:
            for indicator in spec["indicator_order"]:
                label_map = spec["label_maps"][indicator]
                cells = compute_indicator_tests(
                    spec["records"], spec["dates"], label_map
                )
                cell = cells[scope]
                cell_results[(sample_name, scope, indicator)] = cell
                for test in ("T1", "T2", "T3"):
                    summary_rows.append(_summary_row(
                        sample_name, scope, indicator,
                        INDICATOR_ROLES[indicator], cell[test],
                    ))
                print(
                    f"[E4a]   {sample_name}|{scope}|{indicator}: "
                    f"T1 diff={_fmt(cell['T1']['diff'])} "
                    f"(bar={cell['T1']['bar_met']}), "
                    f"T2 material={cell['T2']['bar_met']}, "
                    f"T3 material={cell['T3']['bar_met']}",
                    flush=True,
                )

    bear_label_maps = {
        "R0": labels_bundle["labels"]["R0"],
        "R1": labels_bundle["labels"]["R1"],
        "R2": labels_bundle["labels"]["R2"],
    }
    for indicator, label_map in bear_label_maps.items():
        counts = count_labels(label_map, bear_dates)
        summary_rows.append({
            "sample": PRIMARY_SAMPLE,
            "universe_scope": "BEAR_2022",
            "indicator": indicator,
            "role": INDICATOR_ROLES[indicator],
            "test": "S0",
            "metric": "bear_2022_uptrend_date_count",
            "n_up_dates": counts[UPTREND],
            "n_down_dates": counts[DOWNTREND],
            "bar_met": counts[UPTREND] == 0,
        })

    tier_rows: list[dict[str, Any]] = []
    for sample_name in SAMPLES:
        spec = sample_defs[sample_name]
        for indicator in CONTEXT_INDICATORS:
            tier_rows.extend(build_tier_rows(
                spec["records"], sample_name, spec["dates"],
                spec["label_maps"][indicator], indicator,
            ))
    per_date_rows = build_per_date_rows(labels_bundle)

    verdict = evaluate_e4b_go(
        bear_uptrend_dates=bear_r1_up,
        t1=cell_results[(PRIMARY_SAMPLE, PRIMARY_SCOPE, PRIMARY_INDICATOR)]["T1"],
        t2=cell_results[(PRIMARY_SAMPLE, PRIMARY_SCOPE, PRIMARY_INDICATOR)]["T2"],
        t3=cell_results[(PRIMARY_SAMPLE, PRIMARY_SCOPE, PRIMARY_INDICATOR)]["T3"],
    )
    print(
        f"[E4a] verdict: {verdict['verdict']}"
        + (f" — {verdict['fail_reasons']}" if verdict["fail_reasons"] else ""),
        flush=True,
    )

    label_counts = {
        sample_name: {
            indicator: count_labels(
                sample_defs[sample_name]["label_maps"][indicator],
                sample_defs[sample_name]["dates"],
            )
            for indicator in sample_defs[sample_name]["indicator_order"]
        }
        for sample_name in SAMPLES
    }
    context = {
        "spec_rel": SPEC_REL,
        "runner_rel": RUNNER_SCRIPT_REL,
        "runner_sha": _sha256_file(REPO_ROOT / RUNNER_SCRIPT_REL) or "",
        "command": _reproduction_command(args),
        "base": {
            "name": Path(args.base_dataset).name,
            "rows": int(len(base_frame)),
            "dates": n_base_dates,
            "sha": _sha256_file(Path(args.base_dataset)) or "",
        },
        "bear": {
            "name": Path(args.bear_2022_dataset).name,
            "rows": int(len(bear_frame)),
            "dates": n_bear_dates,
            "sha": _sha256_file(Path(args.bear_2022_dataset)) or "",
        },
        "n_merged_dates": len(merged_dates),
        "merged_sequence": merged_sequence,
        "base_sequence": base_sequence,
        "summary_rows": summary_rows,
        "verdict": verdict,
        "label_counts": label_counts,
        "out_dir_rel": _portable_path(args.out_dir),
    }
    files = {
        "separation_summary.csv": _csv_text(summary_rows, SUMMARY_COLUMNS),
        "per_date_regimes.csv": _csv_text(per_date_rows, PER_DATE_COLUMNS),
        "tier_by_regime.csv": _csv_text(tier_rows, TIER_COLUMNS),
        "report.md": render_report(context),
    }
    out_dir = write_outputs(Path(args.out_dir), files)
    total = sum(path.stat().st_size for path in out_dir.iterdir())
    print(
        f"[E4a] wrote {len(files) + 1} files, {total} bytes to {out_dir.name}",
        flush=True,
    )
    return {
        "verdict": verdict["verdict"],
        "gates": {gate["id"]: gate["pass"] for gate in verdict["gates"]},
        "sample_dates": {
            "merged": len(merged_dates), "base_only": len(base_dates),
        },
        "s0_bear_uptrend_dates": bear_r1_up,
        "output_dir": str(out_dir),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "E4a trailing regime-indicator separation audit (diagnostic "
            "only; offline, deterministic, read-only)."
        )
    )
    parser.add_argument("--base-dataset", required=True)
    parser.add_argument("--bear-2022-dataset", required=True)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
