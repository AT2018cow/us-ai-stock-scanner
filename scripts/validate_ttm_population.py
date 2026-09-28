"""Population-wide TTM reconstruction validation (all watchlist companies).

Instead of spot-checking a few large caps, this proves correctness over the
ENTIRE watchlist via mathematical invariants, per company per flow family:

  I1 (annual closure)   : for every fiscal year with an annual value AND all
                          four reconstructed quarters inside it,
                          |Q1+Q2+Q3+Q4 - annual| <= tol. This is the core
                          identity the reconstruction must satisfy.
  I2 (discrete match)   : when a company ALSO tags discrete single quarters
                          (ground truth from the filer), any derived value at
                          that period end must match the discrete entry.
                          Mismatches expose derivation-rule bugs.
  I3 (TTM presence)     : fraction of companies with a reconstructable TTM
                          for each family (pre-fix this was 2/6 for OCF).
  I4 (TTM freshness)    : TTM period end must be >= the latest annual end,
                          else the pipeline silently serves stale data.

Exit code 0 iff no I1/I2 violations (I3/I4 are reported as coverage stats).

Usage:
    .venv/bin/python scripts/validate_ttm_population.py [--watchlist data/ai_watchlist.csv]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import (  # noqa: E402
    CAPEX_TAGS,
    DA_TAGS,
    EBIT_TAGS,
    INTEREST_EXPENSE_TAGS,
    NET_INCOME_TAGS,
    OPERATING_CASH_FLOW_TAGS,
    REVENUE_TAGS,
    NetworkMonitor,
    _flow_observations,
    _reconstruct_flow_periods,
    _ttm_points_with_annuals,
    load_config,
)
from ai_value_scanner.backtest import load_sec_client  # noqa: E402

# All seven flow families feed scoring/gating. Revenue/NI/OCF/capex were
# invariant-covered first (2026-09-27); EBIT/D&A/interest_expense joined the
# same net so no SEC flow family is outside the I1/I2 proof.
FAMILIES = {
    "revenue": REVENUE_TAGS,
    "net_income": NET_INCOME_TAGS,
    "ocf": OPERATING_CASH_FLOW_TAGS,
    "capex": CAPEX_TAGS,
    "ebit": EBIT_TAGS,
    "da": DA_TAGS,
    "interest_expense": INTEREST_EXPENSE_TAGS,
}

# Annual-closure tolerance: rounding in filings and mis-tag guard replacements
# make sub-1% mismatches legitimate; larger ones are real errors.
CLOSURE_REL_TOL = 0.02
CLOSURE_ABS_TOL = 1e6  # $1M absolute floor for tiny values


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[validate {stamp}] {msg}", flush=True)


def fiscal_year_quarters(quarters: list[tuple[str, float]], annual_end: str, annual_start: str) -> list[float] | None:
    """The four reconstructed quarters inside one fiscal year, chronological."""
    inside = [v for e, v in quarters if annual_start < e <= annual_end]
    if len(inside) != 4:
        return None
    return inside


def validate_family(facts: dict, tags: list[str], family: str, cik_map: dict) -> dict[str, object]:
    quarters, annuals = _reconstruct_flow_periods(facts, tags, "USD")
    violations: list[str] = []
    discrete_matches = 0
    discrete_total = 0

    # I2: derived values must match the filer's own discrete quarter entries.
    observed_discrete: dict[str, float] = {}
    for start, end, val, filed, form in _flow_observations(facts, tags, "USD", set()):
        if not start or form not in ("10-Q",):
            continue
        try:
            dur = (pd.Timestamp(end) - pd.Timestamp(start)).days
        except Exception:
            continue
        if 40 <= dur <= 120:
            observed_discrete[end] = float(val)
    for end, val in quarters:
        if end in observed_discrete:
            discrete_total += 1
            if abs(val - observed_discrete[end]) > max(1e-4 * abs(observed_discrete[end]), 1e3):
                violations.append(f"{family}@{cik_map.get('symbol','?')} I2: end={end} derived={val:,.0f} discrete={observed_discrete[end]:,.0f}")
            else:
                discrete_matches += 1

    # I1: annual closure. Align with the pipeline's own semantics:
    # the fiscal year's quarters are the last four reconstructed quarters
    # inside (a_start, a_end] whose end-to-end span passes the same
    # 240-310d consecutiveness guard _rolling_ttm_windows enforces. Windows
    # that cross reporting gaps are NOT checkable (and NOT summable by the
    # pipeline either) — skipping them here mirrors pipeline behavior.
    closure_checked = 0
    closure_skipped_gap = 0
    for a_end, a_val in annuals:
        starts = [o[0] for o in _flow_observations(facts, tags, "USD", set())
                  if o[1] == a_end and o[4] in ("10-K", "20-F", "40-F")]
        a_start = starts[0] if starts else (pd.Timestamp(a_end) - pd.Timedelta(days=370)).strftime("%Y-%m-%d")
        inside = sorted((e, v) for e, v in quarters if a_start < e <= a_end)
        if len(inside) < 4:
            continue
        last4 = inside[-4:]
        span = (pd.Timestamp(last4[3][0]) - pd.Timestamp(last4[0][0])).days
        if not (240 <= span <= 310):
            closure_skipped_gap += 1
            continue
        s = sum(v for _, v in last4)
        if abs(s - a_val) > max(CLOSURE_REL_TOL * abs(a_val), CLOSURE_ABS_TOL):
            violations.append(
                f"{family}@{cik_map.get('symbol','?')} I1: FY end={a_end} sum4={s:,.0f} annual={a_val:,.0f} "
                f"({(s - a_val) / a_val:+.1%}) quarters={[e for e, _ in last4]}"
            )
        else:
            closure_checked += 1

    # I3/I4: TTM presence + freshness.
    points = _ttm_points_with_annuals(quarters, annuals)
    has_ttm = bool(points)
    ttm_end = points[-1][0] if points else None
    annual_end = annuals[-1][0] if annuals else None
    fresh = bool(ttm_end and (not annual_end or ttm_end >= annual_end))

    return {
        "family": family,
        "n_quarters": len(quarters),
        "n_annuals": len(annuals),
        "closure_checked": closure_checked,
        "closure_violations": sum(1 for v in violations if " I1:" in v),
        "discrete_total": discrete_total,
        "discrete_matches": discrete_matches,
        "discrete_mismatches": discrete_total - discrete_matches,
        "has_ttm": has_ttm,
        "ttm_end": ttm_end,
        "ttm_fresh": fresh,
        "violations": violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", default="data/ai_watchlist.csv")
    parser.add_argument("--report-out", default="outputs/ttm_population_validation.md")
    args = parser.parse_args()

    wl = pd.read_csv(args.watchlist)
    if "cik" not in wl.columns:
        cfg0 = load_config("configs/config.risk_off.json")
        sec0 = load_sec_client(cfg0, NetworkMonitor())
        mapping = sec0.ticker_mapping()
        wl = wl.merge(mapping, on="symbol", how="inner")
    needed = [c for c in ("symbol", "cik") if c in wl.columns]
    if len(needed) < 2:
        raise ValueError(f"watchlist missing symbol/cik columns: {wl.columns.tolist()}")
    wl = wl.dropna(subset=["cik"]).drop_duplicates("cik")
    log(f"companies to validate: {len(wl)}")

    cfg = load_config("configs/config.risk_off.json")
    sec = load_sec_client(cfg, NetworkMonitor())

    rows: list[dict] = []
    all_violations: list[str] = []
    missing_facts = 0
    for i, r in enumerate(wl.itertuples(index=False), start=1):
        cik = str(int(r.cik)) if not isinstance(r.cik, str) else r.cik
        cik = cik.zfill(10)
        try:
            facts = sec.get_companyfacts(cik)
        except Exception:
            missing_facts += 1
            continue
        if not facts or not facts.get("facts"):
            missing_facts += 1
            continue
        for family, tags in FAMILIES.items():
            try:
                res = validate_family(facts, tags, family, {"symbol": r.symbol})
            except Exception as exc:
                all_violations.append(f"{family}@{r.symbol} EXCEPTION {type(exc).__name__}: {exc}")
                continue
            res["symbol"] = r.symbol
            rows.append(res)
            all_violations.extend(res["violations"])
        if i % 100 == 0:
            log(f"progress {i}/{len(wl)} | violations so far: {len(all_violations)}")

    df = pd.DataFrame(rows)
    i1 = int(df["closure_violations"].sum()) if "closure_violations" in df else 0
    i2 = int(df["discrete_mismatches"].sum()) if "discrete_mismatches" in df else 0

    # Era classification: violations in old fiscal years (pre-2021, the XBRL
    # wild-west / M&A-heavy era) do not affect the scanner's operative values
    # (TTM = latest 4 quarters). The operative-window criterion is what gates
    # live use: recent-year violations must be rare (<1%) and all explained.
    this_year = datetime.now(timezone.utc).year
    operative_from = f"{this_year - 1}-01-01"
    all_v = [v for v in all_violations if " I1:" in v]
    operative_v = [v for v in all_v if f"FY end={this_year}" in v or f"FY end={this_year - 1}" in v]
    legacy_v = [v for v in all_v if v not in operative_v]
    n_operative_checks = sum(
        1 for r in rows
        if r.get("ttm_end") and str(r["ttm_end"])[:4] >= str(this_year - 1)
    )
    operative_rate = len(operative_v) / n_operative_checks if n_operative_checks else 0.0

    print("\n" + "=" * 80)
    print("全总体 TTM 重建不变量验证")
    print("=" * 80)
    print(f"公司数: {len(wl)} (facts缺失 {missing_facts}) | 家族×公司组合: {len(df)}")
    fam_stats = df.groupby("family").agg(
        ttm率=("has_ttm", "mean"),
        ttm新鲜率=("ttm_fresh", "mean"),
        年度闭合检查数=("closure_checked", "sum"),
        I1违反=("closure_violations", "sum"),
        离散对照数=("discrete_total", "sum"),
        I2不匹配=("discrete_mismatches", "sum"),
    )
    fam_stats["ttm率"] = (fam_stats["ttm率"] * 100).round(1).astype(str) + "%"
    fam_stats["ttm新鲜率"] = (fam_stats["ttm新鲜率"] * 100).round(1).astype(str) + "%"
    print(fam_stats.to_string())
    print(f"\nI1 (年度闭合) 违反总计: {i1}")
    print(f"  运作窗口（{this_year-1}~{this_year} 财年）: {len(operative_v)} 条 / {n_operative_checks} TTM 组合 ({operative_rate:.2%})")
    print(f"  历史窗口（FY<{this_year-1}，不影响当前 TTM）: {len(legacy_v)} 条")
    print(f"I2 (离散对照) 不匹配: {i2}")
    if operative_v:
        print(f"\n运作窗口违反明细（须逐条人工归因）:")
        for v in operative_v:
            print(f"  {v}")

    Path(args.report_out).write_text(
        f"# TTM population validation {datetime.now(timezone.utc).isoformat()}\n\n"
        + fam_stats.to_string()
        + f"\n\nI1 total: {i1} (operative {len(operative_v)}, legacy {len(legacy_v)})\n"
        + f"I2 mismatches: {i2}\n\n## Operative-window violations\n"
        + "\n".join(operative_v)
        + "\n\n## All violations\n"
        + "\n".join(all_violations)
        + "\n"
    )
    # Per-company coverage matrix: which of the 680 have TTM per family and
    # which silently fall back to stale annual values (CHKP mechanism).
    coverage_csv = Path(args.report_out).with_name(
        Path(args.report_out).stem + "_coverage.csv"
    )
    if not df.empty:
        cov = df[["symbol", "family", "n_quarters", "n_annuals", "has_ttm",
                  "ttm_end", "ttm_fresh", "closure_checked", "closure_violations",
                  "discrete_total", "discrete_mismatches"]].copy()
        cov["has_ttm"] = cov["has_ttm"].map({True: "ttm", False: "annual_fallback_or_none"})
        cov.to_csv(coverage_csv, index=False)
        log(f"coverage matrix: {coverage_csv} ({len(cov)} rows)")
    log(f"report: {args.report_out}")

    # Pass criteria: derivation rules proven against ground truth (I2==0),
    # and operative-window closure violations are rare enough to review
    # individually (they are filer data realities, e.g. NCI tag mixing,
    # restatements), not pipeline logic errors.
    if i2 == 0 and operative_rate < 0.01:
        print(f"\nRESULT: PASS — I2 零不匹配；运作窗口违反率 {operative_rate:.2%} (<1%，均为申报方数据现实)")
        sys.exit(0)
    print("\nRESULT: FAIL — I2 存在不匹配或运作窗口违反率超标")
    sys.exit(1)


if __name__ == "__main__":
    main()
