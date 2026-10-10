# AGENTS.md

This file contains repository-wide instructions for coding agents. Keep it focused on
rules that are stable, current, and broadly applicable. Historical experiment details
belong in their evidence / handoff documents, not here.

## 1. Read first and follow precedence

Before starting substantive work, read:

1. `docs/product_direction_low_frequency_manual_selection.md` — product north star.
2. `docs/mvp_design_low_frequency_manual_selection.md` — canonical MVP architecture,
   decision contract, validation model, Build-vs-Borrow policy, and implementation sequence.
3. `docs/work_handoff_after_pr31_20261010.md` — current handoff / next work.
4. `README.md` — runtime commands, configuration, feature/filter semantics, and script reference.

If older research documents conflict with the three current direction documents above,
treat the older document as historical evidence rather than current roadmap guidance.

## 2. Product north star

The project is a **low-frequency, human-decision-support stock-selection system**:

> Find companies worth owning first; then decide whether the current price/volume
> setup is a relatively reasonable entry.

The system supports human research and manual trading. It is not currently trying to
be a complete automated trading platform.

The user-facing product is:

> **Company Quality × Entry Quality → Action List → Detailed Report**

- **Company Quality** is slow-moving and fundamentals-first: financial quality,
  growth, free cash flow, margins, capital efficiency, balance sheet, dilution,
  valuation, and material accounting / data risks.
- **Entry Quality** is faster-moving and market-data-first: trend, SMA structure,
  20d/60d momentum, pullback/breakout structure, volume, relative strength,
  overextension, and market regime.
- **Action List** is the primary daily / weekly product surface. It should normally
  compress attention to roughly 5–15 names that deserve real human review.
- **Detailed Report** is the evidence layer for the same decision.

Action List and Detailed Report must be renderers of the **same canonical
`StockDecision`**. Do not implement separate decision logic in reporting.

Preferred MVP states are intentionally small and stable:

- Entry: `ENTRY_READY`, `WATCH_PULLBACK`, `WATCH_BREAKOUT`,
  `TREND_DAMAGED`, `INSUFFICIENT_DATA`.
- Action: `PRIORITY_REVIEW`, `WATCH_PULLBACK`, `WATCH_BREAKOUT`,
  `HOLD_MONITOR`, `AVOID`.

These are research / attention states, not automated trade instructions.

## 3. Current MVP sequence

Unless a correctness defect blocks progress, follow the implementation sequence in the
MVP design:

1. decision contract + render skeleton;
2. Company Quality v1 + historical cohort evaluation;
3. Entry Quality v1 + historical state evaluation;
4. integrated Action List + Detailed Report + immutable decision snapshots.

At the end of step 4, the first MVP should be usable.

Do not expand the MVP merely because an adjacent quantitative-finance feature would be
interesting.

## 4. ETF holdings semantics — hard constraint

Source ETFs have a deliberately limited role:

> **ETF constituents are candidate-discovery / watchlist inputs, not portfolios to
> replicate and not investment conclusions.**

Allowed uses:

- periodically discover / refresh relevant underlying stocks;
- seed AI or theme candidate pools;
- retain source-ETF / ETF-count metadata as theme or discovery context.

ETF membership must not by itself imply:

- Company Quality;
- Entry Quality;
- Action State;
- portfolio weight;
- a requirement to trade or track the ETF.

Historical validation policy:

- use actually archived watchlist snapshots when they exist;
- preserve snapshot / universe provenance;
- for dates before reliable snapshot coverage, an explicitly frozen current-pool or
  union approximation may be used for retrospective diagnostics;
- label such periods as **universe approximations**, not true PIT ETF-constituent
  history and not fresh OOS evidence.

Do **not** build, scrape, or reconstruct a historical ETF holdings / weights database
for the MVP. Reconsider that only if a specific future study shows that universe drift
materially biases a decision-quality result and a simpler frozen/snapshot method cannot
answer the question.

Going forward, archive/version the watchlist produced by ETF refreshes so prospective
validation uses real observed candidate-universe snapshots.

## 5. Build vs Borrow

Keep project-specific semantics in this repository:

- point-in-time filing / as-of semantics;
- accounting normalization and TTM reconstruction;
- share-count integrity;
- valuation definitions used by the product;
- Company Quality / Entry Quality / Action mapping;
- historical `StockDecision` reconstruction;
- freshness / provenance;
- Action List compression and Detailed Report explanation.

Prefer mature libraries or thin adapters for generic infrastructure when they reduce
maintenance cost. Do not rewrite working, tested primitives solely to adopt a library.

Examples of generic capabilities that may be borrowed when needed:

- SEC/XBRL access;
- technical-indicator primitives;
- performance statistics / tear sheets;
- optional portfolio simulation.

A third-party library must never become a second implementation of Quality, Entry, or
Action logic.

## 6. Current non-goals

Do not make the following default work items:

- broker order submission;
- account / position synchronization;
- automated rebalancing;
- account-NAV simulator as an MVP prerequisite;
- position-sizing optimization;
- complex portfolio construction;
- high-frequency / intraday trading;
- broad parameter tuning;
- repeated production-threshold changes to improve historical return;
- ML / opaque composite models before the explainable MVP is validated;
- historical ETF constituent reconstruction;
- reopening the old position-gate research path.

Existing `low_value`, `momentum`, `industry_trend`, and `research_pool`
remain useful evidence sources / compatibility outputs. They are not the long-term
user-facing product abstraction.

PR #32 and earlier portfolio/live-pilot work remain historical evidence. They do not
create an obligation to build account-NAV or automated execution.

## 7. Repository layout and everyday commands

Package code lives under `src/ai_value_scanner/`. Root `run_scan.py` and
`run_backtest.py` are thin CLI wrappers.

Common commands:

- Install: `.venv/bin/pip install -e .`
- Scan: `python run_scan.py --config configs/config.risk_off.json [--max-symbols N]`
- Refresh ETF-derived watchlist:
  `python scripts/refresh_ai_watchlist.py --config configs/config.risk_off.json --output data/ai_watchlist.csv`
- Historical replay:
  `python run_backtest.py --mode historical_replay --scan-config configs/config.risk_off.json`
- Small smoke test:
  `python scripts/validate_small_scale.py --config configs/config.risk_off.json --max-symbols 100`
- Full unit tests:
  `python -m unittest discover -s tests`

Tests use stdlib `unittest`, not pytest. CI runs the same unittest command on pull
requests and main pushes. There is currently no mandatory lint / format / typecheck
job.

Environment variables are loaded from gitignored `.env` and include
`ALPACA_API_ENDPOINT`, `ALPACA_API_KEY`, `ALPACA_API_SECRET`, and
`SEC_USER_AGENT`.

Do not put credentials, cache contents, Modal volumes/checkpoints, or bulk research
outputs in Git.

## 8. Historical validation rules

Historical validation exists to test the product decisions, not to justify building a
large custom trading engine.

The preferred unit is a historical decision snapshot:

`decision_date + symbol + Quality + Entry + Action + evidence + data_asof + provenance`

Attach future outcomes separately, typically:

- 20d / 60d / 120d forward return;
- QQQ excess over the same horizon;
- optional adverse-move / drawdown diagnostics.

Required discipline:

- never call retrospective replay OOS merely because dates are chronological;
- do not treat overlapping 60d/120d rows as independent samples;
- aggregate by decision date where appropriate;
- report year / regime / symbol / date concentration;
- freeze thresholds before final comparison tables where practical;
- retrospective results cannot auto-promote production behavior;
- prospective immutable snapshots are the eventual strongest evidence.

`--allow-latest-watchlist-fallback` is off by default. If a research run uses any
universe approximation, record it honestly in metadata.

A new expensive full replay / dataset regeneration requires a specific reason why
existing frozen evidence cannot answer the question.

## 9. Data and computation invariants

### Fundamentals / SEC

- SEC data is live and can change between runs when a new filing arrives; cross-day
  byte/hash equality is therefore not a valid refactor parity expectation unless
  inputs are frozen.
- Preserve filing / accession / data-as-of provenance.
- Canonical pure accounting math lives in
  `src/ai_value_scanner/fundamentals/accounting.py`. Keep it independent of SEC/PIT
  selection, caches, prices, and strategy filters.
- Missing critical fundamental evidence must not silently become a positive Quality
  contribution.

### Prices / corporate actions

- Alpaca bars are cached raw. Split adjustment is applied at compute time through the
  existing corporate-action path.
- Do not casually replace raw/adjusted-price semantics: valuation history intentionally
  keeps raw close × raw filed shares where required for split consistency.

### Liquidity

- Default market-data feed is IEX unless explicitly changed.
- Dollar-volume metrics are therefore IEX-scale proxies, not consolidated-tape
  liquidity. Do not interpret them as real executable capacity or compare them 1:1
  with SIP-derived figures.
- Changing the feed changes liquidity semantics and must not be treated as a cosmetic
  config edit.

### Configuration

- Canonical config code is `src/ai_value_scanner/config.py`.
- New low-level code should import config names from that module; `scanner.py`
  re-exports them for compatibility.
- `channel_profiles` replaces the whole default mapping rather than deep-merging it.
  If a production config declares the mapping, a new channel must be added consistently.
- Do not infer strategy style from enabled thresholds; use explicit
  `ScanConfig.strategy_style`.
- `configs/archive/` is historical; do not edit or run archived configs as current
  production configs.

README is the detailed reference for current filter / threshold / CLI semantics.

## 10. Research / tuning discipline

Broad tuning is not part of the current MVP path.

If research requires tuning:

- use it as an explicit, bounded experiment;
- never silently promote settings;
- keep retrospective research separate from prospective evidence;
- verify any offline score-weight baseline reproduces the configured production
  weights before interpreting candidate changes;
- prefer cheap diagnostics on frozen data before launching new replays.

Do not revive historical PR-specific experiments simply because their scripts or
artifacts still exist.

## 11. Modal / heavy compute

Use Modal only when local execution is materially impractical.

Hard rules:

- **never use `--detach` or detached app execution**;
- run foreground only;
- explicitly use `MODAL_PROFILE=infi`;
- do not rely on whichever profile is currently active;
- tuner candidate concurrency must not exceed 80 in-flight containers;
- reuse persistent checkpoints/results where the run specification matches;
- stop on run-spec / manifest mismatch rather than silently resuming incompatible
  evidence;
- size resources from observed need rather than pre-allocating excessive CPU/RAM.

Cloud execution changes compute placement only. It does not make retrospective
evidence OOS.

Detailed historical Modal run procedures live in the relevant evidence / protocol
documents; do not copy old experiment-specific steps into new work unless that
experiment is intentionally being reproduced.

## 12. Coding and PR conventions

Prefer small, focused PRs with explicit acceptance criteria.

For behavior changes:

- add or update targeted unit tests;
- preserve backward compatibility unless the PR explicitly removes it;
- keep old list/report outputs working during the MVP migration unless a cleanup PR
  intentionally retires them;
- keep decision logic in shared pure functions where possible;
- renderers must consume canonical decision objects rather than recompute states;
- missing/stale data behavior must be explicit and tested.

For research/evidence PRs:

- record code/config/input provenance;
- separate canonical evidence from local working artifacts;
- keep `outputs/` and `cache/` untracked;
- store only compact reviewable evidence in Git;
- never commit `.env`, API credentials, secrets, bulk logs, or checkpoint trees.

Before merging, the final PR head should have its own green CI run. Do not rely on a
post-merge main build as the first validation of the final head.

## 13. When unsure

Before adding work, ask:

1. Does this improve Company Quality?
2. Does this improve Entry Quality?
3. Does this make the Action List more useful?
4. Does this make the Detailed Report more trustworthy?
5. Does this improve PIT correctness / freshness / provenance?
6. Is the generic part already available in a mature third-party tool?

If the answer to all six is no, the work is probably outside the current MVP.
