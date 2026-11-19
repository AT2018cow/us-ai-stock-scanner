#!/usr/bin/env python3
"""A+READY momentum / growth overlay audit (read-only).

Follow-up to the value-overlay audit. Tests whether a momentum or growth
bucket inside A+READY repairs the regime-down underperformance. To avoid
the value-overlay definition trap, every factor is tested three ways:

1. ``cohort``: rank inside A+READY on each signal date, then terciles.
2. ``universe``: rank inside the full survivor pool, then subset A+READY.
3. ``absolute``: fixed thresholds, independent of any ranking universe.

Momentum score = mean(rank(return_60d), rank(relative_strength_60d_qqq)).
Growth score = mean(rank(revenue_yoy), rank(adjusted_net_income_yoy),
rank(operating_cash_flow_yoy)), requiring at least 2 of 3.
A combined exploratory score averages the momentum and growth ranks.

Fixed absolute thresholds:
- Momentum strong: 60d >= +20% or RS60 >= +10%; weak: 60d <= 0% or
  RS60 <= -5%; at least 2 metrics.
- Growth strong: revenue >= +20%, adjusted NI >= +20%, OCF >= +15%;
  weak: revenue <= +5%, adjusted NI <= 0%, OCF <= 0%; at least 2 metrics.

The runner reuses the frozen replay datasets and the canonical v2
decision rebuild from ``audit_a_ready_regime.py``. Offline, deterministic,
read-only: no network calls, no production changes.

Example:
    .venv/bin/python scripts/audit_a_ready_momentum_growth_overlay.py \
      --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
      --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
      --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \
      --out-dir docs/a_ready_momentum_growth_overlay_20261119
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
MIN_TERCILE_NAMES = 6
MIN_HALF_NAMES = 4
COST_BPS_BASE = 10.0

FACTOR_METRICS: dict[str, tuple[str, ...]] = {
    "momentum": ("return_60d", "relative_strength_60d_qqq"),
    "growth": ("revenue_yoy", "adjusted_net_income_yoy", "operating_cash_flow_yoy"),
    "combined": (
        "return_60d",
        "relative_strength_60d_qqq",
        "revenue_yoy",
        "adjusted_net_income_yoy",
        "operating_cash_flow_yoy",
    ),
}
FACTOR_MIN_METRICS: dict[str, int] = {
    "momentum": 2,
    "growth": 2,
    "combined": 3,
}
FACTOR_LABELS: dict[str, str] = {
    "momentum": "Momentum",
    "growth": "Growth",
    "combined": "Momentum+Growth（探索性）",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _enrich_metrics(
    records: Sequence[dict[str, Any]],
    frames: Sequence[pd.DataFrame],
) -> None:
    metrics = sorted({metric for values in FACTOR_METRICS.values() for metric in values})
    lookup: dict[tuple[str, str], dict[str, float | None]] = {}
    for frame in frames:
        for row in frame.to_dict(orient="records"):
            key = (
                str(row.get("signal_date") or "").strip(),
                str(row.get("symbol") or "").strip().upper(),
            )
            lookup[key] = {metric: base._num(row.get(metric)) for metric in metrics}
    for record in records:
        key = (record["signal_date"], record["symbol"])
        record.update(lookup.get(key, {}))


def _composite(
    frame: pd.DataFrame,
    metrics: Sequence[str],
    min_metrics: int,
) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    parts: list[pd.Series] = []
    available = pd.Series(0, index=frame.index, dtype=int)
    for metric in metrics:
        if metric not in frame.columns:
            continue
        series = pd.to_numeric(frame[metric], errors="coerce")
        present = series.notna()
        available = available + present.astype(int)
        lower = series.quantile(0.05)
        upper = series.quantile(0.95)
        series = series.clip(lower, upper)
        parts.append(series.rank(pct=True, method="average"))
    if not parts:
        return pd.Series(np.nan, index=frame.index)
    composite = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    return composite.where(available >= min_metrics)


def _abs_score(
    pairs: Sequence[tuple[float | None, float, float]],
    *,
    min_metrics: int,
) -> str | None:
    score = 0
    available = 0
    for value, strong, weak in pairs:
        if value is None:
            continue
        available += 1
        if value >= strong:
            score += 1
        elif value <= weak:
            score -= 1
    if available < min_metrics:
        return None
    if score >= 1:
        return "strong"
    if score <= -1:
        return "weak"
    return "mid"


def _absolute_bucket(record: Mapping[str, Any], factor: str) -> str | None:
    if factor == "momentum":
        return _abs_score(
            [
                (record.get("return_60d"), 0.20, 0.00),
                (record.get("relative_strength_60d_qqq"), 0.10, -0.05),
            ],
            min_metrics=2,
        )
    if factor == "growth":
        return _abs_score(
            [
                (record.get("revenue_yoy"), 0.20, 0.05),
                (record.get("adjusted_net_income_yoy"), 0.20, 0.00),
                (record.get("operating_cash_flow_yoy"), 0.15, 0.00),
            ],
            min_metrics=2,
        )
    return None


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
        frame.loc[order[:third], bucket_col] = "strong"
        frame.loc[order[third : n - third], bucket_col] = "mid"
        frame.loc[order[n - third :], bucket_col] = "weak"


def _add_factor_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for factor, metrics in FACTOR_METRICS.items():
        min_metrics = FACTOR_MIN_METRICS[factor]
        frame[f"{factor}_score_cohort"] = np.nan
        frame[f"{factor}_score_universe"] = np.nan
        for _, group in frame.groupby("signal_date", sort=True):
            idx = group.index
            frame.loc[idx, f"{factor}_score_universe"] = _composite(
                group, metrics, min_metrics
            )
            a_ready = group[
                (group["grade"] == "A") & (group["entry_state"] == "ENTRY_READY")
            ]
            if not a_ready.empty:
                frame.loc[a_ready.index, f"{factor}_score_cohort"] = _composite(
                    a_ready, metrics, min_metrics
                )
        _assign_buckets(
            frame,
            f"{factor}_score_cohort",
            f"{factor}_cohort_tercile",
            min_names=MIN_TERCILE_NAMES,
        )
        _assign_buckets(
            frame,
            f"{factor}_score_universe",
            f"{factor}_universe_tercile",
            min_names=MIN_TERCILE_NAMES,
        )
        frame[f"{factor}_cohort_half"] = None
        frame[f"{factor}_universe_half"] = None
        for _, group in frame.groupby("signal_date", sort=True):
            for score_col, half_col in (
                (f"{factor}_score_cohort", f"{factor}_cohort_half"),
                (f"{factor}_score_universe", f"{factor}_universe_half"),
            ):
                valid = group[group[score_col].notna()]
                n = len(valid)
                if n < MIN_HALF_NAMES:
                    continue
                order = valid[score_col].sort_values(ascending=False).index
                half = n // 2
                frame.loc[order[:half], half_col] = "strong"
                frame.loc[order[half:], half_col] = "weak"
        if factor != "combined":
            frame[f"{factor}_absolute"] = [
                _absolute_bucket(record, factor)
                for record in frame.to_dict(orient="records")
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
        if record.get(bucket_col) not in {"strong", "weak"}:
            continue
        value = record.get(f"excess_{horizon}")
        if value is None or not math.isfinite(float(value)):
            continue
        by_date.setdefault(record["signal_date"], []).append(record)
    spreads: list[float] = []
    for date in sorted(by_date):
        rows = by_date[date]
        strong = [
            float(row[f"excess_{horizon}"])
            for row in rows
            if row.get(bucket_col) == "strong"
        ]
        weak = [
            float(row[f"excess_{horizon}"])
            for row in rows
            if row.get(bucket_col) == "weak"
        ]
        if strong and weak:
            spreads.append(float(np.mean(strong) - np.mean(weak)))
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
    coverage: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> str:
    def find(
        factor: str,
        bucket_col: str,
        bucket: str,
        segment: str,
        horizon: int,
    ):
        for row in summary_rows:
            if (
                row["factor"] == factor
                and row["bucket_col"] == bucket_col
                and row["bucket"] == bucket
                and row["segment"] == segment
                and row["horizon"] == horizon
            ):
                return row
        return None

    def line(factor: str, bucket_col: str, bucket: str, segment: str, horizon: int) -> str:
        row = find(factor, bucket_col, bucket, segment, horizon)
        if row is None:
            return "| - | - | - | - | - | - | - |"
        return (
            f"| {bucket} | {segment} | {horizon}d | {row['n_dates']} | "
            f"{_pct(row['date_mean_excess'])} | {_rate(row['date_positive_share'])} | "
            f"{_rate(row['row_severe_loss_rate'])} | "
            f"{_pct(row['date_mean_excess_net_10bps'])} |"
        )

    def spread_line(factor: str, bucket_col: str, segment: str, horizon: int) -> str:
        row = next(
            (
                item
                for item in spread_rows
                if item["factor"] == factor
                and item["bucket_col"] == bucket_col
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
    lines.append("# A+READY momentum / growth overlay（只读审计）")
    lines.append("")
    lines.append(
        "- **问题**：在 A+READY 内部，按 momentum / growth 分档，"
        "强档是否跑赢弱档？能否修好 down-ex-2022 的负超额？"
    )
    lines.append(
        "- **性质**：retrospective replay，不是 OOS；不是前瞻证据；不自动改变生产行为。"
    )
    lines.append(
        "- **决策口径**：复用 `audit_a_ready_regime.py` 的 v2 决策重建；"
        "score 在每个 signal date 内做横截面 rank。"
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
        f"- A+READY 行数：{coverage['a_ready_rows']}；"
        f"momentum 有 >=2 指标：{coverage['momentum_valued']}；"
        f"growth 有 >=2 指标：{coverage['growth_valued']}。"
    )
    lines.append(
        f"- 可做 cohort 三分位的日期：{coverage['cohort_tercile_dates']}；"
        f"可做 cohort 中位对半的日期：{coverage['cohort_half_dates']}。"
    )
    lines.append(
        "- 宇宙口径：冻结数据集是“硬门幸存者”，不是完整 700 家 universe；"
        "baseline 为 survivor-pool。"
    )
    lines.append("")
    lines.append("## 2. 方法")
    lines.append("")
    lines.append(
        "- momentum = mean(rank(return_60d), rank(relative_strength_60d_qqq))；"
        "growth = mean(rank(revenue_yoy), rank(adjusted_net_income_yoy), "
        "rank(operating_cash_flow_yoy))，至少 2/3。"
    )
    lines.append(
        "- 三种定义：cohort 内排名、全池排名后取 A+READY 子集、固定绝对阈值；"
        "只有三种定义同号才算稳健。"
    )
    lines.append(
        "- 主统计量：按日期等权的 strong 档均值；价差 = 同日 strong - weak。"
    )
    lines.append(
        f"- severe loss = 前向原始收益 <= {base.SEVERE_LOSS_THRESHOLD * 100:.0f}%；"
        "成本敏感性 = 10bps round-trip。"
    )
    lines.append(
        "- 多重检验：momentum 是主检验，growth 是次级，combined 是探索性；"
        "同一批 51 个日期上反复测试会提高假阳性概率。"
    )
    lines.append("")
    for factor in ("momentum", "growth", "combined"):
        label = FACTOR_LABELS[factor]
        lines.append(f"## 3.{list(('momentum','growth','combined')).index(factor)+1} {label}")
        lines.append("")
        lines.append("### 60d：strong / mid / weak（cohort 内三分位）")
        lines.append("")
        lines.append(
            "| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|")
        for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP", "ALL"):
            for bucket in ("strong", "mid", "weak"):
                lines.append(line(factor, f"{factor}_cohort_tercile", bucket, segment, 60))
        lines.append("")
        lines.append("### 价差：strong - weak（三种定义，60d）")
        lines.append("")
        lines.append(
            "| definition | segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|")
        for definition, bucket_col in (
            ("cohort", f"{factor}_cohort_tercile"),
            ("universe", f"{factor}_universe_tercile"),
        ):
            for segment in ("DOWN_EX_2022", "BEAR_2022", "TRAILING_DOWN", "TRAILING_UP", "ALL"):
                row = next(
                    (
                        item
                        for item in spread_rows
                        if item["factor"] == factor
                        and item["bucket_col"] == bucket_col
                        and item["segment"] == segment
                        and item["horizon"] == 60
                    ),
                    None,
                )
                if row is None:
                    lines.append(f"| {definition} | {segment} | 60d | - | - | - | - | - |")
                else:
                    lines.append(
                        f"| {definition} | {segment} | 60d | {row['n_dates']} | "
                        f"{_pct(row['mean_spread'])} | {_rate(row['positive_share'])} | "
                        f"{_fmt(row['t_stat'], 2)} | {_pct(row['spread_net_10bps'])} |"
                    )
        if factor != "combined":
            row = next(
                (
                    item
                    for item in spread_rows
                    if item["factor"] == factor
                    and item["bucket_col"] == f"{factor}_absolute"
                    and item["segment"] == "DOWN_EX_2022"
                    and item["horizon"] == 60
                ),
                None,
            )
            if row is not None:
                lines.append(
                    f"| absolute | DOWN_EX_2022 | 60d | {row['n_dates']} | "
                    f"{_pct(row['mean_spread'])} | {_rate(row['positive_share'])} | "
                    f"{_fmt(row['t_stat'], 2)} | {_pct(row['spread_net_10bps'])} |"
                )
        lines.append("")
    lines.append("## 4. 关键读数")
    lines.append("")
    findings: list[str] = []
    for factor in ("momentum", "growth", "combined"):
        def spread_of(bucket_col: str) -> Mapping[str, Any] | None:
            return next(
                (
                    item
                    for item in spread_rows
                    if item["factor"] == factor
                    and item["bucket_col"] == bucket_col
                    and item["segment"] == "DOWN_EX_2022"
                    and item["horizon"] == 60
                ),
                None,
            )

        cohort = spread_of(f"{factor}_cohort_tercile")
        universe = spread_of(f"{factor}_universe_tercile")
        absolute = spread_of(f"{factor}_absolute") if factor != "combined" else None
        parts = []
        if cohort:
            parts.append(f"cohort {_pct(cohort['mean_spread'])}")
        if universe:
            parts.append(f"universe {_pct(universe['mean_spread'])}")
        if absolute:
            parts.append(f"absolute {_pct(absolute['mean_spread'])}")
        if not parts:
            findings.append(f"- {FACTOR_LABELS[factor]}：无有效样本。")
            continue
        signs = []
        for item in (cohort, universe, absolute):
            if item and item["mean_spread"] is not None:
                signs.append(item["mean_spread"] > 0)
        robust = bool(signs) and all(signs)
        findings.append(
            f"- **{FACTOR_LABELS[factor]}（down-ex-2022, 60d）**："
            + "；".join(parts)
            + ("。**三种定义同为正 → 候选。**" if robust else "。符号不一致 → 不稳健。")
        )
    findings.append(
        "- 多重检验警告：同一批 51 个日期上测试了 momentum / growth / combined，"
        "任何单一正结果都不能直接 promote；需要前瞻或独立样本复核。"
    )
    findings.append(
        "- 样本限制：cohort 三分位在小日期上只有 2-3 个名字；60d 窗口重叠；"
        "t 值只能当描述性参考。"
    )
    lines.extend(findings)
    lines.append("")
    lines.append("## 5. 边界与下一步")
    lines.append("")
    lines.append(
        "- 这是 retrospective replay；不能称为 OOS，也不能自动 promote 生产阈值。"
    )
    lines.append(
        "- 若某个因子三种定义同为正：写成候选规则，用前瞻 immutable snapshot 复核。"
    )
    lines.append(
        "- 若都不稳健：停止在这批数据上继续加因子，避免过拟合；"
        "接受 A+READY 是风险过滤器。"
    )
    lines.append("")
    lines.append("## 6. 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(
        ".venv/bin/python scripts/audit_a_ready_momentum_growth_overlay.py \\"
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
    lines.append("  --out-dir docs/a_ready_momentum_growth_overlay_20261119")
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
    _enrich_metrics(records, frames)
    frame = pd.DataFrame(records)
    frame = _add_factor_buckets(frame)
    records = frame.to_dict(orient="records")

    a_ready = [
        record
        for record in records
        if record["grade"] == "A" and record["entry_state"] == "ENTRY_READY"
    ]
    coverage = {
        "a_ready_rows": len(a_ready),
        "momentum_valued": sum(
            1 for record in a_ready if record.get("momentum_score_cohort") is not None
        ),
        "growth_valued": sum(
            1 for record in a_ready if record.get("growth_score_cohort") is not None
        ),
        "cohort_tercile_dates": len(
            {
                record["signal_date"]
                for record in a_ready
                if record.get("momentum_cohort_tercile") is not None
            }
        ),
        "cohort_half_dates": len(
            {
                record["signal_date"]
                for record in a_ready
                if record.get("momentum_cohort_half") is not None
            }
        ),
    }

    summary_rows: list[dict[str, Any]] = []
    for factor in FACTOR_METRICS:
        for bucket_col, buckets in (
            (f"{factor}_cohort_tercile", ("strong", "mid", "weak")),
            (f"{factor}_universe_tercile", ("strong", "mid", "weak")),
            (f"{factor}_cohort_half", ("strong", "weak")),
            (f"{factor}_universe_half", ("strong", "weak")),
            (f"{factor}_absolute", ("strong", "mid", "weak")),
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
                                "factor": factor,
                                "bucket_col": bucket_col,
                                "bucket": bucket,
                                "segment": segment,
                                "horizon": horizon,
                                **agg,
                            }
                        )

    spread_rows: list[dict[str, Any]] = []
    for factor in FACTOR_METRICS:
        for bucket_col in (
            f"{factor}_cohort_tercile",
            f"{factor}_universe_tercile",
            f"{factor}_cohort_half",
            f"{factor}_universe_half",
            f"{factor}_absolute",
        ):
            for segment in SEGMENTS:
                for horizon in HORIZONS:
                    spread = _spread(records, bucket_col, segment, horizon)
                    if spread is None:
                        continue
                    spread_rows.append(
                        {
                            "factor": factor,
                            "bucket_col": bucket_col,
                            "segment": segment,
                            "horizon": horizon,
                            **spread,
                        }
                    )

    summary_fields = [
        "factor",
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
        "factor",
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
    _write_csv(out_dir / "overlay_summary.csv", summary_rows, summary_fields)
    _write_csv(out_dir / "overlay_spread.csv", spread_rows, spread_fields)

    runner_path = Path(__file__).resolve()
    report = _report(
        summary_rows=summary_rows,
        spread_rows=spread_rows,
        coverage=coverage,
        provenance={
            "inputs": inputs,
            "runner": runner_path.name,
            "runner_sha256": _sha256(runner_path),
        },
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    checksum_lines = []
    for name in ("report.md", "overlay_summary.csv", "overlay_spread.csv"):
        checksum_lines.append(f"{_sha256(out_dir / name)}  {name}")
    (out_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(
        f"[overlay] a_ready={coverage['a_ready_rows']} "
        f"momentum_valued={coverage['momentum_valued']} "
        f"growth_valued={coverage['growth_valued']} "
        f"cohort_tercile_dates={coverage['cohort_tercile_dates']}"
    )
    print(f"[overlay] wrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
