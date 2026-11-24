"""Append-only local evidence keyed to immutable SIP publication artifacts."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any

from ai_value_scanner.decision.attention import DAILY_ATTENTION_STABILITY_POLICY_VERSION, is_soft_exit_grace_eligible
from ai_value_scanner.decision.model import ActionState, stock_decisions_from_jsonl
from ai_value_scanner.decision.review import issuer_cik
from ai_value_scanner.market_data import SIP_PUBLICATION_DELAY
from ai_value_scanner.market_calendar import NYSE_TZ, is_session_day, session_close_utc
from ai_value_scanner.reporting.snapshot import snapshot_identity
from ai_value_scanner.validation.decision_snapshot import require_valid_snapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    parent TEXT REFERENCES evidence(id),
    recorded_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_group ON evidence(kind, parent);
CREATE UNIQUE INDEX IF NOT EXISTS snapshot_session ON evidence(
    json_extract(payload, '$.style'), json_extract(payload, '$.session')
) WHERE kind = 'snapshot';
CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT, 'forward evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'forward evidence is append-only'); END;
"""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def evidence_id(kind: str, *parts: Any) -> str:
    return kind + ":" + sha256(canonical(parts).encode()).hexdigest()


def utc(value: str | datetime) -> datetime:
    if isinstance(value, str) and value.endswith("Z"):
        value = value[:-1] + "+00:00"
    declared = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if declared.utcoffset() is None:
        raise ValueError("timestamps require a timezone")
    return declared.astimezone(timezone.utc)


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value.strip()


def number(value: Any, field: str, *, minimum: float = 0, maximum: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} is out of range")
    return float(value)


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def publication_day(value: str) -> date:
    day = date.fromisoformat(value)
    if day.isoformat() != value or not is_session_day(day):
        raise ValueError(f"not a NYSE session: {value}")
    return day


class Ledger:
    def __init__(self, path: Path, *, snapshot_root: Path) -> None:
        self.path = path.resolve()
        self.root = snapshot_root.resolve()
        if self.path.is_relative_to(self.root):
            raise ValueError("the ledger must be outside the decision archive")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def records(self, kind: str | None = None, *, parent: str | None = None) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            return entries(db, kind, parent=parent)

    def import_attempt(self, receipt: Mapping[str, Any], *, now: datetime | None = None) -> str:
        recorded = utc(now or datetime.now(timezone.utc))
        if receipt.get("schema_version") != 1 or receipt.get("mode") != "formal":
            raise ValueError("expected a version 1 formal publication receipt")
        run_id = text(receipt.get("run_id"), "run_id")
        style = text(receipt.get("strategy_style"), "strategy_style")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", style) or style in {".", ".."}:
            raise ValueError("invalid strategy style")
        day = publication_day(receipt["expected_session"])
        started = utc(receipt["started_at_utc"])
        finished = utc(receipt["finished_at_utc"])
        if not started <= finished <= recorded:
            raise ValueError("receipt timestamps are out of order")
        status = receipt.get("status")
        proof = None
        destination = None
        first_readable = None
        if status in {"published", "reused"}:
            proof = receipt["publication"]
            if receipt["published_session"] != day.isoformat() or proof["decision_date"] != day.isoformat():
                raise ValueError("receipt session differs from the archived publication")
            relative = f"{day}/{style}"
            if proof.get("snapshot_dir") != relative or (proof.get("strategy_style") or "default") != style:
                raise ValueError("receipt does not identify the expected archive")
            destination = self.root / relative
            first_readable = proof.get("first_readable_at_utc")
            if first_readable is not None:
                first_readable = utc(first_readable)
                if not session_close_utc(day) + SIP_PUBLICATION_DELAY <= first_readable <= finished:
                    raise ValueError("invalid first-readable time")
        elif status not in {"failed", "deferred"}:
            raise ValueError("receipt is not a completed formal attempt")

        attempt_id = evidence_id("receipt", style, run_id)
        payload = {
            "run_id": run_id, "style": style, "session": day.isoformat(),
            "status": status, "started_at_utc": started.isoformat(),
            "finished_at_utc": finished.isoformat(), "exit_code": receipt.get("exit_code"),
            "reason_code": receipt.get("reason_code"), "run_code_sha": receipt.get("run_code_sha"),
            "first_readable_at_utc": first_readable.isoformat() if first_readable else None,
            "receipt_sha256": sha256(canonical(receipt).encode()).hexdigest(),
        }
        with self.transaction() as db:
            existing = lookup(db, attempt_id)
            if existing is not None:
                if existing["payload"] != payload:
                    raise ValueError("receipt conflicts with its archived attempt")
                return attempt_id
        frozen = self._read_archive(destination, proof) if destination is not None else None
        with self.transaction() as db:
            snapshot_id = None
            if frozen is not None:
                snapshot_id = self._append_archive(db, frozen, recorded)
                known = readable_at(db, snapshot_id)
                if known is not None and first_readable is not None and known != first_readable:
                    raise ValueError("receipts disagree about the first-readable time")
                if first_readable is not None and first_readable < utc(frozen[0]["generated_at_utc"]):
                    raise ValueError("publication predates snapshot generation")
            append(db, attempt_id, "receipt", snapshot_id, payload, recorded)
        return attempt_id

    def import_archive(self, directory: Path, *, now: datetime | None = None) -> str:
        """Register archived decisions while leaving publication time unknown."""
        frozen = self._read_archive(directory.resolve(), None)
        with self.transaction() as db:
            return self._append_archive(db, frozen, utc(now or datetime.now(timezone.utc)))

    def _read_archive(self, directory: Path, proof: Mapping[str, Any] | None) -> tuple[dict, tuple, set[str]]:
        if not directory.resolve().is_relative_to(self.root) or not directory.is_dir():
            raise ValueError("snapshot must be a directory under the decision root")
        manifest_bytes = (directory / "run_manifest.json").read_bytes()
        digest = sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes)
        identity = snapshot_identity(manifest)
        day = publication_day(identity["decision_date"])
        style = identity["strategy_style"] or "default"
        if directory != self.root / day.isoformat() / style:
            raise ValueError("snapshot path does not match its manifest identity")
        inputs = manifest["input_provenance"]
        if inputs.get("market_data_mode") != "sip_eod" or inputs.get("market_data_feed") != "sip":
            raise ValueError("forward evidence requires completed-session SIP data")
        if proof is not None and proof["manifest_sha256"] != digest:
            raise ValueError("archive manifest SHA256 differs from the receipt")
        daily, weekly = manifest["daily_symbols"], manifest["weekly_symbols"]
        require_valid_snapshot(directory, attention_cap=max(1, len(daily), len(weekly)))
        decision_bytes = (directory / "decisions.jsonl").read_bytes()
        decision_hash = sha256(decision_bytes).hexdigest()
        pinned = manifest.get("decisions_sha256")
        if (pinned is not None and pinned != decision_hash) or (
            proof is not None and "decisions_sha256" in proof and proof["decisions_sha256"] != pinned
        ):
            raise ValueError("decision SHA256 differs from the publication evidence")
        decisions = stock_decisions_from_jsonl(decision_bytes.decode("utf-8"))
        if any(d.provenance.get("market_data_feed") != "sip" or d.provenance.get("market_data_mode") != "sip_eod" for d in decisions):
            raise ValueError("decision provenance differs from the SIP archive")
        archives = ("action_list.md", "weekly_review.md")
        grace_symbols = set()
        if manifest.get("stability_policy_version") == DAILY_ATTENTION_STABILITY_POLICY_VERSION:
            report = (directory / "action_list.md").read_text(encoding="utf-8")
            grace_symbols.update(re.findall(
                r"^<summary><b>#\d+ ([^<> ]+)</b> \[LIST \d+d · GRACE 1/2\]", report, re.MULTILINE,
            ))
            streaks = manifest.get("in_list_streaks") or {}
            grace_symbols.update(symbol for symbol in daily if streaks.get(symbol, 0) >= 2)
        metadata = {
            "session": day.isoformat(), "style": style, "manifest_sha256": digest,
            "archive": f"{day}/{style}", "generated_at_utc": utc(manifest["generated_at_utc"]).isoformat(),
            "code_sha": manifest.get("code_sha"), "config_fingerprint": manifest.get("config_fingerprint"),
            "decision_policy": identity["policy_version"], "report_layout": identity["layout_version"],
            "report_renderer": manifest.get("report_renderer_revision"),
            "stability_policy": manifest.get("stability_policy_version"),
            "daily": daily, "weekly": weekly,
            "sha256": {**{name: file_sha(directory / name) for name in archives}, "decisions.jsonl": decision_hash},
        }
        if pinned is not None:
            metadata["decision_bytes_pinned"] = True
        return metadata, decisions, grace_symbols

    @staticmethod
    def _append_archive(db: sqlite3.Connection, frozen: tuple[dict, tuple, set[str]], now: datetime) -> str:
        metadata, decisions, grace_symbols = frozen
        snapshot_id = evidence_id("snapshot", metadata["style"], metadata["session"], metadata["manifest_sha256"])
        if not append(db, snapshot_id, "snapshot", None, metadata, now):
            return snapshot_id

        daily = {symbol: rank for rank, symbol in enumerate(metadata["daily"], start=1)}
        weekly = {symbol: rank for rank, symbol in enumerate(metadata["weekly"], start=1)}
        for decision in decisions:
            symbol = decision.symbol
            cik = issuer_cik(decision.provenance.get("cik"))
            s2_reason = None
            if symbol in daily:
                incumbent = any(item.route == "daily_retention" for item in decision.review_conditions)
                if incumbent and decision.action_state is ActionState.PRIORITY_REVIEW:
                    s2_reason = "incumbent_priority_review"
                elif (incumbent or symbol in grace_symbols) and is_soft_exit_grace_eligible(decision, (symbol,)):
                    s2_reason = "soft_exit_grace"
                elif decision.action_state is ActionState.PRIORITY_REVIEW:
                    s2_reason = "priority_review"
                else:
                    s2_reason = "not_recorded"
            observation = {
                "symbol": symbol, "security_id": f"{symbol}:{cik}" if cik else None,
                "industry": decision.provenance.get("sic") or decision.provenance.get("sector"),
                "session": decision.decision_date, "quality": decision.quality.grade.value,
                "entry": decision.entry.state.value, "action": decision.action_state.value,
                "quality_asof": decision.quality.data_asof, "market_asof": decision.entry.market_asof,
                "priority": decision.priority, "daily_rank": daily.get(symbol), "weekly_rank": weekly.get(symbol),
                "candidate": decision.action_state is ActionState.PRIORITY_REVIEW,
                "s2_reason": s2_reason, "sources": list(decision.source_lists),
                "official_close": decision.provenance.get("official_sip_close"),
                "entry_gates": [asdict(gate) for gate in decision.entry.gate_results],
                "review_conditions": [asdict(condition) for condition in decision.review_conditions],
                "ready_age": asdict(decision.ready_age) if decision.ready_age else None,
            }
            append(db, evidence_id("observation", snapshot_id, symbol), "observation", snapshot_id, observation, now)
        return snapshot_id


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "payload": json.loads(row["payload"])}


def lookup(db: sqlite3.Connection, key: str, *, kind: str | None = None) -> dict[str, Any] | None:
    row = db.execute("SELECT * FROM evidence WHERE id = ?", (key,)).fetchone()
    if row is None or (kind is not None and row["kind"] != kind):
        return None
    return _record(row)


def require(db: sqlite3.Connection, key: str, kind: str) -> dict[str, Any]:
    row = lookup(db, key, kind=kind)
    if row is None:
        raise ValueError(f"unknown {kind} ID: {key}")
    return row


def entries(db: sqlite3.Connection, kind: str | None = None, *, parent: str | None = None) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM evidence WHERE (? IS NULL OR kind = ?) AND (? IS NULL OR parent = ?) ORDER BY rowid",
        (kind, kind, parent, parent),
    )
    return [_record(row) for row in rows]


def append(db: sqlite3.Connection, key: str, kind: str, parent: str | None, payload: Mapping[str, Any], now: datetime) -> bool:
    encoded = canonical(payload)
    result = db.execute(
        "INSERT INTO evidence VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
        (key, kind, parent, now.isoformat(), encoded),
    )
    if result.rowcount:
        return True
    row = db.execute("SELECT kind, parent, payload FROM evidence WHERE id = ?", (key,)).fetchone()
    if tuple(row) != (kind, parent, encoded):
        raise ValueError(f"conflicting immutable {kind} record: {key}")
    return False


def readable_at(db: sqlite3.Connection, snapshot_id: str, *, asof: datetime | None = None) -> datetime | None:
    for row in entries(db, "receipt", parent=snapshot_id):
        if asof is not None and utc(row["recorded_at"]) > asof:
            continue
        if value := row["payload"]["first_readable_at_utc"]:
            return utc(value)
    return None


def receipt_files(root: Path, style: str) -> Iterator[Path]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", style) or style in {".", ".."}:
        raise ValueError("invalid strategy style")
    yield from sorted((root / "publication_attempts" / style / "formal").glob("*.json"))


def local_day(value: datetime) -> date:
    return value.astimezone(NYSE_TZ).date()
