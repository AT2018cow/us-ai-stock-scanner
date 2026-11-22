"""Frozen-data evaluation for Short Research v1.

Selection is delegated to ``short_research_v1.build_short_cross_section`` so the
production adapter and this evaluator share one rule implementation.  This
module adds label settlement, cost scenarios, paired statistics, bootstrap,
segments, concentration, and evidence publication.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import warnings
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.evaluation.backtest import holding_session_dates

from .short_research_v1 import (
    MAX_SHORT_CANDIDATES,
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
BOOTSTRAP_REPEATS = 2000
BOOTSTRAP_SEED = 61122
BOOTSTRAP_BLOCK_MONTHS = 6
COST_SCENARIOS: dict[str, tuple[float, float, float]] = {
    "trade_only": (0.0015, 0.0, 0.0),
    "base": (0.0015, 0.05, 0.02),
    "stress": (0.0030, 0.15, 0.04),
}
DEFAULT_OUTPUT_ROOT = "outputs/short_research_v1"
DEFAULT_EVIDENCE_ROOT = "docs/short_research_v1/evidence"

_STRING_COLUMNS = ("symbol", "cik", "sic", "market_data_feed", "watchlist_source")


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


def _csv_text(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(columns),
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


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
    for path in (dataset_path, meta_path, success_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen input: {path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    success = json.loads(success_path.read_text(encoding="utf-8"))
    dataset_sha = _sha256_file(dataset_path)
    meta_sha = _sha256_file(meta_path)
    success_sha = _sha256_file(success_path)
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
        "label_cutoff": "2026-11-05",
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
    )
    if frame.empty:
        raise ValueError(f"{identity.path}: empty dataset")
    frame["signal_date"] = frame["signal_date"].astype(str)
    if frame.duplicated(["signal_date", "symbol"]).any():
        raise ValueError(f"{identity.path}: duplicate signal_date x symbol")
    feeds = {
        str(value).strip().lower()
        for value in frame["market_data_feed"].dropna().unique()
    }
    if feeds != {"sip"}:
        raise ValueError(f"{identity.path}: mixed/unknown feed {sorted(feeds)}")
    return frame, identity


def _planned_endpoints(signal_date: str, horizon: int) -> tuple[str, str]:
    entry, exit_ = holding_session_dates(signal_date, horizon)
    return entry.date().isoformat(), exit_.date().isoformat()


def _settle_record(
    row: Mapping[str, Any],
    *,
    horizon: int,
    peer_median_by_key: Mapping[tuple[str, str, int], tuple[float | None, int]],
) -> dict[str, Any]:
    signal_date = str(row["signal_date"])
    symbol = str(row["symbol"])
    planned_entry, planned_exit = _planned_endpoints(signal_date, horizon)
    label_end = _text(row.get(f"label_end_{horizon}"))
    fwd = _num(row.get(f"fwd_ret_{horizon}"))
    qqq = _num(row.get(f"qqq_return_{horizon}"))
    qqq_end = _text(row.get(f"qqq_label_end_{horizon}"))
    reason: list[str] = []
    valid = True
    if fwd is None:
        valid = False
        reason.append("MISSING_FORWARD_RETURN")
    if label_end is None:
        valid = False
        reason.append("MISSING_EXIT_LABEL")
    elif label_end != planned_exit:
        valid = False
        reason.append("EXIT_LABEL_NOT_PLANNED_SESSION")
    x = None
    if fwd is not None:
        x = 1.0 + fwd + ROUNDTRIP_COST
        if not math.isfinite(x) or x <= 0:
            valid = False
            reason.append("INVALID_RESTORED_PRICE_RATIO")
    if not valid:
        x = None
    short_gross = 1.0 - x if x is not None else None
    long_gross = x - 1.0 if x is not None else None
    holding_days = None
    if label_end is not None:
        try:
            holding_days = max(
                1,
                (date.fromisoformat(label_end) - date.fromisoformat(planned_entry)).days,
            )
        except ValueError:
            holding_days = None
    costs: dict[str, float | None] = {}
    for scenario, (per_side, borrow, dividend) in COST_SCENARIOS.items():
        if x is None or holding_days is None:
            costs[scenario] = None
            continue
        value = (
            1.0
            - x
            - per_side * (1.0 + x)
            - (borrow + dividend) * holding_days / 365.0
        )
        costs[scenario] = value if math.isfinite(value) else None
    qqq_valid = (
        qqq is not None
        and label_end is not None
        and qqq_end is not None
        and qqq_end == label_end
    )
    qqq_long_gross = qqq + ROUNDTRIP_COST if qqq_valid else None
    peer_median, peer_count = peer_median_by_key.get(
        (signal_date, str(row.get("sic") or ""), horizon),
        (None, 0),
    )
    peer_relative_long = (
        long_gross - peer_median
        if long_gross is not None and peer_median is not None
        else None
    )
    return {
        "planned_entry_date": planned_entry,
        "planned_exit_date": planned_exit,
        "label_end": label_end,
        "label_status": "VALID" if valid else "MISSING",
        "label_reasons": "|".join(reason),
        "fwd_ret": fwd,
        "x_ratio": x,
        "short_gross": short_gross,
        "long_gross": long_gross,
        "holding_days": holding_days,
        "short_cost_trade_only": costs["trade_only"],
        "short_cost_base": costs["base"],
        "short_cost_stress": costs["stress"],
        "qqq_valid": qqq_valid,
        "qqq_long_gross": qqq_long_gross,
        "peer_median_long_gross": peer_median,
        "peer_count": peer_count,
        "peer_relative_long": peer_relative_long,
        "period_end_adverse_up": (
            max(0.0, long_gross) if long_gross is not None else None
        ),
    }


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
) -> dict[tuple[str, str, str, int], tuple[float | None, int]]:
    """Same-day, same-dataset U0 peer median long gross return, excluding target."""
    result: dict[tuple[str, str, str, int], tuple[float | None, int]] = {}
    u0 = settled.loc[~settled["scope_excluded"]]
    for (dataset, signal_date, sic), group in u0.groupby(
        ["dataset", "signal_date", "sic"], sort=True
    ):
        valid = group.loc[
            group[f"long_gross_{horizon}"].notna(), ["symbol", f"long_gross_{horizon}"]
        ]
        if len(valid) < 4:
            continue
        for _, row in valid.iterrows():
            others = valid.loc[
                valid["symbol"] != row["symbol"], f"long_gross_{horizon}"
            ]
            if len(others) >= 4:
                result[(str(dataset), str(signal_date), str(sic), horizon)] = (
                    float(others.median()),
                    int(len(others)),
                )
    return result


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
    cost_means: Mapping[str, float | None],
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
    for name, value in cost_means.items():
        if value is None:
            continue
        if s2_mean is not None and value * s2_mean < 0:
            insufficient.append(f"{name} cost scenario changes the S2 sign")
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
    output_root.mkdir(parents=True, exist_ok=True)
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

    checkpoint_identity = {
        "contract_version": SHORT_RESEARCH_CONTRACT_VERSION,
        "rule_version": SHORT_RESEARCH_RULE_VERSION,
        "scope": scope,
        "code_sha": _git_sha(),
        "source_sha256": {
            "short_research_v1.py": _sha256_file(
                Path(__file__).with_name("short_research_v1.py")
            ),
            "short_research_v1_eval.py": _sha256_file(Path(__file__)),
        },
        "inputs": {
            name: identity.dataset_sha256
            for name, identity in identities.items()
        },
        "scan_entry_integration_sha256": (
            _sha256_text(
                json.dumps(
                    scan_entry_integration,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            if scan_entry_integration is not None
            else None
        ),
    }
    checkpoint_path = output_root / "checkpoint.json"
    if checkpoint_path.is_file():
        existing_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if existing_checkpoint.get("identity") != checkpoint_identity:
            raise ValueError(
                "short-research checkpoint identity mismatch; use a new output "
                "directory or reproduce the exact protocol/input/code identity"
            )
        if (output_root / "SHA256SUMS").is_file() and (
            output_root / "validation.json"
        ).is_file():
            validation = json.loads(
                (output_root / "validation.json").read_text(encoding="utf-8")
            )
            return {
                "output_root": str(output_root),
                "scope": scope,
                "reused": True,
                "verdict": validation.get("verdict"),
                "files": sorted(
                    path.name for path in output_root.iterdir() if path.is_file()
                ),
            }

    records: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    members_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for name, frame in frames.items():
        frequency = "weekly" if name in WEEKLY_DATASETS else "monthly"
        for signal_date, group in frame.groupby("signal_date", sort=True):
            try:
                result = build_short_cross_section(
                    group,
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
                continue
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

    settled = records_df.copy()
    for horizon in HORIZONS:
        planned = {
            signal_date: _planned_endpoints(str(signal_date), horizon)
            for signal_date in settled["signal_date"].unique()
        }
        settled[f"planned_entry_{horizon}"] = settled["signal_date"].map(
            lambda value: planned[str(value)][0]
        )
        settled[f"planned_exit_{horizon}"] = settled["signal_date"].map(
            lambda value: planned[str(value)][1]
        )
        settled[f"label_valid_{horizon}"] = (
            settled[f"fwd_ret_{horizon}"].notna()
            & settled[f"label_end_{horizon}"].notna()
            & (
                settled[f"label_end_{horizon}"].astype(str)
                == settled[f"planned_exit_{horizon}"]
            )
        )
        settled[f"x_{horizon}"] = np.where(
            settled[f"label_valid_{horizon}"],
            1.0
            + pd.to_numeric(settled[f"fwd_ret_{horizon}"], errors="coerce")
            + ROUNDTRIP_COST,
            np.nan,
        )
        settled[f"x_{horizon}"] = pd.to_numeric(
            settled[f"x_{horizon}"], errors="coerce"
        )
        settled.loc[
            ~np.isfinite(settled[f"x_{horizon}"]) | (settled[f"x_{horizon}"] <= 0),
            f"label_valid_{horizon}",
        ] = False
        settled[f"short_gross_{horizon}"] = np.where(
            settled[f"label_valid_{horizon}"],
            1.0 - settled[f"x_{horizon}"],
            np.nan,
        )
        settled[f"long_gross_{horizon}"] = np.where(
            settled[f"label_valid_{horizon}"],
            settled[f"x_{horizon}"] - 1.0,
            np.nan,
        )
        settled[f"holding_days_{horizon}"] = [
            (
                max(
                    1,
                    (
                        date.fromisoformat(str(label_end))
                        - date.fromisoformat(str(planned_entry))
                    ).days,
                )
                if _text(label_end) is not None
                and _text(planned_entry) is not None
                else np.nan
            )
            for label_end, planned_entry in zip(
                settled[f"label_end_{horizon}"],
                settled[f"planned_entry_{horizon}"],
            )
        ]
        for scenario, (per_side, borrow, dividend) in COST_SCENARIOS.items():
            settled[f"short_cost_{scenario}_{horizon}"] = (
                1.0
                - settled[f"x_{horizon}"]
                - per_side * (1.0 + settled[f"x_{horizon}"])
                - (borrow + dividend)
                * pd.to_numeric(settled[f"holding_days_{horizon}"], errors="coerce")
                / 365.0
            )
            settled.loc[
                ~settled[f"label_valid_{horizon}"],
                f"short_cost_{scenario}_{horizon}",
            ] = np.nan
        settled[f"qqq_valid_{horizon}"] = (
            settled[f"qqq_return_{horizon}"].notna()
            & settled[f"qqq_label_end_{horizon}"].notna()
            & (
                settled[f"qqq_label_end_{horizon}"].astype(str)
                == settled[f"label_end_{horizon}"].astype(str)
            )
        )
        settled[f"qqq_long_gross_{horizon}"] = np.where(
            settled[f"qqq_valid_{horizon}"],
            pd.to_numeric(settled[f"qqq_return_{horizon}"], errors="coerce")
            + ROUNDTRIP_COST,
            np.nan,
        )
        settled[f"period_end_adverse_up_{horizon}"] = np.where(
            settled[f"label_valid_{horizon}"],
            np.maximum(0.0, settled[f"long_gross_{horizon}"]),
            np.nan,
        )

    # Peer medians are computed per date/SIC from U0 rows with valid labels.
    for horizon in HORIZONS:
        peer_map = _peer_medians(settled, horizon=horizon)
        settled[f"peer_median_long_gross_{horizon}"] = [
            peer_map.get(
                (
                    str(row["dataset"]),
                    str(row["signal_date"]),
                    str(row["sic"]),
                    horizon,
                ),
                (None, 0),
            )[0]
            for _, row in settled.iterrows()
        ]
        settled[f"peer_count_{horizon}"] = [
            peer_map.get(
                (
                    str(row["dataset"]),
                    str(row["signal_date"]),
                    str(row["sic"]),
                    horizon,
                ),
                (None, 0),
            )[1]
            for _, row in settled.iterrows()
        ]
        settled[f"peer_relative_long_{horizon}"] = (
            settled[f"long_gross_{horizon}"]
            - settled[f"peer_median_long_gross_{horizon}"]
        )

    paired_rows: list[dict[str, Any]] = []
    coverage_detail: list[dict[str, Any]] = []
    for dataset in frames:
        frequency = "weekly" if dataset in WEEKLY_DATASETS else "monthly"
        dates = sorted(frames[dataset]["signal_date"].unique())
        for signal_date in dates:
            date_rows = settled.loc[
                (settled["dataset"] == dataset)
                & (settled["signal_date"] == signal_date)
            ]
            for horizon in HORIZONS:
                groups = {
                    group: date_rows.loc[
                        date_rows["signal_groups"].map(
                            lambda values: group in values
                        )
                    ]
                    for group in ("S0", "S1", "S2")
                }
                k = min(
                    MAX_SHORT_CANDIDATES,
                    len(groups["S0"]),
                    len(groups["S1"]),
                    len(groups["S2"]),
                )
                coverage = {
                    "dataset": dataset,
                    "frequency": frequency,
                    "signal_date": signal_date,
                    "horizon": horizon,
                    "k": k,
                    "n_s0": len(groups["S0"]),
                    "n_s1": len(groups["S1"]),
                    "n_s2": len(groups["S2"]),
                    "fixed_deployment_s0": min(5, len(groups["S0"])) / 5.0,
                    "fixed_deployment_s1": min(5, len(groups["S1"])) / 5.0,
                    "fixed_deployment_s2": min(5, len(groups["S2"])) / 5.0,
                }
                for view, limit, weight in (
                    ("same_slot", k, 1.0 / k if k else 0.0),
                    ("fixed_5", 5, 1.0 / 5.0),
                ):
                    for group in ("S0", "S1", "S2"):
                        members = _selected_members(groups[group], limit=limit)
                        for rank, member in enumerate(members, start=1):
                            members_rows.append(
                                {
                                    "dataset": dataset,
                                    "frequency": frequency,
                                    "signal_date": signal_date,
                                    "horizon": horizon,
                                    "group": group,
                                    "view": view,
                                    "rank": rank,
                                    "symbol": member["symbol"],
                                    "sic": member["sic"],
                                    "weight": weight,
                                    "status": member["status"],
                                    "label_status": (
                                        "VALID"
                                        if bool(member[f"label_valid_{horizon}"])
                                        else "MISSING"
                                    ),
                                    "label_reasons": "",
                                    "entry_date": member[f"planned_entry_{horizon}"],
                                    "exit_date": member[f"planned_exit_{horizon}"],
                                    "short_gross": _fmt(
                                        member[f"short_gross_{horizon}"]
                                    ),
                                    "short_cost_base": _fmt(
                                        member[f"short_cost_base_{horizon}"]
                                    ),
                                }
                            )
                        value = _group_return(
                            members,
                            weight=weight,
                            column=f"short_gross_{horizon}",
                        )
                        coverage[f"{view}_{group}_return"] = _fmt(value)
                    for group in ("S0", "S1", "S2"):
                        value = _group_return(
                            _selected_members(groups[group], limit=limit),
                            weight=weight,
                            column=f"short_gross_{horizon}",
                        )
                        coverage[f"{view}_{group}_return"] = _fmt(value)
                coverage_detail.append(coverage)
                same = {
                    group: _num(coverage.get(f"same_slot_{group}_return"))
                    for group in ("S0", "S1", "S2")
                }
                fixed = {
                    group: _num(coverage.get(f"fixed_5_{group}_return"))
                    for group in ("S0", "S1", "S2")
                }
                complete_same = k > 0 and all(
                    same[group] is not None for group in same
                )
                complete_fixed = all(
                    fixed[group] is not None for group in fixed
                )
                paired = {
                    "dataset": dataset,
                    "frequency": frequency,
                    "signal_date": signal_date,
                    "horizon": horizon,
                    "k": k,
                    "same_complete": complete_same,
                    "fixed_complete": complete_fixed,
                    "s0_same": same["S0"],
                    "s1_same": same["S1"],
                    "s2_same": same["S2"],
                    "s1_minus_s0_same": (
                        same["S1"] - same["S0"]
                        if complete_same
                        else None
                    ),
                    "s2_minus_s1_same": (
                        same["S2"] - same["S1"]
                        if complete_same
                        else None
                    ),
                    "s2_minus_s0_same": (
                        same["S2"] - same["S0"]
                        if complete_same
                        else None
                    ),
                    "s0_fixed": fixed["S0"],
                    "s1_fixed": fixed["S1"],
                    "s2_fixed": fixed["S2"],
                    "s1_minus_s0_fixed": (
                        fixed["S1"] - fixed["S0"]
                        if complete_fixed
                        else None
                    ),
                    "s2_minus_s1_fixed": (
                        fixed["S2"] - fixed["S1"]
                        if complete_fixed
                        else None
                    ),
                    "s2_minus_s0_fixed": (
                        fixed["S2"] - fixed["S0"]
                        if complete_fixed
                        else None
                    ),
                }
                paired_rows.append(paired)

    paired_df = pd.DataFrame(paired_rows)
    coverage_df = pd.DataFrame(coverage_detail)

    summary_rows: list[dict[str, Any]] = []
    segments = _segment_masks(paired_df, frames)
    for segment_name, mask in segments.items():
        subset = paired_df.loc[mask]
        if subset.empty:
            continue
        for horizon in HORIZONS:
            h = subset.loc[subset["horizon"] == horizon]
            if h.empty:
                continue
            for view in ("same", "fixed"):
                complete = h.loc[h[f"{view}_complete"]]
                row: dict[str, Any] = {
                    "segment": segment_name,
                    "horizon": horizon,
                    "view": view,
                    "n_dates": int(len(complete)),
                    "n_s0": int(h["k"].gt(0).sum()) if view == "same" else int(len(h)),
                    "deployment_mean": (
                        float(h["k"].clip(upper=5).div(5).mean())
                        if view == "same"
                        else float(
                            (
                                h["s0_fixed"].notna()
                                | h["s1_fixed"].notna()
                                | h["s2_fixed"].notna()
                            ).mean()
                        )
                    ),
                }
                for group in ("s0", "s1", "s2"):
                    row[f"{group}_mean"] = _mean(complete[f"{group}_{view}"])
                    row[f"{group}_hit_rate"] = _share(
                        value is not None and value > 0
                        for value in complete[f"{group}_{view}"]
                    )
                for delta in ("s1_minus_s0", "s2_minus_s1", "s2_minus_s0"):
                    row[f"{delta}_mean"] = _mean(
                        complete[f"{delta}_{view}"]
                    )
                    row[f"{delta}_positive_ratio"] = _share(
                        value is not None and value > 0
                        for value in complete[f"{delta}_{view}"]
                    )
                summary_rows.append(row)

    # Main monthly ALL 20d same-slot series for bootstrap/verdict.
    monthly = paired_df.loc[
        paired_df["frequency"] == "monthly",
        ["signal_date", "horizon", "same_complete", "s2_minus_s0_same", "s2_same"],
    ].drop_duplicates(["signal_date", "horizon"])
    monthly_20 = monthly.loc[monthly["horizon"] == 20].copy()
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
    cost_means = {
        "trade_only": _cost_scenario_mean(settled, "trade_only", 20),
        "base": _cost_scenario_mean(settled, "base", 20),
        "stress": _cost_scenario_mean(settled, "stress", 20),
    }
    verdict = _verdict(
        n_dates=int(main.get("n_dates", 0) or 0),
        years=years,
        s2_mean=_num(main.get("s2_mean")),
        s2_s0=_num(main.get("s2_minus_s0_mean")),
        s2_s1=_num(main.get("s2_minus_s1_mean")),
        s2_s0_ci=delta_ci,
        yearly_s2_s0=yearly,
        loo_s2_s0=loo_delta,
        cost_means=cost_means,
    )

    # Evidence files.
    out = output_root
    out.mkdir(parents=True, exist_ok=True)
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
    pd.DataFrame(members_rows).to_csv(members_path, index=False)

    casebook = _casebook(settled)
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
            demo_frame,
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
        "label_cutoff": "2026-11-05",
    }
    _json_dump(protocol_path, protocol)

    manifest = {
        "run_id": out.name,
        "scope": scope,
        "created_at_utc": (
            f"{max(str(row['signal_date']) for row in coverage_rows)}T23:59:59+00:00"
        ),
        "code_sha": _git_sha(),
        "source_files": {
            "short_research_v1.py": _sha256_file(
                Path(__file__).with_name("short_research_v1.py")
            ),
            "short_research_v1_eval.py": _sha256_file(Path(__file__)),
        },
        "inputs": {
            name: {
                "dataset_sha256": identity.dataset_sha256,
                "metadata_sha256": identity.metadata_sha256,
                "success_sha256": identity.success_sha256,
                "rows": identity.rows,
                "dates": identity.dates,
                "frequency": identity.frequency,
            }
            for name, identity in identities.items()
        },
        "outputs": {},
    }
    for path in (
        coverage_path,
        paired_path,
        summary_path,
        members_path,
        casebook_path,
        report_path,
        validation_path,
        protocol_path,
        scan_integration_path,
        short_json_path,
        short_csv_path,
        daily_fragment_path,
        weekly_fragment_path,
    ):
        manifest["outputs"][path.name] = _sha256_file(path) if path.exists() else None
    _json_dump(manifest_path, manifest)

    commands = _commands_text(scope, output_root)
    commands_path.write_text(commands, encoding="utf-8")

    label_mismatch = int(
        (
            settled["label_end_20"].notna()
            & settled["fwd_ret_20"].notna()
            & (
                settled["label_end_20"].astype(str)
                != settled["planned_exit_20"].astype(str)
            )
        ).sum()
    )
    validation = {
        "ok": (not failures) and label_mismatch == 0,
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
            "all_valid_exit_labels_match_planned_sessions": label_mismatch == 0,
            "label_mismatch_count": label_mismatch,
            "missing_labels_kept_as_missing": True,
            "no_imputed_returns": True,
        },
        "verdict": verdict,
        "scan_entry_integration": dict(scan_entry_integration or {}),
    }
    _json_dump(validation_path, validation)

    report = _render_report(
        scope=scope,
        identities=identities,
        coverage_rows=coverage_rows,
        paired_df=paired_df,
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

    # Recompute output hashes after report/validation/commands exist.
    manifest["outputs"] = {
        path.name: _sha256_file(path)
        for path in (
            coverage_path,
            paired_path,
            summary_path,
            members_path,
            casebook_path,
            report_path,
            validation_path,
            protocol_path,
            commands_path,
            scan_integration_path,
            short_json_path,
            short_csv_path,
            daily_fragment_path,
            weekly_fragment_path,
        )
        if path.exists()
    }
    _json_dump(manifest_path, manifest)

    _json_dump(
        checkpoint_path,
        {
            "identity": checkpoint_identity,
            "complete": True,
            "created_at_utc": manifest["created_at_utc"],
        },
    )
    files = [
        coverage_path,
        paired_path,
        summary_path,
        members_path,
        casebook_path,
        report_path,
        validation_path,
        protocol_path,
        manifest_path,
        commands_path,
        scan_integration_path,
        short_json_path,
        short_csv_path,
        daily_fragment_path,
        weekly_fragment_path,
        checkpoint_path,
    ]
    checksum_lines = "".join(
        f"{_sha256_file(path)}  {path.name}\n" for path in files if path.exists()
    )
    (out / "SHA256SUMS").write_text(checksum_lines, encoding="utf-8")
    return {
        "output_root": str(out),
        "scope": scope,
        "reused": False,
        "verdict": verdict,
        "coverage_rows": len(coverage_rows),
        "paired_rows": len(paired_rows),
        "summary_rows": len(summary_rows),
        "files": [path.name for path in files] + ["SHA256SUMS"],
    }


def _cost_scenario_mean(
    settled: pd.DataFrame,
    scenario: str,
    horizon: int,
) -> float | None:
    column = f"short_cost_{scenario}_{horizon}"
    values = settled.loc[
        settled["selected"] & settled[column].notna(), column
    ]
    return _mean(values)


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
    contribution_by_symbol: Counter[str] = Counter()
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
                net[member.symbol] = net.get(member.symbol, 0.0) + sign * value / k
            if not valid:
                break
        if not valid:
            continue
        per_date[(str(row.dataset), str(row.signal_date))] = net
        contribution_by_symbol.update(net)
    if not per_date:
        return None
    largest = contribution_by_symbol.most_common(1)[0][0]
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


def _segment_masks(
    paired_df: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.Series]:
    masks: dict[str, pd.Series] = {}
    index = paired_df.index
    masks["ALL"] = pd.Series(True, index=index)
    masks["ALL_MONTHLY"] = paired_df["frequency"] == "monthly"
    masks["ALL_WEEKLY"] = paired_df["frequency"] == "weekly"
    masks["COVID_2020_02_03"] = (
        (paired_df["frequency"] == "weekly")
        & paired_df["signal_date"].astype(str).between("2020-02-01", "2020-03-31")
    )
    masks["COVID_2020_04_06"] = (
        (paired_df["frequency"] == "weekly")
        & paired_df["signal_date"].astype(str).between("2020-04-01", "2020-06-30")
    )
    masks["BEAR_2022"] = paired_df["signal_date"].astype(str).str[:4] == "2022"
    for year in sorted({str(value)[:4] for value in paired_df["signal_date"]}):
        masks[f"YEAR_{year}"] = paired_df["signal_date"].astype(str).str[:4] == year
    return masks


def _casebook(settled: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    non_selected = settled.loc[
        (settled["status"] == "CONFIRMED") & (~settled["selected"])
    ]
    if not non_selected.empty:
        row = non_selected.iloc[0]
        rows.append(
            {
                "case_type": "confirmed_not_selected_cap",
                "signal_date": row["signal_date"],
                "symbol": row["symbol"],
                "status": row["status"],
                "label_status": row.get("label_valid_20"),
                "note": "CONFIRMED but outside the five-slot list",
            }
        )
    missing = settled.loc[
        settled["signal_groups"].map(lambda values: bool(values))
        & (~settled["label_valid_20"].astype(bool))
    ]
    if not missing.empty:
        row = missing.iloc[0]
        rows.append(
            {
                "case_type": "selected_group_member_missing_label",
                "signal_date": row["signal_date"],
                "symbol": row["symbol"],
                "status": row["status"],
                "label_status": row.get("label_valid_20"),
                "note": "missing endpoint kept as missing; no substitution",
            }
        )
    if not rows:
        rows.append(
            {
                "case_type": "synthetic_missing_label",
                "signal_date": "n/a",
                "symbol": "n/a",
                "status": "INSUFFICIENT_DATA",
                "label_status": False,
                "note": "synthetic casebook entry; no historical example available",
            }
        )
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
    raw = Path(path)
    try:
        return str(raw.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(raw)


def _commands_text(scope: str, output_root: str | Path) -> str:
    portable = _portable_path(output_root)
    return (
        "# Short Research v1 reproduction\n\n"
        "```bash\n"
        ".venv/bin/python -m unittest discover -s tests -p test_short_research_v1.py\n"
        ".venv/bin/python -m unittest discover -s tests\n"
        "```\n\n"
        "Frozen evaluation (importable entry; no new scan/cron CLI):\n\n"
        "```bash\n"
        f".venv/bin/python - <<'PY'\n"
        "from ai_value_scanner.research.short_research_v1 import evaluate_frozen_short_research\n"
        f"evaluate_frozen_short_research('outputs/review_followup_20261106/datasets', "
        f"{portable!r}, scope='{scope}')\n"
        "PY\n"
        "```\n"
    )


def _render_report(
    *,
    scope: str,
    identities: Mapping[str, DatasetIdentity],
    coverage_rows: Sequence[Mapping[str, Any]],
    paired_df: pd.DataFrame,
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
                ["S2-S0", _pct(main.get("s2_minus_s0_mean"))],
                ["S2-S0 95% CI", f"[{_pct(delta_ci.get('ci_low'))}, {_pct(delta_ci.get('ci_high'))}]"],
                ["S2 95% CI", f"[{_pct(s2_ci.get('ci_low'))}, {_pct(s2_ci.get('ci_high'))}]"],
                ["S2-S0 positive date ratio", _pct_plain(main.get("s2_minus_s0_positive_ratio"))],
                ["base cost S2 mean", _pct(cost_means.get("base"))],
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
    lines.extend(["", "## 5. Casebook", ""])
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
            "- Period-end adverse-up is reported; intraperiod maximum adverse excursion is not verified without raw frozen daily paths.",
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
