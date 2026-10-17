#!/usr/bin/env python3
"""Extended replay evaluation: forward-drawdown attribution & 2022 bear replay.

Offline, deterministic, read-only evaluation runner (zero network calls).

Route A: on the frozen 39-date dataset (2023-01..2026-03) it rebuilds the
production ``build_stock_decisions`` v1/v2 rankings per signal date for both
the Full Universe (``FULL``) and the bias-reduced ETF slice
(``ETF_SLICE``: ``watchlist_etf_count >= 1``), then quantifies cohort
economics, paired v2-vs-v1 deltas, rank-tier excess returns, and
entry/extension crosscuts across trailing-regime and forward-regime
segments (including ``FWD_DRAWDOWN_60D``: ``qqq_return_60 < 0``).

Route B: when ``--bear-2022-dataset`` (2022 tech bear market) and/or
``--extension-dataset`` are provided, the same evaluation is stitched
across datasets (signal-date overlap is rejected) with ``BEAR_2022``,
``BEAR_2022_FWD_DRAWDOWN_60D`` and ``COMBINED_DRAWDOWN_60D`` segments.

Outputs (``--output-dir``): ``cohort_economics_by_regime.csv``,
``paired_deltas_by_regime.csv``, ``rank_tiers_by_regime.csv``,
``entry_and_extension_crosscut.csv``, ``report.md`` and ``SHA256SUMS`` —
deterministic, zero absolute paths, total size < 140 KB.

Example:
    .venv/bin/python scripts/run_extended_replay_evaluation.py \
      --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
      --base-reference-dir outputs/m4_revalidation_current_20261016 \
      --output-dir docs/drawdown_and_bear_replay_20261017
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.research.m4_paired_validation import (
    contains_absolute_path,
    paired_delta_stats,
)

MAX_DIR_BYTES = 160 * 1024
REPRODUCTION_TOLERANCE = 1e-5
RUNNER_SCRIPT_REL = "scripts/run_extended_replay_evaluation.py"
CONTAINER_PATH_PREFIX_RE = re.compile(r"/(?:root|home|tmp)/")
HORIZONS: tuple[int, ...] = (20, 60, 120)
UNIVERSE_SCOPES: tuple[str, ...] = ("FULL", "ETF_SLICE")
VARIANTS: tuple[str, ...] = ("v1_current", "v2_current")
POLICY_BY_VARIANT: dict[str, str] = {"v1_current": "v1", "v2_current": "v2"}
COHORTS: tuple[str, ...] = (
    "TOP5", "TOP15", "PRIORITY_REVIEW", "QUALITY_A", "ENTRY_READY", "UNIVERSE",
)
PAIRED_COHORTS: tuple[str, ...] = ("TOP5", "TOP15", "PRIORITY_REVIEW", "QUALITY_A")
RANK_TIERS: tuple[tuple[str, int, int | None], ...] = (
    ("1-5", 1, 5), ("6-15", 6, 15), ("16-30", 16, 30),
    ("31-50", 31, 50), ("51-100", 51, 100), ("101+", 101, None),
    ("universe", 1, None),
)
ENTRY_STATES: tuple[str, ...] = (
    "ENTRY_READY", "WATCH_PULLBACK", "WATCH_BREAKOUT",
    "TREND_DAMAGED", "INSUFFICIENT_DATA",
)
SMA200_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<1.00x", None, 1.00),
    ("1.00-1.25x", 1.00, 1.25),
    ("1.25-1.35x", 1.25, 1.35),
    ("1.35-1.45x", 1.35, 1.45),
    (">1.45x", 1.45, None),
)
QUALITY_GRADES: tuple[str, ...] = ("A", "B", "C", "UNRATED")
GRADE_SCOPES: tuple[str, ...] = ("all_grades", "grade_A_only")
SEVERE_LOSS_THRESHOLD = -0.20

COHORT_COLUMNS: tuple[str, ...] = (
    "universe_scope", "segment", "variant", "cohort",
    "n_dates_20", "n_dates_60", "n_dates_120", "obs_60",
    "mean_excess_20", "mean_excess_60", "median_excess_60",
    "worst_date_excess_60", "mean_excess_120", "win_rate_vs_qqq_60",
    "mean_raw_ret_60", "severe_loss_rate_60", "severe_underperform_rate_60",
)
PAIRED_COLUMNS: tuple[str, ...] = (
    "universe_scope", "segment", "cohort", "horizon",
    "n_paired_dates", "mean_delta", "median_delta", "ci_low", "ci_high",
    "loo_min", "positive_date_share", "mean_severe_loss_delta_60",
)
TIER_COLUMNS: tuple[str, ...] = (
    "universe_scope", "segment", "tier", "n_dates_60", "obs_60",
    "mean_excess_20", "mean_excess_60", "median_excess_60",
    "diff_vs_universe_60", "win_rate_vs_qqq_60", "mean_raw_ret_60",
    "severe_loss_rate_60",
)
CROSSCUT_COLUMNS: tuple[str, ...] = (
    "universe_scope", "segment", "cut_type", "bucket", "n_dates_60", "obs_60",
    "mean_excess_20", "mean_excess_60", "median_excess_60",
    "mean_raw_ret_60", "severe_loss_rate_60",
)

REFERENCE_SEGMENT_TO_PERIOD: dict[str, str] = {
    "DEV_2023_2024": "DEV_2023_2024",
    "POST_2025_2026Q1": "POST2024_HELD_OUT",
    "BASE_ALL_39": "ALL_39_DATES",
}
REFERENCE_COMPARE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("n_dates_60", "n_dates_60"),
    ("obs_60", "obs_60"),
    ("mean_excess_60", "mean_excess_60"),
    ("median_excess_60", "median_excess_60"),
    ("worst_date_excess_60", "worst_excess_60"),
    ("mean_excess_20", "mean_excess_20"),
    ("mean_excess_120", "mean_excess_120"),
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


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_date_means(values: Iterable[Any]) -> dict[str, Any]:
    """mean / median / worst over per-date means (None entries skipped)."""
    ordered = sorted(float(v) for v in values if _num(v) is not None)
    n = len(ordered)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "worst": None}
    median = (
        ordered[n // 2] if n % 2
        else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
    )
    return {"n": n, "mean": sum(ordered) / n, "median": median, "worst": ordered[0]}


# ---------------------------------------------------------------------------
# Dataset / segment partitioning
# ---------------------------------------------------------------------------


def dataset_date_meta(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Per-date market context: forward QQQ returns, label ends, trailing regime."""
    meta: dict[str, dict[str, Any]] = {}
    if frame is None or frame.empty:
        return meta
    for date, group in frame.groupby("signal_date", sort=True):
        qqq60 = None
        qqq20 = None
        qqq120 = None
        label_end_60 = None
        regime = ""
        for record in group.to_dict(orient="records"):
            if qqq60 is None:
                qqq60 = _num(record.get("qqq_return_60"))
            if qqq20 is None:
                qqq20 = _num(record.get("qqq_return_20"))
            if qqq120 is None:
                qqq120 = _num(record.get("qqq_return_120"))
            if label_end_60 is None:
                token = str(record.get("qqq_label_end_60") or "").strip()
                if token and token.lower() != "nan":
                    label_end_60 = token[:10]
            token = str(record.get("regime") or "").strip().lower()
            if token and not regime:
                regime = token
        meta[str(date)] = {
            "qqq_return_60": qqq60,
            "qqq_return_20": qqq20,
            "qqq_return_120": qqq120,
            "qqq_label_end_60": label_end_60,
            "regime": regime,
        }
    return meta


def validate_disjoint_dates(
    datasets: Mapping[str, Sequence[str]],
) -> None:
    """Reject overlapping signal_date values across stitched datasets."""
    seen: dict[str, str] = {}
    for name, dates in datasets.items():
        for date in dates:
            token = str(date)
            if token in seen:
                raise ValueError(
                    f"overlapping signal_date {token!r} between datasets "
                    f"{seen[token]!r} and {name!r}"
                )
            seen[token] = name


def build_segments(
    base_meta: Mapping[str, Mapping[str, Any]],
    bear_meta: Mapping[str, Mapping[str, Any]] | None = None,
    ext_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """Named date segments per spec 3.3 (disjoint datasets, no dedup needed)."""
    base_dates = sorted(str(d) for d in base_meta)
    segments: dict[str, list[str]] = {}
    segments["BASE_ALL_39"] = base_dates
    segments["DEV_2023_2024"] = [d for d in base_dates if d <= "2024-12-31"]
    segments["POST_2025_2026Q1"] = [
        d for d in base_dates if "2025-01-01" <= d <= "2026-03-31"
    ]
    segments["FWD_DRAWDOWN_60D"] = [
        d for d in base_dates
        if base_meta[d].get("qqq_return_60") is not None
        and base_meta[d]["qqq_return_60"] < 0.0
    ]
    segments["FWD_BULL_60D"] = [
        d for d in base_dates
        if base_meta[d].get("qqq_return_60") is not None
        and base_meta[d]["qqq_return_60"] >= 0.0
    ]
    segments["FWD_DRAWDOWN_20D"] = [
        d for d in base_dates
        if base_meta[d].get("qqq_return_20") is not None
        and base_meta[d]["qqq_return_20"] < 0.0
    ]
    segments["FWD_BULL_20D"] = [
        d for d in base_dates
        if base_meta[d].get("qqq_return_20") is not None
        and base_meta[d]["qqq_return_20"] >= 0.0
    ]
    segments["TRAILING_DOWN"] = [
        d for d in base_dates if base_meta[d].get("regime") == "down"
    ]
    segments["TRAILING_UP"] = [
        d for d in base_dates if base_meta[d].get("regime") == "up"
    ]
    if bear_meta is not None:
        bear_dates = sorted(str(d) for d in bear_meta)
        segments["BEAR_2022"] = bear_dates
        segments["BEAR_2022_FWD_DRAWDOWN_60D"] = [
            d for d in bear_dates
            if bear_meta[d].get("qqq_return_60") is not None
            and bear_meta[d]["qqq_return_60"] < 0.0
        ]
        segments["COMBINED_DRAWDOWN_60D"] = sorted(
            segments["BEAR_2022_FWD_DRAWDOWN_60D"]
            + segments["FWD_DRAWDOWN_60D"]
        )
    if ext_meta is not None:
        ext_dates = sorted(str(d) for d in ext_meta)
        segments["EXT_2026H1"] = [
            d for d in ext_dates if "2026-04-01" <= d <= "2026-06-30"
        ]
        segments["EXT_2026H2"] = [
            d for d in ext_dates if "2026-07-01" <= d <= "2026-09-30"
        ]
        segments["EXT_PIT_20260930"] = [
            d for d in ext_dates if d == "2026-09-30"
        ]
    return segments


# ---------------------------------------------------------------------------
# Frozen-grade provenance helpers (spec section 6)
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_path_strings(value: Any) -> Any:
    """Recursively strip container prefixes (/root/, /home/, /tmp/) from strings."""
    if isinstance(value, str):
        return CONTAINER_PATH_PREFIX_RE.sub("", value)
    if isinstance(value, Mapping):
        return {
            key: _sanitize_path_strings(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_path_strings(item) for item in value]
    return value


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
    ]
    if args.bear_2022_dataset:
        parts += ["--bear-2022-dataset", _portable_path(args.bear_2022_dataset)]
    if args.extension_dataset:
        parts += ["--extension-dataset", _portable_path(args.extension_dataset)]
    parts += [
        "--base-reference-dir", _portable_path(args.base_reference_dir),
        "--output-dir", _portable_path(args.output_dir),
    ]
    return " ".join(parts)


def forward_window_overlaps(
    dates: Sequence[str],
    meta: Mapping[str, Mapping[str, Any]],
) -> dict[str, bool]:
    """Per-date flag: signal_date < previous date's 60d label end (in this list)."""
    ordered = sorted(str(date) for date in dates)
    overlaps: dict[str, bool] = {}
    previous_label_end: str | None = None
    for date in ordered:
        overlaps[date] = bool(previous_label_end and date < previous_label_end)
        label_end = meta.get(date, {}).get("qqq_label_end_60")
        if label_end:
            previous_label_end = str(label_end)[:10]
    return overlaps


_CANONICAL_EPISODE_NAMES: dict[str, str] = {
    "2023-06-30": "EP1_2023Q3",
    "2024-11-29": "EP2_2024Q4_2025Q1",
    "2025-10-31": "EP3_2025Q4",
}


def _episode_cluster_name(index: int, start_date: str) -> str:
    canonical = _CANONICAL_EPISODE_NAMES.get(start_date)
    if canonical:
        return canonical
    try:
        year, month = start_date[:4], int(start_date[5:7])
        quarter = (month - 1) // 3 + 1
        return f"EP{index}_{year}Q{quarter}"
    except (TypeError, ValueError):
        return f"EP{index}"


def assign_episode_clusters(
    dates: Sequence[str],
    meta: Mapping[str, Mapping[str, Any]],
    *,
    bear: bool = False,
) -> tuple[dict[str, str], list[tuple[str, list[str]]]]:
    """Assign overlap-contiguous 60d-window episode clusters to drawdown dates.

    Returns (date -> cluster name, ordered [(cluster name, dates)]). Bear-2022
    negative-60d dates form a single ``EP0_BEAR_2022`` episode regardless of
    overlap contiguity (they are one bear market).
    """
    ordered = sorted(str(date) for date in dates)
    if bear:
        return (
            {date: "EP0_BEAR_2022" for date in ordered},
            [("EP0_BEAR_2022", ordered)] if ordered else [],
        )
    clusters: list[list[str]] = []
    current: list[str] = []
    previous_label_end: str | None = None
    for date in ordered:
        overlaps = bool(
            current and previous_label_end and date < previous_label_end
        )
        if overlaps:
            current.append(date)
        else:
            if current:
                clusters.append(current)
            current = [date]
        label_end = meta.get(date, {}).get("qqq_label_end_60")
        if label_end:
            previous_label_end = str(label_end)[:10]
    if current:
        clusters.append(current)
    mapping: dict[str, str] = {}
    episode_list: list[tuple[str, list[str]]] = []
    for index, cluster in enumerate(clusters, start=1):
        name = _episode_cluster_name(index, cluster[0])
        for date in cluster:
            mapping[date] = name
        episode_list.append((name, cluster))
    return mapping, episode_list


EPISODE_COHORTS: tuple[str, ...] = (
    "TOP15", "PRIORITY_REVIEW", "QUALITY_A", "UNIVERSE",
)


def compute_episode_cluster_summary(
    records: Mapping[str, Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]],
    episodes: Sequence[tuple[str, Sequence[str]]],
    *,
    fwd_episode_names: Sequence[str],
    all_episode_names: Sequence[str],
    date_equal_segment: str = "FWD_DRAWDOWN_60D",
) -> dict[str, Any]:
    """Per-episode and cluster-equal metrics for the drawdown episode table.

    Cluster-equal mean = equal weight over episode means (not over dates), so
    overlapping 60d windows inside an episode cannot dominate the aggregate.
    """
    rows: list[dict[str, Any]] = []
    for scope in UNIVERSE_SCOPES:
        for variant in VARIANTS:
            for cohort in EPISODE_COHORTS:
                member_fn = (
                    lambda record, c=cohort: cohort_member(record, c)
                )
                episode_values: dict[str, dict[str, Any]] = {}
                for name, dates in episodes:
                    summary = segment_cohort_summary(
                        records[scope][variant], dates, member_fn)
                    episode_values[name] = {
                        "mean_excess_60": summary["mean_excess_60"],
                        "severe_loss_rate_60": summary[
                            "severe_loss_rate_60"],
                        "n_dates_60": summary["n_dates_60"],
                    }
                fwd_mean = _mean([
                    episode_values[name]["mean_excess_60"]
                    for name in fwd_episode_names
                    if episode_values.get(name, {}).get("mean_excess_60")
                    is not None
                ])
                all_mean = _mean([
                    episode_values[name]["mean_excess_60"]
                    for name in all_episode_names
                    if episode_values.get(name, {}).get("mean_excess_60")
                    is not None
                ])
                fwd_severe = _mean([
                    episode_values[name]["severe_loss_rate_60"]
                    for name in fwd_episode_names
                    if episode_values.get(name, {}).get(
                        "severe_loss_rate_60") is not None
                ])
                all_severe = _mean([
                    episode_values[name]["severe_loss_rate_60"]
                    for name in all_episode_names
                    if episode_values.get(name, {}).get(
                        "severe_loss_rate_60") is not None
                ])
                rows.append({
                    "universe_scope": scope,
                    "cohort": cohort,
                    "variant": variant,
                    "episode_values": episode_values,
                    "fwd_drawdown_episode_equal_mean_excess_60": fwd_mean,
                    "all_drawdown_episode_equal_mean_excess_60": all_mean,
                    "fwd_drawdown_episode_equal_severe_loss_60": fwd_severe,
                    "all_drawdown_episode_equal_severe_loss_60": all_severe,
                })
    date_equal: dict[str, Any] = {}
    fwd_dates = [
        date for name, dates in episodes
        if name in fwd_episode_names for date in dates
    ]
    for scope in UNIVERSE_SCOPES:
        for variant in VARIANTS:
            for cohort in EPISODE_COHORTS:
                member_fn = (
                    lambda record, c=cohort: cohort_member(record, c)
                )
                summary = segment_cohort_summary(
                    records[scope][variant], fwd_dates, member_fn)
                date_equal[f"{scope}|{variant}|{cohort}"] = {
                    "mean_excess_60": summary["mean_excess_60"],
                    "severe_loss_rate_60": summary["severe_loss_rate_60"],
                }
    return {
        "episodes": [
            {"name": name, "dates": list(dates)} for name, dates in episodes
        ],
        "fwd_episode_names": list(fwd_episode_names),
        "all_episode_names": list(all_episode_names),
        "rows": rows,
        "date_equal": date_equal,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def discover_bear_artifacts(
    bear_dataset_path: str | Path,
    *,
    meta_json: str | None = None,
    success_json: str | None = None,
    discontinuities_csv: str | None = None,
) -> dict[str, Path | None]:
    """Locate sibling/parent Modal & repair artifacts for the 2022 dataset."""
    bear_path = Path(bear_dataset_path)
    bear_dir = bear_path.parent
    run_root = bear_dir.parent

    def _first(candidates: Sequence[Path]) -> Path | None:
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    modal_names = {
        "meta": "company_quality_dataset_risk_off.meta.json",
        "success": "company_quality_dataset_risk_off.SUCCESS.json",
        "splits": "company_quality_dataset_risk_off.splits.json",
        "raw_csv": "company_quality_dataset_risk_off.csv",
    }
    artifacts: dict[str, Path | None] = {}
    for key, name in modal_names.items():
        artifacts[key] = _first([
            run_root / "modal_download" / "datasets" / name,
            bear_dir / "modal_download" / "datasets" / name,
            bear_dir / name,
        ])
    artifacts["meta"] = Path(meta_json) if meta_json else artifacts["meta"]
    artifacts["success"] = (
        Path(success_json) if success_json else artifacts["success"]
    )
    artifacts["discontinuities"] = (
        Path(discontinuities_csv) if discontinuities_csv
        else _first([
            bear_dir / "company_quality_discontinuities.csv",
            run_root / "repaired" / "company_quality_discontinuities.csv",
        ])
    )
    artifacts["frozen_watchlist"] = _first([
        run_root / "frozen_inputs" / "ai_watchlist.csv",
        bear_dir / "frozen_inputs" / "ai_watchlist.csv",
    ])
    artifacts["frozen_config"] = _first([
        run_root / "frozen_inputs" / "config.risk_off.json",
        bear_dir / "frozen_inputs" / "config.risk_off.json",
    ])
    return artifacts


def build_bear_2022_provenance(
    bear_frame: pd.DataFrame,
    bear_dataset_path: str | Path,
    artifacts: Mapping[str, Path | None],
) -> dict[str, Any]:
    """Commit-safe 2022 Modal extraction + split-repair provenance payload."""
    success = _read_json(artifacts["success"]) if artifacts.get("success") else None
    meta = _read_json(artifacts["meta"]) if artifacts.get("meta") else None
    spec = (success or {}).get("spec") or {}
    meta = meta or {}
    discontinuities_rows: int | None = None
    discontinuities_flagged: int | None = None
    discontinuities_path = artifacts.get("discontinuities")
    if discontinuities_path and discontinuities_path.exists():
        try:
            disc_frame = pd.read_csv(discontinuities_path)
            discontinuities_rows = int(len(disc_frame))
            if "null_labels" in disc_frame.columns:
                flagged = (
                    disc_frame["null_labels"].astype(str).str.lower()
                    .isin({"true", "1", "yes"})
                )
                discontinuities_flagged = int(flagged.sum())
        except (OSError, ValueError):
            pass
    provenance = {
        "run_id": spec.get("run_id"),
        "code_sha": spec.get("code_sha"),
        "generated_utc": meta.get("generated_utc"),
        "start_date": spec.get("start_date") or meta.get("start_date"),
        "end_date": spec.get("end_date") or meta.get("end_date"),
        "style": spec.get("style") or meta.get("style"),
        "dataset_kind": spec.get("dataset_kind") or meta.get("dataset_kind"),
        "pre_snapshot_universe": meta.get("pre_snapshot_universe"),
        "allow_latest_watchlist_fallback": meta.get(
            "allow_latest_watchlist_fallback"),
        "n_dates": int(bear_frame["signal_date"].nunique()),
        "n_rows": int(len(bear_frame)),
        "n_unique_symbols": int(bear_frame["symbol"].nunique()),
        "discontinuities_rows": discontinuities_rows,
        "discontinuities_flagged": discontinuities_flagged,
        "sha256": {
            "raw_extract_csv": _sha256_file(artifacts["raw_csv"])
            if artifacts.get("raw_csv") else None,
            "splits_json": _sha256_file(artifacts["splits"])
            if artifacts.get("splits") else None,
            "repaired_csv": _sha256_file(Path(bear_dataset_path)),
            "discontinuities_csv": _sha256_file(discontinuities_path)
            if discontinuities_path else None,
            "frozen_watchlist_csv": _sha256_file(artifacts["frozen_watchlist"])
            if artifacts.get("frozen_watchlist") else None,
            "frozen_config_json": _sha256_file(artifacts["frozen_config"])
            if artifacts.get("frozen_config") else None,
        },
        "meta_summary": meta,
    }
    return _sanitize_path_strings(provenance)


# ---------------------------------------------------------------------------
# Record building (production rebuild per date/scope/variant)
# ---------------------------------------------------------------------------


def _slice_frame(frame: pd.DataFrame) -> pd.DataFrame:
    counts = pd.to_numeric(
        frame.get("watchlist_etf_count"), errors="coerce"
    ).fillna(0)
    return frame[counts >= 1]


def build_scope_records(
    group: pd.DataFrame,
    scope: str,
    variant: str,
    signal_date: str,
) -> list[dict[str, Any]]:
    """Rebuild canonical decisions for one date/scope/variant and attach labels."""
    frame = group if scope == "FULL" else _slice_frame(group)
    if frame.empty:
        return []
    decisions = build_stock_decisions(
        frame,
        decision_date=str(signal_date),
        generated_at_utc=f"{signal_date}T00:00:00Z",
        policy_version=POLICY_BY_VARIANT[variant],
    )
    lookup: dict[str, Any] = {}
    for decision in decisions:
        lookup[str(decision.symbol).strip().upper()] = decision
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        symbol = str(row.get("symbol") or "").strip().upper()
        decision = lookup.get(symbol)
        if decision is None or not symbol:
            continue
        record: dict[str, Any] = {
            "symbol": symbol,
            "priority": int(decision.priority),
            "action_state": decision.action_state.value,
            "grade": decision.quality.grade.value,
            "entry_state": decision.entry.state.value,
            "price_to_sma200": _num(row.get("price_to_sma200")),
        }
        for horizon in HORIZONS:
            fwd = _num(row.get(f"fwd_ret_{horizon}"))
            qqq = _num(row.get(f"qqq_return_{horizon}"))
            record[f"fwd_ret_{horizon}"] = fwd
            record[f"excess_{horizon}"] = (
                fwd - qqq if fwd is not None and qqq is not None else None
            )
        records.append(record)
    return records


def cohort_member(record: Mapping[str, Any], cohort: str) -> bool:
    if cohort == "TOP5":
        return record["priority"] <= 5
    if cohort == "TOP15":
        return record["priority"] <= 15
    if cohort == "PRIORITY_REVIEW":
        return record["action_state"] == "PRIORITY_REVIEW"
    if cohort == "QUALITY_A":
        return record["grade"] == "A"
    if cohort == "ENTRY_READY":
        return record["entry_state"] == "ENTRY_READY"
    if cohort == "UNIVERSE":
        return True
    raise ValueError(f"unknown cohort={cohort!r}")


def tier_member(record: Mapping[str, Any], low: int, high: int | None) -> bool:
    priority = int(record["priority"])
    if priority < low:
        return False
    return high is None or priority <= high


def sma200_bucket_match(
    value: float | None, low: float | None, high: float | None
) -> bool:
    """Bucket semantics: `<v`, `low <= value < high`, or `> low` for the last."""
    if value is None:
        return False
    if low is None:
        return value < float(high)
    if high is None:
        return value > low
    return low <= value < high


# ---------------------------------------------------------------------------
# Aggregation primitives
# ---------------------------------------------------------------------------


def date_metric_means(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    member_fn: Callable[[Mapping[str, Any]], bool],
    key: str,
) -> tuple[dict[str, float], int]:
    """Per-date means over members with a finite ``key`` value + total obs."""
    means: dict[str, float] = {}
    total_obs = 0
    for date in dates:
        values = [
            float(record[key])
            for record in records_by_date.get(date, ())
            if member_fn(record) and _num(record.get(key)) is not None
        ]
        if values:
            means[date] = sum(values) / len(values)
            total_obs += len(values)
    return means, total_obs


def date_share_series(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    member_fn: Callable[[Mapping[str, Any]], bool],
    key: str,
    predicate: Callable[[Mapping[str, Any]], bool],
) -> dict[str, float]:
    """Per-date share of members (with finite ``key``) satisfying predicate."""
    shares: dict[str, float] = {}
    for date in dates:
        members = [
            record
            for record in records_by_date.get(date, ())
            if member_fn(record) and _num(record.get(key)) is not None
        ]
        if members:
            shares[date] = (
                sum(1 for record in members if predicate(record)) / len(members)
            )
    return shares


def segment_cohort_summary(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    member_fn: Callable[[Mapping[str, Any]], bool],
) -> dict[str, Any]:
    """All cohort/tier/crosscut metrics for one segment membership set."""
    summary: dict[str, Any] = {}
    for horizon in HORIZONS:
        means, obs = date_metric_means(
            records_by_date, dates, member_fn, f"excess_{horizon}"
        )
        stats = summarize_date_means(means.values())
        summary[f"n_dates_{horizon}"] = stats["n"]
        summary[f"obs_{horizon}"] = obs
        summary[f"mean_excess_{horizon}"] = stats["mean"]
        summary[f"date_means_excess_{horizon}"] = means
        if horizon == 60:
            summary["median_excess_60"] = stats["median"]
            summary["worst_date_excess_60"] = stats["worst"]
            summary["win_rate_vs_qqq_60"] = (
                sum(1 for value in means.values() if value > 0.0) / len(means)
                if means else None
            )
    raw_means, _ = date_metric_means(
        records_by_date, dates, member_fn, "fwd_ret_60"
    )
    summary["mean_raw_ret_60"] = summarize_date_means(raw_means.values())["mean"]
    loss_shares = date_share_series(
        records_by_date, dates, member_fn, "fwd_ret_60",
        lambda record: float(record["fwd_ret_60"]) <= SEVERE_LOSS_THRESHOLD,
    )
    summary["severe_loss_rate_60"] = _mean(list(loss_shares.values()))
    under_shares = date_share_series(
        records_by_date, dates, member_fn, "excess_60",
        lambda record: float(record["excess_60"]) <= SEVERE_LOSS_THRESHOLD,
    )
    summary["severe_underperform_rate_60"] = _mean(list(under_shares.values()))
    return summary


# ---------------------------------------------------------------------------
# Output table builders
# ---------------------------------------------------------------------------


def build_cohort_rows(
    records: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    segments: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in UNIVERSE_SCOPES:
        for segment, dates in segments.items():
            for variant in VARIANTS:
                by_date = records[scope][variant]
                for cohort in COHORTS:
                    member_fn = (
                        lambda record, c=cohort: cohort_member(record, c)
                    )
                    summary = segment_cohort_summary(by_date, dates, member_fn)
                    rows.append({
                        "universe_scope": scope,
                        "segment": segment,
                        "variant": variant,
                        "cohort": cohort,
                        "n_dates_20": summary["n_dates_20"],
                        "n_dates_60": summary["n_dates_60"],
                        "n_dates_120": summary["n_dates_120"],
                        "obs_60": summary["obs_60"],
                        "mean_excess_20": _fmt(summary["mean_excess_20"]),
                        "mean_excess_60": _fmt(summary["mean_excess_60"]),
                        "median_excess_60": _fmt(summary["median_excess_60"]),
                        "worst_date_excess_60": _fmt(
                            summary["worst_date_excess_60"]),
                        "mean_excess_120": _fmt(summary["mean_excess_120"]),
                        "win_rate_vs_qqq_60": _fmt(summary["win_rate_vs_qqq_60"]),
                        "mean_raw_ret_60": _fmt(summary["mean_raw_ret_60"]),
                        "severe_loss_rate_60": _fmt(
                            summary["severe_loss_rate_60"]),
                        "severe_underperform_rate_60": _fmt(
                            summary["severe_underperform_rate_60"]),
                    })
    return rows


def build_paired_rows(
    records: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    segments: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in UNIVERSE_SCOPES:
        for segment, dates in segments.items():
            for cohort in PAIRED_COHORTS:
                member_fn = (
                    lambda record, c=cohort: cohort_member(record, c)
                )
                for horizon in HORIZONS:
                    v2_means, _ = date_metric_means(
                        records[scope]["v2_current"], dates, member_fn,
                        f"excess_{horizon}",
                    )
                    v1_means, _ = date_metric_means(
                        records[scope]["v1_current"], dates, member_fn,
                        f"excess_{horizon}",
                    )
                    stats = paired_delta_stats(v2_means, v1_means)
                    severe_delta = None
                    if horizon == 60:
                        v1_shares = date_share_series(
                            records[scope]["v1_current"], dates, member_fn,
                            "fwd_ret_60",
                            lambda record: (
                                float(record["fwd_ret_60"])
                                <= SEVERE_LOSS_THRESHOLD
                            ),
                        )
                        v2_shares = date_share_series(
                            records[scope]["v2_current"], dates, member_fn,
                            "fwd_ret_60",
                            lambda record: (
                                float(record["fwd_ret_60"])
                                <= SEVERE_LOSS_THRESHOLD
                            ),
                        )
                        shared = sorted(set(v1_shares) & set(v2_shares))
                        severe_delta = _mean(
                            [v2_shares[d] - v1_shares[d] for d in shared]
                        )
                    rows.append({
                        "universe_scope": scope,
                        "segment": segment,
                        "cohort": cohort,
                        "horizon": str(horizon),
                        "n_paired_dates": stats["n_paired_dates"],
                        "mean_delta": _fmt(stats["mean_paired_delta_60d"]),
                        "median_delta": _fmt(stats["median_paired_delta_60d"]),
                        "ci_low": _fmt(stats["ci95_low_60d"]),
                        "ci_high": _fmt(stats["ci95_high_60d"]),
                        "loo_min": _fmt(stats["loo_min_mean_delta_60d"]),
                        "positive_date_share": _fmt(
                            stats["positive_delta_date_share"]),
                        "mean_severe_loss_delta_60": _fmt(severe_delta),
                    })
    return rows


def build_tier_rows(
    records: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    segments: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    tier_segments = [
        "BASE_ALL_39", "FWD_BULL_60D", "FWD_DRAWDOWN_60D", "TRAILING_DOWN",
    ]
    for optional in ("BEAR_2022", "BEAR_2022_FWD_DRAWDOWN_60D",
                     "COMBINED_DRAWDOWN_60D"):
        if optional in segments:
            tier_segments.append(optional)
    rows: list[dict[str, Any]] = []
    for scope in UNIVERSE_SCOPES:
        by_date = records[scope]["v2_current"]
        for segment in tier_segments:
            dates = segments[segment]
            universe_summary = segment_cohort_summary(
                by_date, dates,
                lambda record: cohort_member(record, "UNIVERSE"),
            )
            universe_mean = universe_summary["mean_excess_60"]
            for label, low, high in RANK_TIERS:
                if label == "universe":
                    member_fn = lambda record: True
                else:
                    member_fn = (
                        lambda record, lo=low, hi=high: tier_member(
                            record, lo, hi)
                    )
                summary = segment_cohort_summary(by_date, dates, member_fn)
                diff = None
                if (
                    summary["mean_excess_60"] is not None
                    and universe_mean is not None
                ):
                    diff = summary["mean_excess_60"] - universe_mean
                rows.append({
                    "universe_scope": scope,
                    "segment": segment,
                    "tier": label,
                    "n_dates_60": summary["n_dates_60"],
                    "obs_60": summary["obs_60"],
                    "mean_excess_20": _fmt(summary["mean_excess_20"]),
                    "mean_excess_60": _fmt(summary["mean_excess_60"]),
                    "median_excess_60": _fmt(summary["median_excess_60"]),
                    "diff_vs_universe_60": _fmt(diff),
                    "win_rate_vs_qqq_60": _fmt(summary["win_rate_vs_qqq_60"]),
                    "mean_raw_ret_60": _fmt(summary["mean_raw_ret_60"]),
                    "severe_loss_rate_60": _fmt(summary["severe_loss_rate_60"]),
                })
    return rows


def build_crosscut_rows(
    records: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    segments: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    crosscut_segments = [
        "BASE_ALL_39", "FWD_BULL_60D", "FWD_DRAWDOWN_60D", "TRAILING_DOWN",
    ]
    if "BEAR_2022" in segments:
        crosscut_segments.append("BEAR_2022")
    rows: list[dict[str, Any]] = []
    for scope in UNIVERSE_SCOPES:
        by_date = records[scope]["v2_current"]
        for segment in crosscut_segments:
            dates = segments[segment]
            for grade_scope in GRADE_SCOPES:
                grade_ok = (
                    lambda record: (
                        grade_scope == "all_grades" or record["grade"] == "A"
                    )
                )
                for state in ENTRY_STATES:
                    member_fn = (
                        lambda record, s=state, g=grade_ok: (
                            record["entry_state"] == s and g(record)
                        )
                    )
                    rows.append(_crosscut_row(
                        scope, segment, "entry_state",
                        f"{state}|{grade_scope}",
                        segment_cohort_summary(by_date, dates, member_fn),
                    ))
                for label, low, high in SMA200_BUCKETS:
                    member_fn = (
                        lambda record, lo=low, hi=high, g=grade_ok: (
                            g(record)
                            and sma200_bucket_match(
                                record["price_to_sma200"], lo, hi)
                        )
                    )
                    rows.append(_crosscut_row(
                        scope, segment, "sma200_extension",
                        f"{label}|{grade_scope}",
                        segment_cohort_summary(by_date, dates, member_fn),
                    ))
            for grade in QUALITY_GRADES:
                member_fn = (
                    lambda record, gr=grade: record["grade"] == gr
                )
                rows.append(_crosscut_row(
                    scope, segment, "quality_grade", grade,
                    segment_cohort_summary(by_date, dates, member_fn),
                ))
    return rows


def _crosscut_row(
    scope: str,
    segment: str,
    cut_type: str,
    bucket: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "universe_scope": scope,
        "segment": segment,
        "cut_type": cut_type,
        "bucket": bucket,
        "n_dates_60": summary["n_dates_60"],
        "obs_60": summary["obs_60"],
        "mean_excess_20": _fmt(summary["mean_excess_20"]),
        "mean_excess_60": _fmt(summary["mean_excess_60"]),
        "median_excess_60": _fmt(summary["median_excess_60"]),
        "mean_raw_ret_60": _fmt(summary["mean_raw_ret_60"]),
        "severe_loss_rate_60": _fmt(summary["severe_loss_rate_60"]),
    }


# ---------------------------------------------------------------------------
# Reproduction check
# ---------------------------------------------------------------------------


def load_reference_rows(reference_path: Path) -> list[dict[str, str]]:
    if not reference_path.exists():
        return []
    try:
        frame = pd.read_csv(reference_path)
    except (OSError, ValueError):
        return []
    return [dict(row) for row in frame.to_dict(orient="records")]


def reproduction_check(
    cohort_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    tolerance: float = REPRODUCTION_TOLERANCE,
) -> dict[str, Any]:
    """Compare computed FULL v1_current cohort rows with the E0 reference.

    Only reference-keyed (period, variant, cohort) rows are compared; any
    extra computed cohorts (e.g. ``UNIVERSE``) are counted as skipped, not
    mismatches.
    """
    result: dict[str, Any] = {
        "status": "PASS",
        "n_checked": 0,
        "n_mismatches": 0,
        "n_skipped_extra": 0,
        "mismatches": [],
    }
    if not reference_rows:
        result["status"] = "MISSING_REFERENCE"
        return result
    reference_index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in reference_rows:
        reference_index[
            (str(row.get("period")), str(row.get("variant")), str(row.get("cohort")))
        ] = row
    for row in cohort_rows:
        if row.get("universe_scope") != "FULL":
            continue
        if row.get("variant") != "v1_current":
            continue
        reference_period = REFERENCE_SEGMENT_TO_PERIOD.get(
            str(row.get("segment")), None
        )
        if reference_period is None:
            continue
        reference_key = (
            reference_period, "v1_current", str(row.get("cohort"))
        )
        reference = reference_index.get(reference_key)
        if reference is None:
            result["n_skipped_extra"] += 1
            continue
        result["n_checked"] += 1
        for computed_key, reference_key in REFERENCE_COMPARE_COLUMNS:
            computed_value = row.get(computed_key)
            reference_value = reference.get(reference_key)
            if reference_key in {"n_dates_60", "obs_60"}:
                ok = int(computed_value) == int(float(reference_value))
            else:
                computed_num = _num(computed_value)
                reference_num = _num(reference_value)
                ok = (
                    computed_num is not None
                    and reference_num is not None
                    and abs(computed_num - reference_num) <= tolerance
                )
            if not ok:
                result["n_mismatches"] += 1
                result["mismatches"].append(
                    f"{reference_period}/{row.get('cohort')}/{computed_key}: "
                    f"computed={computed_value!r} reference={reference_value!r}"
                )
    if result["n_mismatches"]:
        result["status"] = "FAIL"
    elif result["n_checked"] == 0:
        result["status"] = "MISSING_REFERENCE"
    return result


# ---------------------------------------------------------------------------
# Report & file IO
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


def _pct(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:+.1f}%"


def render_report(
    *,
    base_dataset_name: str,
    n_base_rows: int,
    n_base_dates: int,
    segments: Mapping[str, Sequence[str]],
    cohort_rows: Sequence[Mapping[str, Any]],
    tier_rows: Sequence[Mapping[str, Any]],
    crosscut_rows: Sequence[Mapping[str, Any]],
    reproduction: Mapping[str, Any],
    base_meta: Mapping[str, Mapping[str, Any]],
    extra_datasets: Sequence[tuple[str, str, int, int]],
    frozen: Mapping[str, Any] | None = None,
) -> str:
    frozen = frozen or {}
    lines: list[str] = []
    lines.append("# Drawdown Protection & Bear-Market Replay Evaluation")
    lines.append("")
    lines.append(
        "Route A: forward-drawdown attribution on the frozen 39-date dataset "
        "(production `build_stock_decisions` v1/v2 rebuild per date, FULL vs "
        "ETF_SLICE scope). Route B: 2022 bear-market replay when provided."
    )
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Base dataset: `{base_dataset_name}` ({n_base_rows} rows, "
                 f"{n_base_dates} signal dates).")
    for name, label, n_rows, n_dates in extra_datasets:
        lines.append(f"- {label} dataset: `{name}` ({n_rows} rows, "
                     f"{n_dates} signal dates).")
    if frozen.get("runner_sha256"):
        lines.append(
            f"- Runner: `{RUNNER_SCRIPT_REL}` "
            f"SHA256 `{frozen['runner_sha256']}`."
        )
    if frozen.get("command"):
        lines.append(f"- Reproduction command: `{frozen['command']}`.")
    if frozen.get("base_sha256"):
        lines.append(
            f"- Base dataset SHA256: `{frozen['base_sha256']}`."
        )
    bear_frozen = frozen.get("bear") or {}
    if bear_frozen:
        lines.append(
            f"- 2022 bear dataset `{bear_frozen.get('filename', '')}` "
            f"({bear_frozen.get('n_rows', 'n/a')} rows, "
            f"{bear_frozen.get('n_dates', 'n/a')} signal dates) "
            f"SHA256 `{bear_frozen.get('sha256', 'n/a')}`."
        )
        lines.append(
            f"- 2022 Modal extraction: run_id `{bear_frozen.get('run_id')}`, "
            f"code_sha `{bear_frozen.get('code_sha')}`, generated_utc "
            f"`{bear_frozen.get('generated_utc')}`, raw_csv_sha256 "
            f"`{bear_frozen.get('raw_csv_sha256')}`, splits_json_sha256 "
            f"`{bear_frozen.get('splits_json_sha256')}`."
        )
        lines.append(
            f"- 2022 split-repair audit: discontinuities rows "
            f"{bear_frozen.get('discontinuities_rows')}, flagged "
            f"{bear_frozen.get('discontinuities_flagged')}; artifacts "
            "`bear_2022_provenance.json` + `bear_2022_discontinuities.csv`."
        )
    lines.append("- Securities addressed by CIK/ticker rename hygiene at "
                 "refresh time; universe snapshots are the documented "
                 "`union_superset_approx` approximation (AGENTS.md §4): the "
                 "current watchlist applied to all historical dates, not true "
                 "PIT ETF-constituent history; the ETF-slice (etf_count>=1) "
                 "cut is the bias-reduced read.")
    lines.append("- Retrospective replay only; no threshold/weight/policy "
                 "promotion implied (AGENTS.md §8).")
    lines.append("")
    lines.append("## 1. E0 baseline reproduction check")
    lines.append("")
    lines.append(
        f"Status: **{reproduction['status']}** "
        f"({reproduction['n_checked']} cohort rows checked vs "
        f"`e0_current_cohorts.csv` v1_current, tolerance "
        f"{REPRODUCTION_TOLERANCE:g})."
    )
    if reproduction["mismatches"]:
        lines.append("")
        for mismatch in reproduction["mismatches"][:10]:
            lines.append(f"- MISMATCH: {mismatch}")
    lines.append("")
    drawdown_dates = segments.get("FWD_DRAWDOWN_60D", [])
    qqq_values = [
        base_meta[d]["qqq_return_60"]
        for d in drawdown_dates
        if base_meta[d].get("qqq_return_60") is not None
    ]
    trailing_up = segments.get("TRAILING_DOWN", [])
    trailing_next_qqq = [
        base_meta[d]["qqq_return_60"]
        for d in trailing_up
        if base_meta[d].get("qqq_return_60") is not None
    ]
    lines.append("## 2. Trailing regime vs forward-drawdown protection")
    lines.append("")
    lines.append(
        "`regime == \"down\"` is a trailing indicator (benchmark trailing 60d "
        "return on the signal date). In the 2023-2026 bull market most "
        "trailing dips were followed by V-shaped rebounds; the forward lens "
        "`qqq_return_60 < 0` isolates dates whose NEXT 60 trading days were "
        "actual market drawdowns."
    )
    lines.append("")
    if qqq_values:
        lines.append(
            f"- FWD_DRAWDOWN_60D: {len(drawdown_dates)} dates, next-60d QQQ "
            f"range {min(qqq_values):+.1%}..{max(qqq_values):+.1%}."
        )
    if trailing_next_qqq:
        lines.append(
            f"- TRAILING_DOWN: {len(trailing_up)} dates, next-60d QQQ range "
            f"{min(trailing_next_qqq):+.1%}..{max(trailing_next_qqq):+.1%} "
            "(post-dip rebound measure)."
        )
    lines.append("")
    lines.append("## 2b. Forward-Drawdown & 2022 Bear Signal-Date Manifest "
                 "(with 60d Window Overlap)")
    lines.append("")
    manifest_rows = frozen.get("manifest_rows") or []
    if manifest_rows:
        lines.append(_md_table(
            ["signal_date", "segment_tag", "episode_cluster",
             "trailing_regime", "qqq_ret20", "qqq_ret60", "qqq_label_end_60",
             "qqq_ret120", "overlaps_prev_60d_window"],
            [
                [
                    row["signal_date"], row["segment_tag"],
                    row["episode_cluster"] or "-", row["trailing_regime"],
                    _pct(row["qqq_ret20"]), _pct(row["qqq_ret60"]),
                    row["qqq_label_end_60"] or "-", _pct(row["qqq_ret120"]),
                    row["overlaps_prev_60d_window"],
                ]
                for row in manifest_rows
            ],
        ))
        lines.append("")
        lines.append(
            "`overlaps_prev_60d_window` = `signal_date < previous listed "
            "date's qqq_label_end_60`: monthly signal dates inside one "
            "drawdown episode share overlapping 60-trading-day (~3-month) "
            "forward windows and are therefore NOT independent samples "
            "(AGENTS.md §8); the episode-cluster equal-weight table below "
            "gives each contiguous drawdown episode one vote."
        )
        lines.append("")
    episode_summary = frozen.get("episode_summary") or {}
    episode_rows = episode_summary.get("rows") or []
    if episode_rows:
        episode_names = [
            episode["name"]
            for episode in episode_summary.get("episodes", [])
        ]
        fwd_names = episode_summary.get("fwd_episode_names") or []
        all_names = episode_summary.get("all_episode_names") or []
        has_bear_episode = any(
            name not in fwd_names for name in all_names)
        fwd_label = f"FWD_EQ({len(fwd_names)})"
        all_label = f"ALL_EQ({len(all_names)})"
        for metric, title in (
            ("mean_excess_60", "mean 60d net-QQQ excess"),
            ("severe_loss_rate_60", "severe loss rate (fwd_ret_60 <= -20%)"),
        ):
            lines.append(f"Episode-cluster equal-weight summary - {title}:")
            lines.append("")
            headers = ["scope", "cohort", "variant"] + episode_names + [
                fwd_label, "DATE_EQUAL",
            ]
            if has_bear_episode:
                headers.insert(
                    len(headers) - 1, all_label)
            table_rows = []
            for row in episode_rows:
                values = [
                    _pct(
                        row["episode_values"].get(name, {}).get(metric)
                    )
                    for name in episode_names
                ]
                if metric == "mean_excess_60":
                    fwd_value = row[
                        "fwd_drawdown_episode_equal_mean_excess_60"]
                    all_value = row[
                        "all_drawdown_episode_equal_mean_excess_60"]
                else:
                    fwd_value = row[
                        "fwd_drawdown_episode_equal_severe_loss_60"]
                    all_value = row[
                        "all_drawdown_episode_equal_severe_loss_60"]
                date_equal = (episode_summary.get("date_equal") or {}).get(
                    f"{row['universe_scope']}|{row['variant']}|"
                    f"{row['cohort']}",
                    {},
                ).get(metric)
                cells = [
                    row["universe_scope"], row["cohort"], row["variant"],
                    *values, _pct(fwd_value),
                ]
                if has_bear_episode:
                    cells.append(_pct(all_value))
                cells.append(_pct(date_equal))
                table_rows.append(cells)
            lines.append(_md_table(headers, table_rows))
            lines.append("")
    lines.append("## 3. Rank tiers: FWD_BULL_60D vs FWD_DRAWDOWN_60D (v2_current)")
    lines.append("")
    headers = ["scope", "segment", "tier", "n", "mean_ex60", "diff_vs_univ",
               "win_rate", "raw_ret60", "severe_loss60"]
    tier_table_rows = []
    for scope in UNIVERSE_SCOPES:
        for segment in ("FWD_BULL_60D", "FWD_DRAWDOWN_60D"):
            if segment not in segments:
                continue
            selected = _select(
                tier_rows, universe_scope=scope, segment=segment)
            for row in selected:
                tier_table_rows.append([
                    scope, segment, row["tier"], row["n_dates_60"],
                    row["mean_excess_60"], row["diff_vs_universe_60"],
                    row["win_rate_vs_qqq_60"], row["mean_raw_ret_60"],
                    row["severe_loss_rate_60"],
                ])
    lines.append(_md_table(headers, tier_table_rows))
    lines.append("")
    lines.append("## 4. Cohorts & severe-loss rates (v2_current)")
    lines.append("")
    cohort_rows_md = []
    for scope in UNIVERSE_SCOPES:
        for segment in ("FWD_BULL_60D", "FWD_DRAWDOWN_60D", "TRAILING_DOWN",
                        "BASE_ALL_39"):
            if segment not in segments:
                continue
            for cohort in ("TOP15", "PRIORITY_REVIEW"):
                selected = _select(
                    cohort_rows, universe_scope=scope, segment=segment,
                    variant="v2_current", cohort=cohort)
                for row in selected:
                    cohort_rows_md.append([
                        scope, segment, cohort, row["n_dates_60"],
                        row["mean_excess_60"], row["median_excess_60"],
                        row["severe_loss_rate_60"],
                        row["severe_underperform_rate_60"],
                    ])
    lines.append(_md_table(
        ["scope", "segment", "cohort", "n", "mean_ex60", "median_ex60",
         "severe_loss60", "severe_under60"],
        cohort_rows_md,
    ))
    lines.append("")
    lines.append("## 5. Entry state / SMA200 extension / grade crosscuts "
                 "(v2_current, FWD_DRAWDOWN_60D)")
    lines.append("")
    crosscut_md = []
    for scope in UNIVERSE_SCOPES:
        for cut_type in ("entry_state", "sma200_extension", "quality_grade"):
            selected = _select(
                crosscut_rows, universe_scope=scope, segment="FWD_DRAWDOWN_60D",
                cut_type=cut_type)
            for row in selected:
                crosscut_md.append([
                    scope, cut_type, row["bucket"], row["n_dates_60"],
                    row["mean_excess_60"], row["severe_loss_rate_60"],
                ])
    lines.append(_md_table(
        ["scope", "cut", "bucket", "n", "mean_ex60", "severe_loss60"],
        crosscut_md,
    ))
    if "BEAR_2022" in segments:
        lines.append("")
        lines.append("## 6. 2022 tech bear market (BEAR_2022)")
        lines.append("")
        bear_md = []
        for scope in UNIVERSE_SCOPES:
            selected = _select(
                tier_rows, universe_scope=scope, segment="BEAR_2022")
            for row in selected:
                bear_md.append([
                    scope, row["tier"], row["n_dates_60"],
                    row["mean_excess_60"], row["diff_vs_universe_60"],
                    row["severe_loss_rate_60"],
                ])
        lines.append(_md_table(
            ["scope", "tier", "n", "mean_ex60", "diff_vs_univ",
             "severe_loss60"],
            bear_md,
        ))
    lines.append("")
    lines.append("## 7. Interpretive guardrails")
    lines.append("")
    lines.append(
        "- Overlapping 60d/120d windows are not independent samples; "
        "aggregation is date-equal and the sample is small (39 base dates, "
        "8 forward-drawdown dates)."
    )
    lines.append(
        "- `severe_loss_rate_60` = share of cohort members with "
        "`fwd_ret_60 <= -20%` (date-equal mean); tail metrics need many more "
        "drawdown dates before any promotion-grade conclusion."
    )
    lines.append(
        "- Forward labels beyond the dataset's frozen horizon are matured "
        "retrospectively; never call them OOS."
    )
    lines.append("")
    return "\n".join(lines)


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


def write_outputs(
    out_dir: Path,
    files: Mapping[str, str],
) -> Path:
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
        raise ValueError(f"dataset missing signal_date/symbol: {Path(path).name}")
    return frame


def evaluate_datasets(
    datasets: Mapping[str, pd.DataFrame],
) -> tuple[
    dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
    dict[str, dict[str, Any]],
]:
    """Build records for every (scope, variant, dataset, date)."""
    records: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {
        scope: {variant: {} for variant in VARIANTS}
        for scope in UNIVERSE_SCOPES
    }
    metas: dict[str, dict[str, Any]] = {}
    for dataset_name, frame in datasets.items():
        metas[dataset_name] = dataset_date_meta(frame)
        for date, group in frame.groupby("signal_date", sort=True):
            token = str(date)
            for scope in UNIVERSE_SCOPES:
                for variant in VARIANTS:
                    records[scope][variant][token] = build_scope_records(
                        group, scope, variant, token
                    )
    return records, metas


def build_manifest_rows(
    segments: Mapping[str, Sequence[str]],
    metas: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Manifest rows for FWD_DRAWDOWN_60D + BEAR_2022 signal dates."""
    rows: list[dict[str, Any]] = []
    base_meta = metas.get("base", {})
    fwd_dates = list(segments.get("FWD_DRAWDOWN_60D", []))
    if fwd_dates:
        clusters, _ = assign_episode_clusters(fwd_dates, base_meta)
        overlaps = forward_window_overlaps(fwd_dates, base_meta)
        for date in fwd_dates:
            meta = base_meta.get(date, {})
            rows.append({
                "signal_date": date,
                "segment_tag": "FWD_DRAWDOWN_60D",
                "episode_cluster": clusters.get(date, ""),
                "trailing_regime": meta.get("regime") or "",
                "qqq_ret20": meta.get("qqq_return_20"),
                "qqq_ret60": meta.get("qqq_return_60"),
                "qqq_label_end_60": meta.get("qqq_label_end_60") or "",
                "qqq_ret120": meta.get("qqq_return_120"),
                "overlaps_prev_60d_window": (
                    "yes" if overlaps.get(date) else "no"
                ),
            })
    bear_meta = metas.get("bear", {})
    bear_dates = list(segments.get("BEAR_2022", []))
    bear_negative = set(segments.get("BEAR_2022_FWD_DRAWDOWN_60D", []))
    if bear_dates:
        bear_clusters, _ = assign_episode_clusters(
            sorted(bear_negative), bear_meta, bear=True)
        overlaps = forward_window_overlaps(bear_dates, bear_meta)
        for date in bear_dates:
            meta = bear_meta.get(date, {})
            rows.append({
                "signal_date": date,
                "segment_tag": "BEAR_2022",
                "episode_cluster": (
                    bear_clusters.get(date, "") if date in bear_negative
                    else ""
                ),
                "trailing_regime": meta.get("regime") or "",
                "qqq_ret20": meta.get("qqq_return_20"),
                "qqq_ret60": meta.get("qqq_return_60"),
                "qqq_label_end_60": meta.get("qqq_label_end_60") or "",
                "qqq_ret120": meta.get("qqq_return_120"),
                "overlaps_prev_60d_window": (
                    "yes" if overlaps.get(date) else "no"
                ),
            })
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_frame = _load_dataset(args.base_dataset)
    datasets: dict[str, pd.DataFrame] = {"base": base_frame}
    if args.bear_2022_dataset:
        datasets["bear"] = _load_dataset(args.bear_2022_dataset)
    if args.extension_dataset:
        datasets["extension"] = _load_dataset(args.extension_dataset)
    validate_disjoint_dates({
        name: sorted(frame["signal_date"].astype(str).unique())
        for name, frame in datasets.items()
    })
    print(
        f"[replay] datasets: "
        + ", ".join(
            f"{name}={len(frame)}rows/{frame['signal_date'].nunique()}dates"
            for name, frame in datasets.items()
        ),
        flush=True,
    )

    records, metas = evaluate_datasets(datasets)
    segments = build_segments(
        metas["base"],
        metas.get("bear"),
        metas.get("extension"),
    )
    for segment, dates in segments.items():
        if segment in {"COMBINED_DRAWDOWN_60D"}:
            continue
        print(f"[replay] segment {segment}: {len(dates)} dates", flush=True)

    cohort_rows = build_cohort_rows(records, segments)
    paired_rows = build_paired_rows(records, segments)
    tier_rows = build_tier_rows(records, segments)
    crosscut_rows = build_crosscut_rows(records, segments)

    reference_path = (
        Path(args.base_reference_dir) / "e0_current_cohorts.csv"
    )
    reference_rows = load_reference_rows(reference_path)
    reproduction = reproduction_check(cohort_rows, reference_rows)
    print(
        f"[replay] E0 reproduction: {reproduction['status']} "
        f"({reproduction['n_checked']} checked, "
        f"{reproduction['n_mismatches']} mismatches)",
        flush=True,
    )

    # §6.3 manifest + episode-cluster equal-weight summary
    manifest_rows = build_manifest_rows(segments, metas)
    fwd_clusters, fwd_episodes = assign_episode_clusters(
        segments.get("FWD_DRAWDOWN_60D", []), metas.get("base", {}))
    all_episodes = list(fwd_episodes)
    bear_negative = segments.get("BEAR_2022_FWD_DRAWDOWN_60D", [])
    if bear_negative:
        _, bear_episodes = assign_episode_clusters(
            bear_negative, metas.get("bear", {}), bear=True)
        all_episodes += bear_episodes
    episode_summary = compute_episode_cluster_summary(
        records,
        all_episodes,
        fwd_episode_names=[name for name, _ in fwd_episodes],
        all_episode_names=[name for name, _ in all_episodes],
    )
    print(
        "[replay] episode clusters: "
        + ", ".join(
            f"{name}={len(dates)}dates" for name, dates in all_episodes
        ),
        flush=True,
    )

    # §6.1/§6.2 frozen-grade provenance
    frozen: dict[str, Any] = {
        "runner_sha256": _sha256_file(REPO_ROOT / RUNNER_SCRIPT_REL) or "",
        "command": _reproduction_command(args),
        "base_sha256": _sha256_file(Path(args.base_dataset)) or "",
        "manifest_rows": manifest_rows,
        "episode_summary": episode_summary,
    }
    extra_files: dict[str, str] = {}
    if args.bear_2022_dataset:
        bear_artifacts = discover_bear_artifacts(
            args.bear_2022_dataset,
            meta_json=args.bear_2022_meta_json,
            success_json=args.bear_2022_success_json,
            discontinuities_csv=args.bear_2022_discontinuities_csv,
        )
        bear_provenance = build_bear_2022_provenance(
            datasets["bear"], args.bear_2022_dataset, bear_artifacts)
        extra_files["bear_2022_provenance.json"] = (
            json.dumps(bear_provenance, indent=2, sort_keys=True) + "\n"
        )
        discontinuities_path = bear_artifacts.get("discontinuities")
        if discontinuities_path and discontinuities_path.exists():
            extra_files["bear_2022_discontinuities.csv"] = (
                discontinuities_path.read_text(encoding="utf-8")
            )
        frozen["bear"] = {
            "filename": Path(args.bear_2022_dataset).name,
            "n_rows": bear_provenance["n_rows"],
            "n_dates": bear_provenance["n_dates"],
            "sha256": bear_provenance["sha256"]["repaired_csv"],
            "run_id": bear_provenance["run_id"],
            "code_sha": bear_provenance["code_sha"],
            "generated_utc": bear_provenance["generated_utc"],
            "raw_csv_sha256": bear_provenance["sha256"]["raw_extract_csv"],
            "splits_json_sha256": bear_provenance["sha256"]["splits_json"],
            "discontinuities_rows": bear_provenance["discontinuities_rows"],
            "discontinuities_flagged": bear_provenance[
                "discontinuities_flagged"],
        }

    extra_datasets = [
        (
            Path(path).name,
            label,
            int(len(datasets[key])),
            int(datasets[key]["signal_date"].nunique()),
        )
        for key, label, path in (
            ("bear", "2022 bear market", args.bear_2022_dataset),
            ("extension", "post-2026-03 extension", args.extension_dataset),
        )
        if path and key in datasets
    ]
    report = render_report(
        base_dataset_name=Path(args.base_dataset).name,
        n_base_rows=int(len(base_frame)),
        n_base_dates=int(base_frame["signal_date"].nunique()),
        segments=segments,
        cohort_rows=cohort_rows,
        tier_rows=tier_rows,
        crosscut_rows=crosscut_rows,
        reproduction=reproduction,
        base_meta=metas["base"],
        extra_datasets=extra_datasets,
        frozen=frozen,
    )
    files = {
        "cohort_economics_by_regime.csv": _csv_text(
            cohort_rows, COHORT_COLUMNS),
        "paired_deltas_by_regime.csv": _csv_text(
            paired_rows, PAIRED_COLUMNS),
        "rank_tiers_by_regime.csv": _csv_text(tier_rows, TIER_COLUMNS),
        "entry_and_extension_crosscut.csv": _csv_text(
            crosscut_rows, CROSSCUT_COLUMNS),
        "report.md": report,
        **extra_files,
    }
    out_dir = write_outputs(Path(args.output_dir), files)
    total = sum(path.stat().st_size for path in out_dir.iterdir())
    print(
        f"[replay] wrote {len(files) + 1} files, {total} bytes to "
        f"{out_dir.name}",
        flush=True,
    )
    return {
        "segments": {name: len(dates) for name, dates in segments.items()},
        "reproduction": reproduction,
        "episode_clusters": [
            {"name": name, "n_dates": len(dates)}
            for name, dates in all_episodes
        ],
        "output_dir": str(out_dir),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extended replay evaluation: forward-drawdown attribution "
            "(Route A) and 2022 bear-market replay (Route B). Offline, "
            "read-only."
        )
    )
    parser.add_argument("--base-dataset", required=True)
    parser.add_argument("--bear-2022-dataset", default=None)
    parser.add_argument("--extension-dataset", default=None)
    parser.add_argument(
        "--bear-2022-meta-json", default=None,
        help="Optional explicit 2022 Modal meta.json path.",
    )
    parser.add_argument(
        "--bear-2022-success-json", default=None,
        help="Optional explicit 2022 Modal SUCCESS.json path.",
    )
    parser.add_argument(
        "--bear-2022-discontinuities-csv", default=None,
        help="Optional explicit 2022 split-repair discontinuities CSV path.",
    )
    parser.add_argument(
        "--base-reference-dir",
        default="outputs/m4_revalidation_current_20261016",
    )
    parser.add_argument(
        "--output-dir", default="docs/drawdown_and_bear_replay_20261017"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
