from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_symbol_list(symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        value = str(sym).strip().upper()
        if not value or value in seen:
            continue
        out.append(value)
        seen.add(value)
    return out


def apply_group_caps(
    frame: pd.DataFrame,
    max_per_sector: int | None,
    max_per_watchlist_etf_source: int | None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    out_rows: list[pd.Series] = []
    sector_count: dict[str, int] = {}
    etf_count: dict[str, int] = {}

    for _, row in frame.iterrows():
        sector_key = str(row.get("sic", "") or "")[:2]
        etf_tokens = [
            token
            for token in str(
                row.get("watchlist_etfs", "") or ""
            ).split(",")
            if token
        ]
        primary_etf = sorted(etf_tokens)[0] if etf_tokens else ""

        if max_per_sector is not None and sector_key:
            if sector_count.get(sector_key, 0) >= int(max_per_sector):
                continue
        if max_per_watchlist_etf_source is not None and primary_etf:
            if etf_count.get(primary_etf, 0) >= int(
                max_per_watchlist_etf_source
            ):
                continue

        out_rows.append(row)
        if sector_key:
            sector_count[sector_key] = sector_count.get(sector_key, 0) + 1
        if primary_etf:
            etf_count[primary_etf] = etf_count.get(primary_etf, 0) + 1

    if not out_rows:
        return frame.iloc[0:0].copy()
    return pd.DataFrame(out_rows).reset_index(drop=True)


def dedupe_symbol_by_best_channel(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    if (
        frame.empty
        or "symbol" not in frame.columns
        or "composite_score" not in frame.columns
    ):
        return frame, 0
    work = frame.copy()
    work["_symbol"] = work["symbol"].astype(str)
    work["_score"] = pd.to_numeric(
        work["composite_score"],
        errors="coerce",
    ).fillna(-np.inf)
    if "watchlist_etf_count" in work.columns:
        work["_etf_count"] = pd.to_numeric(
            work["watchlist_etf_count"],
            errors="coerce",
        ).fillna(0)
    else:
        work["_etf_count"] = 0
    if "channel" in work.columns:
        work["_channel"] = work["channel"].astype(str)
    else:
        work["_channel"] = ""

    work = work.sort_values(
        by=["_symbol", "_score", "_etf_count", "_channel"],
        ascending=[True, False, False, True],
    )
    deduped = work.drop_duplicates(
        subset=["_symbol"],
        keep="first",
    ).drop(
        columns=["_symbol", "_score", "_etf_count", "_channel"],
        errors="ignore",
    )
    return deduped, int(len(frame) - len(deduped))


def drop_symbols(
    frame: pd.DataFrame,
    symbols: set[str],
) -> tuple[pd.DataFrame, int]:
    if frame.empty or not symbols or "symbol" not in frame.columns:
        return frame, 0
    before = len(frame)
    keep_mask = ~frame["symbol"].astype(str).isin(symbols)
    out = frame[keep_mask].copy()
    return out, int(before - len(out))


def select_symbols_from_ranked_frames(
    ranked_frames: list[pd.DataFrame],
    *,
    top_n: int,
    per_channel_top_n: bool,
) -> tuple[list[str], dict[str, list[str]], dict[str, int]]:
    """Select symbols from already ranked/channel-labelled frames."""
    channel_symbols: dict[str, list[str]] = {}
    channel_counts: dict[str, int] = {}
    non_empty = [frame for frame in ranked_frames if not frame.empty]
    if not non_empty:
        return [], channel_symbols, channel_counts

    if per_channel_top_n:
        picks: list[str] = []
        for part in non_empty:
            channel = (
                str(part["channel"].iloc[0])
                if "channel" in part.columns
                else ""
            )
            selected = (
                part.head(max(1, int(top_n)))["symbol"]
                .dropna()
                .astype(str)
                .tolist()
            )
            channel_symbols[channel] = selected
            channel_counts[channel] = len(selected)
            picks.extend(selected)
        return normalize_symbol_list(picks), channel_symbols, channel_counts

    merged = pd.concat(non_empty, ignore_index=True)
    merged = merged.sort_values("composite_score", ascending=False)
    selected = merged.head(max(1, int(top_n))).copy()
    picks = selected["symbol"].dropna().astype(str).tolist()
    if "channel" in selected.columns:
        for channel in sorted(
            selected["channel"].dropna().astype(str).unique().tolist()
        ):
            symbols = (
                selected[selected["channel"].astype(str) == channel]["symbol"]
                .dropna()
                .astype(str)
                .tolist()
            )
            channel_symbols[channel] = symbols
            channel_counts[channel] = len(symbols)
    return normalize_symbol_list(picks), channel_symbols, channel_counts
