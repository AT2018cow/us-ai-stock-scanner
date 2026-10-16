# Non-Operating Investment Gain & Tax Distortion Defense Spec (Three-Layer Architecture)

> **Target Agent**: DeepSeek (Execution Agent)
> **Reviewer**: Chief Technical Lead / Architect
> **Reference Audit**: `docs/review_nonoperating_investment_gain_blind_spot_20261016.md`
> **Base `main` Reference**: Post-PR #89 (`e959061`)

---

## 1. Problem Statement & Architectural Root Cause

As documented in `docs/review_nonoperating_investment_gain_blind_spot_20261016.md` and verified against `cache/parsed_fund_*.json`, several companies in the candidate universe booked massive below-the-line non-operating investment gains or one-time tax valuation allowance releases that inflated GAAP `net_income`, `net_margin`, and `adjusted_net_income_yoy` without increasing `OperatingIncomeLoss` (`ebit`) or `OperatingCashFlow` (`ocf`):

| Symbol | Reported `net_margin` | Clean `operating_margin` | Margin Gap (`nm - om`) | `OCF / NI` | Reported `NI YoY` | Clean `EBIT YoY` | Root Cause in SEC 10-Q/10-K |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`GOOG`** | `55.7%` | `34.0%` | **`+21.7pp`** | `0.748x` (silent!) | `+114.7%` | `+24.9%` | `$99.0B` Anthropic equity security gain (`EquitySecuritiesFvNiGainLoss`) |
| **`ZM`** | `65.2%` | `23.7%` | **`+41.5pp`** | `0.614x` (silent!) | `+174.0%` | `+22.0%` | `$1.77B` Anthropic strategic investment gain (`GainLossOnInvestments`) |
| **`NTNX`** | `52.8%` | `9.6%` | **`+43.2pp`** | `0.608x` (silent!) | `+700.0%` | `+58.8%` | `$1.18B` deferred tax valuation allowance release (`IncomeTaxExpenseBenefit < 0`) |
| **`WDC`** | `74.1%` | `35.7%` | **`+38.5pp`** | `0.410x` | `+432.9%` | `+105.4%` | `$2.73B` SanDisk spin-off retained interest remeasurement |
| **`AMZN`** | `17.6%` | `12.2%` | **`+5.4pp`** | `1.182x` | `+93.3%` | `+24.6%` | `$53.4B` Anthropic preferred stock upward adjustment |
| **`SHOP`** | `15.1%` | `14.5%` | `+0.6pp` | `1.183x` | **`-15.4%`** | **`+51.3%`** | Prior-year equity gain base effect depressing current `NI YoY` despite `+51.3%` `EBIT YoY` |

### Critical Accounting Trap to Avoid:
In `src/ai_value_scanner/fundamentals/accounting.py` (lines 111–112):
```python
adjusted_net_income = _adjust(net_income, addback, gain)
adjusted_ebit = _adjust(ebit, addback, gain)
```
`NONRECURRING_GAIN_TAGS` is subtracted from **both `net_income` AND `ebit` (`OperatingIncomeLoss`)**. Below-the-line investment gains (`EquitySecuritiesFvNiGainLoss`, `GainLossOnInvestments`, etc.) are NOT inside `OperatingIncomeLoss`. Putting below-the-line investment gain tags into `NONRECURRING_GAIN_TAGS` would falsely subtract `$99B` from `GOOG`'s clean `$40.8B` `ebit`, corrupting `adjusted_ebit` and `operating_margin`!

Therefore, we implement a **Three-Layer Tag-Agnostic Defense** that works for all current and future companies regardless of what XBRL tag they use for below-the-line investment gains or tax benefits.

---

## 2. Shared-Worktree Safety & Allowed Files

### Shared-Worktree Rules:
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** touch or modify anything under `outputs/decisions/`.
- **DO NOT** make any live network calls in unit tests (`python -m unittest`).
- Never output absolute filesystem paths (`/home/...` or `/tmp/...`) in any generated file.

### Allowed to Modify / Create:
1. `src/ai_value_scanner/scanner.py` **(MODIFY — add `"DisposalGroupNotDiscontinuedOperationGainLossOnDisposal"` to `NONRECURRING_GAIN_TAGS`)**
2. `src/ai_value_scanner/decision/quality.py` **(MODIFY — in `build_company_quality_v2` only: implement Layer 1 `nonoperating_gain_inflation` detection + operating-basis de-pollution of `net_margin` and `earnings_growth`, and Layer 2 `ocf_conversion_lagging_high_margin` risk item for `(0.25, 0.80)` OCF/NI when `net_margin >= 20%`; keep `build_company_quality_v1` 100% untouched)**
3. `src/ai_value_scanner/decision/action.py` **(MODIFY — in `assign_action_priorities_v2`: apply `H3_NONOPERATING_GAIN_PRIORITY_PENALTY = 0.06` when `nonoperating_gain_inflation` is in `decision.quality.risks`)**
4. `src/ai_value_scanner/decision/view_model.py` **(MODIFY — format `nonoperating_gain_inflation` and `ocf_conversion_lagging_high_margin` in `_compact_label`, `_inline_fragment`, and `_build_warning_badges_inline` as `⚠️NonOp-Gain(+21.7pp)`)**
5. `scripts/render_snapshot_preview.py` **(MODIFY — update `_with_quality_v2_adjustments` so `--recompute-v2` also applies `nonoperating_gain_inflation` and `ocf_conversion_lagging_high_margin` on frozen `decisions.jsonl` snapshots)**
6. `tests/test_nonoperating_gain_defense.py` **(NEW — unit tests covering all 3 layers on `GOOG`, `ZM`, `NTNX`, `AMZN`, `WDC`, `SHOP`, `MSFT`, `BILL` archetypes, plus `v1` invariance)**

---

## 3. Exact Implementation Specifications

### 3.1 Layer 3 (Above-the-Line Disposal Variant): `src/ai_value_scanner/scanner.py`
In `src/ai_value_scanner/scanner.py` (around line 249), add `"DisposalGroupNotDiscontinuedOperationGainLossOnDisposal"` to `NONRECURRING_GAIN_TAGS`:
```python
NONRECURRING_GAIN_TAGS = [
    "GainLossOnDispositionOfAssets",
    "GainLossOnSaleOfBusiness",
    "GainLossOnSaleOfPropertyPlantEquipment",
    "GainLossOnSaleOfOtherAssets",
    "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
]
```
*(Do NOT bump `PARSED_FUND_CACHE_VERSION` so existing cached files remain valid without forcing a 30-minute cold rebuild.)*

### 3.2 Layer 1 & Layer 2: `src/ai_value_scanner/decision/quality.py` (`build_company_quality_v2` ONLY)
1. Define constants near `QUALITY_V2_POLICY_VERSION`:
   ```python
   QUALITY_V2_NONOP_MARGIN_GAP_MIN = 0.05
   QUALITY_V2_NONOP_NET_MARGIN_FLOOR = 0.12
   QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI = 1.50
   QUALITY_V2_NONOP_YOY_GAP_MIN = 0.40
   QUALITY_V2_HIGH_MARGIN_CONVERSION_WARN_MARGIN = 0.20
   ```
2. Inside `build_company_quality_v2`, after computing `work["fcf_margin"]` and `work["operating_margin"]` (around line 878):
   - Read raw values before scoring:
     ```python
     raw_net_margin = _finite_value(work, "net_margin")
     operating_margin_val = _finite_value(work, "operating_margin")
     fcf_margin_val = _finite_value(work, "fcf_margin")
     ani_yoy_val = _finite_value(work, "adjusted_net_income_yoy")
     if ani_yoy_val is None:
         ani_yoy_val = _finite_value(work, "net_income_yoy")
     ebit_yoy_val = _finite_value(work, "adjusted_ebit_yoy")
     if ebit_yoy_val is None:
         ebit_yoy_val = _finite_value(work, "ebit_yoy")
     ```
   - **Detect `nonoperating_gain_inflation`**:
     - **Case A (Operating Margin Available)**:
       `operating_margin_val is not None and raw_net_margin is not None and raw_net_margin >= QUALITY_V2_NONOP_NET_MARGIN_FLOOR and (raw_net_margin - operating_margin_val) >= QUALITY_V2_NONOP_MARGIN_GAP_MIN and (ocf_value is None or ocf_value < QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI)`
       - `margin_gap = round(raw_net_margin - operating_margin_val, 6)`
       - De-pollute `work["net_margin"] = operating_margin_val` so `profitability_cash` scores the clean operating margin instead of the inflated GAAP net margin!
       - Emit risk item to `risks`:
         ```python
         risks.append(
             _metric_item(
                 code="nonoperating_gain_inflation",
                 label="Non-operating gain / tax distortion",
                 polarity="negative",
                 metric="net_margin",
                 value=margin_gap,
                 threshold=f"net_margin - operating_margin < +{QUALITY_V2_NONOP_MARGIN_GAP_MIN * 100:.0f}pp",
                 message=(
                     f"Reported net margin ({raw_net_margin * 100:.1f}%) exceeds operating margin "
                     f"({operating_margin_val * 100:.1f}%) by +{margin_gap * 100:.1f}pp; "
                     "non-operating gains or tax items inflated GAAP earnings — net margin capped at operating margin."
                 ),
             )
         )
         ```
     - **Case B (Fallback when `operating_margin_val is None` — e.g. missing EBIT tag)**:
       `operating_margin_val is None and raw_net_margin is not None and raw_net_margin >= 0.25 and (ocf_value is None or ocf_value < QUALITY_V2_HEALTHY_OCF_MIN) and fcf_margin_val is not None and (raw_net_margin - fcf_margin_val) >= 0.15`
       - `margin_gap = round(raw_net_margin - fcf_margin_val, 6)`
       - De-pollute `work["net_margin"] = max(0.0, fcf_margin_val)`
       - Emit `nonoperating_gain_inflation` risk item to `risks` with `value=margin_gap`.
   - **De-pollute Earnings Growth (`growth_stability` pillar) when `ebit_yoy_val` is available and diverges from `ani_yoy_val`**:
     - If `ebit_yoy_val is not None and ani_yoy_val is not None`:
       - If `nonop_inflated` is `True` OR `abs(ani_yoy_val - ebit_yoy_val) >= QUALITY_V2_NONOP_YOY_GAP_MIN`:
         set `work[earnings_growth_key] = ebit_yoy_val` so `growth_stability` scores clean operating income YoY (`ebit_yoy_val`) instead of investment-gain-distorted `adjusted_net_income_yoy` (fixing both upward inflation like `GOOG +114.7% -> +24.9%`, `ZM +174.0% -> +22.0%`, `AMZN +93.3% -> +24.6%` AND downward base-effect drag like `SHOP -15.4% -> +51.3%`!).
   - **Layer 2 — Close the `(0.25, 0.80)` Silent OCF/NI Band on High-Margin Companies (`ocf_conversion_lagging_high_margin`)**:
     - After `profitability_cash_scores` is evaluated:
       If `raw_net_margin is not None and raw_net_margin >= QUALITY_V2_HIGH_MARGIN_CONVERSION_WARN_MARGIN`:
       - If `ocf_value is not None and ocf_value < QUALITY_V2_HEALTHY_OCF_MIN` and not any(r.code == "ocf_to_net_income_weak" for r in risks):
         append to `risks`:
         ```python
         risks.append(
             _metric_item(
                 code="ocf_conversion_lagging_high_margin",
                 label="Cash conversion lagging high net margin",
                 polarity="negative",
                 metric="ocf_to_net_income",
                 value=round(ocf_value, 6),
                 threshold=">=0.80x expected when net margin >=20%",
                 message=(
                     f"OCF/NI is {ocf_value:.2f}x despite {raw_net_margin * 100:.1f}% reported net margin; "
                     "earnings include non-cash or non-operating components."
                 ),
             )
         )
         ```

### 3.3 Priority Penalty in `src/ai_value_scanner/decision/action.py` (`assign_action_priorities_v2`)
1. Define constant:
   ```python
   H3_NONOPERATING_GAIN_PRIORITY_PENALTY = 0.06
   ```
2. Add helper:
   ```python
   def _has_nonoperating_gain_risk(decision: StockDecision) -> bool:
       return any(
           item.code == "nonoperating_gain_inflation"
           for item in decision.quality.risks
       )
   ```
3. In `assign_action_priorities_v2`'s `_sort_key(decision)`:
   Add `nonop_penalty = H3_NONOPERATING_GAIN_PRIORITY_PENALTY if _has_nonoperating_gain_risk(decision) else 0.0` alongside `pre_earn_penalty` (so total penalty is `pre_earn_penalty + nonop_penalty` across all branches in `_sort_key`).

### 3.4 Presentation & Warning Badges in `src/ai_value_scanner/decision/view_model.py`
1. In `_compact_label(item: EvidenceItem)`:
   - If `item.code == "nonoperating_gain_inflation"`: return `"Non-Op Gain Margin Gap"`
   - If `item.code == "ocf_conversion_lagging_high_margin"`: return `"OCF/NI (Low vs Margin)"`
2. In `_inline_fragment(item: EvidenceItem)`:
   - If `item.code == "nonoperating_gain_inflation"`:
     format `val_num = _as_float(item.value)` -> if `val_num is not None`, return `f"⚠️ Non-Op Gain (+{val_num * 100:.1f}pp vs OpMargin)"`, else `"⚠️ Non-Op Gain"`
   - If `item.code == "ocf_conversion_lagging_high_margin"`:
     return `f"OCF/NI {format_metric_value(item.metric, item.value)} (lagging margin)"`
3. In `_build_warning_badges_inline(decision: StockDecision, data_trust: DataTrustBadge)`:
   - Check if any item in `decision.quality.risks` has `item.code == "nonoperating_gain_inflation"`:
     - If `val_num = _as_float(item.value)` is not None:
       append `f"⚠️NonOp-Gain(+{val_num * 100:.1f}pp)"`
     - Else:
       append `"⚠️NonOp-Gain"`

### 3.5 Support in `scripts/render_snapshot_preview.py` (`--recompute-v2`)
In `_with_quality_v2_adjustments(decision: StockDecision)` inside `scripts/render_snapshot_preview.py`:
- Also check `net_margin = _evidence_number(decision, "net_margin")`, `op_margin = _evidence_number(decision, "operating_margin")`, `fcf_margin = _evidence_number(decision, "fcf_margin")`, and `ocf_ni = _evidence_number(decision, "ocf_to_net_income")`.
- Note that in a frozen `decisions.jsonl`, if `operating_margin` was in the neutral band `[0.05, 0.20)` (as for `NTNX` where `operating_margin = 0.096`), `op_margin` is `None` in `decisions.jsonl` AND `ocf_to_net_income` (`0.608`) is ALSO `None` in `decisions.jsonl` (because it was in the `[0.25, 0.80)` neutral band, so `"ocf_to_net_income_strong"` is absent from `positives`!).
- Therefore, in `_with_quality_v2_adjustments` (which operates on `StockDecision` evidence items):
  - Trigger `nonoperating_gain_inflation` if `"nonoperating_gain_inflation" not in codes` and either:
    1. `net_margin is not None and op_margin is not None and net_margin >= 0.12 and (net_margin - op_margin) >= 0.05 and (ocf_ni is None or ocf_ni < 1.50)` (sets `gap = round(net_margin - op_margin, 6)`), OR
    2. `net_margin is not None and op_margin is None and net_margin >= 0.40 and "ocf_to_net_income_strong" not in {i.code for i in quality.positives} and fcf_margin is not None and (net_margin - fcf_margin) >= 0.15` (catches `NTNX` in frozen JSONL where `net_margin = 0.528`, `fcf_margin = 0.295`, and both `operating_margin` and `ocf_to_net_income` were in the neutral band! Sets `gap = round(net_margin - fcf_margin, 6)`).
  - When triggered in `_with_quality_v2_adjustments`:
    append `nonoperating_gain_inflation` (`value=gap`) to `risks`, and if `ocf_ni is not None and ocf_ni < 0.80` (or `"ocf_to_net_income_strong" not in {i.code for i in quality.positives}` when `net_margin >= 0.20` and `ocf_ni is not None`), append `ocf_conversion_lagging_high_margin` if not already present.

---

## 4. Verification Commands

Run locally:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_nonoperating_gain_defense.py"
.venv/bin/python -m unittest discover -s tests -p "test_report_review_optimizations.py"
.venv/bin/python -m unittest discover -s tests -p "test_m3_candidate_preflight.py"
.venv/bin/python -m unittest discover -s tests -p "test_m4_paired_validation.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass, stop and report for Chief Architect review.
