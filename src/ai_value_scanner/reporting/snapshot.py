from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ai_value_scanner.decision.model import (
    DECISION_SCHEMA_VERSION,
    StockDecision,
    stock_decisions_from_jsonl,
    stock_decisions_to_jsonl,
)
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)


@dataclass(frozen=True)
class DecisionSnapshotPaths:
    root: Path
    decisions_jsonl: Path
    action_list_md: Path
    weekly_review_md: Path
    detailed_dir: Path
    run_manifest_json: Path


def _safe_style(style: str | None) -> str:
    token = str(style or "default").strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in token)
    return cleaned or "default"


def decision_snapshot_paths(
    output_root: str | Path,
    decision_date: str | date,
    *,
    strategy_style: str | None,
) -> DecisionSnapshotPaths:
    day = decision_date.isoformat() if isinstance(decision_date, date) else str(decision_date)
    root = Path(output_root) / day / _safe_style(strategy_style)
    return DecisionSnapshotPaths(
        root=root,
        decisions_jsonl=root / "decisions.jsonl",
        action_list_md=root / "action_list.md",
        weekly_review_md=root / "weekly_review.md",
        detailed_dir=root / "detailed",
        run_manifest_json=root / "run_manifest.json",
    )


def resolve_git_commit_sha() -> str | None:
    for key in ("GITHUB_SHA", "SOURCE_VERSION", "COMMIT_SHA"):
        value = os.getenv(key)
        if value:
            return str(value)
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = proc.stdout.strip()
    return token or None


def _counts(
    decisions: Iterable[StockDecision],
    attr: str,
) -> dict[str, int]:
    values: list[str] = []
    for decision in decisions:
        if attr == "quality":
            values.append(decision.quality.grade.value)
        elif attr == "entry":
            values.append(decision.entry.state.value)
        elif attr == "action":
            values.append(decision.action_state.value)
        else:
            raise ValueError(f"unsupported count attribute: {attr}")
    return dict(sorted(Counter(values).items()))


def build_run_manifest(
    *,
    decisions: Iterable[StockDecision],
    daily_attention: Iterable[StockDecision],
    weekly_attention: Iterable[StockDecision],
    generated_at_utc: str,
    decision_date: str,
    strategy_style: str | None,
    config_fingerprint: str,
    code_sha: str | None,
    input_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    materialized = tuple(decisions)
    daily = tuple(daily_attention)
    weekly = tuple(weekly_attention)
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "generated_at_utc": str(generated_at_utc),
        "decision_date": str(decision_date),
        "strategy_style": strategy_style,
        "code_sha": code_sha,
        "config_fingerprint": str(config_fingerprint),
        "counts": {
            "decisions": len(materialized),
            "daily_attention": len(daily),
            "weekly_attention": len(weekly),
            "quality": _counts(materialized, "quality"),
            "entry": _counts(materialized, "entry"),
            "action": _counts(materialized, "action"),
        },
        "daily_symbols": [decision.symbol for decision in daily],
        "weekly_symbols": [decision.symbol for decision in weekly],
        "input_provenance": dict(input_provenance or {}),
    }


def write_decision_snapshot(
    *,
    output_root: str | Path,
    strategy_style: str | None,
    decisions: Iterable[StockDecision],
    daily_attention: Iterable[StockDecision],
    weekly_attention: Iterable[StockDecision],
    generated_at_utc: str,
    decision_date: str,
    config_fingerprint: str,
    code_sha: str | None = None,
    input_provenance: Mapping[str, Any] | None = None,
) -> DecisionSnapshotPaths:
    """Write an immutable prospective snapshot with derived Markdown views.

    The date/style directory is never overwritten. A second run for the same
    decision date/style must choose a different output root or leave the first
    prospective snapshot intact.
    """
    decisions_tuple = tuple(decisions)
    daily_tuple = tuple(daily_attention)
    weekly_tuple = tuple(weekly_attention)
    paths = decision_snapshot_paths(
        output_root,
        decision_date,
        strategy_style=strategy_style,
    )
    if paths.root.exists():
        raise FileExistsError(
            f"immutable decision snapshot already exists: {paths.root}"
        )

    parent = paths.root.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_root = parent / f".{paths.root.name}.{os.getpid()}.tmp"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=False)

    try:
        detailed_dir = tmp_root / "detailed"
        detailed_dir.mkdir(parents=True, exist_ok=False)

        (tmp_root / "decisions.jsonl").write_text(
            stock_decisions_to_jsonl(decisions_tuple),
            encoding="utf-8",
        )
        (tmp_root / "action_list.md").write_text(
            render_action_list(
                daily_tuple,
                title="Daily Action List",
                cadence="daily",
            ),
            encoding="utf-8",
        )
        (tmp_root / "weekly_review.md").write_text(
            render_action_list(
                weekly_tuple,
                title="Weekly Review List",
                cadence="weekly",
            ),
            encoding="utf-8",
        )

        detailed_symbols = {
            decision.symbol: decision
            for decision in (*weekly_tuple, *daily_tuple)
        }
        for symbol in sorted(detailed_symbols):
            (detailed_dir / f"{symbol}.md").write_text(
                render_detailed_report(detailed_symbols[symbol]),
                encoding="utf-8",
            )

        manifest = build_run_manifest(
            decisions=decisions_tuple,
            daily_attention=daily_tuple,
            weekly_attention=weekly_tuple,
            generated_at_utc=generated_at_utc,
            decision_date=decision_date,
            strategy_style=strategy_style,
            config_fingerprint=config_fingerprint,
            code_sha=code_sha,
            input_provenance=input_provenance,
        )
        (tmp_root / "run_manifest.json").write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(tmp_root, paths.root)
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise

    return paths


def load_snapshot_decisions(path: str | Path) -> tuple[StockDecision, ...]:
    target = Path(path)
    if target.is_dir():
        target = target / "decisions.jsonl"
    if not target.exists():
        return ()
    return stock_decisions_from_jsonl(target.read_text(encoding="utf-8"))


def load_previous_snapshot(
    output_root: str | Path,
    decision_date: str | date,
    *,
    strategy_style: str | None,
) -> tuple[StockDecision, ...]:
    current = decision_date.isoformat() if isinstance(decision_date, date) else str(decision_date)
    root = Path(output_root)
    if not root.exists():
        return ()

    style = _safe_style(strategy_style)
    candidates: list[tuple[str, Path]] = []
    for day_dir in root.iterdir():
        if not day_dir.is_dir():
            continue
        day = day_dir.name
        if day >= current:
            continue
        decisions_path = day_dir / style / "decisions.jsonl"
        if decisions_path.exists():
            candidates.append((day, decisions_path))
    if not candidates:
        return ()

    _, latest = max(candidates, key=lambda item: item[0])
    return load_snapshot_decisions(latest)
