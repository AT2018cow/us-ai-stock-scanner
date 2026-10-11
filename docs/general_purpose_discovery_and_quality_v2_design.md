# General-purpose US stock discovery and business-model-aware Quality — design contract

> Status: **design proposal only** (2026-10-11). Not a production migration.
> This document extends `docs/product_direction_low_frequency_manual_selection.md`
> and `docs/mvp_design_low_frequency_manual_selection.md`.
> Baseline PR #53 evidence and any existing formal prospective snapshots remain immutable.

## 1. Long-term product objective

Select financially attractive **companies across US-listed equities**, then
independently assess whether their listed securities offer reasonable entry setups:

```text
US Core discovery ---+
Thematic discovery --+--> versioned union + provenance --> current eligibility/coverage gates
Manual discovery ---+                 |
                                    v
                         Company Quality × Entry Quality
                                    |
                       StockDecision / Action List / Detailed Report
```

**AI is an optional thematic lens, not a universe prerequisite, Company Quality
bonus, Action override or definition of the market.**

Preserve the MVP's low-frequency, human-reviewed 5–15-name Action List, no
automatic orders or portfolio engine. This design expands *who can be considered*,
not what a successful investment or a tradable signal means.

## 2. Three independent, overlapping discovery sources

| Source | Purpose | Initial design | Explicitly not |
| --- | --- | --- | --- |
| `us_core` | Market-agnostic, cross-industry coverage | Bounded and frozen snapshot of diverse US-listed operating-company common stocks selected by documented non-performance rules | All US tickers, SPY/QQQ portfolio tracking, implicit proof of Quality |
| `thematic` | Targeted research lenses | Configurable topic ID(s); retain the old AI ETF/watchlist pool as **one** topic | Default investment style, implicit theme alpha, Quality score weight |
| `manual` | Human-researched names independent of themes | Explicit ticker additions with source/as-of/review notes | Guaranteed Quality grade, exemption from the eligibility/audit contract or forced top-15 placement |

### US Core scope

- Start with a **bounded**, pre-registered, sector-diverse US-listed common-stock
  discovery sample rather than an unrestricted thousands-name full-market scan.
- Define the source membership snapshot, size and rules **before** evaluating
  Quality, Entry, returns or Action results. Avoid using historical winners,
  current A grades or post-hoc backtests as the seed list.
- Listing in the US is a discovery condition, **not** a claim of domestic SEC
  10-K/10-Q USD coverage. Foreign reporters, non-USD issuers and unsupported
  financial structures retain explicit fail-closed data/coverage statuses.
- ETFs, funds, warrants and preferred securities are not operating-company
  common-stock seeds in the first US Core cohort. Do not silently erase them
  from a source file: record why they were not admitted, if applicable.
- Use documented, observable fields for sector/size diversification, with
  `UNKNOWN` when mapping is unavailable or uncertain.

### Thematic scope

- AI becomes an optional `theme_id=ai` source. Other themes require an explicit
  separate source definition; do not invent them from keyword matches.
- Existing `core_ai`, `ai_enabler`, `ai_peripheral`, `ai_smallcap` are **legacy
  AI discovery buckets**, retained unchanged as old v1 source provenance.
- `ai_smallcap` is NOT a validated small-cap classification, and
  `ai_enabler`/`ai_peripheral` are NOT audited business sectors.
- ETF members are source hints only, never a portfolio replication task and
  never a direct Quality/Entry/Action contribution.

### Manual scope

- Preserve user-added symbol, reason, as-of and active/inactive status.
- A manual addition does not override SEC coverage, missing facts, exchange
  eligibility, feed, liquidity, executionability, or the attention cap.
- Manual-only names must still appear in the union or an explicit pre-decision
  exclusion. Do not silently drop them for lack of theme or ETF membership.

## 3. Canonical candidate membership contract — proposed for a later code PR

Minimum conceptual fields for every source membership (schema to be versioned
by the implementation PR, not silently inserted into current production CSV):

```text
input_snapshot_id          # immutable source file identity / hash
source_kind                # us_core | thematic | manual
source_id                  # stable source-specific ID, e.g. theme:ai
source_asof                # when membership was valid/known
collected_at_utc           # provenance when file was collected
symbol_raw                 # original exchange/share-class ticker
canonical_symbol           # normalized matching key; do not collapse by CIK
issuer_cik                 # optional, checked separately; never fabricated
theme_id                   # optional thematic tag, nullable for core/manual
legacy_bucket              # optional preserved v1 discovery provenance
member_status              # current source inclusion/exclusion status
source_fingerprint         # content-hash or upstream version
```

**Deduplication and identity:** union exact canonical tradable symbols
without losing the many-to-many source memberships. Common-share classes
of the same issuer (e.g. dotted tickers) may be different securities;
**never collapse by CIK**. Normalize symbol aliases only with versioned,
testable market-data/SEC mappings; unresolved symbols get an auditable
mapping/eligibility status instead of a guessed identity.

**Invariants for the combined discovery universe:**

- Every enabled symbol with >=1 valid source membership appears **exactly once**
  as a decision symbol or exactly once in pre-decision exclusions.
- Preserve **all** memberships and the frozen source files/as-of/hashes;
  one candidate can be core+theme+manual concurrently.
- Account for source-level rejected/invalid rows separately; do not falsely
  claim symbol-level conservation covers raw invalid input lines.
- No new source type may bypass the current eligibility and fail-closed
  fundamentals checks without an explicit separately reviewed policy PR.
- The current `universe_exclusions.jsonl` contract remains the first audit
  baseline; a new schema/version is required for any backward-incompatible
  membership or exclusion representation.

Keep three distinct classifications, never substitute one for another:

1. `discovery_sources` (how a company was found),
2. `business_model` / reliable sector classification (how to interpret accounts),
3. `themes` (what cross-industry research narrative may apply).

## 4. Company Quality v2 design — shared core plus narrow business-model interpretation

Preserve the **conceptual** Company Quality × Entry Quality split and the
single StockDecision/Action List contract. Do not design a dozen different
scoring strategies for every sector.

### Common cross-industry core (no unreviewed v1 policy changes)

Research the stability and provenance of:

- normalized profitability and cash generation;
- revenue and operating performance trends;
- dilution and share-count integrity;
- reporting freshness, currency and missingness;
- accounting anomalies and demonstrable red flags;
- debt/solvency and valuation **only where their economic semantics apply**.

### Narrow, versioned interpretation groups (hypotheses, not v2 weights)

| Business-model group | First concerns to inspect | Guardrail |
| --- | --- | --- |
| Asset-light recurring revenue / software | cash conversion, dilution, recurring economics | Do not assume high multiple means high Quality |
| Cyclical manufacturing / semiconductors / industrials | inventory, margin cycle, capex, FCF volatility | Do not mechanically punish all cyclical cash flow |
| Capital-intensive regulated utility / infrastructure | regulated revenues, structural debt, reinvestment, coverage | Do not treat debt as harmless or FCF deficits as automatically healthy |
| Commodity producers / materials | price-cycle dependence, reserves/capex, earnings normalization | Do not label peak-cycle profitability as persistent |
| Financials / insurance / REIT and unknown | specialized statements, financing structure, coverage | **Do not assign cross-sector-comparable v2 Quality** until the specific financial semantics have validation |

Use a small, versioned business-model classifier with known/unknown and
source/as-of/coverage. Never infer it solely from `ai_smallcap`/ETF holdings.
Possible differences should initially change *interpretation/report evidence*,
not retroactively alter the v1 A/B/C scoring formula.

### Evaluation gate before any production v2 change

- Compare v1 vs **pre-specified** candidate changes on the **same PIT eligible
  cohort**, separating the effect of universe expansion from scoring changes.
- Report cohort counts, true sector/business-model coverage, unknowns,
  confidence, stale facts, unsupported USD/forms, red flags and disagreements.
- Use temporal splits, group-wise 20/60/120-trading-day outcomes and QQQ/SPY
  context **as diagnostics**; explain benchmark and avoid overlapping labels
  as independent samples. No after-the-fact winning weight selection.
- Entry v1 currently uses QQQ-related evidence; benchmark-neutral and
  sector-relative alternatives may be researched separately, **not silently
  substituted** in the generalized universe.
- Version the classifier/Quality policy only after tests, audited disagreement
  cases, bounded experiments and explicit GO for promotion.

## 5. Migration plan and acceptance gates

**Design PR (this PR):** docs only. Product north star becomes market-agnostic;
existing AI watchlist, scanner CLI, config and historical evidence stay as-is.

**Implementation PR A — versioned discovery union, no strategy changes:**
1. Accept a bounded frozen US Core, optional AI theme, and Manual fixtures.
2. Exact symbol/member provenance, source overlap and source-level exclusions.
3. Deterministic merging and stable serialization; fixture unit tests.
4. Preserve existing legacy single-file watchlist behavior if new sources
   are not configured; keep `config.risk_off.json` as the identical v1 baseline.
5. Existing pre-decision IEX `$2m` gate remains unchanged, plus explicit
   `universe_exclusions` reasons. No silent unsupported form/currency upgrade.
6. Add a **separate experiment** comparing old vs new frozen candidate coverage,
   API/caching bounds and action distribution, not a historical return claim.

**Research PR B — audit business-model coverage on frozen comparable cohorts:**
1. Produce actual source/sector/business-model cross-tabs, not label guesses.
2. Identify v1 Quality metric semantics and confidence failure modes.
3. Prototype only small, interpretable v2 evidence changes behind versioned
   research code. Keep current v1 Action selection unchanged.

**Optional implementation/promotion PRs:** only after independent evidence GO.
Never overwrite any prior `--formal` snapshot or relabel a legacy experiment
as general-market performance. Keep prospective v1 and proposed v2 cohorts
separate and explicitly versioned.

## 6. Review evidence to submit for this design PR

No credentialed run, no watchlist refresh and **no experiment evidence needed**.
Review the north-star/design diff and check that all preserved invariants are
explicit. Run the normal exact-head Python 3.12 CI. No ZIP or evidence-only PR.

Each **future** implementation PR must pre-declare its external experiment
command, exact frozen inputs and code SHA, coverage counts, source-membership
JSONL/CSV, old vs new conservation, validator PASS/FAIL, network budget,
manual-review cases and forbidden secrets/raw caches. Submit ordinary
browsable Markdown/JSON/CSV/JSONL evidence files with SHA256 and a pinned
commit, consistent with the proposed evidence workflow in PR #54.

## 7. Explicit non-goals

- No new automatic trading, broker/portfolio/NAV/position gate work.
- No broad new SEC/IFRS/FX/custom taxonomy integration.
- No full-market scraping, historical ETF constituent reconstruction or
  automatic AI theme expansion.
- No live production watchlist changes, no v1 Quality/Entry/Action thresholds
  or rating reinterpretation, no arbitrary sector scoring multipliers.
- No claim that US Core coverage, theme rotation or Quality v2 outperforms
  without independently validated PIT and prospective comparisons.
