# Research review — historical_selection_v1_20261011_02 (H1/H2/H3 + H4)

**Evidence type: retrospective exploratory + temporal diagnostics. NOT
prospective, NOT pristine OOS, NOT a v2 promotion case.** Universe is
`union_superset_approx` for the whole 2023-01→2026-03 window (snapshots only
from 2026-09-22). No production rule was changed to produce these results.

## Verdicts by dimension

| dimension | verdict | one-line reason |
|---|---|---|
| Engineering / integrity | **GO** | exact-head CI + frozen SHA + SUCCESS + evaluator PASS + parity checks |
| Data provenance / scope | **retrospective-approximate** (PIT-universe claim: NO-GO by design) | union approx labelled everywhere |
| Quality diagnostic | **GO as diagnostic; INCONCLUSIVE for any v2 weight change** | A/B<C persistent but compositional; rank IC ~0 |
| Entry diagnostic | **GO as diagnostic; no remap** | READY rare/weak, BREAKOUT = weak-side, persistence 28% |
| Action / attention | **GO as diagnostic; E-first REJECTED; B+READY REJECTED** | identical forward excess; B+READY all HOLD + negative |
| Liquidity (H4) | **INCONCLUSIVE** | no snapshot-vs-bar pairs; see liquidity_limitations.md |
| v2 policy readiness | **NO-GO to production** | retrospective only; needs prospective + independent evidence |

## H1 — Company Quality: A/B persistently trail C, for compositional reasons

- 39/39 dates, all grades, all years: C forward excess positive (≈+0.02/+0.06/
  +0.11 at 20/60/120d), A/B negative (≈−0.007/−0.02/−0.03). Not a single-year
  artifact (C positive in 2024/2025 both regimes; only 2023-up negative).
- Cross-sectional rank IC ≈ 0 (0.021/0.005/−0.003): the score has no
  monotonic rank power in this universe/window. **Do not tune weights.**
- Composition at signal time explains the pattern without any quality
  redefinition: C = trailing +13% 60d rebounders with 31% drawdowns, median
  PE −9.4 (loss-making), 91% missing-any; A = trailing +3.9%, 18% drawdown,
  PE 24x (expensive quality), 28% missing. C is distressed-rebound
  composition, not "better quality".
- Concentration rules out winner-driving: top symbol ≤0.6% of grade rows,
  top date ≤3.2%.
- UNRATED (1,861 rows, 100% missing by construction) mildly positive at
  60/120d — fail-closed is not hiding large winners here, but the sample is
  small and approximate-universe.
- 17 rule-selected cases in `quality_failure_cases.csv` (R1 worst-A ×5,
  R2 best-C ×5, R3 unrated ×3, R4 missing-heavy A/B ×4).

## H2 — Entry: READY is rare and weak; BREAKOUT is weak-side; persistence low

- A/B rows (16,010): READY 2,041 (12.7%) with negative excess at all horizons
  (−0.007/−0.026/−0.029). PULLBACK (2,392) is the best state (+0.010/+0.040
  at 60/120d). DAMAGED (5,785) worst (−0.030/−0.050).
- BREAKOUT decomposition (4,969 rows, reconstruction UNVERIFIED=0/4969):
  dominated by weak-side reasons — RS60_WEAK 1,566; SMA50_BELOW 1,112;
  SMA200_SUB1 742; SMA50_ABOVE 517 — not by overextension (that lives in
  PULLBACK by construction). Worst forward: DEFENSIVE_RET20 (−0.066),
  RET60_NEG (−0.035), SMA200_SUB1 (−0.033).
- READY deterioration (monthly observation gaps, not daily probabilities):
  only 28% still READY next month; 46% → BREAKOUT (exc60 −0.06);
  10% → DAMAGED (exc60 −0.17); rotations into PULLBACK do well (+0.14).
- 16 cases in `entry_failure_cases.csv` (F1 ×8, F2 ×5, F3 ×3).

## H3 — Action: cap binds hard; E-first changes nothing; B+READY stays down

- Action-count parity vs evaluator compactness: **0 mismatches / 39 dates**.
  Symbol-level online lists are unavailable → `historical priority/cap proxy`.
- The cap binds every month: 15 slots vs 260–440 non-AVOID names
  (suppressed 257–440). PRIORITY_REVIEW totals range 0–56/month.
- E-first vs v1: top-15 overlap 10.7/15, top-5 overlap only 1.8/5
  (166 swaps each way) — yet subsequent excess is **identical**
  (h60 −0.0313 vs −0.0316; h120 −0.0448 vs −0.0479). Within-category
  score-order swapping does not matter because Action-category ordering
  dominates. **E-first REJECTED** (clean negative result, keep v1 order).
- B+READY: 1,120 rows, **100% HOLD_MONITOR**, forward excess negative
  (−0.009/−0.023/−0.024). Promoting B+READY would not have helped.
  **Do not promote.** The open question is the cap/attention design itself,
  not the within-list order — reserved for prospective evidence.

## Negative results kept (not hidden)

E-first no-improvement, B+READY rejection, rank IC ~0, H4 INCONCLUSIVE,
READY weakness — all retained. `candidate_policy.md` lists what stays
unchanged and what evidence would be needed to revisit.
