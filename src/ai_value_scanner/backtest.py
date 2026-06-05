from __future__ import annotations

import argparse
import bisect
import copy
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ai_value_scanner.scanner import (
    AI_DISCLOSURE_KEYWORD_GROUPS,
    ANNUAL_FORMS,
    ASSETS_CURRENT_TAGS,
    BACKLOG_TAGS,
    CAPEX_TAGS,
    CASH_AND_EQUIVALENTS_TAGS,
    CURRENT_DEBT_TAGS,
    DA_TAGS,
    EBIT_TAGS,
    INTEREST_EXPENSE_TAGS,
    INVENTORY_TAGS,
    LIABILITIES_CURRENT_TAGS,
    LONG_TERM_DEBT_TAGS,
    NET_INCOME_TAGS,
    OPERATING_CASH_FLOW_TAGS,
    QUARTERLY_FORMS,
    RECEIVABLES_CURRENT_TAGS,
    REVENUE_TAGS,
    SHARES_TAGS,
    AlpacaClient,
    NetworkMonitor,
    RequestRateLimiter,
    ScanConfig,
    SecClient,
    ai_disclosure_score_from_submissions,
    ai_etf_consensus_score,
    ai_market_link_score,
    apply_filters_with_diagnostics,
    build_filter_steps,
    build_industry_trend_steps,
    build_momentum_steps,
    build_research_assessment,
    build_session,
    compile_keyword_patterns,
    compute_historical_valuation_percentile,
    first_fail_concentration,
    load_config,
    load_watchlist_scores,
    watchlist_rows_to_scores,
    resolve_channel_profile,
    safe_divide,
    safe_yoy,
    score_and_rank,
    fundamental_quality_score_from_metrics,
    summarize_diagnostics_by_layer,
    summarize_first_fail_reasons,
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
    scan_config_path: str = "configs/config.balanced.json"
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
    allow_latest_watchlist_fallback: bool = False
    disclosure_lookback_days: int = 720
    entry_price_mode: str = "next_open"
    exit_price_mode: str = "close"
    allow_lookahead_theme_source: bool = False


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
    backlog_series: list[tuple[pd.Timestamp, float]]
    disclosure_series: list[tuple[pd.Timestamp, str]]
    ai_disclosure_score: float
    ai_backlog_signal: float


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


def resolve_watchlist_asof(
    asof: pd.Timestamp,
    snapshots: list[tuple[pd.Timestamp, WatchlistMap, str]],
    latest_map: WatchlistMap,
    allow_latest_fallback: bool,
) -> tuple[WatchlistMap, str]:
    if snapshots:
        dates = [x[0] for x in snapshots]
        idx = bisect.bisect_right(dates, asof.normalize()) - 1
        if idx >= 0:
            dt, mapping, name = snapshots[idx]
            return mapping, f"snapshot:{name}@{dt.date().isoformat()}"
    if allow_latest_fallback and latest_map:
        return latest_map, "latest_fallback"
    return {}, "none"


def _merged_standard_taxonomy_facts(companyfacts: dict[str, Any]) -> dict[str, Any]:
    raw_facts = companyfacts.get("facts", {})
    merged: dict[str, Any] = {}
    for taxonomy in ("us-gaap", "ifrs-full"):
        facts = raw_facts.get(taxonomy, {})
        if not isinstance(facts, dict):
            continue
        for key, value in facts.items():
            if key not in merged:
                merged[key] = value
    return merged


def form_matches_allowed(form: Any, allowed_forms: set[str]) -> bool:
    token = str(form or "").strip().upper()
    if not token:
        return False
    if token in allowed_forms:
        return True
    if "/" in token:
        base = token.split("/", 1)[0]
        if base in allowed_forms:
            return True
    if token.endswith("A") and len(token) > 1:
        if token[:-1] in allowed_forms:
            return True
    return False


def normalize_form_token(form: Any) -> str:
    token = str(form or "").strip().upper()
    if not token:
        return ""
    if "/" in token:
        token = token.split("/", 1)[0]
    if token.endswith("A") and token[:-1] in ANNUAL_FORMS.union(QUARTERLY_FORMS):
        token = token[:-1]
    return token


def extract_metric_points(
    companyfacts: dict[str, Any],
    tags: list[str],
    unit: str,
    allowed_forms: set[str],
) -> list[dict[str, Any]]:
    facts = _merged_standard_taxonomy_facts(companyfacts)
    for tag in tags:
        tag_obj = facts.get(tag, {})
        units = tag_obj.get("units", {})
        entries = units.get(unit, [])
        points: list[dict[str, Any]] = []
        for item in entries:
            if not form_matches_allowed(item.get("form"), allowed_forms):
                continue
            end = item.get("end")
            filed = item.get("filed")
            val = item.get("val")
            if val is None or end is None:
                continue
            visible = filed or end
            try:
                end_dt = pd.Timestamp(end, tz="UTC").normalize()
                vis_dt = pd.Timestamp(visible, tz="UTC").normalize()
                fv = float(val)
            except Exception:
                continue
            if not np.isfinite(fv):
                continue
            points.append(
                {
                    "end": end_dt,
                    "visible": vis_dt,
                    "value": fv,
                    "form": str(item.get("form") or "").upper(),
                }
            )
        if points:
            return points
    return []


def collapse_points_by_end(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not points:
        return []
    best_by_end: dict[pd.Timestamp, dict[str, Any]] = {}
    for point in points:
        end = point["end"]
        prev = best_by_end.get(end)
        if prev is None or point["visible"] > prev["visible"]:
            best_by_end[end] = point
    out = list(best_by_end.values())
    out.sort(key=lambda x: x["end"])
    return out


def build_level_series(points: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, float]]:
    if not points:
        return []
    by_visible: dict[pd.Timestamp, float] = {}
    for point in points:
        vis = point["visible"]
        by_visible[vis] = float(point["value"])
    out = sorted(by_visible.items(), key=lambda x: x[0])
    return out


def build_flow_ttm_or_annual_series(points: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, float]]:
    if not points:
        return []
    quarterly = [p for p in points if normalize_form_token(p.get("form")) not in ANNUAL_FORMS]
    annual = [p for p in points if normalize_form_token(p.get("form")) in ANNUAL_FORMS]
    quarterly = collapse_points_by_end(quarterly)
    ttm_pairs: list[tuple[pd.Timestamp, float]] = []
    if len(quarterly) >= 4:
        for idx in range(3, len(quarterly)):
            window = quarterly[idx - 3 : idx + 1]
            visible = max(p["visible"] for p in window)
            ttm = float(sum(float(p["value"]) for p in window))
            ttm_pairs.append((visible, ttm))
        by_visible: dict[pd.Timestamp, float] = {}
        for vis, value in ttm_pairs:
            by_visible[vis] = value
        return sorted(by_visible.items(), key=lambda x: x[0])

    annual = collapse_points_by_end(annual)
    return build_level_series(annual)


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
            "theme_only": 2,
            "avoid_for_now": 3,
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
        cache_ttl_bars_sec=scan_config.alpaca_cache_ttl_bars_sec,
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


def normalize_symbol_list(symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        s = str(sym).strip().upper()
        if not s or s in seen:
            continue
        out.append(s)
        seen.add(s)
    return out


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


def latest_asof(series: list[tuple[pd.Timestamp, float]], asof: pd.Timestamp) -> float | None:
    if not series:
        return None
    dates = [x[0] for x in series]
    idx = bisect.bisect_right(dates, asof) - 1
    if idx < 0:
        return None
    return float(series[idx][1])


def latest_and_prev_asof(
    series: list[tuple[pd.Timestamp, float]], asof: pd.Timestamp
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
    series: list[tuple[pd.Timestamp, float]], asof: pd.Timestamp
) -> list[tuple[pd.Timestamp, float]]:
    out: list[tuple[pd.Timestamp, float]] = []
    for ts, val in series:
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


def load_symbol_fundamental_pti(sec: SecClient, symbol: str, cik: str) -> tuple[str, FundamentalPointInTime]:
    submissions = sec.get_submissions(cik)
    companyfacts = sec.get_companyfacts(cik)
    revenue_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, REVENUE_TAGS, "USD", QUARTERLY_FORMS)
    )
    net_income_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, NET_INCOME_TAGS, "USD", QUARTERLY_FORMS)
    )
    shares_series = build_level_series(
        extract_metric_points(companyfacts, SHARES_TAGS, "shares", QUARTERLY_FORMS)
    )
    operating_cash_flow_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, OPERATING_CASH_FLOW_TAGS, "USD", QUARTERLY_FORMS)
    )
    capex_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, CAPEX_TAGS, "USD", QUARTERLY_FORMS)
    )
    ebit_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, EBIT_TAGS, "USD", QUARTERLY_FORMS)
    )
    cash_series = build_level_series(
        extract_metric_points(companyfacts, CASH_AND_EQUIVALENTS_TAGS, "USD", QUARTERLY_FORMS)
    )
    long_term_debt_series = build_level_series(
        extract_metric_points(companyfacts, LONG_TERM_DEBT_TAGS, "USD", QUARTERLY_FORMS)
    )
    current_debt_series = build_level_series(
        extract_metric_points(companyfacts, CURRENT_DEBT_TAGS, "USD", QUARTERLY_FORMS)
    )
    current_assets_series = build_level_series(
        extract_metric_points(companyfacts, ASSETS_CURRENT_TAGS, "USD", QUARTERLY_FORMS)
    )
    current_liabilities_series = build_level_series(
        extract_metric_points(companyfacts, LIABILITIES_CURRENT_TAGS, "USD", QUARTERLY_FORMS)
    )
    receivables_series = build_level_series(
        extract_metric_points(companyfacts, RECEIVABLES_CURRENT_TAGS, "USD", QUARTERLY_FORMS)
    )
    inventory_series = build_level_series(
        extract_metric_points(companyfacts, INVENTORY_TAGS, "USD", QUARTERLY_FORMS)
    )
    interest_expense_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, INTEREST_EXPENSE_TAGS, "USD", QUARTERLY_FORMS)
    )
    da_series = build_flow_ttm_or_annual_series(
        extract_metric_points(companyfacts, DA_TAGS, "USD", QUARTERLY_FORMS)
    )
    backlog_series = build_level_series(
        extract_metric_points(companyfacts, BACKLOG_TAGS, "USD", QUARTERLY_FORMS)
    )
    disclosure_series = build_disclosure_series_from_submissions(submissions)
    ai_disclosure_score, _, _ = ai_disclosure_score_from_submissions(
        submissions,
        disclosure_keyword_cap=6,
    )
    revenue_for_backlog = latest_asof(revenue_series, pd.Timestamp.now(tz="UTC").normalize())
    backlog_latest = latest_asof(backlog_series, pd.Timestamp.now(tz="UTC").normalize())
    ai_backlog_signal = 0.0
    if backlog_latest is not None and revenue_for_backlog not in (None, 0):
        ai_backlog_signal = float(
            np.clip(
                (float(backlog_latest) / float(revenue_for_backlog))
                / 0.20,
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


def compute_price_features_asof(
    bar_df: pd.DataFrame,
    asof: pd.Timestamp,
    lookback_days: int,
) -> dict[str, float | int | None] | None:
    if bar_df.empty:
        return None
    idx = bar_df.index.searchsorted(asof, side="right") - 1
    if idx < 0:
        return None

    up_to = bar_df.iloc[: idx + 1]
    if up_to.empty:
        return None
    window = up_to.tail(max(lookback_days, 1))
    price = float(window["close"].iloc[-1])
    high_52w = float(window["high"].max())
    low_52w = float(window["low"].min())
    volume = float(window["volume"].iloc[-1]) if "volume" in window.columns else 0.0
    dollar_volume = price * volume
    avg_dollar_volume_20d = float((up_to["close"].tail(20) * up_to["volume"].tail(20)).mean()) if len(up_to) >= 20 else None

    drawdown = None
    if high_52w > 0:
        drawdown = 1.0 - (price / high_52w)

    range_pos = None
    if high_52w > low_52w:
        range_pos = (price - low_52w) / (high_52w - low_52w)

    sma200 = float(up_to["sma200"].iloc[-1]) if not pd.isna(up_to["sma200"].iloc[-1]) else None
    price_to_sma200 = None
    if sma200 and sma200 > 0:
        price_to_sma200 = price / sma200

    days_below_sma200 = None
    if len(up_to) >= 200:
        trailing = 0
        for _, row in up_to.iloc[::-1].iterrows():
            s = row["sma200"]
            c = row["close"]
            if pd.isna(s):
                break
            if float(c) < float(s):
                trailing += 1
            else:
                break
        days_below_sma200 = trailing

    return_20d = None
    if len(up_to) >= 21:
        prev = float(up_to["close"].iloc[-21])
        if prev > 0:
            return_20d = (price / prev) - 1.0

    return_60d = None
    if len(up_to) >= 61:
        prev_60d = float(up_to["close"].iloc[-61])
        if prev_60d > 0:
            return_60d = (price / prev_60d) - 1.0

    volatility_60d = None
    if len(up_to) >= 61:
        closes = up_to["close"].tail(61).to_numpy(dtype=float)
        daily_ret = (closes[1:] / closes[:-1]) - 1.0
        if daily_ret.size > 0:
            vol = float(np.nanstd(daily_ret, ddof=0) * np.sqrt(252.0))
            if np.isfinite(vol):
                volatility_60d = vol

    return {
        "price": price,
        "dollar_volume": dollar_volume,
        "drawdown_from_52w_high": round(drawdown, 6) if drawdown is not None else None,
        "range_position_52w": round(range_pos, 6) if range_pos is not None else None,
        "price_to_sma200": round(price_to_sma200, 6) if price_to_sma200 is not None else None,
        "days_below_sma200": int(days_below_sma200) if days_below_sma200 is not None else None,
        "avg_dollar_volume_20d": round(avg_dollar_volume_20d, 2) if avg_dollar_volume_20d is not None else None,
        "return_20d": round(return_20d, 6) if return_20d is not None else None,
        "return_60d": round(return_60d, 6) if return_60d is not None else None,
        "volatility_60d": round(volatility_60d, 6) if volatility_60d is not None else None,
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
    safe_start = start_iso.replace(":", "").replace("+", "").replace("-", "")
    safe_end = end_iso.replace(":", "").replace("+", "").replace("-", "")
    return cache_dir / f"news_{symbol}_{safe_start}_{safe_end}_{limit}.json"


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
        "theme_only": 2,
        "avoid_for_now": 3,
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
        steps, weights = build_steps_and_weights(scan_config, channel_name, channel_profile, list_type)
        filtered, step_diagnostics = apply_filters_with_diagnostics(df, steps)
        first_fail_summary = summarize_first_fail_reasons(df, steps)
        ranked = score_and_rank(
            filtered,
            weights,
            scan_config.score_winsor_lower_q,
            scan_config.score_winsor_upper_q,
            scan_config.score_penalty_overvaluation,
            scan_config.score_penalty_deterioration,
        )
        diagnostics["channels"][channel_name] = {
            "n_input": int(len(df)),
            "n_filtered": int(len(filtered)),
            "n_ranked": int(len(ranked)),
            "layer_summary": summarize_diagnostics_by_layer(step_diagnostics),
            "first_fail": first_fail_concentration(first_fail_summary),
        }
        if ranked.empty:
            diagnostics["channel_symbols"][channel_name] = []
            diagnostics["channel_counts"][channel_name] = 0
            continue
        ranked = ranked.copy()
        ranked["channel"] = channel_name
        ranked_frames.append(ranked)

    if not ranked_frames:
        diagnostics["selected_symbols"] = []
        return [], diagnostics

    if per_channel_top_n:
        picks: list[str] = []
        for part in ranked_frames:
            channel = str(part["channel"].iloc[0])
            channel_picks = part.head(top_n)["symbol"].dropna().astype(str).tolist()
            diagnostics["channel_symbols"][channel] = channel_picks
            diagnostics["channel_counts"][channel] = len(channel_picks)
            picks.extend(channel_picks)
    else:
        merged = pd.concat(ranked_frames, ignore_index=True)
        merged = merged.sort_values("composite_score", ascending=False)
        selected = merged.head(top_n).copy()
        picks = selected["symbol"].dropna().astype(str).tolist()
        for channel_name in diagnostics["channels"]:
            part = selected[selected["channel"] == channel_name] if "channel" in selected.columns else pd.DataFrame()
            channel_picks = part["symbol"].dropna().astype(str).tolist()
            diagnostics["channel_symbols"][channel_name] = channel_picks
            diagnostics["channel_counts"][channel_name] = len(channel_picks)
    picks = normalize_symbol_list(picks)
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
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in universe.itertuples(index=False):
        symbol = str(row.symbol).upper()
        bars = bar_db.get(symbol)
        if bars is None:
            continue
        price_feat = compute_price_features_asof(
            bars,
            asof=asof,
            lookback_days=scan_config.price_lookback_days,
        )
        if not price_feat:
            continue
        f = fundamentals.get(symbol)
        if f is None:
            continue

        revenue, revenue_prev = latest_and_prev_asof(f.revenue_series, asof)
        net_income, net_income_prev = latest_and_prev_asof(f.net_income_series, asof)
        shares, shares_prev = latest_and_prev_asof(f.shares_series, asof)
        operating_cash_flow, operating_cash_flow_prev = latest_and_prev_asof(
            f.operating_cash_flow_series, asof
        )
        capex_raw, _ = latest_and_prev_asof(f.capex_series, asof)
        ebit, ebit_prev = latest_and_prev_asof(f.ebit_series, asof)
        cash_and_equivalents, _ = latest_and_prev_asof(f.cash_series, asof)
        debt_long_term, _ = latest_and_prev_asof(f.long_term_debt_series, asof)
        debt_current, _ = latest_and_prev_asof(f.current_debt_series, asof)
        current_assets, _ = latest_and_prev_asof(f.current_assets_series, asof)
        current_liabilities, _ = latest_and_prev_asof(f.current_liabilities_series, asof)
        receivables_current, receivables_prev = latest_and_prev_asof(f.receivables_series, asof)
        inventory_current, inventory_prev = latest_and_prev_asof(f.inventory_series, asof)
        interest_expense, _ = latest_and_prev_asof(f.interest_expense_series, asof)
        depreciation_and_amortization, depreciation_and_amortization_prev = latest_and_prev_asof(
            f.da_series, asof
        )

        capex = abs(capex_raw) if capex_raw is not None else None
        free_cash_flow = (
            float(operating_cash_flow) - float(capex)
            if operating_cash_flow is not None and capex is not None
            else None
        )
        total_debt = None
        if debt_long_term is not None or debt_current is not None:
            total_debt = float(debt_long_term or 0.0) + float(debt_current or 0.0)
        net_debt = None
        if total_debt is not None or cash_and_equivalents is not None:
            net_debt = float(total_debt or 0.0) - float(cash_and_equivalents or 0.0)

        adjusted_net_income = net_income
        adjusted_ebit = ebit
        adjusted_ebitda = (
            float(adjusted_ebit or 0.0) + float(depreciation_and_amortization or 0.0)
            if adjusted_ebit is not None
            else None
        )

        revenue_yoy = safe_yoy(revenue, revenue_prev)
        net_income_yoy = safe_yoy(net_income, net_income_prev)
        adjusted_net_income_yoy = safe_yoy(adjusted_net_income, net_income_prev)
        ebit_yoy = safe_yoy(ebit, ebit_prev)
        adjusted_ebit_yoy = safe_yoy(adjusted_ebit, ebit_prev)
        operating_cash_flow_yoy = safe_yoy(operating_cash_flow, operating_cash_flow_prev)
        shares_yoy = safe_yoy(shares, shares_prev)
        receivables_yoy = safe_yoy(receivables_current, receivables_prev)
        inventory_yoy = safe_yoy(inventory_current, inventory_prev)
        da_yoy = safe_yoy(depreciation_and_amortization, depreciation_and_amortization_prev)

        interest_expense_abs = abs(float(interest_expense)) if interest_expense is not None else None
        interest_coverage = None
        if adjusted_ebit is not None and interest_expense_abs not in (None, 0):
            interest_coverage = float(adjusted_ebit) / float(interest_expense_abs)

        net_debt_to_ebitda = None
        if net_debt is not None and adjusted_ebitda not in (None, 0):
            net_debt_to_ebitda = float(net_debt) / float(adjusted_ebitda)

        current_ratio = None
        if current_assets is not None and current_liabilities not in (None, 0):
            current_ratio = float(current_assets) / float(current_liabilities)

        current_debt_ratio_reported = None
        current_debt_ratio_inferred = None
        current_debt_ratio = None
        current_debt_ratio_source = "missing"
        if debt_current is not None and current_assets not in (None, 0):
            current_debt_ratio_reported = float(debt_current) / float(current_assets)
            current_debt_ratio = current_debt_ratio_reported
            current_debt_ratio_source = "reported"
        elif current_assets not in (None, 0):
            if total_debt is not None and total_debt <= 0:
                current_debt_ratio_inferred = 0.0
                current_debt_ratio = 0.0
                current_debt_ratio_source = "inferred_zero_nonpositive_total_debt"
            elif total_debt is not None and current_liabilities not in (None, 0):
                inferred_current_debt = min(max(float(total_debt), 0.0), float(current_liabilities))
                current_debt_ratio_inferred = inferred_current_debt / float(current_assets)
                current_debt_ratio = current_debt_ratio_inferred
                current_debt_ratio_source = "inferred_total_debt_capped_by_current_liabilities"

        ocf_to_net_income = None
        if operating_cash_flow is not None and adjusted_net_income not in (None, 0):
            ocf_to_net_income = float(operating_cash_flow) / float(adjusted_net_income)

        accrual_ratio = None
        if adjusted_net_income is not None and operating_cash_flow is not None and current_assets not in (None, 0):
            accrual_ratio = (float(adjusted_net_income) - float(operating_cash_flow)) / float(current_assets)

        receivables_growth_gap = None
        if receivables_yoy is not None and revenue_yoy is not None:
            receivables_growth_gap = float(receivables_yoy) - float(revenue_yoy)

        inventory_growth_gap_reported = None
        inventory_growth_gap_inferred = None
        inventory_growth_gap = None
        inventory_growth_gap_source = "missing"
        if inventory_yoy is not None and revenue_yoy is not None:
            inventory_growth_gap_reported = float(inventory_yoy) - float(revenue_yoy)
            inventory_growth_gap = inventory_growth_gap_reported
            inventory_growth_gap_source = "reported"
        elif revenue_yoy is not None:
            inventory_not_applicable = (
                (inventory_current is None and inventory_prev is None)
                or ((inventory_current in (0, 0.0)) and (inventory_prev in (0, 0.0)))
            )
            if inventory_not_applicable:
                inventory_growth_gap_inferred = 0.0
                inventory_growth_gap = 0.0
                inventory_growth_gap_source = "inferred_inventory_not_applicable"

        quality_score = fundamental_quality_score_from_metrics(
            net_debt_to_ebitda=net_debt_to_ebitda,
            interest_coverage=interest_coverage,
            current_ratio=current_ratio,
            ocf_to_net_income=ocf_to_net_income,
            accrual_ratio=accrual_ratio,
        )

        watch_bucket, watch_etf_count, watch_etfs = watchlist_by_symbol.get(symbol, ("", 0, ""))
        theme_ai, theme_enabler = theme_scores.get(symbol, (0.0, 0.0))
        asof_disclosure = ai_disclosure_score_asof(
            f.disclosure_series,
            asof=asof,
            lookback_days=disclosure_lookback_days,
            disclosure_keyword_cap=scan_config.ai_link_disclosure_keyword_cap,
        )
        backlog_latest = latest_asof(f.backlog_series, asof)
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
        ai_link_score = float(
            np.clip(
                0.40 * float(ai_etf_score)
                + 0.35 * float(ai_disclosure_score)
                + 0.15 * float(ai_market_score)
                + 0.10 * float(ai_backlog_signal),
                0.0,
                1.0,
            )
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
                "revenue": revenue,
                "net_income": net_income,
                "operating_cash_flow": operating_cash_flow,
                "free_cash_flow": free_cash_flow,
                "ebit": ebit,
                "adjusted_net_income": adjusted_net_income,
                "adjusted_ebit": adjusted_ebit,
                "adjusted_ebitda": adjusted_ebitda,
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

    df["expectation_proxy"] = (
        0.5 * pd.to_numeric(df["revenue_yoy"], errors="coerce").fillna(0)
        + 0.5 * pd.to_numeric(df[earnings_yoy_col], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(df["return_20d"], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(df["return_60d"], errors="coerce").fillna(0)
    )
    df["cycle_proxy"] = pd.to_numeric(df["adjusted_ebit_yoy"], errors="coerce").fillna(
        pd.to_numeric(df["ebit_yoy"], errors="coerce")
    ) - pd.to_numeric(df["revenue_yoy"], errors="coerce")
    df["adv_participation"] = safe_divide(
        pd.Series(float(scan_config.assumed_position_usd), index=df.index),
        df["avg_dollar_volume_20d"],
    )
    df["estimated_slippage_bps"] = 200.0 * np.sqrt(
        pd.to_numeric(df["adv_participation"], errors="coerce").clip(lower=0)
    )
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

    peer_ps = (
        df.loc[np.isfinite(df["ps"]) & (df["ps"] > 0)]
        .groupby("sic", dropna=True)["ps"]
        .median()
        .rename("peer_median_ps")
    )
    peer_pe = (
        df.loc[np.isfinite(df["pe"]) & (df["pe"] > 0)]
        .groupby("sic", dropna=True)["pe"]
        .median()
        .rename("peer_median_pe")
    )
    df = df.merge(peer_ps, left_on="sic", right_index=True, how="left")
    df = df.merge(peer_pe, left_on="sic", right_index=True, how="left")
    df["ps_discount"] = 1 - safe_divide(df["ps"], df["peer_median_ps"])
    df["pe_discount"] = 1 - safe_divide(df["pe"], df["peer_median_pe"])
    df["ps_percentile_in_sic"] = (
        df.groupby("sic", dropna=False)["ps"].rank(pct=True, method="average")
    )
    df["pe_percentile_in_sic"] = (
        df.groupby("sic", dropna=False)["pe"].rank(pct=True, method="average")
    )
    df["watchlist_bucket"] = df["watchlist_bucket"].fillna("").astype(str)
    df["watchlist_etfs"] = df["watchlist_etfs"].fillna("").astype(str)
    return df


def build_signal_events_historical_replay(
    scan_config: ScanConfig,
    client: AlpacaClient,
    sec: SecClient,
    cfg: BacktestConfig,
    scenario: str,
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
    if snapshots:
        watchlist_allowlist = set()
        for _, mapping, _ in snapshots:
            watchlist_allowlist.update(mapping.keys())
    else:
        watchlist_allowlist = set(latest_watchlist_map.keys())
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
        prefetch_universe = prefetch_universe.head(prefetch_n)

    symbols = prefetch_universe["symbol"].dropna().astype(str).tolist()
    benchmark_etfs = normalize_symbol_list([str(x).upper() for x in (scan_config.ai_link_benchmark_etfs or [])])
    bars_symbols = normalize_symbol_list(symbols + benchmark_etfs)

    bt_log(
        f"universe symbols: {len(symbols)}",
        scope=f"replay:{scenario}",
        started_at_monotonic=replay_start,
    )
    bars_start = (start_dt - timedelta(days=max(420, scan_config.price_lookback_days))).isoformat()
    bar_db = build_bar_db(client, bars_symbols, bars_start, scan_config.chunk_size)
    bt_log(
        f"symbols with bars: {len(bar_db)}",
        scope=f"replay:{scenario}",
        started_at_monotonic=replay_start,
    )

    universe = prefetch_universe[prefetch_universe["symbol"].isin(set(bar_db.keys()))].copy()
    universe = universe.dropna(subset=["cik"]).copy()
    if cfg.replay_max_symbols and cfg.replay_max_symbols > 0:
        universe = universe.head(cfg.replay_max_symbols).copy()
    fundamentals = build_fundamental_pti_db(universe, sec, max_workers=scan_config.max_workers)
    bt_log(
        f"fundamentals loaded: {len(fundamentals)}",
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

    dates = build_rebalance_dates(start_dt, end_dt, cfg.rebalance_frequency)
    bt_log(
        f"rebalance dates: {len(dates)}",
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
        watchlist_by_symbol, watchlist_source = resolve_watchlist_asof(
            asof=asof,
            snapshots=snapshots,
            latest_map=latest_watchlist_map,
            allow_latest_fallback=cfg.allow_latest_watchlist_fallback,
        )
        watchlist_source_counts[watchlist_source] = watchlist_source_counts.get(watchlist_source, 0) + 1
        if not watchlist_by_symbol:
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
        )
        if df.empty:
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
                    "channel_counts": json.dumps(signal_diag.get("channel_counts", {}), sort_keys=True),
                    "channel_symbols": json.dumps(signal_diag.get("channel_symbols", {}), sort_keys=True),
                    "filter_diagnostics": json.dumps(signal_diag.get("channels", {}), sort_keys=True),
                    "source_csv": "",
                    "watchlist_source": watchlist_source,
                }
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
                "source_csv",
                "watchlist_source",
            ]
        )
    return pd.DataFrame(rows)


def build_price_frame_map(bars_map: dict[str, list[dict[str, Any]]]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol, rows in bars_map.items():
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


def next_trading_index(index: pd.DatetimeIndex, signal_dt: pd.Timestamp) -> int | None:
    pos = index.searchsorted(signal_dt, side="right")
    if pos >= len(index):
        return None
    return int(pos)


def forward_return(
    price_frame: pd.DataFrame,
    signal_date: str,
    horizon: int,
    roundtrip_cost: float,
    entry_price_mode: str = "next_open",
    exit_price_mode: str = "close",
    global_end_date: pd.Timestamp | None = None,
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> float | None:
    signal_dt = pd.Timestamp(signal_date, tz="UTC")
    if price_frame is None or price_frame.empty:
        return None
    idx = next_trading_index(price_frame.index, signal_dt)
    if idx is None:
        return None
    hold = max(1, int(horizon))
    exit_idx = idx + hold - 1
    if exit_idx >= len(price_frame):
        if global_end_date is not None and delist_return_assumption is not None:
            last_dt = pd.Timestamp(price_frame.index[-1]).tz_convert("UTC")
            if last_dt < (global_end_date - pd.Timedelta(days=delist_detection_buffer_days)):
                # Assume an adverse delisting return when a symbol disappears
                # well before the backtest window end.
                return float(delist_return_assumption) - roundtrip_cost
        return None

    entry_col = "open" if str(entry_price_mode).strip().lower() == "next_open" else "close"
    exit_col = "open" if str(exit_price_mode).strip().lower() == "open" else "close"
    if entry_col not in price_frame.columns or exit_col not in price_frame.columns:
        return None
    entry = float(price_frame.iloc[idx][entry_col])
    exit_px = float(price_frame.iloc[exit_idx][exit_col])
    if entry <= 0:
        return None
    return (exit_px / entry) - 1.0 - roundtrip_cost


def event_backtest(
    signals: pd.DataFrame,
    prices_by_symbol: dict[str, pd.DataFrame],
    horizons: list[int],
    roundtrip_cost: float,
    benchmark_symbols: list[str],
    entry_price_mode: str = "next_open",
    exit_price_mode: str = "close",
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_rows: list[dict[str, Any]] = []
    benchmark_rows: list[dict[str, Any]] = []
    global_end_date: pd.Timestamp | None = None
    if prices_by_symbol:
        all_last = [pd.Timestamp(s.index.max()).tz_convert("UTC") for s in prices_by_symbol.values() if not s.empty]
        if all_last:
            global_end_date = max(all_last)

    for row in signals.itertuples(index=False):
        symbols: list[str] = list(row.symbols) if isinstance(row.symbols, list) else []
        for horizon in horizons:
            returns: list[float] = []
            priced = 0
            for sym in symbols:
                price_frame = prices_by_symbol.get(sym.upper())
                if price_frame is None:
                    continue
                ret = forward_return(
                    price_frame,
                    row.signal_date,
                    horizon,
                    roundtrip_cost,
                    entry_price_mode=entry_price_mode,
                    exit_price_mode=exit_price_mode,
                    global_end_date=global_end_date,
                    delist_return_assumption=delist_return_assumption,
                    delist_detection_buffer_days=delist_detection_buffer_days,
                )
                if ret is None or not np.isfinite(ret):
                    continue
                priced += 1
                returns.append(float(ret))
            portfolio_return = float(np.mean(returns)) if returns else np.nan
            if not symbols:
                event_status = "no_signal"
            elif priced <= 0:
                event_status = "unpriced"
            elif priced < len(symbols):
                event_status = "partial_valid"
            else:
                event_status = "valid"
            event_rows.append(
                {
                    "scenario": row.scenario,
                    "run_stem": row.run_stem,
                    "run_ts_utc": row.run_ts_utc,
                    "signal_date": row.signal_date,
                    "list_type": row.list_type,
                    "horizon_days": horizon,
                    "n_selected": int(row.n_selected),
                    "n_priced": int(priced),
                    "event_status": event_status,
                    "portfolio_return": portfolio_return,
                }
            )
            for bench in benchmark_symbols:
                price_frame = prices_by_symbol.get(bench.upper())
                ret = None
                if price_frame is not None:
                    ret = forward_return(
                        price_frame,
                        row.signal_date,
                        horizon,
                        0.0,
                        entry_price_mode=entry_price_mode,
                        exit_price_mode=exit_price_mode,
                        global_end_date=global_end_date,
                        delist_return_assumption=None,
                        delist_detection_buffer_days=delist_detection_buffer_days,
                    )
                benchmark_rows.append(
                    {
                        "scenario": row.scenario,
                        "run_stem": row.run_stem,
                        "signal_date": row.signal_date,
                        "horizon_days": horizon,
                        "benchmark": bench.upper(),
                        "benchmark_return": ret,
                    }
                )

    return pd.DataFrame(event_rows), pd.DataFrame(benchmark_rows)


def infer_segment_label(signal_date: str) -> str:
    dt = pd.Timestamp(signal_date)
    y = int(dt.year)
    current_year = datetime.now(timezone.utc).year
    if y in (2023, 2024, 2025):
        return str(y)
    if y == current_year:
        return f"{y}YTD"
    return str(y)


def summarize_backtest(events: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "scenario",
                "list_type",
                "horizon_days",
                "n_events_total",
                "n_events_valid",
                "avg_return",
                "median_return",
                "win_rate",
                "std_return",
                "cumulative_return",
                "avg_n_priced",
                "avg_n_selected",
                "n_no_signal_events",
                "n_unpriced_events",
                "n_partial_valid_events",
                "avg_excess_vs_QQQ",
            ]
        )
    bench_qqq = (
        benchmarks[benchmarks["benchmark"] == "QQQ"][
            ["scenario", "run_stem", "horizon_days", "benchmark_return"]
        ]
        .drop_duplicates(subset=["scenario", "run_stem", "horizon_days"], keep="last")
        .rename(columns={"benchmark_return": "qqq_return"})
    )
    merged = events.merge(bench_qqq, on=["scenario", "run_stem", "horizon_days"], how="left")
    merged["excess_vs_qqq"] = merged["portfolio_return"] - merged["qqq_return"]

    rows: list[dict[str, Any]] = []
    for keys, part in merged.groupby(["scenario", "list_type", "horizon_days"], dropna=False):
        scenario, list_type, horizon = keys
        p = part["portfolio_return"].dropna()
        total_events = int(len(part))
        valid_events = int(len(p))
        if p.empty:
            rows.append(
                {
                    "scenario": scenario,
                    "list_type": list_type,
                    "horizon_days": int(horizon),
                    "n_events_total": total_events,
                    "n_events_valid": valid_events,
                    "avg_return": np.nan,
                    "median_return": np.nan,
                    "win_rate": np.nan,
                    "std_return": np.nan,
                    "cumulative_return": np.nan,
                    "avg_n_priced": float(part["n_priced"].mean()) if not part.empty else np.nan,
                    "avg_n_selected": float(part["n_selected"].mean()) if not part.empty else np.nan,
                    "n_no_signal_events": int((part.get("event_status") == "no_signal").sum())
                    if "event_status" in part
                    else 0,
                    "n_unpriced_events": int((part.get("event_status") == "unpriced").sum())
                    if "event_status" in part
                    else 0,
                    "n_partial_valid_events": int((part.get("event_status") == "partial_valid").sum())
                    if "event_status" in part
                    else 0,
                    "avg_excess_vs_QQQ": np.nan,
                }
            )
            continue
        rows.append(
            {
                "scenario": scenario,
                "list_type": list_type,
                "horizon_days": int(horizon),
                "n_events_total": total_events,
                "n_events_valid": valid_events,
                "avg_return": float(p.mean()),
                "median_return": float(p.median()),
                "win_rate": float((p > 0).mean()),
                "std_return": float(p.std(ddof=0)),
                "cumulative_return": float((1.0 + p).prod() - 1.0),
                "avg_n_priced": float(part["n_priced"].mean()),
                "avg_n_selected": float(part["n_selected"].mean()),
                "n_no_signal_events": int((part.get("event_status") == "no_signal").sum())
                if "event_status" in part
                else 0,
                "n_unpriced_events": int((part.get("event_status") == "unpriced").sum())
                if "event_status" in part
                else 0,
                "n_partial_valid_events": int((part.get("event_status") == "partial_valid").sum())
                if "event_status" in part
                else 0,
                "avg_excess_vs_QQQ": float(part["excess_vs_qqq"].dropna().mean())
                if part["excess_vs_qqq"].notna().any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["scenario", "list_type", "horizon_days"]).reset_index(drop=True)


def summarize_backtest_by_segment(events: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "scenario",
                "segment",
                "list_type",
                "horizon_days",
                "n_events_total",
                "n_events_valid",
                "n_no_signal_events",
                "n_unpriced_events",
                "avg_return",
                "win_rate",
                "avg_excess_vs_QQQ",
            ]
        )
    working = events.copy()
    working["segment"] = working["signal_date"].map(infer_segment_label)

    bench_qqq = (
        benchmarks[benchmarks["benchmark"] == "QQQ"][
            ["scenario", "run_stem", "horizon_days", "benchmark_return"]
        ]
        .drop_duplicates(subset=["scenario", "run_stem", "horizon_days"], keep="last")
        .rename(columns={"benchmark_return": "qqq_return"})
    )
    merged = working.merge(bench_qqq, on=["scenario", "run_stem", "horizon_days"], how="left")
    merged["excess_vs_qqq"] = merged["portfolio_return"] - merged["qqq_return"]

    rows: list[dict[str, Any]] = []
    for keys, part in merged.groupby(
        ["scenario", "segment", "list_type", "horizon_days"],
        dropna=False,
    ):
        scenario, segment, list_type, horizon = keys
        p = part["portfolio_return"].dropna()
        rows.append(
            {
                "scenario": scenario,
                "segment": segment,
                "list_type": list_type,
                "horizon_days": int(horizon),
                "n_events_total": int(len(part)),
                "n_events_valid": int(len(p)),
                "n_no_signal_events": int((part.get("event_status") == "no_signal").sum())
                if "event_status" in part
                else 0,
                "n_unpriced_events": int((part.get("event_status") == "unpriced").sum())
                if "event_status" in part
                else 0,
                "avg_return": float(p.mean()) if not p.empty else np.nan,
                "win_rate": float((p > 0).mean()) if not p.empty else np.nan,
                "avg_excess_vs_QQQ": float(part["excess_vs_qqq"].dropna().mean())
                if part["excess_vs_qqq"].notna().any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["scenario", "segment", "list_type", "horizon_days"]
    ).reset_index(drop=True)


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_signal_diagnostics(signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    diagnostic_rows: list[dict[str, Any]] = []
    channel_rows: list[dict[str, Any]] = []
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()

    for row in signals.itertuples(index=False):
        base = {
            "scenario": getattr(row, "scenario", ""),
            "run_stem": getattr(row, "run_stem", ""),
            "signal_date": getattr(row, "signal_date", ""),
            "list_type": getattr(row, "list_type", ""),
            "watchlist_source": getattr(row, "watchlist_source", ""),
        }
        channel_counts = parse_json_object(getattr(row, "channel_counts", ""))
        channel_symbols = parse_json_object(getattr(row, "channel_symbols", ""))
        filter_diagnostics = parse_json_object(getattr(row, "filter_diagnostics", ""))
        for channel, payload in filter_diagnostics.items():
            if not isinstance(payload, dict):
                continue
            first_fail = payload.get("first_fail") if isinstance(payload.get("first_fail"), dict) else {}
            channel_rows.append(
                {
                    **base,
                    "channel": channel,
                    "n_input": int(payload.get("n_input", 0) or 0),
                    "n_filtered": int(payload.get("n_filtered", 0) or 0),
                    "n_ranked": int(payload.get("n_ranked", 0) or 0),
                    "n_selected_channel": int(channel_counts.get(channel, 0) or 0),
                    "selected_symbols": ",".join(str(x) for x in channel_symbols.get(channel, []))
                    if isinstance(channel_symbols.get(channel), list)
                    else "",
                    "top_first_fail": str(first_fail.get("top_reason", "")),
                    "top_first_fail_pct": float(first_fail.get("top_pct", 0.0) or 0.0),
                }
            )
            layer_summary = payload.get("layer_summary")
            if not isinstance(layer_summary, dict):
                continue
            for layer, layer_payload in layer_summary.items():
                if not isinstance(layer_payload, dict):
                    continue
                diagnostic_rows.append(
                    {
                        **base,
                        "channel": channel,
                        "layer": layer,
                        "before": int(layer_payload.get("before", 0) or 0),
                        "remaining": int(layer_payload.get("remaining", 0) or 0),
                        "removed": int(layer_payload.get("removed", 0) or 0),
                        "pass_rate": float(layer_payload.get("pass_rate", 0.0) or 0.0),
                    }
                )

    diagnostics = pd.DataFrame(diagnostic_rows)
    channel_summary = pd.DataFrame(channel_rows)
    return diagnostics, channel_summary


def build_markdown_report(
    cfg: BacktestConfig,
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
    lines.append(f"- list types: {', '.join(cfg.list_types or VALID_LIST_TYPES)}")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backtest AI lists via existing scans or historical replay."
    )
    p.add_argument("--mode", default="historical_replay", choices=["existing_runs", "historical_replay"])
    p.add_argument("--scan-config", default="configs/config.balanced.json")
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
    p.add_argument("--use-historical-watchlist", action="store_true", default=True)
    p.add_argument("--no-historical-watchlist", action="store_true")
    p.add_argument("--allow-latest-watchlist-fallback", action="store_true", default=False)
    p.add_argument("--no-latest-watchlist-fallback", action="store_true")
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
    return p


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
    scenarios = ["base", "loose", "strict"] if cfg.enable_perturbation else ["base"]
    frames: list[pd.DataFrame] = []
    for scenario in scenarios:
        scenario_cfg = perturb_scan_config(scan_cfg, scenario)
        scenario_cfg.max_symbols = cfg.replay_max_symbols
        df = build_signal_events_historical_replay(
            scan_config=scenario_cfg,
            client=client,
            sec=sec,
            cfg=cfg,
            scenario=scenario,
        )
        frames.append(df)
    signals = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return signals, monitor


def run_backtest(cfg: BacktestConfig) -> dict[str, Any]:
    backtest_start = time.monotonic()
    scan_cfg = load_config(cfg.scan_config_path)
    events_path, summary_path, benchmarks_path, segments_path, report_path = resolve_output_paths(
        cfg.output_prefix,
        Path(cfg.outputs_dir),
        cfg.mode,
    )
    signal_diagnostics_path = events_path.with_name(f"{events_path.stem}_signal_diagnostics.csv")
    signal_channel_summary_path = events_path.with_name(f"{events_path.stem}_signal_channel_summary.csv")

    bt_log("building signals...", started_at_monotonic=backtest_start)
    signals, build_monitor = build_signals(cfg, scan_cfg)
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
    price_map = build_price_frame_map(bars_map)

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
        allow_latest_watchlist_fallback=allow_latest_watchlist_fallback,
        disclosure_lookback_days=args.disclosure_lookback_days,
        theme_source=args.theme_source,
        allow_lookahead_theme_source=bool(args.allow_lookahead_theme_source),
        enable_perturbation=perturb,
        historical_news_lookback_days=args.historical_news_lookback_days,
        historical_news_limit_per_symbol=args.historical_news_limit_per_symbol,
        delist_return_assumption=args.delist_return_assumption,
        delist_detection_buffer_days=args.delist_detection_buffer_days,
    )
    run_backtest(cfg)


if __name__ == "__main__":
    main()
