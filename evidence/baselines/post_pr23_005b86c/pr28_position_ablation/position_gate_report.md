# PR28 risk_off low_value position-gate ablation

Retrospective mechanism validation only. This is not OOS and cannot promote production parameters.

## Contract

- A: current risk_off low_value pipeline.
- B: move the pre-registered position/range hard gates to soft; thresholds and all other rules stay unchanged.
- expanded rows: 23774
- expanded dates: 42
- active targets by channel: {"ai_enabler": ["min_drawdown_from_52w_high", "max_range_position_52w", "max_price_to_sma200"], "ai_peripheral": ["min_drawdown_from_52w_high", "max_range_position_52w", "max_price_to_sma200"], "core_ai": ["min_drawdown_from_52w_high", "max_range_position_52w", "max_price_to_sma200"]}

## Baseline replay parity

- channel-date exact matches: 114/126
- exact parity: False

## 120d paired A/B

- all:ALL: n=36, mean_delta=+0.0660, median_delta=+0.0519, positive_dates=86%, median_jaccard=0.46, top_abs_date_share=10.7%
- year:2023: n=12, mean_delta=+0.0707, median_delta=+0.0416, positive_dates=92%, median_jaccard=0.47, top_abs_date_share=27.1%
- year:2024: n=12, mean_delta=+0.0532, median_delta=+0.0547, positive_dates=100%, median_jaccard=0.44, top_abs_date_share=14.8%
- year:2025: n=10, mean_delta=+0.0810, median_delta=+0.0996, positive_dates=60%, median_jaccard=0.48, top_abs_date_share=24.3%
- year:2026: n=2, mean_delta=+0.0390, median_delta=+0.0390, positive_dates=100%, median_jaccard=0.47, top_abs_date_share=99.7%
- regime:down: n=7, mean_delta=+0.0446, median_delta=+0.0403, positive_dates=86%, median_jaccard=0.51, top_abs_date_share=30.2%
- regime:up: n=29, mean_delta=+0.0712, median_delta=+0.0533, positive_dates=86%, median_jaccard=0.46, top_abs_date_share=12.3%

## Retrospective robustness gate

- pass: **False**
- failures: baseline_selection_parity_failed;selection_overlap_too_low

## Interpretation

- 2023 and 2025 are hypothesis-forming years.
- 2024 is the key full-year stress check.
- 2026YTD is diagnostic because 120d labels are immature.
- Down-regime degradation is a stop condition because risk_off has a defensive role.
