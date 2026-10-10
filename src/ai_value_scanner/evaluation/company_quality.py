from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ai_value_scanner.decision.model import QualityGrade
from ai_value_scanner.decision.quality import (
    QUALITY_POLICY_VERSION,
    build_company_quality_v1,
)


QUALITY_DECISION_COLUMNS = (
    "quality_policy_version",
    "quality_grade",
    "quality_score",
    "quality_confidence",
    "quality_component_scores_json",
    "quality_positive_codes",
    "quality_risk_codes",
    "quality_missing_codes",
    "quality_data_asof",
)


def _codes(items: Iterable[Any]) -> str:
    return ",".join(item.code for item in items)


def validate_quality_replay_frame(
    frame: pd.DataFrame,
    *,
    decision_date_col: str = "signal_date",
    data_asof_col: str = "fundamental_data_asof",
) -> None:
    required = {"symbol", decision_date_col}
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise ValueError(f"quality replay dataset missing required columns: {missing_columns}")

    if data_asof_col not in frame.columns:
        return

    decision_dates = pd.to_datetime(frame[decision_date_col], errors="coerce")
    data_dates = pd.to_datetime(frame[data_asof_col], errors="coerce")
    future_mask = data_dates.notna() & decision_dates.notna() & (data_dates > decision_dates)
    if future_mask.any():
        example = frame.loc[future_mask, ["symbol", decision_date_col, data_asof_col]].iloc[0]
        raise ValueError(
            "quality replay contains future fundamental data: "
            f"symbol={example['symbol']} decision_date={example[decision_date_col]} "
            f"data_asof={example[data_asof_col]}"
        )


def apply_company_quality_v1(
    frame: pd.DataFrame,
    *,
    decision_date_col: str = "signal_date",
    data_asof_col: str = "fundamental_data_asof",
) -> pd.DataFrame:
    """Attach Company Quality v1 decisions to a historical feature frame."""
    validate_quality_replay_frame(
        frame,
        decision_date_col=decision_date_col,
        data_asof_col=data_asof_col,
    )
    out = frame.copy()
    if out.empty:
        for column in QUALITY_DECISION_COLUMNS:
            out[column] = pd.Series(dtype="object")
        return out

    records: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        decision = build_company_quality_v1(
            row,
            decision_date=row.get(decision_date_col),
            data_asof=row.get(data_asof_col),
        )
        records.append(
            {
                "quality_policy_version": QUALITY_POLICY_VERSION,
                "quality_grade": decision.grade.value,
                "quality_score": decision.score,
                "quality_confidence": decision.confidence,
                "quality_component_scores_json": json.dumps(
                    decision.component_scores,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "quality_positive_codes": _codes(decision.positives),
                "quality_risk_codes": _codes(decision.risks),
                "quality_missing_codes": _codes(decision.missing),
                "quality_data_asof": decision.data_asof,
            }
        )

    decisions = pd.DataFrame(records, index=out.index)
    for column in QUALITY_DECISION_COLUMNS:
        out[column] = decisions[column]
    return out


def _cohort_row(
    subset: pd.DataFrame,
    *,
    grade: str,
    horizon: int,
    segment_type: str,
    segment: str,
) -> dict[str, Any]:
    ret_col = f"fwd_ret_{horizon}"
    qqq_col = f"qqq_return_{horizon}"
    returns = pd.to_numeric(subset.get(ret_col), errors="coerce")
    qqq = pd.to_numeric(subset.get(qqq_col), errors="coerce")
    valid_return = returns.notna()
    valid_excess = returns.notna() & qqq.notna()
    excess = returns - qqq

    date_mean_return = float("nan")
    date_mean_excess = float("nan")
    if "signal_date" in subset.columns:
        temp = pd.DataFrame(
            {
                "signal_date": subset["signal_date"].astype(str),
                "ret": returns,
                "excess": excess,
            },
            index=subset.index,
        )
        per_date_ret = temp.loc[temp["ret"].notna()].groupby("signal_date")["ret"].mean()
        per_date_excess = (
            temp.loc[temp["excess"].notna()].groupby("signal_date")["excess"].mean()
        )
        if not per_date_ret.empty:
            date_mean_return = float(per_date_ret.mean())
        if not per_date_excess.empty:
            date_mean_excess = float(per_date_excess.mean())

    return {
        "segment_type": segment_type,
        "segment": segment,
        "quality_grade": grade,
        "horizon_days": int(horizon),
        "n_decisions": int(len(subset)),
        "n_valid_return": int(valid_return.sum()),
        "n_valid_excess": int(valid_excess.sum()),
        "n_dates": int(subset["signal_date"].nunique()) if "signal_date" in subset.columns else 0,
        "mean_return": float(returns[valid_return].mean()) if valid_return.any() else np.nan,
        "median_return": float(returns[valid_return].median()) if valid_return.any() else np.nan,
        "hit_rate": float((returns[valid_return] > 0).mean()) if valid_return.any() else np.nan,
        "mean_excess_vs_qqq": float(excess[valid_excess].mean()) if valid_excess.any() else np.nan,
        "median_excess_vs_qqq": float(excess[valid_excess].median()) if valid_excess.any() else np.nan,
        "excess_hit_rate": float((excess[valid_excess] > 0).mean()) if valid_excess.any() else np.nan,
        "date_equal_weight_mean_return": date_mean_return,
        "date_equal_weight_mean_excess_vs_qqq": date_mean_excess,
    }


def summarize_quality_cohorts(
    frame: pd.DataFrame,
    *,
    horizons: Iterable[int] = (20, 60, 120),
) -> pd.DataFrame:
    """Summarize Quality cohorts overall and by year/regime.

    Date-equal-weight fields are included so overlapping symbol rows are not
    implicitly treated as independent evidence.
    """
    if "quality_grade" not in frame.columns:
        raise ValueError("quality_grade is required; call apply_company_quality_v1 first")

    work = frame.copy()
    if "signal_date" in work.columns:
        work["signal_year"] = pd.to_datetime(
            work["signal_date"], errors="coerce"
        ).dt.year.astype("Int64")

    rows: list[dict[str, Any]] = []

    def append_scope(scope: pd.DataFrame, segment_type: str, segment: str) -> None:
        for grade in [grade.value for grade in QualityGrade]:
            grade_rows = scope[scope["quality_grade"] == grade]
            if grade_rows.empty:
                continue
            for horizon in horizons:
                rows.append(
                    _cohort_row(
                        grade_rows,
                        grade=grade,
                        horizon=int(horizon),
                        segment_type=segment_type,
                        segment=segment,
                    )
                )

    append_scope(work, "overall", "all")

    if "signal_year" in work.columns:
        for year in sorted(x for x in work["signal_year"].dropna().unique()):
            append_scope(
                work[work["signal_year"] == year],
                "year",
                str(int(year)),
            )

    if "regime" in work.columns:
        for regime in sorted(str(x) for x in work["regime"].dropna().unique()):
            append_scope(
                work[work["regime"].astype(str) == regime],
                "regime",
                regime,
            )

    return pd.DataFrame(rows)


def summarize_quality_concentration(frame: pd.DataFrame) -> pd.DataFrame:
    if "quality_grade" not in frame.columns:
        raise ValueError("quality_grade is required")
    rows: list[dict[str, Any]] = []
    for grade in [grade.value for grade in QualityGrade]:
        subset = frame[frame["quality_grade"] == grade]
        if subset.empty:
            continue
        symbol_counts = subset["symbol"].astype(str).value_counts()
        date_counts = (
            subset["signal_date"].astype(str).value_counts()
            if "signal_date" in subset.columns
            else pd.Series(dtype="int64")
        )
        total = float(len(subset))
        rows.append(
            {
                "quality_grade": grade,
                "n_decisions": int(len(subset)),
                "n_symbols": int(symbol_counts.size),
                "n_dates": int(date_counts.size),
                "top_symbol": str(symbol_counts.index[0]) if not symbol_counts.empty else "",
                "top_symbol_share": (
                    float(symbol_counts.iloc[0] / total) if not symbol_counts.empty else np.nan
                ),
                "top_date": str(date_counts.index[0]) if not date_counts.empty else "",
                "top_date_share": (
                    float(date_counts.iloc[0] / total) if not date_counts.empty else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _spearman_rank_correlation(
    left: pd.Series,
    right: pd.Series,
) -> float | None:
    """Compute a finite Spearman rank correlation for one decision date."""
    x = pd.to_numeric(left, errors="coerce")
    y = pd.to_numeric(right, errors="coerce")
    valid = x.notna() & y.notna()
    if valid.sum() < 3:
        return None

    x_valid = x[valid].astype(float)
    y_valid = y[valid].astype(float)
    if x_valid.nunique() < 2 or y_valid.nunique() < 2:
        return None

    result = spearmanr(
        x_valid.to_numpy(),
        y_valid.to_numpy(),
        nan_policy="omit",
    )
    correlation = float(result.statistic)
    return correlation if np.isfinite(correlation) else None


def summarize_quality_rank_correlation(
    frame: pd.DataFrame,
    *,
    horizons: Iterable[int] = (20, 60, 120),
) -> pd.DataFrame:
    if "quality_score" not in frame.columns:
        raise ValueError("quality_score is required")

    rows: list[dict[str, Any]] = []
    for horizon in horizons:
        ret_col = f"fwd_ret_{int(horizon)}"
        qqq_col = f"qqq_return_{int(horizon)}"
        if ret_col not in frame.columns:
            continue
        date_return_ic: list[float] = []
        date_excess_ic: list[float] = []
        for _, group in frame.groupby("signal_date", sort=True):
            score = pd.to_numeric(group["quality_score"], errors="coerce")
            ret = pd.to_numeric(group[ret_col], errors="coerce")
            corr = _spearman_rank_correlation(score, ret)
            if corr is not None:
                date_return_ic.append(corr)
            if qqq_col in group.columns:
                qqq = pd.to_numeric(group[qqq_col], errors="coerce")
                excess = ret - qqq
                corr_ex = _spearman_rank_correlation(score, excess)
                if corr_ex is not None:
                    date_excess_ic.append(corr_ex)

        rows.append(
            {
                "horizon_days": int(horizon),
                "n_dates_return_ic": len(date_return_ic),
                "mean_spearman_return": (
                    float(np.mean(date_return_ic)) if date_return_ic else np.nan
                ),
                "median_spearman_return": (
                    float(np.median(date_return_ic)) if date_return_ic else np.nan
                ),
                "n_dates_excess_ic": len(date_excess_ic),
                "mean_spearman_excess_vs_qqq": (
                    float(np.mean(date_excess_ic)) if date_excess_ic else np.nan
                ),
                "median_spearman_excess_vs_qqq": (
                    float(np.median(date_excess_ic)) if date_excess_ic else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)
