#!/usr/bin/env python3
"""Run Phase M3 non-return preflight & frozen casebook verification.

Offline and read-only over frozen artifacts: the two decisions.jsonl
snapshots, the repaired historical v3 CSVs (24 dev dates only for returns;
all counts on dev dates + snapshots), and the M2 38-case registry.

Evaluates v1_baseline, h1_quality_only, h2_entry_only, h3_action_only and
v2_combined, then writes 5 deliverables + SHA256SUMS under
docs/m3_candidate_preflight_20261015/ (<120 KB, no absolute paths).
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

from ai_value_scanner.decision.entry import ENTRY_POLICY_VERSION, ENTRY_V2_POLICY_VERSION
from ai_value_scanner.decision.integrated import build_stock_decisions
from ai_value_scanner.decision.quality import QUALITY_POLICY_VERSION, QUALITY_V2_POLICY_VERSION
from ai_value_scanner.research import m3_candidate_preflight as m3
from ai_value_scanner.research import m2_failure_attribution as m2

OUT_DIR_NAME = "docs/m3_candidate_preflight_20261015"
MAX_DIR_BYTES = 120 * 1024

SNAP510_JSONL = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/decisions.jsonl"
SNAP510_MANIFEST = "evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/run_manifest.json"
SNAP62_JSONL = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/decisions.jsonl"
SNAP62_MANIFEST = "outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/run_manifest.json"
QUALITY_CSV = "outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv"
M2_REGISTRY = "docs/m2_v1_failure_attribution_20261015/case_registry_frozen.json"

SNAP510_ID = "snap510_2026-10-09_313c5ff"
SNAP62_ID = "snap62_2026-10-12_220a471"
HIST_SCOPE = "hist_dev_24_dates"
SAMPLE_DEV_DATES = ("2023-01-31", "2024-06-28", "2024-12-31")

COMPARISON_COLUMNS = (
    "scope", "variant",
    "n_quality_a", "n_quality_b", "n_quality_c", "n_unrated",
    "n_entry_ready", "n_watch_pullback", "n_watch_breakout", "n_trend_damaged",
    "n_priority_review", "n_watch_pullback_action", "n_watch_breakout_action",
    "n_hold_monitor", "n_avoid",
    "n_cash_cow_accrual_weak", "n_high_growth_wc_penalized_b",
    "n_dead_zone_in_watch_breakout", "n_inverted_ma_in_entry_ready",
    "mean_top15_jaccard_vs_v1",
    "excess_top15", "excess_priority_review", "excess_quality_a", "excess_entry_ready",
)

CASEBOOK_COLUMNS = (
    "study_case_id", "symbol", "signal_date", "scope", "evidence_tier",
    "v1_outcome", "v2_outcome", "failure_resolved", "resolution_detail",
)

DIFF_COLUMNS = (
    "scope", "symbol", "v1_priority", "v2_priority", "v1_action",
    "v2_action", "direction", "reason",
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


def _comparison_row(scope: str, variant: str, summary: dict, defects: dict,
                    jaccard: object, excess: dict) -> dict:
    def _excess(group: str) -> str:
        info = excess.get(group, {})
        return "" if not info else str(info.get("mean_excess", ""))
    return {
        "scope": scope, "variant": variant,
        "n_quality_a": summary["grades"].get("A", 0),
        "n_quality_b": summary["grades"].get("B", 0),
        "n_quality_c": summary["grades"].get("C", 0),
        "n_unrated": summary["grades"].get("UNRATED", 0),
        "n_entry_ready": summary["entries"].get("ENTRY_READY", 0),
        "n_watch_pullback": summary["entries"].get("WATCH_PULLBACK", 0),
        "n_watch_breakout": summary["entries"].get("WATCH_BREAKOUT", 0),
        "n_trend_damaged": summary["entries"].get("TREND_DAMAGED", 0),
        "n_priority_review": summary["actions"].get("PRIORITY_REVIEW", 0),
        "n_watch_pullback_action": summary["actions"].get("WATCH_PULLBACK", 0),
        "n_watch_breakout_action": summary["actions"].get("WATCH_BREAKOUT", 0),
        "n_hold_monitor": summary["actions"].get("HOLD_MONITOR", 0),
        "n_avoid": summary["actions"].get("AVOID", 0),
        "n_cash_cow_accrual_weak": defects["n_cash_cow_accrual_weak"],
        "n_high_growth_wc_penalized_b": defects["n_high_growth_wc_penalized_b"],
        "n_dead_zone_in_watch_breakout": defects["n_dead_zone_in_watch_breakout"],
        "n_inverted_ma_in_entry_ready": defects["n_inverted_ma_in_entry_ready"],
        "mean_top15_jaccard_vs_v1": "" if jaccard is None else jaccard,
        "excess_top15": _excess("TOP15"),
        "excess_priority_review": _excess("PRIORITY_REVIEW"),
        "excess_quality_a": _excess("QUALITY_A"),
        "excess_entry_ready": _excess("ENTRY_READY"),
    }


def _fields(decision) -> tuple[str, str, str, object]:
    """(grade, entry_state, action_state, priority) for dict or object decisions."""
    if decision is None:
        return "", "", "", ""
    if isinstance(decision, dict):
        return (
            str((decision.get("quality", {}) or {}).get("grade", "")),
            str((decision.get("entry", {}) or {}).get("state", "")),
            str(decision.get("action_state", "")),
            decision.get("priority", ""),
        )
    return (
        decision.quality.grade.value,
        decision.entry.state.value,
        decision.action_state.value,
        decision.priority,
    )


def _diff_reason(v1, v2) -> str:
    if v1 is None or v2 is None:
        return "unavailable under one variant (partial snapshot features)"
    g1, e1, a1, p1 = _fields(v1)
    g2, e2, a2, p2 = _fields(v2)
    if a1 != a2:
        if a2 == "PRIORITY_REVIEW" and g1 == "B":
            return "H3 B+READY promotion to PRIORITY_REVIEW"
        return f"action {a1}->{a2}"
    if g1 != g2:
        return f"H1 quality {g1}->{g2}"
    if e1 != e2:
        return f"H2 entry {e1}->{e2}"
    if p1 != p2:
        return "joint-score/priority reorder"
    return "unchanged"


def main() -> int:
    out_dir = REPO_ROOT / OUT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    print("M3: loading frozen inputs ...", flush=True)
    decisions510 = [json.loads(line) for line in (REPO_ROOT / SNAP510_JSONL).read_text().splitlines() if line.strip()]
    decisions62 = [json.loads(line) for line in (REPO_ROOT / SNAP62_JSONL).read_text().splitlines() if line.strip()]
    manifest510 = json.loads((REPO_ROOT / SNAP510_MANIFEST).read_text())
    manifest62 = json.loads((REPO_ROOT / SNAP62_MANIFEST).read_text())
    registry = json.loads((REPO_ROOT / M2_REGISTRY).read_text())
    hist = pd.read_csv(REPO_ROOT / QUALITY_CSV, low_memory=False)
    hist_dev = m2.development_frame(hist)
    assert len(hist) == 25025 and hist["signal_date"].nunique() == 39

    rebuild510 = m3.snapshot_rebuild_frame(decisions510)
    rebuild62 = m3.snapshot_rebuild_frame(decisions62)

    comparison_rows: list[dict] = []
    diff_rows: list[dict] = []
    top15_by_scope_variant: dict[tuple[str, str], list] = {}
    # variant decisions kept for casebook verification + diffs
    snap_variant_decisions: dict[str, dict[str, tuple]] = {}
    snap_v1_rebuild: dict[str, dict] = {}
    snap_surgical_h3: dict[str, dict] = {}
    hist_variant_by_date: dict[str, dict[str, tuple]] = {}
    fidelity: dict[str, float] = {}

    print("M3: snapshot scopes ...", flush=True)
    for scope, decisions, manifest, rebuild_frame in (
        ("snap510", decisions510, manifest510, rebuild510),
        ("snap62", decisions62, manifest62, rebuild62),
    ):
        manifest_top15 = [str(s).strip().upper() for s in manifest.get("daily_symbols", [])]
        frozen_summary = _frozen_summary(decisions, manifest_top15)
        for variant in m3.VARIANTS:
            if variant == "v1_baseline":
                summary = frozen_summary["summary"]
                defects = frozen_summary["defects"]
                top15 = frozen_summary["top15"]
                variant_decisions = None
            else:
                rebuilt = m3.rebuild_snapshot_variant(
                    rebuild_frame, decision_date=rebuild_frame["signal_date"].iloc[0],
                    generated_at_utc="2026-10-15T00:00:00+00:00", variant=variant,
                )
                summary = m3.summarize_decisions(rebuilt)
                defects = m3.defect_counts_for_scope(rebuilt, rebuild_frame)
                top15 = summary["top15"]
                variant_decisions = {d.symbol: d for d in rebuilt}
            snap_variant_decisions.setdefault(scope, {})[variant] = variant_decisions
            top15_by_scope_variant[(scope, variant)] = top15
            jaccard = m3.top15_jaccard(top15, frozen_summary["top15"]) if variant != "v1_baseline" else 1.0
            comparison_rows.append(_comparison_row(
                scope, variant, summary, defects, jaccard, {}))
        snap_variant_decisions[scope]["v1_baseline_frozen"] = {
            str(d.get("symbol", "") or "").strip().upper(): d for d in decisions
        }
        # fidelity: v1 rebuild vs frozen manifest top15
        rebuilt_v1 = m3.rebuild_snapshot_variant(
            rebuild_frame, decision_date=rebuild_frame["signal_date"].iloc[0],
            generated_at_utc="2026-10-15T00:00:00+00:00", variant="v1_baseline")
        snap_v1_rebuild[scope] = {d.symbol: d for d in rebuilt_v1}
        fidelity[scope] = m3.top15_jaccard(
            m3.summarize_decisions(rebuilt_v1)["top15"], frozen_summary["top15"])
        print(f"M3: {scope} v1-rebuild top15 fidelity vs frozen: {fidelity[scope]}", flush=True)
        snap_surgical_h3[scope] = m3.surgical_h3_decisions(decisions)

    print("M3: hist_dev scopes (24 dates x 5 variants) ...", flush=True)
    from dataclasses import replace
    from ai_value_scanner.decision.action import (
        assign_action_priorities_v2,
        map_action_state,
        map_action_state_v2,
    )
    from ai_value_scanner.decision.integrated import _priority_sort_key

    def _assign_priorities_v1(items: list) -> list:
        ordered = sorted(items, key=_priority_sort_key)
        return [replace(d, priority=idx) for idx, d in enumerate(ordered, start=1)]

    for date, group in hist_dev.groupby("signal_date", sort=True):
        date_str = str(date)
        ts = f"{date_str}T23:59:59+00:00"
        decs_v1 = build_stock_decisions(
            group, decision_date=date_str, generated_at_utc=ts, policy_version="v1"
        )
        decs_v2 = build_stock_decisions(
            group, decision_date=date_str, generated_at_utc=ts, policy_version="v2"
        )
        by_sym_v1 = {d.symbol: d for d in decs_v1}
        by_sym_v2 = {d.symbol: d for d in decs_v2}
        hist_variant_by_date.setdefault("v1_baseline", {})[date_str] = tuple(decs_v1)
        hist_variant_by_date.setdefault("v2_combined", {})[date_str] = tuple(decs_v2)
        for variant in ("h1_quality_only", "h2_entry_only", "h3_action_only"):
            stages = m3.VARIANT_STAGES[variant]
            combined = []
            for sym, d1 in by_sym_v1.items():
                d2 = by_sym_v2[sym]
                q_obj = d2.quality if stages["quality_version"] == "v2" else d1.quality
                e_obj = d2.entry if stages["entry_version"] == "v2" else d1.entry
                if stages["action_version"] == "v2":
                    act_state, _ = map_action_state_v2(q_obj, e_obj)
                else:
                    act_state = map_action_state(q_obj.grade, e_obj.state)
                combined.append(
                    replace(d1, quality=q_obj, entry=e_obj, action_state=act_state)
                )
            ranked = (
                assign_action_priorities_v2(combined)
                if stages["action_version"] == "v2"
                else _assign_priorities_v1(combined)
            )
            hist_variant_by_date.setdefault(variant, {})[date_str] = tuple(ranked)
    # aggregate hist_dev comparison rows + jaccard + dev returns
    v1_top15_by_date = {
        date: m3.summarize_decisions(decs)["top15"]
        for date, decs in hist_variant_by_date["v1_baseline"].items()
    }
    for variant in m3.VARIANTS:
        all_decs = [d for by_date in hist_variant_by_date[variant].values() for d in by_date]
        summary = m3.summarize_decisions(all_decs)
        defects = m3.defect_counts_for_scope(all_decs, hist_dev)
        variant_top15 = {
            date: m3.summarize_decisions(decs)["top15"]
            for date, decs in hist_variant_by_date[variant].items()
        }
        jaccard = m3.mean_top15_jaccard_vs_v1(variant_top15, v1_top15_by_date) \
            if variant != "v1_baseline" else 1.0
        excess = m3.dev_excess_for_groups(hist_dev, all_decs)
        comparison_rows.append(_comparison_row(
            HIST_SCOPE, variant, summary, defects, jaccard, excess))

    print("M3: top15 diffs ...", flush=True)
    for scope in ("snap62", "snap510"):
        v1_top15 = top15_by_scope_variant[(scope, "v1_baseline")]
        v2_top15 = top15_by_scope_variant[(scope, "v2_combined")]
        v1_by_symbol = _v1_lookup(scope, decisions62, decisions510, hist_variant_by_date)
        v2_by_symbol = snap_variant_decisions[scope]["v2_combined"] or {}
        for symbol in sorted(set(v1_top15) | set(v2_top15)):
            in_v1, in_v2 = symbol in v1_top15, symbol in v2_top15
            if in_v1 and in_v2:
                continue
            v1d = v1_by_symbol.get(symbol)
            v2d = v2_by_symbol.get(symbol)
            _, _, v1a, v1p = _fields(v1d)
            _, _, v2a, v2p = _fields(v2d)
            diff_rows.append({
                "scope": scope, "symbol": symbol,
                "v1_priority": v1p if v1p != "" else (v1_top15.index(symbol) + 1 if in_v1 else ""),
                "v2_priority": v2p if v2p != "" else (v2_top15.index(symbol) + 1 if in_v2 else ""),
                "v1_action": v1a, "v2_action": v2a,
                "direction": "EXIT" if in_v1 and not in_v2 else "ENTER",
                "reason": _diff_reason(v1d, v2d),
            })
    for date in SAMPLE_DEV_DATES:
        v1_decs = {d.symbol: d for d in hist_variant_by_date["v1_baseline"][date]}
        v2_decs = {d.symbol: d for d in hist_variant_by_date["v2_combined"][date]}
        v1_top15 = m3.summarize_decisions(v1_decs.values())["top15"]
        v2_top15 = m3.summarize_decisions(v2_decs.values())["top15"]
        for symbol in sorted(set(v1_top15) | set(v2_top15)):
            if (symbol in v1_top15) == (symbol in v2_top15):
                continue
            v1d, v2d = v1_decs.get(symbol), v2_decs.get(symbol)
            diff_rows.append({
                "scope": f"hist_dev_{date}", "symbol": symbol,
                "v1_priority": v1d.priority if v1d else "",
                "v2_priority": v2d.priority if v2d else "",
                "v1_action": v1d.action_state.value if v1d else "",
                "v2_action": v2d.action_state.value if v2d else "",
                "direction": "EXIT" if symbol in v1_top15 else "ENTER",
                "reason": _diff_reason(v1d, v2d),
            })

    print("M3: casebook verification (38 cases) ...", flush=True)
    casebook_rows: list[dict] = []
    for case in registry["cases"]:
        scope = _scope_of_case(case)
        symbol = case.get("symbol", "")
        axis = str(case.get("primary_axis", ""))
        v1_display = _case_v1_lookup(case, scope, decisions62, decisions510, hist_variant_by_date)
        if scope in ("snap62", "snap510"):
            v1_policy = snap_v1_rebuild.get(scope, {}).get(symbol)
            v2d = _case_v2_lookup(case, scope, snap_variant_decisions, hist_variant_by_date)
            surgical_note = ""
            if axis == "Axis7":
                surgical = snap_surgical_h3.get(scope, {}).get(symbol)
                if surgical is not None:
                    v2d = surgical
                    surgical_note = " [surgical H3 on frozen decisions (exact); full v2_combined rebuild differs on partial features]"
        else:
            v1_policy = v1_display
            v2d = _case_v2_lookup(case, scope, snap_variant_decisions, hist_variant_by_date)
            surgical_note = ""
        day = _case_day_v2(case, scope, snap_variant_decisions, hist_variant_by_date)
        pair_v2 = _pair_v2_lookup(case, registry["cases"], scope, snap_variant_decisions, hist_variant_by_date)
        verdict = m3.verify_case(case, v1_display, v1_policy, v2d, day, pair_v2)
        if surgical_note:
            verdict["resolution_detail"] = verdict["resolution_detail"] + surgical_note
        if scope in ("snap62", "snap510"):
            verdict["resolution_detail"] = (
                verdict["resolution_detail"]
                + f" [same-info v1-rebuild comparator: {m3.outcome_string(v1_policy)}]"
            )
        casebook_rows.append({
            "study_case_id": case.get("study_case_id", ""),
            "symbol": symbol,
            "signal_date": case.get("signal_date", ""),
            "scope": scope,
            "evidence_tier": case.get("evidence_tier", ""),
            **verdict,
        })

    files: dict[str, str] = {}
    files["m3_preregistration_protocol.json"] = json.dumps({
        "study": "m3_candidate_preflight",
        "frozen": True,
        "variants": {
            name: {**m3.VARIANT_STAGES[name],
                   "quality_policy": QUALITY_V2_POLICY_VERSION if m3.VARIANT_STAGES[name]["quality_version"] == "v2" else QUALITY_POLICY_VERSION,
                   "entry_policy": ENTRY_V2_POLICY_VERSION if m3.VARIANT_STAGES[name]["entry_version"] == "v2" else ENTRY_POLICY_VERSION,
                   "falsifier": m3.VARIANT_FALSIFIERS.get(name, "v1 reference; no change expected.")}
            for name in m3.VARIANTS
        },
        "return_embargo": m3.RETURN_EMBARGO_TEXT,
        "inputs": {
            "decisions_snap510_jsonl": _sha256_file(REPO_ROOT / SNAP510_JSONL),
            "decisions_snap62_jsonl": _sha256_file(REPO_ROOT / SNAP62_JSONL),
            "company_quality_dataset_risk_off_v3_csv": _sha256_file(REPO_ROOT / QUALITY_CSV),
            "m2_case_registry_frozen_json": _sha256_file(REPO_ROOT / M2_REGISTRY),
        },
    }, indent=2, sort_keys=True) + "\n"

    comp_buf = io.StringIO()
    writer = csv.DictWriter(comp_buf, fieldnames=list(COMPARISON_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in comparison_rows:
        writer.writerow(row)
    files["m3_preflight_comparison.csv"] = comp_buf.getvalue()

    case_buf = io.StringIO()
    case_writer = csv.DictWriter(case_buf, fieldnames=list(CASEBOOK_COLUMNS), lineterminator="\n")
    case_writer.writeheader()
    for row in casebook_rows:
        case_writer.writerow(row)
    files["m3_casebook_verification.csv"] = case_buf.getvalue()

    diff_buf = io.StringIO()
    diff_writer = csv.DictWriter(diff_buf, fieldnames=list(DIFF_COLUMNS), lineterminator="\n")
    diff_writer.writeheader()
    for row in sorted(diff_rows, key=lambda r: (r["scope"], r["direction"], r["symbol"])):
        diff_writer.writerow(row)
    files["m3_top15_diff_snap62_and_snap510.csv"] = diff_buf.getvalue()

    files["m3_preflight_report.md"] = render_report(comparison_rows, casebook_rows, diff_rows, fidelity)

    for name, content in files.items():
        if m2.contains_absolute_path(content):
            raise ValueError(f"absolute path leaked into {name}")
        (out_dir / name).write_text(content)
    checksums = "".join(
        f"{hashlib.sha256(files[name].encode()).hexdigest()}  {name}\n"
        for name in sorted(files)
    )
    (out_dir / "SHA256SUMS").write_text(checksums)
    total = sum(p.stat().st_size for p in out_dir.iterdir())
    print(f"M3: wrote {len(files) + 1} files, {total} bytes to {OUT_DIR_NAME}")
    if total >= MAX_DIR_BYTES:
        raise ValueError(f"deliverable directory exceeds {MAX_DIR_BYTES} bytes")
    print("M3: done.")
    return 0


def _frozen_summary(decisions: list, manifest_top15: list) -> dict:
    """v1_baseline counts straight from frozen decisions.jsonl."""
    top15 = [str(s).strip().upper() for s in manifest_top15]
    grades = {"A": 0, "B": 0, "C": 0, "UNRATED": 0}
    entries = {"ENTRY_READY": 0, "WATCH_PULLBACK": 0, "WATCH_BREAKOUT": 0,
               "TREND_DAMAGED": 0, "INSUFFICIENT_DATA": 0}
    actions = {"PRIORITY_REVIEW": 0, "WATCH_PULLBACK": 0, "WATCH_BREAKOUT": 0,
               "HOLD_MONITOR": 0, "AVOID": 0}
    for decision in decisions:
        grades[decision["quality"]["grade"]] = grades.get(decision["quality"]["grade"], 0) + 1
        entries[decision["entry"]["state"]] = entries.get(decision["entry"]["state"], 0) + 1
        actions[decision["action_state"]] = actions.get(decision["action_state"], 0) + 1
    frame = m2.snapshot_frame(decisions, manifest_top15,
                              "frozen") if decisions else pd.DataFrame()
    defects = {
        "n_cash_cow_accrual_weak": 0, "n_high_growth_wc_penalized_b": 0,
        "n_dead_zone_in_watch_breakout": 0, "n_inverted_ma_in_entry_ready": 0,
    }
    if not frame.empty:
        for _, row in frame.iterrows():
            record = row.to_dict()
            accrual = m2.finite_or_none(record.get("accrual_ratio"))
            ocf = m2.finite_or_none(record.get("ocf_to_net_income"))
            fcf = m2.finite_or_none(record.get("free_cash_flow"))
            if "accrual_ratio_weak" in str(record.get("quality_risks_codes", "")).split(",") \
                    and accrual is not None and accrual < -0.10 and ocf is not None \
                    and ocf >= 1.0 and fcf is not None and fcf > 0.0:
                defects["n_cash_cow_accrual_weak"] += 1
            revenue_yoy = m2.finite_or_none(record.get("revenue_yoy"))
            if record.get("quality_grade") == "B" and revenue_yoy is not None and revenue_yoy >= 0.25 \
                    and ocf is not None and ocf >= 0.80 and (
                        "receivables_growth_gap_weak" in str(record.get("quality_risks_codes", "")).split(",")
                        or "inventory_growth_gap_weak" in str(record.get("quality_risks_codes", "")).split(",")):
                defects["n_high_growth_wc_penalized_b"] += 1
    return {"summary": {"n": len(decisions), "grades": grades, "entries": entries,
                        "actions": actions, "top15": top15},
            "defects": defects, "top15": top15}


def _v1_lookup(scope: str, decisions62: list, decisions510: list, hist_by_date: dict):
    if scope == "snap62":
        return {str(d.get("symbol", "") or "").strip().upper(): d for d in decisions62}
    if scope == "snap510":
        return {str(d.get("symbol", "") or "").strip().upper(): d for d in decisions510}
    return {}


def _scope_of_case(case: dict) -> str:
    dataset_id = str(case.get("snapshot_or_dataset_id", ""))
    if "snap510" in dataset_id or "313c5ff" in dataset_id:
        return "snap510"
    if "snap62" in dataset_id or "220a471" in dataset_id:
        return "snap62"
    return "hist_dev"


def _case_v1_lookup(case: dict, scope: str, decisions62: list, decisions510: list, hist_by_date: dict):
    symbol = str(case.get("symbol", ""))
    if scope in ("snap62", "snap510"):
        pool = decisions62 if scope == "snap62" else decisions510
        for decision in pool:
            if str(decision.get("symbol", "") or "").strip().upper() == symbol:
                return decision
        return None
    for by_date in hist_by_date.get("v1_baseline", {}).values():
        for decision in by_date:
            if decision.symbol == symbol and decision.decision_date == case.get("signal_date", ""):
                return decision
    return None


def _case_v2_lookup(case: dict, scope: str, snap_variants: dict, hist_by_date: dict):
    symbol = str(case.get("symbol", ""))
    if scope in ("snap62", "snap510"):
        return (snap_variants.get(scope, {}).get("v2_combined") or {}).get(symbol)
    for by_date in hist_by_date.get("v2_combined", {}).values():
        for decision in by_date:
            if decision.symbol == symbol and decision.decision_date == case.get("signal_date", ""):
                return decision
    return None


def _case_day_v2(case: dict, scope: str, snap_variants: dict, hist_by_date: dict) -> list:
    if scope in ("snap62", "snap510"):
        by_symbol = snap_variants.get(scope, {}).get("v2_combined") or {}
        return list(by_symbol.values())
    return list(hist_by_date.get("v2_combined", {}).get(str(case.get("signal_date", "")), []))


def _pair_v2_lookup(case: dict, all_cases: list, scope: str, snap_variants: dict, hist_by_date: dict):
    if not str(case.get("study_case_id", "")).startswith("M2-R-"):
        return None
    partner_prefix = "M2-R-REJ" if "-SEL" in str(case.get("study_case_id", "")) else "M2-R-SEL"
    for other in all_cases:
        if str(other.get("study_case_id", "")).startswith(partner_prefix) \
                and other.get("signal_date", "") == case.get("signal_date", ""):
            partner_scope = _scope_of_case(other)
            if partner_scope == scope:
                return _case_v2_lookup(other, scope, snap_variants, hist_by_date)
    return None


def render_report(comparison_rows: list, casebook_rows: list, diff_rows: list, fidelity: dict) -> str:
    """Concise preflight report: gates, defect deltas, verification, M4 note."""
    def _row(scope: str, variant: str) -> dict:
        for row in comparison_rows:
            if row["scope"] == scope and row["variant"] == variant:
                return row
        return {}

    def _delta(scope: str, column: str) -> str:
        base = _row(scope, "v1_baseline").get(column, "")
        new = _row(scope, "v2_combined").get(column, "")
        try:
            return f"{base}->{new} (Δ{float(new) - float(base):+.0f})"
        except (TypeError, ValueError):
            return f"{base}->{new}"

    lines = [
        "# M3 Candidate Preflight Report (frozen 2026-10-15, non-return gates)",
        "",
        "Five pre-registered variants evaluated offline: v1_baseline, h1_quality_only,",
        "h2_entry_only, h3_action_only, v2_combined. Snapshot v1_baseline counts come from",
        "frozen decisions.jsonl; variants rebuild from emitted evidence maps (partial",
        "vectors). Rebuild fidelity (v1-rebuild Top-15 Jaccard vs frozen): "
        f"snap510={fidelity.get('snap510', 'n/a')}, snap62={fidelity.get('snap62', 'n/a')}.",
        "Snapshot policy verdicts compare v1-rebuild vs variant-rebuild (same information),",
        "and snapshot Axis7 cases use surgical H3 on frozen decisions (exact mapping+ranking,",
        "no rebuild degradation). Snapshot variant rows are dominated by partial-vector",
        "INSUFFICIENT states, so snapshot policy deltas are only interpretable rebuild-vs-rebuild;",
        "hist_dev carries the policy signal. Hist_dev uses full rows via wired builders.",
        "Return figures are 2023-2024 dev date-equal exploratory only.",
        "",
        "## 1. Variant-by-variant non-return gates",
        "",
    ]
    for scope in ("snap62", "snap510", "hist_dev_24_dates"):
        lines.append(f"### {scope}")
        for variant in ("v1_baseline", "h1_quality_only", "h2_entry_only", "h3_action_only", "v2_combined"):
            row = _row(scope, variant)
            lines.append(
                f"- {variant}: A/B/C/U={row.get('n_quality_a')}/{row.get('n_quality_b')}/"
                f"{row.get('n_quality_c')}/{row.get('n_unrated')}; "
                f"READY/PB/WB/TD={row.get('n_entry_ready')}/{row.get('n_watch_pullback')}/"
                f"{row.get('n_watch_breakout')}/{row.get('n_trend_damaged')}; "
                f"PR/HM/AV={row.get('n_priority_review')}/{row.get('n_hold_monitor')}/{row.get('n_avoid')}; "
                f"Jaccard-vs-v1={row.get('mean_top15_jaccard_vs_v1')}"
            )
    lines += [
        "",
        "## 2. Defect reduction (v1_baseline -> v2_combined)",
        "",
        f"- Axis 1 cash-cow accrual_weak: hist_dev {_delta('hist_dev_24_dates', 'n_cash_cow_accrual_weak')}; "
        f"snap62 {_delta('snap62', 'n_cash_cow_accrual_weak')}; snap510 {_delta('snap510', 'n_cash_cow_accrual_weak')}.",
        f"- Axis 2 penalized high-growth B: hist_dev {_delta('hist_dev_24_dates', 'n_high_growth_wc_penalized_b')}.",
        f"- Axis 5 dead-zone in BREAKOUT: hist_dev {_delta('hist_dev_24_dates', 'n_dead_zone_in_watch_breakout')}.",
        "  (Residual 32 = dead-zone-extension rows failing the extra core-uptrend",
        "  conditions: days_below>3, MA alignment <0.98, or defensive gate.)",
        f"- Axis 8 inverted MA in READY: hist_dev {_delta('hist_dev_24_dates', 'n_inverted_ma_in_entry_ready')}.",
        "",
        "## 3. Frozen casebook verification (38 M2 cases)",
        "",
    ]
    resolved = sum(1 for r in casebook_rows if r["failure_resolved"] == "TRUE")
    preserved = sum(1 for r in casebook_rows if r["failure_resolved"] == "CONTROL_PRESERVED")
    failed = sum(1 for r in casebook_rows if r["failure_resolved"] == "FALSE")
    lines.append(f"- TRUE={resolved}, CONTROL_PRESERVED={preserved}, FALSE={failed} (detail in m3_casebook_verification.csv).")
    for row in casebook_rows:
        if row["failure_resolved"] == "FALSE":
            lines.append(f"  - {row['study_case_id']} {row['symbol']}: v1={row['v1_outcome']} v2={row['v2_outcome']} ({row['resolution_detail']})")
    lines += [
        "",
        "## 4. Top-15 movement",
        "",
        f"- {len(diff_rows)} membership changes recorded in m3_top15_diff_snap62_and_snap510.csv "
        "(snap62, snap510, 2023-01-31, 2024-06-28, 2024-12-31).",
        "",
        "## 5. M4 readiness recommendation",
        "",
        "- If gates pass (defects fall, controls preserved, movement explainable): proceed to M4 formal",
        "  2025/2026Q1 held-out comparative validation with pre-registered utility + return metrics.",
        "- If any control breaks or defects do not fall: revise the candidate, do not relax the gate.",
        "",
        "_End of M3 preflight. No forward-return optimization was performed._",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
