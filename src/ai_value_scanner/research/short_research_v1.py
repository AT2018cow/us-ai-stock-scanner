"""Short Research v1: pure cross-sectional selection rules and contracts.

The module is deliberately independent of the long-only decision pipeline:
long Top-15 selection, action states, and legacy list membership never feed
these rules.  ``build_short_cross_section`` accepts one signal-date feature
frame, validates the point-in-time contract, computes the SIC peer funnel, and
returns a structured result that renderers and snapshot writers consume without
recomputing any rule.

Frozen evaluation lives in ``short_research_v1_eval``; the lazy wrapper at the
bottom keeps the documented ``evaluate_frozen_short_research`` import path.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SHORT_RESEARCH_CONTRACT_VERSION = "short_research_v1"
SHORT_RESEARCH_RULE_VERSION = "short_research_rules_v1"
SHORT_RESEARCH_SCHEMA_VERSION = 1
MAX_SHORT_CANDIDATES = 5

MIN_PRICE = 5.0
MIN_DOLLAR_VOLUME = 2_000_000.0
MIN_AVG_DOLLAR_VOLUME_20D = 10_000_000.0
MIN_INDUSTRY_PEERS = 4  # other U0 companies in the same SIC
MIN_PE_PEERS = 5  # including the target
EXCLUDED_SIC_MIN = 6000
EXCLUDED_SIC_MAX = 6999
MAX_FUNDAMENTAL_ASOF_DAYS = 180
SHORT_RS60_SIC_MAX = 0.0
SHORT_SMA50_MAX = 1.0
SHORT_RET20_MIN = -0.20
SHORT_REVENUE_YOY_MAX = 0.0
SHORT_OCF_GROWTH_MAX = -0.10
SHORT_PE_PERCENTILE_MIN = 0.80
SHORT_PE_PREMIUM_MIN = 0.25
ROUNDTRIP_COST = 0.003

VALID_OCF_DIRECTIONS = frozenset(
    {"positive_base", "reversal", "both_negative", "turnaround"}
)

STATUS_DISABLED = "disabled"
STATUS_READY = "ready"
STATUS_NO_CANDIDATES = "no_candidates"
STATUS_UNAVAILABLE = "unavailable"

STATUS_CONFIRMED = "CONFIRMED"
STATUS_WATCH = "WATCH"
STATUS_NO_SIGNAL = "NO_SIGNAL"
STATUS_INSUFFICIENT = "INSUFFICIENT_DATA"
STATUS_SCOPE_EXCLUDED = "SCOPE_EXCLUDED"

BORROW_UNKNOWN = "UNKNOWN"
BORROW_NOT_SHORTABLE = "NOT_SHORTABLE"
BORROW_EASY = "EASY_TO_BORROW"
BORROW_HARD = "HARD_TO_BORROW"

REQUIRED_COLUMNS: tuple[str, ...] = (
    "signal_date",
    "symbol",
    "cik",
    "sic",
    "market_asof",
    "fundamental_data_asof",
    "market_data_feed",
    "watchlist_source",
    "price",
    "dollar_volume",
    "avg_dollar_volume_20d",
    "return_20d",
    "return_60d",
    "price_to_sma50",
    "revenue",
    "revenue_yoy",
    "operating_cash_flow_growth",
    "operating_cash_flow_growth_direction",
    "adjusted_net_income",
    "pe",
    "shares_stale",
)

OPTIONAL_COLUMNS: tuple[str, ...] = (
    "company_name",
    "sic_description",
    "regime",
    "relative_strength_60d_qqq",
)

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


class ShortResearchInputError(ValueError):
    """A cross-section cannot be evaluated under the v1 input contract."""

    def __init__(self, reason_codes: Iterable[str], detail: str | None = None):
        self.reason_codes = tuple(dict.fromkeys(str(code) for code in reason_codes))
        message = ", ".join(self.reason_codes) or "invalid short-research input"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class BorrowEvidence:
    status: str = BORROW_UNKNOWN
    source: str | None = None
    environment: str | None = None
    observed_at_utc: str | None = None
    reason: str | None = None

    @property
    def display(self) -> str:
        return {
            BORROW_NOT_SHORTABLE: "Broker: not shortable",
            BORROW_EASY: "Broker: easy to borrow",
            BORROW_HARD: "Broker: locate required",
            BORROW_UNKNOWN: "UNKNOWN",
        }.get(self.status, "UNKNOWN")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "display": self.display,
            "source": self.source,
            "environment": self.environment,
            "observed_at_utc": self.observed_at_utc,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "BorrowEvidence":
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            status=str(raw.get("status") or BORROW_UNKNOWN),
            source=_text(raw.get("source")),
            environment=_text(raw.get("environment")),
            observed_at_utc=_text(raw.get("observed_at_utc")),
            reason=_text(raw.get("reason")),
        )


@dataclass(frozen=True)
class ShortCandidate:
    symbol: str
    cik: str
    sic: str
    company_name: str
    sic_description: str
    signal_date: str
    market_asof: str
    fundamental_data_asof: str | None
    market_data_feed: str
    watchlist_source: str
    regime: str
    price: float | None
    dollar_volume: float | None
    avg_dollar_volume_20d: float | None
    return_20d: float | None
    return_60d: float | None
    price_to_sma50: float | None
    relative_strength_60d_qqq: float | None
    rs60_sic: float | None
    peer_median_return_60d: float | None
    industry_peer_count: int | None
    revenue: float | None
    revenue_yoy: float | None
    operating_cash_flow_growth: float | None
    operating_cash_flow_growth_direction: str | None
    adjusted_net_income: float | None
    shares_stale: bool | None
    pe: float | None
    pe_peer_count: int | None
    pe_peer_median: float | None
    pe_percentile: float | None
    pe_premium: float | None
    status: str
    signal_groups: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    invalidation: str = ""
    scope_excluded: bool = False
    selected: bool = False
    rank: int | None = None
    borrow: BorrowEvidence = field(default_factory=BorrowEvidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cik": self.cik,
            "sic": self.sic,
            "company_name": self.company_name,
            "sic_description": self.sic_description,
            "signal_date": self.signal_date,
            "market_asof": self.market_asof,
            "fundamental_data_asof": self.fundamental_data_asof,
            "market_data_feed": self.market_data_feed,
            "watchlist_source": self.watchlist_source,
            "regime": self.regime,
            "price": self.price,
            "dollar_volume": self.dollar_volume,
            "avg_dollar_volume_20d": self.avg_dollar_volume_20d,
            "return_20d": self.return_20d,
            "return_60d": self.return_60d,
            "price_to_sma50": self.price_to_sma50,
            "relative_strength_60d_qqq": self.relative_strength_60d_qqq,
            "rs60_sic": self.rs60_sic,
            "peer_median_return_60d": self.peer_median_return_60d,
            "industry_peer_count": self.industry_peer_count,
            "revenue": self.revenue,
            "revenue_yoy": self.revenue_yoy,
            "operating_cash_flow_growth": self.operating_cash_flow_growth,
            "operating_cash_flow_growth_direction": (
                self.operating_cash_flow_growth_direction
            ),
            "adjusted_net_income": self.adjusted_net_income,
            "shares_stale": self.shares_stale,
            "pe": self.pe,
            "pe_peer_count": self.pe_peer_count,
            "pe_peer_median": self.pe_peer_median,
            "pe_percentile": self.pe_percentile,
            "pe_premium": self.pe_premium,
            "status": self.status,
            "signal_groups": list(self.signal_groups),
            "reason_codes": list(self.reason_codes),
            "invalidation": self.invalidation,
            "scope_excluded": self.scope_excluded,
            "selected": self.selected,
            "rank": self.rank,
            "borrow": self.borrow.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShortCandidate":
        return cls(
            symbol=str(raw.get("symbol") or ""),
            cik=str(raw.get("cik") or ""),
            sic=str(raw.get("sic") or ""),
            company_name=str(raw.get("company_name") or ""),
            sic_description=str(raw.get("sic_description") or ""),
            signal_date=str(raw.get("signal_date") or ""),
            market_asof=str(raw.get("market_asof") or ""),
            fundamental_data_asof=_text(raw.get("fundamental_data_asof")),
            market_data_feed=str(raw.get("market_data_feed") or ""),
            watchlist_source=str(raw.get("watchlist_source") or ""),
            regime=str(raw.get("regime") or "unknown"),
            price=_num(raw.get("price")),
            dollar_volume=_num(raw.get("dollar_volume")),
            avg_dollar_volume_20d=_num(raw.get("avg_dollar_volume_20d")),
            return_20d=_num(raw.get("return_20d")),
            return_60d=_num(raw.get("return_60d")),
            price_to_sma50=_num(raw.get("price_to_sma50")),
            relative_strength_60d_qqq=_num(raw.get("relative_strength_60d_qqq")),
            rs60_sic=_num(raw.get("rs60_sic")),
            peer_median_return_60d=_num(raw.get("peer_median_return_60d")),
            industry_peer_count=_int(raw.get("industry_peer_count")),
            revenue=_num(raw.get("revenue")),
            revenue_yoy=_num(raw.get("revenue_yoy")),
            operating_cash_flow_growth=_num(
                raw.get("operating_cash_flow_growth")
            ),
            operating_cash_flow_growth_direction=_text(
                raw.get("operating_cash_flow_growth_direction")
            ),
            adjusted_net_income=_num(raw.get("adjusted_net_income")),
            shares_stale=_bool_or_none(raw.get("shares_stale")),
            pe=_num(raw.get("pe")),
            pe_peer_count=_int(raw.get("pe_peer_count")),
            pe_peer_median=_num(raw.get("pe_peer_median")),
            pe_percentile=_num(raw.get("pe_percentile")),
            pe_premium=_num(raw.get("pe_premium")),
            status=str(raw.get("status") or STATUS_INSUFFICIENT),
            signal_groups=tuple(str(x) for x in (raw.get("signal_groups") or ())),
            reason_codes=tuple(str(x) for x in (raw.get("reason_codes") or ())),
            invalidation=str(raw.get("invalidation") or ""),
            scope_excluded=bool(raw.get("scope_excluded")),
            selected=bool(raw.get("selected")),
            rank=_int(raw.get("rank")),
            borrow=BorrowEvidence.from_dict(raw.get("borrow")),
        )


@dataclass(frozen=True)
class ShortResearchResult:
    status: str
    signal_date: str | None
    market_data_feed: str | None
    contract_version: str
    rule_version: str
    funnel: Mapping[str, int]
    reason_counts: Mapping[str, int]
    status_counts: Mapping[str, int]
    selected: tuple[ShortCandidate, ...] = ()
    records: tuple[ShortCandidate, ...] = ()
    reason_codes: tuple[str, ...] = ()
    generated_at_utc: str | None = None

    @property
    def enabled(self) -> bool:
        return self.status != STATUS_DISABLED

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SHORT_RESEARCH_SCHEMA_VERSION,
            "contract_version": self.contract_version,
            "rule_version": self.rule_version,
            "status": self.status,
            "signal_date": self.signal_date,
            "market_data_feed": self.market_data_feed,
            "generated_at_utc": self.generated_at_utc,
            "reason_codes": list(self.reason_codes),
            "funnel": dict(self.funnel),
            "reason_counts": dict(self.reason_counts),
            "status_counts": dict(self.status_counts),
            "selected": [candidate.to_dict() for candidate in self.selected],
        }

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> "ShortResearchResult":
        selected = tuple(
            ShortCandidate.from_dict(item)
            for item in (raw.get("selected") or ())
            if isinstance(item, Mapping)
        )
        return cls(
            status=str(raw.get("status") or STATUS_UNAVAILABLE),
            signal_date=_text(raw.get("signal_date")),
            market_data_feed=_text(raw.get("market_data_feed")),
            contract_version=str(
                raw.get("contract_version") or SHORT_RESEARCH_CONTRACT_VERSION
            ),
            rule_version=str(raw.get("rule_version") or SHORT_RESEARCH_RULE_VERSION),
            funnel={str(k): int(v) for k, v in (raw.get("funnel") or {}).items()},
            reason_counts={
                str(k): int(v) for k, v in (raw.get("reason_counts") or {}).items()
            },
            status_counts={
                str(k): int(v) for k, v in (raw.get("status_counts") or {}).items()
            },
            selected=selected,
            records=selected,
            reason_codes=tuple(str(x) for x in (raw.get("reason_codes") or ())),
            generated_at_utc=_text(raw.get("generated_at_utc")),
        )


def build_short_feature_frame(
    frame: pd.DataFrame,
    *,
    signal_date: str,
    market_data_feed: str,
    watchlist_source: str,
) -> pd.DataFrame:
    """Read-only adapter from the scanner frame to the v1 feature whitelist.

    The adapter copies only contract columns; it never mutates the scanner
    frame and never applies long-only financial, ranking, theme, or QQQ gates.
    """
    columns = (
        "symbol",
        "cik",
        "sic",
        "market_asof",
        "fundamental_data_asof",
        "price",
        "dollar_volume",
        "avg_dollar_volume_20d",
        "return_20d",
        "return_60d",
        "price_to_sma50",
        "revenue",
        "revenue_yoy",
        "operating_cash_flow_growth",
        "operating_cash_flow_growth_direction",
        "adjusted_net_income",
        "pe",
        "shares_stale",
        "company_name",
        "sic_description",
        "regime",
        "relative_strength_60d_qqq",
    )
    work = frame.copy()
    adapted = pd.DataFrame(index=work.index)
    for column in columns:
        adapted[column] = work[column] if column in work.columns else np.nan
    adapted["signal_date"] = str(signal_date)
    adapted["market_data_feed"] = str(market_data_feed)
    adapted["watchlist_source"] = str(watchlist_source)
    return adapted.reset_index(drop=True)


def disabled_short_research_result() -> ShortResearchResult:
    return ShortResearchResult(
        status=STATUS_DISABLED,
        signal_date=None,
        market_data_feed=None,
        contract_version=SHORT_RESEARCH_CONTRACT_VERSION,
        rule_version=SHORT_RESEARCH_RULE_VERSION,
        funnel={},
        reason_counts={},
        status_counts={},
    )


def unavailable_short_research_result(
    reason_codes: Iterable[str],
    *,
    signal_date: str | None = None,
    market_data_feed: str | None = None,
    funnel: Mapping[str, int] | None = None,
    status_counts: Mapping[str, int] | None = None,
    reason_counts: Mapping[str, int] | None = None,
    generated_at_utc: str | None = None,
) -> ShortResearchResult:
    codes = tuple(dict.fromkeys(str(code) for code in reason_codes))
    return ShortResearchResult(
        status=STATUS_UNAVAILABLE,
        signal_date=signal_date,
        market_data_feed=market_data_feed,
        contract_version=SHORT_RESEARCH_CONTRACT_VERSION,
        rule_version=SHORT_RESEARCH_RULE_VERSION,
        funnel=dict(funnel or {}),
        reason_counts=dict(reason_counts or {}),
        status_counts=dict(status_counts or {}),
        reason_codes=codes,
        generated_at_utc=generated_at_utc,
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    token = str(value).strip()
    if token.lower() in {"nan", "nat", "none"}:
        return None
    return token or None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    token = str(value).strip().lower()
    if token in {"true", "1", "yes", "y"}:
        return True
    if token in {"false", "0", "no", "n"}:
        return False
    return None


def _parse_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _canonical_cik(value: Any) -> str | None:
    token = _text(value)
    if token is None:
        return None
    if token.endswith(".0"):
        token = token[:-2]
    if not token.isdigit():
        return None
    token = token.lstrip("0") or "0"
    return token if int(token) > 0 else None


def _canonical_sic(value: Any) -> str | None:
    token = _text(value)
    if token is None:
        return None
    if token.endswith(".0"):
        token = token[:-2]
    if not token.isdigit():
        return None
    token = token.zfill(4)
    if len(token) != 4:
        return None
    number = int(token)
    if number < 100 or number > 9999:
        return None
    return token


def _reason(reasons: dict[int, list[str]], index: int, code: str) -> None:
    bucket = reasons.setdefault(int(index), [])
    if code not in bucket:
        bucket.append(code)


def _normalize_features(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[int, list[str]], str, str]:
    if not isinstance(frame, pd.DataFrame):
        raise ShortResearchInputError(("INPUT_NOT_DATAFRAME",))
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ShortResearchInputError(
            ("MISSING_COLUMNS",),
            "missing " + ", ".join(missing),
        )
    work = frame.copy().reset_index(drop=True)
    reasons: dict[int, list[str]] = {}

    signal_dates = {_parse_date(value) for value in work["signal_date"]}
    if None in signal_dates or len(signal_dates) != 1:
        raise ShortResearchInputError(
            ("INVALID_SIGNAL_DATE",),
            "exactly one valid signal_date is required",
        )
    signal_date = next(iter(signal_dates))
    assert signal_date is not None
    signal_iso = signal_date.isoformat()

    feeds = {
        str(value).strip().lower()
        for value in work["market_data_feed"].dropna().tolist()
        if str(value).strip()
    }
    if feeds != {"sip"}:
        raise ShortResearchInputError(
            ("MIXED_OR_UNKNOWN_FEED",),
            f"expected sip only, got {sorted(feeds)}",
        )

    work["signal_date"] = signal_iso
    work["symbol"] = work["symbol"].map(lambda value: str(value or "").strip().upper())
    work["cik"] = work["cik"].map(_canonical_cik)
    work["sic"] = work["sic"].map(_canonical_sic)
    work["company_name"] = work.get("company_name", pd.Series("", index=work.index)).fillna("").astype(str)
    work["sic_description"] = work.get("sic_description", pd.Series("", index=work.index)).fillna("").astype(str)
    work["watchlist_source"] = work["watchlist_source"].fillna("unknown").astype(str)
    work["regime"] = work.get("regime", pd.Series("unknown", index=work.index)).fillna("unknown").astype(str)
    work["market_data_feed"] = work["market_data_feed"].astype(str).str.strip().str.lower()

    work["market_asof_date"] = work["market_asof"].map(_parse_date)
    work["fundamental_data_asof_date"] = work["fundamental_data_asof"].map(_parse_date)

    numeric_columns = (
        "price",
        "dollar_volume",
        "avg_dollar_volume_20d",
        "return_20d",
        "return_60d",
        "price_to_sma50",
        "revenue",
        "revenue_yoy",
        "operating_cash_flow_growth",
        "adjusted_net_income",
        "pe",
        "relative_strength_60d_qqq",
    )
    for column in numeric_columns:
        if column not in work.columns:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
        work.loc[~np.isfinite(work[column].astype(float)), column] = np.nan

    work["shares_stale"] = work["shares_stale"].map(_bool_or_none)
    work["operating_cash_flow_growth_direction"] = (
        work["operating_cash_flow_growth_direction"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    market_asof_ok: list[bool] = []
    fundamental_asof_ok: list[bool] = []
    for index, row in work.iterrows():
        symbol = str(row["symbol"] or "")
        if not _SYMBOL_RE.fullmatch(symbol):
            _reason(reasons, index, "SYMBOL_INVALID")
        if row["cik"] is None:
            _reason(reasons, index, "CIK_INVALID")
        if row["sic"] is None:
            _reason(reasons, index, "SIC_INVALID")
        market_ok = row["market_asof_date"] == signal_date
        market_asof_ok.append(bool(market_ok))
        if not market_ok:
            _reason(reasons, index, "MARKET_ASOF_MISMATCH")
        fundamental_date = row["fundamental_data_asof_date"]
        fundamental_ok = False
        if fundamental_date is None:
            _reason(reasons, index, "FUNDAMENTAL_ASOF_MISSING")
        else:
            age = (signal_date - fundamental_date).days
            if age < 0:
                _reason(reasons, index, "FUNDAMENTAL_ASOF_FUTURE")
            elif age > MAX_FUNDAMENTAL_ASOF_DAYS:
                _reason(reasons, index, "FUNDAMENTAL_ASOF_STALE")
            else:
                fundamental_ok = True
        fundamental_asof_ok.append(fundamental_ok)
        if row["shares_stale"] is None:
            _reason(reasons, index, "SHARES_STALE_UNKNOWN")

    work["_market_asof_ok"] = market_asof_ok
    work["_fundamental_asof_ok"] = fundamental_asof_ok

    duplicate_mask = work.duplicated(["signal_date", "symbol"], keep=False)
    if bool(duplicate_mask.any()):
        duplicate_symbols = sorted(
            work.loc[duplicate_mask, "symbol"].astype(str).unique().tolist()
        )
        raise ShortResearchInputError(
            ("DUPLICATE_DATE_SYMBOL",),
            "duplicate signal_date x symbol keys: " + ", ".join(duplicate_symbols[:10]),
        )

    work = work.drop(columns=["market_asof_date", "fundamental_data_asof_date"])
    return work, reasons, signal_iso, "sip"


def _invalidation_text(row: Mapping[str, Any]) -> str:
    return (
        "Recheck if price closes at/above SMA50, rs60_sic turns >= 0, "
        "revenue_yoy turns > 0, OCF growth turns > -10%, or P/E percentile "
        "falls below 0.80 / premium below 25%."
    )


def _candidate_from_row(
    row: Mapping[str, Any],
    *,
    status: str,
    signal_groups: tuple[str, ...],
    reason_codes: Sequence[str],
    scope_excluded: bool,
    selected: bool,
    rank: int | None,
    borrow: BorrowEvidence,
    rs60_sic: float | None,
    peer_median_return_60d: float | None,
    industry_peer_count: int | None,
    pe_peer_count: int | None,
    pe_peer_median: float | None,
    pe_percentile: float | None,
    pe_premium: float | None,
) -> ShortCandidate:
    return ShortCandidate(
        symbol=str(row.get("symbol") or ""),
        cik=str(row.get("cik") or ""),
        sic=str(row.get("sic") or ""),
        company_name=str(row.get("company_name") or ""),
        sic_description=str(row.get("sic_description") or ""),
        signal_date=str(row.get("signal_date") or ""),
        market_asof=str(row.get("market_asof") or ""),
        fundamental_data_asof=_text(row.get("fundamental_data_asof")),
        market_data_feed=str(row.get("market_data_feed") or ""),
        watchlist_source=str(row.get("watchlist_source") or ""),
        regime=str(row.get("regime") or "unknown"),
        price=_num(row.get("price")),
        dollar_volume=_num(row.get("dollar_volume")),
        avg_dollar_volume_20d=_num(row.get("avg_dollar_volume_20d")),
        return_20d=_num(row.get("return_20d")),
        return_60d=_num(row.get("return_60d")),
        price_to_sma50=_num(row.get("price_to_sma50")),
        relative_strength_60d_qqq=_num(row.get("relative_strength_60d_qqq")),
        rs60_sic=rs60_sic,
        peer_median_return_60d=peer_median_return_60d,
        industry_peer_count=industry_peer_count,
        revenue=_num(row.get("revenue")),
        revenue_yoy=_num(row.get("revenue_yoy")),
        operating_cash_flow_growth=_num(row.get("operating_cash_flow_growth")),
        operating_cash_flow_growth_direction=_text(
            row.get("operating_cash_flow_growth_direction")
        ),
        adjusted_net_income=_num(row.get("adjusted_net_income")),
        shares_stale=_bool_or_none(row.get("shares_stale")),
        pe=_num(row.get("pe")),
        pe_peer_count=pe_peer_count,
        pe_peer_median=pe_peer_median,
        pe_percentile=pe_percentile,
        pe_premium=pe_premium,
        status=status,
        signal_groups=signal_groups,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        invalidation=_invalidation_text(row),
        scope_excluded=scope_excluded,
        selected=selected,
        rank=rank,
        borrow=borrow,
    )


def build_short_cross_section(
    features: pd.DataFrame,
    *,
    borrow_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    report_generated_at_utc: str | datetime | None = None,
) -> ShortResearchResult:
    """Build one signal-date short-research cross-section.

    The function is pure with respect to its inputs: it never reads files,
    never calls the network, and never consults long-only decisions.  Borrow
    metadata is optional and only affects display fields.
    """
    work, reasons, signal_date, feed = _normalize_features(features)
    if work.empty:
        return unavailable_short_research_result(
            ("EMPTY_CROSS_SECTION",),
            signal_date=signal_date,
            market_data_feed=feed,
        )

    # U0: price/liquidity, valid identity, valid SIC, finite required price
    # features, and an exact same-session market as-of.
    for index, row in work.iterrows():
        price = _num(row.get("price"))
        if price is None:
            _reason(reasons, index, "PRICE_MISSING")
        elif price < MIN_PRICE:
            _reason(reasons, index, "PRICE_BELOW_MIN")
        dollar_volume = _num(row.get("dollar_volume"))
        if dollar_volume is None:
            _reason(reasons, index, "DOLLAR_VOLUME_MISSING")
        elif dollar_volume < MIN_DOLLAR_VOLUME:
            _reason(reasons, index, "DOLLAR_VOLUME_BELOW_MIN")
        avg_dv = _num(row.get("avg_dollar_volume_20d"))
        if avg_dv is None:
            _reason(reasons, index, "AVG_DOLLAR_VOLUME_MISSING")
        elif avg_dv < MIN_AVG_DOLLAR_VOLUME_20D:
            _reason(reasons, index, "AVG_DOLLAR_VOLUME_BELOW_MIN")
        for column, code in (
            ("price_to_sma50", "PRICE_TO_SMA50_MISSING"),
            ("return_20d", "RETURN_20D_MISSING"),
            ("return_60d", "RETURN_60D_MISSING"),
        ):
            if _num(row.get(column)) is None:
                _reason(reasons, index, code)
        if _num(row.get("price_to_sma50")) is not None and float(row["price_to_sma50"]) <= 0:
            _reason(reasons, index, "PRICE_TO_SMA50_NONPOSITIVE")
        sic = str(row.get("sic") or "")
        if sic.isdigit() and EXCLUDED_SIC_MIN <= int(sic) <= EXCLUDED_SIC_MAX:
            _reason(reasons, index, "SIC_FINANCIAL_EXCLUDED")

    base_mask = pd.Series(True, index=work.index)
    scope_reason_codes = {
        "SYMBOL_INVALID",
        "CIK_INVALID",
        "SIC_INVALID",
        "SIC_FINANCIAL_EXCLUDED",
        "MARKET_ASOF_MISMATCH",
        "PRICE_MISSING",
        "PRICE_BELOW_MIN",
        "DOLLAR_VOLUME_MISSING",
        "DOLLAR_VOLUME_BELOW_MIN",
        "AVG_DOLLAR_VOLUME_MISSING",
        "AVG_DOLLAR_VOLUME_BELOW_MIN",
        "PRICE_TO_SMA50_MISSING",
        "PRICE_TO_SMA50_NONPOSITIVE",
        "RETURN_20D_MISSING",
        "RETURN_60D_MISSING",
    }
    for index, codes in reasons.items():
        if scope_reason_codes.intersection(codes):
            base_mask.loc[index] = False
    u0 = work.loc[base_mask].copy()
    u0_rows = len(u0)

    # One security per CIK per date: highest 20d average dollar volume, then
    # symbol ascending.  Losing share classes stay visible as scope exclusions.
    if not u0.empty:
        u0 = u0.sort_values(
            ["signal_date", "cik", "avg_dollar_volume_20d", "symbol"],
            ascending=[True, True, False, True],
            kind="mergesort",
        )
        duplicated = u0.duplicated(["signal_date", "cik"], keep="first")
        for index in u0.loc[duplicated].index:
            _reason(reasons, index, "DUPLICATE_CIK_LOWER_ADV")
        u0 = u0.loc[~duplicated].copy()
    u0_unique_rows = len(u0)
    u0_index_set = {int(index) for index in u0.index}

    rs60_by_index: dict[int, float] = {}
    peer_count_by_index: dict[int, int] = {}
    for _, group in u0.groupby("sic", sort=True):
        values = group.loc[
            group["return_60d"].notna(), ["symbol", "return_60d"]
        ]
        if len(values) < MIN_INDUSTRY_PEERS + 1:
            for index in group.index:
                _reason(reasons, index, "INDUSTRY_PEERS_INSUFFICIENT")
            continue
        for index, row in values.iterrows():
            others = values.loc[values["symbol"] != row["symbol"], "return_60d"]
            if len(others) < MIN_INDUSTRY_PEERS:
                _reason(reasons, index, "INDUSTRY_PEERS_INSUFFICIENT")
                continue
            rs60_by_index[int(index)] = float(row["return_60d"]) - float(
                others.median()
            )
            peer_count_by_index[int(index)] = int(len(others))

    pe_by_index: dict[int, tuple[int, float, float, float]] = {}
    pe_base = u0.loc[
        (u0["_fundamental_asof_ok"] == True)  # noqa: E712 - explicit contract
        & (u0["shares_stale"] == False)  # noqa: E712 - explicit contract
        & (u0["adjusted_net_income"].notna())
        & (u0["adjusted_net_income"] > 0)
        & (u0["pe"].notna())
        & (u0["pe"] > 0)
    ].copy()
    for _, group in pe_base.groupby("sic", sort=True):
        if len(group) < MIN_PE_PEERS:
            for index in group.index:
                _reason(reasons, index, "PE_PEERS_INSUFFICIENT")
            continue
        median = float(group["pe"].median())
        ranks = group["pe"].rank(method="average", pct=True)
        for index, row in group.iterrows():
            pe_by_index[int(index)] = (
                int(len(group)),
                median,
                float(ranks.loc[index]),
                float(row["pe"] / median - 1.0),
            )

    # U: common financial/valuation/industry evidence.  Missing pieces are
    # INSUFFICIENT_DATA, not a negative signal.
    u_mask = pd.Series(False, index=u0.index)
    for index, row in u0.iterrows():
        ok = True
        if not bool(row.get("_fundamental_asof_ok")):
            ok = False
            _reason(reasons, index, "FUNDAMENTAL_ASOF_INVALID")
        if int(index) not in rs60_by_index:
            ok = False
            _reason(reasons, index, "INDUSTRY_RS_MISSING")
        if int(index) not in pe_by_index:
            ok = False
            _reason(reasons, index, "PE_VALUATION_MISSING")
        revenue = _num(row.get("revenue"))
        if revenue is None:
            ok = False
            _reason(reasons, index, "REVENUE_MISSING")
        elif revenue <= 0:
            ok = False
            _reason(reasons, index, "REVENUE_NONPOSITIVE")
        revenue_yoy = _num(row.get("revenue_yoy"))
        if revenue_yoy is None:
            ok = False
            _reason(reasons, index, "REVENUE_YOY_MISSING")
        elif revenue_yoy <= -1.0:
            ok = False
            _reason(reasons, index, "REVENUE_YOY_INVALID")
        ocf_growth = _num(row.get("operating_cash_flow_growth"))
        direction = str(row.get("operating_cash_flow_growth_direction") or "")
        if ocf_growth is None:
            ok = False
            _reason(reasons, index, "OCF_GROWTH_MISSING")
        if direction not in VALID_OCF_DIRECTIONS:
            ok = False
            _reason(reasons, index, "OCF_DIRECTION_INVALID")
        if ok:
            u_mask.loc[index] = True

    u = u0.loc[u_mask].copy()
    # Materialize peer fields for selection and records.
    u["rs60_sic"] = [rs60_by_index.get(int(index)) for index in u.index]
    u["industry_peer_count"] = [peer_count_by_index.get(int(index)) for index in u.index]
    u["pe_peer_count"] = [pe_by_index.get(int(index), (None,))[0] for index in u.index]
    u["pe_peer_median"] = [pe_by_index.get(int(index), (None, None))[1] for index in u.index]
    u["pe_percentile"] = [pe_by_index.get(int(index), (None, None, None))[2] for index in u.index]
    u["pe_premium"] = [pe_by_index.get(int(index), (None, None, None, None))[3] for index in u.index]

    u["_s0"] = (
        (u["rs60_sic"] < SHORT_RS60_SIC_MAX)
        & (u["price_to_sma50"] < SHORT_SMA50_MAX)
        & (u["return_20d"] > SHORT_RET20_MIN)
    )
    u["_financial_weak"] = (
        (u["revenue_yoy"] <= SHORT_REVENUE_YOY_MAX)
        & (u["operating_cash_flow_growth"] <= SHORT_OCF_GROWTH_MAX)
    )
    u["_valuation_stretched"] = (
        (u["pe_percentile"] >= SHORT_PE_PERCENTILE_MIN)
        & (u["pe_premium"] >= SHORT_PE_PREMIUM_MIN)
    )
    u["_s1"] = u["_s0"] & u["_financial_weak"]
    u["_s2"] = u["_s1"] & u["_valuation_stretched"]
    u["_sharp_drop"] = u["return_20d"] <= SHORT_RET20_MIN
    u["_watch"] = (
        u["_financial_weak"]
        & u["_valuation_stretched"]
        & (~u["_s0"] | u["_sharp_drop"])
    )

    selected_indices = (
        u.loc[u["_s2"]]
        .sort_values(["rs60_sic", "symbol"], ascending=[True, True], kind="mergesort")
        .head(MAX_SHORT_CANDIDATES)
        .index
    )
    selected_set = {int(index) for index in selected_indices}
    rank_by_index = {
        int(index): rank for rank, index in enumerate(selected_indices, start=1)
    }

    borrow_map = borrow_by_symbol or {}
    report_dt = _coerce_utc(report_generated_at_utc) or datetime.now(timezone.utc)
    records: list[ShortCandidate] = []
    for index, row in work.iterrows():
        idx = int(index)
        codes = tuple(reasons.get(idx, ()))
        if idx not in u0_index_set:
            status = STATUS_SCOPE_EXCLUDED
            groups: tuple[str, ...] = ()
            scope_excluded = True
        elif idx not in u.index:
            status = STATUS_INSUFFICIENT
            groups = ()
            scope_excluded = False
        else:
            s0 = bool(u.at[idx, "_s0"])
            s1 = bool(u.at[idx, "_s1"])
            s2 = bool(u.at[idx, "_s2"])
            groups = tuple(
                name for name, flag in (("S0", s0), ("S1", s1), ("S2", s2)) if flag
            )
            if s2:
                status = STATUS_CONFIRMED
            elif bool(u.at[idx, "_watch"]):
                status = STATUS_WATCH
            else:
                status = STATUS_NO_SIGNAL
            scope_excluded = False
        pe_info = pe_by_index.get(idx, (None, None, None, None))
        borrow = resolve_borrow_evidence(
            borrow_map.get(str(row.get("symbol") or "")),
            signal_date=signal_date,
            report_generated_at_utc=report_dt,
        )
        records.append(
            _candidate_from_row(
                row,
                status=status,
                signal_groups=groups,
                reason_codes=codes,
                scope_excluded=scope_excluded,
                selected=idx in selected_set,
                rank=rank_by_index.get(idx),
                borrow=borrow,
                rs60_sic=rs60_by_index.get(idx),
                peer_median_return_60d=(
                    float(row["return_60d"]) - rs60_by_index[idx]
                    if idx in rs60_by_index
                    and _num(row.get("return_60d")) is not None
                    else None
                ),
                industry_peer_count=peer_count_by_index.get(idx),
                pe_peer_count=pe_info[0],
                pe_peer_median=pe_info[1],
                pe_percentile=pe_info[2],
                pe_premium=pe_info[3],
            )
        )

    selected = tuple(
        sorted(
            (record for record in records if record.selected),
            key=lambda record: (record.rank or 999, record.symbol),
        )
    )
    status_counts = Counter(record.status for record in records)
    reason_counts = Counter(
        code for record in records for code in record.reason_codes
    )
    funnel = {
        "input_rows": int(len(work)),
        "u0_rows": int(u0_rows),
        "u0_unique_rows": int(u0_unique_rows),
        "industry_rs_rows": int(len(rs60_by_index)),
        "pe_eligible_rows": int(len(pe_base)),
        "pe_rows": int(len(pe_by_index)),
        "u_rows": int(len(u)),
        "s0_rows": int(u["_s0"].sum()),
        "s1_rows": int(u["_s1"].sum()),
        "s2_rows": int(u["_s2"].sum()),
        "selected_rows": int(len(selected)),
    }
    return ShortResearchResult(
        status=STATUS_READY if selected else STATUS_NO_CANDIDATES,
        signal_date=signal_date,
        market_data_feed=feed,
        contract_version=SHORT_RESEARCH_CONTRACT_VERSION,
        rule_version=SHORT_RESEARCH_RULE_VERSION,
        funnel=funnel,
        reason_counts=dict(sorted(reason_counts.items())),
        status_counts=dict(sorted(status_counts.items())),
        selected=selected,
        records=tuple(records),
        generated_at_utc=report_dt.isoformat(),
    )


def _coerce_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_borrow_evidence(
    raw: Mapping[str, Any] | None,
    *,
    signal_date: str | date | None,
    report_generated_at_utc: str | datetime | None,
    max_age_hours: float = 24.0,
    expected_source: str | None = None,
    expected_environment: str | None = None,
) -> BorrowEvidence:
    """Normalize optional broker borrow metadata under the v1 trust rules.

    A bare cache without source/environment/observation time is UNKNOWN.  The
    observation must be after the signal-date New York close, before report
    generation, and no more than 24 hours old.
    """
    if not isinstance(raw, Mapping):
        return BorrowEvidence(reason="no broker metadata")
    source = _text(raw.get("source"))
    environment = _text(raw.get("environment"))
    observed_raw = _text(raw.get("observed_at_utc"))
    if not source or not environment or not observed_raw:
        return BorrowEvidence(reason="source/environment/observed_at missing")
    if expected_source is not None and source != expected_source:
        return BorrowEvidence(reason="source mismatch")
    if expected_environment is not None and environment != expected_environment:
        return BorrowEvidence(reason="environment mismatch")
    observed = _coerce_utc(observed_raw)
    report_dt = _coerce_utc(report_generated_at_utc)
    if observed is None or report_dt is None:
        return BorrowEvidence(reason="unparseable observation time")
    signal = _parse_date(signal_date)
    if signal is None:
        return BorrowEvidence(reason="invalid signal date")
    close_local = datetime.combine(
        signal,
        time(16, 0),
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(timezone.utc)
    if observed < close_local:
        return BorrowEvidence(reason="observation precedes signal close")
    if observed > report_dt:
        return BorrowEvidence(reason="observation is after report generation")
    if (report_dt - observed) > timedelta(hours=float(max_age_hours)):
        return BorrowEvidence(reason="observation older than 24 hours")

    shortable = _bool_or_none(raw.get("shortable"))
    easy = _bool_or_none(raw.get("easy_to_borrow"))
    hard = _bool_or_none(raw.get("hard_to_borrow"))
    if shortable is None:
        return BorrowEvidence(reason="shortable field missing or invalid")
    if shortable is False:
        status = BORROW_NOT_SHORTABLE
    elif easy is True and hard is True:
        return BorrowEvidence(reason="conflicting borrow flags")
    elif easy is True:
        status = BORROW_EASY
    elif hard is True:
        status = BORROW_HARD
    else:
        return BorrowEvidence(reason="shortable true without borrow class")
    return BorrowEvidence(
        status=status,
        source=source,
        environment=environment,
        observed_at_utc=observed.isoformat(),
    )


def short_candidate_rows(result: ShortResearchResult) -> list[dict[str, Any]]:
    """CSV rows, in selected rank order, with the required v1 columns."""
    rows: list[dict[str, Any]] = []
    for candidate in result.selected:
        rows.append(
            {
                "signal_date": candidate.signal_date,
                "rank": candidate.rank,
                "symbol": candidate.symbol,
                "sic": candidate.sic,
                "sic_description": candidate.sic_description,
                "fundamental_data_asof": candidate.fundamental_data_asof,
                "market_asof": candidate.market_asof,
                "return_60d": candidate.return_60d,
                "rs60_sic": candidate.rs60_sic,
                "peer_median_return_60d": candidate.peer_median_return_60d,
                "industry_peer_count": candidate.industry_peer_count,
                "price_to_sma50": candidate.price_to_sma50,
                "return_20d": candidate.return_20d,
                "revenue_yoy": candidate.revenue_yoy,
                "operating_cash_flow_growth": candidate.operating_cash_flow_growth,
                "operating_cash_flow_growth_direction": (
                    candidate.operating_cash_flow_growth_direction
                ),
                "pe": candidate.pe,
                "pe_peer_count": candidate.pe_peer_count,
                "pe_peer_median": candidate.pe_peer_median,
                "pe_percentile": candidate.pe_percentile,
                "pe_premium": candidate.pe_premium,
                "signal_status": candidate.status,
                "reason_codes": "|".join(candidate.reason_codes),
                "invalidation": candidate.invalidation,
                "borrow_status": candidate.borrow.status,
                "borrow_source": candidate.borrow.source or "",
                "borrow_environment": candidate.borrow.environment or "",
                "borrow_observed_at_utc": candidate.borrow.observed_at_utc or "",
                "borrow_display": candidate.borrow.display,
            }
        )
    return rows


SHORT_CSV_COLUMNS: tuple[str, ...] = (
    "signal_date",
    "rank",
    "symbol",
    "sic",
    "sic_description",
    "fundamental_data_asof",
    "market_asof",
    "return_60d",
    "rs60_sic",
    "peer_median_return_60d",
    "industry_peer_count",
    "price_to_sma50",
    "return_20d",
    "revenue_yoy",
    "operating_cash_flow_growth",
    "operating_cash_flow_growth_direction",
    "pe",
    "pe_peer_count",
    "pe_peer_median",
    "pe_percentile",
    "pe_premium",
    "signal_status",
    "reason_codes",
    "invalidation",
    "borrow_status",
    "borrow_source",
    "borrow_environment",
    "borrow_observed_at_utc",
    "borrow_display",
)


def short_candidates_csv(result: ShortResearchResult) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(SHORT_CSV_COLUMNS),
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in short_candidate_rows(result):
        writer.writerow(row)
    return buffer.getvalue()


def short_research_json(result: ShortResearchResult) -> str:
    return json.dumps(
        result.to_payload(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


def _fmt_num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_short_research_section(
    result: ShortResearchResult,
    *,
    csv_rel_path: str = "./short_candidates.csv",
) -> list[str]:
    """Render the independent Short Research block from one result object."""
    lines = [
        '<a id="short-research"></a>',
        f"## Short Research ({result.selected_count})",
        "",
        f"- **Status**: `{result.status}` · **Rule**: `{result.rule_version}` "
        f"· **Signal date**: {result.signal_date or 'n/a'} "
        f"· **Feed**: {result.market_data_feed or 'n/a'}",
        "- **Independence**: This is a fourth, separate research list. It does "
        "not change the long Top-15, Action states, Low-Value, Industry-Trend, "
        "Momentum, or Research Pool. It is not a trade instruction.",
    ]
    if result.reason_codes:
        lines.append(
            "- **Unavailable reasons**: "
            + ", ".join(f"`{code}`" for code in result.reason_codes)
        )
    if result.funnel:
        lines.append(
            "- **Funnel**: "
            f"input {result.funnel.get('input_rows', 0)} → "
            f"U0 {result.funnel.get('u0_unique_rows', 0)} → "
            f"industry RS {result.funnel.get('industry_rs_rows', 0)} → "
            f"P/E {result.funnel.get('pe_rows', 0)} → "
            f"U {result.funnel.get('u_rows', 0)} → "
            f"S0 {result.funnel.get('s0_rows', 0)} → "
            f"S1 {result.funnel.get('s1_rows', 0)} → "
            f"S2 {result.funnel.get('s2_rows', 0)} → "
            f"selected {result.funnel.get('selected_rows', 0)}"
        )
    if result.status_counts:
        lines.append(
            "- **Status counts**: "
            + " · ".join(
                f"{key} {value}" for key, value in sorted(result.status_counts.items())
            )
        )
    if result.reason_counts:
        lines.append(
            "- **Reason counts**: "
            + " · ".join(
                f"{key} {value}" for key, value in sorted(result.reason_counts.items())
            )
        )
    lines.append(
        f"- **CSV**: [short_candidates.csv]({csv_rel_path})"
    )
    lines.append("")
    if result.status == STATUS_DISABLED:
        lines.extend(["- Short Research is disabled for this run.", ""])
        return lines
    if result.status == STATUS_UNAVAILABLE:
        lines.extend(
            [
                "- The short-research cross-section was unavailable; no "
                "candidate list was produced. The long-only report is unaffected.",
                "",
            ]
        )
        return lines
    if result.status == STATUS_NO_CANDIDATES:
        lines.extend(
            [
                "- Screening completed; no S2 candidate met all conditions.",
                "",
            ]
        )
        return lines
    lines.extend(
        [
            "| # | Symbol | SIC | RS60 vs peers | SMA50 | 20d | Rev YoY | OCF YoY | P/E pct | P/E prem | Borrow |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for candidate in result.selected:
        lines.append(
            "| {rank} | {symbol} | {sic} | {rs} | {sma} | {r20} | {rev} | {ocf} | "
            "{pct} | {prem} | {borrow} |".format(
                rank=candidate.rank or "",
                symbol=candidate.symbol,
                sic=candidate.sic,
                rs=_fmt_pct(candidate.rs60_sic),
                sma=_fmt_num(candidate.price_to_sma50, 3),
                r20=_fmt_pct(candidate.return_20d),
                rev=_fmt_pct(candidate.revenue_yoy),
                ocf=_fmt_pct(candidate.operating_cash_flow_growth),
                pct=_fmt_num(candidate.pe_percentile, 3),
                prem=_fmt_pct(candidate.pe_premium),
                borrow=candidate.borrow.display,
            )
        )
    lines.append("")
    lines.append(
        "- **Invalidation**: Recheck if price closes at/above SMA50, "
        "`rs60_sic` turns >= 0, revenue growth turns > 0, OCF growth turns "
        "> -10%, or the P/E percentile/premium falls below 0.80 / 25%."
    )
    lines.append(
        "- **Borrow**: `UNKNOWN` means no verified, time-stamped broker "
        "observation was available. Quantity and fee are intentionally blank; "
        "verify with the broker before any action."
    )
    lines.append("")
    return lines


def render_short_research_scan_context(
    result: ShortResearchResult,
    *,
    csv_path: str | Path | None = None,
) -> list[str]:
    lines = [
        "## Short Research",
        "",
        f"- status: {result.status}",
        f"- rule: {result.rule_version}",
        f"- signal date: {result.signal_date or 'n/a'}",
        f"- feed: {result.market_data_feed or 'n/a'}",
        f"- selected: {result.selected_count}",
    ]
    if result.funnel:
        lines.append(
            "- funnel: "
            + ", ".join(f"{key}={value}" for key, value in result.funnel.items())
        )
    if result.reason_codes:
        lines.append("- reasons: " + ", ".join(result.reason_codes))
    if csv_path is not None:
        lines.append(f"- csv: {csv_path}")
    lines.append("")
    return lines


def evaluate_frozen_short_research(
    dataset_root: str | Path,
    output_root: str | Path,
    *,
    scope: str = "full",
) -> dict[str, Any]:
    """Lazy wrapper for the frozen-data evaluator (keeps import graph small)."""
    from .short_research_v1_eval import evaluate_frozen_short_research as _impl

    return _impl(dataset_root, output_root, scope=scope)


__all__ = [
    "BORROW_EASY",
    "BORROW_HARD",
    "BORROW_NOT_SHORTABLE",
    "BORROW_UNKNOWN",
    "BorrowEvidence",
    "MAX_SHORT_CANDIDATES",
    "SHORT_CSV_COLUMNS",
    "SHORT_RESEARCH_CONTRACT_VERSION",
    "SHORT_RESEARCH_RULE_VERSION",
    "STATUS_CONFIRMED",
    "STATUS_DISABLED",
    "STATUS_INSUFFICIENT",
    "STATUS_NO_CANDIDATES",
    "STATUS_NO_SIGNAL",
    "STATUS_READY",
    "STATUS_SCOPE_EXCLUDED",
    "STATUS_UNAVAILABLE",
    "STATUS_WATCH",
    "ShortCandidate",
    "ShortResearchInputError",
    "ShortResearchResult",
    "build_short_cross_section",
    "build_short_feature_frame",
    "disabled_short_research_result",
    "evaluate_frozen_short_research",
    "render_short_research_scan_context",
    "render_short_research_section",
    "resolve_borrow_evidence",
    "short_candidate_rows",
    "short_candidates_csv",
    "short_research_json",
    "unavailable_short_research_result",
]
