from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
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
from ai_value_scanner.decision.view_model import build_snapshot_view_model
from ai_value_scanner.fundamentals.provenance import (
    canonical_json_bytes,
    sha256_hex,
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
    universe_exclusions_jsonl: Path
    discovery_memberships_jsonl: Path
    discovery_source_rejections_jsonl: Path
    discovery_source_inputs_dir: Path
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
        universe_exclusions_jsonl=root / "universe_exclusions.jsonl",
        discovery_memberships_jsonl=root / "discovery_memberships.jsonl",
        discovery_source_rejections_jsonl=root / "discovery_source_rejections.jsonl",
        discovery_source_inputs_dir=root / "discovery_source_inputs",
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


def _mappings_to_jsonl(rows: Iterable[Mapping[str, Any]]) -> str:
    materialized = sorted(
        (dict(row) for row in rows),
        key=lambda row: str(row.get("symbol") or ""),
    )
    if not materialized:
        return ""
    return "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True)
        for row in materialized
    ) + "\n"


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
    candidate_universe_summary: Mapping[str, Any] | None = None,
    discovery_source_summary: Mapping[str, Any] | None = None,
    policy_version: str = "v1",
    layout_version: str = "v1",
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
        **(
            {
                "decision_policy_version": str(policy_version),
                "report_layout_version": str(layout_version),
            }
            if (policy_version != "v1" or layout_version != "v1")
            else {}
        ),
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
        **(
            {"candidate_universe": dict(candidate_universe_summary)}
            if candidate_universe_summary is not None
            else {}
        ),
        **(
            {"discovery_sources": dict(discovery_source_summary)}
            if discovery_source_summary is not None
            else {}
        ),
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
    universe_exclusions: Iterable[Mapping[str, Any]] = (),
    candidate_universe_summary: Mapping[str, Any] | None = None,
    discovery_memberships: Iterable[Mapping[str, Any]] = (),
    discovery_source_rejections: Iterable[Mapping[str, Any]] = (),
    discovery_source_summary: Mapping[str, Any] | None = None,
    ticker_map_rows: Iterable[Mapping[str, Any]] | None = None,
    policy_version: str = "v1",
    layout_version: str = "v1",
) -> DecisionSnapshotPaths:
    """Write an immutable prospective snapshot with derived Markdown views.

    The date/style directory is never overwritten. A second run for the same
    decision date/style must choose a different output root or leave the first
    prospective snapshot intact.

    ``ticker_map_rows`` (optional symbol/cik/company_name records) freezes
    the exact ticker->CIK rows behind the run: the file content is the
    canonical serialization, so its SHA doubles as the content checksum
    recorded in the manifest. Additive only; existing callers unaffected.
    """
    decisions_tuple = tuple(decisions)
    daily_tuple = tuple(daily_attention)
    weekly_tuple = tuple(weekly_attention)
    universe_exclusions_tuple = tuple(dict(row) for row in universe_exclusions)
    discovery_memberships_tuple = tuple(dict(row) for row in discovery_memberships)
    discovery_rejections_tuple = tuple(dict(row) for row in discovery_source_rejections)
    if discovery_source_summary is None and (discovery_memberships_tuple or discovery_rejections_tuple):
        raise ValueError("discovery records require a discovery_source_summary")
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
                layout_version=layout_version,
                all_decisions=decisions_tuple,
            ),
            encoding="utf-8",
        )
        (tmp_root / "weekly_review.md").write_text(
            render_action_list(
                weekly_tuple,
                title="Weekly Review List",
                cadence="weekly",
                layout_version=layout_version,
                all_decisions=decisions_tuple,
            ),
            encoding="utf-8",
        )
        (tmp_root / "universe_exclusions.jsonl").write_text(
            _mappings_to_jsonl(universe_exclusions_tuple),
            encoding="utf-8",
        )

        if discovery_source_summary is not None:
            frozen_inputs = tmp_root / "discovery_source_inputs"
            frozen_inputs.mkdir()
            for item in discovery_source_summary["source_files"]:
                kind = item["source_kind"]
                if kind not in {"us_core", "thematic", "manual"}:
                    raise ValueError("unexpected discovery source kind")
                raw_bytes = Path(item["source_file"]).read_bytes()
                if hashlib.sha256(raw_bytes).hexdigest() != item["sha256"]:
                    raise ValueError("discovery source changed since scan: " + str(kind))
                (frozen_inputs / (kind + ".csv")).write_bytes(raw_bytes)
            (tmp_root / "discovery_memberships.jsonl").write_text(
                _mappings_to_jsonl(discovery_memberships_tuple), encoding="utf-8"
            )
            (tmp_root / "discovery_source_rejections.jsonl").write_text(
                _mappings_to_jsonl(discovery_rejections_tuple), encoding="utf-8"
            )

        detailed_symbols = {
            decision.symbol: decision
            for decision in (*weekly_tuple, *daily_tuple)
        }
        if layout_version == "v2":
            # Secondary Radar links need their detailed reports generated too.
            by_symbol_all = {decision.symbol: decision for decision in decisions_tuple}
            for view_decisions, cadence in ((daily_tuple, "daily"), (weekly_tuple, "weekly")):
                view = build_snapshot_view_model(
                    view_decisions,
                    decisions_tuple,
                    title="Daily Action List" if cadence == "daily" else "Weekly Review List",
                    cadence=cadence,
                )
                for card in (
                    *view.cap_omitted_priority_cards,
                    *view.secondary_b_ready_cards,
                ):
                    if card.symbol in by_symbol_all:
                        detailed_symbols.setdefault(card.symbol, by_symbol_all[card.symbol])
        for symbol in sorted(detailed_symbols):
            (detailed_dir / f"{symbol}.md").write_text(
                render_detailed_report(
                    detailed_symbols[symbol],
                    layout_version=layout_version,
                ),
                encoding="utf-8",
            )

        ticker_map_rows_manifest: dict[str, Any] = {}
        if ticker_map_rows is not None:
            frozen_rows = [
                {"symbol": str(row.get("symbol") or "").strip().upper(),
                 "cik": str(row.get("cik") or "").strip(),
                 "company_name": str(row.get("company_name") or "").strip()}
                for row in ticker_map_rows
            ]
            frozen_rows.sort(key=lambda item: (item["symbol"], item["cik"]))
            rows_bytes = canonical_json_bytes(frozen_rows)
            (tmp_root / "ticker_map_rows.json").write_bytes(rows_bytes)
            ticker_map_rows_manifest = {
                "ticker_map_rows_file": "ticker_map_rows.json",
                "ticker_map_rows_sha256": sha256_hex(rows_bytes),
                "ticker_map_rows_count": len(frozen_rows),
            }

        manifest = build_run_manifest(
            decisions=decisions_tuple,
            daily_attention=daily_tuple,
            weekly_attention=weekly_tuple,
            generated_at_utc=generated_at_utc,
            decision_date=decision_date,
            strategy_style=strategy_style,
            config_fingerprint=config_fingerprint,
            code_sha=code_sha,
            input_provenance={
                **dict(input_provenance or {}),
                **ticker_map_rows_manifest,
            },
            candidate_universe_summary=candidate_universe_summary,
            discovery_source_summary=discovery_source_summary,
            policy_version=policy_version,
            layout_version=layout_version,
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
