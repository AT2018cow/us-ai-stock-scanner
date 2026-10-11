"""H1 — Company Quality historical diagnostic (research-only, read-only).

Reads:  outputs/<RUN_ID>/analysis/action_v1_decisions.csv (master table)
Writes: quality_grade_year_regime.csv, quality_composition.csv,
        quality_coverage.csv, quality_failure_cases.csv
        (all under outputs/<RUN_ID>/analysis/)

Frozen case-selection rules (fixed before viewing forward returns):
  R1 worst-A:      grade==A, valid exc120, sort exc120 ASC,  top 5 (tie: symbol, date)
  R2 best-C:       grade==C, valid exc120, sort exc120 DESC, top 5 (tie: symbol, date)
  R3 unrated-move: grade==UNRATED, valid exc120, sort exc120 DESC, top 3
  R4 missing-heavy: grade in (A,B), n_missing>=4, sort n_missing DESC, exc120 ASC, top 4
Total 17 cases (>=10 required). No cherry-picking: rules are absolute, not
"top decile" style relative picks, and both tails (R1 worst, R2/R3 best) kept.

Universe label: retrospective with approximate historical universe
(union_superset_approx; see coverage_and_integrity.md). No weight/threshold
change may follow from these tables.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "historical_selection_v1_20261011_02"
BASE = Path("outputs") / RUN_ID / "analysis"
MASTER = BASE / "action_v1_decisions.csv"

HORIZONS = (20, 60, 120)


def add_excess(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for h in HORIZONS:
        r, q = df[f"fwd_ret_{h}"], df[f"qqq_return_{h}"]
        df[f"exc_{h}"] = (r - q).where(r.notna() & q.notna())
    df["year"] = df["signal_date"].str.slice(0, 4)
    return df


def date_weighted(g: pd.DataFrame, col: str) -> float:
    v = g.dropna(subset=[col]).groupby("signal_date")[col].mean()
    return float(v.mean()) if len(v) else float("nan")


def summarize(g: pd.DataFrame) -> dict:
    out = {"n": int(len(g))}
    for h in HORIZONS:
        v = g[f"exc_{h}"].dropna()
        out[f"n_exc{h}"] = int(v.size)
        out[f"mean_exc{h}"] = float(v.mean()) if v.size else float("nan")
        out[f"hit_exc{h}"] = float((v > 0).mean()) if v.size else float("nan")
        out[f"datew_exc{h}"] = date_weighted(g, f"exc_{h}")
    return out


def split_codes(s: object) -> list[str]:
    if pd.isna(s) or not str(s).strip():
        return []
    return [c.strip() for c in str(s).replace(";", ",").split(",") if c.strip()]


def main() -> None:
    df = add_excess(pd.read_csv(MASTER))
    print(f"H1 rows={len(df)} dates={df['signal_date'].nunique()} symbols={df['symbol'].nunique()}")

    # 1. grade x year x regime
    rows = []
    for (gr, yr, rg), g in df.groupby(["quality_grade", "year", "regime"], sort=True):
        r = summarize(g)
        r.update(quality_grade=gr, year=yr, regime=rg)
        rows.append(r)
    tab = pd.DataFrame(rows)
    tab.to_csv(BASE / "quality_grade_year_regime.csv", index=False)
    print("grade x year x regime: A/B/C datew_exc120 by year:")
    print(tab[["quality_grade", "year", "regime", "n", "datew_exc120"]].to_string(index=False))

    # 2. composition by grade (trailing characteristics at signal time)
    comp = []
    for gr, g in df.groupby("quality_grade", sort=True):
        miss = g["quality_missing_codes"].apply(lambda s: len(split_codes(s)))
        risk = g["quality_risk_codes"].apply(lambda s: len(split_codes(s)))
        comp.append({
            "quality_grade": gr,
            "n": len(g),
            "n_symbols": g["symbol"].nunique(),
            "mean_confidence": round(float(g["quality_confidence"].mean()), 4),
            "share_missing_any": round(float((miss > 0).mean()), 4),
            "mean_n_missing": round(float(miss.mean()), 3),
            "mean_n_risk": round(float(risk.mean()), 3),
            "mean_trailing_ret20d": round(float(g["return_20d"].mean()), 4),
            "mean_trailing_ret60d": round(float(g["return_60d"].mean()), 4),
            "mean_drawdown_52w": round(float(g["drawdown_from_52w_high"].mean()), 4),
            "mean_rs60_qqq": round(float(g["relative_strength_60d_qqq"].mean()), 4),
            "median_ps": round(float(g["ps"].median()), 3),
            "median_pe": round(float(g["pe"].median()), 2),
            "median_fcf_yield": round(float(g["fcf_yield"].median()), 4),
            "median_market_cap": float(g["market_cap"].median()),
            "mean_quality_score": round(float(g["quality_score"].mean()), 3),
        })
    pd.DataFrame(comp).to_csv(BASE / "quality_composition.csv", index=False)
    print(pd.DataFrame(comp)[["quality_grade", "n", "mean_trailing_ret60d",
          "mean_drawdown_52w", "median_pe", "share_missing_any"]].to_string(index=False))

    # 3. per-row coverage file
    cov = df[["signal_date", "symbol", "quality_grade", "quality_score",
              "quality_confidence", "quality_risk_codes", "quality_missing_codes",
              "fundamental_data_asof", "exchange", "sic", "sic_description",
              "price", "market_cap"]].copy()
    cov["business_model_verified"] = False
    cov.to_csv(BASE / "quality_coverage.csv", index=False)
    print(f"quality_coverage.csv rows={len(cov)}")

    # 4. frozen-rule failure cases
    df["n_risk"] = df["quality_risk_codes"].apply(lambda s: len(split_codes(s)))
    df["n_missing"] = df["quality_missing_codes"].apply(lambda s: len(split_codes(s)))
    valid = df[df["exc_120"].notna()].copy()
    cases = []
    r1 = valid[valid.quality_grade == "A"].sort_values(
        ["exc_120", "symbol", "signal_date"]).head(5)
    for _, r in r1.iterrows():
        cases.append((r, "R1_worst_A"))
    r2 = valid[valid.quality_grade == "C"].sort_values(
        ["exc_120", "symbol", "signal_date"], ascending=[False, True, True]).head(5)
    for _, r in r2.iterrows():
        cases.append((r, "R2_best_C_rebound"))
    r3 = valid[valid.quality_grade == "UNRATED"].sort_values(
        ["exc_120", "symbol", "signal_date"], ascending=[False, True, True]).head(3)
    for _, r in r3.iterrows():
        cases.append((r, "R3_unrated_mover"))
    r4 = valid[valid.quality_grade.isin(["A", "B"]) & (valid.n_missing >= 4)].sort_values(
        ["n_missing", "exc_120", "symbol"], ascending=[False, True, True]).head(4)
    for _, r in r4.iterrows():
        cases.append((r, "R4_missing_heavy_AB"))
    cols = ["signal_date", "symbol", "quality_grade", "quality_score",
            "quality_confidence", "n_risk", "n_missing", "quality_risk_codes",
            "quality_missing_codes", "return_60d", "drawdown_from_52w_high",
            "fwd_ret_120", "exc_120", "regime", "sic_description"]
    out = pd.DataFrame([{c: r[c] for c in cols} | {"rule": rule} for r, rule in cases])
    out.to_csv(BASE / "quality_failure_cases.csv", index=False)
    print(f"quality_failure_cases.csv rows={len(out)} "
          f"(R1={sum(1 for _, x in cases if x=='R1_worst_A')} "
          f"R2={sum(1 for _, x in cases if x.startswith('R2'))} "
          f"R3={sum(1 for _, x in cases if x.startswith('R3'))} "
          f"R4={sum(1 for _, x in cases if x.startswith('R4'))})")


if __name__ == "__main__":
    main()
