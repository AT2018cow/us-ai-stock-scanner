"""Extract per-date hard-gate survivor dataset for offline score-weight sweeps.

Runs the same PIT replay as run_backtest.py (base scenario only) but, instead of
saving only the selected top-N symbols, saves EVERY hard-gate survivor per
(signal_date, list_type, channel) together with:

- all cross-section metric columns (raw inputs for score_and_rank)
- soft_pass_count / soft_total (the soft layer is threshold-based, weight-independent)
- forward returns at each horizon (entry/exit/cost conventions identical to the backtest)
- QQQ benchmark forward returns per (signal_date, horizon)
- regime / benchmark_trailing_60d for regime-conditional scoring

The resulting CSV is the offline playground for sweeping score_weights:
weights only change ranking WITHIN survivors, so one extraction supports
thousands of weight configurations with zero additional backtests.

Usage:
    python scripts/extract_weight_dataset.py --scan-config configs/config.risk_off.json
    python scripts/extract_weight_dataset.py --scan-config configs/config.risk_on.json \
        --output outputs/weight_dataset_risk_on.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.backtest import (
    apply_split_adjustment_to_frame,
    benchmark_trailing_return_asof,
    benchmark_trend_ok_asof,
    build_bar_db,
    build_cross_section_asof,
    build_fundamental_pti_db,
    build_rebalance_dates,
    build_steps_and_weights,
    build_theme_scores_rules_proxy,
    build_universe_for_replay,
    build_union_watchlist_map,
    compute_price_features_asof,
    load_alpaca_client,
    load_sec_client,
    load_watchlist_snapshots,
    normalize_symbol_list,
    parse_date_utc,
    resolve_watchlist_asof,
    union_watchlist_allowlist,
)
from ai_value_scanner.config import load_config
from ai_value_scanner.evaluation.backtest import (
    _hold_window_mature,
    forward_return,
    forward_return_with_exit,
)
from ai_value_scanner.strategy.filtering import (
    apply_filters_with_diagnostics,
    partition_filter_steps,
)


def log(msg: str, started: float) -> None:
    elapsed = time.monotonic() - started
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[extract {stamp} +{elapsed / 60:.1f}m] {msg}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extract hard-gate survivor dataset for weight sweeps.")
    p.add_argument("--scan-config", default="configs/config.risk_off.json")
    p.add_argument("--output", default=None, help="Output CSV path (default: outputs/weight_dataset_<style>.csv)")
    p.add_argument("--list-types", default="low_value,momentum")
    p.add_argument("--start-date", default="2023-01-01")
    p.add_argument("--end-date", default=None)
    p.add_argument("--rebalance-frequency", default="monthly", choices=["weekly", "monthly"])
    p.add_argument("--horizons", default="20,60,120")
    p.add_argument("--trading-cost-bps", type=float, default=15.0)
    p.add_argument("--entry-price-mode", default="next_open", choices=["next_open", "next_close"])
    p.add_argument("--exit-price-mode", default="close", choices=["close", "open"])
    p.add_argument("--replay-max-symbols", type=int, default=800)
    p.add_argument("--replay-asset-status", default="all", choices=["all", "active", "inactive"])
    p.add_argument("--watchlist-history-dir", default="data/watchlist_history")
    p.add_argument("--allow-latest-watchlist-fallback", action="store_true", default=False)
    p.add_argument("--no-latest-watchlist-fallback", action="store_true")
    p.add_argument("--pre-snapshot-universe", default="union", choices=["union", "strict"],
                   help="Universe for replay dates before the first PIT snapshot: "
                        "union (all snapshots + current list, PIT data availability filters; default) "
                        "or strict (legacy empty universe).")
    p.add_argument("--disclosure-lookback-days", type=int, default=720)
    p.add_argument("--theme-source", default="rules_proxy", choices=["rules_proxy", "zero"])
    p.add_argument("--delist-return-assumption", type=float, default=-0.55)
    p.add_argument("--delist-detection-buffer-days", type=int, default=7)
    p.add_argument("--include-channels", default=None, help="Comma-separated channels (default: all in config)")
    return p


def main() -> None:
    args = build_parser().parse_args()
    started = time.monotonic()

    if bool(args.allow_latest_watchlist_fallback and not args.no_latest_watchlist_fallback):
        log(
            "WARNING: --allow-latest-watchlist-fallback is ON: signal dates "
            "without PIT watchlist snapshots will use the latest (future) "
            "constituents — dataset contains lookahead bias. Research-only.",
            started,
        )

    scan_config_path = str(args.scan_config)
    style = "risk_on" if "risk_on" in Path(scan_config_path).name else "risk_off"
    output_path = Path(args.output) if args.output else Path(f"outputs/weight_dataset_{style}.csv")
    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    list_types = [x.strip() for x in str(args.list_types).split(",") if x.strip()]
    roundtrip_cost = (2.0 * args.trading_cost_bps) / 10000.0
    allow_fallback = args.allow_latest_watchlist_fallback and not args.no_latest_watchlist_fallback

    scan_config = load_config(scan_config_path)
    scan_config.max_symbols = args.replay_max_symbols

    client, monitor = load_alpaca_client(scan_config)
    sec = load_sec_client(scan_config, monitor)

    snapshots, latest_watchlist_map = load_watchlist_snapshots(
        type("Cfg", (), {
            "use_historical_watchlist": True,
            "watchlist_history_dir": args.watchlist_history_dir,
            "allow_latest_watchlist_fallback": allow_fallback,
        })(),
        scan_config,
    )
    # Union allowlist: every symbol ever seen (all snapshots + current list).
    # PIT data availability per signal date does the actual time filtering
    # downstream; ordering stays neutral (see prefetch comment below).
    watchlist_allowlist = union_watchlist_allowlist(snapshots, latest_watchlist_map)
    union_map = build_union_watchlist_map(snapshots, latest_watchlist_map)
    if not watchlist_allowlist:
        raise ValueError("No watchlist symbols available for replay.")

    log(f"style={style} | watchlist symbols={len(watchlist_allowlist)}", started)

    base_universe = build_universe_for_replay(
        client=client,
        sec=sec,
        scan_config=scan_config,
        asset_status=args.replay_asset_status,
        symbol_allowlist=watchlist_allowlist,
    )
    base_universe = base_universe.dropna(subset=["symbol"]).copy()
    base_universe["symbol"] = base_universe["symbol"].astype(str).str.upper()
    base_universe = base_universe[base_universe["symbol"].isin(watchlist_allowlist)].copy()

    prefetch_universe = base_universe.copy()
    if args.replay_max_symbols and args.replay_max_symbols > 0:
        if args.replay_asset_status == "all":
            prefetch_n = min(len(prefetch_universe), max(args.replay_max_symbols * 25, args.replay_max_symbols))
        else:
            prefetch_n = min(len(prefetch_universe), args.replay_max_symbols)
        # Truncation order inherits (status, symbol) from build_universe_for_replay:
        # performance-neutral by construction. Do NOT sort by liquidity/volume
        # here — that would tilt historical replay toward present winners.
        prefetch_universe = prefetch_universe.head(prefetch_n)

    symbols = prefetch_universe["symbol"].dropna().astype(str).tolist()
    benchmark_etfs = normalize_symbol_list([str(x).upper() for x in (scan_config.ai_link_benchmark_etfs or [])])
    trend_filter_symbol = str(scan_config.benchmark_trend_filter_symbol or "").upper().strip()
    regime_symbol = str(scan_config.benchmark_trend_filter_symbol or "QQQ").upper()
    bars_symbols = normalize_symbol_list(
        symbols + benchmark_etfs + [s for s in (trend_filter_symbol, regime_symbol) if s]
    )

    start_dt = parse_date_utc(args.start_date) or datetime(2023, 1, 1, tzinfo=timezone.utc)
    end_dt = parse_date_utc(args.end_date) or datetime.now(timezone.utc)
    bars_start = (start_dt - pd.Timedelta(days=max(420, scan_config.price_lookback_days))).isoformat()

    log(f"universe symbols={len(symbols)} | fetching bars from {bars_start[:10]}", started)
    bar_db = build_bar_db(client, bars_symbols, bars_start, scan_config.chunk_size)
    log(f"symbols with bars={len(bar_db)}", started)
    # Authoritative splits for the replay window (same discipline as the live
    # scan and the backtest replay): price features, benchmark returns and
    # forward returns use split-adjusted series; valuation multiples keep raw
    # closes x raw filed shares. Fail open.
    split_events: dict[str, list[tuple[str, float]]] = {}
    try:
        split_events = client.get_corporate_action_splits(
            bars_symbols, bars_start,
            (end_dt or datetime.now(timezone.utc)).date().isoformat(),
        )
        if split_events:
            log(f"split events: {len(split_events)} symbols", started)
    except Exception as exc:
        log(f"corporate-actions split fetch failed ({exc.__class__.__name__}); replay unadjusted", started)

    universe = prefetch_universe[prefetch_universe["symbol"].isin(set(bar_db.keys()))].copy()
    universe = universe.dropna(subset=["cik"]).copy()
    if args.replay_max_symbols and args.replay_max_symbols > 0:
        universe = universe.head(args.replay_max_symbols).copy()

    fundamentals = build_fundamental_pti_db(universe, sec, max_workers=scan_config.max_workers)
    log(f"fundamentals loaded={len(fundamentals)}", started)

    if args.theme_source == "rules_proxy":
        theme_scores = build_theme_scores_rules_proxy(
            universe=universe,
            fundamentals=fundamentals,
            scan_config=scan_config,
        )
        log(f"rules-proxy theme map size={len(theme_scores)}", started)
    else:
        theme_scores = {}

    dates = build_rebalance_dates(start_dt, end_dt, args.rebalance_frequency)
    log(f"rebalance dates={len(dates)}", started)

    global_end_date = None
    if bar_db:
        all_last = [pd.Timestamp(s.index.max()).tz_convert("UTC") for s in bar_db.values() if not s.empty]
        if all_last:
            global_end_date = max(all_last)

    channel_profiles = scan_config.channel_profiles or {}
    if args.include_channels:
        wanted = [x.strip() for x in args.include_channels.split(",") if x.strip()]
        channel_profiles = {k: v for k, v in channel_profiles.items() if k in wanted}

    scored_mode = str(getattr(scan_config, "filter_mode", "scored")).lower() == "scored"
    rows: list[dict[str, Any]] = []
    qqq_rows: list[dict[str, Any]] = []
    last_heartbeat = 0.0

    for i, asof in enumerate(dates, start=1):
        now_tick = time.monotonic()
        if i == 1 or i == len(dates) or (now_tick - last_heartbeat) >= 30.0:
            log(f"progress {i}/{len(dates)} asof={asof.date().isoformat()}", started)
            last_heartbeat = now_tick

        benchmark_trailing_60d = benchmark_trailing_return_asof(
            bar_db, regime_symbol, asof, 60, split_events.get(regime_symbol)
        )
        regime = "unknown"
        if benchmark_trailing_60d is not None:
            regime = "up" if benchmark_trailing_60d >= 0 else "down"

        watchlist_by_symbol, watchlist_source = resolve_watchlist_asof(
            asof=asof,
            snapshots=snapshots,
            latest_map=latest_watchlist_map,
            allow_latest_fallback=allow_fallback,
            pre_snapshot_mode=args.pre_snapshot_universe,
            union_map=union_map,
        )
        if not watchlist_by_symbol:
            continue

        benchmark_returns_20d: list[float] = []
        benchmark_returns_60d: list[float] = []
        for etf in benchmark_etfs:
            etf_bars = bar_db.get(etf)
            if etf_bars is None:
                continue
            etf_feat = compute_price_features_asof(
                etf_bars, asof=asof, lookback_days=scan_config.price_lookback_days,
                split_events=split_events.get(etf),
            )
            if not etf_feat:
                continue
            r20 = etf_feat.get("return_20d")
            r60 = etf_feat.get("return_60d")
            if r20 is not None and np.isfinite(float(r20)):
                benchmark_returns_20d.append(float(r20))
            if r60 is not None and np.isfinite(float(r60)):
                benchmark_returns_60d.append(float(r60))
        benchmark_median_return_20d = float(np.median(benchmark_returns_20d)) if benchmark_returns_20d else None
        benchmark_median_return_60d = float(np.median(benchmark_returns_60d)) if benchmark_returns_60d else None

        qqq_frame = apply_split_adjustment_to_frame(
            bar_db.get("QQQ"), split_events.get("QQQ")
        )
        for h in horizons:
            qqq_ret = None
            qqq_end = None
            if qqq_frame is not None:
                # Same roundtrip cost as the per-symbol legs: sweep/IC excess
                # math (fwd_ret - qqq_return) must compare cost-loaded returns
                # on both sides (same convention as event_backtest benchmarks).
                qqq_ret, qqq_end = forward_return_with_exit(
                    qqq_frame,
                    asof.date().isoformat(),
                    h,
                    roundtrip_cost,
                    entry_price_mode=args.entry_price_mode,
                    exit_price_mode=args.exit_price_mode,
                    global_end_date=global_end_date,
                )
            qqq_rows.append(
                {
                    "signal_date": asof.date().isoformat(),
                    "horizon_days": h,
                    "qqq_return": qqq_ret,
                    "qqq_label_end": qqq_end.date().isoformat() if qqq_end is not None else None,
                }
            )

        df = build_cross_section_asof(
            asof=asof,
            universe=universe,
            bar_db=bar_db,
            fundamentals=fundamentals,
            theme_scores=theme_scores,
            watchlist_by_symbol=watchlist_by_symbol,
            benchmark_return_20d=benchmark_median_return_20d,
            benchmark_return_60d=benchmark_median_return_60d,
            disclosure_lookback_days=args.disclosure_lookback_days,
            scan_config=scan_config,
            benchmark_trend_ok=(
                benchmark_trend_ok_asof(
                    bar_db, trend_filter_symbol, asof, scan_config.benchmark_trend_filter_sma_days,
                    split_events.get(trend_filter_symbol),
                )
                if trend_filter_symbol
                else None
            ),
            split_events=split_events,
        )
        if df.empty:
            continue

        for list_type in list_types:
            for channel_name, channel_profile in channel_profiles.items():
                steps, _weights = build_steps_and_weights(scan_config, channel_name, channel_profile, list_type)
                if scored_mode:
                    hard_steps, soft_steps = partition_filter_steps(steps, channel_name)
                else:
                    hard_steps, soft_steps = steps, []
                survivors, _diag = apply_filters_with_diagnostics(df, hard_steps)
                if survivors.empty:
                    continue
                survivors = survivors.copy()
                if soft_steps:
                    soft_matrix = pd.DataFrame(
                        {name: mask_fn(survivors) for name, mask_fn in soft_steps},
                        index=survivors.index,
                    )
                    survivors["soft_pass_count"] = soft_matrix.sum(axis=1)
                    survivors["soft_total"] = len(soft_steps)
                else:
                    survivors["soft_pass_count"] = np.nan
                    survivors["soft_total"] = np.nan

                for idx, row in survivors.iterrows():
                    symbol = str(row.get("symbol", "")).upper()
                    frame = apply_split_adjustment_to_frame(
                        bar_db.get(symbol), split_events.get(symbol)
                    )
                    rec = {
                        "signal_date": asof.date().isoformat(),
                        "channel": channel_name,
                        "list_type": list_type,
                        "symbol": symbol,
                        "regime": regime,
                        "benchmark_trailing_60d": benchmark_trailing_60d,
                        "soft_pass_count": row.get("soft_pass_count", np.nan),
                        "soft_total": row.get("soft_total", np.nan),
                    }
                    for col in df.columns:
                        if col in ("symbol",):
                            continue
                        rec[col] = row.get(col)
                    for h in horizons:
                        if frame is not None and not frame.empty:
                            fwd, label_end = forward_return_with_exit(
                                frame,
                                asof.date().isoformat(),
                                h,
                                roundtrip_cost,
                                entry_price_mode=args.entry_price_mode,
                                exit_price_mode=args.exit_price_mode,
                                global_end_date=global_end_date,
                                delist_return_assumption=args.delist_return_assumption,
                                delist_detection_buffer_days=args.delist_detection_buffer_days,
                            )
                        elif (
                            args.delist_return_assumption is not None
                            and _hold_window_mature(
                                asof.date().isoformat(), h,
                                args.delist_detection_buffer_days, global_end_date,
                            )
                        ):
                            # Scored name with no price data on a mature hold
                            # window: delist-like disappearance, not a data gap.
                            fwd = float(args.delist_return_assumption) - roundtrip_cost
                            label_end = None
                        else:
                            fwd = None
                            label_end = None
                        rec[f"fwd_ret_{h}"] = fwd
                        # R04: exact label exit date for train/valid boundary
                        # clearing (None = delist-assumed or immature).
                        rec[f"label_end_{h}"] = (
                            label_end.date().isoformat() if label_end is not None else None
                        )
                    rows.append(rec)

    dataset = pd.DataFrame(rows)
    qqq_df = pd.DataFrame(qqq_rows).drop_duplicates(subset=["signal_date", "horizon_days"], keep="last")
    if not dataset.empty:
        # Attach per-horizon QQQ benchmark returns (constant within a signal date)
        for h in horizons:
            qqq_h = qqq_df[qqq_df["horizon_days"] == h][["signal_date", "qqq_return", "qqq_label_end"]]
            qqq_h = qqq_h.rename(columns={"qqq_return": f"qqq_return_{h}", "qqq_label_end": f"qqq_label_end_{h}"})
            dataset = dataset.merge(qqq_h, on="signal_date", how="left")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(output_path, index=False)

    snap_dates = []
    for dt, _, _ in snapshots:
        try:
            snap_dates.append(pd.to_datetime(dt))
        except (TypeError, ValueError):
            continue
    req_start = parse_date_utc(args.start_date) or datetime(2023, 1, 1, tzinfo=timezone.utc)
    req_end = parse_date_utc(args.end_date) or datetime.now(timezone.utc)
    pre_union = args.pre_snapshot_universe == "union"
    if not snap_dates:
        if pre_union:
            watchlist_source = (
                "union_superset_approx (current watchlist; no PIT snapshots — "
                "membership/etf_count are current-value approximations)"
            )
        elif allow_fallback:
            watchlist_source = "latest_fallback_only (LOOKAHEAD: no PIT snapshots in watchlist_history_dir)"
        else:
            watchlist_source = "none (no PIT snapshots; per-date replay universe empty)"
    elif min(snap_dates) <= req_start:
        watchlist_source = "pit_snapshots"
    elif pre_union:
        watchlist_source = (
            "mixed: pit_snapshots from "
            f"{min(snap_dates).date().isoformat()} + union_superset_approx before that "
            "(membership/etf_count approximated from earliest snapshot or current list; "
            "PIT data availability filters candidates; documented upward bias)"
        )
    elif allow_fallback:
        watchlist_source = (
            "mixed: pit_snapshots where available + latest_fallback "
            f"(LOOKAHEAD before {min(snap_dates).date().isoformat()})"
        )
    else:
        watchlist_source = (
            f"pit_snapshots (from {min(snap_dates).date().isoformat()}); "
            "earlier signal dates have no universe (strict mode)"
        )
    meta = {
        "scan_config": scan_config_path,
        "style": style,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "start_date": str(args.start_date),
        "end_date": str(args.end_date),
        "rebalance_frequency": args.rebalance_frequency,
        "horizons": horizons,
        "list_types": list_types,
        "trading_cost_bps": args.trading_cost_bps,
        "roundtrip_cost": roundtrip_cost,
        "entry_price_mode": args.entry_price_mode,
        "exit_price_mode": args.exit_price_mode,
        "theme_source": args.theme_source,
        "replay_asset_status": args.replay_asset_status,
        "replay_max_symbols": args.replay_max_symbols,
        "disclosure_lookback_days": args.disclosure_lookback_days,
        "delist_return_assumption": args.delist_return_assumption,
        "allow_latest_watchlist_fallback": allow_fallback,
        "pre_snapshot_universe": args.pre_snapshot_universe,
        "channels": sorted(channel_profiles.keys()),
        "n_rows": int(len(dataset)),
        "n_dates": int(dataset["signal_date"].nunique()) if not dataset.empty else 0,
        "watchlist_source": watchlist_source,
    }
    meta_path = output_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))

    log(
        f"done: {len(dataset)} survivor rows | {meta['n_dates']} dates | "
        f"saved {output_path} (+ {meta_path.name})",
        started,
    )


if __name__ == "__main__":
    main()
