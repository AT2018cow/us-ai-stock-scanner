"""Opt-in, versioned three-source discovery union; no investment decisions here.

The legacy watchlist loader is intentionally independent from this module.
"""
from __future__ import annotations

from collections import Counter
import csv
from datetime import date
import hashlib
from pathlib import Path
import re
from typing import Any

DISCOVERY_SCHEMA_VERSION = "discovery_sources_v1"
SOURCE_KINDS = ("us_core", "thematic", "manual")
COLUMNS = {"symbol", "source_id", "source_asof", "security_type", "enabled"}
TICKER_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.]{0,14}\Z")
REJECT_CODES = {
    "SOURCE_DISABLED",
    "SOURCE_SYMBOL_INVALID",
    "SOURCE_SOURCE_ID_MISSING",
    "SOURCE_ASOF_INVALID",
    "SOURCE_SECURITY_NOT_COMMON",
    "SOURCE_THEME_ID_MISSING",
    "SOURCE_MANUAL_REASON_MISSING",
    "SOURCE_DUPLICATE_MEMBERSHIP",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _jsonable_path(path: Path) -> str:
    return path.as_posix()


def load_discovery_sources(paths: dict[str, str]) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    """Read frozen CSVs with no API calls; preserve *all* valid source memberships.

    Return (legacy-compatible watchlist rows, memberships, rejected source rows,
    manifest summary). source_id is a stable source identity, never a score.
    """
    if not paths or set(paths) - set(SOURCE_KINDS):
        raise ValueError("discovery_source_files must use us_core/thematic/manual keys")
    source_files = []
    memberships = []
    rejected = []
    watchlist_rows = []
    seen_keys = set()
    for kind in SOURCE_KINDS:
        if kind not in paths:
            continue
        path = Path(paths[kind])
        if not path.is_file():
            raise ValueError("missing discovery source CSV: " + str(path))
        source_bytes = path.read_bytes()
        sha256 = hashlib.sha256(source_bytes).hexdigest()
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames or (COLUMNS - set(reader.fieldnames)):
                    raise ValueError(
                        str(path) + " missing columns: " +
                        ", ".join(sorted(COLUMNS - set(reader.fieldnames or [])))
                    )
                rows = list(reader)
        except UnicodeError as exc:
            raise ValueError("invalid UTF-8 source CSV: " + str(path)) from exc

        file_accepted = 0
        file_rejected = 0
        for row_index, row in enumerate(rows, start=2):
            raw = _text(row.get("symbol"))
            symbol = raw.upper()
            source_id = _text(row.get("source_id"))
            source_asof = _text(row.get("source_asof"))
            security_type = _text(row.get("security_type")).lower()
            theme_id = _text(row.get("theme_id")).lower()
            legacy_bucket = _text(row.get("legacy_bucket")).lower()
            note = _text(row.get("research_note"))
            etfs = _text(row.get("etfs"))
            enabled = _text(row.get("enabled")).lower()
            reason = None
            if enabled in {"0", "false", "no", "n"}:
                reason = "SOURCE_DISABLED"
            elif enabled not in {"1", "true", "yes", "y"}:
                raise ValueError(
                    str(path) + ": invalid enabled at CSV row " + str(row_index)
                )
            elif symbol != raw or not TICKER_PATTERN.fullmatch(symbol):
                # Do not silently transform '-' into '.' or guess share-class aliases.
                reason = "SOURCE_SYMBOL_INVALID"
            elif not source_id:
                reason = "SOURCE_SOURCE_ID_MISSING"
            else:
                try:
                    day = date.fromisoformat(source_asof)
                    if day.isoformat() != source_asof:
                        raise ValueError("noncanonical date")
                except ValueError:
                    reason = "SOURCE_ASOF_INVALID"
            if reason is None and security_type != "common_stock":
                reason = "SOURCE_SECURITY_NOT_COMMON"
            if reason is None and kind == "thematic" and not theme_id:
                reason = "SOURCE_THEME_ID_MISSING"
            if reason is None and kind == "manual" and not note:
                reason = "SOURCE_MANUAL_REASON_MISSING"
            membership_key = (kind, source_id, symbol)
            if reason is None and membership_key in seen_keys:
                reason = "SOURCE_DUPLICATE_MEMBERSHIP"

            if reason is not None:
                rejected.append({
                    "source_kind": kind,
                    "source_file": _jsonable_path(path),
                    "row_number": row_index,
                    "symbol_raw": raw,
                    "reason_code": reason,
                })
                file_rejected += 1
                continue

            seen_keys.add(membership_key)
            # Non-AI / non-theme sources must not masquerade as AI ETF consensus.
            if kind != "thematic" or theme_id != "ai":
                legacy_bucket, etfs = "", ""
            member = {
                "symbol": symbol,
                "symbol_raw": raw,
                "source_kind": kind,
                "source_id": source_id,
                "source_asof": source_asof,
                "source_file": _jsonable_path(path),
                "source_sha256": sha256,
                "security_type": security_type,
                "theme_id": theme_id if kind == "thematic" else None,
                "legacy_bucket": legacy_bucket if legacy_bucket else None,
                "research_note": note if kind == "manual" else None,
            }
            memberships.append(member)
            watchlist_rows.append({
                "symbol": symbol,
                "bucket": legacy_bucket,
                "etf_count": 0,
                "etfs": etfs,
                "enabled": 1,
            })
            file_accepted += 1
        source_files.append({
            "source_kind": kind,
            "source_file": _jsonable_path(path),
            "archived_file": "discovery_source_inputs/" + kind + ".csv",
            "sha256": sha256,
            "raw_rows": len(rows),
            "memberships": file_accepted,
            "rejected_rows": file_rejected,
        })

    memberships.sort(key=lambda x: (x["symbol"], x["source_kind"], x["source_id"]))
    rejected.sort(key=lambda x: (x["source_kind"], x["source_file"], x["row_number"]))
    # The v1 score adapter appends empty buckets when fed multiple rows for a
    # shared symbol. Aggregate first; do NOT change that legacy adapter.
    combined: dict[str, dict[str, set[str]]] = {}
    for row in watchlist_rows:
        symbol = row["symbol"]
        item = combined.setdefault(symbol, {"buckets": set(), "etfs": set()})
        if row["bucket"]:
            item["buckets"].update(x for x in row["bucket"].split(",") if x)
        if row["etfs"]:
            item["etfs"].update(x for x in row["etfs"].split(",") if x)
    watchlist_rows = [
        {
            "symbol": symbol,
            "bucket": ",".join(sorted(values["buckets"])),
            "etf_count": len(values["etfs"]),
            "etfs": ",".join(sorted(values["etfs"])),
            "enabled": 1,
        }
        for symbol, values in sorted(combined.items())
    ]
    symbols = {x["symbol"] for x in memberships}
    summary = {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "source_files": source_files,
        "source_memberships": len(memberships),
        "unique_symbols": len(symbols),
        "multi_source_symbols": sum(
            count > 1 for count in Counter(x["symbol"] for x in memberships).values()
        ),
        "rejected_rows": len(rejected),
        "rejection_reason_counts": dict(
            sorted(Counter(x["reason_code"] for x in rejected).items())
        ),
        "membership_counts_by_kind": dict(
            sorted(Counter(x["source_kind"] for x in memberships).items())
        ),
    }
    if not memberships:
        raise ValueError("discovery sources contain no enabled common-stock memberships")
    return watchlist_rows, memberships, rejected, summary


def assert_memberships_asof(memberships: list[dict[str, Any]], decision_date: str) -> None:
    """Reject future membership vs the *market session*, not the wall-clock run day."""
    for member in memberships:
        if member["source_asof"] > decision_date:
            raise ValueError(
                "future discovery membership for " + member["symbol"] +
                ": " + member["source_asof"] + " > decision session " + decision_date
            )


def validate_discovery_snapshot(
    *,
    memberships: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    summary: dict[str, Any],
    discovery_symbols: set[str],
    decision_date: str,
) -> list[str]:
    """Validate saved snapshot audit against its original manifest contract."""
    errors = []
    if summary.get("schema_version") != DISCOVERY_SCHEMA_VERSION:
        errors.append("discovery source schema version mismatch")
    keys = [(m.get("source_kind"), m.get("source_id"), m.get("symbol")) for m in memberships]
    if len(keys) != len(set(keys)):
        errors.append("duplicate discovery membership identity")
    symbols = {m.get("symbol") for m in memberships}
    if symbols != discovery_symbols:
        errors.append("discovery membership universe does not match decisions+exclusions")
    if summary.get("source_memberships") != len(memberships):
        errors.append("discovery membership count mismatch")
    if summary.get("unique_symbols") != len(symbols):
        errors.append("discovery unique-symbol count mismatch")
    if summary.get("rejected_rows") != len(rejected):
        errors.append("discovery source rejected-row count mismatch")
    if summary.get("multi_source_symbols") != sum(
        n > 1 for n in Counter(m.get("symbol") for m in memberships).values()
    ):
        errors.append("discovery source overlap count mismatch")
    counts = dict(sorted(Counter(m.get("source_kind") for m in memberships).items()))
    if summary.get("membership_counts_by_kind") != counts:
        errors.append("discovery membership kind counts mismatch")
    reasons = dict(sorted(Counter(r.get("reason_code") for r in rejected).items()))
    if summary.get("rejection_reason_counts") != reasons:
        errors.append("discovery source rejection counts mismatch")
    if any(r.get("reason_code") not in REJECT_CODES for r in rejected):
        errors.append("unknown discovery source rejection code")
    if any(m.get("source_asof", "9999") > decision_date for m in memberships):
        errors.append("future discovery membership as-of date")
    files = summary.get("source_files")
    if not isinstance(files, list):
        errors.append("discovery source_files manifest missing")
    else:
        accepted_files = Counter(m.get("source_file") for m in memberships)
        rejected_files = Counter(r.get("source_file") for r in rejected)
        if len({f.get("source_file") for f in files if isinstance(f, dict)}) != len(files):
            errors.append("duplicate discovery source file")
        for f in files:
            if not isinstance(f, dict):
                errors.append("malformed discovery source file manifest")
                continue
            path = f.get("source_file")
            if f.get("memberships") != accepted_files[path] or f.get("rejected_rows") != rejected_files[path]:
                errors.append("discovery source file counts mismatch: " + str(path))
            if f.get("raw_rows") != accepted_files[path] + rejected_files[path]:
                errors.append("discovery source raw-row conservation mismatch: " + str(path))
            if any(
                m.get("source_sha256") != f.get("sha256")
                for m in memberships if m.get("source_file") == path
            ):
                errors.append("discovery membership source SHA mismatch: " + str(path))
    return errors
