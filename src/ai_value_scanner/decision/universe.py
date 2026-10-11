from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import math
from typing import Any

import pandas as pd


CANDIDATE_UNIVERSE_CONTRACT_VERSION = "candidate_universe_v1_2026-10-11"

ASSET_STAGE = "asset_eligibility"
SEC_MAPPING_STAGE = "sec_mapping"
SAMPLE_STAGE = "sample_limit"
PRICE_LIQUIDITY_STAGE = "price_liquidity_prefilter"

ACTIVE_ASSET_MISSING = "ALPACA_ACTIVE_ASSET_MISSING"
NOT_TRADABLE = "NOT_TRADABLE"
EXCHANGE_NOT_ENABLED = "EXCHANGE_NOT_ENABLED"
SEC_MAPPING_MISSING = "SEC_MAPPING_MISSING"
SAMPLE_MAX_SYMBOLS_LIMIT = "SAMPLE_MAX_SYMBOLS_LIMIT"
PRICE_MISSING = "PRICE_MISSING"
PRICE_BELOW_MIN = "PRICE_BELOW_MIN"
DOLLAR_VOLUME_MISSING = "DOLLAR_VOLUME_MISSING"
DOLLAR_VOLUME_BELOW_MIN = "DOLLAR_VOLUME_BELOW_MIN"


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _base_exclusion(
    symbol: str,
    *,
    stage: str,
    reason_code: str,
    asset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if asset is None:
        asset = {}
    return {
        "symbol": _symbol(symbol),
        "status": "excluded",
        "exclusion_stage": stage,
        "reason_code": reason_code,
        "asset_status": asset.get("status"),
        "tradable": asset.get("tradable"),
        "exchange": asset.get("exchange"),
        "price": None,
        "dollar_volume": None,
        "market_data_feed": None,
        "min_price": None,
        "min_dollar_volume": None,
        "watchlist_bucket": None,
        "watchlist_etf_count": None,
        "watchlist_etfs": None,
    }


def classify_asset_mapping_universe(
    *,
    discovery_symbols: Iterable[str],
    assets: Sequence[Mapping[str, Any]],
    sec_mapping: pd.DataFrame,
    enabled_exchanges: Sequence[str] | None,
) -> tuple[set[str], list[dict[str, Any]]]:
    """Return symbols eligible for snapshots plus one exclusion per rejected symbol.

    The assets input is expected to come from Alpaca's active US-equity endpoint.
    A discovery symbol absent from it is recorded as ACTIVE_ASSET_MISSING rather
    than guessed to be inactive or delisted.
    """
    discovery = {_symbol(value) for value in discovery_symbols if _symbol(value)}
    assets_by_symbol: dict[str, Mapping[str, Any]] = {}
    for asset in assets:
        sym = _symbol(asset.get("symbol"))
        if sym and sym not in assets_by_symbol:
            assets_by_symbol[sym] = asset

    mapping_symbols: set[str] = set()
    if not sec_mapping.empty and "symbol" in sec_mapping.columns:
        mapping_symbols = {
            _symbol(value)
            for value in sec_mapping["symbol"].dropna().tolist()
            if _symbol(value)
        }

    exchange_allow = {
        str(value)
        for value in (enabled_exchanges or ())
        if str(value)
    }

    eligible: set[str] = set()
    exclusions: list[dict[str, Any]] = []
    for sym in sorted(discovery):
        asset = assets_by_symbol.get(sym)
        if asset is None:
            exclusions.append(
                _base_exclusion(
                    sym,
                    stage=ASSET_STAGE,
                    reason_code=ACTIVE_ASSET_MISSING,
                )
            )
            continue
        if asset.get("tradable") is not True:
            exclusions.append(
                _base_exclusion(
                    sym,
                    stage=ASSET_STAGE,
                    reason_code=NOT_TRADABLE,
                    asset=asset,
                )
            )
            continue
        exchange = str(asset.get("exchange") or "")
        if exchange_allow and exchange not in exchange_allow:
            exclusions.append(
                _base_exclusion(
                    sym,
                    stage=ASSET_STAGE,
                    reason_code=EXCHANGE_NOT_ENABLED,
                    asset=asset,
                )
            )
            continue
        if sym not in mapping_symbols:
            exclusions.append(
                _base_exclusion(
                    sym,
                    stage=SEC_MAPPING_STAGE,
                    reason_code=SEC_MAPPING_MISSING,
                    asset=asset,
                )
            )
            continue
        eligible.add(sym)

    return eligible, exclusions


def sample_limit_exclusions(
    *,
    all_mapped: pd.DataFrame,
    selected: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Record symbols omitted only because a non-formal max_symbols sample was used."""
    if all_mapped.empty:
        return []
    selected_symbols = {
        _symbol(value) for value in selected.get("symbol", pd.Series(dtype=str)).tolist()
    }
    exclusions: list[dict[str, Any]] = []
    for _, row in all_mapped.iterrows():
        sym = _symbol(row.get("symbol"))
        if not sym or sym in selected_symbols:
            continue
        item = _base_exclusion(
            sym,
            stage=SAMPLE_STAGE,
            reason_code=SAMPLE_MAX_SYMBOLS_LIMIT,
            asset=row,
        )
        item["price"] = _number(row.get("price"))
        item["dollar_volume"] = _number(row.get("dollar_volume"))
        exclusions.append(item)
    return exclusions


def apply_price_liquidity_prefilter(
    frame: pd.DataFrame,
    *,
    min_price: float,
    min_dollar_volume: float,
    market_data_feed: str | None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply the existing prefilter and make every rejection explicit."""
    if frame.empty:
        return frame.copy(), []

    keep: list[bool] = []
    exclusions: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        sym = _symbol(row.get("symbol"))
        price = _number(row.get("price"))
        dollar_volume = _number(row.get("dollar_volume"))
        reason: str | None = None
        if price is None:
            reason = PRICE_MISSING
        elif price < float(min_price):
            reason = PRICE_BELOW_MIN
        elif dollar_volume is None:
            reason = DOLLAR_VOLUME_MISSING
        elif dollar_volume < float(min_dollar_volume):
            reason = DOLLAR_VOLUME_BELOW_MIN

        keep.append(reason is None)
        if reason is None:
            continue
        item = _base_exclusion(
            sym,
            stage=PRICE_LIQUIDITY_STAGE,
            reason_code=reason,
            asset=row,
        )
        item.update(
            {
                "price": price,
                "dollar_volume": dollar_volume,
                "market_data_feed": str(market_data_feed) if market_data_feed else None,
                "min_price": float(min_price),
                "min_dollar_volume": float(min_dollar_volume),
            }
        )
        exclusions.append(item)

    return frame.loc[keep].copy(), exclusions


def attach_watchlist_provenance(
    exclusions: Iterable[Mapping[str, Any]],
    watchlist_scores: pd.DataFrame,
) -> list[dict[str, Any]]:
    by_symbol: dict[str, Mapping[str, Any]] = {}
    if not watchlist_scores.empty and "symbol" in watchlist_scores.columns:
        for _, row in watchlist_scores.iterrows():
            sym = _symbol(row.get("symbol"))
            if sym:
                by_symbol[sym] = row

    out: list[dict[str, Any]] = []
    for raw in exclusions:
        item = dict(raw)
        sym = _symbol(item.get("symbol"))
        source = by_symbol.get(sym)
        if source is not None:
            item["watchlist_bucket"] = str(source.get("watchlist_bucket") or "")
            count = _number(source.get("watchlist_etf_count"))
            item["watchlist_etf_count"] = int(count) if count is not None else 0
            item["watchlist_etfs"] = str(source.get("watchlist_etfs") or "")
        out.append(item)
    return sorted(out, key=lambda row: str(row.get("symbol") or ""))


def build_candidate_universe_summary(
    *,
    discovery_symbols: Iterable[str],
    decision_symbols: Iterable[str],
    exclusions: Sequence[Mapping[str, Any]],
    tradable_mapped_symbols: int,
    post_sample_symbols: int,
    market_data_feed: str | None,
    min_price: float,
    min_dollar_volume: float,
) -> dict[str, Any]:
    discovery = {_symbol(value) for value in discovery_symbols if _symbol(value)}
    decisions = {_symbol(value) for value in decision_symbols if _symbol(value)}
    excluded_symbols = [_symbol(item.get("symbol")) for item in exclusions]
    if any(not symbol for symbol in excluded_symbols):
        raise ValueError("candidate-universe exclusion contains an empty symbol")
    if len(excluded_symbols) != len(set(excluded_symbols)):
        raise ValueError("candidate-universe exclusions contain duplicate symbols")
    excluded_set = set(excluded_symbols)
    overlap = decisions.intersection(excluded_set)
    if overlap:
        raise ValueError(f"decision/exclusion overlap: {sorted(overlap)}")
    accounted = decisions.union(excluded_set)
    if accounted != discovery:
        missing = sorted(discovery - accounted)
        extra = sorted(accounted - discovery)
        raise ValueError(
            "candidate-universe conservation failed: "
            f"missing={missing[:10]} extra={extra[:10]}"
        )

    reason_counts = Counter(str(item.get("reason_code") or "") for item in exclusions)
    stage_counts = Counter(str(item.get("exclusion_stage") or "") for item in exclusions)
    return {
        "contract_version": CANDIDATE_UNIVERSE_CONTRACT_VERSION,
        "discovery_unique_symbols": len(discovery),
        "tradable_mapped_symbols": int(tradable_mapped_symbols),
        "post_sample_symbols": int(post_sample_symbols),
        "decision_universe_symbols": len(decisions),
        "excluded_symbols": len(exclusions),
        "exclusion_stage_counts": dict(sorted(stage_counts.items())),
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "market_data_feed": str(market_data_feed) if market_data_feed else None,
        "min_price": float(min_price),
        "min_dollar_volume": float(min_dollar_volume),
    }
