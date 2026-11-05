# Top-15 Stability & Turnover Validation (Phase 1, diagnostic only)

- Pre-registered spec: `docs/agent_specs/top15_stability_and_turnover_spec.md` (v2).
- Runner: `scripts/evaluate_top15_turnover_stability.py` SHA256 `5f66e08251009f61bc416655611ea5c25d99ae7522b88853851fb7f1a039fca1`.
- Fully offline and deterministic; frozen snapshots/datasets are read-only; no production code, config, or decision snapshot is changed.
- **This is diagnostic evidence only.** No policy change is proposed; Phase 2 requires a separate review and decision.

## 0. Verdict summary (G1–G4)

| gate | criterion | result |
|---|---|---|
| G1 | mean retained >= 12.0 (or turnover -35%) and 5d roundtrip -50% | B0_baseline:FAIL, S1_confirm_2_2_safe:PASS, S2_confirm_1_2_safe:PASS, S3_hysteresis_buffer:PASS, S4_hybrid_hysteresis_regime:PASS |
| G2 | damaged / INSUFFICIENT_DATA / Quality C-UNRATED never in Top-15 | B0_baseline:PASS, S1_confirm_2_2_safe:PASS, S2_confirm_1_2_safe:PASS, S3_hysteresis_buffer:PASS, S4_hybrid_hysteresis_regime:PASS |
| G3 | N=1 schemes stay stable (G1) without chasing (entry ret20 <= S1 + 1pp) | S1_confirm_2_2_safe:PASS, S2_confirm_1_2_safe:PASS, S3_hysteresis_buffer:PASS |
| G4 | ALL_51 60d excess degradation <= 1.0pp; bear/drawdown severe loss not worse | S3_hysteresis_buffer:FAIL |

G1/G2 apply to the 13 daily snapshots; G3 compares entry timing; G4 applies to the 51 frozen monthly cross-sections (B0 vs S3 only).

**Conclusion: no candidate passes all four gates on this evidence.** S1/S2 pass G1–G3 but G4 was not evaluated (Part B is B0 vs S3 only); S3 passes G1–G3 but fails G4 because bear/drawdown severe-loss rates are slightly worse. This Phase 1 evidence therefore does **not** support a Phase 2 promotion; any next step requires a new pre-registered review.

## 1. Provenance

- Base dataset: `company_quality_dataset_risk_off.v3.csv` (25025 rows, 39 dates, SHA256 `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`).
- 2022 bear dataset: `company_quality_dataset_risk_off.repaired.csv` (8251 rows, 12 dates, SHA256 `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6`).
- Live snapshots: `outputs/decisions` (13 dates, 2026-10-19 .. 2026-11-04).
- Scope: ETF_SLICE (`watchlist_etf_count >= 1`) for historical dates; live lists come from each snapshot's `daily_symbols`.
- Gate observations are extracted from each decision's `entry.gate_results` / evidence items; `regime` is reconstructed as `sign(return_60d - relative_strength_60d_qqq)` because the production `market_regime` gate does not persist its observed label on PASS.
- Part A `B0_baseline` uses each snapshot's `daily_symbols`; Part B `B0_baseline` uses the top-15 by production priority (the frozen cross-section has no state-change fillers).
- Reproduction command: `python scripts/evaluate_top15_turnover_stability.py --part all --output-dir docs/top15_stability_validation_20261105`.

## 2. Part A — 13 daily production snapshots

### 2.1 Retained count per transition

| transition | B0_baseline | S1_confirm_2_2_safe | S2_confirm_1_2_safe | S3_hysteresis_buffer | S4_hybrid_hysteresis_regime |
|---|---|---|---|---|---|
| 2026-10-19 → 2026-10-20 | 13 | 15 | 15 | 14 | 14 |
| 2026-10-20 → 2026-10-21 | 8 | 13 | 13 | 11 | 11 |
| 2026-10-21 → 2026-10-22 | 8 | 12 | 12 | 11 | 11 |
| 2026-10-22 → 2026-10-23 | 7 | 13 | 12 | 14 | 14 |
| 2026-10-23 → 2026-10-26 | 12 | 15 | 15 | 15 | 15 |
| 2026-10-26 → 2026-10-27 | 11 | 14 | 13 | 12 | 12 |
| 2026-10-27 → 2026-10-28 | 11 | 14 | 15 | 13 | 13 |
| 2026-10-28 → 2026-10-29 | 11 | 11 | 11 | 10 | 12 |
| 2026-10-29 → 2026-10-30 | 8 | 10 | 10 | 12 | 11 |
| 2026-10-30 → 2026-11-02 | 9 | 10 | 12 | 10 | 9 |
| 2026-11-02 → 2026-11-03 | 11 | 12 | 12 | 12 | 12 |
| 2026-11-03 → 2026-11-04 | 6 | 11 | 10 | 7 | 7 |

### 2.2 Scheme summary metrics

| scheme | mean retained | min retained | mean turnover | 1d whipsaw | 5d roundtrip | damaged leaked | mean list size |
|---|---|---|---|---|---|---|---|
| B0_baseline | 9.58 | 6 | 36.1% | 27 | 22 | 0 | 15.00 |
| S1_confirm_2_2_safe | 12.50 | 10 | 15.8% | 2 | 4 | 0 | 14.85 |
| S2_confirm_1_2_safe | 12.50 | 10 | 16.7% | 2 | 7 | 0 | 15.00 |
| S3_hysteresis_buffer | 11.75 | 7 | 21.7% | 8 | 7 | 0 | 15.00 |
| S4_hybrid_hysteresis_regime | 11.75 | 7 | 21.7% | 9 | 9 | 0 | 15.00 |

### 2.3 Typical trajectories (13 dates, 1 = in the main list)

| symbol | B0_baseline | S1_confirm_2_2_safe | S2_confirm_1_2_safe | S3_hysteresis_buffer | S4_hybrid_hysteresis_regime |
|---|---|---|---|---|---|
| MTCH | 0000000010100 | 0000000000000 | 0000000000000 | 0000000011100 | 0000000000100 |
| ECL | 1100111111010 | 1110000011111 | 1110000011111 | 1100000011010 | 1100000011010 |
| MSFT | 1111111111001 | 1111111111100 | 1111111111101 | 1111111111001 | 1111111111001 |
| AAPL | 0000000001101 | 0000000001111 | 0000000000001 | 0000000000001 | 0000000000001 |
| SSNC | 1110110000110 | 1111111100000 | 1111111100000 | 1110000000110 | 1110000000110 |

Dates: 2026-10-19, 2026-10-20, 2026-10-21, 2026-10-22, 2026-10-23, 2026-10-26, 2026-10-27, 2026-10-28, 2026-10-29, 2026-10-30, 2026-11-02, 2026-11-03, 2026-11-04.

## 3. Part B — 51 frozen monthly cross-sections (B0 vs S3)

| segment | scheme | dates | mean list | retention | mean excess 60d | win rate | severe loss | damaged leaked |
|---|---|---|---|---|---|---|---|---|
| ALL_51 | B0_baseline | 51 | 15.00 | 24.7% | -1.3% | 45.1% | 5.5% | 0 |
| ALL_51 | S3_hysteresis_buffer | 51 | 13.35 | 43.2% | -1.3% | 37.3% | 5.4% | 0 |
| BASE_39 | B0_baseline | 39 | 15.00 | 23.9% | -2.3% | 41.0% | 5.1% | 0 |
| BASE_39 | S3_hysteresis_buffer | 39 | 14.13 | 45.4% | -2.4% | 33.3% | 5.1% | 0 |
| BEAR_2022 | B0_baseline | 12 | 15.00 | 29.1% | +2.1% | 58.3% | 6.7% | 0 |
| BEAR_2022 | S3_hysteresis_buffer | 12 | 10.83 | 36.3% | +2.1% | 50.0% | 6.9% | 0 |
| FWD_DRAWDOWN_60D | B0_baseline | 17 | 15.00 | 21.7% | +3.6% | 64.7% | 11.0% | 0 |
| FWD_DRAWDOWN_60D | S3_hysteresis_buffer | 17 | 12.18 | 33.5% | +3.4% | 52.9% | 12.1% | 0 |

Retention is measured over consecutive dates within each segment; returns are date-equal means of 60d net-QQQ excess; severe loss is the share of stock-date observations with raw 60d return <= -20%.

## 4. Gate evidence

### G1

- Criterion: mean retained >= 12.0 (or turnover -35%) and 5d roundtrip -50%
- B0_baseline: mean retained 9.58; turnover 36.1%; roundtrip 22 (baseline 22)
- S1_confirm_2_2_safe: mean retained 12.50; turnover 15.8%; roundtrip 4 (baseline 22)
- S2_confirm_1_2_safe: mean retained 12.50; turnover 16.7%; roundtrip 7 (baseline 22)
- S3_hysteresis_buffer: mean retained 11.75; turnover 21.7%; roundtrip 7 (baseline 22)
- S4_hybrid_hysteresis_regime: mean retained 11.75; turnover 21.7%; roundtrip 9 (baseline 22)

### G2

- Criterion: damaged / INSUFFICIENT_DATA / Quality C-UNRATED never in Top-15
- B0_baseline: daily damaged leaked 0; historical damaged leaked 0
- S1_confirm_2_2_safe: daily damaged leaked 0; historical damaged leaked n/a
- S2_confirm_1_2_safe: daily damaged leaked 0; historical damaged leaked n/a
- S3_hysteresis_buffer: daily damaged leaked 0; historical damaged leaked 0
- S4_hybrid_hysteresis_regime: daily damaged leaked 0; historical damaged leaked n/a

### G3

- Criterion: N=1 schemes stay stable (G1) without chasing (entry ret20 <= S1 + 1pp)
- S1_confirm_2_2_safe: entries 43; mean entry ret20 +5.5%; delayed vs S1 0; G1 stable=True
- S2_confirm_1_2_safe: entries 45; mean entry ret20 +5.7%; delayed vs S1 6; G1 stable=True
- S3_hysteresis_buffer: entries 54; mean entry ret20 +5.2%; delayed vs S1 7; G1 stable=True

### G4

- Criterion: ALL_51 60d excess degradation <= 1.0pp; bear/drawdown severe loss not worse
- S3_hysteresis_buffer: ALL_51 excess -1.3% vs B0 -1.3%; bear severe-loss not worse=False; drawdown not worse=False

## 5. Honest limitations

- The 13 daily snapshots cover a short window; daily turnover is measured on observed production lists, not a long prospective sample.
- The 51 monthly dates are overlapping 60d labels and are not independent; they are a frozen retrospective cross-section.
- Candidate schemes are offline reconstructions from stored gate observations; they do not re-run production entry/action code with modified thresholds.
- S1/S2 confirmation semantics are evaluated on the same snapshot sequence; the first day is seeded with the baseline list for a fair transition comparison.
- Universe drift / latest-fallback caveats are inherited from the frozen datasets (AGENTS.md §4/§8). No promotion is implied.

## 6. Reproduction

1. Delete `docs/top15_stability_validation_20261105` and re-run `python scripts/evaluate_top15_turnover_stability.py --part all --output-dir docs/top15_stability_validation_20261105`; outputs are deterministic.
2. Verify every file against `SHA256SUMS`.
