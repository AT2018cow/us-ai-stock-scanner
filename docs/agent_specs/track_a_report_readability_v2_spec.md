# Track A Execution Spec — Mobile-First Compact Report v2 (`view_model.py` & `reporting/decision.py`)

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Current Active Branch**: `feature/report-readability-v2-view-model-20261014` (PR #75)
> **Architecture Contract**: Read `docs/agent_specs/00_parallel_tracks_and_view_ir_contract.md` first.

---

## 1. Objective (v2.1 Mobile-First Upgrade)

Upgrade the `layout_version="v2"` Markdown renderers (`render_action_list_v2` and `render_detailed_report_v2`) and supporting helpers in `src/ai_value_scanner/decision/view_model.py` to deliver a **Mobile-First, Zero-Horizontal-Scroll, Collapsible Dashboard**:
1. **No Wide Tables**: Maximum **4 columns** in `Action List` tables and maximum **3 columns** in `Detailed Report` tables so mobile screens never require horizontal scrolling.
2. **Ultra-Compact Metric Labels**: Use short, scannable financial abbreviations (`FCF $15.15B`, `Margin 23.6%`, `OCF/NI 1.52x`, `Rev YoY +20.1%`, `P/S 100pctl`, `SMA50 1.03x`, `RS60 -4.7%`) instead of verbose 40-character phrases.
3. **Default-Collapsed `<details>` Sections**: All 15 stock cards, Secondary Radar tables, and Detailed Report Counter-Evidence / Provenance blocks must use HTML `<details><summary>...</summary>...</details>` (**collapsed by default**, i.e., NO `open` attribute) so the entire page fits in 1–2 mobile screens and expands on tap.
4. **Anchor Navigation (`#top`, section jump bar, and `↑ Top` links)**: Add a one-line Quick Jump bar at the top, anchor links from shortlist symbols to their stock cards / detailed reports, and `[↑ Top](#top)` links inside expanded sections.
5. **100% `v1` Parity Preserved**: Default `layout_version="v1"` must remain 100% byte-identical.

---

## 2. Strict Scope & File Boundaries

### Allowed to Modify:
1. `src/ai_value_scanner/decision/view_model.py`
2. `src/ai_value_scanner/reporting/decision.py`
3. `scripts/render_snapshot_preview.py` (if needed)
4. `tests/test_decision_view_model_and_report_v2.py`

### Strictly Forbidden:
- Do NOT run `git checkout`, `git switch`, `git branch`, `git commit`, `git push`, `git reset`, or `git clean`.
- Do NOT touch any file outside the 4 Track A files above.

---

## 3. Detailed Mobile-First Specification

### 3.1 Short Metric & State Abbreviations in `src/ai_value_scanner/decision/view_model.py`

Add compact label mapping so inline summaries and table cells stay short:

```python
_COMPACT_METRIC_LABELS: dict[str, str] = {
    "net_margin": "Margin",
    "free_cash_flow": "FCF",
    "operating_cash_flow": "OCF",
    "ocf_to_net_income": "OCF/NI",
    "accrual_ratio": "Accrual",
    "revenue_yoy": "Rev YoY",
    "adjusted_net_income_yoy": "EPS YoY",
    "net_income_yoy": "NI YoY",
    "operating_cash_flow_yoy": "OCF YoY",
    "net_debt_to_ebitda": "NetDebt/EBITDA",
    "interest_coverage": "IntCov",
    "current_ratio": "CurrRatio",
    "shares_yoy": "Shares YoY",
    "fcf_yield": "FCF Yield",
    "ps_hist_percentile": "P/S",
    "pe_hist_percentile": "P/E",
    "receivables_growth_gap": "AR Gap",
    "inventory_growth_gap": "Inv Gap",
    "price_to_sma200": "SMA200",
    "price_to_sma50": "SMA50",
    "days_below_sma200": "Below SMA200",
    "return_20d": "Ret20d",
    "return_60d": "Ret60d",
    "relative_strength_60d_qqq": "RS60",
    "drawdown_from_52w_high": "52w DD",
    "range_position_52w": "52w Range",
    "volatility_60d": "Vol60d",
    "fundamental_data_age_days": "Fund Age",
    "market_data_age_days": "Mkt Age",
    "regime": "Regime",
}
```

- **Percentile compactness**: In `format_metric_value`, keep `100th pctl` (or in `_inline_fragment` / `summary_text` produce `P/S 100th pctl`, `FCF $15.15B`, `Margin 23.6%`, `OCF/NI 1.52x`).
- Ensure `_inline_fragment(item)` uses `_COMPACT_METRIC_LABELS.get(item.metric or "", _short_label(item.label))` so `top_positives_inline` reads e.g.:
  `"Margin 23.6%; FCF $15.15B; OCF/NI 1.52x"` (under 45 chars total!)
  and `top_risks_or_blockers_inline` reads e.g.:
  `"Accrual -24.3%; Unmet READY gate(s): ret20_band"` or `"P/S 100th pctl; P/E 100th pctl"`.
- Also use compact labels in `_format_evidence_row(item).summary_text` (e.g., `"Margin: 23.6%"`, `"FCF: $15.15B"`, `"OCF/NI: 1.52x"`).

Add compact badge helpers in `reporting/decision.py`:
- Action short badge:
  - `PRIORITY_REVIEW` -> `PRIORITY`
  - `WATCH_PULLBACK` -> `PULLBACK`
  - `WATCH_BREAKOUT` -> `BREAKOUT`
  - `HOLD_MONITOR` -> `MONITOR`
  - `AVOID` -> `AVOID`
- Entry short badge:
  - `ENTRY_READY` -> `READY`
  - `WATCH_PULLBACK` -> `PULLBACK`
  - `WATCH_BREAKOUT` -> `BREAKOUT`
  - `TREND_DAMAGED` -> `DAMAGED`
  - `INSUFFICIENT_DATA` -> `NO_DATA`

---

### 3.2 `render_action_list_v2` Mobile-First Layout (`src/ai_value_scanner/reporting/decision.py`)

Structure the output of `render_action_list_v2` into 4 compact, mobile-friendly sections:

#### 1. Top Anchor, Header & Quick-Jump Bar:
```markdown
<a id="top"></a>
# Daily Action List (v2)

- **Date**: 2026-10-12 (`daily`) · **Shortlist**: 15 (`PRIORITY_REVIEW 6; WATCH_BREAKOUT 6; WATCH_PULLBACK 3`)
- **Jump**: [Executive Shortlist](#executive-shortlist) · [Stock Cards](#stock-cards) · [Secondary Radar](#secondary-radar)
- *Research priorities only — not automated trade instructions.*
```

#### 2. `## Executive Shortlist` (Strictly **4 Columns** — fits mobile width without horizontal scrolling!):
Columns: `| # | Stock | Action & Setup | Key Bullish / Risk & Blocker |`
- Column 1 (`#`): `{card.rank}`
- Column 2 (`Stock`): `**[{card.symbol}](#card-{card.symbol.lower()})**` (links directly to the collapsible card below!)
- Column 3 (`Action & Setup`): `**{short_action}**`<br>`Q:{card.quality_grade} ({card.quality_score_display}) · E:{short_entry} ({card.entry_score_display})`
- Column 4 (`Key Bullish / Risk & Blocker`): `**+** {_cell(card.top_positives_inline)}`<br>`**!** {_cell(card.top_risks_or_blockers_inline)}`

#### 3. `## Stock Cards` (**All cards collapsed by default using `<details>`**):
For each `card` in `snapshot.primary_cards`:
```markdown
<a id="card-etn"></a>
<details>
<summary><b>#1 ETN</b> — <b>PRIORITY</b> · Q:<b>A</b> (0.85) · E:<b>READY</b> (0.93) — <i>Eaton Corp plc</i></summary>

- **Bullish**: Margin 14.0%; FCF $3.93B; OCF/NI 1.17x
- **Risk / Blocker**: P/S 100th pctl
- **Entry Gates**: all 7 PASS (or list each non-PASS gate: `ret20_band [SILENT_OR_UNOBSERVED]: Not in READY band (silent in v1), need -3% to +12% READY band`)
- **Next Trigger**: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- **Data Trust**: `VERIFIED` · Fund: 2026-07-31 (73d) | Mkt: 2026-10-12 (0d) · Basis: `legacy_unspecified`
- **Links**: [Detailed Report](detailed/ETN.md) · [↑ Top](#top)

</details>
```
*(Note: Keep `- Entry blockers:` or `- Entry gates: all 7 PASS.` and any `- Trust note:` lines inside the `<details>` body.)*

#### 4. `## Secondary Radar (Off-List Watch)` (**Collapsed by default using `<details>`, 4-column tables**):
- If neither `cap_omitted_priority_cards` nor `secondary_b_ready_cards` is present, output `- No off-list radar names for this snapshot.`
- When `cap_omitted_priority_cards` is non-empty, wrap in a default-collapsed `<details>`:
  ```markdown
  <details>
  <summary><b>Cap-Omitted PRIORITY_REVIEW</b> (Quality A + ENTRY_READY beyond Top-15: {N} names)</summary>

  | # | Stock | Grade / Setup | Key Bullish / Risk & Blocker |
  | --- | --- | --- | --- |
  | 16 | **EXPD** | **A** (0.79) · `READY` (0.83) | **+** FCF $923.9M; OCF/NI 1.06x<br>**!** P/S 100th pctl; P/E 100th pctl |
  ...

  [↑ Top](#top)
  </details>
  ```
- When `secondary_b_ready_cards` is non-empty, wrap in a default-collapsed `<details>`:
  ```markdown
  <details>
  <summary><b>Top Quality B + ENTRY_READY Candidates</b> (Mapped to HOLD_MONITOR: {N} names)</summary>

  | # | Stock | Grade / Setup | Key Bullish / Risk & Blocker |
  | --- | --- | --- | --- |
  | 26 | **NVDA** | **B** (0.80) · `READY` (0.95) | **+** Margin 63.7%; FCF $127.01B; Rev YoY +83.4%<br>**!** Accrual 29.7%; AR Gap +43.4% |
  ...

  [↑ Top](#top)
  </details>
  ```

---

### 3.3 `render_detailed_report_v2` Mobile-First Layout (`src/ai_value_scanner/reporting/decision.py`)

Keep all tables in `render_detailed_report_v2` to **at most 3 columns** and collapse bulky sections by default:

1. **Top Anchor, Title & Quick Jump Bar**:
   ```markdown
   <a id="top"></a>
   # Detailed Report — CRM — Salesforce, Inc. (v2)

   - **Jump**: [Executive Summary](#executive-decision) · [Quality 6-Pillar](#company-quality--6-pillar-scorecard) · [Entry 7-Gate Checklist](#entry-quality--readiness-gate-checklist) · [Counter-Evidence](#complete-counter-evidence--missing-data-inventory) · [Provenance](#quality-applicability-decision-history--provenance)
   ```
2. **`## Executive Decision` (2-Column Compact Table)**:
   `| Field | Value |` (same clean 2-column key-value table as before).
3. **`## Attention Alerts & Next Review Trigger`**:
   Concise bullet list of attention flags, next trigger, and structure watch.
4. **`## Company Quality — 6-Pillar Scorecard` (Strictly 3 Columns!)**:
   ```markdown
   | Pillar | Score & Status | Supporting & Risk Evidence |
   | --- | --- | --- |
   | Profitability & Cash Conversion | **0.80** (`STRONG`) | **+** Margin: 23.6%; FCF: $15.15B; OCF/NI: 1.52x<br>**!** Accrual: -24.3% |
   | Growth & Stability | **0.93** (`STRONG`) | **+** Rev YoY: +11.2%; EPS YoY: +47.6%; OCF YoY: +19.6% |
   ```
   *(If `risk_or_missing_items` is non-empty, append `<br>**!** {risks}`; if both support and risk are empty, show `none`.)*
5. **`## Entry Quality — Readiness Gate Checklist` (Strictly 3 Columns!)**:
   ```markdown
   | Readiness Gate | Status | Observed vs Target Band |
   | --- | --- | --- |
   | Data Freshness (Market As-Of) | `PASS` | **0d** (target: <=3d fresh; >7d insufficient) |
   | Long-Term Trend (Price / SMA200) | `PASS` | **1.17x** (target: >= 1.00x (Damaged < 0.95x)) |
   | Recent Momentum (20d Return) | `SILENT_OR_UNOBSERVED` | **Not in READY band (silent in v1)** (target: -3% to +12% READY band) |
   ```
6. **`## Complete Counter-Evidence & Missing Data Inventory` (Default-Collapsed `<details>` with 3-Column Table)**:
   ```markdown
   <details>
   <summary><b>Expand Counter-Evidence & Missing Metrics</b> ({N_counter} counter, {N_missing} missing)</summary>

   | Type / Code | Metric & Value | Target Band & Label |
   | --- | --- | --- |
   | `accrual_ratio_weak` (counter) | accrual_ratio: **-24.3%** | \|accrual\|<=0.10 supportive; >0.35 weak — Accrual quality weak |

   [↑ Top](#top)
   </details>
   ```
7. **`## Quality Applicability, Decision History & Provenance` (Applicability note visible; 30-line machine provenance wrapped in Default-Collapsed `<details>`)**:
   - Keep the 2 applicability bullet lines and `Previous action` / `State change` visible.
   - Wrap the machine provenance (`Schema version`, `Generated at UTC`, `Source lists`, and all `decision.provenance` keys/hashes) inside:
     ```markdown
     <details>
     <summary><b>Expand Audit Provenance & Hashes</b> ({len(decision.provenance)} keys)</summary>

     - Schema version: 1
     ...

     [↑ Top](#top)
     </details>
     ```

---

## 4. Required Unit Test Updates (`tests/test_decision_view_model_and_report_v2.py`)

Update/add unit tests in `tests/test_decision_view_model_and_report_v2.py` to assert:
1. **Table Column Width Cap**:
   - Every Markdown table header line (`| ... |`) in `render_action_list(..., layout_version="v2")` has **at most 4 columns** (`line.count("|") <= 5`).
   - Every Markdown table header line (`| ... |`) in `render_detailed_report(..., layout_version="v2")` has **at most 3 columns** (`line.count("|") <= 4`).
2. **Default-Collapsed `<details>` Tags**:
   - `render_action_list(..., layout_version="v2")` contains `<details>` and `<summary>`, and contains **zero** `<details open` tags (all collapsed by default).
   - `render_detailed_report(..., layout_version="v2")` wraps provenance and counter-evidence in default-collapsed `<details>` tags and contains `[↑ Top](#top)` navigation links.
3. **Compact Labels & Formatted Values**:
   - Inline summaries use compact labels (`FCF $15.15B`, `Margin 23.6%`, `P/S 100th pctl`) and never raw floats (`15154000000.0`, `0.236287`).
4. **100% `v1` Byte Parity**:
   - Default `layout_version="v1"` remains 100% unchanged.

---

## 5. Verification Commands

Run locally:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_decision_view_model_and_report_v2.py"
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/render_snapshot_preview.py \
  --snapshot-dir outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off \
  --output-dir outputs/report_v2_preview_20261014/snap62
.venv/bin/python scripts/render_snapshot_preview.py \
  --snapshot-dir evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff \
  --output-dir outputs/report_v2_preview_20261014/snap510
```
