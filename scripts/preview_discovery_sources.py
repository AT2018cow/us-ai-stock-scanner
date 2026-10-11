"""Offline preview of an opt-in, frozen US Core / Thematic / Manual discovery union."""

from __future__ import annotations

import argparse
import json

import pandas as pd

from ai_value_scanner.config import load_config
from ai_value_scanner.decision.discovery import (
    assert_memberships_asof,
    load_discovery_sources,
)
from ai_value_scanner.scanner import watchlist_rows_to_scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="ScanConfig JSON with discovery_source_files")
    parser.add_argument("--decision-date", help="Expected market-session YYYY-MM-DD; checks source PIT as-of")
    args = parser.parse_args()
    config = load_config(args.config)
    if config.discovery_source_files is None:
        parser.error("config has no discovery_source_files; legacy mode needs no preview")
    rows, memberships, rejected, summary = load_discovery_sources(
        config.discovery_source_files
    )
    if args.decision_date:
        assert_memberships_asof(memberships, args.decision_date)
    scores = watchlist_rows_to_scores(pd.DataFrame(rows))
    if len(scores) != summary["unique_symbols"]:
        raise ValueError("legacy score adapter and discovery source union disagree")
    print(json.dumps({
        "candidate_universe_mode": "opt_in_three_source_union",
        "source_summary": summary,
        "accepted_symbols": sorted(set(member["symbol"] for member in memberships)),
        "rejected_source_rows": rejected,
        "notes": [
            "Discovery memberships do not imply investability or Quality.",
            "No Alpaca/SEC queries were made.",
            "This does not create a formal or experiment StockDecision snapshot.",
        ],
    }, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
