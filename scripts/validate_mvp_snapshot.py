"""CLI for the shared decision snapshot validator."""
from __future__ import annotations

import argparse
import json

from ai_value_scanner.validation.decision_snapshot import (
    EXCLUSION_REASON_TO_STAGE,
    check_ticker_map_rows,
    validate_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an MVP decision snapshot structurally and semantically."
    )
    parser.add_argument("snapshot_root")
    parser.add_argument("--attention-cap", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = validate_snapshot(
        args.snapshot_root,
        attention_cap=max(1, int(args.attention_cap)),
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[{status}] {result['root']}")
        counts = result.get("counts", {})
        if counts:
            print(
                "decisions={decisions} daily={daily_attention} weekly={weekly_attention}".format(
                    **counts
                )
            )
            print(f"quality={counts['quality']}")
            print(f"entry={counts['entry']}")
            print(f"action={counts['action']}")
            if counts.get("candidate_universe"):
                print(f"candidate_universe={counts['candidate_universe']}")
            print(f"fundamental_integrity={counts.get('fundamental_integrity', {})}")
            print(f"fundamental_fallback={counts.get('fundamental_fallback', {})}")
        for warning in result.get("warnings", []):
            print(f"[WARN] {warning}")
        for error in result.get("errors", []):
            print(f"[ERROR] {error}")

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
