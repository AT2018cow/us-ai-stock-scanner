from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


from ai_value_scanner.config import (
    ScanConfig,
    default_ai_link_benchmark_etfs,
    default_channel_profiles,
    default_low_coverage_soft_score_weights,
    default_triage_rules,
    default_watchlist_core_etfs,
    default_watchlist_enabler_etfs,
    default_watchlist_peripheral_etfs,
    load_config,
    merge_soft_score_weights,
    resolve_channel_profile,
)


from ai_value_scanner.fundamentals.accounting import (
    clamp01,
    compute_adjusted_metrics,
    derive_accounting_metrics,
    fundamental_quality_score_from_metrics,
    safe_yoy,
)
from ai_value_scanner.fundamentals.facts import (
    PeriodValue,
    collapse_fact_records_by_end,
    extract_fact_records,
    merged_standard_taxonomy_facts,
    normalize_form,
)
from ai_value_scanner.fundamentals.edgartools_fallback import (
    EDGARTOOLS_FALLBACK_VERSION,
    fetch_usd_10q_companyfacts_patch,
    merge_companyfacts_patch,
)
from ai_value_scanner.fundamentals.reconstruction import (
    ReconstructedFlows,
    current_ttm_pair,
    latest_and_year_ago_level as shared_latest_and_year_ago_level,
    reconstruct_flow_periods,
    rolling_ttm_points,
    ttm_points_with_annual_fallback,
)
from ai_value_scanner.fundamentals.shares import assess_share_count_integrity

from ai_value_scanner.features.derived import compute_cross_section_derived_features
from ai_value_scanner.features.ai_link import (
    ai_etf_consensus_score,
    ai_market_link_score,
    compute_ai_link_score,
)
from ai_value_scanner.features.peer_valuation import compute_peer_relative_valuation
from ai_value_scanner.features.price import (
    compute_price_history_features,
    price_history_percentile_from_closes,
)
from ai_value_scanner.features.valuation import (
    compute_historical_valuation_percentile,
    lookup_close_on_or_before,
    lookup_value_on_or_before,
    safe_divide,
)

from ai_value_scanner.strategy.scoring import robust_normalize_score, score_and_rank
from ai_value_scanner.strategy.rules import (
    HIGH_COVERAGE_HARD_FILTER_METRICS,
    LOW_COVERAGE_HARD_FILTER_METRICS,
    MEDIUM_COVERAGE_HARD_FILTER_METRICS,
    append_professional_filter_steps,
    build_benchmark_trend_step,
    build_filter_steps,
    build_industry_trend_steps,
    build_momentum_steps,
    channel_bucket_mask,
    hard_filter_metric_enabled,
    passes_sic_filters,
    percentile_cap_mask,
    percentile_floor_mask,
    watchlist_member_mask,
)
from ai_value_scanner.strategy.research import (
    apply_low_value_research_gate,
    apply_research_assessment,
    apply_triage_labels,
    assign_triage_label,
    build_research_assessment,
    metric_float,
    text_has_any,
)
from ai_value_scanner.strategy.filtering import (
    CORE_FILTER_STEP_NAMES,
    STYLE_STRUCTURAL_STEP_NAMES,
    apply_filters_with_diagnostics,
    apply_scored_or_hard_filters,
    classify_filter_step_layer,
    first_fail_concentration,
    partition_filter_steps,
    summarize_diagnostics_by_layer,
    summarize_first_fail_reasons,
)
from ai_value_scanner.strategy.selection import (
    apply_group_caps,
    dedupe_symbol_by_best_channel,
    drop_symbols,
)
from ai_value_scanner.decision import (
    DEFAULT_ATTENTION_CAP,
    build_source_list_membership,
    build_stock_decisions,
    decisions_by_symbol,
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.reporting.snapshot import (
    load_previous_snapshot,
    resolve_git_commit_sha,
    write_decision_snapshot,
)

from ai_value_scanner.reporting.scan import (
    build_run_report_markdown,
    default_run_stem,
    log_status,
    resolve_output_paths,
    write_csv_atomic,
)


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

# Two-layer filter architecture: core hard gates + soft scoring dimensions.
# Core gates are one-vote vetoes shared by both styles; style-structural gates
# define each style's identity. Everything else becomes a soft pass/fail that
# contributes to composite_score instead of eliminating the stock.
EPS_TAGS = [
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
]
OPERATING_CASH_FLOW_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    # Fallback tags for filers that do not use the PP&E line (e.g. QCOM and
    # GEV tag capex as generic "productive assets" purchases). Same-period
    # collisions resolve by tag order, so these only fill gaps.
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherProductiveAssets",
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
    # Fallback tags for filers that do not use the two standards above
    # (e.g. GOOGL tags its cash-flow line as plain "Depreciation"). When the
    # same (start,end) period exists under an earlier tag, that tag wins —
    # these only fill periods the primary tags do not cover.
    "DepreciationAmortizationAndAccretionNet",
    "Depreciation",
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
FUNDAMENTAL_FILING_COVERAGE_TAGS = frozenset(
    REVENUE_TAGS + NET_INCOME_TAGS + OPERATING_CASH_FLOW_TAGS
)

FUNDAMENTAL_DATA_ASOF_TAGS = frozenset(
    REVENUE_TAGS
    + NET_INCOME_TAGS
    + SHARES_TAGS
    + EPS_TAGS
    + OPERATING_CASH_FLOW_TAGS
    + CAPEX_TAGS
    + CASH_AND_EQUIVALENTS_TAGS
    + LONG_TERM_DEBT_TAGS
    + CURRENT_DEBT_TAGS
    + EBIT_TAGS
    + NONRECURRING_EXPENSE_TAGS
    + NONRECURRING_GAIN_TAGS
    + INTEREST_EXPENSE_TAGS
    + DA_TAGS
    + ASSETS_CURRENT_TAGS
    + LIABILITIES_CURRENT_TAGS
    + RECEIVABLES_CURRENT_TAGS
    + INVENTORY_TAGS
)

CORE_MONETARY_CURRENCY_TAGS = frozenset(
    REVENUE_TAGS
    + NET_INCOME_TAGS
    + OPERATING_CASH_FLOW_TAGS
    + [
        # Common IFRS taxonomy concepts used only to detect reporting
        # currency. They are not silently promoted into the USD accounting
        # path without explicit normalization.
        "Revenue",
        "CashFlowsFromUsedInOperatingActivities",
    ]
)
_CURRENCY_UNIT_PATTERN = re.compile(r"^[A-Z]{3}$")

EDGARTOOLS_FALLBACK_ALLOWED_TAGS = frozenset(
    set(FUNDAMENTAL_DATA_ASOF_TAGS)
    .union(SHARES_TAGS)
    .union(EPS_TAGS)
    .union(BACKLOG_TAGS)
)
EDGARTOOLS_FALLBACK_CORE_TAG_GROUPS: dict[str, tuple[str, ...]] = {
    "revenue": tuple(REVENUE_TAGS),
    "net_income": tuple(NET_INCOME_TAGS),
    "operating_cash_flow": tuple(OPERATING_CASH_FLOW_TAGS),
}

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
        self._data_provenance: dict[str, dict[str, dict[str, Any]]] = {}

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

    def record_data_source(
        self,
        service: str,
        namespace: str,
        source: str,
        cache_age_sec: float | None = None,
        *,
        data_asof_utc: str | None = None,
        feed: str | None = None,
        degraded_reason: str | None = None,
    ) -> None:
        """Record returned-data provenance separately from cache file age."""
        with self._lock:
            service_map = self._data_provenance.setdefault(service, {})
            row = service_map.setdefault(
                namespace,
                {
                    "counts": {},
                    "max_cache_age_sec": None,
                    "latest_data_asof_utc": None,
                    "feed": None,
                    "degraded_reasons": [],
                    "last_observed_at_utc": None,
                    "stale_fallback_used": False,
                },
            )
            counts = row["counts"]
            counts[source] = int(counts.get(source, 0)) + 1
            row["last_observed_at_utc"] = datetime.now(timezone.utc).isoformat()
            if cache_age_sec is not None and np.isfinite(float(cache_age_sec)):
                age = max(0.0, float(cache_age_sec))
                previous = row.get("max_cache_age_sec")
                row["max_cache_age_sec"] = age if previous is None else max(float(previous), age)
            if data_asof_utc:
                previous_asof = row.get("latest_data_asof_utc")
                if previous_asof is None or str(data_asof_utc) > str(previous_asof):
                    row["latest_data_asof_utc"] = str(data_asof_utc)
            if feed:
                row["feed"] = str(feed)
            if degraded_reason:
                reasons = row["degraded_reasons"]
                if degraded_reason not in reasons:
                    reasons.append(str(degraded_reason))
            if source in {"stale_cache_fallback", "stale_cross_key_fallback"}:
                row["stale_fallback_used"] = True

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
            provenance = json.loads(json.dumps(self._data_provenance))
            stale_market_data = any(
                bool(row.get("stale_fallback_used"))
                for service_map in provenance.values()
                for row in service_map.values()
            )
            return {
                "had_rate_limit_or_network_issue": any_issue,
                "stale_market_data_fallback_used": stale_market_data,
                "data_provenance": provenance,
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

    @staticmethod
    def _payload_data_asof(namespace: str, payload: Any) -> str | None:
        timestamps: list[str] = []
        if namespace == "bars" and isinstance(payload, dict):
            for rows in payload.values():
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if isinstance(row, dict) and row.get("t"):
                        timestamps.append(str(row["t"]))
        elif namespace == "snapshots" and isinstance(payload, dict):
            for snap in payload.values():
                if not isinstance(snap, dict):
                    continue
                for key in ("latestTrade", "latestQuote", "minuteBar", "dailyBar", "prevDailyBar"):
                    item = snap.get(key)
                    if isinstance(item, dict) and item.get("t"):
                        timestamps.append(str(item["t"]))
        return max(timestamps) if timestamps else None

    def _record_market_source(
        self,
        namespace: str,
        source: str,
        payload: Any,
        cache_age_sec: float | None = None,
        degraded_reason: str | None = None,
    ) -> None:
        if not self.monitor:
            return
        self.monitor.record_data_source(
            "alpaca",
            namespace,
            source,
            cache_age_sec,
            data_asof_utc=self._payload_data_asof(namespace, payload),
            feed=self.feed,
            degraded_reason=degraded_reason,
        )

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
                self._record_market_source(namespace, "fresh_cache", payload, age)
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
                age = time.time() - cache_path.stat().st_mtime
                self._record_market_source(
                    namespace,
                    "stale_cache_fallback",
                    payload,
                    age,
                    degraded_reason="network/request failed; exact-key stale cache used",
                )
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
                self._record_market_source(
                    "snapshots",
                    "stale_cross_key_fallback",
                    {symbol: out[symbol] for symbol in out if symbol in payload},
                    time.time() - path.stat().st_mtime,
                    degraded_reason="network/request failed; alternate snapshot cache used",
                )
        if out:
            return out
        if self.monitor:
            self.monitor.record_cache("alpaca", hit=False)
        return {}

    def _load_bars_from_any_cache(
        self,
        symbols: list[str],
        start_iso: str,
        *,
        provenance_source: str = "cross_key_cache",
    ) -> dict[str, list[dict[str, Any]]]:
        if not self.cache_enabled:
            return {}
        targets = [str(s).upper() for s in symbols if s]
        if not targets:
            return {}
        target_set = set(targets)
        best_rows: dict[str, list[dict[str, Any]]] = {}
        best_min_ts: dict[str, str] = {}
        best_len: dict[str, int] = {}
        best_age_sec: dict[str, float] = {}
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
                    best_age_sec[symbol] = max(0.0, time.time() - path.stat().st_mtime)
                hit = True
            if hit and self.monitor:
                self.monitor.record_cache("alpaca", hit=True)
        if best_rows:
            if self.monitor:
                degraded_reason = (
                    "network/request failed; alternate bars cache used"
                    if provenance_source == "stale_cross_key_fallback"
                    else None
                )
                for symbol in sorted(best_rows):
                    self._record_market_source(
                        "bars",
                        provenance_source,
                        {symbol: best_rows[symbol]},
                        best_age_sec.get(symbol),
                        degraded_reason=degraded_reason,
                    )
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
            if self.monitor:
                self._record_market_source("assets", "network", payload)
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
                    if self.monitor:
                        self._record_market_source("snapshots", "network", payload)
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

    def get_corporate_action_splits(
        self, symbols: list[str], start_iso: str, end_iso: str | None = None
    ) -> dict[str, list[tuple[str, float]]]:
        """Authoritative forward/reverse split events: {symbol: [(ex_date, price_mult)]}.

        price_mult = old_rate / new_rate (a 10:1 forward split -> 0.1): raw
        pre-split prices are multiplied by this factor to land in adjusted
        price space. Raises on network errors; callers fail open to raw bars.
        """
        if not symbols:
            return {}
        url = f"{self.data_endpoint}/v1/corporate-actions"
        events: dict[str, list[tuple[str, float]]] = {}
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "symbols": ",".join(sorted({str(s).upper() for s in symbols})),
                "types": "forward_split,reverse_split",
                "start": str(start_iso)[:10],
                "limit": 500,
            }
            if end_iso:
                params["end"] = str(end_iso)[:10]
            if page_token:
                params["page_token"] = page_token
            resp = self._get(url, params=params)
            payload = resp.json()
            actions = payload.get("corporate_actions", {}) or {}
            for item in list(actions.get("forward_splits") or []) + list(actions.get("reverse_splits") or []):
                sym = str(item.get("symbol") or "").upper()
                ex_date = str(item.get("ex_date") or "")
                try:
                    mult = float(item.get("old_rate")) / float(item.get("new_rate"))
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
                if sym and ex_date and np.isfinite(mult) and mult > 0:
                    events.setdefault(sym, []).append((ex_date, mult))
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        for sym in events:
            events[sym].sort()
        return events

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
                    any_cache = self._load_bars_from_any_cache(
                        needs_enrichment,
                        start_iso,
                        provenance_source="cross_key_cache_enrichment",
                    )
                    for symbol, rows in any_cache.items():
                        existing = bars_by_symbol.get(symbol)
                        if self._should_replace_rows(existing, rows, start_iso):
                            bars_by_symbol[symbol] = rows
                time.sleep(0.05)
                continue

            batch_bars: dict[str, list[dict[str, Any]]] = {}
            fetched_from_network = False
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
                fetched_from_network = True
                if self.monitor:
                    self._record_market_source("bars", "network", batch_bars)
            except Exception:
                stale = self._load_cache_stale("bars", cache_key)
                if isinstance(stale, dict):
                    for symbol, rows in stale.items():
                        if isinstance(rows, list):
                            batch_bars.setdefault(symbol, []).extend(rows)
                else:
                    any_cache = self._load_bars_from_any_cache(
                        batch,
                        start_iso,
                        provenance_source="stale_cross_key_fallback",
                    )
                    if any_cache:
                        for symbol, rows in any_cache.items():
                            if isinstance(rows, list):
                                batch_bars.setdefault(symbol, []).extend(rows)
                    else:
                        raise
            # Never refresh cache mtime with fallback data. Otherwise a stale
            # payload becomes indistinguishable from a fresh TTL cache on the
            # next run.
            if fetched_from_network:
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
        submissions_ttl_sec: int = 0,
        monitor: NetworkMonitor | None = None,
    ) -> None:
        self.session = session
        self.headers = {"User-Agent": user_agent}
        self.timeout_sec = timeout_sec
        self.cache_dir = cache_dir
        self.request_limiter = request_limiter
        self.submissions_ttl_sec = max(0, int(submissions_ttl_sec))
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
            # TTL-based refresh: submissions are cheap (~176 KB each) and
            # serve as the change detector for companyfacts staleness.
            age_sec = time.time() - cache_path.stat().st_mtime
            if age_sec <= self.submissions_ttl_sec:
                if self.monitor:
                    self.monitor.record_cache("sec", hit=True)
                return json.loads(cache_path.read_text())
            # TTL expired — fall through to refetch below.
        if self.monitor and cache_path.exists():
            self.monitor.record_cache("sec", hit=False)
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = self._get(url)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        payload = resp.json()
        # Atomic write: a concurrent daily_run reading this file while the
        # scheduled cache refresher overwrites it must never see a torn write.
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, cache_path)
        return payload

    def get_companyfacts(self, cik: str) -> dict[str, Any]:
        cache_path = self.cache_dir / f"facts_{cik}.json"
        meta_path = self.cache_dir / f"facts_meta_{cik}.json"
        subs_path = self.cache_dir / f"submissions_{cik}.json"
        need_fetch = not cache_path.exists()
        latest_accn: str | None = None
        if subs_path.exists():
            try:
                subs = json.loads(subs_path.read_text())
                recent = subs.get("filings", {}).get("recent", {}) or {}
                accessions = recent.get("accessionNumber", []) or []
                if accessions:
                    latest_accn = str(accessions[0])
            except Exception:
                pass  # fall back to metadata/mtime heuristics below
        if cache_path.exists() and not need_fetch:
            # D02: accession-based change detection. The old filingDate
            # vs mtime comparison missed same-day filings (date-midnight
            # < mtime of a cache written earlier that day).
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except Exception:
                    meta = {}
                covered = meta.get("covered_accession")
                pending = meta.get("pending_accession")
                if pending:
                    # Facts API lagged behind submissions: retry until the
                    # payload actually contains the new accession.
                    need_fetch = True
                elif latest_accn and (not covered or latest_accn != covered):
                    need_fetch = True
            else:
                # Legacy cache without accession metadata. Inspect it once so
                # same-day filings are not missed during migration: filingDate
                # alone cannot distinguish two filings on the same date.
                try:
                    cached_text = cache_path.read_text()
                    if latest_accn:
                        if latest_accn not in cached_text:
                            need_fetch = True
                        else:
                            meta_tmp = meta_path.with_suffix(".tmp")
                            meta_tmp.write_text(
                                json.dumps(
                                    {"covered_accession": latest_accn, "pending_accession": None}
                                )
                            )
                            os.replace(meta_tmp, meta_path)
                    if not need_fetch:
                        subs = json.loads(subs_path.read_text())
                        filing_dates = (subs.get("filings", {}).get("recent", {}) or {}).get("filingDate", [])
                        if filing_dates:
                            latest_filing = pd.Timestamp(filing_dates[0]).timestamp()
                            if latest_filing > cache_path.stat().st_mtime:
                                need_fetch = True
                except Exception:
                    pass
        if not need_fetch:
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
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, cache_path)
        # Record which accession the freshly downloaded facts actually cover
        # (or mark pending when the API lags behind submissions).
        if latest_accn:
            try:
                payload_text = resp.text if isinstance(resp.text, str) else json.dumps(payload)
            except Exception:
                payload_text = json.dumps(payload)
            if latest_accn in payload_text:
                new_meta = {"covered_accession": latest_accn, "pending_accession": None}
            else:
                new_meta = {"covered_accession": None, "pending_accession": latest_accn}
            try:
                meta_tmp = meta_path.with_suffix(".tmp")
                meta_tmp.write_text(json.dumps(new_meta))
                os.replace(meta_tmp, meta_path)
            except Exception:
                pass  # metadata failure must not break the fetch
        return payload


def chunks(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _merged_standard_taxonomy_facts(companyfacts: dict[str, Any]) -> dict[str, Any]:
    """Compatibility facade for the shared SEC taxonomy merger."""
    return merged_standard_taxonomy_facts(companyfacts)


def pick_facts_with_forms(
    companyfacts: dict[str, Any], tags: list[str], unit: str, allowed_forms: set[str]
) -> list[tuple[str, float, str]]:
    """Current-view period-end facts using the shared filing-version model."""
    records = extract_fact_records(companyfacts, tags, unit, allowed_forms)
    collapsed = collapse_fact_records_by_end(records)
    return [
        (record.period_end.isoformat(), float(record.value), record.normalized_form)
        for record in reversed(collapsed)
    ]


def reconcile_share_unit_scale(
    companyfacts: dict[str, Any], shares: float | None
) -> tuple[float | None, str | None]:
    """Compatibility facade for the canonical share-unit reconciliation."""
    if shares is None or shares <= 0:
        return shares, None
    assessment = assess_share_count_integrity(
        share_records=extract_fact_records(
            companyfacts, SHARES_TAGS, "shares", QUARTERLY_FORMS
        ),
        eps_records=extract_fact_records(
            companyfacts, EPS_TAGS, "USD/shares", QUARTERLY_FORMS
        ),
        net_income_records=extract_fact_records(
            companyfacts, NET_INCOME_TAGS, "USD", QUARTERLY_FORMS
        ),
        metric_record_groups=(),
    )
    if assessment.period_end is None:
        return shares, None
    return (
        float(shares) * float(assessment.scale_factor),
        assessment.period_end.isoformat(),
    )

def _reconstruct_flow_periods(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Compatibility facade over the canonical flow reconstruction core."""
    flows = reconstruct_flow_periods(
        extract_fact_records(companyfacts, tags, unit, QUARTERLY_FORMS)
    )
    quarters = [(p.period_end.isoformat(), float(p.value)) for p in flows.quarters]
    annuals = [(p.period_end.isoformat(), float(p.value)) for p in flows.annuals]
    return quarters, annuals


def _legacy_period_values(points: list[tuple[str, float]]) -> tuple[PeriodValue, ...]:
    out: list[PeriodValue] = []
    for end, value in points:
        end_dt = pd.to_datetime(end, errors="coerce")
        if pd.isna(end_dt):
            continue
        day = end_dt.date()
        out.append(
            PeriodValue(
                value=float(value),
                period_end=day,
                period_start=None,
                available_on=day,
            )
        )
    return tuple(out)


def _rolling_ttm_windows(
    quarters: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    return [
        (point.period_end.isoformat(), float(point.value))
        for point in rolling_ttm_points(_legacy_period_values(quarters))
    ]


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
    records = extract_fact_records(companyfacts, tags, unit, allowed_forms)
    return shared_latest_and_year_ago_level(records)


def _ttm_points_with_annuals(
    quarters: list[tuple[str, float]], annuals: list[tuple[str, float]]
) -> list[tuple[str, float]]:
    flows = ReconstructedFlows(
        quarters=_legacy_period_values(quarters),
        annuals=_legacy_period_values(annuals),
    )
    return [
        (point.period_end.isoformat(), float(point.value))
        for point in ttm_points_with_annual_fallback(flows)
    ]


def pick_latest_and_prev_ttm(
    companyfacts: dict[str, Any], tags: list[str], unit: str
) -> tuple[float | None, float | None]:
    records = extract_fact_records(companyfacts, tags, unit, QUARTERLY_FORMS)
    # Scanner preserves its public fallback contract: if no genuine rolling
    # four-quarter window exists, load_one_fundamental falls back to annual.
    return current_ttm_pair(records, require_rolling_window=True)


def build_ttm_history(
    companyfacts: dict[str, Any],
    tags: list[str],
    unit: str,
    max_points: int = 16,
) -> list[tuple[str, float]]:
    records = extract_fact_records(companyfacts, tags, unit, QUARTERLY_FORMS)
    flows = reconstruct_flow_periods(records)
    points = ttm_points_with_annual_fallback(flows)
    return [
        (point.period_end.isoformat(), float(point.value))
        for point in points[-int(max(1, max_points)) :]
    ]


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


def apply_split_adjustment(
    bars: list[dict[str, Any]],
    split_events: list[tuple[str, float]] | None,
) -> list[dict[str, Any]]:
    """Split-adjust o/h/l/c/v for pre-split bars.

    split_events: [(ex_date, price_mult)] with price_mult = old_rate/new_rate
    (10:1 forward split -> 0.1). Bars dated BEFORE ex_date carry raw
    pre-split prices and are scaled by the cumulative product of the mults
    of all splits with ex_date after the bar date, so the close series
    becomes continuous in adjusted-price space. Volume is scaled by
    1/mult so that close x volume (dollar volume) stays split-invariant
    and cross-day dollar-volume averages remain correct. Callers that need
    raw prices x raw share counts (valuation history) must pass the
    unadjusted series.
    """
    if not bars or not split_events:
        return bars
    events: list[tuple[str, float]] = []
    for d, m in split_events:
        try:
            mult = float(m)
        except (TypeError, ValueError):
            continue
        if d and mult > 0:
            events.append((str(d), mult))
    events.sort()
    if not events:
        return bars
    out: list[dict[str, Any]] = []
    for row in sorted(bars, key=lambda r: str(r.get("t", ""))):
        bar_date = str(row.get("t", ""))[:10]
        cum = 1.0
        for ex_date, mult in events:
            if ex_date > bar_date:
                cum *= mult
        if cum == 1.0:
            out.append(row)
            continue
        adjusted = dict(row)
        for key in ("o", "h", "l", "c"):
            value = row.get(key)
            if value is None:
                continue
            try:
                adjusted[key] = float(value) * cum
            except (TypeError, ValueError):
                continue
        volume = row.get("v")
        if volume is not None:
            try:
                adjusted["v"] = float(volume) / cum
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        out.append(adjusted)
    return out


def price_dimension_from_bars(
    price: float | None, bars: list[dict[str, Any]]
) -> dict[str, float | int | None]:
    """Adapt scanner bar dictionaries to the canonical price feature core."""
    if price is None or not bars:
        return compute_price_history_features(
            current_price=price,
            range_highs=[],
            range_lows=[],
            closes=[],
            dollar_volumes=[],
        )

    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    dollar_volumes: list[float] = []
    for row in sorted(bars, key=lambda item: str(item.get("t", ""))):
        try:
            high = float(row["h"]) if row.get("h") is not None else None
            low = float(row["l"]) if row.get("l") is not None else None
            close = float(row["c"]) if row.get("c") is not None else None
            volume = float(row["v"]) if row.get("v") is not None else None
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

    return compute_price_history_features(
        current_price=price,
        range_highs=highs,
        range_lows=lows,
        closes=closes,
        dollar_volumes=dollar_volumes,
    )

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


def bars_market_asof(bars: list[dict[str, Any]]) -> str | None:
    """Latest valid daily-bar date, normalized to YYYY-MM-DD."""
    dates = [
        pd.to_datetime(item.get("t"), utc=True, errors="coerce")
        for item in bars
        if item.get("t")
    ]
    valid = [ts for ts in dates if pd.notna(ts)]
    if not valid:
        return None
    return max(valid).date().isoformat()


def resolve_market_decision_date(
    frame: pd.DataFrame,
    *,
    benchmark_market_asof: str | None = None,
) -> str:
    """Resolve the canonical decision date from observed market data.

    Prefer the QQQ benchmark session because Entry Quality is benchmark-aware.
    If that provenance is unavailable, fall back to the latest valid symbol
    market_asof. Never silently use wall-clock UTC date for a prospective
    decision snapshot.
    """
    if benchmark_market_asof:
        parsed = pd.to_datetime(benchmark_market_asof, errors="coerce")
        if pd.notna(parsed):
            return parsed.date().isoformat()
    if "market_asof" in frame.columns:
        parsed = pd.to_datetime(frame["market_asof"], errors="coerce").dropna()
        if not parsed.empty:
            return parsed.max().date().isoformat()
    raise ValueError("cannot resolve decision_date from market data")


def bars_closes(bars: list[dict[str, Any]]) -> list[float]:
    """Chronological list of valid close prices from daily bars."""
    closes: list[float] = []
    sorted_bars = sorted(bars, key=lambda row: str(row.get("t", "")))
    for row in sorted_bars:
        try:
            close = float(row.get("c")) if row.get("c") is not None else None
        except (TypeError, ValueError):
            close = None
        if close is not None and np.isfinite(close) and close > 0:
            closes.append(close)
    return closes


def bars_close_from_lookback(bars: list[dict[str, Any]], lookback_days: int) -> float | None:
    closes = bars_closes(bars)
    if len(closes) < lookback_days:
        return None
    return float(closes[-1])


def bars_sma_from_lookback(bars: list[dict[str, Any]], sma_days: int) -> float | None:
    closes = bars_closes(bars)
    if sma_days <= 0 or len(closes) < sma_days:
        return None
    window = closes[-int(sma_days):]
    return float(np.mean(window))


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
            symbols, err = fetch_stockanalysis_etf_symbols(etf, config.watchlist_fetch_timeout_sec)
            if err:
                print(f"[watchlist] WARNING: {bucket}/{etf} fetch failed ({err}); bucket proceeds partial")
            if not symbols:
                print(f"[watchlist] WARNING: {bucket}/{etf} returned 0 symbols")
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

        # SRC:-prefixed tokens are provenance tags (e.g. SRC:MANUAL), not ETF
        # holdings, and must not inflate the ETF-consensus count.
        etf_tokens = [
            x
            for x in str(rows[symbol]["watchlist_etfs"]).split(",")
            if x and not x.strip().upper().startswith("SRC:")
        ]
        rows[symbol]["watchlist_etf_count"] = len(set(etf_tokens))

    out = pd.DataFrame(rows.values())
    return out[WATCHLIST_SCORE_COLUMNS]


def load_watchlist_scores(config: ScanConfig) -> pd.DataFrame:
    path = Path(config.watchlist_csv_path)
    if not path.exists():
        return pd.DataFrame(columns=WATCHLIST_SCORE_COLUMNS)
    raw = pd.read_csv(path)
    return watchlist_rows_to_scores(raw)


def archive_watchlist_snapshot(config: ScanConfig, started_at: datetime) -> Path | None:
    """Archive the watchlist for point-in-time backtests.

    historical_replay needs to know what the watchlist looked like on each
    replay date; these snapshots cannot be reconstructed retroactively, so
    one is archived on every scan. File names carry a UTC timestamp that
    parse_watchlist_snapshot_date understands.
    """
    src = Path(config.watchlist_csv_path)
    if not src.exists():
        return None
    history_dir = Path("data/watchlist_history")
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    dst = history_dir / f"ai_watchlist_{stamp}.csv"
    if dst.exists():
        return dst
    shutil.copy2(src, dst)
    return dst






def compute_price_history_percentile(
    bars: list[dict[str, Any]], window_days: int
) -> float | None:
    """Compatibility adapter over the canonical close-history percentile."""
    closes: list[float] = []
    for row in sorted(bars, key=lambda item: str(item.get("t", ""))):
        value = row.get("c")
        if value is None:
            continue
        try:
            close = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(close) and close > 0:
            closes.append(close)
    return price_history_percentile_from_closes(
        closes,
        window_observations=window_days,
        min_observations=20,
    )


    return True




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
        submissions_ttl_sec=config.sec_cache_ttl_submissions_sec,
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


def latest_periodic_filing(
    submissions: dict[str, Any],
) -> dict[str, str] | None:
    """Return the newest periodic filing relevant to Company Quality.

    SEC submissions also contain 8-K, 6-K, ownership and other filings that do
    not necessarily update Company Facts. Cache invalidation and freshness
    diagnostics therefore track only 10-Q/10-K/20-F/40-F (including amended
    forms after normalization).
    """
    recent = submissions.get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    filing_dates = recent.get("filingDate", []) or []
    accessions = recent.get("accessionNumber", []) or []
    best: dict[str, str] | None = None
    for index, raw_form in enumerate(forms):
        form = normalize_form(raw_form)
        if form not in QUARTERLY_FORMS:
            continue
        if index >= len(filing_dates):
            continue
        filed = str(filing_dates[index] or "").strip()[:10]
        try:
            datetime.strptime(filed, "%Y-%m-%d")
        except ValueError:
            continue
        accession = (
            str(accessions[index]).strip()
            if index < len(accessions) and accessions[index]
            else ""
        )
        candidate = {
            "form": form,
            "filed": filed,
            "accession": accession,
        }
        if best is None or filed > best["filed"]:
            best = candidate
    return best


def relevant_fundamental_fact_accessions(
    companyfacts: dict[str, Any],
) -> set[str]:
    """Accessions represented by core P&L/cash-flow facts recognized by the scanner."""
    facts = merged_standard_taxonomy_facts(companyfacts)
    accessions: set[str] = set()
    for tag in FUNDAMENTAL_FILING_COVERAGE_TAGS:
        tag_obj = facts.get(tag, {})
        units = tag_obj.get("units", {}) if isinstance(tag_obj, dict) else {}
        if not isinstance(units, dict):
            continue
        for entries in units.values():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                if normalize_form(item.get("form")) not in QUARTERLY_FORMS:
                    continue
                accession = str(item.get("accn") or "").strip()
                if accession:
                    accessions.add(accession)
    return accessions


def fundamental_currency_support(
    companyfacts: dict[str, Any],
    *,
    accession: str | None = None,
) -> tuple[str | None, bool | None]:
    """Detect core monetary currency, optionally for one exact filing accession.

    When an accession is supplied, only core facts from that filing contribute.
    USD is considered supported only when it is the sole detected core monetary
    currency. This avoids the old false-positive behavior where a foreign
    issuer could be labeled USD merely because some historical or supplemental
    fact somewhere in Company Facts used USD.
    """
    facts = merged_standard_taxonomy_facts(companyfacts)
    currencies: set[str] = set()
    target_accession = str(accession or "").strip()
    for tag in CORE_MONETARY_CURRENCY_TAGS:
        tag_obj = facts.get(tag, {})
        units = tag_obj.get("units", {}) if isinstance(tag_obj, dict) else {}
        if not isinstance(units, dict):
            continue
        for unit, entries in units.items():
            token = str(unit).strip().upper()
            if not _CURRENCY_UNIT_PATTERN.fullmatch(token):
                continue
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                if target_accession and str(item.get("accn") or "").strip() != target_accession:
                    continue
                if normalize_form(item.get("form")) not in QUARTERLY_FORMS:
                    continue
                currencies.add(token)
                break
    if currencies == {"USD"}:
        return "USD", True
    if currencies:
        return ",".join(sorted(currencies)), False
    return None, None


def latest_fundamental_filing_date(companyfacts: dict[str, Any]) -> str | None:
    """Latest filed date among financial facts used by the live Quality layer."""
    facts = merged_standard_taxonomy_facts(companyfacts)
    latest: str | None = None
    for tag in FUNDAMENTAL_DATA_ASOF_TAGS:
        tag_obj = facts.get(tag, {})
        units = tag_obj.get("units", {}) if isinstance(tag_obj, dict) else {}
        if not isinstance(units, dict):
            continue
        for entries in units.values():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                if normalize_form(item.get("form")) not in QUARTERLY_FORMS:
                    continue
                raw = item.get("filed")
                if raw is None:
                    continue
                token = str(raw).strip()[:10]
                try:
                    datetime.strptime(token, "%Y-%m-%d")
                except ValueError:
                    continue
                if latest is None or token > latest:
                    latest = token
    return latest


def _parsed_fund_config_fingerprint(config: ScanConfig) -> dict[str, object]:
    # Only fields that change the financial computation inside
    # load_one_fundamental. Output-count or scoring-only knobs must not
    # cause redundant re-parses (D01).
    return {
        "use_ttm_metrics": bool(config.use_ttm_metrics),
        "nonrecurring_addback_revenue_cap": config.nonrecurring_addback_revenue_cap,
        "ai_link_disclosure_keyword_cap": config.ai_link_disclosure_keyword_cap,
        "ai_link_backlog_ratio_cap": config.ai_link_backlog_ratio_cap,
    }


PARSED_FUND_CACHE_VERSION = 7


def _parsed_fund_cache_meta(
    config: ScanConfig,
    latest_filing: str | None,
    latest_accession: str | None = None,
    facts_covered_accession: str | None = None,
) -> dict[str, object]:
    return {
        "v": PARSED_FUND_CACHE_VERSION,
        "cfg": _parsed_fund_config_fingerprint(config),
        "latest_filing": latest_filing,
        "latest_accession": latest_accession,
        "facts_covered_accession": facts_covered_accession,
    }


def _submissions_latest_filing(subs_cache: Path) -> str | None:
    try:
        subs = json.loads(subs_cache.read_text())
        filings = subs.get("filings", {}).get("recent", {}) or {}
        dates = filings.get("filingDate", []) or []
        return str(dates[0]) if dates else None
    except Exception:
        return None


def _submissions_latest_accession(subs_cache: Path) -> str | None:
    try:
        subs = json.loads(subs_cache.read_text())
        filings = subs.get("filings", {}).get("recent", {}) or {}
        accessions = filings.get("accessionNumber", []) or []
        return str(accessions[0]) if accessions else None
    except Exception:
        return None


def _facts_accession_state(cache_dir: str | Path, cik: str) -> tuple[str | None, str | None]:
    meta_path = Path(cache_dir) / f"facts_meta_{cik}.json"
    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        return None, None
    covered = meta.get("covered_accession")
    pending = meta.get("pending_accession")
    return (
        str(covered) if covered else None,
        str(pending) if pending else None,
    )


def load_one_fundamental(sec: SecClient, symbol: str, cik: str, config: ScanConfig) -> dict[str, Any]:
    # --- Pre-parsed cache: the scheduled refresher (or a previous run) has
    # already downloaded the raw submissions/companyfacts, parsed the 4 MB
    # JSON, computed all TTM/YoY/quality metrics, and cached the RESULT.
    # Reading this ~3 KB file skips the entire GIL-bound parse+compute chain
    # (the dominant cost of the SEC step: ~40-45 min for 535 symbols).
    # Invalidation: TTL (as before) AND binding to the config fingerprint
    # plus the raw submissions version (D01): a cache computed with
    # different TTM/cap settings, or before the latest filing, must not be
    # served.
    parsed_path = Path(config.cache_dir) / f"parsed_fund_{cik}.json"
    parsed_ttl = float(config.sec_cache_ttl_submissions_sec)
    # Only trust the parsed cache when the raw submissions cache is also
    # present: the parsed result is derived from submissions + companyfacts,
    # so a parsed cache without its raw sources is meaningless (e.g. unit
    # tests with fake data write parsed caches under fake CIKs).
    subs_cache = Path(config.cache_dir) / f"submissions_{cik}.json"
    if parsed_ttl > 0 and parsed_path.exists() and subs_cache.exists():
        age = time.time() - parsed_path.stat().st_mtime
        if age <= parsed_ttl:
            try:
                cached = json.loads(parsed_path.read_text())
                meta = cached.get("_cache_meta") or {}
                latest_filing = _submissions_latest_filing(subs_cache)
                latest_accession = _submissions_latest_accession(subs_cache)
                facts_covered, facts_pending = _facts_accession_state(config.cache_dir, cik)
                facts_ready = (
                    not facts_pending
                    and (latest_accession is None or facts_covered == latest_accession)
                )
                if (
                    meta.get("v") == PARSED_FUND_CACHE_VERSION
                    and meta.get("cfg") == _parsed_fund_config_fingerprint(config)
                    and meta.get("latest_filing") == latest_filing
                    and meta.get("latest_accession") == latest_accession
                    and meta.get("facts_covered_accession") == facts_covered
                    and facts_ready
                ):
                    cached.pop("_cache_meta", None)
                    cached["symbol"] = symbol  # defensive: match caller expectation
                    return cached
            except Exception:
                pass  # corrupt cache → fall through to the slow path

    submissions = sec.get_submissions(cik)
    companyfacts = sec.get_companyfacts(cik)

    sic = submissions.get("sic")
    sic_desc = submissions.get("sicDescription")
    latest_periodic = latest_periodic_filing(submissions)
    latest_periodic_filing_date = (
        latest_periodic["filed"] if latest_periodic is not None else None
    )
    latest_periodic_form = (
        latest_periodic["form"] if latest_periodic is not None else None
    )
    latest_periodic_accession = (
        latest_periodic["accession"] if latest_periodic is not None else None
    )

    fact_accessions = relevant_fundamental_fact_accessions(companyfacts)
    initially_covered = (
        None
        if not latest_periodic_accession
        else latest_periodic_accession in fact_accessions
    )
    fallback_status = "not_needed"
    fallback_used = False
    fallback_fact_count = 0
    if initially_covered is False:
        fallback = fetch_usd_10q_companyfacts_patch(
            periodic_filing=latest_periodic,
            allowed_tags=EDGARTOOLS_FALLBACK_ALLOWED_TAGS,
            core_tag_groups=EDGARTOOLS_FALLBACK_CORE_TAG_GROUPS,
        )
        fallback_status = fallback.status
        if fallback.used:
            fallback_fact_count = merge_companyfacts_patch(
                companyfacts,
                fallback.patch,
            )
            fallback_used = fallback_fact_count > 0

    # Recompute all integrity/freshness fields from the effective in-memory
    # fact set after the narrow exact-filing patch. The raw SEC cache remains
    # untouched.
    fundamental_data_asof = latest_fundamental_filing_date(companyfacts)
    fact_accessions = relevant_fundamental_fact_accessions(companyfacts)
    fundamental_facts_cover_latest_periodic = (
        None
        if not latest_periodic_accession
        else latest_periodic_accession in fact_accessions
    )
    fundamental_reporting_currency, fundamental_currency_supported = (
        fundamental_currency_support(
            companyfacts,
            accession=latest_periodic_accession,
        )
    )
    fundamental_source = (
        "companyfacts+edgartools_exact_10q"
        if fallback_used and fundamental_facts_cover_latest_periodic is True
        else "companyfacts"
    )

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
    share_integrity = assess_share_count_integrity(
        share_records=extract_fact_records(
            companyfacts, SHARES_TAGS, "shares", QUARTERLY_FORMS
        ),
        eps_records=extract_fact_records(
            companyfacts, EPS_TAGS, "USD/shares", QUARTERLY_FORMS
        ),
        net_income_records=extract_fact_records(
            companyfacts, NET_INCOME_TAGS, "USD", QUARTERLY_FORMS
        ),
        metric_record_groups=(
            extract_fact_records(
                companyfacts, REVENUE_TAGS, "USD", QUARTERLY_FORMS
            ),
            extract_fact_records(
                companyfacts, NET_INCOME_TAGS, "USD", QUARTERLY_FORMS
            ),
        ),
    )
    shares = share_integrity.value
    shares_asof_end = (
        share_integrity.period_end.isoformat()
        if share_integrity.period_end is not None
        else None
    )
    shares_stale = bool(share_integrity.stale)
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

    # Shared pure adjustment arithmetic. Scanner compatibility: the live path
    # historically caps both addbacks and gains above, so cap_ratio=None here
    # prevents a second cap while preserving exact pre-refactor semantics.
    adjusted = compute_adjusted_metrics(
        net_income=net_income,
        ebit=ebit,
        da=da,
        revenue=revenue,
        revenue_prev=revenue_prev,
        addback=nonrecurring_addback,
        gain=nonrecurring_gain,
        addback_prev=nonrecurring_addback_prev,
        gain_prev=nonrecurring_gain_prev,
        cap_ratio=None,
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
        operating_cash_flow=ocf,
        operating_cash_flow_prev=ocf_prev,
        capex_raw=capex_raw,
        ebit=ebit,
        ebit_prev=ebit_prev,
        shares=shares,
        shares_prev=shares_prev,
        cash_and_equivalents=cash_and_equivalents,
        debt_long_term=debt_long_term,
        debt_current=debt_current,
        current_assets=assets_current,
        current_liabilities=liabilities_current,
        receivables_current=receivables_current,
        receivables_prev=receivables_prev,
        inventory_current=inventory_current,
        inventory_prev=inventory_prev,
        interest_expense=interest_expense,
        depreciation_and_amortization=da,
        depreciation_and_amortization_prev=da_prev,
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
    ocf_yoy = accounting["operating_cash_flow_yoy"]
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

    ai_disclosure_score, ai_disclosure_group_hits, ai_disclosure_keyword_hits = (
        ai_disclosure_score_from_submissions(
            submissions, disclosure_keyword_cap=config.ai_link_disclosure_keyword_cap
        )
    )
    ai_backlog_signal = ai_backlog_signal_from_companyfacts(
        companyfacts, revenue=revenue, cap_ratio=config.ai_link_backlog_ratio_cap
    )
    # --- Cache the parsed result so the next run (or the scheduled refresher)
    # can skip the 4 MB JSON parse + TTM computation entirely.
    result = {
        "symbol": symbol,
        "sic": str(sic) if sic is not None else None,
        "sic_description": sic_desc,
        "revenue": revenue,
        "revenue_form": revenue_form,
        "net_income": net_income,
        "net_income_form": net_income_form,
        "shares_outstanding": shares,
        "shares_asof_end": shares_asof_end,
        "shares_stale": shares_stale,
        "fundamental_data_asof": fundamental_data_asof,
        "fundamental_latest_periodic_filing_date": latest_periodic_filing_date,
        "fundamental_latest_periodic_form": latest_periodic_form,
        "fundamental_latest_periodic_accession": latest_periodic_accession,
        "fundamental_facts_cover_latest_periodic": fundamental_facts_cover_latest_periodic,
        "fundamental_reporting_currency": fundamental_reporting_currency,
        "fundamental_currency_supported": fundamental_currency_supported,
        "fundamental_source": fundamental_source,
        "fundamental_edgartools_fallback_used": fallback_used,
        "fundamental_edgartools_fallback_status": fallback_status,
        "fundamental_edgartools_fallback_version": (
            EDGARTOOLS_FALLBACK_VERSION if fallback_used else None
        ),
        "fundamental_edgartools_fallback_fact_count": fallback_fact_count,
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
    # Write the parsed result for the next run / scheduled refresher.
    # Only write when the raw submissions cache also exists: unit tests with
    # fake clients don't write raw caches, and their parsed results must not
    # pollute the production cache directory.
    subs_cache = Path(config.cache_dir) / f"submissions_{cik}.json"
    if subs_cache.exists():
        parsed_path = Path(config.cache_dir) / f"parsed_fund_{cik}.json"
        try:
            latest_filing = _submissions_latest_filing(subs_cache)
            latest_accession = _submissions_latest_accession(subs_cache)
            facts_covered, facts_pending = _facts_accession_state(config.cache_dir, cik)
            facts_ready = (
                not facts_pending
                and (latest_accession is None or facts_covered == latest_accession)
            )
            # Never persist a derived cache while companyfacts is known to lag
            # the newest submission; doing so would freeze stale fundamentals
            # ahead of SecClient's pending-accession retry loop.
            if facts_ready:
                cache_payload = dict(result)
                cache_payload["_cache_meta"] = _parsed_fund_cache_meta(
                    config,
                    latest_filing,
                    latest_accession,
                    facts_covered,
                )
                parsed_tmp = parsed_path.with_suffix(".tmp")
                parsed_tmp.write_text(json.dumps(cache_payload, default=str))
                os.replace(parsed_tmp, parsed_path)
        except Exception:
            pass  # cache write failure must not break the scan
    return result


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
                        "fundamental_data_asof": None,
                        "fundamental_latest_periodic_filing_date": None,
                        "fundamental_latest_periodic_form": None,
                        "fundamental_latest_periodic_accession": None,
                        "fundamental_facts_cover_latest_periodic": None,
                        "fundamental_reporting_currency": None,
                        "fundamental_currency_supported": None,
                        "fundamental_source": None,
                        "fundamental_edgartools_fallback_used": False,
                        "fundamental_edgartools_fallback_status": "collection_error",
                        "fundamental_edgartools_fallback_version": None,
                        "fundamental_edgartools_fallback_fact_count": 0,
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




def run_scan(
    config: ScanConfig,
    output_path: str | None,
    diagnostics_output_path: str | None,
    network_report_output_path: str | None = None,
    report_output_path: str | None = None,
    scan_config_path: str | None = None,
    decision_output_root: str | None = None,
    decision_attention_cap: int = DEFAULT_ATTENTION_CAP,
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
            "`python scripts/refresh_ai_watchlist.py --config configs/config.risk_off.json --output data/ai_watchlist.csv` "
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
    entry_benchmark_symbol = "QQQ"
    bars_symbols = sorted(
        set(symbols_for_bars)
        .union(set(benchmark_symbols))
        .union({entry_benchmark_symbol})
    )
    trend_filter_symbol = normalize_equity_symbol(config.benchmark_trend_filter_symbol or "")
    if trend_filter_symbol and trend_filter_symbol not in bars_symbols:
        bars_symbols = sorted(set(bars_symbols).union({trend_filter_symbol}))
    bars_map = alpaca.get_daily_bars(bars_symbols, bars_start_iso, config.chunk_size)
    # Raw bars are NOT split-adjusted (Alpaca adjustment=raw). Cross-day price
    # metrics below must be computed on a split-continuous series, so split
    # events are pulled from the authoritative corporate-actions feed and the
    # o/h/l/c fields are rescaled at the point of use. Valuation history
    # deliberately keeps the RAW series: raw close x raw shares is
    # self-consistent across splits.
    split_events: dict[str, list[tuple[str, float]]] = {}
    try:
        split_events = alpaca.get_corporate_action_splits(
            bars_symbols, bars_start_iso, datetime.now(timezone.utc).date().isoformat()
        )
        if split_events:
            log_status(
                started_at,
                "INFO",
                f"Split events (corporate actions): {len(split_events)} symbols, "
                f"e.g. {sorted(split_events)[:5]}",
            )
    except Exception as exc:
        # Fail open: unadjusted bars reproduce the legacy behaviour.
        log_status(
            started_at,
            "WARN",
            f"corporate-actions split fetch failed ({exc.__class__.__name__}); "
            "price dimensions left unadjusted",
        )
    benchmark_returns_20d: list[float] = []
    benchmark_returns_60d: list[float] = []
    for etf in benchmark_symbols:
        bench_bars = apply_split_adjustment(bars_map.get(etf, []), split_events.get(etf))
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
    qqq_bars = apply_split_adjustment(
        bars_map.get(entry_benchmark_symbol, []),
        split_events.get(entry_benchmark_symbol),
    )
    qqq_market_asof = bars_market_asof(qqq_bars)
    qqq_trailing_return_60d = bars_return_from_lookback(qqq_bars, 60)
    if qqq_trailing_return_60d is not None and not np.isfinite(
        qqq_trailing_return_60d
    ):
        qqq_trailing_return_60d = None
    entry_regime = (
        "up"
        if qqq_trailing_return_60d is not None
        and float(qqq_trailing_return_60d) >= 0.0
        else "down"
        if qqq_trailing_return_60d is not None
        else "unknown"
    )
    benchmark_trend_ok: bool | None = None
    if trend_filter_symbol:
        trend_bars = apply_split_adjustment(bars_map.get(trend_filter_symbol, []), split_events.get(trend_filter_symbol))
        trend_close = bars_close_from_lookback(
            trend_bars, config.benchmark_trend_filter_sma_days
        )
        trend_sma = bars_sma_from_lookback(
            trend_bars, config.benchmark_trend_filter_sma_days
        )
        if trend_close is not None and trend_sma is not None:
            benchmark_trend_ok = bool(np.isfinite(trend_close) and np.isfinite(trend_sma) and trend_close >= trend_sma)
            log_status(
                started_at,
                "INFO",
                f"Benchmark trend filter ({trend_filter_symbol}): "
                f"close={trend_close:.2f} sma{config.benchmark_trend_filter_sma_days}={trend_sma:.2f} "
                f"trend_ok={benchmark_trend_ok}",
            )
    price_feature_rows: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        symbol_bars = apply_split_adjustment(
            bars_map.get(row.symbol, []),
            split_events.get(row.symbol),
        )
        features = price_dimension_from_bars(row.price, symbol_bars)
        market_asof = bars_market_asof(symbol_bars)
        stock_return_60d = features.get("return_60d")
        relative_strength_60d_qqq = None
        if (
            stock_return_60d is not None
            and qqq_trailing_return_60d is not None
        ):
            relative_strength_60d_qqq = (
                float(stock_return_60d) - float(qqq_trailing_return_60d)
            )
        price_feature_rows.append(
            {
                "symbol": row.symbol,
                **features,
                "market_asof": market_asof,
                "qqq_trailing_return_60d": qqq_trailing_return_60d,
                "relative_strength_60d_qqq": relative_strength_60d_qqq,
                "regime": entry_regime,
            }
        )
    df_price_features = pd.DataFrame(price_feature_rows)
    df = df.merge(df_price_features, on="symbol", how="left")
    if trend_filter_symbol:
        # Missing/unresolvable trend state fails open (True): a data gap must
        # not silently flip the defensive profile into full silence.
        df["benchmark_trend_ok"] = True if benchmark_trend_ok is None else bool(benchmark_trend_ok)

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
        # RAW closes on purpose: paired with raw filed share counts the
        # market-cap product stays correct on both sides of a split. Adjusted
        # closes here would understate pre-split multiples by the split factor.
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
    derived_features = compute_cross_section_derived_features(
        df,
        earnings_yoy_col=earnings_yoy_col,
        assumed_position_usd=config.assumed_position_usd,
    )
    for name, values in derived_features.items():
        df[name] = values

    peer_features = compute_peer_relative_valuation(df, min_peer_count=5)
    for name, values in peer_features.items():
        df[name] = values

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
    df["ai_link_score"] = df.apply(
        lambda row: compute_ai_link_score(
            config,
            ai_etf_score=row.get("ai_etf_consensus_score"),
            ai_disclosure_score=row.get("ai_disclosure_score"),
            ai_market_score=row.get("ai_market_link_score"),
            ai_backlog_signal=row.get("ai_backlog_signal"),
        ),
        axis=1,
    )
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
        filtered, diagnostics = apply_scored_or_hard_filters(df, steps, channel_name, config)

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
            config.pe_cash_backing_haircut,
        )
        ranked = apply_research_assessment(ranked, "low_value")
        pre_research_gate_count = len(ranked)
        ranked = apply_low_value_research_gate(ranked, config)
        log_status(
            started_at,
            "INFO",
            f"  Low-Value research gate: {pre_research_gate_count} => {len(ranked)}",
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
        "price_to_sma50",
        "price_to_sma200",
        "days_below_sma200",
        "return_20d",
        "return_60d",
        "relative_strength_60d_qqq",
        "qqq_trailing_return_60d",
        "volatility_60d",
        "avg_dollar_volume_20d",
        "market_asof",
        "fundamental_data_asof",
        "fundamental_latest_periodic_filing_date",
        "fundamental_latest_periodic_form",
        "fundamental_latest_periodic_accession",
        "fundamental_facts_cover_latest_periodic",
        "fundamental_reporting_currency",
        "fundamental_currency_supported",
        "fundamental_source",
        "fundamental_edgartools_fallback_used",
        "fundamental_edgartools_fallback_status",
        "fundamental_edgartools_fallback_version",
        "fundamental_edgartools_fallback_fact_count",
        "regime",
        "benchmark_trend_ok",
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
        trend_filtered, _ = apply_scored_or_hard_filters(df, trend_steps, channel_name, config)
        trend_ranked = score_and_rank(
            trend_filtered,
            trend_weights,
            config.score_winsor_lower_q,
            config.score_winsor_upper_q,
            config.score_penalty_overvaluation,
            config.score_penalty_deterioration,
            config.pe_cash_backing_haircut,
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
        momentum_filtered, _ = apply_scored_or_hard_filters(df, momentum_steps, channel_name, config)
        momentum_ranked = score_and_rank(
            momentum_filtered,
            momentum_weights,
            config.score_winsor_lower_q,
            config.score_winsor_upper_q,
            config.score_penalty_overvaluation,
            config.score_penalty_deterioration,
            config.pe_cash_backing_haircut,
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
            "left_side_watch": 2,
            "theme_only": 3,
            "avoid_for_now": 4,
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
        "config_schema_version": config.config_schema_version,
        "strategy_style": config.strategy_style,
        "max_symbols": config.max_symbols,
        "top_n_per_channel_low_value": top_n_low_value,
        "top_n_per_channel_trend": top_n_trend,
        "top_n_per_channel_momentum": top_n_momentum,
        "research_pool_top_n": int(config.research_pool_top_n),
        "research_pool_min_score": float(config.research_pool_min_score),
        "low_value_allowed_research_priorities": config.low_value_allowed_research_priorities,
        "low_value_excluded_research_risks": config.low_value_excluded_research_risks,
        "low_value_min_research_score": config.low_value_min_research_score,
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

    decision_snapshot_root: Path | None = None
    decision_output_error: str | None = None
    try:
        decision_date = resolve_market_decision_date(
            df,
            benchmark_market_asof=qqq_market_asof,
        )
        default_decision_dir = (
            "decisions"
            if config.max_symbols is None
            else "decision_samples"
        )
        snapshot_root = Path(
            decision_output_root
            or (Path(config.output_dir) / default_decision_dir)
        )
        previous = load_previous_snapshot(
            snapshot_root,
            decision_date,
            strategy_style=config.strategy_style,
        )
        previous_by_symbol = decisions_by_symbol(previous)
        source_lists = build_source_list_membership(
            {
                "low_value": ranked,
                "industry_trend": industry_trend,
                "momentum": momentum,
                "research_pool": research_pool,
            }
        )
        config_payload = json.dumps(
            vars(config),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        config_fingerprint = hashlib.sha256(
            config_payload.encode("utf-8")
        ).hexdigest()
        code_sha = resolve_git_commit_sha()
        decisions = build_stock_decisions(
            df,
            decision_date=decision_date,
            generated_at_utc=finished_at.isoformat(),
            previous_by_symbol=previous_by_symbol,
            source_lists_by_symbol=source_lists,
            run_provenance={
                "code_sha": code_sha,
                "config_fingerprint": config_fingerprint,
                "strategy_style": config.strategy_style,
                "scan_config_path": scan_config_path,
                "watchlist_csv_path": config.watchlist_csv_path,
            },
        )
        daily_attention = select_daily_attention(
            decisions,
            cap=decision_attention_cap,
        )
        weekly_attention = select_weekly_attention(
            decisions,
            cap=decision_attention_cap,
        )
        decision_paths = write_decision_snapshot(
            output_root=snapshot_root,
            strategy_style=config.strategy_style,
            decisions=decisions,
            daily_attention=daily_attention,
            weekly_attention=weekly_attention,
            generated_at_utc=finished_at.isoformat(),
            decision_date=decision_date,
            config_fingerprint=config_fingerprint,
            code_sha=code_sha,
            input_provenance={
                "watchlist_csv_path": config.watchlist_csv_path,
                "decision_date_source": (
                    "qqq_market_asof" if qqq_market_asof else "latest_symbol_market_asof"
                ),
                "qqq_market_asof": qqq_market_asof,
                "legacy_ranked_csv": str(out_path),
                "industry_trend_csv": str(trend_out_path),
                "momentum_csv": str(momentum_out_path),
                "research_pool_csv": str(research_pool_out_path),
                "network_issue_flag": bool(
                    report.get("had_rate_limit_or_network_issue")
                ),
                "stale_market_data_fallback_used": bool(
                    report.get("stale_market_data_fallback_used")
                ),
                "market_data_provenance": report.get("data_provenance", {}),
            },
        )
        decision_snapshot_root = decision_paths.root
        log_status(
            started_at,
            "INFO",
            "MVP decision snapshot: "
            f"{decision_paths.root} | decisions={len(decisions)} "
            f"| daily={len(daily_attention)} | weekly={len(weekly_attention)}",
        )
    except Exception as exc:
        decision_output_error = f"{type(exc).__name__}: {exc}"
        log_status(
            started_at,
            "WARN",
            "MVP decision output failed without affecting legacy outputs: "
            f"{decision_output_error}",
        )

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
        market_data_provenance=report,
        strategy_style=config.strategy_style,
        scan_config_path=scan_config_path,
        industry_trend_count=len(industry_trend),
        industry_trend_path=trend_out_path,
        momentum_count=len(momentum),
        momentum_path=momentum_out_path,
        research_pool=research_pool,
        research_pool_path=research_pool_out_path,
        diagnostics_layer_summary=diagnostics_layer_summary,
        first_fail_concentration_summary=first_fail_concentration_summary,
    )
    if decision_snapshot_root is not None:
        md_report += (
            "\n## MVP Decision Outputs\n\n"
            f"- snapshot root: {decision_snapshot_root}\n"
            f"- canonical decisions: {decision_snapshot_root / 'decisions.jsonl'}\n"
            f"- daily Action List: {decision_snapshot_root / 'action_list.md'}\n"
            f"- weekly Review List: {decision_snapshot_root / 'weekly_review.md'}\n"
        )
    elif decision_output_error is not None:
        md_report += (
            "\n## MVP Decision Outputs\n\n"
            "- decision output failed without affecting legacy scan artifacts: "
            f"{decision_output_error}\n"
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
            "left_side_watch": 2,
            "theme_only": 3,
            "avoid_for_now": 4,
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
    parser.add_argument(
        "--decision-output-root",
        default=None,
        help=(
            "Root for immutable MVP decision snapshots. "
            "Defaults to <output_dir>/decisions."
        ),
    )
    parser.add_argument(
        "--decision-attention-cap",
        type=int,
        default=DEFAULT_ATTENTION_CAP,
        help="Maximum names in Daily/Weekly Action List outputs (default: 15).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    if args.max_symbols is not None:
        config.max_symbols = args.max_symbols

    started_at = datetime.now(timezone.utc)
    try:
        run_scan(
            config,
            args.output,
            args.diagnostics_output,
            args.network_report_output,
            args.report_output,
            scan_config_path=str(args.config),
            decision_output_root=args.decision_output_root,
            decision_attention_cap=args.decision_attention_cap,
        )
        if config.archive_watchlist_snapshots:
            snapshot_path = archive_watchlist_snapshot(config, started_at)
            if snapshot_path is not None:
                print(f"[snapshot] watchlist archived for PIT backtests: {snapshot_path}")
    except Exception as exc:
        print("")
        print("[ERROR] Scan failed.")
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        print(traceback.format_exc())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
