# Track A Execution Spec — Intermediate View Model & Human-Readable Report v2

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Branch Name**: `feature/report-readability-v2-view-model-20261014`
> **Architecture Contract**: Read `docs/agent_specs/00_parallel_tracks_and_view_ir_contract.md` first.

---

## 1. Objective

Transform the user-facing **Daily Action List**, **Weekly Review List**, and **Detailed Report** from raw debug-style key-value dumps into an intuitive, scannable **English tabular dashboard with human-formatted numbers** (`$15.15B`, `+23.6%`, `1.03x`, `100th pctl`), while:
1. Introducing the decoupled intermediate presentation layer (`src/ai_value_scanner/decision/view_model.py`);
2. Keeping `layout_version="v1"` as the default in `render_action_list()` and `render_detailed_report()` so all existing snapshot validators (`scripts/validate_mvp_snapshot.py`) and existing unit tests pass without modification;
3. Providing a standalone preview CLI (`scripts/render_snapshot_preview.py`) that renders any frozen snapshot directory (such as `2026-10-09` 510-stock or `2026-10-12` 62-stock) into `v2` Markdown files under `outputs/` for side-by-side human inspection.

---

## 2. Strict Scope & File Boundaries

### Allowed to Create or Modify:
1. `src/ai_value_scanner/decision/view_model.py` **(NEW)**
2. `src/ai_value_scanner/reporting/decision.py` **(MODIFY — additive `layout_version="v2"` support)**
3. `scripts/render_snapshot_preview.py` **(NEW)**
4. `tests/test_decision_view_model_and_report_v2.py` **(NEW)**

### Strictly Forbidden to Modify:
- Any file under `src/ai_value_scanner/fundamentals/`
- `src/ai_value_scanner/decision/{model,quality,entry,action,integrated,universe,discovery}.py`
- `src/ai_value_scanner/scanner.py`, `src/ai_value_scanner/backtest.py`, `configs/*`
- Any frozen snapshot under `evidence/`

---

## 3. Detailed Implementation Requirements

### 3.1 Intermediate Layer: `src/ai_value_scanner/decision/view_model.py`

Implement the dataclasses and pure functions specified in `docs/agent_specs/00_parallel_tracks_and_view_ir_contract.md` (§3):

1. **`format_metric_value(metric: str | None, value: Any) -> str`**:
   - Format monetary metrics (`free_cash_flow`, `operating_cash_flow`, `revenue`, `net_income`, `total_debt`, `net_debt`, `cash_and_equivalents`, `market_cap`) as `$X.XXB` (`>= 1e9`), `$X.XM` (`>= 1e6`), or `$X,XXX`, preserving negative signs (`-$875.0M`).
   - Format signed growth/return/RS/gap metrics (`revenue_yoy`, `adjusted_net_income_yoy`, `operating_cash_flow_yoy`, `shares_yoy`, `return_20d`, `return_60d`, `relative_strength_60d_qqq`, `receivables_growth_gap`, `inventory_growth_gap`) as signed percentages (`+23.9%`, `-4.7%`).
   - Format unsigned/level percentages (`net_margin`, `accrual_ratio`, `fcf_yield`, `drawdown_from_52w_high`, `volatility_60d`) as `16.8%`, `-24.3%`.
   - Format percentiles (`ps_hist_percentile`, `pe_hist_percentile`) as `100th pctl`, `25th pctl`, and `range_position_52w` as `60% of 52w range`.
   - Format multiples/ratios (`price_to_sma200`, `price_to_sma50`, `ocf_to_net_income`, `net_debt_to_ebitda`, `interest_coverage`, `current_ratio`) as `1.03x`, `61.40x`.
   - Format day counts (`fundamental_data_age_days`, `market_data_age_days`, `days_below_sma200`) as `0d`, `46d`.
   - Never output raw floats like `15154000000.0` or `0.236287` in human-facing summaries.

2. **`build_stock_card_view_model(decision: StockDecision) -> StockCardViewModel`**:
   - **6-Pillar Quality Breakdown (`quality_pillars`)**:
     Map `decision.quality.component_scores` and quality `positives`/`risks`/`missing` into the 6 canonical pillars in fixed order:
     1. `profitability_cash` ("Profitability & Cash Conversion": `net_margin`, `free_cash_flow`, `ocf_to_net_income`, `accrual_ratio`)
     2. `growth_stability` ("Growth & Stability": `revenue_yoy`, `adjusted_net_income_yoy`, `operating_cash_flow_yoy`)
     3. `balance_sheet` ("Balance Sheet & Solvency": `net_debt_to_ebitda`, `interest_coverage`, `current_ratio`)
     4. `dilution` ("Share Count & Dilution": `shares_yoy`)
     5. `valuation_context` ("Valuation Context": `fcf_yield`, `ps_hist_percentile`, `pe_hist_percentile`)
     6. `operating_red_flags` ("Operating & Accounting Red Flags": `receivables_growth_gap`, `inventory_growth_gap`, plus freshness/coverage items)
   - **Entry Readiness Gate Checklist (`entry_checklist`)**:
     Construct 7 standardized gate rows (`freshness`, `sma200_trend`, `sma50_band`, `ret20_band`, `ret60_trend`, `rs60_qqq`, `regime`):
     - If a corresponding positive `EvidenceItem` is present (e.g., `price_above_sma200`, `price_near_sma50_ready_band`, `return_20d_ready_band`, `return_60d_nonnegative`, `relative_strength_60d_qqq_ready`, `supportive_market_regime`), mark `status="PASS"` with the formatted value.
     - If a corresponding negative/missing `EvidenceItem` is present (including both v1 codes like `price_below_sma50`, `return_60d_weak`, `relative_strength_60d_qqq_weak`, `price_extended_above_sma50`, `return_20d_overextended` AND Track B M1 codes like `days_below_sma200_elevated`, `price_below_sma200_trend`, `price_to_sma50_outside_ready_band`, `return_20d_outside_ready_band`, `return_60d_slightly_negative`, `relative_strength_60d_qqq_below_ready`, `drawdown_from_52w_high_deep`), mark `status="FAIL_BLOCKER"` with the formatted value.
     - If `decision.entry.state != EntryState.ENTRY_READY` and a readiness gate has neither a positive nor negative item in the snapshot (the legacy silent-band case on `CRM`, `TXN`, `PG`, `GOOGL`, `ISRG`), mark `status="SILENT_OR_UNOBSERVED"` with `observed_display="Not in READY band (silent in v1)"` so the reviewer explicitly sees which gate did not confirm `ENTRY_READY`!
   - **Top Inline Summaries (`top_positives_inline`, `top_risks_or_blockers_inline`)**:
     - Concise, human-formatted strings suitable for a Markdown table cell (e.g., `"Net margin 23.6%, FCF $15.15B"` and `"P/S 100th pctl; Entry blocker: RS60 / ret20 not in READY band"`).
     - **Critical rule**: If `decision.action_state != ActionState.PRIORITY_REVIEW` and `top_risks_or_blockers_inline` would otherwise be `"none"`, populate it with the unmet Entry gate names (e.g. `"Unmet READY gate(s): ret20_band"` for `CRM`, `"Unmet READY gate(s): rs60_qqq"` for `PG`/`GOOGL`). Never display `"none"` as the risk/blocker for a `WATCH_BREAKOUT` or `TREND_DAMAGED` stock!

3. **`build_snapshot_view_model(...) -> SnapshotViewModel`**:
   - Accepts `primary_decisions: Iterable[StockDecision]`, optional `all_decisions: Iterable[StockDecision] | None = None`, `title: str`, `cadence: str | None`, and `attention_cap: int = 15`.
   - When `all_decisions` is provided:
     - Populate `cap_omitted_priority_cards`: up to 5 decisions with `action_state == ActionState.PRIORITY_REVIEW` that are not in `primary_decisions` (ordered by priority).
     - Populate `secondary_b_ready_cards`: up to 5 decisions with `quality.grade == QualityGrade.B` and `entry.state == EntryState.ENTRY_READY` (ordered by priority).

---

### 3.2 Renderer Upgrade: `src/ai_value_scanner/reporting/decision.py`

1. Keep existing `render_action_list(decisions, *, title="Action List", cadence=None, layout_version="v1", all_decisions=None)` and `render_detailed_report(decision, *, layout_version="v1")`:
   - When `layout_version == "v1"` (the default), execute the exact existing rendering code path (100% byte-identical output).
   - When `layout_version == "v2"`, delegate to `render_action_list_v2(...)` and `render_detailed_report_v2(...)` backed by `view_model.py`.
2. **`render_action_list_v2` Layout**:
   - **Section 1: Header & Snapshot Summary** (Decision date, cadence, count by Action State).
   - **Section 2: One-Page Executive Shortlist Table** (Markdown table of the primary shortlist):
     `| Rank | Symbol | Company | Action | Quality | Entry | Key Bullish Evidence | Key Risk / Readiness Blocker | Next Review Trigger |`
   - **Section 3: Secondary Radar (Off-List Watch)** (rendered when `cap_omitted_priority_cards` or `secondary_b_ready_cards` is non-empty, or a 1-line note when empty):
     - Sub-table A: *Cap-Omitted `PRIORITY_REVIEW` (`Quality A + ENTRY_READY` beyond Top-15 cap)*
     - Sub-table B: *Top `Quality B + ENTRY_READY` Candidates (Currently mapped to `HOLD_MONITOR`)*
   - **Section 4: Concise Per-Stock Cards** for the primary shortlist (using formatted values, clear Entry checklist blockers, and link to `detailed/{SYMBOL}.md`).
3. **`render_detailed_report_v2` Layout**:
   - **Section 1: Executive Decision Banner Table** (`Symbol`, `Action State`, `Priority Rank`, `Company Quality (Grade / Score / Confidence)`, `Entry Quality (State / Score / Confidence)`, `Data As-Of (Fund / Mkt)`, `Filing Entity & CIK`, `Data Trust Badge`).
   - **Section 2: Attention Alerts & Next Review Trigger** (highlighted callout bullets).
   - **Section 3: Company Quality — 6-Pillar Scorecard Table**:
     `| Pillar | Score | Status | Supporting Evidence (Formatted) | Risks & Missing Metrics (Formatted) |`
   - **Section 4: Entry Quality — Readiness Gate Checklist Table**:
     `| Readiness Gate | Status | Observed Value | Required Band for ENTRY_READY | Notes |`
   - **Section 5: Complete Counter-Evidence & Missing Data Inventory** (formatted table, never raw dicts).
   - **Section 6: Quality Applicability, Decision History & Provenance**.

---

### 3.3 Preview CLI: `scripts/render_snapshot_preview.py`

Create a read-only CLI script:
```bash
python scripts/render_snapshot_preview.py \
  --snapshot-dir outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off \
  --output-dir outputs/report_v2_preview_20261014/snap62
```
- Reads `decisions.jsonl` and `run_manifest.json` from `--snapshot-dir` without modifying anything in `--snapshot-dir`.
- Writes `action_list_v2.md`, `weekly_review_v2.md`, and `detailed_v2/{SYMBOL}.md` (for daily/weekly symbols plus any Secondary Radar symbols) into `--output-dir`.

---

## 4. Required Unit Tests (`tests/test_decision_view_model_and_report_v2.py`)

Write comprehensive unit tests covering:
1. `format_metric_value`: billions (`$15.15B`), negative millions (`-$875.0M`), signed growth (`+23.9%`), margins (`16.8%`), percentiles (`100th pctl`), multiples (`1.03x`), days (`46d`), and `None` (`"n/a"`).
2. Silent-gate detection in `view_model.py`: verify that a `WATCH_BREAKOUT` decision with 0 Entry risk items (like `CRM` or `PG`) produces `SILENT_OR_UNOBSERVED` checklist rows and a non-empty `top_risks_or_blockers_inline` (never `"none"`).
3. Forward compatibility with Track B M1 codes: verify that when `entry.risks` contains M1 codes (`relative_strength_60d_qqq_below_ready`, `days_below_sma200_elevated`, `price_to_sma50_outside_ready_band`), `entry_checklist` upgrades those rows to `FAIL_BLOCKER` with formatted values.
4. Secondary Radar extraction: verify `cap_omitted_priority_cards` (ranks > 15 `PRIORITY_REVIEW`) and `secondary_b_ready_cards` (`Quality B + ENTRY_READY`) are populated accurately when `all_decisions` is passed.
5. `layout_version="v1"` backward compatibility: verify `render_action_list(decisions)` and `render_detailed_report(decision)` with default arguments remain 100% byte-identical to `layout_version="v1"`.
6. CLI preview smoke test in a temporary directory.

---

## 5. Verification & PR Submission Checklist

Run locally before opening the PR:
```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/render_snapshot_preview.py \
  --snapshot-dir evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff \
  --output-dir outputs/report_v2_preview_20261014/snap510
```
- Confirm `git status` shows **no untracked files committed from `outputs/`** and **no edits outside Track A's allowed file list**.
- Open PR against `main` and ensure GitHub Actions CI passes on the exact PR HEAD.
