# Handoff — narrow EdgarTools 10-Q/USD fallback (2026-10-11)

## Read first
Repository: https://github.com/AT2018cow/us-ai-stock-scanner
Required: `AGENTS.md`, `README.md`, `docs/product_direction_low_frequency_manual_selection.md`, `docs/mvp_design_low_frequency_manual_selection.md`, `docs/work_handoff_after_pr31_20261010.md`, and `docs/sec_edgartools_parity_spike.md`. Verify actual main SHA, PR states and current tests before editing. This handoff is a plan, not authorization to merge.

## Product destination (medium/long term)
The MVP is **low-frequency manual stock-selection decision support**, not automated trading: Company Quality × Entry Quality → canonical StockDecision → capped Action List and Detailed Report. Preserve legacy scanner/list compatibility. Action List and report must render the SAME immutable StockDecision; never independently derive actions. Keep confidence/data provenance explicit, fail closed for unsafe SEC facts. Avoid historical-return threshold tuning, broad Entry research, portfolio NAV, broker integration, ETF holdings reconstruction and broad SEC/FX infrastructure. Do not use Modal --detach. One implementation PR per bounded step, exact-head CI green, no merge without explicit user instruction.

After SEC correctness is demonstrated by one credentialed experiment, STOP expanding SEC scope and begin prospective observation (`--formal`) under the MVP acceptance process. Track usability, provenance, attention-cap behavior and prospective outcomes; no retroactive tuning from a single experiment.

## Verified state at handoff
PR #43 EdgarTools diagnostic spike is merged into main at `b0a151050fab2af14f13c9b7996b1f1cad708e74`. EdgarTools `5.61.1` is optional via `pip install -e '.[sec-diagnostic]'`, not a production scanner dependency. PR #44 evidence (https://github.com/AT2018cow/us-ai-stock-scanner/pull/44) was reviewed and **recommended for merge, but was OPEN and not merged at handoff**. Its exact head `57236b1351c22de212b915cf05de15e221625dbc` had green CI (486 tests), evidence-only 7 files, no obvious secrets. Do not assume it has merged; recheck. Evidence location on PR #44 branch: `evidence/sec_edgartools_parity/2026-10-09_b0a1510/`.

PR #44 diagnostic of PR #41 experiment snapshot (decision_date 2026-10-09, scanner code `06c08cb3d7db76baee4389a93eee11958a6732dc`) found core financial concepts in 51/53 flagged filing gaps; ordinary 10-Q 46/47, 20-F 3/4, 40-F 2/2; zero fetch/XBRL failures. Of 47 ordinary 10-Q gaps, 46 have all three core categories and 44 have no custom core taxonomy. EXLS, JCI, PYPL, CDNS, NXPI and NEE have standard us-gaap USD Revenue/Net Income/OCF in their exact latest 10-Q. TTAN and NBIS have no core concepts. This demonstrates **filing-level existence**, NOT valid value/period/TTM reconstruction or parity with existing accounting.

Critical evidence caveat: diagnostic classification `CURRENT_PATH_NON_USD_EDGARTOOLS_USD_SEEN` means **any** USD unit anywhere in filing, not USD core monetary facts. ASML core facts are EUR; TSM TWD; SAP EUR; many Canadian names CAD. Current scanner provenance can misleadingly say USD for TSM/SAP because historic Company Facts contains USD facts. Do NOT clear currency blockers or compare non-USD monetary values to USD market cap.

## Immediate next PR: narrow production fallback
Create a NEW implementation PR, separate from this handoff PR, only after reading code/tests. Trigger ONLY when latest periodic filing is uncovered by Company Facts AND form is ordinary 10-Q AND exact accession is known. Fetch that exact filing with EdgarTools. Initially accept only standardized USD core financials (not custom taxonomy), with explicit context/period and consistent currency checks. Preserve old Company Facts path unchanged when it already covers latest filing. Do not make EdgarTools a second Quality engine.

Normalize source facts into existing PIT/accounting reconstruction pipeline (or introduce the smallest justified shared adapter). Each accepted fact needs: concept, normalized meaning, numeric value, unit, period_start/end, filed date, accession, form, taxonomy, and enough context to reject segmented/dimensional facts. **Do not merely set `fundamental_facts_cover_latest_periodic=True` when EdgarTools says core_found**; that would silently retain stale Quality metrics. Verify current/previous quarter, YTD vs quarterly, TTM, balance-sheet points and unit scaling against existing accounting semantics. If complete trustworthy metrics cannot be reconstructed, keep `UNRATED` with reason; do not synthesize values or relax Quality thresholds. Maintain deterministic cache/invalidation and provenance identifying fallback source and exact filing. Preserve all scanner exports/snapshots and canonical decision contract.

For currency correctness, use latest filing's **core statement fact units**, not any historical/filing-wide USD sighting. Non-USD, mixed, ambiguous or unsupported units fail closed. Avoid FX, broad IFRS/20-F/40-F support, custom taxonomy and unrelated data repairs. Specific edge cases: BE/PLD custom, TTAN no core, TSM/SAP/ASML foreign currency remain unsupported.

## Testing and external experiment contract
Use Python 3.12, `pip install -e .`, `python -m unittest discover -s tests`; test optional dependency installation separately where feasible. Add offline fixtures/unit tests for exact-accession selection, latest-filed PIT eligibility, standardized USD contexts, dimensional exclusion, Q/YTD/TTM reconstruction, stale-cache behavior, failure handling, non-USD rejection, and no regression in normal path. Explicit parity controls: TEL, APH, MSFT (subject to real availability); recovery cases: EXLS, JCI, PYPL, CDNS, NXPI, NEE; negative: TTAN, TSM, SAP, ASML. Do not claim parity from presence-only evidence.

**Every PR needing credentialed external execution MUST include a `Review evidence to submit` section** (also required by AGENTS.md): exact checkout/installation/configuration commands (including EDGAR_IDENTITY or SEC_USER_AGENT, redaction), experiment mode (not formal), expected source/output paths, immutable evidence directory named with ACTUAL checkout code SHA, manifest, validation, decisions/action/report artifacts, per-symbol before/after values/periods/provenance, failures/warnings, sensitive files to exclude (.env, keys, identity/email, raw SEC/EdgarTools caches, raw XBRL, virtualenv), and concrete acceptance questions. Do not claim an external run was performed without access to credentialed environment. User will submit a separate evidence PR for review.

## Acceptance gates
1. Existing normal Company Facts symbols unchanged; legacy output compatibility and same canonical StockDecision for list/report.
2. Latest ordinary 10-Q USD gap symbols get genuinely new and correct normalized accounting values, not just a flipped coverage flag.
3. Correct filing/period/freshness and deterministic provenance; fail closed for missing/inconsistent/ambiguous inputs.
4. No unsafe USD inference for TSM/SAP/ASML; no regression for TTAN/other unsupported.
5. Exact-head CI green and credentialed evidence PR reviewed before deciding whether to proceed to `--formal`.

## Execution sequence in new conversation
First inspect AGENTS/readme/design/handoff/code, recheck PR #44 status. If user separately authorizes merging #44, verify exact-head CI and merge; otherwise do not merge. Implement the bounded fallback PR with tests, run exact-head CI, include external evidence instructions. Ask user to run credentialed experiment and submit evidence PR. Review it for accounting parity and action stability; fix only narrow correctness regressions if needed. Once verified, move to prospective formal observation, not another broad SEC research cycle.
