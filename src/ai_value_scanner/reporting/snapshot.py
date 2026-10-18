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

from ai_value_scanner.decision.attention import (
    DEFAULT_ATTENTION_CAP,
    STATE_CHANGE_ALERTS_POLICY_VERSION,
    select_state_change_alerts,
)
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


# Writer revision marker (R05): snapshots written from this revision onward can
# be byte-verified by the validator; older snapshots are validated structurally
# with an explicit warning instead of pretending their stored files match the
# current renderer.
REPORT_RENDERER_REVISION = "mvp_report_renderer_2026-10-18"


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
    state_change_alerts_summary: Mapping[str, Any] | None = None,
    policy_version: str = "v1",
    layout_version: str = "v1",
) -> dict[str, Any]:
    materialized = tuple(decisions)
    daily = tuple(daily_attention)
    weekly = tuple(weekly_attention)
    stage_quality_versions = {
        str(decision.provenance["quality_policy_version"])
        for decision in materialized
        if decision.provenance.get("quality_policy_version")
    }
    stage_entry_versions = {
        str(decision.provenance["entry_policy_version"])
        for decision in materialized
        if decision.provenance.get("entry_policy_version")
    }
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "generated_at_utc": str(generated_at_utc),
        "decision_date": str(decision_date),
        "strategy_style": strategy_style,
        "code_sha": code_sha,
        "config_fingerprint": str(config_fingerprint),
        "report_renderer_revision": REPORT_RENDERER_REVISION,
        **(
            {
                "decision_policy_version": str(policy_version),
                "report_layout_version": str(layout_version),
            }
            if (policy_version != "v1" or layout_version != "v1")
            else {}
        ),
        **(
            {"quality_policy_version": next(iter(stage_quality_versions))}
            if len(stage_quality_versions) == 1
            else {}
        ),
        **(
            {"entry_policy_version": next(iter(stage_entry_versions))}
            if len(stage_entry_versions) == 1
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
        **(
            {"state_change_alerts": dict(state_change_alerts_summary)}
            if state_change_alerts_summary is not None
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

        alert_rows, alert_summary = build_state_change_alert_records(
            daily=daily_tuple,
            weekly=weekly_tuple,
            decisions=decisions_tuple,
        )
        (tmp_root / "state_change_alerts.jsonl").write_text(
            _mappings_to_jsonl(alert_rows),
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
            # Radar / offense / alert cards link detailed reports too.
            by_symbol_all = {decision.symbol: decision for decision in decisions_tuple}
            for symbol in collect_detailed_report_symbols(
                daily=daily_tuple,
                weekly=weekly_tuple,
                decisions=decisions_tuple,
                layout_version=layout_version,
            ):
                if symbol in by_symbol_all:
                    detailed_symbols.setdefault(symbol, by_symbol_all[symbol])
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
            state_change_alerts_summary=alert_summary,
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


def load_snapshot_manifest(root: str | Path) -> dict[str, Any]:
    """Load and validate the manifest of an existing snapshot (R08).

    Raises ``FileNotFoundError`` when absent and ``ValueError`` when the
    manifest is unreadable or not a JSON object.
    """
    manifest_path = Path(root) / "run_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"snapshot manifest is missing: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"snapshot manifest is unreadable: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError("snapshot manifest must be a JSON object")
    return payload


REQUIRED_SNAPSHOT_FILES = (
    "decisions.jsonl",
    "action_list.md",
    "weekly_review.md",
    "run_manifest.json",
)


def snapshot_missing_files(root: str | Path) -> list[str]:
    root_path = Path(root)
    return [
        name for name in REQUIRED_SNAPSHOT_FILES if not (root_path / name).is_file()
    ]


def snapshot_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Identity recorded by the writer, with explicit v1 defaults (R05/R08)."""
    return {
        "decision_date": str(manifest.get("decision_date") or ""),
        "strategy_style": manifest.get("strategy_style"),
        "policy_version": str(manifest.get("decision_policy_version", "v1")),
        "layout_version": str(manifest.get("report_layout_version", "v1")),
        "quality_policy_version": manifest.get("quality_policy_version"),
        "entry_policy_version": manifest.get("entry_policy_version"),
    }


def collect_detailed_report_symbols(
    *,
    daily: Iterable[StockDecision],
    weekly: Iterable[StockDecision],
    decisions: Iterable[StockDecision],
    layout_version: str,
) -> set[str]:
    """All symbols whose detailed page is linked from the snapshot reports.

    Shared by the writer and the validator so the report link surface can
    never drift: primary daily/weekly names plus (v2 layouts) the Secondary
    Radar, Offense Track, and state-change alert cards.
    """
    daily_tuple = tuple(daily)
    weekly_tuple = tuple(weekly)
    decisions_tuple = tuple(decisions)
    symbols = {decision.symbol for decision in (*weekly_tuple, *daily_tuple)}
    if layout_version != "v2":
        return symbols
    by_symbol = {decision.symbol: decision for decision in decisions_tuple}
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
            *view.growth_compounder_offense_cards,
            *view.state_change_alert_cards,
        ):
            if card.symbol in by_symbol:
                symbols.add(card.symbol)
    return symbols


def build_state_change_alert_records(
    *,
    daily: Iterable[StockDecision],
    weekly: Iterable[StockDecision],
    decisions: Iterable[StockDecision],
    cap: int = DEFAULT_ATTENTION_CAP,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Canonical downgrade-alert selection shared by writer and validator (R07).

    Returns ``(rows, manifest_summary)``: one JSONL-ready record per alert
    symbol (with the scopes where it is shown) and the manifest summary with
    per-scope totals/truncation for auditability.
    """
    daily_tuple = tuple(daily)
    weekly_tuple = tuple(weekly)
    decisions_tuple = tuple(decisions)
    daily_selection = select_state_change_alerts(
        decisions_tuple,
        exclude_symbols={decision.symbol for decision in daily_tuple},
        cap=cap,
    )
    weekly_selection = select_state_change_alerts(
        decisions_tuple,
        exclude_symbols={decision.symbol for decision in weekly_tuple},
        cap=cap,
    )
    rows_by_symbol: dict[str, dict[str, Any]] = {}
    for scope, selection in (("daily", daily_selection), ("weekly", weekly_selection)):
        for decision in selection.alerts:
            row = rows_by_symbol.setdefault(
                decision.symbol,
                {
                    "symbol": decision.symbol,
                    "previous_action_state": (
                        None
                        if decision.previous_action_state is None
                        else decision.previous_action_state.value
                    ),
                    "action_state": decision.action_state.value,
                    "state_change_reason": decision.state_change_reason,
                    "display_scopes": [],
                },
            )
            row["display_scopes"].append(scope)
    rows = sorted(rows_by_symbol.values(), key=lambda row: str(row["symbol"]))
    summary = {
        "policy": STATE_CHANGE_ALERTS_POLICY_VERSION,
        "daily": {
            "total": daily_selection.total,
            "shown_symbols": [d.symbol for d in daily_selection.alerts],
            "truncated": daily_selection.truncated,
        },
        "weekly": {
            "total": weekly_selection.total,
            "shown_symbols": [d.symbol for d in weekly_selection.alerts],
            "truncated": weekly_selection.truncated,
        },
    }
    return rows, summary


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
