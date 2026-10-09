# PR28 — risk_off low_value position-gate ablation (pre-registration)

Status: **research-only, implementation pending**. Base evidence: PR27 merged `d6d6965211ea6c3c66bb01be63a6de124016f456`; evidence commit `bcc50b07dd564e9b548054748df6021da10e747f`.

## Hypothesis

The risk_off low_value position/pullback hard-gate block suppresses subsequent continuation winners. This is a **candidate mechanism**, not established causality. Production ranking is not presumed correct; IC and decile monotonicity remain mixed.

## Frozen inputs

Use the existing PR27 risk_off survivor dataset (SHA256 prefix `4a0203d9`) and corrected risk_on dataset (SHA256 prefix `295e3de8`), with their complete metadata, frozen configs, and historical replay outputs. Before execution verify **full** SHA256 and metadata; abort on missing or mismatched data. Do not regenerate PIT datasets or refresh cache merely to run this ablation.

## Pre-registered arms

- **A control:** exact current risk_off low_value selection.
- **B intervention:** neutralize *only* the risk_off low_value hard checks `max_range_position_52w`, `min_drawdown_from_52w_high`, and `max_price_to_sma200`. Preserve their original raw feature values, score weights, soft-failure logic, all other hard/research gates, per-channel order, sector/ETF caps, Top-N and symbol deduplication.
- No threshold optimization, alternative weights, channel changes, or risk_on parameter transfer. All other list types remain identical.

The intervention must be implemented in an **offline research selector** with a narrow explicit override, not by editing production configs. Do not bypass the same-named soft constraints inadvertently; report their effect separately.

## Parity gate (mandatory before outcome analysis)

On identical date/channel/list-type pools, arm A must reproduce the frozen production selection (selected symbols **and order**, eligibility and first-fail reason). Emit machine-readable per-date diffs and halt if any unexplained mismatch. A candidate-zero aggregate score is **not** a parity test. Arm B must differ only at the specified hard checks; test a no-effect fixture, a single-gate fixture, a multi-gate fixture, and a cap/Top-N displacement fixture.

## Paired evaluation

Use the identical mature-label dates, next-open entry, close exit, 15-bps one-way cost, QQQ benchmark, and 20/60/120-day horizons. Report 2023, 2024, 2025, 2026YTD separately and pooled; include up/down regimes. Use date as the primary paired unit (not date×symbol×channel), deduplicate cross-channel symbols according to production behavior, and disclose overlapping 60/120-day labels. Show changes in eligibility, Top-N turnover, selected returns, excess return, win rate, coverage, concentration, and worst-date losses. Include median, sign count, leave-one-date-out range and uncertainty using a date-block method; do not treat channel-level cases as independent observations.

## Anchored validation and stopping

First perform deterministic offline replay on the frozen cross-section. Do not tune to the full-period results. If the mechanism is coherent, evaluate the **single fixed B arm** on anchored chronological folds, with training-label purge at each held-out boundary; no fold may choose its own gate relaxation. A retrospective config comparison is not anchored OOS. Stop without promotion if parity fails, results hinge on one date/symbol, the 2024/down-regime deterioration is unacceptable, or held-out results fail to support the hypothesis. Record unfavorable outcomes as evidence.

## Required outputs

`input_manifest.json` (full hashes, code SHA, label maturity and scope); `selection_parity.csv`; `arm_selection_by_date.csv`; `paired_outcomes_by_date.csv`; `year_regime_summary.csv`; `anchored_fold_summary.csv` when run; and `research_decision.md` distinguishing descriptive, counterfactual and anchored evidence. Never commit raw 43-MB datasets or mutable caches.

## Constraints

No production config or scanner behavior change, no broad tuner, no automatic promotion, and no new full historical replay unless offline parity proves the frozen dataset insufficient. Any Modal execution must be foreground-only with `MODAL_PROFILE=infi`; **never use `--detach`**.
