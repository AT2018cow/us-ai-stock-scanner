"""Read-side publication evidence for official decision lists."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..market_data import sip_publication_window
from ..validation.decision_snapshot import require_valid_snapshot
from .snapshot import (
    decision_snapshot_paths,
    load_snapshot_decisions,
    snapshot_identity,
    snapshot_missing_files,
)


def read_latest_publication(root: Path, style: str, *, require_sip: bool = True) -> dict[str, Any]:
    pointer = json.loads((root / f"latest_{style}.json").read_text(encoding="utf-8"))
    if not isinstance(pointer, dict):
        raise ValueError("latest pointer must be a JSON object")
    day = date.fromisoformat(str(pointer.get("decision_date")))
    paths = decision_snapshot_paths(root, day.isoformat(), strategy_style=style)
    rel_dir = paths.root.relative_to(root).as_posix()
    if pointer.get("snapshot_dir") != rel_dir or not paths.root.resolve().is_relative_to(root.resolve()):
        raise ValueError("latest pointer does not resolve to the expected session and style directory")
    for field, name in (
        ("action_list_md", "action_list.md"),
        ("weekly_review_md", "weekly_review.md"),
        ("run_manifest_json", "run_manifest.json"),
    ):
        if pointer.get(field) != f"{rel_dir}/{name}":
            raise ValueError(f"latest pointer has an invalid {field}")
    if missing := snapshot_missing_files(paths.root):
        raise ValueError("latest snapshot is incomplete: " + ", ".join(missing))
    manifest_bytes = paths.run_manifest_json.read_bytes()
    manifest_hash = sha256(manifest_bytes).hexdigest()
    if "manifest_sha256" in pointer and pointer["manifest_sha256"] != manifest_hash:
        raise ValueError("latest manifest SHA256 differs from the publication pointer")
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("latest snapshot manifest must be a JSON object")
    if "decisions_sha256" in pointer and pointer["decisions_sha256"] != manifest.get("decisions_sha256"):
        raise ValueError("decision digest differs from the publication pointer")
    identity = snapshot_identity(manifest)
    if (identity["decision_date"], identity["strategy_style"] or "default") != (day.isoformat(), style):
        raise ValueError("latest pointer and manifest identity differ")
    if any(
        pointer.get(key) != value
        for key, value in (
            ("strategy_style", identity["strategy_style"]),
            ("decision_policy_version", identity["policy_version"]),
            ("report_layout_version", identity["layout_version"]),
            ("quality_policy_version", identity["quality_policy_version"]),
            ("entry_policy_version", identity["entry_policy_version"]),
        )
    ):
        raise ValueError("latest pointer and manifest policy or style differ")
    first_readable = pointer.get("first_readable_at_utc")
    if first_readable is not None and datetime.fromisoformat(str(first_readable)).utcoffset() is None:
        raise ValueError("first publication time must include its timezone")
    if require_sip:
        provenance = manifest.get("input_provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("market_data_mode") != "sip_eod"
            or provenance.get("market_data_feed") != "sip"
        ):
            raise ValueError("latest snapshot lacks SIP end-of-day provenance")

    # The cap is configurable at scan time. Readback validates the entire
    # archived lists, including Markdown links and the canonical detail pages.
    selected_counts = []
    for key in ("daily_symbols", "weekly_symbols"):
        selected = manifest.get(key, [])
        if not isinstance(selected, list) or any(not isinstance(symbol, str) for symbol in selected):
            raise ValueError(f"invalid latest manifest {key}")
        selected_counts.append(len(selected))
    require_valid_snapshot(paths.root, attention_cap=max(1, *selected_counts))
    if require_sip and any(
        decision.provenance.get("market_data_mode") != "sip_eod"
        or decision.provenance.get("market_data_feed") != "sip"
        for decision in load_snapshot_decisions(paths.root)
    ):
        raise ValueError("latest decisions lack consistent SIP end-of-day provenance")
    return {
        **pointer,
        "manifest_sha256": manifest_hash,
        "code_sha": manifest.get("code_sha"),
        "config_fingerprint": manifest.get("config_fingerprint"),
        "report_renderer_revision": manifest.get("report_renderer_revision"),
    }


def write_publication_attempt(path: Path, receipt: dict[str, Any]) -> None:
    """Atomically keep the running or completed receipt for one attempt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp = Path(handle.name)
        try:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.close()
            temp.chmod(path.parent.stat().st_mode & 0o666)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def latest_list_status(root: Path, style: str, now_utc: datetime) -> dict[str, Any]:
    expected, window = sip_publication_window(now_utc)
    expected_session = expected.isoformat()
    status: dict[str, Any] = {
        "expected_session": expected_session,
        "published_session": None,
        "first_readable_at_utc": None,
        "status": "awaiting_sip" if window == "awaiting_sip" else "overdue",
        "reason_code": "missing_latest_pointer",
        "publication": None,
    }
    if (root / f"latest_{style}.json").exists():
        try:
            publication = read_latest_publication(root, style)
            published = publication["decision_date"]
            if published > expected_session:
                raise ValueError("latest session is in the future")
        except (OSError, ValueError) as exc:
            return {**status, "status": "invalid", "reason_code": "invalid_latest", "error": str(exc)}
        status.update(
            published_session=published,
            first_readable_at_utc=publication.get("first_readable_at_utc"),
            reason_code="older_session",
            publication=publication,
        )
        if published == expected_session:
            return {**status, "status": "current", "reason_code": None}

    if window == "awaiting_sip":
        return {**status, "reason_code": "sip_delay"}
    attempts = root / "publication_attempts" / style / "formal"
    latest = max(attempts.glob("*.json"), default=None)
    if latest is not None:
        try:
            attempt = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {**status, "reason_code": "unreadable_attempt_receipt"}
        if isinstance(attempt, dict) and attempt.get("expected_session") == expected_session:
            if attempt.get("status") == "failed":
                return {**status, "status": "failed", "reason_code": attempt.get("reason_code")}
            if attempt.get("status") == "running":
                return {**status, "reason_code": "unfinished_publication_attempt"}
    return status


def format_list_status(status: dict[str, Any]) -> str:
    return (
        f"{status['status']} · expected={status['expected_session']} "
        f"published={status['published_session'] or 'unknown'} "
        f"first_readable={status['first_readable_at_utc'] or 'unknown'}"
        + (f" · {status['reason_code']}" if status.get("reason_code") else "")
    )
