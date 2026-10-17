#!/usr/bin/env python3
"""Growth-compounder offense & slow-growth de-crowding validation (C1/C2/C3).

Offline, deterministic validation of three pre-registered candidates against
the production ``v2`` baseline across the four mandatory gates (G1-G4):

- ``C1_de_crowd_slow_growth``: re-rank within ``action_state`` buckets with a
  ``-0.08`` slow-growth deduction and a ``+0.05`` verified-compounder bonus.
- ``C2_offense_compounder_track``: pure growth-compounder offense track
  (6 frozen conditions), backfilled from C1 order when fewer than 15 qualify.
- ``C3_barbell_top15``: 8 defensive anchors from C1 + 7 offense leaders from
  C2 (TOP5 = 3 anchors + 2 offense).

Reuses the dataset/segment helpers from ``scripts/run_extended_replay_evaluation.py``
and rebuilds canonical production ``build_stock_decisions(..., policy_version="v2")``
per signal date. Zero network calls; no production code changes.

Example:
    .venv/bin/python scripts/validate_growth_compounder_offense.py \
      --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
      --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
      --output-dir docs/growth_compounder_offense_validation_20261017
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import run_extended_replay_evaluation as replay
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.research.m4_paired_validation import paired_delta_stats

CANDIDATES: tuple[str, ...] = (
    "v2_baseline",
    "C1_de_crowd_slow_growth",
    "C2_offense_compounder_track",
    "C3_barbell_top15",
)
CANDIDATE_LABELS: dict[str, str] = {
    "v2_baseline": "v2 baseline (production ranking)",
    "C1_de_crowd_slow_growth": "C1 slow-growth de-crowding",
    "C2_offense_compounder_track": "C2 offense compounder track",
    "C3_barbell_top15": "C3 barbell 8+7",
}
HORIZONS: tuple[int, ...] = (20, 60, 120)
G1_SEGMENTS: tuple[str, ...] = (
    "DEV_2023_2024", "POST_2025_2026Q1", "BASE_ALL_39",
)
G2_SEGMENTS: tuple[str, ...] = (
    "FWD_BULL_60D", "FWD_DRAWDOWN_60D",
    "BEAR_2022", "BEAR_2022_FWD_DRAWDOWN_60D",
)
SEVERE_LOSS_THRESHOLD = -0.20
SLOW_GROWTH_THRESHOLD = 0.08
COMPOUNDER_REV_MIN = 0.15
COMPOUNDER_OCF_MIN = 0.80
COMPOUNDER_QUALITY_FLOOR = 0.68
SMA200_FLOOR = 1.00
SMA200_CAP = 1.60
ACTION_STATE_ORDER: tuple[str, ...] = (
    "PRIORITY_REVIEW", "WATCH_PULLBACK", "WATCH_BREAKOUT",
    "HOLD_MONITOR", "AVOID",
)
DEFAULT_SNAPSHOT = (
    "outputs/decision_previews/2026-10-15/risk_off/decisions_recomputed_v2.jsonl"
)

COHORT_COLUMNS: tuple[str, ...] = (
    "scope", "segment", "candidate", "cohort",
    "n_dates_20", "n_dates_60", "n_dates_120", "obs_60",
    "mean_excess_20", "mean_excess_60", "median_excess_60", "mean_excess_120",
    "win_rate_vs_qqq_60", "mean_raw_ret_60", "severe_loss_rate_60",
)
PAIRED_COLUMNS: tuple[str, ...] = (
    "scope", "segment", "candidate", "cohort", "horizon",
    "n_paired_dates", "mean_delta", "median_delta", "ci_low", "ci_high",
    "loo_min", "positive_date_share",
)
ROBUSTNESS_COLUMNS: tuple[str, ...] = (
    "record_type", "scope", "segment", "candidate", "cohort",
    "n_dates_60", "obs_60", "mean_excess_60", "median_excess_60",
    "severe_loss_rate_60", "extra_a", "extra_b", "extra_c",
)
SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "candidate", "rank", "symbol", "grade", "entry_state", "action_state",
    "revenue_yoy", "ocf_to_net_income", "price_to_sma200",
    "relative_strength_60d_qqq", "in_v2_baseline_top15",
)


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def _slice_frame(frame):
    counts = replay.pd.to_numeric(
        frame.get("watchlist_etf_count"), errors="coerce"
    ).fillna(0)
    return frame[counts >= 1]


def build_v2_records(
    group, scope: str, signal_date: str
) -> list[dict[str, Any]]:
    """Rebuild canonical v2 decisions for one date/scope and attach inputs."""
    frame = group if scope == "FULL" else _slice_frame(group)
    if frame.empty:
        return []
    decisions = build_stock_decisions(
        frame,
        decision_date=str(signal_date),
        generated_at_utc=f"{signal_date}T00:00:00Z",
        policy_version="v2",
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
        quality_codes = {item.code for item in decision.quality.risks}
        record: dict[str, Any] = {
            "symbol": symbol,
            "priority": int(decision.priority),
            "action_state": decision.action_state.value,
            "grade": decision.quality.grade.value,
            "quality_score": float(decision.quality.score or 0.0),
            "entry_score": float(decision.entry.score or 0.0),
            "entry_state": decision.entry.state.value,
            "pre_earnings": "pre_earnings_window_risk" in quality_codes,
            "nonop": "nonoperating_gain_inflation" in quality_codes,
            "price_to_sma200": replay._num(row.get("price_to_sma200")),
            "revenue_yoy": replay._num(row.get("revenue_yoy")),
            "ocf_to_net_income": replay._num(row.get("ocf_to_net_income")),
            "relative_strength_60d_qqq": replay._num(
                row.get("relative_strength_60d_qqq")),
        }
        for horizon in HORIZONS:
            fwd = replay._num(row.get(f"fwd_ret_{horizon}"))
            qqq = replay._num(row.get(f"qqq_return_{horizon}"))
            record[f"fwd_ret_{horizon}"] = fwd
            record[f"excess_{horizon}"] = (
                fwd - qqq if fwd is not None and qqq is not None else None
            )
        records.append(record)
    return records


def evaluate_all_records(
    datasets: Mapping[str, Any],
    metas: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """scope -> date -> records, merged across stitched datasets."""
    merged: dict[str, dict[str, list[dict[str, Any]]]] = {
        scope: {} for scope in ("FULL", "ETF_SLICE")
    }
    for frame in datasets.values():
        for date, group in frame.groupby("signal_date", sort=True):
            token = str(date)
            for scope in merged:
                merged[scope][token] = build_v2_records(group, scope, token)
    return merged


# ---------------------------------------------------------------------------
# Candidate rankings (pure)
# ---------------------------------------------------------------------------


def c1_priority_score(record: Mapping[str, Any]) -> float:
    """Base joint score minus v2 penalties, plus slow-growth adjustments."""
    score = (
        0.60 * float(record["quality_score"])
        + 0.40 * float(record["entry_score"])
    )
    if record.get("pre_earnings"):
        score -= 0.06
    if record.get("nonop"):
        score -= 0.06
    revenue_yoy = record.get("revenue_yoy")
    if revenue_yoy is None or revenue_yoy < SLOW_GROWTH_THRESHOLD:
        score -= 0.08
    if (
        revenue_yoy is not None
        and revenue_yoy >= COMPOUNDER_REV_MIN
        and record.get("ocf_to_net_income") is not None
        and record["ocf_to_net_income"] >= COMPOUNDER_OCF_MIN
        and not record.get("nonop")
    ):
        score += 0.05
    return score


def c1_ranking(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """Re-rank within each action_state bucket; buckets keep v2 order."""
    order: list[str] = []
    for action in ACTION_STATE_ORDER:
        bucket = [r for r in records if r["action_state"] == action]
        bucket.sort(key=lambda r: (
            -c1_priority_score(r),
            -float(r["quality_score"]),
            -float(r["entry_score"]),
            str(r["symbol"]),
        ))
        order.extend(str(r["symbol"]) for r in bucket)
    return order


def is_offense_compounder(record: Mapping[str, Any]) -> bool:
    """Frozen 6-condition growth-compounder offense eligibility gate."""
    if record.get("grade") not in {"A", "B"}:
        return False
    if float(record.get("quality_score") or 0.0) < COMPOUNDER_QUALITY_FLOOR:
        return False
    if record.get("nonop"):
        return False
    revenue_yoy = record.get("revenue_yoy")
    if revenue_yoy is None or revenue_yoy < COMPOUNDER_REV_MIN:
        return False
    ocf = record.get("ocf_to_net_income")
    if ocf is None or ocf < COMPOUNDER_OCF_MIN:
        return False
    if record.get("entry_state") not in {"ENTRY_READY", "WATCH_PULLBACK"}:
        return False
    sma200 = record.get("price_to_sma200")
    if sma200 is None or sma200 < SMA200_FLOOR or sma200 > SMA200_CAP:
        return False
    rs60 = record.get("relative_strength_60d_qqq")
    if rs60 is None or rs60 < 0.0:
        return False
    return True


def offense_score(record: Mapping[str, Any]) -> float:
    score = (
        float(record["quality_score"])
        + 0.50 * min(max(float(record["revenue_yoy"]), 0.0), 1.0)
        + 0.50 * min(
            max(float(record["relative_strength_60d_qqq"]), 0.0), 1.0)
    )
    if record.get("pre_earnings"):
        score -= 0.06
    return score


def c2_ranking(
    records: Sequence[Mapping[str, Any]], c1_order: Sequence[str]
) -> list[str]:
    """Eligible offense compounders first, then C1-order backfill."""
    eligible = sorted(
        (r for r in records if is_offense_compounder(r)),
        key=lambda r: (
            -offense_score(r),
            -float(r["quality_score"]),
            -float(r["entry_score"]),
            str(r["symbol"]),
        ),
    )
    ranked = [str(r["symbol"]) for r in eligible]
    for symbol in c1_order:
        if symbol not in ranked:
            ranked.append(symbol)
    return ranked


def c3_components(
    records: Sequence[Mapping[str, Any]],
    c1_order: Sequence[str],
    c2_eligible: Sequence[str],
) -> dict[str, list[str]]:
    """Barbell 8+7 construction with dedup and TOP5 = 3+2 rule."""
    anchors = list(c1_order[:8])
    offense = [s for s in c2_eligible if s not in anchors][:7]
    ranked = anchors + offense
    for symbol in c1_order:
        if len(ranked) >= 15:
            break
        if symbol not in ranked:
            ranked.append(symbol)
    top3 = list(c1_order[:3])
    top2_offense = [s for s in c2_eligible if s not in top3][:2]
    return {
        "ranked": ranked,
        "top5": top3 + top2_offense,
        "anchors": anchors,
        "offense": offense,
    }


def candidate_rankings(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-date candidate ranked lists + TOP5/TOP15 symbol sets."""
    c1_order = c1_ranking(records)
    eligible = [
        str(r["symbol"]) for r in sorted(
            (r for r in records if is_offense_compounder(r)),
            key=lambda r: (
                -offense_score(r),
                -float(r["quality_score"]),
                -float(r["entry_score"]),
                str(r["symbol"]),
            ),
        )
    ]
    c2_order = c2_ranking(records, c1_order)
    c3 = c3_components(records, c1_order, eligible)
    return {
        "v2_baseline": {
            "ranked": [
                str(r["symbol"]) for r in sorted(
                    records, key=lambda r: (int(r["priority"]), str(r["symbol"]))
                )
            ],
        },
        "C1_de_crowd_slow_growth": {"ranked": c1_order},
        "C2_offense_compounder_track": {"ranked": c2_order},
        "C3_barbell_top15": {"ranked": c3["ranked"], "top5": c3["top5"]},
    }


def top5_top15(
    candidate: str, ranking: Mapping[str, Any]
) -> tuple[set[str], set[str]]:
    ranked = list(ranking["ranked"])
    top15 = set(ranked[:15])
    if candidate == "C3_barbell_top15" and ranking.get("top5") is not None:
        top5 = set(ranking["top5"])
    else:
        top5 = set(ranked[:5])
    return top5, top15


# ---------------------------------------------------------------------------
# Statistics over symbol sets
# ---------------------------------------------------------------------------


def set_stats(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    sets_by_date: Mapping[str, set[str]],
    *,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    """Date-equal cohort stats for per-date symbol sets (replay semantics)."""
    exclude = exclude or set()
    summary: dict[str, Any] = {}
    for horizon in HORIZONS:
        means: dict[str, float] = {}
        obs = 0
        for date in dates:
            members = sets_by_date.get(date, set()) - exclude
            values = [
                float(record[f"excess_{horizon}"])
                for record in records_by_date.get(date, ())
                if record["symbol"] in members
                and replay._num(record.get(f"excess_{horizon}")) is not None
            ]
            if values:
                means[date] = sum(values) / len(values)
                obs += len(values)
        stats = replay.summarize_date_means(means.values())
        summary[f"n_dates_{horizon}"] = stats["n"]
        summary[f"obs_{horizon}"] = obs
        summary[f"mean_excess_{horizon}"] = stats["mean"]
        if horizon == 60:
            summary["median_excess_60"] = stats["median"]
            summary["date_means_excess_60"] = means
            summary["win_rate_vs_qqq_60"] = (
                sum(1 for value in means.values() if value > 0.0) / len(means)
                if means else None
            )
    raw_means: dict[str, float] = {}
    for date in dates:
        members = sets_by_date.get(date, set()) - exclude
        values = [
            float(record["fwd_ret_60"])
            for record in records_by_date.get(date, ())
            if record["symbol"] in members
            and replay._num(record.get("fwd_ret_60")) is not None
        ]
        if values:
            raw_means[date] = sum(values) / len(values)
    summary["mean_raw_ret_60"] = replay.summarize_date_means(
        raw_means.values())["mean"]
    loss_shares: list[float] = []
    for date in dates:
        members = sets_by_date.get(date, set()) - exclude
        values = [
            record["fwd_ret_60"]
            for record in records_by_date.get(date, ())
            if record["symbol"] in members
            and replay._num(record.get("fwd_ret_60")) is not None
        ]
        if values:
            loss_shares.append(
                sum(
                    1 for value in values
                    if float(value) <= SEVERE_LOSS_THRESHOLD
                ) / len(values)
            )
    summary["severe_loss_rate_60"] = replay._mean(loss_shares)
    return summary


def sets_for_segment(
    candidate: str,
    cohort: str,
    sets_by_date: Mapping[str, Mapping[str, tuple[set[str], set[str]]]],
    dates: Sequence[str],
) -> dict[str, set[str]]:
    index = 0 if cohort == "TOP5" else 1
    return {
        date: sets_by_date[date][candidate][index]
        for date in dates
        if date in sets_by_date and candidate in sets_by_date[date]
    }


# ---------------------------------------------------------------------------
# Gate computations
# ---------------------------------------------------------------------------


def build_candidate_sets(
    records_by_scope: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
) -> dict[str, dict[str, dict[str, tuple[set[str], set[str]]]]]:
    """scope -> date -> candidate -> (top5, top15) symbol sets."""
    out: dict[str, dict[str, dict[str, tuple[set[str], set[str]]]]] = {}
    for scope, records_by_date in records_by_scope.items():
        out[scope] = {}
        for date, records in records_by_date.items():
            rankings = candidate_rankings(records)
            out[scope][date] = {
                candidate: top5_top15(candidate, ranking)
                for candidate, ranking in rankings.items()
            }
    return out


def top_contributors(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    sets_by_date: Mapping[str, set[str]],
    k: int = 5,
) -> list[str]:
    """Top-k symbols by cumulative positive 60d excess contribution."""
    totals: dict[str, float] = {}
    for date in dates:
        members = sets_by_date.get(date, set())
        for record in records_by_date.get(date, ()):
            if record["symbol"] not in members:
                continue
            excess = replay._num(record.get("excess_60"))
            if excess is None:
                continue
            totals[record["symbol"]] = totals.get(record["symbol"], 0.0) + max(
                float(excess), 0.0)
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [symbol for symbol, _ in ordered[:k]]


def slow_growth_crowding(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    dates: Sequence[str],
    sets_by_date: Mapping[str, set[str]],
) -> dict[str, float | None]:
    low_shares: list[float] = []
    high_shares: list[float] = []
    date_medians: list[float] = []
    for date in dates:
        members = sets_by_date.get(date, set())
        values = [
            float(record["revenue_yoy"])
            for record in records_by_date.get(date, ())
            if record["symbol"] in members
            and replay._num(record.get("revenue_yoy")) is not None
        ]
        if not values:
            continue
        low_shares.append(
            sum(1 for value in values if value < 0.10) / len(values))
        high_shares.append(
            sum(1 for value in values if value >= 0.15) / len(values))
        ordered = sorted(values)
        n = len(ordered)
        date_medians.append(
            ordered[n // 2] if n % 2
            else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
        )
    return {
        "share_rev_lt_0.10": replay._mean(low_shares),
        "share_rev_ge_0.15": replay._mean(high_shares),
        "median_rev_yoy": replay.summarize_date_means(
            date_medians)["median"],
    }


def episode_equal_weight(
    records_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    episodes: Sequence[tuple[str, Sequence[str]]],
    sets_by_date: Mapping[str, set[str]],
    *,
    metric: str,
) -> float | None:
    values: list[float] = []
    for _, dates in episodes:
        stats = set_stats(records_by_date, dates, sets_by_date)
        value = stats.get(metric)
        if value is not None:
            values.append(float(value))
    return replay._mean(values)


def gate_verdicts(
    economics, paired, robustness
) -> dict[str, dict[str, Any]]:
    """Boolean gate inputs per candidate (report + recommendation)."""
    def econ(scope, segment, cohort, candidate, field):
        for row in economics:
            if (row["scope"] == scope and row["segment"] == segment
                    and row["cohort"] == cohort
                    and row["candidate"] == candidate):
                return replay._num(row[field])
        return None

    def pair(scope, segment, cohort, candidate, field):
        for row in paired:
            if (row["scope"] == scope and row["segment"] == segment
                    and row["cohort"] == cohort
                    and row["candidate"] == candidate
                    and row["horizon"] == "60"):
                return replay._num(row[field])
        return None

    universe_severe = econ(
        "ETF_SLICE", "FWD_DRAWDOWN_60D", "UNIVERSE", "v2_baseline",
        "severe_loss_rate_60")
    verdicts: dict[str, dict[str, Any]] = {}
    for candidate in CANDIDATES:
        if candidate == "v2_baseline":
            continue
        delta_all = pair("ETF_SLICE", "BASE_ALL_39", "TOP15", candidate,
                         "mean_delta")
        loo_all = pair("ETF_SLICE", "BASE_ALL_39", "TOP15", candidate,
                       "loo_min")
        bull_delta = pair("ETF_SLICE", "FWD_BULL_60D", "TOP15", candidate,
                          "mean_delta")
        drawdown_excess = econ(
            "ETF_SLICE", "FWD_DRAWDOWN_60D", "TOP15", candidate,
            "mean_excess_60")
        bear_excess = econ("ETF_SLICE", "BEAR_2022", "TOP15", candidate,
                           "mean_excess_60")
        all_eq = None
        for row in robustness:
            if (row["record_type"] == "all_eq_4" and row["scope"] == "ETF_SLICE"
                    and row["candidate"] == candidate):
                all_eq = replay._num(row["mean_excess_60"])
        drawdown_severe = econ(
            "ETF_SLICE", "FWD_DRAWDOWN_60D", "TOP15", candidate,
            "severe_loss_rate_60")
        ex_delta = None
        for row in robustness:
            if (row["record_type"] == "ex_top5" and row["scope"] == "ETF_SLICE"
                    and row["segment"] == "BASE_ALL_39"
                    and row["candidate"] == candidate):
                ex_delta = replay._num(row["extra_b"])
        verdicts[candidate] = {
            "g1_positive_paired_delta_all39": (
                None if delta_all is None else delta_all > 0.0
            ),
            "g1_loo_positive_all39": (
                None if loo_all is None else loo_all > 0.0
            ),
            "g2_bull_offense_delta_positive": (
                None if bull_delta is None else bull_delta > 0.0
            ),
            "g2_drawdown_excess_nonnegative": (
                None if drawdown_excess is None else drawdown_excess >= 0.0
            ),
            "g2_bear_excess_nonnegative": (
                None if bear_excess is None else bear_excess >= 0.0
            ),
            "g2_all_eq_nonnegative": (
                None if all_eq is None else all_eq >= 0.0
            ),
            "g2_drawdown_severe_below_universe": (
                None if drawdown_severe is None or universe_severe is None
                else drawdown_severe < universe_severe
            ),
            "g3_ex_top5_delta_nonnegative": (
                None if ex_delta is None else ex_delta >= 0.0
            ),
        }
    return verdicts


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------


def build_candidate_economics(
    records_by_scope, sets_by_scope, segments
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in ("ETF_SLICE", "FULL"):
        records_by_date = records_by_scope[scope]
        for segment in G1_SEGMENTS + G2_SEGMENTS:
            dates = segments.get(segment, [])
            for candidate in CANDIDATES:
                for cohort in ("TOP5", "TOP15"):
                    sets = sets_for_segment(
                        candidate, cohort, sets_by_scope[scope], dates)
                    summary = set_stats(records_by_date, dates, sets)
                    rows.append({
                        "scope": scope,
                        "segment": segment,
                        "candidate": candidate,
                        "cohort": cohort,
                        "n_dates_20": summary["n_dates_20"],
                        "n_dates_60": summary["n_dates_60"],
                        "n_dates_120": summary["n_dates_120"],
                        "obs_60": summary["obs_60"],
                        "mean_excess_20": replay._fmt(
                            summary["mean_excess_20"]),
                        "mean_excess_60": replay._fmt(
                            summary["mean_excess_60"]),
                        "median_excess_60": replay._fmt(
                            summary["median_excess_60"]),
                        "mean_excess_120": replay._fmt(
                            summary["mean_excess_120"]),
                        "win_rate_vs_qqq_60": replay._fmt(
                            summary["win_rate_vs_qqq_60"]),
                        "mean_raw_ret_60": replay._fmt(
                            summary["mean_raw_ret_60"]),
                        "severe_loss_rate_60": replay._fmt(
                            summary["severe_loss_rate_60"]),
                    })
        # universe reference for severe-rate comparisons
        universe_sets = {
            date: {record["symbol"] for record in records_by_date[date]}
            for date in records_by_date
        }
        for segment in G1_SEGMENTS + G2_SEGMENTS:
            dates = segments.get(segment, [])
            summary = set_stats(records_by_date, dates, universe_sets)
            rows.append({
                "scope": scope,
                "segment": segment,
                "candidate": "v2_baseline",
                "cohort": "UNIVERSE",
                "n_dates_20": summary["n_dates_20"],
                "n_dates_60": summary["n_dates_60"],
                "n_dates_120": summary["n_dates_120"],
                "obs_60": summary["obs_60"],
                "mean_excess_20": replay._fmt(summary["mean_excess_20"]),
                "mean_excess_60": replay._fmt(summary["mean_excess_60"]),
                "median_excess_60": replay._fmt(summary["median_excess_60"]),
                "mean_excess_120": replay._fmt(summary["mean_excess_120"]),
                "win_rate_vs_qqq_60": replay._fmt(
                    summary["win_rate_vs_qqq_60"]),
                "mean_raw_ret_60": replay._fmt(summary["mean_raw_ret_60"]),
                "severe_loss_rate_60": replay._fmt(
                    summary["severe_loss_rate_60"]),
            })
    return rows


def build_paired_rows(records_by_scope, sets_by_scope, segments) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope in ("ETF_SLICE", "FULL"):
        records_by_date = records_by_scope[scope]
        for segment in G1_SEGMENTS + G2_SEGMENTS:
            dates = segments.get(segment, [])
            for cohort in ("TOP5", "TOP15"):
                baseline_sets = sets_for_segment(
                    "v2_baseline", cohort, sets_by_scope[scope], dates)
                for candidate in CANDIDATES:
                    if candidate == "v2_baseline":
                        continue
                    candidate_sets = sets_for_segment(
                        candidate, cohort, sets_by_scope[scope], dates)
                    for horizon in HORIZONS:
                        stats = paired_delta_stats(
                            _horizon_means(
                                records_by_date, dates, candidate_sets,
                                horizon),
                            _horizon_means(
                                records_by_date, dates, baseline_sets,
                                horizon),
                        )
                        rows.append({
                            "scope": scope,
                            "segment": segment,
                            "candidate": candidate,
                            "cohort": cohort,
                            "horizon": str(horizon),
                            "n_paired_dates": stats["n_paired_dates"],
                            "mean_delta": replay._fmt(
                                stats["mean_paired_delta_60d"]),
                            "median_delta": replay._fmt(
                                stats["median_paired_delta_60d"]),
                            "ci_low": replay._fmt(stats["ci95_low_60d"]),
                            "ci_high": replay._fmt(stats["ci95_high_60d"]),
                            "loo_min": replay._fmt(
                                stats["loo_min_mean_delta_60d"]),
                            "positive_date_share": replay._fmt(
                                stats["positive_delta_date_share"]),
                        })
    return rows


def _horizon_means(records_by_date, dates, sets, horizon) -> dict[str, float]:
    means: dict[str, float] = {}
    for date in dates:
        members = sets.get(date, set())
        values = [
            float(record[f"excess_{horizon}"])
            for record in records_by_date.get(date, ())
            if record["symbol"] in members
            and replay._num(record.get(f"excess_{horizon}")) is not None
        ]
        if values:
            means[date] = sum(values) / len(values)
    return means


def build_robustness_rows(
    records_by_scope, sets_by_scope, segments, episodes
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    all_dates = sorted(records_by_scope["ETF_SLICE"])
    for candidate in CANDIDATES:
        sets = sets_for_segment(
            candidate, "TOP15", sets_by_scope["ETF_SLICE"], all_dates)
        excluded = top_contributors(
            records_by_scope["ETF_SLICE"], all_dates, sets)
        baseline_sets = sets_for_segment(
            "v2_baseline", "TOP15", sets_by_scope["ETF_SLICE"], all_dates)
        for segment in G1_SEGMENTS + ("FWD_BULL_60D", "FWD_DRAWDOWN_60D",
                                      "BEAR_2022"):
            dates = segments.get(segment, [])
            cand_stats = set_stats(
                records_by_scope["ETF_SLICE"], dates, sets,
                exclude=set(excluded))
            base_stats = set_stats(
                records_by_scope["ETF_SLICE"], dates, baseline_sets,
                exclude=set(excluded))
            delta = None
            if (cand_stats["mean_excess_60"] is not None
                    and base_stats["mean_excess_60"] is not None):
                delta = (cand_stats["mean_excess_60"]
                         - base_stats["mean_excess_60"])
            rows.append({
                "record_type": "ex_top5",
                "scope": "ETF_SLICE",
                "segment": segment,
                "candidate": candidate,
                "cohort": "TOP15",
                "n_dates_60": cand_stats["n_dates_60"],
                "obs_60": cand_stats["obs_60"],
                "mean_excess_60": replay._fmt(cand_stats["mean_excess_60"]),
                "median_excess_60": replay._fmt(
                    cand_stats["median_excess_60"]),
                "severe_loss_rate_60": replay._fmt(
                    cand_stats["severe_loss_rate_60"]),
                "extra_a": replay._fmt(base_stats["mean_excess_60"]),
                "extra_b": replay._fmt(delta),
                "extra_c": ";".join(excluded),
            })
        crowding = slow_growth_crowding(
            records_by_scope["ETF_SLICE"], all_dates, sets)
        rows.append({
            "record_type": "slow_growth_crowding",
            "scope": "ETF_SLICE",
            "segment": "ALL_51_DATES",
            "candidate": candidate,
            "cohort": "TOP15",
            "n_dates_60": None,
            "obs_60": None,
            "mean_excess_60": "",
            "median_excess_60": "",
            "severe_loss_rate_60": "",
            "extra_a": replay._fmt(crowding["share_rev_lt_0.10"]),
            "extra_b": replay._fmt(crowding["share_rev_ge_0.15"]),
            "extra_c": replay._fmt(crowding["median_rev_yoy"]),
        })
    for scope in ("ETF_SLICE", "FULL"):
        for candidate in CANDIDATES:
            episode_sets = sets_for_segment(
                candidate, "TOP15", sets_by_scope[scope],
                [date for _, dates in episodes for date in dates])
            mean_value = episode_equal_weight(
                records_by_scope[scope], episodes, episode_sets,
                metric="mean_excess_60")
            severe_value = episode_equal_weight(
                records_by_scope[scope], episodes, episode_sets,
                metric="severe_loss_rate_60")
            rows.append({
                "record_type": "all_eq_4",
                "scope": scope,
                "segment": "ALL_EQ(4)",
                "candidate": candidate,
                "cohort": "TOP15",
                "n_dates_60": len(episodes),
                "obs_60": None,
                "mean_excess_60": replay._fmt(mean_value),
                "median_excess_60": "",
                "severe_loss_rate_60": replay._fmt(severe_value),
                "extra_a": ";".join(name for name, _ in episodes),
                "extra_b": "",
                "extra_c": "",
            })
    return rows


# ---------------------------------------------------------------------------
# Gate 4: live snapshot comparison
# ---------------------------------------------------------------------------


def load_snapshot_records(
    snapshot_path: Path,
    cache_index: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cache_index = cache_index or {}
    records: list[dict[str, Any]] = []
    with open(snapshot_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            symbol = str(payload.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            quality = payload.get("quality") or {}
            entry = payload.get("entry") or {}
            quality_codes = {
                item.get("code") for item in quality.get("risks", [])
            }
            payload_cache = cache_index.get(symbol, {})

            def _evidence(metric):
                for block in (quality, entry):
                    for bucket in ("positives", "risks", "missing"):
                        for item in block.get(bucket, []) or []:
                            if item.get("metric") == metric:
                                value = replay._num(item.get("value"))
                                if value is not None:
                                    return value
                return None

            revenue_yoy = _evidence("revenue_yoy")
            if revenue_yoy is None:
                revenue_yoy = replay._num(payload_cache.get("revenue_yoy"))
            ocf = _evidence("ocf_to_net_income")
            if ocf is None:
                ocf = replay._num(payload_cache.get("ocf_to_net_income"))
            record = {
                "symbol": symbol,
                "priority": int(payload.get("priority") or 9999),
                "action_state": str(payload.get("action_state") or "AVOID"),
                "grade": str(quality.get("grade") or "UNRATED"),
                "quality_score": float(quality.get("score") or 0.0),
                "entry_score": float(entry.get("score") or 0.0),
                "entry_state": str(entry.get("state") or "INSUFFICIENT_DATA"),
                "pre_earnings": "pre_earnings_window_risk" in quality_codes,
                "nonop": "nonoperating_gain_inflation" in quality_codes,
                "price_to_sma200": _evidence("price_to_sma200"),
                "revenue_yoy": revenue_yoy,
                "ocf_to_net_income": ocf,
                "relative_strength_60d_qqq": _evidence(
                    "relative_strength_60d_qqq"),
            }
            for horizon in HORIZONS:
                record[f"fwd_ret_{horizon}"] = None
                record[f"excess_{horizon}"] = None
            records.append(record)
    return records


def load_cache_symbol_index(cache_dir: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not cache_dir.exists():
        return index
    for path in sorted(cache_dir.glob("parsed_fund_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        symbol = str(payload.get("symbol") or "").strip().upper()
        if symbol:
            index[symbol] = payload
    return index


def build_snapshot_comparison(
    snapshot_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_symbol = {str(r["symbol"]): r for r in snapshot_records}
    rankings = candidate_rankings(snapshot_records)
    baseline_top15 = {
        str(r["symbol"]) for r in sorted(
            snapshot_records,
            key=lambda r: (int(r["priority"]), str(r["symbol"]))) if
        int(r["priority"]) <= 15
    }
    rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        ranked = list(rankings[candidate]["ranked"])[:15]
        for rank, symbol in enumerate(ranked, start=1):
            record = by_symbol.get(symbol)
            if record is None:
                continue
            rows.append({
                "candidate": candidate,
                "rank": rank,
                "symbol": symbol,
                "grade": record["grade"],
                "entry_state": record["entry_state"],
                "action_state": record["action_state"],
                "revenue_yoy": replay._fmt(record["revenue_yoy"]),
                "ocf_to_net_income": replay._fmt(
                    record["ocf_to_net_income"]),
                "price_to_sma200": replay._fmt(record["price_to_sma200"]),
                "relative_strength_60d_qqq": replay._fmt(
                    record["relative_strength_60d_qqq"]),
                "in_v2_baseline_top15": (
                    "yes" if symbol in baseline_top15 else "no"
                ),
            })
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def render_report(
    *,
    base_name: str,
    base_rows: int,
    base_dates: int,
    bear_name: str,
    bear_rows: int,
    bear_dates: int,
    snapshot_name: str,
    snapshot_sha: str,
    snapshot_rows: int,
    runner_sha: str,
    command: str,
    base_sha: str,
    bear_sha: str,
    economics: Sequence[Mapping[str, Any]],
    paired: Sequence[Mapping[str, Any]],
    robustness: Sequence[Mapping[str, Any]],
    snapshot_rows_data: Sequence[Mapping[str, Any]],
    verdicts: Mapping[str, Mapping[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("# Growth-Compounder Offense & Slow-Growth De-Crowding "
                 "Validation (C1 / C2 / C3)")
    lines.append("")
    lines.append("Offline, deterministic validation of three pre-registered "
                 "candidates against the production v2 baseline across four "
                 "mandatory gates (G1-G4). Retrospective replay only "
                 "(AGENTS.md §4/§8).")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Runner: `scripts/validate_growth_compounder_offense.py` "
                 f"SHA256 `{runner_sha}`.")
    lines.append(f"- Reproduction command: `{command}`.")
    lines.append(f"- Base dataset: `{base_name}` ({base_rows} rows, "
                 f"{base_dates} signal dates) SHA256 `{base_sha}`.")
    lines.append(f"- 2022 bear dataset: `{bear_name}` ({bear_rows} rows, "
                 f"{bear_dates} signal dates) SHA256 `{bear_sha}`.")
    lines.append(f"- Live snapshot: `{snapshot_name}` ({snapshot_rows} "
                 f"decisions) SHA256 `{snapshot_sha}`.")
    lines.append("- Segments, scope filters (ETF_SLICE `watchlist_etf_count "
                 ">= 1`; FULL secondary) and dataset loading reuse "
                 "`scripts/run_extended_replay_evaluation.py`; no production "
                 "threshold/weight/policy changes (candidate rankings exist "
                 "only in this validator).")
    lines.append("")

    lines.append("## Gate 1 - Paired economics vs v2_baseline (TOP15, 60d, "
                 "ETF_SLICE)")
    lines.append("")
    g1_rows = []
    for candidate in CANDIDATES:
        if candidate == "v2_baseline":
            continue
        cells = [CANDIDATE_LABELS[candidate]]
        for segment in G1_SEGMENTS:
            for row in paired:
                if (row["scope"] == "ETF_SLICE" and row["segment"] == segment
                        and row["cohort"] == "TOP15"
                        and row["candidate"] == candidate
                        and row["horizon"] == "60"):
                    cells.append(
                        f"{row['mean_delta']} "
                        f"[{row['ci_low']},{row['ci_high']}] "
                        f"LOO {row['loo_min']} "
                        f"pos {row['positive_date_share']}")
                    break
        g1_rows.append(cells)
    lines.append(replay._md_table(
        ["candidate", "DEV_2023_2024", "POST_2025_2026Q1", "BASE_ALL_39"],
        g1_rows,
    ))
    lines.append("")
    lines.append("Candidate TOP15 date-equal mean 60d net-QQQ excess "
                 "(ETF_SLICE):")
    lines.append("")
    econ_rows = []
    for segment in G1_SEGMENTS:
        row_cells = [segment]
        for candidate in CANDIDATES:
            for row in economics:
                if (row["scope"] == "ETF_SLICE" and row["segment"] == segment
                        and row["cohort"] == "TOP15"
                        and row["candidate"] == candidate):
                    row_cells.append(row["mean_excess_60"])
                    break
        econ_rows.append(row_cells)
    lines.append(replay._md_table(
        ["segment"] + [
            CANDIDATE_LABELS[c] for c in CANDIDATES
        ],
        econ_rows,
    ))
    lines.append("")

    lines.append("## Gate 2 - Bull offense vs drawdown / 2022 bear defense "
                 "(TOP15, 60d, ETF_SLICE)")
    lines.append("")
    g2_rows = []
    for segment in G2_SEGMENTS + ("ALL_EQ(4)",):
        for candidate in CANDIDATES:
            excess = severe = None
            if segment == "ALL_EQ(4)":
                for row in robustness:
                    if (row["record_type"] == "all_eq_4"
                            and row["scope"] == "ETF_SLICE"
                            and row["candidate"] == candidate):
                        excess = row["mean_excess_60"]
                        severe = row["severe_loss_rate_60"]
            else:
                for row in economics:
                    if (row["scope"] == "ETF_SLICE"
                            and row["segment"] == segment
                            and row["cohort"] == "TOP15"
                            and row["candidate"] == candidate):
                        excess = row["mean_excess_60"]
                        severe = row["severe_loss_rate_60"]
            g2_rows.append([segment, CANDIDATE_LABELS[candidate], excess,
                            severe])
    lines.append(replay._md_table(
        ["segment", "candidate", "mean_excess_60", "severe_loss_rate_60"],
        g2_rows,
    ))
    lines.append("")

    lines.append("## Gate 3 - Anti-lottery (EX_TOP5_CONTRIBUTORS) & "
                 "slow-growth crowding")
    lines.append("")
    g3_rows = []
    for row in robustness:
        if row["record_type"] != "ex_top5":
            continue
        if row["segment"] != "BASE_ALL_39":
            continue
        g3_rows.append([
            CANDIDATE_LABELS[row["candidate"]],
            f"{row['mean_excess_60']} (base same-excl {row['extra_a']}, "
            f"delta {row['extra_b']})",
            row["extra_c"],
        ])
    lines.append(replay._md_table(
        ["candidate (BASE_ALL_39, after own top-5 exclusion)",
         "TOP15 mean_excess_60", "excluded"],
        g3_rows,
    ))
    lines.append("")
    crowd_rows = []
    for row in robustness:
        if row["record_type"] != "slow_growth_crowding":
            continue
        crowd_rows.append([
            CANDIDATE_LABELS[row["candidate"]],
            f"{row['extra_a']} (rev<10%)",
            f"{row['extra_b']} (rev>=15%)",
            f"{row['extra_c']} (median rev YoY)",
        ])
    lines.append(replay._md_table(
        ["candidate (TOP15, 51 dates, ETF_SLICE)", "low-growth share",
         "high-growth share", "median rev_yoy"],
        crowd_rows,
    ))
    lines.append("")
    lines.append("## Gate 4 - 2026-10-15 live snapshot Top-15 comparison")
    lines.append("")
    lines.append(
        "Side-by-side Top-15 (rank, symbol, grade, entry state, revenue YoY, "
        "OCF/NI, SMA200 x, RS60) is in `snap_20261015_top15_comparison.csv` "
        "(long format, `in_v2_baseline_top15` marks baseline overlap)."
    )
    lines.append("")
    for candidate in CANDIDATES:
        symbols = [
            f"{row['rank']}.{row['symbol']}"
            for row in snapshot_rows_data
            if row["candidate"] == candidate
        ]
        lines.append(f"- {CANDIDATE_LABELS[candidate]}: "
                     f"{', '.join(symbols[:15])}")
    lines.append("")

    lines.append("## Verdict inputs (pre-registered gates)")
    lines.append("")
    lines.append(replay._md_table(
        ["candidate", "G1 delta>0", "G1 LOO>0", "G2 bull>0",
         "G2 drawdown>=0", "G2 bear>=0", "G2 ALL_EQ>=0",
         "G2 severe<universe", "G3 ex-top5>=0"],
        [
            [
                CANDIDATE_LABELS[candidate],
                *[
                    "n/a" if verdicts[candidate][key] is None
                    else ("yes" if verdicts[candidate][key] else "no")
                    for key in (
                        "g1_positive_paired_delta_all39",
                        "g1_loo_positive_all39",
                        "g2_bull_offense_delta_positive",
                        "g2_drawdown_excess_nonnegative",
                        "g2_bear_excess_nonnegative",
                        "g2_all_eq_nonnegative",
                        "g2_drawdown_severe_below_universe",
                        "g3_ex_top5_delta_nonnegative",
                    )
                ],
            ]
            for candidate in CANDIDATES
            if candidate != "v2_baseline"
        ],
    ))
    lines.append("")
    lines.append("## Explicit recommendation")
    lines.append("")
    passing = []
    for candidate in CANDIDATES:
        if candidate == "v2_baseline":
            continue
        flags = verdicts[candidate]
        if all(value is True for value in flags.values()):
            passing.append(candidate)
    if passing:
        lines.append(
            "Pre-registered all-gate pass: "
            + ", ".join(CANDIDATE_LABELS[c] for c in passing)
            + ". Recommend a bounded shadow experiment before any production "
            "policy change (retrospective evidence cannot auto-promote; "
            "AGENTS.md §8)."
        )
    else:
        lines.append(
            "No candidate clears all pre-registered gate inputs on the "
            "current evidence. Per the frozen decision rule, do not adopt "
            "C1/C2/C3 into production policy; keep v2 production unchanged "
            "and revisit only with prospective immutable snapshots."
        )
    lines.append("")
    lines.append("Guardrails: overlapping 60d windows (monthly dates) are "
                 "handled by episode-cluster equal weighting (ALL_EQ(4)); "
                 "universe snapshots are the documented "
                 "`union_superset_approx` approximation; all metrics are "
                 "date-equal.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline validation of growth-compounder offense candidates "
            "(C1/C2/C3) against v2 baseline across gates G1-G4."
        )
    )
    parser.add_argument(
        "--base-dataset",
        default=(
            "outputs/historical_selection_v1_20261011_03/repaired/"
            "company_quality_dataset_risk_off.v3.csv"
        ),
    )
    parser.add_argument(
        "--bear-2022-dataset",
        default=(
            "outputs/historical_selection_bear2022_20261017_01/repaired/"
            "company_quality_dataset_risk_off.repaired.csv"
        ),
    )
    parser.add_argument("--snapshot-jsonl", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument(
        "--output-dir",
        default="docs/growth_compounder_offense_validation_20261017",
    )
    return parser.parse_args(argv)


def _snapshot_sha(path: Path) -> str:
    digest = replay._sha256_file(path)
    return digest or ""


def _runner_command(args: argparse.Namespace) -> str:
    return " ".join([
        "python", "scripts/validate_growth_compounder_offense.py",
        "--base-dataset", replay._portable_path(args.base_dataset),
        "--bear-2022-dataset", replay._portable_path(args.bear_2022_dataset),
        "--snapshot-jsonl", replay._portable_path(args.snapshot_jsonl),
        "--output-dir", replay._portable_path(args.output_dir),
    ])


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_frame = replay._load_dataset(args.base_dataset)
    bear_frame = replay._load_dataset(args.bear_2022_dataset)
    replay.validate_disjoint_dates({
        "base": sorted(base_frame["signal_date"].astype(str).unique()),
        "bear": sorted(bear_frame["signal_date"].astype(str).unique()),
    })
    datasets = {"base": base_frame, "bear": bear_frame}
    metas = {
        name: replay.dataset_date_meta(frame)
        for name, frame in datasets.items()
    }
    segments = replay.build_segments(metas["base"], metas["bear"])
    fwd_dates = segments["FWD_DRAWDOWN_60D"]
    _, fwd_episodes = replay.assign_episode_clusters(fwd_dates, metas["base"])
    _, bear_episodes = replay.assign_episode_clusters(
        segments["BEAR_2022_FWD_DRAWDOWN_60D"], metas["bear"], bear=True)
    episodes = list(fwd_episodes) + list(bear_episodes)
    print(
        f"[offense] datasets: base={len(base_frame)}rows/"
        f"{base_frame['signal_date'].nunique()}dates, "
        f"bear={len(bear_frame)}rows/"
        f"{bear_frame['signal_date'].nunique()}dates; "
        f"episodes={[name for name, _ in episodes]}",
        flush=True,
    )

    records_by_scope = evaluate_all_records(datasets, metas)
    sets_by_scope = build_candidate_sets(records_by_scope)
    print("[offense] candidate rankings built for "
          f"{len(records_by_scope['ETF_SLICE'])} ETF_SLICE dates", flush=True)

    economics = build_candidate_economics(
        records_by_scope, sets_by_scope, segments)
    paired = build_paired_rows(records_by_scope, sets_by_scope, segments)
    robustness = build_robustness_rows(
        records_by_scope, sets_by_scope, segments, episodes)
    verdicts = gate_verdicts(economics, paired, robustness)
    for candidate, flags in verdicts.items():
        print(f"[offense] verdict {candidate}: {flags}", flush=True)

    snapshot_path = Path(args.snapshot_jsonl)
    cache_index = load_cache_symbol_index(Path(args.cache_dir))
    snapshot_records = (
        load_snapshot_records(snapshot_path, cache_index)
        if snapshot_path.exists() else []
    )
    snapshot_rows = build_snapshot_comparison(snapshot_records)
    print(f"[offense] snapshot records: {len(snapshot_records)}", flush=True)

    report = render_report(
        base_name=Path(args.base_dataset).name,
        base_rows=int(len(base_frame)),
        base_dates=int(base_frame["signal_date"].nunique()),
        bear_name=Path(args.bear_2022_dataset).name,
        bear_rows=int(len(bear_frame)),
        bear_dates=int(bear_frame["signal_date"].nunique()),
        snapshot_name=Path(args.snapshot_jsonl).name,
        snapshot_sha=_snapshot_sha(snapshot_path),
        snapshot_rows=len(snapshot_records),
        runner_sha=replay._sha256_file(
            REPO_ROOT / "scripts" / "validate_growth_compounder_offense.py"
        ) or "",
        command=_runner_command(args),
        base_sha=replay._sha256_file(Path(args.base_dataset)) or "",
        bear_sha=replay._sha256_file(Path(args.bear_2022_dataset)) or "",
        economics=economics,
        paired=paired,
        robustness=robustness,
        snapshot_rows_data=snapshot_rows,
        verdicts=verdicts,
    )
    files = {
        "candidate_cohort_economics.csv": replay._csv_text(
            economics, COHORT_COLUMNS),
        "paired_deltas_vs_v2.csv": replay._csv_text(paired, PAIRED_COLUMNS),
        "robustness_ex_top5_and_episodes.csv": replay._csv_text(
            robustness, ROBUSTNESS_COLUMNS),
        "snap_20261015_top15_comparison.csv": replay._csv_text(
            snapshot_rows, SNAPSHOT_COLUMNS),
        "report.md": report,
    }
    out_dir = replay.write_outputs(Path(args.output_dir), files)
    total = sum(path.stat().st_size for path in out_dir.iterdir())
    print(
        f"[offense] wrote {len(files) + 1} files, {total} bytes to "
        f"{out_dir.name}",
        flush=True,
    )
    return {
        "verdicts": verdicts,
        "output_dir": str(out_dir),
        "n_snapshot_records": len(snapshot_records),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
