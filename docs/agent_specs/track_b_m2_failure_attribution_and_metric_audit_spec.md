# Phase M2 Execution Spec — Systematic v1 Selection Failure Attribution & Metric Validity Audit

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Roadmap Reference**: `docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` (§4 M2)
> **Base `main` Reference**: Post-PR #75 & PR #76 (`ff26ed5`)

---

## 1. Objective

Conduct a strictly offline, read-only **Phase M2 Systematic Failure Attribution & Metric Validity Audit** across the existing frozen datasets:
1. **510-symbol AI Watchlist Snapshot (`2026-10-09`)**: `evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/`
2. **62-symbol 3-Source Generalized Snapshot (`2026-10-12`)**: `outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off/`
3. **39-date Repaired Historical Dataset (`2023-01` to `2026-03`, 25,025 rows)**:
   - Quality dataset: `outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv`
   - Entry dataset: `outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv`
   *(Note: If the local 25k CSVs are absent in a synthetic unit-test environment, the M2 module must support running on synthetic DataFrames while CLI execution uses the real local paths above.)*

The M2 study must quantify **why v1 misallocates human attention or misgrades strong companies**, specifically testing the **4 Fundamental Metric Defects** and **4 Entry / Ranking Mechanism Defects** identified in architectural review, and output the 5 required M2 deliverables under `docs/m2_v1_failure_attribution_20261015/`.

---

## 2. Strict Scope & Shared-Worktree Rules

### Shared-Worktree Safety (CRITICAL):
- You share `/home/ss/opencode_ws/us-ai-stock-scanner` with the Chief Architect.
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make any network requests (no SEC / Alpaca / Modal calls).
- **DO NOT** modify any production scoring logic (`decision/quality.py`, `decision/entry.py`, `decision/action.py`, `scanner.py`) or `configs/*`. M2 is a **diagnostic and attribution phase** that locks the evidence for M3.

### Allowed to Create:
1. `src/ai_value_scanner/research/m2_failure_attribution.py` **(NEW)**
2. `scripts/m2_build_failure_attribution.py` **(NEW)**
3. `tests/test_m2_failure_attribution.py` **(NEW)**
4. `docs/m2_v1_failure_attribution_20261015/` **(NEW directory with 5 compact deliverables + `SHA256SUMS`)**

---

## 3. Specific Mechanisms & Metric Defects to Quantify in `m2_failure_attribution.py`

Implement pure, deterministic diagnostic functions in `src/ai_value_scanner/research/m2_failure_attribution.py` that compute exact counts, rates, and concrete symbol examples for the following **8 diagnostic axes**:

### Axis 1 — `accrual_ratio` Sign-Inversion Bug (`abs(accrual_ratio)` Penalizing Cash-Cow Companies)
- **Mechanism**: In `fundamentals/accounting.py`, `accrual_ratio = (adjusted_net_income - operating_cash_flow) / current_assets`. When `operating_cash_flow > adjusted_net_income` (`accrual_ratio < 0`), cash generation exceeds accounting earnings (healthy!). Yet `decision/quality.py:_score_accrual` takes `abs(value)`, penalizing `accrual_ratio < -0.10` and flagging `accrual_ratio < -0.20` as `accrual_ratio_weak` (score `<= 0.20`).
- **Quantify across `snap510`, `snap62`, and `historical_v3`**:
  - Total rated rows with `accrual_ratio < -0.10` and `accrual_ratio < -0.20` where `ocf_to_net_income >= 1.0` and `free_cash_flow > 0` ("false-positive cash-cow penalty rate").
  - How many companies would upgrade from `Quality B -> A` or `Quality C -> B` if negative accruals (`accrual_ratio <= 0` when `ocf_to_net_income >= 1.0`) scored `1.0` instead of being penalized by `abs()`.
  - Concrete examples (e.g. `META`, `EOG`, `CRM`, `MSFT`, `AMT`, `EQIX`).

### Axis 2 — High-Growth Working-Capital Expansion Penalty (`receivables_growth_gap` / `inventory_growth_gap`)
- **Mechanism**: Point-in-time quarter-end receivables/inventory YoY minus trailing 12-month (TTM) revenue YoY mechanically creates positive gaps for companies experiencing rapid revenue acceleration (`revenue_yoy >= 0.25`) even when cash conversion is healthy (`ocf_to_net_income >= 0.80`).
- **Quantify**:
  - Count and percentage of high-growth companies (`revenue_yoy >= 0.25` and `ocf_to_net_income >= 0.80`) penalized by `receivables_growth_gap > 0.15` or `inventory_growth_gap > 0.20`.
  - How many `Quality B` high-growth leaders (such as `NVDA`, `MU`, `TER`, `AMAT`) would reach `Quality A` (`score >= 0.72` and `confidence >= 0.80`) if working-capital gap penalties were exempted/halved when `revenue_yoy >= 0.25` and `ocf_to_net_income >= 0.80` (combined with the Axis 1 accrual fix).

### Axis 3 — Binary `free_cash_flow > 0` & Self-History Valuation Percentile Drag (`ps_hist_percentile` / `pe_hist_percentile`)
- **Mechanism**:
  1. `_score_fcf` awards `1.0` to any `free_cash_flow > 0` regardless of `fcf_margin` (`free_cash_flow / revenue`).
  2. `ps_hist_percentile > 0.80` and `pe_hist_percentile > 0.80` penalize stocks in sustained multi-year uptrends (scoring `0.10` each).
- **Quantify**:
  - Distribution of `fcf_margin = free_cash_flow / revenue` among rows that currently get `_score_fcf == 1.0` (e.g., how many have thin `< 3%` FCF margin vs strong `>= 15%` FCF margin).
  - Share of `Quality A` and `PRIORITY_REVIEW` stocks flagged with `ps_hist_percentile_weak` or `pe_hist_percentile_weak`.

### Axis 4 — Missing Core Quality Pillars (`operating_margin` & `roic_proxy` / Capital Efficiency)
- **Quantify**:
  - Availability/coverage rate of `operating_margin = adjusted_ebit / revenue` (or `ebit / revenue`) and `fcf_margin = free_cash_flow / revenue` in the historical dataset and current snapshots, demonstrating they can be computed from existing SEC facts with zero new network fetches.

### Axis 5 — Entry Dead-Zone Between `ENTRY_READY` and `WATCH_PULLBACK` (`SMA50 in (1.08, 1.10]` or `return_20d in (12%, 15%]`)
- **Mechanism**: Healthy-trend stocks (`price_to_sma200 >= 1.0`, `return_60d >= 0`, `RS60 >= -3%`, `drawdown <= 22%`) whose only readiness failure is `price_to_sma50 in (1.08, 1.10]` or `return_20d in (0.12, 0.15]` are slightly extended above the buy band, yet fall into `WATCH_BREAKOUT` instead of `WATCH_PULLBACK`.
- **Quantify**:
  - Exact count and symbol list in `snap510`, `snap62` (e.g. `CRM`), and across the 39 historical dates of `WATCH_BREAKOUT` rows that are actually **mildly overextended pullback candidates** rather than pre-breakout bases.

### Axis 6 — `WATCH_BREAKOUT` Heterogeneity Partition (True Near-Breakout vs Weak/Lagging)
- **Quantify**:
  - Partition all `WATCH_BREAKOUT` observations into:
    1. `MILD_EXTENDED_PULLBACK`: passes trend/60d/RS gates, only fails `sma50 > 1.08` or `ret20 > 0.12`;
    2. `NEAR_BREAKOUT_CONSOLIDATION`: `price_to_sma200 >= 1.0` and `return_60d >= -0.03` and `RS60 >= -0.06` (within 3pp of readiness gates);
    3. `WEAK_OR_LAGGING_STRUCTURE`: `price_to_sma200 < 1.0` or `return_60d < -0.03` or `RS60 < -0.06` (e.g. `CAT`, `LIN`).
  - Report counts, shares, and (on the 2023–2024 development dates only, marked `RETROSPECTIVE_EXPLORATORY`) date-equal mean/median 60d net QQQ excess for each sub-bucket conditional on `Quality A/B`.

### Axis 7 — Top-15 Attention Truncation & `Quality B + ENTRY_READY` Suppression
- **Quantify across `snap510`, `snap62`, and the 39 historical dates**:
  - How many dates have `> 15` `PRIORITY_REVIEW` (`A + ENTRY_READY`) candidates, and how many `A + ENTRY_READY` observations are truncated by the 15-name cap;
  - Count of `Quality B + ENTRY_READY` observations (mapped to `HOLD_MONITOR` and ranked behind all `A + WATCH_BREAKOUT` and `A + TREND_DAMAGED`), especially high-score `B` (`quality.score >= 0.65` and `entry.score >= 0.85`, e.g., `NVDA`, `MU`, `TER`, `AMZN`).
  - Compare date-equal 60d net QQQ excess on 2023–2024 development dates (`RETROSPECTIVE_EXPLORATORY`, respecting the 2025/2026Q1 embargo!) between:
    - `Quality A + ENTRY_READY` (Top-15 vs ranks 16+)
    - `Quality B (score >= 0.65) + ENTRY_READY`
    - `Quality A + WATCH_BREAKOUT (WEAK_OR_LAGGING_STRUCTURE)`

### Axis 8 — Missing Technical Structure Features (`sma50_to_sma200` Golden-Cross Alignment & Volume Confirmation)
- **Quantify**:
  - Since `price_to_sma200 = price / sma200` and `price_to_sma50 = price / sma50`, note the exact algebraic identity:
    $$\frac{\text{SMA50}}{\text{SMA200}} = \frac{\text{price\_to\_sma200}}{\text{price\_to\_sma50}}$$
    This means **`sma50_to_sma200` can be computed 100% exactly from existing columns (`price_to_sma200 / price_to_sma50`) on all 25,025 historical rows and all snapshots without fetching a single new bar!**
  - Quantify how many `ENTRY_READY` and `WATCH_BREAKOUT` rows have inverted moving averages (`sma50_to_sma200 < 1.0`, i.e., 50d SMA below 200d SMA) vs aligned uptrends (`sma50_to_sma200 >= 1.0`).

---

## 4. Required Deliverables under `docs/m2_v1_failure_attribution_20261015/`

Your CLI `scripts/m2_build_failure_attribution.py` must deterministically generate these **5 compact files** (total directory size `< 120 KB`, no raw paths `/home/...` or `/tmp/...` anywhere) plus `SHA256SUMS`:

1. **`case_registry_frozen.json`**:
   - Pre-registered stratified case selection contract covering **30–36 fixed cases** across `snap62`, `snap510`, and representative 2023–2024 development dates (covering all 8 axes above, plus positive controls where v1 worked well).
2. **`v1_failure_casebook.csv`**:
   - Must include the canonical M2 schema columns from the roadmap (`study_case_id`, `case_selection_method`, `evidence_tier`, `signal_date`, `symbol`, `snapshot_or_dataset_id`, `quality_grade`, `quality_score`, `confidence`, `entry_state`, `entry_score`, `action_state`, `priority`, `selected_top15`, `primary_failure_axis`, `metric_defect_tags`, `observed_v1_behavior`, `counterfactual_m3_behavior`, `data_verdict`, `reviewer_notes`).
3. **`metric_and_routing_diagnostics.csv`**:
   - Structured quantitative summary table of all **8 Diagnostic Axes** (counts, percentages, affected symbols in `snap62` and `snap510`, and 2023–2024 development-period cohort diagnostics).
4. **`attention_failure_attribution.md`**:
   - Comprehensive, human-readable attribution report presenting the exact empirical findings across the 8 axes:
     - Section 1: Executive Summary & Causal Breakdown
     - Section 2: Fundamental Metric Audit (`accrual_ratio` sign bug, high-growth working-capital penalty, FCF margin vs binary FCF, valuation percentile drag, `operating_margin` coverage)
     - Section 3: Entry & Price-Volume Metric Audit (`(1.08, 1.10]` / `(12%, 15%]` pullback dead-zone, `WATCH_BREAKOUT` 3-way split, `sma50_to_sma200` alignment identity)
     - Section 4: Action Routing & Top-15 Compression Audit (`A+READY` truncation vs `B+READY` suppression vs `A+WATCH_BREAKOUT` weak rows)
5. **`hypothesis_backlog.md`**:
   - Formulate **exactly 3 falsifiable, orthogonal M3 Candidate Hypotheses** backed by the M2 evidence (ready for M3 pre-registration):
     - **H1-Quality (`quality_v2_accounting_core`)**: Fix `accrual_ratio` sign (do not penalize `OCF > NI`), replace binary `FCF > 0` with `fcf_margin` + `operating_margin`, and exempt high-growth cash-generative companies (`revenue_yoy >= 25%` & `OCF/NI >= 0.8`) from point-in-time working-capital gap penalties.
     - **H2-Entry (`entry_v2_structure_and_pullback_seam`)**: Close the `(1.08, 1.10]` SMA50 and `(12%, 15%]` 20d-return dead-zone into `WATCH_PULLBACK`, require `sma50_to_sma200 >= 0.98` for `ENTRY_READY`, and partition `WATCH_BREAKOUT` into `NEAR_BREAKOUT` vs `LAGGING` sub-reasons.
     - **H3-Action (`action_v2_ready_priority_and_joint_rank`)**: Promote high-conviction `Quality B (score >= 0.68, conf >= 0.80) + ENTRY_READY` above unconfirmed `WATCH_BREAKOUT` in attention priority (or surface a dedicated `SECONDARY_READY_REVIEW` slot) and rank within `PRIORITY_REVIEW` by a balanced `0.60 * quality_score + 0.40 * entry_score` composite instead of lexicographic Quality-only tiebreaking.

---

## 5. Strict Statistical & Epistemic Guardrails

- **Respect the 2025 / 2026Q1 Return Embargo**: When reporting any historical forward-return diagnostic from `entry_quality_dataset_risk_off.v3.csv`, compute return statistics **ONLY on the 24 development dates (`2023-01-31` through `2024-12-31`)**! Cross-sectional feature/state counts (without reading `fwd_ret_*`) may be reported across all 39 dates, but **never read or aggregate 2025/2026Q1 forward returns** so the post-2024 period remains unpeeked for M4 validation!
- **No Absolute Paths**: Never output `/home/...` or `/tmp/...` in any generated Markdown, CSV, or JSON file.

---

## 6. Verification Commands

Run locally:
```bash
.venv/bin/python scripts/m2_build_failure_attribution.py
.venv/bin/python -m unittest discover -s tests -p "test_m2_failure_attribution.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass and the 5 deliverables + `SHA256SUMS` are generated in `docs/m2_v1_failure_attribution_20261015/`, stop and report for Chief Architect review.
