#!/usr/bin/env python3
"""Append and inspect private forward-observation and paper research evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.forward.ledger import Ledger, receipt_files
from ai_value_scanner.forward.study import (
    freeze_protocol, record_exit, record_fill, record_outcome, record_paper, record_review, record_setup, study_summary,
)

WRITE = {
    "register": freeze_protocol,
    "review": record_review,
    "setup": record_setup,
    "paper": record_paper,
    "fill": record_fill,
    "exit": record_exit,
    "settle": record_outcome,
}


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("outputs/forward/ledger.sqlite3"))
    parser.add_argument("--snapshot-root", type=Path, default=Path("outputs/decisions"))
    commands = parser.add_subparsers(dest="command", required=True)
    receipts = commands.add_parser("import-receipts", help="Import completed formal SIP attempts and validate their snapshots")
    receipts.add_argument("--style", default="production")
    receipts.add_argument("--receipt", type=Path, action="append")
    archive = commands.add_parser("import-archive", help="Register a SIP archive with unknown publication time")
    archive.add_argument("directory", type=Path)
    for name in WRITE:
        commands.add_parser(name).add_argument("input", type=Path)
    commands.add_parser("summary").add_argument("protocol_id")
    listing = commands.add_parser("list")
    listing.add_argument("--parent", help="Filter by the parent snapshot, observation, or paper ID")
    listing.add_argument("--kind", choices=(
        "snapshot", "receipt", "observation", "protocol", "review", "setup", "paper", "paper_fill", "paper_exit", "outcome",
        "opening_review",
    ))
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.db, snapshot_root=args.snapshot_root)
        if args.command == "import-receipts":
            imported, rejected, incomplete = [], [], 0
            for path in args.receipt or receipt_files(ledger.root, args.style):
                try:
                    receipt = _read(path)
                    if receipt.get("status") == "running":
                        incomplete += 1
                        continue
                    imported.append(ledger.import_attempt(receipt))
                except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
                    rejected.append({"file": path.name, "error": str(exc)})
            result = {"accepted_ids": imported, "incomplete": incomplete, "rejected": rejected}
        elif args.command == "import-archive":
            result = {"id": ledger.import_archive(args.directory)}
        elif args.command == "summary":
            result = study_summary(ledger, args.protocol_id)
        elif args.command == "list":
            result = ledger.records(args.kind, parent=args.parent)
        else:
            result = {"id": WRITE[args.command](ledger, _read(args.input))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
        print(f"forward evidence: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return int(args.command == "import-receipts" and bool(rejected))


if __name__ == "__main__":
    raise SystemExit(main())
