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


def log_status(started_at: datetime, level: str, message: str) -> None:
    now = datetime.now(timezone.utc)
    elapsed = (now - started_at).total_seconds()
    stamp = now.strftime("%H:%M:%S")
    print(f"[{stamp}][{level}][+{elapsed:7.1f}s] {message}")


def default_run_stem(started_at: datetime, max_symbols: int | None) -> str:
    ts = started_at.strftime("%Y%m%dT%H%M%SZ")
    scope = "full" if max_symbols is None else f"sample{max_symbols}"
    return f"ai_value_scan_{ts}_{scope}"


def resolve_output_paths(
    config: ScanConfig,
    started_at: datetime,
    output_path: str | None,
    diagnostics_output_path: str | None,
    network_report_output_path: str | None,
    report_output_path: str | None,
) -> dict[str, Path]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_path:
        ranked_csv = Path(output_path)
    else:
        ranked_csv = output_dir / f"{default_run_stem(started_at, config.max_symbols)}_ranked.csv"

    if diagnostics_output_path:
        diagnostics_base = Path(diagnostics_output_path)
    else:
        diagnostics_base = ranked_csv.with_name(f"{ranked_csv.stem}_diagnostics.csv")

    if network_report_output_path:
        network_json = Path(network_report_output_path)
    else:
        network_json = ranked_csv.with_name(f"{ranked_csv.stem}_network.json")

    if report_output_path:
        report_md = Path(report_output_path)
    else:
        report_md = ranked_csv.with_name(f"{ranked_csv.stem}_report.md")
    return {
        "ranked_csv": ranked_csv,
        "diagnostics_base": diagnostics_base,
        "network_json": network_json,
        "report_md": report_md,
    }


def build_run_report_markdown(
    started_at: datetime,
    finished_at: datetime,
    ranked: pd.DataFrame,
    channel_profiles: dict[str, dict[str, Any]],
    filtered_counts: dict[str, int],
    watchlist_counts: dict[str, int],
    watchlist_symbol_count: int,
    merged_count: int,
    prefilter_count: int,
    paths: dict[str, Path],
    network_issue_flag: bool,
    sec_cache_summary: str | None,
    market_data_provenance: dict[str, Any] | None = None,
    strategy_style: str | None = None,
    scan_config_path: str | None = None,
    industry_trend_count: int | None = None,
    industry_trend_path: Path | None = None,
    momentum_count: int | None = None,
    momentum_path: Path | None = None,
    research_pool: pd.DataFrame | None = None,
    research_pool_path: Path | None = None,
    diagnostics_layer_summary: dict[str, dict[str, dict[str, float | int]]] | None = None,
    first_fail_concentration_summary: dict[str, dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# AI Value Scan Report")
    lines.append("")
    # Explicit style identity is authoritative for current reports. Config
    # path remains for provenance and legacy downstream compatibility.
    if strategy_style is not None:
        lines.append(f"- Strategy-Style: {strategy_style}")
    if scan_config_path is not None:
        lines.append(f"- Config: {scan_config_path}")
    lines.append(f"- Started UTC: {started_at.isoformat()}")
    lines.append(f"- Finished UTC: {finished_at.isoformat()}")
    lines.append(f"- Elapsed seconds: {(finished_at - started_at).total_seconds():.2f}")
    lines.append("")
    lines.append("## Funnel")
    lines.append("")
    lines.append(f"- merged symbols: {merged_count}")
    lines.append(f"- after price/liquidity prefilter: {prefilter_count}")
    for channel_name in channel_profiles.keys():
        lines.append(f"- watchlist {channel_name}: {watchlist_counts.get(channel_name, 0)}")
    lines.append(f"- watchlist matched symbols: {watchlist_symbol_count}")
    for channel_name in channel_profiles.keys():
        lines.append(f"- post-filter {channel_name}: {filtered_counts.get(channel_name, 0)}")
    lines.append(f"- final ranked rows: {len(ranked)}")
    lines.append("")
    if diagnostics_layer_summary:
        lines.append("## Layer Pass Rates")
        lines.append("")
        for channel_name in channel_profiles.keys():
            lines.append(f"### {channel_name}")
            layer_map = diagnostics_layer_summary.get(channel_name, {})
            if not layer_map:
                lines.append("- no diagnostics")
                lines.append("")
                continue
            for layer in ["base_hard", "quality_or_theme_hard", "valuation_hard"]:
                row = layer_map.get(layer)
                if not row:
                    continue
                lines.append(
                    "- "
                    f"{layer}: before={int(row.get('before', 0) or 0)} | "
                    f"remaining={int(row.get('remaining', 0) or 0)} | "
                    f"removed={int(row.get('removed', 0) or 0)} | "
                    f"pass_rate={float(row.get('pass_rate', 0.0) or 0.0):.2%}"
                )
            lines.append("")
    if first_fail_concentration_summary:
        lines.append("## First-Fail Concentration")
        lines.append("")
        for channel_name in channel_profiles.keys():
            row = first_fail_concentration_summary.get(channel_name, {})
            reason = str(row.get("top_reason", "") or "")
            count = int(row.get("top_count", 0) or 0)
            pct = float(row.get("top_pct", 0.0) or 0.0)
            lines.append(
                f"- {channel_name}: top_reason={reason or 'n/a'} | count={count} | pct={pct:.2%}"
            )
        lines.append("")
    lines.append("## Triage")
    lines.append("")
    if ranked.empty:
        lines.append("- no candidates")
    else:
        triage_counts = ranked["triage_label"].value_counts().to_dict()
        lines.append(f"- keep: {triage_counts.get('keep', 0)}")
        lines.append(f"- watch: {triage_counts.get('watch', 0)}")
        lines.append(f"- drop: {triage_counts.get('drop', 0)}")
    lines.append("")
    lines.append("## Shortlist")
    lines.append("")
    if ranked.empty:
        lines.append("- no candidates")
    else:
        for channel_name in channel_profiles.keys():
            top = ranked[
                (ranked["channel"] == channel_name) & (ranked["triage_label"] != "drop")
            ].sort_values(
                "composite_score", ascending=False
            ).head(5)
            lines.append(f"### {channel_name}")
            if top.empty:
                lines.append("- none")
            else:
                for _, row in top.iterrows():
                    lines.append(
                        "- "
                        f"{row['symbol']} | triage={row['triage_label']} | "
                        f"research={str(row.get('research_priority', ''))} | "
                        f"score={float(row['composite_score']):.3f} | "
                        f"ai_link={float(row.get('ai_link_score', 0.0) or 0.0):.3f} | "
                        f"bucket={str(row.get('watchlist_bucket', ''))} | "
                        f"etf_count={int(row.get('watchlist_etf_count', 0) or 0)} | "
                        f"etfs={str(row.get('watchlist_etfs', ''))} | "
                        f"psd={float(row['ps_discount']):.3f} | "
                        f"ped={float(row['pe_discount']):.3f} | "
                        f"risks={str(row.get('research_risks', ''))}"
                    )
            lines.append("")
    if research_pool is not None:
        lines.append("## Research Pool")
        lines.append("")
        if research_pool.empty:
            lines.append("- no candidates")
        else:
            priority_counts = research_pool["research_priority"].value_counts().to_dict()
            lines.append(f"- research_now: {priority_counts.get('research_now', 0)}")
            lines.append(f"- watch_for_pullback: {priority_counts.get('watch_for_pullback', 0)}")
            lines.append(f"- left_side_watch: {priority_counts.get('left_side_watch', 0)}")
            lines.append(f"- theme_only: {priority_counts.get('theme_only', 0)}")
            top_pool = research_pool.sort_values("research_score", ascending=False).head(15)
            for _, row in top_pool.iterrows():
                lines.append(
                    "- "
                    f"{row['symbol']} | priority={str(row.get('research_priority', ''))} | "
                    f"score={float(row.get('research_score', 0.0) or 0.0):.3f} | "
                    f"channel={str(row.get('channel', ''))} | "
                    f"tags={str(row.get('research_tags', ''))} | "
                    f"risks={str(row.get('research_risks', ''))}"
                )
        lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- ranked csv: {paths['ranked_csv']}")
    lines.append(f"- diagnostics base: {paths['diagnostics_base']}")
    lines.append(f"- network report: {paths['network_json']}")
    lines.append(f"- markdown report: {paths['report_md']}")
    if industry_trend_path is not None:
        lines.append(f"- industry trend csv: {industry_trend_path}")
    if industry_trend_count is not None:
        lines.append(f"- industry trend rows: {industry_trend_count}")
    if momentum_path is not None:
        lines.append(f"- momentum csv: {momentum_path}")
    if momentum_count is not None:
        lines.append(f"- momentum rows: {momentum_count}")
    if research_pool_path is not None:
        lines.append(f"- research pool csv: {research_pool_path}")
    if research_pool is not None:
        lines.append(f"- research pool rows: {len(research_pool)}")
        if not research_pool.empty and "research_priority" in research_pool.columns:
            priority_counts = research_pool["research_priority"].value_counts().to_dict()
            lines.append(f"- research_now: {priority_counts.get('research_now', 0)}")
            lines.append(f"- watch_for_pullback: {priority_counts.get('watch_for_pullback', 0)}")
            lines.append(f"- left_side_watch: {priority_counts.get('left_side_watch', 0)}")
            lines.append(f"- theme_only: {priority_counts.get('theme_only', 0)}")
            lines.append(f"- avoid_for_now: {priority_counts.get('avoid_for_now', 0)}")
    lines.append(f"- network issues observed: {'YES' if network_issue_flag else 'NO'}")
    if market_data_provenance:
        stale_used = bool(market_data_provenance.get("stale_market_data_fallback_used"))
        lines.append(
            f"- stale market-data fallback used: {'YES' if stale_used else 'NO'}"
        )
        alpaca_sources = (
            market_data_provenance.get("data_provenance", {}).get("alpaca", {})
        )
        for namespace in ("assets", "snapshots", "bars"):
            row = alpaca_sources.get(namespace)
            if not isinstance(row, dict):
                continue
            counts = row.get("counts", {})
            age = row.get("max_cache_age_sec")
            age_text = "n/a" if age is None else f"{float(age):.0f}s"
            data_asof = row.get("latest_data_asof_utc") or "n/a"
            feed = row.get("feed") or "n/a"
            degraded = row.get("degraded_reasons") or []
            lines.append(
                f"- alpaca {namespace} provenance: {counts} | feed={feed} "
                f"| data_asof={data_asof} | max_cache_age={age_text}"
                + (f" | degraded={degraded}" if degraded else "")
            )
    if sec_cache_summary:
        lines.append(f"- sec cache: {sec_cache_summary}")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan US listed companies for AI-related undervaluation candidates."
    )
    parser.add_argument(
        "--config",
        default="configs/config.risk_off.json",
        help="JSON file path for filter configuration.",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Limit the number of symbols for faster trial runs.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path. Defaults to outputs/ai_value_scan_YYYYMMDDTHHMMSSZ_<scope>_ranked.csv",
    )
    parser.add_argument(
        "--diagnostics-output",
        default=None,
        help="Optional CSV path for filter-step diagnostics.",
    )
    parser.add_argument(
        "--network-report-output",
        default=None,
        help="Optional JSON path for network/rate-limit diagnostics.",
    )
    parser.add_argument(
        "--report-output",
        default=None,
        help="Optional markdown path for detailed run analysis report.",
    )
    return parser
