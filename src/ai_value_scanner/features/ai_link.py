from __future__ import annotations

from typing import Any

import numpy as np

from ai_value_scanner.fundamentals.accounting import clamp01


def ai_etf_consensus_score(
    watchlist_etf_count: float | int | None,
    etf_count_saturation: int,
) -> float:
    """Scale ETF-consensus count to the configured saturation level."""
    if watchlist_etf_count is None:
        return 0.0
    try:
        count = float(watchlist_etf_count)
    except (TypeError, ValueError):
        return 0.0
    saturation = max(1.0, float(etf_count_saturation))
    return round(clamp01(count / saturation), 6)


def ai_market_link_score(
    symbol_return_20d: float | None,
    symbol_return_60d: float | None,
    benchmark_return_20d: float | None,
    benchmark_return_60d: float | None,
    tol_20d: float,
    tol_60d: float,
) -> float:
    """Score how closely symbol momentum tracks the configured AI benchmark."""
    score_20 = 0.5
    if (
        symbol_return_20d is not None
        and benchmark_return_20d is not None
        and tol_20d > 0
    ):
        score_20 = clamp01(
            1.0 - (abs(symbol_return_20d - benchmark_return_20d) / tol_20d)
        )

    score_60 = 0.5
    if (
        symbol_return_60d is not None
        and benchmark_return_60d is not None
        and tol_60d > 0
    ):
        score_60 = clamp01(
            1.0 - (abs(symbol_return_60d - benchmark_return_60d) / tol_60d)
        )

    return round(clamp01(0.4 * score_20 + 0.6 * score_60), 6)


def compute_ai_link_score(
    config: Any,
    ai_etf_score: float | None,
    ai_disclosure_score: float | None,
    ai_market_score: float | None,
    ai_backlog_signal: float | None,
) -> float:
    """Compose AI-link components with config weights without renormalization.

    Theme configs intentionally may sum to less than 1.0 (for example when
    disclosure is disabled), so the historical calibrated scale is preserved.
    Missing components contribute zero and the final score is clipped to [0,1].
    """
    return float(
        np.clip(
            float(config.ai_link_weight_etf_consensus) * float(ai_etf_score or 0.0)
            + float(config.ai_link_weight_disclosure)
            * float(ai_disclosure_score or 0.0)
            + float(config.ai_link_weight_market_link) * float(ai_market_score or 0.0)
            + float(config.ai_link_weight_backlog) * float(ai_backlog_signal or 0.0),
            0.0,
            1.0,
        )
    )
