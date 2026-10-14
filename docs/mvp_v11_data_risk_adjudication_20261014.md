# PR-A — Data-risk adjudication and candidate pre-registration (2026-10-14)

**Review decision:** `A0 STRUCTURAL PASS`; `B0 historical proxy parity PASS`;
`DATA_RISK_REVIEW_REQUIRED`. This is a **review decision and frozen protocol
proposal**, not confirmation that the 52 corporate-action flags are all
real/false, not a PIT certification, and **not authorization to run R/E return
experiments**. `ready_for_candidate_returns=false` stays in effect.

Input evidence commit: `81a0809c9c1f3ca763bc2d538ca968cca8e47c8e`.
Input dataset SHA256:
`2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`.
Audit events SHA256:
`20dc8670c8de44781355c51d6381821b6cc64b00bab9162445af628cac3f9e31`.
Frozen monthly ranking reference SHA256:
`4b0d25e0ad54c394a5eeed2ed47a2c4f0ba01fae29cc8d793f573980a2d88d51`.
Original locally preserved row-reference SHA256:
`b5ce1166c38a4094158bd7ca6dd8844b5d210c2aa2a010a7aa38bdc2bac2abbc`
(original historical archive did not independently register this SHA).

## 1. Reviewer handling of 52 events

- `WOLF` 2025-09-30 `REORG_JUMP_BACKDATED`: **KEEP existing 7
  nulled forward labels (2×60d, 5×120d)**. Do not zero-fill, backfill,
  reattach another security's price series, or relabel with later knowledge.
  The separate WOLF November 2025 shares cliff remains unresolved.
- All other **51 audit-only** records: **DO NOT bulk-delete or assert corrected
  labels**. Keep each `human_disposition=UNREVIEWED` until source evidence
  supports a dated conclusion; the automatic queue is a triage queue, not
  51 independent human verifications. Group into provisional
  `SCORE_INPUT_SCOPE_REVIEW` (share-count/source/units/classes),
  `PRICE_IDENTITY_LABEL_REVIEW` (returns, corporate actions or listings), or
  `BOTH/UNCERTAIN` for investigation. They retain their full original rows.
- `HEI`: treat recurring 55m↔138–139m counts as
  `SHARE_CLASS_SCOPE_MISMATCH_SUSPECTED`, **not** proven split nor merely
  extreme share dilution. The issuer has two listed equity classes.
  SEC fiscal 2025 10-K shows 55,142,805 Common and 84,213,758
  Class A outstanding as of 2025-12-19; summed 139,356,563.
  SEC fiscal 2024 10-K reports 54,986,227 Common and 83,843,858
  Class A as of 2024-12-18.
  Sources:
  - https://www.sec.gov/Archives/edgar/data/46619/000004661925000082/hei-20251031.htm
  - https://www.sec.gov/Archives/edgar/data/46619/000004661924000111/hei-20241031.htm

  **Unverified:** frozen extraction accession, filing acceptance/public times,
  date-specific source facts, HEI vs HEI.A price pairing, denominator used for
  `market_cap` / `fcf_yield` / `ps/pe`, and what was publicly knowable
  for earlier dates. The observed count alternation is compatible with
  `Common-only` versus `Common + Class A` data-source switching.
  Never compute issuer market capitalization as (two-class share sum × HEI
  *single-class* price) without verifying class prices and proper share basis.
- Severe share anomalies (HXL, PKG, SKY, TBLA, SW, LAES, UNIT, etc.) are
  **source/units/identity suspects**, not proven split-adjustment errors.
  Even if the forward price is continuous, a bad denominator may have
  contaminated **Quality and ranking**.
- Large price moves (CORZ, LAES, QUBT, UMAC) are **label-continuity
  suspects**, not proof of false returns. Real winners and valid post-listing
  rallies must not be discarded solely because they are large.

A 2025-12-31 HEI event is the only *event-date* historical Top-5/15 exposure
in the queue; there are three additional *previous-date* Top-15 exposures.
This metric is **NOT** a full exposure analysis: events can affect scores on
later dates and forward returns of earlier Top-k selections.

## 2. Two independent uncertainty axes and frozen comparison conventions

**Score and PIT trust (information potentially knowable at signal time)**

- Never recompute ranks from later annual filings, reconstructed future
  share counts, future event queues, or after-the-fact SEC restatements.
- Preserve `B0` and all R/E candidates' identical 25,025-row historical
  cross-section. Missing `fundamental_data_asof` remains fail-closed
  (`UNRATED/AVOID`). These 346 records cannot be upgraded by imputation.
- Mark a score-input suspicious *signal_date×symbol* when source evidence
  or contemporaneous observation shows shares/source/currency/class/CIK
  uncertainty. Prioritize HEI and extreme scale switches. Do **not**
  retroactively disqualify prior dates from a future anomaly.
- Unless a dated, source-backed, outcome-blind repair is accepted *before*
  result inspection, leave canonical scoring **untouched**. Historical B0
  parity does not certify the original input is economically right.
  Report flagged selected names and inspect whether any apparent improvement
  comes from such rows. **Do not promote a winner dependent on unresolved
  score-input issues**.

**Forward label continuity (future interval: retrospective evaluation only)**

- Retain existing v3 WOLF nulls.
- A separate fixed *sensitivity view* must flag any selected
  `signal_date×symbol×horizon` whose holding interval could overlap an
  unresolved audited event interval `(prev_date, event_date]`.
  Use `signal_date < event_date AND label_end_h > prev_date`; this is a
  conservative interval-intersection flag, **NOT an ex-ante stock filter**.
  This may overflag true rallies; that is intentional as a diagnostic.
  Never use an event identified after the signal date to decide the
  historical Top-15 membership.
- The **primary descriptive comparison** retains the existing valid
  20/60/120 net forward labels, with no new deletion based on returns.
  For **each horizon × date**, compare B0 and each candidate only when
  both Top-15 groups have all 15 paired (stock, QQQ) labels; otherwise
  mark the entire date/horizon as missing for **both** groups. Same for
  Top-5 with 5 paired labels. Never fill label gaps with 0, substitute
  another stock, or report conditional-on-movers as the primary result.
- The **pre-declared interval-exposure sensitivity** omits the
  *entire same date/horizon pair* if **either** selected Top-k group contains
  a flagged label/event overlap. Report how many dates are lost, by
  candidate and horizon. Inadequate remaining dates => `INCONCLUSIVE`;
  do not relax the mask after looking at outcomes.
- A second **score-quality sensitivity** may omit entire date pairs if
  either Top-k selected list contains a flagged unresolved *as-of* score
  observation. Record prevalence and diagnostic results; it cannot be
  post-hoc tuned.
- Never assume a 51-event unverified list fully captures label errors.
  Even a large positive result with unresolved identity/PIT exposure must
  remain `INCONCLUSIVE` for promotion.

**Cost / split / universe conventions**: v3 `fwd_ret_h` and
`qqq_return_h` each already include `30 bps` assumed roundtrip cost.
No second deduction. Label `gross-proxy` only when reliably reconstructible;
do not describe the historical Top-15 as an executed NAV. Universe remains
`retrospective / union_superset_approx`.

## 3. PIT / entity evidence required before return-gate reconsideration

Run **targeted read-only** verification in the local pre-existing SEC cache,
historic extraction manifests/logs and public filing headers for:
- HEI 2023-12-29 / 2024-12-31 / 2025-08-29 / 2025-12-31 and nearby
  date-specific fiscal filings, BOTH traded share classes, share units,
  acceptance times, and valuation denominators;
- original high-severity score-source cases: HXL, PKG, SKY, TBLA, SW,
  LAES, UNIT; cover 2023–2024 development dates first;
- suspicious price identities/reorganizations: CORZ, LAES, QUBT, UMAC,
  WOLF (including successor and delisting labels);
- a **pre-declared** set of other historical Top-15 names and risk codes
  (for example at fixed dates 2023-01-31, 2024-01-31, 2024-12-31),
  to verify the data path is not special-cased to known anomalies.

For each checked `signal_date×symbol`, record: ticker, CIK if evidenced,
security class, issuer/operating entity, currency/unit, SEC accession,
filed/accepted time **and whether available before market decision close**,
source facts, original per-date metrics, any restatement flag, and a
source permalink/hash. Missing => `UNVERIFIED` (not assumed safe).
Review evidence requires valid provenance; do not request new large SEC
downloads or change source CSV. This is a bounded audit, not a full
historical CIK rebuild.

## 4. Candidate matrix disposition — **PARAMETER DEFINITIONS FROZEN**

Approve **the fixed meanings and values only** of
`configs/mvp_v11_candidate_registry.json` as of commit
`81a0809c9c1f3ca763bc2d538ca968cca8e47c8e` (same
registry content as before) for:
`B0`, `R1`–`R5`, `E1`–`E4` (10 primary slots) and conditional
`X1` (11th only if both one R and one E meet 2023–24 dev gates).
**Approval does not change code or default policy, does not approve X1
ahead of time, and explicitly does not authorize comparing candidate
forward returns yet.** No changes to weights/risk codes/Entry thresholds
after results; new candidate IDs require separate pre-outcome approval.
2025 and 2026Q1 cannot be viewed as comparison diagnostics until the
2023–24 winner (or no-winner) is fixed. Primary metric remains 60d
date-equal-weight Top-15 excess improvement versus B0, reference +0.5pp
on 2023–24, with worst dates and concentration checks.

To unlock candidate return computation, require (1) auditable dated PIT and
class/identity evidence at material exposure cases or explicit
`UNVERIFIED` with a conservative comparison strategy, (2) frozen
implementable event/score masks and tests with no return leakage,
(3) reviewed candidate comparator and Entry migration/evidence tests,
(4) exact-head CI PASS, and (5) an explicit go-ahead from the project owner.
Until then `ready_for_candidate_returns=false`.

## 5. Evidence and operational boundary

The existing A0/B0/risk evidence lives on PR-A's code branch; this is not
the final append-only `evidence-observations` archive required for
experimental artifacts. Reconcile storage before final PR-A merge,
pin evidence commits, and avoid extra evidence-only PRs.

No changes to `main`, current production v1, historical v3 CSV bytes,
old formal snapshots, or the original 52-record audit file.


## 6. HEI follow-up ruling after EdgarTools audit

Evidence: PR-A commit 9890d668a66c19f2673cd53e1c77732cede43afc, evidence/mvp-v11-secpit-20261014. Four SEC 10-K/Q filing acceptance timestamps precede the corresponding signals, but the original scorer's accession/CIK binding remains UNVERIFIED. XBRL facts confirm incompatible share basis: frozen HEI 137,185,000 (2023-12-29), 138,455,000 (2024-12-31), and 139,048,000 (2025-12-31) are *annual weighted-average basic EPS denominators* for both classes; 55,054,000 (2025-08-29) is *Common-only period-end outstanding shares*. These are neither the same share-class scope nor the same instant/period basis.

The frozen market_cap multiplication uses a single HEI Common price with those inconsistent denominators; therefore historical valuation and shares_yoy source semantics are not trustworthy. The original report's 2.51–2.52x comparison is **relative to HEI Common-only capitalization, not issuer-wide true market capitalization**. The 9.80B/13.08B/17.84B comparators cannot be called true total issuer cap; the HEI.A class has a separate share price and economic value. The exact impact on issuer-wide cap has NOT been established.

Review classification: SHARE_SCOPE_INCONSISTENCY_CONFIRMED, as **sidecar research audit metadata**, not a historical CSV repair or v1 scoring change. Freeze an outcome-blind retrospective score-quality sensitivity marking all HEI date-by-symbol observations as source-scope uncertain, but distinguish the four directly corroborated dates from remaining unverified dates. Such retrospective flags must never change original candidate membership. In paired sensitivity, omit only the entire date pair when either selected Top-k contains a flagged HEI record, with explicit coverage loss. Do not generalize from HEI to all dual-class tickers without evidence.

Defer numerical correction until original frozen historical CIK/accession identity, both class-specific as-of share counts, both HEI and HEI.A contemporaneous price legs and a documented valuation definition are supported; keep original B0 unchanged and compare proposed corrections separately. The nine already frozen Top-15 controls are approved for one bounded SEC verification, using original SHA ed20b66a5e97df4d6537b6c05ff27a6d37aa20c1ea257d813c74cf2b9d7fc6be and the exact case-type filter in the SEC/PIT runbook. Original 52-event queue remains unchanged. No return comparison is authorized without mask/comparator review and owner approval.
