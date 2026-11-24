"""Point-in-time IEX observations shared by the monitor and ranking preview."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Any

from requests import RequestException

from .decision.entry import build_entry_quality_v2
from .decision.model import EntryDecision
from .market_calendar import NYSE_TZ, is_session_day, latest_completed_session, session_close_utc, session_open_utc
from .scanner import apply_split_adjustment, price_dimension_from_bars

INTRADAY_DATA_VERSION = "iex_observation_v2"
SPLIT_PROCESS_DATE_LOOKAHEAD_DAYS = 30


@dataclass(frozen=True)
class IntradayPolicy:
    max_age_seconds: int = 180
    max_skew_seconds: int = 120

    def __post_init__(self):
        if self.max_age_seconds <= 0 or self.max_skew_seconds <= 0:
            raise ValueError("intraday quote age and skew limits must be positive")


@dataclass(frozen=True)
class IntradayQuote:
    price: float
    source: str
    session: date
    timestamp: datetime | None
    interval_end: datetime | None
    received_at: datetime
    feed: str = "iex"
    price_basis: str = "raw_quote_session"


@dataclass(frozen=True)
class IntradayObservation:
    quote: IntradayQuote | None
    quote_status: str
    asof: datetime
    completed_bars: list[dict]
    provisional_bars: list[dict]
    history_issue: str | None = None

    @property
    def issue(self) -> str | None:
        return self.quote_status if self.quote_status != "fresh" else self.history_issue


@dataclass(frozen=True)
class IntradayBenchmark:
    observation: IntradayObservation
    return_60d: float | None
    trend_ok: bool | None


def positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) and number > 0 else None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.utcoffset() is not None else None


def _daily_session(bar: dict) -> date | None:
    timestamp = _timestamp(bar.get("t"))
    if timestamp is None:
        return None
    session = timestamp.astimezone(NYSE_TZ).date()
    return session if is_session_day(session) else None


def _component(snapshot: dict, name: str) -> dict:
    item = snapshot.get(name)
    return item if isinstance(item, dict) else {}


def market_period(now: datetime) -> str:
    today = now.astimezone(NYSE_TZ).date()
    if not is_session_day(today):
        return "market_closed"
    if now < session_open_utc(today):
        return "pre_market"
    if now >= session_close_utc(today):
        return "post_market"
    return "regular"


def select_quote(
    snapshot: dict, *, received_at: datetime, now: datetime, policy: IntradayPolicy
) -> tuple[IntradayQuote | None, str]:
    """Select a price and its own timestamp. Daily stamps identify a session."""
    if received_at.utcoffset() is None or now.utcoffset() is None or received_at > now:
        raise ValueError("intraday observation requires ordered timezone-aware clocks")
    today = now.astimezone(NYSE_TZ).date()
    period = market_period(now)
    candidates = []
    future = False
    missing_time = False
    for source, key in (("latestTrade", "p"), ("minuteBar", "c")):
        item = _component(snapshot, source)
        price = positive(item.get(key))
        if price is None:
            continue
        stamp = _timestamp(item.get("t"))
        if stamp is None:
            missing_time = True
            continue
        session = stamp.astimezone(NYSE_TZ).date()
        end = stamp + timedelta(minutes=1) if source == "minuteBar" else stamp
        if end > received_at:
            future = True
            continue
        if is_session_day(session) and session_open_utc(session) <= stamp < session_close_utc(session):
            candidates.append(IntradayQuote(price, source, session, stamp, end, received_at))

    if candidates:
        eligible = [
            item for item in candidates
            if item.session == today and (now - item.timestamp).total_seconds() <= policy.max_age_seconds
        ] if period == "regular" else []
        quote = max(eligible or candidates, key=lambda item: (item.interval_end, item.source == "latestTrade"))
        if period != "regular":
            return quote, period
        if quote.session != today:
            return quote, "prior_session_quote"
        if (now - quote.timestamp).total_seconds() > policy.max_age_seconds:
            return quote, "stale_quote"
        return quote, "fresh"

    daily = _component(snapshot, "dailyBar")
    session = _daily_session(daily)
    price = positive(daily.get("c"))
    if price is not None and session is not None and session_open_utc(session) <= received_at:
        quote = IntradayQuote(price, "dailyBar", session, None, None, received_at)
        return quote, "daily_price_without_tick_time" if period == "regular" else period
    if future:
        return None, "future_quote"
    if missing_time:
        return None, "missing_quote_timestamp"
    return None, "no_regular_session_price" if period == "regular" else period


def _completed_bars(bars: list[dict], previous: date) -> list[dict]:
    # Existing split and feature functions use the date component of `t`.
    # Normalize to the NYSE session before using those functions.
    by_session: dict[date, dict] = {}
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        if (session := _daily_session(bar)) is not None and session <= previous:
            normalized = {**bar, "t": session.isoformat()}
            existing = by_session.setdefault(session, normalized)
            if existing != normalized:
                # Preserve the ambiguous slot as missing.
                by_session[session] = {"t": normalized["t"]}
    return [by_session[session] for session in sorted(by_session)]


def prepare_observation(
    snapshot: dict | None,
    bars: list[dict] | None,
    splits: list[tuple[str, float | None]] | None,
    *,
    received_at: datetime,
    now: datetime,
    policy: IntradayPolicy,
) -> IntradayObservation:
    snapshot = snapshot or {}
    quote, status = select_quote(snapshot, received_at=received_at, now=now, policy=policy)
    if status != "fresh" or quote is None:
        return IntradayObservation(quote, status, now, [], [])
    if splits is None:
        return IntradayObservation(quote, status, now, [], [], "split_data_unavailable")

    events: dict[date, float] = {}
    for ex_date, factor in splits:
        try:
            day = date.fromisoformat(ex_date)
        except (TypeError, ValueError):
            return IntradayObservation(quote, status, now, [], [], "invalid_split_event")
        if day > quote.session:
            continue
        value = positive(factor)
        if value is None or events.setdefault(day, value) != value:
            return IntradayObservation(quote, status, now, [], [], "invalid_split_event")
    previous = latest_completed_session(session_open_utc(quote.session))
    history = _completed_bars(bars or [], previous)
    prior_bar = _component(snapshot, "prevDailyBar")
    if (
        (not history or history[-1]["t"] != previous.isoformat())
        and _daily_session(prior_bar) == previous
    ):
        history.append({**prior_bar, "t": previous.isoformat()})
    completed = apply_split_adjustment(history, [(day.isoformat(), ratio) for day, ratio in events.items()])
    if (
        not completed or completed[-1]["t"] != previous.isoformat()
        or positive(completed[-1].get("c")) is None
    ):
        return IntradayObservation(quote, status, now, [], [], "previous_session_bar_missing")

    daily = _component(snapshot, "dailyBar")
    high, low = positive(daily.get("h")), positive(daily.get("l"))
    if _daily_session(daily) != quote.session or high is None or low is None or high < low:
        return IntradayObservation(quote, status, now, completed, [], "current_session_bar_missing")
    provisional = {
        **daily, "t": quote.session.isoformat(), "c": quote.price, "provisional": True,
        "h": max(high, quote.price), "l": min(low, quote.price),
    }
    return IntradayObservation(quote, status, now, completed, [*completed, provisional])


def fetch_observations(client, symbols: list[str], chunk_size: int, lookback_days: int,
                       policy: IntradayPolicy) -> dict[str, IntradayObservation]:
    symbols = list(dict.fromkeys(symbols))
    if chunk_size <= 0:
        raise ValueError("snapshot batch size must be positive")
    if not symbols:
        return {}
    batches = [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]
    snapshots: dict[str, dict] = {}
    receipt_times: dict[str, datetime] = {}
    for batch in batches:
        snapshots.update(client.get_snapshots(batch, chunk_size))
        received_at = datetime.now(timezone.utc)
        receipt_times.update(dict.fromkeys(batch, received_at))
    day = received_at.astimezone(NYSE_TZ).date()
    start = (day - timedelta(days=lookback_days)).isoformat()
    bars = client.get_daily_bars(symbols, start, chunk_size)
    splits: dict[str, list[tuple[str, float | None]] | None] = {}
    # Alpaca filters by process date. The local adjustment still uses ex-date.
    end = (day + timedelta(days=SPLIT_PROCESS_DATE_LOOKAHEAD_DAYS)).isoformat()
    for batch in batches:
        try:
            invalid_events: dict[str, list[str]] = {}
            portion = client.get_corporate_action_splits(batch, start, end, invalid_events=invalid_events)
            splits.update({
                symbol: [*portion.get(symbol, []), *((ex_date, None) for ex_date in invalid_events.get(symbol, []))]
                for symbol in batch
            })
        except (OSError, RequestException, RuntimeError, ValueError):
            splits.update({symbol: None for symbol in batch})
    now = datetime.now(timezone.utc)
    return {
        symbol: prepare_observation(
            snapshots.get(symbol), bars.get(symbol), splits.get(symbol),
            received_at=receipt_times[symbol], now=now, policy=policy,
        )
        for symbol in symbols
    }


def build_benchmark(observation: IntradayObservation, sma_days: int) -> IntradayBenchmark:
    if observation.issue or observation.quote is None:
        return IntradayBenchmark(observation, None, None)
    price = observation.quote.price
    series = observation.provisional_bars
    features = price_dimension_from_bars(price, series)
    window = series[-sma_days:]
    # A complete SMA window ends at the current provisional session.
    expected = observation.quote.session
    closes: list[float] = []
    for bar in reversed(window):
        close = positive(bar.get("c"))
        if bar["t"] != expected.isoformat() or close is None:
            break
        closes.append(close)
        expected = latest_completed_session(session_open_utc(expected))
    trend_ok = price >= sum(closes) / sma_days if len(closes) == sma_days else None
    return IntradayBenchmark(observation, features["return_60d"], trend_ok)


def build_provisional_entry(
    observation: IntradayObservation,
    benchmark: IntradayBenchmark,
    policy: IntradayPolicy,
) -> tuple[EntryDecision | None, str | None]:
    if observation.issue:
        return None, observation.issue
    if benchmark.observation.issue:
        return None, f"qqq_{benchmark.observation.issue}"
    quote, qqq = observation.quote, benchmark.observation.quote
    if quote is None or qqq is None:
        return None, "missing_quote"
    if quote.session != qqq.session:
        return None, "benchmark_session_mismatch"
    if max(quote.interval_end - qqq.timestamp, qqq.interval_end - quote.timestamp).total_seconds() > policy.max_skew_seconds:
        return None, "benchmark_quote_skew"
    if benchmark.return_60d is None or benchmark.trend_ok is None:
        return None, "qqq_history_incomplete"

    features = price_dimension_from_bars(quote.price, observation.provisional_bars)
    stock_ret60 = features["return_60d"]
    if stock_ret60 is None or any(
        features[name] is None
        for name in ("price_to_sma50", "price_to_sma200", "drawdown_from_52w_high")
    ):
        return None, "stock_history_incomplete"
    metrics = {
        **features,
        "market_asof": quote.session.isoformat(),
        "qqq_trailing_return_60d": benchmark.return_60d,
        "relative_strength_60d_qqq": stock_ret60 - benchmark.return_60d,
        "regime": "up" if benchmark.return_60d >= 0 else "down",
        "benchmark_trend_ok": benchmark.trend_ok,
    }
    return build_entry_quality_v2(
        metrics, decision_date=quote.session, market_asof=quote.session,
        runtime_reference_date=quote.session,
    ), None
