from __future__ import annotations

import math
from typing import Sequence
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from ai_value_scanner.market_calendar import is_session_day
from ai_value_scanner.fundamentals.accounting import finite_number


PRICE_FEATURE_VERSION = "price_features_2026-11-06"


@lru_cache(maxsize=4096)
def _expected_sessions(start: date, end: date) -> frozenset[date]:
    return frozenset(start + timedelta(days=i) for i in range((end-start).days+1)
                     if is_session_day(start + timedelta(days=i)))


def _missing_sessions(tokens: Sequence[object]) -> int | None:
    try:
        days = [pd.Timestamp(token).date() for token in tokens]
        if any(pd.isna(day) for day in days) or days != sorted(set(days)):
            return None
        return len(_expected_sessions(days[0], days[-1]) - set(days)) if days else None
    except (ValueError, TypeError):
        return None


PRICE_HISTORY_FEATURE_KEYS = (
    "drawdown_from_52w_high",
    "range_position_52w",
    "price_to_sma50",
    "price_to_sma200",
    "days_below_sma200",
    "return_20d",
    "return_60d",
    "volatility_60d",
    "avg_dollar_volume_20d",
    "volatility_60d_observations",
    "price_history_missing_sessions",
)


def empty_price_history_features() -> dict[str, float | int | None]:
    return {key: None for key in PRICE_HISTORY_FEATURE_KEYS}


def compute_price_history_features(
    *,
    current_price: float | None,
    range_highs: Sequence[float],
    range_lows: Sequence[float],
    closes: Sequence[float],
    dollar_volumes: Sequence[float],
    sma_window: int = 200,
    session_dates: Sequence[object] | None = None,
) -> dict[str, float | int | None]:
    """Compute canonical trailing price/range/momentum/liquidity features.

    Input adaptation is intentionally outside this function:
    - scanner may use a current snapshot price with already-fetched daily bars;
    - historical replay uses the last close visible at its explicit asof;
    - callers decide which bars belong to the range/drawdown lookback window.

    SMA ratios are only defined with complete windows. Calling a shorter
    average SMA50/SMA200 creates a different signal for recently listed names
    and is not considered a valid fallback.
    """
    price = finite_number(current_price)
    if price is None or price <= 0:
        return empty_price_history_features()

    # Preserve slots: dropping a bad observation silently changes every horizon.
    close_values = [finite_number(value) for value in closes]
    highs = [finite_number(value) for value in range_highs]
    lows = [finite_number(value) for value in range_lows]
    dollar_volume_values = [finite_number(value) for value in dollar_volumes]

    def complete(values: list, n: int, *, positive: bool = True) -> bool:
        if len(values) < n:
            return False
        if any(v is None or (v <= 0 if positive else v < 0) for v in values[-n:]):
            return False
        if session_dates is not None:
            if len(session_dates) != len(close_values) or len(session_dates) < n:
                return False
            if _missing_sessions(session_dates[-n:]) != 0:
                return False
        return True

    drawdown = range_pos = None
    if highs and lows and all(v is not None and v > 0 for v in highs + lows):
        high_52w, low_52w = max(highs), min(lows)
        drawdown = 1.0 - price / high_52w
        if high_52w > low_52w:
            range_pos = (price - low_52w) / (high_52w - low_52w)

    price_to_sma50 = None
    if complete(close_values, 50):
        price_to_sma50 = price / float(np.mean(close_values[-50:]))

    price_to_sma200 = days_below_sma200 = None
    required_sma = max(1, int(sma_window))
    if complete(close_values, required_sma):
        price_to_sma200 = price / float(np.mean(close_values[-required_sma:]))
        series = pd.Series(close_values, dtype="float64")
        sma_roll = series.rolling(window=required_sma, min_periods=required_sma).mean()
        trailing = 0
        for i in range(len(series)-1, -1, -1):
            if not np.isfinite(sma_roll.iloc[i]) or series.iloc[i] >= sma_roll.iloc[i]:
                break
            trailing += 1
        days_below_sma200 = trailing

    return_20d = price / close_values[-21] - 1.0 if complete(close_values, 21) else None
    return_60d = price / close_values[-61] - 1.0 if complete(close_values, 61) else None

    volatility_60d = None
    observations = 0
    if len(close_values) >= 61:
        observations = sum(a is not None and b is not None and a > 0 and b > 0
                           for a, b in zip(close_values[-61:-1], close_values[-60:]))
    if complete(close_values, 61):
        window = np.asarray(close_values[-61:], dtype="float64")
        vol = float(np.std(window[1:] / window[:-1] - 1.0, ddof=0) * math.sqrt(252.0))
        if np.isfinite(vol):
            volatility_60d = vol

    avg_dollar_volume_20d = None
    if complete(dollar_volume_values, 20, positive=False):
        avg_dollar_volume_20d = float(np.mean(dollar_volume_values[-20:]))

    return {
        "volatility_60d_observations": observations,
        "price_history_missing_sessions": (
            _missing_sessions(session_dates[-max(61, required_sma):])
            if session_dates is not None else None
        ),
        "drawdown_from_52w_high": (
            round(drawdown, 6) if drawdown is not None else None
        ),
        "range_position_52w": (
            round(range_pos, 6) if range_pos is not None else None
        ),
        "price_to_sma50": (
            round(price_to_sma50, 6) if price_to_sma50 is not None else None
        ),
        "price_to_sma200": (
            round(price_to_sma200, 6) if price_to_sma200 is not None else None
        ),
        "days_below_sma200": (
            int(days_below_sma200) if days_below_sma200 is not None else None
        ),
        "return_20d": round(return_20d, 6) if return_20d is not None else None,
        "return_60d": round(return_60d, 6) if return_60d is not None else None,
        "volatility_60d": (
            round(volatility_60d, 6) if volatility_60d is not None else None
        ),
        "avg_dollar_volume_20d": (
            round(avg_dollar_volume_20d, 2)
            if avg_dollar_volume_20d is not None
            else None
        ),
    }


def price_history_percentile_from_closes(
    closes: Sequence[float],
    window_observations: int,
    *,
    min_observations: int = 20,
) -> float | None:
    """Return the latest close's percentile within a trailing close history."""
    values = [
        float(value)
        for value in closes
        if np.isfinite(float(value)) and float(value) > 0
    ]
    if len(values) < max(1, int(min_observations)):
        return None
    window = values[-int(max(min_observations, window_observations)) :]
    latest = window[-1]
    arr = np.asarray(window, dtype="float64")
    pct = float(np.mean(arr <= latest))
    if not np.isfinite(pct):
        return None
    return round(pct, 6)
