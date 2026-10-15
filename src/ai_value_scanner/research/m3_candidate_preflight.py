"""Phase M3 non-return preflight & frozen casebook verification (pure module).

Evaluates the 5 pre-registered variants (v1_baseline, h1_quality_only,
h2_entry_only, h3_action_only, v2_combined) without reading any forward
returns except through the embargoed development-date helper. No file I/O,
no network calls, no production-logic modification.

Snapshot variants rebuild from emitted evidence feature maps (partial
vectors); absolute v1_baseline counts on snapshots always come from the
frozen decisions.jsonl, and rebuild fidelity is reported explicitly.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.research import m2_failure_attribution as m2


VARIANTS: tuple[str, ...] = (
    "v1_baseline",
    "h1_quality_only",
    "h2_entry_only",
    "h3_action_only",
    "v2_combined",
)

VARIANT_STAGES: dict[str, dict[str, str]] = {
    "v1_baseline": {"quality_version": "v1", "entry_version": "v1", "action_version": "v1"},
    "h1_quality_only": {"quality_version": "v2", "entry_version": "v1", "action_version": "v1"},
    "h2_entry_only": {"quality_version": "v1", "entry_version": "v2", "action_version": "v1"},
    "h3_action_only": {"quality_version": "v1", "entry_version": "v1", "action_version": "v2"},
    "v2_combined": {"quality_version": "v2", "entry_version": "v2", "action_version": "v2"},
}

VARIANT_FALSIFIERS: dict[str, str] = {
    "h1_quality_only": "Falsified if <1% of B/C grades change on dev dates or reviewers reject new pillar explanations.",
    "h2_entry_only": "Falsified if seam rows show no date-equal excess gap vs NEAR on dev dates or sub-reasons are unactionable.",
    "h3_action_only": "Falsified if re-ranking swaps <2 Top-15 members on dev dates or joint rank rates less trustworthy.",
    "v2_combined": "Falsified if combined defects do not fall vs v1_baseline or any positive control breaks.",
}

RETURN_EMBARGO_TEXT = (
    "Forward-return diagnostics use ONLY the 24 development dates "
    "2023-01-31..2024-12-31; 2025/2026Q1 labels remain unpeeked for M4."
)


# ---------------------------------------------------------------------------
# Snapshot offline rebuilds (partial evidence feature maps)
# ---------------------------------------------------------------------------

SNAPSHOT_REBUILD_FEATURES: tuple[str, ...] = (
    *m2.ENTRY_FEATURE_METRICS,
    *m2.QUALITY_VALUE_METRICS,
)


_QUALITY_NEUTRAL_MIDPOINTS: dict[str, float] = {
    "net_margin": 0.06,
    "free_cash_flow": 0.0,
    "ocf_to_net_income": 0.65,
    "accrual_ratio": 0.15,
    "revenue_yoy": 0.03,
    "adjusted_net_income_yoy": 0.03,
    "operating_cash_flow_yoy": 0.03,
    "net_debt_to_ebitda": 2.2,
    "interest_coverage": 2.5,
    "current_ratio": 0.90,
    "shares_yoy": 0.05,
    "fcf_yield": 0.01,
    "ps_hist_percentile": 0.70,
    "pe_hist_percentile": 0.70,
    "receivables_growth_gap": 0.10,
    "inventory_growth_gap": 0.15,
}

_ENTRY_READY_NEUTRAL_MIDPOINTS: dict[str, float] = {
    "price_to_sma200": 1.05,
    "price_to_sma50": 1.02,
    "days_below_sma200": 0.0,
    "return_20d": 0.04,
    "return_60d": 0.05,
    "drawdown_from_52w_high": 0.10,
    "range_position_52w": 0.65,
    "relative_strength_60d_qqq": 0.0,
    "volatility_60d": 0.38,
}

_ENTRY_NON_READY_NEUTRAL_MIDPOINTS: dict[str, float] = {
    "price_to_sma200": 0.98,
    "price_to_sma50": 0.975,
    "days_below_sma200": 5.0,
    "return_20d": -0.04,
    "return_60d": -0.02,
    "drawdown_from_52w_high": 0.10,
    "range_position_52w": 0.45,
    "relative_strength_60d_qqq": -0.04,
    "volatility_60d": 0.38,
}


def snapshot_rebuild_frame(
    decisions: Sequence[Mapping[str, Any]],
) -> pd.DataFrame:
    """Build a scoring frame from frozen decision evidence (offline).

    Emitted positives/risks provide exact metric values; metrics that were
    NOT in ``quality.missing`` (and Entry metrics when ``entry.state`` is not
    ``INSUFFICIENT_DATA``) were present in the neutral scoring band and are
    assigned their v1 neutral-band midpoints so neutral metrics never
    collapse into false MISSING / INSUFFICIENT_DATA states.
    """
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, Mapping):
            continue
        quality = decision.get("quality", {})
        entry = decision.get("entry", {})
        entry_state = str(entry.get("state", "") or "") if isinstance(entry, Mapping) else ""
        entry_features = m2.evidence_feature_map(decision, "entry")
        quality_values = m2.evidence_feature_map(decision, "quality")
        missing_quality_metrics = {
            str(item.get("metric", ""))
            for item in (quality.get("missing", []) if isinstance(quality, Mapping) else [])
            if isinstance(item, Mapping) and item.get("metric")
        }
        row: dict[str, Any] = {
            "symbol": str(decision.get("symbol", "") or "").strip().upper(),
            "signal_date": str(decision.get("decision_date", "") or ""),
            "fundamental_data_asof": quality.get("data_asof") if isinstance(quality, Mapping) else None,
            "market_asof": entry.get("market_asof") if isinstance(entry, Mapping) else None,
            "regime": None,
            "benchmark_trend_ok": None,
        }
        for metric in SNAPSHOT_REBUILD_FEATURES:
            val = entry_features.get(metric, quality_values.get(metric))
            if val is None:
                if metric in _QUALITY_NEUTRAL_MIDPOINTS and metric not in missing_quality_metrics:
                    val = _QUALITY_NEUTRAL_MIDPOINTS[metric]
                elif entry_state and entry_state != "INSUFFICIENT_DATA":
                    if entry_state == "ENTRY_READY" and metric in _ENTRY_READY_NEUTRAL_MIDPOINTS:
                        val = _ENTRY_READY_NEUTRAL_MIDPOINTS[metric]
                    elif metric in _ENTRY_NON_READY_NEUTRAL_MIDPOINTS:
                        val = _ENTRY_NON_READY_NEUTRAL_MIDPOINTS[metric]
            row[metric] = val
        # Heuristic inference for high-growth cash-generative snapshot rows (e.g. NVDA)
        # where ocf_to_net_income was in the neutral [0.80, 1.00) band or negative accrual
        # with positive FCF proves OCF > NI >= 1.0:
        q_pos_codes = {
            str(item.get("code", ""))
            for item in (quality.get("positives", []) if isinstance(quality, Mapping) else [])
            if isinstance(item, Mapping)
        }
        if (
            row.get("ocf_to_net_income") == _QUALITY_NEUTRAL_MIDPOINTS["ocf_to_net_income"]
            and "free_cash_flow_strong" in q_pos_codes
            and row.get("accrual_ratio") is not None
            and float(row["accrual_ratio"]) < 0.0
        ):
            row["ocf_to_net_income"] = 1.05
        risk_codes = {
            str(item.get("code", ""))
            for item in (entry.get("risks", []) if isinstance(entry, Mapping) else [])
            if isinstance(item, Mapping)
        }
        positive_codes = {
            str(item.get("code", ""))
            for item in (entry.get("positives", []) if isinstance(entry, Mapping) else [])
            if isinstance(item, Mapping)
        }
        if "shares_data_stale" in {
            str(item.get("code", ""))
            for item in (quality.get("risks", []) if isinstance(quality, Mapping) else [])
            if isinstance(item, Mapping)
        }:
            row["shares_stale"] = True
        if "defensive_market_regime" in risk_codes:
            row["regime"] = "down"
            row["benchmark_trend_ok"] = False
        elif "supportive_market_regime" in positive_codes:
            row["regime"] = "up"
            row["benchmark_trend_ok"] = True
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    return frame


def rebuild_snapshot_variant(
    rebuild_frame: pd.DataFrame,
    *,
    decision_date: str,
    generated_at_utc: str,
    variant: str,
) -> tuple:
    """Run one variant over a snapshot rebuild frame via the wired builder."""
    stages = VARIANT_STAGES[variant]
    return build_stock_decisions(
        rebuild_frame,
        decision_date=decision_date,
        generated_at_utc=generated_at_utc,
        quality_version=stages["quality_version"],
        entry_version=stages["entry_version"],
        action_version=stages["action_version"],
    )


# ---------------------------------------------------------------------------
# Summaries, defects, similarity
# ---------------------------------------------------------------------------


def summarize_decisions(decisions: Sequence) -> dict[str, Any]:
    """Grade / entry / action counts plus ordered Top-15 symbols."""
    grades = {"A": 0, "B": 0, "C": 0, "UNRATED": 0}
    entries = {"ENTRY_READY": 0, "WATCH_PULLBACK": 0, "WATCH_BREAKOUT": 0,
               "TREND_DAMAGED": 0, "INSUFFICIENT_DATA": 0}
    actions = {"PRIORITY_REVIEW": 0, "WATCH_PULLBACK": 0, "WATCH_BREAKOUT": 0,
               "HOLD_MONITOR": 0, "AVOID": 0}
    for decision in decisions:
        grade = decision.quality.grade.value if hasattr(decision.quality.grade, "value") else str(decision.quality.grade)
        state = decision.entry.state.value if hasattr(decision.entry.state, "value") else str(decision.entry.state)
        action = decision.action_state.value if hasattr(decision.action_state, "value") else str(decision.action_state)
        grades[grade] = grades.get(grade, 0) + 1
        entries[state] = entries.get(state, 0) + 1
        actions[action] = actions.get(action, 0) + 1
    ordered = sorted(decisions, key=lambda d: (d.priority, d.symbol))
    return {
        "n": len(ordered),
        "grades": grades,
        "entries": entries,
        "actions": actions,
        "top15": [d.symbol for d in ordered[:15]],
    }


def defect_counts_for_scope(
    decisions: Sequence, frame: pd.DataFrame
) -> dict[str, Any]:
    """M2 defect counters (Axes 1, 2, 5, 8) for one scope/variant."""
    by_date_symbol: dict[str, dict] = {}
    if "symbol" in frame.columns:
        for _, row in frame.iterrows():
            record = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            by_date_symbol[f"{record.get('signal_date', '')}|{record.get('symbol', '')}"] = record
    n_accrual_fp = 0
    n_wc_penalized_b = 0
    n_dead_zone_wb = 0
    n_inverted_ready = 0
    for decision in decisions:
        grade = _grade_of(decision)
        state = _entry_state_of(decision)
        risk_codes = _risk_codes_of(decision, "quality")
        date_key = getattr(decision, "decision_date", "") or ""
        sym_key = decision.symbol if hasattr(decision, "symbol") else ""
        row = by_date_symbol.get(f"{date_key}|{sym_key}", {})
        get = row.get
        accrual = m2.finite_or_none(get("accrual_ratio"))
        ocf = m2.finite_or_none(get("ocf_to_net_income"))
        fcf = m2.finite_or_none(get("free_cash_flow"))
        if grade != "UNRATED" and "accrual_ratio_weak" in risk_codes and accrual is not None and accrual < -0.10 \
                and ocf is not None and ocf >= 1.0 and fcf is not None and fcf > 0.0:
            n_accrual_fp += 1
        revenue_yoy = m2.finite_or_none(get("revenue_yoy"))
        if grade == "B" and revenue_yoy is not None and revenue_yoy >= 0.25 \
                and ocf is not None and ocf >= 0.80 \
                and ({"receivables_growth_gap_weak", "inventory_growth_gap_weak"} & risk_codes):
            n_wc_penalized_b += 1
        if state == "WATCH_BREAKOUT" and m2.is_dead_zone_pullback(
            state=state,
            price_to_sma200=get("price_to_sma200"),
            price_to_sma50=get("price_to_sma50"),
            return_20d=get("return_20d"),
            return_60d=get("return_60d"),
            relative_strength_60d_qqq=get("relative_strength_60d_qqq"),
            drawdown_from_52w_high=get("drawdown_from_52w_high"),
            volatility_60d=get("volatility_60d"),
            defensive_ok=m2.defensive_gate_ok(
                get("regime"), get("benchmark_trend_ok"),
                get("relative_strength_60d_qqq"), get("return_20d")),
        ):
            n_dead_zone_wb += 1
        ratio = m2.sma50_to_sma200_ratio(get("price_to_sma200"), get("price_to_sma50"))
        if state == "ENTRY_READY" and ratio is not None and ratio < 0.98:
            n_inverted_ready += 1
    return {
        "n_cash_cow_accrual_weak": n_accrual_fp,
        "n_high_growth_wc_penalized_b": n_wc_penalized_b,
        "n_dead_zone_in_watch_breakout": n_dead_zone_wb,
        "n_inverted_ma_in_entry_ready": n_inverted_ready,
    }


def top15_jaccard(first: Sequence[str], second: Sequence[str]) -> float:
    """Jaccard similarity between two Top-15 symbol lists."""
    left, right = set(first), set(second)
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def mean_top15_jaccard_vs_v1(
    variant_top15_by_date: Mapping[str, Sequence[str]],
    v1_top15_by_date: Mapping[str, Sequence[str]],
) -> float | None:
    """Mean Jaccard across shared dates (dev dates for hist)."""
    shared = sorted(set(variant_top15_by_date) & set(v1_top15_by_date))
    if not shared:
        return None
    scores = [top15_jaccard(variant_top15_by_date[d], v1_top15_by_date[d]) for d in shared]
    return round(sum(scores) / len(scores), 6)


def dev_excess_for_groups(
    frame: pd.DataFrame, decisions: Sequence, groups: Mapping[str, Any] | None = None
) -> dict[str, dict[str, float | int]]:
    """Dev-only date-equal 60d excess for TOP15 / PRIORITY_REVIEW / A / READY.

    Each group is evaluated independently (overlapping membership allowed)
    by exact (signal_date, symbol) pair when decision_date is present,
    so no group is masked by another or leaked across dates.
    """
    if frame.empty or "symbol" not in frame.columns:
        return {}
    has_dates = (
        "signal_date" in frame.columns
        and any(getattr(d, "decision_date", None) for d in decisions)
    )
    if has_dates:
        keys = frame["signal_date"].astype(str) + "|" + frame["symbol"].astype(str)

        def _key(d: Any) -> str:
            return f"{getattr(d, 'decision_date', '') or ''}|{d.symbol}"
    else:
        keys = frame["symbol"].astype(str)

        def _key(d: Any) -> str:
            return str(d.symbol)

    top15 = {_key(d) for d in decisions if d.priority <= 15}
    pr = {_key(d) for d in decisions if _action_of(d) == "PRIORITY_REVIEW"}
    qual_a = {_key(d) for d in decisions if _grade_of(d) == "A"}
    ready = {_key(d) for d in decisions if _entry_state_of(d) == "ENTRY_READY"}
    out: dict[str, dict[str, float | int]] = {}
    for name, members in (("TOP15", top15), ("PRIORITY_REVIEW", pr),
                          ("QUALITY_A", qual_a), ("ENTRY_READY", ready)):
        work = frame.copy()
        work["preflight_group"] = "REST"
        work.loc[keys.isin(members), "preflight_group"] = name
        result = m2.date_equal_excess_by_group(work, "preflight_group")
        if name in result:
            out[name] = result[name]
    return out


# ---------------------------------------------------------------------------
# Frozen casebook verification
# ---------------------------------------------------------------------------


def _grade_of(decision) -> str:
    if decision is None:
        return ""
    if isinstance(decision, Mapping):
        return str((decision.get("quality", {}) or {}).get("grade", ""))
    return decision.quality.grade.value


def _entry_state_of(decision) -> str:
    if decision is None:
        return ""
    if isinstance(decision, Mapping):
        return str((decision.get("entry", {}) or {}).get("state", ""))
    return decision.entry.state.value


def _action_of(decision) -> str:
    if decision is None:
        return ""
    if isinstance(decision, Mapping):
        return str(decision.get("action_state", ""))
    return decision.action_state.value


def _priority_of(decision):
    if decision is None:
        return ""
    if isinstance(decision, Mapping):
        return decision.get("priority", "")
    return decision.priority


def _risk_codes_of(decision, side: str) -> set[str]:
    if decision is None:
        return set()
    if isinstance(decision, Mapping):
        section = decision.get("quality" if side == "quality" else "entry", {}) or {}
        return {str(item.get("code", "")) for item in section.get("risks", [])
                if isinstance(item, Mapping)}
    section = decision.quality if side == "quality" else decision.entry
    return {item.code for item in section.risks}


def _positive_codes_of(decision, side: str) -> set[str]:
    if decision is None:
        return set()
    if isinstance(decision, Mapping):
        section = decision.get("quality" if side == "quality" else "entry", {}) or {}
        return {str(item.get("code", "")) for item in section.get("positives", [])
                if isinstance(item, Mapping)}
    section = decision.quality if side == "quality" else decision.entry
    return {item.code for item in section.positives}


def outcome_string(decision) -> str:
    """Compact grade/state/action/priority outcome for one decision."""
    return f"{_grade_of(decision)}/{_entry_state_of(decision)}/{_action_of(decision)}/p{_priority_of(decision)}"


def surgical_h3_decisions(frozen_dicts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply H3 mapping + ranking onto frozen decisions (exact, no rebuild).

    Uses frozen quality/entry objects, so snapshot H3 verification is free of
    partial-vector degradation. Returns symbol -> StockDecision.
    """
    from dataclasses import replace

    from ai_value_scanner.decision.action import (
        assign_action_priorities_v2,
        map_action_state_v2,
    )
    from ai_value_scanner.decision.model import stock_decision_from_dict

    transplanted = []
    for payload in frozen_dicts:
        if not isinstance(payload, Mapping):
            continue
        try:
            decision = stock_decision_from_dict(dict(payload))
        except (ValueError, KeyError, TypeError):
            continue
        action, _ = map_action_state_v2(decision.quality, decision.entry)
        transplanted.append(replace(decision, action_state=action))
    return {d.symbol: d for d in assign_action_priorities_v2(transplanted)}


def verify_case(
    case: Mapping[str, Any],
    v1_display,
    v1_policy,
    v2_decision,
    date_variant_decisions: Sequence | None = None,
    pair_v2_decision=None,
) -> dict[str, str]:
    """Decide failure_resolved for one frozen M2 case.

    v1_display renders v1_outcome (frozen decisions.jsonl on snapshots, v1
    rebuild on hist_dev). v1_policy is the same-information comparator for
    v2_decision (v1 rebuild on snapshots, v1 baseline on hist_dev), so partial
    snapshot vectors never masquerade as policy effects.
    """
    v1_outcome = outcome_string(v1_display) if v1_display is not None else "MISSING"
    v2_outcome = outcome_string(v2_decision) if v2_decision is not None else "MISSING"
    tier = str(case.get("evidence_tier", ""))
    axis = str(case.get("primary_axis", ""))
    if tier == m2.EVIDENCE_TIER_CONTROL or axis == "Control":
        if v1_policy is None or v2_decision is None:
            preserved = False
        else:
            preserved = (
                _grade_of(v1_policy) == _grade_of(v2_decision)
                and _entry_state_of(v1_policy) == _entry_state_of(v2_decision)
                and _action_of(v1_policy) == _action_of(v2_decision)
            )
        return {
            "v1_outcome": v1_outcome,
            "v2_outcome": v2_outcome,
            "failure_resolved": "CONTROL_PRESERVED" if preserved else "FALSE",
            "resolution_detail": "grade/state/action identical under v2_combined"
            if preserved else "control changed under v2_combined (see outcomes)",
        }
    if v1_policy is None or v2_decision is None:
        return {
            "v1_outcome": v1_outcome, "v2_outcome": v2_outcome,
            "failure_resolved": "FALSE",
            "resolution_detail": "decision unavailable under one variant (partial features)",
        }
    v1_risks = _risk_codes_of(v1_policy, "quality")
    v2_risks = _risk_codes_of(v2_decision, "quality")
    v1_entry_risks = _risk_codes_of(v1_policy, "entry")
    predicate = str(case.get("predicate", ""))
    resolved: bool | None = None
    detail = ""
    if axis == "Axis1":
        has_fp = "accrual_ratio_weak" in v1_risks
        fixed = "accrual_ratio_weak" not in v2_risks
        resolved = bool(has_fp and fixed)
        detail = "accrual_ratio_weak cleared under v2" if resolved else "accrual flag persists or vacuous"
    elif axis == "Axis2":
        gap_codes = {"receivables_growth_gap_weak", "inventory_growth_gap_weak"}
        resolved = bool((v1_risks & gap_codes) and not (v2_risks & gap_codes))
        detail = "gap weak flags cleared under v2" if resolved else "gap flags persist"
    elif axis == "Axis3":
        if predicate == "thin_fcf_margin":
            v2_codes = _positive_codes_of(v2_decision, "quality") | v2_risks
            resolved = bool({"fcf_margin_strong", "fcf_margin_weak", "operating_margin_strong",
                             "operating_margin_weak"} & v2_codes)
            detail = "scale-aware margin assessment active under v2" if resolved else "margin pillars silent"
        else:
            val_codes = {"ps_hist_percentile_weak", "pe_hist_percentile_weak"}
            resolved = bool((v1_risks & val_codes) and not (v2_risks & val_codes))
            detail = "valuation weak flags floored under v2" if resolved else "valuation flags persist"
    elif axis == "Axis4":
        v2_codes = _positive_codes_of(v2_decision, "quality") | v2_risks
        resolved = "operating_margin_strong" in v2_codes or "operating_margin_weak" in v2_codes
        detail = "operating_margin scored under v2" if resolved else "operating_margin unscored"
    elif axis == "Axis5":
        resolved = _entry_state_of(v2_decision) == "WATCH_PULLBACK"
        detail = "dead-zone routed to WATCH_PULLBACK" if resolved else f"v2 state={_entry_state_of(v2_decision)}"
    elif axis == "Axis6":
        sub_codes = {"watch_breakout_near_consolidation", "watch_breakout_lagging_structure"}
        v2_entry_codes = _positive_codes_of(v2_decision, "entry") | v1_entry_risks | \
            _risk_codes_of(v2_decision, "entry")
        resolved = bool((sub_codes & v2_entry_codes) or _entry_state_of(v2_decision) != "WATCH_BREAKOUT")
        detail = "sub-bucket differentiated or routed out of BREAKOUT" if resolved else "no differentiation"
    elif axis == "Axis7":
        if predicate == "a_weak_breakout":
            day = list(date_variant_decisions or [])
            weak_priority = _priority_of(v2_decision)
            try:
                weak_in = int(weak_priority) <= 15
            except (TypeError, ValueError):
                weak_in = False
            ready_out = any(
                _entry_state_of(d) == "ENTRY_READY" and _priority_of(d) != "" and int(_priority_of(d)) > 15
                for d in day
            )
            resolved = bool(day) and not (weak_in and ready_out)
            detail = "weak BREAKOUT no longer blocks READY attention" if resolved else "still interleaved"
        else:
            try:
                resolved = int(_priority_of(v2_decision)) <= 15
            except (TypeError, ValueError):
                resolved = False
            detail = "in v2 Top-15" if resolved else f"v2 priority={_priority_of(v2_decision)}"
    elif axis == "Axis8":
        if "inverted_ready" in predicate:
            resolved = _entry_state_of(v2_decision) != "ENTRY_READY"
            detail = "alignment gate blocks READY" if resolved else "still READY while inverted"
        else:
            resolved = "sma50_below_sma200_inverted" in _risk_codes_of(v2_decision, "entry")
            detail = "inversion explicitly flagged" if resolved else "inversion unflagged"
    elif axis == "Paired":
        case_id = str(case.get("study_case_id", ""))
        try:
            v2_priority = int(_priority_of(v2_decision))
        except (TypeError, ValueError):
            v2_priority = None
        if "-REJ" in case_id:
            resolved = v2_priority is not None and v2_priority <= 15
            detail = "suppressed opportunity recovered to Top-15" if resolved else f"v2 priority={_priority_of(v2_decision)}"
        elif "-SEL" in case_id and pair_v2_decision is not None:
            try:
                pair_priority = int(_priority_of(pair_v2_decision))
            except (TypeError, ValueError):
                pair_priority = None
            resolved = v2_priority is not None and pair_priority is not None and pair_priority < v2_priority
            detail = (
                f"paired opportunity now outranks marginal member "
                f"(p{pair_priority} vs p{v2_priority})"
                if resolved else
                f"marginal member still ahead (p{v2_priority} vs p{pair_priority})"
            )
        else:
            resolved = False
            detail = "pair counterpart unavailable"
    else:
        resolved = False
        detail = "unknown axis"
    return {
        "v1_outcome": v1_outcome,
        "v2_outcome": v2_outcome,
        "failure_resolved": "TRUE" if resolved else "FALSE",
        "resolution_detail": detail,
    }
