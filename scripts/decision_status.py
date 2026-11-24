"""Inspect the live publication status and locate the latest Action List."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ai_value_scanner.reporting.publication import format_list_status, latest_list_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=Path("outputs/decisions"))
    parser.add_argument("--style", choices=("production", "risk_off"), default="production")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    status = latest_list_status(args.snapshot_root, args.style, datetime.now(timezone.utc))
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(format_list_status(status))
        if status.get("error"):
            print(status["error"])
        if publication := status["publication"]:
            print("Action List", args.snapshot_root / publication["action_list_md"])
            print("Weekly Review", args.snapshot_root / publication["weekly_review_md"])
    return int(status["status"] in {"overdue", "failed", "invalid"})


if __name__ == "__main__":
    raise SystemExit(main())
