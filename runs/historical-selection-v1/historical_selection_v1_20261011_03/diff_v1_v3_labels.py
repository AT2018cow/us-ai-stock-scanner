"""Row- and cohort-level old-vs-new label diff (v1=_02 original vs v3=_03 fixed).

v1: outputs/historical_selection_v1_20261011_02/analysis/action_v1_decisions.csv
v3: outputs/historical_selection_v1_20261011_03/analysis/action_v1_decisions.csv
Writes: label_diff_by_symbol.csv, label_diff_cohorts.csv (+ stdout headlines)
under outputs/historical_selection_v1_20261011_03/analysis/.

Change classes per (signal_date, symbol, horizon):
  SPLIT_FIX   — v1 value present, v3 value present but different (>1e-9):
                split now known (BKNG/KLAC class) or live-SEC drift.
  NULLED      — v1 value present, v3 NaN with equity_discontinuity_flag=1.
  GRADE_DRIFT — quality_grade differs (live SEC filings moved a grade).
Unchanged rows are not listed. Deterministic.
"""

from __future__ import annotations

import pandas as pd

V1 = "outputs/historical_selection_v1_20261011_02/analysis/action_v1_decisions.csv"
V3 = "outputs/historical_selection_v1_20261011_03/analysis/action_v1_decisions.csv"
OUT = "outputs/historical_selection_v1_20261011_03/analysis"
HORIZONS = (20, 60, 120)
KEYS = ["signal_date", "symbol"]


def exc(df: pd.DataFrame, h: int) -> pd.Series:
    r, q = df[f"fwd_ret_{h}"], df[f"qqq_return_{h}"]
    return (r - q).where(r.notna() & q.notna())


def main() -> None:
    a = pd.read_csv(V1, low_memory=False)
    b = pd.read_csv(V3, low_memory=False)
    print(f"v1 rows={len(a)} v3 rows={len(b)}")
    m = a.merge(b, on=KEYS, suffixes=("_v1", "_v3"), how="outer", indicator=True)
    print("join:", m["_merge"].value_counts().to_dict())
    m = m[m["_merge"] == "both"].copy()
    if "equity_discontinuity_flag" not in m.columns:
        m["equity_discontinuity_flag"] = 0
    m["equity_discontinuity_flag"] = m["equity_discontinuity_flag"].fillna(0).astype(int)
    if "quality_grade_v1" in m.columns:
        drift = m[m["quality_grade_v1"] != m["quality_grade_v3"]]
        print(f"grade drift rows: {len(drift)}")
        print(drift.groupby(["quality_grade_v1", "quality_grade_v3"]).size().to_string() if len(drift) else "(none)")

    recs = []
    for h in HORIZONS:
        # align on merged frame
        r1, q1 = m[f"fwd_ret_{h}_v1"], m[f"qqq_return_{h}_v1"]
        r3, q3 = m[f"fwd_ret_{h}_v3"], m[f"qqq_return_{h}_v3"]
        v1 = (r1 - q1).where(r1.notna() & q1.notna())
        v3 = (r3 - q3).where(r3.notna() & q3.notna())
        changed_val = v1.notna() & v3.notna() & ((v1 - v3).abs() > 1e-9)
        nulled = v1.notna() & v3.isna() & (m["equity_discontinuity_flag"] == 1)
        nulled_other = v1.notna() & v3.isna() & (m["equity_discontinuity_flag"] != 1)
        appeared = v1.isna() & v3.notna()
        sub = m[changed_val | nulled | nulled_other | appeared].copy()
        for _, r in sub.iterrows():
            if nulled.loc[r.name]:
                cls = "NULLED"
            elif changed_val.loc[r.name]:
                cls = "SPLIT_FIX"
            elif appeared.loc[r.name]:
                cls = "APPEARED"
            else:
                cls = "NULLED_OTHER"
            recs.append({"signal_date": r["signal_date"], "symbol": r["symbol"],
                         "horizon": h, "class": cls,
                         "exc_v1": v1.loc[r.name], "exc_v3": v3.loc[r.name],
                         "flag": int(r["equity_discontinuity_flag"])})
    det = pd.DataFrame(recs)
    det.to_csv(f"{OUT}/label_diff_by_symbol.csv", index=False)
    print("row-level changes:", det["class"].value_counts().to_dict())
    print("symbols affected:", sorted(det["symbol"].unique()))

    # cohort-level: grade x horizon mean excess, v1 vs v3 (date-equal-weight)
    for tag, path in [("v1", V1), ("v3", V3)]:
        pass
    rows = []
    for h in HORIZONS:
        for tag, frame in [("v1", a), ("v3", b)]:
            g = frame.copy()
            r, q = g[f"fwd_ret_{h}"], g[f"qqq_return_{h}"]
            g["ex"] = (r - q).where(r.notna() & q.notna())
            for gr, gg in g.groupby("quality_grade"):
                v = gg.dropna(subset=["ex"])
                dw = v.groupby("signal_date")["ex"].mean()
                rows.append({"horizon": h, "version": tag, "grade": gr,
                             "n": len(v), "mean_exc": round(float(v["ex"].mean()), 4),
                             "datew_exc": round(float(dw.mean()), 4)})
    pd.DataFrame(rows).to_csv(f"{OUT}/label_diff_cohorts.csv", index=False)
    piv = pd.DataFrame(rows).pivot_table(index=["horizon", "grade"], columns="version",
                                         values=["mean_exc", "datew_exc"])
    print(piv.to_string())


if __name__ == "__main__":
    main()
