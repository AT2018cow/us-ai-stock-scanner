from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_VALID_LIST_TYPES = [
    "industry_trend",
    "low_value",
    "momentum",
    "research_pool",
]


def build_markdown_report(
    cfg: Any,
    signals: pd.DataFrame,
    summary: pd.DataFrame,
    segment_summary: pd.DataFrame,
    signal_diagnostics: pd.DataFrame,
    signal_channel_summary: pd.DataFrame,
    events_path: Path,
    summary_path: Path,
    benchmarks_path: Path,
    segment_path: Path,
    signal_diagnostics_path: Path,
    signal_channel_summary_path: Path,
) -> str:
    lines: list[str] = []
    lines.append("# Backtest Report")
    lines.append("")
    lines.append(f"- generated UTC: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- mode: {cfg.mode}")
    lines.append(f"- signal rows: {len(signals)}")
    lines.append(f"- list types: {', '.join(cfg.list_types or DEFAULT_VALID_LIST_TYPES)}")
    lines.append(f"- horizons: {', '.join(str(x) for x in (cfg.horizons or []))}")
    lines.append(f"- top_n: {cfg.top_n}")
    lines.append(f"- per_channel_top_n: {cfg.per_channel_top_n}")
    lines.append(f"- trading_cost_bps(one-way): {cfg.trading_cost_bps}")
    lines.append(f"- entry_price_mode: {cfg.entry_price_mode}")
    lines.append(f"- exit_price_mode: {cfg.exit_price_mode}")
    if cfg.mode == "historical_replay":
        lines.append(f"- rebalance_frequency: {cfg.rebalance_frequency}")
        lines.append(f"- replay_max_symbols: {cfg.replay_max_symbols}")
        lines.append(f"- replay_asset_status: {cfg.replay_asset_status}")
        lines.append(f"- use_historical_watchlist: {cfg.use_historical_watchlist}")
        lines.append(f"- watchlist_history_dir: {cfg.watchlist_history_dir}")
        lines.append(f"- watchlist_csv_path_override: {cfg.watchlist_csv_path}")
        lines.append(f"- allow_latest_watchlist_fallback: {cfg.allow_latest_watchlist_fallback}")
        lines.append(f"- disclosure_lookback_days: {cfg.disclosure_lookback_days}")
        lines.append(f"- theme_source: {cfg.theme_source}")
        lines.append(f"- allow_lookahead_theme_source: {cfg.allow_lookahead_theme_source}")
        if cfg.theme_source == "historical_news":
            lines.append(f"- historical_news_lookback_days: {cfg.historical_news_lookback_days}")
            lines.append(f"- historical_news_limit_per_symbol: {cfg.historical_news_limit_per_symbol}")
        lines.append(f"- delist_return_assumption: {cfg.delist_return_assumption}")
        lines.append(f"- delist_detection_buffer_days: {cfg.delist_detection_buffer_days}")
        lines.append(f"- perturbation_enabled: {cfg.enable_perturbation}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    if summary.empty:
        lines.append("- no summary rows")
    else:
        for row in summary.itertuples(index=False):
            avg_ret = "nan" if pd.isna(row.avg_return) else f"{row.avg_return:.4f}"
            win = "nan" if pd.isna(row.win_rate) else f"{row.win_rate:.2%}"
            ex = "nan" if pd.isna(row.avg_excess_vs_QQQ) else f"{row.avg_excess_vs_QQQ:.4f}"
            lines.append(
                "- "
                f"{row.scenario} | {row.list_type} | H={row.horizon_days} | "
                f"n={row.n_events_valid}/{row.n_events_total} | avg={avg_ret} | "
                f"win={win} | excess_vs_QQQ={ex} | "
                f"no_signal={getattr(row, 'n_no_signal_events', 0)} | "
                f"unpriced={getattr(row, 'n_unpriced_events', 0)}"
            )
    lines.append("")
    lines.append("## Segments")
    lines.append("")
    if segment_summary.empty:
        lines.append("- no segment rows")
    else:
        for row in segment_summary.itertuples(index=False):
            avg_ret = "nan" if pd.isna(row.avg_return) else f"{row.avg_return:.4f}"
            win = "nan" if pd.isna(row.win_rate) else f"{row.win_rate:.2%}"
            ex = "nan" if pd.isna(row.avg_excess_vs_QQQ) else f"{row.avg_excess_vs_QQQ:.4f}"
            lines.append(
                "- "
                f"{row.scenario} | {row.segment} | {row.list_type} | H={row.horizon_days} | "
                f"n={row.n_events_valid}/{row.n_events_total} | avg={avg_ret} | "
                f"win={win} | excess_vs_QQQ={ex} | "
                f"no_signal={getattr(row, 'n_no_signal_events', 0)} | "
                f"unpriced={getattr(row, 'n_unpriced_events', 0)}"
            )
    lines.append("")
    lines.append("## Signal Diagnostics")
    lines.append("")
    if signal_channel_summary.empty:
        lines.append("- no signal diagnostics")
    else:
        grouped = signal_channel_summary.groupby(["scenario", "list_type", "channel"], dropna=False)
        for keys, part in grouped:
            scenario, list_type, channel = keys
            avg_selected = pd.to_numeric(part["n_selected_channel"], errors="coerce").mean()
            avg_ranked = pd.to_numeric(part["n_ranked"], errors="coerce").mean()
            top_fail = ""
            if "top_first_fail" in part and not part.empty:
                top_fail = str(part["top_first_fail"].mode().iloc[0]) if not part["top_first_fail"].mode().empty else ""
            lines.append(
                "- "
                f"{scenario} | {list_type} | {channel} | "
                f"avg_selected={avg_selected:.2f} | avg_ranked={avg_ranked:.2f} | "
                f"common_first_fail={top_fail}"
            )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- events: {events_path}")
    lines.append(f"- summary: {summary_path}")
    lines.append(f"- benchmarks: {benchmarks_path}")
    lines.append(f"- segment summary: {segment_path}")
    lines.append(f"- signal diagnostics: {signal_diagnostics_path}")
    lines.append(f"- signal channel summary: {signal_channel_summary_path}")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `historical_replay` remains an approximation; survivorship bias is reduced but not fully eliminated.")
    lines.append("- Default theme source is `rules_proxy` (metadata keyword scoring), stable and reproducible.")
    lines.append("- `theme_source=latest_scan` and `theme_source=historical_news` are optional comparison modes.")
    lines.append("- This is useful for relative validation before long live accumulation, not a perfect PIT backtest.")
    lines.append("")
    return "\n".join(lines) + "\n"

def resolve_output_paths(prefix: str | None, output_dir: Path, mode: str) -> tuple[Path, Path, Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if prefix:
        stem = prefix
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"backtest_{mode}_{stamp}"
    base = output_dir / stem
    return (
        base.with_name(f"{base.name}_events.csv"),
        base.with_name(f"{base.name}_summary.csv"),
        base.with_name(f"{base.name}_benchmarks.csv"),
        base.with_name(f"{base.name}_segments.csv"),
        base.with_name(f"{base.name}_report.md"),
    )
