"""MVP v1.1 offline A0 integrity gate and pre-registered R rank experiments.

No historical outcomes are read by the ranker. Production StockDecision scoring,
states, candidate pool, and default ranking remain unchanged.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from itertools import groupby
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ai_value_scanner.decision.integrated import _priority_sort_key
from ai_value_scanner.decision.model import StockDecision
from ai_value_scanner.evaluation.entry_quality import validate_entry_replay_frame


R_CANDIDATES: dict[str, tuple[float, float, float]] = {
    "R1": (0.80, 0.0, 0.0),
    "R2": (0.70, 0.0, 0.0),
    "R3": (0.60, 0.0, 0.0),
    "R4": (0.70, 0.05, 0.0),
    "R5": (0.70, 0.0, 0.05),
}

RISK_CODES = frozenset({
    "net_debt_to_ebitda_weak",
    "interest_coverage_weak",
    "free_cash_flow_weak",
    "shares_yoy_weak",
    "receivables_growth_gap_weak",
    "inventory_growth_gap_weak",
})


def _valid_unit(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and 0.0 <= number <= 1.0


def _rank_score(decision: StockDecision, candidate_id: str) -> float | None:
    wq, confidence_penalty, risk_penalty = R_CANDIDATES[candidate_id]
    quality, entry = decision.quality, decision.entry
    if not all(_valid_unit(x) for x in (
        quality.score, entry.score, quality.confidence, entry.confidence
    )):
        return None
    risk_flag = bool(RISK_CODES.intersection(item.code for item in quality.risks))
    return (
        wq * float(quality.score)
        + (1.0 - wq) * float(entry.score)
        - confidence_penalty * (1.0 - float(quality.confidence))
        - risk_penalty * int(risk_flag)
    )


def rank_offline(
    decisions: Iterable[StockDecision],
    *,
    candidate_id: str,
) -> tuple[StockDecision, ...]:
    """Rank inside existing Action and Quality-grade groups only.

    Invalid/missing scores sort after complete-score members in their own
    group; their relative order follows canonical v1 (no imputed scores).
    Results have fresh consecutive priorities without mutating input objects.
    """
    if candidate_id != "B0" and candidate_id not in R_CANDIDATES:
        raise ValueError(f"unregistered offline rank candidate: {candidate_id}")
    base = sorted(tuple(decisions), key=_priority_sort_key)
    symbols = [(d.decision_date, d.symbol) for d in base]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate signal_date × symbol decisions")
    if len({d.decision_date for d in base}) > 1:
        raise ValueError("ranking must be performed separately per signal_date")
    if candidate_id == "B0":
        ordered = base
    else:
        ordered: list[StockDecision] = []
        for _, grouped in groupby(base, key=lambda d: _priority_sort_key(d)[:2]):
            same_group = list(grouped)
            def key(d: StockDecision) -> tuple[Any, ...]:
                score = _rank_score(d, candidate_id)
                return (
                    score is None,
                    0.0 if score is None else -score,
                    _priority_sort_key(d)[2:],
                )
            ordered.extend(sorted(same_group, key=key))
    return tuple(replace(d, priority=i) for i, d in enumerate(ordered, 1))


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_frozen_dataset(
    dataset: str | Path,
    *,
    expected_kind: str,
    metadata: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect frozen pre-strategy CSV + same-stem metadata; fail closed.

    This is a STRUCTURAL gate only. It cannot prove SEC filing availability,
    historical ETF membership, price adjustments, or return-label correctness.
    """
    if expected_kind not in {"company_quality", "entry_quality"}:
        raise ValueError("expected_kind must be company_quality or entry_quality")
    path = Path(dataset).expanduser().resolve()
    meta_path = (Path(metadata).expanduser().resolve()
                 if metadata is not None else path.with_suffix(".meta.json"))
    if not path.is_file() or not meta_path.is_file():
        raise ValueError(f"missing dataset or sibling metadata: {path}, {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("dataset metadata must be a JSON object")
    if meta.get("dataset_kind") != expected_kind:
        raise ValueError(f"dataset_kind must be {expected_kind!r}")
    if meta.get("pre_strategy_cross_section") is not True:
        raise ValueError("pre_strategy_cross_section must be true")

    frame = pd.read_csv(path, low_memory=False)
    required = {"signal_date", "symbol", "fundamental_data_asof"}
    if expected_kind == "entry_quality":
        required.add("market_asof")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing historical decision columns: {missing}")
    if frame.empty:
        raise ValueError("empty historical decision dataset")
    symbols = frame["symbol"].astype("string").fillna("").str.strip().str.upper()
    if (symbols == "").any():
        raise ValueError("empty historical symbols")
    dates = pd.to_datetime(frame["signal_date"], errors="coerce", utc=True)
    if dates.isna().any():
        raise ValueError("invalid signal_date")
    if pd.DataFrame({"date": dates, "symbol": symbols}).duplicated().any():
        raise ValueError("duplicate signal_date × normalized symbol")
    for column in ("fundamental_data_asof", "market_asof"):
        if column not in frame:
            continue
        asof = pd.to_datetime(frame[column], errors="coerce", utc=True)
        future = asof.notna() & (asof.dt.normalize() > dates.dt.normalize())
        if future.any():
            raise ValueError(f"{column} contains future as-of observations")
    if expected_kind == "entry_quality":
        validate_entry_replay_frame(frame)

    label_coverage: dict[str, dict[str, int | bool]] = {}
    for horizon in (20, 60, 120):
        ret, benchmark = f"fwd_ret_{horizon}", f"qqq_return_{horizon}"
        present = ret in frame and benchmark in frame
        valid = (
            pd.to_numeric(frame[ret], errors="coerce").notna()
            & pd.to_numeric(frame[benchmark], errors="coerce").notna()
        ) if present else pd.Series(False, index=frame.index)
        label_coverage[str(horizon)] = {
            "columns_present": present,
            "n_paired_valid": int(valid.sum()),
            "n_missing_or_invalid": int((~valid).sum()),
        }
    if meta.get("n_rows") is not None and int(meta["n_rows"]) != len(frame):
        raise ValueError("metadata n_rows disagrees with CSV")
    dates_day = dates.dt.strftime("%Y-%m-%d")
    return {
        "status": "STRUCTURAL_PASS_PIT_AND_LABELS_UNVERIFIED",
        "dataset_kind": expected_kind,
        "dataset_path": str(path),
        "dataset_sha256": _hash(path),
        "metadata_path": str(meta_path),
        "metadata_sha256": _hash(meta_path),
        "n_rows": len(frame),
        "n_symbols": int(symbols.nunique()),
        "n_signal_dates": int(dates_day.nunique()),
        "first_signal_date": str(dates_day.min()),
        "last_signal_date": str(dates_day.max()),
        "n_missing_fundamental_asof": int(frame["fundamental_data_asof"].isna().sum()),
        "n_missing_market_asof": (
            int(frame["market_asof"].isna().sum())
            if "market_asof" in frame else None
        ),
        "label_coverage": label_coverage,
        "provenance": {
            key: meta.get(key, "unknown")
            for key in (
                "code_sha", "config_sha", "watchlist_source",
                "entry_price_mode", "exit_price_mode",
                "trading_cost_bps", "feed",
            )
        },
        "limitations": [
            "Date-level as-of checks do not prove time-of-day filing availability.",
            "SEC filing/entity and corporate-action/forward-label audits remain required.",
            "Historical universe may be union_superset_approx, not true PIT ETF holdings.",
            "No canonical v1 parity or alpha improvement asserted by this gate.",
        ],
    }
