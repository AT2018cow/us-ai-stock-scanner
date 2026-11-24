"""Review a frozen close plan against separately identified opening observations."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Mapping

from ai_value_scanner.market_calendar import NYSE_TZ, session_close_utc, session_open_utc
from .events import timestamp
from .setups import SWING_REVIEW_VERSION, factor_between, next_session, number, price_space, split_factors


def _quote(row: Mapping, *, day: date, asof: datetime, max_age_seconds: int) -> tuple[dict | None, str | None]:
    if row.get("kind") == "daily_bar":
        return None, "daily_bar_has_no_executable_timestamp"
    try:
        stamp = timestamp(row["timestamp"])
        received = timestamp(row["received_at"])
        kind = row["kind"]
        price = number(row["price"])
        source, feed = row["source"], row["feed"]
    except (KeyError, ValueError, TypeError, AttributeError):
        return None, "quote_evidence_incomplete"
    if kind not in ("trade", "quote") or not isinstance(source, str) or not source.strip() or feed not in ("sip", "iex"):
        return None, "quote_provenance_unknown"
    local_stamp = stamp.astimezone(NYSE_TZ)
    if local_stamp.date() != day or local_stamp.time() < time(4) or stamp >= session_close_utc(day):
        return None, "quote_outside_review_session"
    if not stamp <= received <= asof:
        return None, "quote_not_yet_observable"
    if (asof - stamp).total_seconds() > max_age_seconds:
        return None, "quote_stale"
    # A premarket observation cannot stand in for an observed regular-session gap.
    if (stamp < session_open_utc(day)) != (asof < session_open_utc(day)):
        return None, "quote_from_other_market_period"
    result = {
        "price": price, "timestamp": stamp.isoformat(), "received_at": received.isoformat(),
        "kind": kind, "source": source, "feed": feed,
        "phase": "pre_open_indication" if stamp < session_open_utc(day) else "regular_observation",
        "spread_bps": None,
    }
    try:
        bid, ask = number(row["bid"]), number(row["ask"])
        if timestamp(row["bid_at"]) == timestamp(row["ask_at"]) == stamp and bid <= ask:
            result["spread_bps"] = (ask - bid) / (bid / 2 + ask / 2) * 10_000
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    return result, None


def _actual_open(row: Mapping | None, day: date, asof: datetime) -> dict | None:
    if not row or row.get("feed") != "sip" or not row.get("source"):
        return None
    try:
        seen = timestamp(row["received_at"])
        if row.get("kind") == "daily_bar":
            if row.get("session") != day.isoformat() or not session_open_utc(day) <= seen <= asof:
                return None
            return {"price": number(row["price"]), "timestamp": None, "received_at": seen.isoformat(),
                    "source": str(row["source"]), "feed": "sip", "kind": "daily_bar_open_field"}
        market_open = timestamp(row["timestamp"])
        kind = row.get("kind")
        open_at = session_open_utc(day)
        if not (
            (kind == "opening_trade" or kind is None and market_open == open_at)
            and row.get("session", day.isoformat()) == day.isoformat()
            and open_at <= market_open < session_close_utc(day)
            and market_open <= seen <= asof
        ):
            return None
        return {"price": number(row["price"]), "timestamp": market_open.isoformat(),
                "received_at": seen.isoformat(), "source": str(row["source"]), "feed": "sip", "kind": "time_stamped_open"}
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def opening_review(
    close: Mapping[str, Any], inputs: Mapping[str, Any], *, asof: datetime, max_age_seconds: int = 180,
) -> dict[str, Any]:
    asof = timestamp(asof)
    original = date.fromisoformat(close["session"])
    if close.get("version") != SWING_REVIEW_VERSION or close.get("market_feed") != "sip":
        raise ValueError("opening review requires a frozen SIP swing review")
    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        raise ValueError("maximum quote age must be positive")
    day = next_session(original)
    if day != asof.astimezone(NYSE_TZ).date():
        raise ValueError("opening review must use the next NYSE session")
    phase = "pre_open" if asof < session_open_utc(day) else "post_open"
    quote, issue = _quote(inputs.get("quote") or {}, day=day, asof=asof, max_age_seconds=max_age_seconds)
    actual = _actual_open(inputs.get("actual_open"), day, asof)
    source = inputs.get("split_source")
    factor = None
    if inputs.get("split_status") == "verified" and isinstance(source, str) and source.strip():
        try:
            checked = timestamp(inputs["split_checked_at"])
            if not session_close_utc(original) <= checked <= asof:
                raise ValueError("split evidence must have been checked by the observation time")
            splits = inputs["splits"]
            if not isinstance(splits, list):
                raise ValueError("explicit split list required")
            factor = factor_between(split_factors(splits, through=day), original, day)
        except (KeyError, ValueError, TypeError, OverflowError):
            pass
    baseline = None if factor is None or close.get("close") is None else number(close["close"] * factor)
    result = {
        "session": day.isoformat(), "source_session": original.isoformat(), "asof": asof.isoformat(),
        "phase": phase, "quote": quote, "quote_issue": issue, "actual_open": actual,
        "split": {"factor": factor, "source": source if factor is not None else None,
                  "checked_at": checked.isoformat() if factor is not None else None,
                  "status": "verified" if factor is not None else "unavailable"},
        "previous_close_on_quote_basis": baseline,
        "quote_gap": quote["price"] / baseline - 1 if quote and baseline else None,
        "actual_open_gap": actual["price"] / baseline - 1 if actual and baseline else None,
        "sip_dollar_volume_20d": close.get("sip_dollar_volume_20d"),
        "paper_entry_price": None, "patterns": {},
    }
    for label, pattern in close["patterns"].items():
        state = pattern["state"]
        if state["status"] != "confirmed":
            continue
        stop = state["stop"]
        resistance = state["resistance"]
        space = None
        if factor is not None and quote is not None:
            space = price_space(quote["price"], stop * factor, resistance["price"] * factor if resistance else None)
        result["patterns"][label] = {
            "confirmed_session": state["confirmed"], "reference_price": state["reference_price"] * factor if factor is not None else None,
            "stop": stop * factor if factor is not None else None,
            "resistance": resistance["price"] * factor if resistance and factor is not None else None,
            "space": space,
            "reason": "split_basis_unavailable" if factor is None else issue,
        }
    return result


def render_opening_cards(cards: Mapping[str, Mapping[str, Any]]) -> str:
    lines = ["# Opening Swing Review", ""]
    for symbol, card in cards.items():
        lines.extend([f"## {symbol}", "", f"- {card['phase']} · as of {card['asof']}"])
        quote = card["quote"]
        if quote:
            lines.append(f"- {quote['feed'].upper()} {quote['kind']} {quote['price']:.2f} · {quote['timestamp']} · {quote['source']}")
            if quote["spread_bps"] is not None:
                lines.append(f"- Same-timestamp bid/ask spread {quote['spread_bps']:.1f} bp")
        else:
            lines.append(f"- Quote unavailable · `{card['quote_issue']}`")
        if (actual := card["actual_open"]) is not None:
            lines.append(f"- SIP actual open {actual['price']:.2f} · {actual['timestamp'] or actual['kind']}")
        for key, label in (("quote_gap", "Quote indicated gap"), ("actual_open_gap", "SIP open gap")):
            if card[key] is not None:
                lines.append(f"- {label} {card[key]:+.2%}")
        if card["sip_dollar_volume_20d"] is not None:
            lines.append(f"- Prior 20-session mean SIP dollar volume ${card['sip_dollar_volume_20d']:,.0f}")
        if card["split"]["status"] != "verified":
            lines.append("- Split basis unavailable")
        for label, item in card["patterns"].items():
            if (space := item["space"]) is None:
                lines.append(f"- {label} · price space unavailable · `{item['reason']}`")
            else:
                upside = "n/a" if space["upside"] is None else f"{space['upside']:.2f}"
                ratio = "n/a" if space["reward_risk"] is None else f"{space['reward_risk']:.2f}"
                lines.append(f"- {label} · P−S {space['risk']:.2f} · R−P {upside} · reward/risk {ratio} · `{space['status']}`")
        lines.extend(["- Paper execution price · unavailable", ""])
    return "\n".join(lines)
