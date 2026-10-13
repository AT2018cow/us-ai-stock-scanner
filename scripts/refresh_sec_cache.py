"""Client-side scheduled SEC prewarm: refresh, parse, verify cache for the next scan.

Runs on the same machine and cache directory as the scanner; NOT a Modal job.
Failures are reported, never hidden behind a fresh-looking parsed-cache mtime.
Only validated parsed results are counted as ready; existing files are preserved
until the canonical parser atomically replaces them.

Example crontab when the machine timezone is Asia/Singapore:
    30 11 * * * cd <repo> && .venv/bin/python scripts/refresh_sec_cache.py \
        >> .debug_logs/sec_refresh_cron.log 2>&1

11:30 SGT is 23:30 EDT or 22:30 EST, after the 22:00 ET EDGAR intake
cutoff. Allow enough time for this foreground task to FINISH before scanning.
SEC propagation and publication can lag; the latest facts may remain pending.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import (  # noqa: E402
    NetworkMonitor,
    RequestRateLimiter,
    ScanConfig,
    SecClient,
    load_config,
    load_one_fundamental,
    load_valid_parsed_fundamental_cache,
)

RETRYABLE_STATUS = frozenset({403, 408, 429, 500, 502, 503, 504})
THROTTLE_STATUS = frozenset({403, 429})
MAX_TRANSIENT_ATTEMPTS = 3
MAX_THROTTLE_ATTEMPTS = 2
TRANSIENT_BACKOFF_SEC = (5.0, 15.0)
THROTTLE_COOLDOWN_SEC = 180.0
MAX_THROTTLE_COOLDOWN_SEC = 1800.0
MAX_CONSECUTIVE_FAILURES = 5


class SecThrottleCircuitOpen(RuntimeError):
    """Stop the whole job rather than cycling sessions around SEC throttling."""


def _http_status(exc: BaseException) -> int | None:
    if not isinstance(exc, requests.HTTPError):
        return None
    status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
        _http_status(exc) in RETRYABLE_STATUS
    )


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    raw = response.headers.get("Retry-After") if response is not None else None
    if not raw:
        return None
    try:
        delay = float(raw)
        return max(0.0, delay) if delay < float("inf") else None
    except (TypeError, ValueError):
        # HTTP-date Retry-After is uncommon here; fail closed by stopping
        # rather than retrying before an unknown server-requested deadline.
        raise SecThrottleCircuitOpen("SEC Retry-After is not a numeric delay") from exc


def _load_with_retry(
    load_fn: Callable[..., Any],
    symbol: str,
    cik: str,
    cfg: ScanConfig,
    *,
    sleep: Callable[[float], Any] = time.sleep,
    on_retry: Callable[[BaseException], None] | None = None,
) -> tuple[bool, int]:
    """Retry transport/5xx modestly; one global-cooldown retry for 403/429.

    A repeated 403/429 opens the circuit. Never rotate sessions on an HTTP
    throttle; the user agent and rate/policy need attention, not fresh sockets.
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            load_fn(symbol, cik, cfg)
            return True, attempts
        except Exception as exc:  # noqa: BLE001 - explicit classification
            if not _is_retryable(exc):
                raise
            status = _http_status(exc)
            if status in THROTTLE_STATUS:
                if attempts >= MAX_THROTTLE_ATTEMPTS:
                    raise SecThrottleCircuitOpen(
                        f"SEC HTTP {status} persisted after a global cooldown "
                        f"(CIK {cik}); aborting refresh"
                    ) from exc
                delay = max(
                    THROTTLE_COOLDOWN_SEC,
                    _retry_after_seconds(exc) or 0.0,
                )
                if delay > MAX_THROTTLE_COOLDOWN_SEC:
                    raise SecThrottleCircuitOpen(
                        f"SEC requested {delay:.0f}s Retry-After; aborting "
                        "rather than holding or retrying too soon"
                    ) from exc
                sleep(delay)
            else:
                if attempts >= MAX_TRANSIENT_ATTEMPTS:
                    raise
                if (
                    on_retry is not None
                    and isinstance(exc, (requests.ConnectionError, requests.Timeout))
                ):
                    on_retry(exc)
                delay = TRANSIENT_BACKOFF_SEC[
                    min(attempts - 1, len(TRANSIENT_BACKOFF_SEC) - 1)
                ] + random.uniform(0, 2.0)
                sleep(delay)


def log(msg: str) -> None:
    stamp = time.strftime("%H:%M:%S", time.gmtime())
    print(f"[sec_refresh {stamp}] {msg}", flush=True)


def collect_symbols(repo: Path, cfg: ScanConfig) -> tuple[list[str], list[str]]:
    """Existing local watchlists plus configured opt-in US Core/Manual sources."""
    import glob

    raw_files = [str(repo / cfg.watchlist_csv_path)]
    raw_files += sorted(glob.glob(str(repo / "data" / "theme_watchlist_*.csv")))
    raw_files += sorted(glob.glob(str(repo / "data" / "venture_watchlist_*.csv")))
    for value in (cfg.discovery_source_files or {}).values():
        source_path = Path(value)
        raw_files.append(str(source_path if source_path.is_absolute() else repo / source_path))
    files = list(dict.fromkeys(raw_files))
    symbols: set[str] = set()
    for name in files:
        file_path = Path(name)
        if not file_path.exists():
            log(f"WARNING: source missing: {file_path}")
            continue
        try:
            frame = pd.read_csv(file_path)
            if "symbol" not in frame.columns:
                log(f"WARNING: source lacks symbol column: {file_path}")
                continue
            symbols.update(
                str(s).strip().upper() for s in frame["symbol"].dropna().tolist()
                if str(s).strip()
            )
        except Exception as exc:
            log(f"WARNING: cannot read {file_path}: {type(exc).__name__}: {exc}")
    return sorted(symbols), files


def refresh_symbols(
    symbols: list[str],
    mapped: dict[str, str],
    sec: SecClient,
    cfg: ScanConfig,
    *,
    max_age_sec: float,
    conflicting: set[str] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, Any]:
    """Prewarm on one client and cache; return an honest run summary.

    Reuses the scanner's exact raw/identity/content-sha/TTL eligibility test.
    Nothing is deleted before a network fetch: cache writes stay atomic in
    load_one_fundamental; invalid or pending facts are never called refreshed.
    """
    summary: dict[str, Any] = {
        "total": len(symbols), "refreshed": 0, "skipped_valid": 0,
        "no_cik": [], "conflicted": [], "failed": 0, "incomplete": 0,
        "retried_ok": 0, "aborted": False,
    }
    conflicts = conflicting or set()
    consecutive_failures = 0
    t0 = time.monotonic()

    def rotate_transport_session(exc: BaseException) -> None:
        # Only a transport error can justify changing broken TCP connections.
        # Crucially, the SEC limiter and frozen ticker map remain on the SAME
        # SecClient across the swap, and 403/429 never trigger this callback.
        old_session = sec.session
        sec.session = requests.Session()
        old_session.close()
        log(f"transport session renewed after {type(exc).__name__}")

    for index, symbol in enumerate(symbols, 1):
        cik = mapped.get(symbol)
        if symbol in conflicts:
            summary["conflicted"].append(symbol)
            continue
        if not cik:
            summary["no_cik"].append(symbol)
            continue
        valid = load_valid_parsed_fundamental_cache(
            sec, symbol, cik, cfg, max_age_sec=max_age_sec
        )
        if valid is not None:
            summary["skipped_valid"] += 1
            continue
        try:
            _, attempts = _load_with_retry(
                lambda s, c, config: load_one_fundamental(
                    sec, s, c, config, force_refresh_parsed=True
                ),
                symbol, cik, cfg, sleep=sleep, on_retry=rotate_transport_session,
            )
            # A successful function return does not guarantee persistence:
            # companyfacts can lag a recent accession and intentionally
            # suppress the parsed write. Count it as INCOMPLETE, not success.
            valid = load_valid_parsed_fundamental_cache(
                sec, symbol, cik, cfg, max_age_sec=max_age_sec
            )
            if valid is None:
                summary["incomplete"] += 1
                summary["failed"] += 1
                consecutive_failures += 1
                log(f"WARNING: {symbol} CIK {cik}: no eligible parsed cache "
                    "(pending facts, missing cache, or provenance mismatch)")
            else:
                summary["refreshed"] += 1
                consecutive_failures = 0
                if attempts > 1:
                    summary["retried_ok"] += 1
        except SecThrottleCircuitOpen as exc:
            summary["failed"] += 1
            summary["aborted"] = True
            log(f"CIRCUIT OPEN: {exc}")
            break
        except Exception as exc:
            summary["failed"] += 1
            consecutive_failures += 1
            log(f"WARNING: {symbol} CIK {cik}: {type(exc).__name__}: {exc}")

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            log(f"CIRCUIT OPEN: {consecutive_failures} consecutive failures; "
                "aborting rather than repeatedly contacting SEC")
            summary["aborted"] = True
            break
        if index % 100 == 0 or index == len(symbols):
            elapsed = time.monotonic() - t0
            log(
                f"progress {index}/{len(symbols)} "
                f"refreshed={summary['refreshed']} valid_skips={summary['skipped_valid']} "
                f"failed={summary['failed']} incomplete={summary['incomplete']} "
                f"retried_ok={summary['retried_ok']} elapsed={elapsed / 60:.1f}m"
            )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Client-side SEC parsed-cache prewarm.")
    parser.add_argument("--config", default="configs/config.risk_off.json")
    parser.add_argument("--max-age-hours", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test cap")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    load_dotenv(repo / ".env")
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        parser.error("SEC_USER_AGENT is required (set it in repo/.env or the cron environment)")
    if not 0 < args.max_age_hours <= 24:
        parser.error("--max-age-hours must be >0 and <=24")
    cfg: ScanConfig = load_config(args.config)
    if cfg.sec_cache_ttl_submissions_sec <= 0:
        parser.error("sec_cache_ttl_submissions_sec must be positive for scan-side parsed-cache reuse")

    started = time.monotonic()
    monitor = NetworkMonitor()
    sec = SecClient(
        session=requests.Session(),  # No hidden HTTPAdapter retries bypassing the limiter.
        user_agent=user_agent,
        timeout_sec=cfg.request_timeout_sec,
        cache_dir=Path(cfg.cache_dir),
        request_limiter=RequestRateLimiter(
            cfg.sec_max_requests_per_sec, monitor=monitor, service_name="sec"
        ),
        monitor=monitor,
        submissions_ttl_sec=int(args.max_age_hours * 3600),
    )
    try:
        symbols, sources = collect_symbols(repo, cfg)
        if args.limit and args.limit > 0:
            symbols = symbols[:args.limit]
        if not symbols:
            log("ERROR: no symbols found; check configured client watchlists")
            sys.exit(1)
        log(f"client SEC prewarm: {len(sources)} files / {len(symbols)} symbols")
        snapshot = sec.ticker_map_snapshot()  # frozen across session renewals
        frame = snapshot["frame"]
        mapped = frame.set_index("symbol")["cik"].to_dict() if not frame.empty else {}
        summary = refresh_symbols(
            symbols, mapped, sec, cfg, max_age_sec=args.max_age_hours * 3600,
            conflicting=set(snapshot["conflicts"]),
        )
        log(
            f"done in {(time.monotonic() - started)/60:.1f}m "
            f"refreshed={summary['refreshed']} valid_skips={summary['skipped_valid']} "
            f"no_cik={len(summary['no_cik'])} conflicts={len(summary['conflicted'])} "
            f"failed={summary['failed']} incomplete={summary['incomplete']} "
            f"retried_ok={summary['retried_ok']} aborted={summary['aborted']}"
        )
        if summary["no_cik"]:
            log(f"WARNING: unmapped symbols: {', '.join(summary['no_cik'][:20])}")
        if summary["conflicted"]:
            log(f"ERROR: mapping conflict symbols: {', '.join(summary['conflicted'][:20])}")
        if summary["failed"] or summary["aborted"] or summary["conflicted"]:
            sys.exit(1)
    finally:
        sec.session.close()


if __name__ == "__main__":
    main()
