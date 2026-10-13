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
import random
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
    load_one_fundamental,
)

# Retry policy for the nightly burst: EDGAR throttles sustained sessions
# with HTTP 403 even at modest rates. Production evidence (2026-10-13):
# a long-lived session accumulates 403s that burn the full backoff schedule
# and still fail, while the SAME CIKs succeed instantly from a parallel
# fresh session. I.e. the throttle flag sticks to the session, so each
# retry must rotate to a new session (new TCP connections) to recover.
# Retry only transient network/server/throttle errors, never data bugs.
RETRYABLE_STATUS = frozenset({403, 408, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
BACKOFF_SCHEDULE_SEC = (5.0, 15.0, 30.0, 60.0)
CIRCUIT_CONSECUTIVE_FAILS = 10
CIRCUIT_PAUSE_SEC = 180.0


def _is_retryable(exc: BaseException) -> bool:
    import requests

    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return exc.__class__.__name__ == "HTTPError" and int(status or 0) in RETRYABLE_STATUS
    except (TypeError, ValueError):
        return False


def _load_with_retry(load_fn, symbol, cik, cfg, *, sleep=time.sleep,
                     on_retry=None):
    """Call load_fn(symbol, cik, cfg) with bounded retries. Returns (ok, attempts).

    on_retry, if given, is called with the caught retryable exception before
    each backoff sleep (lets the caller rotate a throttled session first).
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            load_fn(symbol, cik, cfg)
            return True, attempts
        except Exception as exc:  # noqa: BLE001 - classified below
            if not _is_retryable(exc) or attempts >= MAX_ATTEMPTS:
                raise
            if on_retry is not None:
                on_retry(exc)
            index = min(attempts - 1, len(BACKOFF_SCHEDULE_SEC) - 1)
            delay = BACKOFF_SCHEDULE_SEC[index] + random.uniform(0, 2.0)
            sleep(delay)
    return False, attempts  # unreachable


def _circuit_pause_sec(pauses: int) -> float:
    """Escalating pause for host-level throttle episodes (cap 30 min)."""
    return min(CIRCUIT_PAUSE_SEC * (2.0 ** max(0, pauses)), 1800.0)


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

    max_age_sec = args.max_age_hours * 3600.0

    from ai_value_scanner.scanner import SecClient

    def make_sec() -> "SecClient":
        return SecClient(
            session=build_session(),
            user_agent=os.getenv("SEC_USER_AGENT", "").strip(),
            timeout_sec=cfg.request_timeout_sec,
            cache_dir=Path(cfg.cache_dir),
            request_limiter=RequestRateLimiter(cfg.sec_max_requests_per_sec, monitor=monitor, service_name="sec"),
            monitor=monitor,
            # Use the script's max-age as the submissions TTL: if the daily run
            # already fetched submissions within max_age, reuse the cache (no
            # network) and only do the CPU-heavy parsing + parsed-cache write.
            submissions_ttl_sec=int(max_age_sec),
        )

    sec = make_sec()
    # Mutable holder so the retry path can rotate a throttled session
    # without rebinding the closure used by load_one_fundamental.
    client = {"sec": sec}

    def rotate_session(exc: BaseException | None = None) -> None:
        try:
            client["sec"].session.close()
        except Exception:  # noqa: BLE001 - best effort; GC reclaims the rest
            pass
        client["sec"] = make_sec()
        reason = f"after {type(exc).__name__}" if exc is not None else "(proactive)"
        log(f"session rotated {reason}")

    symbols, sources = collect_symbols(repo)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
    if not symbols:
        log("no symbols found — check data/ watchlists")
        sys.exit(1)
    log(f"universes: {len(sources)} files -> {len(symbols)} symbols")

    mapping = sec.ticker_mapping()
    mapped = mapping.set_index("symbol")["cik"].to_dict() if not mapping.empty else {}

    now = time.time()
    refreshed, skipped, no_cik, failed = 0, 0, [], 0
    retried_ok, circuit_pauses, consec_fails = 0, 0, 0
    t0 = time.monotonic()

    for i, symbol in enumerate(symbols, 1):
        cik = mapped.get(symbol)
        if not cik:
            no_cik.append(symbol)
            continue
        # Proactive rotation: EDGAR flags sessions with 403s after only a
        # handful of symbols (production 2026-10-13: a fresh session often
        # 403s within ~3 symbols). Cycling connections every 10 symbols keeps
        # sessions small; the reactive retry path covers the rest. Kept at 10
        # rather than lower to avoid rapid session cycling looking abusive.
        if i % 10 == 0:
            rotate_session()
        # Skip check is based on the PARSED cache age (the actual deliverable),
        # not the submissions cache age. A fresh submissions cache without a
        # parsed cache still needs processing (the daily run fetched the raw
        # data but the parsed result was never computed).
        parsed_path = Path(cfg.cache_dir) / f"parsed_fund_{cik}.json"
        if parsed_path.exists() and now - parsed_path.stat().st_mtime < max_age_sec:
            skipped += 1
        else:
            try:
                # Delete any stale parsed cache so load_one_fundamental
                # recomputes from the fresh submissions/companyfacts and
                # writes a new parsed cache for the daily run to consume.
                if parsed_path.exists():
                    parsed_path.unlink()
                # Fetches submissions + companyfacts (incremental via the
                # script's own TTL=max_age), parses the 4 MB JSON, computes
                # TTM/YoY/quality, and writes parsed_fund_{cik}.json.
                # Transient EDGAR throttling (403/429/5xx around the
                # publication cutoff) is retried with backoff + session
                # rotation; data bugs fail fast.
                ok, attempts = _load_with_retry(
                    lambda s, c, g: load_one_fundamental(client["sec"], s, c, g),
                    symbol, cik, cfg,
                    on_retry=rotate_session,
                )
                if attempts > 1:
                    retried_ok += 1
                refreshed += 1
                consec_fails = 0
            except Exception as exc:
                failed += 1
                consec_fails += 1
                log(f"WARNING: {symbol} (CIK {cik}): {type(exc).__name__}: {exc}")
                # Circuit breaker: a streak of consecutive failures means a
                # throttle episode, not bad symbols. Pausing once is cheaper
                # than burning the full backoff schedule on every symbol.
                # Skipped during --limit smoke runs to keep them fast.
                if (consec_fails >= CIRCUIT_CONSECUTIVE_FAILS
                        and not (args.limit and args.limit > 0)):
                    pause = _circuit_pause_sec(circuit_pauses)
                    log(f"CIRCUIT: {consec_fails} consecutive failures; "
                        f"pausing {pause:.0f}s")
                    time.sleep(pause)
                    circuit_pauses += 1
                    consec_fails = 0
        if i % 100 == 0 or i == len(symbols):
            elapsed = time.monotonic() - t0
            log(f"progress {i}/{len(symbols)} | refreshed={refreshed} skipped={skipped} "
                f"failed={failed} retried_ok={retried_ok} pauses={circuit_pauses} "
                f"({elapsed / max(1, i) * len(symbols) / 60:.1f} min projected)")

    elapsed = time.monotonic() - started
    log(f"done in {elapsed / 60:.1f} min | refreshed={refreshed} skipped={skipped} "
        f"no_cik={len(no_cik)} failed={failed} retried_ok={retried_ok} pauses={circuit_pauses}")
    if no_cik:
        log(f"WARNING: symbols without SEC mapping (excluded from refresh): "
            f"{', '.join(no_cik[:20])}{'...' if len(no_cik) > 20 else ''}")
    if failed and refreshed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
