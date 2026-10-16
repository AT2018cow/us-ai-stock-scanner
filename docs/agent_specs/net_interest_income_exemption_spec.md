# Agent Specification: Net Interest Income Deduction in Non-Operating Margin Gap (PLTR Exemption)

- **Date**: 2026-10-16
- **Baseline**: `main` @ `d4f775b` (PR #93)
- **Target Execution Agent**: DeepSeek (implementation + unit tests only; no Git state mutations or live network calls)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Problem & Motivation

### 1.1 Structural Net Interest Income on Net-Cash Companies (`PLTR`, `ALAB`)
- Under Layer-1 Case A (`src/ai_value_scanner/decision/quality.py`), `nonoperating_gain_inflation` triggers whenever `raw_net_margin >= 0.12`, `(raw_net_margin - operating_margin) >= 0.05` (`+5.0pp`), and `ocf_to_net_income < 1.50`.
- For debt-free / net-cash companies holding large short-term Treasury bill balances, recurring **Net Interest Income** (`max(0, interest_income - |interest_expense|)`) sits below `OperatingIncomeLoss` (`EBIT`) on the GAAP income statement and is 100% realized in operating cash flow (`OCF/NI > 1.0x`):
  - **`PLTR`**: `raw_net_margin = 49.0%`, `operating_margin = 42.8%` (`raw_gap = +6.2pp`). However, TTM `InvestmentIncomeInterest` is `$266.4M` (`4.3pp` of revenue) against `$3.5M` `InterestExpense` (`net_interest_margin = +4.3pp`, `OCF/NI = 1.13x`). Excluding net interest income, `PLTR`'s unexplained non-operating gap is only **`+1.9pp < 5.0pp`**.
  - **`ALAB` (Astera Labs)**: `raw_net_margin = 30.7%`, `operating_margin = 22.8%` (`raw_gap = +8.0pp`), TTM `InvestmentIncomeInterest = $45.9M` (`+3.8pp` of revenue, `$0` debt) $\rightarrow$ `gap_ex_net_interest = +4.2pp < 5.0pp`.
- Conversely, for all six confirmed equity/tax-gain polluters (`GOOG`, `AMZN`, `ZM`, `NTNX`, `WDC`, `SHOP`), subtracting `net_interest_margin = max(0, interest_income - |interest_expense|) / revenue` leaves every single one above the trigger threshold:
  - `GOOG`: `raw_gap = 21.7pp`, `net_int_margin = 1.1pp` $\rightarrow$ `effective_gap = 20.6pp >= 5.0pp` (caught by Case A + Case C);
  - `AMZN`: `raw_gap = 5.4pp`, `int_inc = $4.66B`, `int_exp = $3.00B` $\rightarrow$ `net_int_margin = 0.2pp` $\rightarrow$ `effective_gap = 5.1pp >= 5.0pp` (caught by Case A + Case C);
  - `ZM`: `raw_gap = 41.5pp`, `net_int_margin = 0.0pp` $\rightarrow$ `effective_gap = 41.5pp >= 5.0pp` (caught by Case A);
  - `NTNX`: `raw_gap = 43.2pp`, `net_int_margin = 0.0pp` $\rightarrow$ `effective_gap = 43.2pp >= 5.0pp` (caught by Case A);
  - `WDC`: `raw_gap = 38.5pp`, `int_inc $51M < int_exp $403M` $\rightarrow$ `net_int_margin = 0.0pp` $\rightarrow$ `effective_gap = 38.5pp >= 5.0pp` (caught by Case A + Case C);
  - `SHOP`: caught by Case C (`35.9% >= 25%`).

---

## 2. Detailed Design

### 2.1 `src/ai_value_scanner/scanner.py` — Extract TTM `interest_income`

1. Near `INTEREST_EXPENSE_TAGS` in `src/ai_value_scanner/scanner.py`, define:
   ```python
   INTEREST_INCOME_TAGS = [
       "InvestmentIncomeInterest",
       "InterestAndDividendIncomeOperating",
       "InvestmentIncomeInterestAndDividend",
       "InterestIncomeOther",
       "InvestmentIncomeNet",
   ]
   ```
2. In `load_one_fundamental` (`src/ai_value_scanner/scanner.py`, right after `interest_expense, interest_expense_prev, _ = pick_flow_pair(INTEREST_EXPENSE_TAGS, "USD")`):
   - Extract:
     ```python
     interest_income, _, _ = pick_flow_pair(INTEREST_INCOME_TAGS, "USD")
     interest_income_pos = (
         max(0.0, float(interest_income))
         if interest_income is not None
         else None
     )
     ```
   - Store `"interest_income": interest_income_pos` in `result` (and `"interest_income": None` in the fallback dict of `collect_fundamentals`, and include `"interest_income"` in the columns passed to `build_company_quality_v2`; do **not** bump `PARSED_FUND_CACHE_VERSION = 9`).

---

### 2.2 `src/ai_value_scanner/decision/quality.py` — Subtract Net Interest Margin in Layer-1 Case A

In `build_company_quality_v2` (`src/ai_value_scanner/decision/quality.py`):
1. Compute `net_interest_margin`:
   ```python
   interest_income_val = _finite_value(work, "interest_income")
   interest_expense_val = _finite_value(work, "interest_expense")
   net_interest_margin = 0.0
   if (
       revenue_value is not None
       and revenue_value > 0.0
       and interest_income_val is not None
       and interest_income_val > 0.0
   ):
       exp_abs = abs(interest_expense_val) if interest_expense_val is not None else 0.0
       net_interest_margin = max(0.0, (interest_income_val - exp_abs) / revenue_value)
   ```
2. In **Layer-1 Case A**:
   - Define `raw_margin_gap = (raw_net_margin - operating_margin_val)` and `effective_margin_gap = raw_margin_gap - net_interest_margin` when `operating_margin_val is not None and raw_net_margin is not None`.
   - Trigger Case A when:
     ```python
     if (
         operating_margin_val is not None
         and raw_net_margin is not None
         and raw_net_margin >= QUALITY_V2_NONOP_NET_MARGIN_FLOOR
         and (raw_net_margin - operating_margin_val - net_interest_margin)
         >= QUALITY_V2_NONOP_MARGIN_GAP_MIN
         and (ocf_value is None or ocf_value < QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI)
     ):
     ```
   - Note: When Case A triggers (`effective_margin_gap >= 0.05`), keep `margin_gap = round(raw_net_margin - operating_margin_val, 6)` and `work["net_margin"] = operating_margin_val` so all existing Case A risk item values and capped margins (`GOOG +21.7pp`, `ZM +41.5pp`, `NTNX +43.2pp`, `AMZN +5.4pp`, `WDC +38.5pp`) remain 100% unchanged!
   - When `effective_margin_gap < 0.05` (e.g., `PLTR` `raw_gap = 6.2pp`, `net_interest_margin = 4.3pp` $\rightarrow$ `effective_margin_gap = 1.9pp < 5.0pp`), Case A does **not** fire, so `PLTR` keeps its clean grade/score with **no** `nonoperating_gain_inflation` risk item, **no** `⚠️NonOp-Gain` badge, and **no** `-0.06` priority penalty!

---

### 2.3 `scripts/render_snapshot_preview.py` & `scripts/audit_nonop_gain_screen.py` — Sync Net Interest Margin

1. In `scripts/render_snapshot_preview.py`:
   - In `_load_local_cache_enrichment`:
     - Read `interest_income = _as_number(payload.get("interest_income"))` and `interest_expense = _as_number(payload.get("interest_expense"))`.
     - If `interest_income is None` and `facts_{cik}.json` exists:
       compute `ttm_int_inc, _ = pick_latest_and_prev_ttm(companyfacts, INTEREST_INCOME_TAGS, "USD")` (importing `INTEREST_INCOME_TAGS` and `pick_latest_and_prev_ttm` from `ai_value_scanner.scanner`)!
     - Compute `net_interest_margin = max(0.0, (max(0.0, interest_income) - abs(interest_expense or 0.0)) / revenue)` when `revenue > 0` and `interest_income is not None`, and store `"net_interest_margin": net_interest_margin` in `enrichment`.
   - In `_with_quality_v2_adjustments`:
     - Read `net_interest_margin = _evidence_or_enrichment("net_interest_margin") or 0.0`.
     - If `nonoperating_gain_inflation` is already in `decision.quality.risks` (e.g. if re-running on an already-flagged decision) OR when evaluating Case A:
       - Require `(net_margin - op_margin - net_interest_margin) >= QUALITY_V2_NONOP_MARGIN_GAP_MIN` for Case A!
       - Also, if an input decision in `decisions.jsonl` was unaffected (frozen v1 had no `nonoperating_gain_inflation`), `PLTR` will now NOT get `nonoperating_gain_inflation` added during `--recompute-v2`!
2. In `scripts/audit_nonop_gain_screen.py`:
   - Also compute `net_interest_margin` (from `payload.get("interest_income")` or `facts_{cik}.json` via `pick_latest_and_prev_ttm(companyfacts, INTEREST_INCOME_TAGS, "USD")`) and pass `(net_margin - operating_margin - net_interest_margin) >= min_ttm_gap` in `_ttm_margin_gap_hit`, and include `"net_interest_margin"` in each audit row dict so `PLTR` and `ALAB` are no longer false-positive hits in `audit_nonop_gain_screen.py`!

---

## 3. Unit Test Requirements

Extend `tests/test_nonoperating_gain_defense.py` with a dedicated `TestNetInterestIncomeExemption` test class covering:
1. **`PLTR` archetype exempted**:
   - `revenue = 5753.0`, `net_margin = 0.490`, `ebit = 2462.0` (`operating_margin = 42.8%`, `raw_gap = +6.2pp`), `interest_income = 266.4`, `interest_expense = 3.5` (`net_interest_margin = 4.57pp` $\rightarrow$ `effective_gap = 1.63pp < 5.0pp`), `ocf_to_net_income = 1.127`:
     - Does **not** emit `nonoperating_gain_inflation`;
     - `net_margin` is **not** capped;
     - No `⚠️NonOp-Gain` badge and no `-0.06` priority penalty.
2. **`GOOG`, `AMZN`, `ZM`, `NTNX`, `WDC` still caught with interest income present**:
   - `GOOG` (`raw_gap = 21.7pp`, `net_interest_margin = 1.1pp` $\rightarrow$ `effective_gap = 20.6pp >= 5.0pp`) still emits `nonoperating_gain_inflation` with value `0.216605`;
   - `AMZN` (`raw_gap = 5.4pp`, `interest_income = 4660.0`, `interest_expense = 3003.0` on `revenue = 775680.0` $\rightarrow$ `net_interest_margin = 0.21pp`, `effective_gap = 5.15pp >= 5.0pp`) still emits `nonoperating_gain_inflation`;
   - `WDC` (`interest_income = 51.0 < interest_expense = 403.0` $\rightarrow$ `net_interest_margin = 0.0`) still emits `nonoperating_gain_inflation`.
3. **Preview `--recompute-v2` & `audit_nonop_gain_screen.py` with `facts_{cik}.json` interest income**:
   - Verify `PLTR` fixture with `InvestmentIncomeInterest` in `facts_{cik}.json` stays unflagged in both `recompute_v2_decisions` and `run_nonop_gain_audit`.
