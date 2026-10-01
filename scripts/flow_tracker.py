"""Left-side block-flow tracker: SIP trade-tape block statistics per symbol-day.

Fetches historical intraday trades from Alpaca (SIP), classifies prints with
the tick rule, and persists per-day block-flow metrics to data/flow/<SYM>.csv.
Resumable: cached symbol-days are never refetched.

Usage:
  python scripts/flow_tracker.py --auto-left-side --days 8
  python scripts/flow_tracker.py --symbols CRDO,VST --days 8
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv

sys.path.insert(0, "src")

CACHE_DIR = Path("data/flow")
DAY_COLS = [
    "date", "prints", "volume", "notional_m", "dark_share", "vwap",
    "n_blocks_100k", "blocks_100k_sh", "blocks_100k_buy_sh",
    "n_blocks_1m", "blocks_1m_sh", "blocks_1m_buy_sh", "mega_max_m", "close",
]
ZERO_DAY = {
    "prints": 0, "volume": 0, "notional_m": 0.0, "dark_share": 0.0, "vwap": "",
    "n_blocks_100k": 0, "blocks_100k_sh": 0, "blocks_100k_buy_sh": 0.0,
    "n_blocks_1m": 0, "blocks_1m_sh": 0, "blocks_1m_buy_sh": 0.0, "mega_max_m": 0.0, "close": "",
}


def load_env() -> dict[str, str]:
    load_dotenv()
    return dict(os.environ)


def alpaca_headers(env: dict[str, str]) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": env["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": env["ALPACA_API_SECRET"],
    }


def trading_days(n_days: int, end_date: str | None = None) -> list[str]:
    now_utc = datetime.now(timezone.utc)
    if end_date is None:
        if now_utc.time() >= datetime.strptime("20:05", "%H:%M").time():
            end = now_utc.date()
        else:
            end = now_utc.date() - timedelta(days=1)
    else:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    out: list[str] = []
    d = end
    while len(out) < n_days:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def fetch_day_trades(session: requests.Session, headers: dict, symbol: str, day: str) -> list[tuple[float, int, str]]:
    url = "https://data.alpaca.markets/v2/stocks/trades"
    params = {
        "symbols": symbol, "start": f"{day}T13:30:00Z", "end": f"{day}T20:00:00Z",
        "limit": 10000, "feed": "sip", "sort": "asc",
    }
    prints: list[tuple[float, int, str]] = []
    page_token = None
    while True:
        req_params = dict(params)
        if page_token:
            req_params["page_token"] = page_token
        for attempt in range(4):
            resp = session.get(url, headers=headers, params=req_params, timeout=30)
            if resp.status_code == 404:
                return []
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(30 if resp.status_code == 429 else 5)
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError(f"rate-limit retries exhausted for {symbol} {day}")
        data = resp.json()
        for t in data.get("trades", {}).get(symbol, []):
            prints.append((float(t["p"]), int(t["s"]), str(t.get("x", ""))))
        page_token = data.get("next_page_token")
        if not page_token:
            return prints
        time.sleep(0.09)


def compute_day_metrics(prints: list[tuple[float, int, str]]) -> dict:
    if not prints:
        return None
    px = np.array([p for p, _, _ in prints])
    sz = np.array([s for _, s, _ in prints], dtype=np.int64)
    vx = [x for _, _, x in prints]
    notional = px * sz
    buy_sh = np.zeros(len(px))
    last_p = None
    for i in range(len(px)):
        if last_p is not None:
            if px[i] > last_p:
                buy_sh[i] = sz[i]
            elif px[i] == last_p:
                buy_sh[i] = 0.5 * sz[i]
        last_p = px[i]
    dark = int(sz[[v == "D" for v in vx]].sum())
    rows = {}
    for tier, label in ((1e5, "100k"), (1e6, "1m")):
        m = notional >= tier
        rows[f"n_blocks_{label}"] = int(m.sum())
        rows[f"blocks_{label}_sh"] = int(sz[m].sum())
        rows[f"blocks_{label}_buy_sh"] = float(buy_sh[m].sum())
    mega = float(notional.max()) / 1e6 if len(notional) else 0.0
    return {
        "prints": len(px), "volume": int(sz.sum()), "notional_m": round(float(notional.sum()) / 1e6, 1),
        "dark_share": round(dark / max(1, int(sz.sum())), 4),
        "vwap": round(float(notional.sum() / sz.sum()), 4), "close": float(px[-1]),
        "mega_max_m": round(mega, 2), **rows,
    }


def read_cache(symbol: str) -> dict[str, dict]:
    path = CACHE_DIR / f"{symbol}.csv"
    days: dict[str, dict] = {}
    if not path.exists():
        return days
    with open(path) as f:
        for r in csv.DictReader(f):
            days[r["date"]] = r
    return days


def write_cache(symbol: str, days: dict[str, dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DAY_COLS)
        w.writeheader()
        for d in sorted(days):
            w.writerow(days[d])


def auto_left_side_symbols() -> list[str]:
    import glob as _glob
    pools = sorted(_glob.glob("outputs/ai_value_scan_*_full_ranked_research_pool.csv"))
    names: set[str] = set()
    for p in pools[-4:]:
        with open(p) as f:
            for r in csv.DictReader(f):
                if r.get("research_priority") == "left_side_watch":
                    names.add(r["symbol"].upper())
    return sorted(names)


def summarize(symbol: str, lookback_days: int) -> dict | None:
    days = read_cache(symbol)
    if not days:
        return None
    all_rows = [days[d] for d in sorted(days)]
    rows = [r for r in all_rows if int(float(r.get("volume") or 0)) > 0][-lookback_days:]
    b1m_sh = sum(float(r["blocks_1m_sh"]) for r in rows)
    b1m_buy = sum(float(r["blocks_1m_buy_sh"]) for r in rows)
    b100k_sh = sum(float(r["blocks_100k_sh"]) for r in rows)
    b100k_buy = sum(float(r["blocks_100k_buy_sh"]) for r in rows)
    n1m = sum(int(r["n_blocks_1m"]) for r in rows)
    dark = float(np.average([float(r["dark_share"]) for r in rows], weights=[float(r["volume"]) for r in rows]))
    closes = [float(r["close"]) for r in rows]
    px_chg_3d = (closes[-1] / closes[-3] - 1) if len(closes) >= 3 else None
    if n1m >= 4 and b1m_sh > 0:
        tier, ratio, n_blocks = "1m", b1m_buy / b1m_sh, n1m
    elif b100k_sh > 0:
        tier, ratio, n_blocks = "100k", b100k_buy / b100k_sh, sum(int(r["n_blocks_100k"]) for r in rows)
    else:
        tier, ratio, n_blocks = "none", None, 0
    if ratio is None:
        verdict = "insufficient_blocks"
    elif ratio >= 0.60 and px_chg_3d is not None and px_chg_3d >= -0.01:
        verdict = "accumulate_confirm"
    elif ratio >= 0.60:
        verdict = "accumulate_unconfirmed"
    elif ratio <= 0.40:
        verdict = "distribute"
    else:
        verdict = "mixed"
    return {
        "symbol": symbol, "days": len(rows), "tier": tier, "n_blocks": n_blocks,
        "buy_ratio": round(ratio, 3) if ratio is not None else None,
        "dark_share": round(dark, 3), "px_chg_3d": round(px_chg_3d, 4) if px_chg_3d is not None else None,
        "last_close": closes[-1], "verdict": verdict,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="Comma-separated list; overrides --auto-left-side")
    ap.add_argument("--auto-left-side", action="store_true", help="Read latest research pools for left_side_watch names")
    ap.add_argument("--extra-symbols", default="", help="Additional symbols appended to the list")
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols and args.auto_left_side:
        symbols = auto_left_side_symbols()
    if args.extra_symbols:
        symbols += [s.strip().upper() for s in args.extra_symbols.split(",") if s.strip()]
    symbols = sorted(set(symbols))
    if not symbols:
        raise SystemExit("no symbols: pass --symbols or --auto-left-side")

    days_wanted = trading_days(args.days, args.end_date)
    env = load_env()
    headers = alpaca_headers(env)
    session = requests.Session()

    for sym in symbols:
        cache = read_cache(sym)
        missing = [d for d in days_wanted if d not in cache]
        if args.summary_only:
            continue
        for d in missing:
            prints = fetch_day_trades(session, headers, sym, d)
            m = compute_day_metrics(prints)
            if m is None:
                cache[d] = {"date": d, **ZERO_DAY}
            else:
                cache[d] = {"date": d, **m}
            time.sleep(0.05)
        if missing:
            write_cache(sym, cache)
        done = len([d for d in days_wanted if d in cache])
        print(f"[flow] {sym}: {done}/{len(days_wanted)} days cached")

    print(f"\n{'symbol':7s} {'days':>4s} {'tier':>5s} {'blocks':>7s} {'buy%':>6s} {'dark%':>6s} {'px3d':>7s} {'verdict'}")
    for sym in symbols:
        s = summarize(sym, args.days)
        if s is None:
            print(f"{sym:7s} {'-':>4s} no data")
            continue
        px = f"{s['px_chg_3d']:+.1%}" if s["px_chg_3d"] is not None else "-"
        buy = f"{s['buy_ratio']:.0%}" if s["buy_ratio"] is not None else "-"
        print(f"{sym:7s} {s['days']:>4d} {s['tier']:>5s} {s['n_blocks']:>7d} {buy:>6s} {s['dark_share']:>6.0%} {px:>7s} {s['verdict']}")


if __name__ == "__main__":
    main()
