from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from ai_value_scanner.scanner import (
    WATCHLIST_CSV_COLUMNS,
    AlpacaClient,
    RequestRateLimiter,
    ScanConfig,
    SecClient,
    archive_watchlist_snapshot,
    build_sec_ticker_cik_maps,
    load_cached_symbol_to_cik,
    load_config,
    merge_refreshed_watchlist,
    normalize_equity_symbol,
    reconcile_manual_seed_csv,
    reconcile_watchlist_corporate_actions,
    refresh_watchlist_from_etfs,
    write_csv_atomic,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Refresh AI watchlist from ETF holdings (safe additive merge: "
            "SRC:* / ai_smallcap / enabled=0 rows are never dropped; CIK-based "
            "corporate-action reconciliation keeps renamed/delisted tickers clean)."
        )
    )
    p.add_argument("--config", default="configs/config.risk_off.json", help="Scanner config path.")
    p.add_argument("--output", default=None, help="Optional output csv path override.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Fetch ETF holdings and print merge statistics/new rows without writing.",
    )
    p.add_argument(
        "--prune-dropped-etf-rows",
        action="store_true",
        default=False,
        help=(
            "Opt-in: drop prior pure-ETF rows no longer present in the freshly "
            "fetched top holdings (SRC:* and ai_smallcap rows are always kept)."
        ),
    )
    p.add_argument(
        "--no-archive",
        action="store_true",
        default=False,
        help="Skip archiving the refreshed watchlist to data/watchlist_history/.",
    )
    p.add_argument(
        "--no-reconcile-corporate-actions",
        action="store_true",
        default=False,
        help=(
            "Skip CIK-based ticker rename migration and delisted/inactive "
            "ticker removal."
        ),
    )
    p.add_argument(
        "--manual-seed-csv",
        default="data/ai_smallcap_manual.csv",
        help=(
            "Smallcap manual seed CSV kept in sync with corporate-action "
            "renames/removals (default: data/ai_smallcap_manual.csv)."
        ),
    )
    return p


def _normalized_pairs(frame: pd.DataFrame) -> set[tuple[str, str]]:
    """Normalized (symbol, bucket) pairs present in a watchlist frame."""
    if frame is None or frame.empty:
        return set()
    if "symbol" not in frame.columns or "bucket" not in frame.columns:
        return set()
    pairs: set[tuple[str, str]] = set()
    for symbol, bucket in zip(frame["symbol"], frame["bucket"]):
        norm_symbol = normalize_equity_symbol(symbol)
        norm_bucket = str(bucket or "").strip().lower()
        if norm_symbol and norm_bucket:
            pairs.add((norm_symbol, norm_bucket))
    return pairs


def _load_corporate_action_references(
    cfg: ScanConfig,
) -> tuple[dict[str, str], dict[str, list[str]], set[str] | None]:
    """Load SEC ticker maps and Alpaca active symbols; never raises.

    Returns ``({}, {}, None)`` when SEC reference data is unavailable so a
    refresh run can proceed without corporate-action reconciliation.
    """
    load_dotenv()
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        print(
            "[watchlist] WARNING: SEC_USER_AGENT unavailable; "
            "skipping corporate-action reconciliation."
        )
        return {}, {}, None
    try:
        sec = SecClient(
            session=requests.Session(),
            user_agent=user_agent,
            timeout_sec=cfg.request_timeout_sec,
            cache_dir=Path(cfg.cache_dir),
            request_limiter=RequestRateLimiter(cfg.sec_max_requests_per_sec),
            submissions_ttl_sec=cfg.sec_cache_ttl_submissions_sec,
        )
        frame = sec.ticker_map_snapshot()["frame"]
        sec_ticker_to_cik, sec_cik_to_tickers = build_sec_ticker_cik_maps(
            frame.to_dict("records")
        )
    except Exception as exc:
        print(
            "[watchlist] WARNING: SEC ticker mapping unavailable "
            f"({type(exc).__name__}); skipping corporate-action reconciliation."
        )
        return {}, {}, None

    active_symbols: set[str] | None = None
    api_endpoint = os.getenv("ALPACA_API_ENDPOINT", "").strip()
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    if api_endpoint and api_key and api_secret:
        try:
            alpaca = AlpacaClient(
                session=requests.Session(),
                api_endpoint=api_endpoint,
                data_endpoint=os.getenv(
                    "ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets"
                ),
                api_key=api_key,
                api_secret=api_secret,
                feed=os.getenv("ALPACA_FEED", "iex"),
                timeout_sec=cfg.request_timeout_sec,
                request_limiter=RequestRateLimiter(cfg.alpaca_max_requests_per_sec),
                cache_dir=Path(cfg.cache_dir),
                cache_enabled=cfg.alpaca_cache_enabled,
                cache_ttl_assets_sec=cfg.alpaca_cache_ttl_assets_sec,
                cache_ttl_snapshots_sec=cfg.alpaca_cache_ttl_snapshots_sec,
                cache_ttl_bars_sec=cfg.alpaca_cache_ttl_bars_sec,
            )
            assets = alpaca.get_assets(status="active")
            active_symbols = {
                str(asset.get("symbol") or "").strip().upper()
                for asset in assets
                if isinstance(asset, dict) and asset.get("symbol")
            } or None
        except Exception as exc:
            print(
                "[watchlist] WARNING: Alpaca active assets unavailable "
                f"({type(exc).__name__}); reconciling without Alpaca status."
            )
            active_symbols = None
    return sec_ticker_to_cik, sec_cik_to_tickers, active_symbols


def _reconcile_corporate_actions(
    merged: pd.DataFrame,
    cfg: ScanConfig,
    args: argparse.Namespace,
) -> pd.DataFrame:
    """Apply CIK-based rename migration / delisting hygiene, None-safe."""
    (
        sec_ticker_to_cik,
        sec_cik_to_tickers,
        active_alpaca_symbols,
    ) = _load_corporate_action_references(cfg)
    if not sec_ticker_to_cik:
        print("[watchlist] corporate_actions skipped (no SEC ticker mapping).")
        return merged
    historical_symbol_to_cik = load_cached_symbol_to_cik(cfg.cache_dir)
    merged, ca_report = reconcile_watchlist_corporate_actions(
        merged,
        sec_ticker_to_cik=sec_ticker_to_cik,
        sec_cik_to_tickers=sec_cik_to_tickers,
        historical_symbol_to_cik=historical_symbol_to_cik,
        active_alpaca_symbols=active_alpaca_symbols,
    )
    print(
        f"[watchlist] corporate_actions renamed={ca_report['renamed_count']} "
        f"removed_delisted={ca_report['removed_count']}"
    )
    for item in ca_report["renamed"]:
        print(
            f"[watchlist] ~ {item['old_symbol']} -> {item['new_symbol']} "
            f"({item['bucket']}, cik={item['cik']})"
        )
    for item in ca_report["removed_delisted"]:
        print(
            f"[watchlist] - {item['symbol']} "
            f"({item['bucket']}, cik={item['cik']}, reason={item['reason']})"
        )
    manual_stats = reconcile_manual_seed_csv(
        Path(args.manual_seed_csv), ca_report, dry_run=args.dry_run
    )
    if manual_stats["renamed"] or manual_stats["removed"]:
        print(
            f"[watchlist] manual_seed renamed={manual_stats['renamed']} "
            f"removed={manual_stats['removed']}"
        )
    return merged


def main() -> None:
    args = build_parser().parse_args()
    cfg: ScanConfig = load_config(args.config)
    out = Path(args.output) if args.output else Path(cfg.watchlist_csv_path)
    if out.exists():
        existing = pd.read_csv(out)
    else:
        existing = pd.DataFrame(columns=WATCHLIST_CSV_COLUMNS)

    refreshed = refresh_watchlist_from_etfs(cfg)
    if refreshed.empty and not existing.empty:
        print(
            "[watchlist] WARNING: ETF refresh returned 0 rows; "
            "preserving existing watchlist untouched."
        )
        return

    merged, stats = merge_refreshed_watchlist(
        existing,
        refreshed,
        prune_dropped_etf_rows=args.prune_dropped_etf_rows,
    )
    print(
        f"[watchlist] existing={stats['existing_rows']} "
        f"fetched_etf={stats['fetched_etf_rows']} "
        f"added={stats['added_rows']} updated={stats['updated_rows']} "
        f"preserved_protected={stats['preserved_manual_or_smallcap_rows']} "
        f"preserved_etf={stats['preserved_prior_etf_rows']} "
        f"pruned={stats['pruned_etf_rows']} "
        f"total={stats['total_rows']} "
        f"unique_symbols={stats['unique_symbols']}"
    )
    if not args.no_reconcile_corporate_actions:
        merged = _reconcile_corporate_actions(merged, cfg, args)
    if args.dry_run:
        existing_pairs = _normalized_pairs(existing)
        for row in merged.itertuples(index=False):
            if (str(row.symbol), str(row.bucket)) not in existing_pairs:
                print(f"[watchlist] + {row.symbol} ({row.bucket}) etfs={row.etfs}")
        print(f"[watchlist] dry-run complete; output not modified: {out}")
        return

    write_csv_atomic(merged, out)
    if not args.no_archive and out == Path(cfg.watchlist_csv_path):
        snapshot = archive_watchlist_snapshot(cfg, datetime.now(timezone.utc))
        if snapshot is not None:
            print(f"[watchlist] archived snapshot={snapshot}")
    print(f"[watchlist] output={out}")


if __name__ == "__main__":
    main()
