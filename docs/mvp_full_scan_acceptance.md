# MVP full-scan acceptance and prospective observation

> Status: operational acceptance guide for the low-frequency manual-selection MVP.
>
> This document does not change Company Quality, Entry Quality, or Action thresholds.

## 1. Goal

A full-scan acceptance run answers one operational question:

> Can the current repository use the available Alpaca + SEC environment to build a
> valid canonical `StockDecision` snapshot and compress it into the Daily / Weekly
> human-review surfaces?

The acceptance run is not a parameter-tuning exercise and is not a comparison of
legacy strategy styles.

## 2. One-command experiment

For the first real-data check, use an isolated experiment:

```bash
python scripts/run_mvp_full_scan.py
```

This command:

1. verifies the required Alpaca / SEC environment variables;
2. runs the full unittest suite;
3. runs a full watchlist scan with no `--max-symbols`;
4. writes the decision snapshot under a unique
   `outputs/decision_experiments/...` root;
5. validates the canonical JSONL, Daily Action List, Weekly Review, Detailed Reports,
   action mapping, counts, attention cap and renderer identity;
6. prints the exact Action List / manifest / log paths.

The experiment is repeatable and does not occupy the formal prospective archive.

To skip only the already-green unittest preflight:

```bash
python scripts/run_mvp_full_scan.py --skip-unit-tests
```

## 3. Formal prospective snapshot

After an experiment passes and its output looks plausible:

```bash
python scripts/run_mvp_full_scan.py --formal
```

The formal run writes the immutable prospective snapshot under:

```text
outputs/decisions/
  YYYY-MM-DD/
    <strategy_style>/
      decisions.jsonl
      action_list.md
      weekly_review.md
      detailed/
      run_manifest.json
```

A formal date/style snapshot is intentionally not overwritten.

## 4. Acceptance criteria

### Hard PASS / FAIL checks

The validator requires:

- `decisions.jsonl`, `action_list.md`, `weekly_review.md`,
  `run_manifest.json`, and `detailed/` all exist;
- the decision JSONL is readable and non-empty;
- symbols are unique;
- priorities are exactly `1..N`;
- every decision date matches the manifest;
- every Action state equals the canonical
  `map_action_state(Quality, Entry)`;
- manifest decision counts equal the canonical JSONL;
- Daily and Weekly lists do not exceed the configured attention cap;
- selected symbols exist in the canonical JSONL;
- Action List / Weekly Review are exact renderings of the selected
  `StockDecision` objects;
- every selected name has an exact canonical Detailed Report rendering.

These are correctness checks. A failure should be investigated before creating a formal
prospective snapshot.

### WARN checks

The validator warns, but does not fail, when:

- more than 50% of names are Company Quality `UNRATED`;
- more than 50% are Entry `INSUFFICIENT_DATA`;
- Daily or Weekly attention is empty;
- no name is `PRIORITY_REVIEW`;
- network/rate-limit degradation is recorded;
- stale market-data fallback is recorded.

Those outcomes can be economically legitimate, but they deserve inspection because
they may also expose coverage / freshness problems.

## 5. Validate an existing snapshot only

```bash
python scripts/validate_mvp_snapshot.py \
  outputs/decisions/YYYY-MM-DD/risk_off
```

Machine-readable output:

```bash
python scripts/validate_mvp_snapshot.py \
  outputs/decisions/YYYY-MM-DD/risk_off \
  --json
```

## 6. Which config should the MVP prospective observation use?

For the **new** product target, do not treat `risk_on` and `risk_off` as two
separate production decision systems.

The current canonical product already contains the regime distinction where it belongs:

- Company Quality answers whether the company is worth owning / following;
- Entry Quality incorporates QQQ relative strength and defensive-regime rules;
- Action is a deterministic function of Quality × Entry.

The old `risk_on` / `risk_off` pair mainly represents legacy list-filtering and
scoring choices. Those configurations remain useful for compatibility outputs and
historical evidence, but running both every day would:

- duplicate SEC / Alpaca work;
- create two prospective archives for what is intended to be one product decision;
- split the sample size of prospective evidence;
- make users ask which style is authoritative;
- partially reintroduce strategy-style abstraction above the new Quality × Entry model.

### Current operational recommendation

Until a dedicated neutral MVP config is introduced and parity-tested:

> Use `configs/config.risk_off.json` as the **single compatibility base config** for
> MVP prospective observation.

This does **not** mean the new product is philosophically “risk off”. It is simply the
existing default infrastructure config. The canonical Quality / Entry policies remain
the investment decision layer.

Keep `config.risk_on.json` and `config.risk_off.json` in the repository so legacy
outputs and historical research remain reproducible.

A future cleanup PR may introduce a neutral `config.mvp.json` containing only the
shared data-acquisition / universe parameters needed by the canonical decision path.
That cleanup should be done with parity tests; it is not required to begin prospective
observation.

## 7. What not to do after the first real-data run

Do not change frozen Quality / Entry thresholds merely because the first Action List is
too short, too long, or has names that look surprising.

First distinguish:

1. data/freshness/provenance defects;
2. implementation defects;
3. expected behavior of the pre-registered rules;
4. only later, evidence for a new policy version.

The purpose of the prospective archive is to collect evidence without rewriting the
original decision history.
