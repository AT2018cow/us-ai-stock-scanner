# Business-model-aware Quality & Entry diagnostics — research protocol v0

> **Research only. No production change.** No new scores, no re-weighting,
> no threshold edits, no Entry remapping, no Action changes. Question-first,
> evidence-graded, pre-registered below.

## 0. Questions (frozen)

- Q1 (banks/brokers: JPM, BAC, GS, MS): can deposits, financial
  liabilities, net interest income, credit losses and operating cash flow
  be read with general-corporate indicators, or does v1 systematically
  misread them?
- Q2 (REITs: AMT, EQIX, O, PLD): how should net income, FFO/AFFO, property
  capex and real-estate debt be interpreted? What does v1 actually reward?
- Q3 (ordinary operators: ABBV, AAPL, XOM): which generic Quality core
  indicators carry real accounting meaning across industries? Is XOM's
  filing entity usable at all?
- Q4 (Entry, same 11 names, v1 frozen): for each name, which exact READY
  conditions fail, with what evidence — and does the price-structure
  reading match that evidence?

## 1. Samples and business-model labels (with sources, not inferred)

- Bank/broker: JPM, BAC, GS, MS — SIC-major 6 (SEC submissions `sic`
  Division H: Finance, Insurance, Real Estate), broker subset flagged by
  revenue-tag vocabulary (`InvestmentBankingRevenue`,
  `BrokerageCommissionsRevenue` present in companyfacts; verified in cache
  for GS).
- REIT: AMT, EQIX, O, PLD — Nareit-style equity REITs by self-declared
  10-K business description (to be quoted per name in failure cases);
  property-owing operating model, FFO-based reporting.
- Ordinary: ABBV (pharma), AAPL (devices/platforms), XOM (integrated oil;
  filing-entity usability open — subsidiary-CIK question).
- Business-model classes come from SEC SIC + 10-K descriptions, NEVER
  from legacy AI watchlist buckets (`core_ai` etc. are discovery
  provenance, not sectors).

## 2. Method

1. PIT inventory per name (this PR): symbol → CIK → filing entity →
   latest periodic accession/date/form → currency → core-fact presence →
   v1 missing codes → identity verdict. Local SEC/Alpaca cache only.
2. Same-date functional audit (no forwards): grade × operating metrics;
   grade × SIC section; state × price structure.
3. Post-hoc diagnostic (frozen 62, 2026-09-30/10-05/10-09, chained):
   decisions + action lists + detailed reports + stability.
4. Semantics matrix (draft → review): each v1 indicator × each model
   class → applicable / doubtful / inapplicable + what specialist
   evidence would settle it.
5. Entry per-name unmet-condition table, INCLUDING silent bands (gates
   v1 evaluates but does not evidence — documented in §4).

## 3. Judgement standard (evidence grades)

- **GO (applicable)**: indicator means the same accounting fact in this
  model; cases support it.
- **DOUBTFUL**: indicator fires but the accounting referent differs;
  needs specialist evidence; no new score from this study.
- **INAPPLICABLE**: indicator cannot mean what it claims here; v1 output
  for these names must stay UNRATED-or-caveated, never re-weighted on
  this sample.
- A silent gate (no evidence item) can never support a GO.

## 4. Known v1 evidence gaps (frozen, for the record)

READY gates with no emitted evidence item when they bind:
- `relative_strength_60d_qqq` in [-10%, -3%) — verified on EQIX/AAPL
  2026-10-09 (RS -4.75%/-5.45% reconstructed from row return_60d minus
  run-manifest QQQ trailing; no RS item on either side).
- `return_60d` in [-8%, 0%) — verified on EQIX 2026-10-05 (-0.90%,
  value pinned in committed `silent_gate_inputs.csv` with source/method).
- `drawdown_from_52w_high` > 22% — no item on either side (unobserved
  in this sample; code-read confirmed).
- `price_to_sma50` in (1.08, 1.10] — no item (overextended starts >1.10).
- Volatility emits only the failing side; RS/drawdown emit nothing when
  passing either. Candidates for future evidence-completeness work —
  NOT policy changes in this study.

Reconstruction contract (review-blocking): the diagnostics builder may
only cite (a) coded items in the frozen decision, (b) RS-silent values
recomputed from frozen row+manifest inputs, (c) ret60-silent values from
the committed frozen-inputs file. Anything else — including SMA50-slice
and missing-metric rows — is labelled UNOBSERVABLE with candidate gates
enumerated, never "all gates met". "NONE" appears only for ENTRY_READY.

## 5. Deliverables and review points

- This PR (first review): this protocol + identity/PIT inventory +
  semantics matrix draft. Review direction and method, not conclusions.
- Next: failure cases, entry diagnostics table (in this PR as first
  versions), interpretation policy, reviewer notes, then evidence branch
  `runs/business-model-quality-v0/<RUN_ID>/`.
