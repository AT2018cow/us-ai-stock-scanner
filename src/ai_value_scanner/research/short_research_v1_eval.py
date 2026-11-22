"""Frozen-data evaluation for Short Research v1.

Selection is delegated to ``short_research_v1.build_short_cross_section`` so the
production adapter and this evaluator share one rule implementation.  This
module adds label settlement, cost scenarios, paired statistics, bootstrap,
segments, concentration, and evidence publication.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
import warnings
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.evaluation.backtest import holding_session_dates

from .short_research_v1 import (
    MAX_SHORT_CANDIDATES,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    ROUNDTRIP_COST,
    SHORT_RESEARCH_CONTRACT_VERSION,
    SHORT_RESEARCH_RULE_VERSION,
    ShortResearchInputError,
    build_short_cross_section,
    render_short_research_section,
    short_candidates_csv,
    short_research_json,
    unavailable_short_research_result,
)

DATASET_NAMES: tuple[str, ...] = (
    "sip_2016_2020_v1",
    "sip_2021_2026_v1",
    "sip_covid_weekly_v1",
    "sip_bear_weekly_v1",
)
MONTHLY_DATASETS: tuple[str, ...] = ("sip_2016_2020_v1", "sip_2021_2026_v1")
WEEKLY_DATASETS: tuple[str, ...] = ("sip_covid_weekly_v1", "sip_bear_weekly_v1")
SMOKE_DATES: tuple[str, ...] = (
    "2016-01-29",
    "2020-03-31",
    "2022-06-30",
    "2025-01-31",
)
HORIZONS: tuple[int, ...] = (20, 60)
LABEL_CUTOFF = "2026-11-05"
MISSING_SCENARIOS = {"missing_low": -0.50, "missing_high": 0.50}
GROUPS = ("S0", "S1", "S2")
OUTPUT_FILES = frozenset({
    "coverage.csv", "paired_by_date.csv", "summary.csv", "members.csv",
    "casebook.csv", "report.md", "validation.json", "protocol.json",
    "scan_integration.json", "short_research.json", "short_candidates.csv",
    "action_list_short_fragment.md", "weekly_review_short_fragment.md",
    "commands.md", "source_coverage.csv", "industry_stats.csv", "concentration.csv",
})

BOOTSTRAP_REPEATS = 2000
BOOTSTRAP_SEED = 61122
BOOTSTRAP_BLOCK_MONTHS = 6
COST_SCENARIOS: dict[str, tuple[float, float, float]] = {
    "trade_only": (0.0015, 0.0, 0.0),
    "base": (0.0015, 0.05, 0.02),
    "stress": (0.0030, 0.15, 0.04),
}
MEMBER_VALUE_COLUMNS = (
    "short_gross", *(f"short_cost_{scenario}" for scenario in COST_SCENARIOS),
    "period_end_adverse_up", "breakeven_borrow", "peer_median_long_gross",
    "peer_relative_long", "qqq_long_gross",
)
MEMBER_COLUMNS = (
    "dataset", "frequency", "signal_date", "horizon", "group", "view",
    "rank", "symbol", "cik", "sic", "regime", "watchlist_source",
    "weight", "status", "label_status", "label_reasons", "mature",
    "date_complete", "entry_date", "exit_date", *MEMBER_VALUE_COLUMNS,
    "peer_count", "peer_pool",
)
DEFAULT_OUTPUT_ROOT = "outputs/short_research_v1"
DEFAULT_EVIDENCE_ROOT = "docs/short_research_v1/evidence"

_STRING_COLUMNS = ("symbol", "cik", "sic", "market_data_feed", "watchlist_source")
LOGGER = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fmt(value: Any) -> str:
    number = _num(value)
    return "" if number is None else f"{number:.6f}"


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def _share(values: Iterable[bool]) -> float | None:
    items = list(values)
    return sum(1 for item in items if item) / len(items) if items else None


def _pct(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:+.1f}%"


def _pct_exact(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:+.3f}%"


def _pct_plain(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:.1f}%"


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(header) for header in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


@dataclass(frozen=True)
class DatasetIdentity:
    name: str
    path: Path
    rows: int
    dates: int
    dataset_sha256: str
    metadata_sha256: str
    success_sha256: str
    splits_sha256: str
    generation_config: str
    config_reference_sha256: str
    frequency: str
    meta: Mapping[str, Any]


def _manifest_input_hashes() -> dict[str, str]:
    root = Path("docs/value_pullback_optimization_20261106/worker_manifests/prepared")
    hashes: dict[str, str] = {}
    for name, subdir in (
        ("sip_2016_2020_v1", "monthly"),
        ("sip_2021_2026_v1", "monthly"),
        ("sip_covid_weekly_v1", "covid"),
        ("sip_bear_weekly_v1", "bear"),
    ):
        manifest_path = root / subdir / "manifest.json"
        if not manifest_path.is_file():
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        inputs = (payload.get("parity") or {}).get("inputs") or {}
        for key, value in inputs.items():
            if key.startswith(f"datasets/{name}/"):
                hashes[key] = str(value)
    return hashes


def load_frozen_dataset(dataset_root: str | Path, name: str) -> DatasetIdentity:
    root = Path(dataset_root) / name
    dataset_path = root / "dataset.csv"
    meta_path = root / "dataset.meta.json"
    success_path = root / "success.json"
    splits_path = root / "dataset.splits.json"
    for path in (dataset_path, meta_path, success_path, splits_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen input: {path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    success = json.loads(success_path.read_text(encoding="utf-8"))
    dataset_sha = _sha256_file(dataset_path)
    meta_sha = _sha256_file(meta_path)
    success_sha = _sha256_file(success_path)
    splits_sha = _sha256_file(splits_path)
    if splits_sha != meta.get("source_splits_sha256"):
        raise ValueError(f"{splits_path}: frozen split hash mismatch")
    config_ref = Path(str(meta.get("scan_config") or "")).name
    if config_ref != "config.risk_off.json":
        raise ValueError(f"{meta_path}: unexpected source scan configuration")
    config_reference = Path(__file__).resolve().parents[3] / "configs" / config_ref
    if str(success.get("sha256")) != dataset_sha:
        raise ValueError(f"{dataset_path}: success.json sha256 mismatch")
    if str(success.get("metadata_sha256")) != meta_sha:
        raise ValueError(f"{meta_path}: success.json metadata_sha256 mismatch")
    if int(success.get("rows", -1)) != int(meta.get("n_rows", -2)):
        raise ValueError(f"{dataset_path}: success/meta row count mismatch")
    expected_manifest = _manifest_input_hashes()
    if expected_manifest:
        key = f"datasets/{name}/dataset.csv"
        if key in expected_manifest and expected_manifest[key] != dataset_sha:
            raise ValueError(
                f"{dataset_path}: manifest hash mismatch "
                f"{dataset_sha} != {expected_manifest[key]}"
            )
        key = f"datasets/{name}/dataset.meta.json"
        if key in expected_manifest and expected_manifest[key] != meta_sha:
            raise ValueError(f"{meta_path}: manifest metadata hash mismatch")
        key = f"datasets/{name}/success.json"
        if key in expected_manifest and expected_manifest[key] != success_sha:
            raise ValueError(f"{success_path}: manifest success hash mismatch")
    required_meta = {
        "label_contract": "exchange_calendar_endpoints_v3",
        "label_cutoff": LABEL_CUTOFF,
        "entry_price_mode": "next_open",
        "exit_price_mode": "close",
        "roundtrip_cost": ROUNDTRIP_COST,
        "market_data_feed": "sip",
        "pre_strategy_cross_section": True,
    }
    for key, expected in required_meta.items():
        if meta.get(key) != expected:
            raise ValueError(
                f"{meta_path}: {key}={meta.get(key)!r} != {expected!r}"
            )
    return DatasetIdentity(
        name=name,
        path=dataset_path,
        rows=int(success.get("rows", 0)),
        dates=int(success.get("dates", 0)),
        dataset_sha256=dataset_sha,
        metadata_sha256=meta_sha,
        success_sha256=success_sha,
        splits_sha256=splits_sha,
        generation_config=config_ref,
        config_reference_sha256=_sha256_file(config_reference),
        frequency=str(meta.get("rebalance_frequency") or ""),
        meta=meta,
    )


def load_frozen_dataset_frame(
    dataset_root: str | Path,
    name: str,
) -> tuple[pd.DataFrame, DatasetIdentity]:
    identity = load_frozen_dataset(dataset_root, name)
    frame = pd.read_csv(
        identity.path,
        dtype={column: str for column in _STRING_COLUMNS},
        low_memory=False,
        keep_default_na=False,
        na_values=[""],
    )
    if frame.empty:
        raise ValueError(f"{identity.path}: empty dataset")
    frame["signal_date"] = frame["signal_date"].astype(str)
    if frame.duplicated(["signal_date", "symbol"]).any():
        raise ValueError(f"{identity.path}: duplicate signal_date x symbol")
    if not frame["market_data_feed"].astype("string").str.strip().str.lower().fillna("").eq("sip").all():
        raise ValueError(f"{identity.path}: mixed or unknown market data feed")
    if len(frame) != identity.rows or frame["signal_date"].nunique() != identity.dates:
        raise ValueError(f"{identity.path}: frozen row/date count mismatch")
    return frame, identity


def _planned_endpoints(signal_date: str, horizon: int) -> tuple[str, str]:
    entry, exit_ = holding_session_dates(signal_date, horizon)
    return entry.date().isoformat(), exit_.date().isoformat()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    token = str(value).strip()
    if token.lower() in {"nan", "nat", "none"}:
        return None
    return token or None


def _peer_medians(
    settled: pd.DataFrame,
    *,
    horizon: int,
) -> dict[tuple[str, str, str, str, int], tuple[float | None, int, int]]:
    """Exact leave-one-out medians, keyed by the target as well as its cohort."""
    result = {}
    u0 = settled.loc[~settled["scope_excluded"]]
    column = f"long_gross_{horizon}"
    for key, group in u0.groupby(["dataset", "signal_date", "sic"], sort=False):
        valid = group.loc[group[column].notna()].sort_values(column)
        values = valid[column].to_numpy(dtype=float)
        positions = {symbol: index for index, symbol in enumerate(valid["symbol"])}
        for symbol in group["symbol"]:
            excluded = positions.get(symbol, len(values))
            count = len(values) - int(excluded < len(values))
            median = None
            if count >= 4:
                left, right = (count - 1) // 2, count // 2
                median = (
                    values[left + int(left >= excluded)] +
                    values[right + int(right >= excluded)]
                ) / 2
            result[(*key, symbol, horizon)] = (median, count, len(group) - 1)
    return result


def _settle_labels(records: pd.DataFrame, horizon: int) -> None:
    endpoints = {day: _planned_endpoints(day, horizon) for day in records["signal_date"].unique()}
    entry = records["signal_date"].map(lambda day: endpoints[day][0])
    exit_ = records["signal_date"].map(lambda day: endpoints[day][1])
    days = (pd.to_datetime(exit_) - pd.to_datetime(entry)).dt.days.clip(lower=1)
    mature = exit_ <= LABEL_CUTOFF
    fwd = pd.to_numeric(records[f"fwd_ret_{horizon}"], errors="coerce")
    label = records[f"label_end_{horizon}"]
    ratio = 1.0 + fwd + ROUNDTRIP_COST
    valid = mature & label.eq(exit_) & np.isfinite(ratio) & ratio.gt(0)
    qqq_ratio = 1.0 + pd.to_numeric(
        records[f"qqq_return_{horizon}"], errors="coerce"
    ) + ROUNDTRIP_COST
    qqq_valid = mature & records[f"qqq_label_end_{horizon}"].eq(exit_) & (
        np.isfinite(qqq_ratio) & qqq_ratio.gt(0)
    )
    c, _, dividend = COST_SCENARIOS["base"]
    values = {
        "planned_entry": entry, "planned_exit": exit_, "mature": mature,
        "label_valid": valid, "x_ratio": ratio.where(valid),
        "holding_days": days, "qqq_valid": qqq_valid,
        "label_reason": np.select(
            [~mature, ~np.isfinite(fwd), label.isna(), ~label.eq(exit_), ~valid],
            ["NOT_MATURE", "MISSING_FORWARD_RETURN", "MISSING_EXIT_LABEL",
             "EXIT_LABEL_NOT_PLANNED_SESSION", "INVALID_RESTORED_PRICE_RATIO"],
            default="",
        ),
        "short_gross": (1.0 - ratio).where(valid),
        "long_gross": (ratio - 1.0).where(valid),
        "qqq_long_gross": (qqq_ratio - 1.0).where(qqq_valid),
        "period_end_adverse_up": (ratio - 1.0).clip(lower=0).where(valid),
        "breakeven_borrow": ((1.0 - ratio - c * (1.0 + ratio)) * 365 / days - dividend).where(valid),
    }
    for scenario, (c, borrow, dividend) in COST_SCENARIOS.items():
        values[f"short_cost_{scenario}"] = (
            1.0 - ratio - c * (1.0 + ratio) - (borrow + dividend) * days / 365
        ).where(valid)
    for key, value in values.items():
        records[f"{key}_{horizon}"] = value


def _selected_members(
    group: pd.DataFrame,
    *,
    limit: int,
) -> list[Mapping[str, Any]]:
    if group.empty or limit <= 0:
        return []
    ordered = group.sort_values(
        ["rs60_sic", "symbol"], ascending=[True, True], kind="mergesort"
    )
    return [row for _, row in ordered.head(limit).iterrows()]


def _group_return(
    members: Sequence[Mapping[str, Any]],
    *,
    weight: float,
    column: str,
) -> float | None:
    if not members:
        return 0.0 if weight > 0 else None
    values = [_num(row.get(column)) for row in members]
    if any(value is None for value in values):
        return None
    return sum(float(value) * weight for value in values)


def _block_bootstrap(
    values: Sequence[float | None],
    *,
    block: int = BOOTSTRAP_BLOCK_MONTHS,
    repeats: int = BOOTSTRAP_REPEATS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Non-circular block bootstrap over calendar positions with missing masks."""
    array = np.asarray(
        [np.nan if value is None else float(value) for value in values],
        dtype=float,
    )
    n = len(array)
    if n < block or int(np.isfinite(array).sum()) < 2:
        return {
            "n": n,
            "valid": int(np.isfinite(array).sum()),
            "block": block,
            "repeats": repeats,
            "seed": seed,
            "empty_samples": 0,
            "ci_low": None,
            "ci_high": None,
        }
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - block + 1, size=(repeats, math.ceil(n / block)))
    indices = (
        starts[:, :, None] + np.arange(block, dtype=int)
    ).reshape(repeats, -1)[:, :n]
    sampled = array[indices]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        means = np.nanmean(sampled, axis=1)
    empty = int(np.isnan(means).sum())
    finite = means[np.isfinite(means)]
    if finite.size == 0:
        low = high = None
    else:
        low, high = np.percentile(finite, [2.5, 97.5])
    return {
        "n": n,
        "valid": int(np.isfinite(array).sum()),
        "block": block,
        "repeats": repeats,
        "seed": seed,
        "empty_samples": empty,
        "ci_low": float(low) if low is not None else None,
        "ci_high": float(high) if high is not None else None,
    }


def _verdict(
    *,
    n_dates: int,
    years: Sequence[int],
    s2_mean: float | None,
    s2_s0: float | None,
    s2_s1: float | None,
    s2_s0_ci: Mapping[str, Any],
    yearly_s2_s0: Mapping[int, float | None],
    loo_s2_s0: float | None,
    missing_scenarios: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if n_dates < 24:
        return {
            "verdict": "insufficient_evidence",
            "reasons": ["fewer than 24 mature complete dates"],
        }
    if len(set(years)) < 3:
        return {
            "verdict": "insufficient_evidence",
            "reasons": ["fewer than three calendar years"],
        }
    for metric, baseline in (("s2_mean", s2_mean), ("s2_minus_s0_mean", s2_s0)):
        if baseline is not None and any(
            _num(value) is not None and np.sign(value) != np.sign(baseline)
            for value in missing_scenarios.get(metric, {}).values()
        ):
            return {
                "verdict": "insufficient_evidence",
                "reasons": [f"mature missing slots change the sign of {metric}"],
            }
    failed: list[str] = []
    if s2_mean is None or s2_mean <= 0:
        failed.append("S2 absolute short gross return is not positive")
    if s2_s0 is None or s2_s0 <= 0:
        failed.append("S2-S0 paired difference is not positive")
    if s2_s1 is None or s2_s1 <= 0:
        failed.append("S2-S1 paired difference is not positive")
    if failed:
        return {"verdict": "signal_or_increment_failed", "reasons": failed}
    insufficient: list[str] = []
    ci_low = _num(s2_s0_ci.get("ci_low"))
    if ci_low is None or ci_low <= 0:
        insufficient.append("S2-S0 bootstrap lower bound is not positive")
    positive_years = [
        year for year, value in yearly_s2_s0.items() if value is not None and value > 0
    ]
    if len(positive_years) < 2:
        insufficient.append("only one calendar year has a positive average S2-S0")
    if loo_s2_s0 is None or loo_s2_s0 <= 0:
        insufficient.append(
            "S2-S0 turns non-positive after removing the largest positive contributor"
        )
    if insufficient:
        return {"verdict": "insufficient_evidence", "reasons": insufficient}
    return {"verdict": "support_next_round", "reasons": []}


def evaluate_frozen_short_research(
    dataset_root: str | Path,
    output_root: str | Path,
    *,
    scope: str = "full",
    scan_entry_integration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if scope not in {"smoke", "full"}:
        raise ValueError("scope must be 'smoke' or 'full'")
    dataset_root = Path(dataset_root)
    output_root = Path(output_root)
    identities: dict[str, DatasetIdentity] = {}
    frames: dict[str, pd.DataFrame] = {}
    names = DATASET_NAMES if scope == "full" else MONTHLY_DATASETS
    for name in names:
        frame, identity = load_frozen_dataset_frame(dataset_root, name)
        if scope == "smoke":
            frame = frame.loc[frame["signal_date"].isin(SMOKE_DATES)].copy()
            if frame.empty:
                raise ValueError(f"{name}: no smoke dates present")
        identities[name] = identity
        frames[name] = frame

    inputs = {
        name: {
            "dataset_sha256": identity.dataset_sha256,
            "metadata_sha256": identity.metadata_sha256,
            "success_sha256": identity.success_sha256,
            "splits_sha256": identity.splits_sha256,
            "generation_config": identity.generation_config,
            "config_reference_sha256": identity.config_reference_sha256,
            "rows": identity.rows,
            "dates": identity.dates,
            "frequency": identity.frequency,
        }
        for name, identity in identities.items()
    }
    package = Path(__file__).resolve().parents[1]
    source_files = {
        rel: _sha256_file(package / rel) for rel in (
            "research/short_research_v1.py", "research/short_research_v1_eval.py",
            "evaluation/backtest.py", "market_calendar.py",
        )
    }
    checkpoint_identity = {
        "contract_version": SHORT_RESEARCH_CONTRACT_VERSION,
        "rule_version": SHORT_RESEARCH_RULE_VERSION,
        "scope": scope,
        "code_sha": _git_sha(),
        "source_sha256": source_files,
        "inputs": inputs,
        "scan_entry_integration_sha256": (
            _sha256_text(json.dumps(scan_entry_integration, ensure_ascii=False, sort_keys=True))
            if scan_entry_integration is not None else None
        ),
    }
    if output_root.is_dir() and any(output_root.iterdir()):
        return _reuse_evaluation(output_root, checkpoint_identity)
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"short-research output is not a directory: {output_root}")

    records: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    members_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for name, frame in frames.items():
        frequency = "weekly" if name in WEEKLY_DATASETS else "monthly"
        for signal_date, group in frame.groupby("signal_date", sort=True):
            try:
                result = build_short_cross_section(
                    group.loc[:, group.columns.intersection((*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS))],
                    report_generated_at_utc=f"{signal_date}T23:59:59+00:00",
                )
            except ShortResearchInputError as exc:
                failures.append(
                    {
                        "dataset": name,
                        "signal_date": str(signal_date),
                        "reason_codes": list(exc.reason_codes),
                        "detail": str(exc),
                    }
                )
                raise ValueError(
                    f"invalid frozen cross-section {name} {signal_date}: {exc}"
                ) from exc
            for record in result.records:
                item = record.to_dict()
                item["dataset"] = name
                item["frequency"] = frequency
                item["scope_excluded"] = record.scope_excluded
                item["selected"] = record.selected
                item["status"] = record.status
                item["signal_groups"] = list(record.signal_groups)
                records.append(item)
            coverage_rows.append(
                {
                    "dataset": name,
                    "frequency": frequency,
                    "signal_date": str(signal_date),
                    "input_rows": result.funnel.get("input_rows", 0),
                    "u0_rows": result.funnel.get("u0_rows", 0),
                    "u0_unique_rows": result.funnel.get("u0_unique_rows", 0),
                    "industry_rs_rows": result.funnel.get("industry_rs_rows", 0),
                    "pe_eligible_rows": result.funnel.get("pe_eligible_rows", 0),
                    "pe_rows": result.funnel.get("pe_rows", 0),
                    "u_rows": result.funnel.get("u_rows", 0),
                    "s0_rows": result.funnel.get("s0_rows", 0),
                    "s1_rows": result.funnel.get("s1_rows", 0),
                    "s2_rows": result.funnel.get("s2_rows", 0),
                    "selected_rows": result.funnel.get("selected_rows", 0),
                    "status": result.status,
                }
            )

        LOGGER.info("Selected %s frozen cross-sections (%d rows)", name, len(frame))

    if not records:
        raise RuntimeError("no short-research records produced from frozen inputs")
    records_df = pd.DataFrame(records)
    # Attach labels from the source frames.
    label_columns = [
        "signal_date",
        "symbol",
        "fwd_ret_20",
        "label_end_20",
        "fwd_ret_60",
        "label_end_60",
        "qqq_return_20",
        "qqq_label_end_20",
        "qqq_return_60",
        "qqq_label_end_60",
    ]
    label_frames = []
    for name, frame in frames.items():
        part = frame[label_columns].copy()
        part["dataset"] = name
        label_frames.append(part)
    labels = pd.concat(label_frames, ignore_index=True)
    records_df = records_df.merge(
        labels,
        on=["dataset", "signal_date", "symbol"],
        how="left",
        validate="many_to_one",
    )

    settled = records_df
    for horizon in HORIZONS:
        _settle_labels(settled, horizon)
        peer_map = _peer_medians(settled, horizon=horizon)
        peers = [
            peer_map.get((*key, horizon), (None, 0, 0))
            for key in settled[["dataset", "signal_date", "sic", "symbol"]].itertuples(
                index=False, name=None
            )
        ]
        settled[f"peer_median_long_gross_{horizon}"] = [row[0] for row in peers]
        settled[f"peer_count_{horizon}"] = [row[1] for row in peers]
        settled[f"peer_pool_{horizon}"] = [row[2] for row in peers]
        settled[f"peer_relative_long_{horizon}"] = (
            settled[f"long_gross_{horizon}"] - settled[f"peer_median_long_gross_{horizon}"]
        )

    LOGGER.info("Settled the %d selected-study input rows at %s sessions", len(settled), HORIZONS)

    paired_rows = []
    coverage_detail = []
    for (dataset, signal_date), date_rows in settled.groupby(["dataset", "signal_date"], sort=False):
        frequency = "weekly" if dataset in WEEKLY_DATASETS else "monthly"
        ranks = {
            group: _selected_members(
                date_rows.loc[date_rows["signal_groups"].map(lambda values: group in values)],
                limit=MAX_SHORT_CANDIDATES,
            )
            for group in GROUPS
        }
        n_s0, n_s1, n_s2 = (len(ranks[group]) for group in GROUPS)
        k = min(n_s0, n_s1, n_s2)
        k_financial = min(n_s0, n_s1)
        regime = set(date_rows["regime"])
        regime = regime.pop() if len(regime) == 1 else "unknown"
        for horizon in HORIZONS:
            mature = bool(date_rows[f"mature_{horizon}"].iloc[0])
            coverage = {
                "dataset": dataset, "frequency": frequency, "signal_date": signal_date,
                "horizon": horizon, "mature": mature, "regime": regime,
                "k": k, "k_financial": k_financial,
                **{f"n_{group.lower()}": int(date_rows["signal_groups"].map(
                    lambda values: group in values
                ).sum()) for group in GROUPS},
            }
            paired = dict(coverage)
            for group, n in zip(GROUPS, (n_s0, n_s1, n_s2)):
                coverage[f"fixed_deployment_{group.lower()}"] = n / MAX_SHORT_CANDIDATES
            for view, ledger_view, limit, view_groups in (
                ("same", "same_slot", k, GROUPS),
                ("fixed", "fixed_5", MAX_SHORT_CANDIDATES, GROUPS),
                ("financial", "financial_matched", k_financial, GROUPS[:2]),
            ):
                weight = 1 / limit if limit else 0.0
                active = {group: ranks[group][:limit] for group in view_groups}
                gross = {
                    group: _group_return(
                        members, weight=weight, column=f"short_gross_{horizon}"
                    ) if mature else None
                    for group, members in active.items()
                }
                complete = mature and bool(limit) and all(
                    value is not None for value in gross.values()
                )
                paired[f"{view}_complete"] = complete
                for group, members in active.items():
                    key = f"{group.lower()}_{view}"
                    paired[key] = gross[group]
                    paired[f"{key}_deployment"] = len(members) / MAX_SHORT_CANDIDATES
                    coverage[f"{ledger_view}_{group}_return"] = gross[group]
                    coverage[f"{ledger_view}_{group}_missing"] = sum(
                        not member[f"label_valid_{horizon}"] for member in members
                    ) if mature else 0
                    for scenario in COST_SCENARIOS:
                        paired[f"{key}_{scenario}"] = _group_return(
                            members, weight=weight, column=f"short_cost_{scenario}_{horizon}"
                        ) if complete else None
                    for scenario, missing_return in MISSING_SCENARIOS.items():
                        paired[f"{key}_{scenario}"] = sum(
                            weight * (
                                float(member[f"short_gross_{horizon}"])
                                if member[f"label_valid_{horizon}"] else missing_return
                            )
                            for member in members
                        ) if mature and limit else None
                    for rank, member in enumerate(members, start=1):
                        members_rows.append({
                            "dataset": dataset, "frequency": frequency, "signal_date": signal_date,
                            "horizon": horizon, "group": group, "view": ledger_view,
                            "rank": rank, "symbol": member["symbol"], "cik": member["cik"],
                            "sic": member["sic"], "regime": member["regime"],
                            "watchlist_source": member["watchlist_source"],
                            "weight": weight, "status": member["status"],
                            "label_status": "VALID" if member[f"label_valid_{horizon}"]
                            else "MISSING" if mature else "NOT_MATURE",
                            "label_reasons": member[f"label_reason_{horizon}"],
                            "mature": mature, "date_complete": complete,
                            "entry_date": member[f"planned_entry_{horizon}"],
                            "exit_date": member[f"planned_exit_{horizon}"],
                            **{
                                column: _num(member[f"{column}_{horizon}"])
                                for column in MEMBER_VALUE_COLUMNS
                            },
                            "peer_count": int(member[f"peer_count_{horizon}"]),
                            "peer_pool": int(member[f"peer_pool_{horizon}"]),
                        })
                for a, b in (("S1", "S0"), ("S2", "S1"), ("S2", "S0")):
                    if a not in active:
                        continue
                    delta_key = f"{a.lower()}_minus_{b.lower()}_{view}"
                    paired[delta_key] = gross[a] - gross[b] if complete else None
                    for scenario in (*COST_SCENARIOS, *MISSING_SCENARIOS):
                        av = paired[f"{a.lower()}_{view}_{scenario}"]
                        bv = paired[f"{b.lower()}_{view}_{scenario}"]
                        paired[f"{delta_key}_{scenario}"] = av - bv if av is not None and bv is not None else None
            paired_rows.append(paired)
            coverage_detail.append(coverage)

    paired_df = pd.DataFrame(paired_rows)
    coverage_df = pd.DataFrame(coverage_detail)
    members_df = pd.DataFrame(members_rows, columns=MEMBER_COLUMNS)
    summary_rows = _summarize_cohorts(paired_df)

    monthly_20 = paired_df.loc[
        paired_df["frequency"].eq("monthly") & paired_df["horizon"].eq(20)
    ].copy()
    start_period = pd.Period("2016-01", freq="M")
    monthly_20["calendar_index"] = monthly_20["signal_date"].map(
        lambda value: pd.Period(str(value), freq="M").ordinal
        - start_period.ordinal
    )
    monthly_20 = monthly_20.loc[
        monthly_20["calendar_index"].between(0, 129)
    ].sort_values("calendar_index")
    calendar_length = 130
    delta_series: list[float | None] = [None] * calendar_length
    s2_series: list[float | None] = [None] * calendar_length
    for _, row in monthly_20.iterrows():
        idx = int(row["calendar_index"])
        if bool(row["same_complete"]):
            delta_series[idx] = _num(row["s2_minus_s0_same"])
            s2_series[idx] = _num(row["s2_same"])
    delta_ci = _block_bootstrap(delta_series)
    s2_ci = _block_bootstrap(s2_series)

    main = summary_rows and next(
        (
            row
            for row in summary_rows
            if row["segment"] == "ALL_MONTHLY"
            and row["horizon"] == 20
            and row["view"] == "same"
        ),
        None,
    )
    main = main or {}
    years = sorted(
        {
            int(str(day)[:4])
            for day in monthly_20.loc[monthly_20["same_complete"], "signal_date"]
        }
    )
    yearly: dict[int, float | None] = {}
    for year in years:
        values = monthly_20.loc[
            (monthly_20["signal_date"].astype(str).str[:4] == str(year))
            & monthly_20["same_complete"],
            "s2_minus_s0_same",
        ]
        yearly[year] = _mean(values)
    loo_delta = _contribution_loo(settled, paired_df)
    missing_scenarios = {
        metric: {
            scenario: main.get(f"{metric}_{scenario}")
            for scenario in MISSING_SCENARIOS
        }
        for metric in ("s2_mean", "s2_minus_s0_mean")
    }
    cost_means = {scenario: main.get(f"s2_mean_{scenario}") for scenario in COST_SCENARIOS}
    verdict = _verdict(
        n_dates=int(main.get("n_dates", 0) or 0),
        years=years,
        s2_mean=_num(main.get("s2_mean")),
        s2_s0=_num(main.get("s2_minus_s0_mean")),
        s2_s1=_num(main.get("s2_minus_s1_mean")),
        s2_s0_ci=delta_ci,
        yearly_s2_s0=yearly,
        loo_s2_s0=loo_delta,
        missing_scenarios=missing_scenarios,
    )

    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_root.name}.", dir=output_root.parent) as staging:
        # Evidence files.
        out = Path(staging) / "evaluation"
        out.mkdir()
        coverage_path = out / "coverage.csv"
        paired_path = out / "paired_by_date.csv"
        summary_path = out / "summary.csv"
        members_path = out / "members.csv"
        casebook_path = out / "casebook.csv"
        report_path = out / "report.md"
        validation_path = out / "validation.json"
        protocol_path = out / "protocol.json"
        manifest_path = out / "manifest.json"
        commands_path = out / "commands.md"
        scan_integration_path = out / "scan_integration.json"
        short_json_path = out / "short_research.json"
        short_csv_path = out / "short_candidates.csv"
        daily_fragment_path = out / "action_list_short_fragment.md"
        weekly_fragment_path = out / "weekly_review_short_fragment.md"

        coverage_df.to_csv(coverage_path, index=False)
        paired_df.to_csv(paired_path, index=False)
        pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
        members_df.to_csv(members_path, index=False)
        _industry_statistics(members_df, paired_df).to_csv(out / "industry_stats.csv", index=False)
        _concentration(members_df).to_csv(out / "concentration.csv", index=False)
        source_coverage = settled.groupby(
            ["dataset", "frequency", "watchlist_source"], dropna=False, sort=True
        ).agg(
            rows=("symbol", "size"), dates=("signal_date", "nunique"),
            selected=("selected", "sum"), label_20_valid=("label_valid_20", "sum"),
            label_60_valid=("label_valid_60", "sum"),
        ).reset_index()
        source_coverage.to_csv(out / "source_coverage.csv", index=False)

        casebook = _casebook(settled, members_df)
        pd.DataFrame(casebook).to_csv(casebook_path, index=False)

        # Frozen-input scan integration evidence: one non-empty and one empty
        # cross-section rendered through the same contract (not a credentialed scan).
        non_empty = next(
            (
                row
                for row in coverage_rows
                if row["status"] == "ready" and row["selected_rows"] > 0
            ),
            None,
        )
        empty = next(
            (row for row in coverage_rows if row["status"] == "no_candidates"),
            None,
        )
        scan_integration = {
            "evidence_type": "frozen_input_adapter_simulation",
            "note": (
                "No credentialed SIP/SEC scan was run in this environment. The "
                "frozen cross-section was passed through build_short_cross_section "
                "and the same snapshot/report contract; the live scanner adapter is "
                "covered by unit tests and the documented command."
            ),
            "non_empty_case": non_empty,
            "empty_case": empty,
            "statuses": sorted({row["status"] for row in coverage_rows}),
            "failures": failures,
        }
        if scan_entry_integration is not None:
            scan_integration["mocked_scan_entry"] = dict(scan_entry_integration)
        _json_dump(scan_integration_path, scan_integration)
        if non_empty is not None:
            demo_frame = frames[non_empty["dataset"]].loc[
                frames[non_empty["dataset"]]["signal_date"] == non_empty["signal_date"]
            ]
            demo_result = build_short_cross_section(
                demo_frame.loc[:, demo_frame.columns.intersection((*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS))],
                report_generated_at_utc=(
                    f"{non_empty['signal_date']}T23:59:59+00:00"
                ),
            )
        else:
            demo_result = unavailable_short_research_result(
                ("NO_NON_EMPTY_FROZEN_CASE",),
                signal_date=SMOKE_DATES[0],
                market_data_feed="sip",
            )
        short_json_path.write_text(short_research_json(demo_result), encoding="utf-8")
        short_csv_path.write_text(short_candidates_csv(demo_result), encoding="utf-8")
        fragment = "\n".join(render_short_research_section(demo_result)) + "\n"
        daily_fragment_path.write_text(fragment, encoding="utf-8")
        weekly_fragment_path.write_text(fragment, encoding="utf-8")

        protocol = {
            "contract_version": SHORT_RESEARCH_CONTRACT_VERSION,
            "rule_version": SHORT_RESEARCH_RULE_VERSION,
            "scope": scope,
            "smoke_dates": list(SMOKE_DATES),
            "horizons": list(HORIZONS),
            "max_candidates": MAX_SHORT_CANDIDATES,
            "min_price": 5.0,
            "min_dollar_volume": 2_000_000.0,
            "min_avg_dollar_volume_20d": 10_000_000.0,
            "min_industry_peers_excluding_target": 4,
            "min_pe_peers_including_target": 5,
            "excluded_sic_range": [6000, 6999],
            "fundamental_asof_max_days": 180,
            "signal_rules": {
                "S0": "rs60_sic < 0 and price_to_sma50 < 1.0 and return_20d > -0.20",
                "S1": "S0 and revenue_yoy <= 0 and operating_cash_flow_growth <= -0.10",
                "S2": "S1 and pe_percentile >= 0.80 and pe_premium >= 0.25",
            },
            "cost_scenarios": {
                key: {"per_side": value[0], "borrow": value[1], "dividend": value[2]}
                for key, value in COST_SCENARIOS.items()
            },
            "bootstrap": {
                "repeats": BOOTSTRAP_REPEATS,
                "seed": BOOTSTRAP_SEED,
                "block_months": BOOTSTRAP_BLOCK_MONTHS,
            },
            "roundtrip_cost": ROUNDTRIP_COST,
            "label_contract": "exchange_calendar_endpoints_v3",
            "label_cutoff": LABEL_CUTOFF,
            "missing_slot_scenarios": MISSING_SCENARIOS,
        }
        _json_dump(protocol_path, protocol)

        manifest = {
            "run_id": output_root.name,
            "scope": scope,
            "dataset_root": _portable_path(dataset_root),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "code_sha": checkpoint_identity["code_sha"],
            "source_files": source_files,
            "inputs": inputs,
            "outputs": {},
        }
        commands_path.write_text(
            _commands_text(
                scope, dataset_root, output_root,
                with_scan_entry=scan_entry_integration is not None,
            ),
            encoding="utf-8",
        )

        endpoint_mismatches = {
            horizon: (
                settled[f"label_end_{horizon}"].notna()
                & settled[f"fwd_ret_{horizon}"].notna()
                & settled[f"label_end_{horizon}"].ne(settled[f"planned_exit_{horizon}"])
            )
            for horizon in HORIZONS
        }
        input_label_mismatches = {
            str(horizon): int(mismatch.sum()) for horizon, mismatch in endpoint_mismatches.items()
        }
        valid_label_mismatches = sum(
            int((mismatch & settled[f"label_valid_{horizon}"]).sum())
            for horizon, mismatch in endpoint_mismatches.items()
        )
        validation = {
            "ok": (not failures) and valid_label_mismatches == 0,
            "scope": scope,
            "input_identities": {
                name: {
                    "rows": identity.rows,
                    "dates": identity.dates,
                    "dataset_sha256": identity.dataset_sha256,
                }
                for name, identity in identities.items()
            },
            "funnel_totals": {
                key: int(sum(row.get(key, 0) for row in coverage_rows))
                for key in (
                    "input_rows",
                    "u0_rows",
                    "u0_unique_rows",
                    "industry_rs_rows",
                    "pe_eligible_rows",
                    "pe_rows",
                    "u_rows",
                    "s0_rows",
                    "s1_rows",
                    "s2_rows",
                    "selected_rows",
                )
            },
            "s2_dates": int(sum(1 for row in coverage_rows if row["s2_rows"] > 0)),
            "failures": failures,
            "label_checks": {
                "all_valid_exit_labels_match_planned_sessions": valid_label_mismatches == 0,
                "label_mismatch_count": sum(input_label_mismatches.values()),
                "input_label_mismatch_by_horizon": input_label_mismatches,
                "valid_label_endpoint_mismatch_count": valid_label_mismatches,
                "missing_labels_kept_as_missing": True,
                "no_imputed_returns": True,
            },
            "verdict": verdict,
            "paired_bootstrap": delta_ci,
            "s2_bootstrap": s2_ci,
            "missing_slot_scenarios": missing_scenarios,
            "memo": "Missing-slot scenarios only use mature dates. Main estimates use complete cohorts.",
            "scan_entry_integration": dict(scan_entry_integration or {}),
        }
        _json_dump(validation_path, validation)

        report = _render_report(
            scope=scope,
            identities=identities,
            coverage_rows=coverage_rows,
            summary_rows=summary_rows,
            main=main,
            delta_ci=delta_ci,
            s2_ci=s2_ci,
            yearly=yearly,
            loo_delta=loo_delta,
            cost_means=cost_means,
            verdict=verdict,
            failures=failures,
            casebook=casebook,
            scan_integration=scan_integration,
        )
        report_path.write_text(report, encoding="utf-8")

        manifest["outputs"] = {name: _sha256_file(out / name) for name in sorted(OUTPUT_FILES)}
        _json_dump(manifest_path, manifest)
        _json_dump(out / "checkpoint.json", {
            "identity": checkpoint_identity,
            "complete": True,
            "created_at_utc": manifest["created_at_utc"],
        })
        files = sorted(OUTPUT_FILES | {"checkpoint.json", "manifest.json"})
        (out / "SHA256SUMS").write_text(
            "".join(f"{_sha256_file(out / name)}  {name}\n" for name in files),
            encoding="utf-8",
        )
        _reuse_evaluation(out, checkpoint_identity)
        if output_root.exists() and any(output_root.iterdir()):
            return _reuse_evaluation(output_root, checkpoint_identity)
        try:
            os.rename(out, output_root)
        except OSError:
            if output_root.is_dir() and any(output_root.iterdir()):
                return _reuse_evaluation(output_root, checkpoint_identity)
            raise
        return {
            "output_root": str(output_root),
            "scope": scope,
            "reused": False,
            "verdict": verdict,
            "coverage_rows": len(coverage_rows),
            "paired_rows": len(paired_rows),
            "summary_rows": len(summary_rows),
            "files": [*files, "SHA256SUMS"],
        }


def _reuse_evaluation(root: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    try:
        checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
        if checkpoint.get("identity") != identity or checkpoint.get("complete") is not True:
            raise ValueError("checkpoint identity mismatch")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        checksums = dict(
            (filename, digest)
            for digest, filename in (
                line.split("  ", 1)
                for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            )
        )
        if set(checksums) != OUTPUT_FILES | {"checkpoint.json", "manifest.json"}:
            raise ValueError("checksum file does not cover all evaluation artifacts")
        if manifest["outputs"] != {name: checksums[name] for name in OUTPUT_FILES}:
            raise ValueError("manifest output hash mismatch")
        if manifest["inputs"] != identity["inputs"] or manifest["source_files"] != identity["source_sha256"]:
            raise ValueError("manifest input or source identity mismatch")
        for name, digest in checksums.items():
            if _sha256_file(root / name) != digest:
                raise ValueError(f"evaluation artifact hash mismatch: {name}")
        validation = json.loads((root / "validation.json").read_text(encoding="utf-8"))
        if validation.get("ok") is not True:
            raise ValueError("evaluation output did not pass validation")
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise ValueError(
            f"Cannot reuse short-research evaluation at {root}: {exc}. Use a new output directory."
        ) from exc
    return {
        "output_root": str(root),
        "scope": identity["scope"],
        "reused": True,
        "verdict": validation["verdict"],
        "files": sorted([*checksums, "SHA256SUMS"]),
    }


def _summarize_cohorts(paired: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for name, mask in _segment_masks(paired).items():
        for horizon, cohort in paired.loc[mask].groupby("horizon", sort=True):
            for view in ("same", "fixed", "financial"):
                group_keys = ("s0", "s1") if view == "financial" else ("s0", "s1", "s2")
                complete = cohort.loc[cohort[f"{view}_complete"]]
                row = {
                    "segment": name, "horizon": horizon, "view": view,
                    "n_signal_dates": int(len(cohort)), "n_mature_dates": int(cohort["mature"].sum()),
                    "n_dates": int(len(complete)),
                }
                for group in group_keys:
                    values = complete[f"{group}_{view}"]
                    row[f"{group}_mean"] = _mean(values)
                    row[f"{group}_hit_rate"] = _share(values > 0)
                    deployment = cohort[f"{group}_{view}_deployment"]
                    row[f"{group}_deployment_mean"] = float(deployment.mean())
                    row[f"{group}_empty_rate"] = float(deployment.eq(0).mean())
                    for scenario in COST_SCENARIOS:
                        row[f"{group}_mean_{scenario}"] = _mean(complete[f"{group}_{view}_{scenario}"])
                    for scenario in MISSING_SCENARIOS:
                        row[f"{group}_mean_{scenario}"] = _mean(cohort[f"{group}_{view}_{scenario}"])
                for a, b in (("s1", "s0"), ("s2", "s1"), ("s2", "s0")):
                    if a not in group_keys:
                        continue
                    delta = f"{a}_minus_{b}"
                    values = complete[f"{delta}_{view}"]
                    row[f"{delta}_mean"] = _mean(values)
                    row[f"{delta}_positive_ratio"] = _share(values > 0)
                    for scenario in COST_SCENARIOS:
                        row[f"{delta}_mean_{scenario}"] = _mean(complete[f"{delta}_{view}_{scenario}"])
                    for scenario in MISSING_SCENARIOS:
                        row[f"{delta}_mean_{scenario}"] = _mean(cohort[f"{delta}_{view}_{scenario}"])
                rows.append(row)
    return rows


def _industry_statistics(members: pd.DataFrame, paired: pd.DataFrame) -> pd.DataFrame:
    book = ["frequency", "horizon", "view", "group"]
    columns = [*book, "sic"]
    eligible = members.loc[members["date_complete"].eq(True)]
    cohort = pd.concat([eligible, eligible.assign(sic="ALL")], ignore_index=True)
    cohort["down"] = cohort["short_gross"].gt(0)
    cohort["underperformed_peers"] = cohort["peer_relative_long"].lt(0).where(
        cohort["peer_relative_long"].notna()
    )
    cohort["peer_missing_fraction"] = 1.0 - cohort["peer_count"].div(
        cohort["peer_pool"].replace(0, np.nan)
    )
    cohort["weighted_gross"] = cohort["short_gross"] * cohort["weight"]
    cohort["weighted_base"] = cohort["short_cost_base"] * cohort["weight"]
    active = cohort.groupby(columns, dropna=False).agg(
        members=("symbol", "size"), active_dates=("signal_date", "nunique"),
        gross_sum=("weighted_gross", "sum"), base_sum=("weighted_base", "sum"),
        price_down_rate=("down", "mean"),
        peer_observed_members=("peer_relative_long", "count"),
        peer_underperformance_rate=("underperformed_peers", "mean"),
        peer_relative_long_mean=("peer_relative_long", "mean"),
        peer_count_mean=("peer_count", "mean"),
        peer_missing_fraction_mean=("peer_missing_fraction", "mean"),
        qqq_long_gross_mean=("qqq_long_gross", "mean"),
        terminal_adverse_p90=("period_end_adverse_up", lambda values: values.quantile(0.90)),
        terminal_adverse_max=("period_end_adverse_up", "max"),
        breakeven_borrow_median=("breakeven_borrow", "median"),
    ).reset_index()
    date_counts = []
    for view, ledger_view, groups in (
        ("same", "same_slot", GROUPS),
        ("fixed", "fixed_5", GROUPS),
        ("financial", "financial_matched", GROUPS[:2]),
    ):
        counts = paired.groupby(["frequency", "horizon"])[f"{view}_complete"].sum()
        for group in groups:
            date_counts.append(counts.rename("dates").reset_index().assign(view=ledger_view, group=group))
    denominators = pd.concat(date_counts, ignore_index=True)
    # Every SIC contributes to the original portfolio. Missing sector exposures
    # and whole cash dates contribute zero on complete comparison dates.
    statistics = denominators.assign(sic="ALL").merge(active, on=columns, how="left")
    sectors = active.loc[active["sic"].ne("ALL")].merge(denominators, on=book, how="left")
    statistics = pd.concat([statistics, sectors], ignore_index=True)
    for column in ("members", "active_dates", "peer_observed_members"):
        statistics[column] = statistics[column].fillna(0).astype(int)
    dates = statistics["dates"].replace(0, np.nan)
    statistics["gross_mean"] = statistics.pop("gross_sum").astype(float).fillna(0.0).div(dates)
    statistics["base_net_mean"] = statistics.pop("base_sum").astype(float).fillna(0.0).div(dates)
    return statistics.sort_values(columns, ignore_index=True)


def _concentration(members: pd.DataFrame) -> pd.DataFrame:
    keys = ["frequency", "horizon", "view", "group"]
    mature = members.loc[members["mature"].eq(True)].copy()
    mature["weighted_gross"] = mature["weight"] * mature["short_gross"].where(
        mature["date_complete"].eq(True)
    )
    totals = mature.groupby(keys)["weight"].transform("sum")
    mature["slot_share"] = mature["weight"] / totals
    rows = []
    for column in ("cik", "sic"):
        grouped = mature.groupby([*keys, column], sort=True).agg(
            slots=("symbol", "size"), dates=("signal_date", "nunique"), share=("slot_share", "sum"),
            known_contribution_slots=("weighted_gross", "count"),
            weighted_gross_sum=("weighted_gross", lambda values: values.sum(min_count=1)),
        ).reset_index().rename(columns={column: "key"})
        rows.append(grouped.assign(kind=column))
    return pd.concat(rows, ignore_index=True)


def _contribution_loo(
    settled: pd.DataFrame,
    paired_df: pd.DataFrame,
) -> float | None:
    """Remove the largest positive company contribution without reselecting."""
    monthly = paired_df.loc[
        (paired_df["frequency"] == "monthly")
        & (paired_df["horizon"] == 20)
        & paired_df["same_complete"]
    ]
    if monthly.empty:
        return None
    contribution_by_company: Counter[str] = Counter()
    per_date: dict[tuple[str, str], dict[str, float]] = {}
    for row in monthly.itertuples(index=False):
        date_rows = settled.loc[
            (settled["dataset"] == row.dataset)
            & (settled["signal_date"] == row.signal_date)
        ]
        k = int(row.k)
        if k <= 0:
            continue
        net: dict[str, float] = {}
        valid = True
        for group, sign in (("S0", -1.0), ("S2", 1.0)):
            members = date_rows.loc[
                date_rows["signal_groups"].map(lambda values: group in values)
            ].sort_values(
                ["rs60_sic", "symbol"], ascending=[True, True], kind="mergesort"
            ).head(k)
            for member in members.itertuples(index=False):
                value = _num(getattr(member, "short_gross_20", None))
                if value is None:
                    valid = False
                    break
                net[member.cik] = net.get(member.cik, 0.0) + sign * value / k
            if not valid:
                break
        if not valid:
            continue
        per_date[(str(row.dataset), str(row.signal_date))] = net
        contribution_by_company.update(net)
    if not per_date:
        return None
    largest, contribution = contribution_by_company.most_common(1)[0]
    if contribution <= 0:
        return _mean(monthly["s2_minus_s0_same"])
    deltas: list[float] = []
    for (dataset, signal_date), net in per_date.items():
        base = paired_df.loc[
            (paired_df["dataset"] == dataset)
            & (paired_df["signal_date"] == signal_date)
            & (paired_df["horizon"] == 20)
            & paired_df["same_complete"],
            "s2_minus_s0_same",
        ]
        if base.empty:
            continue
        deltas.append(float(base.iloc[0]) - float(net.get(largest, 0.0)))
    return _mean(deltas)


def _segment_masks(paired: pd.DataFrame) -> dict[str, pd.Series]:
    monthly = paired["frequency"].eq("monthly")
    weekly = paired["frequency"].eq("weekly")
    dates = paired["signal_date"]
    covid = paired["dataset"].eq("sip_covid_weekly_v1")
    masks = {
        "ALL_MONTHLY": monthly,
        "ALL_WEEKLY": weekly,
        "COVID_2020_02_03": covid & dates.between("2020-02-01", "2020-03-31"),
        "COVID_2020_04_06": covid & dates.between("2020-04-01", "2020-06-30"),
        "BEAR_2022": paired["dataset"].eq("sip_bear_weekly_v1"),
    }
    for year in sorted(dates.str[:4].unique()):
        masks[f"YEAR_{year}"] = monthly & dates.str.startswith(year)
        masks[f"WEEKLY_YEAR_{year}"] = weekly & dates.str.startswith(year)
    for regime in sorted(paired["regime"].unique()):
        matches = paired["regime"].eq(regime)
        masks[f"MONTHLY_REGIME_{regime}"] = monthly & matches
        masks[f"WEEKLY_REGIME_{regime}"] = weekly & matches
    return masks


def _casebook(settled: pd.DataFrame, members: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    outside_cap = settled.loc[
        settled["status"].eq("CONFIRMED") & ~settled["selected"]
    ]
    if not outside_cap.empty:
        row = outside_cap.iloc[0]
        rows.append({
            "case_type": "confirmed_not_selected_cap",
            "signal_date": row["signal_date"], "symbol": row["symbol"],
            "status": row["status"], "label_status": bool(row["label_valid_20"]),
            "note": "CONFIRMED outside the five-slot list",
        })
    else:
        rows.append({
            "case_type": "synthetic_not_selected_cap",
            "signal_date": "n/a", "symbol": "n/a", "status": "CONFIRMED",
            "label_status": "n/a", "note": "Synthetic sixth-ranked name remains outside the list",
        })

    missing = members.loc[members["label_status"].eq("MISSING")]
    if not missing.empty:
        row = missing.iloc[0]
        rows.append({
            "case_type": "selected_group_member_missing_label",
            "signal_date": row["signal_date"], "symbol": row["symbol"],
            "status": row["status"], "label_status": row["label_status"],
            "note": f"{row['horizon']}d {row['label_reasons']}, kept at original rank",
        })
    else:
        rows.append({
            "case_type": "synthetic_missing_label",
            "signal_date": "n/a", "symbol": "n/a", "status": "CONFIRMED",
            "label_status": "MISSING",
            "note": "Synthetic mature missing label retains its slot and excludes the primary comparison",
        })
    return rows


def _git_sha() -> str | None:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _portable_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    repo_root = Path(__file__).resolve().parents[3]
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return str(resolved)


def _commands_text(
    scope: str,
    dataset_root: Path,
    output_root: Path,
    *,
    with_scan_entry: bool,
) -> str:
    evidence_input = (
        'scan_entry = json.loads((recorded_run / "scan_integration.json").read_text('
        'encoding="utf-8"))["mocked_scan_entry"]\n'
        if with_scan_entry else "scan_entry = None\n"
    )
    return (
        "# Short Research v1 reproduction\n\n"
        "Run from the repository root. For a fresh output, keep recorded_run "
        "pointing at this evidence bundle and choose a new output_root.\n\n"
        "```bash\n"
        ".venv/bin/python -m unittest discover -s tests -p test_short_research_v1.py\n"
        ".venv/bin/python -m unittest discover -s tests\n"
        "```\n\n"
        "Frozen evaluation (importable entry; no new scan/cron CLI):\n\n"
        "```bash\n"
        ".venv/bin/python - <<'PY'\n"
        "import json\n"
        "from pathlib import Path\n"
        "from ai_value_scanner.research.short_research_v1 import evaluate_frozen_short_research\n"
        f"dataset_root = Path({_portable_path(dataset_root)!r})\n"
        f"recorded_run = Path({_portable_path(output_root)!r})\n"
        "output_root = recorded_run\n"
        f"{evidence_input}"
        "print(evaluate_frozen_short_research(\n"
        f"    dataset_root, output_root, scope={scope!r}, scan_entry_integration=scan_entry,\n"
        "))\n"
        "PY\n"
        "```\n"
    )


def _render_report(
    *,
    scope: str,
    identities: Mapping[str, DatasetIdentity],
    coverage_rows: Sequence[Mapping[str, Any]],
    summary_rows: Sequence[Mapping[str, Any]],
    main: Mapping[str, Any],
    delta_ci: Mapping[str, Any],
    s2_ci: Mapping[str, Any],
    yearly: Mapping[int, float | None],
    loo_delta: float | None,
    cost_means: Mapping[str, float | None],
    verdict: Mapping[str, Any],
    failures: Sequence[Mapping[str, Any]],
    casebook: Sequence[Mapping[str, Any]],
    scan_integration: Mapping[str, Any],
) -> str:
    lines = [
        "# Short Research v1 — Frozen Evaluation",
        "",
        f"- Scope: `{scope}`",
        f"- Contract: `{SHORT_RESEARCH_CONTRACT_VERSION}` · Rule: `{SHORT_RESEARCH_RULE_VERSION}`",
        f"- Evidence class: retrospective frozen SIP cross-sections; not OOS and not a return promise.",
        f"- Verdict: **{verdict['verdict']}**",
    ]
    if verdict.get("reasons"):
        lines.append("- Verdict reasons: " + "; ".join(verdict["reasons"]))
    lines.extend(["", "## 1. Inputs", ""])
    input_rows = []
    for name, identity in identities.items():
        input_rows.append(
            [
                name,
                identity.frequency,
                identity.rows,
                identity.dates,
                identity.dataset_sha256[:16] + "…",
            ]
        )
    lines.append(_md_table(["dataset", "freq", "rows", "dates", "sha256"], input_rows))
    lines.extend(["", "## 2. Funnel", ""])
    funnel_rows = []
    for key in (
        "input_rows",
        "u0_rows",
        "u0_unique_rows",
        "industry_rs_rows",
        "pe_eligible_rows",
        "pe_rows",
        "u_rows",
        "s0_rows",
        "s1_rows",
        "s2_rows",
        "selected_rows",
    ):
        funnel_rows.append([key, sum(int(row.get(key, 0)) for row in coverage_rows)])
    lines.append(_md_table(["stage", "rows"], funnel_rows))
    s2_dates = sum(1 for row in coverage_rows if row["s2_rows"] > 0)
    lines.append(f"- S2 signal dates: {s2_dates}")
    lines.extend(["", "## 3. Main 20d same-slot result", ""])
    lines.append(
        _md_table(
            ["metric", "value"],
            [
                ["mature complete dates", main.get("n_dates", 0)],
                ["S0 mean short gross", _pct(main.get("s0_mean"))],
                ["S1 mean short gross", _pct(main.get("s1_mean"))],
                ["S2 mean short gross", _pct(main.get("s2_mean"))],
                ["S1-S0", _pct(main.get("s1_minus_s0_mean"))],
                ["S2-S1", _pct(main.get("s2_minus_s1_mean"))],
                ["S2-S0", _pct_exact(main.get("s2_minus_s0_mean"))],
                ["S2-S0 95% CI", f"[{_pct(delta_ci.get('ci_low'))}, {_pct(delta_ci.get('ci_high'))}]"],
                ["S2 95% CI", f"[{_pct(s2_ci.get('ci_low'))}, {_pct(s2_ci.get('ci_high'))}]"],
                ["S2-S0 positive date ratio", _pct_plain(main.get("s2_minus_s0_positive_ratio"))],
                ["trade-only S2 mean", _pct_exact(cost_means.get("trade_only"))],
                ["base cost S2 mean", _pct_exact(cost_means.get("base"))],
                ["S2-S0 with mature missing slots at -50%", _pct_exact(main.get("s2_minus_s0_mean_missing_low"))],
                ["S2-S0 with mature missing slots at +50%", _pct_exact(main.get("s2_minus_s0_mean_missing_high"))],
                ["stress cost S2 mean", _pct(cost_means.get("stress"))],
                ["leave-one-company-out S2-S0", _pct(loo_delta)],
            ],
        )
    )
    lines.extend(["", "### By year (S2-S0, 20d same-slot)", ""])
    lines.append(
        _md_table(
            ["year", "S2-S0"],
            [[year, _pct(value)] for year, value in sorted(yearly.items())],
        )
    )
    lines.extend(["", "## 4. Segments", ""])
    segment_rows = []
    for row in summary_rows:
        if row["horizon"] != 20:
            continue
        segment_rows.append(
            [
                row["segment"],
                row["view"],
                row["n_dates"],
                _pct(row.get("s2_mean")),
                _pct(row.get("s2_minus_s0_mean")),
                _pct_plain(row.get("s2_minus_s0_positive_ratio")),
            ]
        )
    lines.append(
        _md_table(
            ["segment", "view", "dates", "S2", "S2-S0", "positive ratio"],
            segment_rows,
        )
    )
    lines.extend([
        "", "- Separate financial matched comparison (S1 vs S0) is in the 'financial' rows of summary.csv.",
        "- Industry and group-total diagnostics are in industry_stats.csv. Gross and base net are weighted portfolio contributions averaged across complete dates, including cash. Hit rates, peer coverage and tails use observed members.",

        "- See source_coverage.csv for universe coverage and concentration.csv for company/industry allocation.",
        "", "## 5. Casebook", "",
    ])
    lines.append(
        _md_table(
            ["case", "date", "symbol", "status", "label", "note"],
            [
                [
                    row["case_type"],
                    row["signal_date"],
                    row["symbol"],
                    row["status"],
                    row["label_status"],
                    row["note"],
                ]
                for row in casebook
            ],
        )
    )
    lines.extend(["", "## 6. Scan integration evidence", ""])
    lines.append(
        f"- Evidence type: `{scan_integration.get('evidence_type')}`"
    )
    lines.append(f"- Statuses observed: {scan_integration.get('statuses')}")
    mocked = scan_integration.get("mocked_scan_entry")
    if isinstance(mocked, dict):
        lines.append(
            "- Mocked scan entry: "
            f"off/on long decisions identical={mocked.get('long_decisions_identical')} "
            f"· legacy CSV identical={mocked.get('long_legacy_csv_identical')} "
            f"· on short status={mocked.get('on', {}).get('short_status')} "
            f"· truncation status={mocked.get('truncation', {}).get('short_status')} "
            f"· short-failure status={mocked.get('short_failure', {}).get('short_status')}"
        )
    lines.append(
        "- A credentialed live SIP scan was not run here; the frozen adapter "
        "and snapshot/report contract are covered by tests and the commands file."
    )
    if failures:
        lines.extend(["", "## 7. Failures", ""])
        for failure in failures:
            lines.append(
                f"- {failure['dataset']} {failure['signal_date']}: "
                f"{failure['reason_codes']} ({failure['detail']})"
            )
    lines.extend(
        [
            "",
            "## 8. Honest limitations",
            "",
            "- Monthly inputs are largely `union_superset_approx`; peer and company coverage is affected by the frozen universe.",
            "- Labels are overlapping forward returns; date-level aggregation is used, not independent-row inference.",
            "- Borrow evidence is `UNKNOWN` for all historical rows; no historical borrow database exists.",
            "- Costs are assumptions, not observed borrow fees or locates.",
            "- Period-end adverse-up is reported. No matching complete raw daily path was verified for this run.",
            "- Generation config name is archived in the input metadata. The config reference hash identifies the repository copy used to verify checkpoint identity.",

            "- Retrospective results do not promote production behavior and are not OOS.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "DATASET_NAMES",
    "DEFAULT_EVIDENCE_ROOT",
    "DEFAULT_OUTPUT_ROOT",
    "SMOKE_DATES",
    "evaluate_frozen_short_research",
    "load_frozen_dataset",
    "load_frozen_dataset_frame",
]
