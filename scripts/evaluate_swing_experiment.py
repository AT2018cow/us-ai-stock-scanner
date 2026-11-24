#!/usr/bin/env python3
"""Register, freeze and settle the independent Phase 7 swing experiment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.forward.ledger import Ledger, append, evidence_id, require, utc
from ai_value_scanner.research.swing_cohorts import freeze, register, sha
from ai_value_scanner.research.swing_experiment import evaluate


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, row, *, archive):
    path = path.resolve()
    if path.is_relative_to(archive):
        raise ValueError("research artifacts must be outside the official snapshot archive")
    with path.open("x", encoding="utf-8") as target:
        json.dump(row, target, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        target.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True, help="Stage 4 evidence database")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    registered = commands.add_parser("register", help="record a versioned experiment before observation")
    registered.add_argument("--spec", type=Path, required=True)
    frozen = commands.add_parser("freeze", help="archive selection and timing without reading outcome prices")
    frozen.add_argument("--protocol", required=True)
    frozen.add_argument("--output", type=Path, required=True)
    frozen.add_argument("--asof", help="optional historical ledger cutoff")
    settle = commands.add_parser("evaluate", help="join already-frozen members to independent SIP labels")
    settle.add_argument("--cohort", type=Path, required=True)
    settle.add_argument("--cohort-sha256", required=True, help="value printed by freeze")
    settle.add_argument("--prices", type=Path, required=True)
    settle.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.ledger, snapshot_root=args.snapshot_root)
        now = datetime.now(timezone.utc)
        if args.command == "register":
            print(register(ledger, _read(args.spec), now=now))
            return 0
        if args.command == "freeze":
            cutoff = utc(args.asof) if args.asof else now
            if cutoff > now:
                raise ValueError("freeze cutoff cannot be in the future")
            cohort = freeze(ledger, args.protocol, asof=cutoff)
            digest = sha(cohort)
            _write(args.output, cohort, archive=ledger.root)
            with ledger.transaction() as db:
                append(db, evidence_id("swing_cohort", args.protocol, digest), "swing_cohort", args.protocol,
                       {"sha256": digest, "cutoff": cutoff.isoformat()}, now)
            print(digest)
            return 0
        cohort = _read(args.cohort)
        with ledger.transaction() as db:
            protocol = require(db, cohort["protocol_id"], "swing_protocol")
            if protocol["payload"] != cohort["spec"]:
                raise ValueError("cohort does not match its registered protocol")
            require(db, evidence_id("swing_cohort", cohort["protocol_id"], args.cohort_sha256), "swing_cohort")
        outcome = evaluate(cohort, _read(args.prices), cohort_sha256=args.cohort_sha256, now=now)
        _write(args.output, outcome, archive=ledger.root)
        return 0
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as exc:
        print(f"swing experiment: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
