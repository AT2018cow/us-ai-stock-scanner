# MVP v1.1 PR-A — candidate membership preflight verification report

Date: 2026-10-14
Code under test: PR #70 head `ffb1177dd09f97e0b829e4a4c8247cdaf90419e9`
(CI pass on this head, run 38518835934; local 705 tests OK)
Scope: outcome-blind membership only (2023–2024 development dates). No
candidate returns computed, read, or compared; no SEC/Alpaca/Modal; X1 not
executed; 2025/2026Q1 comparisons remain embargoed.

## 1. Command and outputs

```bash
python scripts/mvp_v11_candidate_preflight.py \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --event-review outputs/mvp_v11_risk/risk_run_01/event_review_queue.csv \
  --output-dir outputs/mvp_v11_preflight/membership_run_01
# → MEMBERSHIP_ONLY_NO_CANDIDATE_RETURNS: 240 date×candidate rows
```

| File (this dir, except flags) | SHA256 | Note |
| --- | --- | --- |
| `preflight_manifest.json` | `6b3fdc52…` | pins code/data/registry/queue/output SHAs |
| `membership_by_date.csv` | `bc9130ed…` | 240 rows = 24 dates × 10 candidates |
| `entry_migrations_by_date.csv` | `ebdf3bef…` | E-state migration counts |
| `score_source_flags_local_only.csv` | `12916eb3…` | 25,025-row sidecar, **local `outputs/` only, not committed** |

Manifest pins verified: code `ffb1177d…`, dataset `2a4600ee…`, metadata
`1574a855…`, event queue `3bf0844f…`, registry `385070b3…` (= on-disk
`configs/mvp_v11_candidate_registry.json`, 11 slots B0/R1–R5/E1–E4/X1).

## 2. Verification results

- **Shape**: exactly 240 rows, 24 signal dates (2023-01 → 2024-12), 10 executed
  candidates; `x1_executed: false`; `ready_for_candidate_returns: false`.
- **Outcome-blindness**: no `fwd_*` / `qqq_return_*` / return columns in any
  output; script strips outcome columns before scoring (covered by unit test
  "preflight ignores injected future returns").
- **B0 anchor**: all self-compare deltas are 0 on all 24 dates (correct).
- **R1–R5 (same Action/Grade reorder only)**: zero entry-state and zero action
  changes for all five; Top-15 swaps R1=17 / R2=25 / R3=39 / R4=25 / R5=26 and
  Top-5 swaps 5 / 13 / 22 / 12 / 14 — monotone in Entry weight as designed
  (R1 gentlest, R3 strongest). R4/R5 penalties change order only, never states.
- **E1/E2 (READY RS −3% → 0% / +3%)**: READY→WATCH_BREAKOUT migrations
  285 / 613 rows; action changes 103 / 232 (all via PR-count changes);
  Top-15 swaps 57 / 122 across 17 / 19 dates. Direction matches the frozen
  hypothesis (fewer weak-relative-strength READY names).
- **E3 (overextended 15% → 12%)**: WATCH_BREAKOUT→WATCH_PULLBACK 198 rows,
  62 action changes, 0 PR-count changes, only 4 Top-15 swaps (2 dates) —
  consistent with the plan's warning that E3 may mostly relabel PULLBACK.
- **E4 (overextended 15% → 18%)**: WATCH_PULLBACK→WATCH_BREAKOUT 82 rows,
  25 action changes, 0 PR-count changes, only 2 Top-15 swaps (2 dates) —
  minimal membership effect, as the 12% READY cap predicts.
- **Score-source sidecar** (sensitivity only, not selection): 346
  missing-fundamental-asof, 39 HEI-scope-uncertain (+4 confirmed 10-K/10-Q
  dates from the SEC audit), 21 severe-share-event date rows, 406 total
  uncertain of 25,025. Kept locally per runbook; not committed.

## 3. Limitations

- Monthly historical priority/cap proxy only; not a Daily/Weekly replay.
- Membership movement is not return improvement; no alpha claim is possible
  from this run (R reorder inside identical Top-15 membership cannot move
  equal-weight returns; E3/E4 relabels need real action-meaning review).
- HEI valuation-denominator distortion, the 51 audit-only events, and all
  filing/entity/CIK caveats from A0/B0/risk/SEC reviews remain open and must
  ride along into the experiment protocol and final recommendation.
- Per runbook: do not merge PR #70 on this preflight alone; the return
  comparator, 2023–2024 development run, and GO/NO-GO decision are still
  pending and require separate authorization.
