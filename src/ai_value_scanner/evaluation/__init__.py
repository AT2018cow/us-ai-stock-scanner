"""Backtest evaluation primitives."""

from .entry_quality import (
    apply_entry_quality_v1,
    build_entry_quality_evaluation_frame,
    build_entry_state_transitions,
    summarize_entry_state_cohorts,
    summarize_entry_state_concentration,
    summarize_entry_state_persistence,
    validate_entry_replay_frame,
)
from .company_quality import (
    apply_company_quality_v1,
    summarize_quality_cohorts,
    summarize_quality_concentration,
    summarize_quality_rank_correlation,
    validate_quality_replay_frame,
)
from .backtest import (
    build_signal_diagnostics,
    event_backtest,
    fallback_label_end_date,
    forward_return,
    forward_return_with_exit,
    infer_segment_label,
    next_trading_index,
    non_overlapping_cumulative,
    non_overlapping_event_returns,
    parse_json_object,
    summarize_backtest,
    summarize_backtest_by_segment,
)

__all__ = [
    "validate_entry_replay_frame",
    "summarize_entry_state_persistence",
    "summarize_entry_state_concentration",
    "summarize_entry_state_cohorts",
    "build_entry_state_transitions",
    "build_entry_quality_evaluation_frame",
    "apply_entry_quality_v1",
    "apply_company_quality_v1",
    "build_signal_diagnostics",
    "event_backtest",
    "fallback_label_end_date",
    "forward_return",
    "forward_return_with_exit",
    "infer_segment_label",
    "next_trading_index",
    "non_overlapping_cumulative",
    "non_overlapping_event_returns",
    "parse_json_object",
    "summarize_backtest",
    "summarize_backtest_by_segment",
    "summarize_quality_cohorts",
    "summarize_quality_concentration",
    "summarize_quality_rank_correlation",
    "validate_quality_replay_frame",
]
