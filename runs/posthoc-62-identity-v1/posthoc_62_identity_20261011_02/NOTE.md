# Acceptance appendix — integration SHA verification (part 2)

Extends `posthoc_62_identity_20261011_01` (renderer/identity samples).
This pack proves the six integration acceptance items ON the fetchable
integration commit (not a local-only merge).

## Exact code composition (all fetchable from origin)

- integration branch `integration/phase2-identity-20261011` @
  `351154d7e860df0a02dbe7e90f85cd286bfcef0f`
  (merge of the three SHAs below; draft PR #61, DO NOT MERGE)
- contains `fix/identity-verification-20261011` @ `574ff8d`
  (incl. tightened empty-ticker rule)
- contains `phase2/report-clarity-20261011` @ `8d34abb`
  (incl. BREAKOUT honesty + asof-MISSING display)
- contains `research/historical-selection-validation-protocol-20261011`
  @ `6711919` (post-hoc entry + split helpers; unmerged research)
- CI on the integration SHA: unittest PASS run 38293753005
  (plus local full suite 572 OK on the same tree)

## Six items (see acceptance_checklist.md — 24/24 PASS)

1. XOM UNRATED + identity code + CIK trace + banner.
2. GS UNRATED without identity code.
3. JPM C + applicability caveat, no balance-sheet verdict.
4. ABBV list/detail token consistency.
5. BREAKOUT honesty, asof handling, AAPL state-change rendering.
6. No policy change: entry.py byte-identical to main; decision/
   additive-only (0 removed lines); quality.py gate scoped to the
   identity check; integrated.py scoped to provenance keys.

## Blast radius of the tightened empty-ticker rule

0/62 post-hoc names, 0/687 watchlist names newly UNRATED (only 6
pre-existing unmapped symbols, unchanged). Historical frames lack the
flag key and keep legacy behavior.

## Files

- `acceptance_checklist.md` (24/24), `NOTE.md` (this file)
- `new/`: 2026-10-09 action_list.md, decisions excerpt note, detailed
  XOM/GS/JPM/ABBV, manifest.json, posthoc_stability.csv
- Mode: `retrospective_posthoc_cohort` (same limits as v1 pack).
