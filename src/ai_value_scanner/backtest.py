from __future__ import annotations

import argparse
import bisect
import copy
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ai_value_scanner.scanner import (
    ANNUAL_FORMS,
    NET_INCOME_TAGS,
    REVENUE_TAGS,
    SHARES_TAGS,
    AlpacaClient,
    NetworkMonitor,
    RequestRateLimiter,
    ScanConfig,
    SecClient,
    apply_filters_with_diagnostics,
    build_filter_steps,
    build_industry_trend_steps,
    build_momentum_steps,
    build_session,
    compile_keyword_patterns,
    load_config,
    resolve_channel_profile,
    safe_divide,
    score_and_rank,
    theme_score_from_news,
)


LIST_SUFFIX = {
    "low_value": "_ranked",
    "industry_trend": "_ranked_industry_trend",
    "momentum": "_ranked_momentum",
}
VALID_LIST_TYPES = sorted(LIST_SUFFIX.keys())
STANDARD_EQUITY_SYMBOL_RE = r"^[A-Z]{1,5}(\.[A-Z])?$"
STANDARD_EQUITY_SYMBOL_PATTERN = re.compile(STANDARD_EQUITY_SYMBOL_RE)


@dataclass
class BacktestConfig:
    mode: str = "historical_replay"
    scan_config_path: str = "config.production.json"
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


@dataclass
class FundamentalPointInTime:
    sic: str | None
    sic_description: str | None
    revenue_series: list[tuple[pd.Timestamp, float]]
    net_income_series: list[tuple[pd.Timestamp, float]]
    shares_series: list[tuple[pd.Timestamp, float]]


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

    if "composite_score" in df.columns:
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
) -> pd.DataFrame:
    assets = client.get_assets(status=asset_status)
    df_assets = pd.DataFrame(assets)
    if df_assets.empty:
        return pd.DataFrame(columns=["symbol", "name", "exchange", "cik", "company_name"])
    if "symbol" not in df_assets.columns:
        return pd.DataFrame(columns=["symbol", "name", "exchange", "cik", "company_name"])

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
    return merged


def extract_metric_series(
    companyfacts: dict[str, Any],
    tags: list[str],
    unit: str,
) -> list[tuple[pd.Timestamp, float]]:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    by_end: dict[pd.Timestamp, float] = {}
    for tag in tags:
        tag_obj = facts.get(tag, {})
        units = tag_obj.get("units", {})
        entries = units.get(unit, [])
        for item in entries:
            if item.get("form") not in ANNUAL_FORMS:
                continue
            filed = item.get("filed")
            end = item.get("end")
            val = item.get("val")
            visible_date = filed or end
            if visible_date is None or val is None:
                continue
            try:
                dt = pd.Timestamp(visible_date, tz="UTC").normalize()
                fv = float(val)
            except Exception:
                continue
            if not np.isfinite(fv):
                continue
            if dt not in by_end:
                by_end[dt] = fv
            else:
                by_end[dt] = fv
    return sorted(by_end.items(), key=lambda x: x[0])


def latest_asof(series: list[tuple[pd.Timestamp, float]], asof: pd.Timestamp) -> float | None:
    if not series:
        return None
    dates = [x[0] for x in series]
    idx = bisect.bisect_right(dates, asof) - 1
    if idx < 0:
        return None
    return float(series[idx][1])


def load_symbol_fundamental_pti(sec: SecClient, symbol: str, cik: str) -> tuple[str, FundamentalPointInTime]:
    submissions = sec.get_submissions(cik)
    companyfacts = sec.get_companyfacts(cik)
    f = FundamentalPointInTime(
        sic=str(submissions.get("sic")) if submissions.get("sic") is not None else None,
        sic_description=submissions.get("sicDescription"),
        revenue_series=extract_metric_series(companyfacts, REVENUE_TAGS, "USD"),
        net_income_series=extract_metric_series(companyfacts, NET_INCOME_TAGS, "USD"),
        shares_series=extract_metric_series(companyfacts, SHARES_TAGS, "shares"),
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
                )
            done += 1
            if total > 0:
                pct = int((done * 100) / total)
                if pct >= last_pct + 10 or done == total:
                    print(f"  [progress] PIT fundamentals: {done}/{total} ({pct}%)")
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
            c = row.get("c")
            h = row.get("h")
            l = row.get("l")
            v = row.get("v")
            if t is None or c is None:
                continue
            try:
                dt = pd.Timestamp(t, tz="UTC").normalize()
                close = float(c)
                high = float(h) if h is not None else close
                low = float(l) if l is not None else close
                vol = float(v) if v is not None else 0.0
            except Exception:
                continue
            table.append({"date": dt, "close": close, "high": high, "low": low, "volume": vol})
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
        "return_20d": round(return_20d, 6) if return_20d is not None else None,
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
            ai = float(getattr(row, "ai_score", 0.0) or 0.0)
            en = float(getattr(row, "enabler_score", 0.0) or 0.0)
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
    ai = theme_score_from_news(news, scan_config.ai_keywords)
    en = theme_score_from_news(news, scan_config.enabler_keywords)
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
    start_dt = asof - timedelta(days=cfg.historical_news_lookback_days)
    start_iso = start_dt.isoformat()
    end_iso = asof.isoformat()
    out: dict[str, tuple[float, float]] = {}
    total = len(symbols)
    done = 0
    last_pct = -1
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
                    print(f"    [progress] historical news: {done}/{total} ({pct}%)")
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
        ai = theme_score_from_metadata_text(text, scan_config.ai_keywords)
        en = theme_score_from_metadata_text(text, scan_config.enabler_keywords)
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
    channel_profiles = scan_config.channel_profiles or {"core_ai": {}}
    ranked_frames: list[pd.DataFrame] = []
    for channel_name, channel_profile in channel_profiles.items():
        if include_channels and channel_name not in include_channels:
            continue
        if list_type == "low_value":
            cp = resolve_channel_profile(scan_config, channel_name, channel_profile)
            steps = build_filter_steps(scan_config, channel_name, channel_profile)
            filtered, _ = apply_filters_with_diagnostics(df, steps)
            ranked = score_and_rank(filtered, cp["score_weights"])
        elif list_type == "industry_trend":
            steps, weights = build_industry_trend_steps(scan_config, channel_name, channel_profile)
            filtered, _ = apply_filters_with_diagnostics(df, steps)
            ranked = score_and_rank(filtered, weights)
        else:
            steps, weights = build_momentum_steps(scan_config, channel_name, channel_profile)
            filtered, _ = apply_filters_with_diagnostics(df, steps)
            ranked = score_and_rank(filtered, weights)
        if ranked.empty:
            continue
        ranked = ranked.copy()
        ranked["channel"] = channel_name
        ranked_frames.append(ranked)

    if not ranked_frames:
        return []

    if per_channel_top_n:
        picks: list[str] = []
        for part in ranked_frames:
            picks.extend(part.head(top_n)["symbol"].dropna().astype(str).tolist())
    else:
        merged = pd.concat(ranked_frames, ignore_index=True)
        merged = merged.sort_values("composite_score", ascending=False)
        picks = merged.head(top_n)["symbol"].dropna().astype(str).tolist()
    return normalize_symbol_list(picks)


def build_cross_section_asof(
    asof: pd.Timestamp,
    universe: pd.DataFrame,
    bar_db: dict[str, pd.DataFrame],
    fundamentals: dict[str, FundamentalPointInTime],
    theme_scores: dict[str, tuple[float, float]],
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
        revenue = latest_asof(f.revenue_series, asof)
        net_income = latest_asof(f.net_income_series, asof)
        shares = latest_asof(f.shares_series, asof)
        ai, en = theme_scores.get(symbol, (0.0, 0.0))

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
                "return_20d": price_feat["return_20d"],
                "volatility_60d": price_feat["volatility_60d"],
                "shares_outstanding": shares,
                "revenue": revenue,
                "net_income": net_income,
                "ai_score": ai,
                "enabler_score": en,
                "news_count": 0,
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in [
        "price",
        "dollar_volume",
        "shares_outstanding",
        "revenue",
        "net_income",
        "ai_score",
        "enabler_score",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["market_cap"] = df["price"] * df["shares_outstanding"]
    df["ps"] = safe_divide(df["market_cap"], df["revenue"])
    df["pe"] = safe_divide(df["market_cap"], df["net_income"])

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
    return df


def build_signal_events_historical_replay(
    scan_config: ScanConfig,
    client: AlpacaClient,
    sec: SecClient,
    cfg: BacktestConfig,
    scenario: str,
) -> pd.DataFrame:
    start_dt = parse_date_utc(cfg.start_date)
    end_dt = parse_date_utc(cfg.end_date)
    if start_dt is None:
        start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
    if end_dt is None:
        end_dt = datetime.now(timezone.utc)
    if end_dt <= start_dt:
        raise ValueError("end_date must be greater than start_date.")

    base_universe = build_universe_for_replay(
        client=client,
        sec=sec,
        scan_config=scan_config,
        asset_status=cfg.replay_asset_status,
    )
    base_universe = base_universe.dropna(subset=["symbol"]).copy()
    base_universe["symbol"] = base_universe["symbol"].astype(str).str.upper()
    base_universe = base_universe.reset_index(drop=True)

    prefetch_universe = base_universe.copy()
    if cfg.replay_max_symbols and cfg.replay_max_symbols > 0:
        if cfg.replay_asset_status == "all":
            prefetch_n = min(len(prefetch_universe), max(cfg.replay_max_symbols * 25, cfg.replay_max_symbols))
        else:
            prefetch_n = min(len(prefetch_universe), cfg.replay_max_symbols)
        prefetch_universe = prefetch_universe.head(prefetch_n)

    symbols = prefetch_universe["symbol"].dropna().astype(str).tolist()

    print(f"[replay:{scenario}] universe symbols: {len(symbols)}")
    bars_start = (start_dt - timedelta(days=max(420, scan_config.price_lookback_days))).isoformat()
    bar_db = build_bar_db(client, symbols, bars_start, scan_config.chunk_size)
    print(f"[replay:{scenario}] symbols with bars: {len(bar_db)}")

    universe = prefetch_universe[prefetch_universe["symbol"].isin(set(bar_db.keys()))].copy()
    universe = universe.dropna(subset=["cik"]).copy()
    if cfg.replay_max_symbols and cfg.replay_max_symbols > 0:
        universe = universe.head(cfg.replay_max_symbols).copy()
    fundamentals = build_fundamental_pti_db(universe, sec, max_workers=scan_config.max_workers)
    print(f"[replay:{scenario}] fundamentals loaded: {len(fundamentals)}")

    theme_scores_static: dict[str, tuple[float, float]] | None = None
    news_cache_dir = Path(scan_config.cache_dir) / "backtest_news"
    universe_symbols = universe["symbol"].dropna().astype(str).tolist()
    if cfg.theme_source == "latest_scan":
        theme_scores_static = load_latest_theme_scores(Path(cfg.outputs_dir))
        print(f"[replay:{scenario}] latest-scan theme map size: {len(theme_scores_static)}")
    elif cfg.theme_source == "rules_proxy":
        theme_scores_static = build_theme_scores_rules_proxy(
            universe=universe,
            fundamentals=fundamentals,
            scan_config=scan_config,
        )
        print(f"[replay:{scenario}] rules-proxy theme map size: {len(theme_scores_static)}")
    elif cfg.theme_source == "historical_news":
        print(
            f"[replay:{scenario}] historical-news scoring enabled "
            f"(lookback={cfg.historical_news_lookback_days}d, limit={cfg.historical_news_limit_per_symbol})"
        )
    else:
        theme_scores_static = {}

    dates = build_rebalance_dates(start_dt, end_dt, cfg.rebalance_frequency)
    print(f"[replay:{scenario}] rebalance dates: {len(dates)}")

    rows: list[dict[str, Any]] = []
    for i, asof in enumerate(dates, start=1):
        if i % 10 == 0 or i == len(dates):
            print(f"  [progress] replay dates: {i}/{len(dates)}")
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
        df = build_cross_section_asof(
            asof=asof,
            universe=universe,
            bar_db=bar_db,
            fundamentals=fundamentals,
            theme_scores=theme_scores,
            scan_config=scan_config,
        )
        if df.empty:
            continue
        for list_type in (cfg.list_types or VALID_LIST_TYPES):
            symbols_selected = rank_and_pick_symbols(
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
                    "source_csv": "",
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
            ]
        )
    return pd.DataFrame(rows)


def build_close_series(bars_map: dict[str, list[dict[str, Any]]]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for symbol, rows in bars_map.items():
        dates: list[pd.Timestamp] = []
        closes: list[float] = []
        for row in rows:
            t = row.get("t")
            c = row.get("c")
            if t is None or c is None:
                continue
            dt = pd.to_datetime(t, utc=True).normalize()
            try:
                close = float(c)
            except (TypeError, ValueError):
                continue
            dates.append(dt)
            closes.append(close)
        if not dates:
            continue
        s = pd.Series(closes, index=pd.DatetimeIndex(dates), dtype="float64")
        s = s[~s.index.duplicated(keep="last")].sort_index()
        out[symbol.upper()] = s
    return out


def next_trading_index(index: pd.DatetimeIndex, signal_dt: pd.Timestamp) -> int | None:
    pos = index.searchsorted(signal_dt, side="right")
    if pos >= len(index):
        return None
    return int(pos)


def forward_return(
    close_series: pd.Series,
    signal_date: str,
    horizon: int,
    roundtrip_cost: float,
    global_end_date: pd.Timestamp | None = None,
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> float | None:
    signal_dt = pd.Timestamp(signal_date, tz="UTC")
    idx = next_trading_index(close_series.index, signal_dt)
    if idx is None:
        return None
    exit_idx = idx + horizon
    if exit_idx >= len(close_series):
        if global_end_date is not None and delist_return_assumption is not None:
            last_dt = pd.Timestamp(close_series.index[-1]).tz_convert("UTC")
            if last_dt < (global_end_date - pd.Timedelta(days=delist_detection_buffer_days)):
                # Assume an adverse delisting return when a symbol disappears
                # well before the backtest window end.
                return float(delist_return_assumption) - roundtrip_cost
        return None
    entry = float(close_series.iloc[idx])
    exit_px = float(close_series.iloc[exit_idx])
    if entry <= 0:
        return None
    return (exit_px / entry) - 1.0 - roundtrip_cost


def event_backtest(
    signals: pd.DataFrame,
    close_by_symbol: dict[str, pd.Series],
    horizons: list[int],
    roundtrip_cost: float,
    benchmark_symbols: list[str],
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_rows: list[dict[str, Any]] = []
    benchmark_rows: list[dict[str, Any]] = []
    global_end_date: pd.Timestamp | None = None
    if close_by_symbol:
        all_last = [pd.Timestamp(s.index.max()).tz_convert("UTC") for s in close_by_symbol.values() if not s.empty]
        if all_last:
            global_end_date = max(all_last)

    for row in signals.itertuples(index=False):
        symbols: list[str] = list(row.symbols) if isinstance(row.symbols, list) else []
        for horizon in horizons:
            returns: list[float] = []
            priced = 0
            for sym in symbols:
                series = close_by_symbol.get(sym.upper())
                if series is None:
                    continue
                ret = forward_return(
                    series,
                    row.signal_date,
                    horizon,
                    roundtrip_cost,
                    global_end_date=global_end_date,
                    delist_return_assumption=delist_return_assumption,
                    delist_detection_buffer_days=delist_detection_buffer_days,
                )
                if ret is None or not np.isfinite(ret):
                    continue
                priced += 1
                returns.append(float(ret))
            portfolio_return = float(np.mean(returns)) if returns else np.nan
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
                    "portfolio_return": portfolio_return,
                }
            )
            for bench in benchmark_symbols:
                series = close_by_symbol.get(bench.upper())
                ret = None
                if series is not None:
                    ret = forward_return(
                        series,
                        row.signal_date,
                        horizon,
                        0.0,
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


def build_markdown_report(
    cfg: BacktestConfig,
    signals: pd.DataFrame,
    summary: pd.DataFrame,
    segment_summary: pd.DataFrame,
    events_path: Path,
    summary_path: Path,
    benchmarks_path: Path,
    segment_path: Path,
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
    if cfg.mode == "historical_replay":
        lines.append(f"- rebalance_frequency: {cfg.rebalance_frequency}")
        lines.append(f"- replay_max_symbols: {cfg.replay_max_symbols}")
        lines.append(f"- replay_asset_status: {cfg.replay_asset_status}")
        lines.append(f"- theme_source: {cfg.theme_source}")
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
                f"win={win} | excess_vs_QQQ={ex}"
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
                f"win={win} | excess_vs_QQQ={ex}"
            )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- events: {events_path}")
    lines.append(f"- summary: {summary_path}")
    lines.append(f"- benchmarks: {benchmarks_path}")
    lines.append(f"- segment summary: {segment_path}")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `historical_replay` is an approximation: universe uses currently tradable symbols.")
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
    p.add_argument("--scan-config", default="config.production.json")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--output-prefix", default=None)
    p.add_argument("--list-types", default="low_value,industry_trend,momentum")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--per-channel-top-n", action="store_true", default=True)
    p.add_argument("--no-per-channel-top-n", action="store_true")
    p.add_argument("--include-channels", default="core_ai,ai_enabler")
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument("--max-runs", type=int, default=None)
    p.add_argument("--start-date", default="2023-01-01", help="YYYY-MM-DD")
    p.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    p.add_argument("--benchmark-symbols", default="QQQ,SOXX,XLI,XLU")
    p.add_argument("--trading-cost-bps", type=float, default=15.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rebalance-frequency", default="weekly", choices=["weekly", "monthly"])
    p.add_argument("--replay-max-symbols", type=int, default=800)
    p.add_argument("--replay-asset-status", default="all", choices=["all", "active", "inactive"])
    p.add_argument(
        "--theme-source",
        default="rules_proxy",
        choices=["rules_proxy", "historical_news", "latest_scan", "zero"],
    )
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
    scan_cfg = load_config(cfg.scan_config_path)
    events_path, summary_path, benchmarks_path, segments_path, report_path = resolve_output_paths(
        cfg.output_prefix,
        Path(cfg.outputs_dir),
        cfg.mode,
    )

    signals, build_monitor = build_signals(cfg, scan_cfg)
    if signals.empty:
        raise ValueError("No signals generated for selected mode/range.")
    print(f"[backtest] mode: {cfg.mode}")
    print(f"[backtest] signal rows: {len(signals)}")

    signals.to_csv(events_path.with_name(f"{events_path.stem}_signals.csv"), index=False)

    if cfg.dry_run:
        empty = pd.DataFrame()
        empty.to_csv(events_path, index=False)
        empty.to_csv(summary_path, index=False)
        empty.to_csv(benchmarks_path, index=False)
        empty.to_csv(segments_path, index=False)
        md = build_markdown_report(
            cfg=cfg,
            signals=signals,
            summary=empty,
            segment_summary=empty,
            events_path=events_path,
            summary_path=summary_path,
            benchmarks_path=benchmarks_path,
            segment_path=segments_path,
        )
        report_path.write_text(md)
        print(f"[backtest] dry-run artifacts written: {report_path}")
        return {
            "events_path": events_path,
            "summary_path": summary_path,
            "benchmarks_path": benchmarks_path,
            "segments_path": segments_path,
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
    print(f"[backtest] symbols for pricing: {len(symbols)}")

    client, run_monitor = load_alpaca_client(scan_cfg)
    start_dt = parse_date_utc(cfg.start_date) or datetime(2023, 1, 1, tzinfo=timezone.utc)
    bars_start = (start_dt - timedelta(days=420)).isoformat()
    bars_map = client.get_daily_bars(symbols, bars_start, scan_cfg.chunk_size)
    close_map = build_close_series(bars_map)

    roundtrip_cost = (2.0 * cfg.trading_cost_bps) / 10000.0
    events, benchmarks = event_backtest(
        signals=signals,
        close_by_symbol=close_map,
        horizons=cfg.horizons or [20, 60, 120],
        roundtrip_cost=roundtrip_cost,
        benchmark_symbols=benchmark_symbols,
        delist_return_assumption=cfg.delist_return_assumption,
        delist_detection_buffer_days=cfg.delist_detection_buffer_days,
    )
    summary = summarize_backtest(events, benchmarks)
    segment_summary = summarize_backtest_by_segment(events, benchmarks)

    events.to_csv(events_path, index=False)
    summary.to_csv(summary_path, index=False)
    benchmarks.to_csv(benchmarks_path, index=False)
    segment_summary.to_csv(segments_path, index=False)

    report_md = build_markdown_report(
        cfg=cfg,
        signals=signals,
        summary=summary,
        segment_summary=segment_summary,
        events_path=events_path,
        summary_path=summary_path,
        benchmarks_path=benchmarks_path,
        segment_path=segments_path,
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
        print(
            "[backtest] warning: no valid forward-return events yet. "
            "Check end_date/horizon or ensure enough future bars exist."
        )

    print(f"[backtest] events: {events_path}")
    print(f"[backtest] summary: {summary_path}")
    print(f"[backtest] benchmarks: {benchmarks_path}")
    print(f"[backtest] segments: {segments_path}")
    print(f"[backtest] report: {report_path}")
    print(f"[backtest] network: {network_path}")
    if not summary.empty:
        print("")
        print("=== Backtest Summary (avg_return) ===")
        for row in summary.itertuples(index=False):
            avg_ret = "nan" if pd.isna(row.avg_return) else f"{row.avg_return:.4f}"
            win = "nan" if pd.isna(row.win_rate) else f"{row.win_rate:.2%}"
            ex = "nan" if pd.isna(row.avg_excess_vs_QQQ) else f"{row.avg_excess_vs_QQQ:.4f}"
            print(
                f"- {row.scenario} | {row.list_type} | H={row.horizon_days} | "
                f"n={row.n_events_valid}/{row.n_events_total} | avg={avg_ret} | "
                f"win={win} | excess_vs_QQQ={ex}"
            )
        print("=== End Backtest Summary ===")

    return {
        "events_path": events_path,
        "summary_path": summary_path,
        "benchmarks_path": benchmarks_path,
        "segments_path": segments_path,
        "report_path": report_path,
        "network_path": network_path,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    per_channel = not args.no_per_channel_top_n
    perturb = not args.no_perturbation
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
        rebalance_frequency=args.rebalance_frequency,
        replay_max_symbols=args.replay_max_symbols,
        replay_asset_status=args.replay_asset_status,
        theme_source=args.theme_source,
        enable_perturbation=perturb,
        historical_news_lookback_days=args.historical_news_lookback_days,
        historical_news_limit_per_symbol=args.historical_news_limit_per_symbol,
        delist_return_assumption=args.delist_return_assumption,
        delist_detection_buffer_days=args.delist_detection_buffer_days,
    )
    run_backtest(cfg)


if __name__ == "__main__":
    main()
