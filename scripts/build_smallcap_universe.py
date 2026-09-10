from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from ai_value_scanner.scanner import ScanConfig, load_config, normalize_equity_symbol

BUCKET = "ai_smallcap"

NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
YAHOO_SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

SOURCE_NASDAQ = "SRC:NASDAQ_SCREEN"
SOURCE_YAHOO = "SRC:YAHOO_HOT"
SOURCE_MANUAL = "SRC:MANUAL"

# Nasdaq industries treated as AI-relevant for the smallcap bucket.
# TECH industries require sector == "Technology"; POWER industries (data-center
# power vertical) match in any sector so Utilities/Energy IPPs are covered.
NASDAQ_TECH_INDUSTRIES = {
    "Semiconductors",
    "Semiconductor Equipment & Materials",
    "Computer Software: Prepackaged Software",
    "Computer Software: Programming Data Processing",
    "EDP Services",
    "Electronic Components",
    "Electrical Products",
    "Computer Manufacturing",
    "Computer peripheral equipment",
    "Radio And Television Broadcasting And Communications Equipment",
}
NASDAQ_POWER_INDUSTRIES = {
    "Electric Utilities: Central",
    "Power Generation",
    "Electrical Products",
}

# Domiciles allowed for the screen. US-listed foreign semis (ASML/NXPI/TEL/TSM
# class names) are research-eligible; China is excluded as a matter of policy
# (VIE structure/regulatory risk). Scan-side exchange filters still apply.
NASDAQ_ALLOWED_COUNTRIES = {
    "United States",
    "Ireland",
    "United Kingdom",
    "Taiwan",
    "Netherlands",
    "Switzerland",
    "Germany",
    "Japan",
    "South Korea",
    "Singapore",
    "Israel",
}

NON_COMMON_NAME_PATTERN = re.compile(
    r"\b(warrant|units?|rights?|preferred|depositary|etn|etf|fund|trust|notes?|spac|acquisition)\b",
    re.IGNORECASE,
)
YAHOO_SUFFIX_PATTERN = re.compile(r"[-.^][A-Z]+$|^[A-Z]+\^")
YAHOO_EXCHANGES = {"NMS", "NYQ", "ASE", "NCM", "NGM"}
YAHOO_SCR_IDS = "most_actives,day_gainers,day_losers"


def _to_float(raw: object) -> float | None:
    try:
        out = float(str(raw).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def filter_nasdaq_rows(
    rows: list[dict[str, object]],
    min_cap: float,
    max_cap: float,
    min_volume: float,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = normalize_equity_symbol(row.get("symbol"))
        if not symbol:
            continue
        if str(row.get("country", "")).strip() not in NASDAQ_ALLOWED_COUNTRIES:
            continue
        industry = str(row.get("industry", "")).strip()
        sector = str(row.get("sector", "")).strip()
        is_tech = sector == "Technology" and industry in NASDAQ_TECH_INDUSTRIES
        is_power = industry in NASDAQ_POWER_INDUSTRIES
        if not (is_tech or is_power):
            continue
        if NON_COMMON_NAME_PATTERN.search(str(row.get("name", ""))):
            continue
        cap = _to_float(row.get("marketCap"))
        if cap is None or cap < min_cap or cap > max_cap:
            continue
        volume = _to_float(row.get("volume"))
        if volume is None or volume < min_volume:
            continue
        out.append({"symbol": symbol, "volume": volume, "source": SOURCE_NASDAQ})
    return out


def fetch_nasdaq_universe(
    timeout_sec: int,
    sleep_sec: float,
    min_cap: float,
    max_cap: float,
    min_volume: float,
) -> list[dict[str, object]]:
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    offset = 0
    limit = 25
    while True:
        params = {"tableonly": "true", "limit": str(limit), "offset": str(offset), "download": "true"}
        resp = session.get(NASDAQ_SCREENER_URL, params=params, timeout=timeout_sec)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        batch = data.get("rows", []) if isinstance(data, dict) else []
        fresh = [r for r in batch if isinstance(r, dict) and str(r.get("symbol", "")) not in seen]
        if not fresh:
            break
        for r in fresh:
            seen.add(str(r.get("symbol", "")))
        rows.extend(fresh)
        total = data.get("totalrecords") if isinstance(data, dict) else None
        if total is not None and len(rows) >= int(total):
            break
        if len(batch) < limit:
            break
        offset += len(batch)
        time.sleep(max(0.0, sleep_sec))
        if offset > 20000:  # safety guard
            break
    return filter_nasdaq_rows(rows, min_cap, max_cap, min_volume)


def filter_yahoo_quotes(
    quotes: list[dict[str, object]],
    min_cap: float,
    max_cap: float,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        if str(quote.get("quoteType", "")).upper() != "EQUITY":
            continue
        if str(quote.get("exchange", "")).upper() not in YAHOO_EXCHANGES:
            continue
        symbol = normalize_equity_symbol(quote.get("symbol"))
        if not symbol or YAHOO_SUFFIX_PATTERN.search(symbol):
            continue
        if NON_COMMON_NAME_PATTERN.search(str(quote.get("shortName", ""))):
            continue
        cap_raw = quote.get("marketCap")
        cap = cap_raw.get("raw") if isinstance(cap_raw, dict) else cap_raw
        cap = _to_float(cap)
        if cap is None or cap < min_cap or cap > max_cap:
            continue
        vol_raw = quote.get("regularMarketVolume")
        volume = vol_raw.get("raw") if isinstance(vol_raw, dict) else vol_raw
        volume = _to_float(volume) or 0.0
        out.append({"symbol": symbol, "volume": volume, "source": SOURCE_YAHOO})
    return out


def fetch_yahoo_hot(
    timeout_sec: int,
    sleep_sec: float,
    min_cap: float,
    max_cap: float,
) -> list[dict[str, object]]:
    quotes: list[dict[str, object]] = []
    # Yahoo accepts a single scrIds value per request (combined values -> HTTP 400).
    for scr_id in [s.strip() for s in YAHOO_SCR_IDS.split(",") if s.strip()]:
        params = {
            "count": "100",
            "scrIds": scr_id,
            "formatted": "false",
            "lang": "en-US",
            "region": "US",
        }
        resp = requests.get(
            YAHOO_SCREENER_URL,
            params=params,
            headers={"User-Agent": BROWSER_UA},
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        payload = resp.json()
        results = payload.get("finance", {}).get("result", []) if isinstance(payload, dict) else []
        for block in results:
            if isinstance(block, dict) and isinstance(block.get("quotes"), list):
                quotes.extend(block["quotes"])
        time.sleep(max(0.0, sleep_sec))
    return filter_yahoo_quotes(quotes, min_cap, max_cap)


def restrict_to_nasdaq(
    yahoo_rows: list[dict[str, object]],
    nasdaq_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep only Yahoo hot names that also pass the Nasdaq AI-industry screen.

    The Yahoo hot lists carry no sector/industry fields, so without this the
    bucket would be polluted by hot non-AI names (retail/meme stocks).
    """
    allowed = {str(r["symbol"]) for r in nasdaq_rows}
    return [r for r in yahoo_rows if str(r["symbol"]) in allowed]


def load_manual_symbols(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if "symbol" not in frame.columns:
        return []
    out: list[dict[str, object]] = []
    for raw in frame["symbol"].tolist():
        symbol = normalize_equity_symbol(raw)
        if symbol:
            out.append({"symbol": symbol, "volume": 0.0, "source": SOURCE_MANUAL})
    return out


def merge_universe(
    candidates: list[dict[str, object]],
    existing_symbols: set[str],
    max_symbols: int,
) -> pd.DataFrame:
    # Manual entries first, then Nasdaq/Yahoo by volume desc.
    manual = [c for c in candidates if c["source"] == SOURCE_MANUAL]
    rest = [c for c in candidates if c["source"] != SOURCE_MANUAL]
    rest.sort(key=lambda c: float(c.get("volume") or 0.0), reverse=True)

    merged: dict[str, dict[str, object]] = {}
    for cand in manual + rest:
        symbol = str(cand["symbol"])
        if symbol in existing_symbols or symbol in merged:
            if symbol in merged:
                prev = str(merged[symbol]["source"])
                if cand["source"] not in prev.split(","):
                    merged[symbol]["source"] = f"{prev},{cand['source']}"
            continue
        merged[symbol] = {"symbol": symbol, "volume": cand.get("volume") or 0.0, "source": cand["source"]}
        if len(merged) >= max(1, max_symbols):
            break

    now_iso = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "symbol": symbol,
            "bucket": BUCKET,
            "etf_count": 0,
            "etfs": info["source"],
            "enabled": 1,
            "updated_utc": now_iso,
        }
        for symbol, info in merged.items()
    ]
    return pd.DataFrame(rows, columns=["symbol", "bucket", "etf_count", "etfs", "enabled", "updated_utc"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build ai_smallcap watchlist universe (Nasdaq screen + Yahoo hot lists + manual CSV).")
    p.add_argument("--config", default="configs/config.balanced.json", help="Scanner config path (for watchlist_csv_path).")
    p.add_argument("--output", default=None, help="Optional output csv path override.")
    p.add_argument("--sources", default="nasdaq,yahoo,manual", help="Comma list of: nasdaq,yahoo,manual.")
    p.add_argument("--manual-csv", default="data/ai_smallcap_manual.csv", help="Manual symbol list path.")
    p.add_argument("--market-cap-min", type=float, default=300_000_000.0)
    p.add_argument("--market-cap-max", type=float, default=80_000_000_000.0)
    p.add_argument("--min-volume", type=float, default=100_000.0, help="Nasdaq daily volume floor.")
    p.add_argument("--max-symbols", type=int, default=400, help="Cap on new ai_smallcap rows.")
    p.add_argument("--request-timeout-sec", type=int, default=20)
    p.add_argument("--sleep-sec", type=float, default=1.0)
    p.add_argument("--offline", action="store_true", help="Skip network sources (manual CSV only).")
    p.add_argument("--dry-run", action="store_true", help="Print counts without writing.")
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg: ScanConfig = load_config(args.config)
    sources = {s.strip().lower() for s in str(args.sources).split(",") if s.strip()}

    candidates: list[dict[str, object]] = []
    failures: list[str] = []
    use_network = not args.offline
    nasdaq_rows: list[dict[str, object]] = []
    if use_network and "nasdaq" in sources:
        try:
            nasdaq_rows = fetch_nasdaq_universe(
                args.request_timeout_sec, args.sleep_sec,
                args.market_cap_min, args.market_cap_max, args.min_volume,
            )
            candidates.extend(nasdaq_rows)
            print(f"[smallcap] nasdaq rows={len(nasdaq_rows)}")
        except Exception as exc:
            failures.append(f"nasdaq:{exc.__class__.__name__}")
    if use_network and "yahoo" in sources:
        try:
            got = fetch_yahoo_hot(args.request_timeout_sec, args.sleep_sec, args.market_cap_min, args.market_cap_max)
            if nasdaq_rows:
                kept = restrict_to_nasdaq(got, nasdaq_rows)
            else:
                kept = got
                print("[smallcap] warning: nasdaq unavailable, yahoo rows kept unfiltered")
            candidates.extend(kept)
            print(f"[smallcap] yahoo rows={len(got)} kept={len(kept)}")
        except Exception as exc:
            failures.append(f"yahoo:{exc.__class__.__name__}")
    if "manual" in sources:
        got = load_manual_symbols(Path(args.manual_csv))
        candidates.extend(got)
        print(f"[smallcap] manual rows={len(got)}")
    if failures:
        print(f"[smallcap] source failures: {','.join(failures)}")
    if not candidates:
        raise SystemExit("[smallcap] no candidates from any source; nothing to write.")

    out = Path(args.output) if args.output else Path(cfg.watchlist_csv_path)
    existing = pd.DataFrame()
    if out.exists():
        existing = pd.read_csv(out)
    existing_symbols = set()
    if not existing.empty and "symbol" in existing.columns:
        # Exclude ai_smallcap rows: the layer is rebuilt from scratch below.
        keep_mask = pd.Series(True, index=existing.index)
        if "bucket" in existing.columns:
            keep_mask = existing["bucket"].astype(str).str.lower() != BUCKET
        existing_symbols = {
            normalize_equity_symbol(s) for s in existing.loc[keep_mask, "symbol"].tolist()
        }
        existing_symbols.discard("")

    new_rows = merge_universe(candidates, existing_symbols, args.max_symbols)
    print(f"[smallcap] new ai_smallcap rows={len(new_rows)} (existing watchlist symbols skipped)")
    if args.dry_run:
        print(new_rows[["symbol", "etfs"]].to_string(index=False))
        return
    # Rebuild the ai_smallcap layer from scratch so stale rows (e.g. names that
    # no longer pass the industry screen) are pruned automatically.
    if not existing.empty and "bucket" in existing.columns:
        pruned = int((existing["bucket"].astype(str).str.lower() == BUCKET).sum())
        existing = existing[existing["bucket"].astype(str).str.lower() != BUCKET]
        if pruned:
            print(f"[smallcap] pruned stale ai_smallcap rows={pruned}")
    combined = pd.concat([existing, new_rows], ignore_index=True) if not existing.empty else new_rows
    combined = combined.sort_values(["bucket", "symbol"]).drop_duplicates(subset=["symbol", "bucket"], keep="first")
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    print(f"[smallcap] output={out} total_rows={len(combined)}")


if __name__ == "__main__":
    main()
