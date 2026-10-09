# Parameter Tuning Report

- generated_utc: 2026-10-09T15:00:17.783597+00:00
- tuning_run_id: `tuning_20261009T080134Z`
- base_config: `outputs/post_pr23_baseline_202610/frozen_inputs/config.risk_off.json`
- param_space: `configs/tuner.param_space.json`
- list_types: `low_value,industry_trend,momentum,research_pool`
- primary_list_types: `low_value`
- windows: `2023:2023-01-01->2023-12-31, 2024:2024-01-01->2024-12-31, 2025:2025-01-01->2025-12-31, 2026YTD:2026-01-01->2026-09-30`
- candidate_count: 36
- selection_mode: `walk_forward`
- constraints_passed (pooled diagnostic): 0
- guardrails: min_avg_return=0.0, min_avg_excess_vs_qqq=0.0, min_avg_win_rate=0.52, min_positive_window_score_ratio=0.5, min_positive_excess_window_ratio=0.5, max_empty_window_ratio=0.25

## Anchored Walk-Forward OOS

Each fold selects a candidate using only the preceding windows; the next window is held out until after selection. The final candidate is the one selected before the last window, not a candidate re-ranked on that held-out data.

### risk_on

- train=`2023` → held-out=`2024` | selected=`cand_012` | train_pass=False | OOS_pass=False | OOS_score=0.0996 | OOS_excess=-0.0056
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- train=`2023+2024` → held-out=`2025` | selected=`cand_032` | train_pass=False | OOS_pass=False | OOS_score=0.0528 | OOS_excess=-0.0014
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- train=`2023+2024+2025` → held-out=`2026YTD` | selected=`cand_032` | train_pass=False | OOS_pass=False | OOS_score=0.0699 | OOS_excess=-0.0047
  training_failure: `total_valid_events_too_low;window_valid_events_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- final_candidate: `cand_032` | promotion_eligible=False

### risk_off

- train=`2023` → held-out=`2024` | selected=`cand_035` | train_pass=False | OOS_pass=False | OOS_score=0.1091 | OOS_excess=-0.0044
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low;positive_window_score_ratio_too_low;positive_excess_window_ratio_too_low`
  OOS_failure: `heldout_valid_events_too_low;heldout_avg_excess_too_low`
- train=`2023+2024` → held-out=`2025` | selected=`cand_030` | train_pass=False | OOS_pass=False | OOS_score=0.0768 | OOS_excess=0.0060
  training_failure: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  OOS_failure: `heldout_valid_events_too_low`
- train=`2023+2024+2025` → held-out=`2026YTD` | selected=`cand_030` | train_pass=False | OOS_pass=False | OOS_score=0.1340 | OOS_excess=0.0031
  training_failure: `total_valid_events_too_low;window_valid_events_too_low`
  OOS_failure: `heldout_valid_events_too_low`
- final_candidate: `cand_030` | promotion_eligible=False


## Profile Picks

- risk_on: `cand_032` | selected_on=`2023+2024+2025` | train_rank=0.1992 | held_out=`2026YTD` | OOS_pass=False | OOS_score=0.0699 | OOS_excess=-0.0047
- risk_off: `cand_030` | selected_on=`2023+2024+2025` | train_rank=0.1190 | held_out=`2026YTD` | OOS_pass=False | OOS_score=0.1340 | OOS_excess=0.0031

## Top 10 Candidates (Pooled Diagnostic; not used for walk-forward selection)

- `cand_030` | obj=-1.4040 | cov=0.833 | win=0.679 | dd=-0.115 | strict_valid=40 | research_valid=42 | research_excess=0.0045 | pos_score_windows=1.000 | pos_excess_windows=0.750 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 1, "passed": 3}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.36, "ai_peripheral.min_ai_link_score": 0.3, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 2.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.006, "min_fundamental_quality_score": 0.6, "research_pool_min_score": 1.8, "research_pool_top_n": 35}`
- `cand_029` | obj=-1.4040 | cov=0.833 | win=0.679 | dd=-0.115 | strict_valid=40 | research_valid=42 | research_excess=0.0045 | pos_score_windows=1.000 | pos_excess_windows=0.750 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 1, "passed": 3}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.36, "ai_peripheral.min_ai_link_score": 0.34, "core_ai.min_ai_link_score": 0.46, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 2.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.004, "min_fundamental_quality_score": 0.56, "research_pool_min_score": 1.8, "research_pool_top_n": 70}`
- `cand_009` | obj=-1.4107 | cov=0.833 | win=0.713 | dd=-0.134 | strict_valid=40 | research_valid=42 | research_excess=0.0059 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.4, "ai_peripheral.min_ai_link_score": 0.34, "core_ai.min_ai_link_score": 0.44, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.7, "min_fcf_yield": 0.004, "min_fundamental_quality_score": 0.6, "research_pool_min_score": 2.4, "research_pool_top_n": 50}`
- `cand_013` | obj=-1.4152 | cov=0.833 | win=0.709 | dd=-0.134 | strict_valid=40 | research_valid=42 | research_excess=0.0059 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.34, "core_ai.min_ai_link_score": 0.46, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 3.5, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.008, "min_fundamental_quality_score": 0.6, "research_pool_min_score": 2.4, "research_pool_top_n": 35}`
- `cand_033` | obj=-1.4152 | cov=0.833 | win=0.709 | dd=-0.134 | strict_valid=40 | research_valid=42 | research_excess=0.0045 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.3, "core_ai.min_ai_link_score": 0.44, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.008, "min_fundamental_quality_score": 0.6, "research_pool_min_score": 1.8, "research_pool_top_n": 35}`
- `cand_011` | obj=-1.4153 | cov=0.833 | win=0.709 | dd=-0.134 | strict_valid=40 | research_valid=42 | research_excess=0.0059 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.34, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 3.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.7, "max_ps_hist_percentile": 0.7, "min_fcf_yield": 0.008, "min_fundamental_quality_score": 0.58, "research_pool_min_score": 2.4, "research_pool_top_n": 35}`
- `cand_027` | obj=-1.4154 | cov=0.833 | win=0.677 | dd=-0.115 | strict_valid=40 | research_valid=42 | research_excess=0.0057 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.34, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link", "negative_momentum"], "low_value_min_research_score": 2.0, "max_net_debt_to_ebitda": 2.5, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.006, "min_fundamental_quality_score": 0.56, "research_pool_min_score": 2.0, "research_pool_top_n": 35}`
- `cand_019` | obj=-1.4154 | cov=0.833 | win=0.677 | dd=-0.115 | strict_valid=40 | research_valid=42 | research_excess=0.0057 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.36, "ai_peripheral.min_ai_link_score": 0.3, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link", "negative_momentum"], "low_value_min_research_score": 2.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.65, "min_fcf_yield": 0.004, "min_fundamental_quality_score": 0.58, "research_pool_min_score": 2.0, "research_pool_top_n": 50}`
- `cand_005` | obj=-1.4156 | cov=0.833 | win=0.677 | dd=-0.115 | strict_valid=40 | research_valid=42 | research_excess=0.0058 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.26, "core_ai.min_ai_link_score": 0.48, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link", "negative_momentum"], "low_value_min_research_score": 2.0, "max_net_debt_to_ebitda": 3.5, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.7, "min_fcf_yield": 0.006, "min_fundamental_quality_score": 0.56, "research_pool_min_score": 2.4, "research_pool_top_n": 35}`
- `cand_022` | obj=-1.4165 | cov=0.833 | win=0.691 | dd=-0.127 | strict_valid=40 | research_valid=42 | research_excess=0.0057 | pos_score_windows=1.000 | pos_excess_windows=0.500 | empty_windows=0.000 | pass=False
  failure_reason: `total_valid_events_too_low;window_valid_events_too_low;avg_excess_vs_qqq_too_low`
  window_failure_summary: `{"negative_excess": 2, "passed": 2}`
  deltas: `{"ai_enabler.min_ai_link_score": 0.32, "ai_peripheral.min_ai_link_score": 0.26, "core_ai.min_ai_link_score": 0.46, "low_value_allowed_research_priorities": ["research_now", "watch_for_pullback", "theme_only"], "low_value_excluded_research_risks": ["possible_value_trap", "weak_ai_link"], "low_value_min_research_score": 2.0, "max_net_debt_to_ebitda": 3.0, "max_pe_hist_percentile": 0.65, "max_ps_hist_percentile": 0.7, "min_fcf_yield": 0.006, "min_fundamental_quality_score": 0.56, "research_pool_min_score": 2.0, "research_pool_top_n": 35}`
