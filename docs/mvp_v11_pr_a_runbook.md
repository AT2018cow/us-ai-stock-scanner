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

## B0 review accepted; next gate: data-risk triage (2026-10-14)

Review accepted `B0_FULL_REFERENCE_PARITY_PASS` at `5139412`: 39 dates,
25,025 rows, archived monthly Top-5/15 and row-level Quality/Entry/Action
parity, 0 mismatches, 346/346 missing-fundamental-asof rows UNRATED/AVOID.
The 56.9 MB row reference `action_v1_decisions.csv` is locally preserved
and internally corroborated by five archived SHA-matching sibling outputs,
but was **not itself independently listed in archived SHA256SUMS**. This
is high-confidence operational parity, not proof of source PIT correctness.
The five canonical Action states have five counts; an earlier B0 report
mistakenly called them "six action counts".

The following preflight is **only** a read-only risk-triage pass. It
does not authorize viewing R/E candidate returns or changing masks.
Read every one of the 51 audit-only events and preserve real winners,
especially cases with abnormal share-count/valuation denominators. Do not
unilaterally drop problematic rows, fill values, or change policies.

```bash
git fetch origin
# Confirm checkout is the latest PR-A head and its own CI is green.
git rev-parse HEAD
python -m unittest discover -s tests

python scripts/mvp_v11_data_risk_audit.py \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --expected-dataset-sha256 2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e \
  --events outputs/historical_selection_v1_20261011_03/repaired/entry_quality_discontinuities.csv \
  --expected-events-sha256 20dc8670c8de44781355c51d6381821b6cc64b00bab9162445af628cac3f9e31 \
  --archived-ranking outputs/mvp_v11_b0/refs/ranking_paired_by_date.csv \
  --expected-ranking-sha256 4b0d25e0ad54c394a5eeed2ed47a2c4f0ba01fae29cc8d793f573980a2d88d51 \
  --output-dir outputs/mvp_v11_risk/risk_run_01
```

**Exact expected files**: `data_risk_review_summary.json`,
`event_review_queue.csv`. The tool leaves the 52 event dispositions
`UNREVIEWED`; it does not access SEC/Alpaca or compute future return
comparisons. Keep CSV as a working review checklist and **do not**
treat its exposure flags as a return-selection algorithm.

Before any parameter experiment, review/provide a small Markdown note covering:

- Evidence for public filing **availability time**, not merely filing
  period end or data-as-of. Mark ambiguous pre-open/after-close timings
  `UNVERIFIED`; do not claim PIT pass from date fields alone.
- SEC CIK/operating entity, share classes, currency and restatement
  continuity on risk-relevant dates, especially the historical Top-15.
- Each of 51 audit-only event records' economic identity, shares-source
  anomalies and price/label implications. List known-supported cases and
  unresolved cases separately; no retrospective removing real winners.
- The proposed **outcome-blind** data-quality flags / exclusion or
  uncertainty masks for sensitivity, without changing source v3 bytes.
- Corroborating sources/identifiers, dates and limitations for reviewer
  validation. No secrets, large licensed inputs or private credentials.

Return compact summary and review queue with pinned SHA and CI result;
do not upload bulk original datasets. If independent filing/event proof is
unavailable, mark it unresolved and STOP before outcome comparisons.

Human approval to freeze the pre-registered B0/R1–R5/E1–E4 registry
and any mask protocol remains required after these findings are reviewed.
The standalone 2025 / 2026Q1 temporal diagnostics stay embargoed until
the development winner is locked on 2023–2024.

## Reviewer disposition: data risk + frozen candidates (2026-10-14)

Read `docs/mvp_v11_data_risk_adjudication_20261014.md` before any
new output. Reviewer accepts A0 structural and B0 historical parity;
risk triage inventory is valid, **but economic input/PIT correctness remains
unverified**. SEC 2024/2025 HEI 10-K reports two common share classes.
55m vs 138–139m historical shifts may be class-scope mix, not a split.
Never silently repair HEI with new SEC filings or multiply the sum of
two share classes by the single HEI price.

**Freeze the candidate parameter definitions** as already registered:
B0, R1–R5, E1–E4, and conditionally X1. This is not permission to
analyze their returns. For now: `ready_for_candidate_returns=false`.
No default v1 production changes.

### Next operator task: bounded PIT/identity investigation

Use original research outputs, source manifests, already cached SEC headers
and public EDGAR documents when necessary. Do not bulk-fetch SEC/Alpaca data.
Identify as-of-public information and share-class denominator for HEI at
2023-12-29, 2024-12-31, 2025-08-29, 2025-12-31; source provenance of HXL,
PKG, SKY, TBLA, SW, LAES, UNIT as relevant to 2023–2024; and review
possible price/issuer discontinuity at CORZ, LAES, QUBT, UMAC, WOLF.
For each, record `signal_date, symbol, accession, accepted_utc,
available_by_signal_close, CIK, security_class, share_units,
shares_source_metric, currency, verification_status, source_url/hash`.
Missing or ambiguous fields must stay `UNVERIFIED`. Include a deterministic
comparison sample of 2023-01-31, 2024-01-31, and 2024-12-31 B0 Top-15
issuers to avoid investigating only known suspicious tickers.
Record that 2025/2026Q1 review is only historical data integrity; do not
compute/review candidate performance there.

### Event-interval preflight (no returns)

Once exact-head CI for the **new audit-only code** is green, run:

```bash
python -m unittest discover -s tests
python scripts/mvp_v11_event_exposure_preflight.py \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --expected-dataset-sha256 2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e \
  --events outputs/historical_selection_v1_20261011_03/repaired/entry_quality_discontinuities.csv \
  --expected-events-sha256 20dc8670c8de44781355c51d6381821b6cc64b00bab9162445af628cac3f9e31 \
  --output-dir outputs/mvp_v11_risk/interval_run_01
```

This preflight reads only `signal_date`, `symbol`, and frozen
`label_end_20/60/120` fields from v3, **not returns**. It outputs
`event_interval_exposure_summary.json` (safe to submit after source
redaction) and `event_interval_exposure_local_only.csv` (75k
signal×symbol×horizon records; keep ignored in outputs). An event record
only locates a monthly *detection interval*, not the exact SEC public or
corporate action timestamp; the overlap flag is a conservative,
retrospective diagnostic **not historical selection membership**.

Deliver the small summary, the exact run SHA/CI, and a source-evidence
audit note (verified vs unresolved; no keys or raw SEC caches).
Do NOT commit original v3 dataset or local full flags CSV to the PR.
Do not edit original `event_review_queue.csv` or claim its 52
`UNREVIEWED` dispositions are settled. The owner/reviewer must examine
the source-evidence audit and confirm the outcome-blind paired-mask
rules before return comparisons start.


## PR-A next implementation: R/E membership-only preflight (not returns)

Code now has:
- `decision/entry.py` canonical shared threshold routine: the public
  `build_entry_quality_v1` retains -3% RS and >15% overextension and
  unchanged v1 evidence texts. A **separate offline-only**
  `build_entry_quality_v11_offline` accepts only frozen E1–E4 thresholds.
  Entry score and confidence, defensive gate, trend/damage and READY 20d
  12% cap stay unchanged.
- `research/mvp_v11_candidates.py`: creates B0 from the existing
  canonical builder, R1–R5 only rearrange within Action/Grade, E1–E4
  re-run Entry on identical historical rows, recompute Action, rationale,
  trigger and priorities; outcomes stripped before scoring.
- `research/mvp_v11_score_masks.py`: SIDE-CAR ONLY risk flags for HEI
  all dates, missing fundamental-asof and severe flagged *event dates*.
  This does not modify selection. A retrospective HEI score-quality
  sensitivity is NOT proof that all HEI history is wrong.
- `research/mvp_v11_comparison.py`: pure paired Top-5/15 20/60/120d
  date-level comparator with both arms complete, no fill, same-universe
  checks and separate score/label-event sensitivity flags. No production
  or report CLI calls it yet. **Only synthetic unit tests** may view return
  deltas until a separate experiment authorization and protocol lock.
- `scripts/mvp_v11_candidate_preflight.py`: SAFE to run after latest
  exact-head CI GREEN; computes NO candidate returns, no SEC/Alpaca/Modal.

On your local OpenCode checkout of the PR-A HEAD, keep the originally
SHA-validated corrected v3 and the original risk_run_01 event queue.
Do not reset or delete uncommitted work. Run:

~~~bash
git rev-parse HEAD
python -m unittest discover -s tests
python scripts/mvp_v11_candidate_preflight.py \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --event-review outputs/mvp_v11_risk/risk_run_01/event_review_queue.csv \
  --output-dir outputs/mvp_v11_preflight/membership_run_01
~~~

The frozen input SHA is
`2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`;
the original risk event queue SHA is
`3bf0844fce0e2df40e81eea69eb2445c24a6abeaff7922473ca315b88143204e`.
Use local original data and verified metadata path, never modify or
rename original evidence to satisfy commands. The CLI validates both
hashes and the unchanged eleven-slot registry. New runs refuse an
existing output directory.

**Expected outputs**:
- `membership_by_date.csv` — 24 development dates × 10 executed candidates
  (B0 + R1–R5 + E1–E4), 240 rows: Top-5/15 before/after,
  swaps, migration counts and suppressed PR counts. X1 is *not*
  executed at this stage.
- `entry_migrations_by_date.csv` — E state migrations with counts.
- `score_source_flags_local_only.csv` — 25,025 risk flag records across the input;
  keep ignored locally; do not commit the 25k-row sidecar.
- `preflight_manifest.json` — code SHA, data SHA, registry SHA, source
  event queue SHA, output SHA, and `ready_for_candidate_returns=false`.

Return for review **only** preflight_manifest.json plus a small Markdown
summary: exact HEAD, CI/unittest, 240 development membership rows, Top-15 member
swaps, R changes limited to same Action/Grade, E1–E4 state migrations,
HEI/major share-event flags and missing-asof handling. Optional compact
membership_by_date.csv may be submitted if size/license permits.
Never upload raw licensed bars, corrected 25k-row v3 or full score flags.
Do not call the pure comparator on real forward returns yet.

**Temporal embargo:** candidate membership comparisons currently run on
only the 24 dates in 2023–2024. The 2025 and 2026 Q1 candidate
migrations/Top-k comparisons remain sealed until the development winner
is locked; only outcome-blind score-source data-quality flags may still
cover the complete original 25,025-row dataset.

**Merge condition:** this code submission is an intermediate **draft**
inside PR-A, not a complete PR-A historical GO/NO-GO. Full comparator
integration, vetted PIT/CIK control results, frozen mask coverage and a
single pre-approved 2023–2024 development run are still required.
Do not merge PR #70 solely because the membership preflight and CI
pass. No PR-B until a reviewed candidate is formally selected.
