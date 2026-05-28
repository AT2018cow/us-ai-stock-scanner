from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
REVENUE_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
]
NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss"]
SHARES_TAGS = [
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
]
STANDARD_EQUITY_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def default_watchlist_core_etfs() -> list[str]:
    return ["AIQ", "BOTZ", "ROBT", "WTAI", "SOXX", "SMH"]


def default_watchlist_enabler_etfs() -> list[str]:
    return ["DTCR", "IFRA", "XLI", "XLU", "NLR", "URA", "SKYY", "CLOU", "SRVR", "GRID", "CIBR"]


def default_channel_profiles() -> dict[str, dict[str, Any]]:
    return {
        "core_ai": {
            "min_ai_score": 0.20,
            "min_enabler_score": 0.00,
            "signal_logic": "ai_only",
            "min_ps_discount": 0.15,
            "min_pe_discount": 0.10,
            "min_drawdown_from_52w_high": None,
            "max_range_position_52w": None,
            "max_price_to_sma200": None,
            "min_days_below_sma200": 7,
            "max_20d_return": 0.12,
            "max_60d_volatility": 0.70,
            "include_sic_prefixes": [],
            "exclude_sic_prefixes": [],
            "include_sic_codes": [],
            "exclude_sic_codes": ["6770"],
            "score_weights": {
                "ps_discount": 0.40,
                "pe_discount": 0.30,
                "ai_score": 0.25,
                "enabler_score": 0.00,
                "liquidity": 0.05,
            },
        },
        "ai_enabler": {
            "min_ai_score": 0.02,
            "min_enabler_score": 0.08,
            "signal_logic": "ai_or_enabler",
            "min_ps_discount": 0.05,
            "min_pe_discount": 0.00,
            "min_drawdown_from_52w_high": None,
            "max_range_position_52w": None,
            "max_price_to_sma200": None,
            "min_days_below_sma200": 5,
            "max_20d_return": 0.18,
            "max_60d_volatility": 0.85,
            "include_sic_prefixes": ["13", "16", "17", "35", "36", "37", "38", "48", "49", "73", "87"],
            "exclude_sic_prefixes": [],
            "include_sic_codes": [],
            "exclude_sic_codes": ["6770"],
            "score_weights": {
                "ps_discount": 0.30,
                "pe_discount": 0.20,
                "ai_score": 0.15,
                "enabler_score": 0.30,
                "liquidity": 0.05,
            },
        },
    }


def default_triage_rules() -> dict[str, dict[str, Any]]:
    return {
        "keep": {
            "core_ai": {
                "min_composite_score": 0.50,
                "min_ai_score": 0.10,
                "min_ps_discount": 0.00,
                "min_pe_discount": 0.00,
            },
            "ai_enabler": {
                "min_composite_score": 0.45,
                "min_enabler_score": 0.05,
                "min_ps_discount": 0.00,
                "min_pe_discount": -0.10,
            },
        },
        "drop": {
            "max_composite_score": 0.35,
            "max_ai_score": 0.02,
            "max_enabler_score": 0.02,
            "require_both_value_premium": True,
        },
    }


@dataclass
class ScanConfig:
    top_n: int = 50
    max_symbols: int | None = None
    max_workers: int = 8
    alpaca_max_requests_per_sec: float = 2.5
    sec_max_requests_per_sec: float = 5.0
    pre_news_top_liquid_symbols: int | None = 1200
    use_ai_watchlist_only: bool = True
    watchlist_csv_path: str = "data/ai_watchlist.csv"
    watchlist_fetch_timeout_sec: int = 20
    watchlist_min_confidence: float = 0.0
    watchlist_core_etfs: list[str] = field(default_factory=default_watchlist_core_etfs)
    watchlist_enabler_etfs: list[str] = field(default_factory=default_watchlist_enabler_etfs)
    chunk_size: int = 200
    request_timeout_sec: int = 20
    news_lookback_days: int = 90
    news_limit_per_symbol: int = 50
    min_ai_score: float = 0.2
    ai_keywords: list[str] = field(
        default_factory=lambda: [
            "artificial intelligence",
            "machine learning",
            "generative ai",
            "large language model",
            "llm",
            "ai inference",
            "ai training",
            "neural network",
            "computer vision",
            "natural language processing",
            "datacenter gpu",
            "ai accelerator",
            "automation software",
        ]
    )
    enabler_keywords: list[str] = field(
        default_factory=lambda: [
            "data center",
            "datacenter",
            "hyperscale",
            "power generation",
            "backup power",
            "prime power",
            "grid",
            "transmission",
            "substation",
            "interconnection",
            "nuclear",
            "small modular reactor",
            "smr",
            "gas turbine",
            "cooling",
            "generator set",
            "genset",
            "backlog",
            "book-to-bill",
            "capital expenditure",
            "capex",
        ]
    )
    min_price: float = 1.0
    min_market_cap: float = 100_000_000.0
    max_market_cap: float | None = None
    min_dollar_volume: float = 1_000_000.0
    require_positive_revenue: bool = True
    require_positive_net_income: bool = True
    min_revenue: float = 10_000_000.0
    min_net_income: float = 1_000_000.0
    max_ps: float | None = None
    max_pe: float | None = None
    min_ps_discount: float = 0.15
    min_pe_discount: float = 0.10
    price_lookback_days: int = 420
    min_drawdown_from_52w_high: float | None = None
    max_range_position_52w: float | None = None
    max_price_to_sma200: float | None = None
    min_days_below_sma200: int | None = 5
    max_20d_return: float | None = 0.18
    max_60d_volatility: float | None = 0.85
    enabled_exchanges: list[str] = field(
        default_factory=lambda: ["NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"]
    )
    enable_sic_prefix_filters: bool = False
    include_sic_prefixes: list[str] = field(default_factory=list)
    exclude_sic_prefixes: list[str] = field(default_factory=list)
    include_sic_codes: list[str] = field(default_factory=list)
    exclude_sic_codes: list[str] = field(default_factory=lambda: ["6770"])
    channel_profiles: dict[str, dict[str, Any]] = field(default_factory=default_channel_profiles)
    triage_rules: dict[str, dict[str, Any]] = field(default_factory=default_triage_rules)
    top_n_per_channel: int | None = None
    cache_dir: str = "cache"
    output_dir: str = "outputs"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScanConfig":
        base = cls()
        for key, value in raw.items():
            if hasattr(base, key):
                setattr(base, key, value)
        return base


@dataclass
class ServiceNetworkStats:
    requests_started: int = 0
    responses: int = 0
    http_2xx: int = 0
    http_3xx: int = 0
    http_4xx: int = 0
    http_429: int = 0
    http_5xx: int = 0
    retries: int = 0
    retry_429: int = 0
    retry_5xx: int = 0
    retry_other: int = 0
    exceptions_total: int = 0
    exceptions_timeout: int = 0
    exceptions_connection: int = 0
    exceptions_http_error: int = 0
    exceptions_other: int = 0
    limiter_wait_calls: int = 0
    limiter_wait_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0


class NetworkMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: dict[str, ServiceNetworkStats] = {}

    def _bucket(self, service: str) -> ServiceNetworkStats:
        if service not in self._stats:
            self._stats[service] = ServiceNetworkStats()
        return self._stats[service]

    def record_request_started(self, service: str) -> None:
        with self._lock:
            self._bucket(service).requests_started += 1

    def record_response(self, service: str, status_code: int, retry_history: list[dict[str, Any]]) -> None:
        with self._lock:
            s = self._bucket(service)
            s.responses += 1
            if 200 <= status_code < 300:
                s.http_2xx += 1
            elif 300 <= status_code < 400:
                s.http_3xx += 1
            elif 400 <= status_code < 500:
                s.http_4xx += 1
            elif 500 <= status_code < 600:
                s.http_5xx += 1
            if status_code == 429:
                s.http_429 += 1

            s.retries += len(retry_history)
            for item in retry_history:
                status = item.get("status")
                if status == 429:
                    s.retry_429 += 1
                elif isinstance(status, int) and 500 <= status < 600:
                    s.retry_5xx += 1
                else:
                    s.retry_other += 1

    def record_exception(self, service: str, exc: Exception) -> None:
        with self._lock:
            s = self._bucket(service)
            s.exceptions_total += 1
            if isinstance(exc, requests.exceptions.Timeout):
                s.exceptions_timeout += 1
            elif isinstance(exc, requests.exceptions.ConnectionError):
                s.exceptions_connection += 1
            elif isinstance(exc, requests.exceptions.HTTPError):
                s.exceptions_http_error += 1
            else:
                s.exceptions_other += 1

    def record_limiter_wait(self, service: str, wait_seconds: float) -> None:
        if wait_seconds <= 0:
            return
        with self._lock:
            s = self._bucket(service)
            s.limiter_wait_calls += 1
            s.limiter_wait_seconds += float(wait_seconds)

    def record_cache(self, service: str, hit: bool) -> None:
        with self._lock:
            s = self._bucket(service)
            if hit:
                s.cache_hits += 1
            else:
                s.cache_misses += 1

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            services = {}
            any_issue = False
            for service, stats in self._stats.items():
                row = {
                    "requests_started": stats.requests_started,
                    "responses": stats.responses,
                    "http_2xx": stats.http_2xx,
                    "http_3xx": stats.http_3xx,
                    "http_4xx": stats.http_4xx,
                    "http_429": stats.http_429,
                    "http_5xx": stats.http_5xx,
                    "retries": stats.retries,
                    "retry_429": stats.retry_429,
                    "retry_5xx": stats.retry_5xx,
                    "retry_other": stats.retry_other,
                    "exceptions_total": stats.exceptions_total,
                    "exceptions_timeout": stats.exceptions_timeout,
                    "exceptions_connection": stats.exceptions_connection,
                    "exceptions_http_error": stats.exceptions_http_error,
                    "exceptions_other": stats.exceptions_other,
                    "limiter_wait_calls": stats.limiter_wait_calls,
                    "limiter_wait_seconds": round(stats.limiter_wait_seconds, 4),
                    "cache_hits": stats.cache_hits,
                    "cache_misses": stats.cache_misses,
                }
                total_cache = row["cache_hits"] + row["cache_misses"]
                row["cache_hit_rate"] = round(row["cache_hits"] / total_cache, 4) if total_cache > 0 else None
                row["had_rate_limit_or_network_issue"] = bool(
                    row["http_429"] > 0
                    or row["retry_429"] > 0
                    or row["retry_5xx"] > 0
                    or row["exceptions_total"] > 0
                )
                services[service] = row
                any_issue = any_issue or row["had_rate_limit_or_network_issue"]
            return {
                "had_rate_limit_or_network_issue": any_issue,
                "services": services,
            }


def extract_retry_history(response: requests.Response) -> list[dict[str, Any]]:
    raw = getattr(response, "raw", None)
    retries = getattr(raw, "retries", None) if raw is not None else None
    history = getattr(retries, "history", ()) if retries is not None else ()
    out: list[dict[str, Any]] = []
    for item in history:
        out.append(
            {
                "status": getattr(item, "status", None),
                "error": str(getattr(item, "error", "")) or None,
            }
        )
    return out


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


class RequestRateLimiter:
    def __init__(
        self,
        max_requests_per_sec: float,
        monitor: NetworkMonitor | None = None,
        service_name: str | None = None,
    ) -> None:
        if max_requests_per_sec <= 0:
            raise ValueError("max_requests_per_sec must be > 0")
        self.min_interval = 1.0 / max_requests_per_sec
        self.monitor = monitor
        self.service_name = service_name
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        sleep_for = 0.0
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                sleep_for = self._next_allowed - now
            base = self._next_allowed if self._next_allowed > now else now
            self._next_allowed = base + self.min_interval
        if sleep_for > 0:
            if self.monitor and self.service_name:
                self.monitor.record_limiter_wait(self.service_name, sleep_for)
            time.sleep(sleep_for)


class AlpacaClient:
    def __init__(
        self,
        session: requests.Session,
        api_endpoint: str,
        data_endpoint: str,
        api_key: str,
        api_secret: str,
        feed: str,
        timeout_sec: int,
        request_limiter: RequestRateLimiter,
        monitor: NetworkMonitor | None = None,
    ) -> None:
        self.session = session
        self.api_endpoint = api_endpoint.rstrip("/")
        self.data_endpoint = data_endpoint.rstrip("/")
        self.timeout_sec = timeout_sec
        self.feed = feed
        self.request_limiter = request_limiter
        self.monitor = monitor
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }

    def _get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        self.request_limiter.wait()
        if self.monitor:
            self.monitor.record_request_started("alpaca")
        try:
            resp = self.session.get(
                url, headers=self.headers, params=params, timeout=self.timeout_sec
            )
            if self.monitor:
                self.monitor.record_response(
                    "alpaca", resp.status_code, extract_retry_history(resp)
                )
            resp.raise_for_status()
            return resp
        except Exception as exc:
            if self.monitor:
                self.monitor.record_exception("alpaca", exc)
            raise

    def get_assets(self, status: str = "active") -> list[dict[str, Any]]:
        url = f"{self.api_endpoint}/v2/assets"
        params = {"status": status, "asset_class": "us_equity"}
        resp = self._get(url, params=params)
        return resp.json()

    def get_snapshots(self, symbols: list[str], chunk_size: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for i in range(0, len(symbols), chunk_size):
            batch = symbols[i : i + chunk_size]
            url = f"{self.data_endpoint}/v2/stocks/snapshots"
            params = {"symbols": ",".join(batch), "feed": self.feed}
            resp = self._get(url, params=params)
            raw = resp.json()
            # Alpaca may return either {"snapshots": {...}} or a top-level
            # {SYMBOL: snapshot} mapping depending on endpoint version.
            if isinstance(raw, dict) and "snapshots" in raw:
                payload = raw.get("snapshots", {})
            elif isinstance(raw, dict):
                payload = raw
            else:
                payload = {}
            result.update(payload)
            time.sleep(0.05)
        return result

    def get_news(
        self,
        symbol: str,
        start_iso: str,
        limit: int,
        end_iso: str | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self.data_endpoint}/v1beta1/news"
        params = {
            "symbols": symbol,
            "start": start_iso,
            "limit": limit,
            "sort": "desc",
        }
        if end_iso:
            params["end"] = end_iso
        resp = self._get(url, params=params)
        data = resp.json()
        return data.get("news", data if isinstance(data, list) else [])

    def get_daily_bars(
        self, symbols: list[str], start_iso: str, chunk_size: int
    ) -> dict[str, list[dict[str, Any]]]:
        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for i in range(0, len(symbols), chunk_size):
            batch = symbols[i : i + chunk_size]
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "start": start_iso,
                    "limit": 10000,
                    "feed": self.feed,
                    "adjustment": "raw",
                }
                if page_token:
                    params["page_token"] = page_token
                url = f"{self.data_endpoint}/v2/stocks/bars"
                resp = self._get(url, params=params)
                payload = resp.json()
                bars = payload.get("bars", {}) if isinstance(payload, dict) else {}
                if isinstance(bars, dict):
                    for symbol, rows in bars.items():
                        if not isinstance(rows, list):
                            continue
                        bars_by_symbol.setdefault(symbol, []).extend(rows)
                page_token = payload.get("next_page_token") if isinstance(payload, dict) else None
                if not page_token:
                    break
            time.sleep(0.05)
        return bars_by_symbol


class SecClient:
    def __init__(
        self,
        session: requests.Session,
        user_agent: str,
        timeout_sec: int,
        cache_dir: Path,
        request_limiter: RequestRateLimiter,
        monitor: NetworkMonitor | None = None,
    ) -> None:
        self.session = session
        self.headers = {"User-Agent": user_agent}
        self.timeout_sec = timeout_sec
        self.cache_dir = cache_dir
        self.request_limiter = request_limiter
        self.monitor = monitor
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, url: str) -> requests.Response:
        self.request_limiter.wait()
        if self.monitor:
            self.monitor.record_request_started("sec")
        try:
            resp = self.session.get(url, headers=self.headers, timeout=self.timeout_sec)
            if self.monitor:
                self.monitor.record_response("sec", resp.status_code, extract_retry_history(resp))
            return resp
        except Exception as exc:
            if self.monitor:
                self.monitor.record_exception("sec", exc)
            raise

    def ticker_mapping(self) -> pd.DataFrame:
        url = "https://www.sec.gov/files/company_tickers.json"
        resp = self._get(url)
        resp.raise_for_status()
        raw = resp.json()
        rows = []
        for row in raw.values():
            rows.append(
                {
                    "symbol": row["ticker"].upper(),
                    "cik": str(row["cik_str"]).zfill(10),
                    "company_name": row["title"],
                }
            )
        return pd.DataFrame(rows)

    def get_submissions(self, cik: str) -> dict[str, Any]:
        cache_path = self.cache_dir / f"submissions_{cik}.json"
        if cache_path.exists():
            if self.monitor:
                self.monitor.record_cache("sec", hit=True)
            return json.loads(cache_path.read_text())
        if self.monitor:
            self.monitor.record_cache("sec", hit=False)
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = self._get(url)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        payload = resp.json()
        cache_path.write_text(json.dumps(payload))
        return payload

    def get_companyfacts(self, cik: str) -> dict[str, Any]:
        cache_path = self.cache_dir / f"facts_{cik}.json"
        if cache_path.exists():
            if self.monitor:
                self.monitor.record_cache("sec", hit=True)
            return json.loads(cache_path.read_text())
        if self.monitor:
            self.monitor.record_cache("sec", hit=False)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        resp = self._get(url)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        payload = resp.json()
        cache_path.write_text(json.dumps(payload))
        return payload


def chunks(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def pick_latest_fact(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[float | None, str | None]:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        if tag not in facts:
            continue
        units = facts[tag].get("units", {})
        entries = units.get(unit, [])
        candidates = []
        for item in entries:
            form = item.get("form")
            if form not in ANNUAL_FORMS:
                continue
            if "val" not in item:
                continue
            end = item.get("end")
            if not end:
                continue
            candidates.append((end, float(item["val"]), form))
        if not candidates:
            continue
        candidates.sort(key=lambda x: x[0], reverse=True)
        latest = candidates[0]
        return latest[1], latest[2]
    return None, None


def price_from_snapshot(snapshot: dict[str, Any]) -> tuple[float | None, float | None]:
    if not snapshot:
        return None, None
    trade = snapshot.get("latestTrade") or {}
    quote = snapshot.get("latestQuote") or {}
    daily = snapshot.get("dailyBar") or {}
    minute = snapshot.get("minuteBar") or {}
    price = trade.get("p") or daily.get("c") or minute.get("c") or quote.get("ap")
    volume = daily.get("v")
    dollar_volume = None
    if price is not None and volume is not None:
        dollar_volume = float(price) * float(volume)
    return (float(price) if price is not None else None, dollar_volume)


def price_dimension_from_bars(
    price: float | None, bars: list[dict[str, Any]]
) -> dict[str, float | int | None]:
    if price is None or not bars:
        return {
            "drawdown_from_52w_high": None,
            "range_position_52w": None,
            "price_to_sma200": None,
            "days_below_sma200": None,
            "return_20d": None,
            "volatility_60d": None,
        }

    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    # Ensure a stable chronological order before computing trailing statistics.
    sorted_bars = sorted(bars, key=lambda row: str(row.get("t", "")))
    for row in sorted_bars:
        try:
            high = float(row.get("h")) if row.get("h") is not None else None
            low = float(row.get("l")) if row.get("l") is not None else None
            close = float(row.get("c")) if row.get("c") is not None else None
        except (TypeError, ValueError):
            continue
        if high is not None:
            highs.append(high)
        if low is not None:
            lows.append(low)
        if close is not None:
            closes.append(close)

    if not highs or not lows:
        return {
            "drawdown_from_52w_high": None,
            "range_position_52w": None,
            "price_to_sma200": None,
            "days_below_sma200": None,
            "return_20d": None,
            "volatility_60d": None,
        }

    high_52w = max(highs)
    low_52w = min(lows)

    drawdown = None
    if high_52w > 0:
        drawdown = (price / high_52w)
        drawdown = 1.0 - drawdown

    range_pos = None
    if high_52w > low_52w:
        range_pos = (price - low_52w) / (high_52w - low_52w)

    price_to_sma200 = None
    days_below_sma200 = None
    if closes:
        window = closes[-200:] if len(closes) >= 200 else closes
        sma200 = float(np.mean(window)) if window else None
        if sma200 and sma200 > 0:
            price_to_sma200 = price / sma200

        if len(closes) >= 200:
            s = pd.Series(closes, dtype="float64")
            sma_roll = s.rolling(window=200, min_periods=200).mean()
            below = s < sma_roll
            trailing = 0
            for flag in reversed(below.tolist()):
                if pd.isna(flag) or not bool(flag):
                    break
                trailing += 1
            days_below_sma200 = trailing

    return_20d = None
    if len(closes) >= 21 and closes[-21] > 0:
        return_20d = (price / closes[-21]) - 1.0

    volatility_60d = None
    if len(closes) >= 61:
        window_61 = np.asarray(closes[-61:], dtype="float64")
        daily_ret = (window_61[1:] / window_61[:-1]) - 1.0
        if daily_ret.size > 0:
            vol = float(np.nanstd(daily_ret, ddof=0) * math.sqrt(252.0))
            if np.isfinite(vol):
                volatility_60d = vol

    return {
        "drawdown_from_52w_high": round(drawdown, 6) if drawdown is not None else None,
        "range_position_52w": round(range_pos, 6) if range_pos is not None else None,
        "price_to_sma200": round(price_to_sma200, 6) if price_to_sma200 is not None else None,
        "days_below_sma200": int(days_below_sma200) if days_below_sma200 is not None else None,
        "return_20d": round(return_20d, 6) if return_20d is not None else None,
        "volatility_60d": round(volatility_60d, 6) if volatility_60d is not None else None,
    }


def theme_score_from_news(news: list[dict[str, Any]], keywords: list[str]) -> float:
    if not news:
        return 0.0
    patterns = compile_keyword_patterns(tuple(k.lower() for k in keywords))
    hit_articles = 0
    weighted_hits = 0.0
    for row in news:
        text = (
            f"{row.get('headline', '')} {row.get('summary', '')} "
            f"{row.get('content', '')}"
        ).lower()
        local_hits = sum(1 for pattern in patterns if pattern.search(text))
        if local_hits > 0:
            hit_articles += 1
            weighted_hits += min(local_hits, 5)
    coverage = hit_articles / len(news)
    density = weighted_hits / (len(news) * 5.0)
    return round(min(1.0, 0.6 * coverage + 0.4 * density), 4)


@lru_cache(maxsize=32)
def compile_keyword_patterns(keywords: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    patterns: list[re.Pattern[str]] = []
    for kw in keywords:
        token = kw.strip().lower()
        if not token:
            continue
        # Match whole words/phrases to avoid substring false positives
        # like "llm" inside "hellmann's".
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
            flags=re.IGNORECASE,
        )
        patterns.append(pattern)
    return tuple(patterns)


def normalize_equity_symbol(raw: Any) -> str:
    token = str(raw or "").strip().upper()
    if token.startswith("$"):
        token = token[1:]
    token = token.replace("-", ".")
    if not token:
        return ""
    if not STANDARD_EQUITY_SYMBOL_PATTERN.match(token):
        return ""
    return token


def fetch_stockanalysis_etf_symbols(
    etf_symbol: str,
    timeout_sec: int,
) -> tuple[list[str], str | None]:
    etf = str(etf_symbol).strip().upper()
    if not etf:
        return [], "empty_etf_symbol"
    url = f"https://stockanalysis.com/etf/{etf.lower()}/holdings/"
    try:
        resp = requests.get(url, timeout=timeout_sec)
        if resp.status_code >= 400:
            return [], f"http_{resp.status_code}"
        html = resp.text
    except Exception as exc:
        return [], f"request_error:{exc.__class__.__name__}"

    block = None
    m = re.search(r"data:\{holdings:\[(.*?)\]\},uses:", html, flags=re.S)
    if m:
        block = m.group(1)
    else:
        m2 = re.search(r"holdings:\[(.*?)\]\s*[,}]", html, flags=re.S)
        if m2:
            block = m2.group(1)
    if not block:
        return [], "holdings_block_not_found"

    raw_symbols = re.findall(r's:"\$?([A-Z0-9\.\-]{1,10})"', block)
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_symbols:
        sym = normalize_equity_symbol(raw)
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    if not out:
        return [], "no_symbols_parsed"
    return out, None


def refresh_watchlist_from_etfs(config: ScanConfig) -> pd.DataFrame:
    core_counts: dict[str, int] = {}
    enabler_counts: dict[str, int] = {}
    core_etf_hits: dict[str, list[str]] = {}
    enabler_etf_hits: dict[str, list[str]] = {}

    for etf in config.watchlist_core_etfs:
        symbols, _ = fetch_stockanalysis_etf_symbols(etf, config.watchlist_fetch_timeout_sec)
        for symbol in symbols:
            core_counts[symbol] = core_counts.get(symbol, 0) + 1
            core_etf_hits.setdefault(symbol, []).append(str(etf).upper())

    for etf in config.watchlist_enabler_etfs:
        symbols, _ = fetch_stockanalysis_etf_symbols(etf, config.watchlist_fetch_timeout_sec)
        for symbol in symbols:
            enabler_counts[symbol] = enabler_counts.get(symbol, 0) + 1
            enabler_etf_hits.setdefault(symbol, []).append(str(etf).upper())

    now_iso = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for symbol, n in core_counts.items():
        conf = min(1.0, 0.50 + 0.10 * n)
        rows.append(
            {
                "symbol": symbol,
                "bucket": "core_ai",
                "confidence": round(conf, 4),
                "source": "etf",
                "etf_count": int(n),
                "etfs": ",".join(sorted(set(core_etf_hits.get(symbol, [])))),
                "enabled": 1,
                "updated_utc": now_iso,
            }
        )
    for symbol, n in enabler_counts.items():
        conf = min(1.0, 0.50 + 0.10 * n)
        rows.append(
            {
                "symbol": symbol,
                "bucket": "ai_enabler",
                "confidence": round(conf, 4),
                "source": "etf",
                "etf_count": int(n),
                "etfs": ",".join(sorted(set(enabler_etf_hits.get(symbol, [])))),
                "enabled": 1,
                "updated_utc": now_iso,
            }
        )
    return pd.DataFrame(rows)


WATCHLIST_SCORE_COLUMNS = [
    "symbol",
    "ai_score",
    "enabler_score",
    "watchlist_source",
    "watchlist_bucket",
    "watchlist_confidence",
    "watchlist_etf_count",
    "watchlist_etfs",
]


def watchlist_rows_to_scores(raw: pd.DataFrame, min_confidence: float) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)
    work = raw.copy()
    work["symbol"] = work.get("symbol", "").apply(normalize_equity_symbol)
    work["bucket"] = work.get("bucket", "").astype(str).str.strip().str.lower()
    work["confidence"] = pd.to_numeric(work.get("confidence", 1.0), errors="coerce").fillna(1.0).clip(lower=0.0, upper=1.0)
    work["enabled"] = (
        work.get("enabled", 1)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"1", "true", "yes", "y"})
    )
    work["etf_count"] = pd.to_numeric(work.get("etf_count", 0), errors="coerce").fillna(0).astype(int)
    work["source"] = work.get("source", "").astype(str)
    work["etfs"] = work.get("etfs", "").astype(str)
    work = work[(work["symbol"] != "") & work["enabled"] & (work["confidence"] >= min_confidence)]
    if work.empty:
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)

    rows: dict[str, dict[str, Any]] = {}
    for row in work.itertuples(index=False):
        symbol = str(row.symbol)
        bucket = str(row.bucket)
        conf = float(row.confidence)
        source = str(row.source)
        etf_count = int(row.etf_count)
        etfs = str(row.etfs)
        if symbol not in rows:
            rows[symbol] = {
                "symbol": symbol,
                "ai_score": 0.0,
                "enabler_score": 0.0,
                "watchlist_source": source,
                "watchlist_bucket": bucket,
                "watchlist_confidence": conf,
                "watchlist_etf_count": etf_count,
                "watchlist_etfs": etfs,
            }
        if bucket == "core_ai":
            rows[symbol]["ai_score"] = max(float(rows[symbol]["ai_score"]), conf)
        elif bucket == "ai_enabler":
            rows[symbol]["enabler_score"] = max(float(rows[symbol]["enabler_score"]), conf)
        elif bucket == "both":
            rows[symbol]["ai_score"] = max(float(rows[symbol]["ai_score"]), conf)
            rows[symbol]["enabler_score"] = max(float(rows[symbol]["enabler_score"]), conf)
        rows[symbol]["watchlist_confidence"] = max(float(rows[symbol]["watchlist_confidence"]), conf)
        rows[symbol]["watchlist_etf_count"] = max(int(rows[symbol]["watchlist_etf_count"]), etf_count)
        prev_bucket = str(rows[symbol]["watchlist_bucket"])
        if prev_bucket != bucket and bucket not in prev_bucket.split(","):
            rows[symbol]["watchlist_bucket"] = f"{prev_bucket},{bucket}" if prev_bucket else bucket
        if source and source not in str(rows[symbol]["watchlist_source"]).split(","):
            rows[symbol]["watchlist_source"] = (
                f"{rows[symbol]['watchlist_source']},{source}" if rows[symbol]["watchlist_source"] else source
            )
        if etfs:
            prev = set(x for x in str(rows[symbol]["watchlist_etfs"]).split(",") if x)
            now = set(x for x in etfs.split(",") if x)
            rows[symbol]["watchlist_etfs"] = ",".join(sorted(prev.union(now)))

    out = pd.DataFrame(rows.values())
    return out[WATCHLIST_SCORE_COLUMNS]


def load_watchlist_scores(config: ScanConfig) -> pd.DataFrame:
    path = Path(config.watchlist_csv_path)
    if not path.exists():
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)
    raw = pd.read_csv(path)
    return watchlist_rows_to_scores(raw, config.watchlist_min_confidence)


def normalize_score(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if np.isnan(lo) or np.isnan(hi) or math.isclose(lo, hi):
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - lo) / (hi - lo)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce").astype(float)
    den = pd.to_numeric(denominator, errors="coerce").astype(float)
    out = pd.Series(np.nan, index=num.index, dtype=float)
    valid = den.notna() & (den != 0) & num.notna()
    out.loc[valid] = num.loc[valid] / den.loc[valid]
    return out


def merge_unique(values: list[str], extras: list[str]) -> list[str]:
    out: list[str] = []
    for item in [*values, *extras]:
        token = str(item).strip()
        if token and token not in out:
            out.append(token)
    return out


def passes_sic_filters(
    sic: str | None,
    include_prefixes: list[str],
    exclude_prefixes: list[str],
    include_codes: list[str],
    exclude_codes: list[str],
) -> bool:
    if not sic:
        return False
    sic = str(sic)
    if include_codes and sic not in include_codes:
        return False
    if exclude_codes and sic in exclude_codes:
        return False
    if include_prefixes and not any(sic.startswith(prefix) for prefix in include_prefixes):
        return False
    if exclude_prefixes and any(sic.startswith(prefix) for prefix in exclude_prefixes):
        return False
    return True


def resolve_channel_profile(
    config: ScanConfig, channel_name: str, profile: dict[str, Any]
) -> dict[str, Any]:
    if config.enable_sic_prefix_filters:
        include_prefixes = merge_unique(config.include_sic_prefixes, profile.get("include_sic_prefixes", []))
        exclude_prefixes = merge_unique(config.exclude_sic_prefixes, profile.get("exclude_sic_prefixes", []))
    else:
        include_prefixes = []
        exclude_prefixes = []
    include_codes = merge_unique(config.include_sic_codes, profile.get("include_sic_codes", []))
    exclude_codes = merge_unique(config.exclude_sic_codes, profile.get("exclude_sic_codes", []))

    return {
        "name": channel_name,
        "signal_logic": profile.get("signal_logic", "ai_only"),
        "min_ai_score": float(profile.get("min_ai_score", config.min_ai_score)),
        "min_enabler_score": float(profile.get("min_enabler_score", 0.0)),
        "min_ps_discount": float(profile.get("min_ps_discount", config.min_ps_discount)),
        "min_pe_discount": float(profile.get("min_pe_discount", config.min_pe_discount)),
        "min_drawdown_from_52w_high": (
            None
            if profile.get("min_drawdown_from_52w_high", config.min_drawdown_from_52w_high) is None
            else float(profile.get("min_drawdown_from_52w_high", config.min_drawdown_from_52w_high))
        ),
        "max_range_position_52w": (
            None
            if profile.get("max_range_position_52w", config.max_range_position_52w) is None
            else float(profile.get("max_range_position_52w", config.max_range_position_52w))
        ),
        "max_price_to_sma200": (
            None
            if profile.get("max_price_to_sma200", config.max_price_to_sma200) is None
            else float(profile.get("max_price_to_sma200", config.max_price_to_sma200))
        ),
        "min_days_below_sma200": (
            None
            if profile.get("min_days_below_sma200", config.min_days_below_sma200) is None
            else int(profile.get("min_days_below_sma200", config.min_days_below_sma200))
        ),
        "max_20d_return": (
            None
            if profile.get("max_20d_return", config.max_20d_return) is None
            else float(profile.get("max_20d_return", config.max_20d_return))
        ),
        "max_60d_volatility": (
            None
            if profile.get("max_60d_volatility", config.max_60d_volatility) is None
            else float(profile.get("max_60d_volatility", config.max_60d_volatility))
        ),
        "include_sic_prefixes": include_prefixes,
        "exclude_sic_prefixes": exclude_prefixes,
        "include_sic_codes": include_codes,
        "exclude_sic_codes": exclude_codes,
        "score_weights": profile.get("score_weights", {}),
    }


def load_config(path: str | None) -> ScanConfig:
    if not path:
        return ScanConfig()
    raw = json.loads(Path(path).read_text())
    return ScanConfig.from_dict(raw)


def load_runtime_settings(config: ScanConfig) -> tuple[AlpacaClient, SecClient, NetworkMonitor]:
    load_dotenv()
    api_endpoint = os.getenv("ALPACA_API_ENDPOINT", "").strip()
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    data_endpoint = os.getenv("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets")
    feed = os.getenv("ALPACA_FEED", "iex")
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()

    if not api_endpoint or not api_key or not api_secret:
        raise ValueError(
            "Missing Alpaca credentials. Fill ALPACA_API_ENDPOINT/KEY/SECRET in .env."
        )
    if not user_agent:
        raise ValueError("Missing SEC_USER_AGENT in .env.")

    session = build_session()
    monitor = NetworkMonitor()
    alpaca_limiter = RequestRateLimiter(
        config.alpaca_max_requests_per_sec, monitor=monitor, service_name="alpaca"
    )
    sec_limiter = RequestRateLimiter(
        config.sec_max_requests_per_sec, monitor=monitor, service_name="sec"
    )
    alpaca = AlpacaClient(
        session=session,
        api_endpoint=api_endpoint,
        data_endpoint=data_endpoint,
        api_key=api_key,
        api_secret=api_secret,
        feed=feed,
        timeout_sec=config.request_timeout_sec,
        request_limiter=alpaca_limiter,
        monitor=monitor,
    )
    sec = SecClient(
        session=session,
        user_agent=user_agent,
        timeout_sec=config.request_timeout_sec,
        cache_dir=Path(config.cache_dir),
        request_limiter=sec_limiter,
        monitor=monitor,
    )
    return alpaca, sec, monitor


def collect_candidates(
    alpaca: AlpacaClient, sec: SecClient, config: ScanConfig, asset_status: str = "active"
) -> pd.DataFrame:
    assets = alpaca.get_assets(status=asset_status)
    df_assets = pd.DataFrame(assets)
    df_assets = df_assets[df_assets["tradable"] == True].copy()
    if config.enabled_exchanges:
        df_assets = df_assets[df_assets["exchange"].isin(config.enabled_exchanges)]
    df_assets["symbol"] = df_assets["symbol"].str.upper()

    mapping = sec.ticker_mapping()
    merged = df_assets.merge(mapping, on="symbol", how="inner")
    merged = merged[["symbol", "name", "exchange", "cik", "company_name"]].drop_duplicates(
        subset=["symbol"]
    )

    symbols = merged["symbol"].tolist()
    snapshots = alpaca.get_snapshots(symbols, config.chunk_size)
    px_rows = []
    for symbol in symbols:
        price, dollar_volume = price_from_snapshot(snapshots.get(symbol, {}))
        px_rows.append(
            {"symbol": symbol, "price": price, "dollar_volume": dollar_volume}
        )
    df_px = pd.DataFrame(px_rows)
    out = merged.merge(df_px, on="symbol", how="left")
    if config.max_symbols:
        # Use liquidity-aware sampling instead of dataframe order to avoid biased subsets.
        out = out.sort_values(
            by=["dollar_volume", "symbol"],
            ascending=[False, True],
            na_position="last",
        ).head(config.max_symbols)
    return out


def load_one_fundamental(sec: SecClient, symbol: str, cik: str) -> dict[str, Any]:
    submissions = sec.get_submissions(cik)
    companyfacts = sec.get_companyfacts(cik)

    sic = submissions.get("sic")
    sic_desc = submissions.get("sicDescription")
    revenue, revenue_form = pick_latest_fact(companyfacts, REVENUE_TAGS, "USD")
    net_income, net_income_form = pick_latest_fact(companyfacts, NET_INCOME_TAGS, "USD")
    shares, shares_form = pick_latest_fact(companyfacts, SHARES_TAGS, "shares")

    return {
        "symbol": symbol,
        "sic": str(sic) if sic is not None else None,
        "sic_description": sic_desc,
        "revenue": revenue,
        "revenue_form": revenue_form,
        "net_income": net_income,
        "net_income_form": net_income_form,
        "shares_outstanding": shares,
        "shares_form": shares_form,
    }


def collect_fundamentals(df: pd.DataFrame, sec: SecClient, config: ScanConfig) -> pd.DataFrame:
    rows = []
    total = len(df)
    done = 0
    last_reported_pct = -1
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {
            pool.submit(load_one_fundamental, sec, row.symbol, row.cik): row.symbol
            for row in df.itertuples(index=False)
        }
        for future in as_completed(futures):
            try:
                rows.append(future.result())
            except Exception:
                rows.append(
                    {
                        "symbol": futures[future],
                        "sic": None,
                        "sic_description": None,
                        "revenue": None,
                        "revenue_form": None,
                        "net_income": None,
                        "net_income_form": None,
                        "shares_outstanding": None,
                        "shares_form": None,
                    }
                )
            done += 1
            if total > 0:
                pct = int((done * 100) / total)
                if pct >= last_reported_pct + 10 or done == total:
                    print(f"  [progress] SEC fundamentals: {done}/{total} ({pct}%)")
                    last_reported_pct = pct
    return pd.DataFrame(rows)


def collect_news_scores(
    symbols: list[str], alpaca: AlpacaClient, config: ScanConfig
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(columns=["symbol", "ai_score", "enabler_score", "news_count"])
    since = (
        datetime.now(timezone.utc) - timedelta(days=config.news_lookback_days)
    ).isoformat()
    rows = []
    total = len(symbols)
    done = 0
    last_reported_pct = -1
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        future_map = {
            pool.submit(alpaca.get_news, symbol, since, config.news_limit_per_symbol): symbol
            for symbol in symbols
        }
        for future in as_completed(future_map):
            symbol = future_map[future]
            try:
                news = future.result()
                rows.append(
                    {
                        "symbol": symbol,
                        "ai_score": theme_score_from_news(news, config.ai_keywords),
                        "enabler_score": theme_score_from_news(news, config.enabler_keywords),
                        "news_count": len(news),
                    }
                )
            except Exception:
                rows.append(
                    {"symbol": symbol, "ai_score": 0.0, "enabler_score": 0.0, "news_count": 0}
                )
            done += 1
            if total > 0:
                pct = int((done * 100) / total)
                if pct >= last_reported_pct + 20 or done == total:
                    print(f"  [progress] Alpaca news: {done}/{total} ({pct}%)")
                    last_reported_pct = pct
    return pd.DataFrame(rows)


def build_filter_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> list[tuple[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        (
            "min_dollar_volume",
            lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume,
        ),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
    ]

    if config.max_market_cap is not None:
        steps.append(("max_market_cap", lambda frame: frame["market_cap"] <= config.max_market_cap))
    if config.require_positive_revenue:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if config.require_positive_net_income:
        steps.append(("positive_net_income", lambda frame: frame["net_income"].fillna(-1) > 0))
    if config.min_revenue is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= config.min_revenue))
    if config.min_net_income is not None:
        steps.append(("min_net_income", lambda frame: frame["net_income"].fillna(0) >= config.min_net_income))
    if config.max_ps is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= config.max_ps))
    if config.max_pe is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= config.max_pe))
    if cp["min_drawdown_from_52w_high"] is not None:
        steps.append(
            (
                "min_drawdown_from_52w_high",
                lambda frame: frame["drawdown_from_52w_high"].fillna(-1) >= cp["min_drawdown_from_52w_high"],
            )
        )
    if cp["max_range_position_52w"] is not None:
        steps.append(
            (
                "max_range_position_52w",
                lambda frame: frame["range_position_52w"].fillna(np.inf) <= cp["max_range_position_52w"],
            )
        )
    if cp["max_price_to_sma200"] is not None:
        steps.append(
            (
                "max_price_to_sma200",
                lambda frame: frame["price_to_sma200"].fillna(np.inf) <= cp["max_price_to_sma200"],
            )
        )
    if cp["min_days_below_sma200"] is not None:
        steps.append(
            (
                "min_days_below_sma200",
                lambda frame: frame["days_below_sma200"].fillna(-1) >= cp["min_days_below_sma200"],
            )
        )
    if cp["max_20d_return"] is not None:
        steps.append(
            (
                "max_20d_return",
                lambda frame: frame["return_20d"].fillna(np.inf) <= cp["max_20d_return"],
            )
        )
    if cp["max_60d_volatility"] is not None:
        steps.append(
            (
                "max_60d_volatility",
                lambda frame: frame["volatility_60d"].fillna(np.inf) <= cp["max_60d_volatility"],
            )
        )

    if cp["signal_logic"] == "ai_or_enabler":
        steps.append(
            (
                "signal_ai_or_enabler",
                lambda frame: (frame["ai_score"] >= cp["min_ai_score"])
                | (frame["enabler_score"] >= cp["min_enabler_score"]),
            )
        )
    elif cp["signal_logic"] == "ai_and_enabler":
        steps.append(
            (
                "signal_ai_and_enabler",
                lambda frame: (frame["ai_score"] >= cp["min_ai_score"])
                & (frame["enabler_score"] >= cp["min_enabler_score"]),
            )
        )
    else:
        steps.append(("min_ai_score", lambda frame: frame["ai_score"] >= cp["min_ai_score"]))

    steps.extend(
        [
            ("min_ps_discount", lambda frame: frame["ps_discount"] >= cp["min_ps_discount"]),
            ("min_pe_discount", lambda frame: frame["pe_discount"] >= cp["min_pe_discount"]),
            (
                "sic_filter",
                lambda frame: frame["sic"].apply(
                    lambda x: passes_sic_filters(
                        x,
                        cp["include_sic_prefixes"],
                        cp["exclude_sic_prefixes"],
                        cp["include_sic_codes"],
                        cp["exclude_sic_codes"],
                    )
                ),
            ),
        ]
    )
    return steps


def build_industry_trend_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> tuple[list[tuple[str, Any]], dict[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)
    trend_signal_logic = str(channel_profile.get("trend_signal_logic", cp["signal_logic"]))
    trend_min_ai = float(channel_profile.get("trend_min_ai_score", cp["min_ai_score"]))
    trend_min_enabler = float(
        channel_profile.get("trend_min_enabler_score", cp["min_enabler_score"])
    )
    trend_weights = channel_profile.get("trend_score_weights")
    if not isinstance(trend_weights, dict):
        if channel_name == "ai_enabler":
            trend_weights = {"ai_score": 0.30, "enabler_score": 0.60, "liquidity": 0.10}
        else:
            trend_weights = {"ai_score": 0.80, "enabler_score": 0.10, "liquidity": 0.10}

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        ("min_dollar_volume", lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
    ]
    if config.max_market_cap is not None:
        steps.append(("max_market_cap", lambda frame: frame["market_cap"] <= config.max_market_cap))
    if config.require_positive_revenue:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))

    if trend_signal_logic == "ai_and_enabler":
        steps.append(
            (
                "trend_signal_ai_and_enabler",
                lambda frame: (frame["ai_score"] >= trend_min_ai)
                & (frame["enabler_score"] >= trend_min_enabler),
            )
        )
    elif trend_signal_logic == "ai_or_enabler":
        steps.append(
            (
                "trend_signal_ai_or_enabler",
                lambda frame: (frame["ai_score"] >= trend_min_ai)
                | (frame["enabler_score"] >= trend_min_enabler),
            )
        )
    else:
        steps.append(("trend_min_ai_score", lambda frame: frame["ai_score"] >= trend_min_ai))

    steps.append(
        (
            "sic_filter",
            lambda frame: frame["sic"].apply(
                lambda x: passes_sic_filters(
                    x,
                    cp["include_sic_prefixes"],
                    cp["exclude_sic_prefixes"],
                    cp["include_sic_codes"],
                    cp["exclude_sic_codes"],
                )
            ),
        )
    )
    return steps, trend_weights


def build_momentum_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> tuple[list[tuple[str, Any]], dict[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)
    momentum_signal_logic = str(
        channel_profile.get("momentum_signal_logic", channel_profile.get("trend_signal_logic", cp["signal_logic"]))
    )
    momentum_min_ai = float(
        channel_profile.get("momentum_min_ai_score", channel_profile.get("trend_min_ai_score", cp["min_ai_score"]))
    )
    momentum_min_enabler = float(
        channel_profile.get(
            "momentum_min_enabler_score",
            channel_profile.get("trend_min_enabler_score", cp["min_enabler_score"]),
        )
    )
    momentum_min_return_20d = channel_profile.get("momentum_min_return_20d", 0.05)
    momentum_min_price_to_sma200 = channel_profile.get("momentum_min_price_to_sma200", 1.05)
    momentum_max_drawdown_from_52w_high = channel_profile.get(
        "momentum_max_drawdown_from_52w_high", 0.25
    )
    momentum_weights = channel_profile.get("momentum_score_weights")
    if not isinstance(momentum_weights, dict):
        momentum_weights = {
            "ai_score": 0.30,
            "enabler_score": 0.40,
            "liquidity": 0.10,
            "return_20d": 0.20,
        }

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        ("min_dollar_volume", lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
        ("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0),
        (
            "momentum_min_return_20d",
            lambda frame: frame["return_20d"].fillna(-np.inf) >= float(momentum_min_return_20d),
        ),
        (
            "momentum_min_price_to_sma200",
            lambda frame: frame["price_to_sma200"].fillna(-np.inf) >= float(momentum_min_price_to_sma200),
        ),
        (
            "momentum_max_drawdown_from_52w_high",
            lambda frame: frame["drawdown_from_52w_high"].fillna(np.inf)
            <= float(momentum_max_drawdown_from_52w_high),
        ),
    ]

    if momentum_signal_logic == "ai_and_enabler":
        steps.append(
            (
                "momentum_signal_ai_and_enabler",
                lambda frame: (frame["ai_score"] >= momentum_min_ai)
                & (frame["enabler_score"] >= momentum_min_enabler),
            )
        )
    elif momentum_signal_logic == "ai_or_enabler":
        steps.append(
            (
                "momentum_signal_ai_or_enabler",
                lambda frame: (frame["ai_score"] >= momentum_min_ai)
                | (frame["enabler_score"] >= momentum_min_enabler),
            )
        )
    else:
        steps.append(("momentum_min_ai_score", lambda frame: frame["ai_score"] >= momentum_min_ai))

    steps.append(
        (
            "sic_filter",
            lambda frame: frame["sic"].apply(
                lambda x: passes_sic_filters(
                    x,
                    cp["include_sic_prefixes"],
                    cp["exclude_sic_prefixes"],
                    cp["include_sic_codes"],
                    cp["exclude_sic_codes"],
                )
            ),
        )
    )
    return steps, momentum_weights


def apply_filters_with_diagnostics(
    df: pd.DataFrame, steps: list[tuple[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, int | str]]]:
    out = df.copy()
    diagnostics: list[dict[str, int | str]] = [
        {"step": "start", "remaining": int(len(out)), "removed": 0}
    ]

    for step_name, mask_fn in steps:
        before = len(out)
        out = out[mask_fn(out)]
        after = len(out)
        diagnostics.append(
            {
                "step": step_name,
                "remaining": int(after),
                "removed": int(before - after),
            }
        )

    return out, diagnostics


def collect_pre_news_symbols(
    df: pd.DataFrame, config: ScanConfig, channel_profiles: dict[str, dict[str, Any]]
) -> tuple[list[str], dict[str, int]]:
    signal_steps = {"min_ai_score", "signal_ai_or_enabler", "signal_ai_and_enabler"}
    symbol_set: set[str] = set()
    channel_counts: dict[str, int] = {}

    for channel_name, channel_profile in channel_profiles.items():
        full_steps = build_filter_steps(config, channel_name, channel_profile)
        pre_steps = [step for step in full_steps if step[0] not in signal_steps]
        pre_filtered, _ = apply_filters_with_diagnostics(df, pre_steps)
        channel_counts[channel_name] = len(pre_filtered)
        if "symbol" in pre_filtered.columns and not pre_filtered.empty:
            symbol_set.update(pre_filtered["symbol"].dropna().astype(str).tolist())

    if not symbol_set:
        return [], channel_counts

    candidates = df[df["symbol"].isin(symbol_set)].copy()
    candidates["dollar_volume"] = pd.to_numeric(candidates["dollar_volume"], errors="coerce").fillna(0)
    candidates = candidates.sort_values("dollar_volume", ascending=False)

    if config.pre_news_top_liquid_symbols is not None:
        candidates = candidates.head(config.pre_news_top_liquid_symbols)

    return candidates["symbol"].dropna().astype(str).drop_duplicates().tolist(), channel_counts


def collect_pre_news_symbols_for_trend(
    df: pd.DataFrame, config: ScanConfig, channel_profiles: dict[str, dict[str, Any]]
) -> tuple[list[str], dict[str, int]]:
    symbol_set: set[str] = set()
    channel_counts: dict[str, int] = {}
    for channel_name, channel_profile in channel_profiles.items():
        trend_steps, _ = build_industry_trend_steps(config, channel_name, channel_profile)
        # Remove trend signal + SIC filter for pre-news pool construction.
        pre_steps = [step for step in trend_steps if not step[0].startswith("trend_signal_") and step[0] != "trend_min_ai_score" and step[0] != "sic_filter"]
        pre_filtered, _ = apply_filters_with_diagnostics(df, pre_steps)
        channel_counts[channel_name] = len(pre_filtered)
        if "symbol" in pre_filtered.columns and not pre_filtered.empty:
            symbol_set.update(pre_filtered["symbol"].dropna().astype(str).tolist())

    if not symbol_set:
        return [], channel_counts

    candidates = df[df["symbol"].isin(symbol_set)].copy()
    candidates["dollar_volume"] = pd.to_numeric(candidates["dollar_volume"], errors="coerce").fillna(0)
    candidates = candidates.sort_values("dollar_volume", ascending=False)

    if config.pre_news_top_liquid_symbols is not None:
        candidates = candidates.head(config.pre_news_top_liquid_symbols)

    return candidates["symbol"].dropna().astype(str).drop_duplicates().tolist(), channel_counts


def collect_pre_news_symbols_for_momentum(
    df: pd.DataFrame, config: ScanConfig, channel_profiles: dict[str, dict[str, Any]]
) -> tuple[list[str], dict[str, int]]:
    symbol_set: set[str] = set()
    channel_counts: dict[str, int] = {}
    for channel_name, channel_profile in channel_profiles.items():
        momentum_steps, _ = build_momentum_steps(config, channel_name, channel_profile)
        # Remove momentum signal + SIC filter for pre-news pool construction.
        pre_steps = [
            step
            for step in momentum_steps
            if not step[0].startswith("momentum_signal_")
            and step[0] != "momentum_min_ai_score"
            and step[0] != "sic_filter"
        ]
        pre_filtered, _ = apply_filters_with_diagnostics(df, pre_steps)
        channel_counts[channel_name] = len(pre_filtered)
        if "symbol" in pre_filtered.columns and not pre_filtered.empty:
            symbol_set.update(pre_filtered["symbol"].dropna().astype(str).tolist())

    if not symbol_set:
        return [], channel_counts

    candidates = df[df["symbol"].isin(symbol_set)].copy()
    candidates["dollar_volume"] = pd.to_numeric(candidates["dollar_volume"], errors="coerce").fillna(0)
    candidates = candidates.sort_values("dollar_volume", ascending=False)

    if config.pre_news_top_liquid_symbols is not None:
        candidates = candidates.head(config.pre_news_top_liquid_symbols)

    return candidates["symbol"].dropna().astype(str).drop_duplicates().tolist(), channel_counts


def summarize_first_fail_reasons(
    df: pd.DataFrame, steps: list[tuple[str, Any]]
) -> pd.DataFrame:
    first_fail = pd.Series("passed", index=df.index, dtype="object")
    unresolved = pd.Series(True, index=df.index)

    for step_name, mask_fn in steps:
        mask = mask_fn(df).fillna(False)
        failed_now = unresolved & (~mask)
        first_fail.loc[failed_now] = step_name
        unresolved = unresolved & mask

    summary = first_fail.value_counts(dropna=False).rename_axis("reason").reset_index(name="count")
    total = max(1, len(df))
    summary["pct"] = (summary["count"] / total).round(4)
    return summary


def score_and_rank(df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    out = df.copy()
    required_cols = ["ps_discount", "pe_discount", "ai_score", "enabler_score", "dollar_volume", "return_20d"]
    for col in required_cols:
        if col not in out.columns:
            out[col] = np.nan

    out["ps_discount_norm"] = normalize_score(out["ps_discount"])
    out["pe_discount_norm"] = normalize_score(out["pe_discount"])
    out["ai_score_norm"] = normalize_score(out["ai_score"])
    out["enabler_score_norm"] = normalize_score(out["enabler_score"])
    out["liquidity_norm"] = normalize_score(np.log1p(out["dollar_volume"].fillna(0)))
    out["return_20d_norm"] = normalize_score(out["return_20d"])

    w_ps = float(weights.get("ps_discount", 0.40))
    w_pe = float(weights.get("pe_discount", 0.30))
    w_ai = float(weights.get("ai_score", 0.25))
    w_enabler = float(weights.get("enabler_score", 0.00))
    w_liq = float(weights.get("liquidity", 0.05))
    w_ret = float(weights.get("return_20d", 0.00))

    out["composite_score"] = (
        w_ps * out["ps_discount_norm"]
        + w_pe * out["pe_discount_norm"]
        + w_ai * out["ai_score_norm"]
        + w_enabler * out["enabler_score_norm"]
        + w_liq * out["liquidity_norm"]
        + w_ret * out["return_20d_norm"]
    )
    return out.sort_values("composite_score", ascending=False)


def assign_triage_label(row: pd.Series, triage_rules: dict[str, dict[str, Any]]) -> str:
    channel = str(row.get("channel", ""))
    keep_cfg = triage_rules.get("keep", {}).get(channel, {})
    drop_cfg = triage_rules.get("drop", {})

    comp = float(row.get("composite_score", 0.0) or 0.0)
    ai = float(row.get("ai_score", 0.0) or 0.0)
    enabler = float(row.get("enabler_score", 0.0) or 0.0)
    psd = float(row.get("ps_discount", 0.0) or 0.0)
    ped = float(row.get("pe_discount", 0.0) or 0.0)

    if keep_cfg:
        keep_ok = comp >= float(keep_cfg.get("min_composite_score", 0.5))
        if channel == "core_ai":
            keep_ok = keep_ok and ai >= float(keep_cfg.get("min_ai_score", 0.1))
        elif channel == "ai_enabler":
            keep_ok = keep_ok and enabler >= float(keep_cfg.get("min_enabler_score", 0.05))
        keep_ok = keep_ok and psd >= float(keep_cfg.get("min_ps_discount", -1.0))
        keep_ok = keep_ok and ped >= float(keep_cfg.get("min_pe_discount", -1.0))
        if keep_ok:
            return "keep"

    drop_by_score = comp <= float(drop_cfg.get("max_composite_score", 0.35))
    drop_by_signal = (
        ai <= float(drop_cfg.get("max_ai_score", 0.02))
        and enabler <= float(drop_cfg.get("max_enabler_score", 0.02))
    )
    require_premium = bool(drop_cfg.get("require_both_value_premium", True))
    if require_premium:
        drop_by_value = psd < 0 and ped < 0
    else:
        drop_by_value = psd < 0 or ped < 0

    if drop_by_score or (drop_by_signal and drop_by_value):
        return "drop"
    return "watch"


def apply_triage_labels(ranked: pd.DataFrame, triage_rules: dict[str, dict[str, Any]]) -> pd.DataFrame:
    out = ranked.copy()
    if out.empty:
        out["triage_label"] = pd.Series(dtype="object")
        return out
    out["triage_label"] = out.apply(lambda r: assign_triage_label(r, triage_rules), axis=1)
    return out


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
    industry_trend_count: int | None = None,
    industry_trend_path: Path | None = None,
    momentum_count: int | None = None,
    momentum_path: Path | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# AI Value Scan Report")
    lines.append("")
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
                        f"score={float(row['composite_score']):.3f} | "
                        f"ai={float(row['ai_score']):.3f} | "
                        f"enabler={float(row['enabler_score']):.3f} | "
                        f"psd={float(row['ps_discount']):.3f} | "
                        f"ped={float(row['pe_discount']):.3f}"
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
    lines.append(f"- network issues observed: {'YES' if network_issue_flag else 'NO'}")
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
        default="config.filters.json",
        help="JSON file path for filter configuration.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override top_n from config.",
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


def run_scan(
    config: ScanConfig,
    output_path: str | None,
    diagnostics_output_path: str | None,
    network_report_output_path: str | None = None,
    report_output_path: str | None = None,
) -> Path:
    started_at = datetime.now(timezone.utc)
    paths = resolve_output_paths(
        config,
        started_at,
        output_path,
        diagnostics_output_path,
        network_report_output_path,
        report_output_path,
    )
    diagnostics_output_path = str(paths["diagnostics_base"])
    network_report_output_path = str(paths["network_json"])
    log_status(started_at, "INFO", "Scan started.")
    log_status(started_at, "INFO", f"Ranked output target: {paths['ranked_csv']}")
    alpaca, sec, network_monitor = load_runtime_settings(config)

    log_status(started_at, "INFO", "[1/6] Loading tradable US equities from Alpaca.")
    df = collect_candidates(alpaca, sec, config)
    merged_count = len(df)
    log_status(started_at, "INFO", f"Merged symbols: {merged_count}")

    df = df[
        df["price"].notna()
        & (pd.to_numeric(df["price"], errors="coerce") >= config.min_price)
        & (pd.to_numeric(df["dollar_volume"], errors="coerce").fillna(0) >= config.min_dollar_volume)
    ].copy()
    prefilter_count = len(df)
    log_status(started_at, "INFO", f"After price/liquidity prefilter: {prefilter_count}")

    log_status(started_at, "INFO", "[2/6] Computing price-dimension features.")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    bars_start_iso = (datetime.now(timezone.utc) - timedelta(days=config.price_lookback_days)).isoformat()
    symbols_for_bars = df["symbol"].dropna().astype(str).tolist()
    bars_map = alpaca.get_daily_bars(symbols_for_bars, bars_start_iso, config.chunk_size)
    price_feature_rows: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        features = price_dimension_from_bars(row.price, bars_map.get(row.symbol, []))
        price_feature_rows.append({"symbol": row.symbol, **features})
    df_price_features = pd.DataFrame(price_feature_rows)
    df = df.merge(df_price_features, on="symbol", how="left")

    log_status(started_at, "INFO", "[3/6] Fetching SEC fundamentals (cached locally).")
    fundamentals = collect_fundamentals(df, sec, config)
    df = df.merge(fundamentals, on="symbol", how="left")
    log_status(started_at, "INFO", "SEC fundamentals merge complete.")

    log_status(started_at, "INFO", "[4/6] Computing valuation and watchlist funnel.")
    for col in ["price", "dollar_volume", "shares_outstanding", "revenue", "net_income"]:
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

    top_n_per_channel = config.top_n_per_channel or config.top_n
    channel_profiles = config.channel_profiles or {"core_ai": {}}
    if not config.use_ai_watchlist_only:
        log_status(
            started_at,
            "INFO",
            "use_ai_watchlist_only=false is ignored: news-based theme scoring has been removed.",
        )
    log_status(started_at, "INFO", "[5/6] Loading AI watchlist scores.")
    watchlist_scores = load_watchlist_scores(config)
    if watchlist_scores.empty:
        raise ValueError(
            "Watchlist is empty or missing. Run "
            "`python scripts/refresh_ai_watchlist.py --config config.production.json --output data/ai_watchlist.csv` "
            "or populate watchlist_csv_path manually."
        )
    df = df.merge(watchlist_scores, on="symbol", how="left")
    for missing_col, default_val in [
        ("watchlist_confidence", 0.0),
        ("watchlist_etf_count", 0),
        ("watchlist_source", ""),
        ("watchlist_bucket", ""),
        ("watchlist_etfs", ""),
    ]:
        if missing_col not in df.columns:
            df[missing_col] = default_val
    df["ai_score"] = pd.to_numeric(df["ai_score"], errors="coerce").fillna(0.0)
    df["enabler_score"] = pd.to_numeric(df["enabler_score"], errors="coerce").fillna(0.0)
    df["watchlist_confidence"] = pd.to_numeric(df["watchlist_confidence"], errors="coerce").fillna(0.0)
    df["watchlist_etf_count"] = pd.to_numeric(df["watchlist_etf_count"], errors="coerce").fillna(0).astype(int)
    df["watchlist_source"] = df["watchlist_source"].fillna("").astype(str)
    df["watchlist_bucket"] = df["watchlist_bucket"].fillna("").astype(str)
    df["watchlist_etfs"] = df["watchlist_etfs"].fillna("").astype(str)
    df["news_count"] = 0

    watchlist_counts = {
        "core_ai": int((df["ai_score"] > 0).sum()),
        "ai_enabler": int((df["enabler_score"] > 0).sum()),
    }
    watchlist_symbol_count = int(((df["ai_score"] > 0) | (df["enabler_score"] > 0)).sum())
    log_status(started_at, "INFO", "Watchlist candidates by channel:")
    for channel_name, count in watchlist_counts.items():
        log_status(started_at, "INFO", f"  {channel_name}: {count}")
    log_status(started_at, "INFO", f"Watchlist matched symbols: {watchlist_symbol_count}")

    ranked_frames: list[pd.DataFrame] = []
    filtered_counts: dict[str, int] = {}

    for channel_name, channel_profile in channel_profiles.items():
        cp = resolve_channel_profile(config, channel_name, channel_profile)
        steps = build_filter_steps(config, channel_name, channel_profile)
        filtered, diagnostics = apply_filters_with_diagnostics(df, steps)
        first_fail_summary = summarize_first_fail_reasons(df, steps)

        log_status(started_at, "INFO", f"Channel={channel_name}: filter diagnostics")
        for row in diagnostics[1:]:
            log_status(started_at, "INFO", f"  {row['step']}: -{row['removed']} => {row['remaining']}")

        log_status(started_at, "INFO", "  First-fail summary:")
        for row in first_fail_summary.itertuples(index=False):
            log_status(started_at, "INFO", f"  {row.reason}: {row.count} ({row.pct:.2%})")

        diagnostics_path = Path(diagnostics_output_path)
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = diagnostics_path.suffix or ".csv"
        diag_file = diagnostics_path.with_name(f"{diagnostics_path.stem}_{channel_name}{suffix}")
        fail_file = diagnostics_path.with_name(
            f"{diagnostics_path.stem}_{channel_name}_first_fail{suffix}"
        )
        pd.DataFrame(diagnostics).to_csv(diag_file, index=False)
        first_fail_summary.to_csv(fail_file, index=False)
        log_status(started_at, "INFO", f"  Diagnostics: {diag_file}")
        log_status(started_at, "INFO", f"  First-fail: {fail_file}")

        ranked = score_and_rank(filtered, cp["score_weights"]).head(top_n_per_channel)
        ranked["channel"] = channel_name
        ranked_frames.append(ranked)
        filtered_counts[channel_name] = len(filtered)
        log_status(started_at, "INFO", f"  Filtered candidates: {len(filtered)}")

    non_empty_ranked_frames = [frame for frame in ranked_frames if not frame.empty]
    ranked = (
        pd.concat(non_empty_ranked_frames, ignore_index=True)
        if non_empty_ranked_frames
        else pd.DataFrame(columns=df.columns.tolist() + ["channel", "composite_score"])
    )

    out_path = paths["ranked_csv"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "channel",
        "symbol",
        "name",
        "exchange",
        "company_name",
        "sic",
        "sic_description",
        "price",
        "dollar_volume",
        "drawdown_from_52w_high",
        "range_position_52w",
        "price_to_sma200",
        "days_below_sma200",
        "return_20d",
        "volatility_60d",
        "market_cap",
        "revenue",
        "net_income",
        "ps",
        "pe",
        "peer_median_ps",
        "peer_median_pe",
        "ps_discount",
        "pe_discount",
        "ai_score",
        "enabler_score",
        "watchlist_confidence",
        "watchlist_bucket",
        "watchlist_source",
        "watchlist_etf_count",
        "watchlist_etfs",
        "news_count",
        "composite_score",
    ]
    ranked = apply_triage_labels(ranked, config.triage_rules)
    if ranked.empty:
        ranked = pd.DataFrame(columns=cols + ["triage_label"])
    else:
        ranked = ranked.sort_values(["channel", "composite_score"], ascending=[True, False])
    ranked.to_csv(out_path, index=False, columns=cols + ["triage_label"])

    for channel_name in channel_profiles.keys():
        ch_out = out_path.with_name(f"{out_path.stem}_{channel_name}{out_path.suffix or '.csv'}")
        if "channel" in ranked.columns:
            channel_df = ranked[ranked["channel"] == channel_name]
        else:
            channel_df = ranked.copy()
        if channel_df.empty:
            channel_df = pd.DataFrame(columns=cols + ["triage_label"])
        channel_df.to_csv(ch_out, index=False, columns=cols + ["triage_label"])
        log_status(started_at, "INFO", f"Channel output ({channel_name}): {ch_out}")

    # Build a second list focused on AI industry trend relevance, without
    # enforcing low-position/value constraints.
    trend_frames: list[pd.DataFrame] = []
    for channel_name, channel_profile in channel_profiles.items():
        trend_steps, trend_weights = build_industry_trend_steps(config, channel_name, channel_profile)
        trend_filtered, _ = apply_filters_with_diagnostics(df, trend_steps)
        trend_ranked = score_and_rank(trend_filtered, trend_weights).head(top_n_per_channel)
        trend_ranked["channel"] = channel_name
        trend_frames.append(trend_ranked)

    non_empty_trend_frames = [frame for frame in trend_frames if not frame.empty]
    industry_trend = (
        pd.concat(non_empty_trend_frames, ignore_index=True)
        if non_empty_trend_frames
        else pd.DataFrame(columns=df.columns.tolist() + ["channel", "composite_score"])
    )
    industry_trend["triage_label"] = "trend"
    if not industry_trend.empty:
        industry_trend = industry_trend.sort_values(["channel", "composite_score"], ascending=[True, False])
    trend_out_path = out_path.with_name(f"{out_path.stem}_industry_trend{out_path.suffix or '.csv'}")
    industry_trend.to_csv(trend_out_path, index=False, columns=cols + ["triage_label"])
    for channel_name in channel_profiles.keys():
        ch_trend_out = trend_out_path.with_name(
            f"{trend_out_path.stem}_{channel_name}{trend_out_path.suffix or '.csv'}"
        )
        if "channel" in industry_trend.columns:
            ch_trend_df = industry_trend[industry_trend["channel"] == channel_name]
        else:
            ch_trend_df = industry_trend.copy()
        if ch_trend_df.empty:
            ch_trend_df = pd.DataFrame(columns=cols + ["triage_label"])
        ch_trend_df.to_csv(ch_trend_out, index=False, columns=cols + ["triage_label"])
        log_status(started_at, "INFO", f"Industry trend output ({channel_name}): {ch_trend_out}")
    log_status(started_at, "INFO", f"Industry trend output: {trend_out_path}")

    # Build a third list focused on momentum/chasing strength.
    momentum_frames: list[pd.DataFrame] = []
    for channel_name, channel_profile in channel_profiles.items():
        momentum_steps, momentum_weights = build_momentum_steps(config, channel_name, channel_profile)
        momentum_filtered, _ = apply_filters_with_diagnostics(df, momentum_steps)
        momentum_ranked = score_and_rank(momentum_filtered, momentum_weights).head(top_n_per_channel)
        momentum_ranked["channel"] = channel_name
        momentum_frames.append(momentum_ranked)

    non_empty_momentum_frames = [frame for frame in momentum_frames if not frame.empty]
    momentum = (
        pd.concat(non_empty_momentum_frames, ignore_index=True)
        if non_empty_momentum_frames
        else pd.DataFrame(columns=df.columns.tolist() + ["channel", "composite_score"])
    )
    momentum["triage_label"] = "momentum"
    if not momentum.empty:
        momentum = momentum.sort_values(["channel", "composite_score"], ascending=[True, False])
    momentum_out_path = out_path.with_name(f"{out_path.stem}_momentum{out_path.suffix or '.csv'}")
    momentum.to_csv(momentum_out_path, index=False, columns=cols + ["triage_label"])
    for channel_name in channel_profiles.keys():
        ch_momentum_out = momentum_out_path.with_name(
            f"{momentum_out_path.stem}_{channel_name}{momentum_out_path.suffix or '.csv'}"
        )
        if "channel" in momentum.columns:
            ch_momentum_df = momentum[momentum["channel"] == channel_name]
        else:
            ch_momentum_df = momentum.copy()
        if ch_momentum_df.empty:
            ch_momentum_df = pd.DataFrame(columns=cols + ["triage_label"])
        ch_momentum_df.to_csv(ch_momentum_out, index=False, columns=cols + ["triage_label"])
        log_status(started_at, "INFO", f"Momentum output ({channel_name}): {ch_momentum_out}")
    log_status(started_at, "INFO", f"Momentum output: {momentum_out_path}")

    log_status(started_at, "INFO", "[6/6] Finalizing outputs.")
    log_status(started_at, "INFO", f"Total ranked rows: {len(ranked)}")
    for channel_name, count in filtered_counts.items():
        log_status(started_at, "INFO", f"{channel_name} filtered candidates: {count}")
    log_status(started_at, "INFO", f"Ranked output: {out_path}")

    network_report_path = Path(network_report_output_path)
    network_report_path.parent.mkdir(parents=True, exist_ok=True)

    finished_at = datetime.now(timezone.utc)
    report = network_monitor.to_dict()
    report["started_at_utc"] = started_at.isoformat()
    report["finished_at_utc"] = finished_at.isoformat()
    report["elapsed_seconds"] = round((finished_at - started_at).total_seconds(), 2)
    report["scan_context"] = {
        "max_symbols": config.max_symbols,
        "top_n": config.top_n,
        "top_n_per_channel": config.top_n_per_channel or config.top_n,
        "use_ai_watchlist_only": config.use_ai_watchlist_only,
        "watchlist_csv_path": config.watchlist_csv_path,
        "watchlist_core_etfs": config.watchlist_core_etfs,
        "watchlist_enabler_etfs": config.watchlist_enabler_etfs,
    }
    network_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log_status(started_at, "INFO", f"Network report: {network_report_path}")
    log_status(
        started_at,
        "INFO",
        f"Network issues observed: {'YES' if report.get('had_rate_limit_or_network_issue') else 'NO'}",
    )
    sec_cache_summary: str | None = None
    sec_stats = report.get("services", {}).get("sec", {})
    if isinstance(sec_stats, dict):
        hits = int(sec_stats.get("cache_hits", 0) or 0)
        misses = int(sec_stats.get("cache_misses", 0) or 0)
        total = hits + misses
        if total > 0:
            hit_rate = (hits / total) * 100.0
            sec_cache_summary = f"hits={hits}, misses={misses}, hit_rate={hit_rate:.2f}%"
            log_status(started_at, "INFO", f"SEC cache: {sec_cache_summary}")

    md_report = build_run_report_markdown(
        started_at=started_at,
        finished_at=finished_at,
        ranked=ranked,
        channel_profiles=channel_profiles,
        filtered_counts=filtered_counts,
        watchlist_counts=watchlist_counts,
        watchlist_symbol_count=watchlist_symbol_count,
        merged_count=merged_count,
        prefilter_count=prefilter_count,
        paths=paths,
        network_issue_flag=bool(report.get("had_rate_limit_or_network_issue")),
        sec_cache_summary=sec_cache_summary,
        industry_trend_count=len(industry_trend),
        industry_trend_path=trend_out_path,
        momentum_count=len(momentum),
        momentum_path=momentum_out_path,
    )
    paths["report_md"].write_text(md_report)
    log_status(started_at, "INFO", f"Detailed report: {paths['report_md']}")

    print("")
    print("=== Low-Value Shortlist (Top 3 Per Channel) ===")
    if ranked.empty:
        print("No candidates.")
    else:
        for channel_name in channel_profiles.keys():
            print(f"[{channel_name}]")
            top = ranked[
                (ranked["channel"] == channel_name) & (ranked["triage_label"] != "drop")
            ].sort_values(
                "composite_score", ascending=False
            ).head(3)
            if top.empty:
                print("  - none")
                continue
            for _, row in top.iterrows():
                print(
                    "  - "
                    f"{row['symbol']} | triage={row['triage_label']} | "
                    f"score={float(row['composite_score']):.3f} | "
                    f"psd={float(row['ps_discount']):.3f} | "
                    f"ped={float(row['pe_discount']):.3f} | "
                    f"ai={float(row['ai_score']):.3f} | "
                    f"enabler={float(row['enabler_score']):.3f}"
                )
    print("=== End Low-Value Shortlist ===")
    print("")
    print("=== Industry Trend Shortlist (Top 3 Per Channel) ===")
    if industry_trend.empty:
        print("No industry trend candidates.")
    else:
        for channel_name in channel_profiles.keys():
            print(f"[{channel_name}]")
            top = industry_trend[industry_trend["channel"] == channel_name].sort_values(
                "composite_score", ascending=False
            ).head(3)
            if top.empty:
                print("  - none")
                continue
            for _, row in top.iterrows():
                print(
                    "  - "
                    f"{row['symbol']} | score={float(row['composite_score']):.3f} | "
                    f"ai={float(row['ai_score']):.3f} | "
                    f"enabler={float(row['enabler_score']):.3f}"
                )
    print("=== End Industry Trend Shortlist ===")
    print("")
    print("=== Momentum Shortlist (Top 3 Per Channel) ===")
    if momentum.empty:
        print("No momentum candidates.")
    else:
        for channel_name in channel_profiles.keys():
            print(f"[{channel_name}]")
            top = momentum[momentum["channel"] == channel_name].sort_values(
                "composite_score", ascending=False
            ).head(3)
            if top.empty:
                print("  - none")
                continue
            for _, row in top.iterrows():
                print(
                    "  - "
                    f"{row['symbol']} | score={float(row['composite_score']):.3f} | "
                    f"r20={float(row['return_20d']):.3f} | "
                    f"ai={float(row['ai_score']):.3f} | "
                    f"enabler={float(row['enabler_score']):.3f}"
                )
    print("=== End Momentum Shortlist ===")
    log_status(started_at, "INFO", "Scan completed successfully.")
    return out_path


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    if args.top_n is not None:
        config.top_n = args.top_n
    if args.max_symbols is not None:
        config.max_symbols = args.max_symbols

    try:
        run_scan(
            config,
            args.output,
            args.diagnostics_output,
            args.network_report_output,
            args.report_output,
        )
    except Exception as exc:
        print("")
        print("[ERROR] Scan failed.")
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        print(traceback.format_exc())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
