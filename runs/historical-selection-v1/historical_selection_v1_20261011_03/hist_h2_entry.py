"""H2 — Entry Quality historical diagnostic, Quality A/B only (research-only).

Reads:  outputs/<RUN_ID>/analysis/action_v1_decisions.csv
Writes: entry_state_by_year_regime.csv, breakout_reason_cases.csv,
        breakout_reason_summary.csv, entry_ready_deterioration.csv,
        entry_failure_cases.csv (under outputs/<RUN_ID>/analysis/)

READY gates reproduced EXACTLY from docs/entry_quality_v1_policy.md §6
(all must hold; defensive extras when regime==down or not benchmark_trend_ok):
  price_to_sma200 >= 1.00
  0.98 <= price_to_sma50 <= 1.08
  -3% <= return_20d <= 12%
  return_60d >= 0%
  relative_strength_60d_qqq >= -3%
  drawdown_from_52w_high <= 22%
  volatility_60d <= 80% annualized IF PRESENT
  defensive: relative_strength_60d_qqq >= +5% AND return_20d >= 0%

Breakout reason codes in FIXED protocol priority (§6.3 + documented VOL ext):
  SMA200_SUB1, SMA50_BELOW, SMA50_ABOVE, RS60_WEAK, RET20_LOW, RET20_HIGH,
  RET60_NEG, DRAWDOWN_DEEP, VOL_HIGH, DEFENSIVE_RS, DEFENSIVE_RET20
A row carries ALL tripped codes; primary_reason = first in this order.
UNVERIFIED (zero codes) must be 0 — else reconstruction is wrong; the count
is asserted in stdout, rows kept with UNVERIFIED for audit.

Frozen failure-case rules:
  F1 ready_failed:  state==ENTRY_READY, valid exc120, sort ASC,  bottom 8
  F2 damaged_bounce: state==TREND_DAMAGED, valid exc120, sort DESC, top 5
  F3 ready_to_damaged: READY rows whose next monthly obs is TREND_DAMAGED,
        valid exc60, sort exc60 ASC, top 3
Monthly transitions are observation gaps (~30d), NOT daily probabilities.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "historical_selection_v1_20261011_02"
BASE = Path("outputs") / RUN_ID / "analysis"
MASTER = BASE / "action_v1_decisions.csv"
HORIZONS = (20, 60, 120)

REASON_ORDER = ["SMA200_SUB1", "SMA50_BELOW", "SMA50_ABOVE", "RS60_WEAK",
                "RET20_LOW", "RET20_HIGH", "RET60_NEG", "DRAWDOWN_DEEP",
                "VOL_HIGH", "DEFENSIVE_RS", "DEFENSIVE_RET20"]


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
        out[f"datew_exc{h}"] = date_weighted(g, f"exc_{h}")
    return out


def breakout_reasons(r: pd.Series) -> list[str]:
    codes = []
    if r["price_to_sma200"] < 1.00:
        codes.append("SMA200_SUB1")
    if r["price_to_sma50"] < 0.98:
        codes.append("SMA50_BELOW")
    if r["price_to_sma50"] > 1.08:
        codes.append("SMA50_ABOVE")
    if r["relative_strength_60d_qqq"] < -0.03:
        codes.append("RS60_WEAK")
    if r["return_20d"] < -0.03:
        codes.append("RET20_LOW")
    if r["return_20d"] > 0.12:
        codes.append("RET20_HIGH")
    if r["return_60d"] < 0:
        codes.append("RET60_NEG")
    if r["drawdown_from_52w_high"] > 0.22:
        codes.append("DRAWDOWN_DEEP")
    if pd.notna(r["volatility_60d"]) and r["volatility_60d"] > 0.80:
        codes.append("VOL_HIGH")
    defensive = (r["regime"] == "down") or (not bool(r["benchmark_trend_ok"]))
    if defensive and r["relative_strength_60d_qqq"] < 0.05:
        codes.append("DEFENSIVE_RS")
    if defensive and r["return_20d"] < 0:
        codes.append("DEFENSIVE_RET20")
    ordered = [c for c in REASON_ORDER if c in codes]
    return ordered if ordered else ["UNVERIFIED"]


def main() -> None:
    df = add_excess(pd.read_csv(MASTER))
    ab = df[df.quality_grade.isin(["A", "B"])].copy()
    print(f"H2 A/B rows={len(ab)} (of {len(df)})")

    # 1. state x year x regime
    rows = []
    for (st, yr, rg), g in ab.groupby(["entry_state", "year", "regime"], sort=True):
        r = summarize(g)
        r.update(entry_state=st, year=yr, regime=rg)
        rows.append(r)
    pd.DataFrame(rows).to_csv(BASE / "entry_state_by_year_regime.csv", index=False)
    print("wrote entry_state_by_year_regime.csv")

    # 2. breakout reason decomposition
    bo = ab[ab.entry_state == "WATCH_BREAKOUT"].copy()
    bo["reason_codes"] = bo.apply(lambda r: ";".join(breakout_reasons(r)), axis=1)
    bo["primary_reason"] = bo["reason_codes"].apply(lambda s: s.split(";")[0])
    n_unv = int((bo["primary_reason"] == "UNVERIFIED").sum())
    print(f"BREAKOUT n={len(bo)} UNVERIFIED={n_unv} (must be 0)")
    keep = ["signal_date", "symbol", "quality_grade", "reason_codes", "primary_reason",
            "price_to_sma200", "price_to_sma50", "return_20d", "return_60d",
            "relative_strength_60d_qqq", "drawdown_from_52w_high", "volatility_60d",
            "regime", "benchmark_trend_ok", "exc_20", "exc_60", "exc_120"]
    bo[keep].to_csv(BASE / "breakout_reason_cases.csv", index=False)
    summ = []
    for pr, g in bo.groupby("primary_reason", sort=True):
        r = summarize(g)
        r.update(primary_reason=pr)
        summ.append(r)
    pd.DataFrame(summ).to_csv(BASE / "breakout_reason_summary.csv", index=False)
    print(pd.DataFrame(summ)[["primary_reason", "n", "mean_exc60",
          "datew_exc60"]].to_string(index=False))

    # 3. READY deterioration via monthly symbol chains
    ch = ab.sort_values(["symbol", "signal_date"]).copy()
    ch["next_state"] = ch.groupby("symbol")["entry_state"].shift(-1)
    ch["next_gap_days"] = (pd.to_datetime(ch.groupby("symbol")["signal_date"].shift(-1))
                           - pd.to_datetime(ch["signal_date"])).dt.days
    ready = ch[ch.entry_state == "ENTRY_READY"].copy()
    ready[["signal_date", "symbol", "next_state", "next_gap_days",
           "exc_20", "exc_60", "exc_120"]].to_csv(
        BASE / "entry_ready_deterioration.csv", index=False)
    print("READY next-state mix:")
    print(ready["next_state"].value_counts(dropna=False).to_string())
    print("READY fwd exc60 by next state:")
    print(ready.groupby("next_state")["exc_60"].agg(["count", "mean"]).round(4).to_string())

    # 4. frozen failure cases
    valid = ab[ab["exc_120"].notna()].copy()
    cases = []
    f1 = valid[valid.entry_state == "ENTRY_READY"].sort_values(
        ["exc_120", "symbol", "signal_date"]).head(8)
    for _, r in f1.iterrows():
        cases.append((r, "F1_ready_failed"))
    f2 = valid[valid.entry_state == "TREND_DAMAGED"].sort_values(
        ["exc_120", "symbol", "signal_date"], ascending=[False, True, True]).head(5)
    for _, r in f2.iterrows():
        cases.append((r, "F2_damaged_bounce"))
    f3src = ready[ready.next_state == "TREND_DAMAGED"]
    f3src = f3src[f3src["exc_60"].notna()].sort_values(
        ["exc_60", "symbol", "signal_date"]).head(3)
    for _, r in f3src.iterrows():
        cases.append((r, "F3_ready_to_damaged"))
    cols = ["signal_date", "symbol", "quality_grade", "entry_state", "next_state",
            "exc_20", "exc_60", "exc_120", "entry_risk_codes", "regime"]
    out = pd.DataFrame([{c: r.get(c) for c in cols} | {"rule": rule}
                        for r, rule in cases])
    out.to_csv(BASE / "entry_failure_cases.csv", index=False)
    print(f"entry_failure_cases.csv rows={len(out)}")


if __name__ == "__main__":
    main()
