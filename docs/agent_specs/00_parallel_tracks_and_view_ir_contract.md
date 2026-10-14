# Parallel Tracks Architecture & Presentation IR Contract (`view_model.py`)

> **Status**: Active Engineering Contract (2026-10-14)
> **Base `main` Reference**: `ef9cc55` (post-PR #73 M0 Baseline Audit)
> **Purpose**: Decouple **Track A (Report Readability & Presentation v2)** from **Track B (Data Correctness M1 & Selection Optimization M2–M4)** via a pure, versioned intermediate representation (`DecisionViewModel` / Presentation IR) so both tracks can be developed, tested, and reviewed in parallel with zero merge conflicts and zero regressions on frozen snapshots.

---

## 1. Architectural Overview

```text
[Track B: Selection & Data Correctness Track]
  src/ai_value_scanner/fundamentals/{shares,facts,provenance}.py
  src/ai_value_scanner/decision/{quality,entry,action,integrated}.py
  src/ai_value_scanner/scanner.py
                       |
                       v
       Canonical StockDecision (decisions.jsonl)
       - Preserves schema_version="1" serialization compatibility
       - Emits structured EvidenceItems & provenance keys
                       |
=======================|==================================================
       [Intermediate Presentation IR Layer (The Bridge)]
  src/ai_value_scanner/decision/view_model.py
  - Pure functions consuming StockDecision + optional manifest/universe context
  - Human-readable value formatting ($15.15B, +23.6%, 1.03x, 100th pctl)
  - Structured 6-pillar Quality table rows & Entry readiness gate checklist
  - Primary Top-15 shortlist + Secondary Radar (cap-omitted A+READY & top B+READY)
  - Data integrity & share-scope badges (VERIFIED, SHARE_SCOPE_WARNING, UNVERIFIED)
=======================|==================================================
                       |
                       v
[Track A: Report Presentation Track]
  src/ai_value_scanner/reporting/decision.py
  - layout_version="v1" (default; preserves 100% byte-for-byte parity for
    existing snapshots and scripts/validate_mvp_snapshot.py)
  - layout_version="v2" (human-readable English tabular dashboard)
  scripts/render_snapshot_preview.py
```

---

## 2. File-Ownership Boundary (Zero-Conflict Guarantee)

To enable concurrent execution without Git conflicts, Track A and Track B own disjoint file sets:

| Track | Owned / Modifiable Files | Strictly Off-Limits |
| --- | --- | --- |
| **Track A (Report Readability v2)** | - `src/ai_value_scanner/decision/view_model.py` (new)<br>- `src/ai_value_scanner/reporting/decision.py`<br>- `scripts/render_snapshot_preview.py` (new)<br>- `tests/test_decision_view_model_and_report_v2.py` (new) | - `src/ai_value_scanner/fundamentals/*`<br>- `src/ai_value_scanner/decision/{quality,entry,action,integrated,model}.py`<br>- `src/ai_value_scanner/scanner.py`<br>- `configs/*` |
| **Track B (M1 Data Scope & Silent Gates)** | - `src/ai_value_scanner/fundamentals/shares.py`<br>- `src/ai_value_scanner/fundamentals/facts.py`<br>- `src/ai_value_scanner/scanner.py`<br>- `src/ai_value_scanner/decision/entry.py`<br>- `tests/test_m1_share_scope_and_entry_silent_gates.py` (new) | - `src/ai_value_scanner/reporting/*`<br>- `src/ai_value_scanner/decision/view_model.py`<br>- `configs/*` |

---

## 3. Canonical Presentation IR Contract (`src/ai_value_scanner/decision/view_model.py`)

### 3.1 Human-Readable Value Formatting Rules (`format_metric_value`)

All numeric values in `EvidenceItem` and component tables must be formatted deterministically into human-readable English strings:

1. **Monetary Dollar Amounts** (`metric` in `{"free_cash_flow", "operating_cash_flow", "revenue", "net_income", "total_debt", "net_debt", "cash_and_equivalents", "market_cap"}`):
   - `abs(v) >= 1e9`: `f"${v / 1e9:,.2f}B"` (negative values formatted as `f"-${abs(v) / 1e9:,.2f}B"`, e.g. `$15.15B`, `-$875.00M` if `< 1e9`).
   - `1e6 <= abs(v) < 1e9`: `f"${v / 1e6:,.1f}M"` (e.g. `$923.9M`, `-$41.5M`).
   - `abs(v) < 1e6`: `f"${v:,.0f}"`.
2. **Percentages / Growth / Returns / Yields / Margins / Drawdowns** (`metric` in `{"net_margin", "accrual_ratio", "revenue_yoy", "adjusted_net_income_yoy", "operating_cash_flow_yoy", "shares_yoy", "fcf_yield", "receivables_growth_gap", "inventory_growth_gap", "return_20d", "return_60d", "relative_strength_60d_qqq", "drawdown_from_52w_high", "volatility_60d"}`):
   - Growth/return/RS metrics (`*_yoy`, `return_*`, `relative_strength_*`, `*_gap`): signed percentage `f"{v * 100:+.1f}%"` (e.g. `+23.9%`, `-4.7%`).
   - Margin/yield/drawdown/volatility/accrual metrics: `f"{v * 100:.1f}%"` (e.g. `16.8%`, `-24.3%`).
3. **Percentiles** (`metric` in `{"ps_hist_percentile", "pe_hist_percentile", "range_position_52w"}`):
   - `f"{v * 100:.0f}th pctl"` for historical valuation percentiles (e.g. `1.0` -> `100th pctl`, `0.25` -> `25th pctl`), and `f"{v * 100:.0f}% of 52w range"` for `range_position_52w`.
4. **Multiples & Ratios** (`metric` in `{"price_to_sma200", "price_to_sma50", "ocf_to_net_income", "net_debt_to_ebitda", "interest_coverage", "current_ratio"}`):
   - `f"{v:.2f}x"` (e.g. `1.03x`, `61.40x`, `-0.83x`).
5. **Day Counts** (`metric` in `{"fundamental_data_age_days", "market_data_age_days", "days_below_sma200"}`):
   - `f"{int(round(float(v)))}d"` (e.g. `0d`, `46d`).

### 3.2 Core Dataclasses in `view_model.py`

```python
@dataclass(frozen=True)
class FormattedEvidenceRow:
    code: str
    label: str
    polarity: str              # "positive" | "negative" | "neutral" | "missing"
    metric: str | None
    formatted_value: str       # e.g. "$15.15B", "+23.9%", "1.03x", "n/a"
    target_band: str           # e.g. ">=10% supportive; <0% weak"
    summary_text: str          # Concise English phrase: e.g. "Free cash flow: $15.15B"

@dataclass(frozen=True)
class QualityPillarRow:
    pillar_key: str            # e.g. "profitability_cash"
    pillar_label: str          # e.g. "Profitability & Cash Conversion"
    score_display: str         # e.g. "0.80" or "MISSING"
    status_badge: str          # "STRONG" | "MIXED" | "WEAK" | "MISSING"
    supporting_items: tuple[FormattedEvidenceRow, ...]
    risk_or_missing_items: tuple[FormattedEvidenceRow, ...]

@dataclass(frozen=True)
class EntryGateCheckRow:
    gate_key: str              # "freshness", "sma200_trend", "sma50_band", "ret20_band", "ret60_trend", "rs60_qqq", "regime"
    gate_label: str            # e.g. "Long-Term Trend (Price / SMA200)"
    status: str                # "PASS" | "FAIL_BLOCKER" | "SILENT_OR_UNOBSERVED"
    observed_display: str      # e.g. "1.17x" or "Not emitted (silent band)"
    target_display: str        # e.g. ">= 1.00x (Damaged < 0.95x)"
    note: str

@dataclass(frozen=True)
class DataTrustBadge:
    overall_status: str        # "VERIFIED" | "CAUTION_LAG_OR_FALLBACK" | "UNVERIFIED_OR_SCOPE_RISK"
    entity_display: str        # e.g. "Salesforce, Inc. (CIK 0001108524)" or "UNVERIFIED"
    share_basis_display: str   # e.g. "point_in_time_outstanding" or "legacy_unspecified"
    freshness_display: str     # e.g. "Fund: 2026-08-27 (46d) | Mkt: 2026-10-12 (0d)"
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class StockCardViewModel:
    decision: StockDecision
    rank: int
    symbol: str
    company_name: str
    action_state: str
    quality_grade: str
    quality_score_display: str
    quality_confidence_display: str
    entry_state: str
    entry_score_display: str
    entry_confidence_display: str
    top_positives_inline: str          # 2-3 concise formatted bullets for summary table
    top_risks_or_blockers_inline: str  # 1-2 concise risks or explicit silent-gate blocker note
    next_trigger_inline: str
    data_trust: DataTrustBadge
    quality_pillars: tuple[QualityPillarRow, ...]
    entry_checklist: tuple[EntryGateCheckRow, ...]
    all_counter_evidence: tuple[FormattedEvidenceRow, ...]
    all_missing_evidence: tuple[FormattedEvidenceRow, ...]

@dataclass(frozen=True)
class SnapshotViewModel:
    title: str
    cadence: str | None
    decision_date: str
    primary_cards: tuple[StockCardViewModel, ...]
    cap_omitted_priority_cards: tuple[StockCardViewModel, ...]
    secondary_b_ready_cards: tuple[StockCardViewModel, ...]
```

### 3.3 Forward & Backward Compatibility Guarantee between Track A and Track B

- **Before Track B merges** (on legacy `2026-10-09` or `2026-10-12` snapshots):
  - When a `WATCH_BREAKOUT` or `TREND_DAMAGED` stock has a gate with neither a positive nor negative `EvidenceItem` (e.g., `CRM`, `TXN`, `PG`, `GOOGL`, `ISRG`), `view_model.py` inspects the missing readiness confirmation and labels that checklist row `SILENT_OR_UNOBSERVED` with a clear explanation (e.g., `"Not in ENTRY_READY band (silent in v1 snapshot)"`), rather than falsely showing `"none"` under risks!
- **After Track B merges** (once `entry.py` emits explicit `EvidenceItem`s for `days_below_sma200_elevated`, `relative_strength_60d_qqq_below_ready`, `return_60d_slightly_negative`, `price_to_sma50_outside_ready_band`, `drawdown_from_52w_high_deep`, etc., and `provenance` carries `share_count_basis`):
  - `view_model.py` automatically picks up those new `EvidenceItem` codes and provenance keys and upgrades the checklist row from `SILENT_OR_UNOBSERVED` to `FAIL_BLOCKER` with the exact formatted value (e.g., `RS60 vs QQQ: -4.7% (target >= -3.0%)`), with **zero code changes required in `view_model.py` or `reporting/decision.py`**.

---

## 4. Reviewer Gate Criteria (Chief Architect Audit Checklist)

Every PR submitted by the execution agent (Muse Spark 1.3) will be audited against:
1. **File Boundary Compliance**: Did the PR stay strictly within its assigned track files?
2. **Legacy Snapshot Validator Parity**: Does `scripts/validate_mvp_snapshot.py` continue to pass 100% on existing frozen v1 snapshots (`layout_version="v1"` default unchanged)?
3. **Decision Invariance**: For Track A and Track B (M1), do `QualityGrade` (for valid single-class issuers), `EntryState`, `entry.score`, `ActionState`, and `priority` remain invariant on the B0 parity test suite?
4. **No Bulk Files**: Are all committed test fixtures and preview samples compact (< 100 KB), with full snapshot previews written only to gitignored `outputs/`?
5. **Exact-HEAD CI**: Do all unit tests (`python -m unittest discover -s tests`) pass on the exact PR HEAD?
