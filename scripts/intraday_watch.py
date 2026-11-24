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
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_value_scanner.config import load_config  # noqa: E402
from ai_value_scanner.market_calendar import latest_completed_session  # noqa: E402
from ai_value_scanner.intraday_market import (  # noqa: E402
    INTRADAY_DATA_VERSION,
    IntradayBenchmark,
    IntradayObservation,
    IntradayPolicy,
    build_benchmark,
    build_provisional_entry,
    fetch_observations,
    market_period,
    positive,
)
from ai_value_scanner.decision.action import map_action_state_v2  # noqa: E402
from ai_value_scanner.decision.model import QualityDecision, QualityGrade  # noqa: E402
from ai_value_scanner.reporting.publication import format_list_status, latest_list_status  # noqa: E402
from ai_value_scanner.scanner import (  # noqa: E402
    AlpacaClient,
    RequestRateLimiter,
    build_session,
    price_dimension_from_bars,
)

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


def load_snapshot(
    snapshot_root: Path, snapshot_dir: Path | None = None, *, now_utc: datetime | None = None
) -> dict:
    """Load the latest production snapshot (or an explicit one)."""
    if snapshot_dir is None:
        publication = latest_list_status(
            snapshot_root, "production", now_utc or datetime.now(timezone.utc)
        )
        pointer = publication["publication"]
        if pointer is None:
            message = format_list_status(publication)
            if publication["status"] == "invalid":
                raise ValueError(f"{message} · {publication['error']}")
            raise FileNotFoundError(message)
        target = snapshot_root / pointer["snapshot_dir"]
        decision_date = pointer["decision_date"]
    else:
        target = snapshot_dir
        decision_date = target.name
        publication = None
    decisions_path = target / "decisions.jsonl"
    if not decisions_path.is_file():
        raise FileNotFoundError(f"missing decisions: {decisions_path}")
    decisions = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    recorded_dates = {str(row['decision_date']) for row in decisions if row.get('decision_date')}
    if len(recorded_dates) > 1:
        raise ValueError('snapshot contains mixed decision dates')
    if recorded_dates:
        recorded_date = next(iter(recorded_dates))
        if snapshot_dir is None and decision_date != recorded_date:
            raise ValueError('snapshot date differs from latest pointer')
        decision_date = recorded_date
    elif snapshot_dir is not None:
        try:
            decision_date = date.fromisoformat(target.parent.name).isoformat()
        except ValueError:
            pass
    return {
        "snapshot_dir": target,
        "decision_date": decision_date,
        "decisions": decisions,
        "action_list": target / "action_list.md",
        "weekly_review": target / "weekly_review.md",
        "publication_status": (
            format_list_status(publication)
            if publication is not None else f"historical snapshot · session={decision_date}"
        ),
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
    feed = 'iex'  # Explicit monitor feed, independent of official SIP decisions.
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


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _session_status(now_utc: datetime) -> str:
    return {
        "regular": "open", "pre_market": "pre-market", "post_market": "post-market",
        "market_closed": "closed (weekend/holiday)",
    }[market_period(now_utc)]


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
    decision: dict | None,
    observation: IntradayObservation,
    benchmark: IntradayBenchmark,
    policy: IntradayPolicy,
) -> dict:
    """Re-estimate Entry only with a fresh, split-consistent benchmark pair."""
    if decision is None:
        return {"shadow_reason": "no_frozen_decision"}
    try:
        entry, reason = build_provisional_entry(observation, benchmark, policy)
    except (ValueError, TypeError, OverflowError):
        return {"shadow_reason": "entry_calculation_failed"}
    if entry is None:
        return {"shadow_reason": reason}
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
        "shadow_date": entry.market_asof,
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


def compute_row(symbol: str, decision: dict | None, observation: IntradayObservation) -> dict:
    """Display the observed price and signals on the same share basis."""
    quote = observation.quote
    display_price = quote.price if quote is not None else None
    price = display_price if observation.quote_status == "fresh" else None
    completed = observation.completed_bars[-YEAR_SESSIONS:]
    prev_close = positive(completed[-1].get("c")) if completed else None
    reference = price_dimension_from_bars(price, completed)
    provisional = price_dimension_from_bars(
        price, observation.provisional_bars[-YEAR_SESSIONS:],
    )

    sma50 = sma200 = None
    if reference["price_to_sma50"] is not None:
        sma50 = sum(float(bar["c"]) for bar in completed[-SMA_SHORT:]) / SMA_SHORT
    if reference["price_to_sma200"] is not None:
        sma200 = sum(float(bar["c"]) for bar in completed[-SMA_LONG:]) / SMA_LONG
    pct_change = price / prev_close - 1.0 if price is not None and prev_close is not None else None
    vs50 = price / sma50 - 1.0 if sma50 else None
    vs200 = price / sma200 - 1.0 if sma200 else None
    drawdown = provisional["drawdown_from_52w_high"]
    range_pos = provisional["range_position_52w"]
    ret20, ret60 = provisional["return_20d"], provisional["return_60d"]

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
        "price": display_price,
        "quote_source": quote.source if quote else None,
        "quote_timestamp": quote.timestamp.isoformat() if quote and quote.timestamp else None,
        "quote_session": quote.session.isoformat() if quote else None,
        "quote_received_at": quote.received_at.isoformat() if quote else None,
        "quote_age_seconds": (
            (observation.asof - quote.timestamp).total_seconds()
            if quote and quote.timestamp else None
        ),
        "quote_status": observation.quote_status,
        "history_issue": observation.history_issue,
        "quote_feed": quote.feed if quote else None,
        "quote_price_basis": quote.price_basis if quote else None,
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


def format_policy(policy: IntradayPolicy) -> str:
    return (
        f"{INTRADAY_DATA_VERSION} · max age {policy.max_age_seconds}s · "
        f"max stock–QQQ skew {policy.max_skew_seconds}s · raw quote session share basis"
    )


def _quote_label(row: dict) -> str:
    parts = [row["quote_status"]]
    if row["quote_source"]:
        parts.append(f"{row['quote_feed']}:{row['quote_source']}")
        parts.append(row["quote_timestamp"] or f"session {row['quote_session']}")
    if row["quote_age_seconds"] is not None:
        parts.append(f"{row['quote_age_seconds']:.0f}s old")
    if row.get("history_issue"):
        parts.append(row["history_issue"])
    if row.get("shadow_reason"):
        parts.append(f"shadow {row['shadow_reason']}")
    return " · ".join(parts)


def format_table(rows: list[dict]) -> str:
    header = (
        f"{'SYM':7s} {'ACT':15s} {'Q':9s} {'E':20s} "
        f"{'PRICE':>9s} {'Δ%':>7s} {'vs50':>7s} {'vs200':>7s} "
        f"{'DD52w':>7s} {'20d':>7s} {'60d':>7s}  FLAGS  QUOTE"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        price = f"{row['price']:.2f}" if row["price"] is not None else "n/a"
        lines.append(
            f"{row['symbol']:7s} {row['action'][:15]:15s} {row['quality'][:9]:9s} "
            f"{row['entry'][:20]:20s} {price:>9s} {_pct(row['pct_change']):>7s} "
            f"{_pct(row['vs50']):>7s} {_pct(row['vs200']):>7s} "
            f"{_pct(row['drawdown_52w']):>7s} {_pct(row['ret20']):>7s} "
            f"{_pct(row['ret60']):>7s}  {','.join(row['flags']) or '-'}  {_quote_label(row)}"
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


def snapshot_market_source(decisions: list[dict]) -> str:
    sources = set()
    for decision in decisions:
        provenance = decision.get('provenance') or {}
        feed = provenance.get('market_data_feed')
        if feed == 'sip' and provenance.get('market_data_mode') == 'sip_eod':
            sources.add('SIP completed-session daily bars')
        else:
            sources.add(str(feed).upper() if feed else 'unspecified (legacy snapshot)')
    return ', '.join(sorted(sources)) or 'unspecified (empty snapshot)'


def render_markdown(
    rows: list[dict],
    *,
    decision_date: str,
    scope: str,
    market_status: str,
    generated_utc: str,
    baseline_source: str = 'unspecified (legacy snapshot)',
    publication_status: str | None = None,
    policy_label: str | None = None,
    benchmark_label: str | None = None,
) -> str:
    lines = [
        f"# Intraday Watch — {generated_utc}",
        "",
        f"- Decision snapshot: `{decision_date}` · Scope: `{scope}` · "
        f"Market: **{market_status}** · Names: {len(rows)}",
        *([f"- Publication: {publication_status}"] if publication_status else []),
        "- Read-only monitor; official decisions stay daily and immutable.",
        f"- Market data: **IEX intraday**; snapshot baseline: **{baseline_source}**. Shadow estimates may differ across feeds.",
        *([f"- Quote checks · {policy_label}"] if policy_label else []),
        *([f"- QQQ · {benchmark_label}"] if benchmark_label else []),
        "",
        "| SYM | Action | Quality | Entry | Price | Δ% | vs50 | vs200 | DD52w | 20d | 60d | Flags | Quote |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        price = f"{row['price']:.2f}" if row["price"] is not None else "n/a"
        lines.append(
            f"| {row['symbol']} | {row['action']} | {row['quality']} | {row['entry']} "
            f"| {price} | {_pct(row['pct_change'])} | {_pct(row['vs50'])} "
            f"| {_pct(row['vs200'])} | {_pct(row['drawdown_52w'])} "
            f"| {_pct(row['ret20'])} | {_pct(row['ret60'])} "
            f"| {','.join(row['flags']) or '-'} | {_quote_label(row)} |"
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
    if args.out and any(
        Path(args.out).resolve().is_relative_to(path.resolve())
        for path in (snapshot_root, snapshot_dir) if path is not None
    ):
        raise ValueError("monitor output must be outside official snapshot directories")
    bundle = load_snapshot(snapshot_root, snapshot_dir)
    decisions = bundle["decisions"]
    baseline_source = snapshot_market_source(decisions)
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
    policy = IntradayPolicy(args.max_quote_age_sec, args.max_quote_skew_sec)
    observations = fetch_observations(client, fetch_symbols, chunk, LOOKBACK_DAYS, policy)
    now_utc = next(iter(observations.values())).asof
    latest_session = latest_completed_session(now_utc)
    benchmark = (
        build_benchmark(observations["QQQ"], config.benchmark_trend_filter_sma_days)
        if shadow else None
    )
    rows: list[dict] = []
    for symbol in symbols:
        observation = observations[symbol]
        decision = by_symbol.get(symbol)
        row = compute_row(symbol, decision, observation)
        if benchmark is not None:
            row.update(compute_shadow(decision, observation, benchmark, policy))
        rows.append(row)
    status = _session_status(now_utc)
    generated = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(
        f"[intraday] feed=IEX (provisional; baseline={baseline_source}) snapshot={bundle['decision_date']} scope={args.scope} "
        f"names={len(rows)} market={status} shadow={'on' if shadow else 'off'} "
        f"session={latest_session.isoformat()} generated={generated}",
        flush=True,
    )
    print(f"[publication] {bundle['publication_status']}", flush=True)
    policy_label = format_policy(policy)
    benchmark_label = (
        _quote_label(compute_row("QQQ", None, benchmark.observation)) if benchmark is not None else None
    )
    print(f"[market-data] {policy_label}", flush=True)
    if benchmark_label is not None:
        print(f"[QQQ] {benchmark_label}", flush=True)
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
                baseline_source=baseline_source,
                publication_status=bundle["publication_status"],
                policy_label=policy_label,
                benchmark_label=benchmark_label,
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
    defaults = IntradayPolicy()
    parser.add_argument("--max-quote-age-sec", type=int, default=defaults.max_age_seconds)
    parser.add_argument("--max-quote-skew-sec", type=int, default=defaults.max_skew_seconds)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.max_quote_age_sec <= 0 or args.max_quote_skew_sec <= 0 or args.chunk_size < 0:
        parser.error("quote limits must be positive and chunk size cannot be negative")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    while True:
        run_once(args)
        if args.poll <= 0:
            return 0
        time.sleep(args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
