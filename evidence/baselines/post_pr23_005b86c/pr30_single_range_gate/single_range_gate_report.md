# PR30 same-state single range-gate ablation

Retrospective mechanism validation only. No production promotion is allowed.

## Frozen contract

- dataset SHA256: bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6
- target: max_range_position_52w hard -> soft
- A: canonical production-parity replay selector on the frozen cross-section.
- B: same cross-section, same config, same scoring/research/caps/Top-N; only the target hard gate moves to the soft layer.

## Same-state oracle parity

- exact ordered rows: 168/168
- pass: True

This parity compares two code paths on identical in-memory rows. It replaces the invalid Oct-8 replay vs Oct-9 extraction timing comparison as the code-equivalence gate; it does not rewrite the historical PR28 hard-stop record.

## 120d paired A/B

- all:ALL: n=37, mean=+0.0002, median=+0.0000, positive=38%, median_jaccard=0.92, top_date=12.7%, block6 CI90=[-0.0033,+0.0036]
- year:2023: n=12, mean=+0.0068, median=+0.0015, positive=50%, median_jaccard=0.94, top_date=48.0%, block6 CI90=[+0.0034,+0.0102]
- year:2024: n=12, mean=-0.0001, median=+0.0013, positive=50%, median_jaccard=0.89, top_date=16.8%, block6 CI90=[-0.0063,+0.0060]
- year:2025: n=10, mean=-0.0056, median=-0.0006, positive=20%, median_jaccard=0.94, top_date=34.5%, block6 CI90=[-0.0071,-0.0041]
- year:2026: n=3, mean=-0.0058, median=+0.0000, positive=0%, median_jaccard=1.00, top_date=100.0%, block6 CI90=[-0.0058,-0.0058]
- regime:down: n=7, mean=-0.0005, median=+0.0000, positive=29%, median_jaccard=0.97, top_date=51.2%, block6 CI90=[-0.0030,+0.0020]
- regime:up: n=30, mean=+0.0003, median=+0.0000, positive=40%, median_jaccard=0.90, top_date=14.3%, block6 CI90=[-0.0032,+0.0042]

## Pre-registered retrospective gate

- pass: **False**
- failures: 2024_120d_delta_not_positive;2025_120d_delta_not_positive;all_120d_positive_date_ratio_not_above_half;all_120d_block_bootstrap_lower_not_positive;down_regime_120d_degraded

## Interpretation limits

- The dataset is retrospective and uses the documented pre-snapshot union approximation.
- 2023/2025 contributed to the original hypothesis. 2024 remains the most useful full-year stress check.
- 2026YTD is diagnostic because long-horizon labels are immature.
- The 120d confidence interval uses a circular moving-block bootstrap with block length ceil(120/21)=6 months to account for overlapping monthly forward labels.
- The old PR28 B arm remains quarantined and is not reused as validation evidence.
