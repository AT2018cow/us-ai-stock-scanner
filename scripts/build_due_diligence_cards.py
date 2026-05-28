#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


def risk_tags(row: pd.Series) -> list[str]:
    tags: list[str] = []
    if int(row.get("watchlist_etf_count", 0) or 0) <= 0:
        tags.append("Missing watchlist ETF signal")
    if float(row.get("ps_discount", 0.0)) < 0:
        tags.append("PS premium vs peers")
    if float(row.get("pe_discount", 0.0)) < 0:
        tags.append("PE premium vs peers")
    if float(row.get("composite_score", 0.0)) < 0.45:
        tags.append("Low composite ranking confidence")
    return tags


def fetch_news(symbol: str, data_endpoint: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    url = f"{data_endpoint.rstrip('/')}/v1beta1/news"
    params = {"symbols": symbol, "limit": 3, "sort": "desc"}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if r.status_code != 200:
        return []
    payload = r.json()
    return payload.get("news", payload if isinstance(payload, list) else [])


def main() -> None:
    load_dotenv('.env')
    input_csv = Path("outputs/validation/scan_loose.csv")
    output_md = Path("outputs/validation/loose_due_diligence.md")

    if not input_csv.exists():
        raise SystemExit(f"missing input: {input_csv}")

    df = pd.read_csv(input_csv)
    if df.empty:
        output_md.write_text("# Loose Due Diligence\n\nNo candidates in scan_loose.csv\n")
        print(output_md)
        return

    apca_key = os.getenv("ALPACA_API_KEY", "").strip()
    apca_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    data_endpoint = os.getenv("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets").strip()
    headers = {
        "APCA-API-KEY-ID": apca_key,
        "APCA-API-SECRET-KEY": apca_secret,
    }

    lines: list[str] = []
    lines.append("# Loose Candidate Due Diligence")
    lines.append("")
    lines.append(f"Generated (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Source: `{input_csv}`")
    lines.append("")

    for idx, row in df.reset_index(drop=True).iterrows():
        symbol = str(row["symbol"])
        channel = str(row.get("channel", ""))
        bucket = str(row.get("watchlist_bucket", "") or "")
        etf_count = int(row.get("watchlist_etf_count", 0) or 0)
        etfs = str(row.get("watchlist_etfs", "") or "")
        ps_discount = float(row.get("ps_discount", 0.0))
        pe_discount = float(row.get("pe_discount", 0.0))
        comp = float(row.get("composite_score", 0.0))

        lines.append(f"## {idx+1}. {symbol} ({channel})")
        lines.append("")
        lines.append(
            f"- Watchlist: bucket={bucket}, etf_count={etf_count}, etfs={etfs}, composite={comp:.4f}"
        )
        lines.append(f"- Relative valuation: ps_discount={ps_discount:.4f}, pe_discount={pe_discount:.4f}")

        tags = risk_tags(row)
        if tags:
            lines.append(f"- Risk tags: {'; '.join(tags)}")
        else:
            lines.append("- Risk tags: none")

        news = fetch_news(symbol, data_endpoint, headers)
        if news:
            lines.append("- Latest news headlines:")
            for item in news[:3]:
                title = str(item.get("headline", "")).strip().replace("\n", " ")
                t = str(item.get("updated_at") or item.get("created_at") or "")
                if len(title) > 180:
                    title = title[:177] + "..."
                lines.append(f"  - {t} | {title}")
        else:
            lines.append("- Latest news headlines: unavailable")

        lines.append("")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n")
    print(output_md)


if __name__ == "__main__":
    main()
