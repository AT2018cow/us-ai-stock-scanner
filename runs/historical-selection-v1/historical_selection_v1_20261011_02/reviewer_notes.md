# Reviewer notes — human audit trail, RUN_ID historical_selection_v1_20261011_02

## What I (execution agent) actually verified vs did not

- Verified: exit codes (0/0), `_SUCCESS.json` spec match, CSV/meta SHA256,
  39/39 dates, 670 symbols, 100% label maturity, kind/pre-strategy flags,
  frozen-input hashes, exact-head CI, evaluator exit-0 runs, reconstruction
  self-checks (UNVERIFIED=0, parity mismatches=0), no production-code edits.
- Did NOT independently re-verify all 25,025 rows cell-by-cell; the
  per-row files (`quality_coverage.csv`, reason cases, ranking pairs) are
  provided for the reviewer's own spot checks.
- Failure cases are rule-selected (R1–R4/F1–F3 frozen in script headers),
  both tails kept. They are illustrative, not a random audit sample.

## Judgments I am NOT making

- No claim that C "beats" A/B as quality (composition + approximate
  universe explain it; SIC-level verification absent —
  `business_model_verified=False` on all coverage rows).
- No claim that E-first/B+READY rejections generalize beyond this
  retrospective AI-legacy universe (they don't authorize complacency
  either — the cap question stays open).
- No OOS/persistence claims: 2025/2026Q1 are temporal diagnostics only.

## Execution history worth knowing (workspace correction)

1. First launch attempt used `MODAL_PROFILE=at2018cow` per user cost
   instruction → blocked by the then-current infi guard (fast fail, zero
   cost, zero writes).
2. Guard + protocol updated to at2018cow (commit `73a6fe6`, CI green),
   per standing user directive that all project experiments use at2018cow.
3. A user-aborted infi `_01` run left an EMPTY datasets dir (no SUCCESS);
   record in `data_inventory.csv`; never reuse.
4. During Entry approval the user message said `MODAL_PROFILE=infi`;
   executed as at2018cow (the approved code SHA rejects infi; flagged to
   user before launching). Standing at2018cow rule reconfirmed.

## Suggested reviewer spot checks

- Recompute one month's v1 top-15 from `action_v1_decisions.csv` with the
  key in `analysis_code_manifest.md`.
- Verify 2–3 `UNVERIFIED`-free breakout rows against policy §6 gates.
- Check `quality_grade_year_regime.csv` C-2023-up cell (sole C-negative
  year/regime) for context.
- Confirm `liquidity_limitations.md` reasoning before any H4 follow-up spend.
