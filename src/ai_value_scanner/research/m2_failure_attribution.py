"""Phase M2 systematic v1 failure attribution & metric validity audit.

Strictly offline, read-only diagnostic module for Phase M2 of the post-PR #70
roadmap (`docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md`,
Phase M2 spec `docs/agent_specs/track_b_m2_failure_attribution_and_metric_audit_spec.md`).

All functions here are pure and deterministic: no file I/O, no network calls,
no production-logic modification. Production decision builders
(`decision.quality.build_company_quality_v1`) are *called* read-only for exact
counterfactual grade recomputation -- never altered.

Epistemic guardrails enforced by this module:
- Forward-return diagnostics are computed ONLY on the 24 development dates
  (`2023-01-31` through `2024-12-31`). Every return diagnostic filters through
  :func:`development_frame` internally, so 2025/2026Q1 labels can never leak.
- No function emits filesystem paths; generated artifacts must never contain
  `/home/...` or `/tmp/...` (see :func:`contains_absolute_path`).
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

import pandas as pd

from ai_value_scanner.decision.quality import build_company_quality_v1


# ---------------------------------------------------------------------------
# Frozen study constants
# ---------------------------------------------------------------------------

DEVELOPMENT_DATES: tuple[str, ...] = (
    "2023-01-31", "2023-02-28", "2023-03-31", "2023-04-28",
    "2023-05-31", "2023-06-30", "2023-07-31", "2023-08-31",
    "2023-09-29", "2023-10-31", "2023-11-30", "2023-12-29",
    "2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30",
    "2024-05-31", "2024-06-28", "2024-07-31", "2024-08-30",
    "2024-09-30", "2024-10-31", "2024-11-29", "2024-12-31",
)
DEVELOPMENT_DATE_SET = frozenset(DEVELOPMENT_DATES)

SNAP510_ID = "snap510_2026-10-09_313c5ff"
SNAP62_ID = "snap62_2026-10-12_220a471"
HISTORICAL_ID = "historical_v3_20261011_03"

# Mirrors of frozen v1 thresholds (read, never modified):
READY_RS60_MIN = -0.03
OVEREXTENDED_RET20_GT = 0.15
ENTRY_READY_SMA50_LO = 0.98
ENTRY_READY_SMA50_HI = 1.08
ENTRY_READY_RET20_LO = -0.03
ENTRY_READY_RET20_HI = 0.12
ENTRY_READY_DD_MAX = 0.22
ENTRY_VOL_MAX = 0.80
QUALITY_A_MIN_SCORE = 0.72
QUALITY_A_MIN_CONFIDENCE = 0.80

WATCH_BREAKOUT_BUCKETS = (
    "MILD_EXTENDED_PULLBACK",
    "NEAR_BREAKOUT_CONSOLIDATION",
    "WEAK_OR_LAGGING_STRUCTURE",
    "UNOBSERVABLE_FEATURES",
)

_ABSOLUTE_PATH_RE = re.compile(r"(?:/home/|/tmp/)\S*")


def contains_absolute_path(text: str) -> bool:
    """True if text contains a /home/... or /tmp/... absolute path."""
    return bool(_ABSOLUTE_PATH_RE.search(text or ""))


# ---------------------------------------------------------------------------
# Scalar numeric helpers
# ---------------------------------------------------------------------------


def finite_or_none(value: Any) -> float | None:
    """Return float(value) if finite, else None (None/NaN/bool/str-safe)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def is_explicit_false(value: Any) -> bool:
    """True only for an explicit False (NaN/None/0.0 are not False)."""
    if value is None or isinstance(value, bool):
        return value is False
    try:
        if isinstance(value, float) and math.isnan(value):
            return False
    except TypeError:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no"}
    return False


def frame_number(frame: pd.DataFrame, column: str) -> pd.Series:
    """Finite-float series for column, NaN where missing/unparseable."""
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


# ---------------------------------------------------------------------------
# Return embargo
# ---------------------------------------------------------------------------


def development_frame(
    frame: pd.DataFrame, date_col: str = "signal_date"
) -> pd.DataFrame:
    """Return only the 24 development-date rows (2023-01-31..2024-12-31).

    Every forward-return diagnostic in this module filters through this
    helper, so 2025/2026Q1 labels remain unpeeked for M4 validation.
    Cross-sectional feature/state counts (no fwd_ret_* reads) may use the
    full frame; return statistics must use this one.
    """
    if date_col not in frame.columns or frame.empty:
        return frame.iloc[0:0].copy()
    return frame.loc[
        frame[date_col].astype(str).isin(DEVELOPMENT_DATE_SET)
    ].copy()


def excess_return_60d(frame: pd.DataFrame) -> pd.Series:
    """Per-row 60d net QQQ excess where both legs are finite, else NaN."""
    fwd = frame_number(frame, "fwd_ret_60")
    qqq = frame_number(frame, "qqq_return_60")
    out = fwd - qqq
    return out.where(fwd.notna() & qqq.notna())


def date_equal_excess_by_group(
    frame: pd.DataFrame,
    group_col: str,
    *,
    date_col: str = "signal_date",
) -> dict[str, dict[str, float | int]]:
    """Date-equal 60d net QQQ excess per group on development dates only.

    Per date, take the group mean excess over rows with valid 60d legs,
    then average those date means (dates equally weighted; overlapping
    60d rows are never treated as independent samples).
    """
    dev = development_frame(frame, date_col=date_col)
    if dev.empty or group_col not in dev.columns:
        return {}
    dev = dev.copy()
    dev["_excess_60d"] = excess_return_60d(dev)
    valid = dev.loc[dev["_excess_60d"].notna()]
    result: dict[str, dict[str, float | int]] = {}
    for group, gframe in valid.groupby(group_col, sort=True):
        date_means = gframe.groupby(date_col)["_excess_60d"].mean()
        result[str(group)] = {
            "n_dates": int(date_means.size),
            "n_obs": int(len(gframe)),
            "mean_excess": round(float(date_means.mean()), 6),
            "median_date_mean_excess": round(float(date_means.median()), 6),
        }
    return result


# ---------------------------------------------------------------------------
# Entry-structure classifiers (Axes 5, 6, 8)
# ---------------------------------------------------------------------------


def defensive_from_features(
    regime: Any, benchmark_trend_ok: Any
) -> bool | None:
    """Mirror v1 defensive trigger: regime down OR benchmark explicitly not-ok.

    Returns None when the regime signal is unobservable. True means the
    defensive regime is present (the extra confirmation gate applies).
    """
    try:
        if regime is None or (not isinstance(regime, str) and pd.isna(regime)):
            regime = ""
    except (TypeError, ValueError):
        regime = ""
    regime_text = str(regime or "").strip().lower()
    if regime_text == "down" or is_explicit_false(benchmark_trend_ok):
        return True
    if regime_text == "up":
        return False
    if regime_text == "" and benchmark_trend_ok is None:
        return None
    try:
        if pd.isna(benchmark_trend_ok) and regime_text == "":
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(benchmark_trend_ok, bool):
        return not benchmark_trend_ok
    return False


def defensive_gate_ok(
    regime: Any,
    benchmark_trend_ok: Any,
    relative_strength_60d_qqq: Any = None,
    return_20d: Any = None,
) -> bool | None:
    """True when the v1 defensive entry gate is satisfied.

    Non-defensive regimes always pass. Defensive regimes pass only with
    extra confirmation (RS60 >= 5% and ret20 >= 0%). None when the regime
    signal itself is unobservable.
    """
    defensive = defensive_from_features(regime, benchmark_trend_ok)
    if defensive is None:
        return None
    if not defensive:
        return True
    rs60 = finite_or_none(relative_strength_60d_qqq)
    ret20 = finite_or_none(return_20d)
    if rs60 is None or ret20 is None:
        return None
    return bool(rs60 >= 0.05 and ret20 >= 0.0)


def classify_watch_breakout(
    *,
    state: Any,
    price_to_sma200: Any = None,
    price_to_sma50: Any = None,
    return_20d: Any = None,
    return_60d: Any = None,
    relative_strength_60d_qqq: Any = None,
    drawdown_from_52w_high: Any = None,
    volatility_60d: Any = None,
    defensive_ok: bool | None = None,
) -> str:
    """Partition a WATCH_BREAKOUT observation into heterogeneity buckets.

    - MILD_EXTENDED_PULLBACK: trend/60d/RS/drawdown/vol/defensive gates pass;
      the only failures are high-side extension (sma50 > 1.08 or ret20 > 0.12).
    - NEAR_BREAKOUT_CONSOLIDATION: sma200 >= 1.0, ret60 >= -0.03,
      RS60 >= -0.06, but not mildly extended.
    - WEAK_OR_LAGGING_STRUCTURE: sma200 < 1.0 or ret60 < -0.03 or RS < -0.06.
    - UNOBSERVABLE_FEATURES: a required gate value is missing.
    """
    if str(state or "") != "WATCH_BREAKOUT":
        return "NOT_WATCH_BREAKOUT"
    sma200 = finite_or_none(price_to_sma200)
    sma50 = finite_or_none(price_to_sma50)
    ret20 = finite_or_none(return_20d)
    ret60 = finite_or_none(return_60d)
    rs60 = finite_or_none(relative_strength_60d_qqq)
    drawdown = finite_or_none(drawdown_from_52w_high)
    volatility = finite_or_none(volatility_60d)
    if sma200 is None or ret60 is None or rs60 is None:
        return "UNOBSERVABLE_FEATURES"
    if sma200 < 1.0 or ret60 < -0.03 or rs60 < -0.06:
        return "WEAK_OR_LAGGING_STRUCTURE"
    vol_ok = volatility is None or volatility <= ENTRY_VOL_MAX
    mild = (
        ret60 >= 0.0
        and rs60 >= READY_RS60_MIN
        and drawdown is not None
        and drawdown <= ENTRY_READY_DD_MAX
        and vol_ok
        and defensive_ok is True
        and ((sma50 is not None and sma50 > ENTRY_READY_SMA50_HI)
             or (ret20 is not None and ret20 > ENTRY_READY_RET20_HI))
        and not (sma50 is not None and sma50 < ENTRY_READY_SMA50_LO)
        and not (ret20 is not None and ret20 < ENTRY_READY_RET20_LO)
    )
    if mild:
        return "MILD_EXTENDED_PULLBACK"
    return "NEAR_BREAKOUT_CONSOLIDATION"


def is_dead_zone_pullback(
    *,
    state: Any,
    price_to_sma200: Any = None,
    price_to_sma50: Any = None,
    return_20d: Any = None,
    return_60d: Any = None,
    relative_strength_60d_qqq: Any = None,
    drawdown_from_52w_high: Any = None,
    volatility_60d: Any = None,
    defensive_ok: bool | None = None,
) -> bool:
    """True for Axis 5 dead-zone rows: healthy trend whose ONLY readiness
    failure is sma50 in (1.08, 1.10] or ret20 in (12%, 15%]."""
    if str(state or "") != "WATCH_BREAKOUT":
        return False
    sma200 = finite_or_none(price_to_sma200)
    sma50 = finite_or_none(price_to_sma50)
    ret20 = finite_or_none(return_20d)
    ret60 = finite_or_none(return_60d)
    rs60 = finite_or_none(relative_strength_60d_qqq)
    drawdown = finite_or_none(drawdown_from_52w_high)
    volatility = finite_or_none(volatility_60d)
    if (
        sma200 is None or sma50 is None or ret20 is None
        or ret60 is None or rs60 is None or drawdown is None
    ):
        return False
    if defensive_ok is not True:
        return False
    if not (
        sma200 >= 1.0
        and ret60 >= 0.0
        and rs60 >= READY_RS60_MIN
        and drawdown <= ENTRY_READY_DD_MAX
        and (volatility is None or volatility <= ENTRY_VOL_MAX)
    ):
        return False
    in_sma50_dead_zone = ENTRY_READY_SMA50_HI < sma50 <= 1.10
    in_ret20_dead_zone = ENTRY_READY_RET20_HI < ret20 <= OVEREXTENDED_RET20_GT
    if not (in_sma50_dead_zone or in_ret20_dead_zone):
        return False
    if sma50 < ENTRY_READY_SMA50_LO or ret20 < ENTRY_READY_RET20_LO:
        return False
    return True


def sma50_to_sma200_ratio(
    price_to_sma200: Any, price_to_sma50: Any
) -> float | None:
    """Exact identity: SMA50/SMA200 = price_to_sma200 / price_to_sma50."""
    numerator = finite_or_none(price_to_sma200)
    denominator = finite_or_none(price_to_sma50)
    if numerator is None or denominator is None or denominator == 0.0:
        return None
    return numerator / denominator


# ---------------------------------------------------------------------------
# Quality counterfactuals (Axes 1, 2) -- exact rebuilds via frozen v1 code
# ---------------------------------------------------------------------------


def accrual_fix_applies(row: Mapping[str, Any]) -> bool:
    """Cash-cow condition: negative accrual while OCF covers earnings."""
    accrual = finite_or_none(row.get("accrual_ratio"))
    ocf = finite_or_none(row.get("ocf_to_net_income"))
    return accrual is not None and accrual <= 0.0 and ocf is not None and ocf >= 1.0


def high_growth_cash_generative(row: Mapping[str, Any]) -> bool:
    """Axis 2 exemption condition: rapid growth with healthy conversion."""
    revenue_yoy = finite_or_none(row.get("revenue_yoy"))
    ocf = finite_or_none(row.get("ocf_to_net_income"))
    return (
        revenue_yoy is not None
        and revenue_yoy >= 0.25
        and ocf is not None
        and ocf >= 0.80
    )


def counterfactual_quality_grade(
    row: Mapping[str, Any],
    *,
    fix_accrual: bool = False,
    zero_working_capital_gaps: bool = False,
) -> str:
    """Rebuild the v1 Quality grade under an M3-style metric fix.

    fix_accrual zeroes a negative accrual_ratio when the cash-cow condition
    holds (exact equivalent of scoring it 1.0 through the frozen code path).
    zero_working_capital_gaps zeroes receivables/inventory growth gaps when
    the high-growth cash-generative condition holds. Returns the grade value.
    """
    patched = dict(row)
    if fix_accrual and accrual_fix_applies(row):
        patched["accrual_ratio"] = 0.0
    if zero_working_capital_gaps and high_growth_cash_generative(row):
        patched["receivables_growth_gap"] = 0.0
        patched["inventory_growth_gap"] = 0.0
    decision = build_company_quality_v1(
        patched,
        decision_date=row.get("signal_date"),
        data_asof=row.get("fundamental_data_asof"),
    )
    return decision.grade.value


def margin_or_none(numerator: Any, revenue: Any) -> float | None:
    """Return numerator/revenue when revenue is positive, else None."""
    top = finite_or_none(numerator)
    bottom = finite_or_none(revenue)
    if top is None or bottom is None or bottom <= 0.0:
        return None
    return top / bottom


QUALITY_COUNTERFACTUAL_KEYS: tuple[str, ...] = (
    "net_margin",
    "free_cash_flow",
    "ocf_to_net_income",
    "accrual_ratio",
    "revenue_yoy",
    "adjusted_net_income_yoy",
    "net_income_yoy",
    "operating_cash_flow_yoy",
    "net_debt_to_ebitda",
    "interest_coverage",
    "current_ratio",
    "shares_yoy",
    "fcf_yield",
    "ps_hist_percentile",
    "pe_hist_percentile",
    "receivables_growth_gap",
    "inventory_growth_gap",
)


def counterfactual_eligible(row: Mapping[str, Any], min_keys: int = 12) -> bool:
    """True when a row carries enough of the v1 quality metric vector for an
    exact grade-rebuild counterfactual.

    Snapshot evidence serializes only emitted metrics, so pre-M1 snapshot
    rows are typically ineligible; historical v3 rows (full facts) qualify.
    Ineligible rows are skipped and counted, never rebuilt.
    """
    observed = sum(1 for key in QUALITY_COUNTERFACTUAL_KEYS if finite_or_none(row.get(key)) is not None)
    return observed >= min_keys


# ---------------------------------------------------------------------------
# Snapshot parsing (decisions.jsonl dicts -> analysis frame)
# ---------------------------------------------------------------------------

ENTRY_FEATURE_METRICS = (
    "price_to_sma200",
    "price_to_sma50",
    "days_below_sma200",
    "return_20d",
    "return_60d",
    "drawdown_from_52w_high",
    "range_position_52w",
    "relative_strength_60d_qqq",
    "volatility_60d",
)

QUALITY_VALUE_METRICS = (
    "net_margin",
    "free_cash_flow",
    "ocf_to_net_income",
    "accrual_ratio",
    "revenue_yoy",
    "adjusted_net_income_yoy",
    "operating_cash_flow_yoy",
    "net_debt_to_ebitda",
    "interest_coverage",
    "current_ratio",
    "shares_yoy",
    "fcf_yield",
    "ps_hist_percentile",
    "pe_hist_percentile",
    "receivables_growth_gap",
    "inventory_growth_gap",
    "revenue",
    "ebit",
    "adjusted_ebit",
)


def evidence_feature_map(decision: Mapping[str, Any], side: str) -> dict[str, float]:
    """Collect metric -> value from a decision side's positives + risks."""
    out: dict[str, float] = {}
    section = decision.get(side, {})
    items: Sequence[Mapping[str, Any]] = []
    if isinstance(section, Mapping):
        for key in ("positives", "risks"):
            group = section.get(key, [])
            if isinstance(group, Sequence):
                items = [*items, *group]
    for item in items:
        if not isinstance(item, Mapping):
            continue
        metric = item.get("metric")
        value = finite_or_none(item.get("value"))
        if isinstance(metric, str) and metric and value is not None:
            out.setdefault(metric, value)
    return out


def snapshot_frame(
    decisions: Sequence[Mapping[str, Any]],
    top15_symbols: Sequence[str],
    dataset_id: str,
) -> pd.DataFrame:
    """Flatten frozen StockDecision dicts into an M2 analysis frame.

    Entry/quality features come from emitted evidence values only; gates
    that were silent in pre-M1 snapshots stay missing (UNOBSERVABLE).
    """
    top15 = {str(symbol).strip().upper() for symbol in top15_symbols}
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, Mapping):
            continue
        quality = decision.get("quality", {})
        entry = decision.get("entry", {})
        symbol = str(decision.get("symbol", "") or "").strip().upper()
        entry_features = evidence_feature_map(decision, "entry")
        quality_values = evidence_feature_map(decision, "quality")
        row: dict[str, Any] = {
            "dataset_id": dataset_id,
            "signal_date": str(decision.get("decision_date", "") or ""),
            "symbol": symbol,
            "quality_grade": quality.get("grade") if isinstance(quality, Mapping) else None,
            "quality_score": finite_or_none(quality.get("score")) if isinstance(quality, Mapping) else None,
            "quality_confidence": finite_or_none(quality.get("confidence")) if isinstance(quality, Mapping) else None,
            "entry_state": entry.get("state") if isinstance(entry, Mapping) else None,
            "entry_score": finite_or_none(entry.get("score")) if isinstance(entry, Mapping) else None,
            "entry_confidence": finite_or_none(entry.get("confidence")) if isinstance(entry, Mapping) else None,
            "action_state": decision.get("action_state"),
            "priority": decision.get("priority"),
            "selected_top15": symbol in top15,
        }
        for metric in ENTRY_FEATURE_METRICS:
            row[metric] = entry_features.get(metric)
        for metric in QUALITY_VALUE_METRICS:
            row[metric] = quality_values.get(metric)
        comp_scores = quality.get("component_scores", {}) if isinstance(quality, Mapping) else {}
        for pillar in PRODUCTION_PILLARS:
            value = comp_scores.get(pillar) if isinstance(comp_scores, Mapping) else None
            row[f"comp_{pillar}"] = finite_or_none(value)
        provenance = decision.get("provenance", {})
        row["filing_accession"] = (
            provenance.get("fundamental_latest_periodic_accession")
            if isinstance(provenance, Mapping) else None
        )
        for side, prefix in (("quality", "quality"), ("entry", "entry")):
            section = decision.get(side, {})
            for key in ("risks", "positives", "missing"):
                items = section.get(key, []) if isinstance(section, Mapping) else []
                codes = [
                    str(item.get("code", ""))
                    for item in items
                    if isinstance(item, Mapping) and item.get("code")
                ]
                row[f"{prefix}_{key}_codes"] = ",".join(codes)
        entry_risks = set((row.get("entry_risks_codes") or "").split(","))
        if "defensive_market_regime" in entry_risks:
            row["defensive_ok"] = False
        elif "supportive_market_regime" in {
            code for code in (row.get("entry_positives_codes") or "").split(",")
        }:
            row["defensive_ok"] = True
        else:
            row["defensive_ok"] = None
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    return frame


# ---------------------------------------------------------------------------
# Axis tables (work on any rated frame with the documented columns)
# ---------------------------------------------------------------------------


def rated_mask(frame: pd.DataFrame) -> pd.Series:
    """Rows with an assigned (non-UNRATED) quality grade."""
    if frame.empty or "quality_grade" not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame["quality_grade"].astype(str).ne("UNRATED") & frame["quality_grade"].notna()


def axis1_accrual_table(frame: pd.DataFrame) -> dict[str, Any]:
    """Axis 1: abs(accrual) false-positive cash-cow penalty + upgrades."""
    accrual = frame_number(frame, "accrual_ratio")
    ocf = frame_number(frame, "ocf_to_net_income")
    fcf = frame_number(frame, "free_cash_flow")
    rated = rated_mask(frame)
    has_accrual = accrual.notna()
    lt_m10 = has_accrual & (accrual < -0.10)
    lt_m20 = has_accrual & (accrual < -0.20)
    cash_cow = (ocf >= 1.0) & (fcf > 0.0)
    fp_m10 = rated & lt_m10 & cash_cow.fillna(False)
    fp_m20 = rated & lt_m20 & cash_cow.fillna(False)
    upgrades_b_to_a: list[str] = []
    upgrades_c_to_b: list[str] = []
    n_candidates = 0
    n_sparse_skipped = 0
    for index, row in frame.loc[rated & has_accrual].iterrows():
        record = row.to_dict()
        if not accrual_fix_applies(record):
            continue
        n_candidates += 1
        if not counterfactual_eligible(record):
            n_sparse_skipped += 1
            continue
        before = str(row.get("quality_grade", ""))
        after = counterfactual_quality_grade(record, fix_accrual=True)
        tag = f"{row.get('signal_date')}:{row.get('symbol')}"
        if before == "B" and after == "A":
            upgrades_b_to_a.append(tag)
        elif before == "C" and after == "B":
            upgrades_c_to_b.append(tag)
    return {
        "n_rows": int(len(frame)),
        "n_rated": int(rated.sum()),
        "n_accrual_lt_m10": int(lt_m10.sum()),
        "n_accrual_lt_m20": int(lt_m20.sum()),
        "n_false_positive_m10": int(fp_m10.sum()),
        "n_false_positive_m20": int(fp_m20.sum()),
        "false_positive_rate_m10": round(float(fp_m10.sum() / rated.sum()), 6) if rated.sum() else 0.0,
        "false_positive_rate_m20": round(float(fp_m20.sum() / rated.sum()), 6) if rated.sum() else 0.0,
        "false_positive_symbols_m10": sorted(
            {str(symbol) for symbol in frame.loc[fp_m10, "symbol"].tolist()}
        ) if "symbol" in frame.columns else [],
        "n_accrual_fix_candidates": int(n_candidates),
        "n_sparse_rows_skipped": int(n_sparse_skipped),
        "n_upgrades_b_to_a": len(upgrades_b_to_a),
        "n_upgrades_c_to_b": len(upgrades_c_to_b),
        "upgrades_b_to_a": sorted(upgrades_b_to_a),
        "upgrades_c_to_b": sorted(upgrades_c_to_b),
    }


def axis2_working_capital_table(frame: pd.DataFrame) -> dict[str, Any]:
    """Axis 2: high-growth working-capital penalty + combined-fix upgrades."""
    revenue_yoy = frame_number(frame, "revenue_yoy")
    ocf = frame_number(frame, "ocf_to_net_income")
    recv_gap = frame_number(frame, "receivables_growth_gap")
    inv_gap = frame_number(frame, "inventory_growth_gap")
    rated = rated_mask(frame)
    high_growth = (revenue_yoy >= 0.25) & (ocf >= 0.80)
    high_growth = high_growth.fillna(False)
    penalized = high_growth & ((recv_gap > 0.15) | (inv_gap > 0.20))
    penalized = penalized.fillna(False)
    b_high = rated & high_growth & (frame["quality_grade"].astype(str) == "B") if "quality_grade" in frame.columns else rated & False
    reach_a_bars: list[str] = []
    reach_a_grade: list[str] = []
    n_sparse_skipped = 0
    for _, row in frame.loc[b_high & penalized].iterrows():
        record = row.to_dict()
        if not counterfactual_eligible(record):
            n_sparse_skipped += 1
            continue
        patched = dict(record)
        if high_growth_cash_generative(record):
            patched["receivables_growth_gap"] = 0.0
            patched["inventory_growth_gap"] = 0.0
        if accrual_fix_applies(record):
            patched["accrual_ratio"] = 0.0
        rebuilt = build_company_quality_v1(
            patched,
            decision_date=record.get("signal_date"),
            data_asof=record.get("fundamental_data_asof"),
        )
        tag = f"{row.get('signal_date')}:{row.get('symbol')}"
        if rebuilt.score >= QUALITY_A_MIN_SCORE and rebuilt.confidence >= QUALITY_A_MIN_CONFIDENCE:
            reach_a_bars.append(tag)
            if rebuilt.grade.value == "A":
                reach_a_grade.append(tag)
    return {
        "n_rows": int(len(frame)),
        "n_high_growth_healthy": int(high_growth.sum()),
        "n_penalized": int(penalized.sum()),
        "penalized_rate": round(float(penalized.sum() / high_growth.sum()), 6) if high_growth.sum() else 0.0,
        "penalized_symbols": sorted(
            {str(symbol) for symbol in frame.loc[penalized, "symbol"].tolist()}
        ) if "symbol" in frame.columns else [],
        "n_b_high_growth_penalized": int((b_high & penalized).sum()),
        "n_sparse_rows_skipped": int(n_sparse_skipped),
        "n_reach_a_bars": len(reach_a_bars),
        "n_reach_a_grade": len(reach_a_grade),
        "reach_a_bars": sorted(reach_a_bars),
        "reach_a_grade": sorted(reach_a_grade),
    }


def axis3_fcf_and_valuation_table(frame: pd.DataFrame) -> dict[str, Any]:
    """Axis 3: binary FCF>0 margin distribution + valuation-percentile drag."""
    fcf = frame_number(frame, "free_cash_flow")
    revenue = frame_number(frame, "revenue")
    with_fcf = fcf.notna() & (fcf > 0.0)
    margins = (fcf / revenue).where(with_fcf & revenue.gt(0.0))
    observed = margins.dropna()
    thin = observed[observed < 0.03]
    strong = observed[observed >= 0.15]
    rated = rated_mask(frame)
    grade_a = rated & (frame["quality_grade"].astype(str) == "A") if "quality_grade" in frame.columns else rated & False
    priority_review = frame["action_state"].astype(str).eq("PRIORITY_REVIEW") if "action_state" in frame.columns else rated & False

    def _flagged(mask: pd.Series) -> pd.Series:
        codes_q = frame.get("quality_risks_codes", pd.Series("", index=frame.index)).astype(str)
        codes_e = frame.get("entry_risks_codes", pd.Series("", index=frame.index)).astype(str)
        if "quality_risks_codes" not in frame.columns:
            return axis3_codes_from_rebuild(frame, mask)
        return mask & (
            codes_q.str.contains("ps_hist_percentile_weak")
            | codes_q.str.contains("pe_hist_percentile_weak")
        )

    flagged_a = _flagged(grade_a)
    flagged_pr = _flagged(priority_review)
    return {
        "n_rows": int(len(frame)),
        "n_fcf_positive": int(with_fcf.sum()),
        "n_fcf_margin_observed": int(observed.size),
        "n_fcf_margin_thin_lt_3pct": int(thin.size),
        "n_fcf_margin_strong_ge_15pct": int(strong.size),
        "fcf_margin_median": round(float(observed.median()), 6) if observed.size else None,
        "n_quality_a": int(grade_a.sum()),
        "n_quality_a_valuation_flagged": int(flagged_a.sum()),
        "n_priority_review": int(priority_review.sum()),
        "n_priority_review_valuation_flagged": int(flagged_pr.sum()),
        "valuation_flagged_a_symbols": sorted(
            str(symbol) for symbol in frame.loc[flagged_a, "symbol"].tolist()
        ) if "symbol" in frame.columns else [],
    }


def axis3_codes_from_rebuild(frame: pd.DataFrame, mask: pd.Series) -> pd.Series:
    """Fallback valuation-flag check via frozen v1 rebuild (historical rows)."""
    out = pd.Series(False, index=frame.index)
    for index, row in frame.loc[mask].iterrows():
        record = row.to_dict()
        decision = build_company_quality_v1(
            record,
            decision_date=record.get("signal_date"),
            data_asof=record.get("fundamental_data_asof"),
        )
        codes = {item.code for item in decision.risks}
        if "ps_hist_percentile_weak" in codes or "pe_hist_percentile_weak" in codes:
            out.loc[index] = True
    return out


def axis4_margin_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    """Axis 4: computability of operating_margin and fcf_margin from facts."""
    revenue = frame_number(frame, "revenue")
    ebit = frame_number(frame, "ebit")
    adjusted_ebit = frame_number(frame, "adjusted_ebit")
    fcf = frame_number(frame, "free_cash_flow")
    ebit_for_margin = adjusted_ebit.where(adjusted_ebit.notna(), ebit)
    operating_margin = (ebit_for_margin / revenue).where(revenue.gt(0.0))
    fcf_margin = (fcf / revenue).where(revenue.gt(0.0))
    return {
        "n_rows": int(len(frame)),
        "n_operating_margin_computable": int(operating_margin.notna().sum()),
        "operating_margin_coverage": round(float(operating_margin.notna().mean()), 6) if len(frame) else 0.0,
        "n_fcf_margin_computable": int(fcf_margin.notna().sum()),
        "fcf_margin_coverage": round(float(fcf_margin.notna().mean()), 6) if len(frame) else 0.0,
    }


def enrich_breakout_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach breakout_bucket, dead_zone_pullback, and sma ratio columns."""
    out = frame.copy()
    if "defensive_ok" not in out.columns:
        if {"regime", "benchmark_trend_ok"}.issubset(out.columns):
            out["defensive_ok"] = [
                defensive_gate_ok(
                    regime, trend,
                    row_rs, row_ret20,
                )
                for regime, trend, row_rs, row_ret20 in zip(
                    out["regime"],
                    out["benchmark_trend_ok"],
                    frame_number(out, "relative_strength_60d_qqq"),
                    frame_number(out, "return_20d"),
                )
            ]
        else:
            out["defensive_ok"] = None
    vol = frame_number(out, "volatility_60d")
    out["_vol_ok"] = vol.isna() | (vol <= ENTRY_VOL_MAX)

    def _bucket(row: pd.Series) -> str:
        defensive = row.get("defensive_ok")
        if defensive is not None and not isinstance(defensive, bool):
            try:
                defensive = None if pd.isna(defensive) else bool(defensive)
            except (TypeError, ValueError):
                defensive = None
        return classify_watch_breakout(
            state=row.get("entry_state"),
            price_to_sma200=row.get("price_to_sma200"),
            price_to_sma50=row.get("price_to_sma50"),
            return_20d=row.get("return_20d"),
            return_60d=row.get("return_60d"),
            relative_strength_60d_qqq=row.get("relative_strength_60d_qqq"),
            drawdown_from_52w_high=row.get("drawdown_from_52w_high"),
            volatility_60d=row.get("volatility_60d"),
            defensive_ok=defensive,
        )

    def _dead_zone(row: pd.Series) -> bool:
        defensive = row.get("defensive_ok")
        if defensive is not None and not isinstance(defensive, bool):
            try:
                defensive = None if pd.isna(defensive) else bool(defensive)
            except (TypeError, ValueError):
                defensive = None
        return is_dead_zone_pullback(
            state=row.get("entry_state"),
            price_to_sma200=row.get("price_to_sma200"),
            price_to_sma50=row.get("price_to_sma50"),
            return_20d=row.get("return_20d"),
            return_60d=row.get("return_60d"),
            relative_strength_60d_qqq=row.get("relative_strength_60d_qqq"),
            drawdown_from_52w_high=row.get("drawdown_from_52w_high"),
            volatility_60d=row.get("volatility_60d"),
            defensive_ok=defensive,
        )

    out["breakout_bucket"] = [_bucket(row) for _, row in out.iterrows()]
    out["dead_zone_pullback"] = [_dead_zone(row) for _, row in out.iterrows()]
    out["sma50_to_sma200"] = [
        sma50_to_sma200_ratio(row.get("price_to_sma200"), row.get("price_to_sma50"))
        for _, row in out.iterrows()
    ]
    return out


def axis5_dead_zone_table(frame: pd.DataFrame) -> dict[str, Any]:
    """Axis 5: dead-zone pullback rows hiding inside WATCH_BREAKOUT."""
    enriched = frame if "dead_zone_pullback" in frame.columns else enrich_breakout_columns(frame)
    is_wb = enriched["entry_state"].astype(str).eq("WATCH_BREAKOUT") if "entry_state" in enriched.columns else pd.Series(False, index=enriched.index)
    dead = is_wb & enriched["dead_zone_pullback"].astype(bool)
    return {
        "n_rows": int(len(frame)),
        "n_watch_breakout": int(is_wb.sum()),
        "n_dead_zone_pullback": int(dead.sum()),
        "dead_zone_share_of_breakout": round(float(dead.sum() / is_wb.sum()), 6) if is_wb.sum() else 0.0,
        "dead_zone_symbols": sorted(
            f"{date}:{symbol}"
            for date, symbol in zip(
                enriched.loc[dead, "signal_date"] if "signal_date" in enriched.columns else [],
                enriched.loc[dead, "symbol"] if "symbol" in enriched.columns else [],
            )
        ),
    }


def axis6_breakout_partition(
    frame: pd.DataFrame, *, with_returns: bool = False
) -> dict[str, Any]:
    """Axis 6: 3-way WATCH_BREAKOUT partition + dev-only return diagnostics."""
    enriched = frame if "breakout_bucket" in frame.columns else enrich_breakout_columns(frame)
    is_wb = enriched["entry_state"].astype(str).eq("WATCH_BREAKOUT") if "entry_state" in enriched.columns else pd.Series(False, index=enriched.index)
    buckets: dict[str, Any] = {}
    for bucket in WATCH_BREAKOUT_BUCKETS:
        mask = is_wb & enriched["breakout_bucket"].astype(str).eq(bucket)
        buckets[bucket] = {
            "n": int(mask.sum()),
            "share_of_breakout": round(float(mask.sum() / is_wb.sum()), 6) if is_wb.sum() else 0.0,
            "symbols": sorted(
                f"{date}:{symbol}"
                for date, symbol in zip(
                    enriched.loc[mask, "signal_date"] if "signal_date" in enriched.columns else [],
                    enriched.loc[mask, "symbol"] if "symbol" in enriched.columns else [],
                )
            ),
        }
    result: dict[str, Any] = {
        "n_rows": int(len(frame)),
        "n_watch_breakout": int(is_wb.sum()),
        "buckets": buckets,
    }
    if with_returns:
        sub = enriched.loc[is_wb].copy()
        sub["bucket_group"] = sub["breakout_bucket"].astype(str)
        result["dev_return_diagnostics"] = date_equal_excess_by_group(sub, "bucket_group")
        result["return_scope"] = "RETROSPECTIVE_EXPLORATORY_2023_2024_DEV_ONLY"
    return result


def axis7_attention_table(
    frame: pd.DataFrame, *, with_returns: bool = False
) -> dict[str, Any]:
    """Axis 7: Top-15 truncation and B+READY suppression."""
    out: dict[str, Any] = {"n_rows": int(len(frame))}
    if frame.empty or "signal_date" not in frame.columns:
        return out
    dates_truncated = 0
    n_truncated_obs = 0
    n_b_ready = 0
    n_b_ready_high = 0
    b_ready_high_symbols: list[str] = []
    per_date_pr: dict[str, int] = {}
    for date, group in frame.groupby("signal_date", sort=True):
        is_pr = group["action_state"].astype(str).eq("PRIORITY_REVIEW") if "action_state" in group.columns else pd.Series(False, index=group.index)
        n_pr = int(is_pr.sum())
        per_date_pr[str(date)] = n_pr
        if n_pr > 15:
            dates_truncated += 1
            n_truncated_obs += n_pr - 15
        b_ready = group[
            group["quality_grade"].astype(str).eq("B")
            & group["entry_state"].astype(str).eq("ENTRY_READY")
        ] if {"quality_grade", "entry_state"}.issubset(group.columns) else group.iloc[0:0]
        n_b_ready += len(b_ready)
        high = b_ready[
            frame_number(b_ready, "quality_score").ge(0.65)
            & frame_number(b_ready, "entry_score").ge(0.85)
        ]
        n_b_ready_high += len(high)
        b_ready_high_symbols.extend(
            f"{date}:{symbol}" for symbol in high["symbol"].tolist()
        ) if "symbol" in high.columns else None
    out.update({
        "n_dates": int(frame["signal_date"].nunique()),
        "n_dates_truncated": int(dates_truncated),
        "n_truncated_a_ready_obs": int(n_truncated_obs),
        "n_b_ready_obs": int(n_b_ready),
        "n_b_ready_high_obs": int(n_b_ready_high),
        "b_ready_high_symbols": sorted(b_ready_high_symbols),
        "per_date_priority_review_counts": per_date_pr,
    })
    if with_returns:
        comp = frame.copy()
        comp["attention_group"] = "OTHER"
        pr = comp["action_state"].astype(str).eq("PRIORITY_REVIEW")
        a_ready = pr & comp["quality_grade"].astype(str).eq("A")
        top15 = comp.get("selected_top15", pd.Series(False, index=comp.index)).astype(bool)
        comp.loc[a_ready & top15, "attention_group"] = "A_READY_TOP15"
        comp.loc[a_ready & ~top15, "attention_group"] = "A_READY_RANK16_PLUS"
        b_high = (
            comp["quality_grade"].astype(str).eq("B")
            & comp["entry_state"].astype(str).eq("ENTRY_READY")
            & frame_number(comp, "quality_score").ge(0.65)
        )
        comp.loc[b_high, "attention_group"] = "B_READY_HIGH"
        weak_wb = comp["breakout_bucket"].astype(str).eq("WEAK_OR_LAGGING_STRUCTURE") if "breakout_bucket" in comp.columns else pd.Series(False, index=comp.index)
        a_weak_wb = comp["quality_grade"].astype(str).eq("A") & weak_wb
        comp.loc[a_weak_wb, "attention_group"] = "A_WB_WEAK"
        out["dev_return_diagnostics"] = date_equal_excess_by_group(comp, "attention_group")
        out["return_scope"] = "RETROSPECTIVE_EXPLORATORY_2023_2024_DEV_ONLY"
    return out


# ---------------------------------------------------------------------------
# Frozen case registry contract (33 stratified cases + resolution)
# ---------------------------------------------------------------------------

CASEBOOK_COLUMNS: tuple[str, ...] = (
    "study_case_id",
    "case_selection_method",
    "evidence_tier",
    "signal_date",
    "symbol",
    "source_snapshot_sha",
    "scanner_code_sha",
    "config_sha",
    "candidate_universe_asof",
    "security_id_or_unverified",
    "issuer_cik_or_unverified",
    "filing_accession_or_unverified",
    "facts_fingerprint_or_unverified",
    "quality_grade",
    "quality_score",
    "confidence",
    "quality_evidence_codes",
    "missing_codes",
    "entry_state",
    "entry_evidence_codes",
    "action_state",
    "priority",
    "selected_top5",
    "selected_top15",
    "excluded_reason",
    "review_question",
    "observed_failure_hypothesis",
    "alternate_explanations",
    "data_verdict",
    "human_review_verdict",
    "review_time_or_unknown",
    "future_label_valid",
    "forward_label_definition",
    "realized_outcome_if_exploratory",
    "reviewer_notes",
    "source_links",
)

TAXONOMY_TAGS = (
    "DATA/IDENTITY ERROR",
    "ACCOUNTING SEMANTIC GAP",
    "EVIDENCE PRESENTATION GAP",
    "RANK/CAP STRUCTURAL GAP",
    "ENTRY TIMING GAP",
    "UNIVERSE/PIT BIAS",
    "CORPORATE_ACTION/LABEL UNCERTAINTY",
    "IRREDUCIBLE UNCERTAINTY",
    "POSITIVE_CONTROL",
)

TAXONOMY_BY_DEFECT: dict[str, str] = {
    "accrual_sign_inversion": "ACCOUNTING SEMANTIC GAP",
    "working_capital_growth_penalty": "ACCOUNTING SEMANTIC GAP",
    "binary_fcf_gate": "ACCOUNTING SEMANTIC GAP",
    "valuation_percentile_drag": "ACCOUNTING SEMANTIC GAP",
    "missing_margin_pillars": "ACCOUNTING SEMANTIC GAP",
    "specialist_accounting_scope": "ACCOUNTING SEMANTIC GAP",
    "pullback_dead_zone": "ENTRY TIMING GAP",
    "ma_alignment_missing": "ENTRY TIMING GAP",
    "breakout_heterogeneity": "EVIDENCE PRESENTATION GAP",
    "top15_truncation": "RANK/CAP STRUCTURAL GAP",
    "b_ready_suppression": "RANK/CAP STRUCTURAL GAP",
    "weak_breakout_rank": "RANK/CAP STRUCTURAL GAP",
    "top15_opportunity_cost": "RANK/CAP STRUCTURAL GAP",
    "none": "POSITIVE_CONTROL",
}

REVIEW_QUESTION_BY_AXIS: dict[str, str] = {
    "Axis1": "Does abs(accrual) penalize cash-cow OCF>NI economics?",
    "Axis2": "Do point-in-time WC gaps penalize funded high growth?",
    "Axis3": "Does binary FCF>0 / self-history valuation misgrade quality?",
    "Axis4": "Are operating/fcf margins computable from existing facts?",
    "Axis5": "Is this WATCH_BREAKOUT a dead-zone pullback misrouted from WATCH_PULLBACK?",
    "Axis6": "Which WATCH_BREAKOUT sub-bucket (mild/near/weak) applies?",
    "Axis7": "Who lost Top-15 attention to cap/rank mechanics on this date?",
    "Axis8": "Are trend moving averages aligned (sma50_to_sma200>=1)?",
    "Control": "Does v1 behave correctly here (reference to preserve)?",
    "Paired": "Same-date opportunity cost: selected member vs suppressed alternative?",
}

EVIDENCE_TIER_STRATIFIED = "STRATIFIED_PRE"
EVIDENCE_TIER_EXPLORATORY = "RETROSPECTIVE_EXPLORATORY"
EVIDENCE_TIER_CONTROL = "POSITIVE_CONTROL"


def _has_code(frame: pd.DataFrame, column: str, code: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.contains(code, regex=False)


def _stratum_predicates() -> dict[str, Any]:
    """Named deterministic row predicates for case resolution."""
    return {
        "accrual_cash_cow_b": lambda f: (
            f["quality_grade"].astype(str).eq("B")
            & _has_code(f, "quality_risks_codes", "accrual_ratio_weak")
            & _has_code(f, "quality_positives_codes", "ocf_to_net_income_strong")
            & _has_code(f, "quality_positives_codes", "free_cash_flow_strong")
        ),
        "high_growth_gap_b": lambda f: (
            f["quality_grade"].astype(str).eq("B")
            & (_has_code(f, "quality_risks_codes", "receivables_growth_gap_weak")
               | _has_code(f, "quality_risks_codes", "inventory_growth_gap_weak"))
            & frame_number(f, "revenue_yoy").ge(0.25)
            & frame_number(f, "ocf_to_net_income").ge(0.80)
        ),
        "thin_fcf_margin": lambda f: (
            frame_number(f, "free_cash_flow").gt(0.0)
            & (frame_number(f, "free_cash_flow") / frame_number(f, "revenue")).lt(0.03)
            & frame_number(f, "revenue").gt(0.0)
        ),
        "a_ready_valuation_drag": lambda f: (
            f["quality_grade"].astype(str).eq("A")
            & f["entry_state"].astype(str).eq("ENTRY_READY")
            & (_has_code(f, "quality_risks_codes", "ps_hist_percentile_weak")
               | _has_code(f, "quality_risks_codes", "pe_hist_percentile_weak"))
        ),
        "margin_computable": lambda f: (
            frame_number(f, "revenue").gt(0.0)
            & (frame_number(f, "adjusted_ebit").notna() | frame_number(f, "ebit").notna())
            & frame_number(f, "free_cash_flow").notna()
        ),
        "crm_silent_breakout": lambda f: (
            f["symbol"].astype(str).eq("CRM")
            & f["entry_state"].astype(str).eq("WATCH_BREAKOUT")
        ),
        "dead_zone": lambda f: f["dead_zone_pullback"].astype(bool) if "dead_zone_pullback" in f.columns else pd.Series(False, index=f.index),
        "bucket_mild": lambda f: f["breakout_bucket"].astype(str).eq("MILD_EXTENDED_PULLBACK") if "breakout_bucket" in f.columns else pd.Series(False, index=f.index),
        "bucket_near": lambda f: f["breakout_bucket"].astype(str).eq("NEAR_BREAKOUT_CONSOLIDATION") if "breakout_bucket" in f.columns else pd.Series(False, index=f.index),
        "bucket_weak": lambda f: f["breakout_bucket"].astype(str).eq("WEAK_OR_LAGGING_STRUCTURE") if "breakout_bucket" in f.columns else pd.Series(False, index=f.index),
        "a_ready_truncated": lambda f: (
            f["quality_grade"].astype(str).eq("A")
            & f["entry_state"].astype(str).eq("ENTRY_READY")
            & f["action_state"].astype(str).eq("PRIORITY_REVIEW")
            & ~f["selected_top15"].astype(bool)
        ),
        "b_ready_high": lambda f: (
            f["quality_grade"].astype(str).eq("B")
            & f["entry_state"].astype(str).eq("ENTRY_READY")
            & frame_number(f, "quality_score").ge(0.65)
            & frame_number(f, "entry_score").ge(0.85)
        ),
        "a_weak_breakout": lambda f: (
            f["quality_grade"].astype(str).eq("A")
            & f["breakout_bucket"].astype(str).eq("WEAK_OR_LAGGING_STRUCTURE")
        ) if "breakout_bucket" in f.columns else pd.Series(False, index=f.index),
        "inverted_ready": lambda f: (
            f["entry_state"].astype(str).eq("ENTRY_READY")
            & frame_number(f, "sma50_to_sma200").lt(1.0)
        ) if "sma50_to_sma200" in f.columns else pd.Series(False, index=f.index),
        "inverted_breakout": lambda f: (
            f["entry_state"].astype(str).eq("WATCH_BREAKOUT")
            & frame_number(f, "sma50_to_sma200").lt(1.0)
        ) if "sma50_to_sma200" in f.columns else pd.Series(False, index=f.index),
        "retro_marginal_selected": lambda f: (
            f["action_state"].astype(str).eq("PRIORITY_REVIEW")
            & pd.to_numeric(f["priority"], errors="coerce").between(11, 15)
        ) if {"action_state", "priority"}.issubset(f.columns) else pd.Series(False, index=f.index),
        "retro_suppressed_opportunity": lambda f: (
            (f["quality_grade"].astype(str).eq("A")
             & f["entry_state"].astype(str).eq("ENTRY_READY")
             & ~f["selected_top15"].astype(bool))
            | (f["quality_grade"].astype(str).eq("B")
               & f["entry_state"].astype(str).eq("ENTRY_READY")
               & frame_number(f, "quality_score").ge(0.65))
        ) if {"quality_grade", "entry_state", "selected_top15"}.issubset(f.columns) else pd.Series(False, index=f.index),
        "clean_ready_control": lambda f: (
            f["quality_grade"].astype(str).eq("A")
            & f["entry_state"].astype(str).eq("ENTRY_READY")
            & f["selected_top15"].astype(bool)
            & (f["quality_risks_codes"].astype(str).eq("") if "quality_risks_codes" in f.columns else True)
        ),
        "good_reject_control": lambda f: (
            f["quality_grade"].astype(str).isin(["C", "UNRATED"])
            & f["action_state"].astype(str).eq("AVOID")
        ),
        "specialist_unrated": lambda f: (
            f["quality_grade"].astype(str).eq("UNRATED")
            & f["symbol"].astype(str).isin(["GS", "JPM", "BAC", "MS", "AMT", "EQIX", "O", "PLD"])
        ),
        "pullback_control": lambda f: (
            f["quality_grade"].astype(str).eq("A")
            & f["entry_state"].astype(str).eq("WATCH_PULLBACK")
        ),
        "damaged_control": lambda f: (
            f["quality_grade"].astype(str).eq("A")
            & f["entry_state"].astype(str).eq("TREND_DAMAGED")
        ),
    }


# (case_id, axis, datasets-in-preference-order, predicate, preferred symbols,
#  tier, defect tags)
CASE_STRATA: tuple[tuple[str, str, tuple[str, ...], str, tuple[str, ...], str, str], ...] = (
    ("M2-A1-SNAP01", "Axis1", ("snap62", "snap510"), "accrual_cash_cow_b", ("CRM", "META", "MSFT", "EOG"), EVIDENCE_TIER_STRATIFIED, "accrual_sign_inversion"),
    ("M2-A1-HIST01", "Axis1", ("hist_dev",), "accrual_cash_cow_b", (), EVIDENCE_TIER_STRATIFIED, "accrual_sign_inversion"),
    ("M2-A1-HIST02", "Axis1", ("hist_dev",), "accrual_cash_cow_b", (), EVIDENCE_TIER_STRATIFIED, "accrual_sign_inversion"),
    ("M2-A1-HIST03", "Axis1", ("hist_dev",), "accrual_cash_cow_b", (), EVIDENCE_TIER_STRATIFIED, "accrual_sign_inversion"),
    ("M2-A2-SNAP01", "Axis2", ("snap62", "snap510"), "high_growth_gap_b", ("NVDA", "MU", "TER", "AMAT"), EVIDENCE_TIER_STRATIFIED, "working_capital_growth_penalty"),
    ("M2-A2-HIST01", "Axis2", ("hist_dev",), "high_growth_gap_b", (), EVIDENCE_TIER_STRATIFIED, "working_capital_growth_penalty"),
    ("M2-A2-HIST02", "Axis2", ("hist_dev",), "high_growth_gap_b", (), EVIDENCE_TIER_STRATIFIED, "working_capital_growth_penalty"),
    ("M2-A2-HIST03", "Axis2", ("hist_dev",), "high_growth_gap_b", (), EVIDENCE_TIER_STRATIFIED, "working_capital_growth_penalty"),
    ("M2-A3-THIN01", "Axis3", ("hist_dev", "snap510"), "thin_fcf_margin", (), EVIDENCE_TIER_STRATIFIED, "binary_fcf_gate"),
    ("M2-A3-THIN02", "Axis3", ("hist_dev",), "thin_fcf_margin", (), EVIDENCE_TIER_STRATIFIED, "binary_fcf_gate"),
    ("M2-A3-VALSNAP01", "Axis3", ("snap62", "snap510"), "a_ready_valuation_drag", ("ETN", "MSFT", "EOG"), EVIDENCE_TIER_STRATIFIED, "valuation_percentile_drag"),
    ("M2-A3-VALHIST01", "Axis3", ("hist_dev",), "a_ready_valuation_drag", (), EVIDENCE_TIER_STRATIFIED, "valuation_percentile_drag"),
    ("M2-A4-COV01", "Axis4", ("hist_dev",), "margin_computable", (), EVIDENCE_TIER_STRATIFIED, "missing_margin_pillars"),
    ("M2-A5-CRM01", "Axis5", ("snap62",), "crm_silent_breakout", ("CRM",), EVIDENCE_TIER_STRATIFIED, "pullback_dead_zone"),
    ("M2-A5-HIST01", "Axis5", ("hist_dev",), "dead_zone", (), EVIDENCE_TIER_STRATIFIED, "pullback_dead_zone"),
    ("M2-A5-SNAP510-01", "Axis5", ("snap510", "hist_dev"), "dead_zone", (), EVIDENCE_TIER_STRATIFIED, "pullback_dead_zone"),
    ("M2-A6-MILD01", "Axis6", ("hist_dev",), "bucket_mild", (), EVIDENCE_TIER_STRATIFIED, "breakout_heterogeneity"),
    ("M2-A6-NEAR01", "Axis6", ("hist_dev", "snap510"), "bucket_near", (), EVIDENCE_TIER_STRATIFIED, "breakout_heterogeneity"),
    ("M2-A6-NEAR02", "Axis6", ("hist_dev",), "bucket_near", (), EVIDENCE_TIER_STRATIFIED, "breakout_heterogeneity"),
    ("M2-A6-WEAK01", "Axis6", ("hist_dev", "snap62"), "bucket_weak", ("CAT", "LIN"), EVIDENCE_TIER_STRATIFIED, "breakout_heterogeneity"),
    ("M2-A6-WEAK62-01", "Axis6", ("snap62",), "bucket_weak", ("CAT", "LIN"), EVIDENCE_TIER_STRATIFIED, "breakout_heterogeneity"),
    ("M2-A7-TRUNC01", "Axis7", ("hist_dev", "snap510"), "a_ready_truncated", (), EVIDENCE_TIER_STRATIFIED, "top15_truncation"),
    ("M2-A7-TRUNC02", "Axis7", ("snap510", "hist_dev"), "a_ready_truncated", (), EVIDENCE_TIER_STRATIFIED, "top15_truncation"),
    ("M2-A7-BREADY01", "Axis7", ("snap62", "snap510", "hist_dev"), "b_ready_high", ("NVDA", "MU", "TER", "AMZN", "META", "AMD"), EVIDENCE_TIER_STRATIFIED, "b_ready_suppression"),
    ("M2-A7-BREADY02", "Axis7", ("hist_dev",), "b_ready_high", (), EVIDENCE_TIER_STRATIFIED, "b_ready_suppression"),
    ("M2-A7-WEAKOUT01", "Axis7", ("hist_dev",), "a_weak_breakout", (), EVIDENCE_TIER_STRATIFIED, "weak_breakout_rank"),
    ("M2-A8-INVREADY01", "Axis8", ("hist_dev",), "inverted_ready", (), EVIDENCE_TIER_STRATIFIED, "ma_alignment_missing"),
    ("M2-A8-INVBREAK01", "Axis8", ("hist_dev", "snap510"), "inverted_breakout", (), EVIDENCE_TIER_STRATIFIED, "ma_alignment_missing"),
    ("M2-C-READY01", "Control", ("snap510", "snap62"), "clean_ready_control", ("TEL", "ETN", "APH"), EVIDENCE_TIER_CONTROL, "none"),
    ("M2-C-READY02", "Control", ("snap62", "snap510"), "clean_ready_control", ("ETN", "KO", "EOG"), EVIDENCE_TIER_CONTROL, "none"),
    ("M2-C-REJECT01", "Control", ("hist_dev", "snap510"), "good_reject_control", (), EVIDENCE_TIER_CONTROL, "none"),
    ("M2-C-UNRATED01", "Control", ("snap510", "snap62", "hist_dev"), "specialist_unrated", ("GS", "JPM", "PLD"), EVIDENCE_TIER_CONTROL, "specialist_accounting_scope"),
    ("M2-C-PULLBACK01", "Control", ("hist_dev", "snap510"), "pullback_control", (), EVIDENCE_TIER_CONTROL, "none"),
    ("M2-C-DAMAGED01", "Control", ("hist_dev", "snap510"), "damaged_control", (), EVIDENCE_TIER_CONTROL, "none"),
    ("M2-R-SEL01", "Paired", ("hist_dev",), "retro_marginal_selected", (), EVIDENCE_TIER_EXPLORATORY, "top15_opportunity_cost", None),
    ("M2-R-REJ01", "Paired", ("hist_dev",), "retro_suppressed_opportunity", (), EVIDENCE_TIER_EXPLORATORY, "top15_opportunity_cost", "M2-R-SEL01"),
    ("M2-R-SEL02", "Paired", ("hist_dev",), "retro_marginal_selected", (), EVIDENCE_TIER_EXPLORATORY, "top15_opportunity_cost", None),
    ("M2-R-REJ02", "Paired", ("hist_dev",), "retro_suppressed_opportunity", (), EVIDENCE_TIER_EXPLORATORY, "top15_opportunity_cost", "M2-R-SEL02"),
)


def resolve_case_registry(
    frames: Mapping[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    """Resolve each frozen stratum to a concrete (date, symbol) row.

    Deterministic: datasets tried in stratum preference order; within a
    dataset, preferred symbols first, then earliest signal_date, then symbol.
    Already-claimed (dataset, date, symbol) rows are skipped so cases are
    distinct. Unmatched strata resolve to status UNMATCHED (reported, never
    fabricated).
    """
    predicates = _stratum_predicates()
    used: set[tuple[str, str, str]] = set()
    resolved: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for stratum in CASE_STRATA:
        case_id, axis, datasets, predicate_key, preferred, tier, tags = stratum[:7]
        same_date_as = stratum[7] if len(stratum) > 7 else None
        predicate = predicates[predicate_key]
        match: dict[str, Any] | None = None
        pair_date: str | None = None
        if same_date_as is not None and same_date_as in by_id:
            pair_match = by_id[same_date_as].get("match") or {}
            pair_date = str(pair_match.get("signal_date", "") or "") or None
        for dataset_key in datasets:
            frame = frames.get(dataset_key)
            if frame is None or frame.empty:
                continue
            if pair_date is not None:
                if "signal_date" not in frame.columns:
                    continue
                frame = frame.loc[frame["signal_date"].astype(str).eq(pair_date)]
                if frame.empty:
                    continue
            try:
                mask = predicate(frame).fillna(False).astype(bool)
            except (KeyError, TypeError, ValueError):
                continue
            candidates = frame.loc[mask]
            if candidates.empty:
                continue
            order = candidates.assign(
                _pref=candidates["symbol"].astype(str).apply(
                    lambda s: preferred.index(s) if s in preferred else len(preferred)
                )
            ).sort_values(
                ["_pref", "signal_date", "symbol"], ascending=[True, True, True]
            )
            for _, row in order.iterrows():
                key = (dataset_key, str(row.get("signal_date", "")), str(row.get("symbol", "")))
                if key not in used:
                    used.add(key)
                    record = row.to_dict()
                    record["dataset_key"] = dataset_key
                    match = record
                    break
            if match is not None:
                break
        resolved.append({
            "study_case_id": case_id,
            "primary_axis": axis,
            "dataset_preference": list(datasets),
            "predicate": predicate_key,
            "preferred_symbols": list(preferred),
            "evidence_tier": tier,
            "metric_defect_tags": tags,
            "same_date_as": same_date_as,
            "status": "MATCHED" if match is not None else "UNMATCHED",
            "match": match,
        })
        by_id[case_id] = resolved[-1]
    return resolved


def axis8_trend_alignment_table(frame: pd.DataFrame) -> dict[str, Any]:
    """Axis 8: sma50_to_sma200 alignment among READY and BREAKOUT rows."""
    enriched = frame if "sma50_to_sma200" in frame.columns else enrich_breakout_columns(frame)
    ratio = pd.to_numeric(enriched["sma50_to_sma200"], errors="coerce")
    result: dict[str, Any] = {"n_rows": int(len(frame))}
    for state in ("ENTRY_READY", "WATCH_BREAKOUT"):
        mask = enriched["entry_state"].astype(str).eq(state) if "entry_state" in enriched.columns else pd.Series(False, index=enriched.index)
        observable = mask & ratio.notna()
        inverted = observable & (ratio < 1.0)
        result[state] = {
            "n": int(mask.sum()),
            "n_observable": int(observable.sum()),
            "n_inverted": int(inverted.sum()),
            "inverted_share_of_observable": round(float(inverted.sum() / observable.sum()), 6) if observable.sum() else 0.0,
            "inverted_symbols": sorted(
                f"{date}:{symbol}"
                for date, symbol in zip(
                    enriched.loc[inverted, "signal_date"] if "signal_date" in enriched.columns else [],
                    enriched.loc[inverted, "symbol"] if "symbol" in enriched.columns else [],
                )
            ),
        }
    return result


# ---------------------------------------------------------------------------
# Gap 2 -- 6-pillar Company Quality v1 decomposition
# ---------------------------------------------------------------------------

PRODUCTION_PILLARS: tuple[str, ...] = (
    "profitability_cash",
    "growth_stability",
    "balance_sheet",
    "dilution",
    "valuation_context",
    "operating_red_flags",
)

PILLAR_DISPLAY_NAMES: dict[str, str] = {
    "profitability_cash": "profitability_and_cash_conversion",
    "growth_stability": "growth_and_stability",
    "balance_sheet": "balance_sheet_resilience",
    "dilution": "dilution_and_capital_discipline",
    "valuation_context": "valuation_context",
    "operating_red_flags": "red_flags",
}

# Production code weights (quality.py) vs spec-canonical weights. The audit
# reports means/coverage/rates (weight-free facts) under the spec display
# names; both weight schedules are carried for adjudication because they
# differ on profitability (0.30 vs 0.25) and red_flags (0.10 vs 0.15).
PILLAR_PRODUCTION_WEIGHTS: dict[str, float] = {
    "profitability_cash": 0.30,
    "growth_stability": 0.20,
    "balance_sheet": 0.20,
    "dilution": 0.10,
    "valuation_context": 0.10,
    "operating_red_flags": 0.10,
}
PILLAR_SPEC_WEIGHTS: dict[str, float] = {
    "profitability_cash": 0.25,
    "growth_stability": 0.20,
    "balance_sheet": 0.20,
    "dilution": 0.10,
    "valuation_context": 0.10,
    "operating_red_flags": 0.15,
}

PILLAR_METRIC_KEYS: dict[str, tuple[str, ...]] = {
    "profitability_cash": ("net_margin", "free_cash_flow", "ocf_to_net_income", "accrual_ratio"),
    "growth_stability": ("revenue_yoy", "adjusted_net_income_yoy", "net_income_yoy", "operating_cash_flow_yoy"),
    "balance_sheet": ("net_debt_to_ebitda", "interest_coverage", "current_ratio"),
    "dilution": ("shares_yoy",),
    "valuation_context": ("fcf_yield", "ps_hist_percentile", "pe_hist_percentile"),
    "operating_red_flags": ("receivables_growth_gap", "inventory_growth_gap"),
}


def pillar_decomposition_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Mean score / coverage / missing / weak-flag rate per pillar per grade.

    Requires comp_<production-pillar> score columns plus quality codes
    columns; rows lacking codes report None rates (never fabricated).
    """
    rows: list[dict[str, Any]] = []
    if frame.empty or "quality_grade" not in frame.columns:
        return rows
    has_codes = {"quality_risks_codes", "quality_missing_codes"}.issubset(frame.columns)
    for grade in ("A", "B", "C", "UNRATED"):
        group = frame.loc[frame["quality_grade"].astype(str).eq(grade)]
        if group.empty:
            continue
        risks = group["quality_risks_codes"].astype(str) if has_codes else pd.Series("", index=group.index)
        missing = group["quality_missing_codes"].astype(str) if has_codes else pd.Series("", index=group.index)
        for pillar in PRODUCTION_PILLARS:
            scores = pd.to_numeric(group.get(f"comp_{pillar}"), errors="coerce")
            keys = PILLAR_METRIC_KEYS[pillar]
            weak = pd.Series(False, index=group.index)
            miss = pd.Series(False, index=group.index)
            for key in keys:
                weak = weak | risks.str.contains(f"{key}_weak", regex=False)
                miss = miss | missing.str.contains(f"{key}_missing", regex=False)
            rows.append({
                "grade": grade,
                "pillar": PILLAR_DISPLAY_NAMES[pillar],
                "production_pillar": pillar,
                "n": int(len(group)),
                "mean_score": round(float(scores.mean()), 6) if scores.notna().any() else None,
                "coverage": round(float(scores.notna().mean()), 6),
                "missing_rate": round(float(miss.mean()), 6) if has_codes else None,
                "weak_flag_rate": round(float(weak.mean()), 6) if has_codes else None,
                "weight_production": PILLAR_PRODUCTION_WEIGHTS[pillar],
                "weight_spec_canonical": PILLAR_SPEC_WEIGHTS[pillar],
            })
    return rows


def growth_split_excess(frame: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    """Dev-only date-equal 60d excess: A/B-C x high/low revenue growth."""
    dev = development_frame(frame)
    if dev.empty:
        return {}
    dev = dev.copy()
    rev = frame_number(dev, "revenue_yoy")
    grade = dev["quality_grade"].astype(str) if "quality_grade" in dev.columns else ""
    dev["growth_group"] = "OTHER"
    dev.loc[grade.eq("A") & rev.ge(0.25), "growth_group"] = "A_HIGH_GROWTH"
    dev.loc[grade.eq("A") & rev.lt(0.25), "growth_group"] = "A_LOW_GROWTH"
    dev.loc[grade.isin(["B", "C"]) & rev.ge(0.25), "growth_group"] = "BC_HIGH_GROWTH"
    dev.loc[grade.isin(["B", "C"]) & rev.lt(0.25), "growth_group"] = "BC_LOW_GROWTH"
    return date_equal_excess_by_group(dev, "growth_group")


# ---------------------------------------------------------------------------
# Gap 3 -- cross-industry / business-model bias audit
# ---------------------------------------------------------------------------

ARCHETYPE_SOFTWARE = "SOFTWARE_AND_ASSET_LIGHT_TECH"
ARCHETYPE_SEMI = "SEMICONDUCTOR_AND_AI_HARDWARE"
ARCHETYPE_INDUSTRIAL = "INDUSTRIAL_AND_MANUFACTURING"
ARCHETYPE_HEAVY = "HEAVY_ASSET_AND_UTILITIES"
ARCHETYPE_CYCLICAL = "CYCLICAL_RESOURCES_AND_ENERGY"
ARCHETYPE_FINANCIAL = "FINANCIALS_AND_SPECIALIST_REITS"
ARCHETYPE_UNCLASSIFIED = "UNCLASSIFIED_RESIDUAL"

ARCHETYPES: tuple[str, ...] = (
    ARCHETYPE_SOFTWARE,
    ARCHETYPE_SEMI,
    ARCHETYPE_INDUSTRIAL,
    ARCHETYPE_HEAVY,
    ARCHETYPE_CYCLICAL,
    ARCHETYPE_FINANCIAL,
)


def sic_to_archetype(sic: Any) -> str:
    """Deterministic SIC -> business-model archetype (documented ranges).

    Anything outside the six archetype ranges reports UNCLASSIFIED_RESIDUAL
    (listed explicitly, never force-fit).
    """
    try:
        if sic is None or (not isinstance(sic, str) and pd.isna(sic)):
            return ARCHETYPE_UNCLASSIFIED
        code = int(float(str(sic).strip()))
    except (TypeError, ValueError):
        return ARCHETYPE_UNCLASSIFIED
    if 6000 <= code <= 6999:
        return ARCHETYPE_FINANCIAL
    if 4000 <= code <= 4999:
        return ARCHETYPE_HEAVY
    if 1000 <= code <= 1499:
        return ARCHETYPE_CYCLICAL
    if 2830 <= code <= 2839:
        return ARCHETYPE_UNCLASSIFIED
    if (2800 <= code <= 2899) or (2900 <= code <= 2999):
        return ARCHETYPE_CYCLICAL
    if 3200 <= code <= 3399:
        return ARCHETYPE_CYCLICAL
    if (3570 <= code <= 3579) or (3660 <= code <= 3669) or (3670 <= code <= 3679):
        return ARCHETYPE_SEMI
    if 7370 <= code <= 7379:
        return ARCHETYPE_SOFTWARE
    if (1500 <= code <= 1799) or (2400 <= code <= 2799) or (3000 <= code <= 3199):
        return ARCHETYPE_INDUSTRIAL
    if (3400 <= code <= 3569) or (3580 <= code <= 3659) or (3680 <= code <= 3999):
        return ARCHETYPE_INDUSTRIAL
    if 5000 <= code <= 5199:
        return ARCHETYPE_INDUSTRIAL
    return ARCHETYPE_UNCLASSIFIED


def build_symbol_archetype_map(frame: pd.DataFrame) -> dict[str, str]:
    """Most-common SIC per symbol -> archetype (for snapshot enrichment)."""
    if frame.empty or not {"symbol", "sic"}.issubset(frame.columns):
        return {}
    mapping: dict[str, str] = {}
    symbols = frame["symbol"].astype(str)
    for symbol, group in frame.groupby(symbols, sort=True):
        try:
            mode_sic = pd.to_numeric(group["sic"], errors="coerce").dropna().mode()
        except (TypeError, ValueError):
            mode_sic = pd.Series(dtype=float)
        mapping[str(symbol)] = sic_to_archetype(mode_sic.iloc[0] if len(mode_sic) else None)
    return mapping


def _top_codes(series: pd.Series, suffix: str, top: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for text in series.astype(str).tolist():
        for code in text.split(","):
            code = code.strip()
            if code.endswith(suffix):
                counts[code] = counts.get(code, 0) + 1
    return [f"{code}={counts[code]}" for code in sorted(counts, key=lambda c: (-counts[c], c))[:top]]


def industry_bias_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-archetype grade shares, confidence, missing rates, top flags."""
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows
    if "archetype" not in frame.columns:
        if "sic" in frame.columns:
            frame = frame.copy()
            frame["archetype"] = [sic_to_archetype(v) for v in frame["sic"].tolist()]
        else:
            return rows
    conf = frame_number(frame, "quality_confidence")
    has_codes = {"quality_risks_codes", "quality_missing_codes"}.issubset(frame.columns)
    for archetype in (*ARCHETYPES, ARCHETYPE_UNCLASSIFIED):
        group = frame.loc[frame["archetype"].astype(str).eq(archetype)]
        if group.empty:
            continue
        grades = group["quality_grade"].astype(str) if "quality_grade" in group.columns else pd.Series(dtype=str)
        rows.append({
            "archetype": archetype,
            "n": int(len(group)),
            "share_a": round(float(grades.eq("A").mean()), 6) if len(group) else 0.0,
            "share_b": round(float(grades.eq("B").mean()), 6) if len(group) else 0.0,
            "share_c": round(float(grades.eq("C").mean()), 6) if len(group) else 0.0,
            "share_unrated": round(float(grades.eq("UNRATED").mean()), 6) if len(group) else 0.0,
            "mean_confidence": round(float(conf.loc[group.index].mean()), 6) if conf.loc[group.index].notna().any() else None,
            "top_missing": ";".join(_top_codes(group["quality_missing_codes"], "_missing")) if has_codes else "",
            "top_weak_flags": ";".join(_top_codes(group["quality_risks_codes"], "_weak")) if has_codes else "",
        })
    return rows


# ---------------------------------------------------------------------------
# Gap 1 -- same-date Top-15 replacement / opportunity-cost comparison
# ---------------------------------------------------------------------------


def replacement_comparison(frame: pd.DataFrame, *, with_returns: bool = False) -> dict[str, Any]:
    """Marginal #11-15 members vs excluded A+READY-16+ / B+READY, same dates."""
    per_date: list[dict[str, Any]] = []
    if frame.empty or "signal_date" not in frame.columns:
        return {"per_date": per_date, "summary": {}}
    for date, group in frame.groupby("signal_date", sort=True):
        is_pr = group["action_state"].astype(str).eq("PRIORITY_REVIEW") if "action_state" in group.columns else pd.Series(False, index=group.index)
        marginal = group.loc[is_pr & pd.to_numeric(group.get("priority"), errors="coerce").between(11, 15)] if "priority" in group.columns else group.iloc[0:0]
        excl_a = group.loc[
            group["quality_grade"].astype(str).eq("A")
            & group["entry_state"].astype(str).eq("ENTRY_READY")
            & ~group["selected_top15"].astype(bool)
        ] if {"quality_grade", "entry_state", "selected_top15"}.issubset(group.columns) else group.iloc[0:0]
        excl_b = group.loc[
            group["quality_grade"].astype(str).eq("B")
            & group["entry_state"].astype(str).eq("ENTRY_READY")
            & frame_number(group, "quality_score").ge(0.65)
        ] if {"quality_grade", "entry_state"}.issubset(group.columns) else group.iloc[0:0]
        if marginal.empty and excl_a.empty and excl_b.empty:
            continue
        has_opportunity = (not marginal.empty) and (not excl_a.empty or not excl_b.empty)

        def _chars(sub: pd.DataFrame) -> dict[str, Any]:
            if sub.empty:
                return {"n": 0, "symbols": [], "mean_q": None, "mean_e": None, "val_weak_share": None}
            codes = sub["quality_risks_codes"].astype(str) if "quality_risks_codes" in sub.columns else pd.Series("", index=sub.index)
            val_weak = codes.str.contains("ps_hist_percentile_weak") | codes.str.contains("pe_hist_percentile_weak")
            return {
                "n": int(len(sub)),
                "symbols": sorted(str(s) for s in sub["symbol"].tolist()) if "symbol" in sub.columns else [],
                "mean_q": round(float(frame_number(sub, "quality_score").mean()), 4) if frame_number(sub, "quality_score").notna().any() else None,
                "mean_e": round(float(frame_number(sub, "entry_score").mean()), 4) if frame_number(sub, "entry_score").notna().any() else None,
                "val_weak_share": round(float(val_weak.mean()), 4),
            }

        per_date.append({
            "signal_date": str(date),
            "has_opportunity": bool(has_opportunity),
            "marginal_11_15": _chars(marginal),
            "excluded_a_ready_16plus": _chars(excl_a),
            "excluded_b_ready_high": _chars(excl_b),
        })
    result: dict[str, Any] = {
        "per_date": per_date,
        "summary": {
            "n_dates_with_opportunity": int(sum(
                1 for d in per_date
                if (d["excluded_a_ready_16plus"]["n"] or d["excluded_b_ready_high"]["n"]) and d["marginal_11_15"]["n"]
            )),
            "n_dates": int(frame["signal_date"].nunique()),
        },
    }
    if with_returns:
        pool = frame.copy()
        pool["replacement_group"] = "OTHER"
        is_pr = pool["action_state"].astype(str).eq("PRIORITY_REVIEW") if "action_state" in pool.columns else pd.Series(False, index=pool.index)
        marginal_mask = is_pr & pd.to_numeric(pool.get("priority"), errors="coerce").between(11, 15) if "priority" in pool.columns else pd.Series(False, index=pool.index)
        excl_mask = (
            (pool["quality_grade"].astype(str).eq("A") & pool["entry_state"].astype(str).eq("ENTRY_READY") & ~pool["selected_top15"].astype(bool))
            | (pool["quality_grade"].astype(str).eq("B") & pool["entry_state"].astype(str).eq("ENTRY_READY") & frame_number(pool, "quality_score").ge(0.65))
        ) if {"quality_grade", "entry_state", "selected_top15"}.issubset(pool.columns) else pd.Series(False, index=pool.index)
        pool.loc[marginal_mask, "replacement_group"] = "MARGINAL_11_15"
        pool.loc[excl_mask, "replacement_group"] = "EXCLUDED_OPPORTUNITY"
        result["dev_return_diagnostics"] = date_equal_excess_by_group(pool, "replacement_group")
        result["return_scope"] = "RETROSPECTIVE_EXPLORATORY_2023_2024_DEV_ONLY"
    return result


# ---------------------------------------------------------------------------
# Gap 5 -- report-evidence parity checks
# ---------------------------------------------------------------------------


def check_snapshot_top15(
    decisions: list[dict[str, Any]], daily_symbols: list[str]
) -> dict[str, Any]:
    """Verify manifest Top-15 == first-15 by priority and all PRIORITY_REVIEW."""
    ordered = sorted(
        [d for d in decisions if isinstance(d, dict)],
        key=lambda d: (d.get("priority") if isinstance(d.get("priority"), int) else 10**9,
                       str(d.get("symbol", ""))),
    )
    top15 = [str(d.get("symbol", "") or "").strip().upper() for d in ordered[:15]]
    expected = [str(s).strip().upper() for s in daily_symbols]
    mismatches = [f"rank{i + 1}:{got}!=manifest:{want}" for i, (got, want) in enumerate(zip(top15, expected)) if got != want]
    if len(top15) != len(expected):
        mismatches.append(f"length {len(top15)} != manifest {len(expected)}")
    non_pr = [
        f"{str(d.get('symbol', ''))}={d.get('action_state')}"
        for d in ordered[:15] if d.get("action_state") != "PRIORITY_REVIEW"
    ]
    return {
        "n_decisions": len(ordered),
        "top15_match_manifest": not mismatches,
        "mismatches": mismatches,
        "all_top15_priority_review": not non_pr,
        "non_pr_members": non_pr,
    }


def check_detailed_reports(
    decisions: list[dict[str, Any]],
    daily_symbols: list[str],
    detailed_texts: dict[str, str],
) -> dict[str, Any]:
    """Verify each Top-15 detailed report exists and names its decision."""
    by_symbol = {str(d.get("symbol", "") or "").strip().upper(): d for d in decisions if isinstance(d, dict)}
    missing_files: list[str] = []
    content_mismatches: list[str] = []
    for symbol in [str(s).strip().upper() for s in daily_symbols]:
        text = detailed_texts.get(symbol, "")
        if not text:
            missing_files.append(symbol)
            continue
        decision = by_symbol.get(symbol, {})
        for token in (symbol, str(decision.get("action_state", "")), str((decision.get("quality", {}) or {}).get("grade", ""))):
            if token and token not in text:
                content_mismatches.append(f"{symbol}:missing:{token}")
    return {
        "n_top15": len(daily_symbols),
        "n_reports_found": len(daily_symbols) - len(missing_files),
        "missing_files": missing_files,
        "content_mismatches": content_mismatches,
        "consistent": not missing_files and not content_mismatches,
    }


def count_silent_nonready(frame: pd.DataFrame) -> dict[str, Any]:
    """Count WATCH_BREAKOUT / TREND_DAMAGED rows with zero entry risks."""
    codes = frame["entry_risks_codes"].astype(str) if "entry_risks_codes" in frame.columns else pd.Series("", index=frame.index)
    empty = codes.str.strip().eq("")
    states = frame["entry_state"].astype(str) if "entry_state" in frame.columns else pd.Series("", index=frame.index)
    wb = states.eq("WATCH_BREAKOUT")
    td = states.eq("TREND_DAMAGED")
    return {
        "n_watch_breakout": int(wb.sum()),
        "n_watch_breakout_silent": int((wb & empty).sum()),
        "n_trend_damaged": int(td.sum()),
        "n_trend_damaged_silent": int((td & empty).sum()),
    }


def entry_subgate_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-gate ENTRY_READY failure counts (observable rows only)."""
    cols = {
        "sma200": frame_number(frame, "price_to_sma200"),
        "sma50": frame_number(frame, "price_to_sma50"),
        "ret20": frame_number(frame, "return_20d"),
        "ret60": frame_number(frame, "return_60d"),
        "rs60": frame_number(frame, "relative_strength_60d_qqq"),
        "drawdown": frame_number(frame, "drawdown_from_52w_high"),
        "vol": frame_number(frame, "volatility_60d"),
    }
    gates: list[tuple[str, str, Any]] = [
        ("sma200_below_1", "sma200", cols["sma200"].lt(1.0)),
        ("sma50_outside_ready_band", "sma50",
         cols["sma50"].lt(ENTRY_READY_SMA50_LO) | cols["sma50"].gt(ENTRY_READY_SMA50_HI)),
        ("ret20_outside_ready_band", "ret20",
         cols["ret20"].lt(ENTRY_READY_RET20_LO) | cols["ret20"].gt(ENTRY_READY_RET20_HI)),
        ("ret60_negative", "ret60", cols["ret60"].lt(0.0)),
        ("rs60_below_ready", "rs60", cols["rs60"].lt(READY_RS60_MIN)),
        ("drawdown_above_cap", "drawdown", cols["drawdown"].gt(ENTRY_READY_DD_MAX)),
        ("volatility_high", "vol", cols["vol"].gt(ENTRY_VOL_MAX)),
    ]
    rows: list[dict[str, Any]] = []
    for name, key, fail in gates:
        observable = cols[key].notna()
        n_fail = int((fail.fillna(False) & observable).sum())
        rows.append({
            "gate": name,
            "n_observable": int(observable.sum()),
            "n_fail": n_fail,
            "fail_share": round(n_fail / int(observable.sum()), 6) if observable.sum() else 0.0,
        })
    return rows


# ---------------------------------------------------------------------------
# Gap 4 -- 36-column casebook row builder + paired RETRO strata
# ---------------------------------------------------------------------------


def excluded_reason_for(match: Mapping[str, Any]) -> str:
    """Machine-readable exclusion reason for a casebook row."""
    if match.get("selected_top15") is True:
        return "NOT_EXCLUDED_TOP15"
    action = str(match.get("action_state", ""))
    grade = str(match.get("quality_grade", ""))
    state = str(match.get("entry_state", ""))
    if action == "PRIORITY_REVIEW":
        return "RANK_16_PLUS_TRUNCATED"
    if grade == "B" and state == "ENTRY_READY":
        return "B_READY_SUPPRESSED_HOLD_MONITOR"
    if state == "WATCH_BREAKOUT":
        return "WATCH_BREAKOUT_NOT_READY"
    if state == "WATCH_PULLBACK":
        return "PULLBACK_WATCH_NOT_READY"
    if state == "TREND_DAMAGED":
        return "TREND_DAMAGED_HOLD_MONITOR"
    if action == "AVOID":
        return "AVOID_GRADE_OR_INSUFFICIENT"
    return "NOT_SELECTED"


def realized_excess_text(match: Mapping[str, Any]) -> str | None:
    """Realized 60d net-QQQ outcome; None unless a dev-date row (embargo)."""
    date = str(match.get("signal_date", "") or "")
    if date not in DEVELOPMENT_DATE_SET:
        return None
    fwd = finite_or_none(match.get("fwd_ret_60"))
    qqq = finite_or_none(match.get("qqq_return_60"))
    if fwd is None or qqq is None:
        return "LABEL_MISSING_DEV_DATE"
    return f"{fwd - qqq:+.6f}_60d_net_qqq_excess"


def casebook_row(
    entry: Mapping[str, Any],
    provenance: Mapping[str, Any],
    texts: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one exact 36-column roadmap casebook row."""
    match = entry.get("match") or {}
    tier = str(entry.get("evidence_tier", ""))
    is_retro = tier == EVIDENCE_TIER_EXPLORATORY
    realized = realized_excess_text(match) if (is_retro and match) else None
    priority = match.get("priority", "")
    try:
        selected_top5 = "TRUE" if int(priority) <= 5 else "FALSE"
    except (TypeError, ValueError):
        selected_top5 = ""
    quality_codes = str(match.get("quality_positives_codes", "") or "")
    if match.get("quality_risks_codes"):
        quality_codes = f"{quality_codes}|{match.get('quality_risks_codes')}" if quality_codes else str(match.get("quality_risks_codes"))
    entry_codes = str(match.get("entry_positives_codes", "") or "")
    if match.get("entry_risks_codes"):
        entry_codes = f"{entry_codes}|{match.get('entry_risks_codes')}" if entry_codes else str(match.get("entry_risks_codes"))
    return {
        "study_case_id": entry.get("study_case_id", ""),
        "case_selection_method": f"STRATIFIED:{entry.get('predicate', '')}" if tier != EVIDENCE_TIER_EXPLORATORY else f"PAIRED:{entry.get('predicate', '')}",
        "evidence_tier": tier,
        "signal_date": match.get("signal_date", ""),
        "symbol": match.get("symbol", ""),
        "source_snapshot_sha": provenance.get("source_snapshot_sha", "UNVERIFIED"),
        "scanner_code_sha": provenance.get("scanner_code_sha", "UNVERIFIED"),
        "config_sha": provenance.get("config_sha", "UNVERIFIED"),
        "candidate_universe_asof": provenance.get("candidate_universe_asof", "UNVERIFIED"),
        "security_id_or_unverified": match.get("symbol", "") or "UNVERIFIED",
        "issuer_cik_or_unverified": match.get("cik", "") or "UNVERIFIED",
        "filing_accession_or_unverified": match.get("filing_accession", "") or "UNVERIFIED",
        "facts_fingerprint_or_unverified": match.get("facts_fingerprint", "") or "UNVERIFIED",
        "quality_grade": match.get("quality_grade", ""),
        "quality_score": match.get("quality_score", ""),
        "confidence": match.get("quality_confidence", ""),
        "quality_evidence_codes": quality_codes,
        "missing_codes": match.get("quality_missing_codes", ""),
        "entry_state": match.get("entry_state", ""),
        "entry_evidence_codes": entry_codes,
        "action_state": match.get("action_state", ""),
        "priority": priority,
        "selected_top5": selected_top5 if match else "",
        "selected_top15": "TRUE" if match.get("selected_top15") is True else ("FALSE" if match else ""),
        "excluded_reason": excluded_reason_for(match) if match else "UNMATCHED",
        "review_question": REVIEW_QUESTION_BY_AXIS.get(str(entry.get("primary_axis", "")), ""),
        "observed_failure_hypothesis": texts.get("observed_failure_hypothesis", ""),
        "alternate_explanations": texts.get("alternate_explanations", ""),
        "data_verdict": texts.get("data_verdict", ""),
        "human_review_verdict": "PENDING_CHIEF_REVIEW",
        "review_time_or_unknown": "UNKNOWN",
        "future_label_valid": "TRUE" if (is_retro and realized not in (None, "LABEL_MISSING_DEV_DATE")) else "FALSE",
        "forward_label_definition": "fwd_ret_60_minus_qqq_return_60_over_60_trading_days" if is_retro else "UNPEEKED",
        "realized_outcome_if_exploratory": realized if realized is not None else "UNPEEKED_PRE_STRATIFIED",
        "reviewer_notes": texts.get("reviewer_notes", ""),
        "source_links": provenance.get("source_links", ""),
    }
