from __future__ import annotations

import numpy as np
import pandas as pd


def lookup_value_on_or_before(
    points: list[tuple[pd.Timestamp, float]],
    target_ts: pd.Timestamp,
) -> float | None:
    """Return the latest point whose timestamp is not after target_ts."""
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
    """Return the latest close on/before target_ts within an optional gap."""
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
    """Percentile of the current valuation multiple versus own history."""
    if (
        current_multiple is None
        or not np.isfinite(current_multiple)
        or current_multiple <= 0
    ):
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


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Vectorized numeric division with NaN for invalid/zero denominators."""
    num = pd.to_numeric(numerator, errors="coerce").astype(float)
    den = pd.to_numeric(denominator, errors="coerce").astype(float)
    out = pd.Series(np.nan, index=num.index, dtype=float)
    valid = den.notna() & (den != 0) & num.notna()
    out.loc[valid] = num.loc[valid] / den.loc[valid]
    return out
