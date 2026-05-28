#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def risk_tags(row: pd.Series) -> list[str]:
    tags: list[str] = []
    ps_discount = float(row.get("ps_discount", 0.0) or 0.0)
    pe_discount = float(row.get("pe_discount", 0.0) or 0.0)
    comp = float(row.get("composite_score", 0.0) or 0.0)
    if int(row.get("watchlist_etf_count", 0) or 0) <= 0:
        tags.append("Missing watchlist signal")
    if ps_discount <= 0 and pe_discount <= 0:
        tags.append("No valuation discount")
    if comp < 0.35:
        tags.append("Lower composite confidence")
    return tags


def row_line(row: pd.Series) -> str:
    symbol = str(row.get("symbol", ""))
    company = str(row.get("company_name", "") or row.get("name", ""))
    channel = str(row.get("channel", ""))
    triage = str(row.get("triage_label", ""))
    comp = float(row.get("composite_score", 0.0) or 0.0)
    psd = float(row.get("ps_discount", 0.0) or 0.0)
    ped = float(row.get("pe_discount", 0.0) or 0.0)
    bucket = str(row.get("watchlist_bucket", "") or "")
    etf_count = int(row.get("watchlist_etf_count", 0) or 0)
    etfs = str(row.get("watchlist_etfs", "") or "")
    news_count = int(row.get("news_count", 0) or 0)
    tags = risk_tags(row)
    risk = "none" if not tags else ", ".join(tags)
    return (
        f"- {symbol} | {company} | {channel}/{triage} | score={comp:.3f} | "
        f"bucket={bucket} etf_count={etf_count} etfs={etfs} | "
        f"psd={psd:.3f} ped={ped:.3f} | "
        f"news={news_count} | risk={risk}"
    )


def build_report(df: pd.DataFrame, max_watch: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# Investment List (Keep / Watch)")
    lines.append("")
    lines.append(f"Generated UTC: {now}")
    lines.append(f"Total rows: {len(df)}")
    lines.append("")

    counts = df["triage_label"].value_counts().to_dict() if "triage_label" in df.columns else {}
    lines.append("## Triage Summary")
    lines.append("")
    lines.append(f"- keep: {counts.get('keep', 0)}")
    lines.append(f"- watch: {counts.get('watch', 0)}")
    lines.append(f"- drop: {counts.get('drop', 0)}")
    lines.append("")

    keep_df = df[df["triage_label"] == "keep"].copy()
    watch_df = df[df["triage_label"] == "watch"].copy()
    keep_df = keep_df.sort_values("composite_score", ascending=False)
    watch_df = watch_df.sort_values("composite_score", ascending=False)

    lines.append("## Keep")
    lines.append("")
    if keep_df.empty:
        lines.append("- none")
    else:
        for _, row in keep_df.iterrows():
            lines.append(row_line(row))
    lines.append("")

    lines.append(f"## Watch (Top {max_watch}, Dedup By Symbol)")
    lines.append("")
    watch_dedup = (
        watch_df.sort_values("composite_score", ascending=False)
        .drop_duplicates(subset=["symbol"], keep="first")
    )
    if watch_dedup.empty:
        lines.append("- none")
    else:
        for _, row in watch_dedup.head(max_watch).iterrows():
            lines.append(row_line(row))
    lines.append("")

    lines.append("## Core AI Watch")
    lines.append("")
    core_watch = watch_df[watch_df["channel"] == "core_ai"].head(max_watch)
    if core_watch.empty:
        lines.append("- none")
    else:
        for _, row in core_watch.iterrows():
            lines.append(row_line(row))
    lines.append("")

    lines.append("## AI Enabler Watch")
    lines.append("")
    ena_watch = watch_df[watch_df["channel"] == "ai_enabler"].head(max_watch)
    if ena_watch.empty:
        lines.append("- none")
    else:
        for _, row in ena_watch.iterrows():
            lines.append(row_line(row))
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a readable investment list from scan output.")
    parser.add_argument("--input", default="outputs/full_market_scan.csv", help="Input scan CSV path.")
    parser.add_argument(
        "--output",
        default="outputs/full_market_investment_list.md",
        help="Output markdown path.",
    )
    parser.add_argument(
        "--max-watch",
        type=int,
        default=20,
        help="Max watch rows per watch section.",
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"missing input: {in_path}")

    df = pd.read_csv(in_path)
    if df.empty:
        out_path.write_text("# Investment List (Keep / Watch)\n\nNo rows.\n")
        print(out_path)
        return

    expected_cols = {"triage_label", "channel", "composite_score"}
    missing = expected_cols - set(df.columns)
    if missing:
        raise SystemExit(f"input missing required columns: {sorted(missing)}")

    report = build_report(df, max_watch=max(1, args.max_watch))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(out_path)


if __name__ == "__main__":
    main()
