#!/usr/bin/env python3
"""Run Phase M4 dual-track paired validation (offline, read-only).

Single-pass bespoke evaluation per signal date (all 5 variants at once,
production builders read-only, exact production ranking verified in unit
tests), parallelized over dates for the <60s budget. Snapshot scopes reuse
frozen decisions for v1_baseline and evidence-map rebuilds for variants.

Writes 5 deliverables + SHA256SUMS under docs/m4_paired_validation_20261015/
(<140 KB, no absolute paths). Forward returns touch ONLY their period's
date-equal aggregation; 2025/2026Q1 labels are unsealed here once, labeled
RETROSPECTIVE_HELD_OUT (never prospective OOS).
"""

from __future__ import annotations

import concurrent.futures
import csv
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd

from ai_value_scanner.decision.entry import ENTRY_POLICY_VERSION, ENTRY_V2_POLICY_VERSION
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.model import stock_decision_from_dict
from ai_value_scanner.decision.quality import QUALITY_POLICY_VERSION, QUALITY_V2_POLICY_VERSION
from ai_value_scanner.research import m3_candidate_preflight as m3pre
from ai_value_scanner.research import m4_paired_validation as m4

OUT_DIR_NAME = "docs/m4_paired_validation_20261015"
MAX_DIR_BYTES = 140 * 1024

SNAP510_JSONL = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/decisions.jsonl"
SNAP510_MANIFEST = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/run_manifest.json"
SNAP62_JSONL = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/decisions.jsonl"
SNAP62_MANIFEST = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/run_manifest.json"
QUALITY_CSV = "outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv"

SNAP510_ID = "snap510_2026-10-09_313c5ff"
SNAP62_ID = "snap62_2026-10-12_220a471"

HIST_COLUMNS = (
    "signal_date", "symbol", "regime", "benchmark_trend_ok",
    "fundamental_data_asof", "market_asof",
    "revenue", "revenue_yoy", "net_margin", "free_cash_flow",
    "ocf_to_net_income", "accrual_ratio", "operating_cash_flow_yoy",
    "net_income", "net_income_yoy", "operating_cash_flow",
    "adjusted_net_income", "adjusted_net_income_yoy",
    "ebit", "ebit_yoy", "adjusted_ebit", "adjusted_ebit_yoy", "adjusted_ebitda",
    "nonrecurring_expense_addback", "nonrecurring_gain_subtraction",
    "cash_and_equivalents", "total_debt", "net_debt", "interest_expense",
    "depreciation_and_amortization", "current_assets", "current_liabilities",
    "receivables_current", "inventory_current", "receivables_yoy", "inventory_yoy",
    "receivables_growth_gap", "inventory_growth_gap", "da_yoy",
    "fundamental_quality_score", "interest_coverage", "net_debt_to_ebitda",
    "current_ratio", "current_debt_ratio_reported", "current_debt_ratio_inferred",
    "current_debt_ratio", "current_debt_ratio_source", "fcf_yield",
    "ps_hist_percentile", "pe_hist_percentile", "shares_yoy", "shares_stale",
    "price", "drawdown_from_52w_high", "range_position_52w",
    "price_to_sma50", "price_to_sma200", "days_below_sma200",
    "return_20d", "return_60d", "volatility_60d", "relative_strength_60d_qqq",
    "fwd_ret_20", "fwd_ret_60", "fwd_ret_120",
    "qqq_return_20", "qqq_return_60", "qqq_return_120",
)

UTILITY_COLUMNS = (
    "scope", "variant", "n_decisions",
    "n_contradictory_cash_accrual", "n_silent_non_ready_entry",
    "mean_top15_ready_share", "mean_top15_quality_a_share",
    "mean_top15_high_growth_share", "report_v2_parity_ok",
)

ECONOMIC_COLUMNS = (
    "period", "variant", "cohort",
    "n_matured_dates_20d", "n_total_obs_20d", "mean_excess_20d",
    "n_matured_dates_60d", "n_total_obs_60d", "mean_excess_60d",
    "median_date_excess_60d", "p10_date_excess_60d", "worst_date_excess_60d",
    "n_matured_dates_120d", "n_total_obs_120d", "mean_excess_120d",
    "mean_paired_delta_60d", "median_paired_delta_60d",
    "positive_delta_date_share", "ci95_low_60d", "ci95_high_60d",
    "loo_min_mean_delta_60d",
)

SPLIT_COLUMNS = (
    "split_type", "split_value", "variant", "cohort",
    "n_dates", "n_obs", "mean_excess_60d",
    "mean_paired_delta_60d", "ci95_low_60d", "ci95_high_60d",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _evaluate_hist_date(payload: tuple[str, object]) -> tuple[str, dict]:
    """Worker: compact 5-variant evaluation for one signal date (pure)."""
    date, group = payload
    return date, m4.evaluate_date_compact(group, date)


def main() -> int:
    started = time.time()
    out_dir = REPO_ROOT / OUT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    print("M4: loading frozen inputs ...", flush=True)
    hist = pd.read_csv(REPO_ROOT / QUALITY_CSV, usecols=list(HIST_COLUMNS), low_memory=False)
    if len(hist) != 25025 or hist["signal_date"].nunique() != 39:
        raise ValueError("unexpected historical dataset shape")
    decisions510 = [json.loads(line) for line in (REPO_ROOT / SNAP510_JSONL).read_text().splitlines() if line.strip()]
    decisions62 = [json.loads(line) for line in (REPO_ROOT / SNAP62_JSONL).read_text().splitlines() if line.strip()]
    manifest510 = json.loads((REPO_ROOT / SNAP510_MANIFEST).read_text())
    manifest62 = json.loads((REPO_ROOT / SNAP62_MANIFEST).read_text())
    partitions = m4.partition_dates(hist["signal_date"].unique().tolist())
    print(f"M4: dev={len(partitions['DEV_2023_2024'])} post={len(partitions['POST2024_HELD_OUT'])}", flush=True)

    print("M4: bespoke per-date evaluation (5 variants, parallel) ...", flush=True)
    payloads = [
        (str(date), group)
        for date, group in hist.groupby("signal_date", sort=True)
    ]
    workers = max(1, min(2, (os.cpu_count() or 1)))
    compact: dict[str, dict] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        for date, result in pool.map(_evaluate_hist_date, payloads):
            compact[date] = result
    print(f"M4: evaluated {len(compact)} dates in {time.time() - started:.1f}s", flush=True)

    # ---- Track 1: human utility -------------------------------------------
    utility_rows: list[dict] = []
    frozen_utility: dict[str, dict] = {}
    for scope, decisions in (("snap62", decisions62), ("snap510", decisions510)):
        frozen_records = tuple(m4.scored_row_from_frozen(d) for d in decisions)
        frozen_utility[scope] = m4.human_utility_for_scope(frozen_records)
        utility_rows.append({"scope": scope, "variant": "v1_baseline",
                             **frozen_utility[scope], "report_v2_parity_ok": ""})
        rebuild_frame = m3pre.snapshot_rebuild_frame(decisions)
        per_variant = m4.evaluate_date_frame(
            rebuild_frame, str(rebuild_frame["signal_date"].iloc[0]))
        for variant in m4.VARIANTS:
            if variant == "v1_baseline":
                continue
            metrics = m4.human_utility_for_scope(per_variant[variant]["records"])
            utility_rows.append({"scope": scope, "variant": variant,
                                 **metrics, "report_v2_parity_ok": ""})

    def _aggregate_utility(dates: list) -> dict[str, dict[str, dict]]:
        by_variant: dict[str, dict[str, dict]] = {}
        for variant in m4.VARIANTS:
            contradictory = sum(compact[date][variant]["utility"]["contradictory"] for date in dates)
            silent = sum(compact[date][variant]["utility"]["silent"] for date in dates)
            shares = {
                key: [compact[date][variant]["utility"][key] for date in dates
                      if compact[date][variant]["utility"][key] is not None]
                for key in ("ready_share", "a_share", "growth_share")
            }
            by_variant[variant] = {
                "n_decisions": sum(compact[date][variant]["n"] for date in dates),
                "n_contradictory_cash_accrual": contradictory,
                "n_silent_non_ready_entry": silent,
                "mean_top15_ready_share": _mean_or_none(shares["ready_share"]),
                "mean_top15_quality_a_share": _mean_or_none(shares["a_share"]),
                "mean_top15_high_growth_share": _mean_or_none(shares["growth_share"]),
            }
        return by_variant

    hist_utility = {
        "DEV_2023_2024": _aggregate_utility(partitions["DEV_2023_2024"]),
        "POST2024_HELD_OUT": _aggregate_utility(partitions["POST2024_HELD_OUT"]),
        "ALL_39_DATES": _aggregate_utility(partitions["ALL_39_DATES"]),
    }
    for scope in ("DEV_2023_2024", "POST2024_HELD_OUT", "ALL_39_DATES"):
        for variant in m4.VARIANTS:
            utility_rows.append({"scope": scope, "variant": variant,
                                 **hist_utility[scope][variant],
                                 "report_v2_parity_ok": ""})

    # ---- Track 1 parity sample (real renders) ------------------------------
    parity_samples = []
    for label, frozen in (("snap62", decisions62), ("snap510", decisions510)):
        objects = []
        for payload in frozen:
            try:
                objects.append(stock_decision_from_dict(dict(payload)))
            except (ValueError, KeyError, TypeError):
                pass
        parity_samples.append((label, m4.render_and_check_v2(objects, title=f"M4 {label}")))
    sample_date = "2024-06-28"
    sample_group = hist[hist["signal_date"] == sample_date]
    for variant, stages in (("v1_baseline", {}), ("v2_combined", {"policy_version": "v2"})):
        built = build_stock_decisions(
            sample_group, decision_date=sample_date,
            generated_at_utc=f"{sample_date}T23:59:59+00:00", **stages)
        parity_samples.append(
            (f"hist_{sample_date}_{variant}", m4.render_and_check_v2(built, title=f"M4 {sample_date}")))
    parity_ok_all = all(check["report_v2_parity_ok"] for _, check in parity_samples)
    for row in utility_rows:
        row["report_v2_parity_ok"] = "TRUE" if parity_ok_all else "FALSE"

    # ---- Track 2: paired economics -----------------------------------------
    def _cohort_means(dates: list, variant: str, cohort: str, horizon: int) -> tuple[dict, int]:
        means: dict[str, float] = {}
        total_obs = 0
        for date in dates:
            entry = compact[date][variant]["cohort_means"][cohort][horizon]
            if entry[0] is not None:
                means[date] = entry[0]
                total_obs += entry[1]
        return means, total_obs

    def _regime_means(dates: list, variant: str, cohort: str, regime: str) -> tuple[dict, int]:
        means: dict[str, float] = {}
        total_obs = 0
        for date in dates:
            entry = compact[date][variant]["regime_means"][cohort][regime]
            if entry[0] is not None:
                means[date] = entry[0]
                total_obs += entry[1]
        return means, total_obs

    economic_rows: list[dict] = []
    split_rows: list[dict] = []
    for period in m4.PERIODS:
        dates = partitions[period]
        for variant in m4.VARIANTS:
            for cohort in m4.COHORTS:
                horizon_stats: dict[int, dict] = {}
                for horizon in m4.HORIZONS:
                    means, total_obs = _cohort_means(dates, variant, cohort, horizon)
                    summary = m4.summarize_date_means(list(means.values()))
                    horizon_stats[horizon] = {
                        "means": means, "total_obs": total_obs, "summary": summary}
                v1_means, _ = _cohort_means(dates, "v1_baseline", cohort, 60)
                paired = m4.paired_delta_stats(
                    horizon_stats[60]["means"], v1_means,
                ) if variant != "v1_baseline" else m4.paired_delta_stats(
                    horizon_stats[60]["means"], horizon_stats[60]["means"])
                summary60 = horizon_stats[60]["summary"]
                summary20 = {"n": horizon_stats[20]["summary"]["n_matured_dates"],
                             "obs": horizon_stats[20]["total_obs"],
                             "mean": horizon_stats[20]["summary"]["mean"]}
                summary120 = {"n": horizon_stats[120]["summary"]["n_matured_dates"],
                              "obs": horizon_stats[120]["total_obs"],
                              "mean": horizon_stats[120]["summary"]["mean"]}
                economic_rows.append({
                    "period": period, "variant": variant, "cohort": cohort,
                    "n_matured_dates_20d": summary20["n"], "n_total_obs_20d": summary20["obs"],
                    "mean_excess_20d": _fmt(summary20["mean"]),
                    "n_matured_dates_60d": summary60["n_matured_dates"],
                    "n_total_obs_60d": horizon_stats[60]["total_obs"],
                    "mean_excess_60d": _fmt(summary60["mean"]),
                    "median_date_excess_60d": _fmt(summary60["median"]),
                    "p10_date_excess_60d": _fmt(summary60["p10"]),
                    "worst_date_excess_60d": _fmt(summary60["worst"]),
                    "n_matured_dates_120d": summary120["n"], "n_total_obs_120d": summary120["obs"],
                    "mean_excess_120d": _fmt(summary120["mean"]),
                    "mean_paired_delta_60d": _fmt(paired["mean_paired_delta_60d"]),
                    "median_paired_delta_60d": _fmt(paired["median_paired_delta_60d"]),
                    "positive_delta_date_share": _fmt(paired["positive_delta_date_share"]),
                    "ci95_low_60d": _fmt(paired["ci95_low_60d"]),
                    "ci95_high_60d": _fmt(paired["ci95_high_60d"]),
                    "loo_min_mean_delta_60d": _fmt(paired["loo_min_mean_delta_60d"]),
                })
    # year & regime splits on ALL_39 for TOP15 / PRIORITY_REVIEW
    all_dates = partitions["ALL_39_DATES"]
    for split_type, split_values in (
        ("year", ("2023", "2024", "2025", "2026Q1")),
        ("regime", ("UP_SUPPORTIVE", "DEFENSIVE_OR_DOWN")),
    ):
        for split_value in split_values:
            for variant in m4.VARIANTS:
                for cohort in ("TOP15", "PRIORITY_REVIEW"):
                    split_dates = [
                        date for date in all_dates
                        if split_type == "regime" or m4.year_bucket(date) == split_value
                    ]
                    regime_filter = split_value if split_type == "regime" else None
                    if split_type == "regime":
                        means, total_obs = _regime_means(
                            split_dates, variant, cohort, split_value)
                    else:
                        means, total_obs = _cohort_means(
                            split_dates, variant, cohort, 60)
                    if split_type == "regime":
                        v1_means, _ = _regime_means(
                            list(means), "v1_baseline", cohort, split_value)
                    else:
                        v1_means, _ = _cohort_means(
                            list(means), "v1_baseline", cohort, 60)
                    paired = m4.paired_delta_stats(means, v1_means) if variant != "v1_baseline" \
                        else m4.paired_delta_stats(means, means)
                    summary = m4.summarize_date_means(list(means.values()))
                    split_rows.append({
                        "split_type": split_type, "split_value": split_value,
                        "variant": variant, "cohort": cohort,
                        "n_dates": summary["n_matured_dates"], "n_obs": total_obs,
                        "mean_excess_60d": _fmt(summary["mean"]),
                        "mean_paired_delta_60d": _fmt(paired["mean_paired_delta_60d"]),
                        "ci95_low_60d": _fmt(paired["ci95_low_60d"]),
                        "ci95_high_60d": _fmt(paired["ci95_high_60d"]),
                    })

    # ---- Track 3: gate ------------------------------------------------------
    gate = _build_gate(utility_rows, economic_rows)
    files: dict[str, str] = {}
    files["m4_human_utility_summary.csv"] = _to_csv(utility_rows, list(UTILITY_COLUMNS))
    files["m4_paired_economic_summary.csv"] = _to_csv(economic_rows, list(ECONOMIC_COLUMNS))
    files["m4_year_and_regime_splits.csv"] = _to_csv(split_rows, list(SPLIT_COLUMNS))
    files["m4_promotion_gate.json"] = json.dumps(gate, indent=2, sort_keys=True) + "\n"
    files["m4_validation_report.md"] = render_report(
        utility_rows, economic_rows, split_rows, gate, parity_samples)
    for name, content in files.items():
        if m4.contains_absolute_path(content):
            raise ValueError(f"absolute path leaked into {name}")
        (out_dir / name).write_text(content)
    checksums = "".join(
        f"{hashlib.sha256(files[name].encode()).hexdigest()}  {name}\n"
        for name in sorted(files)
    )
    (out_dir / "SHA256SUMS").write_text(checksums)
    total = sum(p.stat().st_size for p in out_dir.iterdir())
    print(f"M4: wrote {len(files) + 1} files, {total} bytes in {time.time() - started:.1f}s")
    if total >= MAX_DIR_BYTES:
        raise ValueError(f"deliverable directory exceeds {MAX_DIR_BYTES} bytes")
    print("M4: done.")
    return 0


def _mean_or_none(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 6) if present else None


def _to_csv(rows: list, columns: list) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


def _build_gate(utility_rows: list, economic_rows: list) -> dict:
    """Track 3 Gate G4/G5 artifact from the computed tables."""
    utility_by_scope_variant = {(r["scope"], r["variant"]): r for r in utility_rows}
    human: dict[str, dict] = {}
    for variant in m4.VARIANTS:
        metrics = utility_by_scope_variant.get(("ALL_39_DATES", variant), {})
        baseline = utility_by_scope_variant.get(("ALL_39_DATES", "v1_baseline"), {})
        human[variant] = m4.human_utility_verdict(metrics, baseline)

    def _paired(period: str, variant: str, cohort: str = "TOP15") -> dict:
        for row in economic_rows:
            if row["period"] == period and row["variant"] == variant and row["cohort"] == cohort:
                return {
                    "mean_paired_delta_60d": _num(row["mean_paired_delta_60d"]),
                    "loo_min_mean_delta_60d": _num(row["loo_min_mean_delta_60d"]),
                    "ci95_low_60d": _num(row["ci95_low_60d"]),
                    "ci95_high_60d": _num(row["ci95_high_60d"]),
                }
        return {}

    economic_post = {}
    economic_all = {}
    for v in m4.VARIANTS:
        if v == "v1_baseline":
            economic_post[v] = "REFERENCE_SELF_COMPARISON"
            economic_all[v] = "REFERENCE_SELF_COMPARISON"
        else:
            economic_post[v] = m4.economic_verdict(_paired("POST2024_HELD_OUT", v))
            economic_all[v] = m4.economic_verdict(_paired("ALL_39_DATES", v))
    recommendation = m4.overall_recommendation(human, economic_post, economic_all)
    return {
        "study": "m4_dual_track_paired_validation",
        "frozen": True,
        "evidence_tiers": {
            "DEV_2023_2024": m4.TIER_DEV,
            "POST2024_HELD_OUT": m4.TIER_POST2024,
            "ALL_39_DATES": m4.TIER_ALL,
        },
        "primary_economic_cohort": "TOP15",
        "primary_economic_horizon": "60d net QQQ excess, date-equal, paired by date",
        "human_utility_verdict": human,
        "economic_verdict": {
            "POST2024_HELD_OUT": economic_post,
            "ALL_39_DATES": economic_all,
        },
        "overall_m4_recommendation": recommendation,
        "production_default": 'policy_version="v1" remains untouched unless explicitly promoted in M5',
        "inputs": {
            "decisions_snap510_jsonl": _sha256_file(REPO_ROOT / SNAP510_JSONL),
            "decisions_snap62_jsonl": _sha256_file(REPO_ROOT / SNAP62_JSONL),
            "company_quality_dataset_risk_off_v3_csv": _sha256_file(REPO_ROOT / QUALITY_CSV),
        },
        "policy_versions": {
            "v1": {"quality": QUALITY_POLICY_VERSION, "entry": ENTRY_POLICY_VERSION},
            "v2": {"quality": QUALITY_V2_POLICY_VERSION, "entry": ENTRY_V2_POLICY_VERSION},
        },
    }


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def render_report(utility_rows: list, economic_rows: list, split_rows: list, gate: dict,
                  parity_samples: list | None = None) -> str:
    """Concise decision-grade validation report (all figures from tables)."""
    def _econ(period: str, variant: str, cohort: str = "TOP15") -> dict:
        for row in economic_rows:
            if row["period"] == period and row["variant"] == variant and row["cohort"] == cohort:
                return row
        return {}

    lines = [
        "# M4 Dual-Track Paired Validation Report (frozen 2026-10-15)",
        "",
        "Track 1 (human utility) across snap62/snap510/DEV/POST2024/ALL_39; Track 2",
        "(paired 20/60/120d net-QQQ economics) across DEV_2023_2024, POST2024_HELD_OUT",
        "(15 dates, unsealed once, RETROSPECTIVE_HELD_OUT — never prospective OOS),",
        "and ALL_39_DATES, with date-level bootstrap 95% CI, LOO sensitivity, and",
        "year/regime splits. policy_version=\"v1\" stays the production default.",
        "",
        "## 1. Human utility (ALL_39_DATES)",
        "",
    ]
    for variant in m4.VARIANTS:
        row = next((r for r in utility_rows
                    if r["scope"] == "ALL_39_DATES" and r["variant"] == variant), {})
        verdict = gate["human_utility_verdict"].get(variant, {})
        lines.append(
            f"- {variant}: contradictory={row.get('n_contradictory_cash_accrual')}, "
            f"silent={row.get('n_silent_non_ready_entry')}, "
            f"ready_share={row.get('mean_top15_ready_share')}, "
            f"gate={verdict.get('verdict')}"
        )
    lines += ["", "## 2. Paired economics, TOP15 60d (v2_combined vs v1_baseline)", ""]
    for period in m4.PERIODS:
        row = _econ(period, "v2_combined")
        verdict = gate["economic_verdict"].get(period, {}).get("v2_combined", "development reference (no gate)")
        lines.append(
            f"- {period}: mean_delta={row.get('mean_paired_delta_60d')} "
            f"CI95=[{row.get('ci95_low_60d')},{row.get('ci95_high_60d')}] "
            f"LOO_min={row.get('loo_min_mean_delta_60d')} "
            f"verdict={verdict}"
        )
    lines += ["", "## 3. Year / regime robustness (TOP15 60d, v2_combined)", ""]
    for row in split_rows:
        if row["variant"] == "v2_combined" and row["cohort"] == "TOP15":
            lines.append(
                f"- {row['split_type']}={row['split_value']}: excess={row['mean_excess_60d']} "
                f"delta={row['mean_paired_delta_60d']} "
                f"CI95=[{row['ci95_low_60d']},{row['ci95_high_60d']}] "
                f"(n_dates={row['n_dates']})"
            )
    lines += ["", "## 4. Gate G4/G5 recommendation", "",
              gate["overall_m4_recommendation"]["recommendation"],
              f"Shadow candidates: {gate['overall_m4_recommendation']['shadow_candidates']}",
              "", "## 5. Report v2 parity sample", ""]
    for label, check in parity_samples or []:
        lines.append(
            f"- {label}: n={check['n_decisions']} exceptions={check['n_exceptions']} "
            f"ordering_mismatches={check['n_ordering_mismatches']} "
            f"abs_paths={check['n_absolute_paths']} ok={check['report_v2_parity_ok']}"
        )
    lines += ["", "_End of M4 validation._", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
