from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd


PRICE_HISTORY_FEATURE_KEYS = (
    "drawdown_from_52w_high",
    "range_position_52w",
    "price_to_sma200",
    "days_below_sma200",
    "return_20d",
    "return_60d",
    "volatility_60d",
    "avg_dollar_volume_20d",
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
) -> dict[str, float | int | None]:
    """Compute canonical trailing price/range/momentum/liquidity features.

    Input adaptation is intentionally outside this function:
    - scanner may use a current snapshot price with already-fetched daily bars;
    - historical replay uses the last close visible at its explicit asof;
    - callers decide which bars belong to the range/drawdown lookback window.

    price_to_sma200 is only defined with a complete SMA window. Calling a
    shorter average SMA200 creates a different signal for recently listed
    names and is not considered a valid fallback.
    """
    if current_price is None or not range_highs or not range_lows:
        return empty_price_history_features()

    price = float(current_price)
    highs = [float(value) for value in range_highs]
    lows = [float(value) for value in range_lows]
    close_values = [float(value) for value in closes]
    dollar_volume_values = [float(value) for value in dollar_volumes]

    high_52w = max(highs)
    low_52w = min(lows)

    drawdown = None
    if high_52w > 0:
        drawdown = 1.0 - (price / high_52w)

    range_pos = None
    if high_52w > low_52w:
        range_pos = (price - low_52w) / (high_52w - low_52w)

    price_to_sma200 = None
    days_below_sma200 = None
    required_sma = max(1, int(sma_window))
    if len(close_values) >= required_sma:
        window = close_values[-required_sma:]
        sma = float(np.mean(np.asarray(window, dtype="float64")))
        if np.isfinite(sma) and sma > 0:
            price_to_sma200 = price / sma

        series = pd.Series(close_values, dtype="float64")
        sma_roll = series.rolling(
            window=required_sma,
            min_periods=required_sma,
        ).mean()
        below = series < sma_roll
        trailing = 0
        for flag in reversed(below.tolist()):
            if pd.isna(flag) or not bool(flag):
                break
            trailing += 1
        days_below_sma200 = trailing

    return_20d = None
    if len(close_values) >= 21 and close_values[-21] > 0:
        return_20d = (price / close_values[-21]) - 1.0

    return_60d = None
    if len(close_values) >= 61 and close_values[-61] > 0:
        return_60d = (price / close_values[-61]) - 1.0

    volatility_60d = None
    if len(close_values) >= 61:
        window_61 = np.asarray(close_values[-61:], dtype="float64")
        daily_ret = (window_61[1:] / window_61[:-1]) - 1.0
        if daily_ret.size > 0:
            vol = float(np.nanstd(daily_ret, ddof=0) * math.sqrt(252.0))
            if np.isfinite(vol):
                volatility_60d = vol

    avg_dollar_volume_20d = None
    if len(dollar_volume_values) >= 20:
        adv20 = float(
            np.mean(np.asarray(dollar_volume_values[-20:], dtype="float64"))
        )
        if np.isfinite(adv20):
            avg_dollar_volume_20d = adv20

    return {
        "drawdown_from_52w_high": (
            round(drawdown, 6) if drawdown is not None else None
        ),
        "range_position_52w": (
            round(range_pos, 6) if range_pos is not None else None
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
