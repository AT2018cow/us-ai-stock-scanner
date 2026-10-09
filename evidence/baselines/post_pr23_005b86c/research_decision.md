# Research decision: post-PR23 baseline checkpoint

Date: 2026-10-09
RUN_ID: `post_pr23_baseline_202610`
Code: experiment replay/dataset/tuner executed on Modal, experiment SHA `26f93e4`
(PR #25 merge); tuner CLI resilience fix `005b86c` (no science change).
Production configs **unchanged**, no `--promote` used.

## 1. Evidence classes (kept separate)

1. **current-config retrospective baseline** — frozen configs over 2023-01-01 →
   2026-09-30, monthly, 15 bps, next_open/close, rules_proxy, no fallback.
   For attribution and paired style comparison. **Not automatically OOS**.
2. **anchored OOS selection baseline** — walk-forward tuner, 36 candidates per
   style, seed 42, windows 2023/2024/2025/2026YTD, label purge at every
   held-out boundary. Only this class may be labelled anchored OOS.

## 2. Retrospective findings (descriptive, not promotion claims)

- The return mass sits in `momentum` and `industry_trend`; `low_value` is
  weakest under risk_off (120d avg ~10% vs ~18% momentum, excess −1.3%).
  120d horizons show high win rates but these are equal-weighted
  signal-portfolio labels, not tradable NAV.
- Paired risk_on − risk_off (same dates/benchmarks/costs) is near zero for
  most list/year cells. The aggregate risk_on edge concentrates in
  `low_value` 2023 (+6.7pp) and 2025 (+12.0pp).
- Symbol concentration is moderate: 120d top-1 share 6–9% (MU in momentum
  both styles); removing the top winner keeps all totals positive.
- Sweep candidate-zero offline baselines: risk_off 0.152 (train 0.169 /
  valid 0.052), risk_on 0.199 (train 0.217 / valid 0.136), with R04 purging
  1/3/6 late-train dates for 20/60/120d.

## 3. Anchored OOS findings

- All 12 held-out folds report `OOS_pass=False`, dominated by
  `heldout_valid_events_too_low`: strict guardrails demand more valid events
  than a single held-out year provides for these lists/horzons.
- 2025 held-out selections show positive excess (risk_on cand_005 +8.0%,
  risk_off-profile cand_012 +8.5% in the risk_on run) but neither survives
  the 2026YTD held-out (both final candidates −2.0%).
- Fold selections are unstable across windows (cand_034 → cand_005 →
  cand_028): no candidate generalizes; both runs conclude
  `promotion_eligible=False`. **No production parameter change.**

## 4. Data limitations / evidence grade

- Alpaca IEX dollar volumes are a ~3% tape proxy; do not read them as real
  liquidity or capacity.
- Universe is the fixed current candidate pool with PIT availability
  filtering; pre-2026-09-22 dates use the union approximation. All 32
  watchlist_history snapshots have identical content.
- SEC is live data: the Modal risk_off replay differs from the earlier local
  attempt only at the final unpriced 2026-09-30 date (low_value 19 vs 18
  selected); causality is filing drift, not code drift.
- `non-overlapping cumulative` is a sampling diagnostic, **not account NAV**.
- Sample sizes are small for held-out claims; keep claims descriptive.

## 5. Next ablation hypotheses (1–2 only)

1. **risk_off low_value gate audit**: risk_off's strict valuation/quality
   gates discard the winners that risk_on low_value catches in 2023/2025.
   First-fail diagnostics on the 2023/2025 low_value dates will show which
   gate removes them.
2. **Ranking monotonicity before any weight tuning**: use the two frozen
   weight datasets to test score-decile forward returns and rank IC per
   list; if high score is not monotone vs mid/low, threshold tuning is
   pointless.

Chosen next PR from attribution, not from a pooled sweep.
