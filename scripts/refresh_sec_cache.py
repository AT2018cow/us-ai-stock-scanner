"""Scheduled SEC cache refresher: pre-warm submissions + companyfacts once daily.

EDGAR accepts filings 6:00-22:00 ET weekdays (nothing arrives 22:00-06:00 ET).
A single daily refresh after the 22:00 ET cutoff — e.g. 22:30 ET / 02:30 UTC —
covers every filing available at the daily run (01:33 ET), so the run reads
the cache with zero downloads.

Design:
- Covers the union of all watchlist universes (main + 5 themes + 5 ventures).
- Skip-if-fresh: submissions cache files newer than --max-age-hours are left
  alone, so extra invocations are no-ops.
- Companyfacts uses the same incremental rule as live runs (refetch only when
  the fresh submissions show a newer filing).
- Cache writes are atomic (tmp + rename) so a concurrent daily_run can never
  read a torn file.

Typical crontab (system TZ = UTC+8; 10:30 local = 22:30 ET = 02:30 UTC):
    30 10 * * *  cd <repo> && .venv/bin/python scripts/refresh_sec_cache.py \
        >> .debug_logs/sec_refresh_cron.log 2>&1
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.backtest import load_sec_client  # noqa: E402
from ai_value_scanner.scanner import (  # noqa: E402
    NetworkMonitor,
    RequestRateLimiter,
    ScanConfig,
    build_session,
    load_config,
)


def log(msg: str) -> None:
    stamp = time.strftime("%H:%M:%S", time.gmtime())
    print(f"[sec_refresh {stamp}] {msg}", flush=True)


def collect_symbols(repo: Path) -> tuple[list[str], list[str]]:
    """Union of all watchlist universes. Returns (symbols, source_files)."""
    import glob

    symbols: set[str] = set()
    files: list[str] = [str(repo / "data" / "ai_watchlist.csv")]
    files += sorted(glob.glob(str(repo / "data" / "theme_watchlist_*.csv")))
    files += sorted(glob.glob(str(repo / "data" / "venture_watchlist_*.csv")))
    for path in files:
        f = Path(path)
        if not f.exists():
            continue
        try:
            df = pd.read_csv(f)
        except Exception as exc:
            log(f"WARNING: {f.name}: {exc}")
            continue
        if "symbol" not in df.columns:
            continue
        symbols.update(df["symbol"].dropna().astype(str).str.upper())
    return sorted(symbols), files


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-warm the SEC submissions/companyfacts cache.")
    parser.add_argument("--config", default="configs/config.risk_off.json")
    parser.add_argument("--max-age-hours", type=float, default=20.0,
                        help="Skip a submission file if its cache is younger than this (hours).")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap for smoke tests.")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    cfg: ScanConfig = load_config(args.config)
    monitor = NetworkMonitor()
    import os

    from ai_value_scanner.scanner import SecClient

    sec = SecClient(
        session=build_session(),
        user_agent=os.getenv("SEC_USER_AGENT", "").strip(),
        timeout_sec=cfg.request_timeout_sec,
        cache_dir=Path(cfg.cache_dir),
        request_limiter=RequestRateLimiter(cfg.sec_max_requests_per_sec, monitor=monitor, service_name="sec"),
        monitor=monitor,
        submissions_ttl_sec=0,  # the script decides freshness via max-age, not TTL
    )

    symbols, sources = collect_symbols(repo)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
    if not symbols:
        log("no symbols found — check data/ watchlists")
        sys.exit(1)
    log(f"universes: {len(sources)} files -> {len(symbols)} symbols")

    mapping = sec.ticker_mapping()
    mapped = mapping.set_index("symbol")["cik"].to_dict() if not mapping.empty else {}

    max_age_sec = args.max_age_hours * 3600.0
    now = time.time()
    refreshed, skipped, no_cik, failed = 0, 0, [], 0
    t0 = time.monotonic()

    for i, symbol in enumerate(symbols, 1):
        cik = mapped.get(symbol)
        if not cik:
            no_cik.append(symbol)
            continue
        cache_path = Path(cfg.cache_dir) / f"submissions_{cik}.json"
        if cache_path.exists() and now - cache_path.stat().st_mtime < max_age_sec:
            skipped += 1
        else:
            try:
                # Delete the stale parsed cache so load_one_fundamental
                # recomputes from the fresh submissions/companyfacts and
                # writes a new parsed cache for the daily run to consume.
                parsed_path = Path(cfg.cache_dir) / f"parsed_fund_{cik}.json"
                if parsed_path.exists():
                    parsed_path.unlink()
                # Fetches submissions + companyfacts (incremental), parses
                # the 4 MB JSON, computes TTM/YoY/quality, and writes
                # parsed_fund_{cik}.json — the daily run reads this instead.
                from ai_value_scanner.scanner import load_one_fundamental

                load_one_fundamental(sec, symbol, cik, cfg)
                refreshed += 1
            except Exception as exc:
                failed += 1
                log(f"WARNING: {symbol} (CIK {cik}): {type(exc).__name__}: {exc}")
        if i % 100 == 0 or i == len(symbols):
            elapsed = time.monotonic() - t0
            log(f"progress {i}/{len(symbols)} | refreshed={refreshed} skipped={skipped} "
                f"failed={failed} ({elapsed / max(1, i) * len(symbols) / 60:.1f} min projected)")

    elapsed = time.monotonic() - started
    log(f"done in {elapsed / 60:.1f} min | refreshed={refreshed} skipped={skipped} "
        f"no_cik={len(no_cik)} failed={failed}")
    if no_cik:
        log(f"WARNING: symbols without SEC mapping (excluded from refresh): "
            f"{', '.join(no_cik[:20])}{'...' if len(no_cik) > 20 else ''}")
    if failed and refreshed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
