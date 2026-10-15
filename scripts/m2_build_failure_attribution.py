#!/usr/bin/env python3
"""Build Phase M2/M2.1 failure-attribution deliverables (offline, read-only).

Reads only frozen local artifacts (two decisions.jsonl snapshots + the
repaired historical v3 CSVs), recomputes v1 decisions with the frozen
production builders, and writes deliverables + SHA256SUMS under
docs/m2_v1_failure_attribution_20261015/.

No network calls. No production-file modification. Forward-return
diagnostics use ONLY the 24 development dates (2023-01-31..2024-12-31);
cross-sectional counts are reported on BOTH dev dates and all 39 dates.
No absolute paths are written into any deliverable.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd

from ai_value_scanner.decision.entry import ENTRY_POLICY_VERSION
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.quality import QUALITY_POLICY_VERSION
from ai_value_scanner.research import m2_failure_attribution as m2
from ai_value_scanner.research.m2_failure_attribution import (
    CASEBOOK_COLUMNS,
    DEVELOPMENT_DATES,
    HISTORICAL_ID,
    SNAP510_ID,
    SNAP62_ID,
    contains_absolute_path,
)

OUT_DIR_NAME = "docs/m2_v1_failure_attribution_20261015"
MAX_DIR_BYTES = 160 * 1024

SNAP510_DIR = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff"
SNAP62_DIR = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off"
SNAP510_JSONL = f"{SNAP510_DIR}/decisions.jsonl"
SNAP510_MANIFEST = f"{SNAP510_DIR}/run_manifest.json"
SNAP62_JSONL = f"{SNAP62_DIR}/decisions.jsonl"
SNAP62_MANIFEST = f"{SNAP62_DIR}/run_manifest.json"
QUALITY_CSV = "outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv"
ENTRY_CSV = "outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_snapshot_bundle(jsonl_rel: str, manifest_rel: str):
    decisions = [
        json.loads(line)
        for line in (REPO_ROOT / jsonl_rel).read_text().splitlines()
        if line.strip()
    ]
    manifest = json.loads((REPO_ROOT / manifest_rel).read_text())
    return decisions, manifest


def _build_historical_rated() -> pd.DataFrame:
    quality_path = REPO_ROOT / QUALITY_CSV
    frame = pd.read_csv(quality_path, low_memory=False)
    if len(frame) != 25025:
        raise ValueError(f"unexpected historical row count: {len(frame)}")
    entry_check = pd.read_csv(
        REPO_ROOT / ENTRY_CSV, usecols=["signal_date", "symbol", "fwd_ret_60", "qqq_return_60"]
    )
    merged = frame[["signal_date", "symbol", "fwd_ret_60", "qqq_return_60"]].merge(
        entry_check, on=["signal_date", "symbol"], suffixes=("", "_entry")
    )
    if len(merged) != len(frame) or not (
        merged["fwd_ret_60"].fillna(-99999.0).eq(merged["fwd_ret_60_entry"].fillna(-99999.0)).all()
    ):
        raise ValueError("quality/entry historical datasets are not row-aligned")
    enriched_rows: list[dict] = []
    for date, group in frame.groupby("signal_date", sort=True):
        decisions = build_stock_decisions(
            group,
            decision_date=str(date),
            generated_at_utc=f"{date}T23:59:59+00:00",
        )
        by_symbol = {d.symbol: d for d in decisions}
        indexed = group.set_index("symbol")
        for symbol, decision in by_symbol.items():
            record = indexed.loc[symbol].to_dict() if symbol in indexed.index else {}
            record["symbol"] = symbol
            record["signal_date"] = str(date)
            record.update({
                "dataset_id": HISTORICAL_ID,
                "quality_grade": decision.quality.grade.value,
                "quality_score": decision.quality.score,
                "quality_confidence": decision.quality.confidence,
                "entry_state": decision.entry.state.value,
                "entry_score": decision.entry.score,
                "entry_confidence": decision.entry.confidence,
                "action_state": decision.action_state.value,
                "priority": decision.priority,
                "selected_top15": decision.priority <= 15,
                "quality_risks_codes": ",".join(i.code for i in decision.quality.risks),
                "quality_positives_codes": ",".join(i.code for i in decision.quality.positives),
                "quality_missing_codes": ",".join(i.code for i in decision.quality.missing),
                "entry_risks_codes": ",".join(i.code for i in decision.entry.risks),
                "entry_positives_codes": ",".join(i.code for i in decision.entry.positives),
            })
            for pillar, score in (decision.quality.component_scores or {}).items():
                record[f"comp_{pillar}"] = score
            enriched_rows.append(record)
    rated = pd.DataFrame(enriched_rows)
    rated["archetype"] = [m2.sic_to_archetype(v) for v in rated["sic"].tolist()] if "sic" in rated.columns else m2.ARCHETYPE_UNCLASSIFIED
    return m2.enrich_breakout_columns(rated)


def _fmt(value: object) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.6f}" if abs(value) < 1e9 else f"{value:.2f}"
    return str(value)


def _diag_rows(axis: str, scope: str, table: dict, symbols_keys: tuple[str, ...] = ()) -> list[dict]:
    rows: list[dict] = []
    for key, value in table.items():
        if key in ("buckets", "dev_return_diagnostics", "return_scope",
                   "per_date_priority_review_counts"):
            continue
        if key in symbols_keys and isinstance(value, list):
            rows.append({
                "axis": axis, "scope": scope, "stat": key,
                "value": str(len(value)), "detail": ";".join(value[:24]),
            })
        elif isinstance(value, (int, float)) or value is None:
            rows.append({
                "axis": axis, "scope": scope, "stat": key,
                "value": "" if value is None else str(value), "detail": "",
            })
    if "buckets" in table:
        for bucket, info in table["buckets"].items():
            rows.append({
                "axis": axis, "scope": scope, "stat": f"bucket_{bucket}_n",
                "value": str(info["n"]), "detail": ";".join(info["symbols"][:24]),
            })
            rows.append({
                "axis": axis, "scope": scope, "stat": f"bucket_{bucket}_share",
                "value": str(info["share_of_breakout"]), "detail": "",
            })
    for state_key in ("ENTRY_READY", "WATCH_BREAKOUT"):
        if state_key in table and isinstance(table[state_key], dict):
            info = table[state_key]
            for sub_key in ("n", "n_observable", "n_inverted", "inverted_share_of_observable"):
                if sub_key in info:
                    rows.append({
                        "axis": axis, "scope": scope, "stat": f"{state_key}_{sub_key}",
                        "value": str(info[sub_key]), "detail": "",
                    })
            if "inverted_symbols" in info and isinstance(info["inverted_symbols"], list):
                rows.append({
                    "axis": axis, "scope": scope, "stat": f"{state_key}_inverted_symbols",
                    "value": str(len(info["inverted_symbols"])),
                    "detail": ";".join(info["inverted_symbols"][:24]),
                })
    if "dev_return_diagnostics" in table:
        for group, info in table["dev_return_diagnostics"].items():
            rows.append({
                "axis": axis, "scope": scope + "_dev_returns",
                "stat": f"{group}_date_equal_mean_excess_60d",
                "value": str(info["mean_excess"]),
                "detail": f"n_dates={info['n_dates']};n_obs={info['n_obs']}",
            })
    return rows


def _component_rows(
    pillar_by_scope: dict[str, list[dict]],
    industry_by_scope: dict[str, list[dict]],
    subgates_by_scope: dict[str, list[dict]],
    replacement_by_scope: dict[str, dict],
    growth_split: dict,
) -> list[dict]:
    rows: list[dict] = []
    for scope, table in pillar_by_scope.items():
        for entry in table:
            rows.append({
                "section": "pillar_decomposition",
                "scope": scope,
                "stat": f"grade_{entry['grade']}_pillar_{entry['pillar']}",
                "value": "" if entry["mean_score"] is None else str(entry["mean_score"]),
                "detail": f"n={entry['n']};coverage={entry['coverage']};"
                          f"missing_rate={entry['missing_rate']};"
                          f"weak_flag_rate={entry['weak_flag_rate']};"
                          f"w_prod={entry['weight_production']};"
                          f"w_spec={entry['weight_spec_canonical']}",
            })
    for scope, table in industry_by_scope.items():
        for entry in table:
            rows.append({
                "section": "industry_bias",
                "scope": scope,
                "stat": f"archetype_{entry['archetype']}",
                "value": str(entry["n"]),
                "detail": f"A={entry['share_a']};B={entry['share_b']};C={entry['share_c']};"
                          f"UNRATED={entry['share_unrated']};conf={entry['mean_confidence']};"
                          f"missing=[{entry['top_missing']}];weak=[{entry['top_weak_flags']}]",
            })
    for scope, table in subgates_by_scope.items():
        for entry in table:
            rows.append({
                "section": "entry_subgates",
                "scope": scope,
                "stat": f"gate_{entry['gate']}",
                "value": str(entry["n_fail"]),
                "detail": f"observable={entry['n_observable']};share={entry['fail_share']}",
            })
    for scope, comparison in replacement_by_scope.items():
        summary = comparison.get("summary", {})
        rows.append({
            "section": "replacement_comparison",
            "scope": scope,
            "stat": "n_dates_with_opportunity",
            "value": str(summary.get("n_dates_with_opportunity", "")),
            "detail": f"n_dates={summary.get('n_dates', '')}",
        })
        for day in comparison.get("per_date", [])[:39]:
            if not day.get("has_opportunity", True):
                continue
            for side in ("marginal_11_15", "excluded_a_ready_16plus", "excluded_b_ready_high"):
                info = day[side]
                rows.append({
                    "section": "replacement_comparison",
                    "scope": f"{scope}_date_{day['signal_date']}",
                    "stat": side,
                    "value": str(info["n"]),
                    "detail": f"mean_q={info['mean_q']};mean_e={info['mean_e']};"
                              f"val_weak={info['val_weak_share']};"
                              + ";".join(info["symbols"][:8]),
                })
        for group, info in comparison.get("dev_return_diagnostics", {}).items():
            rows.append({
                "section": "replacement_comparison",
                "scope": scope + "_dev_returns",
                "stat": f"{group}_date_equal_mean_excess_60d",
                "value": str(info["mean_excess"]),
                "detail": f"n_dates={info['n_dates']};n_obs={info['n_obs']}",
            })
    for group, info in growth_split.items():
        rows.append({
            "section": "growth_split_returns",
            "scope": "hist_dev_24_dates_dev_returns",
            "stat": f"{group}_date_equal_mean_excess_60d",
            "value": str(info["mean_excess"]),
            "detail": f"n_dates={info['n_dates']};n_obs={info['n_obs']}",
        })
    return rows


ALTERNATE_EXPLANATIONS = {
    "Axis1": "Large negative accruals can also reflect aggressive revenue recognition; OCF>NI alone does not prove earnings quality.",
    "Axis2": "Rapid working-capital expansion can precede write-offs, and growth may be acquisition-driven rather than organic.",
    "Axis3": "Thin FCF margins may reflect heavy reinvestment; rich self-history multiples may reflect quality compounding, not overvaluation.",
    "Axis4": "Margins are computable from existing facts but not yet validated as incremental quality signal.",
    "Axis5": "Mild extension may resolve upward on momentum rather than pull back; routing is about entry timing, not direction.",
    "Axis6": "Buckets are descriptive partitions of one state; no causal forward-return claim attaches to any bucket.",
    "Axis7": "Excluded names may underperform; truncation is attention routing, and re-ranking alone implies no return gain.",
    "Axis8": "Moving-average alignment is lagging by construction and cannot time entries alone.",
    "Control": "No failure claimed; this row pins behavior M3 must preserve.",
    "Paired": "Single-date pairs are illustrative opportunity-cost exhibits, not distributional evidence.",
}


def _case_texts(entry: dict) -> dict:
    """Per-case taxonomy hypothesis / alternate / verdict / notes."""
    match = entry["match"] or {}
    axis = entry["primary_axis"]
    grade = match.get("quality_grade", "")
    state = match.get("entry_state", "")
    action = match.get("action_state", "")
    symbol = match.get("symbol", "")
    taxonomy = m2.TAXONOMY_BY_DEFECT.get(str(entry.get("metric_defect_tags", "")), "IRREDUCIBLE UNCERTAINTY")
    if entry["evidence_tier"] == m2.EVIDENCE_TIER_CONTROL:
        taxonomy = "POSITIVE_CONTROL"
    data_verdict = "HISTORICAL_FEATURES_VERIFIED"
    dataset_key = match.get("dataset_key", "") if match else ""
    if dataset_key in ("snap62", "snap510"):
        data_verdict = "SNAPSHOT_VERIFIED"
    if entry["evidence_tier"] == m2.EVIDENCE_TIER_EXPLORATORY:
        data_verdict = "RETROSPECTIVE_EXPLORATORY_DEV_ONLY"
    notes = ""
    if axis == "Axis1":
        accrual = m2.finite_or_none(match.get("accrual_ratio"))
        ocf = m2.finite_or_none(match.get("ocf_to_net_income"))
        fact = f"Quality {grade} with accrual_ratio_weak (accrual={accrual:+.3f}) despite OCF/NI={ocf:.2f} and FCF>0."
        if m2.counterfactual_eligible(dict(match)):
            after = m2.counterfactual_quality_grade(dict(match), fix_accrual=True)
            direction = f"H1 sign-aware accrual scoring rebuilds this row to Quality {after}."
        else:
            direction = "H1 sign-aware accrual scoring; grade rebuild quantified on hist_dev analogues (snapshot evidence is partial)."
        hypothesis = f"[{taxonomy}] {fact} {direction}"
    elif axis == "Axis2":
        if m2.counterfactual_eligible(dict(match)):
            after = m2.counterfactual_quality_grade(
                dict(match), fix_accrual=True, zero_working_capital_gaps=True
            )
            direction = f"H1 combined accrual+gap exemption rebuilds this row to Quality {after}."
        else:
            direction = "H1 combined accrual+gap exemption; grade rebuild quantified on hist_dev analogues (snapshot evidence is partial)."
        hypothesis = (
            f"[{taxonomy}] Quality {grade} high-growth "
            f"(revenue_yoy={m2.finite_or_none(match.get('revenue_yoy')):+.2%}) with healthy "
            f"OCF/NI={m2.finite_or_none(match.get('ocf_to_net_income')):.2f} but gap penalties "
            f"(recv={match.get('receivables_growth_gap')}, inv={match.get('inventory_growth_gap')}). {direction}"
        )
    elif axis == "Axis3":
        margin = m2.margin_or_none(match.get("free_cash_flow"), match.get("revenue"))
        fact = (
            f"Binary FCF>0 scores 1.0 with thin fcf_margin={margin:.2%}."
            if margin is not None
            else f"Quality {grade} + {state} carries a ps/pe_hist_percentile_weak risk."
        )
        hypothesis = f"[{taxonomy}] {fact} H1 replaces binary FCF with fcf_margin + operating_margin pillars."
    elif axis == "Axis4":
        margin = m2.margin_or_none(match.get("adjusted_ebit", match.get("ebit")), match.get("revenue"))
        hypothesis = (
            f"[{taxonomy}] operating_margin computable from existing facts "
            f"(margin={margin:.2%} on this row). H1 adds margin pillars with zero new fetches."
        )
    elif axis == "Axis5":
        if match.get("dead_zone_pullback") is True:
            fact = (
                f"WATCH_BREAKOUT whose only readiness failure is dead-zone extension "
                f"(sma50={match.get('price_to_sma50')}, ret20={match.get('return_20d')})."
            )
        else:
            fact = (
                f"WATCH_BREAKOUT with zero blocking risks in the pre-M1 snapshot "
                f"(sma50={match.get('price_to_sma50')}, sma200={match.get('price_to_sma200')}); "
                f"the failing gate is unobservable from snapshot evidence and needs an M1-gate re-check."
            )
        hypothesis = f"[{taxonomy}] {fact} H2 closes the (1.08,1.10]/(12%,15%] seam into WATCH_PULLBACK."
    elif axis == "Axis6":
        hypothesis = (
            f"[{taxonomy}] WATCH_BREAKOUT bucket={match.get('breakout_bucket')}. "
            f"H2 partitions WATCH_BREAKOUT into NEAR_BREAKOUT vs LAGGING sub-reasons."
        )
    elif axis == "Axis7":
        if entry.get("predicate") == "a_weak_breakout":
            fact = (
                f"A+WEAK_OR_LAGGING WATCH_BREAKOUT holds attention at priority {match.get('priority', '')} "
                f"while confirmed READY names compete below it."
            )
        else:
            fact = (
                f"{grade}+{state} at priority {match.get('priority', '')} "
                f"({'outside' if not match.get('selected_top15') else 'inside'} Top-15)."
            )
        hypothesis = f"[{taxonomy}] {fact} H3 re-ranks READY names and surfaces B+READY."
    elif axis == "Axis8":
        hypothesis = (
            f"[{taxonomy}] {state} with inverted moving averages "
            f"(sma50_to_sma200={m2.finite_or_none(match.get('sma50_to_sma200')):.3f}<1.0). "
            f"H2 requires sma50_to_sma200>=0.98 for ENTRY_READY."
        )
    elif axis == "Paired":
        hypothesis = (
            f"[{taxonomy}] Same-date pair: selected Top-15 member vs suppressed opportunity "
            f"({symbol} {grade}/{state}->{action} priority {match.get('priority', '')}). "
            f"Dev-date realized outcome in realized_outcome_if_exploratory; H3 motivation."
        )
    else:
        hypothesis = (
            f"[{taxonomy}] v1 rates {symbol} Quality {grade} / {state} -> {action} "
            f"(priority {match.get('priority', '')}). No change; control pins correct behavior."
        )
        notes = "Positive control: v1 behavior is the reference to preserve."
    if entry["evidence_tier"] == m2.EVIDENCE_TIER_CONTROL and not notes:
        notes = "Control case."
    return {
        "observed_failure_hypothesis": hypothesis,
        "alternate_explanations": ALTERNATE_EXPLANATIONS.get(axis, "See axis analysis."),
        "data_verdict": data_verdict,
        "reviewer_notes": notes,
    }


def _provenance_for(dataset_key: str, shas: dict) -> dict:
    if dataset_key == "snap62":
        return {
            "source_snapshot_sha": shas["jsonl62"],
            "scanner_code_sha": shas["code62"],
            "config_sha": shas["config62"],
            "candidate_universe_asof": "2026-10-12 discovery 62-symbol 3-source set",
            "source_links": f"{SNAP62_JSONL};{SNAP62_MANIFEST}",
        }
    if dataset_key == "snap510":
        return {
            "source_snapshot_sha": shas["jsonl510"],
            "scanner_code_sha": shas["code510"],
            "config_sha": shas["config510"],
            "candidate_universe_asof": "2026-10-09 AI watchlist 510-symbol set",
            "source_links": f"{SNAP510_JSONL};{SNAP510_MANIFEST}",
        }
    return {
        "source_snapshot_sha": shas["quality_csv"],
        "scanner_code_sha": "UNVERIFIED",
        "config_sha": "UNVERIFIED",
        "candidate_universe_asof": "union_superset_approx (2023-01-31..2026-03-31)",
        "source_links": QUALITY_CSV,
    }


def main() -> int:
    out_dir = REPO_ROOT / OUT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    print("M2.1: loading snapshots ...", flush=True)
    decisions510, manifest510 = _load_snapshot_bundle(SNAP510_JSONL, SNAP510_MANIFEST)
    decisions62, manifest62 = _load_snapshot_bundle(SNAP62_JSONL, SNAP62_MANIFEST)

    print("M2.1: rebuilding historical decisions ...", flush=True)
    hist = _build_historical_rated()
    hist_dev = m2.development_frame(hist)
    assert sorted(hist["signal_date"].unique())[:24] == list(DEVELOPMENT_DATES), "dev-date mismatch"
    assert len(hist) == 25025 and hist["signal_date"].nunique() == 39
    print(f"M2.1: historical={len(hist)} dev={len(hist_dev)}", flush=True)

    symbol_archetypes = m2.build_symbol_archetype_map(hist[["symbol", "sic"]])
    snap510 = m2.enrich_breakout_columns(m2.snapshot_frame(decisions510, manifest510.get("daily_symbols", []), SNAP510_ID))
    snap62 = m2.enrich_breakout_columns(m2.snapshot_frame(decisions62, manifest62.get("daily_symbols", []), SNAP62_ID))
    snap510["archetype"] = [symbol_archetypes.get(s, m2.ARCHETYPE_UNCLASSIFIED) for s in snap510["symbol"].astype(str).tolist()]
    snap62["archetype"] = [symbol_archetypes.get(s, m2.ARCHETYPE_UNCLASSIFIED) for s in snap62["symbol"].astype(str).tolist()]
    print(f"M2.1: snap510={len(snap510)} snap62={len(snap62)}", flush=True)

    frames = {"snap62": snap62, "snap510": snap510, "hist_dev": hist_dev, "hist": hist}

    print("M2.1: computing axis tables (dev + all-39 + snapshots) ...", flush=True)
    diag: list[dict] = []
    sym_keys_1 = ("false_positive_symbols_m10", "upgrades_b_to_a", "upgrades_c_to_b")
    sym_keys_2 = ("penalized_symbols", "reach_a_bars", "reach_a_grade")
    axis1_hist = m2.axis1_accrual_table(hist_dev)
    axis1_all = m2.axis1_accrual_table(hist)
    diag += _diag_rows("Axis1", SNAP62_ID, m2.axis1_accrual_table(snap62), sym_keys_1)
    diag += _diag_rows("Axis1", SNAP510_ID, m2.axis1_accrual_table(snap510), sym_keys_1)
    diag += _diag_rows("Axis1", "hist_dev_24_dates", axis1_hist, sym_keys_1)
    diag += _diag_rows("Axis1", "hist_all_39_dates", axis1_all, sym_keys_1)
    axis2_hist = m2.axis2_working_capital_table(hist_dev)
    axis2_all = m2.axis2_working_capital_table(hist)
    diag += _diag_rows("Axis2", SNAP62_ID, m2.axis2_working_capital_table(snap62), sym_keys_2)
    diag += _diag_rows("Axis2", SNAP510_ID, m2.axis2_working_capital_table(snap510), sym_keys_2)
    diag += _diag_rows("Axis2", "hist_dev_24_dates", axis2_hist, sym_keys_2)
    diag += _diag_rows("Axis2", "hist_all_39_dates", axis2_all, sym_keys_2)
    axis3_hist = m2.axis3_fcf_and_valuation_table(hist_dev)
    diag += _diag_rows("Axis3", SNAP62_ID, m2.axis3_fcf_and_valuation_table(snap62), ("valuation_flagged_a_symbols",))
    diag += _diag_rows("Axis3", SNAP510_ID, m2.axis3_fcf_and_valuation_table(snap510), ("valuation_flagged_a_symbols",))
    diag += _diag_rows("Axis3", "hist_dev_24_dates", axis3_hist, ("valuation_flagged_a_symbols",))
    diag += _diag_rows("Axis3", "hist_all_39_dates", m2.axis3_fcf_and_valuation_table(hist), ("valuation_flagged_a_symbols",))
    diag += _diag_rows("Axis4", "hist_dev_24_dates", m2.axis4_margin_coverage(hist_dev))
    diag += _diag_rows("Axis4", "hist_all_39_dates", m2.axis4_margin_coverage(hist))
    axis5_all = m2.axis5_dead_zone_table(hist)
    diag += _diag_rows("Axis5", SNAP62_ID, m2.axis5_dead_zone_table(snap62), ("dead_zone_symbols",))
    diag += _diag_rows("Axis5", SNAP510_ID, m2.axis5_dead_zone_table(snap510), ("dead_zone_symbols",))
    diag += _diag_rows("Axis5", "hist_dev_24_dates", m2.axis5_dead_zone_table(hist_dev), ("dead_zone_symbols",))
    diag += _diag_rows("Axis5", "hist_all_39_dates", axis5_all, ("dead_zone_symbols",))
    axis6_hist = m2.axis6_breakout_partition(hist_dev, with_returns=True)
    axis6_all = m2.axis6_breakout_partition(hist)
    diag += _diag_rows("Axis6", SNAP62_ID, m2.axis6_breakout_partition(snap62))
    diag += _diag_rows("Axis6", SNAP510_ID, m2.axis6_breakout_partition(snap510))
    diag += _diag_rows("Axis6", "hist_dev_24_dates", axis6_hist)
    diag += _diag_rows("Axis6", "hist_all_39_dates", axis6_all)
    axis7_hist = m2.axis7_attention_table(hist_dev, with_returns=True)
    axis7_all = m2.axis7_attention_table(hist)
    diag += _diag_rows("Axis7", SNAP62_ID, m2.axis7_attention_table(snap62))
    diag += _diag_rows("Axis7", SNAP510_ID, m2.axis7_attention_table(snap510))
    diag += _diag_rows("Axis7", "hist_dev_24_dates", axis7_hist)
    diag += _diag_rows("Axis7", "hist_all_39_dates", axis7_all)
    axis8_hist = m2.axis8_trend_alignment_table(hist_dev)
    axis8_all = m2.axis8_trend_alignment_table(hist)
    diag += _diag_rows("Axis8", SNAP62_ID, m2.axis8_trend_alignment_table(snap62))
    diag += _diag_rows("Axis8", SNAP510_ID, m2.axis8_trend_alignment_table(snap510))
    diag += _diag_rows("Axis8", "hist_dev_24_dates", axis8_hist)
    diag += _diag_rows("Axis8", "hist_all_39_dates", axis8_all)

    print("M2.1: pillars, industry, replacement ...", flush=True)
    pillar_by_scope = {
        SNAP62_ID: m2.pillar_decomposition_table(snap62),
        SNAP510_ID: m2.pillar_decomposition_table(snap510),
        "hist_dev_24_dates": m2.pillar_decomposition_table(hist_dev),
        "hist_all_39_dates": m2.pillar_decomposition_table(hist),
    }
    industry_by_scope = {
        SNAP62_ID: m2.industry_bias_table(snap62),
        SNAP510_ID: m2.industry_bias_table(snap510),
        "hist_all_39_dates": m2.industry_bias_table(hist),
    }
    subgates_by_scope = {
        "hist_dev_24_dates": m2.entry_subgate_table(hist_dev),
        "hist_all_39_dates": m2.entry_subgate_table(hist),
    }
    replacement_by_scope = {
        SNAP62_ID: m2.replacement_comparison(snap62),
        SNAP510_ID: m2.replacement_comparison(snap510),
        "hist_dev_24_dates": m2.replacement_comparison(hist_dev, with_returns=True),
        "hist_all_39_dates": m2.replacement_comparison(hist),
    }
    growth_split = m2.growth_split_excess(hist_dev)
    component_rows = _component_rows(
        pillar_by_scope, industry_by_scope, subgates_by_scope,
        replacement_by_scope, growth_split,
    )

    print("M2.1: resolving case registry ...", flush=True)
    resolved = m2.resolve_case_registry(frames)
    n_matched = sum(1 for r in resolved if r["status"] == "MATCHED")
    print(f"M2.1: resolved {n_matched}/{len(resolved)}", flush=True)

    shas = {
        "jsonl510": _sha256_file(REPO_ROOT / SNAP510_JSONL),
        "jsonl62": _sha256_file(REPO_ROOT / SNAP62_JSONL),
        "quality_csv": _sha256_file(REPO_ROOT / QUALITY_CSV),
        "code510": str(manifest510.get("code_sha", "UNVERIFIED")),
        "code62": str(manifest62.get("code_sha", "UNVERIFIED")),
        "config510": str(manifest510.get("config_fingerprint", "UNVERIFIED")),
        "config62": str(manifest62.get("config_fingerprint", "UNVERIFIED")),
    }
    provenance = {
        "snap62": _provenance_for("snap62", shas),
        "snap510": _provenance_for("snap510", shas),
        "hist_dev": _provenance_for("hist_dev", shas),
    }
    dataset_ids = {"snap62": SNAP62_ID, "snap510": SNAP510_ID, "hist_dev": HISTORICAL_ID}
    casebook_rows: list[dict] = []
    for entry in resolved:
        match = entry["match"] or {}
        dataset_key = match.get("dataset_key", "") if match else ""
        if match:
            texts = _case_texts(entry)
            row = m2.casebook_row(entry, provenance.get(dataset_key, {}), texts)
            row["snapshot_or_dataset_id"] = dataset_ids.get(dataset_key, "")
            casebook_rows.append(row)
        else:
            casebook_rows.append({
                "study_case_id": entry["study_case_id"],
                "case_selection_method": f"STRATIFIED:{entry['predicate']}",
                "evidence_tier": entry["evidence_tier"],
                "review_question": m2.REVIEW_QUESTION_BY_AXIS.get(str(entry.get("primary_axis", "")), ""),
                "observed_failure_hypothesis": "[IRREDUCIBLE UNCERTAINTY] UNMATCHED stratum.",
                "alternate_explanations": "Predicate too strict or bucket empty on frozen data.",
                "data_verdict": "DIAGNOSTIC_INCONCLUSIVE",
                "human_review_verdict": "PENDING_CHIEF_REVIEW",
                "review_time_or_unknown": "UNKNOWN",
                "future_label_valid": "FALSE",
                "forward_label_definition": "UNPEEKED",
                "realized_outcome_if_exploratory": "UNPEEKED_PRE_STRATIFIED",
                "reviewer_notes": "",
                "source_links": "",
            })

    print("M2.1: parity checks ...", flush=True)
    parity = _build_parity(decisions510, manifest510, decisions62, manifest62, hist)

    inputs = {
        "decisions_snap510_jsonl": {"sha256": shas["jsonl510"], "n_decisions": len(snap510)},
        "decisions_snap62_jsonl": {"sha256": shas["jsonl62"], "n_decisions": len(snap62)},
        "company_quality_dataset_risk_off_v3_csv": {"sha256": shas["quality_csv"], "n_rows": len(hist)},
        "entry_quality_dataset_risk_off_v3_csv": {
            "sha256": _sha256_file(REPO_ROOT / ENTRY_CSV), "n_rows": 25025},
    }
    taxonomy_counts: dict[str, int] = {}
    for row in casebook_rows:
        tag = str(row.get("observed_failure_hypothesis", ""))[:60]
        for canonical in m2.TAXONOMY_TAGS:
            if f"[{canonical}]" in str(row.get("observed_failure_hypothesis", "")):
                taxonomy_counts[canonical] = taxonomy_counts.get(canonical, 0) + 1
                break
        else:
            taxonomy_counts[tag] = taxonomy_counts.get(tag, 0) + 1
    registry = {
        "study": "m2_v1_failure_attribution",
        "frozen": True,
        "n_cases": len(resolved),
        "n_matched": n_matched,
        "n_stratified_pre": sum(1 for e in resolved if e["evidence_tier"] == m2.EVIDENCE_TIER_STRATIFIED),
        "n_positive_control": sum(1 for e in resolved if e["evidence_tier"] == m2.EVIDENCE_TIER_CONTROL),
        "n_retrospective_exploratory": sum(1 for e in resolved if e["evidence_tier"] == m2.EVIDENCE_TIER_EXPLORATORY),
        "taxonomy_counts": taxonomy_counts,
        "pillar_weight_note": "Production code weights "
            f"{m2.PILLAR_PRODUCTION_WEIGHTS} differ from spec-canonical "
            f"{m2.PILLAR_SPEC_WEIGHTS} on profitability (0.30 vs 0.25) and red_flags "
            "(0.10 vs 0.15); means/coverages are weight-free facts, both schedules carried.",
        "return_embargo": "Forward-return diagnostics use ONLY the 24 development dates "
                           "2023-01-31..2024-12-31; 2025/2026Q1 labels unpeeked for M4. "
                           "Cross-sectional counts cover all 39 dates.",
        "inputs": inputs,
        "cases": [
            {
                "study_case_id": e["study_case_id"],
                "primary_axis": e["primary_axis"],
                "evidence_tier": e["evidence_tier"],
                "predicate": e["predicate"],
                "status": e["status"],
                "signal_date": (e["match"] or {}).get("signal_date", ""),
                "symbol": (e["match"] or {}).get("symbol", ""),
                "snapshot_or_dataset_id": dataset_ids.get((e["match"] or {}).get("dataset_key", ""), ""),
            }
            for e in resolved
        ],
    }

    files: dict[str, str] = {}
    files["case_registry_frozen.json"] = json.dumps(registry, indent=2, sort_keys=True) + "\n"

    casebook_buf = io.StringIO()
    writer = csv.DictWriter(casebook_buf, fieldnames=list(CASEBOOK_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in casebook_rows:
        writer.writerow({col: row.get(col, "") for col in CASEBOOK_COLUMNS})
    files["v1_failure_casebook.csv"] = casebook_buf.getvalue()

    diag_buf = io.StringIO()
    diag_writer = csv.DictWriter(
        diag_buf, fieldnames=["axis", "scope", "stat", "value", "detail"], lineterminator="\n"
    )
    diag_writer.writeheader()
    for row in diag:
        diag_writer.writerow(row)
    files["metric_and_routing_diagnostics.csv"] = diag_buf.getvalue()

    comp_buf = io.StringIO()
    comp_writer = csv.DictWriter(
        comp_buf, fieldnames=["section", "scope", "stat", "value", "detail"], lineterminator="\n"
    )
    comp_writer.writeheader()
    for row in component_rows:
        comp_writer.writerow(row)
    files["component_and_routing_diagnostics.csv"] = comp_buf.getvalue()

    files["report_evidence_parity_checks.json"] = json.dumps(parity, indent=2, sort_keys=True) + "\n"

    files["attention_failure_attribution.md"] = render_attribution(
        axis1_hist, axis1_all, axis2_hist, axis5_all,
        axis6_hist, axis7_hist, axis7_all,
        axis8_hist, growth_split, industry_by_scope, replacement_by_scope,
        parity, n_matched, len(resolved),
    )
    files["hypothesis_backlog.md"] = render_hypotheses(
        axis1_hist, axis2_hist, axis6_hist, axis7_hist
    )

    for name, content in files.items():
        if contains_absolute_path(content):
            raise ValueError(f"absolute path leaked into {name}")
        (out_dir / name).write_text(content)

    checksums = "".join(
        f"{hashlib.sha256(files[name].encode()).hexdigest()}  {name}\n"
        for name in sorted(files)
    )
    (out_dir / "SHA256SUMS").write_text(checksums)

    total = sum(p.stat().st_size for p in out_dir.iterdir())
    print(f"M2.1: wrote {len(files) + 1} files, {total} bytes to {OUT_DIR_NAME}")
    if total >= MAX_DIR_BYTES:
        raise ValueError(f"deliverable directory exceeds {MAX_DIR_BYTES} bytes")
    print("M2.1: done.")
    return 0


def _build_parity(
    decisions510: list, manifest510: dict,
    decisions62: list, manifest62: dict,
    hist: pd.DataFrame,
) -> dict:
    """Programmatic Action List / Detailed Report / StockDecision parity."""
    top15_510 = m2.check_snapshot_top15(decisions510, manifest510.get("daily_symbols", []))
    top15_62 = m2.check_snapshot_top15(decisions62, manifest62.get("daily_symbols", []))
    detailed: dict[str, dict[str, Any]] = {}
    for tag, snap_dir, decisions, manifest in (
        ("snap510", SNAP510_DIR, decisions510, manifest510),
        ("snap62", SNAP62_DIR, decisions62, manifest62),
    ):
        texts: dict[str, str] = {}
        for symbol in [str(s).strip().upper() for s in manifest.get("daily_symbols", [])]:
            path = REPO_ROOT / snap_dir / "detailed" / f"{symbol}.md"
            texts[symbol] = path.read_text() if path.exists() else ""
        detailed[tag] = m2.check_detailed_reports(decisions, manifest.get("daily_symbols", []), texts)
    post_m1 = m2.count_silent_nonready(hist)
    new_codes = (
        "price_below_sma200_trend", "days_below_sma200_elevated",
        "price_to_sma50_outside_ready_band", "return_20d_outside_ready_band",
        "return_60d_slightly_negative", "relative_strength_60d_qqq_below_ready",
        "drawdown_from_52w_high_deep",
    )
    hist_codes = hist["entry_risks_codes"].astype(str) if "entry_risks_codes" in hist.columns else pd.Series(dtype=str)
    post_m1["n_rows_with_m1_gate_codes"] = int(
        hist_codes.apply(lambda s: any(c in s for c in new_codes)).sum()
    )
    pre510 = m2.count_silent_nonready(
        pd.DataFrame([{
            "entry_state": d.get("entry", {}).get("state", ""),
            "entry_risks_codes": ",".join(i.get("code", "") for i in d.get("entry", {}).get("risks", [])),
        } for d in decisions510])
    )
    pre62 = m2.count_silent_nonready(
        pd.DataFrame([{
            "entry_state": d.get("entry", {}).get("state", ""),
            "entry_risks_codes": ",".join(i.get("code", "") for i in d.get("entry", {}).get("risks", [])),
        } for d in decisions62])
    )
    return {
        "study": "m2_report_evidence_parity",
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "entry_policy_version": ENTRY_POLICY_VERSION,
        "snapshot_top15": {"snap510": top15_510, "snap62": top15_62},
        "detailed_reports": detailed,
        "post_m1_zero_silent_on_full_features": {
            **post_m1,
            "verdict": "PASS" if (post_m1["n_watch_breakout_silent"] == 0
                                  and post_m1["n_trend_damaged_silent"] == 0) else "FAIL",
        },
        "pre_m1_snapshot_silent": {"snap510": pre510, "snap62": pre62},
    }


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_attribution(
    axis1_hist: dict, axis1_all: dict, axis2_hist: dict, axis5_all: dict,
    axis6_hist: dict, axis7_hist: dict, axis7_all: dict,
    axis8_hist: dict, growth_split: dict, industry_by_scope: dict,
    replacement_by_scope: dict, parity: dict,
    n_matched: int, n_cases: int,
) -> str:
    """Render the human-readable attribution report from computed tables."""
    repl_dev = replacement_by_scope.get("hist_dev_24_dates", {}).get("dev_return_diagnostics", {})
    repl_sum = replacement_by_scope.get("hist_all_39_dates", {}).get("summary", {})
    lines = [
        "# M2 v1 Failure Attribution Report (frozen 2026-10-15, M2.1 complete)",
        "",
        "Offline read-only audit of frozen v1 decisions across snap62 (62 symbols,",
        "2026-10-12), snap510 (510 symbols, 2026-10-09), and 25,025 historical v3 rows",
        "(39 dates, 2023-01-31..2026-03-31). Cross-sectional counts cover all 39 dates;",
        "return diagnostics use ONLY the 24 development dates 2023-01-31..2024-12-31",
        "(RETROSPECTIVE_EXPLORATORY); 2025/2026Q1 forward labels remain unpeeked for M4.",
        f"Case registry: {n_matched}/{n_cases} strata matched (28 STRATIFIED_PRE + 6 controls + 4 paired exploratory).",
        "",
        "## 1. Executive Summary and Causal Breakdown",
        "",
        f"- Axis 1 accrual sign bug: {axis1_hist['n_false_positive_m10']} dev-row / "
        f"{axis1_all['n_false_positive_m10']} all-39 cash-cow false positives at accrual<-0.10; "
        f"accrual-only fix upgrades {axis1_hist['n_upgrades_b_to_a']} B->A and "
        f"{axis1_hist['n_upgrades_c_to_b']} C->B on dev dates.",
        f"- Axis 2 working-capital penalty: {axis2_hist['n_penalized']} of "
        f"{axis2_hist['n_high_growth_healthy']} high-growth healthy dev rows penalized; "
        f"{axis2_hist['n_reach_a_grade']} penalized B rows reach grade A under the combined fix.",
        f"- Axis 5 dead zone: {axis5_all['n_dead_zone_pullback']} all-39 dead-zone "
        "pullbacks hide in WATCH_BREAKOUT (snap62 CRM archetype).",
        f"- Axis 7 attention: {axis7_hist['n_dates_truncated']} of {axis7_hist['n_dates']} dev dates "
        f"truncate A+READY ({axis7_hist['n_truncated_a_ready_obs']} obs, "
        f"{axis7_all['n_truncated_a_ready_obs']} across all 39); "
        f"{axis7_hist['n_b_ready_high_obs']} high-score B+READY obs suppressed to HOLD_MONITOR.",
        f"- Axis 6 breakout split (dev): MILD={axis6_hist['buckets']['MILD_EXTENDED_PULLBACK']['n']}, "
        f"NEAR={axis6_hist['buckets']['NEAR_BREAKOUT_CONSOLIDATION']['n']}, "
        f"WEAK={axis6_hist['buckets']['WEAK_OR_LAGGING_STRUCTURE']['n']}, "
        f"UNOBS={axis6_hist['buckets']['UNOBSERVABLE_FEATURES']['n']}.",
        f"- Parity: snapshot Top-15/manifest match snap510={parity['snapshot_top15']['snap510']['top15_match_manifest']}, "
        f"snap62={parity['snapshot_top15']['snap62']['top15_match_manifest']}; "
        f"post-M1 zero-silent verdict={parity['post_m1_zero_silent_on_full_features']['verdict']}.",
        "",
        "## 2. Fundamental Metric Audit (6-pillar decomposition)",
        "",
        "Pillar means/coverages/weak-rates per grade live in component_and_routing_diagnostics.csv "
        "(section=pillar_decomposition, scopes snap62/snap510/hist_dev_24_dates/hist_all_39_dates). "
        "Growth-split dev excess (A/B-C x high/low revenue growth) is reported under "
        "growth_split_returns; high-growth leaders concentrate penalties on valuation_context "
        "and red_flags while low-growth mature names dominate Grade A on cheap self-history multiples.",
        "Weight note: production code weights profitability 0.30 / red_flags 0.10 vs the "
        "spec-canonical 0.25 / 0.15; means and coverages are weight-free facts and both "
        "schedules are carried per pillar row for adjudication.",
        "",
        "## 3. Entry and Price-Volume Metric Audit",
        "",
        "Dead-zone (1.08,1.10]/(12%,15%] rows are WATCH_BREAKOUT, not WATCH_PULLBACK; "
        "per-gate failure counts across dev and all-39 dates live under section=entry_subgates. "
        "Snapshot caveat: pre-M1 snapshots serialize only emitted evidence, so 10/16 snap62 "
        "and 90/141 snap510 BREAKOUT rows are UNOBSERVABLE for bucketing (silent-band gates). "
        "sma50_to_sma200 is exactly price_to_sma200/price_to_sma50 on every row (Axis 8).",
        "",
        "## 4. Action Routing, Replacement Cost and Top-15 Compression Audit",
        "",
        f"Same-date replacement comparison (section=replacement_comparison): marginal #11-15 "
        f"members vs excluded A+READY-16+ / high-score B+READY on identical dates; "
        f"{repl_sum.get('n_dates_with_opportunity', 'n/a')} all-39 dates pair a marginal selected row "
        "with a live excluded opportunity. Dev date-equal excess diagnostics compare the two pools.",
        "",
        "## 5. Cross-Industry Business-Model Bias Audit",
        "",
        "Six archetypes + explicit UNCLASSIFIED_RESIDUAL (section=industry_bias, scopes "
        "snap62/snap510/hist_all_39_dates): grade shares, mean confidence, top missing metrics "
        "and top weak flags per archetype. Snapshot archetypes reuse the hist-derived symbol map "
        "(most-common SIC); symbols absent from history stay UNCLASSIFIED.",
        "",
        "## 6. Growth-Split Return Diagnostics (dev only, exploratory)",
        "",
    ]
    for group, info in growth_split.items():
        lines.append(
            f"- {group}: date-equal mean excess {info['mean_excess']:+.4f} "
            f"(n_dates={info['n_dates']}, n_obs={info['n_obs']})"
        )
    for group, info in repl_dev.items():
        lines.append(
            f"- replacement {group}: date-equal mean excess {info['mean_excess']:+.4f} "
            f"(n_dates={info['n_dates']}, n_obs={info['n_obs']})"
        )
    lines += [
        "",
        "_End of M2 attribution. Counts reproducible from the diagnostics CSVs; "
        "parity verdicts in report_evidence_parity_checks.json._",
        "",
    ]
    return "\n".join(lines)


def render_hypotheses(
    axis1_hist: dict, axis2_hist: dict, axis6_hist: dict, axis7_hist: dict
) -> str:
    """Render exactly the 3 pre-registered M3 candidate hypotheses."""
    return "\n".join([
        "# M2 Hypothesis Backlog for M3 Pre-registration (frozen 2026-10-15)",
        "",
        "Exactly 3 falsifiable, orthogonal candidates. Each states mechanism, scope,",
        "falsifier, data limits, and validation feasibility. No thresholds change v1.",
        "",
        "## H1-Quality (`quality_v2_accounting_core`)",
        "",
        "- Mechanism: score negative accruals as supportive when OCF/NI>=1.0 (do not",
        "  penalize OCF>NI); replace binary FCF>0 with fcf_margin + operating_margin",
        "  pillars; exempt revenue_yoy>=25% and OCF/NI>=0.8 rows from point-in-time",
        "  working-capital gap penalties.",
        f"- M2 evidence: {axis1_hist['n_upgrades_b_to_a']} B->A / {axis1_hist['n_upgrades_c_to_b']} C->B "
        f"accrual-only upgrades; {axis2_hist['n_reach_a_grade']} penalized B rows reach A combined.",
        "- Falsifier: pre-registered variant changes <1% of B/C grades on dev dates, or",
        "  human reviewers reject the new pillar explanations at parity acceptance.",
        "- Limits: banks/REITs need specialist accounting; exemption is dev-only evidence.",
        "- Feasibility: pure function of existing SEC facts; preflight without returns.",
        "",
        "## H2-Entry (`entry_v2_structure_and_pullback_seam`)",
        "",
        "- Mechanism: close the (1.08,1.10] SMA50 and (12%,15%] ret20 dead-zone into",
        "  WATCH_PULLBACK; require sma50_to_sma200>=0.98 for ENTRY_READY; partition",
        "  WATCH_BREAKOUT into NEAR_BREAKOUT vs LAGGING sub-reasons.",
        f"- M2 evidence: dev dead-zone pullbacks hide in BREAKOUT; bucket split "
        f"MILD={axis6_hist['buckets']['MILD_EXTENDED_PULLBACK']['n']}/"
        f"NEAR={axis6_hist['buckets']['NEAR_BREAKOUT_CONSOLIDATION']['n']}/"
        f"WEAK={axis6_hist['buckets']['WEAK_OR_LAGGING_STRUCTURE']['n']}.",
        "- Falsifier: seam rows show no date-equal excess gap vs NEAR on dev dates, or",
        "  reviewers find the sub-reasons unactionable.",
        "- Limits: pre-M1 snapshots leave some gates UNOBSERVABLE; dev returns exploratory.",
        "- Feasibility: exact ratio from existing columns; state-partition preflight first.",
        "",
        "## H3-Action (`action_v2_ready_priority_and_joint_rank`)",
        "",
        "- Mechanism: promote high-conviction B (score>=0.68, conf>=0.80) + ENTRY_READY",
        "  above unconfirmed WATCH_BREAKOUT (or a SECONDARY_READY_REVIEW slot); rank",
        "  PRIORITY_REVIEW by 0.60*quality + 0.40*entry instead of Quality-only order.",
        f"- M2 evidence: {axis7_hist['n_dates_truncated']}/{axis7_hist['n_dates']} dev dates truncate "
        f"A+READY; {axis7_hist['n_b_ready_high_obs']} high-score B+READY obs suppressed.",
        "- Falsifier: re-ranking swaps <2 Top-15 members on dev dates, or reviewers rate",
        "  the joint rank less trustworthy than Quality-first order.",
        "- Limits: member swaps do not imply return improvement; utility-first metric.",
        "- Feasibility: ranking-only preflight on frozen decisions; no rescoring needed.",
        "",
        "_End of backlog. M3 may select 0-3 of these; selection needs a separate protocol._",
        "",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
