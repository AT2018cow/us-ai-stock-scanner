# M4 Dual-Track Paired Validation Report (frozen 2026-10-15)

Track 1 (human utility) across snap62/snap510/DEV/POST2024/ALL_39; Track 2
(paired 20/60/120d net-QQQ economics) across DEV_2023_2024, POST2024_HELD_OUT
(15 dates, unsealed once, RETROSPECTIVE_HELD_OUT — never prospective OOS),
and ALL_39_DATES, with date-level bootstrap 95% CI, LOO sensitivity, and
year/regime splits. policy_version="v1" stays the production default.

## 1. Human utility (ALL_39_DATES)

- v1_baseline: contradictory=4949, silent=0, ready_share=0.905983, gate=FAIL
- h1_quality_only: contradictory=0, silent=0, ready_share=0.917949, gate=PASS
- h2_entry_only: contradictory=4949, silent=0, ready_share=0.890598, gate=FAIL
- h3_action_only: contradictory=4949, silent=0, ready_share=0.935043, gate=FAIL
- v2_combined: contradictory=0, silent=0, ready_share=0.947009, gate=PASS

## 2. Paired economics, TOP15 60d (v2_combined vs v1_baseline)

- DEV_2023_2024: mean_delta=-0.003973 CI95=[-0.013229,0.005764] LOO_min=-0.006672 verdict=development reference (no gate)
- POST2024_HELD_OUT: mean_delta=0.000892 CI95=[-0.017469,0.017494] LOO_min=-0.002227 verdict=POSITIVE_POINT_ESTIMATE_CI_WIDE
- ALL_39_DATES: mean_delta=-0.002102 CI95=[-0.011345,0.007563] LOO_min=-0.003686 verdict=NEGATIVE_OR_FLAT

## 3. Year / regime robustness (TOP15 60d, v2_combined)

- year=2023: excess=-0.037239 delta=0.007071 CI95=[-0.004676,0.020607] (n_dates=12)
- year=2024: excess=-0.023451 delta=-0.015018 CI95=[-0.024524,-0.004836] (n_dates=12)
- year=2025: excess=-0.018881 delta=0.004872 CI95=[-0.015008,0.021590] (n_dates=12)
- year=2026Q1: excess=-0.085557 delta=-0.015032 CI95=[-0.065211,0.016546] (n_dates=3)
- regime=UP_SUPPORTIVE: excess=-0.016684 delta=0.001713 CI95=[-0.006080,0.009579] (n_dates=29)
- regime=DEFENSIVE_OR_DOWN: excess=-0.072769 delta=-0.013165 CI95=[-0.037999,0.010930] (n_dates=10)

## 4. Gate G4/G5 recommendation

Retain v1: no candidate clears both the human-utility gate and robust paired economics. policy_version="v1" remains the production default; revisit mechanisms, do not relax the gate.
Shadow candidates: []

## 5. Report v2 parity sample

- snap62: n=62 exceptions=0 ordering_mismatches=0 abs_paths=0 ok=True
- snap510: n=510 exceptions=0 ordering_mismatches=0 abs_paths=0 ok=True
- hist_2024-06-28_v1_baseline: n=638 exceptions=0 ordering_mismatches=0 abs_paths=0 ok=True
- hist_2024-06-28_v2_combined: n=638 exceptions=0 ordering_mismatches=0 abs_paths=0 ok=True

_End of M4 validation._
