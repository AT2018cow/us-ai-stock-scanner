# Parameter Tuning Report

- generated_utc: 2026-10-05T23:05:27.164264+00:00
- tuning_run_id: `pre_e01_f39d06f_tuner_risk_off`
- base_config: `configs/config.risk_off.json`
- param_space: `configs/tuner.param_space.json`
- list_types: `low_value,industry_trend,momentum,research_pool`
- primary_list_types: `low_value`
- windows: `2023:2023-01-01->2023-12-31, 2024:2024-01-01->2024-12-31, 2025:2025-01-01->2025-12-31`
- candidate_count: 4
- selection_mode: `walk_forward`
- constraints_passed (pooled diagnostic): 0
- guardrails: min_avg_return=0.0, min_avg_excess_vs_qqq=0.0, min_avg_win_rate=0.52, min_positive_window_score_ratio=0.5, min_positive_excess_window_ratio=0.5, max_empty_window_ratio=0.25

## Anchored Walk-Forward OOS

Each fold selects a candidate using only the preceding windows; the next window is held out until after selection. The final candidate is the one selected before the last window, not a candidate re-ranked on that held-out data.

### risk_on

- train=`2023` → held-out=`2024` | selected=`cand_003` | train_pass=False | OOS_pass=False | OOS_score=0.1425 | OOS_excess=-0.0029
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- train=`2023+2024` → held-out=`2025` | selected=`cand_001` | train_pass=False | OOS_pass=False | OOS_score=-0.0226 | OOS_excess=-0.0218
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low;heldout_avg_win_rate_too_low`
- final_candidate: `cand_001` | promotion_eligible=False

### risk_off

- train=`2023` → held-out=`2024` | selected=`cand_001` | train_pass=False | OOS_pass=False | OOS_score=0.1425 | OOS_excess=-0.0029
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- train=`2023+2024` → held-out=`2025` | selected=`cand_004` | train_pass=False | OOS_pass=False | OOS_score=-0.0228 | OOS_excess=-0.0220
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low;heldout_avg_win_rate_too_low`
- final_candidate: `cand_004` | promotion_eligible=False


## Profile Picks

- risk_on: `cand_001` | selected_on=`2023+2024` | train_rank=0.1889 | held_out=`2025` | OOS_pass=False | OOS_score=-0.0226 | OOS_excess=-0.0218
- risk_off: `cand_004` | selected_on=`2023+2024` | train_rank=0.1262 | held_out=`2025` | OOS_pass=False | OOS_score=-0.0228 | OOS_excess=-0.0220

## Top 10 Candidates (Pooled Diagnostic; not used for walk-forward selection)

- `cand_002` | obj=-1.7426 | cov=0.944 | win=0.633 | dd=-0.155 | strict_valid=34 | research_valid=36 | research_excess=0.0095 | pos_score_windows=0.667 | pos_excess_windows=0.000 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  window_failure_summary: `{"negative_excess": 3}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.4, "ai_peripheral.min_ai_link_score": 0.26, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link", "negative_momentum"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 2.5, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.004, "min_fundamental_quality_score": 0.56, "research_pool_min_score": 2.4, "research_pool_top_n": 35}`
- `cand_003` | obj=-1.7431 | cov=0.944 | win=0.633 | dd=-0.155 | strict_valid=34 | research_valid=36 | research_excess=0.0096 | pos_score_windows=0.667 | pos_excess_windows=0.000 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  window_failure_summary: `{"negative_excess": 3}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.36, "ai_peripheral.min_ai_link_score": 0.3, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link", "negative_momentum"], "low_value_min_research_score": 0.0, "max_net_debt_to_ebitda": 3.5, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.006, "min_fundamental_quality_score": 0.58, "research_pool_min_score": 2.0, "research_pool_top_n": 35}`
- `cand_004` | obj=-1.7433 | cov=0.944 | win=0.633 | dd=-0.155 | strict_valid=34 | research_valid=36 | research_excess=0.0103 | pos_score_windows=0.667 | pos_excess_windows=0.000 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  window_failure_summary: `{"negative_excess": 3}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.36, "ai_peripheral.min_ai_link_score": 0.26, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.7, "max_ps_hist_percentile": 0.7, "min_fcf_yield": 0.004, "min_fundamental_quality_score": 0.56, "research_pool_min_score": 2.4, "research_pool_top_n": 50}`
- `cand_001` | obj=-1.7439 | cov=0.944 | win=0.633 | dd=-0.155 | strict_valid=34 | research_valid=36 | research_excess=0.0100 | pos_score_windows=0.667 | pos_excess_windows=0.000 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  window_failure_summary: `{"negative_excess": 3}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.34, "core_ai.min_ai_link_score": 0.44, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 2.5, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.7, "min_fcf_yield": 0.004, "min_fundamental_quality_score": 0.6, "research_pool_min_score": 1.8, "research_pool_top_n": 70}`
