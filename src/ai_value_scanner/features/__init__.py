"""Shared feature calculations used by scanner and historical replay."""

from .ai_link import (
    ai_etf_consensus_score,
    ai_market_link_score,
    compute_ai_link_score,
)
from .price import (
    compute_price_history_features,
    empty_price_history_features,
    price_history_percentile_from_closes,
)
from .valuation import (
    compute_historical_valuation_percentile,
    lookup_close_on_or_before,
    lookup_value_on_or_before,
    safe_divide,
)

__all__ = [
    "ai_etf_consensus_score",
    "ai_market_link_score",
    "compute_ai_link_score",
    "compute_historical_valuation_percentile",
    "compute_price_history_features",
    "empty_price_history_features",
    "lookup_close_on_or_before",
    "lookup_value_on_or_before",
    "price_history_percentile_from_closes",
    "safe_divide",
]
