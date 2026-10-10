from __future__ import annotations

import argparse
import bisect
import copy
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ai_value_scanner.config import ScanConfig, load_config, resolve_channel_profile
from ai_value_scanner.replay_checkpoint import SignalDateCheckpointStore, path_sha256

from ai_value_scanner.fundamentals.accounting import (
    compute_adjusted_metrics,
    derive_accounting_metrics,
    fundamental_quality_score_from_metrics,
    safe_yoy,
)
from ai_value_scanner.fundamentals.facts import (
    FactRecord,
    VisibilityCutoff,
    extract_fact_records,
)
from ai_value_scanner.fundamentals.reconstruction import (
    build_flow_visibility_series,
    build_level_visibility_series,
    current_ttm_pair,
    latest_and_year_ago_level as shared_latest_and_year_ago_level,
)
from ai_value_scanner.fundamentals.shares import assess_share_count_integrity

from ai_value_scanner.features.derived import compute_cross_section_derived_features
from ai_value_scanner.features.ai_link import (
    ai_etf_consensus_score,
    ai_market_link_score,
    compute_ai_link_score,
)
from ai_value_scanner.features.price import compute_price_history_features
from ai_value_scanner.features.peer_valuation import compute_peer_relative_valuation
from ai_value_scanner.features.valuation import (
    compute_historical_valuation_percentile,
    safe_divide,
)

from ai_value_scanner.evaluation.backtest import (
    _hold_window_mature,
    build_signal_diagnostics,
    event_backtest,
    fallback_label_end_date,
    forward_return,
    forward_return_with_exit,
    infer_segment_label,
    next_trading_index,
    non_overlapping_cumulative,
    non_overlapping_event_returns,
    parse_json_object,
    summarize_backtest,
    summarize_backtest_by_segment,
)
from ai_value_scanner.reporting.backtest import (
    build_markdown_report,
    resolve_output_paths,
)

from ai_value_scanner.validation.snapshots import FeatureSnapshotWriter
from ai_value_scanner.strategy.scoring import score_and_rank
from ai_value_scanner.strategy.rules import (
    build_filter_steps,
    build_industry_trend_steps,
    build_momentum_steps,
)
from ai_value_scanner.strategy.research import (
    apply_low_value_research_gate,
    apply_research_assessment,
    build_research_assessment,
)
from ai_value_scanner.strategy.filtering import (
    apply_scored_or_hard_filters,
    first_fail_concentration,
    near_miss_concentration,
    summarize_diagnostics_by_layer,
    summarize_first_fail_reasons,
)
from ai_value_scanner.strategy.selection import (
    apply_group_caps,
    normalize_symbol_list,
    select_symbols_from_ranked_frames,
)

from ai_value_scanner.scanner import (
    AI_DISCLOSURE_KEYWORD_GROUPS,
    ASSETS_CURRENT_TAGS,
    BACKLOG_TAGS,
    CAPEX_TAGS,
    CASH_AND_EQUIVALENTS_TAGS,
    CURRENT_DEBT_TAGS,
    DA_TAGS,
    EBIT_TAGS,
    EPS_TAGS,
    INTEREST_EXPENSE_TAGS,
    INVENTORY_TAGS,
    LIABILITIES_CURRENT_TAGS,
    LONG_TERM_DEBT_TAGS,
    NET_INCOME_TAGS,
    NONRECURRING_EXPENSE_TAGS,
    NONRECURRING_GAIN_TAGS,
    OPERATING_CASH_FLOW_TAGS,
    QUARTERLY_FORMS,
    RECEIVABLES_CURRENT_TAGS,
    REVENUE_TAGS,
    SHARES_TAGS,
    AlpacaClient,
    NetworkMonitor,
    RequestRateLimiter,
    SecClient,
    ai_disclosure_score_from_submissions,
    ai_etf_consensus_score,
    ai_market_link_score,
    apply_split_adjustment,
    build_session,
    compile_keyword_patterns,
    compute_historical_valuation_percentile,
    load_watchlist_scores,
    watchlist_rows_to_scores,
    safe_divide,
    theme_score_from_news,
)


LIST_SUFFIX = {
    "low_value": "_ranked",
    "industry_trend": "_ranked_industry_trend",
    "momentum": "_ranked_momentum",
    "research_pool": "_ranked_research_pool",
}
VALID_LIST_TYPES = sorted(LIST_SUFFIX.keys())
STANDARD_EQUITY_SYMBOL_RE = r"^[A-Z]{1,5}(\.[A-Z])?$"
STANDARD_EQUITY_SYMBOL_PATTERN = re.compile(STANDARD_EQUITY_SYMBOL_RE)


@dataclass
class BacktestConfig:
    mode: str = "historical_replay"
    scan_config_path: str = "configs/config.risk_off.json"
    outputs_dir: str = "outputs"
    output_prefix: str | None = None
    list_types: list[str] | None = None
    top_n: int = 10
    per_channel_top_n: bool = True
    include_channels: list[str] | None = None
    exclude_drop_for_low_value: bool = True
    horizons: list[int] | None = None
    max_runs: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    benchmark_symbols: list[str] | None = None
    trading_cost_bps: float = 15.0
    dry_run: bool = False
    rebalance_frequency: str = "weekly"
    replay_max_symbols: int = 800
    theme_source: str = "rules_proxy"
    enable_perturbation: bool = True
    historical_news_lookback_days: int = 180
    historical_news_limit_per_symbol: int = 80
    replay_asset_status: str = "all"
    delist_return_assumption: float = -0.55
    delist_detection_buffer_days: int = 7
    use_historical_watchlist: bool = True
    watchlist_history_dir: str = "data/watchlist_history"
    watchlist_csv_path: str | None = None
    allow_latest_watchlist_fallback: bool = False
    pre_snapshot_universe: str = "union"
    disclosure_lookback_days: int = 720
    entry_price_mode: str = "next_open"
    exit_price_mode: str = "close"
    allow_lookahead_theme_source: bool = False
    feature_snapshot_dir: str | None = None
    feature_snapshot_dates: list[str] | None = None
    feature_snapshot_only: bool = False
    signal_checkpoint_dir: str | None = None
    resume_signal_checkpoints: bool = False
    signal_checkpoint_commit: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


@dataclass
class FundamentalPointInTime:
    sic: str | None
    sic_description: str | None
    revenue_series: list[tuple[pd.Timestamp, float]]
    net_income_series: list[tuple[pd.Timestamp, float]]
    shares_series: list[tuple[pd.Timestamp, float]]
    operating_cash_flow_series: list[tuple[pd.Timestamp, float]]
    capex_series: list[tuple[pd.Timestamp, float]]
    ebit_series: list[tuple[pd.Timestamp, float]]
    cash_series: list[tuple[pd.Timestamp, float]]
    long_term_debt_series: list[tuple[pd.Timestamp, float]]
    current_debt_series: list[tuple[pd.Timestamp, float]]
    current_assets_series: list[tuple[pd.Timestamp, float]]
    current_liabilities_series: list[tuple[pd.Timestamp, float]]
    receivables_series: list[tuple[pd.Timestamp, float]]
    inventory_series: list[tuple[pd.Timestamp, float]]
    interest_expense_series: list[tuple[pd.Timestamp, float]]
    da_series: list[tuple[pd.Timestamp, float]]
    backlog_series: list[tuple[pd.Timestamp, float, pd.Timestamp]]
    disclosure_series: list[tuple[pd.Timestamp, str]]
    ai_disclosure_score: float
    ai_backlog_signal: float
    # C05: per-tag TTM series so the replay can apply the same non-recurring
    # adjustments as the scan (sum of positive latest values across tags,
    # capped by nonrecurring_addback_revenue_cap).
    nonrecurring_expense_series: dict[str, list[tuple[pd.Timestamp, float, pd.Timestamp]]] = field(
        default_factory=dict
    )
    nonrecurring_gain_series: dict[str, list[tuple[pd.Timestamp, float, pd.Timestamp]]] = field(
        default_factory=dict
    )
    # Canonical raw facts are retained so production replay can reconstruct
    # the complete visible state at each asof, including amendments that only
    # change a historical YoY base rather than the latest TTM value.
    fact_records: dict[str, list[FactRecord]] = field(default_factory=dict)
    nonrecurring_expense_facts: dict[str, list[FactRecord]] = field(default_factory=dict)
    nonrecurring_gain_facts: dict[str, list[FactRecord]] = field(default_factory=dict)


def parse_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def parse_int_csv(raw: str | None, default: list[int]) -> list[int]:
    if not raw:
        return default
    out: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        out.append(int(token))
    return sorted(list(set(out)))


def parse_date_utc(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def parse_run_timestamp(run_stem: str) -> datetime | None:
    parts = run_stem.split("_")
    if len(parts) < 4:
        return None
    stamp = parts[3]
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_elapsed(seconds: float) -> str:
    whole = max(0, int(seconds))
    mins, sec = divmod(whole, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h{mins:02d}m{sec:02d}s"
    if mins > 0:
        return f"{mins}m{sec:02d}s"
    return f"{sec}s"


def bt_log(message: str, scope: str = "backtest", started_at_monotonic: float | None = None) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    elapsed = ""
    if started_at_monotonic is not None:
        elapsed = f" +{_format_elapsed(time.monotonic() - started_at_monotonic)}"
    print(f"[{scope} {ts}{elapsed}] {message}", flush=True)


def build_signal_checkpoint_manifest(
    cfg: BacktestConfig,
    scan_config: ScanConfig,
    scenario: str,
) -> dict[str, Any]:
    """Strict fingerprint for resumable historical-replay signal checkpoints."""
    watchlist_csv_path = cfg.watchlist_csv_path or scan_config.watchlist_csv_path
    return {
        "scenario": str(scenario),
        "strategy_style": str(scan_config.strategy_style or ""),
        "scan_config_path": str(cfg.scan_config_path),
        "scan_config_sha256": path_sha256(cfg.scan_config_path),
        "start_date": cfg.start_date,
        "end_date": cfg.end_date,
        "rebalance_frequency": cfg.rebalance_frequency,
        "replay_max_symbols": int(cfg.replay_max_symbols),
        "replay_asset_status": cfg.replay_asset_status,
        "theme_source": cfg.theme_source,
        "disclosure_lookback_days": int(cfg.disclosure_lookback_days),
        "list_types": list(cfg.list_types or VALID_LIST_TYPES),
        "top_n": int(cfg.top_n),
        "per_channel_top_n": bool(cfg.per_channel_top_n),
        "include_channels": list(cfg.include_channels or []),
        "horizons": list(cfg.horizons or [20, 60, 120]),
        "benchmark_symbols": list(cfg.benchmark_symbols or []),
        "trading_cost_bps": float(cfg.trading_cost_bps),
        "entry_price_mode": cfg.entry_price_mode,
        "exit_price_mode": cfg.exit_price_mode,
        "delist_return_assumption": float(cfg.delist_return_assumption),
        "delist_detection_buffer_days": int(cfg.delist_detection_buffer_days),
        "watchlist_csv_path": str(watchlist_csv_path or ""),
        "watchlist_csv_sha256": path_sha256(watchlist_csv_path),
        "watchlist_history_dir": str(cfg.watchlist_history_dir),
        "watchlist_history_sha256": path_sha256(cfg.watchlist_history_dir),
        "allow_latest_watchlist_fallback": bool(cfg.allow_latest_watchlist_fallback),
        "pre_snapshot_universe": cfg.pre_snapshot_universe,
    }


def keyword_list_from_groups(group_names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in group_names:
        for token in AI_DISCLOSURE_KEYWORD_GROUPS.get(group, []):
            key = str(token).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def resolve_ai_and_enabler_keywords(scan_config: ScanConfig) -> tuple[list[str], list[str]]:
    raw_ai = getattr(scan_config, "ai_keywords", None)
    if isinstance(raw_ai, list) and raw_ai:
        ai_keywords = [str(x).strip().lower() for x in raw_ai if str(x).strip()]
    else:
        ai_keywords = keyword_list_from_groups(["ai_compute", "semiconductor", "data_center"])

    raw_enabler = getattr(scan_config, "enabler_keywords", None)
    if isinstance(raw_enabler, list) and raw_enabler:
        enabler_keywords = [str(x).strip().lower() for x in raw_enabler if str(x).strip()]
    else:
        enabler_keywords = keyword_list_from_groups(["power_grid", "commercial_signal", "data_center"])

    return ai_keywords, enabler_keywords


def parse_watchlist_snapshot_date(path: Path) -> pd.Timestamp | None:
    name = path.stem
    patterns = [
        r"(\d{8}T\d{6}Z)",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{8})",
    ]
    for pattern in patterns:
        m = re.search(pattern, name)
        if not m:
            continue
        token = m.group(1)
        try:
            if "T" in token:
                dt = pd.Timestamp(datetime.strptime(token, "%Y%m%dT%H%M%SZ"), tz="UTC")
            elif "-" in token:
                dt = pd.Timestamp(datetime.strptime(token, "%Y-%m-%d"), tz="UTC")
            else:
                dt = pd.Timestamp(datetime.strptime(token, "%Y%m%d"), tz="UTC")
            return dt.normalize()
        except Exception:
            continue
    return None


WatchlistMap = dict[str, tuple[str, int, str]]


def watchlist_map_from_scores(scores: pd.DataFrame) -> WatchlistMap:
    out: WatchlistMap = {}
    if scores.empty:
        return out
    for row in scores.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).upper().strip()
        if not symbol:
            continue
        out[symbol] = (
            str(getattr(row, "watchlist_bucket", "") or ""),
            int(getattr(row, "watchlist_etf_count", 0) or 0),
            str(getattr(row, "watchlist_etfs", "") or ""),
        )
    return out


def load_watchlist_snapshots(
    cfg: BacktestConfig,
    scan_config: ScanConfig,
) -> tuple[list[tuple[pd.Timestamp, WatchlistMap, str]], WatchlistMap]:
    latest_scores = load_watchlist_scores(scan_config)
    latest_map = watchlist_map_from_scores(latest_scores)
    snapshots: list[tuple[pd.Timestamp, WatchlistMap, str]] = []
    if not cfg.use_historical_watchlist:
        return snapshots, latest_map

    history_dir = Path(cfg.watchlist_history_dir)
    if not history_dir.exists() or not history_dir.is_dir():
        return snapshots, latest_map

    for path in sorted(history_dir.glob("*.csv")):
        snap_dt = parse_watchlist_snapshot_date(path)
        if snap_dt is None:
            continue
        try:
            raw = pd.read_csv(path)
            scores = watchlist_rows_to_scores(raw)
            snap_map = watchlist_map_from_scores(scores)
        except Exception:
            continue
        if not snap_map:
            continue
        snapshots.append((snap_dt, snap_map, path.name))

    snapshots.sort(key=lambda x: x[0])
    return snapshots, latest_map


def union_watchlist_allowlist(
    snapshots: list[tuple[pd.Timestamp, WatchlistMap, str]],
    latest_map: WatchlistMap,
) -> set[str]:
    """Every symbol ever seen: all snapshot mappings plus the current list."""
    out: set[str] = set()
    for _, mapping, _ in snapshots or []:
        out.update(mapping.keys())
    out.update((latest_map or {}).keys())
    return out


def build_union_watchlist_map(
    snapshots: list[tuple[pd.Timestamp, WatchlistMap, str]],
    latest_map: WatchlistMap,
) -> WatchlistMap:
    """Union map for pre-snapshot replay dates: per-symbol metadata comes from
    the earliest snapshot containing the symbol (closest to a PIT view),
    falling back to the current list for names only seen there. PIT data
    availability (bars/filings as of each replay date) does the actual time
    filtering downstream. Residual bias: names that died before the first
    snapshot and never appear in any list stay excluded (documented upward).
    """
    merged: WatchlistMap = {}
    for _, mapping, _ in sorted(snapshots or [], key=lambda x: x[0]):
        for sym, val in mapping.items():
            merged.setdefault(sym, val)
    for sym, val in (latest_map or {}).items():
        merged.setdefault(sym, val)
    return merged


def resolve_watchlist_asof(
    asof: pd.Timestamp,
    snapshots: list[tuple[pd.Timestamp, WatchlistMap, str]],
    latest_map: WatchlistMap,
    allow_latest_fallback: bool,
    pre_snapshot_mode: str = "union",
    union_map: WatchlistMap | None = None,
) -> tuple[WatchlistMap, str]:
    if snapshots:
        dates = [x[0] for x in snapshots]
        idx = bisect.bisect_right(dates, asof.normalize()) - 1
        if idx >= 0:
            dt, mapping, name = snapshots[idx]
            return mapping, f"snapshot:{name}@{dt.date().isoformat()}"
    if pre_snapshot_mode == "union" and union_map:
        return union_map, "union_superset_approx"
    if allow_latest_fallback and latest_map:
        return latest_map, "latest_fallback"
    return {}, "none"


def _coerce_fact_records(points: list[Any]) -> list[FactRecord]:
    """Accept canonical FactRecord rows plus legacy dict points used by tests."""
    out: list[FactRecord] = []
    for index, point in enumerate(points):
        if isinstance(point, FactRecord):
            out.append(point)
            continue
        if not isinstance(point, dict):
            continue
        end_raw = point.get("end")
        value_raw = point.get("value")
        if end_raw is None or value_raw is None:
            continue
        try:
            end_ts = pd.Timestamp(end_raw)
            start_raw = point.get("start")
            start_ts = pd.Timestamp(start_raw) if start_raw is not None else None
            visible_ts = pd.Timestamp(point.get("visible") or end_raw)
            value = float(value_raw)
        except Exception:
            continue
        if not np.isfinite(value):
            continue
        accession_raw = point.get("accession") or point.get("accn")
        out.append(
            FactRecord(
                tag=str(point.get("tag") or f"legacy_{index}"),
                unit=str(point.get("unit") or ""),
                value=value,
                period_end=end_ts.date(),
                period_start=start_ts.date() if start_ts is not None else None,
                filed=visible_ts.date(),
                accession=str(accession_raw) if accession_raw else None,
                form=str(point.get("form") or ""),
                tag_priority=int(point.get("tag_priority") or index),
            )
        )
    return out


def extract_metric_points(
    companyfacts: dict[str, Any],
    tags: list[str],
    unit: str,
    allowed_forms: set[str],
) -> list[FactRecord]:
    """Parse metric facts through the canonical SEC fact model."""
    return extract_fact_records(companyfacts, tags, unit, allowed_forms)


def collapse_points_by_end(points: list[Any]) -> list[FactRecord]:
    """Compatibility helper retaining canonical fact records."""
    from ai_value_scanner.fundamentals.facts import collapse_fact_records_by_end

    return collapse_fact_records_by_end(_coerce_fact_records(points))


def _period_value_to_series_tuple(point: Any) -> tuple[pd.Timestamp, float, pd.Timestamp]:
    return (
        pd.Timestamp(point.available_on, tz="UTC"),
        float(point.value),
        pd.Timestamp(point.period_end, tz="UTC"),
    )


def build_level_series(points: list[Any]) -> list[tuple[pd.Timestamp, float, pd.Timestamp]]:
    """PIT level series built from the shared filing-version core."""
    return [
        _period_value_to_series_tuple(point)
        for point in build_level_visibility_series(_coerce_fact_records(points))
    ]


def build_flow_ttm_or_annual_series(
    points: list[Any],
) -> list[tuple[pd.Timestamp, float, pd.Timestamp]]:
    """PIT TTM/annual staircase built from the shared reconstruction core."""
    return [
        _period_value_to_series_tuple(point)
        for point in build_flow_visibility_series(_coerce_fact_records(points))
    ]


def build_disclosure_series_from_submissions(submissions: dict[str, Any]) -> list[tuple[pd.Timestamp, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []

    forms = recent.get("form", [])
    filed = recent.get("filingDate", recent.get("filed", []))
    items = recent.get("items", [])
    primary_desc = recent.get("primaryDocDescription", [])
    primary_doc = recent.get("primaryDocument", [])
    n = max(
        len(forms) if isinstance(forms, list) else 0,
        len(filed) if isinstance(filed, list) else 0,
        len(items) if isinstance(items, list) else 0,
        len(primary_desc) if isinstance(primary_desc, list) else 0,
        len(primary_doc) if isinstance(primary_doc, list) else 0,
    )
    out: list[tuple[pd.Timestamp, str]] = []
    for i in range(n):
        filed_val = filed[i] if isinstance(filed, list) and i < len(filed) else None
        if not filed_val:
            continue
        try:
            filed_dt = pd.Timestamp(filed_val, tz="UTC").normalize()
        except Exception:
            continue
        parts = [
            str(forms[i]) if isinstance(forms, list) and i < len(forms) else "",
            str(items[i]) if isinstance(items, list) and i < len(items) else "",
            str(primary_desc[i]) if isinstance(primary_desc, list) and i < len(primary_desc) else "",
            str(primary_doc[i]) if isinstance(primary_doc, list) and i < len(primary_doc) else "",
        ]
        text = " ".join(x for x in parts if x).strip().lower()
        if text:
            out.append((filed_dt, text))
    out.sort(key=lambda x: x[0])
    return out


def ai_disclosure_score_asof(
    disclosure_series: list[tuple[pd.Timestamp, str]],
    asof: pd.Timestamp,
    lookback_days: int,
    disclosure_keyword_cap: int,
) -> float:
    if not disclosure_series:
        return 0.0
    cutoff = asof.normalize() - pd.Timedelta(days=max(1, int(lookback_days)))
    snippets: list[str] = [
        text for ts, text in disclosure_series if cutoff <= ts <= asof.normalize() and text
    ]
    if not snippets:
        return 0.0
    text = " ".join(snippets)
    group_hits = 0
    keyword_hits = 0
    total_groups = len(AI_DISCLOSURE_KEYWORD_GROUPS)
    for keywords in AI_DISCLOSURE_KEYWORD_GROUPS.values():
        local_hits = 0
        for pattern in compile_keyword_patterns(tuple(k.lower() for k in keywords)):
            if pattern.search(text):
                local_hits += 1
        if local_hits > 0:
            group_hits += 1
            keyword_hits += local_hits
    if total_groups <= 0:
        return 0.0
    group_coverage = group_hits / float(total_groups)
    keyword_density = min(1.0, keyword_hits / max(1.0, float(disclosure_keyword_cap)))
    return round(float(np.clip(0.7 * group_coverage + 0.3 * keyword_density, 0.0, 1.0)), 6)


def discover_runs(outputs_dir: Path) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for path in outputs_dir.glob("ai_value_scan_*_ranked*.csv"):
        stem = path.stem
        list_type: str | None = None
        run_stem: str | None = None
        for candidate_type, suffix in LIST_SUFFIX.items():
            if stem.endswith(suffix):
                list_type = candidate_type
                run_stem = stem[: -len(suffix)]
                break
        if not list_type or not run_stem:
            continue
        ts = parse_run_timestamp(run_stem)
        if ts is None:
            continue
        row = buckets.setdefault(
            run_stem,
            {
                "run_stem": run_stem,
                "run_ts_utc": ts,
                "paths": {},
            },
        )
        row["paths"][list_type] = path
    runs = [row for row in buckets.values() if row.get("paths")]
    runs.sort(key=lambda x: x["run_ts_utc"])
    return runs


def filter_runs(
    runs: list[dict[str, Any]],
    start_dt: datetime | None,
    end_dt: datetime | None,
    max_runs: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in runs:
        ts = row["run_ts_utc"]
        if start_dt and ts < start_dt:
            continue
        if end_dt and ts > end_dt + timedelta(days=1):
            continue
        out.append(row)
    if max_runs is not None and max_runs > 0:
        out = out[-max_runs:]
    return out


def pick_symbols_from_list(
    csv_path: Path,
    list_type: str,
    top_n: int,
    per_channel_top_n: bool,
    include_channels: list[str] | None,
    exclude_drop_for_low_value: bool,
) -> list[str]:
    if not csv_path.exists():
        return []
    df = pd.read_csv(csv_path)
    if df.empty or "symbol" not in df.columns:
        return []

    if include_channels and "channel" in df.columns:
        df = df[df["channel"].isin(include_channels)]
    if list_type == "low_value" and exclude_drop_for_low_value and "triage_label" in df.columns:
        df = df[df["triage_label"] != "drop"]
    if df.empty:
        return []

    if list_type == "research_pool" and "research_priority" in df.columns:
        df = df[df["research_priority"].astype(str) != "avoid_for_now"].copy()
    if df.empty:
        return []

    if list_type == "research_pool" and "research_score" in df.columns:
        priority_order = {
            "research_now": 0,
            "watch_for_pullback": 1,
            "left_side_watch": 2,
            "theme_only": 3,
            "avoid_for_now": 4,
        }
        priority_series = (
            df["research_priority"]
            if "research_priority" in df.columns
            else pd.Series("", index=df.index)
        )
        df["_priority_rank"] = priority_series.map(priority_order).fillna(9).astype(int)
        df["_research_score"] = pd.to_numeric(df["research_score"], errors="coerce").fillna(-np.inf)
        df = df.sort_values(["_priority_rank", "_research_score"], ascending=[True, False])
    elif "composite_score" in df.columns:
        df = df.sort_values("composite_score", ascending=False)

    if per_channel_top_n and "channel" in df.columns:
        picks: list[str] = []
        for channel in sorted(df["channel"].dropna().astype(str).unique().tolist()):
            part = df[df["channel"] == channel].head(top_n)
            picks.extend(part["symbol"].dropna().astype(str).tolist())
    else:
        picks = df.head(top_n)["symbol"].dropna().astype(str).tolist()

    uniq: list[str] = []
    seen: set[str] = set()
    for sym in picks:
        s = sym.upper().strip()
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def build_signal_events_from_existing_runs(
    runs: list[dict[str, Any]],
    list_types: list[str],
    top_n: int,
    per_channel_top_n: bool,
    include_channels: list[str] | None,
    exclude_drop_for_low_value: bool,
    scenario: str = "base",
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for run in runs:
        ts = run["run_ts_utc"]
        signal_date = ts.date().isoformat()
        paths = run["paths"]
        for list_type in list_types:
            path = paths.get(list_type)
            if not path:
                continue
            symbols = pick_symbols_from_list(
                csv_path=path,
                list_type=list_type,
                top_n=top_n,
                per_channel_top_n=per_channel_top_n,
                include_channels=include_channels,
                exclude_drop_for_low_value=exclude_drop_for_low_value,
            )
            rows.append(
                {
                    "scenario": scenario,
                    "run_stem": run["run_stem"],
                    "run_ts_utc": ts.isoformat(),
                    "signal_date": signal_date,
                    "list_type": list_type,
                    "symbols": symbols,
                    "n_selected": len(symbols),
                    "source_csv": str(path),
                    "watchlist_source": "existing_runs",
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "scenario",
                "run_stem",
                "run_ts_utc",
                "signal_date",
                "list_type",
                "symbols",
                "n_selected",
                "source_csv",
                "watchlist_source",
            ]
        )
    return pd.DataFrame(rows)


def load_alpaca_client(scan_config: ScanConfig) -> tuple[AlpacaClient, NetworkMonitor]:
    load_dotenv()
    api_endpoint = os.getenv("ALPACA_API_ENDPOINT", "").strip()
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    data_endpoint = os.getenv("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets")
    feed = os.getenv("ALPACA_FEED", "iex")
    if not api_endpoint or not api_key or not api_secret:
        raise ValueError("Missing Alpaca credentials in .env.")

    monitor = NetworkMonitor()
    session = build_session()
    limiter = RequestRateLimiter(
        scan_config.alpaca_max_requests_per_sec,
        monitor=monitor,
        service_name="alpaca",
    )
    client = AlpacaClient(
        session=session,
        api_endpoint=api_endpoint,
        data_endpoint=data_endpoint,
        api_key=api_key,
        api_secret=api_secret,
        feed=feed,
        timeout_sec=scan_config.request_timeout_sec,
        request_limiter=limiter,
        cache_dir=Path(scan_config.cache_dir),
        cache_enabled=scan_config.alpaca_cache_enabled,
        cache_ttl_assets_sec=scan_config.alpaca_cache_ttl_assets_sec,
        cache_ttl_snapshots_sec=scan_config.alpaca_cache_ttl_snapshots_sec,
        # Historical daily bars barely change within a tuning session; the
        # default 6h TTL (mtime-based) would mark Volume-hosted cache files
        # stale and make every cloud container re-fetch and concurrently
        # rewrite the same bars files. Use a 30-day TTL for replay.
        cache_ttl_bars_sec=2_592_000,
        monitor=monitor,
    )
    return client, monitor


def load_sec_client(scan_config: ScanConfig, monitor: NetworkMonitor) -> SecClient:
    load_dotenv()
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise ValueError("Missing SEC_USER_AGENT in .env.")
    session = build_session()
    limiter = RequestRateLimiter(
        scan_config.sec_max_requests_per_sec,
        monitor=monitor,
        service_name="sec",
    )
    return SecClient(
        session=session,
        user_agent=user_agent,
        timeout_sec=scan_config.request_timeout_sec,
        cache_dir=Path(scan_config.cache_dir),
        request_limiter=limiter,
        monitor=monitor,
    )


def is_standard_equity_symbol(symbol: str) -> bool:
    s = str(symbol).strip().upper()
    if not s:
        return False
    return bool(STANDARD_EQUITY_SYMBOL_PATTERN.match(s))


def build_universe_for_replay(
    client: AlpacaClient,
    sec: SecClient,
    scan_config: ScanConfig,
    asset_status: str,
    symbol_allowlist: set[str] | None = None,
) -> pd.DataFrame:
    assets = client.get_assets(status=asset_status)
    df_assets = pd.DataFrame(assets)
    if df_assets.empty or "symbol" not in df_assets.columns:
        df_assets = pd.DataFrame(columns=["symbol", "name", "exchange", "status"])

    if not df_assets.empty:
        df_assets["symbol"] = df_assets["symbol"].astype(str).str.upper()
        df_assets = df_assets[df_assets["symbol"].apply(is_standard_equity_symbol)]
        if scan_config.enabled_exchanges and "exchange" in df_assets.columns:
            df_assets = df_assets[df_assets["exchange"].isin(scan_config.enabled_exchanges)]

    cols = ["symbol", "name", "exchange", "status"]
    for col in cols:
        if col not in df_assets.columns:
            df_assets[col] = None
    df_assets = df_assets[cols].drop_duplicates(subset=["symbol"])
    df_assets["status_rank"] = df_assets["status"].map({"active": 0, "inactive": 1}).fillna(2)
    df_assets = df_assets.sort_values(["status_rank", "symbol"]).drop(columns=["status_rank"])

    mapping = sec.ticker_mapping()
    merged = df_assets.merge(mapping, on="symbol", how="left")
    if "company_name" not in merged.columns:
        merged["company_name"] = None
    if "cik" not in merged.columns:
        merged["cik"] = None
    merged = merged[["symbol", "name", "exchange", "status", "cik", "company_name"]]
    merged = merged.dropna(subset=["symbol"]).drop_duplicates(subset=["symbol"]).reset_index(drop=True)

    if symbol_allowlist:
        allowlist = set(str(x).upper() for x in symbol_allowlist if str(x).strip())
        merged["symbol"] = merged["symbol"].astype(str).str.upper()
        existing = set(merged["symbol"].tolist())
        missing = sorted(allowlist.difference(existing))
        if missing:
            mapping_extra = mapping.copy()
            mapping_extra["symbol"] = mapping_extra["symbol"].astype(str).str.upper()
            mapping_extra = mapping_extra[mapping_extra["symbol"].isin(missing)].copy()
            if not mapping_extra.empty:
                for col in ("name", "exchange", "status"):
                    mapping_extra[col] = None
                for col in ("cik", "company_name"):
                    if col not in mapping_extra.columns:
                        mapping_extra[col] = None
                mapping_extra = mapping_extra[
                    ["symbol", "name", "exchange", "status", "cik", "company_name"]
                ].drop_duplicates(subset=["symbol"])
                merged = pd.concat([merged, mapping_extra], ignore_index=True)
        merged = merged[merged["symbol"].isin(allowlist)].copy()
        merged = merged.drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    return merged


def latest_asof(series: list[tuple], asof: pd.Timestamp) -> float | None:
    if not series:
        return None
    dates = [x[0] for x in series]
    idx = bisect.bisect_right(dates, asof) - 1
    if idx < 0:
        return None
    return float(series[idx][1])


def series_value_asof(
    series: list[tuple], asof: pd.Timestamp
) -> tuple[float | None, pd.Timestamp | None]:
    """Latest visible value (and its report period end) at or before asof."""
    if not series:
        return None, None
    dates = [x[0] for x in series]
    idx = bisect.bisect_right(dates, asof) - 1
    if idx < 0:
        return None, None
    entry = series[idx]
    try:
        value = float(entry[1])
    except (TypeError, ValueError):
        return None, None
    end = entry[2] if len(entry) > 2 else None
    return value, end


def latest_and_year_ago_flow(
    series: list[tuple], asof: pd.Timestamp, min_gap_days: int = 320, max_gap_days: int = 410
) -> tuple[float | None, float | None]:
    """Latest value plus a true year-ago base (C02).

    Mirrors the scanner's pick_latest_and_prev_ttm: the YoY base is the TTM
    window whose period end is min_gap..max_gap days before the latest
    window's end (closest to 365), not the adjacent window. Legacy 2-tuple
    entries (no period end) degrade to the adjacent-window behaviour so
    synthetic series keep working.
    """
    if not series:
        return None, None
    entries = sorted((x for x in series if x[0] <= asof), key=lambda x: x[0])
    if not entries:
        return None, None
    latest = entries[-1]
    try:
        latest_value = float(latest[1])
    except (TypeError, ValueError):
        return None, None
    latest_end = latest[2] if len(latest) > 2 else None
    if latest_end is None:
        prev = float(entries[-2][1]) if len(entries) > 1 else None
        return latest_value, prev
    lo = latest_end - pd.Timedelta(days=max_gap_days)
    hi = latest_end - pd.Timedelta(days=min_gap_days)
    best_gap: int | None = None
    prev: float | None = None
    for entry in entries[:-1]:
        end = entry[2] if len(entry) > 2 else None
        if end is None or end < lo or end > hi:
            continue
        try:
            value = float(entry[1])
        except (TypeError, ValueError):
            continue
        gap = abs(int((latest_end - end).days) - 365)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            prev = value
    return latest_value, prev


def latest_and_year_ago_level(
    series: list[tuple],
    asof: pd.Timestamp,
    min_age_days: int = 320,
    max_age_days: int = 410,
) -> tuple[float | None, float | None]:
    """Latest visible level plus a genuine year-ago comparison period."""
    if not series:
        return None, None
    entries = sorted((x for x in series if x[0] <= asof), key=lambda x: x[0])
    if not entries:
        return None, None
    latest = entries[-1]
    try:
        latest_value = float(latest[1])
    except (TypeError, ValueError):
        return None, None
    latest_end = latest[2] if len(latest) > 2 else None
    if latest_end is None:
        # Legacy synthetic 2-tuples do not carry a report period end; keep
        # their compatibility behavior without weakening production PIT data.
        prev = float(entries[-2][1]) if len(entries) > 1 else None
        return latest_value, prev

    best_gap: int | None = None
    prev: float | None = None
    for entry in entries[:-1]:
        end = entry[2] if len(entry) > 2 else None
        if end is None:
            continue
        gap_days = int((latest_end - end).days)
        if not min_age_days <= gap_days <= max_age_days:
            continue
        distance = abs(gap_days - 365)
        if best_gap is None or distance < best_gap:
            best_gap = distance
            try:
                prev = float(entry[1])
            except (TypeError, ValueError):
                prev = None
    return latest_value, prev


def flow_pair_asof(
    records: list[FactRecord],
    series: list[tuple],
    asof: pd.Timestamp,
) -> tuple[float | None, float | None]:
    """Canonical PIT flow pair, with legacy-series fallback for synthetic callers."""
    if records:
        return current_ttm_pair(
            records,
            VisibilityCutoff(filed_through=pd.Timestamp(asof).date()),
        )
    return latest_and_year_ago_flow(series, asof)


def level_pair_asof(
    records: list[FactRecord],
    series: list[tuple],
    asof: pd.Timestamp,
) -> tuple[float | None, float | None]:
    """Canonical PIT level pair, with legacy-series fallback for synthetic callers."""
    if records:
        return shared_latest_and_year_ago_level(
            records,
            VisibilityCutoff(filed_through=pd.Timestamp(asof).date()),
        )
    return latest_and_year_ago_level(series, asof)


def flow_value_asof(
    records: list[FactRecord],
    series: list[tuple],
    asof: pd.Timestamp,
) -> float | None:
    return flow_pair_asof(records, series, asof)[0]


def level_value_asof(
    records: list[FactRecord],
    series: list[tuple],
    asof: pd.Timestamp,
) -> float | None:
    return level_pair_asof(records, series, asof)[0]


def latest_and_prev_asof(
    series: list[tuple], asof: pd.Timestamp
) -> tuple[float | None, float | None]:
    if not series:
        return None, None
    dates = [x[0] for x in series]
    idx = bisect.bisect_right(dates, asof) - 1
    if idx < 0:
        return None, None
    latest = float(series[idx][1])
    prev = float(series[idx - 1][1]) if idx - 1 >= 0 else None
    return latest, prev


def series_up_to_asof(
    series: list[tuple], asof: pd.Timestamp
) -> list[tuple[pd.Timestamp, float]]:
    out: list[tuple[pd.Timestamp, float]] = []
    for entry in series:
        ts, val = entry[0], entry[1]
        if ts > asof:
            break
        try:
            fv = float(val)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(fv):
            continue
        out.append((ts, fv))
    return out


def close_history_from_frame_asof(
    bars: pd.DataFrame, asof: pd.Timestamp
) -> list[tuple[pd.Timestamp, float]]:
    if bars is None or bars.empty:
        return []
    if "close" not in bars.columns:
        return []
    out: list[tuple[pd.Timestamp, float]] = []
    if isinstance(bars.index, pd.DatetimeIndex):
        idx = bars.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        up_to = bars.loc[idx <= asof].copy()
        if up_to.empty:
            return []
        for ts, close_raw in up_to["close"].items():
            try:
                close = float(close_raw)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(close) or close <= 0:
                continue
            out.append((pd.Timestamp(ts).tz_convert("UTC").normalize(), close))
    elif "date" in bars.columns:
        up_to = bars[bars["date"] <= asof].copy()
        if up_to.empty:
            return []
        for row in up_to.itertuples(index=False):
            try:
                ts_raw = pd.Timestamp(getattr(row, "date"))
                if ts_raw.tzinfo is None:
                    ts = ts_raw.tz_localize("UTC").normalize()
                else:
                    ts = ts_raw.tz_convert("UTC").normalize()
                close = float(getattr(row, "close"))
            except Exception:
                continue
            if not np.isfinite(close) or close <= 0:
                continue
            out.append((ts, close))
    else:
        return []
    out.sort(key=lambda x: x[0])
    return out


def load_symbol_fundamental_pti(
    sec: SecClient,
    symbol: str,
    cik: str,
) -> tuple[str, FundamentalPointInTime]:
    submissions = sec.get_submissions(cik)
    companyfacts = sec.get_companyfacts(cik)
    fact_records: dict[str, list[FactRecord]] = {}

    def flow_metric(name: str, tags: list[str], unit: str = "USD") -> list[tuple]:
        records = extract_metric_points(companyfacts, tags, unit, QUARTERLY_FORMS)
        fact_records[name] = records
        return build_flow_ttm_or_annual_series(records)

    def level_metric(name: str, tags: list[str], unit: str = "USD") -> list[tuple]:
        records = extract_metric_points(companyfacts, tags, unit, QUARTERLY_FORMS)
        fact_records[name] = records
        return build_level_series(records)

    revenue_series = flow_metric("revenue", REVENUE_TAGS)
    net_income_series = flow_metric("net_income", NET_INCOME_TAGS)
    shares_series = level_metric("shares", SHARES_TAGS, "shares")
    fact_records["eps"] = extract_metric_points(
        companyfacts,
        EPS_TAGS,
        "USD/shares",
        QUARTERLY_FORMS,
    )
    operating_cash_flow_series = flow_metric(
        "operating_cash_flow",
        OPERATING_CASH_FLOW_TAGS,
    )
    capex_series = flow_metric("capex", CAPEX_TAGS)
    ebit_series = flow_metric("ebit", EBIT_TAGS)
    cash_series = level_metric("cash", CASH_AND_EQUIVALENTS_TAGS)
    long_term_debt_series = level_metric("long_term_debt", LONG_TERM_DEBT_TAGS)
    current_debt_series = level_metric("current_debt", CURRENT_DEBT_TAGS)
    current_assets_series = level_metric("current_assets", ASSETS_CURRENT_TAGS)
    current_liabilities_series = level_metric(
        "current_liabilities",
        LIABILITIES_CURRENT_TAGS,
    )
    receivables_series = level_metric("receivables", RECEIVABLES_CURRENT_TAGS)
    inventory_series = level_metric("inventory", INVENTORY_TAGS)
    interest_expense_series = flow_metric("interest_expense", INTEREST_EXPENSE_TAGS)
    da_series = flow_metric("da", DA_TAGS)
    backlog_series = level_metric("backlog", BACKLOG_TAGS)

    # C05: keep both raw facts and compatibility staircases for each adjustment
    # tag. Raw facts drive production asof reconstruction below.
    nonrecurring_expense_facts = {
        tag: extract_metric_points(companyfacts, [tag], "USD", QUARTERLY_FORMS)
        for tag in NONRECURRING_EXPENSE_TAGS
    }
    nonrecurring_gain_facts = {
        tag: extract_metric_points(companyfacts, [tag], "USD", QUARTERLY_FORMS)
        for tag in NONRECURRING_GAIN_TAGS
    }
    nonrecurring_expense_series = {
        tag: build_flow_ttm_or_annual_series(records)
        for tag, records in nonrecurring_expense_facts.items()
    }
    nonrecurring_gain_series = {
        tag: build_flow_ttm_or_annual_series(records)
        for tag, records in nonrecurring_gain_facts.items()
    }

    disclosure_series = build_disclosure_series_from_submissions(submissions)
    ai_disclosure_score, _, _ = ai_disclosure_score_from_submissions(
        submissions,
        disclosure_keyword_cap=6,
    )
    revenue_for_backlog = latest_asof(
        revenue_series,
        pd.Timestamp.now(tz="UTC").normalize(),
    )
    backlog_latest = latest_asof(
        backlog_series,
        pd.Timestamp.now(tz="UTC").normalize(),
    )
    ai_backlog_signal = 0.0
    if backlog_latest is not None and revenue_for_backlog not in (None, 0):
        ai_backlog_signal = float(
            np.clip(
                (float(backlog_latest) / float(revenue_for_backlog)) / 0.20,
                0.0,
                1.0,
            )
        )

    f = FundamentalPointInTime(
        sic=str(submissions.get("sic")) if submissions.get("sic") is not None else None,
        sic_description=submissions.get("sicDescription"),
        revenue_series=revenue_series,
        net_income_series=net_income_series,
        shares_series=shares_series,
        operating_cash_flow_series=operating_cash_flow_series,
        capex_series=capex_series,
        ebit_series=ebit_series,
        cash_series=cash_series,
        long_term_debt_series=long_term_debt_series,
        current_debt_series=current_debt_series,
        current_assets_series=current_assets_series,
        current_liabilities_series=current_liabilities_series,
        receivables_series=receivables_series,
        inventory_series=inventory_series,
        interest_expense_series=interest_expense_series,
        da_series=da_series,
        backlog_series=backlog_series,
        disclosure_series=disclosure_series,
        ai_disclosure_score=float(ai_disclosure_score or 0.0),
        ai_backlog_signal=float(ai_backlog_signal or 0.0),
        nonrecurring_expense_series=nonrecurring_expense_series,
        nonrecurring_gain_series=nonrecurring_gain_series,
        fact_records=fact_records,
        nonrecurring_expense_facts=nonrecurring_expense_facts,
        nonrecurring_gain_facts=nonrecurring_gain_facts,
    )
    return symbol, f


def build_fundamental_pti_db(
    universe: pd.DataFrame,
    sec: SecClient,
    max_workers: int,
) -> dict[str, FundamentalPointInTime]:
    out: dict[str, FundamentalPointInTime] = {}
    rows = universe[["symbol", "cik"]].dropna().drop_duplicates().itertuples(index=False)
    symbols = [(str(r.symbol).upper(), str(r.cik)) for r in rows]
    total = len(symbols)
    done = 0
    last_pct = -1
    phase_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(load_symbol_fundamental_pti, sec, sym, cik): sym for sym, cik in symbols}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                s, f = fut.result()
                out[s] = f
            except Exception:
                out[sym] = FundamentalPointInTime(
                    sic=None,
                    sic_description=None,
                    revenue_series=[],
                    net_income_series=[],
                    shares_series=[],
                    operating_cash_flow_series=[],
                    capex_series=[],
                    ebit_series=[],
                    cash_series=[],
                    long_term_debt_series=[],
                    current_debt_series=[],
                    current_assets_series=[],
                    current_liabilities_series=[],
                    receivables_series=[],
                    inventory_series=[],
                    interest_expense_series=[],
                    da_series=[],
                    backlog_series=[],
                    disclosure_series=[],
                    ai_disclosure_score=0.0,
                    ai_backlog_signal=0.0,
                )
            done += 1
            if total > 0:
                pct = int((done * 100) / total)
                if pct >= last_pct + 10 or done == total:
                    bt_log(
                        f"PIT fundamentals: {done}/{total} ({pct}%)",
                        scope="replay",
                        started_at_monotonic=phase_start,
                    )
                    last_pct = pct
    return out


def build_bar_db(
    client: AlpacaClient,
    symbols: list[str],
    start_iso: str,
    chunk_size: int,
) -> dict[str, pd.DataFrame]:
    bars_map = client.get_daily_bars(symbols, start_iso, chunk_size)
    out: dict[str, pd.DataFrame] = {}
    for symbol, rows in bars_map.items():
        table: list[dict[str, Any]] = []
        for row in rows:
            t = row.get("t")
            o = row.get("o")
            c = row.get("c")
            h = row.get("h")
            l = row.get("l")
            v = row.get("v")
            if t is None or c is None:
                continue
            try:
                dt = pd.Timestamp(t, tz="UTC").normalize()
                open_px = float(o) if o is not None else float(c)
                close = float(c)
                high = float(h) if h is not None else close
                low = float(l) if l is not None else close
                vol = float(v) if v is not None else 0.0
            except Exception:
                continue
            table.append(
                {
                    "date": dt,
                    "open": open_px,
                    "close": close,
                    "high": high,
                    "low": low,
                    "volume": vol,
                }
            )
        if not table:
            continue
        df = pd.DataFrame(table).drop_duplicates(subset=["date"], keep="last").sort_values("date")
        df = df.set_index("date")
        df["sma200"] = df["close"].rolling(window=200, min_periods=200).mean()
        out[symbol.upper()] = df
    return out


def apply_split_adjustment_to_frame(
    frame: pd.DataFrame | None,
    split_events: list[tuple[str, float]] | None,
) -> pd.DataFrame | None:
    """Split-adjust a price frame's o/h/l/c (and volume inversely).

    Same semantics as scanner.apply_split_adjustment but operating on the
    replay's DataFrame bars: pre-split rows are rescaled so the close series
    is continuous in adjusted-price space, volume is scaled inversely to keep
    dollar volume split-invariant, and the 200-day SMA is recomputed from the
    adjusted closes. Returns a copy; the shared bar_db is never mutated.
    Callers that pair closes with raw filed share counts (valuation history)
    must keep using the unadjusted frame.
    """
    if frame is None or frame.empty or not split_events:
        return frame
    events = sorted((str(d), float(m)) for d, m in split_events if d and m > 0)
    if not events:
        return frame
    out = frame.copy()
    mults = np.ones(len(out))
    for ex_date, mult in events:
        try:
            mask = np.asarray(out.index < pd.Timestamp(ex_date, tz="UTC"))
        except (TypeError, ValueError):
            continue
        mults = np.where(mask, mults * mult, mults)
    if np.all(mults == 1.0):
        return frame
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") * mults
    if "volume" in out.columns:
        with np.errstate(divide="ignore", invalid="ignore"):
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce") / np.where(mults == 0, np.nan, mults)
    if "close" in out.columns:
        out["sma200"] = (
            pd.to_numeric(out["close"], errors="coerce").rolling(window=200, min_periods=200).mean()
        )
    return out


def compute_price_features_asof(
    bar_df: pd.DataFrame,
    asof: pd.Timestamp,
    lookback_days: int,
    split_events: list[tuple[str, float]] | None = None,
) -> dict[str, float | int | None] | None:
    """Adapt PIT replay bars to the canonical price-history feature core."""
    if bar_df.empty:
        return None
    if split_events:
        bar_df = apply_split_adjustment_to_frame(bar_df, split_events)
        if bar_df is None or bar_df.empty:
            return None

    cutoff = pd.Timestamp(asof)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    idx = bar_df.index.searchsorted(cutoff, side="right") - 1
    if idx < 0:
        return None
    up_to = bar_df.iloc[: idx + 1]
    if up_to.empty:
        return None

    # price_lookback_days is a calendar-day contract in the live scanner,
    # where bars are fetched from now-lookback_days. Replay must use the same
    # meaning rather than treating the number as a count of trading rows.
    range_start = cutoff.normalize() - pd.Timedelta(days=max(1, int(lookback_days)))
    range_window = up_to.loc[up_to.index >= range_start]
    if range_window.empty:
        return None

    price = float(pd.to_numeric(up_to["close"], errors="coerce").iloc[-1])
    volume = (
        float(pd.to_numeric(up_to["volume"], errors="coerce").iloc[-1])
        if "volume" in up_to.columns
        else 0.0
    )
    dollar_volume = price * volume

    highs = (
        pd.to_numeric(range_window["high"], errors="coerce").dropna().astype(float).tolist()
        if "high" in range_window.columns
        else []
    )
    lows = (
        pd.to_numeric(range_window["low"], errors="coerce").dropna().astype(float).tolist()
        if "low" in range_window.columns
        else []
    )
    closes = pd.to_numeric(up_to["close"], errors="coerce").dropna().astype(float).tolist()

    dollar_volumes: list[float] = []
    if "volume" in up_to.columns:
        close_series = pd.to_numeric(up_to["close"], errors="coerce")
        volume_series = pd.to_numeric(up_to["volume"], errors="coerce")
        dollar_volumes = (close_series * volume_series).dropna().astype(float).tolist()

    features = compute_price_history_features(
        current_price=price,
        range_highs=highs,
        range_lows=lows,
        closes=closes,
        dollar_volumes=dollar_volumes,
    )
    return {
        "price": price,
        "dollar_volume": dollar_volume,
        **features,
    }

def build_rebalance_dates(
    start_date: datetime,
    end_date: datetime,
    frequency: str,
) -> list[pd.Timestamp]:
    if frequency == "monthly":
        idx = pd.date_range(start=start_date.date(), end=end_date.date(), freq="BME", tz="UTC")
    else:
        idx = pd.date_range(start=start_date.date(), end=end_date.date(), freq="W-FRI", tz="UTC")
    out: list[pd.Timestamp] = []
    for x in idx:
        ts = pd.Timestamp(x)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        out.append(ts.normalize())
    return out


def load_latest_theme_scores(outputs_dir: Path) -> dict[str, tuple[float, float]]:
    runs = discover_runs(outputs_dir)
    if not runs:
        return {}
    latest = runs[-1]
    table: dict[str, tuple[float, float]] = {}
    for list_type in VALID_LIST_TYPES:
        path = latest["paths"].get(list_type)
        if not path or not Path(path).exists():
            continue
        df = pd.read_csv(path)
        if df.empty or "symbol" not in df.columns:
            continue
        for row in df.itertuples(index=False):
            symbol = str(getattr(row, "symbol", "")).upper().strip()
            if not symbol:
                continue
            ai_raw = (
                getattr(row, "ai_score", None)
                if hasattr(row, "ai_score")
                else getattr(row, "ai_link_score", None)
            )
            en_raw = (
                getattr(row, "enabler_score", None)
                if hasattr(row, "enabler_score")
                else getattr(row, "ai_backlog_signal", None)
            )
            try:
                ai = float(ai_raw) if ai_raw is not None else 0.0
            except (TypeError, ValueError):
                ai = 0.0
            try:
                en = float(en_raw) if en_raw is not None else 0.0
            except (TypeError, ValueError):
                en = 0.0
            prev = table.get(symbol, (0.0, 0.0))
            table[symbol] = (max(prev[0], ai), max(prev[1], en))
    return table


def read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False))


def build_news_cache_path(
    cache_dir: Path,
    symbol: str,
    start_iso: str,
    end_iso: str,
    limit: int,
) -> Path:
    safe_symbol = str(symbol or "").upper()
    if not re.match(r"^[A-Z0-9.\-]{1,16}$", safe_symbol):
        raise ValueError(f"refusing to build cache path for suspicious symbol: {symbol!r}")
    safe_start = start_iso.replace(":", "").replace("+", "").replace("-", "")
    safe_end = end_iso.replace(":", "").replace("+", "").replace("-", "")
    return cache_dir / f"news_{safe_symbol}_{safe_start}_{safe_end}_{limit}.json"


def load_symbol_theme_from_historical_news(
    client: AlpacaClient,
    scan_config: ScanConfig,
    symbol: str,
    start_iso: str,
    end_iso: str,
    limit: int,
    cache_dir: Path,
    ai_keywords: list[str],
    enabler_keywords: list[str],
) -> tuple[str, tuple[float, float]]:
    cache_path = build_news_cache_path(cache_dir, symbol, start_iso, end_iso, limit)
    cached = read_json_file(cache_path)
    if isinstance(cached, dict):
        ai = float(cached.get("ai_score", 0.0) or 0.0)
        en = float(cached.get("enabler_score", 0.0) or 0.0)
        return symbol, (ai, en)

    try:
        news = client.get_news(symbol=symbol, start_iso=start_iso, limit=limit, end_iso=end_iso)
    except Exception:
        news = []
    ai = theme_score_from_news(news, ai_keywords)
    en = theme_score_from_news(news, enabler_keywords)
    write_json_file(
        cache_path,
        {
            "symbol": symbol,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "limit": limit,
            "ai_score": ai,
            "enabler_score": en,
            "news_count": len(news),
        },
    )
    return symbol, (ai, en)


def build_theme_scores_historical_news_asof(
    client: AlpacaClient,
    scan_config: ScanConfig,
    symbols: list[str],
    asof: pd.Timestamp,
    cfg: BacktestConfig,
    cache_dir: Path,
) -> dict[str, tuple[float, float]]:
    ai_keywords, enabler_keywords = resolve_ai_and_enabler_keywords(scan_config)
    start_dt = asof - timedelta(days=cfg.historical_news_lookback_days)
    start_iso = start_dt.isoformat()
    end_iso = asof.isoformat()
    out: dict[str, tuple[float, float]] = {}
    total = len(symbols)
    done = 0
    last_pct = -1
    phase_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=scan_config.max_workers) as pool:
        futs = {
            pool.submit(
                load_symbol_theme_from_historical_news,
                client,
                scan_config,
                symbol,
                start_iso,
                end_iso,
                cfg.historical_news_limit_per_symbol,
                cache_dir,
                ai_keywords,
                enabler_keywords,
            ): symbol
            for symbol in symbols
        }
        for fut in as_completed(futs):
            symbol = futs[fut]
            try:
                s, pair = fut.result()
                out[s] = pair
            except Exception:
                out[symbol] = (0.0, 0.0)
            done += 1
            if total > 0:
                pct = int((done * 100) / total)
                if pct >= last_pct + 25 or done == total:
                    bt_log(
                        f"historical news scoring: {done}/{total} ({pct}%)",
                        scope="replay",
                        started_at_monotonic=phase_start,
                    )
                    last_pct = pct
    return out


def theme_score_from_metadata_text(text: str, keywords: list[str]) -> float:
    content = (text or "").strip().lower()
    if not content:
        return 0.0
    patterns = compile_keyword_patterns(tuple(k.lower() for k in keywords))
    if not patterns:
        return 0.0
    hits = sum(1 for p in patterns if p.search(content))
    if hits <= 0:
        return 0.0
    norm_base = min(len(patterns), 8)
    density = hits / norm_base if norm_base > 0 else 0.0
    score = min(1.0, 0.35 + 0.65 * density)
    return round(float(score), 4)


def build_theme_scores_rules_proxy(
    universe: pd.DataFrame,
    fundamentals: dict[str, FundamentalPointInTime],
    scan_config: ScanConfig,
) -> dict[str, tuple[float, float]]:
    ai_keywords, enabler_keywords = resolve_ai_and_enabler_keywords(scan_config)
    out: dict[str, tuple[float, float]] = {}
    for row in universe.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).upper().strip()
        if not symbol:
            continue
        f = fundamentals.get(symbol)
        name = str(getattr(row, "name", "") or "")
        company_name = str(getattr(row, "company_name", "") or "")
        sic = str(getattr(f, "sic", "") or "") if f is not None else ""
        sic_desc = str(getattr(f, "sic_description", "") or "") if f is not None else ""
        text = " ".join([name, company_name, sic, sic_desc]).strip()
        ai = theme_score_from_metadata_text(text, ai_keywords)
        en = theme_score_from_metadata_text(text, enabler_keywords)
        out[symbol] = (ai, en)
    return out


def scale_min_threshold(v: float, factor: float) -> float:
    if v >= 0:
        return v * factor
    return v / factor


def perturb_scan_config(base: ScanConfig, scenario: str) -> ScanConfig:
    cfg = copy.deepcopy(base)
    if scenario == "base":
        return cfg
    factor = 0.8 if scenario == "loose" else 1.2

    for ch_name, profile in (cfg.channel_profiles or {}).items():
        for key in [
            "min_ps_discount",
            "min_pe_discount",
            "momentum_min_return_20d",
            "min_drawdown_from_52w_high",
        ]:
            if key in profile and profile[key] is not None:
                profile[key] = float(scale_min_threshold(float(profile[key]), factor))

        for key in [
            "max_range_position_52w",
            "max_price_to_sma200",
            "max_20d_return",
            "max_60d_volatility",
            "momentum_max_drawdown_from_52w_high",
        ]:
            if key in profile and profile[key] is not None:
                val = float(profile[key])
                if scenario == "loose":
                    profile[key] = min(2.0, val * 1.1)
                else:
                    profile[key] = max(0.0, val * 0.9)
    return cfg


def rank_and_pick_symbols(
    df: pd.DataFrame,
    scan_config: ScanConfig,
    list_type: str,
    top_n: int,
    per_channel_top_n: bool,
    include_channels: list[str] | None,
) -> list[str]:
    picks, _ = rank_and_pick_symbols_with_diagnostics(
        df=df,
        scan_config=scan_config,
        list_type=list_type,
        top_n=top_n,
        per_channel_top_n=per_channel_top_n,
        include_channels=include_channels,
    )
    return picks


def build_steps_and_weights(
    scan_config: ScanConfig,
    channel_name: str,
    channel_profile: dict[str, Any],
    list_type: str,
) -> tuple[list[tuple[str, Any]], dict[str, float]]:
    if list_type == "low_value":
        cp = resolve_channel_profile(scan_config, channel_name, channel_profile)
        return build_filter_steps(scan_config, channel_name, channel_profile), cp["score_weights"]
    if list_type == "industry_trend":
        return build_industry_trend_steps(scan_config, channel_name, channel_profile)
    if list_type == "momentum":
        return build_momentum_steps(scan_config, channel_name, channel_profile)
    raise ValueError(f"Unsupported list type for hard-filter ranking: {list_type}")


def pick_research_pool_symbols_with_diagnostics(
    df: pd.DataFrame,
    scan_config: ScanConfig,
    top_n: int,
    per_channel_top_n: bool,
    include_channels: list[str] | None,
) -> tuple[list[str], dict[str, Any]]:
    channel_profiles = scan_config.channel_profiles or {"core_ai": {}}
    work = df.copy()
    diagnostics: dict[str, Any] = {
        "channels": {},
        "channel_symbols": {},
        "channel_counts": {},
        "priority_counts": {},
    }
    if work.empty:
        diagnostics["selected_symbols"] = []
        return [], diagnostics

    if "channel" not in work.columns:
        work["channel"] = ""

    def infer_channel(row: pd.Series) -> str:
        bucket = str(row.get("watchlist_bucket", "") or "")
        for channel_name in channel_profiles.keys():
            if channel_name in bucket:
                return channel_name
        return str(row.get("channel", "") or "")

    work["channel"] = work.apply(infer_channel, axis=1)
    if include_channels:
        work = work[work["channel"].isin(include_channels)].copy()
    if work.empty:
        diagnostics["selected_symbols"] = []
        return [], diagnostics

    assessments = work.apply(lambda r: build_research_assessment(r, "research_pool"), axis=1)
    for col in [
        "research_priority",
        "research_score",
        "research_tags",
        "research_risks",
        "research_summary",
    ]:
        work[col] = assessments.map(lambda item: item[col])
    work = work[
        (pd.to_numeric(work["research_score"], errors="coerce").fillna(-np.inf) >= scan_config.research_pool_min_score)
        & (work["research_priority"].astype(str) != "avoid_for_now")
    ].copy()
    if work.empty:
        diagnostics["selected_symbols"] = []
        return [], diagnostics

    priority_order = {
        "research_now": 0,
        "watch_for_pullback": 1,
        "left_side_watch": 2,
        "theme_only": 3,
        "avoid_for_now": 4,
    }
    work["_priority_rank"] = work["research_priority"].map(priority_order).fillna(9).astype(int)
    work["_research_score"] = pd.to_numeric(work["research_score"], errors="coerce").fillna(-np.inf)
    work = work.sort_values(["_priority_rank", "_research_score", "symbol"], ascending=[True, False, True])
    cap = min(max(1, int(top_n)), max(1, int(scan_config.research_pool_top_n)))

    if per_channel_top_n:
        selected_frames: list[pd.DataFrame] = []
        for channel in sorted(work["channel"].dropna().astype(str).unique().tolist()):
            part = work[work["channel"] == channel].head(cap)
            diagnostics["channel_symbols"][channel] = part["symbol"].dropna().astype(str).tolist()
            diagnostics["channel_counts"][channel] = int(len(part))
            selected_frames.append(part)
        selected = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    else:
        selected = work.head(cap).copy()
        for channel in sorted(work["channel"].dropna().astype(str).unique().tolist()):
            part = selected[selected["channel"] == channel]
            diagnostics["channel_symbols"][channel] = part["symbol"].dropna().astype(str).tolist()
            diagnostics["channel_counts"][channel] = int(len(part))

    for channel in sorted(work["channel"].dropna().astype(str).unique().tolist()):
        part = work[work["channel"] == channel]
        diagnostics["channels"][channel] = {
            "n_input": int(len(df)),
            "n_filtered": int(len(part)),
            "n_ranked": int(len(part)),
            "priority_counts": part["research_priority"].value_counts().to_dict(),
        }
    diagnostics["priority_counts"] = (
        selected["research_priority"].value_counts().to_dict() if not selected.empty else {}
    )
    picks = normalize_symbol_list(selected["symbol"].dropna().astype(str).tolist()) if not selected.empty else []
    diagnostics["selected_symbols"] = picks
    return picks, diagnostics


def rank_and_pick_symbols_with_diagnostics(
    df: pd.DataFrame,
    scan_config: ScanConfig,
    list_type: str,
    top_n: int,
    per_channel_top_n: bool,
    include_channels: list[str] | None,
) -> tuple[list[str], dict[str, Any]]:
    if list_type == "research_pool":
        return pick_research_pool_symbols_with_diagnostics(
            df=df,
            scan_config=scan_config,
            top_n=top_n,
            per_channel_top_n=per_channel_top_n,
            include_channels=include_channels,
        )

    channel_profiles = scan_config.channel_profiles or {"core_ai": {}}
    ranked_frames: list[pd.DataFrame] = []
    diagnostics: dict[str, Any] = {
        "channels": {},
        "channel_symbols": {},
        "channel_counts": {},
    }

    for channel_name, channel_profile in channel_profiles.items():
        if include_channels and channel_name not in include_channels:
            continue
        steps, weights = build_steps_and_weights(
            scan_config,
            channel_name,
            channel_profile,
            list_type,
        )
        filtered, step_diagnostics = apply_scored_or_hard_filters(
            df,
            steps,
            channel_name,
            scan_config,
        )
        first_fail_summary = summarize_first_fail_reasons(df, steps)

        ranked = score_and_rank(
            filtered,
            weights,
            scan_config.score_winsor_lower_q,
            scan_config.score_winsor_upper_q,
            scan_config.score_penalty_overvaluation,
            scan_config.score_penalty_deterioration,
            scan_config.pe_cash_backing_haircut,
        )

        # Scanner low-value output applies research eligibility after scoring.
        # Replay must use the same post-score gate or historical selections are
        # not production-parity even when the feature matrix is identical.
        if list_type == "low_value" and not ranked.empty:
            ranked = apply_research_assessment(ranked, "low_value")
            ranked = apply_low_value_research_gate(ranked, scan_config)

        # Production scanner applies diversification caps per channel before
        # top-N selection. These caps are active in risk_on/risk_off configs.
        ranked = apply_group_caps(
            ranked,
            scan_config.max_per_sector_per_list,
            scan_config.max_per_watchlist_etf_source_per_list,
        )

        diagnostics["channels"][channel_name] = {
            "n_input": int(len(df)),
            "n_filtered": int(len(filtered)),
            "n_ranked": int(len(ranked)),
            "layer_summary": summarize_diagnostics_by_layer(
                step_diagnostics
            ),
            "first_fail": first_fail_concentration(first_fail_summary),
            "near_miss": near_miss_concentration(df, steps),
        }
        if ranked.empty:
            diagnostics["channel_symbols"][channel_name] = []
            diagnostics["channel_counts"][channel_name] = 0
            continue

        ranked = ranked.copy()
        ranked["channel"] = channel_name
        ranked_frames.append(ranked)

    picks, channel_symbols, channel_counts = select_symbols_from_ranked_frames(
        ranked_frames,
        top_n=top_n,
        per_channel_top_n=per_channel_top_n,
        dedupe_best_channel=bool(
            scan_config.enforce_unique_symbol_per_list
        ),
    )
    for channel_name in diagnostics["channels"]:
        diagnostics["channel_symbols"][channel_name] = channel_symbols.get(
            channel_name,
            [],
        )
        diagnostics["channel_counts"][channel_name] = channel_counts.get(
            channel_name,
            0,
        )
    diagnostics["selected_symbols"] = picks
    return picks, diagnostics

def build_cross_section_asof(
    asof: pd.Timestamp,
    universe: pd.DataFrame,
    bar_db: dict[str, pd.DataFrame],
    fundamentals: dict[str, FundamentalPointInTime],
    theme_scores: dict[str, tuple[float, float]],
    watchlist_by_symbol: dict[str, tuple[str, int, str]],
    benchmark_return_20d: float | None,
    benchmark_return_60d: float | None,
    disclosure_lookback_days: int,
    scan_config: ScanConfig,
    benchmark_trend_ok: bool | None = None,
    split_events: dict[str, list[tuple[str, float]]] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in universe.itertuples(index=False):
        symbol = str(row.symbol).upper()
        bars = bar_db.get(symbol)
        if bars is None:
            continue
        symbol_splits = (split_events or {}).get(symbol)
        price_feat = compute_price_features_asof(
            bars,
            asof=asof,
            lookback_days=scan_config.price_lookback_days,
            split_events=symbol_splits,
        )
        if not price_feat:
            continue
        f = fundamentals.get(symbol)
        if f is None:
            continue

        raw = f.fact_records
        visible_filing_dates = [
            record.filed
            for fact_map in (
                raw,
                f.nonrecurring_expense_facts,
                f.nonrecurring_gain_facts,
            )
            for records in fact_map.values()
            for record in records
            if record.filed is not None and record.filed <= asof.date()
        ]
        fundamental_data_asof = (
            max(visible_filing_dates).isoformat() if visible_filing_dates else None
        )
        revenue, revenue_prev = flow_pair_asof(
            raw.get("revenue", []),
            f.revenue_series,
            asof,
        )
        net_income, net_income_prev = flow_pair_asof(
            raw.get("net_income", []),
            f.net_income_series,
            asof,
        )
        share_records = raw.get("shares", [])
        _shares_raw, shares_prev = level_pair_asof(
            share_records,
            f.shares_series,
            asof,
        )
        if share_records:
            share_integrity = assess_share_count_integrity(
                share_records=share_records,
                eps_records=raw.get("eps", []),
                net_income_records=raw.get("net_income", []),
                metric_record_groups=(
                    raw.get("revenue", []),
                    raw.get("net_income", []),
                ),
                cutoff=VisibilityCutoff(
                    filed_through=pd.Timestamp(asof).date(),
                ),
            )
            shares = share_integrity.value
            shares_asof_end = (
                share_integrity.period_end.isoformat()
                if share_integrity.period_end is not None
                else None
            )
            shares_stale = bool(share_integrity.stale)
        else:
            # Legacy/synthetic callers may provide only the compatibility
            # series. Preserve their pre-15A behavior; production replay
            # carries raw FactRecord rows and uses the integrity path above.
            shares = _shares_raw
            _, legacy_shares_end = series_value_asof(f.shares_series, asof)
            shares_asof_end = (
                pd.Timestamp(legacy_shares_end).date().isoformat()
                if legacy_shares_end is not None
                else None
            )
            shares_stale = False
        operating_cash_flow, operating_cash_flow_prev = flow_pair_asof(
            raw.get("operating_cash_flow", []),
            f.operating_cash_flow_series,
            asof,
        )
        capex_raw = flow_value_asof(raw.get("capex", []), f.capex_series, asof)
        ebit, ebit_prev = flow_pair_asof(
            raw.get("ebit", []),
            f.ebit_series,
            asof,
        )
        cash_and_equivalents = level_value_asof(
            raw.get("cash", []),
            f.cash_series,
            asof,
        )
        debt_long_term = level_value_asof(
            raw.get("long_term_debt", []),
            f.long_term_debt_series,
            asof,
        )
        debt_current = level_value_asof(
            raw.get("current_debt", []),
            f.current_debt_series,
            asof,
        )
        current_assets = level_value_asof(
            raw.get("current_assets", []),
            f.current_assets_series,
            asof,
        )
        current_liabilities = level_value_asof(
            raw.get("current_liabilities", []),
            f.current_liabilities_series,
            asof,
        )
        receivables_current, receivables_prev = level_pair_asof(
            raw.get("receivables", []),
            f.receivables_series,
            asof,
        )
        inventory_current, inventory_prev = level_pair_asof(
            raw.get("inventory", []),
            f.inventory_series,
            asof,
        )
        interest_expense = flow_value_asof(
            raw.get("interest_expense", []),
            f.interest_expense_series,
            asof,
        )
        depreciation_and_amortization, depreciation_and_amortization_prev = flow_pair_asof(
            raw.get("da", []),
            f.da_series,
            asof,
        )

        # C05: apply the scan's non-recurring adjustments (sum of positive
        # latest values across tags, capped by nonrecurring_addback_revenue_cap).
        def _nonrecurring_sums(
            series_map: dict[str, list[tuple]],
            facts_map: dict[str, list[FactRecord]],
        ) -> tuple[float | None, float | None]:
            latest_sum = 0.0
            prev_sum = 0.0
            has_latest = False
            has_prev = False
            for tag in set(series_map).union(facts_map):
                latest, prev = flow_pair_asof(
                    facts_map.get(tag, []),
                    series_map.get(tag, []),
                    asof,
                )
                if latest is None:
                    continue
                latest_val = max(0.0, float(latest))
                latest_sum += latest_val
                has_latest = has_latest or latest_val > 0
                if prev is not None:
                    prev_val = max(0.0, float(prev))
                    prev_sum += prev_val
                    has_prev = has_prev or prev_val > 0
            return (latest_sum if has_latest else None, prev_sum if has_prev else None)

        addback, addback_prev = _nonrecurring_sums(
            f.nonrecurring_expense_series,
            f.nonrecurring_expense_facts,
        )
        gain, gain_prev = _nonrecurring_sums(
            f.nonrecurring_gain_series,
            f.nonrecurring_gain_facts,
        )
        adjusted = compute_adjusted_metrics(
            net_income=net_income,
            ebit=ebit,
            da=depreciation_and_amortization,
            revenue=revenue,
            revenue_prev=revenue_prev,
            addback=addback,
            gain=gain,
            addback_prev=addback_prev,
            gain_prev=gain_prev,
            cap_ratio=(
                scan_config.nonrecurring_addback_revenue_cap
                if scan_config.nonrecurring_addback_revenue_cap is not None
                else None
            ),
            net_income_prev=net_income_prev,
            ebit_prev=ebit_prev,
        )
        adjusted_net_income = adjusted["adjusted_net_income"]
        adjusted_ebit = adjusted["adjusted_ebit"]
        adjusted_ebitda = adjusted["adjusted_ebitda"]
        adjusted_net_income_prev = adjusted["adjusted_net_income_prev"]
        adjusted_ebit_prev = adjusted["adjusted_ebit_prev"]

        accounting = derive_accounting_metrics(
            revenue=revenue,
            revenue_prev=revenue_prev,
            net_income=net_income,
            net_income_prev=net_income_prev,
            operating_cash_flow=operating_cash_flow,
            operating_cash_flow_prev=operating_cash_flow_prev,
            capex_raw=capex_raw,
            ebit=ebit,
            ebit_prev=ebit_prev,
            shares=shares,
            shares_prev=shares_prev,
            cash_and_equivalents=cash_and_equivalents,
            debt_long_term=debt_long_term,
            debt_current=debt_current,
            current_assets=current_assets,
            current_liabilities=current_liabilities,
            receivables_current=receivables_current,
            receivables_prev=receivables_prev,
            inventory_current=inventory_current,
            inventory_prev=inventory_prev,
            interest_expense=interest_expense,
            depreciation_and_amortization=depreciation_and_amortization,
            depreciation_and_amortization_prev=depreciation_and_amortization_prev,
            adjusted_net_income=adjusted_net_income,
            adjusted_net_income_prev=adjusted_net_income_prev,
            adjusted_ebit=adjusted_ebit,
            adjusted_ebit_prev=adjusted_ebit_prev,
            adjusted_ebitda=adjusted_ebitda,
        )
        capex = accounting["capex"]
        free_cash_flow = accounting["free_cash_flow"]
        total_debt = accounting["total_debt"]
        net_debt = accounting["net_debt"]
        revenue_yoy = accounting["revenue_yoy"]
        net_income_yoy = accounting["net_income_yoy"]
        adjusted_net_income_yoy = accounting["adjusted_net_income_yoy"]
        ebit_yoy = accounting["ebit_yoy"]
        adjusted_ebit_yoy = accounting["adjusted_ebit_yoy"]
        operating_cash_flow_yoy = accounting["operating_cash_flow_yoy"]
        shares_yoy = accounting["shares_yoy"]
        receivables_yoy = accounting["receivables_yoy"]
        inventory_yoy = accounting["inventory_yoy"]
        da_yoy = accounting["da_yoy"]
        interest_expense_abs = accounting["interest_expense"]
        interest_coverage = accounting["interest_coverage"]
        net_debt_to_ebitda = accounting["net_debt_to_ebitda"]
        current_ratio = accounting["current_ratio"]
        current_debt_ratio_reported = accounting["current_debt_ratio_reported"]
        current_debt_ratio_inferred = accounting["current_debt_ratio_inferred"]
        current_debt_ratio = accounting["current_debt_ratio"]
        current_debt_ratio_source = accounting["current_debt_ratio_source"]
        ocf_to_net_income = accounting["ocf_to_net_income"]
        accrual_ratio = accounting["accrual_ratio"]
        receivables_growth_gap = accounting["receivables_growth_gap"]
        inventory_growth_gap = accounting["inventory_growth_gap"]
        inventory_growth_gap_reported = accounting["inventory_growth_gap_reported"]
        inventory_growth_gap_inferred = accounting["inventory_growth_gap_inferred"]
        inventory_growth_gap_source = accounting["inventory_growth_gap_source"]
        quality_score = accounting["fundamental_quality_score"]

        watch_bucket, watch_etf_count, watch_etfs = watchlist_by_symbol.get(symbol, ("", 0, ""))
        theme_ai, theme_enabler = theme_scores.get(symbol, (0.0, 0.0))
        asof_disclosure = ai_disclosure_score_asof(
            f.disclosure_series,
            asof=asof,
            lookback_days=disclosure_lookback_days,
            disclosure_keyword_cap=scan_config.ai_link_disclosure_keyword_cap,
        )
        backlog_latest = level_value_asof(
            raw.get("backlog", []),
            f.backlog_series,
            asof,
        )
        asof_backlog = 0.0
        if backlog_latest is not None and revenue not in (None, 0) and scan_config.ai_link_backlog_ratio_cap > 0:
            asof_backlog = float(
                np.clip(
                    (float(backlog_latest) / float(revenue))
                    / float(scan_config.ai_link_backlog_ratio_cap),
                    0.0,
                    1.0,
                )
            )
        ai_disclosure_score = float(
            np.clip(max(float(theme_ai or 0.0), float(asof_disclosure)), 0.0, 1.0)
        )
        ai_backlog_signal = float(
            np.clip(max(float(theme_enabler or 0.0), float(asof_backlog)), 0.0, 1.0)
        )
        ai_etf_score = ai_etf_consensus_score(watch_etf_count, scan_config.ai_link_etf_count_saturation)
        ai_market_score = ai_market_link_score(
            symbol_return_20d=price_feat.get("return_20d"),
            symbol_return_60d=price_feat.get("return_60d"),
            benchmark_return_20d=benchmark_return_20d,
            benchmark_return_60d=benchmark_return_60d,
            tol_20d=float(scan_config.ai_link_market_return_tolerance_20d),
            tol_60d=float(scan_config.ai_link_market_return_tolerance_60d),
        )
        ai_link_score = compute_ai_link_score(
            scan_config,
            ai_etf_score=ai_etf_score,
            ai_disclosure_score=ai_disclosure_score,
            ai_market_score=ai_market_score,
            ai_backlog_signal=ai_backlog_signal,
        )

        rows.append(
            {
                "symbol": symbol,
                "name": getattr(row, "name", None),
                "exchange": getattr(row, "exchange", None),
                "company_name": getattr(row, "company_name", None),
                "sic": f.sic,
                "sic_description": f.sic_description,
                "price": price_feat["price"],
                "dollar_volume": price_feat["dollar_volume"],
                "drawdown_from_52w_high": price_feat["drawdown_from_52w_high"],
                "range_position_52w": price_feat["range_position_52w"],
                "price_to_sma200": price_feat["price_to_sma200"],
                "days_below_sma200": price_feat["days_below_sma200"],
                "avg_dollar_volume_20d": price_feat["avg_dollar_volume_20d"],
                "return_20d": price_feat["return_20d"],
                "return_60d": price_feat["return_60d"],
                "volatility_60d": price_feat["volatility_60d"],
                "shares_outstanding": shares,
                "shares_asof_end": shares_asof_end,
                "shares_stale": shares_stale,
                "fundamental_data_asof": fundamental_data_asof,
                "revenue": revenue,
                "net_income": net_income,
                "operating_cash_flow": operating_cash_flow,
                "free_cash_flow": free_cash_flow,
                "ebit": ebit,
                "adjusted_net_income": adjusted_net_income,
                "adjusted_ebit": adjusted_ebit,
                "adjusted_ebitda": adjusted_ebitda,
                "nonrecurring_expense_addback": addback,
                "nonrecurring_gain_subtraction": gain,
                "cash_and_equivalents": cash_and_equivalents,
                "total_debt": total_debt,
                "net_debt": net_debt,
                "interest_expense": interest_expense_abs,
                "depreciation_and_amortization": depreciation_and_amortization,
                "current_assets": current_assets,
                "current_liabilities": current_liabilities,
                "receivables_current": receivables_current,
                "inventory_current": inventory_current,
                "revenue_yoy": revenue_yoy,
                "net_income_yoy": net_income_yoy,
                "adjusted_net_income_yoy": adjusted_net_income_yoy,
                "ebit_yoy": ebit_yoy,
                "adjusted_ebit_yoy": adjusted_ebit_yoy,
                "da_yoy": da_yoy,
                "operating_cash_flow_yoy": operating_cash_flow_yoy,
                "shares_yoy": shares_yoy,
                "receivables_yoy": receivables_yoy,
                "inventory_yoy": inventory_yoy,
                "receivables_growth_gap": receivables_growth_gap,
                "inventory_growth_gap": inventory_growth_gap,
                "inventory_growth_gap_reported": inventory_growth_gap_reported,
                "inventory_growth_gap_inferred": inventory_growth_gap_inferred,
                "inventory_growth_gap_source": inventory_growth_gap_source,
                "fundamental_quality_score": quality_score,
                "interest_coverage": interest_coverage,
                "net_debt_to_ebitda": net_debt_to_ebitda,
                "current_ratio": current_ratio,
                "current_debt_ratio_reported": current_debt_ratio_reported,
                "current_debt_ratio_inferred": current_debt_ratio_inferred,
                "current_debt_ratio": current_debt_ratio,
                "current_debt_ratio_source": current_debt_ratio_source,
                "ocf_to_net_income": ocf_to_net_income,
                "accrual_ratio": accrual_ratio,
                "watchlist_bucket": watch_bucket,
                "watchlist_etf_count": watch_etf_count,
                "watchlist_etfs": watch_etfs,
                "ai_etf_consensus_score": ai_etf_score,
                "ai_disclosure_score": ai_disclosure_score,
                "ai_market_link_score": ai_market_score,
                "ai_backlog_signal": ai_backlog_signal,
                "ai_link_score": ai_link_score,
                "news_count": 0,
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in [
        "price",
        "dollar_volume",
        "avg_dollar_volume_20d",
        "return_20d",
        "return_60d",
        "volatility_60d",
        "shares_outstanding",
        "revenue",
        "net_income",
        "operating_cash_flow",
        "free_cash_flow",
        "ebit",
        "adjusted_net_income",
        "adjusted_ebit",
        "adjusted_ebitda",
        "cash_and_equivalents",
        "total_debt",
        "net_debt",
        "interest_expense",
        "depreciation_and_amortization",
        "current_assets",
        "current_liabilities",
        "receivables_current",
        "inventory_current",
        "revenue_yoy",
        "net_income_yoy",
        "adjusted_net_income_yoy",
        "ebit_yoy",
        "adjusted_ebit_yoy",
        "da_yoy",
        "operating_cash_flow_yoy",
        "shares_yoy",
        "receivables_yoy",
        "inventory_yoy",
        "receivables_growth_gap",
        "inventory_growth_gap",
        "inventory_growth_gap_reported",
        "inventory_growth_gap_inferred",
        "fundamental_quality_score",
        "interest_coverage",
        "net_debt_to_ebitda",
        "current_ratio",
        "current_debt_ratio_reported",
        "current_debt_ratio_inferred",
        "current_debt_ratio",
        "ocf_to_net_income",
        "accrual_ratio",
        "watchlist_etf_count",
        "ai_etf_consensus_score",
        "ai_disclosure_score",
        "ai_market_link_score",
        "ai_backlog_signal",
        "ai_link_score",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["market_cap"] = df["price"] * df["shares_outstanding"]
    df["enterprise_value"] = df["market_cap"] + df["total_debt"].fillna(0) - df["cash_and_equivalents"].fillna(0)
    earnings_col = "adjusted_net_income" if scan_config.use_adjusted_quality_metrics else "net_income"
    ebit_col = "adjusted_ebit" if scan_config.use_adjusted_quality_metrics else "ebit"
    earnings_yoy_col = "adjusted_net_income_yoy" if scan_config.use_adjusted_quality_metrics else "net_income_yoy"
    df["ps"] = safe_divide(df["market_cap"], df["revenue"])
    df["pe"] = safe_divide(df["market_cap"], df[earnings_col])
    df["ev_to_ebit"] = safe_divide(df["enterprise_value"], df[ebit_col])
    df["fcf_yield"] = safe_divide(df["free_cash_flow"], df["market_cap"])
    df["net_margin"] = safe_divide(df[earnings_col], df["revenue"])

    derived_features = compute_cross_section_derived_features(
        df,
        earnings_yoy_col=earnings_yoy_col,
        assumed_position_usd=scan_config.assumed_position_usd,
    )
    for name, values in derived_features.items():
        df[name] = values

    ps_hist_values: list[float | None] = []
    pe_hist_values: list[float | None] = []
    ps_hist_obs: list[int] = []
    pe_hist_obs: list[int] = []
    ps_hist_sources: list[str] = []
    pe_hist_sources: list[str] = []
    for row in df.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).upper()
        f = fundamentals.get(symbol)
        bars = bar_db.get(symbol)
        if f is None or bars is None:
            ps_hist_values.append(None)
            pe_hist_values.append(None)
            ps_hist_obs.append(0)
            pe_hist_obs.append(0)
            ps_hist_sources.append("missing_inputs")
            pe_hist_sources.append("missing_inputs")
            continue

        closes = close_history_from_frame_asof(bars, asof)
        revenue_hist = series_up_to_asof(f.revenue_series, asof)
        net_income_hist = series_up_to_asof(f.net_income_series, asof)
        shares_hist = series_up_to_asof(f.shares_series, asof)

        current_shares = pd.to_numeric(pd.Series([getattr(row, "shares_outstanding", None)]), errors="coerce").iloc[0]
        if not np.isfinite(current_shares) or current_shares <= 0:
            current_shares = np.nan
        current_ps = pd.to_numeric(pd.Series([getattr(row, "ps", None)]), errors="coerce").iloc[0]
        if not np.isfinite(current_ps) or current_ps <= 0:
            current_ps = np.nan
        current_pe = pd.to_numeric(pd.Series([getattr(row, "pe", None)]), errors="coerce").iloc[0]
        if not np.isfinite(current_pe) or current_pe <= 0:
            current_pe = np.nan

        ps_pct, ps_obs = compute_historical_valuation_percentile(
            current_multiple=(None if not np.isfinite(current_ps) else float(current_ps)),
            closes=closes,
            denominator_history=revenue_hist,
            shares_history=shares_hist,
            current_shares=(None if not np.isfinite(current_shares) else float(current_shares)),
            window_days=scan_config.own_history_valuation_window_days,
            min_observations=3,
        )
        pe_pct, pe_obs = compute_historical_valuation_percentile(
            current_multiple=(None if not np.isfinite(current_pe) else float(current_pe)),
            closes=closes,
            denominator_history=net_income_hist,
            shares_history=shares_hist,
            current_shares=(None if not np.isfinite(current_shares) else float(current_shares)),
            window_days=scan_config.own_history_valuation_window_days,
            min_observations=3,
        )
        ps_hist_values.append(ps_pct)
        pe_hist_values.append(pe_pct)
        ps_hist_obs.append(int(ps_obs))
        pe_hist_obs.append(int(pe_obs))
        ps_hist_sources.append("valuation_history" if ps_pct is not None else "insufficient_history")
        pe_hist_sources.append("valuation_history" if pe_pct is not None else "insufficient_history")

    df["ps_hist_percentile"] = ps_hist_values
    df["pe_hist_percentile"] = pe_hist_values
    df["ps_hist_observation_count"] = ps_hist_obs
    df["pe_hist_observation_count"] = pe_hist_obs
    df["ps_hist_percentile_source"] = ps_hist_sources
    df["pe_hist_percentile_source"] = pe_hist_sources

    peer_features = compute_peer_relative_valuation(df, min_peer_count=5)
    for name, values in peer_features.items():
        df[name] = values

    df["watchlist_bucket"] = df["watchlist_bucket"].fillna("").astype(str)
    df["watchlist_etfs"] = df["watchlist_etfs"].fillna("").astype(str)
    if benchmark_trend_ok is not None:
        df["benchmark_trend_ok"] = bool(benchmark_trend_ok)

    return df


def build_signal_events_historical_replay(
    scan_config: ScanConfig,
    client: AlpacaClient,
    sec: SecClient,
    cfg: BacktestConfig,
    scenario: str,
    shared_cache: dict[str, Any] | None = None,
    snapshot_writer: FeatureSnapshotWriter | None = None,
) -> pd.DataFrame:
    replay_start = time.monotonic()
    start_dt = parse_date_utc(cfg.start_date)
    end_dt = parse_date_utc(cfg.end_date)
    if start_dt is None:
        start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
    if end_dt is None:
        end_dt = datetime.now(timezone.utc)
    if end_dt <= start_dt:
        raise ValueError("end_date must be greater than start_date.")

    snapshots, latest_watchlist_map = load_watchlist_snapshots(cfg, scan_config)
    # Union allowlist: every symbol ever seen (all snapshots + current list).
    # PIT data availability per replay date does the actual time filtering
    # downstream, so this needs no ETF history and never blocks on snapshot
    # coverage. Neutral (status, symbol) ordering is preserved for any
    # downstream truncation.
    watchlist_allowlist = union_watchlist_allowlist(snapshots, latest_watchlist_map)
    union_map = build_union_watchlist_map(snapshots, latest_watchlist_map)
    if not watchlist_allowlist:
        raise ValueError(
            "No watchlist symbols available for replay. Provide current watchlist or historical snapshots."
        )

    base_universe = build_universe_for_replay(
        client=client,
        sec=sec,
        scan_config=scan_config,
        asset_status=cfg.replay_asset_status,
        symbol_allowlist=watchlist_allowlist,
    )
    base_universe = base_universe.dropna(subset=["symbol"]).copy()
    base_universe["symbol"] = base_universe["symbol"].astype(str).str.upper()
    base_universe = base_universe.reset_index(drop=True)
    base_universe = base_universe[base_universe["symbol"].isin(watchlist_allowlist)].copy()

    prefetch_universe = base_universe.copy()
    if cfg.replay_max_symbols and cfg.replay_max_symbols > 0:
        if cfg.replay_asset_status == "all":
            prefetch_n = min(len(prefetch_universe), max(cfg.replay_max_symbols * 25, cfg.replay_max_symbols))
        else:
            prefetch_n = min(len(prefetch_universe), cfg.replay_max_symbols)
        # Truncation order inherits (status, symbol) from build_universe_for_replay:
        # performance-neutral by construction. Do NOT sort by liquidity/volume
        # here — that would tilt historical replay toward present winners.
        prefetch_universe = prefetch_universe.head(prefetch_n)

    symbols = prefetch_universe["symbol"].dropna().astype(str).tolist()
    benchmark_etfs = normalize_symbol_list([str(x).upper() for x in (scan_config.ai_link_benchmark_etfs or [])])
    trend_filter_symbol = str(scan_config.benchmark_trend_filter_symbol or "").upper().strip()
    # Regime tagging always needs the regime symbol's bars (defaults to QQQ),
    # even when the config has no benchmark trend filter enabled — otherwise
    # every signal silently falls to regime="unknown" (observed for balanced
    # in Phase 4: 1584/1584 unknown because QQQ never entered the bar fetch).
    regime_symbol = str(scan_config.benchmark_trend_filter_symbol or "QQQ").upper()
    bars_symbols = normalize_symbol_list(
        symbols
        + benchmark_etfs
        + [s for s in (trend_filter_symbol, regime_symbol) if s]
    )

    bt_log(
        f"universe symbols: {len(symbols)}",
        scope=f"replay:{scenario}",
        started_at_monotonic=replay_start,
    )
    bars_start = (start_dt - timedelta(days=max(420, scan_config.price_lookback_days))).isoformat()
    _bar_db_shared = shared_cache is not None and "bar_db" in shared_cache
    if _bar_db_shared:
        bar_db = shared_cache["bar_db"]
    else:
        bar_db = build_bar_db(client, bars_symbols, bars_start, scan_config.chunk_size)
        if shared_cache is not None:
            shared_cache["bar_db"] = bar_db
    bt_log(
        f"symbols with bars: {len(bar_db)}" + (" (shared)" if _bar_db_shared else ""),
        scope=f"replay:{scenario}",
        started_at_monotonic=replay_start,
    )
    # Authoritative split events for the replay window (same mechanism as the
    # live scan): cross-day price features, benchmark returns and forward
    # returns are computed on split-adjusted series. Valuation multiples keep
    # raw closes x raw filed shares and are never adjusted. Fail open.
    _split_shared = shared_cache is not None and "split_events" in shared_cache
    if _split_shared:
        split_events = shared_cache["split_events"]
    else:
        split_events = {}
        try:
            split_events = client.get_corporate_action_splits(
                bars_symbols,
                bars_start,
                (end_dt or datetime.now(timezone.utc)).date().isoformat(),
            )
            if split_events:
                bt_log(
                    f"split events: {len(split_events)} symbols",
                    scope=f"replay:{scenario}",
                    started_at_monotonic=replay_start,
                )
        except Exception as exc:
            bt_log(
                f"corporate-actions split fetch failed ({exc.__class__.__name__}); replay unadjusted",
                scope=f"replay:{scenario}",
                started_at_monotonic=replay_start,
            )
        if shared_cache is not None:
            shared_cache["split_events"] = split_events

    universe = prefetch_universe[prefetch_universe["symbol"].isin(set(bar_db.keys()))].copy()
    universe = universe.dropna(subset=["cik"]).copy()
    if cfg.replay_max_symbols and cfg.replay_max_symbols > 0:
        universe = universe.head(cfg.replay_max_symbols).copy()
    _fund_shared = shared_cache is not None and "fundamentals" in shared_cache
    if _fund_shared:
        fundamentals = shared_cache["fundamentals"]
    else:
        fundamentals = build_fundamental_pti_db(universe, sec, max_workers=scan_config.max_workers)
        if shared_cache is not None:
            shared_cache["fundamentals"] = fundamentals
    bt_log(
        f"fundamentals loaded: {len(fundamentals)}"
        + (" (shared across scenarios)" if _fund_shared else ""),
        scope=f"replay:{scenario}",
        started_at_monotonic=replay_start,
    )

    theme_scores_static: dict[str, tuple[float, float]] | None = None
    news_cache_dir = Path(scan_config.cache_dir) / "backtest_news"
    universe_symbols = universe["symbol"].dropna().astype(str).tolist()
    if cfg.theme_source == "latest_scan":
        theme_scores_static = load_latest_theme_scores(Path(cfg.outputs_dir))
        bt_log(
            f"latest-scan theme map size: {len(theme_scores_static)}",
            scope=f"replay:{scenario}",
            started_at_monotonic=replay_start,
        )
    elif cfg.theme_source == "rules_proxy":
        theme_scores_static = build_theme_scores_rules_proxy(
            universe=universe,
            fundamentals=fundamentals,
            scan_config=scan_config,
        )
        bt_log(
            f"rules-proxy theme map size: {len(theme_scores_static)}",
            scope=f"replay:{scenario}",
            started_at_monotonic=replay_start,
        )
    elif cfg.theme_source == "historical_news":
        bt_log(
            "historical-news scoring enabled "
            f"(lookback={cfg.historical_news_lookback_days}d, limit={cfg.historical_news_limit_per_symbol})",
            scope=f"replay:{scenario}",
            started_at_monotonic=replay_start,
        )
    else:
        theme_scores_static = {}

    if cfg.feature_snapshot_only:
        requested = cfg.feature_snapshot_dates or []
        if not requested:
            raise ValueError(
                "feature_snapshot_only requires at least one --feature-snapshot-dates value"
            )
        dates = []
        for token in requested:
            ts = pd.Timestamp(token)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            if start_dt <= ts.to_pydatetime() <= end_dt:
                dates.append(ts.normalize())
        dates = sorted(set(dates))
    else:
        dates = build_rebalance_dates(start_dt, end_dt, cfg.rebalance_frequency)
    bt_log(
        f"replay dates: {len(dates)}"
        + (" (snapshot-only)" if cfg.feature_snapshot_only else ""),
        scope=f"replay:{scenario}",
        started_at_monotonic=replay_start,
    )

    checkpoint_store: SignalDateCheckpointStore | None = None
    if cfg.signal_checkpoint_dir and not cfg.feature_snapshot_only:
        checkpoint_store = SignalDateCheckpointStore(
            Path(cfg.signal_checkpoint_dir) / scenario,
            build_signal_checkpoint_manifest(cfg, scan_config, scenario),
            resume=bool(cfg.resume_signal_checkpoints),
            commit_callback=cfg.signal_checkpoint_commit,
        )
        bt_log(
            f"signal checkpoints: {checkpoint_store.root} "
            f"(resume={bool(cfg.resume_signal_checkpoints)})",
            scope=f"replay:{scenario}",
            started_at_monotonic=replay_start,
        )

    rows: list[dict[str, Any]] = []
    watchlist_source_counts: dict[str, int] = {}
    last_heartbeat = 0.0
    for i, asof in enumerate(dates, start=1):
        now_tick = time.monotonic()
        if i == 1 or i == len(dates) or (now_tick - last_heartbeat) >= 30.0:
            bt_log(
                f"replay dates progress: {i}/{len(dates)} (asof={asof.date().isoformat()})",
                scope=f"replay:{scenario}",
                started_at_monotonic=replay_start,
            )
            last_heartbeat = now_tick

        signal_date = asof.date().isoformat()
        if checkpoint_store is not None:
            checkpoint = checkpoint_store.load(signal_date)
            if checkpoint is not None:
                checkpoint_rows = [
                    dict(row) for row in checkpoint.get("rows", [])
                ]
                rows.extend(checkpoint_rows)
                checkpoint_source = checkpoint.get("watchlist_source")
                if checkpoint_source:
                    source_key = str(checkpoint_source)
                    watchlist_source_counts[source_key] = (
                        watchlist_source_counts.get(source_key, 0) + 1
                    )
                bt_log(
                    f"checkpoint hit: {i}/{len(dates)} "
                    f"(asof={signal_date}, rows={len(checkpoint_rows)})",
                    scope=f"replay:{scenario}",
                    started_at_monotonic=replay_start,
                )
                continue
        date_row_start = len(rows)

        benchmark_trailing_60d = benchmark_trailing_return_asof(
            bar_db, regime_symbol, asof, 60, split_events.get(regime_symbol)
        )
        regime = "unknown"
        if benchmark_trailing_60d is not None:
            regime = "up" if benchmark_trailing_60d >= 0 else "down"
        watchlist_by_symbol, watchlist_source = resolve_watchlist_asof(
            asof=asof,
            snapshots=snapshots,
            latest_map=latest_watchlist_map,
            allow_latest_fallback=cfg.allow_latest_watchlist_fallback,
            pre_snapshot_mode=cfg.pre_snapshot_universe,
            union_map=union_map,
        )
        watchlist_source_counts[watchlist_source] = watchlist_source_counts.get(watchlist_source, 0) + 1
        if not watchlist_by_symbol:
            if checkpoint_store is not None:
                checkpoint_store.save(signal_date, [], watchlist_source)
            continue
        if cfg.theme_source == "historical_news":
            theme_scores = build_theme_scores_historical_news_asof(
                client=client,
                scan_config=scan_config,
                symbols=universe_symbols,
                asof=asof,
                cfg=cfg,
                cache_dir=news_cache_dir,
            )
        else:
            theme_scores = theme_scores_static or {}

        benchmark_returns_20d: list[float] = []
        benchmark_returns_60d: list[float] = []
        for etf in benchmark_etfs:
            etf_bars = bar_db.get(etf)
            if etf_bars is None:
                continue
            etf_feat = compute_price_features_asof(
                etf_bars,
                asof=asof,
                lookback_days=scan_config.price_lookback_days,
                split_events=split_events.get(etf),
            )
            if not etf_feat:
                continue
            r20 = etf_feat.get("return_20d")
            r60 = etf_feat.get("return_60d")
            if r20 is not None and np.isfinite(float(r20)):
                benchmark_returns_20d.append(float(r20))
            if r60 is not None and np.isfinite(float(r60)):
                benchmark_returns_60d.append(float(r60))
        benchmark_median_return_20d = (
            float(np.median(np.asarray(benchmark_returns_20d, dtype="float64")))
            if benchmark_returns_20d
            else None
        )
        benchmark_median_return_60d = (
            float(np.median(np.asarray(benchmark_returns_60d, dtype="float64")))
            if benchmark_returns_60d
            else None
        )
        df = build_cross_section_asof(
            asof=asof,
            universe=universe,
            bar_db=bar_db,
            fundamentals=fundamentals,
            theme_scores=theme_scores,
            watchlist_by_symbol=watchlist_by_symbol,
            benchmark_return_20d=benchmark_median_return_20d,
            benchmark_return_60d=benchmark_median_return_60d,
            disclosure_lookback_days=cfg.disclosure_lookback_days,
            scan_config=scan_config,
            benchmark_trend_ok=(
                benchmark_trend_ok_asof(
                    bar_db,
                    trend_filter_symbol,
                    asof,
                    scan_config.benchmark_trend_filter_sma_days,
                    split_events.get(trend_filter_symbol),
                )
                if trend_filter_symbol
                else None
            ),
            split_events=split_events,
        )
        if df.empty:
            if checkpoint_store is not None:
                checkpoint_store.save(signal_date, [], watchlist_source)
            continue

        snapshot_dates = set(cfg.feature_snapshot_dates or [])
        should_capture = (
            snapshot_writer is not None
            and (
                not snapshot_dates
                or asof.date().isoformat() in snapshot_dates
            )
        )
        if should_capture:
            snapshot_writer.write(
                style=str(scan_config.strategy_style or "unknown"),
                scenario=scenario,
                asof=asof,
                frame=df,
            )
        if cfg.feature_snapshot_only:
            continue

        for list_type in (cfg.list_types or VALID_LIST_TYPES):
            symbols_selected, signal_diag = rank_and_pick_symbols_with_diagnostics(
                df=df,
                scan_config=scan_config,
                list_type=list_type,
                top_n=cfg.top_n,
                per_channel_top_n=cfg.per_channel_top_n,
                include_channels=cfg.include_channels,
            )
            rows.append(
                {
                    "scenario": scenario,
                    "run_stem": f"replay_{scenario}_{asof.date().isoformat()}",
                    "run_ts_utc": asof.isoformat(),
                    "signal_date": asof.date().isoformat(),
                    "list_type": list_type,
                    "symbols": symbols_selected,
                    "n_selected": len(symbols_selected),
                    "benchmark_trailing_60d": benchmark_trailing_60d,
                    "regime": regime,
                    "channel_counts": json.dumps(signal_diag.get("channel_counts", {}), sort_keys=True),
                    "channel_symbols": json.dumps(signal_diag.get("channel_symbols", {}), sort_keys=True),
                    "filter_diagnostics": json.dumps(signal_diag.get("channels", {}), sort_keys=True),
                    "source_csv": "",
                    "watchlist_source": watchlist_source,
                }
            )

        if checkpoint_store is not None:
            checkpoint_store.save(
                signal_date,
                rows[date_row_start:],
                watchlist_source,
            )

    if watchlist_source_counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(watchlist_source_counts.items()))
        bt_log(
            f"watchlist source usage: {summary}",
            scope=f"replay:{scenario}",
            started_at_monotonic=replay_start,
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "scenario",
                "run_stem",
                "run_ts_utc",
                "signal_date",
                "list_type",
                "symbols",
                "n_selected",
                "benchmark_trailing_60d",
                "regime",
                "source_csv",
                "watchlist_source",
            ]
        )
    return pd.DataFrame(rows)


def benchmark_trailing_return_asof(
    bar_db: dict[str, pd.DataFrame],
    symbol: str,
    asof: pd.Timestamp,
    lookback_days: int,
    split_events: list[tuple[str, float]] | None = None,
) -> float | None:
    """PIT trailing return of the benchmark at a replay point.

    Uses only data up to `asof` (no lookahead): this marks the market regime
    for each signal so regime-conditional scoring can filter on it.
    """
    frame = bar_db.get(symbol.upper())
    if frame is None or frame.empty:
        return None
    frame = apply_split_adjustment_to_frame(frame, split_events)
    closes = close_history_from_frame_asof(frame, asof)
    if not closes or lookback_days <= 0:
        return None
    values = [float(v) for _, v in closes]
    if len(values) <= lookback_days:
        return None
    base = values[-(lookback_days + 1)]
    if base <= 0:
        return None
    return (values[-1] / base) - 1.0


def benchmark_trend_ok_asof(
    bar_db: dict[str, pd.DataFrame],
    trend_symbol: str,
    asof: pd.Timestamp,
    sma_days: int,
    split_events: list[tuple[str, float]] | None = None,
) -> bool | None:
    """Benchmark trend state at a replay point: close vs its own long SMA.

    Returns None when the filter cannot be evaluated (missing symbol or not
    enough history); callers treat None as fail-open.
    """
    frame = bar_db.get(trend_symbol.upper())
    if frame is None or frame.empty:
        return None
    frame = apply_split_adjustment_to_frame(frame, split_events)
    closes = close_history_from_frame_asof(frame, asof)
    if not closes or sma_days <= 0:
        return None
    values = [float(v) for _, v in closes]
    if len(values) < sma_days:
        return None
    window = values[-int(sma_days):]
    return bool(values[-1] >= float(np.mean(window)))


def build_price_frame_map(
    bars_map: dict[str, list[dict[str, Any]]],
    split_events: dict[str, list[tuple[str, float]]] | None = None,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol, rows in bars_map.items():
        if split_events:
            rows = apply_split_adjustment(rows, split_events.get(str(symbol).upper()) or None)
        dates: list[pd.Timestamp] = []
        opens: list[float] = []
        closes: list[float] = []
        for row in rows:
            t = row.get("t")
            o = row.get("o")
            c = row.get("c")
            if t is None or c is None:
                continue
            dt = pd.to_datetime(t, utc=True).normalize()
            try:
                open_px = float(o) if o is not None else float(c)
                close = float(c)
            except (TypeError, ValueError):
                continue
            dates.append(dt)
            opens.append(open_px)
            closes.append(close)
        if not dates:
            continue
        frame = pd.DataFrame(
            {"open": opens, "close": closes},
            index=pd.DatetimeIndex(dates),
        )
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        out[symbol.upper()] = frame
    return out




def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backtest AI lists via existing scans or historical replay."
    )
    p.add_argument("--mode", default="historical_replay", choices=["existing_runs", "historical_replay"])
    p.add_argument("--scan-config", default="configs/config.risk_off.json")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--output-prefix", default=None)
    p.add_argument("--list-types", default="low_value,industry_trend,momentum")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--per-channel-top-n", action="store_true", default=True)
    p.add_argument("--no-per-channel-top-n", action="store_true")
    p.add_argument("--include-channels", default="core_ai,ai_enabler,ai_peripheral")
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument("--max-runs", type=int, default=None)
    p.add_argument("--start-date", default="2023-01-01", help="YYYY-MM-DD")
    p.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    p.add_argument("--benchmark-symbols", default="QQQ,SOXX,XLI,XLU")
    p.add_argument("--trading-cost-bps", type=float, default=15.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--entry-price-mode", default="next_open", choices=["next_open", "next_close"])
    p.add_argument("--exit-price-mode", default="close", choices=["close", "open"])
    p.add_argument("--rebalance-frequency", default="weekly", choices=["weekly", "monthly"])
    p.add_argument("--replay-max-symbols", type=int, default=800)
    p.add_argument("--replay-asset-status", default="all", choices=["all", "active", "inactive"])
    p.add_argument("--watchlist-history-dir", default="data/watchlist_history")
    p.add_argument(
        "--watchlist-csv-path",
        default=None,
        help="Optional current-pool CSV override; useful for frozen refactor baselines.",
    )
    p.add_argument("--use-historical-watchlist", action="store_true", default=True)
    p.add_argument("--no-historical-watchlist", action="store_true")
    p.add_argument("--allow-latest-watchlist-fallback", action="store_true", default=False)
    p.add_argument("--no-latest-watchlist-fallback", action="store_true")
    p.add_argument("--pre-snapshot-universe", default="union", choices=["union", "strict"],
                   help="Universe for replay dates before the first PIT snapshot: "
                        "union (all snapshots + current list, PIT data availability filters; default) "
                        "or strict (legacy empty universe).")
    p.add_argument("--disclosure-lookback-days", type=int, default=720)
    p.add_argument(
        "--theme-source",
        default="rules_proxy",
        choices=["rules_proxy", "historical_news", "latest_scan", "zero"],
    )
    p.add_argument("--allow-lookahead-theme-source", action="store_true", default=False)
    p.add_argument("--historical-news-lookback-days", type=int, default=180)
    p.add_argument("--historical-news-limit-per-symbol", type=int, default=80)
    p.add_argument("--delist-return-assumption", type=float, default=-0.55)
    p.add_argument("--delist-detection-buffer-days", type=int, default=7)
    p.add_argument("--enable-perturbation", action="store_true", default=True)
    p.add_argument("--no-perturbation", action="store_true")
    p.add_argument(
        "--signal-checkpoint-dir",
        default=None,
        help=(
            "Optional directory for per-signal-date replay checkpoints. "
            "Use a persistent path for long research runs."
        ),
    )
    p.add_argument(
        "--resume-signal-checkpoints",
        action="store_true",
        default=False,
        help=(
            "Reuse completed signal-date checkpoints. The run is rejected "
            "if the checkpoint manifest does not match the current inputs."
        ),
    )
    p.add_argument(
        "--feature-snapshot-dir",
        default=None,
        help="Optional directory for deterministic pre-strategy cross-section snapshots.",
    )
    p.add_argument(
        "--feature-snapshot-dates",
        default=None,
        help="Comma-separated YYYY-MM-DD dates to capture. Required with --feature-snapshot-only.",
    )
    p.add_argument(
        "--feature-snapshot-only",
        action="store_true",
        default=False,
        help="Build only requested feature snapshots and skip ranking/event backtest.",
    )
    return p



def build_signals(cfg: BacktestConfig, scan_cfg: ScanConfig) -> tuple[pd.DataFrame, NetworkMonitor | None]:
    list_types = cfg.list_types or VALID_LIST_TYPES
    for t in list_types:
        if t not in VALID_LIST_TYPES:
            raise ValueError(f"Invalid list type: {t}")

    if cfg.mode == "existing_runs":
        runs = discover_runs(Path(cfg.outputs_dir))
        runs = filter_runs(
            runs,
            start_dt=parse_date_utc(cfg.start_date),
            end_dt=parse_date_utc(cfg.end_date),
            max_runs=cfg.max_runs,
        )
        signals = build_signal_events_from_existing_runs(
            runs=runs,
            list_types=list_types,
            top_n=cfg.top_n,
            per_channel_top_n=cfg.per_channel_top_n,
            include_channels=cfg.include_channels,
            exclude_drop_for_low_value=cfg.exclude_drop_for_low_value,
            scenario="base",
        )
        return signals, None

    if cfg.theme_source == "latest_scan" and not cfg.allow_lookahead_theme_source:
        raise ValueError(
            "theme_source=latest_scan introduces lookahead bias in historical_replay. "
            "Use --allow-lookahead-theme-source to override explicitly."
        )

    client, monitor = load_alpaca_client(scan_cfg)
    sec = load_sec_client(scan_cfg, monitor)
    scenarios = (
        ["base"]
        if cfg.feature_snapshot_only
        else (["base", "loose", "strict"] if cfg.enable_perturbation else ["base"])
    )
    frames: list[pd.DataFrame] = []
    scenario_cache: dict[str, Any] = {}
    snapshot_writer: FeatureSnapshotWriter | None = None
    if cfg.feature_snapshot_dir:
        snapshot_writer = FeatureSnapshotWriter(
            cfg.feature_snapshot_dir,
            metadata={
                "scan_config_path": cfg.scan_config_path,
                "strategy_style": scan_cfg.strategy_style,
                "start_date": cfg.start_date,
                "end_date": cfg.end_date,
                "replay_max_symbols": cfg.replay_max_symbols,
                "theme_source": cfg.theme_source,
                "snapshot_dates": sorted(cfg.feature_snapshot_dates or []),
                "snapshot_only": bool(cfg.feature_snapshot_only),
            },
        )
    for scenario in scenarios:
        scenario_cfg = perturb_scan_config(scan_cfg, scenario)
        scenario_cfg.max_symbols = cfg.replay_max_symbols
        df = build_signal_events_historical_replay(
            scan_config=scenario_cfg,
            client=client,
            sec=sec,
            cfg=cfg,
            scenario=scenario,
            shared_cache=scenario_cache,
            snapshot_writer=snapshot_writer,
        )
        frames.append(df)
    if snapshot_writer is not None:
        if cfg.feature_snapshot_only and not snapshot_writer.records:
            raise ValueError(
                "feature snapshot capture produced zero cross sections; "
                "check requested dates and watchlist coverage"
            )
        snapshot_writer.finalize()
    signals = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return signals, monitor


def run_backtest(cfg: BacktestConfig) -> dict[str, Any]:
    backtest_start = time.monotonic()
    if cfg.signal_checkpoint_dir and cfg.feature_snapshot_dir:
        raise ValueError(
            "signal-date checkpoints cannot be combined with feature snapshot capture; "
            "resume would skip already-completed dates and produce an incomplete snapshot set"
        )
    if cfg.feature_snapshot_only and not cfg.feature_snapshot_dir:
        raise ValueError(
            "feature_snapshot_only requires --feature-snapshot-dir"
        )
    if cfg.feature_snapshot_only and not cfg.feature_snapshot_dates:
        raise ValueError(
            "feature_snapshot_only requires --feature-snapshot-dates"
        )
    scan_cfg = load_config(cfg.scan_config_path)
    if cfg.watchlist_csv_path:
        scan_cfg.watchlist_csv_path = cfg.watchlist_csv_path
    events_path, summary_path, benchmarks_path, segments_path, report_path = resolve_output_paths(
        cfg.output_prefix,
        Path(cfg.outputs_dir),
        cfg.mode,
    )
    signal_diagnostics_path = events_path.with_name(f"{events_path.stem}_signal_diagnostics.csv")
    signal_channel_summary_path = events_path.with_name(f"{events_path.stem}_signal_channel_summary.csv")

    bt_log("building signals...", started_at_monotonic=backtest_start)
    signals, build_monitor = build_signals(cfg, scan_cfg)
    if cfg.feature_snapshot_only:
        manifest = (
            Path(cfg.feature_snapshot_dir) / "manifest.json"
            if cfg.feature_snapshot_dir
            else None
        )
        if manifest is None or not manifest.exists():
            raise ValueError("feature snapshot capture produced no manifest")
        bt_log(
            f"feature snapshot manifest: {manifest}",
            started_at_monotonic=backtest_start,
        )
        return {"feature_snapshot_manifest": manifest}
    if signals.empty:
        raise ValueError("No signals generated for selected mode/range.")
    bt_log(f"mode: {cfg.mode}", started_at_monotonic=backtest_start)
    bt_log(f"signal rows: {len(signals)}", started_at_monotonic=backtest_start)

    signals.to_csv(events_path.with_name(f"{events_path.stem}_signals.csv"), index=False)

    if cfg.dry_run:
        empty = pd.DataFrame()
        empty.to_csv(events_path, index=False)
        empty.to_csv(summary_path, index=False)
        empty.to_csv(benchmarks_path, index=False)
        empty.to_csv(segments_path, index=False)
        empty.to_csv(signal_diagnostics_path, index=False)
        empty.to_csv(signal_channel_summary_path, index=False)
        md = build_markdown_report(
            cfg=cfg,
            signals=signals,
            summary=empty,
            segment_summary=empty,
            signal_diagnostics=empty,
            signal_channel_summary=empty,
            events_path=events_path,
            summary_path=summary_path,
            benchmarks_path=benchmarks_path,
            segment_path=segments_path,
            signal_diagnostics_path=signal_diagnostics_path,
            signal_channel_summary_path=signal_channel_summary_path,
        )
        report_path.write_text(md)
        bt_log(f"dry-run artifacts written: {report_path}", started_at_monotonic=backtest_start)
        return {
            "events_path": events_path,
            "summary_path": summary_path,
            "benchmarks_path": benchmarks_path,
            "segments_path": segments_path,
            "signal_diagnostics_path": signal_diagnostics_path,
            "signal_channel_summary_path": signal_channel_summary_path,
            "report_path": report_path,
        }

    benchmark_symbols = normalize_symbol_list(cfg.benchmark_symbols or ["QQQ", "SOXX", "XLI", "XLU"])
    symbol_set: set[str] = set()
    for syms in signals["symbols"].tolist():
        if isinstance(syms, list):
            for sym in syms:
                symbol_set.add(str(sym).upper())
    for bench in benchmark_symbols:
        symbol_set.add(bench.upper())
    symbols = sorted(symbol_set)
    bt_log(f"symbols for pricing: {len(symbols)}", started_at_monotonic=backtest_start)

    client, run_monitor = load_alpaca_client(scan_cfg)
    start_dt = parse_date_utc(cfg.start_date) or datetime(2023, 1, 1, tzinfo=timezone.utc)
    bars_start = (start_dt - timedelta(days=420)).isoformat()
    bt_log("loading pricing bars...", started_at_monotonic=backtest_start)
    bars_map = client.get_daily_bars(symbols, bars_start, scan_cfg.chunk_size)
    # Same split discipline as the live scan: forward returns must be computed
    # on split-adjusted prices (a 10:1 split would otherwise print as -90%).
    # Fail open to raw bars on fetch errors.
    pricing_splits: dict[str, list[tuple[str, float]]] = {}
    try:
        pricing_splits = client.get_corporate_action_splits(symbols, bars_start)
    except Exception as exc:
        bt_log(
            f"corporate-actions split fetch failed ({exc.__class__.__name__}); pricing unadjusted",
            started_at_monotonic=backtest_start,
        )
    price_map = build_price_frame_map(bars_map, pricing_splits)

    roundtrip_cost = (2.0 * cfg.trading_cost_bps) / 10000.0
    events, benchmarks = event_backtest(
        signals=signals,
        prices_by_symbol=price_map,
        horizons=cfg.horizons or [20, 60, 120],
        roundtrip_cost=roundtrip_cost,
        benchmark_symbols=benchmark_symbols,
        entry_price_mode=cfg.entry_price_mode,
        exit_price_mode=cfg.exit_price_mode,
        delist_return_assumption=cfg.delist_return_assumption,
        delist_detection_buffer_days=cfg.delist_detection_buffer_days,
    )
    summary = summarize_backtest(events, benchmarks)
    segment_summary = summarize_backtest_by_segment(events, benchmarks)
    signal_diagnostics, signal_channel_summary = build_signal_diagnostics(signals)
    bt_log(
        f"backtest aggregation done (events={len(events)}, summary_rows={len(summary)})",
        started_at_monotonic=backtest_start,
    )

    events.to_csv(events_path, index=False)
    summary.to_csv(summary_path, index=False)
    benchmarks.to_csv(benchmarks_path, index=False)
    segment_summary.to_csv(segments_path, index=False)
    signal_diagnostics.to_csv(signal_diagnostics_path, index=False)
    signal_channel_summary.to_csv(signal_channel_summary_path, index=False)

    report_md = build_markdown_report(
        cfg=cfg,
        signals=signals,
        summary=summary,
        segment_summary=segment_summary,
        signal_diagnostics=signal_diagnostics,
        signal_channel_summary=signal_channel_summary,
        events_path=events_path,
        summary_path=summary_path,
        benchmarks_path=benchmarks_path,
        segment_path=segments_path,
        signal_diagnostics_path=signal_diagnostics_path,
        signal_channel_summary_path=signal_channel_summary_path,
    )
    report_path.write_text(report_md)

    network = run_monitor.to_dict()
    if build_monitor is not None:
        network["replay_build_phase"] = build_monitor.to_dict()
    network_path = report_path.with_name(f"{report_path.stem}_network.json")
    network_path.write_text(json.dumps(network, ensure_ascii=False, indent=2))

    total_valid_events = (
        int(pd.to_numeric(summary.get("n_events_valid"), errors="coerce").fillna(0).sum())
        if not summary.empty
        else 0
    )
    if total_valid_events == 0:
        bt_log(
            "warning: no valid forward-return events yet. "
            "Check end_date/horizon or ensure enough future bars exist.",
            started_at_monotonic=backtest_start,
        )

    bt_log(f"events: {events_path}", started_at_monotonic=backtest_start)
    bt_log(f"summary: {summary_path}", started_at_monotonic=backtest_start)
    bt_log(f"benchmarks: {benchmarks_path}", started_at_monotonic=backtest_start)
    bt_log(f"segments: {segments_path}", started_at_monotonic=backtest_start)
    bt_log(f"signal diagnostics: {signal_diagnostics_path}", started_at_monotonic=backtest_start)
    bt_log(f"signal channel summary: {signal_channel_summary_path}", started_at_monotonic=backtest_start)
    bt_log(f"report: {report_path}", started_at_monotonic=backtest_start)
    bt_log(f"network: {network_path}", started_at_monotonic=backtest_start)
    if not summary.empty:
        print("", flush=True)
        print("=== Backtest Summary (avg_return) ===", flush=True)
        for row in summary.itertuples(index=False):
            avg_ret = "nan" if pd.isna(row.avg_return) else f"{row.avg_return:.4f}"
            win = "nan" if pd.isna(row.win_rate) else f"{row.win_rate:.2%}"
            ex = "nan" if pd.isna(row.avg_excess_vs_QQQ) else f"{row.avg_excess_vs_QQQ:.4f}"
            print(
                f"- {row.scenario} | {row.list_type} | H={row.horizon_days} | "
                f"n={row.n_events_valid}/{row.n_events_total} | avg={avg_ret} | "
                f"win={win} | excess_vs_QQQ={ex}",
                flush=True,
            )
        print("=== End Backtest Summary ===", flush=True)

    return {
        "events_path": events_path,
        "summary_path": summary_path,
        "benchmarks_path": benchmarks_path,
        "segments_path": segments_path,
        "signal_diagnostics_path": signal_diagnostics_path,
        "signal_channel_summary_path": signal_channel_summary_path,
        "report_path": report_path,
        "network_path": network_path,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    per_channel = not args.no_per_channel_top_n
    perturb = not args.no_perturbation
    use_historical_watchlist = bool(args.use_historical_watchlist and not args.no_historical_watchlist)
    allow_latest_watchlist_fallback = bool(
        args.allow_latest_watchlist_fallback and not args.no_latest_watchlist_fallback
    )
    cfg = BacktestConfig(
        mode=args.mode,
        scan_config_path=args.scan_config,
        outputs_dir=args.outputs_dir,
        output_prefix=args.output_prefix,
        list_types=parse_csv_list(args.list_types),
        top_n=args.top_n,
        per_channel_top_n=per_channel,
        include_channels=parse_csv_list(args.include_channels),
        horizons=parse_int_csv(args.horizons, [20, 60, 120]),
        max_runs=args.max_runs,
        start_date=args.start_date,
        end_date=args.end_date,
        benchmark_symbols=parse_csv_list(args.benchmark_symbols),
        trading_cost_bps=args.trading_cost_bps,
        dry_run=bool(args.dry_run),
        entry_price_mode=args.entry_price_mode,
        exit_price_mode=args.exit_price_mode,
        rebalance_frequency=args.rebalance_frequency,
        replay_max_symbols=args.replay_max_symbols,
        replay_asset_status=args.replay_asset_status,
        use_historical_watchlist=use_historical_watchlist,
        watchlist_history_dir=args.watchlist_history_dir,
        watchlist_csv_path=args.watchlist_csv_path,
        allow_latest_watchlist_fallback=allow_latest_watchlist_fallback,
        pre_snapshot_universe=args.pre_snapshot_universe,
        disclosure_lookback_days=args.disclosure_lookback_days,
        theme_source=args.theme_source,
        allow_lookahead_theme_source=bool(args.allow_lookahead_theme_source),
        enable_perturbation=perturb,
        historical_news_lookback_days=args.historical_news_lookback_days,
        historical_news_limit_per_symbol=args.historical_news_limit_per_symbol,
        delist_return_assumption=args.delist_return_assumption,
        delist_detection_buffer_days=args.delist_detection_buffer_days,
        feature_snapshot_dir=args.feature_snapshot_dir,
        feature_snapshot_dates=parse_csv_list(args.feature_snapshot_dates),
        feature_snapshot_only=bool(args.feature_snapshot_only),
        signal_checkpoint_dir=args.signal_checkpoint_dir,
        resume_signal_checkpoints=bool(args.resume_signal_checkpoints),
    )
    run_backtest(cfg)


if __name__ == "__main__":
    main()
