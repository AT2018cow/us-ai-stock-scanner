# MVP Design — Low-Frequency Human Decision-Support Stock Selection

> Status: **implementation design / canonical MVP plan**
>
> Date: 2026-10-10
>
> Product north star:
> `docs/product_direction_low_frequency_manual_selection.md`
>
> This document records the **implemented v1 and v2 MVP architecture** and validation
> invariants. The *long-term target* is a source-agnostic US-listed-company
> research assistant, not a permanent AI-themed scanner.
> The proposed discovery-universe and business-model-aware Quality v2 contract
> is in `docs/general_purpose_discovery_and_quality_v2_design.md`, and the
> completed M0–M5 MVP v2 implementation and validation ledger is in
> `docs/mvp_v2_completion_and_handoff_20261015.md`.

---

## 1. MVP goal

The MVP is a low-frequency stock-selection assistant that answers two separate
questions:

1. **Company Quality** — is this company financially strong enough to deserve
   serious long-term attention?
2. **Entry Quality** — if the company is worth following, is the current
   price/volume setup a relatively reasonable entry?

The system then combines those two judgments into a compact **Action List** and
a supporting **Detailed Report**.

The MVP does **not** place orders, manage brokerage state, optimize portfolio
weights, or claim that historical backtests prove future profitability.

The MVP is complete when a user can run the scanner and receive a short,
auditable list of companies worth reviewing, with a consistent explanation of:

- why the company is attractive or unattractive;
- why the current entry setup is attractive or unattractive;
- what risk or missing evidence could invalidate the judgment;
- what change should cause the system to upgrade or downgrade the state.

---

## 2. User-facing MVP outputs

### 2.1 Core product: Daily / Weekly Action List

The Action List is the primary product surface.

It should answer:

> **Which companies deserve my attention today / this week, why, and what should
> I wait for next?**

The MVP Action List should normally contain roughly **5–15 names requiring real
human attention**, not a fixed number of trades.

Recommended action states:

- **PRIORITY_REVIEW**
  - strong Company Quality;
  - Entry Quality is acceptable;
  - deserves immediate human review;
  - this is not an automatic buy order.

- **WATCH_PULLBACK**
  - Company Quality is strong;
  - current setup is too extended / not attractive enough;
  - wait for normalization or a better pullback.

- **WATCH_BREAKOUT**
  - Company Quality is acceptable;
  - trend confirmation is incomplete;
  - wait for a breakout / relative-strength confirmation.

- **HOLD_MONITOR**
  - quality remains acceptable;
  - no new high-quality entry;
  - continue monitoring.

- **AVOID**
  - Company Quality is weak, the technical structure is materially damaged,
    or evidence is insufficient / stale enough that confidence is low.

The exact wording shown to the user may evolve, but the underlying state enum
should remain small and stable.

### 2.2 Supporting product: Detailed Report

The Detailed Report is the evidence layer behind the Action List.

It should explain the same decision object in more depth:

- filing-aware financial data;
- growth and profitability;
- free cash flow and cash conversion;
- balance sheet / debt;
- dilution;
- valuation context;
- price trend and moving-average structure;
- 20d / 60d momentum;
- distance from highs / drawdown;
- relative strength;
- market regime;
- risks and counter-evidence;
- data freshness;
- provenance;
- previous state and state-change reasons.

**The Action List and Detailed Report must never implement separate decision
logic.** Both are renderers of the same canonical `StockDecision`.

---

## 3. Canonical architecture

The MVP architecture is:

```text
SEC / Alpaca / watchlist data
          |
          v
existing canonical feature + PIT reconstruction layer
          |
          +-------------------------+
          |                         |
          v                         v
 Company Quality v1           Entry Quality v1
          |                         |
          +------------+------------+
                       |
                       v
                 StockDecision
                       |
          +------------+-------------+
          |                          |
          v                          v
      Action List              Detailed Report
          |
          v
 immutable decision snapshots
          |
          v
 historical / prospective evaluation
```

This design deliberately separates:

- **data acquisition / normalization**;
- **investment judgment**;
- **presentation**;
- **validation**.

---

### 3.1 ETF holdings semantics — hard constraint

ETF holdings have a **special, deliberately limited role** in this project.

> **Source-ETF constituents are a discovery / candidate-universe input. They are
> not a portfolio that this project is trying to replicate, and historical ETF
> constituent reconstruction is not an MVP objective.**

Current intended use:

- selected AI / theme ETFs are periodically inspected to discover relevant underlying stocks;
- the union of those underlying names helps seed / refresh the current watchlist or theme candidate pool;
- metadata such as source ETF names or ETF-count consensus may be retained as **theme / discovery context**;
- the scanner then evaluates the **underlying companies** using our own Company Quality and Entry Quality logic.

ETF membership must **not** by itself mean:

- the company is high quality;
- the entry is attractive;
- the stock should be selected;
- the system should copy the ETF's weight;
- the system should trade or track the ETF itself.

#### Historical validation rule

For historical decision replay:

1. use our actually archived watchlist snapshots when they exist;
2. preserve their as-of provenance;
3. where the repository lacks an old watchlist snapshot, an explicitly frozen union / fixed-pool approximation may be used for retrospective diagnostics;
4. such an approximation must be labelled as a **universe approximation**, not as true point-in-time ETF constituent history and not as fresh OOS evidence.

The existing canonical post-PR23 evidence already documents a union approximation before the first reliable watchlist snapshots. That limitation should remain visible rather than being "fixed" by inventing historical ETF holdings after the fact.

#### What agents must not build by default

Do **not** make any of the following an MVP prerequisite:

- a historical ETF holdings database;
- daily reconstruction of past ETF constituents;
- scraping archived ETF holdings pages;
- reconstructing historical ETF portfolio weights;
- ETF tracking-error / replication infrastructure.

Those tasks add substantial data-engineering complexity without directly improving the MVP's core questions:

> Is this a good company, and is this a good entry?

Historical ETF constituent reconstruction should only be reconsidered if a specific future study demonstrates that universe drift materially biases a decision-quality result and that no simpler frozen/snapshot approach can answer the question.

#### Forward-looking rule

Going forward, when the candidate watchlist is refreshed from ETF holdings, archive/version the resulting watchlist and its provenance. Prospective validation should use those real snapshots. We should improve future evidence quality prospectively rather than attempting to manufacture a perfect ETF history retrospectively.

---

### 3.2 Future market-agnostic discovery-universe contract (design only)

**The three future candidate sources are US Core Universe, Thematic Universe,
and Manual Research Universe.** These are independent, overlapping *discovery*
paths, not competing portfolios/strategies and not substitutes for the
Quality × Entry two-stage judgment.

- **US Core:** frozen, bounded, sector-diverse discovery sample of
  US-listed operating-company common stocks, chosen by documented non-performance
  criteria rather than AI/technology relevance.
- **Thematic:** optional registered themes; AI is one theme. Existing
  `core_ai` / `ai_enabler` / `ai_peripheral` / `ai_smallcap` are
  backward-compatible *legacy discovery tags*, not sector or size truth.
- **Manual:** explicit user-supplied names with reason/source date; neither
  guaranteed Action List attention nor exempt from audit and eligibility.

The future union must preserve multi-source membership, input dates, origin
files and hashes, versioned symbol/CIK identity resolution, and a strict
`discovered = decisions + exclusions` audit for enabled unique symbols.
Source tags, accounting business models and investment theme tags must be
stored separately. Do **not** reconstruct missing historical source memberships.

**Company Quality v2 must keep a common financial-quality core**, with narrow
business-model-aware evidence interpretation only after accounting-semantic
verification. Banks, insurers, REITs, foreign/unsupported reporting and
unknown models must remain explicitly uncertain / fail-closed until validated;
do not use unverified sector-based multipliers or extrapolate the old AI
universe's observed selection rates to the general US universe.

**Migration gate:** this PR updates documents only. Current
`data/ai_watchlist.csv`, `configs/config.risk_off.json`, v1 Company Quality,
Entry Quality, Action mapping, IEX liquidity prefilter, SEC fallback scope,
formal snapshots and historical experiment evidence **remain unchanged**.
Separate future code PRs must provide fixture parity, frozen-universe coverage,
cost, exclusion provenance, stable snapshots and independent GO.

See `docs/general_purpose_discovery_and_quality_v2_design.md` for the
proposed field-level membership contract, rollout sequence and the research
evidence contract.

---

## 4. Build vs Borrow policy

The project should not reimplement mature generic infrastructure unless our
domain semantics require it.

### 4.1 Keep / build ourselves

These are project-specific and remain owned by this repository:

- point-in-time filing semantics;
- historical as-of reconstruction;
- accounting normalization;
- TTM reconstruction;
- share-count integrity;
- valuation definitions used by our product;
- Company Quality logic;
- Entry Quality logic;
- Action mapping;
- historical `StockDecision` reconstruction;
- provenance / freshness;
- Action List ranking and compression;
- Detailed Report explanation;
- retrospective vs prospective evidence discipline.

### 4.2 Borrow where appropriate

Generic infrastructure should be borrowed behind adapters when it reduces
maintenance cost.

Potential tools:

- **EdgarTools**
  - useful for SEC filing / XBRL access and standardized statement extraction;
  - do not replace our PIT semantics without parity tests;
  - official docs: https://edgartools.readthedocs.io/

- **TA-Lib**
  - useful if Entry Quality later needs a broader indicator library;
  - do not replace simple, already-tested SMA / momentum calculations merely for
    cosmetic reasons;
  - official docs: https://ta-lib.github.io/ta-lib-python/

- **QuantStats**
  - useful for metrics / tear sheets once we have a return series;
  - Apache-2.0;
  - should be pinned and wrapped because reported metrics can change across
    correctness releases;
  - project: https://github.com/ranaroussi/quantstats

- **Zipline Reloaded**
  - candidate for a future simple multi-asset portfolio sanity-check adapter;
  - Apache-2.0;
  - not required for the MVP's core historical decision validation;
  - project: https://github.com/stefan-jansen/zipline-reloaded

- **VectorBT**
  - technically useful for fast vectorized portfolio experiments;
  - current upstream license is Apache 2.0 with Commons Clause;
  - therefore it is **not the default production dependency** for this project;
  - it may be used only after explicit license review if ever needed.

### 4.3 Rule

Before adding a new subsystem, ask:

> Is this generic infrastructure, or does it encode our unique investment /
> point-in-time semantics?

Generic infrastructure should usually be borrowed.
Product semantics should stay in this repository.

---

## 5. Canonical decision contract

Implementation should introduce a dedicated package, preferably:

```text
src/ai_value_scanner/decision/
    __init__.py
    model.py
    quality.py
    entry.py
    action.py
```

### 5.1 Enums

Recommended MVP enums:

```python
class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    UNRATED = "UNRATED"


class EntryState(str, Enum):
    ENTRY_READY = "ENTRY_READY"
    WATCH_PULLBACK = "WATCH_PULLBACK"
    WATCH_BREAKOUT = "WATCH_BREAKOUT"
    TREND_DAMAGED = "TREND_DAMAGED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ActionState(str, Enum):
    PRIORITY_REVIEW = "PRIORITY_REVIEW"
    WATCH_PULLBACK = "WATCH_PULLBACK"
    WATCH_BREAKOUT = "WATCH_BREAKOUT"
    HOLD_MONITOR = "HOLD_MONITOR"
    AVOID = "AVOID"
```

If an explicit `OVEREXTENDED` entry state is later useful, add it only if it
has a materially different product action from `WATCH_PULLBACK`. Avoid
creating many overlapping states.

### 5.2 Evidence item

Every judgment should be explainable from structured evidence rather than
free-text-only logic.

Recommended shape:

```python
@dataclass(frozen=True)
class EvidenceItem:
    code: str
    label: str
    polarity: Literal["positive", "negative", "neutral", "missing"]
    metric: str | None
    value: float | str | None
    threshold: float | str | None
    message: str
```

Examples:

- `revenue_growth_positive`
- `fcf_conversion_weak`
- `dilution_elevated`
- `balance_sheet_strong`
- `trend_above_sma200`
- `momentum_60d_positive`
- `price_extended_from_trend`
- `relative_strength_weak`
- `fundamental_data_stale`

### 5.3 Quality decision

```python
@dataclass(frozen=True)
class QualityDecision:
    grade: QualityGrade
    score: float | None
    confidence: float
    component_scores: dict[str, float | None]
    positives: tuple[EvidenceItem, ...]
    risks: tuple[EvidenceItem, ...]
    missing: tuple[EvidenceItem, ...]
    data_asof: str | None
```

`score` is secondary. The product-facing grade and explanation are primary.

### 5.4 Entry decision

```python
@dataclass(frozen=True)
class EntryDecision:
    state: EntryState
    score: float | None
    confidence: float
    positives: tuple[EvidenceItem, ...]
    risks: tuple[EvidenceItem, ...]
    market_asof: str | None
```

### 5.5 Final StockDecision

```python
@dataclass(frozen=True)
class StockDecision:
    schema_version: str
    symbol: str
    company_name: str | None
    decision_date: str
    generated_at_utc: str
    quality: QualityDecision
    entry: EntryDecision
    action_state: ActionState
    priority: int
    rationale: tuple[EvidenceItem, ...]
    review_trigger: str | None
    source_lists: tuple[str, ...]
    provenance: dict[str, str | int | float | bool | None]
    previous_action_state: ActionState | None = None
    state_change_reason: str | None = None
```

### 5.6 One source of truth

The canonical artifact should be a machine-readable decision snapshot:

- JSON / JSONL preferred for nested evidence;
- CSV may be emitted as a flattened compatibility export;
- Action List Markdown and Detailed Report Markdown are renderers.

The following must be impossible by design:

- Action List says `PRIORITY_REVIEW`;
- Detailed Report says `WATCH_PULLBACK`;
- both came from the same run.

---

## 6. Company Quality v1 design

Company Quality is intentionally slow-moving and fundamentals-first.

### 6.1 Existing assets to reuse

The repository already contains reusable canonical components under:

- `src/ai_value_scanner/fundamentals/accounting.py`;
- `src/ai_value_scanner/fundamentals/facts.py`;
- `src/ai_value_scanner/fundamentals/reconstruction.py`;
- `src/ai_value_scanner/fundamentals/shares.py`;
- `src/ai_value_scanner/features/valuation.py`;
- `src/ai_value_scanner/features/peer_valuation.py`.

Existing accounting work already covers data such as:

- revenue and YoY growth;
- net income / adjusted income;
- operating cash flow;
- free cash flow;
- debt / net debt;
- interest coverage;
- current ratio;
- OCF / net income;
- accrual ratio;
- receivables / inventory growth gaps;
- share-count change.

Do not reimplement these in the MVP.

### 6.2 MVP quality components

Quality v1 should use a small number of interpretable components:

1. **Profitability / cash quality**
   - profitability;
   - free cash flow;
   - OCF conversion;
   - accrual quality.

2. **Growth / stability**
   - revenue growth;
   - earnings / cash-flow growth;
   - avoid rewarding a single noisy period excessively.

3. **Balance-sheet strength**
   - debt burden;
   - interest coverage;
   - liquidity.

4. **Dilution / capital discipline**
   - share-count growth;
   - material dilution should be visible as a risk.

5. **Valuation context**
   - valuation relative to own / peer context where available;
   - valuation should not turn a weak business into Quality A.

6. **Accounting / operating red flags**
   - receivables vs revenue growth;
   - inventory vs revenue growth;
   - stale / incomplete fundamentals.

### 6.3 Important semantics

- Missing evidence must **not** silently become a positive or neutral-quality
  contribution.
- A company must not receive Quality A if critical evidence coverage is too low.
- Confidence and grade are separate.
- AI / theme relevance is an **eligibility/context** signal, not a substitute
  for financial quality.
- Exact component thresholds / grade cutoffs must be pre-registered in the
  Company Quality PR before final historical outcome tables are inspected.
- Do not run a broad optimizer over quality weights for MVP v1.

---

## 7. Entry Quality v1 design

Entry Quality should use a small, understandable set of market features.

### 7.1 Existing assets to reuse

The current canonical price feature core already provides:

- `drawdown_from_52w_high`;
- `range_position_52w`;
- `price_to_sma200`;
- `days_below_sma200`;
- `return_20d`;
- `return_60d`;
- `volatility_60d`;
- `avg_dollar_volume_20d`.

Existing `momentum`, `industry_trend`, market-regime and PR #32 research can
be used as evidence, but the new Entry decision should eventually work at the
per-stock feature level rather than merely inherit old list membership.

### 7.2 Minimal new features

Only add new Entry features if they materially improve interpretation.

Reasonable MVP additions:

- price vs SMA50;
- relative strength vs QQQ over a fixed horizon;
- optional relative strength vs industry / theme basket;
- simple recent-volume confirmation if reliable volume history is already
  available.

Do not add RSI / MACD / ADX / candlestick libraries merely to make the system
look sophisticated.

### 7.3 Entry state priority

The classifier should be deterministic and ordered conceptually:

1. insufficient/stale data;
2. trend damaged;
3. pullback / overextension condition;
4. breakout-watch condition;
5. entry-ready condition;
6. otherwise conservative monitoring.

Exact thresholds belong in the Entry Quality PR and must be frozen before final
historical comparisons.

---

## 8. Action mapping v1

Action mapping should be deterministic and simple.

Illustrative MVP mapping:

| Quality | Entry | Action |
|---|---|---|
| A | ENTRY_READY | PRIORITY_REVIEW |
| A | WATCH_PULLBACK | WATCH_PULLBACK |
| A | WATCH_BREAKOUT | WATCH_BREAKOUT |
| A | TREND_DAMAGED | HOLD_MONITOR |
| B | ENTRY_READY | HOLD_MONITOR / secondary review |
| B | WATCH_* | HOLD_MONITOR |
| C | any | AVOID |
| UNRATED | any | AVOID |
| any | INSUFFICIENT_DATA | AVOID or explicit low-confidence suppression |

The implementation should use one pure function for this mapping.

No renderer may override the result.

---

## 9. Historical validation design

Historical validation is required, but it should validate the **product
decision**, not recreate a large automated trading platform.

### 9.1 Core validation unit: Decision Snapshot

For each historical observation date and eligible symbol, reconstruct:

```text
decision_date
symbol
Quality grade
Entry state
Action state
evidence / reasons
fundamental data as-of
market data as-of
code / config provenance
```

Then attach future outcomes separately:

- 20d forward return;
- 60d forward return;
- 120d forward return;
- QQQ excess over the same horizon;
- optional forward adverse-move / drawdown diagnostic when inexpensive.

### 9.2 Reuse current historical machinery

The repository already has:

- historical replay infrastructure;
- PIT fundamental reconstruction;
- evaluation modules;
- forward-return labels;
- benchmark handling;
- evidence / provenance conventions.

The MVP should **reuse these capabilities** instead of writing a new backtester.

The new historical decision evaluator should operate as close as possible to
the canonical feature snapshot, before old list-specific hard gates remove the
examples we need to study.

In particular, Quality validation needs weak and mediocre companies as
comparators. A dataset containing only old low_value survivors is not sufficient.

### 9.3 What proves Company Quality useful?

Retrospective MVP diagnostics should include:

- count / coverage of A, B, C;
- missing-data / UNRATED rate;
- average and median 20d / 60d / 120d return by grade;
- QQQ excess by grade;
- cross-sectional rank correlation where score exists;
- annual splits;
- regime splits;
- symbol / date concentration;
- leave-one-year or leave-one-date diagnostics where practical.

The desired pattern is not one magic Sharpe ratio. It is evidence that stronger
quality grades are economically sensible, reasonably stable, and not driven by
one date / symbol / year.

### 9.4 What proves Entry Quality useful?

Entry validation should be conditioned on companies that pass a minimum Quality
standard.

Compare:

- ENTRY_READY;
- WATCH_PULLBACK;
- WATCH_BREAKOUT;
- TREND_DAMAGED.

Report:

- forward returns;
- QQQ excess;
- hit rate;
- worst-date / concentration diagnostics;
- year / regime splits;
- state transition persistence.

A useful Entry classifier should not simply reward the stocks that have already
risen the most.

### 9.5 What proves the final Action List useful?

Evaluate final Action states separately.

Primary questions:

- does `PRIORITY_REVIEW` contain stronger forward outcomes than suppressed /
  lower-priority states?
- does `WATCH_PULLBACK` avoid some adverse chase entries?
- does the Action List remain compact?
- is selection dominated by one year / symbol / industry?
- how much does the list change between observations?

### 9.6 Statistical discipline

Keep existing research standards:

- retrospective is not called OOS;
- overlapping 60d / 120d labels are not treated as independent rows;
- aggregate by decision date where appropriate;
- use block / date-level bootstrap or Newey-West when significance is quoted;
- always show year / regime / concentration;
- freeze thresholds before looking at final comparison tables.

---

## 10. Third-party backtesting role

### 10.1 What third-party tools are for

A third-party portfolio tool is useful only for a **sanity check** such as:

> If `PRIORITY_REVIEW` names were bought with a simple equal-weight,
> low-frequency rule, is the result obviously destroyed by overlap, turnover,
> costs or concentration?

This is secondary evidence.

### 10.2 What third-party tools are not for

They do not decide:

- which historical SEC data was available;
- how TTM was reconstructed;
- what Quality grade should have existed;
- what Entry state should have existed;
- whether a decision used future data.

Those remain our responsibility.

### 10.3 MVP decision

**Do not make Zipline / VectorBT a hard dependency of the core MVP.**

The MVP can be validated with historical decision cohorts.

After the MVP produces stable `StockDecision` snapshots, add an adapter if a
simple account-level sanity check is still useful.

If an adapter is added:

- prefer a permissive-license library such as Zipline Reloaded;
- keep the adapter optional;
- feed it frozen decisions rather than duplicating Quality / Entry logic inside
  the library;
- use QuantStats or another audited library for reporting metrics;
- pin versions and add fixture-based parity tests.

---

## 11. Prospective validation

Backtesting is necessary but cannot prove future correctness.

The MVP should begin prospective evidence collection as soon as the integrated
output exists.

Archive immutable daily / weekly snapshots containing:

- Quality;
- Entry;
- Action;
- reasons;
- risks;
- data as-of;
- code SHA;
- schema version.

Later attach outcomes without rewriting the original decision.

This is the strongest eventual test of whether the Action List improves human
research quality.

---

## 12. Output files

Suggested MVP outputs:

```text
outputs/
  decisions/
    YYYY-MM-DD/
      decisions.jsonl
      action_list.md
      detailed/
        NVDA.md
        GOOGL.md
        ...
      run_manifest.json
```

The canonical record is `decisions.jsonl`.

`action_list.md` and each detailed report are derived views.

The manifest should include at least:

- generated time;
- business / decision date;
- Git commit SHA where available;
- config fingerprint;
- input / data provenance summary;
- schema version;
- counts by Quality / Entry / Action state.

---

## 13. Integration with current repository

The MVP should be additive.

Do not immediately delete:

- old list outputs;
- old trade-plan compatibility tooling;
- old backtest commands;
- research evidence.

During migration:

```text
existing scanner feature frame
        |
        +--> legacy low_value / momentum / industry_trend outputs
        |
        +--> new decision layer
               |
               +--> Action List
               +--> Detailed Report
```

Once the new product is validated and routinely used, legacy outputs can be
de-emphasized or retired in a separate cleanup decision.

---

## 14. MVP implementation PR sequence

The design document itself should be a documentation-only PR.

After it is merged, implement the MVP in **four focused PRs**.

### Implementation PR 1 — Decision contract and render skeleton

Scope:

- add `decision/model.py`;
- define enums and immutable decision dataclasses;
- JSON / JSONL serialization contract;
- deterministic Action mapping;
- Action List / Detailed Report skeleton renderers that consume a
  `StockDecision`;
- no new production scoring.

Tests:

- serialization round-trip;
- deterministic action mapping;
- missing-data states;
- renderer consistency;
- schema-version fixture.

Acceptance:

> one synthetic `StockDecision` can be rendered into both product views with
> no duplicated decision logic.

### Implementation PR 2 — Company Quality v1 + historical cohort evaluation

Scope:

- implement simple, explainable Quality components using existing fundamental
  features;
- define evidence codes;
- define coverage / confidence rules;
- emit A / B / C / UNRATED;
- add historical Quality decision replay;
- add cohort evaluation by 20d / 60d / 120d outcome.

No broad tuning.

Acceptance:

- historical output has valid PIT provenance;
- grades are explainable;
- missing evidence cannot produce false A grades;
- retrospective diagnostics are produced by year / regime / concentration;
- exact thresholds are recorded before the final evaluation output is inspected.

### Implementation PR 3 — Entry Quality v1 + historical state evaluation

Scope:

- implement Entry states from existing price / momentum / regime features;
- add only minimal missing features;
- reuse PR #32 evidence as context;
- evaluate Entry states conditional on Quality A/B;
- verify state persistence and regime behavior.

Acceptance:

- deterministic Entry state;
- no list-membership-only shortcut;
- ENTRY_READY is not simply “highest recent return”;
- state outcome tables are produced with retrospective caveats.

### Implementation PR 4 — Integrated Action List + Detailed Report + snapshot history

Scope:

- create real Daily / Weekly Action List;
- create detailed candidate reports;
- rank / cap attention list;
- persist immutable `decisions.jsonl`;
- show state changes vs previous snapshot;
- integrate into daily runner in an additive, failure-contained way;
- produce an integrated retrospective Action-state evaluation.

Acceptance:

- one command produces the MVP outputs;
- Action List and reports are contract-identical;
- main list is compact;
- state changes are explained;
- snapshot archive is prospective-ready;
- legacy scanner outputs continue to work.

At this point the **MVP is usable**.

---

## 15. Post-MVP optional PRs

Only after real use exposes a need:

- third-party portfolio sanity-check adapter;
- QuantStats tear sheet;
- EdgarTools provider experiment with parity fixtures;
- TA-Lib indicator adapter;
- HTML / richer UI output;
- email / notification delivery;
- user annotations / notes;
- richer state history;
- portfolio / broker tooling.

These are not required to call the first MVP complete.

---

## 16. MVP non-goals

Do not add in the four MVP implementation PRs:

- broker integration;
- automatic order creation;
- position sizing optimizer;
- account-level strategy optimization;
- high-frequency / intraday logic;
- broad parameter tuner;
- machine-learning classifier;
- opaque composite model;
- dozens of technical indicators;
- LLM-only Quality judgments;
- new expensive historical dataset generation without a concrete need;
- automatic production promotion from retrospective results;
- Modal `--detach`.

---

## 17. MVP success criteria

The MVP is successful if:

1. every candidate has one canonical `StockDecision`;
2. Company Quality and Entry Quality are explicitly separate;
3. reasons and risks are structured and auditable;
4. Action List is compact enough for routine human use;
5. Detailed Report explains exactly the same decision;
6. historical replay can reconstruct decisions without future leakage;
7. retrospective cohort analysis shows whether Quality / Entry states have
   useful separation rather than hiding weak results;
8. prospective snapshots can begin immediately;
9. the system does not require a custom portfolio engine to be useful;
10. existing reliable code is reused instead of rewritten for novelty.

The MVP should optimize for **decision usefulness and trust**, not architecture
completeness.

---

## 18. Implementation rule for future agents

Before changing this design, answer:

- Does the proposed change improve Company Quality?
- Does it improve Entry Quality?
- Does it make the Action List more useful?
- Does it make the Detailed Report more trustworthy?
- Does it improve PIT correctness / provenance?
- Can a mature third-party tool provide the generic part instead?

If none apply, it is probably outside the MVP.

---

## 19. Implemented MVP v2 Selection & Reporting Upgrade (M0–M5 & Post-Review Hardening, 2026-10-16)

Following the M0–M5 failure-attribution and validation roadmap (`docs/mvp_v2_completion_and_handoff_20261015.md`), the repository now includes **MVP v2 (`policy_version="v2"`, `layout_version="v2"`)**, enabled by default in production configs (`configs/config.risk_off.json`, `configs/config.risk_on.json`, `configs/config.strict_candidate.json`) while keeping `ScanConfig` Python defaults at `"v1"` for unit-test backward compatibility:

1. **Share-Scope Integrity & Non-Ready Gate Completeness (Phase M1)**:
   - Point-in-time common shares (`POINT_IN_TIME_SHARES_TAGS`) are strictly separated from weighted-average shares (`WEIGHTED_AVERAGE_SHARES_TAGS`) in `fundamentals/shares.py`, with `select_consistent_share_records` enforcing YoY tag/basis consistency.
   - `decision/entry.py` emits explicit negative `EvidenceItem`s for every unmet `ENTRY_READY` condition on `WATCH_BREAKOUT` and `TREND_DAMAGED` rows (`0` silent non-ready decisions).
2. **Company Quality v2 (`build_company_quality_v2` in `decision/quality.py`)**:
   - **Sign-aware accrual scoring (`_score_accrual_v2`)**: Negative accruals (`OCF > NI`) score `1.0` when `OCF/NI >= 0.80`, eliminating false-positive `accrual_ratio_weak` penalties on cash-generative compounders.
   - **Scale-normalized profitability (`fcf_margin` & `operating_margin`)**: Replaces binary `FCF > 0` with `fcf_margin = free_cash_flow / revenue` (with graceful fallback on partial dicts) and adds `operating_margin = adjusted_ebit / revenue` to `profitability_cash`.
   - **High-growth working-capital exemption**: When `revenue_yoy >= 25%` and `ocf_to_net_income >= 0.80`, floors `receivables_growth_gap` and `inventory_growth_gap` at `0.75` and exempts them from `severe_checks`.
   - **Valuation-percentile floor**: Floors `ps_hist_percentile` and `pe_hist_percentile` at `0.35` when `fcf_yield >= 2%` or high-growth cash-generative.
   - **Reverse-split / share-basis discontinuity guard**: When `shares_yoy < -30%` or `> +100%`, neutralizes `dilution` to `0.50` and emits `shares_yoy_split_or_basis_discontinuity`.
   - **Pre-earnings window warning**: Emits informational `pre_earnings_window_risk` when `70 <= age_days <= 400` without altering `Quality` grade/score/confidence.
3. **Entry Quality v2 (`build_entry_quality_v2` in `decision/entry.py`)**:
   - **Pullback seam closure**: Healthy-trend stocks whose only readiness failure is `price_to_sma50 > 1.08` or `return_20d > 0.12` route directly to `WATCH_PULLBACK` instead of `WATCH_BREAKOUT`.
   - **Moving-average alignment gate**: Requires `sma50_to_sma200 = price_to_sma200 / price_to_sma50 >= 0.98` for `ENTRY_READY` and emits `sma50_above_sma200_aligned` (`>= 1.00`) or `sma50_below_sma200_inverted` (`< 1.00`).
   - **`WATCH_BREAKOUT` sub-bucket differentiation**: Distinguishes `watch_breakout_near_consolidation` from `watch_breakout_lagging_structure` (`-0.10` score penalty).
   - **Medium-term extension score deduction**: Deducts `0.06` (`SMA200 > 1.35x` or `60d > +35%`) or `0.10` (`SMA200 > 1.45x` or `60d > +45%`) from `entry.score` and emits non-blocking `price_extended_above_sma200` / `return_60d_extended` risk items while keeping `EntryState.ENTRY_READY` intact.
4. **Action & Priority v2 (`map_action_state_v2` & `assign_action_priorities_v2` in `decision/action.py`)**:
   - Promotes high-conviction `Quality B (score >= 0.68, confidence >= 0.80) + ENTRY_READY (score >= 0.80)` into `PRIORITY_REVIEW`.
   - Ranks `PRIORITY_REVIEW` by `0.60 * quality.score + 0.40 * entry.score + 0.04 * I(grade == A) - 0.06 * I(pre_earnings_window_risk)` and ranks remaining `ENTRY_READY` ahead of `TREND_DAMAGED` inside `HOLD_MONITOR`.
5. **Presentation IR & Report Layout v2 (`decision/view_model.py`, `reporting/decision.py`, `reporting/snapshot.py`)**:
   - Collapsible `<details>` accordion cards in Action List v2 with top `- **Pool & Concentration**:` disclosure, per-card `**Pool**:` provenance, inline warning badges (`⚠️Pre-Earnings`, `⚠️Extended`, `⚠️Share-Basis/Split`), cross-pillar `Why Own` highlights, 6-Pillar Quality Scorecard table and 7-Gate Readiness Checklist table in Detailed Report v2, and CLI support via `--decision-policy-version v2`, `--report-layout-version v2`, and `--enable-v2-shadow`.
