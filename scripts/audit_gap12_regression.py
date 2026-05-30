#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ai_value_scanner.scanner import (
    ScanConfig,
    apply_filters_with_diagnostics,
    apply_group_caps,
    build_filter_steps,
    build_industry_trend_steps,
    build_momentum_steps,
    collect_candidates,
    collect_fundamentals,
    compute_price_history_percentile,
    dedupe_symbol_by_best_channel,
    drop_symbols,
    load_config,
    load_runtime_settings,
    load_watchlist_scores,
    price_dimension_from_bars,
    safe_divide,
    score_and_rank,
    summarize_first_fail_reasons,
)


LIST_TYPES = ("low_value", "industry_trend", "momentum")
NEW_METRIC_COVERAGE_FIELDS = [
    "ps_hist_percentile",
    "pe_hist_percentile",
    "interest_coverage",
    "net_debt_to_ebitda",
    "current_ratio",
    "current_debt_ratio",
    "ocf_to_net_income",
    "accrual_ratio",
    "receivables_growth_gap",
    "inventory_growth_gap",
    "shares_yoy",
    "fundamental_quality_score",
    "expectation_proxy",
    "cycle_proxy",
    "adv_participation",
    "estimated_slippage_bps",
    "nonrecurring_expense_addback",
    "nonrecurring_gain_subtraction",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit gap-12 metrics with baseline/new regression.")
    p.add_argument("--config", default="config.production.json")
    p.add_argument("--max-symbols", type=int, default=None)
    p.add_argument("--output-dir", default="outputs/audits")
    return p.parse_args()


def build_frame(config: ScanConfig) -> tuple[pd.DataFrame, dict[str, int]]:
    alpaca, sec, _ = load_runtime_settings(config)
    watchlist_scores = load_watchlist_scores(config)
    if watchlist_scores.empty:
        raise ValueError("watchlist is empty; run refresh_ai_watchlist first.")
    allow = set(watchlist_scores["symbol"].dropna().astype(str).tolist())

    df = collect_candidates(alpaca, sec, config, symbol_allowlist=allow)
    universe_count = len(df)
    df = df[
        df["price"].notna()
        & (pd.to_numeric(df["price"], errors="coerce") >= config.min_price)
        & (pd.to_numeric(df["dollar_volume"], errors="coerce").fillna(0) >= config.min_dollar_volume)
    ].copy()
    prefilter_count = len(df)

    bars_start_dt = (datetime.now(timezone.utc) - timedelta(days=config.price_lookback_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    bars_start_iso = bars_start_dt.isoformat().replace("+00:00", "Z")
    symbols = df["symbol"].dropna().astype(str).tolist()
    bars_map = alpaca.get_daily_bars(symbols, bars_start_iso, config.chunk_size)

    price_rows: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        bars = bars_map.get(row.symbol, [])
        feat = price_dimension_from_bars(row.price, bars)
        hist_pct = compute_price_history_percentile(bars, config.own_history_valuation_window_days)
        feat["ps_hist_percentile"] = hist_pct
        feat["pe_hist_percentile"] = hist_pct
        price_rows.append({"symbol": row.symbol, **feat})
    df = df.merge(pd.DataFrame(price_rows), on="symbol", how="left")

    fundamentals = collect_fundamentals(df, sec, config)
    df = df.merge(fundamentals, on="symbol", how="left")

    for col in [
        "price",
        "dollar_volume",
        "shares_outstanding",
        "revenue",
        "net_income",
        "adjusted_net_income",
        "operating_cash_flow",
        "free_cash_flow",
        "ebit",
        "adjusted_ebit",
        "adjusted_ebitda",
        "cash_and_equivalents",
        "total_debt",
        "net_debt",
        "interest_expense",
        "current_assets",
        "current_liabilities",
        "receivables_current",
        "inventory_current",
        "revenue_yoy",
        "net_income_yoy",
        "adjusted_net_income_yoy",
        "ebit_yoy",
        "adjusted_ebit_yoy",
        "shares_yoy",
        "receivables_growth_gap",
        "inventory_growth_gap",
        "interest_coverage",
        "net_debt_to_ebitda",
        "current_ratio",
        "current_debt_ratio",
        "ocf_to_net_income",
        "accrual_ratio",
        "fundamental_quality_score",
        "ps_hist_percentile",
        "pe_hist_percentile",
        "nonrecurring_expense_addback",
        "nonrecurring_gain_subtraction",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["market_cap"] = df["price"] * df["shares_outstanding"]
    df["enterprise_value"] = df["market_cap"] + df["total_debt"].fillna(0) - df["cash_and_equivalents"].fillna(0)
    df["ps"] = safe_divide(df["market_cap"], df["revenue"])
    df["pe"] = safe_divide(df["market_cap"], df["adjusted_net_income"])
    df["ev_to_ebit"] = safe_divide(df["enterprise_value"], df["adjusted_ebit"])
    df["fcf_yield"] = safe_divide(df["free_cash_flow"], df["market_cap"])
    df["net_margin"] = safe_divide(df["adjusted_net_income"], df["revenue"])

    df["expectation_proxy"] = (
        0.5 * pd.to_numeric(df["revenue_yoy"], errors="coerce").fillna(0)
        + 0.5 * pd.to_numeric(df["adjusted_net_income_yoy"], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(df["return_20d"], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(df["return_60d"], errors="coerce").fillna(0)
    )
    df["cycle_proxy"] = pd.to_numeric(df["adjusted_ebit_yoy"], errors="coerce").fillna(
        pd.to_numeric(df["ebit_yoy"], errors="coerce")
    ) - pd.to_numeric(df["revenue_yoy"], errors="coerce")
    df["adv_participation"] = safe_divide(pd.Series(float(config.assumed_position_usd), index=df.index), df["avg_dollar_volume_20d"])
    df["estimated_slippage_bps"] = 200.0 * np.sqrt(
        pd.to_numeric(df["adv_participation"], errors="coerce").clip(lower=0)
    )

    peer_ps = (
        df.loc[np.isfinite(df["ps"]) & (df["ps"] > 0)]
        .groupby("sic", dropna=True)["ps"]
        .median()
        .rename("peer_median_ps")
    )
    peer_pe = (
        df.loc[np.isfinite(df["pe"]) & (df["pe"] > 0)]
        .groupby("sic", dropna=True)["pe"]
        .median()
        .rename("peer_median_pe")
    )
    df = df.merge(peer_ps, left_on="sic", right_index=True, how="left")
    df = df.merge(peer_pe, left_on="sic", right_index=True, how="left")
    df["ps_discount"] = 1 - safe_divide(df["ps"], df["peer_median_ps"])
    df["pe_discount"] = 1 - safe_divide(df["pe"], df["peer_median_pe"])

    df["ps_percentile_in_sic"] = 0.5
    ps_valid = np.isfinite(df["ps"]) & (df["ps"] > 0) & df["sic"].notna()
    ps_sizes = df.loc[ps_valid].groupby("sic")["ps"].transform("size")
    ps_rank = df.loc[ps_valid].groupby("sic")["ps"].rank(method="average", pct=True)
    ps_eligible_idx = ps_sizes[ps_sizes >= 5].index
    df.loc[ps_eligible_idx, "ps_percentile_in_sic"] = ps_rank.loc[ps_eligible_idx]

    df["pe_percentile_in_sic"] = 0.5
    pe_valid = np.isfinite(df["pe"]) & (df["pe"] > 0) & df["sic"].notna()
    pe_sizes = df.loc[pe_valid].groupby("sic")["pe"].transform("size")
    pe_rank = df.loc[pe_valid].groupby("sic")["pe"].rank(method="average", pct=True)
    pe_eligible_idx = pe_sizes[pe_sizes >= 5].index
    df.loc[pe_eligible_idx, "pe_percentile_in_sic"] = pe_rank.loc[pe_eligible_idx]

    df = df.merge(watchlist_scores, on="symbol", how="left")
    for missing_col, default_val in [
        ("watchlist_etf_count", 0),
        ("watchlist_bucket", ""),
        ("watchlist_etfs", ""),
    ]:
        if missing_col not in df.columns:
            df[missing_col] = default_val
    df["watchlist_etf_count"] = pd.to_numeric(df["watchlist_etf_count"], errors="coerce").fillna(0).astype(int)
    df["watchlist_bucket"] = df["watchlist_bucket"].fillna("").astype(str)
    df["watchlist_etfs"] = df["watchlist_etfs"].fillna("").astype(str)

    meta = {
        "watchlist_rows": int(len(watchlist_scores)),
        "watchlist_unique_symbols": int(watchlist_scores["symbol"].nunique()),
        "universe_after_mapping": int(universe_count),
        "after_prefilter": int(prefilter_count),
    }
    return df, meta


def scenario_config(base: ScanConfig, mode: str) -> ScanConfig:
    cfg = copy.deepcopy(base)
    if mode == "new":
        return cfg
    if mode != "baseline":
        raise ValueError(f"unknown mode: {mode}")
    cfg.use_ttm_metrics = False
    cfg.min_fundamental_quality_score = None
    cfg.max_net_debt_to_ebitda = None
    cfg.min_interest_coverage = None
    cfg.max_current_debt_ratio = None
    cfg.min_current_ratio = None
    cfg.min_ocf_to_net_income = None
    cfg.max_accrual_ratio = None
    cfg.max_receivables_growth_gap = None
    cfg.max_inventory_growth_gap = None
    cfg.max_shares_yoy = None
    cfg.max_ps_hist_percentile = None
    cfg.max_pe_hist_percentile = None
    cfg.min_expectation_proxy = None
    cfg.min_cycle_proxy = None
    cfg.max_adv_participation = None
    cfg.max_estimated_slippage_bps = None
    cfg.max_per_sector_per_list = None
    cfg.max_per_watchlist_etf_source_per_list = None
    for channel_profile in cfg.channel_profiles.values():
        for key in [
            "min_fundamental_quality_score",
            "max_net_debt_to_ebitda",
            "min_interest_coverage",
            "max_current_debt_ratio",
            "min_current_ratio",
            "min_ocf_to_net_income",
            "max_accrual_ratio",
            "max_receivables_growth_gap",
            "max_inventory_growth_gap",
            "max_shares_yoy",
            "max_ps_hist_percentile",
            "max_pe_hist_percentile",
            "min_expectation_proxy",
            "min_cycle_proxy",
            "max_adv_participation",
            "max_estimated_slippage_bps",
        ]:
            channel_profile[key] = None
    return cfg


def run_one_scenario(cfg: ScanConfig, frame: pd.DataFrame) -> dict[str, Any]:
    channel_profiles = cfg.channel_profiles or {"core_ai": {}}
    n_total = int(len(frame))
    top_low = max(1, int(cfg.top_n_per_channel_low_value))
    top_trend = max(1, int(cfg.top_n_per_channel_trend))
    top_momentum = max(1, int(cfg.top_n_per_channel_momentum))

    low_ranked_frames: list[pd.DataFrame] = []
    trend_ranked_frames: list[pd.DataFrame] = []
    momentum_ranked_frames: list[pd.DataFrame] = []

    channel_summary: dict[str, Any] = {}
    first_fail_top: dict[str, list[dict[str, Any]]] = {}

    for channel_name, channel_profile in channel_profiles.items():
        low_steps = build_filter_steps(cfg, channel_name, channel_profile)
        low_filtered, _ = apply_filters_with_diagnostics(frame, low_steps)
        low_first_fail = summarize_first_fail_reasons(frame, low_steps)
        first_fail_top[channel_name] = low_first_fail.head(10).to_dict(orient="records")

        low_ranked = score_and_rank(
            low_filtered,
            channel_profile.get("score_weights", {}),
            cfg.score_winsor_lower_q,
            cfg.score_winsor_upper_q,
            cfg.score_penalty_overvaluation,
            cfg.score_penalty_deterioration,
        )
        low_ranked = apply_group_caps(
            low_ranked,
            cfg.max_per_sector_per_list,
            cfg.max_per_watchlist_etf_source_per_list,
        ).head(top_low)
        low_ranked["channel"] = channel_name
        low_ranked_frames.append(low_ranked)

        trend_steps, trend_weights = build_industry_trend_steps(cfg, channel_name, channel_profile)
        trend_filtered, _ = apply_filters_with_diagnostics(frame, trend_steps)
        trend_ranked = score_and_rank(
            trend_filtered,
            trend_weights,
            cfg.score_winsor_lower_q,
            cfg.score_winsor_upper_q,
            cfg.score_penalty_overvaluation,
            cfg.score_penalty_deterioration,
        )
        trend_ranked = apply_group_caps(
            trend_ranked,
            cfg.max_per_sector_per_list,
            cfg.max_per_watchlist_etf_source_per_list,
        ).head(top_trend)
        trend_ranked["channel"] = channel_name
        trend_ranked_frames.append(trend_ranked)

        momentum_steps, momentum_weights = build_momentum_steps(cfg, channel_name, channel_profile)
        momentum_filtered, _ = apply_filters_with_diagnostics(frame, momentum_steps)
        momentum_ranked = score_and_rank(
            momentum_filtered,
            momentum_weights,
            cfg.score_winsor_lower_q,
            cfg.score_winsor_upper_q,
            cfg.score_penalty_overvaluation,
            cfg.score_penalty_deterioration,
        )
        momentum_ranked = apply_group_caps(
            momentum_ranked,
            cfg.max_per_sector_per_list,
            cfg.max_per_watchlist_etf_source_per_list,
        ).head(top_momentum)
        momentum_ranked["channel"] = channel_name
        momentum_ranked_frames.append(momentum_ranked)

        channel_summary[channel_name] = {
            "n_total": n_total,
            "low_value_pass": int(len(low_filtered)),
            "low_value_pass_rate": round(float(len(low_filtered) / max(1, n_total)), 4),
            "industry_trend_pass": int(len(trend_filtered)),
            "industry_trend_pass_rate": round(float(len(trend_filtered) / max(1, n_total)), 4),
            "momentum_pass": int(len(momentum_filtered)),
            "momentum_pass_rate": round(float(len(momentum_filtered) / max(1, n_total)), 4),
        }

    def _concat(frames: list[pd.DataFrame], fallback_cols: list[str]) -> pd.DataFrame:
        valid = [f for f in frames if not f.empty]
        if not valid:
            return pd.DataFrame(columns=fallback_cols)
        return pd.concat(valid, ignore_index=True)

    low = _concat(low_ranked_frames, frame.columns.tolist() + ["channel", "composite_score"])
    trend = _concat(trend_ranked_frames, frame.columns.tolist() + ["channel", "composite_score"])
    momentum = _concat(momentum_ranked_frames, frame.columns.tolist() + ["channel", "composite_score"])

    if cfg.enforce_unique_symbol_per_list:
        low, _ = dedupe_symbol_by_best_channel(low)
        trend, _ = dedupe_symbol_by_best_channel(trend)
        momentum, _ = dedupe_symbol_by_best_channel(momentum)
    if cfg.enforce_unique_symbol_across_lists:
        low_symbols = set(low["symbol"].dropna().astype(str).tolist())
        trend, _ = drop_symbols(trend, low_symbols)
        prior = low_symbols | set(trend["symbol"].dropna().astype(str).tolist())
        momentum, _ = drop_symbols(momentum, prior)

    list_frames = {"low_value": low, "industry_trend": trend, "momentum": momentum}
    list_symbols = {
        k: set(v["symbol"].dropna().astype(str).tolist()) if "symbol" in v.columns else set()
        for k, v in list_frames.items()
    }
    return {
        "channel_summary": channel_summary,
        "first_fail_top": first_fail_top,
        "list_counts": {k: int(len(v)) for k, v in list_frames.items()},
        "list_symbols": {k: sorted(list(s)) for k, s in list_symbols.items()},
    }


def coverage_summary(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    n = max(1, len(frame))
    for col in NEW_METRIC_COVERAGE_FIELDS:
        if col not in frame.columns:
            out[col] = {"present": False, "coverage": 0.0, "non_null": 0}
            continue
        non_null = int(frame[col].notna().sum())
        out[col] = {"present": True, "coverage": round(non_null / n, 4), "non_null": non_null}
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compare_scenarios(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"channels": {}, "lists": {}}
    channel_names = sorted(
        set(base.get("channel_summary", {}).keys()).union(set(new.get("channel_summary", {}).keys()))
    )
    for ch in channel_names:
        b = base["channel_summary"].get(ch, {})
        n = new["channel_summary"].get(ch, {})
        out["channels"][ch] = {
            "low_value_pass": {"baseline": b.get("low_value_pass", 0), "new": n.get("low_value_pass", 0)},
            "low_value_pass_rate": {
                "baseline": b.get("low_value_pass_rate", 0.0),
                "new": n.get("low_value_pass_rate", 0.0),
            },
            "industry_trend_pass": {
                "baseline": b.get("industry_trend_pass", 0),
                "new": n.get("industry_trend_pass", 0),
            },
            "momentum_pass": {"baseline": b.get("momentum_pass", 0), "new": n.get("momentum_pass", 0)},
            "top_first_fail_new": new["first_fail_top"].get(ch, [])[:5],
        }
    for lt in LIST_TYPES:
        b_set = set(base["list_symbols"].get(lt, []))
        n_set = set(new["list_symbols"].get(lt, []))
        out["lists"][lt] = {
            "baseline_count": len(b_set),
            "new_count": len(n_set),
            "jaccard": round(jaccard(b_set, n_set), 4),
            "added_in_new": sorted(list(n_set - b_set))[:20],
            "removed_in_new": sorted(list(b_set - n_set))[:20],
        }
    return out


def render_markdown(
    config_path: str,
    meta: dict[str, int],
    coverage: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    new: dict[str, Any],
    compare: dict[str, Any],
) -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    lines.append("# Gap-12 审计报告")
    lines.append("")
    lines.append(f"- 生成时间(UTC): {now}")
    lines.append(f"- 配置文件: `{config_path}`")
    lines.append(f"- watchlist 行数: {meta['watchlist_rows']}")
    lines.append(f"- watchlist 唯一 symbol: {meta['watchlist_unique_symbols']}")
    lines.append(f"- tradable+映射后 universe: {meta['universe_after_mapping']}")
    lines.append(f"- 预筛后样本: {meta['after_prefilter']}")
    lines.append("")
    lines.append("## 1. 新增指标可得性（当前数据源）")
    lines.append("")
    lines.append("| 指标 | 非空覆盖率 | 非空数量 |")
    lines.append("|---|---:|---:|")
    for key, row in coverage.items():
        if not row["present"]:
            lines.append(f"| {key} | 0.0000 | 0 |")
        else:
            lines.append(f"| {key} | {row['coverage']:.4f} | {row['non_null']} |")
    lines.append("")
    lines.append("## 2. 四个重点口径复核")
    lines.append("")
    lines.append("1. `ps_hist_percentile/pe_hist_percentile`: 当前是价格历史分位近似，不是严格历史估值分位。")
    lines.append("2. TTM 抽取: 优先季度TTM，缺失时回退 annual/periodic；缺失值不会被新增硬过滤直接误杀。")
    lines.append("3. `current_debt_ratio`: 当前口径为 `current_debt/current_assets`（已在单元测试锁定）。")
    lines.append("4. 新增硬过滤敏感性: 见第3节基线对照（通过率、首因失败、名单变化）。")
    lines.append("")
    lines.append("## 3. 基线/新版回归对照")
    lines.append("")
    lines.append("### 3.1 通道通过率（Low-Value 及并行清单）")
    lines.append("")
    lines.append("| 通道 | low pass 基线 | low pass 新版 | low pass rate 基线 | low pass rate 新版 | trend pass 基线 | trend pass 新版 | momentum pass 基线 | momentum pass 新版 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    channel_names = sorted(compare.get("channels", {}).keys())
    for ch in channel_names:
        row = compare["channels"][ch]
        lines.append(
            "| "
            f"{ch} | "
            f"{row['low_value_pass']['baseline']} | {row['low_value_pass']['new']} | "
            f"{row['low_value_pass_rate']['baseline']:.4f} | {row['low_value_pass_rate']['new']:.4f} | "
            f"{row['industry_trend_pass']['baseline']} | {row['industry_trend_pass']['new']} | "
            f"{row['momentum_pass']['baseline']} | {row['momentum_pass']['new']} |"
        )
    lines.append("")
    lines.append("### 3.2 首因失败（新版 Top-5）")
    lines.append("")
    for ch in channel_names:
        lines.append(f"#### {ch}")
        top = compare["channels"][ch]["top_first_fail_new"]
        if not top:
            lines.append("- 无数据")
            continue
        for item in top:
            lines.append(f"- {item.get('reason')}: {item.get('count')} ({item.get('pct'):.2%})")
    lines.append("")
    lines.append("### 3.3 三清单结果差异")
    lines.append("")
    lines.append("| 清单 | 基线数量 | 新版数量 | Jaccard |")
    lines.append("|---|---:|---:|---:|")
    for lt in LIST_TYPES:
        row = compare["lists"][lt]
        lines.append(f"| {lt} | {row['baseline_count']} | {row['new_count']} | {row['jaccard']:.4f} |")
    lines.append("")
    for lt in LIST_TYPES:
        row = compare["lists"][lt]
        lines.append(f"#### {lt} 差异样本")
        lines.append(f"- 新版新增（最多20只）: {', '.join(row['added_in_new']) if row['added_in_new'] else '无'}")
        lines.append(f"- 新版移除（最多20只）: {', '.join(row['removed_in_new']) if row['removed_in_new'] else '无'}")
        lines.append("")
    lines.append("## 4. 口径定义表（关键新增项）")
    lines.append("")
    lines.append("| 指标 | 定义 | 数据源 | 风险/限制 |")
    lines.append("|---|---|---|---|")
    lines.append("| ps_hist_percentile / pe_hist_percentile | 个股价格在自身历史窗口中的分位近似 | Alpaca bars | 不是严格历史估值分位，受价格替代口径影响 |")
    lines.append("| current_debt_ratio | current_debt / current_assets | SEC facts | 部分公司无 current debt 标签，覆盖率偏低 |")
    lines.append("| net_debt_to_ebitda | (debt-cash)/adjusted_ebitda | SEC facts | ebitda 依赖 D&A 标签可得性 |")
    lines.append("| expectation_proxy | 0.5*rev_yoy+0.5*ni_yoy-0.5*r20-0.5*r60 | SEC + Alpaca | 代理因子，不等价一致预期差 |")
    lines.append("| adv_participation | assumed_position_usd / ADV20 | Alpaca bars | 依赖 assumed_position 假设 |")
    lines.append("")
    lines.append("## 5. 风险清单")
    lines.append("")
    lines.append("- 部分新增指标受 SEC 标签覆盖限制（尤其 current_debt_ratio、inventory_growth_gap）。")
    lines.append("- 历史估值分位目前是价格近似，可能与真实历史 PS/PE 分位偏离。")
    lines.append("- 新增硬过滤多时，边界样本对阈值较敏感，需要回归验证后再生产固化。")
    lines.append("")
    lines.append("## 6. 建议阈值（当前基线）")
    lines.append("")
    lines.append("- `min_fundamental_quality_score = 0.45`")
    lines.append("- `max_net_debt_to_ebitda = 5.0`")
    lines.append("- `min_interest_coverage = 1.8`")
    lines.append("- `max_current_debt_ratio = 0.75`")
    lines.append("- `min_current_ratio = 0.9`")
    lines.append("- `min_ocf_to_net_income = 0.6`")
    lines.append("- `max_accrual_ratio = 0.35`")
    lines.append("- `max_receivables_growth_gap = 0.6`")
    lines.append("- `max_inventory_growth_gap = 1.0`")
    lines.append("- `max_shares_yoy = 0.08`")
    lines.append("- `max_ps_hist_percentile = 0.85`, `max_pe_hist_percentile = 0.85`")
    lines.append("- `min_expectation_proxy = -0.2`")
    lines.append("- `assumed_position_usd = 250000`, `max_adv_participation = 0.05`, `max_estimated_slippage_bps = 40`")
    lines.append("")
    lines.append("建议：生产硬过滤优先依赖覆盖率高于 90% 的指标；覆盖率较低指标先用于软打分或观察。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    if args.max_symbols is not None:
        cfg.max_symbols = int(args.max_symbols)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"gap12_audit_{stamp}.json"
    md_path = out_dir / f"gap12_audit_{stamp}.md"

    frame, meta = build_frame(cfg)
    base_cfg = scenario_config(cfg, "baseline")
    new_cfg = scenario_config(cfg, "new")

    baseline = run_one_scenario(base_cfg, frame)
    new = run_one_scenario(new_cfg, frame)
    compare = compare_scenarios(baseline, new)
    coverage = coverage_summary(frame)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": args.config,
        "meta": meta,
        "coverage": coverage,
        "baseline": baseline,
        "new": new,
        "compare": compare,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    md = render_markdown(args.config, meta, coverage, baseline, new, compare)
    md_path.write_text(md)

    print(f"[audit] json: {json_path}")
    print(f"[audit] md:   {md_path}")


if __name__ == "__main__":
    main()
