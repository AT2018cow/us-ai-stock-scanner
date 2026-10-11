# Research review — historical_selection_v1_20261011_03 (corporate-action fix)

**Supersedes the return tables of `..._02` (evidence commit `9c22f19`,
NOT overwritten) for label correctness. Scope unchanged: retrospective
exploratory + temporal diagnostics, union_superset_approx universe, no OOS,
no v2 promotion, no production change.**

## What was wrong in v1 labels, and what changed (v1 → v2 → v3)

1. **Split-query cutoff (FIXED, extractor+replay).** Splits with ex-dates
   past the 2026-03-31 signal-window end were unknown: 9 symbols affected
   (APH, BKNG, CRWD, CVNA, IESC, KLAC, MOVE, MQ, POWL). BKNG 25:1
   (ex 2026-04-06) printed fwd_ret_120 ≈ −0.97; KLAC 10:1 (ex 2026-06-12)
   printed ≈ −0.88. After the fix (query end 2026-09-25 covering every
   label end): BKNG −0.20…+0.29, KLAC +0.23…+1.04 (genuine fundamentals).
   50 labels corrected (SPLIT_FIX), fwd120<−0.5 rows 489 → 471.
2. **Equity continuity (NEW guard + repair).** WOLF reverse splits are
   absent from the Alpaca feed since 2020; the Sep-2025 ~23x price jump on
   flat shares, followed by the Nov-2025 share catch-up collapse, backdates
   one discontinuity to 2025-09-30. 7 spanning labels nulled (the +7x…+24x
   windfalls). 51 further share/price anomalies disclosed audit-only
   (PKG/HEI unit oscillations, LAES dilution, meme spikes) — labels kept.
3. **Live-SEC drift (disclosed, not a bug).** 64/25,025 rows changed grade
   between the _02 and _03 extractions (mostly UNRATED → graded on fresh
   filings). Expected; SEC data is live.

Row-level proof: `label_diff_by_symbol.csv` (57 rows: 50 SPLIT_FIX +
7 NULLED, exactly 10 symbols). Cohort proof: `label_diff_cohorts.csv`.

## Verdicts by dimension (v3 data)

| dimension | verdict |
|---|---|
| Engineering / integrity | **GO** (af70b5e CI + frozen SHA + SUCCESS + 545 tests + parity re-passed) |
| Provenance / scope | **retrospective-approximate** (unchanged limitation) |
| Quality diagnostic | **GO as diagnostic; INCONCLUSIVE for any v2 weight change** |
| Entry diagnostic | **GO as diagnostic; no remap** |
| Action / attention | **GO as diagnostic; E-first REJECTED; B+READY REJECTED** (reconfirmed) |
| Liquidity (H4) | **INCONCLUSIVE** (unchanged) |
| v2 policy readiness | **NO-GO to production** |

## H1–H3 on corrected labels (all prior verdicts stand)

- Quality 120d QQQ-excess (datew): A −0.029, B −0.031, C +0.105,
  UNRATED +0.033. Pattern identical to v1; C edge slightly smaller
  (WOLF windfalls removed, KLAC gains correctly placed). Rank IC still ~0.
  Composition explanation unchanged (C = distressed rebound).
- Entry (A/B): READY 120d −0.028 (still weak); PULLBACK +0.044 (still
  best); BREAKOUT reason mix stable (RS60_WEAK 1,574; reconstruction
  UNVERIFIED = 0 again); READY persistence 28%.
- Action: count parity 0 mismatches again; cap 15 vs 260–440/month;
  E-first top-15 excess h120 −0.0416 vs −0.0436 (no improvement, rejected);
  B+READY 1,117 rows, 100% HOLD_MONITOR, negative excess (not promoted).

The fix removed mechanical garbage, not signal. No conclusion flipped —
which is itself evidence the H1–H3 verdicts were not split-artifacts
(except WOLF's C-contribution, now excised and disclosed).
