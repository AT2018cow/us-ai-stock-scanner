# M0 Attention Failure Cases & M1 Correctness Engineering Contract (2026-10-14)

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

1. **Silent `WATCH_BREAKOUT` Readiness Blockers (`CRM`, `TXN`, `PG`, `GOOGL` in 62-stock shortlist; 74 symbols in 510-stock snapshot)**:
   - In `src/ai_value_scanner/decision/entry.py`, `ENTRY_READY` requires `0.98 <= price_to_sma50 <= 1.08`, `-0.03 <= return_20d <= 0.12`, `return_60d >= 0.0`, `relative_strength_60d_qqq >= -0.03`, `drawdown_from_52w_high <= 0.22`, and `volatility_60d <= 0.80`.
   - However, negative `EvidenceItem`s are only emitted for extreme weakness (`price_to_sma50 < 0.97` or `> 1.10`, `return_60d <= -0.08`, `relative_strength_60d_qqq <= -0.10`, `volatility_60d > 0.80`), and **never** for `drawdown_from_52w_high > 0.22`, `price_to_sma200 in [0.95, 1.00)`, `price_to_sma50 in [0.97, 0.98) ∪ (1.08, 1.10]`, `return_20d in (-0.15, -0.03) ∪ (0.12, 0.15]`, `return_60d in (-0.08, 0.0)`, or `relative_strength_60d_qqq in (-0.10, -0.03)`.
   - Consequently, **4 of the 6 `WATCH_BREAKOUT` names on the 2026-10-12 15-stock Action List (`CRM`, `TXN`, `PG`, `GOOGL`) display zero Entry risk items**, leaving the human reviewer with no explanation of which gate blocked `ENTRY_READY`.
2. **Silent `TREND_DAMAGED` Trigger (`ISRG` in 62-stock snapshot; 14 symbols in 510-stock snapshot)**:
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
