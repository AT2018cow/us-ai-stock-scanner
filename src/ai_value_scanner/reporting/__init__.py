"""Reporting and output helpers."""

from .backtest import build_markdown_report as build_backtest_markdown_report
from .backtest import resolve_output_paths as resolve_backtest_output_paths
from .scan import (
    build_run_report_markdown,
    default_run_stem,
    log_status,
    resolve_output_paths,
    write_csv_atomic,
)

__all__ = [
    "build_backtest_markdown_report",
    "build_run_report_markdown",
    "default_run_stem",
    "log_status",
    "resolve_backtest_output_paths",
    "resolve_output_paths",
    "write_csv_atomic",
]

from .snapshot import (
    DecisionSnapshotPaths,
    build_run_manifest,
    decision_snapshot_paths,
    load_previous_snapshot,
    load_snapshot_decisions,
    resolve_git_commit_sha,
    write_decision_snapshot,
)
