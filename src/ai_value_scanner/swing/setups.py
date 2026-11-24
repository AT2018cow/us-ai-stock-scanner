"""SIP close patterns and price-space calculations shared by scan and replay."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from hashlib import sha256
import json
import math
from statistics import mean, median
from typing import Any, Iterable, Mapping

from ai_value_scanner.market_calendar import is_session_day, latest_completed_session, session_open_utc


SWING_REVIEW_VERSION = "swing_review_v1"
BREAKOUT_VERSION = "breakout_20d_v1"
PULLBACK_VERSION = "pullback_reclaim_v1"
WINDOW = 20
MAX_PLATFORM_WIDTH = .15
MIN_BREAKOUT_VOLUME = 1.5
BREAKOUT_EXPIRY = 20
RECLAIM_WINDOW = 5
RESISTANCE_LOOKBACK = 120


@dataclass(frozen=True)
class Bar:
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Resistance:
    price: float
    formed_session: str
    confirmed_session: str
    source: str = "sip_daily_prior_local_high"


@dataclass(frozen=True)
class Pattern:
    version: str
    status: str
    reason: str
    origin: str | None = None
    confirmed: str | None = None
    ended: str | None = None
    reference_price: float | None = None
    stop: float | None = None
    resistance: Resistance | None = None
    evidence: dict[str, float] | None = None

    @property
    def live(self) -> bool:
        return self.status == "confirmed"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Pattern:
        fields = dict(data)
        if fields.get("resistance") is not None:
            fields["resistance"] = Resistance(**fields["resistance"])
        return cls(**fields)


@lru_cache(maxsize=4096)
def previous_session(day: date) -> date:
    return latest_completed_session(session_open_utc(day))


@lru_cache(maxsize=4096)
def next_session(day: date) -> date:
    day += timedelta(days=1)
    while not is_session_day(day):
        day += timedelta(days=1)
    return day


def number(value: Any, *, positive: bool = True) -> float:
    if isinstance(value, bool):
        raise ValueError("not a market number")
    computed = float(value)
    if not math.isfinite(computed) or computed < 0 or (positive and computed == 0):
        raise ValueError("invalid market number")
    return computed


def split_factors(events: Iterable[tuple[str, float]], *, through: date) -> dict[date, float]:
    factors = {}
    for token, raw in events:
        session = date.fromisoformat(token)
        if session > through:
            continue
        factor = number(raw)
        if session in factors and factors[session] != factor:
            raise ValueError("conflicting split factors")
        factors[session] = factor
    return factors


def factor_between(splits: Mapping[date, float], earlier: date, later: date) -> float:
    return number(math.prod(factor for day, factor in splits.items() if earlier < day <= later))


def _complete_bars(rows: Iterable[Mapping], through: date, splits: Mapping[date, float]) -> list[Bar]:
    sessions: dict[date, Bar | None] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("t", ""))[:10])
        except ValueError:
            continue
        if day > through or not is_session_day(day):
            continue
        try:
            o, h, low, c = (number(row[key]) for key in ("o", "h", "l", "c"))
            v = number(row["v"], positive=False)
            if low > min(o, c) or h < max(o, c):
                raise ValueError("inconsistent OHLC")
            factor = factor_between(splits, day, through)
            bar = Bar(day, *(number(price * factor) for price in (o, h, low, c)), number(v / factor, positive=False))
        except (KeyError, TypeError, ValueError, OverflowError):
            bar = None
        sessions[day] = bar if day not in sessions or sessions[day] == bar else None
    tail = []
    day = through
    while (bar := sessions.get(day)) is not None:
        tail.append(bar)
        day = previous_session(day)
    return list(reversed(tail))


def _resistance(bars: list[Bar], boundary: int, signal: int, reference: float) -> Resistance | None:
    """Use pre-setup highs with two right-hand bars available by the signal."""
    best = None
    first_eligible = max(0, boundary - RESISTANCE_LOOKBACK)
    left = first_eligible
    while left and bars[left - 1].high == bars[left].high:
        left -= 1
    while left < boundary and left + 2 <= signal:
        high = bars[left].high
        right = left
        while right + 1 <= signal and bars[right + 1].high == high:
            right += 1
        if (
            high > reference and left >= 2 and first_eligible <= right < boundary and right + 2 <= signal
            and all(bars[index].high < high for index in (left - 2, left - 1, right + 1, right + 2))
        ):
            candidate = Resistance(high, bars[right].session.isoformat(), bars[right + 2].session.isoformat())
            if best is None or high <= best.price:
                best = candidate
        left = right + 1
    return best


def price_space(price: float, stop: float, resistance: float | None) -> dict[str, Any]:
    price, stop = number(price), number(stop)
    if resistance is not None:
        resistance = number(resistance)
    risk = price - stop
    upside = resistance - price if resistance is not None else None
    status = "available"
    if risk <= 0:
        status = "stop_breached"
    elif upside is None:
        status = "resistance_unknown"
    elif upside <= 0:
        status = "target_passed"
    return {
        "price": price, "stop": stop, "resistance": resistance, "risk": risk, "upside": upside,
        "reward_risk": upside / risk if status == "available" else None, "status": status,
    }


def _elapsed(indices: Mapping[str, int], prior: str | None, index: int) -> int | None:
    earlier = indices.get(prior)
    return index - earlier if earlier is not None else None


def _breakout(bars: list[Bar], index: int, indices: Mapping[str, int], prior: Pattern) -> Pattern:
    today = bars[index]
    day = today.session.isoformat()
    if prior.live:
        age = _elapsed(indices, prior.confirmed, index)
        if today.close < prior.stop:
            return replace(prior, status="invalidated", reason="close_below_breakout_level", ended=day)
        if age is None:
            return replace(prior, status="insufficient", reason="confirmation_continuity_unknown")
        if age >= BREAKOUT_EXPIRY:
            return replace(prior, status="invalidated", reason="breakout_expired", ended=day)
        return prior
    if prior.ended:
        cooldown = _elapsed(indices, prior.ended, index)
        if cooldown is not None and cooldown <= WINDOW:
            return prior

    if index < WINDOW:
        return Pattern(BREAKOUT_VERSION, "insufficient", "requires_twenty_prior_sessions")
    platform = bars[index - WINDOW:index]
    upper = max(bar.high for bar in platform)
    lower = min(bar.low for bar in platform)
    baseline = median(bar.volume for bar in platform)
    if baseline <= 0:
        return Pattern(BREAKOUT_VERSION, "insufficient", "nonpositive_volume_baseline")
    limit = lower * (1 + MAX_PLATFORM_WIDTH)
    # Normalization through split multipliers can round a boundary price by a
    # few representable ticks. Preserve the inclusive decimal-price boundary.
    too_wide = upper - limit > 4 * max(math.ulp(upper), math.ulp(limit))
    width = (upper - lower) / lower
    if not too_wide:
        width = min(width, MAX_PLATFORM_WIDTH)
    ratio = today.volume / baseline
    evidence = {"platform_high": upper, "platform_low": lower, "platform_width": width,
                "prior_volume_median": baseline, "volume_ratio": ratio}
    origin = platform[0].session.isoformat()
    if too_wide or today.close <= upper or ratio < MIN_BREAKOUT_VOLUME:
        reason = (
            "platform_too_wide" if too_wide
            else "close_has_not_broken_out" if today.close <= upper else "volume_confirmation_missing"
        )
        return Pattern(BREAKOUT_VERSION, "watching", reason, origin=origin, evidence=evidence)
    return Pattern(
        BREAKOUT_VERSION, "confirmed", "close_and_volume_confirmed", origin=origin, confirmed=day,
        reference_price=today.close, stop=upper, resistance=_resistance(bars, index - WINDOW, index, today.close),
        evidence=evidence,
    )


def _pullback(bars: list[Bar], index: int, indices: Mapping[str, int], prior: Pattern) -> Pattern:
    today = bars[index]
    day = today.session.isoformat()
    if prior.live:
        if today.close < prior.stop:
            return replace(prior, status="invalidated", reason="close_below_pullback_low", ended=day)
        return prior

    if prior.status == "watching" and prior.stop is not None:
        age = _elapsed(indices, prior.origin, index)
        if today.close < prior.stop:
            return replace(prior, status="invalidated", reason="pullback_low_breached_before_reclaim", ended=day)
        if age is None:
            return replace(prior, status="insufficient", reason="pullback_continuity_unknown")
        if age > RECLAIM_WINDOW:
            return replace(prior, status="invalidated", reason="reclaim_window_expired", ended=day)
        if index < 49:
            return replace(prior, status="insufficient", reason="reclaim_average_unavailable")
        sma50 = mean(bar.close for bar in bars[index - 49:index + 1])
        if today.close > sma50:
            return replace(
                prior, status="confirmed", reason="first_close_back_above_sma50", confirmed=day,
                reference_price=today.close, resistance=_resistance(bars, indices[prior.origin], index, today.close),
                evidence={**prior.evidence, "reclaim_sma50": sma50},
            )
        return prior

    if index < 199:
        return Pattern(PULLBACK_VERSION, "insufficient", "requires_two_hundred_sessions")
    sma50 = mean(bar.close for bar in bars[index - 49:index + 1])
    sma200 = mean(bar.close for bar in bars[index - 199:index + 1])
    baseline = median(bar.volume for bar in bars[index - WINDOW:index])
    if baseline <= 0:
        return Pattern(PULLBACK_VERSION, "insufficient", "nonpositive_volume_baseline")
    data = {"sma50": sma50, "sma200": sma200, "prior_volume_median": baseline,
            "volume_ratio": today.volume / baseline}
    if sma50 >= sma200 and bars[index - 1].close > sma50 >= today.close and today.volume < baseline:
        return Pattern(PULLBACK_VERSION, "watching", "pullback_observed_waiting_reclaim",
                       origin=day, stop=today.low, evidence=data)
    return Pattern(PULLBACK_VERSION, "watching", "no_qualified_pullback", evidence=data)


def _rebase(pattern: Pattern, factor: float) -> Pattern:
    def price(value):
        return number(value * factor) if value is not None else None

    evidence = pattern.evidence
    if evidence and factor != 1:
        prices = {"platform_high", "platform_low", "sma50", "sma200", "reclaim_sma50"}
        evidence = {
            key: price(value) if key in prices else value / factor if key == "prior_volume_median" else value
            for key, value in evidence.items()
        }
    resistance = pattern.resistance
    return replace(pattern, reference_price=price(pattern.reference_price), stop=price(pattern.stop),
                   resistance=replace(resistance, price=price(resistance.price)) if resistance else None, evidence=evidence)


def _weekly(bars: list[Bar]) -> dict[str, Any] | None:
    completed = [bar for bar in bars if next_session(bar.session).isocalendar()[:2] != bar.session.isocalendar()[:2]]
    # A week at the head of the archive may lack its earlier trading days.
    completed = [bar for bar in completed if next_session(
        bar.session - timedelta(days=bar.session.weekday() + 1)
    ) >= bars[0].session]
    if not completed:
        return None
    last = completed[-1]
    return {
        "completed_week_end": last.session.isoformat(),
        "close": last.close,
        "change": last.close / completed[-2].close - 1 if len(completed) >= 2 else None,
    }


def evaluate_close(
    rows: Iterable[Mapping], session: date, *, splits: Iterable[tuple[str, float]] = (),
    prior: Mapping[str, Any] | None = None, issue: str | None = None,
) -> dict[str, Any]:
    """Build the canonical display evidence without changing the stock decision."""
    if not is_session_day(session):
        raise ValueError("a close review requires a NYSE session")
    states = (("breakout", BREAKOUT_VERSION, _breakout), ("pullback", PULLBACK_VERSION, _pullback))
    try:
        factors = split_factors(splits, through=session)
        bars = _complete_bars(rows, session, factors) if issue is None else []
    except (ValueError, TypeError, OverflowError):
        bars = []
        issue = "split_data_invalid"
    evidence = {
        "version": SWING_REVIEW_VERSION, "session": session.isoformat(), "market_feed": "sip",
        "price_basis": "signal_session_shares", "close": None, "sip_dollar_volume_20d": None,
        "weekly": None, "patterns": {},
        "bars_sha256": sha256(json.dumps(
            [[bar.session.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars],
            separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest(),
    }
    indices = {bar.session.isoformat(): index for index, bar in enumerate(bars)}
    previous = previous_session(session)
    seed = (
        bool(bars) and prior is not None and prior.get("version") == SWING_REVIEW_VERSION
        and prior.get("session") == previous.isoformat() and previous.isoformat() in indices
    )
    for key, version, step in states:
        state = Pattern(version, "insufficient", issue or "completed_session_bar_unavailable")
        if bars:
            start = 0
            if seed:
                old = Pattern.from_dict(prior["patterns"][key]["state"])
                if old.status in ("confirmed", "watching", "invalidated"):
                    state = _rebase(old, factor_between(factors, previous, session))
                    start = len(bars) - 1
            for index in range(start, len(bars)):
                state = step(bars, index, indices, state)
            if key == "pullback" and start == 0 and state.reason == "no_qualified_pullback":
                state = replace(state, status="insufficient", reason="pullback_continuity_unknown")
        evidence["patterns"][key] = {
            "state": asdict(state),
            "new_confirmation": state.confirmed == session.isoformat() and state.live,
            "space": price_space(bars[-1].close, state.stop, state.resistance.price if state.resistance else None)
            if state.stop is not None and state.live else None,
        }
    if bars:
        evidence["close"] = bars[-1].close
        if len(bars) >= WINDOW:
            evidence["sip_dollar_volume_20d"] = mean(bar.close * bar.volume for bar in bars[-WINDOW:])
        evidence["weekly"] = _weekly(bars)
    return evidence


def validate_close_context(review: Mapping[str, Any], session: str) -> None:
    if review["version"] != SWING_REVIEW_VERSION or review["session"] != session or review["market_feed"] != "sip":
        raise ValueError("swing review has incompatible version, session or feed")
    for name, version in (("breakout", BREAKOUT_VERSION), ("pullback", PULLBACK_VERSION)):
        item = review["patterns"][name]
        pattern = Pattern.from_dict(item["state"])
        if pattern.version != version or pattern.status not in ("confirmed", "watching", "invalidated", "insufficient"):
            raise ValueError("invalid swing pattern state or version")
        last = None
        for token in (pattern.origin, pattern.confirmed, pattern.ended):
            if token is None:
                continue
            day = date.fromisoformat(token)
            if not is_session_day(day) or token > session or (last is not None and token < last):
                raise ValueError("inconsistent swing pattern dates")
            last = token
        if pattern.resistance is not None and (
            not pattern.origin or not pattern.confirmed
            or pattern.resistance.formed_session >= pattern.origin
            or pattern.resistance.confirmed_session > pattern.confirmed
            or pattern.resistance.formed_session >= pattern.resistance.confirmed_session
        ):
            raise ValueError("resistance was not available at setup confirmation")
        expected_space = None
        if pattern.live:
            if pattern.confirmed is None or pattern.stop is None or pattern.reference_price is None:
                raise ValueError("confirmed swing pattern is missing reference evidence")
            expected_space = price_space(
                review["close"], pattern.stop, pattern.resistance.price if pattern.resistance else None,
            )
        if item["space"] != expected_space or item["new_confirmation"] != (pattern.live and pattern.confirmed == session):
            raise ValueError("swing pattern does not match its frozen price evidence")
