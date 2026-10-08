#!/usr/bin/env python3
"""Run strategy selection offline against frozen feature snapshots.

This is the fast refactor gate for strategy/scoring work. Snapshot creation is
the expensive step and should be done once from a frozen cache. Old/new code
then consumes the identical CSV bundle without SEC, Alpaca, PIT reconstruction
or price-history work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import ai_value_scanner.backtest as backtest
from ai_value_scanner.config import load_config
from ai_value_scanner.validation.snapshots import (
    load_feature_snapshot,
    load_snapshot_manifest,
)


SCHEMA_VERSION = 1
DEFAULT_LIST_TYPES = ("low_value", "industry_trend", "momentum", "research_pool")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return round(value, 12)
    return value


def parse_csv(raw: str | None, default: tuple[str, ...] = ()) -> list[str]:
    if not raw:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_gate_result(
    *,
    snapshot_dir: Path,
    scan_config_path: Path,
    list_types: list[str],
    top_n: int,
    per_channel_top_n: bool,
    include_channels: list[str],
) -> dict[str, Any]:
    manifest = load_snapshot_manifest(snapshot_dir)
    config = load_config(scan_config_path)
    style = str(config.strategy_style)

    records = [
        record
        for record in manifest.get("snapshots", [])
        if str(record.get("style")) == style
    ]
    if not records:
        raise ValueError(
            f"snapshot bundle contains no records for strategy_style={style!r}"
        )

    results: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: item["key"]):
        frame = load_feature_snapshot(snapshot_dir / record["path"])
        for list_type in list_types:
            selected, diagnostics = backtest.rank_and_pick_symbols_with_diagnostics(
                df=frame.copy(),
                scan_config=config,
                list_type=list_type,
                top_n=int(top_n),
                per_channel_top_n=bool(per_channel_top_n),
                include_channels=include_channels,
            )
            normalized_diagnostics = jsonable(diagnostics)
            results.append(
                {
                    "snapshot_key": record["key"],
                    "list_type": list_type,
                    "selected_symbols": [str(symbol) for symbol in selected],
                    "n_selected": len(selected),
                    "channel_counts": normalized_diagnostics.get("channel_counts", {}),
                    "diagnostics_sha256": canonical_hash(normalized_diagnostics),
                    "diagnostics": normalized_diagnostics,
                }
            )

    result_hash = canonical_hash(results)
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "offline strategy gate over frozen pre-strategy feature snapshots",
        "snapshot_bundle_sha256": manifest.get("bundle_sha256"),
        "snapshot_schema_version": manifest.get("schema_version"),
        "scan_config_path": str(scan_config_path),
        "scan_config_sha256": sha256_file(scan_config_path),
        "strategy_style": style,
        "parameters": {
            "list_types": list_types,
            "top_n": int(top_n),
            "per_channel_top_n": bool(per_channel_top_n),
            "include_channels": include_channels,
        },
        "result_sha256": result_hash,
        "results": results,
    }


def compare_gate_results(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    diffs: list[str] = []
    for key in (
        "schema_version",
        "snapshot_bundle_sha256",
        "snapshot_schema_version",
        "scan_config_sha256",
        "strategy_style",
        "parameters",
        "result_sha256",
    ):
        if baseline.get(key) != current.get(key):
            diffs.append(
                f"{key}: baseline={baseline.get(key)!r} current={current.get(key)!r}"
            )
    if baseline.get("results") != current.get("results"):
        diffs.append("results differ")
    return diffs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run/compare strategy outputs using frozen feature snapshots."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--snapshot-dir", required=True)
    run.add_argument("--scan-config", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--list-types", default=",".join(DEFAULT_LIST_TYPES))
    run.add_argument("--top-n", type=int, default=10)
    run.add_argument(
        "--include-channels",
        default="core_ai,ai_enabler,ai_peripheral",
    )
    run.add_argument("--per-channel-top-n", action="store_true", default=True)
    run.add_argument("--global-top-n", action="store_false", dest="per_channel_top_n")

    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--current", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        result = build_gate_result(
            snapshot_dir=Path(args.snapshot_dir),
            scan_config_path=Path(args.scan_config),
            list_types=parse_csv(args.list_types, DEFAULT_LIST_TYPES),
            top_n=args.top_n,
            per_channel_top_n=args.per_channel_top_n,
            include_channels=parse_csv(args.include_channels),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"FAST_GATE_RESULT {result['result_sha256']}")
        print(f"output: {output}")
        return

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    diffs = compare_gate_results(baseline, current)
    if diffs:
        print("FAST_GATE_MISMATCH")
        for diff in diffs:
            print(f"- {diff}")
        raise SystemExit(1)
    print("FAST_GATE_MATCH")


if __name__ == "__main__":
    main()
