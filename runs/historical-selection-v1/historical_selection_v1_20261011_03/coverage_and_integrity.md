# Coverage and integrity — RUN_ID historical_selection_v1_20261011_03

## Universe verdict (UNCHANGED HARD LIMITATION)

**`retrospective with approximate historical universe`** (union approx;
snapshots only from 2026-09-22). Mechanism diagnostics only.

## Dataset integrity (v3 = fixed splits + continuity repair)

| item | company_quality | entry_quality |
|---|---|---|
| rows | 25,025 | 25,025 |
| signal dates / symbols | 39 (2023-01-31→2026-03-31) / 670 | same |
| raw CSV SHA256 | 99387193…0dc337 (both kinds byte-identical pre-strategy rows) | same |
| meta SHA256 | 5644f2af…04e0002 | 1574a855…1239e6a |
| splits.json SHA256 | f5c7e421…f9c6e4f109 (48 symbols w/ events) | same file |
| split query end | 2026-09-25 (covers max label_end 2026-09-22) | same |
| repaired CSV SHA256 | 2a4600ee…5a328e (.v3, +2 flag cols) | same |
| SUCCESS | status success, spec code af70b5e | same |
| discontinuities audit | 1 nulling (WOLF REORG_JUMP_BACKDATED, 5 rows / 7 labels) + 51 disclosures | same |
| label maturity | 100% valid 20/60/120d | 100% valid |

Grade mix v3 (action master): A 6,888 / B 9,152 / C 7,158 / UNRATED 1,822
(64 rows drifted vs _02 on live-SEC refetch, mostly UNRATED → graded).

## Label-diff summary v1(_02) → v3 (full tables: label_diff_*.csv)

- 50 SPLIT_FIX labels across 9 symbols (APH, BKNG, CRWD, CVNA, IESC, KLAC,
  MOVE, MQ, POWL); 7 NULLED (WOLF); 0 other rows changed (25,025-row join
  complete, no additions/drops).
- Cohort direction unchanged at every grade × horizon; C120 datew
  +0.1137 → +0.1049, A120 −0.0323 → −0.0294.

## PIT / statistical discipline (unchanged)

Per-date filing cutoffs; split-adjusted labels (now complete); raw closes ×
raw shares for valuation; no overlapping-row independence claims;
date-equal-weight reporting; 2023–24 exploratory, 2025/26Q1 temporal only.
