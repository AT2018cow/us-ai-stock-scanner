# Parameter Tuning Report

- generated_utc: 2026-10-09T16:23:52.901911+00:00
- tuning_run_id: `corrected_oos_risk_on`
- base_config: `configs/config.risk_on.json`
- param_space: `configs/tuner.param_space.momentum.json`
- list_types: `low_value,industry_trend,momentum,research_pool`
- primary_list_types: `low_value`
- windows: `2023:2023-01-01->2023-12-31, 2024:2024-01-01->2024-12-31, 2025:2025-01-01->2025-12-31, 2026YTD:2026-01-01->2026-09-30`
- candidate_count: 36
- selection_mode: `walk_forward`
- constraints_passed (pooled diagnostic): 0
- guardrails: min_avg_return=0.0, min_avg_excess_vs_qqq=0.0, min_avg_win_rate=0.52, min_positive_window_score_ratio=0.5, min_positive_excess_window_ratio=0.5, max_empty_window_ratio=0.25, min_total_valid_event_ratio=0.8, min_window_valid_event_ratio=0.8, min_oos_pass_ratio=0.6666666666666666, min_oos_positive_excess_ratio=0.6666666666666666
- offline_rescore_source: `evidence/baselines/post_pr23_005b86c/tuner_risk_on_results.csv` (candidate backtests were not rerun; pooled candidate fields below are source diagnostics, while anchored fold selection/guardrails are recomputed from window_metrics_json)

## Anchored Walk-Forward OOS

Each fold selects a candidate using only the preceding windows; the next window is held out until after selection. The final candidate is the one selected before the last window, not a candidate re-ranked on that held-out data.

### risk_on

- train=`2023` → held-out=`2024` | selected=`cand_034` | train_pass=False | OOS_pass=False | OOS_score=0.1143 | OOS_excess=-0.0073
  training_failure: `avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_avg_excess_too_low`
- train=`2023+2024` → held-out=`2025` | selected=`cand_005` | train_pass=False | OOS_pass=True | OOS_score=0.3461 | OOS_excess=0.0804
  training_failure: `avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
- train=`2023+2024+2025` → held-out=`2026YTD` | selected=`cand_028` | train_pass=False | OOS_pass=False | OOS_score=0.1121 | OOS_excess=-0.0199
  training_failure: `avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- OOS aggregate: folds=3 | pass_ratio=0.333 | positive_excess_ratio=0.333
- final_candidate: `cand_028` | promotion_eligible=False
- promotion_failure: `oos_pass_ratio_too_low;oos_positive_excess_ratio_too_low;final_training_constraints_failed;final_heldout_failed`

### risk_off

- train=`2023` → held-out=`2024` | selected=`cand_026` | train_pass=False | OOS_pass=False | OOS_score=0.1058 | OOS_excess=-0.0049
  training_failure: `avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_avg_excess_too_low`
- train=`2023+2024` → held-out=`2025` | selected=`cand_012` | train_pass=False | OOS_pass=True | OOS_score=0.3543 | OOS_excess=0.0847
  training_failure: `avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
- train=`2023+2024+2025` → held-out=`2026YTD` | selected=`cand_005` | train_pass=False | OOS_pass=False | OOS_score=0.1121 | OOS_excess=-0.0199
  training_failure: `avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- OOS aggregate: folds=3 | pass_ratio=0.333 | positive_excess_ratio=0.333
- final_candidate: `cand_005` | promotion_eligible=False
- promotion_failure: `oos_pass_ratio_too_low;oos_positive_excess_ratio_too_low;final_training_constraints_failed;final_heldout_failed`


## Profile Picks

- risk_on: `cand_028` | selected_on=`2023+2024+2025` | train_rank=0.2007 | held_out=`2026YTD` | OOS_pass=False | OOS_score=0.1121 | OOS_excess=-0.0199
- risk_off: `cand_005` | selected_on=`2023+2024+2025` | train_rank=0.1268 | held_out=`2026YTD` | OOS_pass=False | OOS_score=0.1121 | OOS_excess=-0.0199

## Top 10 Candidates (Pooled Diagnostic; not used for walk-forward selection)

- `cand_027` | obj=-1.3451 | cov=0.812 | win=0.760 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0024 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.02, "ai_enabler.momentum_min_return_60d": 0.08, "ai_peripheral.momentum_min_return_20d": 0.02, "ai_peripheral.momentum_min_return_60d": 0.03, "core_ai.momentum_max_60d_volatility": 0.75, "core_ai.momentum_max_drawdown_from_52w_high": 0.25, "core_ai.momentum_min_price_to_sma200": 1.04, "core_ai.momentum_min_return_20d": 0.03, "core_ai.momentum_min_return_60d": 0.05, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.05}`
- `cand_009` | obj=-1.3454 | cov=0.812 | win=0.759 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0038 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.06, "ai_enabler.momentum_min_return_60d": 0.12, "ai_peripheral.momentum_min_return_20d": 0.02, "ai_peripheral.momentum_min_return_60d": 0.12, "core_ai.momentum_max_60d_volatility": 0.9, "core_ai.momentum_max_drawdown_from_52w_high": 0.25, "core_ai.momentum_min_price_to_sma200": 1.04, "core_ai.momentum_min_return_20d": 0.03, "core_ai.momentum_min_return_60d": 0.1, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.05}`
- `cand_028` | obj=-1.3454 | cov=0.812 | win=0.759 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0038 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.06, "ai_enabler.momentum_min_return_60d": 0.12, "ai_peripheral.momentum_min_return_20d": 0.06, "ai_peripheral.momentum_min_return_60d": 0.12, "core_ai.momentum_max_60d_volatility": 0.75, "core_ai.momentum_max_drawdown_from_52w_high": 0.25, "core_ai.momentum_min_price_to_sma200": 1.04, "core_ai.momentum_min_return_20d": 0.05, "core_ai.momentum_min_return_60d": 0.1, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.05}`
- `cand_012` | obj=-1.3454 | cov=0.812 | win=0.759 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0043 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.06, "ai_enabler.momentum_min_return_60d": 0.08, "ai_peripheral.momentum_min_return_20d": 0.02, "ai_peripheral.momentum_min_return_60d": 0.03, "core_ai.momentum_max_60d_volatility": 0.6, "core_ai.momentum_max_drawdown_from_52w_high": 0.15, "core_ai.momentum_min_price_to_sma200": 1.04, "core_ai.momentum_min_return_20d": 0.07, "core_ai.momentum_min_return_60d": 0.1, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.02}`
- `cand_005` | obj=-1.3462 | cov=0.812 | win=0.759 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0030 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.06, "ai_enabler.momentum_min_return_60d": 0.08, "ai_peripheral.momentum_min_return_20d": 0.06, "ai_peripheral.momentum_min_return_60d": 0.03, "core_ai.momentum_max_60d_volatility": 0.6, "core_ai.momentum_max_drawdown_from_52w_high": 0.25, "core_ai.momentum_min_price_to_sma200": 1.08, "core_ai.momentum_min_return_20d": 0.05, "core_ai.momentum_min_return_60d": 0.1, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.05}`
- `cand_034` | obj=-1.3489 | cov=0.812 | win=0.755 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0030 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.02, "ai_enabler.momentum_min_return_60d": 0.12, "ai_peripheral.momentum_min_return_20d": 0.04, "ai_peripheral.momentum_min_return_60d": 0.03, "core_ai.momentum_max_60d_volatility": 0.9, "core_ai.momentum_max_drawdown_from_52w_high": 0.15, "core_ai.momentum_min_price_to_sma200": 1.0, "core_ai.momentum_min_return_20d": 0.07, "core_ai.momentum_min_return_60d": 0.15, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.05}`
- `cand_002` | obj=-1.3516 | cov=0.812 | win=0.749 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0038 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.02, "ai_enabler.momentum_min_return_60d": 0.03, "ai_peripheral.momentum_min_return_20d": 0.06, "ai_peripheral.momentum_min_return_60d": 0.12, "core_ai.momentum_max_60d_volatility": 0.6, "core_ai.momentum_max_drawdown_from_52w_high": 0.15, "core_ai.momentum_min_price_to_sma200": 1.0, "core_ai.momentum_min_return_20d": 0.07, "core_ai.momentum_min_return_60d": 0.1, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.02}`
- `cand_001` | obj=-1.3516 | cov=0.812 | win=0.749 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0038 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.02, "ai_enabler.momentum_min_return_60d": 0.03, "ai_peripheral.momentum_min_return_20d": 0.02, "ai_peripheral.momentum_min_return_60d": 0.12, "core_ai.momentum_max_60d_volatility": 0.75, "core_ai.momentum_max_drawdown_from_52w_high": 0.35, "core_ai.momentum_min_price_to_sma200": 1.0, "core_ai.momentum_min_return_20d": 0.07, "core_ai.momentum_min_return_60d": 0.05, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.02}`
- `cand_004` | obj=-1.3516 | cov=0.812 | win=0.749 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0038 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.02, "ai_enabler.momentum_min_return_60d": 0.08, "ai_peripheral.momentum_min_return_20d": 0.02, "ai_peripheral.momentum_min_return_60d": 0.03, "core_ai.momentum_max_60d_volatility": 0.6, "core_ai.momentum_max_drawdown_from_52w_high": 0.25, "core_ai.momentum_min_price_to_sma200": 1.04, "core_ai.momentum_min_return_20d": 0.07, "core_ai.momentum_min_return_60d": 0.1, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.05}`
- `cand_003` | obj=-1.3516 | cov=0.812 | win=0.749 | dd=-0.172 | strict_valid=38 | research_valid=42 | research_excess=0.0038 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.momentum_min_return_20d": 0.02, "ai_enabler.momentum_min_return_60d": 0.08, "ai_peripheral.momentum_min_return_20d": 0.06, "ai_peripheral.momentum_min_return_60d": 0.08, "core_ai.momentum_max_60d_volatility": 0.75, "core_ai.momentum_max_drawdown_from_52w_high": 0.35, "core_ai.momentum_min_price_to_sma200": 1.08, "core_ai.momentum_min_return_20d": 0.07, "core_ai.momentum_min_return_60d": 0.15, "global.max_20d_return": 0.3, "global.min_price_to_sma200": 1.02}`
