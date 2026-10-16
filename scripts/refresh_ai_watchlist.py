from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ai_value_scanner.scanner import (
    WATCHLIST_CSV_COLUMNS,
    ScanConfig,
    archive_watchlist_snapshot,
    load_config,
    merge_refreshed_watchlist,
    normalize_equity_symbol,
    refresh_watchlist_from_etfs,
    write_csv_atomic,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Refresh AI watchlist from ETF holdings (safe additive merge: "
            "SRC:* / ai_smallcap / enabled=0 rows are never dropped)."
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
