from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from ai_value_scanner.config import ScanConfig


def assign_triage_label(row: pd.Series, triage_rules: dict[str, dict[str, Any]]) -> str:
    channel = str(row.get("channel", ""))
    keep_cfg = triage_rules.get("keep", {}).get(channel, {})
    drop_cfg = triage_rules.get("drop", {})

    def to_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return default
        if not np.isfinite(out):
            return default
        return out

    comp = to_float(row.get("composite_score", 0.0), default=0.0)
    psd = to_float(row.get("ps_discount", 0.0), default=0.0)
    ped = to_float(row.get("pe_discount", 0.0), default=0.0)

    if keep_cfg:
        keep_ok = comp >= float(keep_cfg.get("min_composite_score", 0.5))
        keep_ok = keep_ok and psd >= float(keep_cfg.get("min_ps_discount", -1.0))
        keep_ok = keep_ok and ped >= float(keep_cfg.get("min_pe_discount", -1.0))
        if keep_ok:
            return "keep"

    drop_by_score = comp <= float(drop_cfg.get("max_composite_score", 0.35))
    if drop_by_score and bool(drop_cfg.get("require_both_value_premium", False)):
        drop_by_score = (psd <= 0.0) and (ped <= 0.0)
    if drop_by_score:
        return "drop"
    return "watch"


def apply_triage_labels(ranked: pd.DataFrame, triage_rules: dict[str, dict[str, Any]]) -> pd.DataFrame:
    out = ranked.copy()
    if out.empty:
        out["triage_label"] = pd.Series(dtype="object")
        return out
    out["triage_label"] = out.apply(lambda r: assign_triage_label(r, triage_rules), axis=1)
    return out


def metric_float(row: pd.Series, col: str, default: float = np.nan) -> float:
    try:
        value = float(row.get(col, default))
    except (TypeError, ValueError):
        return default
    if not np.isfinite(value):
        return default
    return value


def text_has_any(text: str, tokens: Iterable[str]) -> bool:
    upper = str(text or "").upper()
    return any(token in upper for token in tokens)


def build_research_assessment(row: pd.Series, list_type: str = "") -> dict[str, Any]:
    tags: list[str] = []
    risks: list[str] = []
    score = 0.0

    ps_hist = metric_float(row, "ps_hist_percentile")
    pe_hist = metric_float(row, "pe_hist_percentile")
    ps_discount = metric_float(row, "ps_discount", 0.0)
    pe_discount = metric_float(row, "pe_discount", 0.0)
    ps_sic_pct = metric_float(row, "ps_percentile_in_sic")
    pe_sic_pct = metric_float(row, "pe_percentile_in_sic")
    quality = metric_float(row, "fundamental_quality_score", 0.0)
    ai_link = metric_float(row, "ai_link_score", 0.0)
    fcf_yield = metric_float(row, "fcf_yield")
    ev_to_ebit = metric_float(row, "ev_to_ebit")
    pe = metric_float(row, "pe")
    ps = metric_float(row, "ps")
    revenue_yoy = metric_float(row, "revenue_yoy")
    net_income_yoy = metric_float(row, "net_income_yoy")
    return_20d = metric_float(row, "return_20d", 0.0)
    return_60d = metric_float(row, "return_60d", 0.0)
    price_to_sma200 = metric_float(row, "price_to_sma200")
    drawdown = metric_float(row, "drawdown_from_52w_high", 0.0)
    watchlist_etfs = str(row.get("watchlist_etfs", "") or "")
    bucket = str(row.get("watchlist_bucket", "") or "")
    channel = str(row.get("channel", "") or "")

    if (np.isfinite(ps_hist) and ps_hist <= 0.25) or (np.isfinite(pe_hist) and pe_hist <= 0.25):
        tags.append("cheap_relative_to_history")
        score += 1.8
    if (
        ps_discount >= 0.10
        or pe_discount >= 0.10
        or (np.isfinite(ps_sic_pct) and ps_sic_pct <= 0.35)
        or (np.isfinite(pe_sic_pct) and pe_sic_pct <= 0.35)
    ):
        tags.append("cheap_relative_to_peers")
        score += 1.5
    if (np.isfinite(fcf_yield) and fcf_yield >= 0.06) or (
        np.isfinite(ev_to_ebit) and ev_to_ebit <= 12.0
    ):
        tags.append("cash_flow_value")
        score += 1.2
    if quality >= 0.85:
        tags.append("quality_compounder")
        score += 1.6
    elif quality >= 0.70:
        tags.append("acceptable_quality")
        score += 0.8
    if revenue_yoy >= 0.10:
        tags.append("sales_growth")
        score += 0.8
    if net_income_yoy >= 0.15:
        tags.append("profit_growth")
        score += 0.8
    if ai_link >= 0.55:
        tags.append("strong_ai_link")
        score += 1.5
    elif ai_link >= 0.42:
        tags.append("medium_ai_link")
        score += 0.8

    infra_tokens = [
        "GRID",
        "PAVE",
        "IFRA",
        "XLI",
        "XLU",
        "NLR",
        "URA",
        "SRVR",
        "SKYY",
        "CLOU",
        "CIBR",
        "IHAK",
        "ITA",
        "IYT",
        "VPU",
        "XLRE",
        "VNQ",
    ]
    if (
        "ai_enabler" in bucket
        or "ai_peripheral" in bucket
        or "ai_smallcap" in bucket
        or "ai_enabler" in channel
        or "ai_peripheral" in channel
        or "ai_smallcap" in channel
        or text_has_any(watchlist_etfs, infra_tokens)
    ):
        tags.append("ai_infrastructure_exposure")
        score += 0.7

    if return_20d >= 0.05 and return_60d >= 0.10 and (
        not np.isfinite(price_to_sma200) or price_to_sma200 >= 1.0
    ):
        tags.append("momentum_breakout")
        score += 1.3
    if drawdown >= 0.10 and (not np.isfinite(price_to_sma200) or price_to_sma200 <= 1.05):
        tags.append("pullback_value")
        score += 0.7

    if ps_discount < -0.10 or pe_discount < -0.10:
        risks.append("expensive_relative_to_peers")
        score -= 1.0
    if (
        (np.isfinite(pe) and pe > 30.0)
        or (np.isfinite(ev_to_ebit) and ev_to_ebit > 30.0)
        or (np.isfinite(ps) and ps > 10.0)
    ):
        risks.append("high_absolute_valuation")
        score -= 1.2
    if ai_link < 0.35:
        risks.append("weak_ai_link")
        score -= 0.8
    if revenue_yoy < 0.03 or net_income_yoy < 0.0:
        risks.append("weak_growth")
        score -= 0.9
    if return_20d < -0.05 and return_60d < 0.0:
        risks.append("negative_momentum")
        score -= 0.8
    value_tag_count = len(
        set(tags)
        & {"cheap_relative_to_history", "cheap_relative_to_peers", "cash_flow_value", "pullback_value"}
    )
    if value_tag_count >= 2 and ("weak_growth" in risks or "negative_momentum" in risks):
        risks.append("possible_value_trap")
        score -= 1.2

    tag_set = set(tags)
    risk_set = set(risks)
    major_risks = risk_set & {
        "possible_value_trap",
        "weak_ai_link",
        "high_absolute_valuation",
        "negative_momentum",
    }
    has_ai = bool(tag_set & {"strong_ai_link", "medium_ai_link", "ai_infrastructure_exposure"})
    has_value = bool(
        tag_set & {"cheap_relative_to_history", "cheap_relative_to_peers", "cash_flow_value"}
    )
    has_quality = quality >= 0.70 or "quality_compounder" in tag_set
    has_growth_or_momentum = bool(
        tag_set & {"sales_growth", "profit_growth", "momentum_breakout"}
    )

    has_overvaluation_risk = bool(
        risk_set & {"high_absolute_valuation", "expensive_relative_to_peers"}
    )
    has_weak_ai_risk = "weak_ai_link" in risk_set

    if "possible_value_trap" in risk_set:
        # High-quality cheap names that are merely in a downtrend (negative
        # momentum) are not automatic traps. Keep them visible as left-side
        # watch candidates: strong quality, positive growth, clear value
        # tags, and AI linkage — flagged for manual timing, never auto-buy.
        left_side = (
            "negative_momentum" in risk_set
            and has_quality
            and has_value
            and np.isfinite(revenue_yoy)
            and revenue_yoy >= 0.03
            and np.isfinite(net_income_yoy)
            and net_income_yoy >= 0.0
        )
        if left_side and has_ai:
            priority = "left_side_watch"
        else:
            priority = "theme_only" if has_ai else "avoid_for_now"
    elif has_weak_ai_risk and "ai_infrastructure_exposure" in tag_set:
        priority = "theme_only"
    elif has_weak_ai_risk:
        priority = "avoid_for_now"
    elif has_quality and has_ai and has_overvaluation_risk:
        priority = "watch_for_pullback"
    elif has_quality and has_value and has_ai and len(major_risks) <= 1:
        priority = "research_now"
    elif has_quality and has_ai and has_growth_or_momentum and len(major_risks) <= 1:
        priority = "research_now"
    elif has_ai:
        priority = "theme_only"
    else:
        priority = "avoid_for_now"

    if not tags:
        tags.append("no_clear_edge")
    if not risks:
        risks.append("no_major_risk_flag")

    summary = (
        f"{priority}: tags={';'.join(tags[:4])}; "
        f"risks={';'.join(risks[:3])}; score={score:.2f}; source={list_type or 'scan'}"
    )
    return {
        "research_priority": priority,
        "research_score": round(score, 3),
        "research_tags": ",".join(tags),
        "research_risks": ",".join(risks),
        "research_summary": summary,
    }


def apply_research_assessment(frame: pd.DataFrame, list_type: str = "") -> pd.DataFrame:
    out = frame.copy()
    research_cols = [
        "research_priority",
        "research_score",
        "research_tags",
        "research_risks",
        "research_summary",
    ]
    if out.empty:
        for col in research_cols:
            out[col] = pd.Series(dtype="object")
        return out
    assessments = out.apply(lambda r: build_research_assessment(r, list_type), axis=1)
    for col in research_cols:
        out[col] = assessments.map(lambda item: item[col])
    return out


def apply_low_value_research_gate(frame: pd.DataFrame, config: ScanConfig) -> pd.DataFrame:
    """Keep Low-Value focused on investable value, not broad thematic cheapness."""
    out = frame.copy()
    if out.empty:
        return out
    if "research_priority" not in out.columns or "research_risks" not in out.columns:
        out = apply_research_assessment(out, "low_value")

    allowed = {
        str(x).strip()
        for x in (config.low_value_allowed_research_priorities or [])
        if str(x).strip()
    }
    excluded_risks = {
        str(x).strip()
        for x in (config.low_value_excluded_research_risks or [])
        if str(x).strip()
    }

    mask = pd.Series(True, index=out.index)
    if allowed:
        mask &= out["research_priority"].fillna("").astype(str).isin(allowed)
    if excluded_risks:
        risks = out["research_risks"].fillna("").astype(str).str.split(",")
        mask &= ~risks.apply(lambda values: bool(set(str(x).strip() for x in values) & excluded_risks))
    if config.low_value_min_research_score is not None:
        mask &= (
            pd.to_numeric(out["research_score"], errors="coerce").fillna(-np.inf)
            >= float(config.low_value_min_research_score)
        )
    return out[mask].copy()
