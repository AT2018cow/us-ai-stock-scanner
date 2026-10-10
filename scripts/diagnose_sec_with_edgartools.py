from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from dotenv import load_dotenv

from ai_value_scanner.fundamentals.edgartools_diagnostic import (
    build_run_meta,
    classify_case,
    configure_edgartools,
    diagnose_accession,
    load_snapshot_cases,
    render_summary_markdown,
    summarize_results,
)


DEFAULT_REPRESENTATIVE_SYMBOLS = (
    "EXLS",
    "JCI",
    "PYPL",
    "CDNS",
    "NXPI",
    "NEE",
    "TSM",
    "ASML",
    "SAP",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostic-only EdgarTools parity check for SEC filing/XBRL gaps. "
            "This script never changes Quality, Entry, Action, or scanner caches."
        )
    )
    parser.add_argument(
        "--snapshot-root",
        required=True,
        help="Canonical decision snapshot root containing decisions.jsonl.",
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_REPRESENTATIVE_SYMBOLS),
        help=(
            "Comma-separated symbols to inspect. Defaults to representative "
            "US 10-Q and foreign-issuer cases."
        ),
    )
    parser.add_argument(
        "--all-flagged",
        action="store_true",
        help=(
            "Also inspect every snapshot decision carrying "
            "latest_periodic_filing_not_covered or fundamental_currency_unsupported."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Output directory. Default: "
            "outputs/sec_edgartools_diagnostic/<UTC timestamp>."
        ),
    )
    return parser


def _parse_symbols(raw: str) -> tuple[str, ...]:
    return tuple(
        token.strip().upper()
        for token in str(raw or "").split(",")
        if token.strip()
    )


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv()

    snapshot_root = Path(args.snapshot_root)
    symbols = _parse_symbols(args.symbols)
    cases, decisions_path = load_snapshot_cases(
        snapshot_root,
        symbols=symbols,
        all_flagged=bool(args.all_flagged),
    )

    get_filing, runtime_meta = configure_edgartools()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(
        args.output_dir
        or f"outputs/sec_edgartools_diagnostic/{stamp}"
    )
    if output_dir.exists():
        raise SystemExit(
            f"Refusing to overwrite existing diagnostic output: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=False)

    rows: list[dict[str, object]] = []
    print(f"Selected {len(cases)} SEC parity case(s).")
    for index, case in enumerate(cases, start=1):
        symbol = str(case["symbol"])
        accession = str(case.get("current_latest_periodic_accession") or "")
        print(f"[{index}/{len(cases)}] {symbol} {accession or '(no accession)'}")
        if not accession:
            edgar = {
                "symbol": symbol,
                "accession": None,
                "edgartools_fetch_ok": False,
                "xbrl_available": False,
                "error": "missing_latest_periodic_accession",
            }
        else:
            edgar = diagnose_accession(
                symbol=symbol,
                accession=accession,
                get_filing=get_filing,
            )
        row = {
            **case,
            "classification": classify_case(case, edgar),
            "edgartools": edgar,
        }
        rows.append(row)

    summary = summarize_results(rows)
    run_meta = build_run_meta(
        snapshot_root=snapshot_root,
        decisions_path=decisions_path,
        runtime_meta=runtime_meta,
        case_count=len(rows),
    )

    diagnostics_path = output_dir / "diagnostics.jsonl"
    diagnostics_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(
        render_summary_markdown(rows, summary),
        encoding="utf-8",
    )
    (output_dir / "run_meta.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("Diagnostic complete.")
    print("Output:", output_dir)
    print(
        "Filing-gap core-found:",
        f"{summary['current_path_gap_edgartools_core_found']}/"
        f"{summary['current_path_gap_cases']}",
    )
    print("Classifications:", summary["classifications"])


if __name__ == "__main__":
    main()
