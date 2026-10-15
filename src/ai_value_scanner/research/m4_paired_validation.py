"""Phase M4 dual-track paired validation (pure module, no I/O, no network).

Track 1 (human utility & explainability) and Track 2 (paired economic
outcomes on DEV_2023_2024 / POST2024_HELD_OUT / ALL_39_DATES) plus Track 3
Gate G4/G5 promotion rules. Forward returns are aggregated date-equal;
period membership is explicit so the 2025/2026Q1 embargo is structural.

The per-date batch evaluator calls the frozen production builders
read-only and replicates the production ranking keys exactly (verified
against build_stock_decisions in unit tests); it skips per-row provenance
hashing so a full 39-date x 5-variant pass fits the CLI time budget.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from ai_value_scanner.decision.action import (
    _ACTION_ORDER_V2 as _H3_ACTION_ORDER,
)
from ai_value_scanner.decision.action import (
    _QUALITY_ORDER_V2 as _H3_QUALITY_ORDER,
)
from ai_value_scanner.decision.action import (
    H3_GRADE_A_BONUS,
    H3_JOINT_ENTRY_WEIGHT,
    H3_JOINT_QUALITY_WEIGHT,
    map_action_state,
    map_action_state_v2,
)
from ai_value_scanner.decision.entry import build_entry_quality_v1, build_entry_quality_v2
from ai_value_scanner.decision.integrated import _ACTION_ORDER, _QUALITY_ORDER
from ai_value_scanner.decision.model import ActionState, EntryState, QualityGrade
from ai_value_scanner.decision.quality import (
    build_company_quality_v1,
    build_company_quality_v2,
)
from ai_value_scanner.research import m2_failure_attribution as m2mod


# ---------------------------------------------------------------------------
# Epistemic partitions & tiers
# ---------------------------------------------------------------------------

TIER_DEV = "RETROSPECTIVE_DEVELOPMENT"
TIER_POST2024 = "RETROSPECTIVE_POST2024_HELD_OUT_APPROX_UNIVERSE"
TIER_ALL = "RETROSPECTIVE_FULL_REPLAY_APPROX_UNIVERSE"

PERIODS: tuple[str, ...] = ("DEV_2023_2024", "POST2024_HELD_OUT", "ALL_39_DATES")
VARIANTS: tuple[str, ...] = (
    "v1_baseline",
    "h1_quality_only",
    "h2_entry_only",
    "h3_action_only",
    "v2_combined",
)
VARIANT_STAGES: dict[str, tuple[str, str, str]] = {
    "v1_baseline": ("v1", "v1", "v1"),
    "h1_quality_only": ("v2", "v1", "v1"),
    "h2_entry_only": ("v1", "v2", "v1"),
    "h3_action_only": ("v1", "v1", "v2"),
    "v2_combined": ("v2", "v2", "v2"),
}
COHORTS: tuple[str, ...] = ("TOP5", "TOP15", "PRIORITY_REVIEW", "QUALITY_A", "ENTRY_READY")
HORIZONS: tuple[int, ...] = (20, 60, 120)

BOOTSTRAP_SEED = 20261015
BOOTSTRAP_DRAWS = 1000

_ABSOLUTE_PATH_RE = re.compile(r"(?:/home/|/tmp/)\S*")


def contains_absolute_path(text: str) -> bool:
    """True if text contains a /home/... or /tmp/... absolute path."""
    return bool(_ABSOLUTE_PATH_RE.search(text or ""))


def partition_dates(all_dates: Sequence[str]) -> dict[str, list[str]]:
    """Split signal dates into DEV / POST2024_HELD_OUT / ALL_39 partitions."""
    ordered = sorted({str(d) for d in all_dates})
    dev = [d for d in ordered if d in m2mod.DEVELOPMENT_DATE_SET]
    post = [d for d in ordered if d not in m2mod.DEVELOPMENT_DATE_SET]
    return {"DEV_2023_2024": dev, "POST2024_HELD_OUT": post, "ALL_39_DATES": ordered}


def year_bucket(signal_date: str) -> str:
    """Calendar bucket: YYYY, with 2026 dates reported as 2026Q1."""
    token = str(signal_date or "")
    if token.startswith("2026"):
        return "2026Q1"
    return token[:4] if len(token) >= 4 else "UNKNOWN"


def _explicit_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            if math.isnan(float(value)):
                return None
        except (TypeError, ValueError):
            return None
        return bool(value)
    token = str(value).strip().lower()
    if token in {"true", "1", "yes"}:
        return True
    if token in {"false", "0", "no"}:
        return False
    return None


def regime_class(regime: Any, benchmark_trend_ok: Any) -> str:
    """UP_SUPPORTIVE / DEFENSIVE_OR_DOWN / UNCLASSIFIED per-row regime."""
    text = "" if regime is None else str(regime).strip().lower()
    if text in {"", "nan", "none"}:
        text = ""
    trend = _explicit_bool(benchmark_trend_ok)
    if text == "down" or trend is False:
        return "DEFENSIVE_OR_DOWN"
    if text == "up" and trend is True:
        return "UP_SUPPORTIVE"
    return "UNCLASSIFIED"


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def finite_or_none(value: Any) -> float | None:
    """Float(value) when finite, else None (None/NaN/bool/str-safe)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def frame_number(frame: pd.DataFrame, column: str) -> pd.Series:
    """Finite-float series for column, NaN where missing/unparseable."""
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    token = str(value).strip()
    if not token or token.lower() == "nan":
        return None
    return token


def joint_score(quality_score: float | None, entry_score: float | None) -> float:
    """H3 joint composite 0.60*quality + 0.40*entry (mirrors action.py)."""
    quality = float(quality_score) if quality_score is not None else 0.0
    entry = float(entry_score) if entry_score is not None else 0.0
    return H3_JOINT_QUALITY_WEIGHT * quality + H3_JOINT_ENTRY_WEIGHT * entry


# ---------------------------------------------------------------------------
# Bespoke per-date batch evaluator (exact replica of production ranking)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredRow:
    """Minimal per-row decision record for preflight aggregation."""

    symbol: str
    signal_date: str
    grade: str
    state: str
    action: str
    priority: int
    quality_score: float | None
    entry_score: float | None
    quality_confidence: float
    entry_confidence: float
    quality_risks: frozenset
    quality_positives: frozenset
    entry_risks: frozenset
    ocf_to_net_income: float | None
    free_cash_flow: float | None
    accrual_ratio: float | None
    revenue_yoy: float | None


def _v1_rank_key(record: dict[str, Any]) -> tuple:
    quality_score = record["quality_score"]
    entry_score = record["entry_score"]
    return (
        _ACTION_ORDER[record["action_state"]],
        _QUALITY_ORDER[record["quality_grade"]],
        -(quality_score if quality_score is not None else -1.0),
        -(entry_score if entry_score is not None else -1.0),
        -float(record["quality_confidence"]),
        -float(record["entry_confidence"]),
        record["symbol"],
    )


def _v2_rank_key(record: dict[str, Any]) -> tuple:
    action = record["action_state"]
    joint = joint_score(record["quality_score"], record["entry_score"])
    action_order = _H3_ACTION_ORDER[action]
    if action is ActionState.PRIORITY_REVIEW:
        bonus = H3_GRADE_A_BONUS if record["quality_grade"] is QualityGrade.A else 0.0
        return (action_order, -(joint + bonus), record["symbol"])
    if action is ActionState.HOLD_MONITOR:
        ready_first = 0 if record["entry_state"] is EntryState.ENTRY_READY else 1
        return (action_order, ready_first, -joint, record["symbol"])
    return (
        action_order,
        _H3_QUALITY_ORDER[record["quality_grade"]],
        -joint,
        record["symbol"],
    )


def evaluate_date_frame(
    group: pd.DataFrame, decision_date: str
) -> dict[str, dict[str, Any]]:
    """Evaluate one signal date under all 5 variants (single pass).

    Returns variant -> {"records": tuple[ScoredRow, ...]} with production
    builders, production action maps, and exact production ranking keys.
    """
    day = str(decision_date)
    features: dict[str, dict[str, float | None]] = {}
    if not group.empty and "symbol" in group.columns:
        symbols = group["symbol"].astype(str).str.upper()
        for column in ("ocf_to_net_income", "free_cash_flow", "accrual_ratio", "revenue_yoy"):
            series = frame_number(group, column)
            for symbol, value in zip(symbols.tolist(), series.tolist()):
                features.setdefault(str(symbol), {})[column] = (
                    None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)
                )
    provisional: dict[str, list[dict[str, Any]]] = {variant: [] for variant in VARIANTS}
    for _, row in group.iterrows():
        symbol = str(row.get("symbol", "") or "").strip().upper()
        if not symbol:
            continue
        data_asof = _text_or_none(row.get("fundamental_data_asof"))
        market_asof = _text_or_none(row.get("market_asof"))
        quality_v1 = build_company_quality_v1(row, decision_date=day, data_asof=data_asof)
        quality_v2 = build_company_quality_v2(row, decision_date=day, data_asof=data_asof)
        entry_v1 = build_entry_quality_v1(row, decision_date=day, market_asof=market_asof)
        entry_v2 = build_entry_quality_v2(row, decision_date=day, market_asof=market_asof)
        combos = {
            "v1_baseline": (quality_v1, entry_v1, map_action_state(quality_v1.grade, entry_v1.state)),
            "h1_quality_only": (quality_v2, entry_v1, map_action_state(quality_v2.grade, entry_v1.state)),
            "h2_entry_only": (quality_v1, entry_v2, map_action_state(quality_v1.grade, entry_v2.state)),
            "h3_action_only": (quality_v1, entry_v1, map_action_state_v2(quality_v1, entry_v1)[0]),
            "v2_combined": (quality_v2, entry_v2, map_action_state_v2(quality_v2, entry_v2)[0]),
        }
        feats = features.get(symbol, {})
        for variant, (quality, entry, action) in combos.items():
            provisional[variant].append({
                "symbol": symbol,
                "quality_grade": quality.grade,
                "entry_state": entry.state,
                "action_state": action,
                "quality_score": quality.score,
                "entry_score": entry.score,
                "quality_confidence": quality.confidence,
                "entry_confidence": entry.confidence,
                "quality_risks": frozenset(item.code for item in quality.risks),
                "quality_positives": frozenset(item.code for item in quality.positives),
                "entry_risks": frozenset(item.code for item in entry.risks),
                "ocf_to_net_income": feats.get("ocf_to_net_income"),
                "free_cash_flow": feats.get("free_cash_flow"),
                "accrual_ratio": feats.get("accrual_ratio"),
                "revenue_yoy": feats.get("revenue_yoy"),
            })
    out: dict[str, dict[str, Any]] = {}
    for variant, rows in provisional.items():
        key = _v2_rank_key if VARIANT_STAGES[variant][2] == "v2" else _v1_rank_key
        ordered = sorted(rows, key=key)
        records = tuple(
            ScoredRow(
                symbol=item["symbol"],
                signal_date=day,
                grade=item["quality_grade"].value,
                state=item["entry_state"].value,
                action=item["action_state"].value,
                priority=index,
                quality_score=item["quality_score"],
                entry_score=item["entry_score"],
                quality_confidence=float(item["quality_confidence"]),
                entry_confidence=float(item["entry_confidence"]),
                quality_risks=item["quality_risks"],
                quality_positives=item["quality_positives"],
                entry_risks=item["entry_risks"],
                ocf_to_net_income=item["ocf_to_net_income"],
                free_cash_flow=item["free_cash_flow"],
                accrual_ratio=item["accrual_ratio"],
                revenue_yoy=item["revenue_yoy"],
            )
            for index, item in enumerate(ordered, start=1)
        )
        out[variant] = {"records": records}
    return out


def scored_row_from_frozen(decision: Mapping[str, Any]) -> ScoredRow:
    """Adapt a frozen decisions.jsonl dict to a ScoredRow (snapshot utility).

    Feature values come only from emitted evidence; silent gates stay None.
    """
    quality = decision.get("quality", {}) if isinstance(decision, Mapping) else {}
    entry = decision.get("entry", {}) if isinstance(decision, Mapping) else {}
    quality_values = m2mod.evidence_feature_map(decision, "quality")
    entry_values = m2mod.evidence_feature_map(decision, "entry")
    values = {**entry_values, **quality_values}
    quality_section = quality if isinstance(quality, Mapping) else {}
    entry_section = entry if isinstance(entry, Mapping) else {}
    def _codes(section: Mapping[str, Any], key: str) -> frozenset:
        items = section.get(key, [])
        return frozenset(str(item.get("code", "")) for item in items if isinstance(item, Mapping))
    try:
        priority = int(decision.get("priority", 0) or 0)
    except (TypeError, ValueError):
        priority = 0
    return ScoredRow(
        symbol=str(decision.get("symbol", "") or "").strip().upper(),
        signal_date=str(decision.get("decision_date", "") or ""),
        grade=str(quality_section.get("grade", "")),
        state=str(entry_section.get("state", "")),
        action=str(decision.get("action_state", "")),
        priority=priority,
        quality_score=m2mod.finite_or_none(quality_section.get("score")),
        entry_score=m2mod.finite_or_none(entry_section.get("score")),
        quality_confidence=float(quality_section.get("confidence", 0.0) or 0.0),
        entry_confidence=float(entry_section.get("confidence", 0.0) or 0.0),
        quality_risks=_codes(quality_section, "risks"),
        quality_positives=_codes(quality_section, "positives"),
        entry_risks=_codes(entry_section, "risks"),
        ocf_to_net_income=values.get("ocf_to_net_income"),
        free_cash_flow=values.get("free_cash_flow"),
        accrual_ratio=values.get("accrual_ratio"),
        revenue_yoy=values.get("revenue_yoy"),
    )


# ---------------------------------------------------------------------------
# Compact single-pass per-date evaluation (parallel-worker friendly)
# ---------------------------------------------------------------------------


def evaluate_date_compact(group: pd.DataFrame, decision_date: str) -> dict[str, Any]:
    """Evaluate one signal date under all 5 variants, returning compact data.

    Designed for process-pool workers: only JSON-friendly scalars/lists cross
    the pool boundary (no dataclass instances, no EvidenceItems).
    """
    evaluated = evaluate_date_frame(group, decision_date)
    symbols = group["symbol"].astype(str).str.upper() if "symbol" in group.columns else pd.Series([], dtype=str)
    legs: dict[int, tuple] = {}
    for horizon in HORIZONS:
        legs[horizon] = (frame_number(group, f"fwd_ret_{horizon}"), frame_number(group, f"qqq_return_{horizon}"))
    regime_series = pd.Series(
        [regime_class(row.get("regime"), row.get("benchmark_trend_ok")) for _, row in group.iterrows()],
        index=group.index,
    ) if {"regime", "benchmark_trend_ok"}.issubset(group.columns) \
        else pd.Series("UNCLASSIFIED", index=group.index)
    out: dict[str, Any] = {}
    for variant in VARIANTS:
        records = evaluated[variant]["records"]
        by_symbol = {r.symbol: r for r in records}
        ordered = sorted(records, key=lambda r: (r.priority, r.symbol))
        top15 = [r.symbol for r in ordered if r.priority <= 15]
        grades: dict[str, int] = {}
        entries: dict[str, int] = {}
        actions: dict[str, int] = {}
        for record in records:
            grades[record.grade] = grades.get(record.grade, 0) + 1
            entries[record.state] = entries.get(record.state, 0) + 1
            actions[record.action] = actions.get(record.action, 0) + 1
        utility = human_utility_for_scope(records)
        top15_rows = [r for r in records if r.priority <= 15]
        cohort_means: dict[str, dict] = {}
        for cohort in COHORTS:
            members = cohort_members(records, cohort)
            mask = symbols.isin(members)
            per_horizon: dict[int, list] = {}
            for horizon in HORIZONS:
                fwd, qqq = legs[horizon]
                valid = mask & fwd.notna() & qqq.notna()
                selected = (fwd - qqq).loc[valid]
                if selected.empty:
                    per_horizon[horizon] = [None, 0]
                else:
                    per_horizon[horizon] = [round(float(selected.mean()), 6), int(selected.size)]
            cohort_means[cohort] = per_horizon
        regime_means: dict[str, dict] = {}
        for cohort in ("TOP15", "PRIORITY_REVIEW"):
            members = cohort_members(records, cohort)
            mask = symbols.isin(members)
            per_regime: dict[str, list] = {}
            for regime in ("UP_SUPPORTIVE", "DEFENSIVE_OR_DOWN"):
                fwd, qqq = legs[60]
                valid = mask & regime_series.eq(regime) & fwd.notna() & qqq.notna()
                selected = (fwd - qqq).loc[valid]
                if selected.empty:
                    per_regime[regime] = [None, 0]
                else:
                    per_regime[regime] = [round(float(selected.mean()), 6), int(selected.size)]
            regime_means[cohort] = per_regime
        out[variant] = {
            "n": len(records),
            "grades": grades,
            "entries": entries,
            "actions": actions,
            "top15": top15,
            "utility": {
                "contradictory": utility["n_contradictory_cash_accrual"],
                "silent": utility["n_silent_non_ready_entry"],
                "ready_share": utility["mean_top15_ready_share"],
                "a_share": utility["mean_top15_quality_a_share"],
                "growth_share": utility["mean_top15_high_growth_share"],
            },
            "cohort_means": cohort_means,
            "regime_means": regime_means,
        }
    return out


def human_utility_for_scope(
    records: Sequence[ScoredRow],
) -> dict[str, Any]:
    """Track 1 metrics over one scope's decision records (any variant)."""
    rows = list(records)
    n = len(rows)
    contradictory = sum(
        1 for r in rows
        if r.grade != "UNRATED"
        and "accrual_ratio_weak" in r.quality_risks
        and r.accrual_ratio is not None
        and r.accrual_ratio < 0.0
        and (("ocf_to_net_income_strong" in r.quality_positives)
             or (r.ocf_to_net_income is not None and r.ocf_to_net_income >= 1.0
                 and r.free_cash_flow is not None and r.free_cash_flow > 0.0))
    )
    silent = sum(
        1 for r in rows
        if r.state in ("WATCH_BREAKOUT", "TREND_DAMAGED") and not r.entry_risks
    )
    by_date: dict[str, list[ScoredRow]] = {}
    for record in rows:
        by_date.setdefault(record.signal_date, []).append(record)
    ready_shares: list[float] = []
    a_shares: list[float] = []
    growth_shares: list[float] = []
    for members in by_date.values():
        top15 = [r for r in members if r.priority <= 15]
        if not top15:
            continue
        ready_shares.append(sum(1 for r in top15 if r.state == "ENTRY_READY") / len(top15))
        a_shares.append(sum(1 for r in top15 if r.grade == "A") / len(top15))
        growth_shares.append(sum(
            1 for r in top15
            if r.revenue_yoy is not None and r.revenue_yoy >= 0.25
        ) / len(top15))
    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 6) if values else None
    return {
        "n_decisions": n,
        "n_contradictory_cash_accrual": contradictory,
        "n_silent_non_ready_entry": silent,
        "mean_top15_ready_share": _mean(ready_shares),
        "mean_top15_quality_a_share": _mean(a_shares),
        "mean_top15_high_growth_share": _mean(growth_shares),
    }


def render_and_check_v2(
    decisions: Sequence,
    *,
    title: str = "Action List",
) -> dict[str, Any]:
    """Render Report v2 (action list + detailed) and check parity.

    Returns exception count, ordering mismatches vs input priority order,
    absolute-path hits, and the overall boolean.
    """
    from ai_value_scanner.reporting.decision import (
        render_action_list_v2,
        render_detailed_report_v2,
    )
    exceptions: list[str] = []
    ordered = sorted(decisions, key=lambda d: (d.priority, d.symbol))
    try:
        action_md = render_action_list_v2(ordered, title=title)
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        action_md = ""
        exceptions.append(f"action_list:{type(exc).__name__}:{exc}")
    detailed: dict[str, str] = {}
    for decision in ordered[:15]:
        try:
            detailed[decision.symbol] = render_detailed_report_v2(decision)
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            exceptions.append(f"detailed:{decision.symbol}:{type(exc).__name__}:{exc}")
    expected = [d.symbol for d in ordered[:15]]
    jump_pattern = re.compile(r"#card-([a-z0-9.]+)")
    rendered_order = [token.upper() for token in jump_pattern.findall(action_md)]
    rendered_top = [s for s in rendered_order if s in set(expected)]
    ordering_mismatches = (
        [] if rendered_top == expected[: len(rendered_top)] and rendered_top
        else [f"expected {expected} got {rendered_top}"]
    )
    abs_paths = sum(
        1 for text in [action_md, *detailed.values()] if contains_absolute_path(text)
    )
    return {
        "n_decisions": len(ordered),
        "n_exceptions": len(exceptions),
        "exceptions": exceptions[:5],
        "n_ordering_mismatches": len(ordering_mismatches),
        "ordering_mismatches": ordering_mismatches[:5],
        "n_absolute_paths": abs_paths,
        "report_v2_parity_ok": not exceptions and not ordering_mismatches and abs_paths == 0,
    }


# ---------------------------------------------------------------------------
# Track 2: paired economics
# ---------------------------------------------------------------------------


def cohort_members(records: Sequence[ScoredRow], cohort: str) -> set[str]:
    """Symbols in a cohort (single date's records)."""
    if cohort == "TOP5":
        return {r.symbol for r in records if r.priority <= 5}
    if cohort == "TOP15":
        return {r.symbol for r in records if r.priority <= 15}
    if cohort == "PRIORITY_REVIEW":
        return {r.symbol for r in records if r.action == "PRIORITY_REVIEW"}
    if cohort == "QUALITY_A":
        return {r.symbol for r in records if r.grade == "A"}
    if cohort == "ENTRY_READY":
        return {r.symbol for r in records if r.state == "ENTRY_READY"}
    raise ValueError(f"unknown cohort={cohort!r}")


def date_cohort_excess(
    frame: pd.DataFrame, members: set[str], horizon: int
) -> tuple[float | None, int]:
    """Mean net-QQQ excess over cohort members with finite legs + n obs."""
    fwd = frame_number(frame, f"fwd_ret_{horizon}")
    qqq = frame_number(frame, f"qqq_return_{horizon}")
    symbols = frame["symbol"].astype(str).str.upper() if "symbol" in frame.columns else pd.Series([], dtype=str)
    mask = symbols.isin(members) & fwd.notna() & qqq.notna()
    selected = (fwd - qqq).loc[mask]
    if selected.empty:
        return None, 0
    return round(float(selected.mean()), 6), int(selected.size)


def summarize_date_means(means: list[float]) -> dict[str, Any]:
    """Aggregate a list of per-date means (descriptive, no pairing)."""
    if not means:
        return {"n_matured_dates": 0, "mean": None, "median": None, "p10": None, "worst": None}
    ordered = sorted(means)
    n = len(ordered)
    p10_index = min(n - 1, int(0.10 * n))
    return {
        "n_matured_dates": n,
        "mean": round(sum(ordered) / n, 6),
        "median": round(ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0, 6),
        "p10": round(ordered[p10_index], 6),
        "worst": round(ordered[0], 6),
    }


def paired_delta_stats(
    variant_means: Mapping[str, float],
    v1_means: Mapping[str, float],
    *,
    seed: int = BOOTSTRAP_SEED,
    n_boot: int = BOOTSTRAP_DRAWS,
) -> dict[str, Any]:
    """Paired date-by-date delta stats with bootstrap CI and LOO minimum."""
    shared = sorted(set(variant_means) & set(v1_means))
    deltas = [variant_means[day] - v1_means[day] for day in shared]
    n = len(deltas)
    if not deltas:
        return {
            "n_paired_dates": 0, "mean_paired_delta_60d": None,
            "median_paired_delta_60d": None, "positive_delta_date_share": None,
            "ci95_low_60d": None, "ci95_high_60d": None, "loo_min_mean_delta_60d": None,
        }
    ordered = sorted(deltas)
    mean = sum(deltas) / n
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
    rng = random.Random(seed)
    boot_means = sorted(sum(rng.choices(deltas, k=n)) / n for _ in range(n_boot))
    low = boot_means[int(0.025 * n_boot)]
    high = boot_means[min(n_boot - 1, int(0.975 * n_boot))]
    loo_min = min(
        (sum(deltas[:i] + deltas[i + 1:]) / (n - 1)) for i in range(n)
    ) if n >= 2 else mean
    return {
        "n_paired_dates": n,
        "mean_paired_delta_60d": round(mean, 6),
        "median_paired_delta_60d": round(median, 6),
        "positive_delta_date_share": round(sum(1 for d in deltas if d > 0) / n, 6),
        "ci95_low_60d": round(low, 6),
        "ci95_high_60d": round(high, 6),
        "loo_min_mean_delta_60d": round(loo_min, 6),
    }


# ---------------------------------------------------------------------------
# Track 3: Gate G4/G5 promotion rules
# ---------------------------------------------------------------------------


def human_utility_verdict(
    variant_metrics: Mapping[str, Any], v1_metrics: Mapping[str, Any]
) -> dict[str, Any]:
    """PASS iff contradictions and silent gates are eliminated and the Top-15
    ENTRY_READY share is preserved or improved vs v1_baseline."""
    contradictions_ok = (variant_metrics.get("n_contradictory_cash_accrual") or 0) == 0
    silent_ok = (variant_metrics.get("n_silent_non_ready_entry") or 0) == 0
    variant_share = variant_metrics.get("mean_top15_ready_share")
    v1_share = v1_metrics.get("mean_top15_ready_share")
    share_ok = (
        variant_share is not None and v1_share is not None and variant_share >= v1_share
    )
    passed = bool(contradictions_ok and silent_ok and share_ok)
    return {
        "verdict": "PASS" if passed else "FAIL",
        "contradictions_eliminated": bool(contradictions_ok),
        "silent_gates_eliminated": bool(silent_ok),
        "ready_share_preserved_or_improved": bool(share_ok),
    }


def economic_verdict(paired: Mapping[str, Any]) -> str:
    """Honest classification from paired 60d delta stats (TOP15, 60d)."""
    mean = paired.get("mean_paired_delta_60d")
    loo_min = paired.get("loo_min_mean_delta_60d")
    ci_low = paired.get("ci95_low_60d")
    if mean is None or mean <= 0:
        return "NEGATIVE_OR_FLAT"
    if loo_min is not None and loo_min > 0:
        return "POSITIVE_ROBUST"
    if ci_low is not None and ci_low <= 0:
        return "POSITIVE_POINT_ESTIMATE_CI_WIDE"
    return "POSITIVE_POINT_ESTIMATE_CI_WIDE"


def overall_recommendation(
    human: Mapping[str, Mapping[str, Any]],
    economic_post: Mapping[str, str],
    economic_all: Mapping[str, str],
) -> dict[str, Any]:
    """Deterministic M5 recommendation; v1 stays the production default."""
    shadow: list[str] = []
    for variant in VARIANTS:
        if variant == "v1_baseline":
            continue
        utility_pass = human.get(variant, {}).get("verdict") == "PASS"
        robust = (
            economic_post.get(variant) == "POSITIVE_ROBUST"
            or economic_all.get(variant) == "POSITIVE_ROBUST"
        )
        if utility_pass and robust:
            shadow.append(variant)
    if "v2_combined" in shadow:
        text = (
            "Advance v2_combined (and its robust stages) to M5 opt-in shadow "
            "deployment alongside default v1; policy_version=\"v1\" remains the "
            "production default and no threshold changes ship without M5 sign-off."
        )
    elif shadow:
        text = (
            f"Advance {', '.join(sorted(shadow))} to M5 opt-in shadow deployment "
            "alongside default v1; v2_combined is not recommended as a whole. "
            "policy_version=\"v1\" remains the production default."
        )
    else:
        text = (
            "Retain v1: no candidate clears both the human-utility gate and "
            "robust paired economics. policy_version=\"v1\" remains the production "
            "default; revisit mechanisms, do not relax the gate."
        )
    return {"shadow_candidates": sorted(shadow), "recommendation": text}
