# Work Handoff after PR31 — product-direction reset (2026-10-10)

> **Canonical direction changed on 2026-10-10.**
>
> First read: `docs/product_direction_low_frequency_manual_selection.md`.
>
> The previous roadmap in this file targeted portfolio NAV, prospective portfolio
> validation and staged live deployment. That is no longer the primary product
> objective. The repository is now being developed as a **low-frequency,
> human-decision-support stock-selection system**.

## 1. Current repository state

Baseline verified before this direction change:

- current `main` at reset: `5ea55046c35324af11daa1cc6407a860ba984116`;
- PR31 correctness closure is complete;
- existing canonical replay / attribution evidence remains useful research input;
- PR #32 portfolio viability triage may remain useful historical evidence about
  momentum / industry_trend, but its proposed account-NAV follow-up is **not**
  the required next stage.

Do not discard prior research. Reinterpret it under the new product goal.

## 2. New product goal

The system should answer two questions separately:

> **1. Is this a company worth owning / following?**
>
> **2. If yes, is the current price / volume setup a relatively reasonable entry?**

The human remains the final decision maker.

The system is not expected to place orders, manage brokerage state, rebalance
automatically, optimize portfolio weights, or trade frequently.

## 3. Final user-facing product

The final user-facing product has two layers.

### Core: Daily / Weekly Action List

The Action List is the main product. It should be short and answer:

- which companies deserve attention now;
- Company Quality;
- Entry Quality;
- Action State;
- why the name is on the list;
- the most important risk;
- what condition should trigger the next review.

Target main-list size: roughly **5–15 names requiring real human attention**,
not a fixed number of trades.

Preferred states include:

- Buy / Entry Ready;
- Watch Pullback;
- Watch Breakout;
- Hold / Monitor;
- Avoid / Deteriorating.

These are research states, not automatic orders.

Daily output should emphasize changes. Weekly output should provide a fuller
Quality × Entry review.

### Supporting layer: Detailed Report

Every Action List candidate should link conceptually to a detailed report with:

- filing-aware fundamentals;
- growth, margins, FCF and capital efficiency;
- balance sheet, debt and dilution;
- valuation context;
- price trend, SMA structure and momentum;
- pullback / breakout / overextension context;
- relative strength vs QQQ / industry;
- explicit risks and counter-evidence;
- data freshness / provenance;
- Quality / Entry / Action history and change reasons.

Action List and Detailed Report must come from the same underlying decision
logic. The report explains the list; it must not contradict it.

## 4. Canonical mental model

### Company Quality

Slow-moving, fundamentals-first.

Use SEC and existing valuation / quality infrastructure to evaluate:

- growth quality;
- profitability;
- free cash flow;
- margins;
- capital efficiency;
- balance-sheet strength;
- dilution;
- accounting red flags;
- valuation context;
- business / AI-theme relevance.

Output should be understandable, e.g. A / B / C plus reasons.

### Entry Quality

Faster-moving, market-data-first.

Use existing momentum / industry-trend / technical infrastructure to evaluate:

- medium-term trend;
- SMA structure;
- 20d / 60d momentum;
- pullback / breakout structure;
- distance from highs;
- volume behavior;
- relative strength vs QQQ / theme;
- overextension;
- broad-market regime.

Prefer human-readable states such as Entry Ready, Watch Pullback,
Watch Breakout, Trend Damaged and Overextended.

## 5. How existing list types should migrate

Do not spend the next cycle deciding which existing list becomes an automated portfolio.

Instead:

- `low_value` contributes fundamentals / valuation / value-trap logic;
- `momentum` contributes Entry Quality and relative-strength evidence;
- `industry_trend` contributes industry / theme confirmation;
- `research_pool` remains a discovery layer.

The future user abstraction is:

> **Quality × Entry → Action List → Detailed Report**

Existing list names may remain internally during migration.

## 6. Immediate engineering priority

The next substantive PR should define the **decision-output contract**.

Before changing production scoring, define a minimal candidate model containing:

- symbol;
- company-quality grade / score;
- entry-quality state / score;
- final action state;
- top positive fundamental reasons;
- top fundamental risks;
- top technical / price reasons;
- freshness / provenance;
- state-change explanation.

The same contract should support both the compact Action List and the Detailed Report.

Do not start with weight tuning.
Do not start with account NAV.
Do not start by rewriting the whole scanner.

## 7. Suggested development sequence

### Stage A — documentation alignment

This direction-reset PR.

Done when AGENTS, README, handoff and live-pilot status no longer conflict.

### Stage B — output-contract PR

Create the schema / model for Quality, Entry and Action State, including the
shared evidence fields needed by Action List and Detailed Report.

Prefer an additive compatibility layer so existing scans still work.

Tests should cover deterministic state mapping, missing-data behavior and
Action-List/report consistency.

### Stage C — Company Quality baseline

Build a simple, explainable fundamentals grade from existing SEC metrics.

Required diagnostics include coverage, missingness, freshness, distribution by
channel / market-cap bucket, examples of upgrades / downgrades and historical
stability where PIT data supports it.

Do not optimize score weights against one pooled forward-return objective.

### Stage D — Entry Quality baseline

Use existing market features to classify price setup.

Required diagnostics include state counts, state transitions, forward returns
by state as diagnostics, regime splits, overextension / trend-damage false
positives and overlap with existing momentum / industry_trend.

The objective is useful timing context, not frequent trading.

### Stage E — Action List + Detailed Report

Combine Quality and Entry with simple deterministic rules.

Examples:

- Quality A + Entry Ready → priority manual review;
- Quality A + Overextended → Watch Pullback;
- Quality A + Watch Breakout → monitor;
- Quality C → normally suppress regardless of momentum.

Keep the main list compact; put depth in the report.

### Stage F — prospective observation

Archive actual outputs before outcomes are known.

Track whether the system:

- surfaces genuinely high-quality companies;
- avoids obvious weak fundamentals;
- distinguishes good companies from bad entry points;
- produces understandable state transitions;
- reduces the user's research workload.

### Stage G — optional portfolio tooling

Only revisit account NAV, sizing, broker integration or automated execution if
real usage later demonstrates a concrete need. They are not current success
criteria.

## 8. Validation philosophy

Historical forward returns remain useful diagnostics, but are not the sole target.

For Company Quality, prioritize financial correctness, PIT availability,
economic plausibility, stability and separation of obviously stronger/weaker businesses.

For Entry Quality, prioritize interpretable timing states, subsequent-return
separation, regime stability, reasonable state persistence and avoidance of
“chase what already went up” behavior.

For Action List + Detailed Report, prioritize shortlist usefulness,
explainability, state stability, evidence consistency and attention saved.

Do not force every module to maximize the same 120d return metric.

## 9. Low-frequency operating model

Recommended cadence:

- daily market-data refresh;
- fundamentals refresh when filings change;
- Company Quality weekly or event-driven;
- Entry Quality daily;
- Daily Action List daily, emphasizing material changes;
- Weekly Review List once per week;
- detailed report generated/refreshed for candidates as needed;
- manual research / trading only when the user decides action is justified.

A daily process may legitimately produce **no new trade**.

## 10. What not to do next

Do not:

- build the account-NAV simulator as the default next PR;
- add broker order submission;
- add automated position management;
- reopen the old position-gate route;
- launch broad tuner searches;
- optimize dozens of score weights;
- increase trading frequency to manufacture sample size;
- collapse Quality and Entry into one opaque number;
- build a detailed report with logic different from the Action List;
- regenerate expensive historical evidence without a specific need;
- use Modal `--detach`.

Modal remains available for genuinely heavy research, foreground only, with
explicit `MODAL_PROFILE=infi`.

## 11. Treatment of PR #32 and old portfolio research

PR #32 can still inform Entry Quality design:

- momentum provides useful historical signal evidence;
- industry_trend may add confirmation / context;
- style redundancy findings can prevent duplicate logic.

However:

- do not treat PR #32 as an obligation to build account NAV;
- do not tune portfolio allocations from that evidence;
- do not interpret the 50/50 proxy as the new product design.

The new question is:

> How can existing signals help identify a good entry for a financially attractive company?

## 12. Definition of success

A successful next-generation scanner should:

1. identify financially stronger companies;
2. explain why they are stronger;
3. separately identify whether current price action is favorable;
4. flag overextended or damaged setups;
5. generate a short daily / weekly Action List;
6. provide a detailed report for each important candidate;
7. show data freshness and provenance;
8. change states for understandable reasons;
9. support low-frequency human decisions without pretending to automate them.

## 13. New-conversation entry point

In a new conversation:

1. verify latest `main`;
2. read `AGENTS.md`;
3. read `docs/product_direction_low_frequency_manual_selection.md`;
4. read this handoff;
5. identify the smallest next PR that improves Quality, Entry, Action List,
   Detailed Report, explainability or data correctness.

Unless a correctness bug blocks progress, the expected next PR is the
**Quality / Entry / Action output-contract PR**.
