from __future__ import annotations

import argparse
from pathlib import Path

from ai_value_scanner.scanner import ScanConfig, load_config, refresh_watchlist_from_etfs


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Refresh AI watchlist from ETF holdings.")
    p.add_argument("--config", default="config.production.json", help="Scanner config path.")
    p.add_argument("--output", default=None, help="Optional output csv path override.")
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg: ScanConfig = load_config(args.config)
    df = refresh_watchlist_from_etfs(cfg)
    out = Path(args.output) if args.output else Path(cfg.watchlist_csv_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        print("[watchlist] no rows generated from ETF refresh.")
    else:
        df = df.sort_values(["bucket", "symbol"]).drop_duplicates(subset=["symbol", "bucket"], keep="first")
        df.to_csv(out, index=False)
        core_n = int((df["bucket"] == "core_ai").sum()) if "bucket" in df.columns else 0
        enabler_n = int((df["bucket"] == "ai_enabler").sum()) if "bucket" in df.columns else 0
        print(f"[watchlist] rows={len(df)} core_ai={core_n} ai_enabler={enabler_n}")
    print(f"[watchlist] output={out}")


if __name__ == "__main__":
    main()
