# Phase M3 Execution Spec — Pre-Registered Quality/Entry/Action v2 Candidates & Non-Return Preflight

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Roadmap Reference**: `docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` (§4 M3)
> **Prerequisite Evidence**: `docs/m2_v1_failure_attribution_20261015/` (38/38 frozen strata matched across `snap62`, `snap510`, and 25,025-row `historical_v3`: 28 `STRATIFIED_PRE`, 6 `POSITIVE_CONTROL`, 4 paired `RETROSPECTIVE_EXPLORATORY`)

---

## 1. Objective

Implement the **3 orthogonal, explainable v2 candidate policies (`H1-Quality`, `H2-Entry`, `H3-Action`)** backed by the Phase M2 empirical attribution, keep `policy_version="v1"` as the 100% invariant default across all production entrypoints, and execute the **M3 Non-Return Preflight & Frozen Casebook Verification** across `snap62`, `snap510`, and the 24 development dates (`2023-01-31..2024-12-31`).

---

## 2. Strict Scope & Shared-Worktree Rules

### Shared-Worktree Safety (CRITICAL):
- You share `/home/ss/opencode_ws/us-ai-stock-scanner` with the Chief Architect.
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make any network calls (no SEC / Alpaca / Modal calls).
- **DO NOT** alter `v1` behavior: `build_company_quality_v1`, `build_entry_quality_v1`, `map_action_state`, `assign_action_priorities`, and `build_stock_decisions(..., policy_version="v1")` must remain 100% bit-for-bit identical to current `main`.
- **DO NOT** touch `decision/view_model.py` or `reporting/decision.py` (Track A files).

### Allowed to Create / Modify:
1. `src/ai_value_scanner/decision/quality.py` **(MODIFY — add `build_company_quality_v2` implementing `H1-Quality`; keep `build_company_quality_v1` unchanged)**
2. `src/ai_value_scanner/decision/entry.py` **(MODIFY — add `build_entry_quality_v2` implementing `H2-Entry`; keep `build_entry_quality_v1` unchanged)**
3. `src/ai_value_scanner/decision/action.py` **(MODIFY — add `map_action_state_v2` and `assign_action_priorities_v2` implementing `H3-Action`; keep v1 functions unchanged)**
4. `src/ai_value_scanner/decision/integrated.py` **(MODIFY — add optional keyword argument `policy_version: str = "v1"` or separate `quality_version: str = "v1"`, `entry_version: str = "v1"`, `action_version: str = "v1"` to `build_stock_decisions` so `v1`, `h1_only`, `h2_only`, `h3_only`, and `v2_combined` can be run cleanly)**
5. `src/ai_value_scanner/research/m3_candidate_preflight.py` **(NEW — pure preflight evaluation & casebook verification module)**
6. `scripts/m3_run_candidate_preflight.py` **(NEW — deterministic CLI producing `docs/m3_candidate_preflight_20261015/`)**
7. `tests/test_m3_candidate_preflight.py` **(NEW — unit tests for `H1`, `H2`, `H3`, `v1` invariance, 2025/2026Q1 embargo, and control-case preservation)**
8. `docs/m3_candidate_preflight_20261015/` **(NEW directory with 5 compact deliverables + `SHA256SUMS`, total `< 120 KB`)**

---

## 3. Exact Mathematical Specification of the 3 Candidate Policies

### 3.1 `H1-Quality` (`build_company_quality_v2` in `src/ai_value_scanner/decision/quality.py`)

Keep the 6-pillar structure, pillar weights, and grade thresholds (`A: score >= 0.72, conf >= 0.80`; `B: score >= 0.52, conf >= 0.60`; specialist accounting unrated guard) identical to v1, while fixing the 4 empirically proven fundamental metric defects:

1. **Fix 1 — Sign-Aware Accrual Scoring (`_score_accrual_v2`)**:
   - In accounting (`accrual_ratio = (adjusted_net_income - operating_cash_flow) / current_assets`), negative accruals (`accrual_ratio <= 0.0`) mean operating cash flow exceeds accounting net income.
   - Define `_score_accrual_v2(value: float, ocf_to_ni: float | None = None) -> float`:
     - If `value <= 0.0`:
       - When `ocf_to_ni is None or ocf_to_ni >= 0.80`: return `1.0` (cash-backed earnings; never penalize negative accrual when cash conversion is healthy!).
       - When `ocf_to_ni < 0.80`: return `_score_accrual(value)` (fallback if both NI and OCF are negative/distorted).
     - If `value > 0.0` (earnings exceed operating cash flow):
       - `value <= 0.05 -> 1.0`
       - `value <= 0.10 -> 0.80`
       - `value <= 0.20 -> 0.50`
       - `value <= 0.35 -> 0.20`
       - `value > 0.35 -> 0.0`
   - Threshold text: `"<=0 (with OCF/NI>=0.8) or <=0.10 supportive; >0.35 weak"`.

2. **Fix 2 — Scale-Normalized `fcf_margin` + `operating_margin` in `profitability_and_cash_conversion`**:
   - Compute `fcf_margin = free_cash_flow / revenue` when `revenue is not None and revenue > 0` and `free_cash_flow is not None`.
     - Score `_score_fcf_margin(margin: float) -> float`:
       - `margin >= 0.15 -> 1.0`
       - `margin >= 0.08 -> 0.85`
       - `margin >= 0.03 -> 0.65`
       - `margin > 0.0 -> 0.40`
       - `margin > -0.05 -> 0.20`
       - `margin <= -0.05 -> 0.0`
     - **Graceful fallback for partial snapshot dicts**: If `revenue` is not present in `metrics` (e.g., when re-evaluating a pre-M1 `decisions.jsonl` dict that only stored `free_cash_flow`), fall back to `_assess_numeric_metric` on `free_cash_flow` with `_score_fcf` so confidence is not artificially reduced on partial snapshot dicts. When `revenue > 0` is present, assess `fcf_margin` (metric key `"fcf_margin"`, label `"FCF margin"`, `strong_score=0.80`, `weak_score=0.25`, `threshold_text=">=8% supportive; <=0% weak"`).
   - Compute `operating_margin = ebit_val / revenue` when `revenue is not None and revenue > 0` and `ebit_val = adjusted_ebit if adjusted_ebit is not None else ebit` is not None.
     - Score `_score_operating_margin(margin: float) -> float`:
       - `margin >= 0.20 -> 1.0`
       - `margin >= 0.12 -> 0.80`
       - `margin >= 0.05 -> 0.55`
       - `margin >= 0.0 -> 0.30`
       - `margin < 0.0 -> 0.0`
     - When `operating_margin` is computable, include it as an additional metric inside `profitability_cash_scores` (metric key `"operating_margin"`, label `"Operating margin"`, `strong_score=0.80`, `weak_score=0.25`, `threshold_text=">=12% supportive; <0% weak"`). If `revenue` or `ebit` is absent from `metrics`, do not append a missing-metric penalty so `confidence` denominator stays compatible with partial dicts.

3. **Fix 3 — High-Growth Cash-Generative Working-Capital Gap Exemption (`red_flags` pillar)**:
   - Define `is_high_growth_cash_generative = (revenue_yoy is not None and revenue_yoy >= 0.25 and ocf_to_net_income is not None and ocf_to_net_income >= 0.80)`.
   - When `is_high_growth_cash_generative` is `True`:
     - Score `receivables_growth_gap` as `max(_score_receivables_gap(val), 0.75)` and `inventory_growth_gap` as `max(_score_inventory_gap(val), 0.75)` so rapid top-line expansion backed by strong cash collection (`OCF/NI >= 0.80`) never triggers a false `receivables_growth_gap_weak` or `inventory_growth_gap_weak` risk or drags down `Quality A`.

4. **Fix 4 — Softened Self-History Valuation Percentile Drag for Cash-Generative Compounders**:
   - When `fcf_yield is not None and fcf_yield >= 0.02` (or `is_high_growth_cash_generative` is `True`), score `ps_hist_percentile` and `pe_hist_percentile` with a floor of `0.35` (instead of `0.10`, and `weak_score=0.25` is not triggered), preventing secular compounders at 52-week highs with healthy FCF yield/growth from accumulating redundant self-history valuation risk flags.

---

### 3.2 `H2-Entry` (`build_entry_quality_v2` in `src/ai_value_scanner/decision/entry.py`)

Keep the 5 canonical `EntryState` enum values (`ENTRY_READY`, `WATCH_PULLBACK`, `WATCH_BREAKOUT`, `TREND_DAMAGED`, `INSUFFICIENT_DATA`) and the 4 pillar weights unchanged, while fixing the 3 entry structure defects proven in M2:

1. **Fix 1 — Close the `(1.08, 1.10]` SMA50 and `(12%, 15%]` `return_20d` Pullback Seam**:
   - Compute `sma50_to_sma200 = price_to_sma200 / price_to_sma50` when both `price_to_sma200` and `price_to_sma50` are finite and `price_to_sma50 > 0`.
   - Require `ma_alignment_ok = (sma50_to_sma200 is not None and sma50_to_sma200 >= 0.98)` in `entry_ready`.
   - Define `core_uptrend_ready_except_extension`:
     - `price_to_sma200 >= 1.0`
     - `ma_alignment_ok` (`sma50_to_sma200 >= 0.98`)
     - `days_below_sma200 is None or days_below_sma200 <= 3`
     - `return_60d >= 0.0`
     - `relative_strength_60d_qqq >= -0.03`
     - `drawdown_from_52w_high <= 0.22`
     - `volatility_ok` (`volatility_60d is None or volatility_60d <= 0.80`)
     - `defensive_entry_ok`
     - `price_to_sma50 >= 0.98` and `return_20d >= -0.03`
     - AND `(price_to_sma50 > 1.08 or return_20d > 0.12)`
   - Route `overextended or core_uptrend_ready_except_extension` to **`EntryState.WATCH_PULLBACK`**!
   - This eliminates the `(1.08, 1.10]` and `(12%, 15%]` dead zone so mildly extended uptrend stocks (411 dev observations in M2) are properly classified as `WATCH_PULLBACK` instead of `WATCH_BREAKOUT`.

2. **Fix 2 — Moving-Average Alignment Evidence (`sma50_to_sma200`)**:
   - When `sma50_to_sma200 is not None`:
     - If `sma50_to_sma200 >= 1.0`: emit positive `EvidenceItem(code="sma50_above_sma200_aligned", label="SMA50 / SMA200 alignment", metric="sma50_to_sma200", value=sma50_to_sma200, threshold=">=1.00 golden-cross alignment", direction="positive", summary=f"50d SMA is {sma50_to_sma200:.2f}x 200d SMA (aligned uptrend).")`.
     - If `sma50_to_sma200 < 0.98`: emit negative `EvidenceItem(code="sma50_below_sma200_inverted", label="SMA50 / SMA200 alignment", metric="sma50_to_sma200", value=sma50_to_sma200, threshold=">=0.98 required for ENTRY_READY", direction="negative", summary=f"50d SMA is {sma50_to_sma200:.2f}x 200d SMA (inverted medium/long trend blocks ENTRY_READY).")`.

3. **Fix 3 — Explicit `WATCH_BREAKOUT` Sub-Bucket Differentiation (`NEAR_BREAKOUT` vs `LAGGING_STRUCTURE`)**:
   - When `state == EntryState.WATCH_BREAKOUT`:
     - Check if structure is near-breakout (`price_to_sma200 >= 1.0` and `return_60d >= -0.03` and `relative_strength_60d_qqq >= -0.06` and `(sma50_to_sma200 is None or sma50_to_sma200 >= 0.98)`):
       - If True: include `"near-breakout consolidation"` in `summary`.
       - If False (i.e. `WEAK_OR_LAGGING_STRUCTURE`): apply a `0.10` score penalty (`score = max(0.0, round(score - 0.10, 6))`) and include `"lagging structure below breakout readiness"` in `summary` so genuine near-breakout consolidations always rank above lagging `WATCH_BREAKOUT` names!
   - Also preserve all M1 silent-gate negative `EvidenceItem`s so every non-`ENTRY_READY` stock has explicit blocking risk items.

---

### 3.3 `H3-Action` (`map_action_state_v2` & `assign_action_priorities_v2` in `src/ai_value_scanner/decision/action.py`)

Keep the 5 canonical `ActionState` enum values unchanged, while fixing the Top-15 ranking and `B + ENTRY_READY` suppression proven in M2:

1. **`map_action_state_v2(quality: QualityDecision, entry: EntryDecision) -> tuple[ActionState, list[str]]`**:
   - Identical to `map_action_state` **except** for one targeted, pre-registered rule:
     - When `quality.grade == QualityGrade.B` and `(quality.score or 0.0) >= 0.68` and `quality.confidence >= 0.80` and `entry.state == EntryState.ENTRY_READY` and `(entry.score or 0.0) >= 0.80`:
       - Map to **`ActionState.PRIORITY_REVIEW`** with rationale:
         `"High-conviction Company Quality B (score >= 0.68, confidence >= 0.80) with confirmed Entry Ready setup qualifies for Priority Review."`
     - All other `(QualityGrade, EntryState)` combinations map to the exact same `ActionState` as v1.

2. **`assign_action_priorities_v2(decisions: Iterable[StockDecision]) -> list[StockDecision]`**:
   - Rank decisions by:
     1. `_ACTION_ORDER[decision.action_state]` (`PRIORITY_REVIEW -> WATCH_PULLBACK -> WATCH_BREAKOUT -> HOLD_MONITOR -> AVOID`)
     2. Inside `PRIORITY_REVIEW`: rank by descending **joint conviction composite**:
        $$\text{joint\_score} = 0.60 \times \text{quality.score} + 0.40 \times \text{entry.score} + \mathbb{I}(\text{quality.grade} == \text{A}) \times 0.04$$
        *(This ensures strong `Quality A + ENTRY_READY` with solid entries remain at the top, while an `A + ENTRY_READY` with a `0.98` entry setup ranks ahead of a marginal `A` with a weaker `0.70` entry, and a promoted `B + ENTRY_READY` must have an exceptional combined score to enter Top-15.)*
     3. Inside `HOLD_MONITOR`: rank `EntryState.ENTRY_READY` (e.g. lower-score `B + ENTRY_READY`) **ahead of** `EntryState.TREND_DAMAGED` (e.g. `A + TREND_DAMAGED`), then by descending `0.60 * quality.score + 0.40 * entry.score`.
     4. Inside `WATCH_PULLBACK`, `WATCH_BREAKOUT`, and `AVOID`: rank by `_QUALITY_ORDER[decision.quality.grade]`, then descending `0.60 * quality.score + 0.40 * entry.score`, then `symbol`.

---

## 4. Wiring in `src/ai_value_scanner/decision/integrated.py`

Add optional version selectors to `build_stock_decisions` with `"v1"` defaults:
```python
def build_stock_decisions(
    frame: pd.DataFrame,
    *,
    decision_date: str | date | None = None,
    generated_at_utc: str | None = None,
    policy_version: str = "v1",
    quality_version: str | None = None,
    entry_version: str | None = None,
    action_version: str | None = None,
) -> list[StockDecision]:
```
- When `policy_version == "v1"` and the per-stage versions are `None`, use `"v1"` for all 3 stages (100% backward compatible).
- When `policy_version == "v2"`, default all 3 stages to `"v2"` unless overridden by `quality_version`, `entry_version`, or `action_version`.
- Valid stage versions are `"v1"` and `"v2"`; raise `ValueError` on unknown version strings.

---

## 5. Required M3 Deliverables under `docs/m3_candidate_preflight_20261015/`

Implement `src/ai_value_scanner/research/m3_candidate_preflight.py` and `scripts/m3_run_candidate_preflight.py` to evaluate the **5 pre-registered variants**:
- `v1_baseline` (`q=v1, e=v1, a=v1`)
- `h1_quality_only` (`q=v2, e=v1, a=v1`)
- `h2_entry_only` (`q=v1, e=v2, a=v1`)
- `h3_action_only` (`q=v1, e=v1, a=v2`)
- `v2_combined` (`q=v2, e=v2, a=v2`)

across `snap62`, `snap510` (rebuilding from `decisions.jsonl` feature maps or raw historical rows where full facts exist; note that for `snap62` and `snap510`, also support rebuilding from the cached/emitted feature maps in `m2_failure_attribution.snapshot_frame` so `snap62` and `snap510` can be evaluated offline), and the **24 development dates (`2023-01-31..2024-12-31`)** of `historical_v3`.

Generate these **5 compact files + `SHA256SUMS`** (total size `< 120 KB`, zero `/home/...` or `/tmp/...` paths):

1. **`m3_preregistration_protocol.json`**:
   - Records the exact parameters, stage versions, falsifiers, and the 2025/2026Q1 return embargo declaration for the 5 variants.
2. **`m3_preflight_comparison.csv`**:
   - Side-by-side comparison across the 5 variants on `snap62`, `snap510`, and `hist_dev_24_dates`:
     - Grade counts (`n_quality_a`, `n_quality_b`, `n_quality_c`, `n_unrated`)
     - Entry state counts (`n_entry_ready`, `n_watch_pullback`, `n_watch_breakout`, `n_trend_damaged`)
     - Action state counts (`n_priority_review`, `n_watch_pullback_action`, `n_watch_breakout_action`, `n_hold_monitor`, `n_avoid`)
     - Defect resolution counts:
       - `n_cash_cow_accrual_weak` (Axis 1 false positives remaining)
       - `n_high_growth_wc_penalized_b` (Axis 2 penalized high-growth B rows remaining)
       - `n_dead_zone_in_watch_breakout` (Axis 5 dead-zone pullbacks remaining in `WATCH_BREAKOUT`)
       - `n_inverted_ma_in_entry_ready` (Axis 8 `sma50_to_sma200 < 0.98` in `ENTRY_READY`)
       - `mean_top15_jaccard_vs_v1` (Top-15 turnover / Jaccard similarity vs `v1_baseline` across the 24 dev dates)
     - Exploratory 2023–2024 dev-period date-equal 60d net QQQ excess (`RETROSPECTIVE_EXPLORATORY`) for `TOP15`, `PRIORITY_REVIEW`, `QUALITY_A`, and `ENTRY_READY`.
3. **`m3_casebook_verification.csv`**:
   - Re-evaluates all **38 frozen cases** from `docs/m2_v1_failure_attribution_20261015/case_registry_frozen.json` under `v1_baseline`, `h1_quality_only`, `h2_entry_only`, `h3_action_only`, and `v2_combined`, recording `v1_outcome`, `v2_outcome`, `failure_resolved` (`TRUE`/`FALSE`/`CONTROL_PRESERVED`), and verifying **100% preservation of the 6 positive control cases (`M2-C-*`)**.
4. **`m3_top15_diff_snap62_and_snap510.csv`**:
   - Concrete symbol-level Top-15 membership comparison between `v1_baseline` and `v2_combined` on `snap62`, `snap510`, and sample development dates (`2023-01-31`, `2024-06-28`, `2024-12-31`), showing which stocks enter/exit Top-15 and why.
5. **`m3_preflight_report.md`**:
   - Concise engineering & research preflight report summarizing:
     - Variant-by-variant non-return gate results;
     - Exact defect reduction rates (Axes 1, 2, 5, 6, 7, 8);
     - Verification of the 38 frozen M2 cases + 6 positive controls;
     - Readiness recommendation for Phase M4 (formal 2025/2026Q1 held-out comparative validation).

---

## 6. Verification Commands

Run locally:
```bash
.venv/bin/python scripts/m3_run_candidate_preflight.py
.venv/bin/python -m unittest discover -s tests -p "test_m3_candidate_preflight.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass and `docs/m3_candidate_preflight_20261015/` is generated, stop and report for Chief Architect review.
