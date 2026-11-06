"""Research context computed once alongside StockDecision, never by renderers."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from ai_value_scanner.fundamentals.accounting import finite_number

REVIEW_CONTEXT_VERSION = 'review_context_2026-11-06'


def _positive_multiple(numerator: Any, denominator: Any) -> float | None:
    numerator, denominator = finite_number(numerator), finite_number(denominator)
    if numerator is None or numerator <= 0 or denominator is None or denominator <= 0:
        return None
    return finite_number(numerator / denominator)


def build_review_context(metrics: Mapping[str, Any]) -> dict[str, str | float | None]:
    out: dict[str, str | float | None] = {'review_context_version': REVIEW_CONTEXT_VERSION}
    market_cap = finite_number(metrics.get('market_cap'))
    gaap = finite_number(metrics.get('net_income'))
    adjusted = finite_number(metrics.get('adjusted_net_income'))
    out['review_valuation_basis'] = 'Current market cap / TTM income; fixed price and shares, no fair-value forecast'
    out['review_earnings_calendar_status'] = 'Unverified: filing age is not a confirmed earnings-release date'
    out['review_gaap_pe'] = _positive_multiple(market_cap, gaap)
    if market_cap is not None and market_cap > 0 and adjusted is not None and adjusted > 0:
        for label, factor in (('lower', .8), ('base', 1.), ('higher', 1.2)):
            out[f'review_adjusted_pe_{label}'] = _positive_multiple(market_cap, adjusted * factor)
    else:
        out['review_valuation_unavailable'] = 'Positive TTM adjusted income and market cap are required'
    return out
