"""Dedicated daily cron orchestrator: SEC prewarm (Stage 1) + MVP scan (Stage 2).

Single-responsibility split:
- ``scripts/refresh_sec_cache.py`` ONLY refreshes the SEC parsed cache and
  must never trigger a stock scan.
- This script wires Stage 1 (``run_sec_prewarm``) to Stage 2
  (``run_daily_scan_after_prewarm``) for the daily scheduled run.

Example crontab (machine timezone UTC+8; 11:00 local is after the US market
close and the 22:00 ET EDGAR filing cutoff):
    0 11 * * * cd <repo> && .venv/bin/python scripts/run_daily_cron.py \
        --config configs/config.production.json >> .debug_logs/daily_cron.log 2>&1
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refresh_sec_cache import (  # noqa: E402
    ScanConfig,
    load_config,
    log,
    run_sec_prewarm,
)
from ai_value_scanner.scanner import OfficialPublicationError, run_scan_with_status  # noqa: E402
from ai_value_scanner.market_data import sip_publication_window  # noqa: E402
from ai_value_scanner.reporting.publication import (  # noqa: E402
    read_latest_publication,
    write_publication_attempt,
)
from ai_value_scanner.reporting.snapshot import resolve_git_commit_sha  # noqa: E402


def run_daily_scan_after_prewarm(
    cfg: ScanConfig,
    *,
    config_path: str,
    summary: Mapping[str, Any],
    limit: int = 0,
    skip_scan: bool = False,
    alpaca_ttl_sec: int = 3600,
    scan_fn: Callable[..., Any] | None = None,
    scan_now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Stage 2 of the unified daily cron: full MVP scan right after prewarm.

    Forces a short Alpaca freshness window (default 1h) so the cron scan
    always fetches fresh post-close market data even if a manual scan ran the
    night before, while 100% reusing the SEC parsed caches just written by
    Stage 1 (they are minutes old). Pure decision logic; all network I/O
    stays inside ``scan_fn``/``run_scan_with_status``.

    R04: when the scan callable returns a structured ``ScanRunStatus``, the
    cron treats a missing/failed canonical decision snapshot or latest
    pointer as failure even though the legacy CSV was written. Injected
    legacy callables that only return a Path keep their old contract.
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
        scan_options = {} if scan_now_utc is None else {"freshness_now_utc": scan_now_utc}
        result = (scan_fn or run_scan_with_status)(
            scan_cfg,
            scan_config_path=config_path,
            allow_existing_decision_snapshot=True,
            **scan_options,
        )
    except Exception as exc:  # noqa: BLE001 - cron must report, not crash
        log(f"ERROR: daily MVP scan failed: {type(exc).__name__}: {exc}")
        if isinstance(exc, OfficialPublicationError):
            return {
                "scan_executed": False, "scan_failed": True,
                "error": str(exc), "reason_code": exc.reason_code,
            }
        return {"scan_executed": False, "scan_failed": True, "error": str(exc)}

    if hasattr(result, "core_failed"):
        outcome = {
            "scan_executed": True,
            "scan_failed": bool(result.core_failed),
            "output_path": str(result.output_path),
            "decision_snapshot_root": (
                None
                if result.decision_snapshot_root is None
                else str(result.decision_snapshot_root)
            ),
            "decision_output_status": str(result.decision_output_status),
            "latest_pointer_status": str(result.latest_pointer_status),
            "shadow_status": result.shadow_status,
        }
        if result.core_failed:
            outcome["error"] = (
                result.decision_output_error
                or result.latest_pointer_error
                or "core decision output missing or failed"
            )
        return outcome
    return {
        "scan_executed": True,
        "scan_failed": False,
        "output_path": str(result),
    }


def _run_attempt(
    args: argparse.Namespace, cfg: ScanConfig, repo: Path, receipt: dict[str, Any]
) -> int:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        receipt.update(status="failed", reason_code="missing_sec_user_agent")
        log("ERROR: SEC_USER_AGENT is required")
        return 1

    receipt["prewarm_status"] = "running"
    summary = run_sec_prewarm(
        cfg,
        repo=repo,
        user_agent=user_agent,
        max_age_hours=args.max_age_hours,
        limit=args.limit,
    )
    blocked = bool(summary["aborted"] or summary["conflicted"])
    prewarm_failed = bool(summary["failed"] or blocked)
    receipt["prewarm_status"] = "failed" if prewarm_failed else "succeeded"
    receipt["prewarm_counts"] = {
        key: summary[key]
        for key in ("total", "refreshed", "skipped_valid", "failed", "incomplete")
        if key in summary
    }
    if args.skip_scan or args.limit > 0 or blocked:
        receipt.update(
            status="failed" if prewarm_failed else "prewarm_only",
            reason_code="sec_prewarm_failed" if prewarm_failed else None,
        )
        return int(prewarm_failed)

    missing_credentials = [
        key for key in ("ALPACA_API_ENDPOINT", "ALPACA_API_KEY", "ALPACA_API_SECRET")
        if not os.getenv(key, "").strip()
    ]
    if missing_credentials:
        receipt.update(status="failed", reason_code="missing_alpaca_credentials")
        log("ERROR: daily MVP scan requires " + ", ".join(missing_credentials))
        return 1

    scan_now = datetime.now(timezone.utc)
    if cfg.official_market_mode == "sip_eod":
        expected, window = sip_publication_window(scan_now)
        receipt["expected_session"] = expected.isoformat()
        if window != "available":
            receipt.update(status="deferred", reason_code=window)
            log(f"daily MVP scan deferred: {window}")
            return int(prewarm_failed)

    result = run_daily_scan_after_prewarm(
        cfg,
        config_path=args.config,
        summary=summary,
        limit=args.limit,
        skip_scan=args.skip_scan,
        alpaca_ttl_sec=args.alpaca_ttl_sec,
        scan_now_utc=scan_now,
    )
    receipt["decision_output_status"] = result.get("decision_output_status")
    receipt["latest_pointer_status"] = result.get("latest_pointer_status")
    if result.get("scan_failed") or not result.get("scan_executed"):
        receipt.update(status="failed", reason_code=result.get("reason_code", "scan_failed"))
        log(f"ERROR: daily MVP scan failed: {result.get('error') or result.get('reason')}")
        return 1
    if (
        result.get("decision_output_status") not in {"written", "reused"}
        or result.get("latest_pointer_status") != (
            "not_applicable" if receipt["mode"] == "smoke" else "written"
        )
    ):
        receipt.update(status="failed", reason_code="missing_scan_artifacts")
        log("ERROR: daily MVP scan produced no matching decision artifacts")
        return 1

    if receipt["mode"] == "smoke":
        receipt["status"] = "sampled"
        receipt["decision_snapshot_root"] = result.get("decision_snapshot_root")
    else:
        receipt["status"] = "reused" if result["decision_output_status"] == "reused" else "published"
    receipt["reason_code"] = "sec_prewarm_failed" if prewarm_failed else None
    if result.get("shadow_status") == "failed":
        log("WARNING: v2 shadow snapshot failed while the main snapshot was published")
    return int(prewarm_failed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily cron: SEC prewarm (Stage 1) + MVP scan (Stage 2)."
    )
    parser.add_argument("--config", default="configs/config.production.json")
    parser.add_argument("--max-age-hours", type=float, default=4.0)
    parser.add_argument(
        "--alpaca-ttl-sec",
        type=int,
        default=3600,
        help="Stage 2 Alpaca freshness window in seconds.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test cap")
    parser.add_argument("--forward-ledger", type=Path, help="Append completed formal SIP receipts to this local SQLite ledger.")
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        default=False,
        help="Only run Stage 1 SEC prewarm; skip the Stage 2 daily MVP scan.",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    load_dotenv(repo / ".env")
    if not 0 < args.max_age_hours <= 24:
        parser.error("--max-age-hours must be >0 and <=24")
    if not args.alpaca_ttl_sec > 0:
        parser.error("--alpaca-ttl-sec must be positive")
    cfg: ScanConfig = load_config(args.config)
    if cfg.sec_cache_ttl_submissions_sec <= 0:
        parser.error("sec_cache_ttl_submissions_sec must be positive for scan-side parsed-cache reuse")

    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    style = cfg.strategy_style or "default"
    mode = "formal"
    if args.skip_scan:
        mode = "prewarm_only"
    elif args.limit > 0 or cfg.max_symbols is not None:
        mode = "smoke"
    root = Path(cfg.output_dir) / "decisions"
    receipt_path = root / "publication_attempts" / style / mode / f"{run_id}.json"
    expected_session = None
    if mode == "formal" and cfg.official_market_mode == "sip_eod":
        expected_session = sip_publication_window(started)[0].isoformat()
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "strategy_style": style,
        "run_code_sha": resolve_git_commit_sha(),
        "started_at_utc": started.isoformat(),
        "expected_session": expected_session,
        "published_session": None,
        "status": "running",
        "prewarm_status": "not_attempted",
    }
    write_publication_attempt(receipt_path, receipt)
    try:
        exit_code = _run_attempt(args, cfg, repo, receipt)
    except (Exception, SystemExit) as exc:
        if receipt["prewarm_status"] == "running":
            receipt["prewarm_status"] = "failed"
            reason = "sec_prewarm_failed"
        else:
            reason = "cron_exception"
        receipt.update(status="failed", reason_code=reason, error_type=type(exc).__name__)
        log(f"ERROR: daily cron failed: {type(exc).__name__}: {exc}")
        exit_code = 1

    if mode == "formal":
        try:
            publication = read_latest_publication(
                root, style, require_sip=cfg.official_market_mode == "sip_eod"
            )
        except (OSError, ValueError):
            publication = None
        if publication is not None:
            receipt.update(published_session=publication["decision_date"], publication=publication)
        if receipt["status"] in {"published", "reused"} and (
            publication is None
            or (
                cfg.official_market_mode == "sip_eod"
                and receipt["published_session"] != receipt["expected_session"]
            )
        ):
            receipt.update(status="failed", reason_code="latest_pointer_verification_failed")
            exit_code = 1

    receipt.update(finished_at_utc=datetime.now(timezone.utc).isoformat(), exit_code=exit_code)
    write_publication_attempt(receipt_path, receipt)
    log(f"daily cron {receipt['status']} (exit={exit_code}) receipt={receipt_path}")
    if args.forward_ledger is not None and mode == "formal" and cfg.official_market_mode == "sip_eod":
        from ai_value_scanner.forward.ledger import Ledger

        try:
            Ledger(args.forward_ledger, snapshot_root=root).import_attempt(receipt)
        except Exception as exc:
            log(f"WARN: forward ledger import failed ({type(exc).__name__}); completed receipt is available for recovery")
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
