# Work handoff after PR31 — strategic roadmap to a profitable stock-selection system

Date: 2026-10-10

This is the current research and product handoff after PR #31 and its
post-merge evidence closure.

The purpose of this document is not merely to describe the next maintenance
task. It defines the shortest disciplined path from the current research state
to a stock-selection process that has a credible chance of making money after
costs, can be run prospectively, can be deployed with controlled capital, and
can be stopped quickly when evidence deteriorates.

There is no guarantee of profitability. The objective is to maximize the
probability that any capital deployed is backed by reproducible signal,
portfolio-level evidence, forward validation, and explicit risk controls.

---

## 1. Current repository / evidence state

Reviewed closure state:

- PR31 merge:
  `39e46a519ce98d793fde21c41cbbe20299d9ad63`
- post-merge evidence closure:
  `fc781d744d76c6c0b916796d89c190839f3dc60b`
- current handoff/AGENTS cleanup follows that closure
- PR31 URL:
  https://github.com/AT2018cow/us-ai-stock-scanner/pull/31
- final PR31 head:
  `02ff54d744323acb7f479fbf6876a823f521438f`
- final PR31-head GitHub Actions run #136: success
- no production config change
- no production scanner/backtest change
- no production parameter promotion

PR31 correctness closure is complete:

- research dataset `channel` leakage into research assessment has been
  closed across the direct research call sites;
- canonical PR30 evidence now hard-fails on dirty Git worktrees;
- clean-checkout PR30 rerun reproduced 168/168 same-state ordered parity and
  the same negative single-gate result;
- corrected PR27 attribution changed only 10/412 downstream
  research-assessment-related cells;
- headline hard-gate attribution, direct soft failures and paired selection
  diagnostics were unchanged.

Do not repeat PR30 or PR27 attribution again unless a new correctness issue is
found.

---

## 2. The actual goal

The project goal is not:

- maximize retrospective return;
- rescue every list type;
- find a parameter set that looks best on 2023-2026;
- produce the highest backtest Sharpe by searching enough combinations;
- make `low_value` work at all costs.

The actual goal is:

> Build a small number of stable stock-selection rules that produce positive
> expected return after realistic costs, convert those signals into a
> portfolio-level strategy with controlled drawdown and turnover, validate the
> frozen strategy prospectively, then deploy capital gradually while
> monitoring for deterioration.

The fastest route to that goal is **not** necessarily to keep improving the
weakest list. Existing evidence already says that some parts of the system are
more promising than others.

---

## 3. What the evidence currently says

### 3.1 Strongest current signal families

The post-PR23 retrospective baseline shows that the return mass is primarily in
`momentum` and `industry_trend`.

Representative pooled 120d retrospective results:

- risk_off momentum:
  about +6.9 percentage points excess vs QQQ;
- risk_on momentum:
  about +6.8 percentage points excess;
- risk_off industry_trend:
  about +6.1 percentage points excess;
- risk_on industry_trend:
  about +6.4 percentage points excess.

Momentum also has the strongest ranking evidence:

- pooled 120d rank IC roughly +0.09 to +0.10;
- Newey-West t-stat roughly 4.4-4.8;
- top-minus-bottom excess roughly +6.8 to +6.9 percentage points.

This is materially stronger and more stable than the corresponding
`low_value` ranking evidence.

These are still retrospective signal-label portfolios, not account NAV.
Therefore they are **promising raw alpha**, not yet proof of a tradable
strategy.

### 3.2 Low_value remains the main research weakness

Risk_off `low_value` was weak in the frozen retrospective baseline:

- 20d excess about -0.64 percentage points;
- 60d excess about -1.19 percentage points;
- 120d excess about -1.28 percentage points.

Risk_on `low_value` was better, especially in 2023 and 2025, but the edge was
unstable by year/regime.

The ranking diagnostics show:

- positive pooled IC in some horizons;
- weak or non-monotonic decile structure;
- sign changes by year and regime;
- poor down-regime behavior in several diagnostics.

Therefore `low_value` may still contain useful information, but it is not
currently the shortest route to production alpha.

### 3.3 Position-gate hypothesis is closed

PR27 found that risk_off excluded many later continuation winners through
position/extension hard gates.

PR28 tested the broad three-gate mechanism but failed its pre-registered
validity/overlap requirements.

PR30 then isolated only:

`max_range_position_52w: hard -> soft`

with clean same-state production parity.

The result failed:

- 2024 120d delta not positive;
- 2025 120d delta not positive;
- fewer than half of mature 120d dates improved;
- block-bootstrap 90% lower bound not above zero;
- down-regime delta negative.

Conclusion:

> Do not spend more time trying to rescue alpha by relaxing the current
> position hard gates.

The position-gate research path is stopped unless genuinely new independent
evidence later supports a different interaction mechanism.

### 3.4 Broad tuner is not currently justified

The anchored walk-forward tuner did not produce a stable production candidate:

- candidate identity changed across folds;
- final 2026YTD behavior did not confirm the strongest 2025 candidates;
- all final profile/search combinations were promotion-ineligible.

Therefore a larger search is more likely to increase overfitting than to solve
the current problem.

Do not launch another broad parameter tuner until a narrow mechanism is first
shown to be stable offline and the portfolio-level objective is clearly
defined.

---

## 4. The shortest path to making money: two tracks, not one

From this point, work should split conceptually into two tracks.

### Track A — monetization / portfolio track

Goal:

> Take the already stronger signal families and determine whether they can
> produce a tradable account-level return after turnover, overlap, costs and
> drawdowns.

This track should have priority because it is the shortest path to real money.

Primary candidates:

- momentum;
- industry_trend;
- a simple momentum + industry_trend combination;
- optionally risk_on/risk_off style selection if it adds robust incremental
  value.

Low_value should be excluded from the initial minimal portfolio candidate
unless it proves incremental value.

### Track B — alpha research track

Goal:

> Improve or replace weak parts of the selector without delaying deployment of
> already stronger signals.

Primary research question:

- does the low_value **ranking / research-gate interaction** destroy useful
  cross-sectional information?

Possible later mechanisms:

- research gate is too coarse after composite ranking;
- research priority/score duplicates information already in composite score;
- research gate creates discontinuities near Top-N;
- low_value should use a different ranking objective rather than different
  hard gates;
- low_value may not deserve production capital at all.

Track B is useful, but Track A must not wait for it.

---

## 5. Definition of “ready to make money”

A signal is not production-ready merely because its average forward return is
positive.

Before meaningful capital deployment, the system needs to satisfy six layers.

### Layer 1 — signal validity

Need evidence that selected names outperform relevant alternatives after
costs.

Required diagnostics:

- rank IC;
- decile monotonicity;
- top-minus-bottom spread;
- per-year behavior;
- per-regime behavior;
- concentration by date/symbol/channel;
- robustness to Top-N choice;
- robustness to modest cost changes.

### Layer 2 — selection stability

Need to know whether tiny score changes completely rewrite the portfolio.

Required diagnostics:

- selected-symbol Jaccard;
- turnover;
- rank movement near the cutoff;
- channel overlap;
- duplicate-symbol behavior;
- leave-one-date-out / block-bootstrap stability.

### Layer 3 — portfolio-level economics

This is currently one of the largest missing pieces.

The existing post-PR23 return summaries are equal-weight signal-label
portfolios. They are not the same as a real account.

A production candidate needs a portfolio simulator that explicitly models:

- capital;
- position weights;
- rebalance dates;
- overlapping holdings;
- duplicate symbols across lists/channels;
- cash;
- entry at next open;
- exits;
- realized turnover;
- round-trip trading cost;
- mark-to-market NAV;
- drawdowns;
- exposure;
- per-symbol and per-sector limits.

Required portfolio metrics:

- CAGR / total return;
- excess return vs QQQ;
- max drawdown;
- annualized volatility;
- Sharpe and preferably Sortino;
- turnover;
- average number of holdings;
- concentration;
- worst month / quarter;
- fraction of positive months;
- cost drag;
- regime-specific performance.

Without this layer, the project can identify good stocks but still fail to make
money as an account.

### Layer 4 — chronological robustness

The final candidate must be fixed before each held-out evaluation.

Use:

- anchored chronological folds;
- purged labels at boundaries;
- no parameter choice from held-out outcomes;
- fixed candidate comparison, not a broad search.

The goal is not to maximize held-out return. The goal is to reject unstable
strategies cheaply.

### Layer 5 — prospective forward evidence

Historical data has now been examined extensively. There is no untouched
historical period left that can honestly become “new” OOS evidence.

True final OOS evidence must therefore come from **future observations after
the strategy is frozen**.

Required process:

- freeze candidate code/config;
- record commit/config/data provenance;
- archive every live signal before outcome is known;
- do not retroactively alter cohorts;
- settle 20d / 60d / 120d returns as they mature;
- compare realized selection behavior with historical expectations.

20d outcomes can provide the earliest warning signal, but they must not be used
as the sole basis for a strategy intended to earn 60d/120d alpha.

### Layer 6 — live execution and risk management

Only after the above should capital scale.

The project already has a staged live-pilot protocol. Use it rather than
jumping directly from retrospective evidence to meaningful size.

Need:

- small initial capital;
- position-size limits;
- sector/name caps;
- drawdown kill-switch;
- QQQ / market-breaker behavior;
- data-quality gate;
- weekly population validation;
- manual review initially;
- realized-vs-model slippage monitoring.

---

## 6. Recommended roadmap from PR31 to production capital

The sequence below is the preferred default. PR numbers are illustrative; the
scientific gates matter more than numbering.

### Stage 0 — correctness foundation

Status: **DONE**

Completed through PR24-PR31:

- frozen experiment protocol;
- replay checkpointing;
- Modal durability;
- anchored OOS guardrail corrections;
- style-aware survivor extraction;
- production base-weight parity;
- same-state selector parity;
- channel-column research-assessment parity;
- clean-worktree evidence provenance.

Do not reopen this stage unless a new correctness defect is found.

---

### Stage 1 — build the “minimal profitable candidate” shortlist

Priority: **NEXT**

Purpose:

> Determine which existing list/style components deserve portfolio-level
> testing before changing any alpha logic.

Use current canonical evidence. No new replay required initially.

Candidate set should be intentionally small, for example:

1. momentum only;
2. industry_trend only;
3. momentum + industry_trend;
4. optional simple style split if risk_on/risk_off adds incremental value.

Do not include dozens of combinations.

For each candidate, measure from existing signal evidence:

- date-level return;
- excess vs QQQ;
- annual consistency;
- regime consistency;
- channel concentration;
- symbol concentration;
- selection overlap;
- turnover proxy;
- incremental diversification between lists.

Key question:

> Does combining momentum and industry_trend improve stability/drawdown without
> diluting their existing alpha?

Decision gate:

Advance only candidates whose edge is:

- not one-year dependent;
- not one-symbol dependent;
- positive after current cost assumptions;
- not destroyed by removing the top contributor;
- stable enough to justify portfolio simulation.

If neither list survives this triage, stop and return to alpha research instead
of building portfolio infrastructure around weak signals.

---

### Stage 2 — build account-NAV portfolio simulation

Priority: **HIGH — this is required before claiming the system can make money**

Current signal-label averages cannot answer:

- how much capital is simultaneously invested;
- whether positions overlap;
- what turnover costs;
- what drawdown an account experiences;
- whether list overlap creates accidental concentration.

Build one canonical portfolio simulator, preferably as shared research
infrastructure rather than another ad-hoc script.

Initial version should stay simple:

- monthly rebalance to match frozen baseline cadence;
- next-open execution;
- equal-weight selected positions;
- explicit cash;
- production group caps;
- symbol deduplication;
- fixed transaction cost;
- no leverage;
- no shorting;
- QQQ benchmark.

Do **not** optimize sizing rules in the first version.

Outputs should include:

- daily or rebalance-to-rebalance NAV;
- trade ledger;
- holdings history;
- turnover;
- cost ledger;
- contribution by list/style/symbol;
- yearly metrics;
- drawdown series;
- benchmark-relative metrics.

After parity is proven, later extensions may test:

- inverse-vol weighting;
- conviction tiers;
- max position size;
- list allocation;
- defensive cash allocation;
- market breaker.

But the first simulator should answer one question:

> If we had actually traded the strongest current signals with simple,
> auditable rules, would the account have made money after costs with tolerable
> drawdown?

---

### Stage 3 — choose the first deployable portfolio candidate

The first production candidate should be the **simplest candidate that works**.

Prefer:

- fewer signal families;
- fewer parameters;
- lower turnover;
- lower concentration;
- stable year/regime performance.

Do not prefer a more complex candidate merely because it has a slightly higher
retrospective return.

A reasonable ordering is:

1. momentum-only portfolio;
2. momentum + industry_trend if diversification improves risk-adjusted return;
3. only then consider adding low_value.

Low_value should earn its allocation by demonstrating incremental portfolio
value.

Possible acceptance criteria for a first candidate should be pre-registered,
for example:

- positive net excess in multiple full years;
- no single year contributes the majority of total alpha;
- acceptable max drawdown relative to QQQ;
- positive block-bootstrap lower bound for the primary return metric or other
  similarly conservative uncertainty criterion;
- no single symbol/date dominates;
- stable performance under higher-cost stress;
- acceptable turnover.

Exact thresholds should be specified **before** looking at the candidate's
final portfolio result.

---

### Stage 4 — narrow low_value research in parallel

This stage should not block the first portfolio candidate.

The next low_value mechanism should address ranking/research interaction, not
position hard gates.

The highest-value first diagnostic is:

> Compare the production composite ranking before research assessment with the
> final post-research-gate ranking/selection on the same frozen rows. Measure
> whether the research layer improves or destroys forward-return monotonicity.

Useful outputs:

- IC before vs after research assessment;
- decile monotonicity before vs after;
- Top-N return before vs after;
- symbols removed by research gate;
- symbols promoted/demoted by research priority;
- forward-return difference for removed vs retained names;
- year/regime/channel splits;
- selection Jaccard;
- concentration;
- block-bootstrap uncertainty.

A clean first mechanism test could be one of:

- research gate disabled but research score retained;
- research score used as a small ranking term but not a hard gate;
- current research gate vs composite-score-only ranking.

Choose **one** mechanism after diagnostics. Pre-register it before looking at
the A/B outcome.

Do not launch weight tuning until the ranking/gate structure itself is shown to
be sensible.

---

### Stage 5 — anchored robustness of the fixed portfolio candidate

Once a simple portfolio candidate exists, freeze it and run chronological
validation.

Important distinction:

- use the tuner infrastructure as an evaluation harness if useful;
- do not reopen a large search space.

Test the **fixed candidate** across:

- 2023;
- 2024;
- 2025;
- 2026YTD diagnostic;
- up/down regimes;
- higher transaction costs;
- Top-N perturbation;
- modest rebalance-date perturbation if practical.

The goal is to answer:

> Does the same simple strategy remain acceptable when we stop changing it?

If a candidate only works after choosing different settings in every fold, it
is not ready.

---

### Stage 6 — prospective paper / shadow portfolio

This is the first genuinely new OOS phase.

Freeze:

- code SHA;
- config SHA;
- list allocation;
- Top-N;
- rebalance schedule;
- sizing;
- cost assumptions;
- stop/kill rules.

Then archive live signals before outcomes are known.

Track:

- selected names;
- actual next-open prices;
- theoretical fills;
- realized holding returns;
- turnover;
- portfolio NAV;
- benchmark NAV;
- signal drift;
- data freshness;
- missing-data incidents.

Do not change the candidate every week.

If a serious correctness defect is found, fix it, version the strategy, and
restart the prospective clock for the changed component.

---

### Stage 7 — staged real-capital pilot

Use the existing `docs/live_pilot_protocol.md`.

The purpose is not to maximize early profits. It is to test whether research
returns survive contact with real execution.

Start with capital small enough that a full stop does not matter financially.

Before increasing capital, require:

- data pipeline healthy;
- no unresolved provenance issue;
- paper/live selection concordance;
- realized slippage within assumptions;
- no unexpected liquidity issue;
- drawdown within pre-registered band;
- no repeated operational failures;
- forward evidence not materially contradicting the frozen thesis.

Scale only in steps.

Never compensate for weak performance by increasing risk.

---

### Stage 8 — monitoring, kill-switches and research cadence

A profitable strategy can stop being profitable. Production needs explicit
degradation detection.

Monitor at least:

- rolling excess return;
- rolling hit rate;
- realized vs expected turnover;
- rank IC on matured forward outcomes;
- list contribution;
- concentration;
- drawdown;
- data freshness;
- missing SEC/price inputs;
- signal-count drift;
- regime changes.

Define actions in advance:

- warning;
- freeze new entries;
- reduce capital;
- stop strategy;
- return to research.

Avoid continuous parameter tweaking.

Prefer scheduled research reviews, e.g. monthly or quarterly, unless an actual
correctness defect requires immediate action.

---

## 7. Suggested PR sequence

The exact numbering may change, but the work should roughly proceed as follows.

### Next PR: portfolio viability / candidate triage

No production change.

Build compact evidence comparing:

- momentum;
- industry_trend;
- momentum + industry_trend;
- risk_on/risk_off incremental contribution.

Use existing canonical replay outputs first.

Deliverable:

- shortlist of 1-2 portfolio candidates;
- explicit rejection reasons for the others;
- no parameter tuning.

### Following PR: canonical portfolio NAV simulator

No alpha tuning.

Implement account-level mechanics and parity tests.

Deliverable:

- NAV;
- holdings;
- trades;
- turnover;
- costs;
- drawdown;
- benchmark;
- contribution analysis.

### Following PR: fixed-candidate robustness

Freeze the best simple candidate.

Run chronological / cost / concentration stress.

Deliverable:

- go/no-go decision for prospective paper portfolio.

### Parallel or subsequent PR: low_value ranking/research-gate diagnostic

Use frozen survivor data.

Do not change production behavior yet.

Deliverable:

- one pre-registered mechanism or a decision to remove/deprioritize low_value.

### Then: prospective portfolio infrastructure

Archive forward cohorts and account NAV without hindsight.

### Then: staged live pilot

Only after prior gates pass.

---

## 8. Decision tree for speed

To avoid months of low-value research, use this decision logic.

### If momentum / industry_trend portfolio-level NAV is strong

Then:

1. freeze a simple candidate;
2. run robustness;
3. begin prospective paper/shadow validation;
4. prepare staged live pilot;
5. continue low_value research separately.

This is the preferred fast path.

### If signal-label returns look strong but NAV is weak

Likely causes include:

- overlap;
- turnover;
- concentration;
- holding-period mismatch;
- cost drag;
- poor portfolio construction.

Fix portfolio mechanics before changing alpha.

### If both signal-label and NAV evidence weaken under robustness

Do not tune harder.

Return to signal research and ask whether:

- universe definition;
- scoring objective;
- research layer;
- regime model;
- horizon choice

is fundamentally wrong.

### If low_value improves but adds no portfolio diversification

Do not allocate to it merely because its standalone return becomes positive.

Every extra component should justify complexity by improving:

- expected return;
- drawdown;
- stability;
- diversification;
- or capacity.

---

## 9. What “fast” means in this project

Fast does **not** mean:

- more candidates;
- more Modal containers;
- more parameter search;
- more retrospective years;
- more relaxed significance gates.

Fast means:

- reuse frozen data;
- eliminate weak hypotheses quickly;
- test the strongest existing signals first;
- build portfolio economics early;
- minimize degrees of freedom;
- freeze candidates sooner;
- start prospective evidence sooner;
- deploy tiny capital before large capital;
- stop bad strategies quickly.

The main opportunity cost now is continuing to optimize retrospective stock
scores without first proving that the already stronger signals can generate a
good account-level NAV.

---

## 10. Research / validation standards that remain mandatory

### Retrospective vs OOS

Never call a retrospective replay OOS merely because it uses chronological
dates.

Anchored walk-forward evaluation is stronger than pooled retrospective
analysis, but once many research decisions have been made from the same
historical windows, the final unbiased evidence must be prospective.

### Overlapping labels

Monthly 60d/120d outcomes overlap.

Use:

- Newey-West where appropriate;
- moving/block bootstrap;
- date-level rather than symbol-row independence assumptions.

Do not quote raw row counts as independent sample sizes.

### Concentration

Always report:

- top symbol contribution;
- top date contribution;
- leave-one-date-out range;
- year concentration;
- channel concentration.

### Costs

Current frozen baseline uses 15 bps per side / 30 bps round-trip.

Portfolio validation should also stress higher costs.

IEX dollar volume is only an approximate tape-scale proxy; do not infer live
capacity directly from IEX-scale dollar-volume numbers.

### Data provenance

Canonical research evidence requires:

- clean Git checkout;
- commit SHA;
- tree SHA where supported;
- config hash;
- dataset hash;
- explicit frozen input paths;
- no silent fallback.

---

## 11. Modal / compute policy

User requirement:

> **Never use Modal detach.**

If Modal is required:

- foreground `modal run` only;
- explicit `MODAL_PROFILE=infi`;
- never rely on active/default profile;
- tuner candidate concurrency <= 80;
- persistent results on `ai-scanner-research`;
- reuse checkpoints;
- no expensive replay when existing frozen datasets answer the question.

The next portfolio-triage and low_value diagnostic work should primarily be
offline using existing evidence.

A new multi-year replay or broad Modal run requires a written reason why the
existing frozen artifacts are insufficient.

---

## 12. Production-risk principles

The strategy should eventually answer four different questions separately.

### Selection

Which stocks should be owned?

### Sizing

How much should each stock contribute to portfolio risk?

### Timing

When are selections entered, refreshed and exited?

### Risk control

When should new exposure be reduced or stopped?

Do not try to solve all four by tuning one composite stock score.

The current project is strongest on selection research and still needs more
work on portfolio sizing/timing/economic validation.

---

## 13. What should not be done next

Do not:

- reopen the position-gate relaxation path;
- tune `max_range_position_52w`;
- launch another 36-candidate search because PR30 failed;
- optimize low_value before testing strong-list portfolio economics;
- change production thresholds from retrospective evidence alone;
- interpret equal-weight signal-label portfolios as account NAV;
- regenerate frozen datasets without a correctness need;
- run full replay just because compute is available;
- increase model complexity without a measurable portfolio benefit;
- use Modal `--detach`;
- deploy meaningful capital before portfolio-level and forward validation.

---

## 14. The immediate next task

The next conversation should **not** begin with another low_value tweak.

The first task should be:

> Build a compact portfolio-viability / list-triage PR using existing
> canonical evidence to compare momentum, industry_trend, and their simple
> combination, quantify stability/concentration/overlap/turnover, and define
> the smallest portfolio candidate worth taking into account-NAV simulation.

At the same time, keep a separate research backlog item for:

> low_value pre-research ranking vs post-research-gate monotonicity.

The first item is the faster route to money.

---

## 15. Definition of project success

The project is not “done” when one backtest looks good.

A successful system should eventually have:

1. reproducible stock selection;
2. positive portfolio-level expected return after costs;
3. tolerable drawdown and turnover;
4. robustness across years/regimes;
5. no extreme dependence on one stock/date;
6. prospective paper evidence;
7. real execution consistent with model assumptions;
8. staged capital deployment;
9. automatic health monitoring;
10. explicit stop conditions when the edge disappears.

Only then can the system be described as a credible process for making money
rather than a research scanner that finds attractive historical examples.

---

## 16. New-conversation entry point

Use this document as the long-horizon roadmap.

The next conversation should verify current main, then start Stage 1:
portfolio viability / candidate triage.

Do not let the conversation collapse back into “what is the next small bug or
parameter to change?” unless a correctness issue blocks the roadmap.
