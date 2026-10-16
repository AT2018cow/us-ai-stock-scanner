"""Audit candidate-universe coverage against index constituent benchmarks.

Compares the ETF-derived watchlist (candidate discovery input, NOT a portfolio)
with S&P 500 / Nasdaq-100 (QQQ tracking index) constituent snapshots and reports
coverage plus the missing-ticker list in benchmark order.

Offline by default: reads a watchlist CSV and one or more constituent CSVs.
Use --fetch to refresh versioned benchmark snapshots from the monthly publisher
into data/benchmarks/ (network only in this script, never in unit tests).

Examples:
    python scripts/audit_universe_coverage.py \\
        --watchlist data/ai_watchlist.csv \\
        --benchmark data/benchmarks/sp500_202610.csv:SP500 \\
        --benchmark data/benchmarks/nasdaq100_202610.csv:NASDAQ100
    python scripts/audit_universe_coverage.py --fetch --fetch-ym 2026-10
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WATCHLIST = REPO_ROOT / "data" / "ai_watchlist.csv"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmarks"
FETCH_URL = "https://yfiua.github.io/index-constituents/{ym}/{fname}"
FETCH_FILES = {
    "SP500": "constituents-sp500.csv",
    "NASDAQ100": "constituents-nasdaq100.csv",
}


def normalize_symbol(raw: str) -> str:
    """Canonical ticker key: case-insensitive, class-suffix punctuation unified.

    BRK.B (index) and BRK-B (data vendor) both normalize to BRKB.
    """
    return raw.strip().upper().replace(".", "").replace("-", "").replace("/", "").replace(" ", "")


def load_symbol_set(path: Path, column: str = "symbol") -> set[str]:
    """Load distinct normalized symbols from a CSV with a symbol column."""
    symbols: set[str] = set()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        key = cols.get(column.lower(), cols.get("symbol", next(iter(cols.values()), None)))
        for row in reader:
            raw = (row.get(key) or "").strip() if key else ""
            if raw:
                symbols.add(normalize_symbol(raw))
    return symbols


def load_benchmark_ordered(path: Path) -> list[tuple[str, str]]:
    """Load benchmark as (raw_symbol, name) in file order (cap-descending as published)."""
    ordered: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        sym_key = cols.get("symbol", next(iter(cols.values())))
        name_key = cols.get("name")
        for row in reader:
            raw = (row.get(sym_key) or "").strip()
            if raw:
                ordered.append((raw, (row.get(name_key) or "").strip() if name_key else ""))
    return ordered


def audit(watchlist: set[str], benchmark: list[tuple[str, str]]) -> dict:
    missing = [(s, n) for s, n in benchmark if normalize_symbol(s) not in watchlist]
    total = len(benchmark)
    covered = total - len(missing)
    return {
        "total": total,
        "covered": covered,
        "missing": len(missing),
        "coverage_pct": round(100.0 * covered / total, 1) if total else 0.0,
        "missing_list": missing,
    }


def fetch_benchmarks(ym: str, out_dir: Path) -> list[Path]:
    """Download monthly constituent snapshots (network). Returns written paths."""
    ymf = ym.replace("-", "/")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    tag = ym.replace("-", "")
    for label, fname in FETCH_FILES.items():
        url = FETCH_URL.format(ym=ymf, fname=fname)
        dest = out_dir / f"{label.lower()}_{tag}.csv"
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (operator-run script)
            dest.write_bytes(resp.read())
        written.append(dest)
    return written


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Audit watchlist coverage vs index benchmarks.")
    p.add_argument("--watchlist", default=str(DEFAULT_WATCHLIST))
    p.add_argument(
        "--benchmark",
        action="append",
        default=[],
        metavar="PATH:LABEL",
        help="Constituent CSV + label, repeatable.",
    )
    p.add_argument("--fetch", action="store_true", help="Refresh benchmark snapshots, then exit.")
    p.add_argument("--fetch-ym", default="2026-10", help="Benchmark month YYYY-MM for --fetch.")
    p.add_argument("--top-missing", type=int, default=30, help="Missing tickers to print per benchmark.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.fetch:
        for dest in fetch_benchmarks(args.fetch_ym, BENCHMARK_DIR):
            print(f"[coverage] fetched {dest}")
        return 0
    watchlist = load_symbol_set(Path(args.watchlist))
    print(f"[coverage] watchlist: {len(watchlist)} distinct symbols from {args.watchlist}")
    if not args.benchmark:
        print("[coverage] no --benchmark given.", file=sys.stderr)
        return 2
    for spec in args.benchmark:
        path_str, _, label = spec.partition(":")
        bench = load_benchmark_ordered(Path(path_str))
        result = audit(watchlist, bench)
        print(f"[coverage] {label or path_str}: "
              f"{result['covered']}/{result['total']} covered ({result['coverage_pct']}%), "
              f"missing {result['missing']}")
        for sym, name in result["missing_list"][: args.top_missing]:
            print(f"  MISSING {sym} {name}")
        if result["missing"] > args.top_missing:
            print(f"  ... and {result['missing'] - args.top_missing} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
