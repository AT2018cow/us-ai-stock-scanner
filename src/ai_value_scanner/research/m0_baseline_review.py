"""M0 read-only baseline inventory, human-attention review worksheet, and M1 gate.

Strictly read-only diagnostic module for Phase M0 of the post-PR #70 roadmap
(`docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md`).
It consumes already-frozen decision snapshots and audit artifacts without
making network requests, computing forward returns, or altering v1 policy.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


WORKSHEET_COLUMNS: tuple[str, ...] = (
    "study_case_id",
    "stratum",
    "snapshot_id",
    "signal_date",
    "symbol",
    "priority_rank",
    "in_top15_shortlist",
    "action_state",
    "quality_grade",
    "quality_score",
    "quality_confidence",
    "fundamental_data_asof",
    "entry_state",
    "entry_score",
    "market_asof",
    "cik_traceable",
    "positives_summary",
    "risks_summary",
    "missing_or_silent_gates",
    "trigger_clarity",
    "data_comparability_verdict",
    "primary_attribution_axis",
    "worth_human_review_yn_unknown",
    "reviewer_rationale",
)

ATTRIBUTION_AXES = frozenset({
    "NONE_ACTIONABLE_BASELINE",
    "DATA_OR_ACCOUNTING_SCOPE_ERROR",
    "EVIDENCE_PRESENTATION_GAP",
    "SELECTION_OR_RANKING_MECHANISM_GAP",
})


@dataclass(frozen=True)
class CaseSpec:
    study_case_id: str
    stratum: str
    snapshot_key: str  # "snap62" or "snap510"
    symbol: str
    data_comparability_verdict: str
    primary_attribution_axis: str
    worth_human_review_yn_unknown: str
    silent_or_scope_note: str
    reviewer_rationale: str


FROZEN_M0_CASE_SPECS: tuple[CaseSpec, ...] = (
    # Stratum A: Top-15 PRIORITY_REVIEW controls (62-stock 2026-10-12 MVP Beta)
    CaseSpec(
        study_case_id="M0-01",
        stratum="A_TOP15_PRIORITY_REVIEW",
        snapshot_key="snap62",
        symbol="ETN",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="NONE_ACTIONABLE_BASELINE",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="None (all 7 ENTRY_READY gates explicitly evidenced)",
        reviewer_rationale=(
            "Rank #1 PRIORITY_REVIEW control: Quality A (1.00) and ENTRY_READY (0.95) "
            "with complete positive/counter-evidence and explicit downgrade trigger."
        ),
    ),
    CaseSpec(
        study_case_id="M0-02",
        stratum="A_TOP15_PRIORITY_REVIEW",
        snapshot_key="snap62",
        symbol="KO",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="NONE_ACTIONABLE_BASELINE",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="None (valuation percentile 1.0 caution explicitly disclosed)",
        reviewer_rationale=(
            "Rank #2 PRIORITY_REVIEW control: high-visibility valuation caution "
            "(ps/pe percentile=1.0) is surfaced alongside strong operating cash conversion."
        ),
    ),
    CaseSpec(
        study_case_id="M0-03",
        stratum="A_TOP15_PRIORITY_REVIEW",
        snapshot_key="snap62",
        symbol="MSFT",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="NONE_ACTIONABLE_BASELINE",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="None (accrual and valuation cautions explicitly disclosed)",
        reviewer_rationale=(
            "Rank #5 PRIORITY_REVIEW control: actionable shortlist entry with "
            "balanced positive fundamentals, explicit accrual/P-S risks, and clear READY state."
        ),
    ),
    # Stratum B: Cap-suppressed PRIORITY_REVIEW ranks 16-19 (510-stock 2026-10-09 full scan)
    CaseSpec(
        study_case_id="M0-04",
        stratum="B_CAP_SUPPRESSED_PRIORITY_REVIEW",
        snapshot_key="snap510",
        symbol="EXPD",
        data_comparability_verdict="LEGACY_PRE_P0_NO_CIK_IN_PROVENANCE",
        primary_attribution_axis="SELECTION_OR_RANKING_MECHANISM_GAP",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="Omitted from Top-15 Daily/Weekly shortlist by Quality-first tiebreak (rank #16)",
        reviewer_rationale=(
            "Quality A (0.787) + ENTRY_READY (0.835): meets full PRIORITY_REVIEW criteria "
            "but is truncated at rank #16 behind names with lower Entry scores because v1 "
            "sorts strictly by Quality score before Entry score."
        ),
    ),
    CaseSpec(
        study_case_id="M0-05",
        stratum="B_CAP_SUPPRESSED_PRIORITY_REVIEW",
        snapshot_key="snap510",
        symbol="ZM",
        data_comparability_verdict="LEGACY_PRE_P0_NO_CIK_IN_PROVENANCE",
        primary_attribution_axis="SELECTION_OR_RANKING_MECHANISM_GAP",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="Omitted from Top-15 Daily/Weekly shortlist despite 0.925 Entry score (rank #17)",
        reviewer_rationale=(
            "Quality A (0.782) + ENTRY_READY (0.925, zero quality risks): stronger entry "
            "setup than most Top-15 members, yet invisible on the primary 15-name surface."
        ),
    ),
    # Stratum C: Quality A + WATCH_PULLBACK (62-stock 2026-10-12 MVP Beta)
    CaseSpec(
        study_case_id="M0-06",
        stratum="C_WATCH_PULLBACK_CLARITY",
        snapshot_key="snap62",
        symbol="AMD",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="NONE_ACTIONABLE_BASELINE",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="None (price_extended_above_sma50 and return_20d_overextended explicit)",
        reviewer_rationale=(
            "Rank #7 WATCH_PULLBACK control: overextension predicates (SMA50=1.204, "
            "ret20=+27.8%) and normalization band (SMA50<=1.08, ret20<=12%) are concrete."
        ),
    ),
    CaseSpec(
        study_case_id="M0-07",
        stratum="C_WATCH_PULLBACK_CLARITY",
        snapshot_key="snap62",
        symbol="META",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="NONE_ACTIONABLE_BASELINE",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="None (explicit overextension risk items)",
        reviewer_rationale=(
            "Rank #9 WATCH_PULLBACK control: clear separation between strong Company "
            "Quality (A) and extended short-term price action."
        ),
    ),
    # Stratum D: WATCH_BREAKOUT heterogeneity & silent-band blockers (62-stock 2026-10-12 MVP Beta)
    CaseSpec(
        study_case_id="M0-08",
        stratum="D_WATCH_BREAKOUT_HETEROGENEITY",
        snapshot_key="snap62",
        symbol="LIN",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="NONE_ACTIONABLE_BASELINE",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note="None (explicit relative_strength_60d_qqq_weak=-11.88% item emitted)",
        reviewer_rationale=(
            "Explicitly evidenced WATCH_BREAKOUT: reviewer can immediately see that "
            "60d QQQ relative strength (-11.88% vs >=-3% gate) is the readiness blocker."
        ),
    ),
    CaseSpec(
        study_case_id="M0-09",
        stratum="D_WATCH_BREAKOUT_HETEROGENEITY",
        snapshot_key="snap62",
        symbol="CRM",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="EVIDENCE_PRESENTATION_GAP",
        worth_human_review_yn_unknown="unknown",
        silent_or_scope_note=(
            "SILENT_READY_BLOCKER: zero Entry risk items emitted; passes SMA200/ret20/ret60/RS60 "
            "but blocks on an unevidenced SMA50 (0.97-0.98 or 1.08-1.10) or drawdown (>22%) band"
        ),
        reviewer_rationale=(
            "Rank #10 on Action List with 5 positive Entry items and 0 Entry risk items: "
            "human reviewer cannot tell from the report why CRM is WATCH_BREAKOUT instead of ENTRY_READY."
        ),
    ),
    CaseSpec(
        study_case_id="M0-10",
        stratum="D_WATCH_BREAKOUT_HETEROGENEITY",
        snapshot_key="snap62",
        symbol="TXN",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="EVIDENCE_PRESENTATION_GAP",
        worth_human_review_yn_unknown="unknown",
        silent_or_scope_note=(
            "SILENT_RET60_AND_RS_BAND: return_60d in (-8%, 0%) and RS60 in (-10%, -3%) "
            "emit neither positive nor negative EvidenceItems"
        ),
        reviewer_rationale=(
            "Rank #11 on Action List with 0 Entry risk items: medium-term momentum and RS "
            "sit in v1's silent dead-zone, hiding the exact distance to ENTRY_READY."
        ),
    ),
    CaseSpec(
        study_case_id="M0-11",
        stratum="D_WATCH_BREAKOUT_HETEROGENEITY",
        snapshot_key="snap62",
        symbol="PG",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="EVIDENCE_PRESENTATION_GAP",
        worth_human_review_yn_unknown="unknown",
        silent_or_scope_note=(
            "SILENT_RS_BAND: 60d QQQ relative strength in (-10%, -3%) fails the >=-3% "
            "ENTRY_READY gate without emitting a negative EvidenceItem"
        ),
        reviewer_rationale=(
            "Rank #14 on Action List with 5 positive Entry items and 0 Entry risk items: "
            "RS60 miss is silent in both Action List and Detailed Report."
        ),
    ),
    CaseSpec(
        study_case_id="M0-12",
        stratum="D_WATCH_BREAKOUT_HETEROGENEITY",
        snapshot_key="snap62",
        symbol="GOOGL",
        data_comparability_verdict="SHARE_CLASS_MULTI_CLASS_TOTAL_SCOPE_NOTE",
        primary_attribution_axis="EVIDENCE_PRESENTATION_GAP",
        worth_human_review_yn_unknown="unknown",
        silent_or_scope_note=(
            "SILENT_RS_BAND on Entry (0 Entry risks emitted) + 3-class total share count "
            "(Class A+B+C ~12.24B) paired with GOOGL Class A price in valuation"
        ),
        reviewer_rationale=(
            "Rank #15 on Action List: exhibits both the silent RS60 readiness blocker "
            "(0 Entry risks shown) and multi-class share-count scope note from PR-A SEC controls."
        ),
    ),
    # Stratum E: Quality B + ENTRY_READY and Quality A + TREND_DAMAGED routed to HOLD_MONITOR
    CaseSpec(
        study_case_id="M0-13",
        stratum="E_HOLD_MONITOR_COMPRESSION",
        snapshot_key="snap62",
        symbol="NVDA",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="SELECTION_OR_RANKING_MECHANISM_GAP",
        worth_human_review_yn_unknown="Y",
        silent_or_scope_note=(
            "Quality B (0.796, just below 0.80 A cutoff) + ENTRY_READY (0.95) mapped to "
            "HOLD_MONITOR (rank #26) behind all 7 A+WATCH_BREAKOUT names"
        ),
        reviewer_rationale=(
            "High-conviction B+ENTRY_READY candidate (penalized only by accrual/receivables "
            "working-capital growth during 83% revenue expansion) is buried in 39 HOLD_MONITOR rows."
        ),
    ),
    CaseSpec(
        study_case_id="M0-14",
        stratum="E_HOLD_MONITOR_COMPRESSION",
        snapshot_key="snap62",
        symbol="ISRG",
        data_comparability_verdict="VERIFIED_CIK_AND_ASOF",
        primary_attribution_axis="EVIDENCE_PRESENTATION_GAP",
        worth_human_review_yn_unknown="unknown",
        silent_or_scope_note=(
            "SILENT_TREND_DAMAGED_TRIGGER: Entry state is TREND_DAMAGED ( via days_below_sma200>=15 "
            "or sma200 in [0.95,1.00) ), but the ONLY emitted Entry risk is price_extended_above_sma50=1.104"
        ),
        reviewer_rationale=(
            "Rank #17 (first off-list name): state says TREND_DAMAGED while the only displayed "
            "risk says 'Price is extended above SMA50 (1.104), prefer a pullback' and ret60 is +23.9%."
        ),
    ),
    # Stratum F: Financial-data identity, share-class scope, and specialist accounting cases
    CaseSpec(
        study_case_id="M0-15",
        stratum="F_DATA_SCOPE_AND_ACCOUNTING",
        snapshot_key="snap510",
        symbol="HEI",
        data_comparability_verdict="CONFIRMED_SHARE_SCOPE_ALTERNATION",
        primary_attribution_axis="DATA_OR_ACCOUNTING_SCOPE_ERROR",
        worth_human_review_yn_unknown="N",
        silent_or_scope_note=(
            "SHARES_TAGS mixes 10-Q Common-only instant shares (~55M) with 10-K two-class "
            "weighted-average basic shares (~138M) multiplied by single-class HEI price"
        ),
        reviewer_rationale=(
            "Scored Quality A (0.922) in 2026-10-09 snapshot, but PR-A SEC/EdgarTools audit "
            "confirmed ~2.5x share-count basis alternation across 10-K/10-Q, corrupting market_cap, "
            "fcf_yield, pe/ps percentiles, and shares_yoy."
        ),
    ),
    CaseSpec(
        study_case_id="M0-16",
        stratum="F_DATA_SCOPE_AND_ACCOUNTING",
        snapshot_key="snap62",
        symbol="XOM",
        data_comparability_verdict="UNCOMPARABLE_CROSS_ENTITY_FACTS",
        primary_attribution_axis="DATA_OR_ACCOUNTING_SCOPE_ERROR",
        worth_human_review_yn_unknown="N",
        silent_or_scope_note=(
            "CIK 0002115436 (ExxonMobil Holdings Corp) has 0 own 10-K/10-Q in submissions; "
            "flipped between UNRATED (14 missing) and B (opco facts) at identical asof 2026-08-03"
        ),
        reviewer_rationale=(
            "Canonical P0 identity/content case: B grade in 2026-10-12 snapshot is cross-entity "
            "opco facts under a holdings CIK and must not be trusted until entity binding is resolved."
        ),
    ),
    CaseSpec(
        study_case_id="M0-17",
        stratum="F_DATA_SCOPE_AND_ACCOUNTING",
        snapshot_key="snap62",
        symbol="PLD",
        data_comparability_verdict="FILING_FACTS_COVERAGE_LAG_AND_REIT_SEMANTICS",
        primary_attribution_axis="DATA_OR_ACCOUNTING_SCOPE_ERROR",
        worth_human_review_yn_unknown="N",
        silent_or_scope_note=(
            "REIT accounting (GAAP FCF/current-ratio missing or non-standard without FFO/AFFO) "
            "+ historical Q2 10-Q filing-to-companyfacts lag noted in PR #62"
        ),
        reviewer_rationale=(
            "Rated Quality B (0.61, confidence 0.70) with 5 missing metrics; REIT cash-flow/leverage "
            "semantics are not cross-sector comparable to operating industrials/software."
        ),
    ),
    CaseSpec(
        study_case_id="M0-18",
        stratum="F_DATA_SCOPE_AND_ACCOUNTING",
        snapshot_key="snap62",
        symbol="JPM",
        data_comparability_verdict="BANK_ACCOUNTING_INAPPLICABLE_IN_V1",
        primary_attribution_axis="DATA_OR_ACCOUNTING_SCOPE_ERROR",
        worth_human_review_yn_unknown="N",
        silent_or_scope_note=(
            "Depository institution: 8 balance-sheet/FCF metrics missing (component=None) "
            "and OCF/NI (-2.45) reflects banking operating-asset flows rather than industrial distress"
        ),
        reviewer_rationale=(
            "Rated Quality C (0.392, confidence 0.533) and routed to AVOID: v1 generic industrial "
            "accounting core cannot validly grade banks/brokers (same class as BAC/MS/GS)."
        ),
    ),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_decisions_by_symbol(jsonl_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[str(row["symbol"])] = row
    return out


def _format_evidence_list(items: Sequence[Mapping[str, Any]], max_items: int = 4) -> str:
    if not items:
        return "(none)"
    parts: list[str] = []
    for item in items[:max_items]:
        code = str(item.get("code", ""))
        val = item.get("value")
        if isinstance(val, float):
            parts.append(f"{code}={val:.4g}")
        elif val is not None:
            parts.append(f"{code}={val}")
        else:
            parts.append(code)
    if len(items) > max_items:
        parts.append(f"+{len(items) - max_items}_more")
    return "; ".join(parts)


def _assess_trigger_clarity(decision: Mapping[str, Any], spec: CaseSpec) -> str:
    if spec.primary_attribution_axis == "DATA_OR_ACCOUNTING_SCOPE_ERROR":
        return "UNRELIABLE_DATA_OR_ACCOUNTING_BASIS"
    if spec.primary_attribution_axis == "EVIDENCE_PRESENTATION_GAP":
        return "PARTIAL_SILENT_GATE_BLOCKER"
    return "CLEAR_EXPLICIT_TRIGGERS"


def build_worksheet_rows(
    *,
    snap62_decisions: Mapping[str, Mapping[str, Any]],
    snap62_manifest: Mapping[str, Any],
    snap510_decisions: Mapping[str, Mapping[str, Any]],
    snap510_manifest: Mapping[str, Any],
    specs: Sequence[CaseSpec] = FROZEN_M0_CASE_SPECS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for spec in specs:
        if spec.study_case_id in seen_ids:
            raise ValueError(f"duplicate study_case_id: {spec.study_case_id}")
        seen_ids.add(spec.study_case_id)
        if spec.primary_attribution_axis not in ATTRIBUTION_AXES:
            raise ValueError(f"invalid attribution axis: {spec.primary_attribution_axis}")
        if spec.worth_human_review_yn_unknown not in {"Y", "N", "unknown"}:
            raise ValueError(f"invalid worth_human_review value: {spec.worth_human_review_yn_unknown}")

        if spec.snapshot_key == "snap62":
            source_map = snap62_decisions
            manifest = snap62_manifest
            snapshot_id = "mvp_beta_2026-10-12_220a471"
        elif spec.snapshot_key == "snap510":
            source_map = snap510_decisions
            manifest = snap510_manifest
            snapshot_id = "mvp_v1_full_2026-10-09_313c5ff"
        else:
            raise ValueError(f"unknown snapshot_key: {spec.snapshot_key}")

        if spec.symbol not in source_map:
            raise KeyError(f"{spec.symbol} not found in {spec.snapshot_key}")

        d = source_map[spec.symbol]
        q = d["quality"]
        e = d["entry"]
        prov = d.get("provenance", {})
        daily_set = set(manifest.get("daily_symbols") or [])
        cik = prov.get("cik")

        q_pos = _format_evidence_list(q.get("positives") or [], max_items=3)
        e_pos = _format_evidence_list(e.get("positives") or [], max_items=3)
        q_risk = _format_evidence_list(q.get("risks") or [], max_items=3)
        e_risk = _format_evidence_list(e.get("risks") or [], max_items=3)
        q_miss = [str(x.get("code", "")) for x in (q.get("missing") or [])]

        miss_str = ",".join(q_miss) if q_miss else "none"
        missing_or_silent = f"Q_missing=[{miss_str}] | {spec.silent_or_scope_note}"

        rows.append({
            "study_case_id": spec.study_case_id,
            "stratum": spec.stratum,
            "snapshot_id": snapshot_id,
            "signal_date": str(d["decision_date"]),
            "symbol": spec.symbol,
            "priority_rank": int(d["priority"]),
            "in_top15_shortlist": spec.symbol in daily_set,
            "action_state": str(d["action_state"]),
            "quality_grade": str(q["grade"]),
            "quality_score": round(float(q["score"]), 6) if q.get("score") is not None else "",
            "quality_confidence": round(float(q["confidence"]), 6),
            "fundamental_data_asof": str(q.get("data_asof") or ""),
            "entry_state": str(e["state"]),
            "entry_score": round(float(e["score"]), 6) if e.get("score") is not None else "",
            "market_asof": str(e.get("market_asof") or ""),
            "cik_traceable": bool(cik and str(cik).strip()),
            "positives_summary": f"Q:[{q_pos}] E:[{e_pos}]",
            "risks_summary": f"Q:[{q_risk}] E:[{e_risk}]",
            "missing_or_silent_gates": missing_or_silent,
            "trigger_clarity": _assess_trigger_clarity(d, spec),
            "data_comparability_verdict": spec.data_comparability_verdict,
            "primary_attribution_axis": spec.primary_attribution_axis,
            "worth_human_review_yn_unknown": spec.worth_human_review_yn_unknown,
            "reviewer_rationale": spec.reviewer_rationale,
        })
    return rows


def scan_silent_entry_gates(decisions: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Identify non-ENTRY_READY decisions whose blocking predicates are silent in risks."""
    watch_breakout_zero_risks: list[str] = []
    trend_damaged_without_damage_item: list[str] = []
    damage_codes = {
        "price_materially_below_sma200",
        "price_below_sma50",
        "return_60d_weak",
        "relative_strength_60d_qqq_weak",
    }
    for d in sorted(decisions, key=lambda x: int(x["priority"])):
        sym = str(d["symbol"])
        e = d["entry"]
        state = str(e["state"])
        risk_codes = {str(r.get("code", "")) for r in (e.get("risks") or [])}
        if state == "WATCH_BREAKOUT" and not risk_codes:
            watch_breakout_zero_risks.append(sym)
        elif state == "TREND_DAMAGED" and not (risk_codes & damage_codes):
            trend_damaged_without_damage_item.append(sym)
    return {
        "watch_breakout_zero_entry_risks": watch_breakout_zero_risks,
        "trend_damaged_without_damage_risk_item": trend_damaged_without_damage_item,
    }


def write_m0_deliverables(
    *,
    output_dir: Path,
    snap510_dir: Path,
    snap62_dir: Path,
    git_main_sha: str,
    evidence_branch_sha: str,
) -> dict[str, str]:
    """Generate the 4 M0 deliverables and return their SHA256 map."""
    output_dir.mkdir(parents=True, exist_ok=True)

    snap510_jsonl = snap510_dir / "decisions.jsonl"
    snap510_manifest_path = snap510_dir / "run_manifest.json"
    snap62_jsonl = snap62_dir / "decisions.jsonl"
    snap62_manifest_path = snap62_dir / "run_manifest.json"

    snap510_decisions = load_decisions_by_symbol(snap510_jsonl)
    snap510_manifest = json.loads(snap510_manifest_path.read_text(encoding="utf-8"))
    snap62_decisions = load_decisions_by_symbol(snap62_jsonl)
    snap62_manifest = json.loads(snap62_manifest_path.read_text(encoding="utf-8"))

    snap510_sha = sha256_file(snap510_jsonl)
    snap62_sha = sha256_file(snap62_jsonl)

    rows = build_worksheet_rows(
        snap62_decisions=snap62_decisions,
        snap62_manifest=snap62_manifest,
        snap510_decisions=snap510_decisions,
        snap510_manifest=snap510_manifest,
    )

    silent_62 = scan_silent_entry_gates(list(snap62_decisions.values()))
    silent_510 = scan_silent_entry_gates(list(snap510_decisions.values()))

    # 1. Write human_review_worksheet.csv
    worksheet_path = output_dir / "human_review_worksheet.csv"
    with worksheet_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(WORKSHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    # 2. Write baseline_inventory.md
    inventory_path = output_dir / "baseline_inventory.md"
    inventory_md = f"""# M0 Baseline Inventory & Provenance Audit (2026-10-14)

- **Audit Mode**: Read-only (`RETROSPECTIVE_EXPLORATORY` & `POINT_IN_TIME_RECONSTRUCTED` cross-sections; zero network calls, zero forward-return computation, zero v1 policy changes).
- **Verified `main` HEAD**: `{git_main_sha}`
- **Verified `evidence-observations` HEAD**: `{evidence_branch_sha}`

## 1. Frozen Snapshot & Evidence Inventory

| Artifact ID | Scope & Decision Date | Code SHA | File / Archive Location | `decisions.jsonl` / Primary SHA256 | Decisions | CIK Traceable |
| --- | --- | --- | --- | --- | ---: | --- |
| `mvp_v1_full_2026-10-09_313c5ff` | 510-stock AI Watchlist (`risk_off`), `2026-10-09` | `313c5ffedc9c1cf837b70d5e95d01d545d5c592f` | `evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/` | `{snap510_sha}` | 510 | `0/510` (pre-PR #59/#66) |
| `mvp_beta_2026-10-12_220a471` | 62-stock 3-Source Discovery Union (`us_core`+`thematic`+`manual`), `2026-10-12` | `220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac` | `evidence-observations:runs/mvp-beta/mvp_beta_20261012_01/` | `{snap62_sha}` | 62 | `62/62` (post-PR #66) |
| `historical_v3_repaired` | 39 monthly signal dates (`2023-01` to `2026-03`), 670 symbols | `2d8919444828643f7b888f90907e0b0e6632bfc4` | `evidence-observations:runs/historical-selection-v1/historical_selection_v1_20261011_03/` | `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e` | 25,025 | N/A (`union_superset_approx`) |
| `mvp_v11_pr_a_archive` | PR #70 Historical Optimizer (`NO-GO / KEEP V1`) + 13 SEC/PIT cases | `9514166907e7f279fd6efd6f77f672badb9bd6f7` | `evidence-observations:runs/mvp-v11-pr-a-20261014/` | Commit `{evidence_branch_sha}` | 1,440 paired | 13 audited cases (`UNVERIFIED` binding) |
| `p0_identity_acceptance_02` | PR #64 L0/L1/L2 provenance & `UNCOMPARABLE` fixture matrix | `11cc71d` (merged) | `evidence-observations:runs/p0-identity-v1/p0_identity_20261013_02/` | Commit `fd8328b389a0efe0c300ce8654dd30448ef8f265` | 6 cases | Synthetic + cached fixtures |
| `business_model_quality_v0` | PR #62 11-company specialist accounting & entry silent-gate matrix | `f1090f1` (merged) | `data/research/business_model_quality_v0/` | Tracked in `main` | 11 symbols × 3 dates | 11/11 CIK inventoried |

## 2. Cross-Sectional State Distributions

### 2.1 510-Symbol AI Watchlist Snapshot (`2026-10-09`, code `313c5ff`)
- **Company Quality**: `A=183`, `B=205`, `C=92`, `UNRATED=30`
- **Entry Quality**: `ENTRY_READY=47`, `WATCH_PULLBACK=85`, `WATCH_BREAKOUT=141`, `TREND_DAMAGED=230`, `INSUFFICIENT_DATA=7`
- **Action State**: `PRIORITY_REVIEW=19` (15 in Daily/Weekly shortlist; **4 omitted by Top-15 cap**: `EXPD`, `ZM`, `JCI`, `SAIC`), `WATCH_PULLBACK=33`, `WATCH_BREAKOUT=55`, `HOLD_MONITOR=281` (includes **23 `B + ENTRY_READY`** and **76 `A + TREND_DAMAGED`**), `AVOID=122`
- **Silent Entry Gates Detected**:
  - `WATCH_BREAKOUT` with **0 Entry risk items**: `{len(silent_510["watch_breakout_zero_entry_risks"])}` symbols ({", ".join(silent_510["watch_breakout_zero_entry_risks"][:12])}{"..." if len(silent_510["watch_breakout_zero_entry_risks"]) > 12 else ""})
  - `TREND_DAMAGED` **without a trend-damage risk item** (triggered by `days_below_sma200 >= 15` or `sma200 in [0.95, 1.00)`): `{len(silent_510["trend_damaged_without_damage_risk_item"])}` symbols ({", ".join(silent_510["trend_damaged_without_damage_risk_item"][:12])}{"..." if len(silent_510["trend_damaged_without_damage_risk_item"]) > 12 else ""})

### 2.2 62-Symbol Generalized MVP Beta Snapshot (`2026-10-12`, code `220a471`)
- **Company Quality**: `A=24`, `B=31`, `C=5`, `UNRATED=2`
- **Entry Quality**: `ENTRY_READY=14`, `WATCH_PULLBACK=3`, `WATCH_BREAKOUT=16`, `TREND_DAMAGED=29`, `INSUFFICIENT_DATA=0`
- **Action State**: `PRIORITY_REVIEW=6` (`ETN`, `KO`, `EOG`, `JNJ`, `MSFT`, `TMO`), `WATCH_PULLBACK=3` (`AMD`, `AMAT`, `META`), `WATCH_BREAKOUT=7` (`CRM`, `TXN`, `CAT`, `LIN`, `PG`, `GOOGL`, plus rank #16 `LLY`), `HOLD_MONITOR=39` (includes **8 `B + ENTRY_READY`** and **8 `A + TREND_DAMAGED`**), `AVOID=7`
- **Silent Entry Gates Detected**:
  - `WATCH_BREAKOUT` with **0 Entry risk items**: `{len(silent_62["watch_breakout_zero_entry_risks"])}` symbols (`{", ".join(silent_62["watch_breakout_zero_entry_risks"])}`)
  - `TREND_DAMAGED` **without a trend-damage risk item**: `{len(silent_62["trend_damaged_without_damage_risk_item"])}` symbols (`{", ".join(silent_62["trend_damaged_without_damage_risk_item"])}`)
"""
    inventory_path.write_text(inventory_md, encoding="utf-8")

    # 3. Write attention_failure_cases.md
    failures_path = output_dir / "attention_failure_cases.md"
    failures_md = f"""# M0 Attention Failure Cases & M1 Correctness Engineering Contract (2026-10-14)

## 1. Executive Summary

Read-only inspection of the 18 stratified cases across `mvp_v1_full_2026-10-09_313c5ff` (510 symbols) and `mvp_beta_2026-10-12_220a471` (62 symbols) confirms that canonical `StockDecision` rendering is structurally consistent, but reveals **three concrete failure families** that degrade human research efficiency or corrupt fundamental comparability.

Crucially, these three families belong to **three distinct causal axes** and must not be conflated or addressed via parameter tuning:

| Failure Family | Causal Attribution Axis | Representative Cases | Impact on Human Research | Target Milestone |
| --- | --- | --- | --- | --- |
| **Family 1: Share-Count Basis Alternation, Cross-Entity Facts & Specialist Accounting** | `DATA_OR_ACCOUNTING_SCOPE_ERROR` | `HEI`, `XOM`, `GOOGL`, `VSH`, `PLD`, `JPM`, `GS` | Corrupts `market_cap`, `fcf_yield`, `pe/ps`, `shares_yoy`, or grades banks/REITs on inapplicable industrial ratios | **M1 Correctness PR** (before M2 attribution) |
| **Family 2: Silent Entry Readiness & Trend-Damage Predicates** | `EVIDENCE_PRESENTATION_GAP` | `CRM`, `TXN`, `PG`, `GOOGL` (`WATCH_BREAKOUT`); `ISRG` (`TREND_DAMAGED`) | Shortlist/report shows 0 blocking Entry risks (or contradictory overextension risk on a `TREND_DAMAGED` stock), leaving reviewer unable to answer "why not READY / what to wait for" | **M1/M2 Evidence-Completeness PR** (0 state/score change) |
| **Family 3: Top-15 Cap Truncation & `HOLD_MONITOR` Compression** | `SELECTION_OR_RANKING_MECHANISM_GAP` | `EXPD`, `ZM`, `JCI`, `SAIC` (ranks #16–19 `PRIORITY_REVIEW`); `NVDA`, `AMZN` (`B + ENTRY_READY`) | Truncates eligible `A + ENTRY_READY` names by Quality-first tiebreaking and buries `B + ENTRY_READY` behind `A + WATCH_BREAKOUT` with no secondary review cue | **M2 Attribution -> M3 Bounded Hypothesis** |

---

## 2. Detailed Diagnosis of the Three Failure Families

### Family 1 (`DATA_OR_ACCOUNTING_SCOPE_ERROR`): Share-Count Scope Mixing & Entity/Accounting Integrity

1. **Confirmed Share-Count Concept & Class Mixing (`HEI`, `VSH`, `GOOGL`)**:
   - In `src/ai_value_scanner/scanner.py` (`SHARES_TAGS`) and `src/ai_value_scanner/fundamentals/facts.py` (`collapse_fact_records_by_end`), point-in-time single-class shares (`EntityCommonStockSharesOutstanding`, `CommonStockSharesOutstanding`) and period-weighted average basic/diluted shares (`WeightedAverageNumberOfSharesOutstandingBasic`, `WeightedAverageNumberOfDilutedSharesOutstanding`) are pooled into one list and collapsed purely by `(unit, period_end)` where later filings override tag priority.
   - **Empirical effect on `HEI`**: 10-Q filings supply Common-only point-in-time shares (~55.05M), while 10-K filings supply two-class (`HEI` + `HEI.A`) annual weighted-average basic shares (~137.2M–139.0M). Both are multiplied by the single-class `HEI` price, causing a ~2.5x artificial alternation in `market_cap`, `fcf_yield`, `ps/pe` percentiles, and `shares_yoy` dilution. In the 2026-10-09 510-stock snapshot, `HEI` is graded **Quality A (0.922)** without any share-scope warning.
   - **Empirical effect on `VSH` and `GOOGL`**: PR-A SEC controls confirmed `VSH` uses period-weighted basic shares (143.98M vs ~141.7M cover total across Class A+B) and `GOOGL` uses three-class total shares (Class A + unlisted Class B + Class C ~12.24B) multiplied by `GOOGL` Class A price.
2. **Cross-Entity Facts Under Holdings Mapping (`XOM`) & Filing-Facts Lag (`PLD`)**:
   - `XOM` maps to CIK `0002115436` (`ExxonMobil Holdings Corp`, 34 recent filings, 0 own 10-K/10-Q), which alternated between `UNRATED` (14 missing metrics in `posthoc_2026-10-09`) and `Quality B` (opco-scale `$19.26B` FCF in `mvp_beta_2026-10-12`) at the exact same `data_asof=2026-08-03`.
   - PR #64 (`fundamentals/provenance.py`) added L0/L1/L2 hashes and `UNCOMPARABLE` audit detection, but live/snapshot reporting still requires explicit share-scope and entity-coherence surfacing so `XOM`-class rows are never treated as verified comparable B grades.
3. **Specialist Accounting Inapplicability (`JPM`, `BAC`, `MS`, `GS`, `AMT`, `EQIX`, `O`, `PLD`)**:
   - Banks (`JPM`, `BAC`, `MS`) receive `Quality C` because 7–8 balance-sheet/FCF metrics are `MISSING` (`balance_sheet=None`) and banking operating-cash-flow swings score negatively; broker `GS` is `UNRATED` with a `-$41.5B` FCF artifact and missing revenue tag (`RevenuesNetOfInterestExpense`). REITs (`AMT`, `EQIX`, `O`, `PLD`) receive `Quality B` on GAAP net-income/depreciation metrics without FFO/AFFO normalization.

### Family 2 (`EVIDENCE_PRESENTATION_GAP`): Silent Entry Readiness & Trend-Damage Blockers

1. **Silent `WATCH_BREAKOUT` Readiness Blockers (`CRM`, `TXN`, `PG`, `GOOGL` in 62-stock shortlist; {len(silent_510["watch_breakout_zero_entry_risks"])} symbols in 510-stock snapshot)**:
   - In `src/ai_value_scanner/decision/entry.py`, `ENTRY_READY` requires `0.98 <= price_to_sma50 <= 1.08`, `-0.03 <= return_20d <= 0.12`, `return_60d >= 0.0`, `relative_strength_60d_qqq >= -0.03`, `drawdown_from_52w_high <= 0.22`, and `volatility_60d <= 0.80`.
   - However, negative `EvidenceItem`s are only emitted for extreme weakness (`price_to_sma50 < 0.97` or `> 1.10`, `return_60d <= -0.08`, `relative_strength_60d_qqq <= -0.10`, `volatility_60d > 0.80`), and **never** for `drawdown_from_52w_high > 0.22`, `price_to_sma200 in [0.95, 1.00)`, `price_to_sma50 in [0.97, 0.98) ∪ (1.08, 1.10]`, `return_20d in (-0.15, -0.03) ∪ (0.12, 0.15]`, `return_60d in (-0.08, 0.0)`, or `relative_strength_60d_qqq in (-0.10, -0.03)`.
   - Consequently, **4 of the 6 `WATCH_BREAKOUT` names on the 2026-10-12 15-stock Action List (`CRM`, `TXN`, `PG`, `GOOGL`) display zero Entry risk items**, leaving the human reviewer with no explanation of which gate blocked `ENTRY_READY`.
2. **Silent `TREND_DAMAGED` Trigger (`ISRG` in 62-stock snapshot; {len(silent_510["trend_damaged_without_damage_risk_item"])} symbols in 510-stock snapshot)**:
   - `TREND_DAMAGED` triggers when `price_to_sma200 < 0.95` OR `days_below_sma200 >= 15` (or combined SMA50/ret60/RS60 weakness). Yet `entry.py` emits **no `EvidenceItem` for `days_below_sma200 >= 15`**.
   - For `ISRG` (rank #17, `Quality A`, `return_60d = +23.89%`, `RS60 = +16.60%`), `EntryState` is `TREND_DAMAGED`, but the **only** emitted Entry risk item is `price_extended_above_sma50 = 1.104` ("Price is extended enough to prefer a pullback"). This is self-contradictory to a human reader.

### Family 3 (`SELECTION_OR_RANKING_MECHANISM_GAP`): Attention-Cap Truncation & `HOLD_MONITOR` Routing

1. **Top-15 Truncation of Eligible `PRIORITY_REVIEW` Candidates (`EXPD`, `ZM`, `JCI`, `SAIC`)**:
   - In the 510-stock snapshot, 19 symbols achieve `PRIORITY_REVIEW` (`Quality A + ENTRY_READY`). Because `_action_sort_key` ranks by `(Action, QualityGrade, -QualityScore, -EntryScore)`, ranks #16–19 (`EXPD` Entry 0.835, `ZM` Entry 0.925, `JCI` Entry 0.875, `SAIC` Entry 0.835) are completely excluded from the 15-name Daily/Weekly Action List without a truncation notice.
2. **Compression of `Quality B + ENTRY_READY` into `HOLD_MONITOR` (`NVDA`, `AMZN`, `MU`, `TER`)**:
   - In the 62-stock snapshot, `NVDA` (`Quality B` 0.796, just 0.004 below the `0.80` Quality A cutoff, `ENTRY_READY` 0.950) is mapped to `HOLD_MONITOR` at priority rank #26—ranked behind 7 `Quality A + WATCH_BREAKOUT` names (including `CRM`, `TXN`, `PG`, `GOOGL`) and 8 `Quality A + TREND_DAMAGED` names.

---

## 3. M1 Correctness Engineering Contract (Gate G0 -> G1)

Before running M2 systematic historical attribution, **M1 must close the data/scope and silent-evidence defects** in a dedicated, outcome-blind correctness PR with **zero changes to v1 scoring weights, grade cutoffs, Entry state thresholds, or Action mapping**:

1. **Share-Count Basis & Provenance Separation (`src/ai_value_scanner/fundamentals/shares.py`, `facts.py`, `scanner.py`)**:
   - Separate point-in-time outstanding share tags (`EntityCommonStockSharesOutstanding`, `CommonStockSharesOutstanding`) from period-weighted average share tags (`WeightedAverageNumberOfSharesOutstandingBasic`, `WeightedAverageNumberOfDilutedSharesOutstanding`) so period-weighted annual facts cannot silently overwrite point-in-time quarterly shares for the same issuer (`HEI` fix).
   - Record explicit share-basis provenance (`share_count_source_tag`, `share_count_basis`: `point_in_time_outstanding` vs `weighted_average_fallback`, and `share_scope_Diagnostic`) and fail closed / flag severe cross-period basis jumps.
2. **Entry Evidence Completeness Without State Drift (`src/ai_value_scanner/decision/entry.py`)**:
   - Emit explicit negative/diagnostic `EvidenceItem`s whenever an active `TREND_DAMAGED` predicate (`days_below_sma200 >= 15`) or `ENTRY_READY` blocker (`price_to_sma200 in [0.95, 1.00)`, `price_to_sma50` outside `0.98–1.08`, `return_20d` outside `-3%..+12%`, `return_60d in (-8%, 0%)`, `relative_strength_60d_qqq in (-10%, -3%)`, `drawdown_from_52w_high > 0.22`) fires.
   - Preserve **100% identical `EntryState`, `entry.score`, `entry.confidence`, `ActionState`, and priority ordering** across all existing snapshots and historical B0 parity tests.
3. **Strict Preservation of Frozen History**:
   - Do not modify `entry_quality_dataset_risk_off.v3.csv` (`2a4600ee...`), any archived `evidence-observations` commit, or production `configs/config.risk_off.json`.
"""
    failures_path.write_text(failures_md, encoding="utf-8")

    # 4. Write review_gate.json
    axis_counts: dict[str, int] = {}
    worth_counts: dict[str, int] = {}
    for r in rows:
        ax = str(r["primary_attribution_axis"])
        axis_counts[ax] = axis_counts.get(ax, 0) + 1
        w = str(r["worth_human_review_yn_unknown"])
        worth_counts[w] = worth_counts.get(w, 0) + 1

    gate_payload = {
        "milestone": "M0_BASELINE_AND_USAGE_AUDIT",
        "audit_date": "2026-10-14",
        "verdict": "GO_FOR_M1_CORRECTNESS_ENGINEERING",
        "evidence_tiers_used": [
            "RETROSPECTIVE_EXPLORATORY",
            "POINT_IN_TIME_RECONSTRUCTED",
        ],
        "human_live_timing_measured": False,
        "network_requests_made": 0,
        "forward_returns_inspected": False,
        "production_v1_policy_modified": False,
        "git_main_sha": git_main_sha,
        "evidence_observations_sha": evidence_branch_sha,
        "inputs": {
            "snap510_decisions_jsonl_sha256": snap510_sha,
            "snap62_decisions_jsonl_sha256": snap62_sha,
            "historical_v3_dataset_sha256": "2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e",
        },
        "worksheet_summary": {
            "total_cases": len(rows),
            "by_primary_attribution_axis": dict(sorted(axis_counts.items())),
            "by_worth_human_review": dict(sorted(worth_counts.items())),
        },
        "silent_entry_gate_prevalence": {
            "snap62_watch_breakout_zero_risk_count": len(silent_62["watch_breakout_zero_entry_risks"]),
            "snap62_watch_breakout_zero_risk_symbols": silent_62["watch_breakout_zero_entry_risks"],
            "snap62_trend_damaged_missing_damage_item_count": len(silent_62["trend_damaged_without_damage_risk_item"]),
            "snap62_trend_damaged_missing_damage_item_symbols": silent_62["trend_damaged_without_damage_risk_item"],
            "snap510_watch_breakout_zero_risk_count": len(silent_510["watch_breakout_zero_entry_risks"]),
            "snap510_trend_damaged_missing_damage_item_count": len(silent_510["trend_damaged_without_damage_risk_item"]),
        },
        "top_failure_families": [
            {
                "id": "M0-FAM-1",
                "axis": "DATA_OR_ACCOUNTING_SCOPE_ERROR",
                "title": "Share-count basis alternation (HEI/VSH/GOOGL), cross-entity facts (XOM), and specialist accounting (JPM/GS/PLD)",
                "target_milestone": "M1",
            },
            {
                "id": "M0-FAM-2",
                "axis": "EVIDENCE_PRESENTATION_GAP",
                "title": "Silent Entry READY blockers on WATCH_BREAKOUT (CRM/TXN/PG/GOOGL) and silent days_below_sma200 trigger on TREND_DAMAGED (ISRG)",
                "target_milestone": "M1_OR_M2",
            },
            {
                "id": "M0-FAM-3",
                "axis": "SELECTION_OR_RANKING_MECHANISM_GAP",
                "title": "Top-15 cap truncation of eligible PRIORITY_REVIEW (EXPD/ZM/JCI/SAIC) and B+ENTRY_READY suppression into HOLD_MONITOR (NVDA)",
                "target_milestone": "M2_TO_M3",
            },
        ],
        "m1_entry_criteria_met": True,
    }
    gate_path = output_dir / "review_gate.json"
    gate_path.write_text(json.dumps(gate_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    hashes = {
        p.name: sha256_file(p)
        for p in sorted([inventory_path, worksheet_path, failures_path, gate_path], key=lambda x: x.name)
    }
    sha_lines = [f"{digest}  {name}" for name, digest in hashes.items()]
    (output_dir / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    return hashes
