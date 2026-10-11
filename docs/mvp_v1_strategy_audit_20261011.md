# MVP v1 strategy research — baseline audit and bounded v2 hypotheses

Status: **research-only baseline; no production promotion**  
Audit date: 2026-10-11  
Source: merged evidence PR #50, \`evidence/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/\`  
Snapshot decision date: 2026-10-09; style: \`risk_off\` compatibility base  
Source scanner code SHA: \`313c5ffedc9c1cf837b70d5e95d01d545d5c592f\`  
Snapshot config fingerprint: \`a9f081748727d4a2affcf8aae93c05cfa607d45b4a2e6a6d61b413adc1070a6c\`  
The v1 Quality / Entry / Action policies remain unchanged.

## Objective and epistemic boundary

The production pipeline and PR #50 credentialed experiment passed correctness
validation, **not investment-strategy validation**. The objective is to diagnose
whether the current \`Company Quality × Entry Quality → Action List\` routing directs
human attention well, and design bounded, falsifiable v2 comparisons. This first
audit is **one live, same-date cross-section**; it cannot establish alpha,
predictive discrimination, reproducibility across dates, or optimal parameters.

Historical replay evidence and future formal prospective snapshots must be kept
separate. The existing retrospective evaluators are diagnostic, not OOS proof.
The model's current \`risk_off\` config is a compatibility base, **not** an
additional investment policy.

## Reproduce the snapshot audit (no credentials / no network)

From an installed project checkout containing merged PR #50:

\`\`\`bash
python scripts/audit_mvp_strategy_snapshot.py \
  evidence/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/
python scripts/audit_mvp_strategy_snapshot.py \
  evidence/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/ --format json
\`\`\`

This read-only tool checks symbol uniqueness, priority continuity, Action mapping,
manifest count/date/code SHA, and Daily/Weekly manifest attention membership
before calculating summaries. It deliberately **does not** compute forward returns
or tune any rule. The existing formal snapshot validator remains authoritative
for renderer correctness.

## Verified PR #50 cross-section

- 510 decisions; Quality **A=183, B=205, C=92, UNRATED=30**.
- Entry **ENTRY_READY=47**, WATCH_PULLBACK=85, WATCH_BREAKOUT=141,
  TREND_DAMAGED=230, INSUFFICIENT_DATA=7.
- Action **PRIORITY_REVIEW=19**, WATCH_PULLBACK=33, WATCH_BREAKOUT=55,
  HOLD_MONITOR=281, AVOID=122.
- EdgarTools exact-filing fallback was used for 44 cases; this was a
  data-correctness recovery, not evidence that new strategies outperform.
- All 19 \`PRIORITY_REVIEW\` symbols are Quality A and \`ENTRY_READY\`;
  the default 15-name Daily and Weekly lists omit four otherwise eligible names:
  **EXPD, ZM, JCI, SAIC** (ranks 16–19).
- The current ranking sorts first by Action class, then Quality grade,
  then **Quality score before Entry score**. Thus top-15 attention among
  \`PRIORITY_REVIEW\` is not an independently validated research-value ranking.
- **23 Quality B + ENTRY_READY** decisions are all \`HOLD_MONITOR\` under the
  deliberately simple v1 Action mapping. This is a policy choice, not a defect.
- **76 Quality A + TREND_DAMAGED** decisions are also \`HOLD_MONITOR\`.
  Review whether monitor-oriented attention is actually useful, separately
  from generating new-entry signals.
- **141 WATCH_BREAKOUT** Entry decisions, with grade breakdown A=55,
  B=57, C=21, UNRATED=8. The v1 Entry state machine uses \`WATCH_BREAKOUT\`
  as its *otherwise* fallback for sufficient-data, non-damaged,
  non-overextended, non-\`ENTRY_READY\` rows. The name alone does **not**
  demonstrate a real breakout setup; this bucket's heterogeneity requires audit.
- The watchlist \`ai_smallcap\`, \`ai_enabler\`, \`core_ai\`, and
  \`ai_peripheral\` values are **multi-label discovery provenance**,
  not industry/market-cap classifications and not a direct AI-exposure score.
  Do not use ETF membership to boost Quality, Entry or Action mechanically.

These counts are a single-date descriptive baseline. In particular, the
number of A grades, a full cap, or a high Entry Ready count **does not** by
itself demonstrate misclassification or profitability.

## Bounded v2 research questions (not proposed production changes)

### H1 — Attention-rank utility (highest initial priority)

**Question:** Within a fixed \`PRIORITY_REVIEW\` cohort, is ordering by Quality
score first better for human research outcomes than a pre-specified alternative
using both Quality and Entry evidence, state persistence, and explicit risks?

- Compare the unchanged v1 top-15 to fixed alternative ranks on identical PIT
  dates and candidate sets. Keep \`StockDecision\` and Action enum unchanged.
- Measure top-5/top-15 relevant follow-ups, reviewer acceptance/rejection and
  time spent, state churn, suppressed valid names, QQQ-relative 20/60/120d
  outcomes **as supporting diagnostics**, not as optimized targets.
- Include sectors / discovery sources descriptively; do not manufacture sector
  classification from multi-label watchlist buckets.
- Stop if changes only reorder names without a stable, interpretable gain.

### H2 — Action mapping of Quality B + ENTRY_READY

**Question:** Are the 23 B/ready observations a useful secondary research queue,
or are they correctly deprioritized by v1?

- Compare A/ready, B/ready, B/other-entry and the rest on frozen PIT cohorts.
- Use Quality confidence, relevant risk flags and economic/sector variation.
- An optional research view may show B/ready separately, but do **not** silently
  map all of them to \`PRIORITY_REVIEW\` or overwrite historical Actions.

### H3 — WATCH_BREAKOUT semantics

**Question:** Are non-damaged / non-overextended / not-ready rows genuinely
breakout candidates, or is v1's catch-all state hiding neutral/weak conditions?

- Partition this bucket using **existing** v1 evidence codes and explicit
  failed readiness predicates (e.g. SMA50 position, 60d RS, market regime).
- Compare transitions toward ENTRY_READY, deterioration, and forward
  outcomes by reason and by Quality grade.
- Prefer a research-only reason breakdown over inventing a new production
  state before outcome and usability evidence exist.

### H4 — Quality measurement robustness by accounting/business model

**Question:** Do uniform balance-sheet/profitability thresholds create
systematic mis-ranking for legitimate business-model differences?

- Inspect standard USD cases (e.g. utilities / industrial / software) by
  observed missing/risk codes, confidence and score components.
- Test whether adjustments improve explanatory correctness **without**
  broadening SEC/IFRS/FX/custom taxonomy or letting missing data become positive.
- Document metric semantics/PIT provenance before any industry-specific v2.

## Evaluation contract before any v2 proposal

1. Reuse frozen \`company_quality\` / \`entry_quality\` pre-strategy PIT datasets
   and existing evaluators:
   \`scripts/evaluate_company_quality.py\`,
   \`scripts/evaluate_entry_quality.py\`,
   \`scripts/evaluate_action_states.py\`.
   Do not launch a new expensive replay merely to collect more tuning samples.
2. For Quality: inspect 20/60/120d returns and QQQ excess by grade, annual/regime
   splits, Spearman by date, confidence/missingness and date/symbol concentration.
3. For Entry: condition on Quality A/B, inspect transitions, persistence and
   forward adverse move; avoid simply rewarding already-strong recent returns.
4. For Action: compare all states and top-k attention to suppressed names **within
   the same decision date and eligible universe**; separate ranking from candidate
   inclusion and quality coverage effects.
5. Retrospective diagnostics are not fresh OOS. Overlapping 60/120d observations
   are dependent; use decision-date aggregation and clearly marked temporal
   holdouts if a v2 candidate is eventually tested.
6. Freeze v2 hypothesis, comparator, outcomes and risk checks **before** inspecting
   holdout outcomes. A single 2026-10-09 snapshot cannot choose winning weights.
7. Preserve v1 as the prospective baseline. The approved first
   \`run_mvp_full_scan.py --formal\` can proceed independently; research code
   must not touch the formal archive or adjust live thresholds.
8. Publish any promotion proposal separately with explicit tests, evidence,
   honest failure cases, policy versioning and exact-head CI. No automatic
   promotion from retrospective wins.

## Next bounded deliverable

Read the **already frozen** cohort reports/datasets (if available in the user's
research environment), establish sample sizes/date coverage, then produce one
evaluation table for H1–H3 with missing-data and concentration diagnostics.
If the datasets are unavailable or lack reliable PIT provenance, record that
blocker; do not claim comparative performance. Only after that table should
one small research-only v2 experiment be considered.
