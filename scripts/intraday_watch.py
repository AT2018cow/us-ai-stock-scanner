#!/usr/bin/env python3
"""Intraday watch monitor for the latest production decision snapshot.

Read-only companion to the daily Action List: it refreshes *prices only* for
the names surfaced in the latest report (or a wider scope) and compares them
with completed-session daily features (SMA50/SMA200, 52-week high/low, 20d/60d
returns). It never writes decision snapshots, nor changes the official Action
List — those stay daily and immutable by design.

Usage:
    python scripts/intraday_watch.py                      # report scope (default)
    python scripts/intraday_watch.py --scope attention    # all watch/priority states
    python scripts/intraday_watch.py --scope all          # whole decision pool (slow)
    python scripts/intraday_watch.py --symbols ADI,CTAS   # custom list
    python scripts/intraday_watch.py --poll 300 --save     # loop + markdown log

Scope semantics:
    report     symbols linked in the latest ``action_list.md`` (default); add
               ``--include-weekly`` to union ``weekly_review.md``
    attention  decisions with action_state in PRIORITY_REVIEW / WATCH_PULLBACK /
               WATCH_BREAKOUT
    all        every decision in the snapshot (hundreds; expect ~1 minute)
    symbols    explicit ``--symbols`` list (overrides --scope)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_value_scanner.config import load_config  # noqa: E402
from ai_value_scanner.market_calendar import (  # noqa: E402
    is_session_day,
    latest_completed_session,
    session_close_utc,
)
from ai_value_scanner.decision.action import map_action_state_v2  # noqa: E402
from ai_value_scanner.decision.entry import build_entry_quality_v2  # noqa: E402
from ai_value_scanner.decision.model import QualityDecision, QualityGrade  # noqa: E402
from ai_value_scanner.scanner import (  # noqa: E402
    AlpacaClient,
    RequestRateLimiter,
    build_session,
    price_dimension_from_bars,
)

ET = ZoneInfo("America/New_York")
DEFAULT_CONFIG = "configs/config.production.json"
DEFAULT_SNAPSHOT_ROOT = REPO_ROOT / "outputs" / "decisions"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "intraday"
WATCH_ACTION_STATES = frozenset({"PRIORITY_REVIEW", "WATCH_PULLBACK", "WATCH_BREAKOUT"})
DETAILED_LINK_RE = re.compile(r"\./detailed/([A-Za-z0-9][A-Za-z0-9.\-]*)\.md")
SMA_SHORT = 50
SMA_LONG = 200
LOOKBACK_DAYS = 400
YEAR_SESSIONS = 252


# ---------------------------------------------------------------------------
# Snapshot loading and symbol scopes
# ---------------------------------------------------------------------------


def load_snapshot(snapshot_root: Path, snapshot_dir: Path | None = None) -> dict:
    """Load the latest production snapshot (or an explicit one)."""
    if snapshot_dir is None:
        pointer_path = snapshot_root / "latest_production.json"
        if not pointer_path.is_file():
            raise FileNotFoundError(
                f"missing production pointer: {pointer_path}; "
                "run the daily cron first"
            )
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        target = snapshot_root / str(pointer.get("snapshot_dir") or "")
        decision_date = str(pointer.get("decision_date") or "")
    else:
        target = snapshot_dir
        decision_date = target.name
    decisions_path = target / "decisions.jsonl"
    if not decisions_path.is_file():
        raise FileNotFoundError(f"missing decisions: {decisions_path}")
    decisions = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "snapshot_dir": target,
        "decision_date": decision_date,
        "decisions": decisions,
        "action_list": target / "action_list.md",
        "weekly_review": target / "weekly_review.md",
    }


def _report_symbols(text: str) -> list[str]:
    """Symbols linked in a rendered report, preserving report order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in DETAILED_LINK_RE.finditer(text or ""):
        symbol = match.group(1).upper()
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return ordered


def select_symbols(
    decisions: list[dict],
    *,
    scope: str = "report",
    action_list_text: str = "",
    weekly_review_text: str = "",
    include_weekly: bool = False,
    custom: str = "",
) -> list[str]:
    """Resolve the monitored symbol list for a scope."""
    if custom.strip():
        seen: set[str] = set()
        ordered: list[str] = []
        for token in re.split(r"[\s,]+", custom.strip()):
            symbol = token.upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
        return ordered

    if scope == "report":
        symbols = _report_symbols(action_list_text)
        if include_weekly:
            known = set(symbols)
            symbols.extend(
                s for s in _report_symbols(weekly_review_text) if s not in known
            )
        return symbols

    def priority(record: dict) -> int:
        try:
            return int(record.get("priority") or 10**6)
        except (TypeError, ValueError):
            return 10**6

    if scope == "top":
        ordered = sorted(decisions, key=priority)
        return [str(r.get("symbol")) for r in ordered if priority(r) <= 15]

    if scope == "attention":
        selected = [
            r for r in decisions
            if str(r.get("action_state")) in WATCH_ACTION_STATES
        ]
        return [str(r.get("symbol")) for r in sorted(selected, key=priority)]

    if scope == "all":
        return [str(r.get("symbol")) for r in sorted(decisions, key=priority)]

    raise ValueError(f"unsupported scope: {scope!r}")


# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------


def build_alpaca_client(config) -> AlpacaClient:
    """Build an Alpaca client with caching disabled (fresh prices only)."""
    load_dotenv(REPO_ROOT / ".env")
    import os

    api_endpoint = os.getenv("ALPACA_API_ENDPOINT", "").strip()
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    data_endpoint = os.getenv(
        "ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets"
    ).strip()
    feed = os.getenv("ALPACA_FEED", "iex").strip() or "iex"
    if not api_endpoint or not api_key or not api_secret:
        raise ValueError(
            "Missing Alpaca credentials; fill ALPACA_API_ENDPOINT/KEY/SECRET in .env"
        )
    limiter = RequestRateLimiter(config.alpaca_max_requests_per_sec)
    return AlpacaClient(
        session=build_session(),
        api_endpoint=api_endpoint,
        data_endpoint=data_endpoint,
        api_key=api_key,
        api_secret=api_secret,
        feed=feed,
        timeout_sec=config.request_timeout_sec,
        request_limiter=limiter,
        cache_dir=Path(config.cache_dir),
        cache_enabled=False,
        cache_ttl_assets_sec=0,
        cache_ttl_snapshots_sec=0,
        cache_ttl_bars_sec=0,
    )


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _bar_et_date(row: dict) -> date | None:
    parsed = _parse_ts(str(row.get("t") or ""))
    return parsed.astimezone(ET).date() if parsed else None


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _session_status(now_utc: datetime) -> str:
    now_et = now_utc.astimezone(ET)
    today = now_et.date()
    if not is_session_day(today):
        return "closed (weekend/holiday)"
    open_dt = datetime.combine(today, dtime(9, 30), tzinfo=ET)
    close_dt = session_close_utc(today).astimezone(ET)
    if open_dt <= now_et < close_dt:
        return "open"
    if now_et < open_dt:
        return "pre-market"
    return "closed"


def _snapshot_price(snapshot: dict | None) -> float | None:
    snapshot = snapshot or {}
    trade = snapshot.get("latestTrade") or {}
    minute = snapshot.get("minuteBar") or {}
    daily = snapshot.get("dailyBar") or {}
    return (
        _finite(trade.get("p"))
        or _finite(minute.get("c"))
        or _finite(daily.get("c"))
    )


def _snapshot_et_date(snapshot: dict | None) -> date | None:
    """Latest ET date present in a snapshot (daily bar / trade / minute bar)."""
    if not snapshot:
        return None
    dates: list[date] = []
    for key in ("dailyBar", "latestTrade", "minuteBar"):
        item = snapshot.get(key) or {}
        parsed = _parse_ts(str(item.get("t") or ""))
        if parsed is not None:
            dates.append(parsed.astimezone(ET).date())
    return max(dates) if dates else None


def _provisional_series(
    bars: list[dict] | None, snapshot: dict | None
) -> tuple[float | None, list[dict], date | None]:
    """Completed bars plus a snapshot-derived provisional bar for its session.

    Any existing bar for the snapshot's session is replaced, so a partially
    updating daily bar cannot be double-counted.
    """
    price = _snapshot_price(snapshot)
    snapshot_date = _snapshot_et_date(snapshot)
    ordered = [
        b for b in sorted(bars or [], key=lambda b: str(b.get("t") or ""))
        if isinstance(b, dict)
    ]
    if snapshot_date is None:
        return price, ordered, None
    series = [b for b in ordered if _bar_et_date(b) != snapshot_date]
    last_date = _bar_et_date(series[-1]) if series else None
    if last_date is not None and snapshot_date < last_date:
        return price, ordered, snapshot_date
    if price is None:
        return price, series, snapshot_date
    daily = snapshot.get("dailyBar") or {}
    open_ = _finite(daily.get("o")) or price
    high = _finite(daily.get("h")) or price
    low = _finite(daily.get("l")) or price
    close = _finite(daily.get("c")) or price
    stamp = daily.get("t") or (snapshot.get("latestTrade") or {}).get("t")
    if not stamp:
        stamp = f"{snapshot_date.isoformat()}T20:00:00+00:00"
    series.append(
        {
            "t": stamp,
            "o": open_,
            "h": max(high, open_, close),
            "l": min(low, open_, close),
            "c": close,
            "v": daily.get("v"),
            "provisional": True,
        }
    )
    return price, series, snapshot_date


def _qqq_context(
    qqq_snapshot: dict | None, qqq_bars: list[dict] | None, config
) -> dict | None:
    """Benchmark context (regime / trend filter / 60d return) for the shadow."""
    price, series, snapshot_date = _provisional_series(qqq_bars, qqq_snapshot)
    if price is None or not series:
        return None
    features = price_dimension_from_bars(price, series)
    return_60d = features.get("return_60d")
    closes = [c for c in (_finite(b.get("c")) for b in series) if c is not None]
    sma_days = int(getattr(config, "benchmark_trend_filter_sma_days", 200) or 200)
    sma = _mean(closes[-sma_days:]) if len(closes) >= sma_days else None
    trend_ok = True if sma is None else price >= sma
    regime = (
        "up" if return_60d is not None and return_60d >= 0.0
        else "down" if return_60d is not None
        else "unknown"
    )
    return {
        "price": price,
        "snapshot_date": snapshot_date,
        "return_60d": return_60d,
        "trend_ok": trend_ok,
        "regime": regime,
    }


def _quality_from_snapshot(decision: dict | None) -> QualityDecision | None:
    quality = (decision or {}).get("quality") or {}
    try:
        grade = QualityGrade(str(quality.get("grade")))
    except ValueError:
        return None
    return QualityDecision(
        grade=grade,
        score=_finite(quality.get("score")),
        confidence=_finite(quality.get("confidence")) or 0.0,
        component_scores=dict(quality.get("component_scores") or {}),
        positives=(),
        risks=(),
        missing=(),
        data_asof=quality.get("data_asof"),
    )


def compute_shadow(
    symbol: str,
    decision: dict | None,
    snapshot: dict | None,
    bars: list[dict] | None,
    qqq_context: dict | None,
    config,
) -> dict | None:
    """Provisional Entry re-estimation using the current price as a close.

    Reuses the production Entry v2 builder and action mapping. The result is
    explicitly provisional: quality is carried over from the snapshot, and the
    current session is treated as if it had closed now.
    """
    if decision is None or qqq_context is None:
        return None
    price, series, snapshot_date = _provisional_series(bars, snapshot)
    if price is None or not series or snapshot_date is None:
        return None
    features = price_dimension_from_bars(price, series)
    stock_ret60 = features.get("return_60d")
    qqq_ret60 = qqq_context.get("return_60d")
    rs60 = (
        stock_ret60 - qqq_ret60
        if stock_ret60 is not None and qqq_ret60 is not None
        else None
    )
    metrics = {
        **features,
        "market_asof": snapshot_date.isoformat(),
        "qqq_trailing_return_60d": qqq_ret60,
        "relative_strength_60d_qqq": rs60,
        "regime": qqq_context.get("regime"),
        "benchmark_trend_ok": qqq_context.get("trend_ok"),
    }
    try:
        entry = build_entry_quality_v2(
            metrics,
            decision_date=snapshot_date,
            market_asof=snapshot_date,
            runtime_reference_date=snapshot_date,
        )
    except Exception:  # noqa: BLE001 - a shadow must never break the monitor
        return None
    action = None
    quality = _quality_from_snapshot(decision)
    if quality is not None:
        try:
            action, _ = map_action_state_v2(quality, entry)
        except ValueError:
            action = None
    official = decision.get("entry") or {}
    official_status = {
        str(gate.get("gate_key")): str(gate.get("status"))
        for gate in (official.get("gate_results") or [])
        if isinstance(gate, dict)
    }
    shadow_status = {gate.gate_key: gate.status for gate in entry.gate_results}
    flips = [
        f"{key}:{official_status[key]}→{shadow_status[key]}"
        for key in sorted(official_status)
        if key in shadow_status and official_status[key] != shadow_status[key]
    ]
    official_score = _finite(official.get("score"))
    return {
        "shadow_state": entry.state.value,
        "shadow_score": entry.score,
        "shadow_delta": (
            entry.score - official_score
            if entry.score is not None and official_score is not None
            else None
        ),
        "shadow_action": action.value if action is not None else None,
        "shadow_date": snapshot_date.isoformat(),
        "gate_flips": flips,
    }


def _decision_context(decision: dict | None) -> dict:
    if not decision:
        return {
            "action": "-",
            "priority": None,
            "quality": "-",
            "entry": "-",
            "pre_earnings": False,
        }
    quality = decision.get("quality") or {}
    entry = decision.get("entry") or {}
    risks = list(quality.get("risks") or []) + list(entry.get("risks") or [])
    pre_earnings = any(
        isinstance(item, dict) and item.get("code") == "pre_earnings_window_risk"
        for item in risks
    )
    return {
        "action": str(decision.get("action_state") or "-"),
        "priority": decision.get("priority"),
        "quality": (
            f"{quality.get('grade') or '?'}:{float(quality.get('score')):.3f}"
            if _finite(quality.get("score")) is not None
            else "-"
        ),
        "entry": (
            f"{entry.get('state') or '?'}:{float(entry.get('score')):.3f}"
            if _finite(entry.get("score")) is not None
            else "-"
        ),
        "pre_earnings": pre_earnings,
    }


def compute_row(
    symbol: str,
    decision: dict | None,
    snapshot: dict | None,
    bars: list[dict] | None,
    *,
    latest_session: date,
) -> dict:
    """Compute one monitor row from a snapshot and completed daily bars."""
    snapshot = snapshot or {}
    bars = [b for b in (bars or []) if isinstance(b, dict)]
    completed = [
        b for b in sorted(bars, key=lambda b: str(b.get("t") or ""))
        if (_bar_et_date(b) is not None and _bar_et_date(b) <= latest_session)
    ]
    closes = [c for c in (_finite(b.get("c")) for b in completed) if c is not None]
    highs = [h for h in (_finite(b.get("h")) for b in completed) if h is not None]
    lows = [lo for lo in (_finite(b.get("l")) for b in completed) if lo is not None]

    trade = snapshot.get("latestTrade") or {}
    minute = snapshot.get("minuteBar") or {}
    daily = snapshot.get("dailyBar") or {}
    prev_daily = snapshot.get("prevDailyBar") or {}
    price = _snapshot_price(snapshot)
    prev_close = _finite(prev_daily.get("c")) or (closes[-1] if closes else None)

    sma50 = _mean(closes[-SMA_SHORT:]) if len(closes) >= SMA_SHORT else None
    sma200 = _mean(closes[-SMA_LONG:]) if len(closes) >= SMA_LONG else None
    high_52w = max(highs[-YEAR_SESSIONS:], default=None)
    low_52w = min(lows[-YEAR_SESSIONS:], default=None)
    if price is not None:
        high_52w = max([v for v in (high_52w, price) if v is not None], default=None)
        low_52w = min([v for v in (low_52w, price) if v is not None], default=None)

    pct_change = (
        price / prev_close - 1.0
        if price is not None and prev_close not in (None, 0)
        else None
    )
    vs50 = price / sma50 - 1.0 if price is not None and sma50 else None
    vs200 = price / sma200 - 1.0 if price is not None and sma200 else None
    drawdown = (
        1.0 - price / high_52w if price is not None and high_52w else None
    )
    range_pos = (
        (price - low_52w) / (high_52w - low_52w)
        if None not in (price, low_52w, high_52w) and high_52w > low_52w
        else None
    )
    ret20 = (
        price / closes[-20] - 1.0 if price is not None and len(closes) >= 20 else None
    )
    ret60 = (
        price / closes[-60] - 1.0 if price is not None and len(closes) >= 60 else None
    )

    flags: list[str] = []
    if price is not None and sma50:
        if price < sma50:
            flags.append("S50↓")
            if prev_close is not None and prev_close >= sma50:
                flags.append("S50✖")
    if price is not None and sma200:
        if price < sma200:
            flags.append("S200↓")
            if prev_close is not None and prev_close >= sma200:
                flags.append("S200✖")
        elif price / sma200 > 1.6:
            flags.append("EXT")
    if drawdown is not None and drawdown <= 0.03:
        flags.append("HI")
    if range_pos is not None and range_pos <= 0.05:
        flags.append("LO")
    if pct_change is not None and abs(pct_change) >= 0.03:
        flags.append("MOVE")
    context = _decision_context(decision)
    if context["pre_earnings"]:
        flags.append("PE")

    return {
        "symbol": symbol,
        "price": price,
        "pct_change": pct_change,
        "sma50": sma50,
        "sma200": sma200,
        "vs50": vs50,
        "vs200": vs200,
        "drawdown_52w": drawdown,
        "range_pos_52w": range_pos,
        "ret20": ret20,
        "ret60": ret60,
        "flags": flags,
        "action": context["action"],
        "priority": context["priority"],
        "quality": context["quality"],
        "entry": context["entry"],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _pct(value: float | None, width: int = 7) -> str:
    return f"{value * 100:+.{1}f}%" if value is not None else "n/a"


def format_table(rows: list[dict]) -> str:
    header = (
        f"{'SYM':7s} {'ACT':15s} {'Q':9s} {'E':20s} "
        f"{'PRICE':>9s} {'Δ%':>7s} {'vs50':>7s} {'vs200':>7s} "
        f"{'DD52w':>7s} {'20d':>7s} {'60d':>7s}  FLAGS"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        price = f"{row['price']:.2f}" if row["price"] is not None else "n/a"
        lines.append(
            f"{row['symbol']:7s} {row['action'][:15]:15s} {row['quality'][:9]:9s} "
            f"{row['entry'][:20]:20s} {price:>9s} {_pct(row['pct_change']):>7s} "
            f"{_pct(row['vs50']):>7s} {_pct(row['vs200']):>7s} "
            f"{_pct(row['drawdown_52w']):>7s} {_pct(row['ret20']):>7s} "
            f"{_pct(row['ret60']):>7s}  {','.join(row['flags']) or '-'}"
        )
    return "\n".join(lines)


def format_shadow_table(rows: list[dict]) -> str:
    header = (
        f"{'SYM':7s} {'E official':22s} {'E shadow':22s} {'Δscore':>7s} "
        f"{'A official':16s} {'A shadow':16s}  FLIPS"
    )
    lines = [
        "[shadow] provisional Entry re-estimation (current price as provisional close; NOT a decision)",
        header,
        "-" * len(header),
    ]
    for row in rows:
        if not row.get("shadow_state"):
            continue
        shadow_score = row.get("shadow_score")
        shadow_text = (
            f"{row['shadow_state']}:{shadow_score:.2f}"
            if shadow_score is not None
            else str(row["shadow_state"])
        )
        delta = row.get("shadow_delta")
        delta_text = f"{delta:+.3f}" if delta is not None else "n/a"
        lines.append(
            f"{row['symbol']:7s} {row['entry'][:22]:22s} {shadow_text[:22]:22s} "
            f"{delta_text:>7s} {row['action'][:16]:16s} "
            f"{(row.get('shadow_action') or '-')[:16]:16s}  "
            f"{','.join(row.get('gate_flips') or []) or '-'}"
        )
    return "\n".join(lines)


def render_markdown(
    rows: list[dict],
    *,
    decision_date: str,
    scope: str,
    market_status: str,
    generated_utc: str,
) -> str:
    lines = [
        f"# Intraday Watch — {generated_utc}",
        "",
        f"- Decision snapshot: `{decision_date}` · Scope: `{scope}` · "
        f"Market: **{market_status}** · Names: {len(rows)}",
        "- Read-only monitor; official decisions stay daily and immutable.",
        "",
        "| SYM | Action | Quality | Entry | Price | Δ% | vs50 | vs200 | DD52w | 20d | 60d | Flags |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        price = f"{row['price']:.2f}" if row["price"] is not None else "n/a"
        lines.append(
            f"| {row['symbol']} | {row['action']} | {row['quality']} | {row['entry']} "
            f"| {price} | {_pct(row['pct_change'])} | {_pct(row['vs50'])} "
            f"| {_pct(row['vs200'])} | {_pct(row['drawdown_52w'])} "
            f"| {_pct(row['ret20'])} | {_pct(row['ret60'])} "
            f"| {','.join(row['flags']) or '-'} |"
        )
    shadow_rows = [row for row in rows if row.get("shadow_state")]
    if shadow_rows:
        lines.append("")
        lines.append(
            "## Provisional Entry shadow (current price as provisional close — NOT a decision)"
        )
        lines.append("")
        lines.append(
            "| SYM | E official | E shadow | Δscore | Action official | Action shadow | Gate flips |"
        )
        lines.append("|---|---|---|---:|---|---|---|")
        for row in shadow_rows:
            score = row.get("shadow_score")
            shadow_text = (
                f"{row['shadow_state']}:{score:.2f}"
                if score is not None
                else row["shadow_state"]
            )
            delta = row.get("shadow_delta")
            lines.append(
                f"| {row['symbol']} | {row['entry']} | {shadow_text} "
                f"| {f'{delta:+.3f}' if delta is not None else 'n/a'} "
                f"| {row['action']} | {row.get('shadow_action') or '-'} "
                f"| {','.join(row.get('gate_flips') or []) or '-'} |"
            )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_once(args: argparse.Namespace, *, client=None) -> list[dict]:
    snapshot_root = Path(args.snapshot_root)
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else None
    bundle = load_snapshot(snapshot_root, snapshot_dir)
    decisions = bundle["decisions"]
    by_symbol = {str(r.get("symbol")): r for r in decisions}
    action_list_text = (
        bundle["action_list"].read_text(encoding="utf-8")
        if bundle["action_list"].is_file() else ""
    )
    weekly_text = (
        bundle["weekly_review"].read_text(encoding="utf-8")
        if bundle["weekly_review"].is_file() else ""
    )
    symbols = select_symbols(
        decisions,
        scope=args.scope,
        action_list_text=action_list_text,
        weekly_review_text=weekly_text,
        include_weekly=args.include_weekly,
        custom=args.symbols or "",
    )
    if not symbols:
        raise ValueError("no symbols selected; check --scope/--symbols")

    config = load_config(args.config)
    if client is None:
        client = build_alpaca_client(config)
    chunk = args.chunk_size or config.chunk_size
    shadow = not getattr(args, "no_shadow", False)
    fetch_symbols = list(symbols)
    if shadow and "QQQ" not in fetch_symbols:
        fetch_symbols.append("QQQ")
    snapshots = client.get_snapshots(fetch_symbols, chunk)
    start_iso = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    bars = client.get_daily_bars(fetch_symbols, start_iso, chunk)

    now_utc = datetime.now(timezone.utc)
    latest_session = latest_completed_session(now_utc)
    qqq_context = (
        _qqq_context(snapshots.get("QQQ"), bars.get("QQQ"), config)
        if shadow else None
    )
    rows: list[dict] = []
    for symbol in symbols:
        row = compute_row(
            symbol,
            by_symbol.get(symbol),
            snapshots.get(symbol),
            bars.get(symbol),
            latest_session=latest_session,
        )
        if shadow:
            shadow_info = compute_shadow(
                symbol,
                by_symbol.get(symbol),
                snapshots.get(symbol),
                bars.get(symbol),
                qqq_context,
                config,
            )
            if shadow_info:
                row.update(shadow_info)
        rows.append(row)
    status = _session_status(now_utc)
    generated = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(
        f"[intraday] snapshot={bundle['decision_date']} scope={args.scope} "
        f"names={len(rows)} market={status} shadow={'on' if shadow else 'off'} "
        f"session={latest_session.isoformat()} generated={generated}",
        flush=True,
    )
    print(format_table(rows), flush=True)
    if any(row.get("shadow_state") for row in rows):
        print("")
        print(format_shadow_table(rows), flush=True)

    if args.save or args.out:
        out_path = (
            Path(args.out)
            if args.out
            else DEFAULT_OUTPUT_ROOT / bundle["decision_date"]
            / f"monitor_{now_utc.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            render_markdown(
                rows,
                decision_date=bundle["decision_date"],
                scope=args.scope,
                market_status=status,
                generated_utc=generated,
            ),
            encoding="utf-8",
        )
        print(f"[intraday] saved: {out_path}", flush=True)
    return rows


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only intraday watch monitor for the latest production snapshot."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    parser.add_argument("--snapshot-dir", default=None)
    parser.add_argument(
        "--scope", choices=("report", "top", "attention", "all"), default="report"
    )
    parser.add_argument(
        "--symbols", default="",
        help="Explicit comma/space separated symbols (overrides --scope).",
    )
    parser.add_argument("--include-weekly", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=0)
    parser.add_argument("--poll", type=int, default=0, help="Repeat every N seconds.")
    parser.add_argument(
        "--no-shadow", action="store_true",
        help="Skip the provisional Entry re-estimation (shadow) section.",
    )
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--out", default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    while True:
        run_once(args)
        if args.poll <= 0:
            return 0
        time.sleep(args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
