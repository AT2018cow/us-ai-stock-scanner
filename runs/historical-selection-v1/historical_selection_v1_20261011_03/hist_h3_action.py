"""H3 — Action/Attention ranking: v1 parity + pre-registered E-first (research-only).

Reads:  outputs/<RUN_ID>/analysis/action_v1_decisions.csv
        outputs/<RUN_ID>/analysis/action_v1_compactness.csv (parity check)
Writes: ranking_paired_by_date.csv, ranking_diff_cases.csv, b_ready_cases.csv
        (under outputs/<RUN_ID>/analysis/)

Baseline V1 key — EXACT repro of decision/integrated.py::_priority_sort_key:
  (action_order, quality_order, -quality_score, -entry_score,
   -quality_confidence, -entry_confidence, symbol)
Candidate E-first — the ONE pre-registered candidate: swap ONLY the two score
positions within the same Action category AND same Quality grade; cap stays 15:
  (action_order, quality_order, -entry_score, -quality_score,
   -quality_confidence, -entry_confidence, symbol)
(No score is None in this dataset; the None->+1.0 fallback is coded but must
never trigger — asserted.)

Parity: per-date action-state counts are checked against the evaluator's
compactness file (same input rows → must match exactly). Symbol-level online
lists are unavailable historically, so results are labelled
`historical priority/cap proxy`, never parity PASS vs production.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "historical_selection_v1_20261011_02"
BASE = Path("outputs") / RUN_ID / "analysis"
MASTER = BASE / "action_v1_decisions.csv"
COMPACT = BASE / "action_v1_compactness.csv"
CAP = 15

ACTION_ORDER = {"PRIORITY_REVIEW": 0, "WATCH_PULLBACK": 1, "WATCH_BREAKOUT": 2,
                "HOLD_MONITOR": 3, "AVOID": 4}
QUALITY_ORDER = {"A": 0, "B": 1, "C": 2, "UNRATED": 3}
HORIZONS = (20, 60, 120)


def v1_key(r) -> tuple:
    if r["action_state"] not in ACTION_ORDER or r["quality_grade"] not in QUALITY_ORDER:
        raise ValueError(f"unknown state/grade: {r['action_state']}/{r['quality_grade']}")
    qs = float(r["quality_score"]) if pd.notna(r["quality_score"]) else -1.0
    es = float(r["entry_score"]) if pd.notna(r["entry_score"]) else -1.0
    return (ACTION_ORDER[r["action_state"]], QUALITY_ORDER[r["quality_grade"]],
            -qs, -es, -float(r["quality_confidence"]), -float(r["entry_confidence"]),
            r["symbol"])


def ef_key(r) -> tuple:
    if r["action_state"] not in ACTION_ORDER or r["quality_grade"] not in QUALITY_ORDER:
        raise ValueError(f"unknown state/grade: {r['action_state']}/{r['quality_grade']}")
    qs = float(r["quality_score"]) if pd.notna(r["quality_score"]) else -1.0
    es = float(r["entry_score"]) if pd.notna(r["entry_score"]) else -1.0
    return (ACTION_ORDER[r["action_state"]], QUALITY_ORDER[r["quality_grade"]],
            -es, -qs, -float(r["quality_confidence"]), -float(r["entry_confidence"]),
            r["symbol"])


def exc_mean(g: pd.DataFrame, h: int) -> tuple[int, float]:
    r, q = g[f"fwd_ret_{h}"], g[f"qqq_return_{h}"]
    v = (r - q)[r.notna() & q.notna()]
    return (int(v.size), float(v.mean()) if v.size else float("nan"))


def main() -> None:
    df = pd.read_csv(MASTER)
    assert df[["quality_score", "entry_score", "quality_confidence",
               "entry_confidence"]].notna().all().all(), "null score/confidence!"
    comp = pd.read_csv(COMPACT).set_index("signal_date")

    # parity: per-date action counts vs evaluator compactness
    mism = 0
    for d, g in df.groupby("signal_date"):
        c = g["action_state"].value_counts()
        row = comp.loc[d]
        for st, col in [("PRIORITY_REVIEW", "priority_review_count"),
                        ("WATCH_PULLBACK", "watch_pullback_count"),
                        ("WATCH_BREAKOUT", "watch_breakout_count"),
                        ("HOLD_MONITOR", "hold_monitor_count"),
                        ("AVOID", "avoid_count")]:
            if int(c.get(st, 0)) != int(row[col]):
                mism += 1
                print(f"MISMATCH {d} {st}: mine={c.get(st,0)} compact={row[col]}")
    print(f"action-count parity vs compactness: {mism} mismatches (must be 0)")

    paired, diffs = [], []
    for d, g in sorted(df.groupby("signal_date"), key=lambda x: x[0]):
        g = g.copy()
        g["_v1"] = g.apply(v1_key, axis=1)
        g["_ef"] = g.apply(ef_key, axis=1)
        v1_sorted = g.sort_values("_v1", kind="mergesort")
        ef_sorted = g.sort_values("_ef", kind="mergesort")
        v1_15 = list(v1_sorted["symbol"].head(CAP))
        v1_5 = v1_15[:5]
        ef_15 = list(ef_sorted["symbol"].head(CAP))
        ef_5 = ef_15[:5]
        pr_syms = set(g[g.action_state == "PRIORITY_REVIEW"]["symbol"])
        row = {"signal_date": d, "n_eligible": len(g),
               "n_non_avoid": int((g.action_state != "AVOID").sum()),
               "v1_top5": ";".join(v1_5), "v1_top15": ";".join(v1_15),
               "ef_top5": ";".join(ef_5), "ef_top15": ";".join(ef_15),
               "overlap_top5": len(set(v1_5) & set(ef_5)),
               "overlap_top15": len(set(v1_15) & set(ef_15)),
               "pr_suppressed_by_cap": sorted(pr_syms - set(v1_15)).__str__(),
               "n_pr_total": len(pr_syms)}
        for h in HORIZONS:
            n1, m1 = exc_mean(g[g.symbol.isin(v1_15)], h)
            n2, m2 = exc_mean(g[g.symbol.isin(ef_15)], h)
            row[f"v1_top15_n_exc{h}"] = n1
            row[f"v1_top15_mean_exc{h}"] = round(m1, 4)
            row[f"ef_top15_n_exc{h}"] = n2
            row[f"ef_top15_mean_exc{h}"] = round(m2, 4)
        paired.append(row)
        in_v1, in_ef = set(v1_15), set(ef_15)
        for _, r in g[g.symbol.isin((in_v1 - in_ef) | (in_ef - in_v1))].iterrows():
            diffs.append({"signal_date": d, "symbol": r["symbol"],
                          "direction": "OUT_under_ef" if r["symbol"] in in_v1 else "IN_under_ef",
                          "action_state": r["action_state"], "quality_grade": r["quality_grade"],
                          "entry_state": r["entry_state"]})
    pd.DataFrame(paired).to_csv(BASE / "ranking_paired_by_date.csv", index=False)
    pd.DataFrame(diffs).to_csv(BASE / "ranking_diff_cases.csv", index=False)
    p = pd.DataFrame(paired)
    print(f"dates={len(p)} mean overlap top15={p['overlap_top15'].mean():.1f}/15 "
          f"top5={p['overlap_top5'].mean():.1f}/5")
    d = pd.DataFrame(diffs)
    print("swap directions:", d["direction"].value_counts().to_dict() if len(d) else "none — identical lists")
    for h in HORIZONS:
        print(f"h={h}: v1_top15 mean_exc={p[f'v1_top15_mean_exc{h}'].mean():.4f} "
              f"ef_top15 mean_exc={p[f'ef_top15_mean_exc{h}'].mean():.4f} (mean of date means)")

    # B + ENTRY_READY secondary queue
    br = df[(df.quality_grade == "B") & (df.entry_state == "ENTRY_READY")].copy()
    ar = df[(df.quality_grade == "A") & (df.entry_state == "ENTRY_READY")].copy()
    for h in HORIZONS:
        r, q = br[f"fwd_ret_{h}"], br[f"qqq_return_{h}"]
        v = (r - q)[r.notna() & q.notna()]
        print(f"B+READY n={len(br)} exc{h}: n={v.size} mean={v.mean():.4f}")
    br[["signal_date", "symbol", "action_state", "quality_score", "entry_score",
        "fwd_ret_20", "fwd_ret_60", "fwd_ret_120", "qqq_return_20",
        "qqq_return_60", "qqq_return_120"]].to_csv(BASE / "b_ready_cases.csv", index=False)
    print(f"b_ready_cases.csv rows={len(br)}; A+READY rows={len(ar)} "
          f"(B+READY action mix: {br['action_state'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
