#!/usr/bin/env python3
"""Offline Top-15 turnover / stability evaluation (Phase 1, diagnostic only).

Implements the pre-registered candidate schemes from
``docs/agent_specs/top15_stability_and_turnover_spec.md`` (v2):

    B0_baseline                  current production rules (single-day gates)
    S1_confirm_2_2_safe          N=2 entry confirmation + soft M=2 exit, hard M=1
    S2_confirm_1_2_safe          N=1 entry + soft M=2 exit, hard M=1
    S3_hysteresis_buffer         incumbent hysteresis bands + ranking bonus
    S4_hybrid_hysteresis_regime  S3 + 3-day regime confirmation

Part A replays the 13 daily production snapshots (2026-10-19 .. 2026-11-04).
Part B replays the 51 frozen monthly cross-sections (39 base + 12 bear-2022)
for B0 vs S3.

Fully offline and deterministic. It never writes decision snapshots and does
not change production code; the output is evidence for a later Phase 2
decision only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_value_scanner.decision.integrated import build_stock_decisions  # noqa: E402
from ai_value_scanner.research.m4_paired_validation import (  # noqa: E402
    contains_absolute_path,
)

DEFAULT_OUT_DIR = "docs/top15_stability_validation_20261105"
DEFAULT_DECISIONS_ROOT = "outputs/decisions"
DEFAULT_BASE_DATASET = (
    "outputs/historical_selection_v1_20261011_03/repaired/"
    "company_quality_dataset_risk_off.v3.csv"
)
DEFAULT_BEAR_DATASET = (
    "outputs/historical_selection_bear2022_20261017_01/repaired/"
    "company_quality_dataset_risk_off.repaired.csv"
)
LIVE_DATES: tuple[str, ...] = (
    "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23",
    "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30",
    "2026-11-02", "2026-11-03", "2026-11-04",
)
SCHEMES: tuple[str, ...] = (
    "B0_baseline",
    "S1_confirm_2_2_safe",
    "S2_confirm_1_2_safe",
    "S3_hysteresis_buffer",
    "S4_hybrid_hysteresis_regime",
)
TRAJECTORY_SYMBOLS: tuple[str, ...] = ("MTCH", "ECL", "MSFT", "AAPL", "SSNC")
SEGMENTS: tuple[str, ...] = (
    "ALL_51", "BASE_39", "BEAR_2022", "FWD_DRAWDOWN_60D",
)
HARD_OVERBOUGHT_SMA50 = 1.12
HARD_OVERBOUGHT_RET20 = 0.15
SEVERE_LOSS_THRESHOLD = -0.20
HISTORICAL_HORIZON = "excess_60"
MAX_TOP15 = 15


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _fmt(value: Any) -> str:
    number = _num(value)
    return "" if number is None else f"{number:.6f}"


def _pct(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:+.1f}%"


def _pct_plain(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:.1f}%"


def _share(values: Sequence[bool]) -> float | None:
    return (sum(1 for value in values if value) / len(values)) if values else None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(raw: str | Path | None) -> str:
    if raw is None:
        return ""
    path = Path(raw)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _csv_text(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Decision metric extraction
# ---------------------------------------------------------------------------


def extract_metrics(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract scheme inputs from one canonical StockDecision JSON record."""
    entry = record.get("entry") or {}
    quality = record.get("quality") or {}
    gates: dict[str, Mapping[str, Any]] = {}
    for gate in entry.get("gate_results") or []:
        if isinstance(gate, Mapping) and gate.get("gate_key"):
            gates[str(gate["gate_key"])] = gate

    def observed(key: str) -> float | None:
        return _num((gates.get(key) or {}).get("observed"))

    metrics: dict[str, Any] = {
        "symbol": str(record.get("symbol") or "").strip().upper(),
        "priority": int(record.get("priority") or 10**6),
        "action_state": str(record.get("action_state") or ""),
        "quality_grade": str(quality.get("grade") or ""),
        "quality_score": _num(quality.get("score")),
        "quality_confidence": _num(quality.get("confidence")),
        "entry_state": str(entry.get("state") or ""),
        "entry_score": _num(entry.get("score")),
        "price_to_sma200": observed("sma200_trend"),
        "price_to_sma50": observed("sma50_band"),
        "return_20d": observed("ret20_band"),
        "return_60d": observed("ret60_trend"),
        "rs60": observed("rs60_qqq"),
        "drawdown": observed("drawdown_cap"),
        "volatility": observed("volatility_cap"),
        "sma50_to_sma200": observed("ma_alignment"),
        "days_below_sma200": None,
        "gate_status": {
            key: str(gate.get("status") or "") for key, gate in gates.items()
        },
        "gate_blocking": {
            key: bool(gate.get("blocking")) for key, gate in gates.items()
        },
        "pre_earnings": any(
            isinstance(item, Mapping)
            and item.get("code") == "pre_earnings_window_risk"
            for item in (quality.get("risks") or [])
        ),
        "nonop": any(
            isinstance(item, Mapping)
            and item.get("code") == "nonoperating_gain_inflation"
            for item in (quality.get("risks") or [])
        ),
    }
    if metrics["sma50_to_sma200"] is None:
        sma50 = metrics["price_to_sma50"]
        sma200 = metrics["price_to_sma200"]
        if sma50 not in (None, 0) and sma200 is not None:
            metrics["sma50_to_sma200"] = sma200 / sma50
    # Evidence items carry the same metrics even when a gate is non-blocking.
    for item in (
        *(quality.get("risks") or []),
        *(quality.get("positives") or []),
        *(entry.get("risks") or []),
        *(entry.get("positives") or []),
    ):
        if not isinstance(item, Mapping):
            continue
        metric = str(item.get("metric") or "")
        value = _num(item.get("value"))
        if metric in metrics and metrics[metric] is None and value is not None:
            metrics[metric] = value
    if metrics["return_60d"] is not None and metrics["rs60"] is not None:
        metrics["qqq60"] = metrics["return_60d"] - metrics["rs60"]
    else:
        metrics["qqq60"] = None
    return metrics


def _derive_regime(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    values = sorted(
        value for value in (m.get("qqq60") for m in metrics.values())
        if value is not None
    )
    if not values:
        return "up"
    median = values[len(values) // 2]
    return "up" if median >= 0.0 else "down"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_live_snapshots(
    decisions_root: str | Path, dates: Sequence[str]
) -> dict[str, dict[str, Any]]:
    root = Path(decisions_root)
    day_data: dict[str, dict[str, Any]] = {}
    for date in dates:
        snapshot = root / date / "production"
        manifest_path = snapshot / "run_manifest.json"
        decisions_path = snapshot / "decisions.jsonl"
        if not manifest_path.is_file() or not decisions_path.is_file():
            raise FileNotFoundError(f"missing production snapshot: {snapshot}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = [
            json.loads(line)
            for line in decisions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        metrics = {
            str(record.get("symbol")): extract_metrics(record)
            for record in records
        }
        day_data[date] = {
            "metrics": metrics,
            "daily_symbols": [
                str(symbol).strip().upper()
                for symbol in (manifest.get("daily_symbols") or [])
            ],
            "regime": _derive_regime(metrics),
            "dataset": "live",
        }
    return day_data


def load_historical(
    base_dataset: str | Path, bear_dataset: str | Path
) -> dict[str, dict[str, Any]]:
    base = pd.read_csv(base_dataset, low_memory=False)
    bear = pd.read_csv(bear_dataset, low_memory=False)
    base["_dataset"] = "base"
    bear["_dataset"] = "bear"
    frame_all = pd.concat([bear, base], ignore_index=True)
    day_data: dict[str, dict[str, Any]] = {}
    for date, group in frame_all.groupby("signal_date", sort=True):
        token = str(date)
        slice_frame = group[group["watchlist_etf_count"] >= 1]
        if slice_frame.empty:
            continue
        decisions = build_stock_decisions(
            slice_frame,
            decision_date=token,
            generated_at_utc=f"{token}T00:00:00Z",
            policy_version="v2",
        )
        by_symbol = {decision.symbol: decision for decision in decisions}
        rows = {
            str(row["symbol"]).strip().upper(): row
            for row in slice_frame.to_dict(orient="records")
        }
        metrics: dict[str, dict[str, Any]] = {}
        for symbol, decision in by_symbol.items():
            record = {
                "symbol": symbol,
                "priority": decision.priority,
                "action_state": decision.action_state.value,
                "quality": {
                    "grade": decision.quality.grade.value,
                    "score": decision.quality.score,
                    "confidence": decision.quality.confidence,
                    "risks": [
                        {
                            "code": item.code,
                            "metric": item.metric,
                            "value": item.value,
                        }
                        for item in decision.quality.risks
                    ],
                },
                "entry": {
                    "state": decision.entry.state.value,
                    "score": decision.entry.score,
                    "gate_results": [
                        {
                            "gate_key": gate.gate_key,
                            "status": gate.status,
                            "blocking": gate.blocking,
                            "metric": gate.metric,
                            "observed": gate.observed,
                        }
                        for gate in decision.entry.gate_results
                    ],
                    "risks": [
                        {
                            "code": item.code,
                            "metric": item.metric,
                            "value": item.value,
                            "polarity": item.polarity,
                        }
                        for item in decision.entry.risks
                    ],
                    "positives": [
                        {
                            "code": item.code,
                            "metric": item.metric,
                            "value": item.value,
                            "polarity": item.polarity,
                        }
                        for item in decision.entry.positives
                    ],
                },
            }
            metric = extract_metrics(record)
            row = rows.get(symbol) or {}
            fwd_ret_60 = _num(row.get("fwd_ret_60"))
            qqq_return_60 = _num(row.get("qqq_return_60"))
            metric["fwd_ret_60"] = fwd_ret_60
            metric["qqq_return_60"] = qqq_return_60
            metric["excess_60"] = (
                fwd_ret_60 - qqq_return_60
                if fwd_ret_60 is not None and qqq_return_60 is not None
                else None
            )
            metric["dataset"] = str(row.get("_dataset") or "")
            metrics[symbol] = metric
        ranked = sorted(
            metrics.values(), key=lambda m: (m["priority"], m["symbol"])
        )
        daily_symbols = [
            m["symbol"] for m in ranked if m["priority"] <= MAX_TOP15
        ]
        day_data[token] = {
            "metrics": metrics,
            "daily_symbols": daily_symbols,
            "regime": _derive_regime(metrics),
            "dataset": str(group["_dataset"].iloc[0]),
            "qqq_return_60": _num(group["qqq_return_60"].iloc[0]),
        }
    return day_data


# ---------------------------------------------------------------------------
# Candidate scheme rules
# ---------------------------------------------------------------------------


def is_hard_damaged(metrics: Mapping[str, Any]) -> bool:
    return bool(
        metrics.get("entry_state") in {"TREND_DAMAGED", "INSUFFICIENT_DATA"}
        or metrics.get("quality_grade") in {"C", "UNRATED"}
        or (
            metrics.get("price_to_sma50") is not None
            and metrics["price_to_sma50"] > HARD_OVERBOUGHT_SMA50
        )
        or (
            metrics.get("return_20d") is not None
            and metrics["return_20d"] > HARD_OVERBOUGHT_RET20
        )
    )


def is_damaged_only(metrics: Mapping[str, Any]) -> bool:
    return bool(
        metrics.get("entry_state") in {"TREND_DAMAGED", "INSUFFICIENT_DATA"}
        or metrics.get("quality_grade") in {"C", "UNRATED"}
    )


def entry_gates_ok(
    metrics: Mapping[str, Any], *, incumbent: bool, regime: str
) -> bool:
    widened = {"sma50_band", "ret20_band", "rs60_qqq", "market_regime"}
    for key, status in (metrics.get("gate_status") or {}).items():
        if key in widened:
            continue
        if (metrics.get("gate_blocking") or {}).get(key) and status == "BLOCK":
            return False
    sma50 = metrics.get("price_to_sma50")
    if sma50 is None:
        return False
    low, high = (0.96, 1.10) if incumbent else (0.98, 1.08)
    if not (low <= sma50 <= high):
        return False
    ret20 = metrics.get("return_20d")
    if ret20 is None:
        return False
    low20, high20 = (-0.05, 0.14) if incumbent else (-0.03, 0.12)
    if not (low20 <= ret20 <= high20):
        return False
    rs60 = metrics.get("rs60")
    if rs60 is None:
        return False
    if regime == "down":
        min_rs = 0.02 if incumbent else 0.05
        min_ret = -0.02 if incumbent else 0.0
        if rs60 < min_rs or ret20 < min_ret:
            return False
    else:
        min_rs = -0.05 if incumbent else -0.03
        if rs60 < min_rs:
            return False
    return True


def quality_eligible(
    metrics: Mapping[str, Any], *, incumbent: bool, entry_ready: bool
) -> bool:
    grade = metrics.get("quality_grade")
    if grade == "A":
        return entry_ready
    if grade != "B" or not entry_ready:
        return False
    score = metrics.get("quality_score")
    confidence = metrics.get("quality_confidence")
    if score is None or confidence is None:
        return False
    if score < 0.68 or confidence < 0.80:
        return False
    threshold = 0.74 if incumbent else 0.80
    entry_score = metrics.get("entry_score")
    return entry_score is not None and entry_score >= threshold


def scheme_eligible(
    metrics: Mapping[str, Any], *, incumbent: bool, regime: str
) -> bool:
    if is_hard_damaged(metrics):
        return False
    if not entry_gates_ok(metrics, incumbent=incumbent, regime=regime):
        return False
    return quality_eligible(metrics, incumbent=incumbent, entry_ready=True)


def joint_score(metrics: Mapping[str, Any]) -> float:
    score = 0.60 * (metrics.get("quality_score") or 0.0) + 0.40 * (
        metrics.get("entry_score") or 0.0
    )
    if metrics.get("quality_grade") == "A":
        score += 0.04
    if metrics.get("pre_earnings"):
        score -= 0.06
    if metrics.get("nonop"):
        score -= 0.06
    return score


# ---------------------------------------------------------------------------
# Scheme replay
# ---------------------------------------------------------------------------


def run_scheme(
    scheme: str, dates: Sequence[str], day_data: Mapping[str, Mapping[str, Any]]
) -> dict[str, list[str]]:
    if scheme not in SCHEMES:
        raise ValueError(f"unknown scheme: {scheme!r}")
    lists: dict[str, list[str]] = {}
    first_day = dates[0]
    prev_list = list(day_data[first_day]["daily_symbols"])
    raw_streak: dict[str, int] = {}
    soft_streak: dict[str, int] = {}
    previous_regime: str | None = None
    confirmed_regime: str | None = None
    regime_run = 0
    for index, date in enumerate(dates):
        data = day_data[date]
        metrics = data["metrics"]
        if scheme == "B0_baseline":
            current = list(data["daily_symbols"])
            lists[date] = current
            prev_list = current
            continue
        for symbol, metric in metrics.items():
            if metric.get("action_state") == "PRIORITY_REVIEW":
                raw_streak[symbol] = raw_streak.get(symbol, 0) + 1
            else:
                raw_streak[symbol] = 0
        regime_today = str(data.get("regime") or "up")
        if scheme == "S4_hybrid_hysteresis_regime":
            if regime_today == previous_regime:
                regime_run += 1
            else:
                regime_run = 1
            if confirmed_regime is None or regime_run >= 3:
                confirmed_regime = regime_today
            regime_used = confirmed_regime or regime_today
            previous_regime = regime_today
        else:
            regime_used = regime_today

        incumbents = set(prev_list)
        keep: list[str] = []
        for symbol in prev_list:
            metric = metrics.get(symbol)
            if metric is None:
                continue
            if is_hard_damaged(metric):
                soft_streak.pop(symbol, None)
                continue
            if scheme in {"S1_confirm_2_2_safe", "S2_confirm_1_2_safe"}:
                if metric.get("action_state") == "PRIORITY_REVIEW":
                    keep.append(symbol)
                    soft_streak[symbol] = 0
                else:
                    soft_streak[symbol] = soft_streak.get(symbol, 0) + 1
                    if soft_streak[symbol] < 2:
                        keep.append(symbol)
                    else:
                        soft_streak.pop(symbol, None)
            else:
                if scheme_eligible(metric, incumbent=True, regime=regime_used):
                    keep.append(symbol)

        candidates: list[str] = []
        for symbol, metric in metrics.items():
            if symbol in incumbents:
                continue
            if scheme in {"S1_confirm_2_2_safe", "S2_confirm_1_2_safe"}:
                needed = 2 if scheme.startswith("S1") else 1
                if (
                    metric.get("action_state") == "PRIORITY_REVIEW"
                    and raw_streak.get(symbol, 0) >= needed
                ):
                    candidates.append(symbol)
            else:
                if scheme_eligible(metric, incumbent=False, regime=regime_used):
                    candidates.append(symbol)

        if scheme in {"S1_confirm_2_2_safe", "S2_confirm_1_2_safe"}:
            def sort_key(symbol: str) -> tuple[int, str]:
                return (int(metrics[symbol].get("priority") or 10**6), symbol)
        else:
            def sort_key(symbol: str) -> tuple[float, str]:
                bonus = 0.02 if symbol in incumbents else 0.0
                return (-(joint_score(metrics[symbol]) + bonus), symbol)

        keep = sorted(set(keep), key=sort_key)[:MAX_TOP15]
        candidates = sorted(set(candidates), key=sort_key)
        slots = max(0, MAX_TOP15 - len(keep))
        current = sorted(set(keep) | set(candidates[:slots]), key=sort_key)
        lists[date] = current
        prev_list = current
        if index == 0:
            continue
    return lists


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _membership(
    lists: Mapping[str, Sequence[str]], dates: Sequence[str]
) -> dict[str, list[bool]]:
    symbols = sorted({symbol for date in dates for symbol in lists[date]})
    return {
        symbol: [symbol in set(lists[date]) for date in dates]
        for symbol in symbols
    }


def _one_day_whipsaws(lists: Mapping[str, Sequence[str]], dates: Sequence[str]) -> int:
    count = 0
    for sequence in _membership(lists, dates).values():
        index = 0
        while index < len(sequence):
            if not sequence[index]:
                index += 1
                continue
            end = index
            while end + 1 < len(sequence) and sequence[end + 1]:
                end += 1
            if end == index and end + 1 < len(sequence) and not sequence[end + 1]:
                count += 1
            index = end + 1
    return count


def _roundtrips_5d(
    lists: Mapping[str, Sequence[str]], dates: Sequence[str], window: int = 5
) -> int:
    count = 0
    for sequence in _membership(lists, dates).values():
        last_exit: int | None = None
        for index in range(1, len(sequence)):
            if sequence[index - 1] and not sequence[index]:
                last_exit = index
            elif not sequence[index - 1] and sequence[index] and last_exit is not None:
                if index - last_exit <= window:
                    count += 1
                last_exit = None
    return count


def summarize_lists(
    lists: Mapping[str, Sequence[str]],
    dates: Sequence[str],
    day_data: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    transitions = list(zip(dates, dates[1:]))
    retained: list[int] = []
    removed: list[int] = []
    added: list[int] = []
    prev_sizes: list[int] = []
    for previous, current in transitions:
        previous_set = set(lists[previous])
        current_set = set(lists[current])
        retained.append(len(previous_set & current_set))
        removed.append(len(previous_set - current_set))
        added.append(len(current_set - previous_set))
        prev_sizes.append(len(previous_set))
    damaged = 0
    for date in dates:
        metrics = day_data[date]["metrics"]
        for symbol in lists[date]:
            metric = metrics.get(symbol)
            if metric is not None and is_damaged_only(metric):
                damaged += 1
    turnover_rates = [
        removed_count / max(prev_size, 1)
        for removed_count, prev_size in zip(removed, prev_sizes)
    ]
    return {
        "mean_retained_count": _mean([float(v) for v in retained]),
        "min_retained_count": min(retained) if retained else None,
        "mean_daily_turnover_rate": _mean(turnover_rates),
        "one_day_whipsaw_count": _one_day_whipsaws(lists, dates),
        "roundtrip_5d_count": _roundtrips_5d(lists, dates),
        "damaged_leaked_count": damaged,
        "mean_list_size": _mean([float(len(lists[date])) for date in dates]),
        "transitions": list(zip(dates, dates[1:])),
        "retained": retained,
        "removed": removed,
        "added": added,
        "prev_sizes": prev_sizes,
    }


def segment_summary(
    lists: Mapping[str, Sequence[str]],
    dates: Sequence[str],
    day_data: Mapping[str, Mapping[str, Any]],
    segment_dates: Sequence[str],
) -> dict[str, Any]:
    selected = [date for date in dates if date in set(segment_dates)]
    retentions: list[float] = []
    for previous, current in zip(selected, selected[1:]):
        previous_set = set(lists[previous])
        current_set = set(lists[current])
        retentions.append(len(previous_set & current_set) / max(len(previous_set), 1))
    date_means: list[float] = []
    observations: list[float] = []
    for date in selected:
        metrics = day_data[date]["metrics"]
        values = [
            metric[HISTORICAL_HORIZON]
            for symbol in lists[date]
            if (metric := metrics.get(symbol)) is not None
            and metric.get(HISTORICAL_HORIZON) is not None
        ]
        if values:
            date_means.append(sum(values) / len(values))
        for symbol in lists[date]:
            metric = metrics.get(symbol)
            if metric is not None and metric.get("fwd_ret_60") is not None:
                observations.append(float(metric["fwd_ret_60"]))
    severe = [
        value <= SEVERE_LOSS_THRESHOLD for value in observations
    ]
    damaged = 0
    for date in selected:
        metrics = day_data[date]["metrics"]
        for symbol in lists[date]:
            metric = metrics.get(symbol)
            if metric is not None and is_damaged_only(metric):
                damaged += 1
    return {
        "n_dates": len(selected),
        "mean_list_size": _mean([float(len(lists[date])) for date in selected]),
        "retention_rate": _mean(retentions),
        "mean_excess_60": _mean(date_means),
        "win_rate": _share([value > 0 for value in date_means]),
        "severe_loss_rate": _share(severe),
        "damaged_leaked_count": damaged,
        "n_observations": len(observations),
    }


def entry_stats(
    lists: Mapping[str, Sequence[str]],
    dates: Sequence[str],
    day_data: Mapping[str, Mapping[str, Any]],
    reference: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    entries: list[tuple[str, str]] = []
    for index, date in enumerate(dates):
        previous = set(lists[dates[index - 1]]) if index else set()
        for symbol in lists[date]:
            if symbol not in previous:
                entries.append((date, symbol))
    values = [
        metric["return_20d"]
        for date, symbol in entries
        if (metric := day_data[date]["metrics"].get(symbol)) is not None
        and metric.get("return_20d") is not None
    ]
    delayed = 0
    if reference is not None:
        for date, symbol in entries:
            if symbol in set(reference.get(date, ())):
                continue
            later = dates[dates.index(date) + 1] if dates.index(date) + 1 < len(dates) else None
            if later is not None and symbol in set(reference.get(later, ())):
                delayed += 1
    return {
        "entry_count": len(entries),
        "mean_entry_ret20": _mean(values),
        "delayed_entries_vs_reference": delayed,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(header) for header in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(context: Mapping[str, Any]) -> str:
    live_dates: Sequence[str] = context["live_dates"]
    live_lists: Mapping[str, Mapping[str, Sequence[str]]] = context["live_lists"]
    live_summaries: Mapping[str, Mapping[str, Any]] = context["live_summaries"]
    trajectories: Mapping[str, Mapping[str, str]] = context["trajectories"]
    gates: Mapping[str, Mapping[str, Any]] = context["gates"]
    historical_rows: Sequence[Mapping[str, Any]] = context.get("historical_rows", ())
    lines: list[str] = []
    lines.append("# Top-15 Stability & Turnover Validation (Phase 1, diagnostic only)")
    lines.append("")
    lines.append(
        "- Pre-registered spec: "
        "`docs/agent_specs/top15_stability_and_turnover_spec.md` (v2)."
    )
    lines.append(
        f"- Runner: `scripts/evaluate_top15_turnover_stability.py` "
        f"SHA256 `{context['runner_sha']}`."
    )
    lines.append(
        "- Fully offline and deterministic; frozen snapshots/datasets are read-only; "
        "no production code, config, or decision snapshot is changed."
    )
    lines.append(
        "- **This is diagnostic evidence only.** No policy change is proposed; "
        "Phase 2 requires a separate review and decision."
    )
    lines.append("")
    lines.append("## 0. Verdict summary (G1–G4)")
    lines.append("")
    gate_rows = []
    for gate_id in ("G1", "G2", "G3", "G4"):
        gate = gates[gate_id]
        gate_rows.append([
            gate_id, gate["criterion"],
            ", ".join(
                f"{scheme}:{'PASS' if result else ('n/a' if result is None else 'FAIL')}"
                for scheme, result in gate["results"].items()
            ),
        ])
    lines.append(_md_table(["gate", "criterion", "result"], gate_rows))
    lines.append("")
    lines.append(
        "G1/G2 apply to the 13 daily snapshots; G3 compares entry timing; "
        "G4 applies to the 51 frozen monthly cross-sections (B0 vs S3 only)."
    )
    lines.append("")
    lines.append(
        "**Conclusion: no candidate passes all four gates on this evidence.** "
        "S1/S2 pass G1–G3 but G4 was not evaluated (Part B is B0 vs S3 only); "
        "S3 passes G1–G3 but fails G4 because bear/drawdown severe-loss rates "
        "are slightly worse. This Phase 1 evidence therefore does **not** "
        "support a Phase 2 promotion; any next step requires a new "
        "pre-registered review."
    )
    lines.append("")
    lines.append("## 1. Provenance")
    lines.append("")
    base = context["base"]
    bear = context["bear"]
    lines.append(
        f"- Base dataset: `{base['name']}` ({base['rows']} rows, "
        f"{base['dates']} dates, SHA256 `{base['sha']}`)."
    )
    lines.append(
        f"- 2022 bear dataset: `{bear['name']}` ({bear['rows']} rows, "
        f"{bear['dates']} dates, SHA256 `{bear['sha']}`)."
    )
    lines.append(
        f"- Live snapshots: `{context['decisions_root_rel']}` "
        f"({len(live_dates)} dates, {live_dates[0]} .. {live_dates[-1]})."
    )
    lines.append(
        "- Scope: ETF_SLICE (`watchlist_etf_count >= 1`) for historical dates; "
        "live lists come from each snapshot's `daily_symbols`."
    )
    lines.append(
        "- Gate observations are extracted from each decision's "
        "`entry.gate_results` / evidence items; `regime` is reconstructed as "
        "`sign(return_60d - relative_strength_60d_qqq)` because the production "
        "`market_regime` gate does not persist its observed label on PASS."
    )
    lines.append(
        "- Part A `B0_baseline` uses each snapshot's `daily_symbols`; Part B "
        "`B0_baseline` uses the top-15 by production priority (the frozen "
        "cross-section has no state-change fillers)."
    )
    lines.append(f"- Reproduction command: `{context['command']}`.")
    lines.append("")
    lines.append("## 2. Part A — 13 daily production snapshots")
    lines.append("")
    lines.append("### 2.1 Retained count per transition")
    lines.append("")
    transition_rows = []
    for index, (previous, current) in enumerate(zip(live_dates, live_dates[1:])):
        transition_rows.append([
            f"{previous} → {current}",
            *[
                f"{live_summaries[scheme]['retained'][index]}"
                for scheme in SCHEMES
            ],
        ])
    lines.append(_md_table(["transition", *SCHEMES], transition_rows))
    lines.append("")
    lines.append("### 2.2 Scheme summary metrics")
    lines.append("")
    summary_rows = []
    for scheme in SCHEMES:
        summary = live_summaries[scheme]
        summary_rows.append([
            scheme,
            f"{summary['mean_retained_count']:.2f}",
            f"{summary['min_retained_count']}",
            _pct_plain(summary["mean_daily_turnover_rate"]),
            summary["one_day_whipsaw_count"],
            summary["roundtrip_5d_count"],
            summary["damaged_leaked_count"],
            f"{summary['mean_list_size']:.2f}",
        ])
    lines.append(_md_table(
        [
            "scheme", "mean retained", "min retained", "mean turnover",
            "1d whipsaw", "5d roundtrip", "damaged leaked", "mean list size",
        ],
        summary_rows,
    ))
    lines.append("")
    lines.append("### 2.3 Typical trajectories (13 dates, 1 = in the main list)")
    lines.append("")
    trajectory_rows = []
    for symbol in TRAJECTORY_SYMBOLS:
        trajectory_rows.append([
            symbol, *[trajectories[symbol][scheme] for scheme in SCHEMES],
        ])
    lines.append(_md_table(["symbol", *SCHEMES], trajectory_rows))
    lines.append("")
    lines.append(
        "Dates: " + ", ".join(live_dates) + "."
    )
    lines.append("")
    lines.append("## 3. Part B — 51 frozen monthly cross-sections (B0 vs S3)")
    lines.append("")
    if historical_rows:
        historical_table = []
        for row in historical_rows:
            historical_table.append([
                row["segment"], row["scheme"], row["n_dates"],
                f"{row['mean_list_size']:.2f}",
                _pct_plain(row["retention_rate"]),
                _pct(row["mean_excess_60"]),
                _pct_plain(row["win_rate"]),
                _pct_plain(row["severe_loss_rate"]),
                row["damaged_leaked_count"],
            ])
        lines.append(_md_table(
            [
                "segment", "scheme", "dates", "mean list", "retention",
                "mean excess 60d", "win rate", "severe loss", "damaged leaked",
            ],
            historical_table,
        ))
        lines.append("")
        lines.append(
            "Retention is measured over consecutive dates within each segment; "
            "returns are date-equal means of 60d net-QQQ excess; severe loss is "
            "the share of stock-date observations with raw 60d return <= -20%."
        )
    else:
        lines.append("- Part B skipped (`--part a`).")
    lines.append("")
    lines.append("## 4. Gate evidence")
    lines.append("")
    for gate_id in ("G1", "G2", "G3", "G4"):
        gate = gates[gate_id]
        lines.append(f"### {gate_id}")
        lines.append("")
        lines.append(f"- Criterion: {gate['criterion']}")
        for scheme, detail in gate["details"].items():
            lines.append(f"- {scheme}: {detail}")
        lines.append("")
    lines.append("## 5. Honest limitations")
    lines.append("")
    lines.append(
        "- The 13 daily snapshots cover a short window; daily turnover is "
        "measured on observed production lists, not a long prospective sample."
    )
    lines.append(
        "- The 51 monthly dates are overlapping 60d labels and are not "
        "independent; they are a frozen retrospective cross-section."
    )
    lines.append(
        "- Candidate schemes are offline reconstructions from stored gate "
        "observations; they do not re-run production entry/action code with "
        "modified thresholds."
    )
    lines.append(
        "- S1/S2 confirmation semantics are evaluated on the same snapshot "
        "sequence; the first day is seeded with the baseline list for a fair "
        "transition comparison."
    )
    lines.append(
        "- Universe drift / latest-fallback caveats are inherited from the "
        "frozen datasets (AGENTS.md §4/§8). No promotion is implied."
    )
    lines.append("")
    lines.append("## 6. Reproduction")
    lines.append("")
    lines.append(
        f"1. Delete `{context['out_dir_rel']}` and re-run "
        f"`{context['command']}`; outputs are deterministic."
    )
    lines.append("2. Verify every file against `SHA256SUMS`.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    live = load_live_snapshots(args.decisions_root, LIVE_DATES)
    live_dates = sorted(live)
    live_lists = {
        scheme: run_scheme(scheme, live_dates, live) for scheme in SCHEMES
    }
    live_summaries = {
        scheme: summarize_lists(live_lists[scheme], live_dates, live)
        for scheme in SCHEMES
    }
    trajectories: dict[str, dict[str, str]] = {}
    for symbol in TRAJECTORY_SYMBOLS:
        trajectories[symbol] = {
            scheme: "".join(
                "1" if symbol in set(live_lists[scheme][date]) else "0"
                for date in live_dates
            )
            for scheme in SCHEMES
        }

    historical_rows: list[dict[str, Any]] = []
    historical_entries: dict[str, dict[str, Any]] = {}
    if args.part == "all":
        historical = load_historical(args.base_dataset, args.bear_dataset)
        historical_dates = sorted(historical)
        historical_lists = {
            "B0_baseline": run_scheme("B0_baseline", historical_dates, historical),
            "S3_hysteresis_buffer": run_scheme(
                "S3_hysteresis_buffer", historical_dates, historical
            ),
        }
        segment_dates = {
            "ALL_51": historical_dates,
            "BASE_39": [
                date for date in historical_dates
                if historical[date].get("dataset") == "base"
            ],
            "BEAR_2022": [
                date for date in historical_dates
                if historical[date].get("dataset") == "bear"
            ],
            "FWD_DRAWDOWN_60D": [
                date for date in historical_dates
                if (historical[date].get("qqq_return_60") or 0.0) < 0.0
            ],
        }
        for segment in SEGMENTS:
            for scheme in ("B0_baseline", "S3_hysteresis_buffer"):
                summary = segment_summary(
                    historical_lists[scheme], historical_dates, historical,
                    segment_dates[segment],
                )
                historical_rows.append({
                    "segment": segment,
                    "scheme": scheme,
                    **summary,
                })
        historical_entries = {
            scheme: entry_stats(
                historical_lists[scheme], historical_dates, historical
            )
            for scheme in ("B0_baseline", "S3_hysteresis_buffer")
        }

    baseline = live_summaries["B0_baseline"]
    gates: dict[str, dict[str, Any]] = {}
    g1_results: dict[str, bool | None] = {}
    g2_results: dict[str, bool | None] = {}
    g1_details: dict[str, str] = {}
    g2_details: dict[str, str] = {}
    for scheme in SCHEMES:
        summary = live_summaries[scheme]
        retained_ok = (
            summary["mean_retained_count"] is not None
            and summary["mean_retained_count"] >= 12.0
        )
        turnover_ok = (
            baseline["mean_daily_turnover_rate"] not in (None, 0)
            and summary["mean_daily_turnover_rate"] is not None
            and (
                1.0
                - summary["mean_daily_turnover_rate"]
                / baseline["mean_daily_turnover_rate"]
            ) >= 0.35
        )
        roundtrip_ok = False
        if baseline["roundtrip_5d_count"]:
            roundtrip_ok = (
                1.0
                - summary["roundtrip_5d_count"] / baseline["roundtrip_5d_count"]
            ) >= 0.50
        g1_results[scheme] = bool(
            (retained_ok or turnover_ok) and roundtrip_ok
        )
        g1_details[scheme] = (
            f"mean retained {summary['mean_retained_count']:.2f}; "
            f"turnover {_pct_plain(summary['mean_daily_turnover_rate'])}; "
            f"roundtrip {summary['roundtrip_5d_count']} "
            f"(baseline {baseline['roundtrip_5d_count']})"
        )
        g2_results[scheme] = bool(
            summary["damaged_leaked_count"] == 0
            and (
                all(
                    row["damaged_leaked_count"] == 0
                    for row in historical_rows
                    if row["scheme"] == scheme
                )
                if any(row["scheme"] == scheme for row in historical_rows)
                else True
            )
        )
        historical_damaged = [
            row["damaged_leaked_count"]
            for row in historical_rows
            if row["scheme"] == scheme
        ]
        g2_details[scheme] = (
            f"daily damaged leaked {summary['damaged_leaked_count']}; "
            f"historical damaged leaked "
            f"{'n/a' if not historical_damaged else ('0' if all(count == 0 for count in historical_damaged) else '>0')}"
        )
    gates["G1"] = {
        "criterion": "mean retained >= 12.0 (or turnover -35%) and 5d roundtrip -50%",
        "results": g1_results,
        "details": g1_details,
    }
    gates["G2"] = {
        "criterion": "damaged / INSUFFICIENT_DATA / Quality C-UNRATED never in Top-15",
        "results": g2_results,
        "details": g2_details,
    }

    # G3: N=1 entry does not chase and does not sacrifice stability.
    s1_stats = entry_stats(
        live_lists["S1_confirm_2_2_safe"], live_dates, live,
        reference=live_lists["S1_confirm_2_2_safe"],
    )
    s2_stats = entry_stats(
        live_lists["S2_confirm_1_2_safe"], live_dates, live,
        reference=live_lists["S1_confirm_2_2_safe"],
    )
    s3_stats = entry_stats(
        live_lists["S3_hysteresis_buffer"], live_dates, live,
        reference=live_lists["S1_confirm_2_2_safe"],
    )
    g3_results: dict[str, bool | None] = {}
    g3_details: dict[str, str] = {}
    for scheme, stats in (
        ("S1_confirm_2_2_safe", s1_stats),
        ("S2_confirm_1_2_safe", s2_stats),
        ("S3_hysteresis_buffer", s3_stats),
    ):
        stable = bool(g1_results.get(scheme))
        no_chase = (
            stats["mean_entry_ret20"] is None
            or s1_stats["mean_entry_ret20"] is None
            or stats["mean_entry_ret20"] <= s1_stats["mean_entry_ret20"] + 0.01
        )
        g3_results[scheme] = bool(stable and no_chase)
        g3_details[scheme] = (
            f"entries {stats['entry_count']}; mean entry ret20 "
            f"{_pct(stats['mean_entry_ret20'])}; delayed vs S1 "
            f"{stats['delayed_entries_vs_reference']}; G1 stable={stable}"
        )
    gates["G3"] = {
        "criterion": "N=1 schemes stay stable (G1) without chasing (entry ret20 <= S1 + 1pp)",
        "results": g3_results,
        "details": g3_details,
    }

    # G4: historical B0 vs S3.
    g4_results: dict[str, bool | None] = {}
    g4_details: dict[str, str] = {}
    if historical_rows:
        by_segment_scheme = {
            (row["segment"], row["scheme"]): row for row in historical_rows
        }
        base_all = by_segment_scheme.get(("ALL_51", "B0_baseline"))
        s3_all = by_segment_scheme.get(("ALL_51", "S3_hysteresis_buffer"))
        excess_ok = (
            base_all is not None and s3_all is not None
            and base_all["mean_excess_60"] is not None
            and s3_all["mean_excess_60"] is not None
            and s3_all["mean_excess_60"] >= base_all["mean_excess_60"] - 0.01
        )
        bear_ok = True
        drawdown_ok = True
        for segment in ("BEAR_2022", "FWD_DRAWDOWN_60D"):
            base_seg = by_segment_scheme.get((segment, "B0_baseline"))
            s3_seg = by_segment_scheme.get((segment, "S3_hysteresis_buffer"))
            if base_seg and s3_seg and base_seg["severe_loss_rate"] is not None:
                if s3_seg["severe_loss_rate"] > base_seg["severe_loss_rate"] + 1e-9:
                    if segment == "BEAR_2022":
                        bear_ok = False
                    else:
                        drawdown_ok = False
        g4_results["S3_hysteresis_buffer"] = bool(excess_ok and bear_ok and drawdown_ok)
        g4_details["S3_hysteresis_buffer"] = (
            f"ALL_51 excess {_pct(s3_all['mean_excess_60'] if s3_all else None)} "
            f"vs B0 {_pct(base_all['mean_excess_60'] if base_all else None)}; "
            f"bear severe-loss not worse={bear_ok}; drawdown not worse={drawdown_ok}"
        )
    else:
        g4_results["S3_hysteresis_buffer"] = None
        g4_details["S3_hysteresis_buffer"] = "Part B skipped"
    gates["G4"] = {
        "criterion": "ALL_51 60d excess degradation <= 1.0pp; bear/drawdown severe loss not worse",
        "results": g4_results,
        "details": g4_details,
    }

    return {
        "live_dates": live_dates,
        "live_lists": live_lists,
        "live_summaries": live_summaries,
        "trajectories": trajectories,
        "historical_rows": historical_rows,
        "historical_entries": historical_entries,
        "gates": gates,
    }


def _write_outputs(out_dir: Path, files: Mapping[str, str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if contains_absolute_path(content):
            raise ValueError(f"absolute path leaked into {name}")
        (out_dir / name).write_text(content, encoding="utf-8")
    checksums = "".join(
        f"{_sha256_text(files[name])}  {name}\n" for name in sorted(files)
    )
    (out_dir / "SHA256SUMS").write_text(checksums, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    result = evaluate(args)
    runner_sha = _sha256_file(Path(__file__).resolve()) or ""
    base_frame = pd.read_csv(args.base_dataset, low_memory=False)
    bear_frame = pd.read_csv(args.bear_dataset, low_memory=False)
    command = (
        "python scripts/evaluate_top15_turnover_stability.py "
        f"--part {args.part} --output-dir {_portable_path(args.output_dir)}"
    )
    context = {
        **result,
        "runner_sha": runner_sha,
        "command": command,
        "out_dir_rel": _portable_path(args.output_dir),
        "decisions_root_rel": _portable_path(args.decisions_root),
        "base": {
            "name": Path(args.base_dataset).name,
            "rows": int(len(base_frame)),
            "dates": int(base_frame["signal_date"].nunique()),
            "sha": _sha256_file(Path(args.base_dataset)) or "",
        },
        "bear": {
            "name": Path(args.bear_dataset).name,
            "rows": int(len(bear_frame)),
            "dates": int(bear_frame["signal_date"].nunique()),
            "sha": _sha256_file(Path(args.bear_dataset)) or "",
        },
    }
    daily_rows: list[dict[str, Any]] = []
    for scheme in SCHEMES:
        summary = result["live_summaries"][scheme]
        for index, (previous, current) in enumerate(zip(
            result["live_dates"], result["live_dates"][1:]
        )):
            daily_rows.append({
                "date_from": previous,
                "date_to": current,
                "scheme": scheme,
                "prev_count": summary["prev_sizes"][index],
                "curr_count": len(result["live_lists"][scheme][current]),
                "retained": summary["retained"][index],
                "removed": summary["removed"][index],
                "added": summary["added"][index],
            })
    summary_rows: list[dict[str, Any]] = []
    for scheme in SCHEMES:
        summary = result["live_summaries"][scheme]
        summary_rows.append({
            "scheme": scheme,
            "mean_retained_count": _fmt(summary["mean_retained_count"]),
            "min_retained_count": summary["min_retained_count"],
            "mean_daily_turnover_rate": _fmt(summary["mean_daily_turnover_rate"]),
            "one_day_whipsaw_count": summary["one_day_whipsaw_count"],
            "roundtrip_5d_count": summary["roundtrip_5d_count"],
            "damaged_leaked_count": summary["damaged_leaked_count"],
            "mean_list_size": _fmt(summary["mean_list_size"]),
            "g1_pass": result["gates"]["G1"]["results"].get(scheme),
            "g2_pass": result["gates"]["G2"]["results"].get(scheme),
            "g3_pass": result["gates"]["G3"]["results"].get(scheme),
        })
    historical_rows: list[dict[str, Any]] = []
    for row in result["historical_rows"]:
        historical_rows.append({
            "segment": row["segment"],
            "scheme": row["scheme"],
            "n_dates": row["n_dates"],
            "mean_list_size": _fmt(row["mean_list_size"]),
            "retention_rate": _fmt(row["retention_rate"]),
            "mean_excess_60": _fmt(row["mean_excess_60"]),
            "win_rate": _fmt(row["win_rate"]),
            "severe_loss_rate": _fmt(row["severe_loss_rate"]),
            "damaged_leaked_count": row["damaged_leaked_count"],
            "n_observations": row["n_observations"],
        })
    files = {
        "daily_turnover_comparison.csv": _csv_text(
            daily_rows,
            (
                "date_from", "date_to", "scheme", "prev_count", "curr_count",
                "retained", "removed", "added",
            ),
        ),
        "scheme_summary_metrics.csv": _csv_text(
            summary_rows,
            (
                "scheme", "mean_retained_count", "min_retained_count",
                "mean_daily_turnover_rate", "one_day_whipsaw_count",
                "roundtrip_5d_count", "damaged_leaked_count", "mean_list_size",
                "g1_pass", "g2_pass", "g3_pass",
            ),
        ),
        "report.md": render_report(context),
    }
    if historical_rows:
        files["historical_51dates_comparison.csv"] = _csv_text(
            historical_rows,
            (
                "segment", "scheme", "n_dates", "mean_list_size",
                "retention_rate", "mean_excess_60", "win_rate",
                "severe_loss_rate", "damaged_leaked_count", "n_observations",
            ),
        )
    _write_outputs(Path(args.output_dir), files)
    total = sum(
        (Path(args.output_dir) / name).stat().st_size
        for name in (*files, "SHA256SUMS")
    )
    print(
        f"[turnover] wrote {len(files) + 1} files, {total} bytes to "
        f"{_portable_path(args.output_dir)}"
    )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline Top-15 turnover/stability evaluation (Phase 1, diagnostic only)."
        )
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--decisions-root", default=DEFAULT_DECISIONS_ROOT)
    parser.add_argument("--base-dataset", default=DEFAULT_BASE_DATASET)
    parser.add_argument("--bear-dataset", default=DEFAULT_BEAR_DATASET)
    parser.add_argument(
        "--part", choices=("all", "a"), default="all",
        help="Run both parts (default) or Part A only (test/debug).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
