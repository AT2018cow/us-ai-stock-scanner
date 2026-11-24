"""Price paths on fixed NYSE endpoints using independently sourced SIP labels."""
from __future__ import annotations

from collections import Counter
from datetime import date
import math

from ai_value_scanner.forward.ledger import utc
from ai_value_scanner.market_calendar import is_session_day, session_close_utc, session_open_utc
from ai_value_scanner.market_data import SIP_PUBLICATION_DELAY
from ai_value_scanner.swing.setups import factor_between, next_session, number, previous_session, split_factors
from .swing_cohorts import sessions

NO_TRADE = {"suspended", "halted_all_session"}
EVENT_STATES = NO_TRADE | {"delisted", "merger", "identity_unverified"}


class PriceBook:
    """Reviewed labels need one explicit continuity interval and actions per security."""

    def __init__(self, evidence: dict, *, forward: bool = False):
        if evidence.get("feed") != "sip" or evidence.get("price_basis") != "raw" or not evidence.get("source"):
            raise ValueError("price labels require a source and raw SIP evidence")
        self.at = utc(evidence["asof_utc"])
        self.source = evidence["source"]
        self.forward = forward
        self.data = {}
        for security, raw in evidence["securities"].items():
            start, end = (date.fromisoformat(raw[key]) for key in ("verified_from", "verified_through"))
            if start > end or not is_session_day(start) or not is_session_day(end) or session_close_utc(end) > self.at:
                raise ValueError(f"{security}: invalid verified price interval")
            if (raw.get("security_id") != security or not raw.get("identity_source")
                or not raw.get("corporate_actions_source") or not all(
                    isinstance(raw.get(key), list) for key in ("splits", "distributions", "bars")
                )):
                raise ValueError(f"{security}: explicit security identity, sources and action lists required")
            splits = split_factors(raw["splits"], through=end)
            if len(raw["splits"]) != len(splits) or any(not start <= day <= end or not is_session_day(day) for day in splits):
                raise ValueError(f"{security}: duplicate or out of range split")
            distributions, bars, events, close_times = {}, {}, {}, {}
            for token, value in raw["distributions"]:
                day = date.fromisoformat(token)
                if not start <= day <= end or not is_session_day(day) or day in distributions:
                    raise ValueError(f"{security}: invalid or duplicate cash distribution")
                distributions[day] = number(value, positive=False)
            for row in raw["bars"]:
                day = date.fromisoformat(row["session"])
                if not start <= day <= end or not is_session_day(day) or day in bars:
                    raise ValueError(f"{security}: invalid or duplicate bar session")
                o, h, l, c = (number(row[key]) for key in ("o", "h", "l", "c"))
                if l > min(o, c) or max(o, c) > h:
                    raise ValueError(f"{security}: inconsistent OHLC")
                bars[day] = o, h, l, c
                if row.get("close_known_at_utc"):
                    observed = utc(row["close_known_at_utc"])
                    if not session_close_utc(day) <= observed <= self.at:
                        raise ValueError(f"{security}: invalid close observation time")
                    close_times[day] = observed
            for token, state in (raw.get("events") or {}).items():
                day = date.fromisoformat(token)
                if not is_session_day(day) or day in bars or not start <= day <= end or state not in EVENT_STATES:
                    raise ValueError(f"{security}: inconsistent price-event evidence")
                events[day] = state
            self.data[security] = {"start": start, "end": end, "bars": bars, "splits": splits,
                                   "distributions": distributions, "events": events, "close_times": close_times}

    def close_time(self, security, day):
        observed = self.data[security]["close_times"].get(day)
        if observed or self.forward:
            return observed
        return session_close_utc(day) + SIP_PUBLICATION_DELAY

    def observation(self, security, day):
        if session_close_utc(day) > self.at:
            return "future_unmatured", None
        data = self.data.get(security)
        if not data or not data["start"] <= day <= data["end"]:
            return "mature_missing", None
        event = data["events"].get(day)
        if event:
            return event, None
        bar = data["bars"].get(day)
        return ("observed", bar) if bar else ("mature_missing", None)

    def factor(self, security, start, end):
        data = self.data.get(security)
        if not data or not data["start"] <= start <= end <= data["end"]:
            return None
        if any(start <= day <= end and state not in NO_TRADE for day, state in data["events"].items()):
            return None
        return factor_between(data["splits"], start, end)

    def cash_distribution(self, security, enter, day):
        amount = self.data[security]["distributions"].get(day, 0.)
        return amount / self.factor(security, enter, day)

    def first_open(self, security, planned, last):
        for day in sessions(planned, last):
            state, bar = self.observation(security, day)
            if state == "observed":
                return "entered", day, bar[0]
            if state not in NO_TRADE:
                return state, day, None
        return "no_executable_open", None, None


def _empty(status, terminal, **data):
    return {"status": status, "terminal_session": terminal.isoformat(), "net_15": None, "net_30": None, **data}


def cash(book, terminal, reason):
    if session_close_utc(terminal) > book.at:
        return _empty("future_unmatured", terminal, reason=reason)
    return _empty("cash", terminal, reason=reason, gross=0.) | {"net_15": 0., "net_30": 0.}


def settle(book: PriceBook, security: str, planned: date, terminal: date, *, signal: date | None = None,
           locked: float | None = None, exit_on_break: bool = False, avoid_invalidated: bool = False,
           open_deadline: date | None = None, fixed_horizon: int | None = None) -> dict:
    """Simulate a single preregistered path. Any unresolved gap stays unknown."""
    open_deadline = min(terminal, open_deadline or terminal)
    if fixed_horizon is None and session_close_utc(terminal) > book.at:
        return _empty("future_unmatured", terminal, planned_open=planned.isoformat())
    if planned > open_deadline:
        return cash(book, terminal, "cannot_enter_within_window")
    status, enter, entry_price = book.first_open(security, planned, open_deadline)
    if status == "no_executable_open":
        return cash(book, terminal, status) | {"planned_open": planned.isoformat()}
    if status != "entered":
        return _empty(status, terminal, planned_open=planned.isoformat())
    if fixed_horizon is not None:
        from .swing_cohorts import day_shift
        terminal = day_shift(enter, fixed_horizon - 1)
    if locked is not None:
        if signal is None or book.factor(security, signal, enter) is None:
            return _empty("action_basis_unknown", terminal, planned_open=planned.isoformat())
        if avoid_invalidated:
            # This is a pre-open plan. Reading the entry print to veto the plan
            # would also rule out using that same print as the fill proxy.
            for day in sessions(next_session(signal), previous_session(enter)):
                state, bar = book.observation(security, day)
                if state in NO_TRADE:
                    continue
                if state != "observed":
                    return _empty(state, terminal, planned_open=planned.isoformat())
                visible = book.close_time(security, day)
                if visible is None:
                    return _empty("close_timestamp_unknown", terminal, planned_open=planned.isoformat())
                if visible < session_open_utc(enter) and bar[3] < locked * book.factor(security, signal, day):
                    return cash(book, terminal, "invalidation_known_before_open")
    entry = {"planned_open": planned.isoformat(), "entry_session": enter.isoformat(),
             "entry_time_utc": session_open_utc(enter).isoformat(),
             "price_denominator": entry_price, "shares_at_entry": 1}
    if session_close_utc(terminal) > book.at:
        return _empty("future_unmatured", terminal, **entry)
    low = high = entry_price
    dividend, trigger, trigger_at, closing, reason = 0., None, None, None, None
    trade_days = 0
    untraded = Counter()
    for day in sessions(enter, terminal):
        state, bar = book.observation(security, day)
        if state not in NO_TRADE and state != "observed":
            return _empty(state, terminal, **entry)
        if day > enter:
            dividend += book.cash_distribution(security, enter, day)
        if state in NO_TRADE:
            untraded[state] += 1
            continue
        trade_days += 1
        basis = book.factor(security, enter, day)
        o, h, l, c = (value / basis for value in bar)
        if trigger_at and trigger_at < session_open_utc(day) and exit_on_break:
            closing, reason = o, "structure_next_open"
            low, high = min(low, o), max(high, o)
            break
        low, high = min(low, l), max(high, h)
        if day == terminal:
            closing, reason = c, "fixed_horizon_close"
        elif locked is not None and bar[3] < locked * book.factor(security, signal, day):
            observed = book.close_time(security, day)
            if observed is None and exit_on_break:
                return _empty("close_timestamp_unknown", terminal, **entry)
            if observed and (trigger_at is None or observed < trigger_at):
                trigger, trigger_at = day, observed
    if closing is None:
        return _empty("terminal_close_unavailable", terminal, no_trade=dict(untraded), **entry)
    gross = (closing + dividend) / entry_price - 1
    num = {"gross": gross, "mfe": high / entry_price - 1, "mae": low / entry_price - 1}
    if not all(math.isfinite(value) for value in num.values()):
        return _empty("nonfinite_path", terminal, **entry)
    where = session_open_utc if reason == "structure_next_open" else session_close_utc
    return {"status": "settled", "terminal_session": terminal.isoformat(), **entry,
            "exit_session": day.isoformat(), "exit_time_utc": where(day).isoformat(), "reason": reason,
            "close_signal_session": trigger.isoformat() if trigger else None,
            "close_signal_observed_at_utc": trigger_at.isoformat() if trigger_at else None,
            "holding_sessions": len(sessions(enter, day)), "traded_sessions": trade_days,
            "no_trade": dict(untraded),
            "exit_price_entry_share_basis": closing, "cash_distributions_entry_share_basis": dividend, **num,
            **{f"net_{bps}": gross - 2 * bps / 10_000 for bps in (15, 30)},
            "costs_by_side": {str(bps): {"entry": entry_price * bps / 10_000, "exit": entry_price * bps / 10_000}
                              for bps in (15, 30)}}


def false_breakout(book, security, signal, through, anchor):
    for day in sessions(next_session(signal), through):
        state, bar = book.observation(security, day)
        if state in NO_TRADE:
            continue
        basis = book.factor(security, signal, day)
        if state != "observed" or basis is None:
            return {"status": state if state != "observed" else "action_basis_unknown"}
        if bar[3] < anchor * basis:
            return {"status": "breached", "session": day.isoformat()}
    return {"status": "not_breached"}


def barrier_order(book, security, signal, entered, terminal, lower, upper):
    """Diagnostic first-touch paths on OHLC, not an executable exit rule."""
    if not lower < upper:
        return {"status": "invalid_barriers"}
    for day in sessions(entered, terminal):
        state, bar = book.observation(security, day)
        if state in NO_TRADE:
            continue
        factor = book.factor(security, signal, day)
        if state != "observed" or factor is None:
            return {"status": state if state != "observed" else "action_basis_unknown"}
        o, h, l, _ = (p / factor for p in bar)
        shared = {"session": day.isoformat(), "basis": "signal_session_shares"}
        if o <= lower or o >= upper:
            return {**shared, "status": "lower_first" if o <= lower else "upper_first",
                    "conservative": o, "optimistic": o, "seen_at": "open"}
        if l <= lower and h >= upper:
            return {**shared, "status": "same_bar_order_unknown", "conservative": lower, "optimistic": upper}
        if l <= lower or h >= upper:
            px = lower if l <= lower else upper
            return {**shared, "status": "lower_first" if l <= lower else "upper_first",
                    "conservative": px, "optimistic": px}
    return {"status": "neither_touched"}
