# PR30 outcome: parity fixed, single-gate mechanism fails

Date: 2026-10-10
Code fix: research scripts now drop the dataset `channel` column before
research assessment, matching production (whose cross-sections carry no
channel at assessment time). Regression test:
`test_rank_channel_ignores_dataset_channel_column` (fails pre-fix with the
`2.7 vs 2.0` signature, passes post-fix).

## Root cause of the same-state code-path mismatch (resolved)

`build_research_assessment` awards `ai_infrastructure_exposure` (+0.7 and a
priority flip) to any row whose `channel` contains `ai_enabler`. The PR28/PR30
research path scored dataset rows that still carried their channel label, so
ai_enabler-channel rows lacking bucket/ETF triggers were over-included versus
production. All 20 pre-fix **same-state** mismatches were ai_enabler; core_ai
and ai_peripheral were clean in that same-state comparison. After the fix,
same-state oracle parity is **168/168**.

This does **not** retroactively convert the historical PR28 Oct-8 replay vs
Oct-9 extraction check from 114/126 to a pass. That older cross-run artifact
contained 10 ai_enabler mismatches plus one ai_peripheral and one core_ai
mismatch and also spans mutable data/cache states. The channel leak explains
the research code-path parity defect; the old cross-run hard-stop remains
historical evidence of non-identical run state.

## B-arm result (valid comparison, negative outcome)

Relaxing only `max_range_position_52w` (hard→soft, threshold unchanged):

- 120d pooled B-A: mean +0.0002, median 0.0000, positive-dates 38%,
  block-6 90% CI [-0.0033, +0.0036] (covers zero)
- 2023: +0.68% (one date contributes 48%)
- 2024 (key stress year): -0.01%
- 2025 (hypothesis year): -0.56%, positive-dates only 20%
- down regime: -0.05%
- median A/B Jaccard 0.90+ (narrow perturbation, as designed)

Failed gates: 2024/2025 deltas not positive, positive-date ratio, bootstrap
lower bound, down-regime. The single range-gate relaxation does not explain
the 2023/2025 low_value edge. Position-gate path stops here unless a new
mechanism (e.g. multi-gate interaction) is pre-registered separately.
No production change.
