from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

import pandas as pd

from ai_value_scanner.config import ScanConfig


def write_csv_atomic(df: "pd.DataFrame", path: str | Path) -> None:
    """Write a DataFrame to CSV atomically via tmp-file + rename.

    Production input files (watchlist, universes, cohort ledgers) must never
    be left truncated if the process dies mid-write or another run reads a
    half-written file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, target)

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
