#!/usr/bin/env python3
"""A+READY value overlay audit (read-only).

Question: inside the A+READY cohort, does a cheap valuation bucket
outperform an expensive bucket, especially in the current down-ex-2022
regime? The overlay is deliberately simple and cross-sectional:

    value_score = mean(
        rank(fcf_yield, high=cheap),
        rank(-pe_hist_percentile, high=cheap),
        rank(-ps_hist_percentile, high=cheap),
    )

Ranks are computed within each signal date. The primary split ranks
inside A+READY (``cohort``); a robustness split ranks inside the full
survivor pool and then subsets A+READY (``universe``). Terciles require
at least 6 valued names on a date; median halves require at least 4.

The runner reuses the frozen replay datasets and the canonical v2
decision rebuild from ``audit_a_ready_regime.py``. Offline, deterministic,
read-only: no network calls, no production changes.

Example:
    .venv/bin/python scripts/audit_a_ready_value_overlay.py \
      --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
      --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
      --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \
      --out-dir docs/a_ready_value_overlay_20261119
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import numpy as np
import pandas as pd

import audit_a_ready_regime as base

HORIZONS: tuple[int, ...] = (20, 60, 120)
SEGMENTS: tuple[str, ...] = (
    "ALL",
    "TRAILING_UP",
    "TRAILING_DOWN",
    "BEAR_2022",
    "DOWN_EX_2022",
)
VALUE_METRICS: tuple[str, ...] = (
    "fcf_yield",
    "pe_hist_percentile",
    "ps_hist_percentile",
)
MIN_TERCILE_NAMES = 6
MIN_HALF_NAMES = 4
COST_BPS_BASE = 10.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _enrich_values(
    records: Sequence[dict[str, Any]],
    frames: Sequence[pd.DataFrame],
) -> None:
    lookup: dict[tuple[str, str], dict[str, float | None]] = {}
    for frame in frames:
        for row in frame.to_dict(orient="records"):
            key = (
                str(row.get("signal_date") or "").strip(),
                str(row.get("symbol") or "").strip().upper(),
            )
            lookup[key] = {
                metric: base._num(row.get(metric)) for metric in VALUE_METRICS
            }
    for record in records:
        key = (record["signal_date"], record["symbol"])
        record.update(lookup.get(key, {}))


def _composite(frame: pd.DataFrame) -> pd.Series:
    """Higher = cheaper. Requires at least 2 of the 3 value metrics."""
    if frame.empty:
        return pd.Series(dtype=float)
    parts: list[pd.Series] = []
    available = pd.Series(0, index=frame.index, dtype=int)
    for metric in VALUE_METRICS:
        if metric not in frame.columns:
            continue
        series = pd.to_numeric(frame[metric], errors="coerce")
        present = series.notna()
        available = available + present.astype(int)
        if metric == "fcf_yield":
            # Winsorize within the date to stop data artifacts from
            # dominating the rank; rank is still scale-free.
            lower = series.quantile(0.05)
            upper = series.quantile(0.95)
            series = series.clip(lower, upper)
            parts.append(series.rank(pct=True, method="average"))
        else:
            parts.append((-series).rank(pct=True, method="average"))
    if not parts:
        return pd.Series(np.nan, index=frame.index)
    composite = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    return composite.where(available >= 2)


def _assign_buckets(
    frame: pd.DataFrame,
    score_col: str,
    bucket_col: str,
    *,
    min_names: int,
) -> None:
    frame[bucket_col] = None
    for _, group in frame.groupby("signal_date", sort=True):
        valid = group[group[score_col].notna()]
        n = len(valid)
        if n < min_names:
            continue
        order = valid[score_col].sort_values(ascending=False).index
        third = n // 3
        if third == 0:
            continue
        frame.loc[order[:third], bucket_col] = "cheap"
        frame.loc[order[third : n - third], bucket_col] = "mid"
        frame.loc[order[n - third :], bucket_col] = "expensive"


def _absolute_bucket(record: Mapping[str, Any]) -> str | None:
    """Fixed-threshold value bucket, independent of the ranking universe.

    Cheap: FCF yield >= 5%, PE hist percentile <= 30%, PS hist percentile
    <= 30%. Expensive: FCF yield <= 2%, PE/PS percentile >= 70%. Requires
    at least two available metrics.
    """
    score = 0
    available = 0
    fcf = record.get("fcf_yield")
    if fcf is not None:
        available += 1
        if fcf >= 0.05:
            score += 1
        elif fcf <= 0.02:
            score -= 1
    for metric in ("pe_hist_percentile", "ps_hist_percentile"):
        value = record.get(metric)
        if value is not None:
            available += 1
            if value <= 0.30:
                score += 1
            elif value >= 0.70:
                score -= 1
    if available < 2:
        return None
    if score >= 1:
        return "cheap"
    if score <= -1:
        return "expensive"
    return "mid"


def _add_value_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["value_score_universe"] = np.nan
    frame["value_score_cohort"] = np.nan
    for _, group in frame.groupby("signal_date", sort=True):
        idx = group.index
        frame.loc[idx, "value_score_universe"] = _composite(group)
        a_ready = group[
            (group["grade"] == "A") & (group["entry_state"] == "ENTRY_READY")
        ]
        if not a_ready.empty:
            frame.loc[a_ready.index, "value_score_cohort"] = _composite(a_ready)
    _assign_buckets(
        frame,
        "value_score_cohort",
        "cohort_tercile",
        min_names=MIN_TERCILE_NAMES,
    )
    _assign_buckets(
        frame,
        "value_score_universe",
        "universe_tercile",
        min_names=MIN_TERCILE_NAMES,
    )
    # Median halves are more robust to small cohorts than terciles.
    frame["cohort_half"] = None
    frame["universe_half"] = None
    for _, group in frame.groupby("signal_date", sort=True):
        for score_col, half_col in (
            ("value_score_cohort", "cohort_half"),
            ("value_score_universe", "universe_half"),
        ):
            valid = group[group[score_col].notna()]
            n = len(valid)
            if n < MIN_HALF_NAMES:
                continue
            order = valid[score_col].sort_values(ascending=False).index
            half = n // 2
            frame.loc[order[:half], half_col] = "cheap"
            frame.loc[order[half:], half_col] = "expensive"
    frame["absolute_bucket"] = [
        _absolute_bucket(record) for record in frame.to_dict(orient="records")
    ]
    return frame


def _aggregate_selection(
    selected: Sequence[Mapping[str, Any]],
    horizon: int,
) -> dict[str, Any] | None:
    if not selected:
        return None
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for record in selected:
        by_date.setdefault(record["signal_date"], []).append(record)
    date_excess: list[float] = []
    date_raw: list[float] = []
    for date in sorted(by_date):
        rows = by_date[date]
        raw = [
            float(row[f"fwd_ret_{horizon}"])
            for row in rows
            if row.get(f"fwd_ret_{horizon}") is not None
            and math.isfinite(float(row[f"fwd_ret_{horizon}"]))
        ]
        excess = [
            float(row[f"excess_{horizon}"])
            for row in rows
            if row.get(f"excess_{horizon}") is not None
            and math.isfinite(float(row[f"excess_{horizon}"]))
        ]
        if raw:
            date_raw.append(float(np.mean(raw)))
        if excess:
            date_excess.append(float(np.mean(excess)))
    row_excess = [
        float(record[f"excess_{horizon}"])
        for record in selected
        if record.get(f"excess_{horizon}") is not None
        and math.isfinite(float(record[f"excess_{horizon}"]))
    ]
    row_raw = [
        float(record[f"fwd_ret_{horizon}"])
        for record in selected
        if record.get(f"fwd_ret_{horizon}") is not None
        and math.isfinite(float(record[f"fwd_ret_{horizon}"]))
    ]
    return {
        "n_dates": len(by_date),
        "n_rows": len(selected),
        "date_mean_raw": base._mean(date_raw),
        "date_mean_excess": base._mean(date_excess),
        "date_median_excess": base._median(date_excess),
        "date_positive_share": base._share(date_excess, lambda value: value > 0),
        "date_t_stat": base._t_stat(date_excess),
        "row_mean_excess": base._mean(row_excess),
        "row_win_rate": base._share(row_excess, lambda value: value > 0),
        "row_severe_loss_rate": base._share(
            row_raw, lambda value: value <= base.SEVERE_LOSS_THRESHOLD
        ),
        "date_mean_excess_net_10bps": (
            base._mean(date_excess) - COST_BPS_BASE / 10000.0
            if date_excess
            else None
        ),
    }


def _bucket_member(bucket_col: str, bucket: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda record: record.get(bucket_col) == bucket


def _spread(
    records: Sequence[Mapping[str, Any]],
    bucket_col: str,
    segment: str,
    horizon: int,
) -> dict[str, Any] | None:
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if not base._segment_member(record, segment):
            continue
        if record.get(bucket_col) not in {"cheap", "expensive"}:
            continue
        if record.get(f"excess_{horizon}") is None:
            continue
        if not math.isfinite(float(record[f"excess_{horizon}"])):
            continue
        by_date.setdefault(record["signal_date"], []).append(record)
    spreads: list[float] = []
    for date in sorted(by_date):
        rows = by_date[date]
        cheap = [
            float(row[f"excess_{horizon}"])
            for row in rows
            if row.get(bucket_col) == "cheap"
            and row.get(f"excess_{horizon}") is not None
        ]
        expensive = [
            float(row[f"excess_{horizon}"])
            for row in rows
            if row.get(bucket_col) == "expensive"
            and row.get(f"excess_{horizon}") is not None
        ]
        if cheap and expensive:
            spreads.append(float(np.mean(cheap) - np.mean(expensive)))
    if not spreads:
        return None
    return {
        "n_dates": len(spreads),
        "mean_spread": base._mean(spreads),
        "median_spread": base._median(spreads),
        "positive_share": base._share(spreads, lambda value: value > 0),
        "t_stat": base._t_stat(spreads),
        "spread_net_10bps": base._mean(spreads) - COST_BPS_BASE / 10000.0,
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "-"
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "-"
    return f"{value * 100:+.2f}%"


def _rate(value: Any) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "-"
    return f"{value * 100:.1f}%"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    pd.DataFrame(rows, columns=list(fields)).to_csv(
        path, index=False, lineterminator="\n"
    )


def _report(
    *,
    summary_rows: Sequence[Mapping[str, Any]],
    spread_rows: Sequence[Mapping[str, Any]],
    per_date_rows: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> str:
    def find(bucket_col: str, bucket: str, segment: str, horizon: int):
        for row in summary_rows:
            if (
                row["bucket_col"] == bucket_col
                and row["bucket"] == bucket
                and row["segment"] == segment
                and row["horizon"] == horizon
            ):
                return row
        return None

    def line(bucket_col: str, bucket: str, segment: str, horizon: int) -> str:
        row = find(bucket_col, bucket, segment, horizon)
        if row is None:
            return "| - | - | - | - | - | - | - |"
        return (
            f"| {bucket} | {segment} | {horizon}d | {row['n_dates']} | "
            f"{_pct(row['date_mean_excess'])} | {_rate(row['date_positive_share'])} | "
            f"{_rate(row['row_severe_loss_rate'])} | "
            f"{_pct(row['date_mean_excess_net_10bps'])} |"
        )

    def spread_line(bucket_col: str, segment: str, horizon: int) -> str:
        row = next(
            (
                item
                for item in spread_rows
                if item["bucket_col"] == bucket_col
                and item["segment"] == segment
                and item["horizon"] == horizon
            ),
            None,
        )
        if row is None:
            return "| - | - | - | - | - | - |"
        return (
            f"| {segment} | {horizon}d | {row['n_dates']} | "
            f"{_pct(row['mean_spread'])} | {_rate(row['positive_share'])} | "
            f"{_fmt(row['t_stat'], 2)} | {_pct(row['spread_net_10bps'])} |"
        )

    lines: list[str] = []
    lines.append("# A+READY value overlay：便宜档 vs 贵档（只读审计）")
    lines.append("")
    lines.append(
        "- **问题**：在 A+READY 内部，按估值分档（FCF yield / PE 历史分位 / PS 历史分位），"
        "便宜档是否跑赢贵档？在 down-ex-2022 是否成立？"
    )
    lines.append(
        "- **性质**：retrospective replay，不是 OOS；不是前瞻证据；不自动改变生产行为。"
    )
    lines.append(
        "- **决策口径**：复用 `audit_a_ready_regime.py` 的 v2 决策重建；"
        "value score 在每个 signal date 内做横截面 rank。"
    )
    lines.append("")
    lines.append("## 1. 数据与覆盖")
    lines.append("")
    lines.append("| 输入 | 行数 | 日期数 | SHA256 |")
    lines.append("|---|---:|---:|---|")
    for item in provenance["inputs"]:
        lines.append(
            f"| `{item['label']}` | {item['rows']} | {item['dates']} | "
            f"`{item['sha256']}` |"
        )
    lines.append("")
    lines.append(
        f"- A+READY 行数：{coverage['a_ready_rows']}；其中有 >=2 个估值指标："
        f"{coverage['a_ready_valued']}（{_rate(coverage['a_ready_coverage'])}）。"
    )
    lines.append(
        f"- 可做 cohort 三分位的日期：{coverage['cohort_tercile_dates']}；"
        f"可做 cohort 中位对半的日期：{coverage['cohort_half_dates']}。"
    )
    lines.append(
        "- 三分位要求单日 A+READY 有 >=6 个有估值指标的名字；中位对半要求 >=4 个。"
    )
    lines.append(
        "- 宇宙口径：冻结数据集是“硬门幸存者”，不是完整 700 家 universe；"
        "baseline 为 survivor-pool。"
    )
    lines.append("")
    lines.append("## 2. 方法")
    lines.append("")
    lines.append(
        "- `value_score = mean(rank(fcf_yield), rank(-pe_hist_percentile), "
        "rank(-ps_hist_percentile))`，越高越便宜；至少 2/3 指标可用。"
    )
    lines.append(
        "- 主切分：在 A+READY 内部按日期排名（cohort）；稳健性切分："
        "在当日全池排名后取 A+READY 子集（universe）。"
    )
    lines.append(
        "- 主统计量：按日期等权的 cheap 档均值；价差 = 同日 cheap 均值 - expensive 均值。"
    )
    lines.append(
        f"- severe loss = 前向原始收益 <= {base.SEVERE_LOSS_THRESHOLD * 100:.0f}%；"
        "成本敏感性 = 10bps round-trip。"
    )
    lines.append("")
    lines.append("## 3. 主结果：A+READY 内部三分位（60d）")
    lines.append("")
    lines.append(
        "| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP", "ALL"):
        for bucket in ("cheap", "mid", "expensive"):
            lines.append(line("cohort_tercile", bucket, segment, 60))
    lines.append("")
    lines.append("### 价差：cheap - expensive（按日期）")
    lines.append("")
    lines.append(
        "| segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP", "ALL"):
        for horizon in HORIZONS:
            lines.append(spread_line("cohort_tercile", segment, horizon))
    lines.append("")
    lines.append("### 稳健性：全池排名后取 A+READY 子集（60d）")
    lines.append("")
    lines.append(
        "| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP"):
        for bucket in ("cheap", "expensive"):
            lines.append(line("universe_tercile", bucket, segment, 60))
    lines.append("")
    lines.append("### 中位对半（更抗小样本）")
    lines.append("")
    lines.append(
        "| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP"):
        for bucket in ("cheap", "expensive"):
            lines.append(line("cohort_half", bucket, segment, 60))
    lines.append("")
    lines.append("### 绝对估值阈值（固定阈值，不依赖排名宇宙）")
    lines.append("")
    lines.append(
        "cheap = FCF yield >= 5% 或 PE/PS 历史分位 <= 30%；"
        "expensive = FCF yield <= 2% 或 PE/PS 历史分位 >= 70%；至少 2 个指标。"
    )
    lines.append("")
    lines.append(
        "| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP"):
        for bucket in ("cheap", "mid", "expensive"):
            lines.append(line("absolute_bucket", bucket, segment, 60))
    lines.append("")
    lines.append("### 绝对阈值价差：cheap - expensive")
    lines.append("")
    lines.append(
        "| segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP", "ALL"):
        for horizon in HORIZONS:
            lines.append(spread_line("absolute_bucket", segment, horizon))
    lines.append("")
    lines.append("## 4. 关键读数")
    lines.append("")
    lines.append(
        "- **结论先行**：value overlay 不稳健——cohort 内排名为正，"
        "但全池排名与绝对阈值均为负；不能据此建立买入规则。"
    )
    findings: list[str] = []
    cheap_down = find("cohort_tercile", "cheap", "DOWN_EX_2022", 60)
    exp_down = find("cohort_tercile", "expensive", "DOWN_EX_2022", 60)
    spread_down = next(
        (
            item
            for item in spread_rows
            if item["bucket_col"] == "cohort_tercile"
            and item["segment"] == "DOWN_EX_2022"
            and item["horizon"] == 60
        ),
        None,
    )
    if cheap_down and exp_down:
        findings.append(
            f"- **down-ex-2022（60d）**：cheap {_pct(cheap_down['date_mean_excess'])} "
            f"vs expensive {_pct(exp_down['date_mean_excess'])}；"
            f"cheap 正日期占比 {_rate(cheap_down['date_positive_share'])}，"
            f"n_dates={cheap_down['n_dates']}。"
        )
    if spread_down:
        findings.append(
            f"- **价差（down-ex-2022, 60d, cohort 三分位）**：cheap - expensive "
            f"{_pct(spread_down['mean_spread'])}，正日期占比 "
            f"{_rate(spread_down['positive_share'])}，t={_fmt(spread_down['t_stat'], 2)}，"
            f"扣 10bps 后 {_pct(spread_down['spread_net_10bps'])}。"
        )
    spread_universe = next(
        (
            item
            for item in spread_rows
            if item["bucket_col"] == "universe_tercile"
            and item["segment"] == "DOWN_EX_2022"
            and item["horizon"] == 60
        ),
        None,
    )
    spread_absolute = next(
        (
            item
            for item in spread_rows
            if item["bucket_col"] == "absolute_bucket"
            and item["segment"] == "DOWN_EX_2022"
            and item["horizon"] == 60
        ),
        None,
    )
    if spread_universe and spread_absolute:
        findings.append(
            f"- **定义敏感性（down-ex-2022, 60d）**：cohort 三分位 "
            f"{_pct(spread_down['mean_spread']) if spread_down else '-'}；"
            f"全池三分位 {_pct(spread_universe['mean_spread'])}"
            f"（正日期 {_rate(spread_universe['positive_share'])}）；"
            f"绝对阈值 {_pct(spread_absolute['mean_spread'])}"
            f"（正日期 {_rate(spread_absolute['positive_share'])}）。"
        )
        if (
            spread_down
            and spread_universe["mean_spread"] is not None
            and spread_down["mean_spread"] is not None
            and spread_universe["mean_spread"] * spread_down["mean_spread"] < 0
        ):
            findings.append(
                "- **结论：value overlay 不稳健**——cohort 内排名为正，"
                "全池排名为负；符号取决于排名宇宙，不能直接当买入规则。"
            )
    cheap_all = find("cohort_tercile", "cheap", "ALL", 60)
    exp_all = find("cohort_tercile", "expensive", "ALL", 60)
    if cheap_all and exp_all:
        findings.append(
            f"- **全样本（60d）**：cheap {_pct(cheap_all['date_mean_excess'])} "
            f"vs expensive {_pct(exp_all['date_mean_excess'])}；"
            f"价差 {_pct(cheap_all['date_mean_excess'] - exp_all['date_mean_excess'])}。"
        )
    if spread_down and spread_universe:
        if spread_down["mean_spread"] > 0 and spread_universe["mean_spread"] > 0:
            findings.append(
                "- 结论方向：cohort 与全池定义为正；value overlay 值得进入候选规则，"
                "但仍需前瞻复核。"
            )
        elif spread_down["mean_spread"] * spread_universe["mean_spread"] < 0:
            findings.append(
                "- 结论方向：**定义冲突**；不能判定 value overlay 有效，"
                "不要据此建立买入规则。"
            )
        else:
            findings.append(
                "- 结论方向：**value overlay 没有把 down-ex-2022 拉回正**；"
                "A+READY 的“便宜档”仍不足以构成 alpha。"
            )
    findings.append(
        "- 样本限制：cohort 三分位在小日期上只有 2-3 个名字；"
        "60d 窗口重叠；t 值只能当描述性参考。"
    )
    lines.extend(findings)
    lines.append("")
    lines.append("## 5. 每日期明细")
    lines.append("")
    lines.append(
        "`per_date_value.csv` 给出每个日期、每个 bucket 的 60d 均值与 cheap-expensive 价差，"
        "用于检查结果是否被少数日期主导。"
    )
    lines.append("")
    lines.append("## 6. 边界与下一步")
    lines.append("")
    lines.append(
        "- 这是 retrospective replay；不能称为 OOS，也不能自动 promote 生产阈值。"
    )
    lines.append(
        "- 若 value overlay 有效：把它写成候选规则，再用前瞻 immutable snapshot 复核。"
    )
    lines.append(
        "- 若无效：接受 A+READY 是风险过滤器，不要继续在它身上叠加因子直到过拟合。"
    )
    lines.append("")
    lines.append("## 7. 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(
        ".venv/bin/python scripts/audit_a_ready_value_overlay.py \\"
    )
    lines.append(
        "  --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \\"
    )
    lines.append(
        "  --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \\"
    )
    lines.append(
        "  --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \\"
    )
    lines.append("  --out-dir docs/a_ready_value_overlay_20261119")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dataset", required=True)
    parser.add_argument("--bear-2022-dataset", default="")
    parser.add_argument("--regime-labels", default="")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    base_path = Path(args.base_dataset)
    bear_path = Path(args.bear_2022_dataset) if args.bear_2022_dataset else None
    labels_path = Path(args.regime_labels) if args.regime_labels else None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = base._load_regime_labels(labels_path) if labels_path else {}
    frames: list[pd.DataFrame] = []
    inputs: list[dict[str, Any]] = []
    for path, label, dataset_name in (
        (base_path, "base_2023_2026", "base"),
        (bear_path, "bear_2022", "bear_2022"),
    ):
        if path is None or not path.exists():
            continue
        frame = base._load_dataset(path, dataset_name)
        frames.append(frame)
        inputs.append(
            {
                "label": label,
                "rows": int(len(frame)),
                "dates": int(frame["signal_date"].nunique()),
                "sha256": _sha256(path),
            }
        )
    if not frames:
        raise SystemExit("no input datasets found")
    combined = pd.concat(frames, ignore_index=True)
    records = base._rebuild_records(combined, regime_labels=labels)
    _enrich_values(records, frames)
    frame = pd.DataFrame(records)
    frame = _add_value_buckets(frame)
    records = frame.to_dict(orient="records")

    a_ready = [
        record
        for record in records
        if record["grade"] == "A" and record["entry_state"] == "ENTRY_READY"
    ]
    valued = [record for record in a_ready if record.get("value_score_cohort") is not None]
    coverage = {
        "a_ready_rows": len(a_ready),
        "a_ready_valued": len(valued),
        "a_ready_coverage": (len(valued) / len(a_ready)) if a_ready else None,
        "cohort_tercile_dates": len(
            {
                record["signal_date"]
                for record in a_ready
                if record.get("cohort_tercile") is not None
            }
        ),
        "cohort_half_dates": len(
            {
                record["signal_date"]
                for record in a_ready
                if record.get("cohort_half") is not None
            }
        ),
    }

    summary_rows: list[dict[str, Any]] = []
    for bucket_col, buckets in (
        ("cohort_tercile", ("cheap", "mid", "expensive")),
        ("universe_tercile", ("cheap", "mid", "expensive")),
        ("cohort_half", ("cheap", "expensive")),
        ("universe_half", ("cheap", "expensive")),
        ("absolute_bucket", ("cheap", "mid", "expensive")),
    ):
        for bucket in buckets:
            for segment in SEGMENTS:
                selected = [
                    record
                    for record in records
                    if record.get(bucket_col) == bucket
                    and base._segment_member(record, segment)
                ]
                for horizon in HORIZONS:
                    agg = _aggregate_selection(selected, horizon)
                    if agg is None:
                        continue
                    summary_rows.append(
                        {
                            "bucket_col": bucket_col,
                            "bucket": bucket,
                            "segment": segment,
                            "horizon": horizon,
                            **agg,
                        }
                    )

    spread_rows: list[dict[str, Any]] = []
    for bucket_col in (
        "cohort_tercile",
        "universe_tercile",
        "cohort_half",
        "universe_half",
        "absolute_bucket",
    ):
        for segment in SEGMENTS:
            for horizon in HORIZONS:
                spread = _spread(records, bucket_col, segment, horizon)
                if spread is None:
                    continue
                spread_rows.append(
                    {
                        "bucket_col": bucket_col,
                        "segment": segment,
                        "horizon": horizon,
                        **spread,
                    }
                )

    per_date_rows: list[dict[str, Any]] = []
    for segment in SEGMENTS:
        for date in sorted({record["signal_date"] for record in records}):
            rows = [
                record
                for record in records
                if record["signal_date"] == date
                and base._segment_member(record, segment)
            ]
            if not rows:
                continue
            out: dict[str, Any] = {
                "segment": segment,
                "signal_date": date,
                "regime_raw": rows[0]["regime_raw"],
                "is_bear_2022": rows[0]["is_bear_2022"],
            }
            for bucket in ("cheap", "mid", "expensive"):
                bucket_rows = [
                    row for row in rows if row.get("cohort_tercile") == bucket
                ]
                out[f"n_{bucket}"] = len(bucket_rows)
                out[f"mean_excess_60_{bucket}"] = base._mean(
                    [
                        float(row["excess_60"])
                        for row in bucket_rows
                        if row.get("excess_60") is not None
                        and math.isfinite(float(row["excess_60"]))
                    ]
                )
            if (
                out.get("mean_excess_60_cheap") is not None
                and out.get("mean_excess_60_expensive") is not None
            ):
                out["spread_60"] = (
                    out["mean_excess_60_cheap"] - out["mean_excess_60_expensive"]
                )
            else:
                out["spread_60"] = None
            per_date_rows.append(out)

    summary_fields = [
        "bucket_col",
        "bucket",
        "segment",
        "horizon",
        "n_dates",
        "n_rows",
        "date_mean_raw",
        "date_mean_excess",
        "date_median_excess",
        "date_positive_share",
        "date_t_stat",
        "row_mean_excess",
        "row_win_rate",
        "row_severe_loss_rate",
        "date_mean_excess_net_10bps",
    ]
    spread_fields = [
        "bucket_col",
        "segment",
        "horizon",
        "n_dates",
        "mean_spread",
        "median_spread",
        "positive_share",
        "t_stat",
        "spread_net_10bps",
    ]
    per_date_fields = [
        "segment",
        "signal_date",
        "regime_raw",
        "is_bear_2022",
        "n_cheap",
        "n_mid",
        "n_expensive",
        "mean_excess_60_cheap",
        "mean_excess_60_mid",
        "mean_excess_60_expensive",
        "spread_60",
    ]
    _write_csv(out_dir / "value_overlay_summary.csv", summary_rows, summary_fields)
    _write_csv(out_dir / "value_overlay_spread.csv", spread_rows, spread_fields)
    _write_csv(out_dir / "per_date_value.csv", per_date_rows, per_date_fields)

    runner_path = Path(__file__).resolve()
    report = _report(
        summary_rows=summary_rows,
        spread_rows=spread_rows,
        per_date_rows=per_date_rows,
        coverage=coverage,
        provenance={
            "inputs": inputs,
            "runner": runner_path.name,
            "runner_sha256": _sha256(runner_path),
        },
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    checksum_lines = []
    for name in (
        "report.md",
        "value_overlay_summary.csv",
        "value_overlay_spread.csv",
        "per_date_value.csv",
    ):
        checksum_lines.append(f"{_sha256(out_dir / name)}  {name}")
    (out_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(
        f"[overlay] a_ready={coverage['a_ready_rows']} valued={coverage['a_ready_valued']} "
        f"cohort_tercile_dates={coverage['cohort_tercile_dates']} "
        f"cohort_half_dates={coverage['cohort_half_dates']}"
    )
    print(f"[overlay] wrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
