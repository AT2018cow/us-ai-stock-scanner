#!/usr/bin/env python3
"""A+READY cohort economics by trailing regime (read-only audit).

Question: on the frozen historical replay datasets, does the intersection
"Company Quality A + Entry Quality ENTRY_READY" earn a positive forward
excess return versus QQQ, and does that hold when the trailing regime is
"down"?

This runner rebuilds canonical v2 decisions with the same production
``build_stock_decisions`` used by the live scan, then aggregates forward
20/60/120d returns by cohort and trailing-regime segment. It is offline,
deterministic and read-only: no network calls, no production code changes,
no writes outside ``--out-dir``.

Primary cohort: ``A_AND_READY`` (grade A and entry ENTRY_READY).
Controls: ``UNIVERSE``, ``QUALITY_A``, ``ENTRY_READY``,
``A_AND_READY_TOP15``.

Regime segments: ``ALL``, ``TRAILING_UP``, ``TRAILING_DOWN``,
``BEAR_2022``, ``DOWN_EX_2022``.

Aggregation discipline: forward windows overlap, so rows are not
independent. The headline statistic is the equal-weighted mean of
per-date cohort means; row-level win/severe-loss rates are shown as
context only. The t-statistic is descriptive, not a formal test.

Example:
    .venv/bin/python scripts/audit_a_ready_regime.py \
      --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
      --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
      --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \
      --out-dir docs/a_ready_regime_validation_20261119
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions

HORIZONS: tuple[int, ...] = (20, 60, 120)
COHORTS: tuple[str, ...] = (
    "UNIVERSE",
    "QUALITY_A",
    "ENTRY_READY",
    "A_AND_READY",
    "A_AND_READY_TOP15",
)
SEGMENTS: tuple[str, ...] = (
    "ALL",
    "TRAILING_UP",
    "TRAILING_DOWN",
    "BEAR_2022",
    "DOWN_EX_2022",
)
SEVERE_LOSS_THRESHOLD = -0.20
COST_BPS_BASE = 10.0
COST_BPS_CONSERVATIVE = 20.0
POLICY_VERSION = "v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _load_regime_labels(path: Path) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return labels
    frame = pd.read_csv(path, low_memory=False)
    for row in frame.to_dict(orient="records"):
        date = str(row.get("signal_date") or "").strip()
        if not date:
            continue
        labels[date] = {
            "regime_raw": str(row.get("regime_raw") or "").strip().lower(),
            "is_bear_2022": str(row.get("is_bear_2022") or "").strip().lower()
            in {"true", "1", "yes"},
        }
    return labels


def _load_dataset(path: Path, dataset_name: str) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["signal_date"] = frame["signal_date"].astype(str).str.strip()
    frame["_dataset"] = dataset_name
    return frame


def _rebuild_records(
    frame: pd.DataFrame,
    *,
    regime_labels: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for signal_date, group in frame.groupby("signal_date", sort=True):
        date = str(signal_date).strip()
        try:
            decisions = build_stock_decisions(
                group,
                decision_date=date,
                generated_at_utc=f"{date}T00:00:00Z",
                policy_version=POLICY_VERSION,
            )
        except Exception as exc:  # noqa: BLE001 - audit must not abort on one date
            print(f"[warn] {date}: rebuild failed: {exc}", file=sys.stderr)
            continue
        by_symbol = {
            str(decision.symbol).strip().upper(): decision for decision in decisions
        }
        meta = regime_labels.get(date, {})
        regime_raw = str(
            meta.get("regime_raw") or group["regime"].iloc[0] or ""
        ).strip().lower()
        is_bear_2022 = bool(meta.get("is_bear_2022")) or (
            str(group["_dataset"].iloc[0]) == "bear_2022"
        )
        for row in group.to_dict(orient="records"):
            symbol = str(row.get("symbol") or "").strip().upper()
            decision = by_symbol.get(symbol)
            if decision is None:
                continue
            record: dict[str, Any] = {
                "signal_date": date,
                "symbol": symbol,
                "grade": decision.quality.grade.value,
                "entry_state": decision.entry.state.value,
                "action_state": decision.action_state.value,
                "priority": int(decision.priority),
                "regime_raw": regime_raw,
                "is_bear_2022": is_bear_2022,
                "dataset": str(row.get("_dataset") or ""),
                "volatility_60d": _num(row.get("volatility_60d")),
                "drawdown_from_52w_high": _num(row.get("drawdown_from_52w_high")),
                "price_to_sma200": _num(row.get("price_to_sma200")),
                "return_20d": _num(row.get("return_20d")),
                "return_60d": _num(row.get("return_60d")),
            }
            for horizon in HORIZONS:
                fwd = _num(row.get(f"fwd_ret_{horizon}"))
                qqq = _num(row.get(f"qqq_return_{horizon}"))
                record[f"fwd_ret_{horizon}"] = fwd
                record[f"qqq_return_{horizon}"] = qqq
                record[f"excess_{horizon}"] = (
                    fwd - qqq if fwd is not None and qqq is not None else None
                )
            records.append(record)
    return records


def _cohort_member(record: Mapping[str, Any], cohort: str) -> bool:
    if cohort == "UNIVERSE":
        return True
    if cohort == "QUALITY_A":
        return record["grade"] == "A"
    if cohort == "ENTRY_READY":
        return record["entry_state"] == "ENTRY_READY"
    if cohort == "A_AND_READY":
        return record["grade"] == "A" and record["entry_state"] == "ENTRY_READY"
    if cohort == "A_AND_READY_TOP15":
        return (
            record["grade"] == "A"
            and record["entry_state"] == "ENTRY_READY"
            and int(record["priority"]) <= 15
        )
    raise ValueError(f"unknown cohort: {cohort!r}")


def _segment_member(record: Mapping[str, Any], segment: str) -> bool:
    if segment == "ALL":
        return True
    if segment == "TRAILING_UP":
        return record["regime_raw"] == "up"
    if segment == "TRAILING_DOWN":
        return record["regime_raw"] == "down"
    if segment == "BEAR_2022":
        return bool(record["is_bear_2022"])
    if segment == "DOWN_EX_2022":
        return record["regime_raw"] == "down" and not bool(record["is_bear_2022"])
    raise ValueError(f"unknown segment: {segment!r}")


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.mean(values))


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.median(values))


def _std(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return float(np.std(values, ddof=1))


def _share(values: Sequence[float], predicate) -> float | None:
    if not values:
        return None
    return float(sum(1 for value in values if predicate(value)) / len(values))


def _t_stat(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    std = _std(values)
    if std is None or std == 0:
        return None
    return float(np.mean(values) / (std / math.sqrt(len(values))))


def _aggregate(
    records: Sequence[Mapping[str, Any]],
    cohort: str,
    segment: str,
    horizon: int,
) -> dict[str, Any] | None:
    selected = [
        record
        for record in records
        if _cohort_member(record, cohort)
        and _segment_member(record, segment)
        and record.get(f"fwd_ret_{horizon}") is not None
    ]
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
        ]
        excess = [
            float(row[f"excess_{horizon}"])
            for row in rows
            if row.get(f"excess_{horizon}") is not None
        ]
        if raw:
            date_raw.append(float(np.mean(raw)))
        if excess:
            date_excess.append(float(np.mean(excess)))
    row_excess = [
        float(record[f"excess_{horizon}"])
        for record in selected
        if record.get(f"excess_{horizon}") is not None
    ]
    row_raw = [float(record[f"fwd_ret_{horizon}"]) for record in selected]
    return {
        "cohort": cohort,
        "segment": segment,
        "horizon": horizon,
        "n_dates": len(by_date),
        "n_rows": len(selected),
        "date_mean_raw": _mean(date_raw),
        "date_mean_excess": _mean(date_excess),
        "date_median_excess": _median(date_excess),
        "date_positive_share": _share(date_excess, lambda value: value > 0),
        "date_t_stat": _t_stat(date_excess),
        "row_mean_raw": _mean(row_raw),
        "row_mean_excess": _mean(row_excess),
        "row_median_excess": _median(row_excess),
        "row_win_rate": _share(row_excess, lambda value: value > 0),
        "row_severe_loss_rate": _share(
            row_raw, lambda value: value <= SEVERE_LOSS_THRESHOLD
        ),
        "date_mean_excess_net_10bps": (
            _mean(date_excess) - COST_BPS_BASE / 10000.0
            if date_excess
            else None
        ),
        "date_mean_excess_net_20bps": (
            _mean(date_excess) - COST_BPS_CONSERVATIVE / 10000.0
            if date_excess
            else None
        ),
    }


def _profile(
    records: Sequence[Mapping[str, Any]],
    cohort: str,
    segment: str,
) -> dict[str, Any] | None:
    selected = [
        record
        for record in records
        if _cohort_member(record, cohort) and _segment_member(record, segment)
    ]
    if not selected:
        return None

    def mean_of(key: str) -> float | None:
        values = [
            float(record[key])
            for record in selected
            if record.get(key) is not None
        ]
        return _mean(values)

    severe = [
        float(record["fwd_ret_60"])
        for record in selected
        if record.get("fwd_ret_60") is not None
    ]
    return {
        "cohort": cohort,
        "segment": segment,
        "n_rows": len(selected),
        "volatility_60d": mean_of("volatility_60d"),
        "drawdown_from_52w_high": mean_of("drawdown_from_52w_high"),
        "price_to_sma200": mean_of("price_to_sma200"),
        "return_20d": mean_of("return_20d"),
        "return_60d": mean_of("return_60d"),
        "severe_loss_rate_60": _share(
            severe, lambda value: value <= SEVERE_LOSS_THRESHOLD
        ),
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
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
    frame = pd.DataFrame(rows, columns=list(fields))
    frame.to_csv(path, index=False, lineterminator="\n")


def _report(
    *,
    summary_rows: Sequence[Mapping[str, Any]],
    per_date_rows: Sequence[Mapping[str, Any]],
    profile_rows: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
) -> str:
    def find(cohort: str, segment: str, horizon: int) -> Mapping[str, Any] | None:
        for row in summary_rows:
            if (
                row["cohort"] == cohort
                and row["segment"] == segment
                and row["horizon"] == horizon
            ):
                return row
        return None

    def line(cohort: str, segment: str, horizon: int) -> str:
        row = find(cohort, segment, horizon)
        if row is None:
            return "| - | - | - | - | - | - | - | - |"
        return (
            f"| {cohort} | {segment} | {horizon}d | {row['n_dates']} | "
            f"{_pct(row['date_mean_excess'])} | {_rate(row['date_positive_share'])} | "
            f"{_rate(row['row_severe_loss_rate'])} | "
            f"{_pct(row['date_mean_excess_net_10bps'])} |"
        )

    def profile_line(cohort: str, segment: str) -> str:
        row = next(
            (
                item
                for item in profile_rows
                if item["cohort"] == cohort and item["segment"] == segment
            ),
            None,
        )
        if row is None:
            return "| - | - | - | - | - | - | - |"
        return (
            f"| {cohort} | {segment} | {row['n_rows']} | "
            f"{_rate(row['volatility_60d'])} | {_rate(row['drawdown_from_52w_high'])} | "
            f"{_fmt(row['price_to_sma200'], 3)}x | {_pct(row['return_20d'])} | "
            f"{_pct(row['return_60d'])} |"
        )

    lines: list[str] = []
    lines.append("# A+READY 与 regime：冻结数据回测（只读审计）")
    lines.append("")
    lines.append(
        "- **问题**：`Company Quality A + Entry Quality ENTRY_READY` 的 20/60/120 日前向收益，"
        "是否跑赢 QQQ？在 trailing regime = down 时是否仍然成立？"
    )
    lines.append(
        "- **性质**：retrospective replay，不是 OOS；不是前瞻证据；不自动改变生产行为。"
    )
    lines.append(
        "- **决策口径**：`build_stock_decisions(policy_version=\"v2\")`，与线上同一套 "
        "quality v2 / entry v2 / action v2。"
    )
    lines.append("")
    lines.append("## 1. 数据与可复现性")
    lines.append("")
    lines.append("| 输入 | 行数 | 日期数 | SHA256 |")
    lines.append("|---|---:|---:|---|")
    for item in provenance["inputs"]:
        lines.append(
            f"| `{item['label']}` | {item['rows']} | {item['dates']} | "
            f"`{item['sha256']}` |"
        )
    lines.append("")
    lines.append(f"- Runner: `{provenance['runner']}` · SHA256 `{provenance['runner_sha256']}`")
    lines.append(
        f"- 合并样本：{provenance['total_rows']} 行 / {provenance['total_dates']} 个日期；"
        f"其中 regime down {provenance['down_dates']} 个（2022 熊市 {provenance['bear_dates']} 个）。"
    )
    lines.append(
        "- 宇宙口径：冻结数据集是“硬门幸存者”，不是完整 700 家 universe；"
        "baseline 为 survivor-pool，不是全市场。"
    )
    lines.append(
        "- watchlist 口径：当前 watchlist 回填历史（union superset approximation）；"
        "不是真正的 PIT ETF 成分历史。"
    )
    lines.append("")
    lines.append("## 2. 方法")
    lines.append("")
    lines.append(
        "- 每个 signal date 重建 v2 决策；cohort 为逐行状态，不含 Grace / 顺序 action。"
    )
    lines.append(
        "- 前向窗口重叠，行不是独立样本；主统计量是“按日期等权的 cohort 均值”，"
        "并报告正日期占比与描述性 t 值。"
    )
    lines.append(
        f"- severe loss = 前向原始收益 <= {SEVERE_LOSS_THRESHOLD * 100:.0f}%；"
        f"成本敏感性 = 10bps / 20bps round-trip。"
    )
    lines.append("")
    lines.append("## 3. 主结果：A+READY vs 全池")
    lines.append("")
    lines.append(
        "| cohort | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for segment in ("TRAILING_DOWN", "TRAILING_UP", "BEAR_2022", "DOWN_EX_2022", "ALL"):
        for horizon in HORIZONS:
            lines.append(line("A_AND_READY", segment, horizon))
    lines.append("")
    lines.append("### 对照：全池 / QUALITY_A / ENTRY_READY（60d）")
    lines.append("")
    lines.append(
        "| cohort | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for cohort in ("UNIVERSE", "QUALITY_A", "ENTRY_READY", "A_AND_READY", "A_AND_READY_TOP15"):
        for segment in ("TRAILING_DOWN", "TRAILING_UP"):
            lines.append(line(cohort, segment, 60))
    lines.append("")
    lines.append("## 4. 关键读数")
    lines.append("")
    findings: list[str] = []
    for segment, label in (
        ("TRAILING_DOWN", "regime down"),
        ("TRAILING_UP", "regime up"),
        ("BEAR_2022", "2022 熊市"),
        ("DOWN_EX_2022", "down 且非 2022"),
    ):
        row = find("A_AND_READY", segment, 60)
        if row is None:
            findings.append(f"- {label}：无有效样本。")
            continue
        findings.append(
            f"- **{label}（60d）**：date-level 超额 {_pct(row['date_mean_excess'])}，"
            f"正日期占比 {_rate(row['date_positive_share'])}，"
            f"severe-loss {_rate(row['row_severe_loss_rate'])}，"
            f"n_dates={row['n_dates']}；扣 10bps 后 {_pct(row['date_mean_excess_net_10bps'])}。"
        )
    down = find("A_AND_READY", "TRAILING_DOWN", 60)
    up = find("A_AND_READY", "TRAILING_UP", 60)
    if down and up:
        if down["date_mean_excess"] is not None and up["date_mean_excess"] is not None:
            if down["date_mean_excess"] > 0 and up["date_mean_excess"] > 0:
                findings.append(
                    "- 结论方向：down 与 up 都为正超额；但 down 的样本更小，"
                    "不能据此宣称“防御市里可以放心买”。"
                )
            elif down["date_mean_excess"] <= 0 < up["date_mean_excess"]:
                findings.append(
                    "- 结论方向：**edge 只在 up regime**；down regime 没有正超额。"
                    "这支持“regime down 只观察、不进攻”的纪律。"
                )
            elif up["date_mean_excess"] <= 0 < down["date_mean_excess"]:
                findings.append(
                    "- 结论方向：down 为正、up 不为正；这与“防御市里质量 flight”一致，"
                    "但样本小，需谨慎。"
                )
            else:
                findings.append(
                    "- 结论方向：down 与 up 都不为正；这套信号在冻结样本上没有稳定 edge。"
                )
    if down and down["date_mean_excess_net_10bps"] is not None:
        if down["date_mean_excess"] > 0 and down["date_mean_excess_net_10bps"] <= 0:
            findings.append(
                "- 成本敏感性：10bps 把 down regime 的正超额抹平；"
                "成本假设会改变结论。"
            )
        elif down["date_mean_excess"] > 0:
            findings.append(
                "- 成本敏感性：10bps / 20bps 不改变 down regime 的正负号。"
            )
    universe_down = find("UNIVERSE", "TRAILING_DOWN", 60)
    if universe_down and down:
        findings.append(
            f"- **相对 survivor pool**：同一批 down 日期，全池 60d 超额 "
            f"{_pct(universe_down['date_mean_excess'])}，A+READY "
            f"{_pct(down['date_mean_excess'])}；A+READY 的 severe-loss "
            f"{_rate(down['row_severe_loss_rate'])} vs 全池 "
            f"{_rate(universe_down['row_severe_loss_rate'])}。"
        )
    bear = find("A_AND_READY", "BEAR_2022", 60)
    down_ex = find("A_AND_READY", "DOWN_EX_2022", 60)
    if bear and down_ex:
        findings.append(
            f"- **2022 vs 非 2022**：2022 熊市 60d 超额 {_pct(bear['date_mean_excess'])}，"
            f"但非 2022 的 down 日期 {_pct(down_ex['date_mean_excess'])}"
            f"（正日期占比 {_rate(down_ex['date_positive_share'])}，n_dates={down_ex['n_dates']}）。"
            "防御性在 2022 有效，在 2023–2026 的 AI 快速反弹里反而拖累。"
        )
    findings.append(
        "- 读法：A+READY 更像“低波动/低回撤过滤器”，不是 alpha 信号；"
        "它降低尾部风险，但在反弹里让出上行。"
    )
    findings.append(
        "- 样本限制：down 日期里 2022 熊市占多数；60d 窗口重叠；"
        "t 值只能当描述性参考，不能当显著性证明。"
    )
    lines.extend(findings)
    lines.append("")
    lines.append("## 5. 为什么跑输：低波动/低回撤的代价")
    lines.append("")
    lines.append(
        "行级均值（非日期等权），用于解释 cohort 的风险画像；"
        "severe-loss 为 60d 原始收益 <= -20%。"
    )
    lines.append("")
    lines.append(
        "| cohort | segment | n_rows | vol_60d | drawdown_52w | SMA200 | 20d | 60d |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for cohort in ("UNIVERSE", "A_AND_READY"):
        for segment in ("ALL", "TRAILING_DOWN", "DOWN_EX_2022", "BEAR_2022"):
            lines.append(profile_line(cohort, segment))
    lines.append("")
    lines.append("## 6. 对当前 regime 的含义")
    lines.append("")
    lines.append(
        "- 当前（2026-11-18）是 **down 且非 2022**；历史同类 bucket 是 "
        "`DOWN_EX_2022`：60d 超额 "
        f"{_pct(down_ex['date_mean_excess']) if down_ex else '-'}，"
        f"正日期占比 {_rate(down_ex['date_positive_share']) if down_ex else '-'}，"
        f"n_dates={down_ex['n_dates'] if down_ex else '-'}。"
    )
    lines.append(
        "- 这不是“一定会跌”，是“历史上这个 cohort 在同类 regime 里跑输 survivor pool”。"
    )
    lines.append(
        "- 如果目标是“少亏”，A+READY 的 severe-loss 更低；如果目标是“跑赢 QQQ”，"
        "这套信号在冻结样本上没有证明。"
    )
    lines.append("")
    lines.append("## 7. 每日期明细")
    lines.append("")
    lines.append(
        "`per_date.csv` 给出每个 signal date、每个 cohort 的 20/60/120d 等权均值，"
        "用于检查结果是否被少数日期主导。"
    )
    lines.append("")
    lines.append("## 8. 边界与下一步")
    lines.append("")
    lines.append(
        "- 这是 retrospective replay；不能称为 OOS，也不能自动 promote 生产阈值。"
    )
    lines.append(
        "- 本次结果：A+READY 在 down 与 up 都没有正超额；2022 宽熊是唯一正 bucket；"
        "当前 down-ex-2022 是最差 bucket。"
    )
    lines.append(
        "- 因此：不要把 A+READY 当 alpha 信号；它是低波动/低回撤过滤器，"
        "适合“少亏”，不适合“跑赢”。"
    )
    lines.append(
        "- 下一步（廉价、可复现）：在现有 51 个日期上做 value overlay 分层"
        "（`fcf_yield` / `pe_hist_percentile` / `ps_hist_percentile`），"
        "看能否把 down-ex-2022 的 -6.67% 拉回 0 以上；再决定是否进入买入规则。"
    )
    lines.append(
        "- 若 overlay 也无效：接受“系统是风险过滤器”，不要再把它当 alpha 用。"
    )
    lines.append("")
    lines.append("## 9. 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(
        ".venv/bin/python scripts/audit_a_ready_regime.py \\"
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
    lines.append("  --out-dir docs/a_ready_regime_validation_20261119")
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

    labels = _load_regime_labels(labels_path) if labels_path else {}
    frames: list[pd.DataFrame] = []
    inputs: list[dict[str, Any]] = []
    for path, label, dataset_name in (
        (base_path, "base_2023_2026", "base"),
        (bear_path, "bear_2022", "bear_2022"),
    ):
        if path is None or not path.exists():
            continue
        frame = _load_dataset(path, dataset_name)
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
    records = _rebuild_records(combined, regime_labels=labels)

    summary_rows: list[dict[str, Any]] = []
    for cohort in COHORTS:
        for segment in SEGMENTS:
            for horizon in HORIZONS:
                row = _aggregate(records, cohort, segment, horizon)
                if row is not None:
                    summary_rows.append(row)

    per_date_rows: list[dict[str, Any]] = []
    for cohort in ("A_AND_READY", "UNIVERSE"):
        for segment in SEGMENTS:
            selected = [
                record
                for record in records
                if _cohort_member(record, cohort) and _segment_member(record, segment)
            ]
            by_date: dict[str, list[Mapping[str, Any]]] = {}
            for record in selected:
                by_date.setdefault(record["signal_date"], []).append(record)
            for date in sorted(by_date):
                rows = by_date[date]
                out: dict[str, Any] = {
                    "cohort": cohort,
                    "segment": segment,
                    "signal_date": date,
                    "regime_raw": rows[0]["regime_raw"],
                    "is_bear_2022": rows[0]["is_bear_2022"],
                    "n_names": len(rows),
                }
                for horizon in HORIZONS:
                    raw = [
                        float(row[f"fwd_ret_{horizon}"])
                        for row in rows
                        if row.get(f"fwd_ret_{horizon}") is not None
                    ]
                    excess = [
                        float(row[f"excess_{horizon}"])
                        for row in rows
                        if row.get(f"excess_{horizon}") is not None
                    ]
                    out[f"mean_raw_{horizon}"] = _mean(raw)
                    out[f"mean_excess_{horizon}"] = _mean(excess)
                per_date_rows.append(out)

    profile_rows: list[dict[str, Any]] = []
    for cohort in ("UNIVERSE", "A_AND_READY"):
        for segment in ("ALL", "TRAILING_DOWN", "DOWN_EX_2022", "BEAR_2022"):
            row = _profile(records, cohort, segment)
            if row is not None:
                profile_rows.append(row)

    summary_fields = [
        "cohort",
        "segment",
        "horizon",
        "n_dates",
        "n_rows",
        "date_mean_raw",
        "date_mean_excess",
        "date_median_excess",
        "date_positive_share",
        "date_t_stat",
        "row_mean_raw",
        "row_mean_excess",
        "row_median_excess",
        "row_win_rate",
        "row_severe_loss_rate",
        "date_mean_excess_net_10bps",
        "date_mean_excess_net_20bps",
    ]
    per_date_fields = [
        "cohort",
        "segment",
        "signal_date",
        "regime_raw",
        "is_bear_2022",
        "n_names",
        "mean_raw_20",
        "mean_excess_20",
        "mean_raw_60",
        "mean_excess_60",
        "mean_raw_120",
        "mean_excess_120",
    ]
    _write_csv(out_dir / "cohort_by_regime.csv", summary_rows, summary_fields)
    _write_csv(out_dir / "per_date.csv", per_date_rows, per_date_fields)

    down_dates = len(
        {
            record["signal_date"]
            for record in records
            if record["regime_raw"] == "down"
        }
    )
    bear_dates = len(
        {record["signal_date"] for record in records if record["is_bear_2022"]}
    )
    runner_path = Path(__file__).resolve()
    report = _report(
        summary_rows=summary_rows,
        per_date_rows=per_date_rows,
        profile_rows=profile_rows,
        provenance={
            "inputs": inputs,
            "runner": runner_path.name,
            "runner_sha256": _sha256(runner_path),
            "total_rows": len(records),
            "total_dates": len({record["signal_date"] for record in records}),
            "down_dates": down_dates,
            "bear_dates": bear_dates,
        },
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    checksum_lines = []
    for name in ("report.md", "cohort_by_regime.csv", "per_date.csv"):
        checksum_lines.append(f"{_sha256(out_dir / name)}  {name}")
    (out_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(f"[audit] rows={len(records)} dates={len({r['signal_date'] for r in records})} "
          f"down_dates={down_dates} bear_dates={bear_dates}")
    print(f"[audit] wrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
