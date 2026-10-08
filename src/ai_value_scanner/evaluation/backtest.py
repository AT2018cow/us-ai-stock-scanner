from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from typing import Any

import numpy as np
import pandas as pd


def next_trading_index(index: pd.DatetimeIndex, signal_dt: pd.Timestamp) -> int | None:
    pos = index.searchsorted(signal_dt, side="right")
    if pos >= len(index):
        return None
    return int(pos)


def forward_return_with_exit(
    price_frame: pd.DataFrame,
    signal_date: str,
    horizon: int,
    roundtrip_cost: float,
    entry_price_mode: str = "next_open",
    exit_price_mode: str = "close",
    global_end_date: pd.Timestamp | None = None,
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> tuple[float | None, pd.Timestamp | None]:
    """Forward return plus the actual exit date (R04 label-end metadata).

    The exit date lets downstream train/valid splits clear labels that
    extend past the split boundary instead of guessing hold lengths in
    calendar days. Exit date is None for delist-assumed returns (exact
    delist date unknown) and for immature windows.
    """
    signal_dt = pd.Timestamp(signal_date, tz="UTC")
    if price_frame is None or price_frame.empty:
        return None, None
    idx = next_trading_index(price_frame.index, signal_dt)
    if idx is None:
        return None, None
    hold = max(1, int(horizon))
    exit_idx = idx + hold - 1
    if exit_idx >= len(price_frame):
        if global_end_date is not None and delist_return_assumption is not None:
            last_dt = pd.Timestamp(price_frame.index[-1]).tz_convert("UTC")
            if last_dt < (global_end_date - pd.Timedelta(days=delist_detection_buffer_days)):
                # Assume an adverse delisting return when a symbol disappears
                # well before the backtest window end.
                return float(delist_return_assumption) - roundtrip_cost, None
        return None, None

    entry_col = "open" if str(entry_price_mode).strip().lower() == "next_open" else "close"
    exit_col = "open" if str(exit_price_mode).strip().lower() == "open" else "close"
    if entry_col not in price_frame.columns or exit_col not in price_frame.columns:
        return None, None
    entry = float(price_frame.iloc[idx][entry_col])
    exit_px = float(price_frame.iloc[exit_idx][exit_col])
    if entry <= 0:
        return None, None
    exit_date = pd.Timestamp(price_frame.index[exit_idx]).tz_convert("UTC")
    return (exit_px / entry) - 1.0 - roundtrip_cost, exit_date


def fallback_label_end_date(signal_date: str, horizon: int) -> pd.Timestamp | None:
    """Conservative label end when an exact trading-day exit is unavailable.

    Used for leakage purging only. The horizon is in trading days, so convert
    with a 7/5 calendar factor plus a small holiday/data buffer. Over-purging a
    boundary event is preferable to letting a forward-return label cross into
    the held-out window.
    """
    try:
        dt = pd.Timestamp(signal_date)
        if dt.tzinfo is None:
            dt = dt.tz_localize("UTC")
        else:
            dt = dt.tz_convert("UTC")
    except (TypeError, ValueError):
        return None
    days = int(math.ceil(max(1, int(horizon)) * 7.0 / 5.0)) + 10
    return dt + pd.Timedelta(days=days)


def forward_return(
    price_frame: pd.DataFrame,
    signal_date: str,
    horizon: int,
    roundtrip_cost: float,
    entry_price_mode: str = "next_open",
    exit_price_mode: str = "close",
    global_end_date: pd.Timestamp | None = None,
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> float | None:
    ret, _ = forward_return_with_exit(
        price_frame,
        signal_date,
        horizon,
        roundtrip_cost,
        entry_price_mode=entry_price_mode,
        exit_price_mode=exit_price_mode,
        global_end_date=global_end_date,
        delist_return_assumption=delist_return_assumption,
        delist_detection_buffer_days=delist_detection_buffer_days,
    )
    return ret


def _hold_window_mature(
    signal_date: str,
    horizon: int,
    buffer_days: int,
    global_end_date: pd.Timestamp | None,
) -> bool:
    """True when a hold window must have completed before the data end.

    A horizon in trading days spans at most ~1.5x in calendar days (weekends
    + holidays) plus buffer. Only mature windows may treat missing prices as
    adverse disappearances; recent signals keep the legacy skip behaviour.
    """
    if global_end_date is None:
        return False
    try:
        signal_dt = pd.Timestamp(signal_date, tz="UTC")
        end_dt = pd.Timestamp(global_end_date).tz_convert("UTC")
    except (TypeError, ValueError):
        return False
    return (end_dt - signal_dt).days > int(horizon * 1.5) + int(buffer_days) + 10


def event_backtest(
    signals: pd.DataFrame,
    prices_by_symbol: dict[str, pd.DataFrame],
    horizons: list[int],
    roundtrip_cost: float,
    benchmark_symbols: list[str],
    entry_price_mode: str = "next_open",
    exit_price_mode: str = "close",
    delist_return_assumption: float | None = None,
    delist_detection_buffer_days: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_rows: list[dict[str, Any]] = []
    benchmark_rows: list[dict[str, Any]] = []
    global_end_date: pd.Timestamp | None = None
    if prices_by_symbol:
        all_last = [pd.Timestamp(s.index.max()).tz_convert("UTC") for s in prices_by_symbol.values() if not s.empty]
        if all_last:
            global_end_date = max(all_last)

    for row in signals.itertuples(index=False):
        symbols: list[str] = list(row.symbols) if isinstance(row.symbols, list) else []
        for horizon in horizons:
            returns: list[float] = []
            label_end_dates: list[pd.Timestamp] = []
            priced = 0
            assumed_delist = 0
            fallback_end = fallback_label_end_date(row.signal_date, horizon)
            for sym in symbols:
                price_frame = prices_by_symbol.get(sym.upper())
                if price_frame is None:
                    # No price data at all for a scored name: on a mature hold
                    # window this is a delist-like disappearance (the adverse
                    # assumption applies); on recent signals the window simply
                    # hasn't matured and the legacy skip is kept.
                    if (
                        delist_return_assumption is not None
                        and _hold_window_mature(
                            row.signal_date, horizon,
                            delist_detection_buffer_days, global_end_date,
                        )
                    ):
                        returns.append(float(delist_return_assumption) - roundtrip_cost)
                        priced += 1
                        assumed_delist += 1
                        if fallback_end is not None:
                            label_end_dates.append(fallback_end)
                    continue
                ret, exit_date = forward_return_with_exit(
                    price_frame,
                    row.signal_date,
                    horizon,
                    roundtrip_cost,
                    entry_price_mode=entry_price_mode,
                    exit_price_mode=exit_price_mode,
                    global_end_date=global_end_date,
                    delist_return_assumption=delist_return_assumption,
                    delist_detection_buffer_days=delist_detection_buffer_days,
                )
                if ret is None or not np.isfinite(ret):
                    continue
                priced += 1
                returns.append(float(ret))
                if exit_date is not None:
                    label_end_dates.append(exit_date)
                elif fallback_end is not None:
                    # Delist-assumption path has no market exit timestamp.
                    label_end_dates.append(fallback_end)
            portfolio_return = float(np.mean(returns)) if returns else np.nan
            if not symbols:
                event_status = "no_signal"
            elif priced <= 0:
                event_status = "unpriced"
            elif priced < len(symbols):
                event_status = "partial_valid"
            else:
                event_status = "valid"
            label_end = max(label_end_dates) if label_end_dates else fallback_end
            event_rows.append(
                {
                    "scenario": row.scenario,
                    "run_stem": row.run_stem,
                    "run_ts_utc": row.run_ts_utc,
                    "signal_date": row.signal_date,
                    "label_end_date": (
                        label_end.date().isoformat() if label_end is not None else None
                    ),
                    "list_type": row.list_type,
                    "horizon_days": horizon,
                    "n_selected": int(row.n_selected),
                    "n_priced": int(priced),
                    "n_assumed_delist": int(assumed_delist),
                    "event_status": event_status,
                    "portfolio_return": portfolio_return,
                    "benchmark_trailing_60d": getattr(row, "benchmark_trailing_60d", None),
                    "regime": getattr(row, "regime", "unknown"),
                }
            )
            for bench in benchmark_symbols:
                price_frame = prices_by_symbol.get(bench.upper())
                ret = None
                bench_exit = fallback_end
                if price_frame is not None:
                    # Benchmarks pay the same roundtrip cost: excess_vs_QQQ
                    # must compare cost-loaded returns on both sides.
                    ret, exact_exit = forward_return_with_exit(
                        price_frame,
                        row.signal_date,
                        horizon,
                        roundtrip_cost,
                        entry_price_mode=entry_price_mode,
                        exit_price_mode=exit_price_mode,
                        global_end_date=global_end_date,
                        delist_return_assumption=None,
                        delist_detection_buffer_days=delist_detection_buffer_days,
                    )
                    if exact_exit is not None:
                        bench_exit = exact_exit
                benchmark_rows.append(
                    {
                        "scenario": row.scenario,
                        "run_stem": row.run_stem,
                        "signal_date": row.signal_date,
                        "label_end_date": (
                            bench_exit.date().isoformat() if bench_exit is not None else None
                        ),
                        "horizon_days": horizon,
                        "benchmark": bench.upper(),
                        "benchmark_return": ret,
                    }
                )

    return pd.DataFrame(event_rows), pd.DataFrame(benchmark_rows)


def infer_segment_label(signal_date: str) -> str:
    dt = pd.Timestamp(signal_date)
    y = int(dt.year)
    current_year = datetime.now(timezone.utc).year
    if y in (2023, 2024, 2025):
        return str(y)
    if y == current_year:
        return f"{y}YTD"
    return str(y)


def non_overlapping_event_returns(part: pd.DataFrame, horizon: int) -> list[float]:
    """Select the event returns of disjoint (non-overlapping) holds.

    Weekly/monthly signal grids with multi-month holds overlap heavily.
    Greedy earliest-first selection with a calendar gap covering the holding
    window keeps disjoint holds, so each selected event's capital is not
    reused while still held. This is a SAMPLING diagnostic, not a full
    account equity curve (R05): compounding these returns approximates
    sequential non-overlapping trading, not the rolling portfolio.
    """
    sub = part.dropna(subset=["portfolio_return"]).copy()
    if sub.empty:
        return []
    try:
        sub["_sig_dt"] = pd.to_datetime(sub["signal_date"], utc=True)
    except (TypeError, ValueError):
        return []
    sub = sub.sort_values("_sig_dt")
    gap = pd.Timedelta(days=int(horizon * 7 / 5) + 2)
    rets: list[float] = []
    last = None
    for _, r in sub.iterrows():
        d = r["_sig_dt"]
        if pd.isna(d):
            continue
        if last is None or (d - last) >= gap:
            rets.append(float(r["portfolio_return"]))
            last = d
    return rets


def non_overlapping_cumulative(part: pd.DataFrame, horizon: int) -> tuple[float, int]:
    """Compound event returns over non-overlapping signal dates only.

    Greedy earliest-first selection with a calendar gap covering the holding
    window keeps disjoint holds. Returns (cumulative_return, n_events_used).
    """
    rets = non_overlapping_event_returns(part, horizon)
    if not rets:
        return float("nan"), 0
    acc = 1.0
    for r in rets:
        acc *= 1.0 + r
    return float(acc - 1.0), len(rets)


def summarize_backtest(events: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "scenario",
                "list_type",
                "horizon_days",
                "n_events_total",
                "n_events_valid",
                "avg_return",
                "median_return",
                "win_rate",
                "std_return",
                "cumulative_return",
                "n_cumulative_events",
                "avg_n_priced",
                "avg_n_selected",
                "n_no_signal_events",
                "n_unpriced_events",
                "n_partial_valid_events",
                "avg_excess_vs_QQQ",
            ]
        )
    bench_qqq = (
        benchmarks[benchmarks["benchmark"] == "QQQ"][
            ["scenario", "run_stem", "horizon_days", "benchmark_return"]
        ]
        .drop_duplicates(subset=["scenario", "run_stem", "horizon_days"], keep="last")
        .rename(columns={"benchmark_return": "qqq_return"})
    )
    merged = events.merge(bench_qqq, on=["scenario", "run_stem", "horizon_days"], how="left")
    merged["excess_vs_qqq"] = merged["portfolio_return"] - merged["qqq_return"]

    rows: list[dict[str, Any]] = []
    for keys, part in merged.groupby(["scenario", "list_type", "horizon_days"], dropna=False):
        scenario, list_type, horizon = keys
        p = part["portfolio_return"].dropna()
        total_events = int(len(part))
        valid_events = int(len(p))
        cum_ret, n_cum = non_overlapping_cumulative(part, int(horizon))
        if p.empty:
            rows.append(
                {
                    "scenario": scenario,
                    "list_type": list_type,
                    "horizon_days": int(horizon),
                    "n_events_total": total_events,
                    "n_events_valid": valid_events,
                    "avg_return": np.nan,
                    "median_return": np.nan,
                    "win_rate": np.nan,
                    "std_return": np.nan,
                    "cumulative_return": np.nan,
                    "n_cumulative_events": 0,
                    "avg_n_priced": float(part["n_priced"].mean()) if not part.empty else np.nan,
                    "avg_n_selected": float(part["n_selected"].mean()) if not part.empty else np.nan,
                    "n_no_signal_events": int((part.get("event_status") == "no_signal").sum())
                    if "event_status" in part
                    else 0,
                    "n_unpriced_events": int((part.get("event_status") == "unpriced").sum())
                    if "event_status" in part
                    else 0,
                    "n_partial_valid_events": int((part.get("event_status") == "partial_valid").sum())
                    if "event_status" in part
                    else 0,
                    "avg_excess_vs_QQQ": np.nan,
                }
            )
            continue
        rows.append(
            {
                "scenario": scenario,
                "list_type": list_type,
                "horizon_days": int(horizon),
                "n_events_total": total_events,
                "n_events_valid": valid_events,
                "avg_return": float(p.mean()),
                "median_return": float(p.median()),
                "win_rate": float((p > 0).mean()),
                "std_return": float(p.std(ddof=0)),
                "cumulative_return": float(cum_ret),
                "n_cumulative_events": int(n_cum),
                "avg_n_priced": float(part["n_priced"].mean()),
                "avg_n_selected": float(part["n_selected"].mean()),
                "n_no_signal_events": int((part.get("event_status") == "no_signal").sum())
                if "event_status" in part
                else 0,
                "n_unpriced_events": int((part.get("event_status") == "unpriced").sum())
                if "event_status" in part
                else 0,
                "n_partial_valid_events": int((part.get("event_status") == "partial_valid").sum())
                if "event_status" in part
                else 0,
                "avg_excess_vs_QQQ": float(part["excess_vs_qqq"].dropna().mean())
                if part["excess_vs_qqq"].notna().any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["scenario", "list_type", "horizon_days"]).reset_index(drop=True)


def summarize_backtest_by_segment(events: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "scenario",
                "segment",
                "list_type",
                "horizon_days",
                "n_events_total",
                "n_events_valid",
                "n_no_signal_events",
                "n_unpriced_events",
                "avg_return",
                "win_rate",
                "avg_excess_vs_QQQ",
            ]
        )
    working = events.copy()
    working["segment"] = working["signal_date"].map(infer_segment_label)

    bench_qqq = (
        benchmarks[benchmarks["benchmark"] == "QQQ"][
            ["scenario", "run_stem", "horizon_days", "benchmark_return"]
        ]
        .drop_duplicates(subset=["scenario", "run_stem", "horizon_days"], keep="last")
        .rename(columns={"benchmark_return": "qqq_return"})
    )
    merged = working.merge(bench_qqq, on=["scenario", "run_stem", "horizon_days"], how="left")
    merged["excess_vs_qqq"] = merged["portfolio_return"] - merged["qqq_return"]

    rows: list[dict[str, Any]] = []
    for keys, part in merged.groupby(
        ["scenario", "segment", "list_type", "horizon_days"],
        dropna=False,
    ):
        scenario, segment, list_type, horizon = keys
        p = part["portfolio_return"].dropna()
        rows.append(
            {
                "scenario": scenario,
                "segment": segment,
                "list_type": list_type,
                "horizon_days": int(horizon),
                "n_events_total": int(len(part)),
                "n_events_valid": int(len(p)),
                "n_no_signal_events": int((part.get("event_status") == "no_signal").sum())
                if "event_status" in part
                else 0,
                "n_unpriced_events": int((part.get("event_status") == "unpriced").sum())
                if "event_status" in part
                else 0,
                "avg_return": float(p.mean()) if not p.empty else np.nan,
                "win_rate": float((p > 0).mean()) if not p.empty else np.nan,
                "avg_excess_vs_QQQ": float(part["excess_vs_qqq"].dropna().mean())
                if part["excess_vs_qqq"].notna().any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["scenario", "segment", "list_type", "horizon_days"]
    ).reset_index(drop=True)


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_signal_diagnostics(signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    diagnostic_rows: list[dict[str, Any]] = []
    channel_rows: list[dict[str, Any]] = []
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()

    for row in signals.itertuples(index=False):
        base = {
            "scenario": getattr(row, "scenario", ""),
            "run_stem": getattr(row, "run_stem", ""),
            "signal_date": getattr(row, "signal_date", ""),
            "list_type": getattr(row, "list_type", ""),
            "watchlist_source": getattr(row, "watchlist_source", ""),
        }
        channel_counts = parse_json_object(getattr(row, "channel_counts", ""))
        channel_symbols = parse_json_object(getattr(row, "channel_symbols", ""))
        filter_diagnostics = parse_json_object(getattr(row, "filter_diagnostics", ""))
        for channel, payload in filter_diagnostics.items():
            if not isinstance(payload, dict):
                continue
            first_fail = payload.get("first_fail") if isinstance(payload.get("first_fail"), dict) else {}
            near_miss = payload.get("near_miss") if isinstance(payload.get("near_miss"), dict) else {}
            channel_rows.append(
                {
                    **base,
                    "channel": channel,
                    "n_input": int(payload.get("n_input", 0) or 0),
                    "n_filtered": int(payload.get("n_filtered", 0) or 0),
                    "n_ranked": int(payload.get("n_ranked", 0) or 0),
                    "n_selected_channel": int(channel_counts.get(channel, 0) or 0),
                    "selected_symbols": ",".join(str(x) for x in channel_symbols.get(channel, []))
                    if isinstance(channel_symbols.get(channel), list)
                    else "",
                    "top_first_fail": str(first_fail.get("top_reason", "")),
                    "top_first_fail_pct": float(first_fail.get("top_pct", 0.0) or 0.0),
                    "top_near_miss": str(near_miss.get("top_reason", "")),
                    "top_near_miss_pct": float(near_miss.get("top_pct", 0.0) or 0.0),
                    "near_miss_reasons": json.dumps(
                        near_miss.get("reasons", []), ensure_ascii=False, sort_keys=True
                    ),
                }
            )
            layer_summary = payload.get("layer_summary")
            if not isinstance(layer_summary, dict):
                continue
            for layer, layer_payload in layer_summary.items():
                if not isinstance(layer_payload, dict):
                    continue
                diagnostic_rows.append(
                    {
                        **base,
                        "channel": channel,
                        "layer": layer,
                        "before": int(layer_payload.get("before", 0) or 0),
                        "remaining": int(layer_payload.get("remaining", 0) or 0),
                        "removed": int(layer_payload.get("removed", 0) or 0),
                        "pass_rate": float(layer_payload.get("pass_rate", 0.0) or 0.0),
                    }
                )

    diagnostics = pd.DataFrame(diagnostic_rows)
    channel_summary = pd.DataFrame(channel_rows)
    return diagnostics, channel_summary
