"""Dedicated daily cron orchestrator: SEC prewarm (Stage 1) + MVP scan (Stage 2).

Single-responsibility split:
- ``scripts/refresh_sec_cache.py`` ONLY refreshes the SEC parsed cache and
  must never trigger a stock scan.
- This script wires Stage 1 (``run_sec_prewarm``) to Stage 2
  (``run_daily_scan_after_prewarm``) for the daily scheduled run.

Example crontab (machine timezone UTC+8; 11:00 local is after the US market
close and the 22:00 ET EDGAR filing cutoff):
    0 11 * * * cd <repo> && .venv/bin/python scripts/run_daily_cron.py \
        --config configs/config.risk_off.json >> .debug_logs/daily_cron.log 2>&1
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refresh_sec_cache import (  # noqa: E402
    ScanConfig,
    load_config,
    log,
    run_sec_prewarm,
)
from ai_value_scanner.scanner import run_scan  # noqa: E402


def run_daily_scan_after_prewarm(
    cfg: ScanConfig,
    *,
    config_path: str,
    summary: Mapping[str, Any],
    limit: int = 0,
    skip_scan: bool = False,
    alpaca_ttl_sec: int = 3600,
    scan_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Stage 2 of the unified daily cron: full MVP scan right after prewarm.

    Forces a short Alpaca freshness window (default 1h) so the cron scan
    always fetches fresh post-close market data even if a manual scan ran the
    night before, while 100% reusing the SEC parsed caches just written by
    Stage 1 (they are minutes old). Pure decision logic; all network I/O
    stays inside ``scan_fn``/``run_scan``.
    """
    if skip_scan or (limit and limit > 0):
        return {
            "scan_executed": False,
            "scan_failed": False,
            "reason": "skipped_by_flag_or_limit",
        }
    if summary.get("aborted") is True or bool(summary.get("conflicted")):
        return {
            "scan_executed": False,
            "scan_failed": False,
            "reason": "aborted_or_conflicted_prewarm",
        }
    scan_cfg = dataclasses.replace(
        cfg,
        alpaca_cache_ttl_assets_sec=min(cfg.alpaca_cache_ttl_assets_sec, alpaca_ttl_sec),
        alpaca_cache_ttl_snapshots_sec=min(cfg.alpaca_cache_ttl_snapshots_sec, alpaca_ttl_sec),
        alpaca_cache_ttl_bars_sec=min(cfg.alpaca_cache_ttl_bars_sec, alpaca_ttl_sec),
    )
    try:
        out_path = (scan_fn or run_scan)(
            scan_cfg,
            scan_config_path=config_path,
            allow_existing_decision_snapshot=True,
        )
    except Exception as exc:  # noqa: BLE001 - cron must report, not crash
        log(f"ERROR: daily MVP scan failed: {type(exc).__name__}: {exc}")
        return {"scan_executed": False, "scan_failed": True, "error": str(exc)}
    return {"scan_executed": True, "scan_failed": False, "output_path": str(out_path)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily cron: SEC prewarm (Stage 1) + MVP scan (Stage 2)."
    )
    parser.add_argument("--config", default="configs/config.risk_off.json")
    parser.add_argument("--max-age-hours", type=float, default=4.0)
    parser.add_argument(
        "--alpaca-ttl-sec",
        type=int,
        default=3600,
        help="Stage 2 Alpaca freshness window in seconds.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test cap")
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        default=False,
        help="Only run Stage 1 SEC prewarm; skip the Stage 2 daily MVP scan.",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    load_dotenv(repo / ".env")
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        parser.error("SEC_USER_AGENT is required (set it in repo/.env or the cron environment)")
    if not 0 < args.max_age_hours <= 24:
        parser.error("--max-age-hours must be >0 and <=24")
    if not args.alpaca_ttl_sec > 0:
        parser.error("--alpaca-ttl-sec must be positive")
    cfg: ScanConfig = load_config(args.config)
    if cfg.sec_cache_ttl_submissions_sec <= 0:
        parser.error("sec_cache_ttl_submissions_sec must be positive for scan-side parsed-cache reuse")

    # Stage 1: pure SEC prewarm (shared implementation, never scans).
    summary = run_sec_prewarm(
        cfg,
        repo=repo,
        user_agent=user_agent,
        max_age_hours=args.max_age_hours,
        limit=args.limit,
    )
    # Stage 2: full MVP scan on the just-warmed SEC cache. Skipped for
    # smoke-test caps, --skip-scan runs, aborted or conflicted prewarms,
    # and environments without Alpaca credentials.
    if not args.skip_scan and not (args.limit and args.limit > 0):
        if os.getenv("ALPACA_API_KEY", "").strip():
            scan_res = run_daily_scan_after_prewarm(
                cfg,
                config_path=args.config,
                summary=summary,
                limit=args.limit,
                skip_scan=args.skip_scan,
                alpaca_ttl_sec=args.alpaca_ttl_sec,
            )
            if scan_res.get("scan_executed"):
                log(f"daily MVP scan finished: {scan_res.get('output_path')}")
            elif scan_res.get("scan_failed"):
                log(f"ERROR: daily MVP scan failed: {scan_res.get('error')}")
                sys.exit(1)
            else:
                log(f"daily MVP scan not executed: {scan_res.get('reason')}")
        else:
            log("WARNING: ALPACA_API_KEY not set; skipping Stage 2 daily scan")
    if summary["failed"] or summary["aborted"] or summary["conflicted"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
