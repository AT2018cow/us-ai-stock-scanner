"""Backtest evaluation primitives."""

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
]
