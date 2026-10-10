# MVP handoff after PR #47 review — 2026-10-11

## Read first

Repository: `AT2018cow/us-ai-stock-scanner`.

Before editing, read:

1. `AGENTS.md`
2. `docs/product_direction_low_frequency_manual_selection.md`
3. `docs/mvp_design_low_frequency_manual_selection.md`
4. `docs/work_handoff_after_pr45_20261011.md`
5. `docs/sec_edgartools_live_fallback.md`
6. this document

Always verify the current `main` SHA and the real states of PR #47 and any newer PRs. Do not assume this document authorizes a merge.

## Product direction

The product remains a **low-frequency, human-decision-support stock-selection MVP**:

`Company Quality × Entry Quality -> canonical StockDecision -> Action List -> Detailed Report`.

The MVP is not an automated trading platform. Preserve the same canonical StockDecision for list and report, legacy scanner compatibility, immutable/provenance-aware snapshots, and fail-closed behavior for unsafe fundamental data.

Do not expand by default into broker integration, account NAV, portfolio optimization, historical ETF reconstruction, broad threshold tuning, full IFRS normalization, FX infrastructure, or a generic XBRL engine.

## Verified repository state

PR #45 (`MVP correctness: add narrow EdgarTools USD 10-Q fallback`) is merged.

Merge SHA:

`1f500648b9a00382fdc5b32bbf09330d0fdf5211`

PR #47 is the credentialed experiment evidence for that merge:

`https://github.com/AT2018cow/us-ai-stock-scanner/pull/47`

PR #47 exact head at review:

`f5fe89a2e49ffde205c3b75effaa1c773f6bfbb5`

The evidence PR is evidence-only, ahead of main by one commit, behind by zero, and its exact-head CI passed:

- workflow run `38074152127`
- job `114277491331`
- `Ran 497 tests in 1.629s`
- `OK`

The evidence package is:

`evidence/mvp_edgartools_fallback/2026-10-09_1f50064/`

PR #47 is valid raw evidence and may be retained/merged as evidence after normal user approval. The experiment result itself is **NOT a GO for formal prospective observation yet**.

## PR #47 result

The experiment ran:

`python scripts/run_mvp_full_scan.py`

in experiment mode, not `--formal`.

Decision date: `2026-10-09`.

Validator passed, but fallback usage was:

- `edgartools_10q_used = 0`
- `not_needed = 457`
- `core_facts_incomplete = 45`
- `filing_mismatch = 2`
- `ineligible_form = 6`

The original integrity gap therefore remained:

- `latest_periodic_filing_not_covered = 53`
- `fundamental_currency_unsupported = 17`

EXLS, JCI, PYPL, CDNS, NXPI and NEE all remained `UNRATED` with `latest_periodic_filing_not_covered`.

TTAN remained fail-closed. TSM / ASML / SAP were not incorrectly promoted. The Daily Action List remained the same 15 names as the prior live-correctness experiment. These are useful safety observations, but they do not prove the fallback works.

## Root cause found during review

The zero-use result is a concrete adapter/API contract bug, not evidence that EdgarTools cannot recover the filings.

PR #44 had already shown filing-level core concepts for 51/53 gaps and 46/47 ordinary 10-Q gaps, including standard USD us-gaap Revenue / Net Income / OCF for EXLS, JCI, PYPL, CDNS and NXPI.

PR #45 production code calls:

`filing.xbrl().facts.query().by_dimension(None).to_dataframe()`

with EdgarTools pinned at `5.61.1`.

The exact EdgarTools 5.61.1 XBRL FactQuery DataFrame schema includes:

- `concept`
- `value`
- `numeric_value`
- `period_start`
- `period_end`
- `period_instant`
- `unit_ref`
- `currency`
- other context fields

It does **not** expose a `unit` column on this FactQuery DataFrame path.

However `src/ai_value_scanner/fundamentals/edgartools_fallback.py` currently uses `row.get("unit")` in both:

- core-currency detection; and
- conversion to the Company Facts-compatible patch.

Therefore real filing rows have no detected currency on this path. Ordinary USD 10-Qs are incorrectly classified as `core_facts_incomplete` before a patch can be constructed.

The unit tests missed this because the fake FactQuery fixtures use a synthetic `unit` field, matching the adapter's incorrect assumption rather than EdgarTools 5.61.1's real FactQuery schema.

This is the immediate correctness blocker.

### Filing mismatch cases

BE and TTAN appear as `filing_mismatch` because SEC submissions are normalized to latest periodic `10-Q`, while EdgarTools reports their exact filing form as `10-Q/A`.

This is not the primary blocker and should not trigger scope expansion. Keeping amended filings fail-closed is acceptable for the narrow MVP unless a tiny, explicit normalization rule is separately justified.

## Short-term goal: one corrective PR only

Create one small correctness PR. Do not redesign the fallback.

Required fix:

1. Adapt the EdgarTools FactQuery row conversion to its real 5.61.1 schema.
2. For monetary core facts, prefer the resolved `currency` field.
3. Use `unit_ref` only as provenance / a carefully-tested fallback where needed; do not infer USD from arbitrary substring matches.
4. Preserve current `by_dimension(None)` consolidated/undimensioned filtering.
5. Preserve exact accession, form, filed date, period start/end/instant, numeric value and taxonomy checks.
6. Preserve the existing TTM freshness gate: a successful fact conversion alone must not clear the blocker.
7. Preserve rollback when latest Revenue / Net Income / OCF rolling TTM cannot all be driven by the latest accession.
8. Keep 20-F, 40-F, IFRS, non-USD, mixed currency, custom-only facts and unsupported amended filings fail-closed.
9. Do not alter Quality / Entry thresholds or Action mapping.
10. Do not broaden the two live-only revenue aliases based on this experiment.

### Required tests

Replace/add fixtures that mirror the **real EdgarTools 5.61.1 FactQuery DataFrame schema**:

- use `currency="USD"` and realistic `unit_ref`, not a fake `unit="USD"`;
- verify EXLS-like standard USD rows create a patch;
- verify segment/dimension rows remain excluded;
- verify EUR/CAD/TWD core rows are rejected;
- verify missing/ambiguous currency fails closed;
- verify exact period fields feed the existing quarter/YTD/TTM reconstruction;
- verify latest-accession TTM gate and rollback;
- keep the existing normal Company Facts path unchanged;
- test `10-Q/A` behavior explicitly so it is intentional rather than accidental.

Run Python 3.12, `pip install -e .`, and `python -m unittest discover -s tests`. Exact PR head CI must be green.

## External experiment after the corrective PR

The corrective PR must include a full **Review evidence to submit** section before asking the user to run anything.

Run only:

`python scripts/run_mvp_full_scan.py`

Do **not** use `--formal` yet.

Submit a new immutable evidence PR under a new path such as:

`evidence/mvp_edgartools_fallback_fix/<decision_date>_<actual_code_sha7>/`

Include the same canonical artifacts as PR #47 plus `fallback_cases.md`.

The review must specifically verify:

1. fallback is actually used on at least the ordinary USD 10-Q cases that can satisfy existing TTM reconstruction;
2. EXLS / JCI / PYPL / CDNS / NXPI use the latest accession only when latest Revenue / Net Income / OCF TTM is genuinely reconstructed;
3. NEE and utility revenue aliases remain accounting-consistent;
4. TTAN and unsupported/incomplete cases fail closed;
5. TSM / ASML / SAP remain non-USD/foreign unsupported and cannot be promoted by incidental USD facts;
6. ordinary Company Facts controls and Action List renderers do not regress;
7. validator passes and fallback provenance is deterministic;
8. fallback/network use remains bounded.

Do not submit `.env`, SEC identity/email, keys, raw SEC/EdgarTools caches, raw filing XBRL, Alpaca raw caches, virtualenv, or unrelated bulk outputs.

## GO / NO-GO rule after rerun

If the schema correction produces correct latest-accession accounting on the expected ordinary USD 10-Q cases, unsupported cases remain fail-closed, controls stay stable, and validator/CI are green:

**GO** — stop SEC expansion and run the first `python scripts/run_mvp_full_scan.py --formal` immutable prospective snapshot.

If there is another narrow adapter bug that directly prevents the already-proven ordinary USD 10-Q data from entering existing accounting safely, fix only that concrete correctness defect.

Do not start a third broad SEC research cycle. If remaining cases require IFRS, FX, custom taxonomy or major XBRL infrastructure, accept `UNRATED` and move on.

## Medium-term goal: 4–12 weeks

After GO, development priority shifts from feature building to actual MVP use:

- create immutable prospective snapshots at the intended low-frequency cadence;
- use Daily Action List for changes and Weekly Review as the main human research workbench;
- record whether 5–15 names actually reduce research workload;
- observe state persistence, upgrades/downgrades, stale/missing evidence and review triggers;
- monitor whether attention cap hides meaningful candidates;
- attach 20/60/120d outcomes later as diagnostics without retroactively changing old decisions;
- avoid threshold tuning from a small number of early prospective samples.

## Long-term goal: 3–12 months

Use accumulated frozen prospective decisions to decide whether Quality/Entry v2 is justified.

Only evidence-triggered future work should be considered:

- versioned Quality/Entry policy improvements;
- reporting/audit UX improvements;
- selective additional data coverage if it materially changes candidate usefulness;
- optional portfolio/broker tooling only if real manual use demonstrates a concrete need.

Do not turn the repository into a generic financial-data platform or automated trading system by default.

## New-conversation first action

The new conversation should not re-review the whole project from scratch.

It should:

1. read the documents listed at the top;
2. inspect PR #47 and confirm the zero-use evidence;
3. inspect EdgarTools 5.61.1 FactQuery schema and PR #45 adapter;
4. implement the single schema-correction PR described above;
5. get exact-head CI green;
6. provide external experiment instructions;
7. review the new evidence and make the formal prospective GO / NO-GO decision.
