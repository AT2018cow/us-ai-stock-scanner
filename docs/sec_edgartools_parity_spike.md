# EdgarTools SEC parity spike

Status: historical diagnostic evidence. The spike established that exact-filing
XBRL recovers the large majority of observed ordinary 10-Q Company Facts gaps.
The bounded production follow-up is documented in
`docs/sec_edgartools_live_fallback.md`.

This document preserves the original diagnostic protocol; it is not the current
production installation/runtime guide.

This spike evaluates whether filing-level XBRL parsing from EdgarTools can explain
the SEC Company Facts coverage gaps observed in the first prospective-style MVP
experiments.

It does **not** replace the scanner SEC path and does **not** modify Company Quality,
Entry Quality, Action State, or canonical decision snapshots.

## Question this spike answers

For a decision already marked with:

- `latest_periodic_filing_not_covered`; or
- `fundamental_currency_unsupported`;

can EdgarTools read the exact latest filing accession and find core financial
concepts that our current Company Facts path did not recognize?

Core concepts for this diagnostic are deliberately small:

- revenue;
- net income / profit-loss;
- operating cash flow.

The diagnostic also records:

- filing form and filing date;
- whether filing-level XBRL is available;
- detected units / currencies;
- detected taxonomies;
- whether a standardized core concept comes from a custom taxonomy.

## Original spike installation

At the time of this diagnostic spike, EdgarTools was installed only through the optional extra:

```bash
pip install -e '.[sec-diagnostic]'
```

Normal `pip install -e .`, CI, production scans, historical replay, and Quality /
Entry calculations do not require EdgarTools.

The pinned spike version is:

```text
edgartools==5.61.1
```

Do not install the unrelated PyPI package named `edgar`.

## SEC identity configuration

EdgarTools requires an SEC-compliant identity containing a name and email.

Preferred configuration:

```bash
export EDGAR_IDENTITY="Your Name your_email@example.com"
```

The script will fall back to the repository's existing `SEC_USER_AGENT` environment
variable when `EDGAR_IDENTITY` is absent.

The diagnostic output records only which environment variable supplied the identity.
It never records the identity value.

Do not commit `EDGAR_IDENTITY`, `SEC_USER_AGENT`, `.env`, or any email address
used only for SEC access.

## Run against the live-correctness experiment

Use the canonical snapshot produced by the PR #41 validation experiment.

For the run already performed on 2026-10-10, the local experiment path was:

```text
outputs/decision_experiments/risk_off_20261010T143355Z/2026-10-09/risk_off
```

If that local output has been removed, use an equivalent checked-out evidence
snapshot containing the same `decisions.jsonl`.

Run the full flagged diagnostic plus the representative controls. Use the SHA
of the code that is actually checked out for the experiment:

```bash
CODE_SHA7="$(git rev-parse --short=7 HEAD)"

python scripts/diagnose_sec_with_edgartools.py \
  --snapshot-root outputs/decision_experiments/risk_off_20261010T143355Z/2026-10-09/risk_off \
  --all-flagged \
  --output-dir "outputs/sec_edgartools_diagnostic/2026-10-09_${CODE_SHA7}"
```

You may run on the exact PR head before merge or on `main` after merge. The
evidence must record the SHA actually used; do not copy a stale PR-head SHA after
a squash merge.

The default representative symbol set is:

```text
EXLS,JCI,PYPL,CDNS,NXPI,NEE,TSM,ASML,SAP
```

With `--all-flagged`, those controls are unioned with every integrity-flagged
decision in the snapshot. This intentionally includes SAP even if it does not carry
one of the two integrity codes.

For a smaller connectivity smoke test:

```bash
python scripts/diagnose_sec_with_edgartools.py \
  --snapshot-root <SNAPSHOT_ROOT> \
  --symbols EXLS,JCI,ASML,SAP \
  --output-dir outputs/sec_edgartools_diagnostic/smoke
```

Do not use the smoke test as review evidence.

## Output

The diagnostic writes only compact derived evidence:

```text
<output-dir>/
  diagnostics.jsonl
  summary.json
  summary.md
  run_meta.json
```

It does not persist filing HTML, filing XBRL payloads, SEC responses, or EdgarTools
cache contents in the repository.

`run_meta.json` records:

- scanner repository code SHA;
- source snapshot path;
- SHA-256 of the source `decisions.jsonl`;
- EdgarTools version;
- SEC identity source name, but not its value;
- case count and generation time.

## Classification semantics

Important classifications:

- `CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND`
  - our canonical snapshot says the latest periodic filing is not covered;
  - filing-level EdgarTools parsing finds at least one core concept;
  - this is evidence that a thin adapter / mapping improvement may recover a
    common case.

- `CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND_CUSTOM`
  - same as above, but the matched core concept is associated with a non-standard
    taxonomy;
  - useful diagnostic evidence, not permission to build a generic custom-taxonomy
    engine.

- `CURRENT_PATH_GAP_EDGARTOOLS_CORE_NOT_FOUND`
  - EdgarTools can parse XBRL but does not find the diagnostic core concepts;
  - MVP should normally continue to fail closed unless a simple common pattern is
    demonstrated.

- `CURRENT_PATH_NON_USD_EDGARTOOLS_NON_USD_ONLY`
  - confirms that the current non-USD fail-closed behavior is reasonable.

- `EDGARTOOLS_FETCH_FAILED` / `EDGARTOOLS_XBRL_UNAVAILABLE`
  - operational / filing-level limitations requiring review, not automatic
    production fallbacks.

## Stop rule

This spike must not turn into a general SEC/XBRL platform project.

A production follow-up is justified only when the evidence shows a **common,
repeatable ordinary-filer pattern** that can be fixed behind a thin adapter without
changing our PIT, accounting, Quality, Entry, or Action semantics.

Good follow-up examples:

- many ordinary 10-Q gaps become readable through the same standardized
  filing-level concepts;
- a small set of common concept aliases explains a material share of gaps;
- a narrow EdgarTools fallback can be parity-tested against our existing accounting
  contract.

Do not proceed by default with:

- complete custom-taxonomy support;
- a generic XBRL engine;
- full IFRS normalization;
- an FX service;
- production threshold changes.

If the spike shows mostly one-off custom/foreign cases or little recovery, keep the
current `UNRATED` fail-closed behavior and move on to prospective observation.

## Review evidence to submit

After running the full diagnostic, create a separate evidence PR with:

```text
evidence/sec_edgartools_parity/2026-10-09_<ACTUAL_CODE_SHA7>/
  README.md
  diagnostics.jsonl
  summary.json
  summary.md
  run_meta.json
  source_run_manifest.json
  source_validation.json
```

Copy the source snapshot's `run_manifest.json` and `validation.json` as
`source_run_manifest.json` and `source_validation.json`.

The evidence README must record:

- exact code SHA;
- exact command;
- snapshot root used;
- EdgarTools version;
- whether `EDGAR_IDENTITY` or `SEC_USER_AGENT` supplied identity
  (**name only, never the value**);
- whether any input/output was manually edited;
- the summary classification counts verbatim.

Do **not** commit:

- `.env`;
- `EDGAR_IDENTITY` or its value;
- `SEC_USER_AGENT` or email;
- raw filing HTML / XBRL;
- EdgarTools local caches;
- repository SEC raw caches;
- Alpaca caches;
- credentials;
- unrelated `outputs/`.

Review will focus on:

1. ordinary 10-Q filing-gap recovery rate;
2. whether EXLS / JCI / PYPL / CDNS / NXPI gaps are readable filing-level XBRL;
3. whether recovered concepts are standard or custom taxonomy;
4. whether ASML / TSM / SAP behavior is explained more precisely;
5. whether the result supports one narrow fallback adapter or instead supports
   stopping SEC expansion and keeping fail-closed `UNRATED`.
