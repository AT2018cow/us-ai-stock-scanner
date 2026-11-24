#!/usr/bin/env python3
"""Replay a frozen SIP close or compare a saved close plan with opening observations."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.forward.ledger import Ledger, append, evidence_id, file_sha, readable_at, require
from ai_value_scanner.market_calendar import session_close_utc
from ai_value_scanner.reporting.snapshot import load_snapshot_decisions, load_snapshot_manifest
from ai_value_scanner.swing.events import known_events, load_calendar, timestamp
from ai_value_scanner.swing.opening import opening_review, render_opening_cards
from ai_value_scanner.swing.setups import evaluate_close
from ai_value_scanner.validation.decision_snapshot import require_valid_snapshot


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _close(args):
    inputs = _read(args.inputs)
    session = date.fromisoformat(inputs["session"])
    context = evaluate_close(inputs["bars"], session, splits=inputs.get("splits", ()), prior=inputs.get("prior"),
                             issue=inputs.get("issue"))
    if args.event_calendar:
        asof = timestamp(inputs["asof"])
        if asof < session_close_utc(session):
            raise ValueError("close review cutoff precedes the session close")
        calendar, digest = load_calendar(args.event_calendar)
        context["calendar"] = known_events(calendar, inputs["symbol"].upper(), inputs["cik"], decision_day=session, asof=asof)
        context["calendar_sha256"] = digest
    return context


def _record_opening(ledger: Ledger, archive: Path, manifest: dict, cards: dict) -> None:
    recorded = datetime.now(timezone.utc)
    date_token = manifest["decision_date"]
    style = manifest.get("strategy_style") or "default"
    sid = evidence_id("snapshot", style, date_token, file_sha(archive / "run_manifest.json"))
    with ledger.transaction() as db:
        frozen = require(db, sid, "snapshot")["payload"]
        if frozen["sha256"]["decisions.jsonl"] != file_sha(archive / "decisions.jsonl"):
            raise ValueError("current archive decision bytes differ from the registered observation")
        for symbol, card in cards.items():
            asof = timestamp(card["asof"])
            if asof > recorded:
                raise ValueError("opening observation lies in the future")
            if (available := readable_at(db, sid)) is not None and asof < available:
                raise ValueError("opening observation predates the official publication")
            oid = evidence_id("observation", sid, symbol)
            require(db, oid, "observation")
            key = evidence_id("opening_review", oid, card["phase"], card["asof"])
            append(db, key, "opening_review", oid, card, recorded)


def _opening(args):
    manifest = load_snapshot_manifest(args.snapshot)
    lengths = [len(manifest.get(key, [])) for key in ("daily_symbols", "weekly_symbols")]
    require_valid_snapshot(args.snapshot, attention_cap=max(1, *lengths))
    by_symbol = {decision.symbol: decision for decision in load_snapshot_decisions(args.snapshot)}
    asof = timestamp(args.asof) if args.asof else datetime.now(timezone.utc)
    if asof < timestamp(manifest["generated_at_utc"]):
        raise ValueError("opening observation predates the archived close plan")
    cards = {}
    for symbol, inputs in _read(args.observations).items():
        decision = by_symbol.get(symbol)
        if decision is None or decision.swing_review is None or decision.provenance.get("market_data_mode") != "sip_eod":
            raise ValueError(f"{symbol}: frozen SIP close review unavailable")
        cards[symbol] = opening_review(decision.swing_review, inputs, asof=asof, max_age_seconds=args.max_age_seconds)
    if args.ledger:
        _record_opening(Ledger(args.ledger, snapshot_root=args.snapshot_root), args.snapshot, manifest, cards)
    return cards


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    close = commands.add_parser("close", help="Recompute close evidence from frozen inputs")
    close.add_argument("inputs", type=Path)
    close.add_argument("--event-calendar", type=Path)
    opening = commands.add_parser("opening", help="Build an opening card from an archived close decision")
    opening.add_argument("--snapshot", type=Path, required=True)
    opening.add_argument("--observations", type=Path, required=True)
    opening.add_argument("--asof")
    opening.add_argument("--max-age-seconds", type=int, default=180)
    opening.add_argument("--ledger", type=Path)
    opening.add_argument("--snapshot-root", type=Path, default=Path("outputs/decisions"))
    opening.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    try:
        result = _close(args) if args.command == "close" else _opening(args)
        if args.command == "opening" and args.format == "markdown":
            print(render_opening_cards(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, TypeError, KeyError, AttributeError, ValueError, sqlite3.Error) as exc:
        print(f"swing review: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
