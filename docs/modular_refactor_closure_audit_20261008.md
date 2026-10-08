# Modular Refactor Closure Audit — 2026-10-08

Baseline for closure: `f80d8d735be343c7f6360f3af9ec4adeff631ae7` (PR #22 merged)

## Closure question

The closure gate is **not** “is current main byte-for-byte equivalent to pre-E01?”.
That would be incorrect because several refactor-era PRs intentionally fixed
production/replay correctness defects.

The actual closure gate is:

1. mechanical extractions preserve their pre-extraction behavior;
2. intentional semantic changes are limited to reviewed correctness fixes;
3. scanner and historical replay now resolve shared semantics through the same
   canonical modules;
4. workflow/CLI/reporting/evaluation entry wiring is live and tested;
5. canonical core packages do not depend back on scanner/backtest facades.

## Evidence classes

### Mechanical / zero-drift extractions

These PRs were intended to preserve behavior:

- #7 config extraction
- #8 accounting arithmetic extraction
- #12 valuation + AI-link features
- #14 derived expectation/cycle/slippage
- #18 scoring
- #20 rules/research extraction, apart from the wiring regression fixed in #21
- #22 evaluation/reporting extraction

Evidence includes unit/golden tests, canonical-function identity tests, and
same-data-state gates where the affected layer warranted them. PR #12/#14 had
zero-drift replay evidence; later strategy/reporting extractions use the faster
snapshot/golden/identity model introduced by PR #17.

### Intentional correctness changes

Current behavior is **not supposed to match** the old pre-refactor behavior in
these areas:

- #2 anchored OOS + forward-label purge
- #10 PIT fact reconstruction/amendments/genuine year-ago rules
- #13 true SMA200 and calendar-day price lookback
- #15 share-unit reconciliation and stale-share protection
- #16 peer-cohort eligibility and minimum cohort percentile fallback
- #19 replay group caps, low-value research gate and deterministic channel
  selection parity
- #21 scanner CLI/reporting wiring repair

Therefore any future comparison to the old pre-E01 baseline must treat these as
known semantic changes, not refactor regressions.

## Final structural equivalence guards

`tests/test_modular_refactor_closure.py` pins the completed architecture:

- scanner config objects/functions are the canonical `config.py` objects;
- scanner and replay accounting/reconstruction/share-integrity functions are
  canonical fundamentals objects;
- scanner and replay derived/AI-link/peer/price/valuation functions are
  canonical feature objects;
- scanner and replay scoring/filter/rule/research/selection functions are
  canonical strategy objects;
- replay forward-return/event/summary/diagnostic functions are canonical
  evaluation objects;
- scanner/backtest reporting functions are canonical reporting objects;
- `run_scan()` and `run_backtest()` globals are bound to those modules;
- fundamentals/features/strategy/evaluation/reporting/validation packages are
  forbidden from importing scanner/backtest workflow facades;
- the reusable weight-dataset script depends on the canonical evaluation layer
  rather than a private backtest facade helper.

This protects the functional intent of the modularization after closure.

## Remaining accepted adapter dependency

`backtest.py` still imports selected constants, client/adaptor types and
legacy helpers from `scanner.py` (for example SEC/Alpaca clients and tag
constants).

This is accepted for closure because the refactor stop condition was to share
the **calculation and strategy semantics** that affect research parity:

```text
config
  -> facts/PIT reconstruction
  -> accounting/share integrity
  -> features
  -> strategy/scoring/selection/research
  -> evaluation/reporting
```

Data-client/cache/HTTP adapter extraction is not required for alpha research
and must not become another architecture project unless it blocks research.

## Known non-equivalence retained by policy

The scanner/replay non-recurring adjustment-cap policy difference documented
since PR #8 remains:

- scanner pre-caps both addbacks and gains before shared arithmetic;
- replay passes the configured cap into shared adjustment arithmetic.

This is a known accounting-policy difference, not an accidental module drift.
If future attribution shows material impact, handle it as a dedicated
correctness/policy study with golden tests and quantified historical impact.

## Validation policy after closure

Do not use a full historical replay as the default equivalence test.

- docs/reporting/mechanical wiring: unit + closure guards
- strategy mechanical move: golden + frozen Fast Gate
- strategy intentional change: OOS experiment on identical frozen inputs
- feature/fundamental correctness: targeted PIT/golden + short-window gate
- full replay: only major correctness checkpoint or production-promotion gate

## Closure decision

If PR #23 CI passes with the closure guard suite:

> **The modular refactor is closed.**

Further architecture-only splitting should stop. The next baseline should be a
fresh current OOS stock-selection baseline from post-PR23 main, because the
pre-E01 performance baseline predates intentional correctness fixes.
