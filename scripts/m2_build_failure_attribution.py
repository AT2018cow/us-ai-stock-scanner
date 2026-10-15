#!/usr/bin/env python3
"""Build Phase M2 failure-attribution deliverables (offline, read-only).

Reads only frozen local artifacts (two decisions.jsonl snapshots + the
repaired historical v3 CSVs), recomputes v1 decisions with the frozen
production builders, and writes 5 compact deliverables + SHA256SUMS under
docs/m2_v1_failure_attribution_20261015/.

No network calls. No production-file modification. Forward-return
diagnostics use ONLY the 24 development dates (2023-01-31..2024-12-31).
No absolute paths are written into any deliverable.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd

from ai_value_scanner.decision.integrated import build_stock_decisions
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
MAX_DIR_BYTES = 120 * 1024

SNAP510_JSONL = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/decisions.jsonl"
SNAP510_MANIFEST = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/run_manifest.json"
SNAP62_JSONL = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/decisions.jsonl"
SNAP62_MANIFEST = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/run_manifest.json"
QUALITY_CSV = "outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv"
ENTRY_CSV = "outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_snapshot(jsonl_rel: str, manifest_rel: str, dataset_id: str) -> pd.DataFrame:
    decisions = [
        json.loads(line)
        for line in (REPO_ROOT / jsonl_rel).read_text().splitlines()
        if line.strip()
    ]
    manifest = json.loads((REPO_ROOT / manifest_rel).read_text())
    frame = m2.snapshot_frame(decisions, manifest.get("daily_symbols", []), dataset_id)
    return m2.enrich_breakout_columns(frame)


def _codes(row: pd.Series, column: str) -> str:
    value = row.get(column, "")
    return "" if value is None else str(value)


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
            enriched_rows.append(record)
    rated = pd.DataFrame(enriched_rows)
    return m2.enrich_breakout_columns(rated)


def _fmt(value: object) -> str:
    if value is None:
        return ""
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


def _case_texts(entry: dict) -> dict:
    """Per-case observed / counterfactual / notes text (axis-specific)."""
    match = entry["match"] or {}
    axis = entry["primary_axis"]
    grade = match.get("quality_grade", "")
    state = match.get("entry_state", "")
    action = match.get("action_state", "")
    symbol = match.get("symbol", "")
    observed = f"v1 rates {symbol} Quality {grade} / {state} -> {action} (priority {match.get('priority', '')})."
    counterfactual = "No M3 change proposed by this case alone; see H1-H3 backlog."
    notes = ""
    data_verdict = "HISTORICAL_FEATURES_VERIFIED"
    dataset_key = match.get("dataset_key", "") if match else ""
    if dataset_key in ("snap62", "snap510"):
        data_verdict = "SNAPSHOT_VERIFIED"
    if axis == "Axis1":
        accrual = m2.finite_or_none(match.get("accrual_ratio"))
        ocf = m2.finite_or_none(match.get("ocf_to_net_income"))
        observed = (
            f"Quality {grade} with accrual_ratio_weak "
            f"(accrual={accrual:+.3f}) despite OCF/NI={ocf:.2f} and FCF>0."
        )
        if m2.counterfactual_eligible(dict(match)):
            after = m2.counterfactual_quality_grade(dict(match), fix_accrual=True)
            counterfactual = f"H1 sign-aware accrual scoring rebuilds this row to Quality {after}."
        else:
            counterfactual = ("H1 sign-aware accrual scoring; grade rebuild quantified on "
                              "hist_dev analogues (snapshot evidence is partial).")
        notes = "accrual_ratio_weak code present while cash conversion is strong."
    elif axis == "Axis2":
        if m2.counterfactual_eligible(dict(match)):
            after = m2.counterfactual_quality_grade(
                dict(match), fix_accrual=True, zero_working_capital_gaps=True
            )
            counterfactual = f"H1 combined accrual+gap exemption rebuilds this row to Quality {after}."
        else:
            counterfactual = ("H1 combined accrual+gap exemption; grade rebuild quantified on "
                              "hist_dev analogues (snapshot evidence is partial).")
        observed = (
            f"Quality {grade} high-growth (revenue_yoy={m2.finite_or_none(match.get('revenue_yoy')):+.2%}) "
            f"with healthy OCF/NI={m2.finite_or_none(match.get('ocf_to_net_income')):.2f} "
            f"but gap penalties (recv_gap={match.get('receivables_growth_gap')}, "
            f"inv_gap={match.get('inventory_growth_gap')})."
        )
    elif axis == "Axis3":
        margin = m2.margin_or_none(match.get("free_cash_flow"), match.get("revenue"))
        observed = (
            f"Binary FCF>0 scores 1.0 with thin fcf_margin={margin:.2%}."
            if margin is not None else
            f"Quality {grade} + {state} carries a ps/pe_hist_percentile_weak risk."
        )
        counterfactual = "H1 replaces binary FCF with fcf_margin + operating_margin pillars."
    elif axis == "Axis4":
        margin = m2.margin_or_none(
            match.get("adjusted_ebit", match.get("ebit")), match.get("revenue")
        )
        observed = f"operating_margin computable from existing facts (margin={margin:.2%} on this row)."
        counterfactual = "H1 adds operating_margin/fcf_margin pillars with zero new fetches."
    elif axis == "Axis5":
        if match.get("dead_zone_pullback") is True:
            observed = (
                f"WATCH_BREAKOUT whose only readiness failure is dead-zone extension "
                f"(sma50={match.get('price_to_sma50')}, ret20={match.get('return_20d')}); "
                f"mild pullback candidate misrouted from WATCH_PULLBACK."
            )
        else:
            observed = (
                f"WATCH_BREAKOUT with zero blocking risks in the pre-M1 snapshot "
                f"(sma50={match.get('price_to_sma50')}, sma200={match.get('price_to_sma200')}); "
                f"the failing gate is unobservable from snapshot evidence "
                f"(ret20/drawdown/vol absent) and needs an M1-gate re-check, "
                f"not a presumed dead-zone label."
            )
        counterfactual = "H2 closes the (1.08,1.10]/(12%,15%] seam into WATCH_PULLBACK."
    elif axis == "Axis6":
        observed = f"WATCH_BREAKOUT bucket={match.get('breakout_bucket')} (heterogeneous state)."
        counterfactual = "H2 partitions WATCH_BREAKOUT into NEAR_BREAKOUT vs LAGGING sub-reasons."
    elif axis == "Axis7":
        if entry.get("predicate") == "a_weak_breakout":
            observed = (
                f"A+WEAK_OR_LAGGING WATCH_BREAKOUT holds attention at priority "
                f"{match.get('priority', '')} while confirmed READY names compete below it: "
                f"weak-breakout rank inversion."
            )
        else:
            observed = (
                f"{grade}+{state} at priority {match.get('priority', '')} "
                f"({'outside' if not match.get('selected_top15') else 'inside'} Top-15): "
                f"attention truncated/suppressed by Quality-first lexicographic ranking."
            )
        counterfactual = "H3 ranks READY names by 0.60*quality + 0.40*entry and surfaces B+READY."
    elif axis == "Axis8":
        observed = (
            f"{state} with inverted moving averages "
            f"(sma50_to_sma200={m2.finite_or_none(match.get('sma50_to_sma200')):.3f}<1.0)."
        )
        counterfactual = "H2 requires sma50_to_sma200>=0.98 for ENTRY_READY."
    else:
        notes = "Positive control: v1 behavior is the reference to preserve."
        counterfactual = "No change; control pins current correct behavior."
    if entry["evidence_tier"] == m2.EVIDENCE_TIER_CONTROL:
        notes = (notes + " Control case." if notes else "Control case.").strip()
    return {
        "observed_v1_behavior": observed,
        "counterfactual_m3_behavior": counterfactual,
        "data_verdict": data_verdict,
        "reviewer_notes": notes,
    }


def main() -> int:
    out_dir = REPO_ROOT / OUT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    print("M2: loading snapshots ...", flush=True)
    snap510 = _load_snapshot(SNAP510_JSONL, SNAP510_MANIFEST, SNAP510_ID)
    snap62 = _load_snapshot(SNAP62_JSONL, SNAP62_MANIFEST, SNAP62_ID)
    print(f"M2: snap510={len(snap510)} snap62={len(snap62)}", flush=True)

    print("M2: verifying historical datasets ...", flush=True)
    hist = _build_historical_rated()
    hist_dev = m2.development_frame(hist)
    assert sorted(hist["signal_date"].unique())[:24] == list(DEVELOPMENT_DATES), "dev-date mismatch"
    print(f"M2: historical={len(hist)} dev={len(hist_dev)}", flush=True)

    frames = {"snap62": snap62, "snap510": snap510, "hist_dev": hist_dev, "hist": hist}

    print("M2: computing axis tables ...", flush=True)
    diag: list[dict] = []
    diag += _diag_rows("Axis1", SNAP62_ID, m2.axis1_accrual_table(snap62), ("false_positive_symbols_m10", "upgrades_b_to_a", "upgrades_c_to_b"))
    diag += _diag_rows("Axis1", SNAP510_ID, m2.axis1_accrual_table(snap510), ("false_positive_symbols_m10", "upgrades_b_to_a", "upgrades_c_to_b"))
    axis1_hist = m2.axis1_accrual_table(hist_dev)
    diag += _diag_rows("Axis1", "hist_dev_24_dates", axis1_hist, ("false_positive_symbols_m10", "upgrades_b_to_a", "upgrades_c_to_b"))
    diag += _diag_rows("Axis2", SNAP62_ID, m2.axis2_working_capital_table(snap62), ("penalized_symbols", "reach_a_bars", "reach_a_grade"))
    diag += _diag_rows("Axis2", SNAP510_ID, m2.axis2_working_capital_table(snap510), ("penalized_symbols", "reach_a_bars", "reach_a_grade"))
    axis2_hist = m2.axis2_working_capital_table(hist_dev)
    diag += _diag_rows("Axis2", "hist_dev_24_dates", axis2_hist, ("penalized_symbols", "reach_a_bars", "reach_a_grade"))
    diag += _diag_rows("Axis3", SNAP62_ID, m2.axis3_fcf_and_valuation_table(snap62), ("valuation_flagged_a_symbols",))
    diag += _diag_rows("Axis3", SNAP510_ID, m2.axis3_fcf_and_valuation_table(snap510), ("valuation_flagged_a_symbols",))
    axis3_hist = m2.axis3_fcf_and_valuation_table(hist_dev)
    diag += _diag_rows("Axis3", "hist_dev_24_dates", axis3_hist, ("valuation_flagged_a_symbols",))
    diag += _diag_rows("Axis4", "hist_dev_24_dates", m2.axis4_margin_coverage(hist_dev))
    diag += _diag_rows("Axis4", "hist_all_39_dates", m2.axis4_margin_coverage(hist))
    diag += _diag_rows("Axis5", SNAP62_ID, m2.axis5_dead_zone_table(snap62), ("dead_zone_symbols",))
    diag += _diag_rows("Axis5", SNAP510_ID, m2.axis5_dead_zone_table(snap510), ("dead_zone_symbols",))
    diag += _diag_rows("Axis5", "hist_dev_24_dates", m2.axis5_dead_zone_table(hist_dev), ("dead_zone_symbols",))
    axis6_hist = m2.axis6_breakout_partition(hist_dev, with_returns=True)
    diag += _diag_rows("Axis6", SNAP62_ID, m2.axis6_breakout_partition(snap62))
    diag += _diag_rows("Axis6", SNAP510_ID, m2.axis6_breakout_partition(snap510))
    diag += _diag_rows("Axis6", "hist_dev_24_dates", axis6_hist)
    axis7_hist = m2.axis7_attention_table(hist_dev, with_returns=True)
    diag += _diag_rows("Axis7", SNAP62_ID, m2.axis7_attention_table(snap62))
    diag += _diag_rows("Axis7", SNAP510_ID, m2.axis7_attention_table(snap510))
    diag += _diag_rows("Axis7", "hist_dev_24_dates", axis7_hist)
    axis8_hist = m2.axis8_trend_alignment_table(hist_dev)
    diag += _diag_rows("Axis8", SNAP62_ID, m2.axis8_trend_alignment_table(snap62))
    diag += _diag_rows("Axis8", SNAP510_ID, m2.axis8_trend_alignment_table(snap510))
    diag += _diag_rows("Axis8", "hist_dev_24_dates", axis8_hist)

    print("M2: resolving case registry ...", flush=True)
    resolved = m2.resolve_case_registry(frames)
    n_matched = sum(1 for r in resolved if r["status"] == "MATCHED")
    print(f"M2: resolved {n_matched}/{len(resolved)}", flush=True)

    dataset_ids = {"snap62": SNAP62_ID, "snap510": SNAP510_ID, "hist_dev": HISTORICAL_ID}
    casebook_rows: list[dict] = []
    for entry in resolved:
        match = entry["match"] or {}
        if match:
            texts = _case_texts(entry)
        else:
            texts = {
            "observed_v1_behavior": "UNMATCHED stratum; no row satisfied the predicate.",
            "counterfactual_m3_behavior": "DIAGNOSTIC_INCONCLUSIVE for this stratum.",
            "data_verdict": "DIAGNOSTIC_INCONCLUSIVE",
            "reviewer_notes": "",
        }
        dataset_key = match.get("dataset_key", "") if match else ""
        casebook_rows.append({
            "study_case_id": entry["study_case_id"],
            "case_selection_method": f"STRATIFIED:{entry['predicate']}",
            "evidence_tier": entry["evidence_tier"],
            "signal_date": match.get("signal_date", ""),
            "symbol": match.get("symbol", ""),
            "snapshot_or_dataset_id": dataset_ids.get(dataset_key, ""),
            "quality_grade": match.get("quality_grade", ""),
            "quality_score": _fmt(match.get("quality_score")),
            "confidence": _fmt(match.get("quality_confidence")),
            "entry_state": match.get("entry_state", ""),
            "entry_score": _fmt(match.get("entry_score")),
            "action_state": match.get("action_state", ""),
            "priority": match.get("priority", ""),
            "selected_top15": "TRUE" if match.get("selected_top15") is True else ("FALSE" if match else ""),
            "primary_failure_axis": entry["primary_axis"],
            "metric_defect_tags": entry["metric_defect_tags"],
            "observed_v1_behavior": texts["observed_v1_behavior"],
            "counterfactual_m3_behavior": texts["counterfactual_m3_behavior"],
            "data_verdict": texts["data_verdict"],
            "reviewer_notes": texts["reviewer_notes"],
        })

    inputs = {
        "decisions_snap510_jsonl": {"sha256": _sha256_file(REPO_ROOT / SNAP510_JSONL), "n_decisions": len(snap510)},
        "decisions_snap62_jsonl": {"sha256": _sha256_file(REPO_ROOT / SNAP62_JSONL), "n_decisions": len(snap62)},
        "company_quality_dataset_risk_off_v3_csv": {"sha256": _sha256_file(REPO_ROOT / QUALITY_CSV), "n_rows": len(hist)},
        "entry_quality_dataset_risk_off_v3_csv": {"sha256": _sha256_file(REPO_ROOT / ENTRY_CSV), "n_rows": 25025},
    }
    registry = {
        "study": "m2_v1_failure_attribution",
        "frozen": True,
        "n_cases": len(resolved),
        "n_matched": n_matched,
        "return_embargo": "Forward-return diagnostics use ONLY the 24 development dates "
                           "2023-01-31..2024-12-31; 2025/2026Q1 labels unpeeked for M4.",
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

    import io
    casebook_buf = io.StringIO()
    writer = csv.DictWriter(casebook_buf, fieldnames=list(CASEBOOK_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in casebook_rows:
        writer.writerow(row)
    files["v1_failure_casebook.csv"] = casebook_buf.getvalue()

    diag_buf = io.StringIO()
    diag_writer = csv.DictWriter(
        diag_buf, fieldnames=["axis", "scope", "stat", "value", "detail"], lineterminator="\n"
    )
    diag_writer.writeheader()
    for row in diag:
        diag_writer.writerow(row)
    files["metric_and_routing_diagnostics.csv"] = diag_buf.getvalue()

    files["attention_failure_attribution.md"] = render_attribution(
        snap62, snap510, hist, hist_dev, axis1_hist, axis2_hist, axis3_hist,
        axis6_hist, axis7_hist, axis8_hist, n_matched, len(resolved),
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
    print(f"M2: wrote {len(files) + 1} files, {total} bytes to {OUT_DIR_NAME}")
    if total >= MAX_DIR_BYTES:
        raise ValueError(f"deliverable directory exceeds {MAX_DIR_BYTES} bytes")
    print("M2: done.")
    return 0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _stat(diag_rows: list[dict], axis: str, scope: str, stat: str) -> str:
    for row in diag_rows:
        if row["axis"] == axis and row["scope"] == scope and row["stat"] == stat:
            return row["value"]
    return "n/a"


def render_attribution(
    snap62: pd.DataFrame, snap510: pd.DataFrame,
    hist: pd.DataFrame, hist_dev: pd.DataFrame,
    axis1_hist: dict, axis2_hist: dict, axis3_hist: dict,
    axis6_hist: dict, axis7_hist: dict, axis8_hist: dict,
    n_matched: int, n_cases: int,
) -> str:
    """Render the human-readable attribution report from computed tables."""
    lines = [
        "# M2 v1 Failure Attribution Report (frozen 2026-10-15)",
        "",
        "Offline read-only audit of frozen v1 decisions across snap62 (62 symbols,",
        "2026-10-12), snap510 (510 symbols, 2026-10-09), and 25,025 historical v3 rows",
        "(39 dates, 2023-01-31..2026-03-31). Return diagnostics use ONLY the 24",
        "development dates 2023-01-31..2024-12-31 (RETROSPECTIVE_EXPLORATORY);",
        "2025/2026Q1 forward labels remain unpeeked for M4.",
        f"Case registry: {n_matched}/{n_cases} strata matched.",
        "",
        "## 1. Executive Summary and Causal Breakdown",
        "",
        f"- Axis 1 accrual sign bug: {axis1_hist['n_false_positive_m10']} dev-row "
        f"cash-cow false positives at accrual<-0.10 ({axis1_hist['n_false_positive_m20']} at <-0.20); "
        f"accrual-only fix upgrades {axis1_hist['n_upgrades_b_to_a']} B->A and "
        f"{axis1_hist['n_upgrades_c_to_b']} C->B on dev dates.",
        f"- Axis 2 working-capital penalty: {axis2_hist['n_penalized']} of "
        f"{axis2_hist['n_high_growth_healthy']} high-growth healthy dev rows penalized; "
        f"{axis2_hist['n_reach_a_grade']} penalized B rows reach grade A under the combined fix.",
        f"- Axis 3 binary FCF: {axis3_hist['n_fcf_margin_thin_lt_3pct']} of "
        f"{axis3_hist['n_fcf_margin_observed']} FCF-positive dev rows run sub-3% margins yet score 1.0; "
        f"{axis3_hist['n_priority_review_valuation_flagged']} of {axis3_hist['n_priority_review']} "
        "PRIORITY_REVIEW rows carry ps/pe percentile weak flags.",
        f"- Axis 5 dead zone: {m2.axis5_dead_zone_table(hist_dev)['n_dead_zone_pullback']} dev dead-zone "
        "pullbacks hide in WATCH_BREAKOUT (snap62 CRM archetype).",
        f"- Axis 6 breakout split (dev): MILD={axis6_hist['buckets']['MILD_EXTENDED_PULLBACK']['n']}, "
        f"NEAR={axis6_hist['buckets']['NEAR_BREAKOUT_CONSOLIDATION']['n']}, "
        f"WEAK={axis6_hist['buckets']['WEAK_OR_LAGGING_STRUCTURE']['n']}, "
        f"UNOBS={axis6_hist['buckets']['UNOBSERVABLE_FEATURES']['n']}.",
        f"- Axis 7 attention: {axis7_hist['n_dates_truncated']} of {axis7_hist['n_dates']} dev dates "
        f"truncate A+READY ({axis7_hist['n_truncated_a_ready_obs']} obs); "
        f"{axis7_hist['n_b_ready_high_obs']} high-score B+READY obs suppressed to HOLD_MONITOR.",
        f"- Axis 8 MA alignment: on dev dates, {axis8_hist['ENTRY_READY']['n_inverted']}/"
        f"{axis8_hist['ENTRY_READY']['n_observable']} ({_pct(axis8_hist['ENTRY_READY']['inverted_share_of_observable'])}) "
        f"ENTRY_READY rows and {axis8_hist['WATCH_BREAKOUT']['n_inverted']}/"
        f"{axis8_hist['WATCH_BREAKOUT']['n_observable']} ({_pct(axis8_hist['WATCH_BREAKOUT']['inverted_share_of_observable'])}) "
        "WATCH_BREAKOUT rows have inverted moving averages (SMA50 < SMA200).",
        "",
        "## 2. Fundamental Metric Audit",
        "",
        "### 2.1 accrual_ratio sign inversion (Axis 1)",
        "v1 scores abs(accrual): OCF>NI cash generation reads as weak when accrual<-0.10.",
        f"Dev false-positive rate: {_pct(axis1_hist['false_positive_rate_m10'])} at -0.10, "
        f"{_pct(axis1_hist['false_positive_rate_m20'])} at -0.20.",
        "### 2.2 High-growth working-capital penalty (Axis 2)",
        f"Penalized share of high-growth healthy rows: {_pct(axis2_hist['penalized_rate'])}.",
        "### 2.3 Binary FCF and valuation drag (Axis 3)",
        f"FCF margin median among FCF-positive rows: {axis3_hist['fcf_margin_median']}; "
        f"thin-margin count: {axis3_hist['n_fcf_margin_thin_lt_3pct']}; "
        f"strong-margin count: {axis3_hist['n_fcf_margin_strong_ge_15pct']}.",
        "### 2.4 Missing margin pillars (Axis 4)",
        f"operating_margin computable on {_pct(m2.axis4_margin_coverage(hist_dev)['operating_margin_coverage'])} "
        f"of dev rows and {_pct(m2.axis4_margin_coverage(hist)['operating_margin_coverage'])} of all rows "
        "from existing facts with zero new fetches. Snapshot decisions.jsonl serializes only "
        "emitted evidence (no revenue/ebit values), so coverage is proven on historical rows, "
        "whose facts are the same SEC source.",
        "",
        "## 3. Entry and Price-Volume Metric Audit",
        "",
        "Dead-zone (1.08,1.10]/(12%,15%] rows are WATCH_BREAKOUT, not WATCH_PULLBACK;",
        "the 3-way split separates MILD pullbacks from NEAR consolidations and WEAK laggards.",
        "MILD rows occur across all 24 dev dates (411 obs, 9.2% of BREAKOUT),",
        "so the seam is structural, not a single-date artifact.",
        "Snapshot caveat: pre-M1 snapshots serialize only emitted evidence, so 10/16 snap62",
        "and 90/141 snap510 BREAKOUT rows are UNOBSERVABLE for bucketing (silent-band gates);",
        "CAT/LIN fall in this unobservable set, not the confirmed-weak set.",
        "sma50_to_sma200 is exactly price_to_sma200/price_to_sma50 on every row (Axis 8).",
        "",
        "## 4. Action Routing and Top-15 Compression Audit",
        "",
        f"{axis7_hist['n_dates_truncated']} dev dates truncate eligible A+READY names while "
        f"{axis7_hist['n_b_ready_high_obs']} high-score B+READY rows sit in HOLD_MONITOR behind "
        "A+WATCH_BREAKOUT names. Date-equal 60d net-QQQ comparisons are exploratory only.",
        "",
        "_End of M2 attribution. All counts reproducible from metric_and_routing_diagnostics.csv._",
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
