from __future__ import annotations

import argparse
import hashlib
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
QUARTERLY_FORMS = {"10-Q", "10-K", "20-F", "40-F"}
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
OPERATING_CASH_FLOW_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "CapitalExpendituresIncurredButNotYetPaid",
    "CapitalExpenditures",
]
CASH_AND_EQUIVALENTS_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
LONG_TERM_DEBT_TAGS = [
    "LongTermDebtAndFinanceLeaseObligations",
    "LongTermDebtNoncurrent",
]
CURRENT_DEBT_TAGS = [
    "DebtCurrent",
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
]
EBIT_TAGS = [
    "OperatingIncomeLoss",
    "EarningsBeforeInterestAndTaxes",
]
NONRECURRING_EXPENSE_TAGS = [
    "BusinessCombinationAcquisitionRelatedCosts",
    "BusinessCombinationIntegrationRelatedCosts",
    "RestructuringCharges",
    "AssetImpairmentCharges",
    "GoodwillImpairmentLoss",
]
NONRECURRING_GAIN_TAGS = [
    "GainLossOnDispositionOfAssets",
    "GainLossOnSaleOfBusiness",
    "GainLossOnSaleOfPropertyPlantEquipment",
    "GainLossOnSaleOfOtherAssets",
]
INTEREST_EXPENSE_TAGS = [
    "InterestExpense",
    "InterestAndDebtExpense",
]
DA_TAGS = [
    "DepreciationAndAmortization",
    "DepreciationDepletionAndAmortization",
]
ASSETS_CURRENT_TAGS = ["AssetsCurrent"]
LIABILITIES_CURRENT_TAGS = ["LiabilitiesCurrent"]
RECEIVABLES_CURRENT_TAGS = ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"]
INVENTORY_TAGS = ["InventoryNet"]
BACKLOG_TAGS = [
    "RevenueRemainingPerformanceObligation",
    "ContractWithCustomerLiability",
    "DeferredRevenueCurrentAndNoncurrent",
]
STANDARD_EQUITY_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

AI_DISCLOSURE_KEYWORD_GROUPS: dict[str, list[str]] = {
    "ai_compute": [
        "artificial intelligence",
        "ai workload",
        "machine learning",
        "llm",
        "generative ai",
        "inference",
        "training cluster",
    ],
    "data_center": [
        "data center",
        "hyperscaler",
        "colocation",
        "server rack",
        "cooling system",
    ],
    "semiconductor": [
        "gpu",
        "accelerator",
        "semiconductor",
        "advanced packaging",
        "high bandwidth memory",
    ],
    "power_grid": [
        "grid connection",
        "substation",
        "power demand",
        "load growth",
        "transmission",
        "nuclear",
    ],
    "commercial_signal": [
        "remaining performance obligation",
        "backlog",
        "order book",
        "book-to-bill",
        "capacity expansion",
    ],
}


def default_ai_link_benchmark_etfs() -> list[str]:
    return [
        "AIQ",
        "BOTZ",
        "SMH",
        "SOXX",
        "XLK",
        "XLI",
        "XLU",
        "PAVE",
    ]


def default_watchlist_core_etfs() -> list[str]:
    return [
        "AIQ",
        "BOTZ",
        "ROBT",
        "WTAI",
        "SOXX",
        "SMH",
        "IRBO",
        "ARKQ",
        "IGV",
        "IGM",
        "FDN",
        "PNQI",
        "SOXQ",
        "XSD",
        "KOMP",
    ]


def default_watchlist_enabler_etfs() -> list[str]:
    return [
        "DTCR",
        "IFRA",
        "XLI",
        "XLU",
        "NLR",
        "URA",
        "SKYY",
        "CLOU",
        "SRVR",
        "GRID",
        "CIBR",
        "IHAK",
        "BUG",
        "PAVE",
        "IGF",
        "IXP",
    ]


def default_watchlist_peripheral_etfs() -> list[str]:
    return [
        "XLB",
        "VIS",
        "ITA",
        "IYT",
        "ITB",
        "PICK",
        "COPX",
        "VPU",
        "XLRE",
        "VNQ",
        "FXR",
        "IGE",
    ]


def default_channel_profiles() -> dict[str, dict[str, Any]]:
    return {
        "core_ai": {
            "min_watchlist_etf_count": 1,
            "min_ai_link_score": 0.30,
            "min_ps_discount": 0.15,
            "min_pe_discount": 0.10,
            "max_ps_percentile_in_sic": 0.45,
            "max_pe_percentile_in_sic": 0.45,
            "max_ev_to_ebit": 24.0,
            "min_fcf_yield": 0.02,
            "min_revenue_yoy": 0.00,
            "min_net_income_yoy": -0.05,
            "min_drawdown_from_52w_high": None,
            "max_range_position_52w": None,
            "max_price_to_sma200": None,
            "min_days_below_sma200": 7,
            "max_20d_return": 0.12,
            "max_60d_volatility": 0.70,
            "score_weights": {
                "ps_discount": 0.24,
                "pe_discount": 0.16,
                "ps_percentile_low": 0.10,
                "pe_percentile_low": 0.08,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.05,
                "watchlist_etf_count": 0.15,
                "ai_link_score": 0.10,
                "range_position_52w_low": 0.10,
                "days_below_sma200": 0.05,
                "net_margin": 0.02,
            },
        },
        "ai_enabler": {
            "min_watchlist_etf_count": 1,
            "min_ai_link_score": 0.45,
            "min_ps_discount": 0.08,
            "min_pe_discount": 0.02,
            "max_ps_percentile_in_sic": 0.55,
            "max_pe_percentile_in_sic": 0.55,
            "max_ev_to_ebit": 30.0,
            "min_fcf_yield": 0.015,
            "min_revenue_yoy": -0.02,
            "min_net_income_yoy": -0.10,
            "min_drawdown_from_52w_high": None,
            "max_range_position_52w": None,
            "max_price_to_sma200": None,
            "min_days_below_sma200": 5,
            "max_20d_return": 0.18,
            "max_60d_volatility": 0.85,
            "score_weights": {
                "ps_discount": 0.18,
                "pe_discount": 0.12,
                "ps_percentile_low": 0.12,
                "pe_percentile_low": 0.10,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.05,
                "watchlist_etf_count": 0.25,
                "ai_link_score": 0.12,
                "range_position_52w_low": 0.15,
                "days_below_sma200": 0.05,
                "net_margin": 0.03,
            },
        },
        "ai_peripheral": {
            "min_watchlist_etf_count": 1,
            "min_ai_link_score": 0.55,
            "min_ps_discount": 0.02,
            "min_pe_discount": -0.10,
            "max_ps_percentile_in_sic": 0.70,
            "max_pe_percentile_in_sic": 0.70,
            "max_ev_to_ebit": 36.0,
            "min_fcf_yield": 0.005,
            "min_revenue_yoy": -0.05,
            "min_net_income_yoy": -0.15,
            "min_drawdown_from_52w_high": 0.05,
            "max_range_position_52w": 0.90,
            "max_price_to_sma200": 1.20,
            "min_days_below_sma200": 3,
            "max_20d_return": 0.18,
            "max_60d_volatility": 0.95,
            "score_weights": {
                "ps_discount": 0.24,
                "pe_discount": 0.16,
                "ps_percentile_low": 0.10,
                "pe_percentile_low": 0.08,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.07,
                "watchlist_etf_count": 0.08,
                "ai_link_score": 0.15,
                "range_position_52w_low": 0.08,
                "days_below_sma200": 0.04,
            },
            "trend_min_return_60d": -0.03,
            "trend_max_60d_volatility": 0.70,
            "trend_min_avg_dollar_volume_20d": 20000000.0,
            "momentum_min_return_20d": 0.06,
            "momentum_min_return_60d": 0.05,
            "momentum_min_price_to_sma200": 1.06,
            "momentum_max_drawdown_from_52w_high": 0.25,
            "momentum_max_60d_volatility": 0.75,
            "momentum_min_avg_dollar_volume_20d": 25000000.0,
            "momentum_min_watchlist_etf_count": 1,
        },
    }


def default_triage_rules() -> dict[str, dict[str, Any]]:
    return {
        "keep": {
            "core_ai": {
                "min_composite_score": 0.50,
                "min_ps_discount": 0.00,
                "min_pe_discount": 0.00,
            },
            "ai_enabler": {
                "min_composite_score": 0.45,
                "min_ps_discount": 0.00,
                "min_pe_discount": -0.10,
            },
            "ai_peripheral": {
                "min_composite_score": 0.50,
                "min_ps_discount": 0.05,
                "min_pe_discount": 0.00,
            },
        },
        "drop": {
            "max_composite_score": 0.35,
            "require_both_value_premium": True,
        },
    }


def default_low_coverage_soft_score_weights() -> dict[str, float]:
    return {
        "current_debt_ratio_low": 0.03,
        "inventory_growth_gap_low": 0.03,
    }


@dataclass
class ScanConfig:
    max_symbols: int | None = None
    max_workers: int = 8
    alpaca_max_requests_per_sec: float = 2.5
    sec_max_requests_per_sec: float = 5.0
    alpaca_cache_enabled: bool = True
    alpaca_cache_ttl_assets_sec: int = 21600
    alpaca_cache_ttl_snapshots_sec: int = 120
    alpaca_cache_ttl_bars_sec: int = 21600
    watchlist_csv_path: str = "data/ai_watchlist.csv"
    watchlist_fetch_timeout_sec: int = 20
    ai_link_benchmark_etfs: list[str] = field(default_factory=default_ai_link_benchmark_etfs)
    ai_link_etf_count_saturation: int = 4
    ai_link_disclosure_keyword_cap: int = 6
    ai_link_market_return_tolerance_20d: float = 0.25
    ai_link_market_return_tolerance_60d: float = 0.40
    ai_link_backlog_ratio_cap: float = 0.20
    watchlist_core_etfs: list[str] = field(default_factory=default_watchlist_core_etfs)
    watchlist_enabler_etfs: list[str] = field(default_factory=default_watchlist_enabler_etfs)
    watchlist_peripheral_etfs: list[str] = field(default_factory=default_watchlist_peripheral_etfs)
    chunk_size: int = 200
    request_timeout_sec: int = 20
    min_price: float = 1.0
    min_market_cap: float = 100_000_000.0
    max_market_cap: float | None = None
    min_dollar_volume: float = 1_000_000.0
    min_avg_dollar_volume_20d: float | None = None
    require_positive_revenue: bool = True
    require_positive_net_income: bool = True
    require_positive_operating_cash_flow: bool = True
    require_positive_free_cash_flow: bool = True
    require_positive_ebit: bool = True
    use_adjusted_quality_metrics: bool = True
    nonrecurring_addback_revenue_cap: float | None = 0.25
    use_ttm_metrics: bool = True
    min_fundamental_quality_score: float | None = 0.45
    min_revenue: float = 10_000_000.0
    min_net_income: float = 1_000_000.0
    min_operating_cash_flow: float | None = 0.0
    min_free_cash_flow: float | None = 0.0
    min_ebit: float | None = 0.0
    min_net_margin: float | None = None
    max_ps: float | None = None
    max_pe: float | None = None
    max_ev_to_ebit: float | None = 25.0
    min_fcf_yield: float | None = 0.02
    max_ps_percentile_in_sic: float | None = 0.60
    max_pe_percentile_in_sic: float | None = 0.60
    min_revenue_yoy: float | None = 0.00
    min_net_income_yoy: float | None = -0.10
    max_net_debt_to_ebitda: float | None = 5.0
    min_interest_coverage: float | None = 1.8
    max_current_debt_ratio: float | None = 0.75
    min_current_ratio: float | None = 0.90
    min_ocf_to_net_income: float | None = 0.60
    max_accrual_ratio: float | None = 0.35
    max_receivables_growth_gap: float | None = 0.60
    max_inventory_growth_gap: float | None = 1.00
    max_shares_yoy: float | None = 0.08
    own_history_valuation_window_days: int = 252
    max_ps_hist_percentile: float | None = 0.85
    max_pe_hist_percentile: float | None = 0.85
    min_expectation_proxy: float | None = -0.20
    min_cycle_proxy: float | None = None
    assumed_position_usd: float = 250_000.0
    max_adv_participation: float = 0.05
    max_estimated_slippage_bps: float | None = 40.0
    max_per_sector_per_list: int | None = 3
    max_per_watchlist_etf_source_per_list: int | None = None
    metric_hard_filter_coverage_mode: str = "balanced"
    force_hard_filter_low_coverage_metrics: bool = False
    low_coverage_soft_score_weights: dict[str, float] = field(
        default_factory=default_low_coverage_soft_score_weights
    )
    score_penalty_overvaluation: float = 0.20
    score_penalty_deterioration: float = 0.20
    min_ps_discount: float = 0.15
    min_pe_discount: float = 0.10
    price_lookback_days: int = 420
    min_drawdown_from_52w_high: float | None = None
    max_range_position_52w: float | None = None
    max_price_to_sma200: float | None = None
    min_days_below_sma200: int | None = 5
    min_return_20d: float | None = None
    min_return_60d: float | None = None
    max_20d_return: float | None = 0.18
    max_60d_volatility: float | None = 0.85
    min_drawdown_percentile: float | None = None
    min_avg_dollar_volume_20d_percentile: float | None = None
    max_60d_volatility_percentile: float | None = None
    score_winsor_lower_q: float = 0.05
    score_winsor_upper_q: float = 0.95
    enabled_exchanges: list[str] = field(
        default_factory=lambda: ["NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"]
    )
    require_channel_bucket_match: bool = True
    enforce_unique_symbol_per_list: bool = False
    enforce_unique_symbol_across_lists: bool = False
    exclude_sic_codes: list[str] = field(default_factory=lambda: ["6770"])
    channel_profiles: dict[str, dict[str, Any]] = field(default_factory=default_channel_profiles)
    triage_rules: dict[str, dict[str, Any]] = field(default_factory=default_triage_rules)
    top_n_per_channel_low_value: int = 10
    top_n_per_channel_trend: int = 10
    top_n_per_channel_momentum: int = 10
    research_pool_top_n: int = 50
    research_pool_min_score: float = 2.0
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
        cache_dir: Path,
        cache_enabled: bool,
        cache_ttl_assets_sec: int,
        cache_ttl_snapshots_sec: int,
        cache_ttl_bars_sec: int,
        monitor: NetworkMonitor | None = None,
    ) -> None:
        self.session = session
        self.api_endpoint = api_endpoint.rstrip("/")
        self.data_endpoint = data_endpoint.rstrip("/")
        self.timeout_sec = timeout_sec
        self.feed = feed
        self.request_limiter = request_limiter
        self.cache_dir = cache_dir / "alpaca"
        self.cache_enabled = bool(cache_enabled)
        self.cache_ttl_assets_sec = max(0, int(cache_ttl_assets_sec))
        self.cache_ttl_snapshots_sec = max(0, int(cache_ttl_snapshots_sec))
        self.cache_ttl_bars_sec = max(0, int(cache_ttl_bars_sec))
        self.monitor = monitor
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_file(self, namespace: str, key_payload: dict[str, Any]) -> Path:
        digest = hashlib.sha1(
            json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{namespace}_{digest}.json"

    def _load_cache(
        self, namespace: str, key_payload: dict[str, Any], ttl_sec: int
    ) -> Any | None:
        if not self.cache_enabled or ttl_sec <= 0:
            return None
        cache_path = self._cache_file(namespace, key_payload)
        if not cache_path.exists():
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=False)
            return None
        age = time.time() - cache_path.stat().st_mtime
        if age > float(ttl_sec):
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=False)
            return None
        try:
            payload = json.loads(cache_path.read_text())
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=True)
            return payload
        except Exception:
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=False)
            return None

    def _load_cache_stale(self, namespace: str, key_payload: dict[str, Any]) -> Any | None:
        if not self.cache_enabled:
            return None
        cache_path = self._cache_file(namespace, key_payload)
        if not cache_path.exists():
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=False)
            return None
        try:
            payload = json.loads(cache_path.read_text())
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=True)
            return payload
        except Exception:
            if self.monitor:
                self.monitor.record_cache("alpaca", hit=False)
            return None

    def _load_snapshots_from_any_cache(self, symbols: list[str]) -> dict[str, Any]:
        if not self.cache_enabled:
            return {}
        remaining = set(str(s).upper() for s in symbols if s)
        if not remaining:
            return {}
        out: dict[str, Any] = {}
        for path in sorted(self.cache_dir.glob("snapshots_*.json")):
            if not remaining:
                break
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            hit = False
            for symbol in list(remaining):
                if symbol in payload:
                    out[symbol] = payload[symbol]
                    remaining.discard(symbol)
                    hit = True
            if hit and self.monitor:
                self.monitor.record_cache("alpaca", hit=True)
        if out:
            return out
        if self.monitor:
            self.monitor.record_cache("alpaca", hit=False)
        return {}

    def _load_bars_from_any_cache(self, symbols: list[str], start_iso: str) -> dict[str, list[dict[str, Any]]]:
        if not self.cache_enabled:
            return {}
        targets = [str(s).upper() for s in symbols if s]
        if not targets:
            return {}
        target_set = set(targets)
        best_rows: dict[str, list[dict[str, Any]]] = {}
        best_min_ts: dict[str, str] = {}
        best_len: dict[str, int] = {}
        start_key = str(start_iso or "")
        for path in sorted(self.cache_dir.glob("bars_*.json")):
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            hit = False
            for symbol in target_set:
                rows = payload.get(symbol)
                if not isinstance(rows, list):
                    continue
                filtered: list[dict[str, Any]] = []
                min_ts = ""
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    ts = str(row.get("t") or "")
                    if ts and (not min_ts or ts < min_ts):
                        min_ts = ts
                    if start_key and ts and ts < start_key:
                        continue
                    filtered.append(row)
                candidate = filtered if filtered else rows
                if not candidate:
                    continue
                cand_len = len(candidate)
                prev_len = best_len.get(symbol, -1)
                prev_min_ts = best_min_ts.get(symbol, "")
                if (
                    cand_len > prev_len
                    or (cand_len == prev_len and min_ts and (not prev_min_ts or min_ts < prev_min_ts))
                ):
                    best_rows[symbol] = candidate
                    best_len[symbol] = cand_len
                    best_min_ts[symbol] = min_ts
                hit = True
            if hit and self.monitor:
                self.monitor.record_cache("alpaca", hit=True)
        if best_rows:
            return best_rows
        if self.monitor:
            self.monitor.record_cache("alpaca", hit=False)
        return {}

    @staticmethod
    def _rows_min_timestamp(rows: list[dict[str, Any]]) -> str:
        min_ts = ""
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = str(row.get("t") or "")
            if not ts:
                continue
            if not min_ts or ts < min_ts:
                min_ts = ts
        return min_ts

    @classmethod
    def _should_replace_rows(
        cls, existing: list[dict[str, Any]] | None, candidate: list[dict[str, Any]], start_iso: str
    ) -> bool:
        if not isinstance(candidate, list) or not candidate:
            return False
        if not isinstance(existing, list) or not existing:
            return True
        start_key = str(start_iso or "")
        existing_min = cls._rows_min_timestamp(existing)
        candidate_min = cls._rows_min_timestamp(candidate)
        existing_has_coverage = bool(existing_min and (not start_key or existing_min <= start_key))
        candidate_has_coverage = bool(candidate_min and (not start_key or candidate_min <= start_key))
        if candidate_has_coverage and not existing_has_coverage:
            return True
        if len(candidate) > len(existing):
            return True
        if len(candidate) == len(existing) and candidate_min and (
            not existing_min or candidate_min < existing_min
        ):
            return True
        return False

    def _save_cache(self, namespace: str, key_payload: dict[str, Any], payload: Any) -> None:
        if not self.cache_enabled:
            return
        cache_path = self._cache_file(namespace, key_payload)
        cache_path.write_text(json.dumps(payload))

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
        cache_key = {
            "api_endpoint": self.api_endpoint,
            "status": status,
            "asset_class": "us_equity",
        }
        cached = self._load_cache("assets", cache_key, self.cache_ttl_assets_sec)
        if isinstance(cached, list):
            return cached
        try:
            resp = self._get(url, params=params)
            payload = resp.json()
            self._save_cache("assets", cache_key, payload)
            return payload
        except Exception:
            stale = self._load_cache_stale("assets", cache_key)
            if isinstance(stale, list):
                return stale
            raise

    def get_snapshots(self, symbols: list[str], chunk_size: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for i in range(0, len(symbols), chunk_size):
            batch = symbols[i : i + chunk_size]
            cache_key = {
                "data_endpoint": self.data_endpoint,
                "feed": self.feed,
                "symbols": sorted(str(sym).upper() for sym in batch),
            }
            payload = self._load_cache("snapshots", cache_key, self.cache_ttl_snapshots_sec)
            if not isinstance(payload, dict):
                try:
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
                    self._save_cache("snapshots", cache_key, payload)
                except Exception:
                    stale = self._load_cache_stale("snapshots", cache_key)
                    if isinstance(stale, dict):
                        payload = stale
                    else:
                        any_cache = self._load_snapshots_from_any_cache(batch)
                        if any_cache:
                            payload = any_cache
                        else:
                            raise
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
            cache_key = {
                "data_endpoint": self.data_endpoint,
                "feed": self.feed,
                "start": start_iso,
                "symbols": sorted(str(sym).upper() for sym in batch),
            }
            cached = self._load_cache("bars", cache_key, self.cache_ttl_bars_sec)
            if isinstance(cached, dict):
                needs_enrichment: list[str] = []
                for symbol, rows in cached.items():
                    if isinstance(rows, list):
                        bars_by_symbol.setdefault(symbol, []).extend(rows)
                for sym in batch:
                    cached_rows = cached.get(sym)
                    if not isinstance(cached_rows, list) or not cached_rows:
                        needs_enrichment.append(sym)
                        continue
                    min_ts = self._rows_min_timestamp(cached_rows)
                    if not min_ts or (start_iso and min_ts > str(start_iso)):
                        needs_enrichment.append(sym)
                if needs_enrichment:
                    any_cache = self._load_bars_from_any_cache(needs_enrichment, start_iso)
                    for symbol, rows in any_cache.items():
                        existing = bars_by_symbol.get(symbol)
                        if self._should_replace_rows(existing, rows, start_iso):
                            bars_by_symbol[symbol] = rows
                time.sleep(0.05)
                continue

            batch_bars: dict[str, list[dict[str, Any]]] = {}
            try:
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
                            batch_bars.setdefault(symbol, []).extend(rows)
                    page_token = payload.get("next_page_token") if isinstance(payload, dict) else None
                    if not page_token:
                        break
            except Exception:
                stale = self._load_cache_stale("bars", cache_key)
                if isinstance(stale, dict):
                    for symbol, rows in stale.items():
                        if isinstance(rows, list):
                            batch_bars.setdefault(symbol, []).extend(rows)
                else:
                    any_cache = self._load_bars_from_any_cache(batch, start_iso)
                    if any_cache:
                        for symbol, rows in any_cache.items():
                            if isinstance(rows, list):
                                batch_bars.setdefault(symbol, []).extend(rows)
                    else:
                        raise
            self._save_cache("bars", cache_key, batch_bars)
            for symbol, rows in batch_bars.items():
                bars_by_symbol.setdefault(symbol, []).extend(rows)
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

    def _ticker_mapping_from_cached_submissions(self) -> pd.DataFrame:
        rows: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for path in sorted(self.cache_dir.glob("submissions_*.json")):
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            cik_raw = payload.get("cik")
            cik = ""
            if cik_raw is not None:
                cik = str(cik_raw).strip()
            if not cik:
                stem = path.stem
                if stem.startswith("submissions_"):
                    cik = stem.replace("submissions_", "", 1).strip()
            if not cik:
                continue
            if cik.isdigit():
                cik = cik.zfill(10)
            company_name = str(payload.get("name") or "").strip()
            tickers = payload.get("tickers")
            candidates: list[str] = []
            if isinstance(tickers, list):
                candidates = [str(t) for t in tickers]
            else:
                ticker = payload.get("ticker")
                if ticker:
                    candidates = [str(ticker)]
            for ticker in candidates:
                symbol = ticker.strip().upper()
                if not symbol or not STANDARD_EQUITY_SYMBOL_PATTERN.match(symbol):
                    continue
                key = (symbol, cik)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "symbol": symbol,
                        "cik": cik,
                        "company_name": company_name,
                    }
                )
        if not rows:
            return pd.DataFrame(columns=["symbol", "cik", "company_name"])
        return pd.DataFrame(rows)

    def ticker_mapping(self) -> pd.DataFrame:
        url = "https://www.sec.gov/files/company_tickers.json"
        primary_exc: Exception | None = None
        try:
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
            out = pd.DataFrame(rows)
            if not out.empty:
                return out
        except Exception as exc:
            primary_exc = exc

        fallback = self._ticker_mapping_from_cached_submissions()
        if not fallback.empty:
            return fallback
        if primary_exc is not None:
            raise RuntimeError(
                "Failed to load SEC ticker mapping from both network and local submissions cache."
            ) from primary_exc
        return fallback

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


def pick_facts_with_forms(
    companyfacts: dict[str, Any], tags: list[str], unit: str, allowed_forms: set[str]
) -> list[tuple[str, float, str]]:
    facts = _merged_standard_taxonomy_facts(companyfacts)
    for tag in tags:
        if tag not in facts:
            continue
        units = facts[tag].get("units", {})
        entries = units.get(unit, [])
        candidates: list[tuple[str, float, str, str]] = []
        for item in entries:
            form = item.get("form")
            if form not in allowed_forms:
                continue
            if "val" not in item:
                continue
            end = item.get("end")
            if not end:
                continue
            filed = item.get("filed") or ""
            candidates.append((end, float(item["val"]), str(form), str(filed)))
        if not candidates:
            continue
        # Keep one observation per fiscal period end; prefer most recently filed.
        by_end: dict[str, tuple[float, str, str]] = {}
        for end, val, form, filed in candidates:
            prev = by_end.get(end)
            if prev is None or filed > prev[2]:
                by_end[end] = (val, form, filed)
        collapsed = [(end, val, form) for end, (val, form, _) in by_end.items()]
        collapsed.sort(key=lambda x: x[0], reverse=True)
        return collapsed
    return []


def pick_latest_fact(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[float | None, str | None]:
    values = pick_facts_with_forms(companyfacts, tags, unit, ANNUAL_FORMS)
    if not values:
        return None, None
    _, val, form = values[0]
    return val, form


def pick_latest_and_prev_fact(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[float | None, float | None]:
    values = pick_facts_with_forms(companyfacts, tags, unit, ANNUAL_FORMS)
    if not values:
        return None, None
    latest = values[0][1]
    prev = values[1][1] if len(values) > 1 else None
    return latest, prev


def pick_sum_latest_and_prev_facts(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[float | None, float | None]:
    latest_sum = 0.0
    prev_sum = 0.0
    has_latest = False
    has_prev = False
    for tag in tags:
        values = pick_facts_with_forms(companyfacts, [tag], unit, ANNUAL_FORMS)
        if not values:
            continue
        # Treat expense-like tags as add-backs only when positive.
        latest_val = max(0.0, float(values[0][1]))
        latest_sum += latest_val
        has_latest = has_latest or latest_val > 0
        if len(values) > 1:
            prev_val = max(0.0, float(values[1][1]))
            prev_sum += prev_val
            has_prev = has_prev or prev_val > 0
    return (latest_sum if has_latest else None, prev_sum if has_prev else None)


def pick_latest_and_year_ago_with_forms(
    companyfacts: dict[str, Any], tags: list[str], unit: str, allowed_forms: set[str]
) -> tuple[float | None, float | None]:
    values = pick_facts_with_forms(companyfacts, tags, unit, allowed_forms)
    if not values:
        return None, None
    latest_end = pd.to_datetime(values[0][0], errors="coerce")
    latest = float(values[0][1])
    if pd.isna(latest_end):
        prev = float(values[1][1]) if len(values) > 1 else None
        return latest, prev
    # Prefer a year-ago point for balance-sheet metrics; fallback to second latest.
    year_ago = latest_end - pd.Timedelta(days=300)
    for end, val, _ in values[1:]:
        end_dt = pd.to_datetime(end, errors="coerce")
        if not pd.isna(end_dt) and end_dt <= year_ago:
            return latest, float(val)
    prev = float(values[1][1]) if len(values) > 1 else None
    return latest, prev


def pick_latest_and_prev_ttm(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[float | None, float | None]:
    values = pick_facts_with_forms(companyfacts, tags, unit, QUARTERLY_FORMS)
    if len(values) < 4:
        return None, None
    latest_ttm = float(sum(v for _, v, _ in values[:4]))
    prev_ttm = float(sum(v for _, v, _ in values[4:8])) if len(values) >= 8 else None
    return latest_ttm, prev_ttm


def build_ttm_history(
    companyfacts: dict[str, Any],
    tags: list[str],
    unit: str,
    max_points: int = 16,
) -> list[tuple[str, float]]:
    periodic_values = pick_facts_with_forms(companyfacts, tags, unit, QUARTERLY_FORMS)
    quarterly: list[tuple[pd.Timestamp, float]] = []
    for end, val, form in periodic_values:
        if form in ANNUAL_FORMS:
            continue
        end_dt = pd.to_datetime(end, errors="coerce", utc=True)
        if pd.isna(end_dt):
            continue
        quarterly.append((end_dt, float(val)))
    quarterly.sort(key=lambda x: x[0])

    out: list[tuple[str, float]] = []
    if len(quarterly) >= 4:
        for idx in range(3, len(quarterly)):
            end_dt = quarterly[idx][0]
            ttm = float(sum(quarterly[j][1] for j in range(idx - 3, idx + 1)))
            out.append((end_dt.strftime("%Y-%m-%d"), ttm))
        return out[-int(max(1, max_points)) :]

    annual_values = pick_facts_with_forms(companyfacts, tags, unit, ANNUAL_FORMS)
    annual: list[tuple[pd.Timestamp, float]] = []
    for end, val, _ in annual_values:
        end_dt = pd.to_datetime(end, errors="coerce")
        if pd.isna(end_dt):
            continue
        annual.append((end_dt, float(val)))
    annual.sort(key=lambda x: x[0])
    for end_dt, value in annual:
        out.append((end_dt.strftime("%Y-%m-%d"), float(value)))
    return out[-int(max(1, max_points)) :]


def build_fact_history(
    companyfacts: dict[str, Any],
    tags: list[str],
    unit: str,
    allowed_forms: set[str],
    max_points: int = 24,
) -> list[tuple[str, float]]:
    values = pick_facts_with_forms(companyfacts, tags, unit, allowed_forms)
    out: list[tuple[pd.Timestamp, float]] = []
    for end, val, _ in values:
        end_dt = pd.to_datetime(end, errors="coerce")
        if pd.isna(end_dt):
            continue
        out.append((end_dt, float(val)))
    out.sort(key=lambda x: x[0])
    return [
        (end_dt.strftime("%Y-%m-%d"), float(value))
        for end_dt, value in out[-int(max(1, max_points)) :]
    ]


def serialize_history_pairs(pairs: list[tuple[str, float]]) -> str | None:
    if not pairs:
        return None
    payload = [{"end": end, "value": float(value)} for end, value in pairs]
    return json.dumps(payload, separators=(",", ":"))


def parse_history_pairs(raw: Any) -> list[tuple[pd.Timestamp, float]]:
    if raw is None:
        return []
    if isinstance(raw, float) and np.isnan(raw):
        return []
    data: Any
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except Exception:
            return []
    elif isinstance(raw, list):
        data = raw
    else:
        return []

    out: list[tuple[pd.Timestamp, float]] = []
    for item in data:
        end: Any = None
        value: Any = None
        if isinstance(item, dict):
            end = item.get("end")
            value = item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            end, value = item[0], item[1]
        end_dt = pd.to_datetime(end, errors="coerce", utc=True)
        if pd.isna(end_dt):
            continue
        try:
            val = float(value)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(val):
            continue
        out.append((end_dt.normalize(), val))
    out.sort(key=lambda x: x[0])
    return out


def extract_close_history_from_bars(bars: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, float]]:
    out: list[tuple[pd.Timestamp, float]] = []
    for row in bars:
        ts = pd.to_datetime(row.get("t"), errors="coerce", utc=True)
        if pd.isna(ts):
            continue
        value = row.get("c")
        try:
            close = float(value)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(close) or close <= 0:
            continue
        out.append((ts.normalize(), close))
    out.sort(key=lambda x: x[0])
    return out


def lookup_value_on_or_before(
    points: list[tuple[pd.Timestamp, float]], target_ts: pd.Timestamp
) -> float | None:
    if not points:
        return None
    value: float | None = None
    for ts, val in points:
        if ts <= target_ts:
            value = float(val)
        else:
            break
    return value


def lookup_close_on_or_before(
    closes: list[tuple[pd.Timestamp, float]],
    target_ts: pd.Timestamp,
    max_gap_days: int = 14,
) -> float | None:
    if not closes:
        return None
    max_gap = max(0, int(max_gap_days))
    for ts, close in reversed(closes):
        if ts <= target_ts:
            if max_gap <= 0:
                return float(close)
            gap_days = int((target_ts - ts).days)
            if gap_days <= max_gap:
                return float(close)
            return None
    return None


def compute_historical_valuation_percentile(
    current_multiple: float | None,
    closes: list[tuple[pd.Timestamp, float]],
    denominator_history: list[tuple[pd.Timestamp, float]],
    shares_history: list[tuple[pd.Timestamp, float]],
    current_shares: float | None,
    window_days: int,
    min_observations: int = 3,
) -> tuple[float | None, int]:
    if current_multiple is None or not np.isfinite(current_multiple) or current_multiple <= 0:
        return None, 0
    if not closes or not denominator_history:
        return None, 0

    latest_ts = closes[-1][0]
    start_ts = latest_ts - pd.Timedelta(days=max(30, int(window_days)))
    samples: list[float] = []

    for end_ts, denom in denominator_history:
        if end_ts < start_ts:
            continue
        if not np.isfinite(denom) or denom <= 0:
            continue
        close = lookup_close_on_or_before(closes, end_ts, max_gap_days=14)
        if close is None:
            continue
        shares = lookup_value_on_or_before(shares_history, end_ts)
        if shares is None and current_shares is not None and np.isfinite(current_shares):
            shares = float(current_shares)
        if shares is None or not np.isfinite(shares) or shares <= 0:
            continue
        multiple = float(close) * float(shares) / float(denom)
        if np.isfinite(multiple) and multiple > 0:
            samples.append(multiple)

    obs = len(samples)
    if obs < int(max(1, min_observations)):
        return None, obs

    arr = np.asarray(samples, dtype="float64")
    pct = float(np.mean(arr <= float(current_multiple)))
    if not np.isfinite(pct):
        return None, obs
    return round(pct, 6), obs


def pick_latest_and_prev_with_forms(
    companyfacts: dict[str, Any], tags: list[str], unit: str, allowed_forms: set[str]
) -> tuple[float | None, float | None]:
    values = pick_facts_with_forms(companyfacts, tags, unit, allowed_forms)
    if not values:
        return None, None
    latest = values[0][1]
    prev = values[1][1] if len(values) > 1 else None
    return latest, prev


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
            "return_60d": None,
            "volatility_60d": None,
            "avg_dollar_volume_20d": None,
        }

    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    dollar_volumes: list[float] = []
    # Ensure a stable chronological order before computing trailing statistics.
    sorted_bars = sorted(bars, key=lambda row: str(row.get("t", "")))
    for row in sorted_bars:
        try:
            high = float(row.get("h")) if row.get("h") is not None else None
            low = float(row.get("l")) if row.get("l") is not None else None
            close = float(row.get("c")) if row.get("c") is not None else None
            volume = float(row.get("v")) if row.get("v") is not None else None
        except (TypeError, ValueError):
            continue
        if high is not None:
            highs.append(high)
        if low is not None:
            lows.append(low)
        if close is not None:
            closes.append(close)
        if close is not None and volume is not None:
            dollar_volumes.append(close * volume)

    if not highs or not lows:
        return {
            "drawdown_from_52w_high": None,
            "range_position_52w": None,
            "price_to_sma200": None,
            "days_below_sma200": None,
            "return_20d": None,
            "return_60d": None,
            "volatility_60d": None,
            "avg_dollar_volume_20d": None,
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

    return_60d = None
    if len(closes) >= 61 and closes[-61] > 0:
        return_60d = (price / closes[-61]) - 1.0

    volatility_60d = None
    if len(closes) >= 61:
        window_61 = np.asarray(closes[-61:], dtype="float64")
        daily_ret = (window_61[1:] / window_61[:-1]) - 1.0
        if daily_ret.size > 0:
            vol = float(np.nanstd(daily_ret, ddof=0) * math.sqrt(252.0))
            if np.isfinite(vol):
                volatility_60d = vol

    avg_dollar_volume_20d = None
    if len(dollar_volumes) >= 20:
        adv20 = float(np.mean(np.asarray(dollar_volumes[-20:], dtype="float64")))
        if np.isfinite(adv20):
            avg_dollar_volume_20d = adv20

    return {
        "drawdown_from_52w_high": round(drawdown, 6) if drawdown is not None else None,
        "range_position_52w": round(range_pos, 6) if range_pos is not None else None,
        "price_to_sma200": round(price_to_sma200, 6) if price_to_sma200 is not None else None,
        "days_below_sma200": int(days_below_sma200) if days_below_sma200 is not None else None,
        "return_20d": round(return_20d, 6) if return_20d is not None else None,
        "return_60d": round(return_60d, 6) if return_60d is not None else None,
        "volatility_60d": round(volatility_60d, 6) if volatility_60d is not None else None,
        "avg_dollar_volume_20d": round(avg_dollar_volume_20d, 2)
        if avg_dollar_volume_20d is not None
        else None,
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


def _append_text_fragments(node: Any, sink: list[str]) -> None:
    if node is None:
        return
    if isinstance(node, str):
        text = node.strip()
        if text:
            sink.append(text)
        return
    if isinstance(node, dict):
        for value in node.values():
            _append_text_fragments(value, sink)
        return
    if isinstance(node, list):
        for value in node:
            _append_text_fragments(value, sink)


def build_submissions_disclosure_text(submissions: dict[str, Any], max_recent_forms: int = 20) -> str:
    parts: list[str] = []
    _append_text_fragments(submissions.get("name"), parts)
    _append_text_fragments(submissions.get("sicDescription"), parts)
    _append_text_fragments(submissions.get("business"), parts)

    recent = submissions.get("filings", {}).get("recent", {})
    if isinstance(recent, dict):
        candidate_fields = ["form", "primaryDocDescription", "items", "primaryDocument"]
        for field in candidate_fields:
            values = recent.get(field, [])
            if isinstance(values, list):
                for value in values[: max(0, int(max_recent_forms))]:
                    _append_text_fragments(value, parts)

    if not parts:
        return ""
    return " ".join(parts).lower()


def ai_disclosure_score_from_submissions(
    submissions: dict[str, Any], disclosure_keyword_cap: int = 6
) -> tuple[float, int, int]:
    text = build_submissions_disclosure_text(submissions)
    if not text:
        return 0.0, 0, 0

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
        return 0.0, group_hits, keyword_hits
    group_coverage = group_hits / float(total_groups)
    keyword_density = min(1.0, keyword_hits / max(1.0, float(disclosure_keyword_cap)))
    score = clamp01(0.7 * group_coverage + 0.3 * keyword_density)
    return round(score, 6), int(group_hits), int(keyword_hits)


def ai_backlog_signal_from_companyfacts(
    companyfacts: dict[str, Any], revenue: float | None, cap_ratio: float
) -> float:
    backlog_latest, _ = pick_latest_and_prev_with_forms(
        companyfacts, BACKLOG_TAGS, "USD", QUARTERLY_FORMS
    )
    if backlog_latest is None or revenue is None or revenue <= 0:
        return 0.0
    ratio = float(backlog_latest) / float(revenue)
    if cap_ratio <= 0:
        return 0.0
    return round(clamp01(ratio / float(cap_ratio)), 6)


def ai_etf_consensus_score(watchlist_etf_count: float | int | None, etf_count_saturation: int) -> float:
    if watchlist_etf_count is None:
        return 0.0
    try:
        count = float(watchlist_etf_count)
    except (TypeError, ValueError):
        return 0.0
    saturation = max(1.0, float(etf_count_saturation))
    return round(clamp01(count / saturation), 6)


def bars_return_from_lookback(bars: list[dict[str, Any]], lookback_days: int) -> float | None:
    if not bars or lookback_days <= 0:
        return None
    closes: list[float] = []
    sorted_bars = sorted(bars, key=lambda row: str(row.get("t", "")))
    for row in sorted_bars:
        try:
            close = float(row.get("c")) if row.get("c") is not None else None
        except (TypeError, ValueError):
            close = None
        if close is not None and np.isfinite(close) and close > 0:
            closes.append(close)
    if len(closes) <= lookback_days:
        return None
    base = closes[-(lookback_days + 1)]
    latest = closes[-1]
    if base <= 0:
        return None
    return (latest / base) - 1.0


def ai_market_link_score(
    symbol_return_20d: float | None,
    symbol_return_60d: float | None,
    benchmark_return_20d: float | None,
    benchmark_return_60d: float | None,
    tol_20d: float,
    tol_60d: float,
) -> float:
    score_20 = 0.5
    if symbol_return_20d is not None and benchmark_return_20d is not None and tol_20d > 0:
        score_20 = clamp01(1.0 - (abs(symbol_return_20d - benchmark_return_20d) / tol_20d))

    score_60 = 0.5
    if symbol_return_60d is not None and benchmark_return_60d is not None and tol_60d > 0:
        score_60 = clamp01(1.0 - (abs(symbol_return_60d - benchmark_return_60d) / tol_60d))

    return round(clamp01(0.4 * score_20 + 0.6 * score_60), 6)


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
    bucket_to_etfs: dict[str, list[str]] = {
        "core_ai": list(config.watchlist_core_etfs),
        "ai_enabler": list(config.watchlist_enabler_etfs),
        "ai_peripheral": list(config.watchlist_peripheral_etfs),
    }
    bucket_counts: dict[str, dict[str, int]] = {
        bucket: {} for bucket in bucket_to_etfs.keys()
    }
    bucket_etf_hits: dict[str, dict[str, list[str]]] = {
        bucket: {} for bucket in bucket_to_etfs.keys()
    }

    for bucket, etf_list in bucket_to_etfs.items():
        for etf in etf_list:
            symbols, _ = fetch_stockanalysis_etf_symbols(etf, config.watchlist_fetch_timeout_sec)
            for symbol in symbols:
                bucket_counts[bucket][symbol] = bucket_counts[bucket].get(symbol, 0) + 1
                bucket_etf_hits[bucket].setdefault(symbol, []).append(str(etf).upper())

    now_iso = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for bucket, counts in bucket_counts.items():
        for symbol, n in counts.items():
            rows.append(
                {
                    "symbol": symbol,
                    "bucket": bucket,
                    "etf_count": int(n),
                    "etfs": ",".join(sorted(set(bucket_etf_hits[bucket].get(symbol, [])))),
                    "enabled": 1,
                    "updated_utc": now_iso,
                }
            )
    return pd.DataFrame(rows)


WATCHLIST_SCORE_COLUMNS = [
    "symbol",
    "watchlist_bucket",
    "watchlist_etf_count",
    "watchlist_etfs",
]


def watchlist_rows_to_scores(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)
    required_cols = {"symbol", "bucket", "etf_count", "etfs", "enabled"}
    missing = sorted(required_cols.difference(set(raw.columns)))
    if missing:
        raise ValueError(
            f"watchlist csv missing required columns: {', '.join(missing)}; "
            "expected: symbol,bucket,etf_count,etfs,enabled,updated_utc"
        )
    work = raw.copy()
    work["symbol"] = work["symbol"].apply(normalize_equity_symbol)
    work["bucket"] = work["bucket"].astype(str).str.strip().str.lower()
    work["enabled"] = (
        work["enabled"].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})
    )
    work["etf_count"] = pd.to_numeric(work["etf_count"], errors="coerce").fillna(0).astype(int)
    work["etfs"] = work["etfs"].astype(str)
    work = work[(work["symbol"] != "") & work["enabled"]]
    if work.empty:
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)

    rows: dict[str, dict[str, Any]] = {}
    for row in work.itertuples(index=False):
        symbol = str(row.symbol)
        bucket = str(row.bucket)
        etfs = str(row.etfs)
        if symbol not in rows:
            rows[symbol] = {
                "symbol": symbol,
                "watchlist_bucket": bucket,
                "watchlist_etf_count": 0,
                "watchlist_etfs": etfs,
            }
        prev_bucket = str(rows[symbol]["watchlist_bucket"])
        if prev_bucket != bucket and bucket not in prev_bucket.split(","):
            rows[symbol]["watchlist_bucket"] = f"{prev_bucket},{bucket}" if prev_bucket else bucket
        if etfs:
            prev = set(x for x in str(rows[symbol]["watchlist_etfs"]).split(",") if x)
            now = set(x for x in etfs.split(",") if x)
            rows[symbol]["watchlist_etfs"] = ",".join(sorted(prev.union(now)))
        else:
            # Keep a deterministic empty list representation for count recalculation.
            rows[symbol]["watchlist_etfs"] = ",".join(
                sorted(x for x in str(rows[symbol]["watchlist_etfs"]).split(",") if x)
            )

        etf_tokens = [x for x in str(rows[symbol]["watchlist_etfs"]).split(",") if x]
        rows[symbol]["watchlist_etf_count"] = len(set(etf_tokens))

    out = pd.DataFrame(rows.values())
    return out[WATCHLIST_SCORE_COLUMNS]


def load_watchlist_scores(config: ScanConfig) -> pd.DataFrame:
    path = Path(config.watchlist_csv_path)
    if not path.exists():
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)
    raw = pd.read_csv(path)
    return watchlist_rows_to_scores(raw)


def percentile_floor_mask(series: pd.Series, q: float) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(False, index=series.index, dtype="bool")
    threshold = float(valid.quantile(q))
    return s.fillna(-np.inf) >= threshold


def percentile_cap_mask(series: pd.Series, q: float) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(False, index=series.index, dtype="bool")
    threshold = float(valid.quantile(q))
    return s.fillna(np.inf) <= threshold


def robust_normalize_score(series: pd.Series, lower_q: float, upper_q: float) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce").astype(float)
    valid = x.dropna()
    if valid.empty:
        return pd.Series([0.5] * len(x), index=x.index, dtype="float64")
    lo = float(valid.quantile(lower_q))
    hi = float(valid.quantile(upper_q))
    if not np.isfinite(lo):
        lo = float(valid.min())
    if not np.isfinite(hi):
        hi = float(valid.max())
    if hi < lo:
        lo, hi = hi, lo
    clipped = x.clip(lower=lo, upper=hi)
    mean = float(clipped.mean())
    std = float(clipped.std(ddof=0))
    if not np.isfinite(std) or std <= 1e-12:
        return pd.Series([0.5] * len(x), index=x.index, dtype="float64")
    z = (clipped - mean) / std
    # Map z-score to [0,1], reducing outlier dominance while preserving order.
    norm = 1.0 / (1.0 + np.exp(-z))
    # Missing inputs should be neutral, not NaN, to keep composite scores stable.
    return pd.to_numeric(norm, errors="coerce").fillna(0.5)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce").astype(float)
    den = pd.to_numeric(denominator, errors="coerce").astype(float)
    out = pd.Series(np.nan, index=num.index, dtype=float)
    valid = den.notna() & (den != 0) & num.notna()
    out.loc[valid] = num.loc[valid] / den.loc[valid]
    return out


def safe_yoy(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous is None:
        return None
    if previous == 0:
        return None
    try:
        return float(latest) / float(previous) - 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


HIGH_COVERAGE_HARD_FILTER_METRICS = {
    "fundamental_quality_score",
    "net_debt_to_ebitda",
    "current_ratio",
    "ocf_to_net_income",
    "accrual_ratio",
    "shares_yoy",
    "ps_hist_percentile",
    "pe_hist_percentile",
    "adv_participation",
    "estimated_slippage_bps",
}
MEDIUM_COVERAGE_HARD_FILTER_METRICS = {
    "interest_coverage",
    "receivables_growth_gap",
    "expectation_proxy",
    "cycle_proxy",
}
LOW_COVERAGE_HARD_FILTER_METRICS = {
    "current_debt_ratio",
    "inventory_growth_gap",
}


def hard_filter_metric_enabled(metric: str, config: ScanConfig, cp: dict[str, Any]) -> bool:
    mode = str(config.metric_hard_filter_coverage_mode or "high_coverage_only").strip().lower()
    if metric in LOW_COVERAGE_HARD_FILTER_METRICS:
        if metric == "current_debt_ratio" and cp.get("hard_filter_current_debt_ratio", False):
            return True
        if metric == "inventory_growth_gap" and cp.get("hard_filter_inventory_growth_gap", False):
            return True
        if bool(config.force_hard_filter_low_coverage_metrics):
            return True
        return False
    if mode == "all_metrics":
        return True
    if mode == "balanced":
        return metric in HIGH_COVERAGE_HARD_FILTER_METRICS or metric in MEDIUM_COVERAGE_HARD_FILTER_METRICS
    # high_coverage_only
    return metric in HIGH_COVERAGE_HARD_FILTER_METRICS


def merge_soft_score_weights(
    base_weights: dict[str, float] | None, soft_weights: dict[str, float]
) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(base_weights, dict):
        for k, v in base_weights.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    for k, v in soft_weights.items():
        if k not in out:
            out[k] = float(v)
    return out


def fundamental_quality_score_from_metrics(
    net_debt_to_ebitda: float | None,
    interest_coverage: float | None,
    current_ratio: float | None,
    ocf_to_net_income: float | None,
    accrual_ratio: float | None,
) -> float:
    # Neutral fallback for missing inputs keeps coverage broad while rewarding quality.
    nd_component = 0.5
    if net_debt_to_ebitda is not None:
        if net_debt_to_ebitda <= 0:
            nd_component = 1.0
        else:
            nd_component = clamp01(1.0 - (float(net_debt_to_ebitda) / 6.0))

    ic_component = 0.5
    if interest_coverage is not None:
        ic_component = clamp01(float(interest_coverage) / 8.0)

    cr_component = 0.5
    if current_ratio is not None:
        cr_component = clamp01(float(current_ratio) / 2.0)

    ocf_component = 0.5
    if ocf_to_net_income is not None:
        ocf_component = clamp01(float(ocf_to_net_income) / 1.2)

    accrual_component = 0.5
    if accrual_ratio is not None:
        accrual_component = clamp01(1.0 - abs(float(accrual_ratio)))

    return round(
        float(np.mean([nd_component, ic_component, cr_component, ocf_component, accrual_component])),
        6,
    )


def compute_price_history_percentile(
    bars: list[dict[str, Any]], window_days: int
) -> float | None:
    if not bars:
        return None
    closes: list[float] = []
    sorted_bars = sorted(bars, key=lambda row: str(row.get("t", "")))
    for row in sorted_bars:
        value = row.get("c")
        if value is None:
            continue
        try:
            close = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(close) and close > 0:
            closes.append(close)
    if len(closes) < 20:
        return None
    window = closes[-int(max(20, window_days)) :]
    latest = window[-1]
    arr = np.asarray(window, dtype="float64")
    pct = float(np.mean(arr <= latest))
    if np.isfinite(pct):
        return round(pct, 6)
    return None


def apply_group_caps(
    frame: pd.DataFrame,
    max_per_sector: int | None,
    max_per_watchlist_etf_source: int | None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    out_rows: list[pd.Series] = []
    sector_count: dict[str, int] = {}
    etf_count: dict[str, int] = {}

    for _, row in frame.iterrows():
        sector_key = str(row.get("sic", "") or "")[:2]
        etf_tokens = [x for x in str(row.get("watchlist_etfs", "") or "").split(",") if x]
        primary_etf = sorted(etf_tokens)[0] if etf_tokens else ""

        if max_per_sector is not None and sector_key:
            if sector_count.get(sector_key, 0) >= int(max_per_sector):
                continue
        if max_per_watchlist_etf_source is not None and primary_etf:
            if etf_count.get(primary_etf, 0) >= int(max_per_watchlist_etf_source):
                continue

        out_rows.append(row)
        if sector_key:
            sector_count[sector_key] = sector_count.get(sector_key, 0) + 1
        if primary_etf:
            etf_count[primary_etf] = etf_count.get(primary_etf, 0) + 1

    if not out_rows:
        return frame.iloc[0:0].copy()
    return pd.DataFrame(out_rows).reset_index(drop=True)


def watchlist_member_mask(frame: pd.DataFrame) -> pd.Series:
    if "watchlist_bucket" in frame.columns:
        bucket = frame["watchlist_bucket"].astype(str).str.strip()
    else:
        bucket = pd.Series("", index=frame.index, dtype="object")
    if "watchlist_etf_count" in frame.columns:
        etf_count = pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
    else:
        etf_count = pd.Series(0, index=frame.index, dtype="float64")
    return (bucket != "") | (etf_count > 0)


def channel_bucket_mask(frame: pd.DataFrame, channel_name: str) -> pd.Series:
    if "watchlist_bucket" not in frame.columns:
        return pd.Series(False, index=frame.index, dtype="bool")
    bucket = frame["watchlist_bucket"].fillna("").astype(str)
    pattern = rf"(?:^|,){re.escape(str(channel_name))}(?:,|$)"
    return bucket.str.contains(pattern, regex=True)


def passes_sic_filters(
    sic: str | None,
    exclude_codes: list[str],
) -> bool:
    if not sic:
        return False
    sic = str(sic)
    if exclude_codes and sic in exclude_codes:
        return False
    return True


def resolve_channel_profile(
    config: ScanConfig, channel_name: str, profile: dict[str, Any]
) -> dict[str, Any]:
    exclude_codes = sorted(set(str(x).strip() for x in config.exclude_sic_codes if str(x).strip()))
    score_weights = merge_soft_score_weights(
        profile.get("score_weights", {}),
        config.low_coverage_soft_score_weights,
    )

    return {
        "name": channel_name,
        "require_positive_revenue": bool(
            profile.get("require_positive_revenue", config.require_positive_revenue)
        ),
        "require_positive_net_income": bool(
            profile.get("require_positive_net_income", config.require_positive_net_income)
        ),
        "require_positive_operating_cash_flow": bool(
            profile.get(
                "require_positive_operating_cash_flow", config.require_positive_operating_cash_flow
            )
        ),
        "require_positive_free_cash_flow": bool(
            profile.get("require_positive_free_cash_flow", config.require_positive_free_cash_flow)
        ),
        "require_positive_ebit": bool(profile.get("require_positive_ebit", config.require_positive_ebit)),
        "require_channel_bucket_match": bool(
            profile.get("require_channel_bucket_match", config.require_channel_bucket_match)
        ),
        "min_watchlist_etf_count": int(profile.get("min_watchlist_etf_count", 1)),
        "min_ai_link_score": (
            None
            if profile.get("min_ai_link_score") is None
            else float(profile.get("min_ai_link_score"))
        ),
        "min_avg_dollar_volume_20d": (
            None
            if profile.get("min_avg_dollar_volume_20d", config.min_avg_dollar_volume_20d) is None
            else float(profile.get("min_avg_dollar_volume_20d", config.min_avg_dollar_volume_20d))
        ),
        "min_net_margin": (
            None
            if profile.get("min_net_margin", config.min_net_margin) is None
            else float(profile.get("min_net_margin", config.min_net_margin))
        ),
        "min_revenue": (
            None
            if profile.get("min_revenue", config.min_revenue) is None
            else float(profile.get("min_revenue", config.min_revenue))
        ),
        "min_net_income": (
            None
            if profile.get("min_net_income", config.min_net_income) is None
            else float(profile.get("min_net_income", config.min_net_income))
        ),
        "min_operating_cash_flow": (
            None
            if profile.get("min_operating_cash_flow", config.min_operating_cash_flow) is None
            else float(profile.get("min_operating_cash_flow", config.min_operating_cash_flow))
        ),
        "min_free_cash_flow": (
            None
            if profile.get("min_free_cash_flow", config.min_free_cash_flow) is None
            else float(profile.get("min_free_cash_flow", config.min_free_cash_flow))
        ),
        "min_ebit": (
            None
            if profile.get("min_ebit", config.min_ebit) is None
            else float(profile.get("min_ebit", config.min_ebit))
        ),
        "max_ev_to_ebit": (
            None
            if profile.get("max_ev_to_ebit", config.max_ev_to_ebit) is None
            else float(profile.get("max_ev_to_ebit", config.max_ev_to_ebit))
        ),
        "max_ps": (
            None
            if profile.get("max_ps", config.max_ps) is None
            else float(profile.get("max_ps", config.max_ps))
        ),
        "max_pe": (
            None
            if profile.get("max_pe", config.max_pe) is None
            else float(profile.get("max_pe", config.max_pe))
        ),
        "min_fcf_yield": (
            None
            if profile.get("min_fcf_yield", config.min_fcf_yield) is None
            else float(profile.get("min_fcf_yield", config.min_fcf_yield))
        ),
        "max_ps_percentile_in_sic": (
            None
            if profile.get("max_ps_percentile_in_sic", config.max_ps_percentile_in_sic) is None
            else float(profile.get("max_ps_percentile_in_sic", config.max_ps_percentile_in_sic))
        ),
        "max_pe_percentile_in_sic": (
            None
            if profile.get("max_pe_percentile_in_sic", config.max_pe_percentile_in_sic) is None
            else float(profile.get("max_pe_percentile_in_sic", config.max_pe_percentile_in_sic))
        ),
        "min_revenue_yoy": (
            None
            if profile.get("min_revenue_yoy", config.min_revenue_yoy) is None
            else float(profile.get("min_revenue_yoy", config.min_revenue_yoy))
        ),
        "min_net_income_yoy": (
            None
            if profile.get("min_net_income_yoy", config.min_net_income_yoy) is None
            else float(profile.get("min_net_income_yoy", config.min_net_income_yoy))
        ),
        "min_fundamental_quality_score": (
            None
            if profile.get("min_fundamental_quality_score", config.min_fundamental_quality_score) is None
            else float(profile.get("min_fundamental_quality_score", config.min_fundamental_quality_score))
        ),
        "max_net_debt_to_ebitda": (
            None
            if profile.get("max_net_debt_to_ebitda", config.max_net_debt_to_ebitda) is None
            else float(profile.get("max_net_debt_to_ebitda", config.max_net_debt_to_ebitda))
        ),
        "min_interest_coverage": (
            None
            if profile.get("min_interest_coverage", config.min_interest_coverage) is None
            else float(profile.get("min_interest_coverage", config.min_interest_coverage))
        ),
        "max_current_debt_ratio": (
            None
            if profile.get("max_current_debt_ratio", config.max_current_debt_ratio) is None
            else float(profile.get("max_current_debt_ratio", config.max_current_debt_ratio))
        ),
        "min_current_ratio": (
            None
            if profile.get("min_current_ratio", config.min_current_ratio) is None
            else float(profile.get("min_current_ratio", config.min_current_ratio))
        ),
        "min_ocf_to_net_income": (
            None
            if profile.get("min_ocf_to_net_income", config.min_ocf_to_net_income) is None
            else float(profile.get("min_ocf_to_net_income", config.min_ocf_to_net_income))
        ),
        "max_accrual_ratio": (
            None
            if profile.get("max_accrual_ratio", config.max_accrual_ratio) is None
            else float(profile.get("max_accrual_ratio", config.max_accrual_ratio))
        ),
        "max_receivables_growth_gap": (
            None
            if profile.get("max_receivables_growth_gap", config.max_receivables_growth_gap) is None
            else float(profile.get("max_receivables_growth_gap", config.max_receivables_growth_gap))
        ),
        "max_inventory_growth_gap": (
            None
            if profile.get("max_inventory_growth_gap", config.max_inventory_growth_gap) is None
            else float(profile.get("max_inventory_growth_gap", config.max_inventory_growth_gap))
        ),
        "max_shares_yoy": (
            None
            if profile.get("max_shares_yoy", config.max_shares_yoy) is None
            else float(profile.get("max_shares_yoy", config.max_shares_yoy))
        ),
        "max_ps_hist_percentile": (
            None
            if profile.get("max_ps_hist_percentile", config.max_ps_hist_percentile) is None
            else float(profile.get("max_ps_hist_percentile", config.max_ps_hist_percentile))
        ),
        "max_pe_hist_percentile": (
            None
            if profile.get("max_pe_hist_percentile", config.max_pe_hist_percentile) is None
            else float(profile.get("max_pe_hist_percentile", config.max_pe_hist_percentile))
        ),
        "min_expectation_proxy": (
            None
            if profile.get("min_expectation_proxy", config.min_expectation_proxy) is None
            else float(profile.get("min_expectation_proxy", config.min_expectation_proxy))
        ),
        "min_cycle_proxy": (
            None
            if profile.get("min_cycle_proxy", config.min_cycle_proxy) is None
            else float(profile.get("min_cycle_proxy", config.min_cycle_proxy))
        ),
        "max_adv_participation": (
            None
            if profile.get("max_adv_participation", config.max_adv_participation) is None
            else float(profile.get("max_adv_participation", config.max_adv_participation))
        ),
        "max_estimated_slippage_bps": (
            None
            if profile.get("max_estimated_slippage_bps", config.max_estimated_slippage_bps) is None
            else float(profile.get("max_estimated_slippage_bps", config.max_estimated_slippage_bps))
        ),
        "hard_filter_current_debt_ratio": bool(
            profile.get("hard_filter_current_debt_ratio", config.force_hard_filter_low_coverage_metrics)
        ),
        "hard_filter_inventory_growth_gap": bool(
            profile.get("hard_filter_inventory_growth_gap", config.force_hard_filter_low_coverage_metrics)
        ),
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
        "min_return_20d": (
            None
            if profile.get("min_return_20d", config.min_return_20d) is None
            else float(profile.get("min_return_20d", config.min_return_20d))
        ),
        "min_return_60d": (
            None
            if profile.get("min_return_60d", config.min_return_60d) is None
            else float(profile.get("min_return_60d", config.min_return_60d))
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
        "min_drawdown_percentile": (
            None
            if profile.get("min_drawdown_percentile", config.min_drawdown_percentile) is None
            else float(profile.get("min_drawdown_percentile", config.min_drawdown_percentile))
        ),
        "min_avg_dollar_volume_20d_percentile": (
            None
            if profile.get(
                "min_avg_dollar_volume_20d_percentile", config.min_avg_dollar_volume_20d_percentile
            )
            is None
            else float(
                profile.get(
                    "min_avg_dollar_volume_20d_percentile", config.min_avg_dollar_volume_20d_percentile
                )
            )
        ),
        "max_60d_volatility_percentile": (
            None
            if profile.get("max_60d_volatility_percentile", config.max_60d_volatility_percentile) is None
            else float(profile.get("max_60d_volatility_percentile", config.max_60d_volatility_percentile))
        ),
        "exclude_sic_codes": exclude_codes,
        "score_weights": score_weights,
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
        cache_dir=Path(config.cache_dir),
        cache_enabled=config.alpaca_cache_enabled,
        cache_ttl_assets_sec=config.alpaca_cache_ttl_assets_sec,
        cache_ttl_snapshots_sec=config.alpaca_cache_ttl_snapshots_sec,
        cache_ttl_bars_sec=config.alpaca_cache_ttl_bars_sec,
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
    alpaca: AlpacaClient,
    sec: SecClient,
    config: ScanConfig,
    asset_status: str = "active",
    symbol_allowlist: set[str] | None = None,
) -> pd.DataFrame:
    assets = alpaca.get_assets(status=asset_status)
    df_assets = pd.DataFrame(assets)
    df_assets = df_assets[df_assets["tradable"] == True].copy()
    if config.enabled_exchanges:
        df_assets = df_assets[df_assets["exchange"].isin(config.enabled_exchanges)]
    df_assets["symbol"] = df_assets["symbol"].str.upper()
    if symbol_allowlist is not None:
        df_assets = df_assets[df_assets["symbol"].isin(symbol_allowlist)].copy()

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


def load_one_fundamental(sec: SecClient, symbol: str, cik: str, config: ScanConfig) -> dict[str, Any]:
    submissions = sec.get_submissions(cik)
    companyfacts = sec.get_companyfacts(cik)

    sic = submissions.get("sic")
    sic_desc = submissions.get("sicDescription")

    def pick_flow_pair(tags: list[str], unit: str) -> tuple[float | None, float | None, str]:
        if config.use_ttm_metrics:
            latest, prev = pick_latest_and_prev_ttm(companyfacts, tags, unit)
            if latest is not None:
                return latest, prev, "ttm"
        latest, prev = pick_latest_and_prev_fact(companyfacts, tags, unit)
        if latest is not None:
            return latest, prev, "annual"
        latest, prev = pick_latest_and_prev_with_forms(companyfacts, tags, unit, QUARTERLY_FORMS)
        if latest is not None:
            return latest, prev, "periodic"
        return None, None, "missing"

    def pick_latest_with_forms(tags: list[str], unit: str) -> tuple[float | None, float | None]:
        return pick_latest_and_year_ago_with_forms(companyfacts, tags, unit, QUARTERLY_FORMS)

    def pick_sum_positive_flows(tags: list[str]) -> tuple[float | None, float | None]:
        latest_sum = 0.0
        prev_sum = 0.0
        has_latest = False
        has_prev = False
        for tag in tags:
            latest = None
            prev = None
            if config.use_ttm_metrics:
                latest, prev = pick_latest_and_prev_ttm(companyfacts, [tag], "USD")
            if latest is None:
                values = pick_facts_with_forms(companyfacts, [tag], "USD", ANNUAL_FORMS)
                if values:
                    latest = float(values[0][1])
                    prev = float(values[1][1]) if len(values) > 1 else None
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

    revenue, revenue_prev, revenue_form = pick_flow_pair(REVENUE_TAGS, "USD")
    net_income, net_income_prev, net_income_form = pick_flow_pair(NET_INCOME_TAGS, "USD")
    ocf, ocf_prev, operating_cash_flow_form = pick_flow_pair(OPERATING_CASH_FLOW_TAGS, "USD")
    capex_raw, _, _ = pick_flow_pair(CAPEX_TAGS, "USD")
    ebit, ebit_prev, ebit_form = pick_flow_pair(EBIT_TAGS, "USD")
    interest_expense, interest_expense_prev, _ = pick_flow_pair(INTEREST_EXPENSE_TAGS, "USD")
    da, da_prev, _ = pick_flow_pair(DA_TAGS, "USD")

    shares, shares_prev = pick_latest_with_forms(SHARES_TAGS, "shares")
    revenue_ttm_history = build_ttm_history(companyfacts, REVENUE_TAGS, "USD")
    net_income_ttm_history = build_ttm_history(companyfacts, NET_INCOME_TAGS, "USD")
    shares_history = build_fact_history(companyfacts, SHARES_TAGS, "shares", QUARTERLY_FORMS)
    shares_form = "periodic" if shares is not None else None
    cash_and_equivalents, _ = pick_latest_with_forms(CASH_AND_EQUIVALENTS_TAGS, "USD")
    debt_long_term, _ = pick_latest_with_forms(LONG_TERM_DEBT_TAGS, "USD")
    debt_current, _ = pick_latest_with_forms(CURRENT_DEBT_TAGS, "USD")
    assets_current, _ = pick_latest_with_forms(ASSETS_CURRENT_TAGS, "USD")
    liabilities_current, _ = pick_latest_with_forms(LIABILITIES_CURRENT_TAGS, "USD")
    receivables_current, receivables_prev = pick_latest_with_forms(RECEIVABLES_CURRENT_TAGS, "USD")
    inventory_current, inventory_prev = pick_latest_with_forms(INVENTORY_TAGS, "USD")

    nonrecurring_addback_raw, nonrecurring_addback_prev_raw = pick_sum_positive_flows(
        NONRECURRING_EXPENSE_TAGS
    )
    nonrecurring_gain_raw, nonrecurring_gain_prev_raw = pick_sum_positive_flows(NONRECURRING_GAIN_TAGS)

    capex = abs(capex_raw) if capex_raw is not None else None
    free_cash_flow = (ocf - capex) if (ocf is not None and capex is not None) else None
    total_debt = None
    if debt_long_term is not None or debt_current is not None:
        total_debt = float(debt_long_term or 0.0) + float(debt_current or 0.0)
    net_debt = None
    if total_debt is not None or cash_and_equivalents is not None:
        net_debt = float(total_debt or 0.0) - float(cash_and_equivalents or 0.0)
    revenue_yoy = safe_yoy(revenue, revenue_prev)
    net_income_yoy = safe_yoy(net_income, net_income_prev)
    ebit_yoy = safe_yoy(ebit, ebit_prev)
    ocf_yoy = safe_yoy(ocf, ocf_prev)
    shares_yoy = safe_yoy(shares, shares_prev)
    receivables_yoy = safe_yoy(receivables_current, receivables_prev)
    inventory_yoy = safe_yoy(inventory_current, inventory_prev)
    da_yoy = safe_yoy(da, da_prev)
    addback_cap_ratio = config.nonrecurring_addback_revenue_cap
    nonrecurring_addback = nonrecurring_addback_raw
    nonrecurring_addback_prev = nonrecurring_addback_prev_raw
    if addback_cap_ratio is not None:
        if nonrecurring_addback is not None and revenue is not None and revenue > 0:
            nonrecurring_addback = min(nonrecurring_addback, float(revenue) * float(addback_cap_ratio))
        if nonrecurring_addback_prev is not None and revenue_prev is not None and revenue_prev > 0:
            nonrecurring_addback_prev = min(
                nonrecurring_addback_prev,
                float(revenue_prev) * float(addback_cap_ratio),
            )
    nonrecurring_gain = nonrecurring_gain_raw
    nonrecurring_gain_prev = nonrecurring_gain_prev_raw
    if addback_cap_ratio is not None:
        if nonrecurring_gain is not None and revenue is not None and revenue > 0:
            nonrecurring_gain = min(nonrecurring_gain, float(revenue) * float(addback_cap_ratio))
        if nonrecurring_gain_prev is not None and revenue_prev is not None and revenue_prev > 0:
            nonrecurring_gain_prev = min(
                nonrecurring_gain_prev,
                float(revenue_prev) * float(addback_cap_ratio),
            )

    adjusted_net_income = None
    if net_income is not None:
        adjusted_net_income = (
            float(net_income)
            + float(nonrecurring_addback or 0.0)
            - float(nonrecurring_gain or 0.0)
        )
    adjusted_ebit = None
    if ebit is not None:
        adjusted_ebit = (
            float(ebit) + float(nonrecurring_addback or 0.0) - float(nonrecurring_gain or 0.0)
        )
    adjusted_net_income_prev = None
    if net_income_prev is not None:
        adjusted_net_income_prev = (
            float(net_income_prev)
            + float(nonrecurring_addback_prev or 0.0)
            - float(nonrecurring_gain_prev or 0.0)
        )
    adjusted_ebit_prev = None
    if ebit_prev is not None:
        adjusted_ebit_prev = (
            float(ebit_prev)
            + float(nonrecurring_addback_prev or 0.0)
            - float(nonrecurring_gain_prev or 0.0)
        )
    adjusted_net_income_yoy = safe_yoy(adjusted_net_income, adjusted_net_income_prev)
    adjusted_ebit_yoy = safe_yoy(adjusted_ebit, adjusted_ebit_prev)
    adjusted_da = float(da or 0.0) + float(nonrecurring_addback or 0.0) - float(nonrecurring_gain or 0.0)
    adjusted_ebitda = (float(adjusted_ebit) + adjusted_da) if adjusted_ebit is not None else None

    ai_disclosure_score, ai_disclosure_group_hits, ai_disclosure_keyword_hits = (
        ai_disclosure_score_from_submissions(
            submissions, disclosure_keyword_cap=config.ai_link_disclosure_keyword_cap
        )
    )
    ai_backlog_signal = ai_backlog_signal_from_companyfacts(
        companyfacts, revenue=revenue, cap_ratio=config.ai_link_backlog_ratio_cap
    )

    interest_expense_abs = abs(float(interest_expense)) if interest_expense is not None else None
    interest_coverage = None
    if adjusted_ebit is not None and interest_expense_abs is not None and interest_expense_abs > 0:
        interest_coverage = float(adjusted_ebit) / interest_expense_abs

    net_debt_to_ebitda = None
    if net_debt is not None and adjusted_ebitda is not None and adjusted_ebitda != 0:
        net_debt_to_ebitda = float(net_debt) / float(adjusted_ebitda)

    current_ratio = None
    if assets_current is not None and liabilities_current not in (None, 0):
        current_ratio = float(assets_current) / float(liabilities_current)

    current_debt_ratio_reported = None
    current_debt_ratio_inferred = None
    current_debt_ratio = None
    current_debt_ratio_source = "missing"
    if debt_current is not None and assets_current not in (None, 0):
        current_debt_ratio_reported = float(debt_current) / float(assets_current)
        current_debt_ratio = current_debt_ratio_reported
        current_debt_ratio_source = "reported"
    elif assets_current not in (None, 0):
        if total_debt is not None and total_debt <= 0:
            current_debt_ratio_inferred = 0.0
            current_debt_ratio = current_debt_ratio_inferred
            current_debt_ratio_source = "inferred_zero_nonpositive_total_debt"
        elif total_debt is not None and liabilities_current not in (None, 0):
            inferred_current_debt = min(max(float(total_debt), 0.0), float(liabilities_current))
            current_debt_ratio_inferred = inferred_current_debt / float(assets_current)
            current_debt_ratio = current_debt_ratio_inferred
            current_debt_ratio_source = "inferred_total_debt_capped_by_current_liabilities"

    ocf_to_net_income = None
    if ocf is not None and adjusted_net_income not in (None, 0):
        ocf_to_net_income = float(ocf) / float(adjusted_net_income)

    accrual_ratio = None
    if adjusted_net_income is not None and ocf is not None and assets_current not in (None, 0):
        accrual_ratio = (float(adjusted_net_income) - float(ocf)) / float(assets_current)

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
        # Inventory is often not applicable for software/service names; use neutral fallback.
        inventory_not_applicable = (
            (inventory_current is None and inventory_prev is None)
            or ((inventory_current in (0, 0.0)) and (inventory_prev in (0, 0.0)))
        )
        if inventory_not_applicable:
            inventory_growth_gap_inferred = 0.0
            inventory_growth_gap = inventory_growth_gap_inferred
            inventory_growth_gap_source = "inferred_inventory_not_applicable"

    quality_score = fundamental_quality_score_from_metrics(
        net_debt_to_ebitda=net_debt_to_ebitda,
        interest_coverage=interest_coverage,
        current_ratio=current_ratio,
        ocf_to_net_income=ocf_to_net_income,
        accrual_ratio=accrual_ratio,
    )
    return {
        "symbol": symbol,
        "sic": str(sic) if sic is not None else None,
        "sic_description": sic_desc,
        "revenue": revenue,
        "revenue_form": revenue_form,
        "net_income": net_income,
        "net_income_form": net_income_form,
        "shares_outstanding": shares,
        "revenue_ttm_history_json": serialize_history_pairs(revenue_ttm_history),
        "net_income_ttm_history_json": serialize_history_pairs(net_income_ttm_history),
        "shares_history_json": serialize_history_pairs(shares_history),
        "shares_form": shares_form,
        "operating_cash_flow": ocf,
        "operating_cash_flow_form": operating_cash_flow_form,
        "capex": capex,
        "free_cash_flow": free_cash_flow,
        "ebit": ebit,
        "ebit_form": ebit_form,
        "cash_and_equivalents": cash_and_equivalents,
        "total_debt": total_debt,
        "net_debt": net_debt,
        "interest_expense": interest_expense_abs,
        "depreciation_and_amortization": da,
        "current_assets": assets_current,
        "current_liabilities": liabilities_current,
        "receivables_current": receivables_current,
        "inventory_current": inventory_current,
        "revenue_yoy": revenue_yoy,
        "net_income_yoy": net_income_yoy,
        "ebit_yoy": ebit_yoy,
        "da_yoy": da_yoy,
        "operating_cash_flow_yoy": ocf_yoy,
        "shares_yoy": shares_yoy,
        "receivables_yoy": receivables_yoy,
        "inventory_yoy": inventory_yoy,
        "receivables_growth_gap": receivables_growth_gap,
        "inventory_growth_gap": inventory_growth_gap,
        "nonrecurring_expense_addback": nonrecurring_addback,
        "nonrecurring_gain_subtraction": nonrecurring_gain,
        "adjusted_net_income": adjusted_net_income,
        "adjusted_ebit": adjusted_ebit,
        "adjusted_ebitda": adjusted_ebitda,
        "adjusted_net_income_yoy": adjusted_net_income_yoy,
        "adjusted_ebit_yoy": adjusted_ebit_yoy,
        "interest_coverage": interest_coverage,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "current_ratio": current_ratio,
        "current_debt_ratio_reported": current_debt_ratio_reported,
        "current_debt_ratio_inferred": current_debt_ratio_inferred,
        "current_debt_ratio": current_debt_ratio,
        "current_debt_ratio_source": current_debt_ratio_source,
        "ocf_to_net_income": ocf_to_net_income,
        "accrual_ratio": accrual_ratio,
        "inventory_growth_gap_reported": inventory_growth_gap_reported,
        "inventory_growth_gap_inferred": inventory_growth_gap_inferred,
        "inventory_growth_gap_source": inventory_growth_gap_source,
        "fundamental_quality_score": quality_score,
        "ai_disclosure_score": ai_disclosure_score,
        "ai_disclosure_group_hits": ai_disclosure_group_hits,
        "ai_disclosure_keyword_hits": ai_disclosure_keyword_hits,
        "ai_backlog_signal": ai_backlog_signal,
    }


def collect_fundamentals(df: pd.DataFrame, sec: SecClient, config: ScanConfig) -> pd.DataFrame:
    rows = []
    total = len(df)
    done = 0
    last_reported_pct = -1
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {
            pool.submit(load_one_fundamental, sec, row.symbol, row.cik, config): row.symbol
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
                        "revenue_ttm_history_json": None,
                        "net_income_ttm_history_json": None,
                        "shares_history_json": None,
                        "shares_form": None,
                        "operating_cash_flow": None,
                        "operating_cash_flow_form": None,
                        "capex": None,
                        "free_cash_flow": None,
                        "ebit": None,
                        "ebit_form": None,
                        "cash_and_equivalents": None,
                        "total_debt": None,
                        "net_debt": None,
                        "interest_expense": None,
                        "depreciation_and_amortization": None,
                        "current_assets": None,
                        "current_liabilities": None,
                        "receivables_current": None,
                        "inventory_current": None,
                        "revenue_yoy": None,
                        "net_income_yoy": None,
                        "ebit_yoy": None,
                        "da_yoy": None,
                        "operating_cash_flow_yoy": None,
                        "shares_yoy": None,
                        "receivables_yoy": None,
                        "inventory_yoy": None,
                        "receivables_growth_gap": None,
                        "inventory_growth_gap": None,
                        "nonrecurring_expense_addback": None,
                        "nonrecurring_gain_subtraction": None,
                        "adjusted_net_income": None,
                        "adjusted_ebit": None,
                        "adjusted_ebitda": None,
                        "adjusted_net_income_yoy": None,
                        "adjusted_ebit_yoy": None,
                        "interest_coverage": None,
                        "net_debt_to_ebitda": None,
                        "current_ratio": None,
                        "current_debt_ratio_reported": None,
                        "current_debt_ratio_inferred": None,
                        "current_debt_ratio": None,
                        "current_debt_ratio_source": None,
                        "ocf_to_net_income": None,
                        "accrual_ratio": None,
                        "inventory_growth_gap_reported": None,
                        "inventory_growth_gap_inferred": None,
                        "inventory_growth_gap_source": None,
                        "fundamental_quality_score": None,
                        "ai_disclosure_score": None,
                        "ai_disclosure_group_hits": None,
                        "ai_disclosure_keyword_hits": None,
                        "ai_backlog_signal": None,
                    }
                )
            done += 1
            if total > 0:
                pct = int((done * 100) / total)
                if pct >= last_reported_pct + 10 or done == total:
                    print(f"  [progress] SEC fundamentals: {done}/{total} ({pct}%)")
                    last_reported_pct = pct
    return pd.DataFrame(rows)


def append_professional_filter_steps(
    steps: list[tuple[str, Any]], cp: dict[str, Any], config: ScanConfig
) -> list[tuple[str, Any]]:
    if cp["min_fundamental_quality_score"] is not None and hard_filter_metric_enabled(
        "fundamental_quality_score", config, cp
    ):
        steps.append(
            (
                "min_fundamental_quality_score",
                lambda frame: pd.to_numeric(frame["fundamental_quality_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_fundamental_quality_score"],
            )
        )
    if cp["max_net_debt_to_ebitda"] is not None and hard_filter_metric_enabled(
        "net_debt_to_ebitda", config, cp
    ):
        steps.append(
            (
                "max_net_debt_to_ebitda",
                lambda frame: (
                    pd.to_numeric(frame["net_debt_to_ebitda"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["net_debt_to_ebitda"], errors="coerce")
                        <= cp["max_net_debt_to_ebitda"]
                    )
                ),
            )
        )
    if cp["min_interest_coverage"] is not None and hard_filter_metric_enabled(
        "interest_coverage", config, cp
    ):
        steps.append(
            (
                "min_interest_coverage",
                lambda frame: (
                    pd.to_numeric(frame["interest_coverage"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["interest_coverage"], errors="coerce")
                        >= cp["min_interest_coverage"]
                    )
                ),
            )
        )
    if cp["max_current_debt_ratio"] is not None and hard_filter_metric_enabled(
        "current_debt_ratio", config, cp
    ):
        steps.append(
            (
                "max_current_debt_ratio",
                lambda frame: (
                    pd.to_numeric(frame["current_debt_ratio"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["current_debt_ratio"], errors="coerce")
                        <= cp["max_current_debt_ratio"]
                    )
                ),
            )
        )
    if cp["min_current_ratio"] is not None and hard_filter_metric_enabled("current_ratio", config, cp):
        steps.append(
            (
                "min_current_ratio",
                lambda frame: (
                    pd.to_numeric(frame["current_ratio"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["current_ratio"], errors="coerce")
                        >= cp["min_current_ratio"]
                    )
                ),
            )
        )
    if cp["min_ocf_to_net_income"] is not None and hard_filter_metric_enabled(
        "ocf_to_net_income", config, cp
    ):
        steps.append(
            (
                "min_ocf_to_net_income",
                lambda frame: (
                    pd.to_numeric(frame["ocf_to_net_income"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["ocf_to_net_income"], errors="coerce")
                        >= cp["min_ocf_to_net_income"]
                    )
                ),
            )
        )
    if cp["max_accrual_ratio"] is not None and hard_filter_metric_enabled("accrual_ratio", config, cp):
        steps.append(
            (
                "max_accrual_ratio",
                lambda frame: (
                    pd.to_numeric(frame["accrual_ratio"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["accrual_ratio"], errors="coerce").abs()
                        <= cp["max_accrual_ratio"]
                    )
                ),
            )
        )
    if cp["max_receivables_growth_gap"] is not None and hard_filter_metric_enabled(
        "receivables_growth_gap", config, cp
    ):
        steps.append(
            (
                "max_receivables_growth_gap",
                lambda frame: (
                    pd.to_numeric(frame["receivables_growth_gap"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["receivables_growth_gap"], errors="coerce")
                        <= cp["max_receivables_growth_gap"]
                    )
                ),
            )
        )
    if cp["max_inventory_growth_gap"] is not None and hard_filter_metric_enabled(
        "inventory_growth_gap", config, cp
    ):
        steps.append(
            (
                "max_inventory_growth_gap",
                lambda frame: (
                    pd.to_numeric(frame["inventory_growth_gap"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["inventory_growth_gap"], errors="coerce")
                        <= cp["max_inventory_growth_gap"]
                    )
                ),
            )
        )
    if cp["max_shares_yoy"] is not None and hard_filter_metric_enabled("shares_yoy", config, cp):
        steps.append(
            (
                "max_shares_yoy",
                lambda frame: (
                    pd.to_numeric(frame["shares_yoy"], errors="coerce").isna()
                    | (pd.to_numeric(frame["shares_yoy"], errors="coerce") <= cp["max_shares_yoy"])
                ),
            )
        )
    if cp["max_ps_hist_percentile"] is not None and hard_filter_metric_enabled(
        "ps_hist_percentile", config, cp
    ):
        steps.append(
            (
                "max_ps_hist_percentile",
                lambda frame: (
                    pd.to_numeric(frame["ps_hist_percentile"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["ps_hist_percentile"], errors="coerce")
                        <= cp["max_ps_hist_percentile"]
                    )
                ),
            )
        )
    if cp["max_pe_hist_percentile"] is not None and hard_filter_metric_enabled(
        "pe_hist_percentile", config, cp
    ):
        steps.append(
            (
                "max_pe_hist_percentile",
                lambda frame: (
                    pd.to_numeric(frame["pe_hist_percentile"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["pe_hist_percentile"], errors="coerce")
                        <= cp["max_pe_hist_percentile"]
                    )
                ),
            )
        )
    if cp["min_expectation_proxy"] is not None and hard_filter_metric_enabled(
        "expectation_proxy", config, cp
    ):
        steps.append(
            (
                "min_expectation_proxy",
                lambda frame: (
                    pd.to_numeric(frame["expectation_proxy"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["expectation_proxy"], errors="coerce")
                        >= cp["min_expectation_proxy"]
                    )
                ),
            )
        )
    if cp["min_cycle_proxy"] is not None and hard_filter_metric_enabled("cycle_proxy", config, cp):
        steps.append(
            (
                "min_cycle_proxy",
                lambda frame: (
                    pd.to_numeric(frame["cycle_proxy"], errors="coerce").isna()
                    | (pd.to_numeric(frame["cycle_proxy"], errors="coerce") >= cp["min_cycle_proxy"])
                ),
            )
        )
    if cp["max_adv_participation"] is not None and hard_filter_metric_enabled(
        "adv_participation", config, cp
    ):
        steps.append(
            (
                "max_adv_participation",
                lambda frame: (
                    pd.to_numeric(frame["adv_participation"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["adv_participation"], errors="coerce")
                        <= cp["max_adv_participation"]
                    )
                ),
            )
        )
    if cp["max_estimated_slippage_bps"] is not None and hard_filter_metric_enabled(
        "estimated_slippage_bps", config, cp
    ):
        steps.append(
            (
                "max_estimated_slippage_bps",
                lambda frame: (
                    pd.to_numeric(frame["estimated_slippage_bps"], errors="coerce").isna()
                    | (
                        pd.to_numeric(frame["estimated_slippage_bps"], errors="coerce")
                        <= cp["max_estimated_slippage_bps"]
                    )
                ),
            )
        )
    return steps


def build_filter_steps(
    config: ScanConfig, channel_name: str, channel_profile: dict[str, Any]
) -> list[tuple[str, Any]]:
    cp = resolve_channel_profile(config, channel_name, channel_profile)
    net_income_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    net_income_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"

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
    if cp["require_positive_revenue"]:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if cp["require_positive_net_income"]:
        steps.append(
            (
                "positive_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_revenue"] is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= cp["min_revenue"]))
    if cp["min_net_income"] is not None:
        steps.append(
            (
                "min_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(0)
                >= cp["min_net_income"],
            )
        )
    if cp["require_positive_operating_cash_flow"]:
        steps.append(
            (
                "positive_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_free_cash_flow"]:
        steps.append(
            (
                "positive_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_ebit"]:
        steps.append(
            (
                "positive_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_operating_cash_flow"] is not None:
        steps.append(
            (
                "min_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-np.inf)
                >= cp["min_operating_cash_flow"],
            )
        )
    if cp["min_free_cash_flow"] is not None:
        steps.append(
            (
                "min_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-np.inf)
                >= cp["min_free_cash_flow"],
            )
        )
    if cp["min_ebit"] is not None:
        steps.append(
            (
                "min_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-np.inf) >= cp["min_ebit"],
            )
        )
    if cp["min_fcf_yield"] is not None:
        steps.append(
            (
                "min_fcf_yield",
                lambda frame: pd.to_numeric(frame["fcf_yield"], errors="coerce").fillna(-np.inf)
                >= cp["min_fcf_yield"],
            )
        )
    if cp["max_ev_to_ebit"] is not None:
        steps.append(
            (
                "max_ev_to_ebit",
                lambda frame: pd.to_numeric(frame["ev_to_ebit"], errors="coerce").fillna(np.inf)
                <= cp["max_ev_to_ebit"],
            )
        )
    if cp["min_revenue_yoy"] is not None:
        steps.append(
            (
                "min_revenue_yoy",
                lambda frame: pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(-np.inf)
                >= cp["min_revenue_yoy"],
            )
        )
    if cp["min_net_income_yoy"] is not None:
        steps.append(
            (
                "min_net_income_yoy",
                lambda frame: pd.to_numeric(frame[net_income_yoy_col], errors="coerce").fillna(-np.inf)
                >= cp["min_net_income_yoy"],
            )
        )
    if cp["min_net_margin"] is not None:
        steps.append(
            (
                "min_net_margin",
                lambda frame: pd.to_numeric(frame["net_margin"], errors="coerce").fillna(-np.inf)
                >= cp["min_net_margin"],
            )
        )
    if cp["max_ps"] is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= cp["max_ps"]))
    if cp["max_pe"] is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= cp["max_pe"]))
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
    if cp["min_return_20d"] is not None:
        steps.append(
            (
                "min_return_20d",
                lambda frame: frame["return_20d"].fillna(-np.inf) >= cp["min_return_20d"],
            )
        )
    if cp["min_return_60d"] is not None:
        steps.append(
            (
                "min_return_60d",
                lambda frame: frame["return_60d"].fillna(-np.inf) >= cp["min_return_60d"],
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
    if cp["min_drawdown_percentile"] is not None:
        steps.append(
            (
                "min_drawdown_percentile",
                lambda frame: percentile_floor_mask(frame["drawdown_from_52w_high"], cp["min_drawdown_percentile"]),
            )
        )
    if cp["min_avg_dollar_volume_20d_percentile"] is not None:
        steps.append(
            (
                "min_avg_dollar_volume_20d_percentile",
                lambda frame: percentile_floor_mask(
                    frame["avg_dollar_volume_20d"], cp["min_avg_dollar_volume_20d_percentile"]
                ),
            )
        )
    if cp["max_60d_volatility_percentile"] is not None:
        steps.append(
            (
                "max_60d_volatility_percentile",
                lambda frame: percentile_cap_mask(
                    frame["volatility_60d"], cp["max_60d_volatility_percentile"]
                ),
            )
        )
    if cp["min_watchlist_etf_count"] > 1:
        steps.append(
            (
                "min_watchlist_etf_count",
                lambda frame: pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
                >= int(cp["min_watchlist_etf_count"]),
            )
        )
    if cp["min_avg_dollar_volume_20d"] is not None:
        steps.append(
            (
                "min_avg_dollar_volume_20d",
                lambda frame: pd.to_numeric(frame["avg_dollar_volume_20d"], errors="coerce").fillna(0)
                >= cp["min_avg_dollar_volume_20d"],
            )
        )

    steps = append_professional_filter_steps(steps, cp, config)
    steps.append(("watchlist_membership", watchlist_member_mask))
    if cp["require_channel_bucket_match"]:
        steps.append(
            (
                "channel_bucket_match",
                lambda frame: channel_bucket_mask(frame, channel_name),
            )
        )
    if cp["min_ai_link_score"] is not None:
        steps.append(
            (
                "min_ai_link_score",
                lambda frame: pd.to_numeric(frame["ai_link_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_ai_link_score"],
            )
        )

    steps.extend(
        [
            (
                "min_value_discount_any",
                lambda frame: (
                    pd.to_numeric(frame["ps_discount"], errors="coerce").fillna(-np.inf) >= cp["min_ps_discount"]
                )
                | (
                    pd.to_numeric(frame["pe_discount"], errors="coerce").fillna(-np.inf) >= cp["min_pe_discount"]
                ),
            ),
            (
                "max_ps_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["ps_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_ps_percentile_in_sic"]
                if cp["max_ps_percentile_in_sic"] is not None
                else pd.Series(True, index=frame.index),
            ),
            (
                "max_pe_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["pe_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_pe_percentile_in_sic"]
                if cp["max_pe_percentile_in_sic"] is not None
                else pd.Series(True, index=frame.index),
            ),
            (
                "sic_filter",
                lambda frame: frame["sic"].apply(
                    lambda x: passes_sic_filters(
                        x,
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
    net_income_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    net_income_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"
    trend_weights = channel_profile.get("trend_score_weights")
    trend_min_watchlist_etf_count = int(
        channel_profile.get("trend_min_watchlist_etf_count", cp["min_watchlist_etf_count"])
    )
    trend_min_return_60d = channel_profile.get("trend_min_return_60d", cp["min_return_60d"])
    trend_max_60d_volatility = channel_profile.get("trend_max_60d_volatility", cp["max_60d_volatility"])
    trend_min_avg_dollar_volume_20d = channel_profile.get(
        "trend_min_avg_dollar_volume_20d", cp["min_avg_dollar_volume_20d"]
    )
    if not isinstance(trend_weights, dict):
        if channel_name == "ai_enabler":
            trend_weights = {
                "liquidity": 0.20,
                "watchlist_etf_count": 0.30,
                "ai_link_score": 0.20,
                "return_20d": 0.30,
                "drawdown_from_52w_high": -0.10,
            }
        else:
            trend_weights = {
                "liquidity": 0.20,
                "watchlist_etf_count": 0.25,
                "ai_link_score": 0.20,
                "return_20d": 0.35,
                "drawdown_from_52w_high": -0.10,
            }
    trend_weights = merge_soft_score_weights(trend_weights, config.low_coverage_soft_score_weights)

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        ("min_dollar_volume", lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
    ]
    if config.max_market_cap is not None:
        steps.append(("max_market_cap", lambda frame: frame["market_cap"] <= config.max_market_cap))
    if cp["require_positive_revenue"]:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if cp["require_positive_net_income"]:
        steps.append(
            (
                "positive_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_operating_cash_flow"]:
        steps.append(
            (
                "positive_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_free_cash_flow"]:
        steps.append(
            (
                "positive_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_ebit"]:
        steps.append(
            (
                "positive_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_revenue"] is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= cp["min_revenue"]))
    if cp["min_net_income"] is not None:
        steps.append(
            (
                "min_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(0)
                >= cp["min_net_income"],
            )
        )
    if cp["max_ps"] is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= cp["max_ps"]))
    if cp["max_pe"] is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= cp["max_pe"]))
    if cp["min_revenue_yoy"] is not None:
        steps.append(
            (
                "min_revenue_yoy",
                lambda frame: pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(-np.inf)
                >= cp["min_revenue_yoy"],
            )
        )
    if cp["min_net_income_yoy"] is not None:
        steps.append(
            (
                "min_net_income_yoy",
                lambda frame: pd.to_numeric(frame[net_income_yoy_col], errors="coerce").fillna(-np.inf)
                >= cp["min_net_income_yoy"],
            )
        )
    if cp["min_fcf_yield"] is not None:
        steps.append(
            (
                "min_fcf_yield",
                lambda frame: pd.to_numeric(frame["fcf_yield"], errors="coerce").fillna(-np.inf)
                >= cp["min_fcf_yield"],
            )
        )
    if cp["max_ev_to_ebit"] is not None:
        steps.append(
            (
                "max_ev_to_ebit",
                lambda frame: pd.to_numeric(frame["ev_to_ebit"], errors="coerce").fillna(np.inf)
                <= cp["max_ev_to_ebit"],
            )
        )
    if cp["max_ps_percentile_in_sic"] is not None:
        steps.append(
            (
                "max_ps_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["ps_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_ps_percentile_in_sic"],
            )
        )
    if cp["max_pe_percentile_in_sic"] is not None:
        steps.append(
            (
                "max_pe_percentile_in_sic",
                lambda frame: pd.to_numeric(frame["pe_percentile_in_sic"], errors="coerce").fillna(np.inf)
                <= cp["max_pe_percentile_in_sic"],
            )
        )
    if trend_min_return_60d is not None:
        steps.append(
            (
                "trend_min_return_60d",
                lambda frame: frame["return_60d"].fillna(-np.inf) >= float(trend_min_return_60d),
            )
        )
    if trend_max_60d_volatility is not None:
        steps.append(
            (
                "trend_max_60d_volatility",
                lambda frame: frame["volatility_60d"].fillna(np.inf) <= float(trend_max_60d_volatility),
            )
        )
    if trend_min_avg_dollar_volume_20d is not None:
        steps.append(
            (
                "trend_min_avg_dollar_volume_20d",
                lambda frame: pd.to_numeric(frame["avg_dollar_volume_20d"], errors="coerce").fillna(0)
                >= float(trend_min_avg_dollar_volume_20d),
            )
        )
    if trend_min_watchlist_etf_count > 1:
        steps.append(
            (
                "trend_min_watchlist_etf_count",
                lambda frame: pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
                >= trend_min_watchlist_etf_count,
            )
        )

    steps = append_professional_filter_steps(steps, cp, config)
    steps.append(("watchlist_membership", watchlist_member_mask))
    if cp["require_channel_bucket_match"]:
        steps.append(
            (
                "channel_bucket_match",
                lambda frame: channel_bucket_mask(frame, channel_name),
            )
        )
    if cp["min_ai_link_score"] is not None:
        steps.append(
            (
                "min_ai_link_score",
                lambda frame: pd.to_numeric(frame["ai_link_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_ai_link_score"],
            )
        )

    steps.append(
        (
            "sic_filter",
            lambda frame: frame["sic"].apply(
                lambda x: passes_sic_filters(
                    x,
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
    net_income_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    net_income_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"
    momentum_min_return_20d = channel_profile.get("momentum_min_return_20d", 0.05)
    momentum_min_price_to_sma200 = channel_profile.get("momentum_min_price_to_sma200", 1.05)
    momentum_max_drawdown_from_52w_high = channel_profile.get(
        "momentum_max_drawdown_from_52w_high", 0.25
    )
    momentum_min_watchlist_etf_count = int(
        channel_profile.get("momentum_min_watchlist_etf_count", cp["min_watchlist_etf_count"])
    )
    momentum_min_return_60d = channel_profile.get("momentum_min_return_60d", cp["min_return_60d"])
    momentum_max_60d_volatility = channel_profile.get(
        "momentum_max_60d_volatility", cp["max_60d_volatility"]
    )
    momentum_min_avg_dollar_volume_20d = channel_profile.get(
        "momentum_min_avg_dollar_volume_20d", cp["min_avg_dollar_volume_20d"]
    )
    momentum_weights = channel_profile.get("momentum_score_weights")
    if not isinstance(momentum_weights, dict):
        momentum_weights = {
            "liquidity": 0.10,
            "return_20d": 0.50,
            "watchlist_etf_count": 0.20,
            "ai_link_score": 0.20,
            "drawdown_from_52w_high": -0.10,
        }
    momentum_weights = merge_soft_score_weights(
        momentum_weights, config.low_coverage_soft_score_weights
    )

    steps: list[tuple[str, Any]] = [
        ("price_notna", lambda frame: frame["price"].notna()),
        ("min_price", lambda frame: frame["price"] >= config.min_price),
        ("min_dollar_volume", lambda frame: frame["dollar_volume"].fillna(0) >= config.min_dollar_volume),
        ("market_cap_notna", lambda frame: frame["market_cap"].notna()),
        ("min_market_cap", lambda frame: frame["market_cap"] >= config.min_market_cap),
        (
            "min_fcf_yield",
            lambda frame: pd.to_numeric(frame["fcf_yield"], errors="coerce").fillna(-np.inf)
            >= float(cp["min_fcf_yield"])
            if cp["min_fcf_yield"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "max_ev_to_ebit",
            lambda frame: pd.to_numeric(frame["ev_to_ebit"], errors="coerce").fillna(np.inf)
            <= float(cp["max_ev_to_ebit"])
            if cp["max_ev_to_ebit"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "min_revenue_yoy",
            lambda frame: pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(-np.inf)
            >= float(cp["min_revenue_yoy"])
            if cp["min_revenue_yoy"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "min_net_income_yoy",
            lambda frame: pd.to_numeric(frame[net_income_yoy_col], errors="coerce").fillna(-np.inf)
            >= float(cp["min_net_income_yoy"])
            if cp["min_net_income_yoy"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "max_ps_percentile_in_sic",
            lambda frame: pd.to_numeric(frame["ps_percentile_in_sic"], errors="coerce").fillna(np.inf)
            <= float(cp["max_ps_percentile_in_sic"])
            if cp["max_ps_percentile_in_sic"] is not None
            else pd.Series(True, index=frame.index),
        ),
        (
            "max_pe_percentile_in_sic",
            lambda frame: pd.to_numeric(frame["pe_percentile_in_sic"], errors="coerce").fillna(np.inf)
            <= float(cp["max_pe_percentile_in_sic"])
            if cp["max_pe_percentile_in_sic"] is not None
            else pd.Series(True, index=frame.index),
        ),
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
    if cp["require_positive_revenue"]:
        steps.append(("positive_revenue", lambda frame: frame["revenue"].fillna(-1) > 0))
    if cp["require_positive_net_income"]:
        steps.append(
            (
                "positive_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_operating_cash_flow"]:
        steps.append(
            (
                "positive_operating_cash_flow",
                lambda frame: pd.to_numeric(frame["operating_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_free_cash_flow"]:
        steps.append(
            (
                "positive_free_cash_flow",
                lambda frame: pd.to_numeric(frame["free_cash_flow"], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["require_positive_ebit"]:
        steps.append(
            (
                "positive_ebit",
                lambda frame: pd.to_numeric(frame[ebit_col], errors="coerce").fillna(-1) > 0,
            )
        )
    if cp["min_revenue"] is not None:
        steps.append(("min_revenue", lambda frame: frame["revenue"].fillna(0) >= cp["min_revenue"]))
    if cp["min_net_income"] is not None:
        steps.append(
            (
                "min_net_income",
                lambda frame: pd.to_numeric(frame[net_income_col], errors="coerce").fillna(0)
                >= cp["min_net_income"],
            )
        )
    if cp["max_ps"] is not None:
        steps.append(("max_ps", lambda frame: frame["ps"].fillna(np.inf) <= cp["max_ps"]))
    if cp["max_pe"] is not None:
        steps.append(("max_pe", lambda frame: frame["pe"].fillna(np.inf) <= cp["max_pe"]))
    if momentum_min_return_60d is not None:
        steps.append(
            (
                "momentum_min_return_60d",
                lambda frame: frame["return_60d"].fillna(-np.inf) >= float(momentum_min_return_60d),
            )
        )
    if momentum_max_60d_volatility is not None:
        steps.append(
            (
                "momentum_max_60d_volatility",
                lambda frame: frame["volatility_60d"].fillna(np.inf) <= float(momentum_max_60d_volatility),
            )
        )
    if momentum_min_avg_dollar_volume_20d is not None:
        steps.append(
            (
                "momentum_min_avg_dollar_volume_20d",
                lambda frame: pd.to_numeric(frame["avg_dollar_volume_20d"], errors="coerce").fillna(0)
                >= float(momentum_min_avg_dollar_volume_20d),
            )
        )
    if momentum_min_watchlist_etf_count > 1:
        steps.append(
            (
                "momentum_min_watchlist_etf_count",
                lambda frame: pd.to_numeric(frame["watchlist_etf_count"], errors="coerce").fillna(0)
                >= momentum_min_watchlist_etf_count,
            )
        )

    steps = append_professional_filter_steps(steps, cp, config)
    steps.append(("watchlist_membership", watchlist_member_mask))
    if cp["require_channel_bucket_match"]:
        steps.append(
            (
                "channel_bucket_match",
                lambda frame: channel_bucket_mask(frame, channel_name),
            )
        )
    if cp["min_ai_link_score"] is not None:
        steps.append(
            (
                "min_ai_link_score",
                lambda frame: pd.to_numeric(frame["ai_link_score"], errors="coerce").fillna(-np.inf)
                >= cp["min_ai_link_score"],
            )
        )

    steps.append(
        (
            "sic_filter",
            lambda frame: frame["sic"].apply(
                lambda x: passes_sic_filters(
                    x,
                    cp["exclude_sic_codes"],
                )
            ),
        )
    )
    return steps, momentum_weights


def classify_filter_step_layer(step_name: str) -> str:
    base_steps = {
        "price_notna",
        "min_price",
        "min_dollar_volume",
        "market_cap_notna",
        "min_market_cap",
        "max_market_cap",
        "watchlist_membership",
        "channel_bucket_match",
        "sic_filter",
        "min_watchlist_etf_count",
        "min_avg_dollar_volume_20d",
        "trend_min_watchlist_etf_count",
        "trend_min_avg_dollar_volume_20d",
        "momentum_min_watchlist_etf_count",
        "momentum_min_avg_dollar_volume_20d",
    }
    valuation_steps = {
        "min_value_discount_any",
        "max_ps_percentile_in_sic",
        "max_pe_percentile_in_sic",
        "max_ps",
        "max_pe",
        "max_ps_hist_percentile",
        "max_pe_hist_percentile",
        "min_drawdown_from_52w_high",
        "max_range_position_52w",
        "max_price_to_sma200",
        "min_days_below_sma200",
        "min_drawdown_percentile",
        "min_return_20d",
        "min_return_60d",
        "max_20d_return",
        "max_60d_volatility",
        "max_60d_volatility_percentile",
        "trend_min_return_60d",
        "trend_max_60d_volatility",
        "momentum_min_return_20d",
        "momentum_min_return_60d",
        "momentum_min_price_to_sma200",
        "momentum_max_drawdown_from_52w_high",
        "momentum_max_60d_volatility",
    }
    if step_name in base_steps:
        return "base_hard"
    if step_name in valuation_steps:
        return "valuation_hard"
    return "quality_or_theme_hard"


def summarize_diagnostics_by_layer(
    diagnostics: list[dict[str, int | float | str]]
) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for row in diagnostics:
        step = str(row.get("step", ""))
        if step == "start":
            continue
        layer = str(row.get("layer", classify_filter_step_layer(step)))
        before = int(row.get("before", 0) or 0)
        remaining = int(row.get("remaining", 0) or 0)
        removed = int(row.get("removed", 0) or 0)
        if layer not in out:
            out[layer] = {"before": before, "remaining": remaining, "removed": removed}
        else:
            out[layer]["remaining"] = remaining
            out[layer]["removed"] = int(out[layer]["removed"]) + removed
            if int(out[layer]["before"]) <= 0 and before > 0:
                out[layer]["before"] = before
    for layer, payload in out.items():
        before = int(payload.get("before", 0) or 0)
        remaining = int(payload.get("remaining", 0) or 0)
        payload["pass_rate"] = float(remaining / before) if before > 0 else 1.0
    return out


def first_fail_concentration(first_fail_summary: pd.DataFrame) -> dict[str, Any]:
    if first_fail_summary.empty:
        return {"top_reason": "", "top_count": 0, "top_pct": 0.0}
    filtered = first_fail_summary[first_fail_summary["reason"] != "passed"].copy()
    if filtered.empty:
        return {"top_reason": "passed", "top_count": 0, "top_pct": 0.0}
    top = filtered.sort_values("count", ascending=False).iloc[0]
    return {
        "top_reason": str(top.get("reason", "")),
        "top_count": int(top.get("count", 0) or 0),
        "top_pct": float(top.get("pct", 0.0) or 0.0),
    }


def apply_filters_with_diagnostics(
    df: pd.DataFrame, steps: list[tuple[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, int | float | str]]]:
    out = df.copy()
    diagnostics: list[dict[str, int | float | str]] = [
        {"step": "start", "before": int(len(out)), "remaining": int(len(out)), "removed": 0, "pass_rate": 1.0, "layer": "start"}
    ]

    for step_name, mask_fn in steps:
        before = len(out)
        out = out[mask_fn(out)]
        after = len(out)
        pass_rate = float(after / before) if before > 0 else 1.0
        diagnostics.append(
            {
                "step": step_name,
                "before": int(before),
                "remaining": int(after),
                "removed": int(before - after),
                "pass_rate": pass_rate,
                "layer": classify_filter_step_layer(step_name),
            }
        )

    return out, diagnostics


def dedupe_symbol_by_best_channel(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if frame.empty or "symbol" not in frame.columns or "composite_score" not in frame.columns:
        return frame, 0
    work = frame.copy()
    work["_symbol"] = work["symbol"].astype(str)
    work["_score"] = pd.to_numeric(work["composite_score"], errors="coerce").fillna(-np.inf)
    if "watchlist_etf_count" in work.columns:
        work["_etf_count"] = pd.to_numeric(work["watchlist_etf_count"], errors="coerce").fillna(0)
    else:
        work["_etf_count"] = 0
    if "channel" in work.columns:
        work["_channel"] = work["channel"].astype(str)
    else:
        work["_channel"] = ""
    # Keep one row per symbol: highest score first, then broader ETF coverage.
    work = work.sort_values(
        by=["_symbol", "_score", "_etf_count", "_channel"],
        ascending=[True, False, False, True],
    )
    deduped = work.drop_duplicates(subset=["_symbol"], keep="first").drop(
        columns=["_symbol", "_score", "_etf_count", "_channel"],
        errors="ignore",
    )
    removed = len(frame) - len(deduped)
    return deduped, int(removed)


def drop_symbols(frame: pd.DataFrame, symbols: set[str]) -> tuple[pd.DataFrame, int]:
    if frame.empty or not symbols or "symbol" not in frame.columns:
        return frame, 0
    before = len(frame)
    keep_mask = ~frame["symbol"].astype(str).isin(symbols)
    out = frame[keep_mask].copy()
    return out, int(before - len(out))


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


def score_and_rank(
    df: pd.DataFrame,
    weights: dict[str, float],
    score_winsor_lower_q: float,
    score_winsor_upper_q: float,
    overvaluation_penalty_weight: float = 0.20,
    deterioration_penalty_weight: float = 0.20,
) -> pd.DataFrame:
    out = df.copy()
    required_cols = [
        "ps_discount",
        "pe_discount",
        "dollar_volume",
        "return_20d",
        "return_60d",
        "watchlist_etf_count",
        "range_position_52w",
        "drawdown_from_52w_high",
        "days_below_sma200",
        "net_margin",
        "ev_to_ebit",
        "fcf_yield",
        "ps_percentile_in_sic",
        "pe_percentile_in_sic",
        "revenue_yoy",
        "net_income_yoy",
        "adjusted_net_income_yoy",
        "ebit_yoy",
        "operating_cash_flow_yoy",
        "fundamental_quality_score",
        "net_debt_to_ebitda",
        "interest_coverage",
        "ocf_to_net_income",
        "accrual_ratio",
        "shares_yoy",
        "ps_hist_percentile",
        "pe_hist_percentile",
        "expectation_proxy",
        "cycle_proxy",
        "adv_participation",
        "estimated_slippage_bps",
        "current_debt_ratio",
        "inventory_growth_gap",
        "ai_link_score",
    ]
    for col in required_cols:
        if col not in out.columns:
            out[col] = np.nan

    component_series: dict[str, pd.Series] = {
        "ps_discount": out["ps_discount"],
        "pe_discount": out["pe_discount"],
        "liquidity": np.log1p(pd.to_numeric(out["dollar_volume"], errors="coerce").fillna(0)),
        "return_20d": out["return_20d"],
        "return_60d": out["return_60d"],
        "watchlist_etf_count": pd.to_numeric(out["watchlist_etf_count"], errors="coerce"),
        "range_position_52w_low": 1 - pd.to_numeric(out["range_position_52w"], errors="coerce"),
        "drawdown_from_52w_high": pd.to_numeric(out["drawdown_from_52w_high"], errors="coerce"),
        "days_below_sma200": pd.to_numeric(out["days_below_sma200"], errors="coerce"),
        "net_margin": pd.to_numeric(out["net_margin"], errors="coerce"),
        "ev_to_ebit_low": -pd.to_numeric(out["ev_to_ebit"], errors="coerce"),
        "fcf_yield": pd.to_numeric(out["fcf_yield"], errors="coerce"),
        "ps_percentile_low": 1 - pd.to_numeric(out["ps_percentile_in_sic"], errors="coerce"),
        "pe_percentile_low": 1 - pd.to_numeric(out["pe_percentile_in_sic"], errors="coerce"),
        "revenue_yoy": pd.to_numeric(out["revenue_yoy"], errors="coerce"),
        "net_income_yoy": pd.to_numeric(out["net_income_yoy"], errors="coerce"),
        "ebit_yoy": pd.to_numeric(out["ebit_yoy"], errors="coerce"),
        "operating_cash_flow_yoy": pd.to_numeric(out["operating_cash_flow_yoy"], errors="coerce"),
        "fundamental_quality_score": pd.to_numeric(out["fundamental_quality_score"], errors="coerce"),
        "net_debt_to_ebitda_low": -pd.to_numeric(out["net_debt_to_ebitda"], errors="coerce"),
        "interest_coverage": pd.to_numeric(out["interest_coverage"], errors="coerce"),
        "ocf_to_net_income": pd.to_numeric(out["ocf_to_net_income"], errors="coerce"),
        "accrual_ratio_low": -pd.to_numeric(out["accrual_ratio"], errors="coerce").abs(),
        "shares_yoy_low": -pd.to_numeric(out["shares_yoy"], errors="coerce"),
        "ps_hist_percentile_low": 1 - pd.to_numeric(out["ps_hist_percentile"], errors="coerce"),
        "pe_hist_percentile_low": 1 - pd.to_numeric(out["pe_hist_percentile"], errors="coerce"),
        "expectation_proxy": pd.to_numeric(out["expectation_proxy"], errors="coerce"),
        "cycle_proxy": pd.to_numeric(out["cycle_proxy"], errors="coerce"),
        "adv_participation_low": -pd.to_numeric(out["adv_participation"], errors="coerce"),
        "estimated_slippage_bps_low": -pd.to_numeric(out["estimated_slippage_bps"], errors="coerce"),
        "current_debt_ratio_low": -pd.to_numeric(out["current_debt_ratio"], errors="coerce"),
        "inventory_growth_gap_low": -pd.to_numeric(out["inventory_growth_gap"], errors="coerce"),
        "ai_link_score": pd.to_numeric(out["ai_link_score"], errors="coerce"),
    }
    default_weights = {
        "ps_discount": 0.40,
        "pe_discount": 0.30,
        "liquidity": 0.05,
        "return_20d": 0.00,
        "return_60d": 0.00,
        "watchlist_etf_count": 0.00,
        "range_position_52w_low": 0.00,
        "drawdown_from_52w_high": 0.00,
        "days_below_sma200": 0.00,
        "net_margin": 0.00,
        "ev_to_ebit_low": 0.00,
        "fcf_yield": 0.00,
        "ps_percentile_low": 0.10,
        "pe_percentile_low": 0.10,
        "revenue_yoy": 0.00,
        "net_income_yoy": 0.00,
        "ebit_yoy": 0.00,
        "operating_cash_flow_yoy": 0.00,
        "fundamental_quality_score": 0.00,
        "net_debt_to_ebitda_low": 0.00,
        "interest_coverage": 0.00,
        "ocf_to_net_income": 0.00,
        "accrual_ratio_low": 0.00,
        "shares_yoy_low": 0.00,
        "ps_hist_percentile_low": 0.00,
        "pe_hist_percentile_low": 0.00,
        "expectation_proxy": 0.00,
        "cycle_proxy": 0.00,
        "adv_participation_low": 0.00,
        "estimated_slippage_bps_low": 0.00,
        "current_debt_ratio_low": 0.00,
        "inventory_growth_gap_low": 0.00,
        "ai_link_score": 0.00,
    }
    out["composite_score"] = 0.0
    use_fallback_defaults = not isinstance(weights, dict) or len(weights) == 0
    for key, raw in component_series.items():
        norm_col = f"{key}_norm"
        out[norm_col] = robust_normalize_score(raw, score_winsor_lower_q, score_winsor_upper_q)
        if use_fallback_defaults:
            weight = float(default_weights.get(key, 0.0))
        else:
            weight = float(weights.get(key, 0.0))
        out["composite_score"] += weight * out[norm_col]

    ps_pct = pd.to_numeric(out["ps_percentile_in_sic"], errors="coerce").fillna(1.0)
    pe_pct = pd.to_numeric(out["pe_percentile_in_sic"], errors="coerce").fillna(1.0)
    # Penalize names that are expensive relative to their own SIC cohort.
    overvaluation_penalty = ((ps_pct - 0.5).clip(lower=0) + (pe_pct - 0.5).clip(lower=0)) / 1.0

    rev_yoy = pd.to_numeric(out["revenue_yoy"], errors="coerce")
    adj_ni_yoy = pd.to_numeric(out["adjusted_net_income_yoy"], errors="coerce")
    ni_yoy = adj_ni_yoy.where(adj_ni_yoy.notna(), pd.to_numeric(out["net_income_yoy"], errors="coerce"))
    rev_decline = (-rev_yoy).clip(lower=0).fillna(0)
    ni_decline = (-ni_yoy).clip(lower=0).fillna(0)
    # Penalize fundamental deterioration (growth turning negative).
    deterioration_penalty = (rev_decline + ni_decline).clip(upper=1.5) / 1.5

    out["overvaluation_penalty"] = overvaluation_penalty
    out["deterioration_penalty"] = deterioration_penalty
    out["composite_score"] = (
        out["composite_score"]
        - float(overvaluation_penalty_weight) * out["overvaluation_penalty"]
        - float(deterioration_penalty_weight) * out["deterioration_penalty"]
    )

    return out.sort_values("composite_score", ascending=False)


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
        or "ai_enabler" in channel
        or "ai_peripheral" in channel
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

    if "possible_value_trap" in risk_set and score < 3.0:
        priority = "avoid_for_now"
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
    research_pool: pd.DataFrame | None = None,
    research_pool_path: Path | None = None,
    diagnostics_layer_summary: dict[str, dict[str, dict[str, float | int]]] | None = None,
    first_fail_concentration_summary: dict[str, dict[str, Any]] | None = None,
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
            lines.append(f"- theme_only: {priority_counts.get('theme_only', 0)}")
            lines.append(f"- avoid_for_now: {priority_counts.get('avoid_for_now', 0)}")
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
        default="configs/config.balanced.json",
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


def run_scan(
    config: ScanConfig,
    output_path: str | None,
    diagnostics_output_path: str | None,
    network_report_output_path: str | None = None,
    report_output_path: str | None = None,
) -> Path:
    def resolve_top_n(value: Any, fallback: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            resolved = int(fallback)
        return max(1, resolved)

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

    log_status(started_at, "INFO", "[1/6] Loading AI watchlist and tradable universe.")
    watchlist_scores = load_watchlist_scores(config)
    if watchlist_scores.empty:
        raise ValueError(
            "Watchlist is empty or missing. Run "
            "`python scripts/refresh_ai_watchlist.py --config configs/config.balanced.json --output data/ai_watchlist.csv` "
            "or populate watchlist_csv_path manually."
        )
    watchlist_allowlist = set(watchlist_scores["symbol"].dropna().astype(str).tolist())
    log_status(started_at, "INFO", f"Watchlist rows loaded: {len(watchlist_scores)}")
    log_status(started_at, "INFO", f"Watchlist unique symbols: {len(watchlist_allowlist)}")

    df = collect_candidates(
        alpaca,
        sec,
        config,
        symbol_allowlist=watchlist_allowlist,
    )
    merged_count = len(df)
    log_status(started_at, "INFO", f"Universe symbols after tradable/mapping merge: {merged_count}")

    df = df[
        df["price"].notna()
        & (pd.to_numeric(df["price"], errors="coerce") >= config.min_price)
        & (pd.to_numeric(df["dollar_volume"], errors="coerce").fillna(0) >= config.min_dollar_volume)
    ].copy()
    prefilter_count = len(df)
    log_status(started_at, "INFO", f"After price/liquidity prefilter: {prefilter_count}")

    log_status(started_at, "INFO", "[2/6] Computing price-dimension features.")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    bars_start_dt = (datetime.now(timezone.utc) - timedelta(days=config.price_lookback_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    bars_start_iso = bars_start_dt.isoformat().replace("+00:00", "Z")
    symbols_for_bars = df["symbol"].dropna().astype(str).tolist()
    benchmark_symbols = sorted(
        {
            normalize_equity_symbol(sym)
            for sym in (config.ai_link_benchmark_etfs or [])
            if normalize_equity_symbol(sym)
        }
    )
    bars_symbols = sorted(set(symbols_for_bars).union(set(benchmark_symbols)))
    bars_map = alpaca.get_daily_bars(bars_symbols, bars_start_iso, config.chunk_size)
    benchmark_returns_20d: list[float] = []
    benchmark_returns_60d: list[float] = []
    for etf in benchmark_symbols:
        bench_bars = bars_map.get(etf, [])
        ret20 = bars_return_from_lookback(bench_bars, 20)
        ret60 = bars_return_from_lookback(bench_bars, 60)
        if ret20 is not None and np.isfinite(ret20):
            benchmark_returns_20d.append(float(ret20))
        if ret60 is not None and np.isfinite(ret60):
            benchmark_returns_60d.append(float(ret60))
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
    price_feature_rows: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        symbol_bars = bars_map.get(row.symbol, [])
        features = price_dimension_from_bars(row.price, symbol_bars)
        price_feature_rows.append({"symbol": row.symbol, **features})
    df_price_features = pd.DataFrame(price_feature_rows)
    df = df.merge(df_price_features, on="symbol", how="left")

    log_status(started_at, "INFO", "[3/6] Fetching SEC fundamentals (cached locally).")
    fundamentals = collect_fundamentals(df, sec, config)
    df = df.merge(fundamentals, on="symbol", how="left")
    log_status(started_at, "INFO", "SEC fundamentals merge complete.")

    log_status(started_at, "INFO", "[4/6] Computing valuation and watchlist funnel.")
    for col, default in [
        ("ps_hist_percentile", np.nan),
        ("pe_hist_percentile", np.nan),
        ("ps_hist_observation_count", np.nan),
        ("pe_hist_observation_count", np.nan),
        ("ps_hist_percentile_source", "insufficient_history"),
        ("pe_hist_percentile_source", "insufficient_history"),
        ("revenue_ttm_history_json", None),
        ("net_income_ttm_history_json", None),
        ("shares_history_json", None),
    ]:
        if col not in df.columns:
            df[col] = default
    for col in [
        "price",
        "dollar_volume",
        "shares_outstanding",
        "revenue",
        "net_income",
        "adjusted_net_income",
        "operating_cash_flow",
        "free_cash_flow",
        "ebit",
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
        "nonrecurring_expense_addback",
        "nonrecurring_gain_subtraction",
        "interest_coverage",
        "net_debt_to_ebitda",
        "current_ratio",
        "current_debt_ratio_reported",
        "current_debt_ratio_inferred",
        "current_debt_ratio",
        "ocf_to_net_income",
        "accrual_ratio",
        "inventory_growth_gap_reported",
        "inventory_growth_gap_inferred",
        "fundamental_quality_score",
        "ai_disclosure_score",
        "ai_disclosure_group_hits",
        "ai_disclosure_keyword_hits",
        "ai_backlog_signal",
        "ps_hist_percentile",
        "pe_hist_percentile",
        "ps_hist_observation_count",
        "pe_hist_observation_count",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["market_cap"] = df["price"] * df["shares_outstanding"]
    df["enterprise_value"] = df["market_cap"] + df["total_debt"].fillna(0) - df["cash_and_equivalents"].fillna(0)
    earnings_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"
    earnings_yoy_col = (
        "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    )
    df["ps"] = safe_divide(df["market_cap"], df["revenue"])
    df["pe"] = safe_divide(df["market_cap"], df[earnings_col])
    df["ev_to_ebit"] = safe_divide(df["enterprise_value"], df[ebit_col])
    df["fcf_yield"] = safe_divide(df["free_cash_flow"], df["market_cap"])
    df["net_margin"] = safe_divide(df[earnings_col], df["revenue"])
    ps_hist_values: list[float | None] = []
    pe_hist_values: list[float | None] = []
    ps_hist_obs: list[int] = []
    pe_hist_obs: list[int] = []
    ps_hist_sources: list[str] = []
    pe_hist_sources: list[str] = []
    for row in df.itertuples(index=False):
        closes = extract_close_history_from_bars(bars_map.get(row.symbol, []))
        revenue_hist = parse_history_pairs(getattr(row, "revenue_ttm_history_json", None))
        net_income_hist = parse_history_pairs(getattr(row, "net_income_ttm_history_json", None))
        shares_hist = parse_history_pairs(getattr(row, "shares_history_json", None))

        current_shares_raw = getattr(row, "shares_outstanding", None)
        current_shares = None
        try:
            if current_shares_raw is not None:
                current_shares = float(current_shares_raw)
        except (TypeError, ValueError):
            current_shares = None
        if current_shares is not None and (not np.isfinite(current_shares) or current_shares <= 0):
            current_shares = None

        current_ps_raw = getattr(row, "ps", None)
        current_ps = None
        try:
            if current_ps_raw is not None:
                current_ps = float(current_ps_raw)
        except (TypeError, ValueError):
            current_ps = None
        if current_ps is not None and (not np.isfinite(current_ps) or current_ps <= 0):
            current_ps = None

        current_pe_raw = getattr(row, "pe", None)
        current_pe = None
        try:
            if current_pe_raw is not None:
                current_pe = float(current_pe_raw)
        except (TypeError, ValueError):
            current_pe = None
        if current_pe is not None and (not np.isfinite(current_pe) or current_pe <= 0):
            current_pe = None

        ps_hist_pct, ps_obs = compute_historical_valuation_percentile(
            current_multiple=current_ps,
            closes=closes,
            denominator_history=revenue_hist,
            shares_history=shares_hist,
            current_shares=current_shares,
            window_days=config.own_history_valuation_window_days,
            min_observations=3,
        )
        pe_hist_pct, pe_obs = compute_historical_valuation_percentile(
            current_multiple=current_pe,
            closes=closes,
            denominator_history=net_income_hist,
            shares_history=shares_hist,
            current_shares=current_shares,
            window_days=config.own_history_valuation_window_days,
            min_observations=3,
        )
        ps_hist_values.append(ps_hist_pct)
        pe_hist_values.append(pe_hist_pct)
        ps_hist_obs.append(int(ps_obs))
        pe_hist_obs.append(int(pe_obs))
        ps_hist_sources.append("valuation_history" if ps_hist_pct is not None else "insufficient_history")
        pe_hist_sources.append("valuation_history" if pe_hist_pct is not None else "insufficient_history")

    df["ps_hist_percentile"] = ps_hist_values
    df["pe_hist_percentile"] = pe_hist_values
    df["ps_hist_observation_count"] = ps_hist_obs
    df["pe_hist_observation_count"] = pe_hist_obs
    df["ps_hist_percentile_source"] = ps_hist_sources
    df["pe_hist_percentile_source"] = pe_hist_sources
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
        pd.Series(float(config.assumed_position_usd), index=df.index),
        df["avg_dollar_volume_20d"],
    )
    df["estimated_slippage_bps"] = 200.0 * np.sqrt(
        pd.to_numeric(df["adv_participation"], errors="coerce").clip(lower=0)
    )

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

    # SIC-relative valuation percentile (lower is cheaper); fall back to neutral 0.5 for tiny cohorts.
    df["ps_percentile_in_sic"] = 0.5
    ps_valid = np.isfinite(df["ps"]) & (df["ps"] > 0) & df["sic"].notna()
    ps_sizes = df.loc[ps_valid].groupby("sic")["ps"].transform("size")
    ps_rank = df.loc[ps_valid].groupby("sic")["ps"].rank(method="average", pct=True)
    ps_eligible_idx = ps_sizes[ps_sizes >= 5].index
    df.loc[ps_eligible_idx, "ps_percentile_in_sic"] = ps_rank.loc[ps_eligible_idx]

    df["pe_percentile_in_sic"] = 0.5
    pe_valid = np.isfinite(df["pe"]) & (df["pe"] > 0) & df["sic"].notna()
    pe_sizes = df.loc[pe_valid].groupby("sic")["pe"].transform("size")
    pe_rank = df.loc[pe_valid].groupby("sic")["pe"].rank(method="average", pct=True)
    pe_eligible_idx = pe_sizes[pe_sizes >= 5].index
    df.loc[pe_eligible_idx, "pe_percentile_in_sic"] = pe_rank.loc[pe_eligible_idx]

    top_n_low_value = resolve_top_n(config.top_n_per_channel_low_value, 10)
    top_n_trend = resolve_top_n(config.top_n_per_channel_trend, 10)
    top_n_momentum = resolve_top_n(config.top_n_per_channel_momentum, 10)
    channel_profiles = config.channel_profiles or {"core_ai": {}}
    log_status(started_at, "INFO", "[5/6] Applying watchlist attributes.")
    df = df.merge(watchlist_scores, on="symbol", how="left")
    for missing_col, default_val in [
        ("watchlist_etf_count", 0),
        ("watchlist_bucket", ""),
        ("watchlist_etfs", ""),
    ]:
        if missing_col not in df.columns:
            df[missing_col] = default_val
    df["watchlist_etf_count"] = pd.to_numeric(df["watchlist_etf_count"], errors="coerce").fillna(0).astype(int)
    df["watchlist_bucket"] = df["watchlist_bucket"].fillna("").astype(str)
    df["watchlist_etfs"] = df["watchlist_etfs"].fillna("").astype(str)
    df["ai_etf_consensus_score"] = df["watchlist_etf_count"].apply(
        lambda x: ai_etf_consensus_score(x, config.ai_link_etf_count_saturation)
    )
    df["ai_market_link_score"] = df.apply(
        lambda row: ai_market_link_score(
            symbol_return_20d=(
                float(row["return_20d"])
                if pd.notna(pd.to_numeric(row["return_20d"], errors="coerce"))
                else None
            ),
            symbol_return_60d=(
                float(row["return_60d"])
                if pd.notna(pd.to_numeric(row["return_60d"], errors="coerce"))
                else None
            ),
            benchmark_return_20d=benchmark_median_return_20d,
            benchmark_return_60d=benchmark_median_return_60d,
            tol_20d=float(config.ai_link_market_return_tolerance_20d),
            tol_60d=float(config.ai_link_market_return_tolerance_60d),
        ),
        axis=1,
    )
    if "ai_disclosure_score" not in df.columns:
        df["ai_disclosure_score"] = 0.0
    if "ai_backlog_signal" not in df.columns:
        df["ai_backlog_signal"] = 0.0
    df["ai_disclosure_score"] = pd.to_numeric(df["ai_disclosure_score"], errors="coerce").fillna(0.0)
    df["ai_backlog_signal"] = pd.to_numeric(df["ai_backlog_signal"], errors="coerce").fillna(0.0)
    df["ai_link_score"] = (
        0.40 * pd.to_numeric(df["ai_etf_consensus_score"], errors="coerce").fillna(0.0)
        + 0.35 * pd.to_numeric(df["ai_disclosure_score"], errors="coerce").fillna(0.0)
        + 0.15 * pd.to_numeric(df["ai_market_link_score"], errors="coerce").fillna(0.0)
        + 0.10 * pd.to_numeric(df["ai_backlog_signal"], errors="coerce").fillna(0.0)
    ).clip(lower=0.0, upper=1.0)
    df["news_count"] = 0

    watchlist_counts: dict[str, int] = {}
    for channel_name in channel_profiles.keys():
        channel_mask = df["watchlist_bucket"].str.contains(
            rf"(?:^|,){re.escape(str(channel_name))}(?:,|$)", regex=True
        )
        watchlist_counts[channel_name] = int(channel_mask.sum())
    watchlist_symbol_count = int(watchlist_member_mask(df).sum())
    log_status(started_at, "INFO", "Watchlist candidates by channel:")
    for channel_name, count in watchlist_counts.items():
        log_status(started_at, "INFO", f"  {channel_name}: {count}")
    log_status(started_at, "INFO", f"Watchlist matched symbols: {watchlist_symbol_count}")
    log_status(
        started_at,
        "INFO",
        f"Per-channel output caps => low_value={top_n_low_value}, trend={top_n_trend}, momentum={top_n_momentum}",
    )

    ranked_frames: list[pd.DataFrame] = []
    filtered_counts: dict[str, int] = {}
    diagnostics_layer_summary: dict[str, dict[str, dict[str, float | int]]] = {}
    first_fail_concentration_summary: dict[str, dict[str, Any]] = {}

    for channel_name, channel_profile in channel_profiles.items():
        cp = resolve_channel_profile(config, channel_name, channel_profile)
        steps = build_filter_steps(config, channel_name, channel_profile)
        filtered, diagnostics = apply_filters_with_diagnostics(df, steps)
        first_fail_summary = summarize_first_fail_reasons(df, steps)

        log_status(started_at, "INFO", f"Channel={channel_name}: filter diagnostics")
        for row in diagnostics[1:]:
            log_status(
                started_at,
                "INFO",
                f"  {row['step']}: -{row['removed']} => {row['remaining']} "
                f"(pass={float(row.get('pass_rate', 0.0)):.2%}, layer={row.get('layer', 'n/a')})",
            )

        layer_stats = summarize_diagnostics_by_layer(diagnostics)
        diagnostics_layer_summary[channel_name] = layer_stats
        for layer_name in ["base_hard", "quality_or_theme_hard", "valuation_hard"]:
            row = layer_stats.get(layer_name)
            if not row:
                continue
            log_status(
                started_at,
                "INFO",
                f"  Layer {layer_name}: before={int(row.get('before', 0) or 0)} "
                f"remaining={int(row.get('remaining', 0) or 0)} "
                f"removed={int(row.get('removed', 0) or 0)} "
                f"pass={float(row.get('pass_rate', 0.0) or 0.0):.2%}",
            )

        log_status(started_at, "INFO", "  First-fail summary:")
        for row in first_fail_summary.itertuples(index=False):
            log_status(started_at, "INFO", f"  {row.reason}: {row.count} ({row.pct:.2%})")
        concentration = first_fail_concentration(first_fail_summary)
        first_fail_concentration_summary[channel_name] = concentration
        log_status(
            started_at,
            "INFO",
            f"  First-fail concentration: reason={concentration['top_reason']} "
            f"count={concentration['top_count']} pct={concentration['top_pct']:.2%}",
        )

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

        ranked = score_and_rank(
            filtered,
            cp["score_weights"],
            config.score_winsor_lower_q,
            config.score_winsor_upper_q,
            config.score_penalty_overvaluation,
            config.score_penalty_deterioration,
        )
        ranked = apply_group_caps(
            ranked,
            config.max_per_sector_per_list,
            config.max_per_watchlist_etf_source_per_list,
        ).head(top_n_low_value)
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
    if config.enforce_unique_symbol_per_list:
        ranked, removed = dedupe_symbol_by_best_channel(ranked)
        log_status(started_at, "INFO", f"Low-Value channel-overlap dedupe removed: {removed}")

    out_path = paths["ranked_csv"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "channel",
        "primary_channel",
        "eligible_channels",
        "channel_scores",
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
        "return_60d",
        "volatility_60d",
        "avg_dollar_volume_20d",
        "market_cap",
        "enterprise_value",
        "revenue",
        "net_income",
        "adjusted_net_income",
        "operating_cash_flow",
        "free_cash_flow",
        "ebit",
        "adjusted_ebit",
        "adjusted_ebitda",
        "nonrecurring_expense_addback",
        "nonrecurring_gain_subtraction",
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
        "interest_coverage",
        "net_debt_to_ebitda",
        "current_ratio",
        "current_debt_ratio_reported",
        "current_debt_ratio_inferred",
        "current_debt_ratio",
        "current_debt_ratio_source",
        "ocf_to_net_income",
        "accrual_ratio",
        "fundamental_quality_score",
        "inventory_growth_gap_reported",
        "inventory_growth_gap_inferred",
        "inventory_growth_gap_source",
        "ai_etf_consensus_score",
        "ai_disclosure_score",
        "ai_disclosure_group_hits",
        "ai_disclosure_keyword_hits",
        "ai_market_link_score",
        "ai_backlog_signal",
        "ai_link_score",
        "ps_hist_percentile",
        "pe_hist_percentile",
        "ps_hist_observation_count",
        "pe_hist_observation_count",
        "ps_hist_percentile_source",
        "pe_hist_percentile_source",
        "expectation_proxy",
        "cycle_proxy",
        "adv_participation",
        "estimated_slippage_bps",
        "net_margin",
        "ps",
        "pe",
        "ev_to_ebit",
        "fcf_yield",
        "peer_median_ps",
        "peer_median_pe",
        "ps_discount",
        "pe_discount",
        "ps_percentile_in_sic",
        "pe_percentile_in_sic",
        "overvaluation_penalty",
        "deterioration_penalty",
        "watchlist_bucket",
        "watchlist_etf_count",
        "watchlist_etfs",
        "news_count",
        "composite_score",
        "research_priority",
        "research_score",
        "research_tags",
        "research_risks",
        "research_summary",
    ]

    def attach_channel_membership_columns(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for col, default in [
            ("eligible_channels", ""),
            ("channel_scores", "{}"),
            ("primary_channel", ""),
        ]:
            if col not in out.columns:
                out[col] = default
        if out.empty or "symbol" not in out.columns or "channel" not in out.columns:
            return out

        work = out.copy()
        work["_symbol"] = work["symbol"].astype(str)
        work["_channel"] = work["channel"].fillna("").astype(str)
        work["_score"] = pd.to_numeric(work.get("composite_score"), errors="coerce")
        work = work.sort_values(
            by=["_symbol", "_score", "_channel"],
            ascending=[True, False, True],
        )

        eligible_map: dict[str, str] = {}
        scores_map: dict[str, str] = {}
        primary_map: dict[str, str] = {}
        for symbol, grp in work.groupby("_symbol", dropna=False):
            if not symbol or symbol.lower() == "nan":
                continue
            channels: list[str] = []
            score_dict: dict[str, float | None] = {}
            for _, row in grp.iterrows():
                channel = str(row.get("_channel", "") or "")
                if not channel or channel in score_dict:
                    continue
                raw_score = row.get("_score", np.nan)
                if pd.notna(raw_score) and np.isfinite(raw_score):
                    score_dict[channel] = round(float(raw_score), 6)
                else:
                    score_dict[channel] = None
                channels.append(channel)
            if not channels:
                continue
            eligible_map[symbol] = ",".join(channels)
            primary_map[symbol] = channels[0]
            scores_map[symbol] = json.dumps(score_dict, ensure_ascii=False, separators=(",", ":"))

        out["_symbol"] = out["symbol"].astype(str)
        out["eligible_channels"] = out["_symbol"].map(eligible_map).fillna("")
        out["channel_scores"] = out["_symbol"].map(scores_map).fillna("{}")
        out["primary_channel"] = out["_symbol"].map(primary_map).fillna("")
        out = out.drop(columns=["_symbol"], errors="ignore")
        return out

    def ensure_export_columns(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for col in cols + ["triage_label"]:
            if col not in out.columns:
                out[col] = np.nan
        return out

    ranked = apply_triage_labels(ranked, config.triage_rules)
    ranked = apply_research_assessment(ranked, "low_value")
    ranked = attach_channel_membership_columns(ranked)
    if ranked.empty:
        ranked = pd.DataFrame(columns=cols + ["triage_label"])
    else:
        ranked = ranked.sort_values(["channel", "composite_score"], ascending=[True, False])
    ranked = ensure_export_columns(ranked)
    ranked.to_csv(out_path, index=False, columns=cols + ["triage_label"])

    for channel_name in channel_profiles.keys():
        ch_out = out_path.with_name(f"{out_path.stem}_{channel_name}{out_path.suffix or '.csv'}")
        if "channel" in ranked.columns:
            channel_df = ranked[ranked["channel"] == channel_name]
        else:
            channel_df = ranked.copy()
        if channel_df.empty:
            channel_df = pd.DataFrame(columns=cols + ["triage_label"])
        channel_df = ensure_export_columns(channel_df)
        channel_df.to_csv(ch_out, index=False, columns=cols + ["triage_label"])
        log_status(started_at, "INFO", f"Channel output ({channel_name}): {ch_out}")

    # Build a second list focused on AI industry trend relevance, without
    # enforcing low-position/value constraints.
    trend_frames: list[pd.DataFrame] = []
    for channel_name, channel_profile in channel_profiles.items():
        trend_steps, trend_weights = build_industry_trend_steps(config, channel_name, channel_profile)
        trend_filtered, _ = apply_filters_with_diagnostics(df, trend_steps)
        trend_ranked = score_and_rank(
            trend_filtered,
            trend_weights,
            config.score_winsor_lower_q,
            config.score_winsor_upper_q,
            config.score_penalty_overvaluation,
            config.score_penalty_deterioration,
        )
        trend_ranked = apply_group_caps(
            trend_ranked,
            config.max_per_sector_per_list,
            config.max_per_watchlist_etf_source_per_list,
        ).head(top_n_trend)
        trend_ranked["channel"] = channel_name
        trend_frames.append(trend_ranked)

    non_empty_trend_frames = [frame for frame in trend_frames if not frame.empty]
    industry_trend = (
        pd.concat(non_empty_trend_frames, ignore_index=True)
        if non_empty_trend_frames
        else pd.DataFrame(columns=df.columns.tolist() + ["channel", "composite_score"])
    )
    if config.enforce_unique_symbol_per_list:
        industry_trend, removed = dedupe_symbol_by_best_channel(industry_trend)
        log_status(started_at, "INFO", f"Industry-Trend channel-overlap dedupe removed: {removed}")
    if config.enforce_unique_symbol_across_lists:
        low_symbols = set(ranked["symbol"].dropna().astype(str).tolist())
        industry_trend, removed = drop_symbols(industry_trend, low_symbols)
        log_status(started_at, "INFO", f"Industry-Trend cross-list dedupe removed: {removed}")
    industry_trend["triage_label"] = "trend"
    industry_trend = apply_research_assessment(industry_trend, "industry_trend")
    industry_trend = attach_channel_membership_columns(industry_trend)
    if not industry_trend.empty:
        industry_trend = industry_trend.sort_values(["channel", "composite_score"], ascending=[True, False])
    industry_trend = ensure_export_columns(industry_trend)
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
        ch_trend_df = ensure_export_columns(ch_trend_df)
        ch_trend_df.to_csv(ch_trend_out, index=False, columns=cols + ["triage_label"])
        log_status(started_at, "INFO", f"Industry trend output ({channel_name}): {ch_trend_out}")
    log_status(started_at, "INFO", f"Industry trend output: {trend_out_path}")

    # Build a third list focused on momentum/chasing strength.
    momentum_frames: list[pd.DataFrame] = []
    for channel_name, channel_profile in channel_profiles.items():
        momentum_steps, momentum_weights = build_momentum_steps(config, channel_name, channel_profile)
        momentum_filtered, _ = apply_filters_with_diagnostics(df, momentum_steps)
        momentum_ranked = score_and_rank(
            momentum_filtered,
            momentum_weights,
            config.score_winsor_lower_q,
            config.score_winsor_upper_q,
            config.score_penalty_overvaluation,
            config.score_penalty_deterioration,
        )
        momentum_ranked = apply_group_caps(
            momentum_ranked,
            config.max_per_sector_per_list,
            config.max_per_watchlist_etf_source_per_list,
        ).head(top_n_momentum)
        momentum_ranked["channel"] = channel_name
        momentum_frames.append(momentum_ranked)

    non_empty_momentum_frames = [frame for frame in momentum_frames if not frame.empty]
    momentum = (
        pd.concat(non_empty_momentum_frames, ignore_index=True)
        if non_empty_momentum_frames
        else pd.DataFrame(columns=df.columns.tolist() + ["channel", "composite_score"])
    )
    if config.enforce_unique_symbol_per_list:
        momentum, removed = dedupe_symbol_by_best_channel(momentum)
        log_status(started_at, "INFO", f"Momentum channel-overlap dedupe removed: {removed}")
    if config.enforce_unique_symbol_across_lists:
        prior_symbols = set(ranked["symbol"].dropna().astype(str).tolist()) | set(
            industry_trend["symbol"].dropna().astype(str).tolist()
        )
        momentum, removed = drop_symbols(momentum, prior_symbols)
        log_status(started_at, "INFO", f"Momentum cross-list dedupe removed: {removed}")
    momentum["triage_label"] = "momentum"
    momentum = apply_research_assessment(momentum, "momentum")
    momentum = attach_channel_membership_columns(momentum)
    if not momentum.empty:
        momentum = momentum.sort_values(["channel", "composite_score"], ascending=[True, False])
    momentum = ensure_export_columns(momentum)
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
        ch_momentum_df = ensure_export_columns(ch_momentum_df)
        ch_momentum_df.to_csv(ch_momentum_out, index=False, columns=cols + ["triage_label"])
        log_status(started_at, "INFO", f"Momentum output ({channel_name}): {ch_momentum_out}")
    log_status(started_at, "INFO", f"Momentum output: {momentum_out_path}")

    # Build a wider research pool from the watchlist universe after price/liquidity
    # and data enrichment. This is intentionally not a buy list.
    research_pool = df.copy()
    if "channel" not in research_pool.columns:
        research_pool["channel"] = ""

    def infer_research_channel(row: pd.Series) -> str:
        bucket = str(row.get("watchlist_bucket", "") or "")
        for channel_name in channel_profiles.keys():
            if channel_name in bucket:
                return channel_name
        return str(row.get("channel", "") or "")

    if not research_pool.empty:
        research_pool["channel"] = research_pool.apply(infer_research_channel, axis=1)
        research_pool["triage_label"] = "research_pool"
        research_pool = apply_research_assessment(research_pool, "research_pool")
        research_pool["composite_score"] = pd.to_numeric(
            research_pool["research_score"], errors="coerce"
        )
        research_pool = research_pool[
            (pd.to_numeric(research_pool["research_score"], errors="coerce").fillna(-np.inf) >= config.research_pool_min_score)
            & (research_pool["research_priority"].astype(str) != "avoid_for_now")
        ].copy()
        research_pool = apply_group_caps(
            research_pool,
            config.max_per_sector_per_list,
            config.max_per_watchlist_etf_source_per_list,
        )
        priority_order = {
            "research_now": 0,
            "watch_for_pullback": 1,
            "theme_only": 2,
            "avoid_for_now": 3,
        }
        research_pool["_research_priority_rank"] = (
            research_pool["research_priority"].map(priority_order).fillna(9).astype(int)
        )
        research_pool = research_pool.sort_values(
            ["_research_priority_rank", "research_score", "ai_link_score"],
            ascending=[True, False, False],
        ).head(max(1, int(config.research_pool_top_n)))
        research_pool = research_pool.drop(columns=["_research_priority_rank"], errors="ignore")
        research_pool = attach_channel_membership_columns(research_pool)
    else:
        research_pool = pd.DataFrame(columns=cols + ["triage_label"])
    research_pool = ensure_export_columns(research_pool)
    research_pool_out_path = out_path.with_name(
        f"{out_path.stem}_research_pool{out_path.suffix or '.csv'}"
    )
    research_pool.to_csv(research_pool_out_path, index=False, columns=cols + ["triage_label"])
    log_status(started_at, "INFO", f"Research pool output: {research_pool_out_path}")

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
        "top_n_per_channel_low_value": top_n_low_value,
        "top_n_per_channel_trend": top_n_trend,
        "top_n_per_channel_momentum": top_n_momentum,
        "research_pool_top_n": int(config.research_pool_top_n),
        "research_pool_min_score": float(config.research_pool_min_score),
        "enforce_unique_symbol_per_list": bool(config.enforce_unique_symbol_per_list),
        "enforce_unique_symbol_across_lists": bool(config.enforce_unique_symbol_across_lists),
        "watchlist_csv_path": config.watchlist_csv_path,
        "ai_link_benchmark_etfs": config.ai_link_benchmark_etfs,
        "ai_link_etf_count_saturation": config.ai_link_etf_count_saturation,
        "ai_link_disclosure_keyword_cap": config.ai_link_disclosure_keyword_cap,
        "ai_link_market_return_tolerance_20d": config.ai_link_market_return_tolerance_20d,
        "ai_link_market_return_tolerance_60d": config.ai_link_market_return_tolerance_60d,
        "ai_link_backlog_ratio_cap": config.ai_link_backlog_ratio_cap,
        "ai_link_benchmark_median_return_20d": benchmark_median_return_20d,
        "ai_link_benchmark_median_return_60d": benchmark_median_return_60d,
        "watchlist_core_etfs": config.watchlist_core_etfs,
        "watchlist_enabler_etfs": config.watchlist_enabler_etfs,
        "watchlist_peripheral_etfs": config.watchlist_peripheral_etfs,
        "use_ttm_metrics": bool(config.use_ttm_metrics),
        "use_adjusted_quality_metrics": bool(config.use_adjusted_quality_metrics),
        "min_fundamental_quality_score": config.min_fundamental_quality_score,
        "max_net_debt_to_ebitda": config.max_net_debt_to_ebitda,
        "min_interest_coverage": config.min_interest_coverage,
        "metric_hard_filter_coverage_mode": config.metric_hard_filter_coverage_mode,
        "force_hard_filter_low_coverage_metrics": bool(config.force_hard_filter_low_coverage_metrics),
        "low_coverage_soft_score_weights": config.low_coverage_soft_score_weights,
        "max_adv_participation": config.max_adv_participation,
        "max_estimated_slippage_bps": config.max_estimated_slippage_bps,
        "diagnostics_layer_summary": diagnostics_layer_summary,
        "first_fail_concentration_summary": first_fail_concentration_summary,
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
        research_pool=research_pool,
        research_pool_path=research_pool_out_path,
        diagnostics_layer_summary=diagnostics_layer_summary,
        first_fail_concentration_summary=first_fail_concentration_summary,
    )
    paths["report_md"].write_text(md_report)
    log_status(started_at, "INFO", f"Detailed report: {paths['report_md']}")

    print("")
    print("=== Low-Value Shortlist (All Selected Per Channel) ===")
    if ranked.empty:
        print("No candidates.")
    else:
        for channel_name in channel_profiles.keys():
            print(f"[{channel_name}]")
            top = ranked[ranked["channel"] == channel_name].sort_values(
                "composite_score", ascending=False
            )
            if top.empty:
                print("  - none")
                continue
            for _, row in top.iterrows():
                print(
                    "  - "
                    f"{row['symbol']} | triage={row['triage_label']} | "
                    f"research={row.get('research_priority', '')} | "
                    f"score={float(row['composite_score']):.3f} | "
                    f"ai_link={float(row.get('ai_link_score', 0.0) or 0.0):.3f} | "
                    f"psd={float(row['ps_discount']):.3f} | "
                    f"ped={float(row['pe_discount']):.3f} | "
                    f"risks={str(row.get('research_risks', ''))} | "
                    f"bucket={str(row.get('watchlist_bucket', ''))} | "
                    f"etf_count={int(row.get('watchlist_etf_count', 0) or 0)} | "
                    f"etfs={str(row.get('watchlist_etfs', ''))}"
                )
    print("=== End Low-Value Shortlist ===")
    print("")
    print("=== Industry Trend Shortlist (All Selected Per Channel) ===")
    if industry_trend.empty:
        print("No industry trend candidates.")
    else:
        for channel_name in channel_profiles.keys():
            print(f"[{channel_name}]")
            top = industry_trend[industry_trend["channel"] == channel_name].sort_values(
                "composite_score", ascending=False
            )
            if top.empty:
                print("  - none")
                continue
            for _, row in top.iterrows():
                print(
                    "  - "
                    f"{row['symbol']} | research={row.get('research_priority', '')} | "
                    f"score={float(row['composite_score']):.3f} | "
                    f"ai_link={float(row.get('ai_link_score', 0.0) or 0.0):.3f} | "
                    f"tags={str(row.get('research_tags', ''))} | "
                    f"bucket={str(row.get('watchlist_bucket', ''))} | "
                    f"etf_count={int(row.get('watchlist_etf_count', 0) or 0)} | "
                    f"etfs={str(row.get('watchlist_etfs', ''))}"
                )
    print("=== End Industry Trend Shortlist ===")
    print("")
    print("=== Momentum Shortlist (All Selected Per Channel) ===")
    if momentum.empty:
        print("No momentum candidates.")
    else:
        for channel_name in channel_profiles.keys():
            print(f"[{channel_name}]")
            top = momentum[momentum["channel"] == channel_name].sort_values(
                "composite_score", ascending=False
            )
            if top.empty:
                print("  - none")
                continue
            for _, row in top.iterrows():
                print(
                    "  - "
                    f"{row['symbol']} | research={row.get('research_priority', '')} | "
                    f"score={float(row['composite_score']):.3f} | "
                    f"ai_link={float(row.get('ai_link_score', 0.0) or 0.0):.3f} | "
                    f"r20={float(row['return_20d']):.3f} | "
                    f"tags={str(row.get('research_tags', ''))} | "
                    f"bucket={str(row.get('watchlist_bucket', ''))} | "
                    f"etf_count={int(row.get('watchlist_etf_count', 0) or 0)} | "
                    f"etfs={str(row.get('watchlist_etfs', ''))}"
                )
    print("=== End Momentum Shortlist ===")
    print("")
    print("=== Research Pool (Broader Candidates) ===")
    if research_pool.empty:
        print("No research pool candidates.")
    else:
        priority_order = {
            "research_now": 0,
            "watch_for_pullback": 1,
            "theme_only": 2,
            "avoid_for_now": 3,
        }
        display_pool = research_pool.copy()
        display_pool["_priority_rank"] = (
            display_pool["research_priority"].map(priority_order).fillna(9).astype(int)
        )
        display_pool = display_pool.sort_values(
            ["_priority_rank", "research_score"], ascending=[True, False]
        )
        for _, row in display_pool.iterrows():
            print(
                "  - "
                f"{row['symbol']} | priority={row.get('research_priority', '')} | "
                f"score={float(row.get('research_score', 0.0) or 0.0):.3f} | "
                f"channel={str(row.get('channel', ''))} | "
                f"ai_link={float(row.get('ai_link_score', 0.0) or 0.0):.3f} | "
                f"tags={str(row.get('research_tags', ''))} | "
                f"risks={str(row.get('research_risks', ''))}"
            )
    print("=== End Research Pool ===")
    log_status(started_at, "INFO", "Scan completed successfully.")
    return out_path


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

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
