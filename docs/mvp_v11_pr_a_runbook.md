# MVP v1.1 PR-A: offline optimizer development (draft)

This PR is **not an experimental result**. It does not change default v1 production
decision or the risk_off configuration. Research must stop at A0 until corrected
historical v3 inputs, as-of provenance, and baseline parity have been verified.

## Implemented in this initial commit

- Immutable 11-slot candidate semantics (B0, R1–R5, E1–E4, conditional X1).
- A0 structural CSV + sibling .meta.json gate (dataset kind, pre-strategy,
  normalized signal_date×symbol uniqueness, date-level future as-of,
  per-horizon paired-label coverage, file SHA256).
- Offline R-only ranking that preserves canonical Action/Grade groups,
  applies registered weights/penalties, and falls back conservatively
  for missing scores. It does not change the canonical StockDecision factory.

## Not implemented / blocking further experiments

- Recovery and independent audit of corrected v3 full CSV/metadata/splits,
  51 event exceptions, filing public timestamps, true label cost assumptions.
- Canonical B0 row-by-row Quality/Entry/Action/priority parity to registered
  historical decisions; all date slices and source identity checks.
- E1–E4 versioned canonical Entry threshold recomputation, state migration and
  explanation parity (do not manually replace Entry state text).
- X1 lock rules, paired return comparator with fixed masks, temporal diagnostics,
  risk sensitivity, immutable manifests and append-only evidence packaging.

Do **not** execute candidate return comparisons from this initial commit.

## Review evidence to submit — read-only A0 run

Only when corrected v3 datasets have been located, on a clean checkout of this
exact PR HEAD and with dependencies installed:

```bash
python -m unittest discover -s tests
python scripts/mvp_v11_a0.py \
  --quality-dataset /ABS/PATH/corrected_company_quality_v3.csv \
  --entry-dataset /ABS/PATH/corrected_entry_quality_v3.csv \
  --output outputs/mvp_v11_a0/structural_gate.json
```

The paths are placeholders, **not claimed to exist**. These corrected v3 CSV
files have names ending in `.v3.csv`, whereas the archived metadata uses
`.meta.json` without `.v3`. Therefore, use the explicit `--quality-meta`
and `--entry-meta` options pointing to verified matching originals. Do not
rename/alter historical evidence to satisfy a path convention. If the matching
metadata is in a different directory, supply that path.

Send for review the small `structural_gate.json` and redacted test summary,
the exact checked-out commit SHA, paths/filenames and dataset SHA256. Do not
commit raw CSV, credentials, env files, Alpaca bars, Modal caches, or large
logs. Because structural validation does not prove PIT/price labels, submit
the corrected source study manifest and splits separately before B0 parity.

**Experiment classification:** retrospective A0 inventory, not formal,
not an OOS backtest; no paid Modal compute required. The gate overwrites no
previous audit file. Review questions: are both source kinds correct and
verified, are 39 signal dates and 25,025 raw rows accounted for without
inventing missing labels, are filing/identity caveats documented, and can
current v1 reproduce the same fixed observations?

Future work and paired evidence remain **inside this PR-A**. A second PR
will be opened only for one selected, approved opt-in v1.1 implementation.
