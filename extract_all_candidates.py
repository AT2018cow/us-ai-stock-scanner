"""
利用已有缓存，重新执行扫描的前4/6阶段（数据拉取与指标计算），
在硬过滤之前导出完整候选池，再筛选：free_cash_flow < 0 & net_income > 0
"""
import sys, re
sys.path.insert(0, "src")

from ai_value_scanner.scanner import (
    ScanConfig,
    load_config,
    load_runtime_settings,
    load_watchlist_scores,
    collect_candidates,
    collect_fundamentals,
    price_dimension_from_bars,
    normalize_equity_symbol,
    bars_return_from_lookback,
    extract_close_history_from_bars,
    parse_history_pairs,
    compute_historical_valuation_percentile,
    ai_etf_consensus_score,
    ai_market_link_score,
    safe_divide,
    log_status,
)
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta


def run_extract(config_path: str, out_csv: str) -> None:
    started_at = datetime.now(timezone.utc)
    config = load_config(config_path)
    alpaca, sec, _ = load_runtime_settings(config)

    print("[1/6] Loading watchlist...")
    watchlist_scores = load_watchlist_scores(config)
    watchlist_allowlist = set(watchlist_scores["symbol"].dropna().astype(str).tolist())
    print(f"  Watchlist: {len(watchlist_allowlist)} symbols")

    print("[2/6] Collecting candidates...")
    df = collect_candidates(alpaca, sec, config, symbol_allowlist=watchlist_allowlist)
    df = df[
        df["price"].notna()
        & (pd.to_numeric(df["price"], errors="coerce") >= config.min_price)
        & (pd.to_numeric(df["dollar_volume"], errors="coerce").fillna(0) >= config.min_dollar_volume)
    ].copy()
    print(f"  After prefilter: {len(df)}")

    print("[3/6] Price features...")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    bars_start_dt = (datetime.now(timezone.utc) - timedelta(days=config.price_lookback_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    bars_start_iso = bars_start_dt.isoformat().replace("+00:00", "Z")
    symbols_for_bars = df["symbol"].dropna().astype(str).tolist()
    benchmark_symbols = sorted(
        {
            normalize_equity_symbol(sym)
            for sym in (config.ai_link_benchmark_etfs or [])
            if normalize_equity_symbol(sym)
        }
    )
    bars_map = alpaca.get_daily_bars(sorted(set(symbols_for_bars + benchmark_symbols)), bars_start_iso, config.chunk_size)

    benchmark_returns_20d: list[float] = []
    benchmark_returns_60d: list[float] = []
    for etf in benchmark_symbols:
        bench_bars = bars_map.get(etf, [])
        ret20 = bars_return_from_lookback(bench_bars, 20)
        ret60 = bars_return_from_lookback(bench_bars, 60)
        if ret20 is not None and np.isfinite(ret20):
            benchmark_returns_20d.append(float(ret20))
        if ret60 is not None and np.isfinite(ret60):
            benchmark_returns_60d.append(float(ret60))
    benchmark_median_return_20d = float(np.median(np.asarray(benchmark_returns_20d, dtype="float64"))) if benchmark_returns_20d else None
    benchmark_median_return_60d = float(np.median(np.asarray(benchmark_returns_60d, dtype="float64"))) if benchmark_returns_60d else None

    price_rows = []
    for row in df.itertuples(index=False):
        features = price_dimension_from_bars(row.price, bars_map.get(row.symbol, []))
        price_rows.append({"symbol": row.symbol, **features})
    df = df.merge(pd.DataFrame(price_rows), on="symbol", how="left")

    print("[4/6] Fundamentals & valuation...")
    fundamentals = collect_fundamentals(df, sec, config)
    df = df.merge(fundamentals, on="symbol", how="left")

    for col, default in [
        ("ps_hist_percentile", np.nan), ("pe_hist_percentile", np.nan),
        ("ps_hist_observation_count", np.nan), ("pe_hist_observation_count", np.nan),
        ("ps_hist_percentile_source", "insufficient_history"),
        ("pe_hist_percentile_source", "insufficient_history"),
        ("revenue_ttm_history_json", None), ("net_income_ttm_history_json", None), ("shares_history_json", None),
    ]:
        if col not in df.columns:
            df[col] = default

    for col in [
        "price","dollar_volume","shares_outstanding","revenue","net_income",
        "adjusted_net_income","operating_cash_flow","free_cash_flow","ebit","adjusted_ebit",
        "adjusted_ebitda","cash_and_equivalents","total_debt","net_debt",
        "interest_expense","depreciation_and_amortization","current_assets","current_liabilities",
        "receivables_current","inventory_current","revenue_yoy","net_income_yoy",
        "adjusted_net_income_yoy","ebit_yoy","adjusted_ebit_yoy","da_yoy",
        "operating_cash_flow_yoy","shares_yoy","receivables_yoy","inventory_yoy",
        "receivables_growth_gap","inventory_growth_gap","nonrecurring_expense_addback",
        "nonrecurring_gain_subtraction","interest_coverage","net_debt_to_ebitda",
        "current_ratio","current_debt_ratio_reported","current_debt_ratio_inferred",
        "ocf_to_net_income","accrual_ratio","inventory_growth_gap_reported",
        "inventory_growth_gap_inferred","fundamental_quality_score",
        "ai_disclosure_score","ai_disclosure_group_hits","ai_disclosure_keyword_hits","ai_backlog_signal",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["market_cap"] = df["price"] * df["shares_outstanding"]
    df["enterprise_value"] = df["market_cap"] + df["total_debt"].fillna(0) - df["cash_and_equivalents"].fillna(0)
    earnings_col = "adjusted_net_income" if config.use_adjusted_quality_metrics else "net_income"
    ebit_col = "adjusted_ebit" if config.use_adjusted_quality_metrics else "ebit"
    earnings_yoy_col = "adjusted_net_income_yoy" if config.use_adjusted_quality_metrics else "net_income_yoy"
    df["ps"] = safe_divide(df["market_cap"], df["revenue"])
    df["pe"] = safe_divide(df["market_cap"], df[earnings_col])
    df["ev_to_ebit"] = safe_divide(df["enterprise_value"], df[ebit_col])
    df["fcf_yield"] = safe_divide(df["free_cash_flow"], df["market_cap"])
    df["net_margin"] = safe_divide(df[earnings_col], df["revenue"])

    ps_hist_values: list[float | None] = []
    pe_hist_values: list[float | None] = []
    ps_hist_obs: list[int] = []
    pe_hist_obs: list[int] = []
    ps_hist_sources: list[str] = []
    pe_hist_sources: list[str] = []
    for row in df.itertuples(index=False):
        closes = extract_close_history_from_bars(bars_map.get(row.symbol, []))
        revenue_hist = parse_history_pairs(getattr(row, "revenue_ttm_history_json", None))
        net_income_hist = parse_history_pairs(getattr(row, "net_income_ttm_history_json", None))
        shares_hist = parse_history_pairs(getattr(row, "shares_history_json", None))
        current_shares = float(row.shares_outstanding) if pd.notna(row.shares_outstanding) else None
        current_ps = float(row.ps) if pd.notna(row.ps) else None
        current_pe = float(row.pe) if pd.notna(row.pe) else None
        ps_hist_pct, ps_obs = compute_historical_valuation_percentile(
            current_multiple=current_ps, closes=closes, denominator_history=revenue_hist,
            shares_history=shares_hist, current_shares=current_shares,
            window_days=config.own_history_valuation_window_days, min_observations=3,
        )
        pe_hist_pct, pe_obs = compute_historical_valuation_percentile(
            current_multiple=current_pe, closes=closes, denominator_history=net_income_hist,
            shares_history=shares_hist, current_shares=current_shares,
            window_days=config.own_history_valuation_window_days, min_observations=3,
        )
        ps_hist_values.append(ps_hist_pct)
        pe_hist_values.append(pe_hist_pct)
        ps_hist_obs.append(int(ps_obs))
        pe_hist_obs.append(int(pe_obs))
        ps_hist_sources.append("valuation_history" if ps_hist_pct is not None else "insufficient_history")
        pe_hist_sources.append("valuation_history" if pe_hist_pct is not None else "insufficient_history")

    df["ps_hist_percentile"] = ps_hist_values
    df["pe_hist_percentile"] = pe_hist_values
    df["ps_hist_observation_count"] = ps_hist_obs
    df["pe_hist_observation_count"] = pe_hist_obs
    df["ps_hist_percentile_source"] = ps_hist_sources
    df["pe_hist_percentile_source"] = pe_hist_sources
    df["expectation_proxy"] = (
        0.5 * pd.to_numeric(df["revenue_yoy"], errors="coerce").fillna(0)
        + 0.5 * pd.to_numeric(df[earnings_yoy_col], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(df["return_20d"], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(df["return_60d"], errors="coerce").fillna(0)
    )
    df["cycle_proxy"] = pd.to_numeric(df["adjusted_ebit_yoy"], errors="coerce").fillna(
        pd.to_numeric(df["ebit_yoy"], errors="coerce")
    ) - pd.to_numeric(df["revenue_yoy"], errors="coerce")
    df["adv_participation"] = safe_divide(pd.Series(float(config.assumed_position_usd), index=df.index), df["avg_dollar_volume_20d"])
    df["estimated_slippage_bps"] = 200.0 * np.sqrt(pd.to_numeric(df["adv_participation"], errors="coerce").clip(lower=0))

    # Exclude names with stale/missing share counts from peer medians so a
    # distorted market cap (e.g. BIDU, last share count reported 2010) does
    # not skew SIC-relative valuation multiples.
    stale_mask = pd.Series(False, index=df.index)
    if "shares_stale" in df.columns:
        stale_mask = pd.to_numeric(df["shares_stale"], errors="coerce").fillna(0).astype(bool)
    peer_ps = df.loc[np.isfinite(df["ps"]) & (df["ps"] > 0) & ~stale_mask].groupby("sic", dropna=True)["ps"].median().rename("peer_median_ps")
    peer_pe = df.loc[np.isfinite(df["pe"]) & (df["pe"] > 0) & ~stale_mask].groupby("sic", dropna=True)["pe"].median().rename("peer_median_pe")
    df = df.merge(peer_ps, left_on="sic", right_index=True, how="left")
    df = df.merge(peer_pe, left_on="sic", right_index=True, how="left")
    df["ps_discount"] = 1 - safe_divide(df["ps"], df["peer_median_ps"])
    df["pe_discount"] = 1 - safe_divide(df["pe"], df["peer_median_pe"])

    df["ps_percentile_in_sic"] = 0.5
    ps_valid = np.isfinite(df["ps"]) & (df["ps"] > 0) & df["sic"].notna() & ~stale_mask
    ps_sizes = df.loc[ps_valid].groupby("sic")["ps"].transform("size")
    ps_rank = df.loc[ps_valid].groupby("sic")["ps"].rank(method="average", pct=True)
    ps_eligible_idx = ps_sizes[ps_sizes >= 5].index
    df.loc[ps_eligible_idx, "ps_percentile_in_sic"] = ps_rank.loc[ps_eligible_idx]

    df["pe_percentile_in_sic"] = 0.5
    pe_valid = np.isfinite(df["pe"]) & (df["pe"] > 0) & df["sic"].notna() & ~stale_mask
    pe_sizes = df.loc[pe_valid].groupby("sic")["pe"].transform("size")
    pe_rank = df.loc[pe_valid].groupby("sic")["pe"].rank(method="average", pct=True)
    pe_eligible_idx = pe_sizes[pe_sizes >= 5].index
    df.loc[pe_eligible_idx, "pe_percentile_in_sic"] = pe_rank.loc[pe_eligible_idx]

    print("[5/6] Watchlist attributes...")
    df = df.merge(watchlist_scores, on="symbol", how="left")
    for missing_col, default_val in [
        ("watchlist_etf_count", 0), ("watchlist_bucket", ""), ("watchlist_etfs", ""),
    ]:
        if missing_col not in df.columns:
            df[missing_col] = default_val
    df["watchlist_etf_count"] = pd.to_numeric(df["watchlist_etf_count"], errors="coerce").fillna(0).astype(int)
    df["watchlist_bucket"] = df["watchlist_bucket"].fillna("").astype(str)
    df["watchlist_etfs"] = df["watchlist_etfs"].fillna("").astype(str)
    df["ai_etf_consensus_score"] = df["watchlist_etf_count"].apply(lambda x: ai_etf_consensus_score(x, config.ai_link_etf_count_saturation))
    df["ai_market_link_score"] = df.apply(
        lambda row: ai_market_link_score(
            symbol_return_20d=(float(row["return_20d"]) if pd.notna(pd.to_numeric(row["return_20d"], errors="coerce")) else None),
            symbol_return_60d=(float(row["return_60d"]) if pd.notna(pd.to_numeric(row["return_60d"], errors="coerce")) else None),
            benchmark_return_20d=benchmark_median_return_20d,
            benchmark_return_60d=benchmark_median_return_60d,
            tol_20d=float(config.ai_link_market_return_tolerance_20d),
            tol_60d=float(config.ai_link_market_return_tolerance_60d),
        ), axis=1,
    )
    if "ai_disclosure_score" not in df.columns:
        df["ai_disclosure_score"] = 0.0
    if "ai_backlog_signal" not in df.columns:
        df["ai_backlog_signal"] = 0.0
    df["ai_disclosure_score"] = pd.to_numeric(df["ai_disclosure_score"], errors="coerce").fillna(0.0)
    df["ai_backlog_signal"] = pd.to_numeric(df["ai_backlog_signal"], errors="coerce").fillna(0.0)
    df["ai_link_score"] = (
        0.40 * pd.to_numeric(df["ai_etf_consensus_score"], errors="coerce").fillna(0.0)
        + 0.35 * pd.to_numeric(df["ai_disclosure_score"], errors="coerce").fillna(0.0)
        + 0.15 * pd.to_numeric(df["ai_market_link_score"], errors="coerce").fillna(0.0)
        + 0.10 * pd.to_numeric(df["ai_backlog_signal"], errors="coerce").fillna(0.0)
    ).clip(lower=0.0, upper=1.0)
    df["news_count"] = 0

    df.to_csv(out_csv, index=False)
    print(f"  Exported => {out_csv} ({len(df)} rows)")


if __name__ == "__main__":
    run_extract("configs/config.balanced.json", "outputs/all_candidates_metrics.csv")
