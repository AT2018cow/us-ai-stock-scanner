# Track B Execution Spec — M1 Share-Scope Integrity & Entry Silent-Gate Completeness

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Branch Name**: `fix/m1-share-scope-and-entry-silent-gates-20261014`
> **Architecture Contract**: Read `docs/agent_specs/00_parallel_tracks_and_view_ir_contract.md` and `docs/m0_baseline_review_20261014/attention_failure_cases.md` first.

---

## 1. Objective

Close the **Phase M1 P0 Correctness Engineering Contract** identified in M0 (`docs/m0_baseline_review_20261014/attention_failure_cases.md` §3) without altering any v1 scoring weights, grade cutoffs, Entry state thresholds, Action mappings, or frozen historical datasets:

1. **Part 1 — Share-Count Basis Separation & Cross-Period Scope Protection (`HEI / VSH / GOOGL`)**:
   - Prevent period-weighted average share counts (`WeightedAverageNumberOfSharesOutstandingBasic` / `Diluted`, which in `HEI` 10-K filings sum two share classes `~138M`) from being mixed with or overriding point-in-time outstanding share counts (`EntityCommonStockSharesOutstanding` / `CommonStockSharesOutstanding`, which in `HEI` 10-Q filings report single-class Common shares `~55M`).
   - Ensure current shares and year-ago shares (`shares_yoy`) are computed from a **consistent share-count basis**, and record explicit share-basis provenance (`share_count_basis`, `share_count_tag`).
2. **Part 2 — Entry Silent-Gate Evidence Completeness (`CRM / TXN / PG / GOOGL / ISRG`)**:
   - Emit explicit `EvidenceItem`s in `src/ai_value_scanner/decision/entry.py` for every active `TREND_DAMAGED` trigger (`days_below_sma200 >= 15`) and every unmet `ENTRY_READY` gate (`price_to_sma200 in [0.95, 1.00)`, `price_to_sma50 in [0.97, 0.98) ∪ (1.08, 1.10]`, `return_20d in (-0.15, -0.03) ∪ (0.12, 0.15]`, `return_60d in (-0.08, 0.0)`, `relative_strength_60d_qqq in (-0.10, -0.03)`, `drawdown_from_52w_high > 0.22`) while keeping **`EntryState`, `entry.score`, `entry.confidence`, `ActionState`, and `priority` 100% invariant**.

---

## 2. Strict Scope & File Boundaries

### Allowed to Create or Modify:
1. `src/ai_value_scanner/fundamentals/shares.py`
2. `src/ai_value_scanner/fundamentals/facts.py` (only if helper needed for tag-group filtering)
3. `src/ai_value_scanner/scanner.py` (share-tag separation & provenance wiring)
4. `src/ai_value_scanner/decision/entry.py` (silent-gate `EvidenceItem` emission)
5. `tests/test_m1_share_scope_and_entry_silent_gates.py` **(NEW)**

### Strictly Forbidden to Modify:
- `src/ai_value_scanner/reporting/*` (owned by Track A)
- `src/ai_value_scanner/decision/view_model.py` (owned by Track A)
- `src/ai_value_scanner/decision/{quality,action,model}.py`
- `configs/*`, `evidence/*`, or any frozen historical CSV in `outputs/`

---

## 3. Detailed Implementation Requirements

### 3.1 Part 1: Share-Count Basis Separation (`shares.py` & `scanner.py`)

#### Problem in Current Code:
In `src/ai_value_scanner/scanner.py:190`:
```python
SHARES_TAGS = [
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
]
```
All four tags are passed together into `extract_fact_records(companyfacts, SHARES_TAGS, ...)` and collapsed via `collapse_fact_records_by_end()`, where `revision_key = (visible_on, accession, -tag_priority)`. Because `visible_on` (filing date) takes precedence over `tag_priority`, a later 10-K reporting `WeightedAverageNumberOfSharesOutstandingBasic` overwrites an earlier or same-period point-in-time share count, and across quarters the time series alternates between `EntityCommonStockSharesOutstanding` (10-Q, ~55M for `HEI`) and `WeightedAverageNumberOfSharesOutstandingBasic` (10-K, ~138M for `HEI`).

#### Required Solution:
1. Define two explicit tag constants in `src/ai_value_scanner/fundamentals/shares.py` (and re-export/use in `scanner.py` while keeping `SHARES_TAGS` as their concatenation for backward compatibility):
   ```python
   POINT_IN_TIME_SHARES_TAGS: tuple[str, ...] = (
       "EntityCommonStockSharesOutstanding",
       "CommonStockSharesOutstanding",
   )
   WEIGHTED_AVERAGE_SHARES_TAGS: tuple[str, ...] = (
       "WeightedAverageNumberOfSharesOutstandingBasic",
       "WeightedAverageNumberOfDilutedSharesOutstanding",
   )
   ```
2. Extend `ShareCountIntegrity` in `src/ai_value_scanner/fundamentals/shares.py` with backward-compatible defaults:
   ```python
   @dataclass(frozen=True, slots=True)
   class ShareCountIntegrity:
       value: float | None
       period_end: date | None
       stale: bool
       scale_factor: float
       latest_metric_end: date | None
       basis: str = "missing"          # "point_in_time_outstanding" | "weighted_average_fallback" | "missing"
       source_tag: str | None = None
   ```
3. Add a pure helper `select_consistent_share_records(share_records, cutoff=None, stale_after_days=400, metric_record_groups=()) -> tuple[list[FactRecord], str]`:
   - Partition `share_records` into `pit_records` (`record.tag in POINT_IN_TIME_SHARES_TAGS`) and `wa_records` (`record.tag in WEIGHTED_AVERAGE_SHARES_TAGS`).
   - If `pit_records` has a latest visible record that is positive and not stale (relative to `latest_metric_end` within `stale_after_days`), select **only `pit_records`** (`basis="point_in_time_outstanding"`).
   - Otherwise, fall back to `wa_records` (`basis="weighted_average_fallback"`).
   - **Crucial invariant**: Never mix `pit_records` and `wa_records` across periods for the same issuer! Both the current share count (`assess_share_count_integrity`) and the historical/YoY share series used for `shares_yoy` must use the **same selected record subset** so `HEI` never computes `shares_yoy` or `market_cap` across a 55M ↔ 138M basis switch.
4. In `assess_share_count_integrity`:
   - Use `select_consistent_share_records` so `ShareCountIntegrity.basis` and `ShareCountIntegrity.source_tag` are populated accurately.
   - Note: Keep the EPS/net-income unit-scaling check (`1,000x` or `1,000,000x` when reported in thousands/millions), which only triggers for `ratio in [500, 2000]` or `[500_000, 2_000_000]` (so a 2.5x dual-class ratio is never falsely scaled).

---

### 3.2 Part 2: Entry Silent-Gate Evidence Completeness (`src/ai_value_scanner/decision/entry.py`)

#### Problem in Current Code:
In `_build_entry_with_thresholds` (`src/ai_value_scanner/decision/entry.py`), several predicates that trigger `TREND_DAMAGED` or block `ENTRY_READY` emit **no `EvidenceItem`**:
- `days_below_sma200 >= 15` triggers `TREND_DAMAGED` (line 610), yet emits no risk item (`ISRG`, `COST`, `WMT` in 62-stock snapshot; 14 stocks in 510-stock snapshot).
- `price_to_sma200 in [0.95, 1.00)` blocks `ENTRY_READY`, yet emits neither positive nor risk item.
- `price_to_sma50 in [0.97, 0.98)` or `(1.08, 1.10]` blocks `ENTRY_READY`, yet emits neither positive nor risk item (`CRM`).
- `return_20d < -0.03` or `return_20d in (0.12, overextended_return20_gt]` blocks `ENTRY_READY`, yet emits neither positive nor risk item (`CRM`).
- `return_60d in (-0.08, 0.0)` blocks `ENTRY_READY`, yet emits neither positive nor risk item (`TXN`, `EQIX`).
- `relative_strength_60d_qqq in (-0.10, ready_rs60_min)` blocks `ENTRY_READY`, yet emits neither positive nor risk item (`PG`, `GOOGL`, `TXN`, `AAPL`, `EQIX`).
- `drawdown_from_52w_high > 0.22` blocks `ENTRY_READY`, yet emits no item (`CRM` if drawdown > 22%).

#### Required Solution:
In `_build_entry_with_thresholds` (`src/ai_value_scanner/decision/entry.py`), add the following explicit `risks.append(_item(...))` branches for the previously silent intervals:

1. **SMA200 mild below-trend band (`0.95 <= sma200 < 1.00`)**:
   - `code="price_below_sma200_trend"`, `label="Price below SMA200"`, `polarity="negative"`, `metric="price_to_sma200"`, `value=round(sma200, 6)`, `threshold=">=1.00 for ENTRY_READY"`, `message="Price is slightly below its 200-day average and does not confirm ENTRY_READY."`
2. **Days below SMA200 elevated (`days_below is not None and days_below >= 15`)**:
   - `code="days_below_sma200_elevated"`, `label="Persistent days below SMA200"`, `polarity="negative"`, `metric="days_below_sma200"`, `value=int(days_below) if float(days_below).is_integer() else round(days_below, 2)`, `threshold="<15 days"`, `message="Stock has spent 15 or more recent sessions below SMA200, flagging trend damage."`
3. **SMA50 near-miss bands (`0.97 <= sma50 < 0.98` or `1.08 < sma50 <= 1.10`)**:
   - `code="price_to_sma50_outside_ready_band"`, `label="Price outside SMA50 readiness band"`, `polarity="negative"`, `metric="price_to_sma50"`, `value=round(sma50, 6)`, `threshold="0.98–1.08"`, `message="Price is outside the 0.98–1.08 SMA50 readiness band."`
4. **20d return outside readiness band (`return_20d < -0.03` or `0.12 < return_20d <= overextended_return20_gt`)**:
   - `code="return_20d_outside_ready_band"`, `label="20d return outside readiness band"`, `polarity="negative"`, `metric="return_20d"`, `value=round(return_20d, 6)`, `threshold="-3% to +12%"`, `message="20d momentum is outside the -3% to +12% readiness band."`
5. **60d return mildly negative (`-0.08 < return_60d < 0.0`)**:
   - `code="return_60d_slightly_negative"`, `label="60d trend slightly negative"`, `polarity="negative"`, `metric="return_60d"`, `value=round(return_60d, 6)`, `threshold=">=0% for ENTRY_READY"`, `message="60d return is negative and blocks ENTRY_READY."`
6. **60d QQQ relative strength in silent below-ready band (`-0.10 < relative_strength < ready_rs60_min`)**:
   - Only when `ready_rs60_min == -0.03` (since `ready_rs60_min > -0.03` already emits `relative_strength_60d_qqq_below_candidate_ready`):
   - `code="relative_strength_60d_qqq_below_ready"`, `label="60d relative strength below readiness gate"`, `polarity="negative"`, `metric="relative_strength_60d_qqq"`, `value=round(relative_strength, 6)`, `threshold=">=-3%"`, `message="60d QQQ relative strength is below the -3% ENTRY_READY gate."`
7. **Drawdown from 52w high deeper than readiness cap (`drawdown is not None and drawdown > 0.22`)**:
   - `code="drawdown_from_52w_high_deep"`, `label="52w drawdown exceeds readiness cap"`, `polarity="negative"`, `metric="drawdown_from_52w_high"`, `value=round(drawdown, 6)`, `threshold="<=22% for ENTRY_READY"`, `message="Drawdown from 52-week high exceeds the 22% ENTRY_READY cap."`
8. **Defensive regime extra RS/ret20 gate not met**:
   - When `defensive_regime` is True and `base_ready` is True but `defensive_ready` is False, `defensive_market_regime` is already in `risks` (verify this is always present).

#### Hard Invariants for Part 2:
- **Zero State / Score / Priority Drift**: `_entry_score_and_confidence`, `state`, `confidence`, `map_action_state`, and `_priority_sort_key` must produce **100% identical outputs** before and after this change.
- **No Unexplained Non-READY States**: For any decision with `state in {EntryState.WATCH_BREAKOUT, EntryState.TREND_DAMAGED}`, `len(entry.risks)` must now be `>= 1`!

---

## 4. Required Unit Tests (`tests/test_m1_share_scope_and_entry_silent_gates.py`)

Write unit tests verifying:
1. **`HEI` Share-Scope Regression Test**:
   - Construct a `FactRecord` sequence mimicking `HEI`: 10-Q `EntityCommonStockSharesOutstanding` (`55_054_000` at `2025-07-31`, `54_800_000` at `2024-07-31`) mixed with a later-filed 10-K `WeightedAverageNumberOfSharesOutstandingBasic` (`139_048_000` at `2025-10-31`).
   - Verify `assess_share_count_integrity` and `select_consistent_share_records` select `EntityCommonStockSharesOutstanding` (`55_054_000`, `basis="point_in_time_outstanding"`), never alternating to `139_048_000`.
2. **Weighted-Average Fallback Test**:
   - When an issuer has *no* point-in-time share tags (`EntityCommonStockSharesOutstanding` / `CommonStockSharesOutstanding` absent) and only reports `WeightedAverageNumberOfSharesOutstandingBasic`, verify it cleanly falls back with `basis="weighted_average_fallback"`.
3. **Entry Silent-Gate Completeness Tests (`CRM`, `TXN`, `PG`, `GOOGL`, `ISRG` archetypes)**:
   - Test `PG`/`GOOGL` archetype (`RS60 = -0.045`): `state == WATCH_BREAKOUT`, `relative_strength_60d_qqq_below_ready` is in `entry.risks`.
   - Test `TXN` archetype (`return_60d = -0.02`, `RS60 = -0.05`): `return_60d_slightly_negative` and `relative_strength_60d_qqq_below_ready` are in `entry.risks`.
   - Test `CRM` archetype (`return_20d = 0.135` or `drawdown = 0.25` with all other gates passing): `return_20d_outside_ready_band` or `drawdown_from_52w_high_deep` is in `entry.risks`.
   - Test `ISRG` archetype (`days_below_sma200 = 18`, `price_to_sma50 = 1.104`, `return_60d = 0.239`): `state == TREND_DAMAGED` AND `days_below_sma200_elevated` is in `entry.risks` alongside `price_extended_above_sma50`.
4. **State & Score Parity Check**:
   - Verify that across a grid of synthetic rows covering all 5 `EntryState`s, `entry.state`, `entry.score`, and `entry.confidence` are 100% unchanged.

---

## 5. Verification & PR Submission Checklist

Run locally before opening the PR:
```bash
.venv/bin/python -m unittest discover -s tests
```
- Confirm all existing tests (including `test_entry_quality_v1.py`, `test_mvp_v11_b0_parity.py`, `test_mvp_v11_entry_candidates.py`) and the new `test_m1_share_scope_and_entry_silent_gates.py` pass.
- Confirm `git status` shows edits **only** within Track B's allowed file list.
- Open PR against `main` and ensure GitHub Actions CI passes on the exact PR HEAD.
