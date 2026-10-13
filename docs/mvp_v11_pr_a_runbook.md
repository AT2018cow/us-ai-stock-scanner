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
  --quality-dataset /ABS/PATH/company_quality_dataset_risk_off.v3.csv \
  --quality-meta /ABS/PATH/company_quality_dataset_risk_off.meta.json \
  --entry-dataset /ABS/PATH/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta /ABS/PATH/entry_quality_dataset_risk_off.meta.json \
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

## A0 review accepted; move to B0 (2026-10-14)

A0 evidence is stored in `evidence/mvp-v11-a0-20261014/` on PR-A.
The local corrected v3 CSV hashes match the archived _03 study manifest:
`2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`.
The 25,025 rows, 670 symbols, 39 monthly dates, 2 missing 60d and 5 missing
120d labels agree with the WOLF continuity audit. This is **STRUCTURAL PASS**
only. 346 rows have missing fundamental as-of and 51 anomalies are audit-only.

A0 did not prove intra-day SEC filing availability, economic security identity,
or that the 51 audit-only labels are reliable. Keep this caveat in every
subsequent recommendation. The archived `fwd_ret` and `qqq_return`
columns each embed approximately 30bps roundtrip cost; do not subtract costs
a second time.

### B0 historical parity run (no candidate outcomes)

**Check the exact PR-A HEAD CI first.** Do not merge PR-A into main. Use the
same frozen `entry_quality_dataset_risk_off.v3.csv` input as A0. This new B0
script strips future returns, label dates, and continuity flags before
feeding rows through `build_stock_decisions`. The output is a MONTHLY
historical priority/cap proxy, not a Daily/Weekly state-change replay.

The original evidence branch contains two **frozen, independently archived**
references:
- `ranking_paired_by_date.csv` SHA256 `4b0d25e0ad54c394a5eeed2ed47a2c4f0ba01fae29cc8d793f573980a2d88d51`
- `action_v1_compactness.csv` SHA256 `91107b89b2237f612677037f7b771a552b07130559cccdee98eea8068cfe5942`

Locate these in the local copy of
`evidence-observations:runs/historical-selection-v1/historical_selection_v1_20261011_03/`,
or export immutable copies using `git show`, after fetching that branch.
Keep the copies under ignored `outputs/`, never overwrite the archived
Git branch.

```bash
git fetch origin
git fetch origin evidence-observations
git rev-parse HEAD
python -m unittest discover -s tests

mkdir -p outputs/mvp_v11_b0/refs
git show origin/evidence-observations:runs/historical-selection-v1/historical_selection_v1_20261011_03/ranking_paired_by_date.csv > outputs/mvp_v11_b0/refs/ranking_paired_by_date.csv
git show origin/evidence-observations:runs/historical-selection-v1/historical_selection_v1_20261011_03/action_v1_compactness.csv > outputs/mvp_v11_b0/refs/action_v1_compactness.csv
sha256sum outputs/mvp_v11_b0/refs/*.csv

python scripts/mvp_v11_b0_parity.py \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --expected-dataset-sha256 2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e \
  --archived-ranking outputs/mvp_v11_b0/refs/ranking_paired_by_date.csv \
  --archived-compactness outputs/mvp_v11_b0/refs/action_v1_compactness.csv \
  --output-dir outputs/mvp_v11_b0/b0_run_01
```

**The above default run returns B0_AGGREGATE_ONLY_PARTIAL** if all archived
monthly totals and Top-5/15 lists match. This deliberately is NOT enough
to authorize candidate return experiments: the original _03 archive does not
include the 25k-row `action_v1_decisions.csv`. If the pre-existing original
`outputs/historical_selection_v1_20261011_03/analysis/action_v1_decisions.csv`
still exists, **do not regenerate it using current code**. Record its SHA256
and provenance first, then repeat the B0 command under a new output directory
with both:

```text
--archived-decisions /ABS/PATH/original_action_v1_decisions.csv
--expected-decisions-sha256 <SHA256_OF_THAT_ORIGINAL_FILE>
```

Only then can the tool compare every signal_date×symbol's grade, scores,
confidence, Entry/Action states and (when present) evidence risk codes.
The operator must audit the reference's age/source, not simply pin a newly
generated CSV. Mismatch returns exit code 2 and blocks optimization.

**Review evidence to submit:** `baseline_parity.json`,
`baseline_parity_by_date.csv`, `baseline_parity_mismatches.csv`,
a Markdown explanation of row-level historical reference origin/absence,
input/reference SHA256, exact PR HEAD, test/CI status, 346 missing-fundamental
rows' behaviour, discrepancies, and known audit caveats. Only submit small
browsable derived evidence; never raw 25k CSV, secrets, or large caches.
No paid Modal compute or re-extraction; stop and report any mismatch.

Even full reference parity alone **does not authorize optimization**:
separate PIT/entity/forward-label event audit and frozen candidate approval
remain mandatory. B0 cannot assert historical Daily/Weekly production parity.
