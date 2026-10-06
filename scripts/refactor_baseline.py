#!/usr/bin/env python3
"""Capture and compare the post-correctness / pre-E01 refactor baseline.

This tool does not run scans/backtests itself. It fingerprints fixed-prefix
artifacts produced by the documented baseline protocol, together with the
configs/watchlist that generated them. Later E01 PRs can rerun the same
experiments and use the compare subcommand as a zero-behaviour-drift gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_VERSION = 1

BACKTEST_SUFFIXES = {
    "signals": "_events_signals.csv",
    "events": "_events.csv",
    "summary": "_summary.csv",
    "benchmarks": "_benchmarks.csv",
    "segments": "_segments.csv",
    "signal_diagnostics": "_events_signal_diagnostics.csv",
    "signal_channel_summary": "_events_signal_channel_summary.csv",
    "report": "_report.md",
    "network": "_report_network.json",
}
DETERMINISTIC_BACKTEST_ARTIFACTS = (
    "signals",
    "events",
    "summary",
    "benchmarks",
    "segments",
    "signal_diagnostics",
    "signal_channel_summary",
)
TUNING_SUFFIXES = {
    "results": "_results.csv",
    "summary": "_summary.json",
    "report": "_report.md",
}

EXPERIMENT_LOCATION_KEYS = {
    "watchlist_csv_path",
    "watchlist_history_dir",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str, cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else None,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def git_context(root: Path | None = None) -> dict[str, Any]:
    status = _git("status", "--porcelain", cwd=root)
    return {
        "commit": _git("rev-parse", "HEAD", cwd=root),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root),
        "dirty": bool(status),
        "dirty_paths": status.splitlines() if status else [],
    }


def json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_record(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return None
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def csv_shape(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path)
    return {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
    }


def _jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 12)
    return value


def canonical_summary(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    sort_cols = [
        c
        for c in ("scenario", "list_type", "horizon_days")
        if c in frame.columns
    ]
    if sort_cols:
        frame = frame.sort_values(sort_cols, kind="mergesort")
    keep = [
        c
        for c in (
            "scenario",
            "list_type",
            "horizon_days",
            "n_events_total",
            "n_events_valid",
            "n_no_signal_events",
            "n_unpriced_events",
            "n_partial_valid_events",
            "avg_return",
            "median_return",
            "win_rate",
            "std_return",
            "avg_excess_vs_QQQ",
        )
        if c in frame.columns
    ]
    records: list[dict[str, Any]] = []
    for _, row in frame[keep].iterrows():
        records.append({key: _jsonable(row[key]) for key in keep})
    return records


def signal_contract(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path)
    result: dict[str, Any] = {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
    }
    if "signal_date" in frame.columns:
        dates = sorted(frame["signal_date"].dropna().astype(str).unique().tolist())
        result["signal_dates"] = dates
        result["signal_date_count"] = len(dates)
    if "scenario" in frame.columns:
        result["scenarios"] = sorted(
            frame["scenario"].dropna().astype(str).unique().tolist()
        )
    if "list_type" in frame.columns:
        result["list_types"] = sorted(
            frame["list_type"].dropna().astype(str).unique().tolist()
        )
    return result


def network_contract(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"present": False}
    payload = json_payload(path)
    alpaca = (payload.get("data_provenance") or {}).get("alpaca", {})
    return {
        "present": True,
        "had_rate_limit_or_network_issue": bool(
            payload.get("had_rate_limit_or_network_issue")
        ),
        "stale_market_data_fallback_used": bool(
            payload.get("stale_market_data_fallback_used")
        ),
        "alpaca": alpaca,
    }


def input_file(path: Path) -> dict[str, Any]:
    record = file_record(path)
    assert record is not None
    if path.suffix.lower() == ".json":
        try:
            payload = json_payload(path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            record["config_schema_version"] = payload.get("config_schema_version")
            record["strategy_style"] = payload.get("strategy_style")
    return record


def directory_contract(path: Path, pattern: str = "*.csv") -> dict[str, Any]:
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(path)
    files = sorted(p for p in path.glob(pattern) if p.is_file())
    if not files:
        raise ValueError(f"no snapshot CSV files found in {path}")
    records = [
        {
            "name": p.name,
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
        }
        for p in files
    ]
    digest = hashlib.sha256(
        "\n".join(f"{r['name']}:{r['sha256']}" for r in records).encode("utf-8")
    ).hexdigest()
    return {
        "path": str(path),
        "file_count": len(records),
        "sha256": digest,
        "files": records,
    }


def watchlist_contract(path: Path) -> dict[str, Any]:
    record = input_file(path)
    frame = pd.read_csv(path)
    record["rows"] = int(len(frame))
    if "enabled" in frame.columns:
        enabled = frame["enabled"].astype(str).str.lower().isin(
            {"1", "true", "yes", "y"}
        )
        record["enabled_rows"] = int(enabled.sum())
    if "symbol" in frame.columns:
        symbols = sorted(frame["symbol"].dropna().astype(str).str.upper().unique())
        record["unique_symbols"] = len(symbols)
        record["symbol_set_sha256"] = hashlib.sha256(
            "\n".join(symbols).encode("utf-8")
        ).hexdigest()
    return record


def backtest_contract(outputs_dir: Path, prefix: str) -> dict[str, Any]:
    paths = {
        key: outputs_dir / f"{prefix}{suffix}"
        for key, suffix in BACKTEST_SUFFIXES.items()
    }
    for key in DETERMINISTIC_BACKTEST_ARTIFACTS:
        if not paths[key].exists():
            raise FileNotFoundError(paths[key])

    artifacts: dict[str, Any] = {}
    for key, path in paths.items():
        artifacts[key] = file_record(path, required=key in DETERMINISTIC_BACKTEST_ARTIFACTS)

    return {
        "prefix": prefix,
        "deterministic_sha256": {
            key: artifacts[key]["sha256"]
            for key in DETERMINISTIC_BACKTEST_ARTIFACTS
        },
        "artifact_records": artifacts,
        "summary_contract": canonical_summary(paths["summary"]),
        "signals_contract": signal_contract(paths["signals"]),
        "events_shape": csv_shape(paths["events"]),
        "segments_shape": csv_shape(paths["segments"]),
        "network_contract": network_contract(paths["network"]),
    }


def tuning_contract(outputs_dir: Path, prefix: str) -> dict[str, Any]:
    paths = {
        key: outputs_dir / f"{prefix}{suffix}"
        for key, suffix in TUNING_SUFFIXES.items()
    }
    for key in ("results", "summary"):
        if not paths[key].exists():
            raise FileNotFoundError(paths[key])
    summary = json_payload(paths["summary"])
    results = pd.read_csv(paths["results"])
    return {
        "prefix": prefix,
        "deterministic_sha256": {
            "results": sha256_file(paths["results"]),
        },
        "artifact_records": {
            key: file_record(path, required=key in {"results", "summary"})
            for key, path in paths.items()
        },
        "selection_mode": summary.get("selection_mode"),
        "candidate_count": int(summary.get("candidates", len(results))),
        "picks": summary.get("picks"),
        "walk_forward": summary.get("walk_forward"),
        "result_columns": list(results.columns),
        "result_rows": int(len(results)),
    }


def capture_manifest(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repo_root).resolve()
    outputs = (root / args.outputs_dir).resolve()
    ctx = git_context(root)
    if args.require_clean and ctx["dirty"]:
        raise SystemExit(
            "Refusing to capture a refactor baseline from a dirty worktree. "
            "Commit/stash changes or pass --allow-dirty explicitly."
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": args.baseline_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "post-correctness / pre-E01 zero-behaviour-drift baseline",
        "git": ctx,
        "experiment_contract": {
            "historical_replay_start": args.replay_start,
            "historical_replay_end": args.replay_end,
            "rebalance_frequency": args.rebalance_frequency,
            "horizons": [20, 60, 120],
            "list_types": [
                "low_value",
                "industry_trend",
                "momentum",
                "research_pool",
            ],
            "theme_source": "rules_proxy",
            "pre_snapshot_universe": "union",
            "watchlist_csv_path": args.watchlist,
            "watchlist_history_dir": args.watchlist_history_dir,
            "allow_latest_watchlist_fallback": False,
            "promote": False,
        },
        "inputs": {
            "risk_off_config": input_file(root / args.risk_off_config),
            "risk_on_config": input_file(root / args.risk_on_config),
            "tuner_param_space": input_file(root / args.param_space),
            "watchlist": watchlist_contract(root / args.watchlist),
            "watchlist_history": directory_contract(root / args.watchlist_history_dir),
        },
        "runs": {
            "risk_off": backtest_contract(outputs, args.risk_off_prefix),
            "risk_on": backtest_contract(outputs, args.risk_on_prefix),
        },
    }
    if args.tuning_prefix:
        manifest["tuning_smoke"] = tuning_contract(outputs, args.tuning_prefix)
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def semantic_experiment_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return only behavior-defining experiment settings.

    Input locations are provenance, not identity. Frozen input identity is
    enforced separately by SHA256, so moving the same baseline files from
    outputs/ into evidence/ must not create a false mismatch.
    """
    contract = dict(manifest.get("experiment_contract") or {})
    for key in EXPERIMENT_LOCATION_KEYS:
        contract.pop(key, None)
    return contract


def compare_values(path: str, expected: Any, actual: Any, diffs: list[str]) -> None:
    if expected != actual:
        diffs.append(f"{path}: baseline={expected!r} current={actual!r}")


def compare_manifest(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    diffs: list[str] = []
    compare_values(
        "schema_version",
        baseline.get("schema_version"),
        current.get("schema_version"),
        diffs,
    )
    compare_values(
        "experiment_contract",
        semantic_experiment_contract(baseline),
        semantic_experiment_contract(current),
        diffs,
    )
    for key in (
        "risk_off_config",
        "risk_on_config",
        "tuner_param_space",
        "watchlist",
        "watchlist_history",
    ):
        compare_values(
            f"inputs.{key}.sha256",
            baseline["inputs"][key]["sha256"],
            current["inputs"][key]["sha256"],
            diffs,
        )

    for style in ("risk_off", "risk_on"):
        b = baseline["runs"][style]
        a = current["runs"][style]
        compare_values(
            f"runs.{style}.deterministic_sha256",
            b["deterministic_sha256"],
            a["deterministic_sha256"],
            diffs,
        )
        compare_values(
            f"runs.{style}.summary_contract",
            b["summary_contract"],
            a["summary_contract"],
            diffs,
        )
        compare_values(
            f"runs.{style}.signals_contract",
            b["signals_contract"],
            a["signals_contract"],
            diffs,
        )

    b_tune = baseline.get("tuning_smoke")
    a_tune = current.get("tuning_smoke")
    if (b_tune is None) != (a_tune is None):
        diffs.append("tuning_smoke: present in only one manifest")
    elif b_tune is not None and a_tune is not None:
        for key in (
            "deterministic_sha256",
            "selection_mode",
            "candidate_count",
            "picks",
            "walk_forward",
            "result_columns",
            "result_rows",
        ):
            compare_values(
                f"tuning_smoke.{key}",
                b_tune.get(key),
                a_tune.get(key),
                diffs,
            )
    return diffs


def common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo-root", default=".")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--risk-off-prefix", required=True)
    p.add_argument("--risk-on-prefix", required=True)
    p.add_argument("--tuning-prefix", default=None)
    p.add_argument("--risk-off-config", default="configs/config.risk_off.json")
    p.add_argument("--risk-on-config", default="configs/config.risk_on.json")
    p.add_argument("--param-space", default="configs/tuner.param_space.json")
    p.add_argument("--watchlist", default="data/ai_watchlist.csv")
    p.add_argument(
        "--watchlist-history-dir",
        default="data/watchlist_history",
        help="Frozen PIT watchlist-history directory used by the baseline experiments.",
    )
    p.add_argument("--replay-start", default="2023-01-01")
    p.add_argument("--replay-end", default="2026-03-31")
    p.add_argument("--rebalance-frequency", default="monthly")
    clean = p.add_mutually_exclusive_group()
    clean.add_argument("--require-clean", action="store_true", default=True)
    clean.add_argument("--allow-dirty", action="store_false", dest="require_clean")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Capture/compare fixed post-correctness baseline artifacts for E01."
    )
    subs = p.add_subparsers(dest="command", required=True)

    capture = subs.add_parser("capture")
    common_args(capture)
    capture.add_argument("--baseline-id", required=True)
    capture.add_argument("--output", required=True)

    compare = subs.add_parser("compare")
    common_args(compare)
    compare.add_argument("--baseline", required=True)

    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "capture":
        manifest = capture_manifest(args)
        output = Path(args.output)
        write_manifest(output, manifest)
        print(f"baseline manifest: {output}")
        print(f"git commit: {manifest['git']['commit']}")
        print("capture complete; no production config was modified")
        return

    baseline = json_payload(Path(args.baseline))
    current_args = argparse.Namespace(
        **vars(args),
        baseline_id=baseline.get("baseline_id", "comparison"),
    )
    current = capture_manifest(current_args)
    diffs = compare_manifest(baseline, current)
    if diffs:
        print("BASELINE_MISMATCH")
        for diff in diffs:
            print(f"- {diff}")
        raise SystemExit(1)
    print("BASELINE_MATCH")
    print("deterministic artifacts, summary contracts, signals, inputs and tuner smoke match")


if __name__ == "__main__":
    main()
