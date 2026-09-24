"""Observation-period scanner: run both styles (risk_off, risk_on) back to back.

Two-style architecture (see docs/OBSERVATION_PROTOCOL.md): every observation
cycle runs both production configs and prints a side-by-side summary. No
combined weight, no rotation — the styles are observed independently.

Usage:
    .venv/bin/python scripts/observation_scan.py [--max-symbols N]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

STYLES = [
    ("risk_off", "configs/config.risk_off.json"),
    ("risk_on", "configs/config.risk_on.json"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Two-style observation scan")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--skip-scan", action="store_true",
                        help="Only print the observation summary from latest outputs")
    args = parser.parse_args()

    if not args.skip_scan:
        for label, cfg_path in STYLES:
            print(f"\n{'='*70}\n[{label}] scan start ({cfg_path})\n{'='*70}", flush=True)
            cmd = [sys.executable, "run_scan.py", "--config", cfg_path]
            if args.max_symbols:
                cmd += ["--max-symbols", str(args.max_symbols)]
            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f"[{label}] scan FAILED (exit {result.returncode})", flush=True)
                sys.exit(result.returncode)

    # Observation summary from the latest outputs of each style
    print(f"\n{'='*70}\n[observation summary]\n{'='*70}", flush=True)
    import json
    import glob

    import pandas as pd

    for label, _ in STYLES:
        reports = sorted(glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"))
        candidates = [
            (p, Path(p).name.split("_")[2])
            for p in reports
            if Path(p).name.startswith("ai_value_scan_")
        ]
        # latest report with that config's style signature: use triage section
        latest = reports[-1] if reports else None
        if not latest:
            print(f"[{label}] no scan report found", flush=True)
            continue
        text = Path(latest).read_text()
        import re
        triage = re.search(r"## Triage\n(.*?)\n## Shortlist", text, re.S)
        shortlist = re.search(r"## Shortlist\n(.*?)\n## Research Pool", text, re.S)
        print(f"\n[{label}] latest report: {Path(latest).name}")
        if triage:
            print(triage.group(1).strip())
        if shortlist:
            lines = [l for l in shortlist.group(1).strip().splitlines() if l.strip()][:20]
            print("\n".join(lines))
    print(
        "\nObservation reminder: record signal counts, style feature mirror stats, "
        "and regime tags per OBSERVATION_PROTOCOL.md.",
        flush=True,
    )


if __name__ == "__main__":
    main()
