"""Observation-period scanner: run both styles (risk_off, risk_on) back to back.

Two-style architecture (see docs/two_style_observation_protocol.md): every observation
cycle runs both production configs and prints a side-by-side summary. No
combined weight, no rotation — the styles are observed independently.

Usage:
    .venv/bin/python scripts/observation_scan.py [--max-symbols N]
"""
from __future__ import annotations

import argparse
import re
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

    # Observation summary — interleaved with scan so each style reads its own report.
    print(f"\n{'='*70}\n[observation summary]\n{'='*70}", flush=True)
    import glob
    import re
    from pathlib import Path as _P

    if args.skip_scan:
        # No new scan: use the two most recent reports (risk_off ran first → mtime order).
        reports = sorted(glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"),
                         key=lambda p: _P(p).stat().st_mtime)
        if len(reports) < 2:
            print("[skip-scan] fewer than 2 reports found; run a full observation scan first.", flush=True)
            return
        # [-2] = risk_off (earlier), [-1] = risk_on (later)
        for label, latest in zip([s[0] for s in STYLES], reports[-2:]):
            _print_summary(label, latest)
    else:
        # We just ran the scans: interleave and grab each style's report.
        style_reports = sorted(glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"),
                              key=lambda p: _P(p).stat().st_mtime)
        if len(style_reports) < len(STYLES):
            print("[warning] fewer reports than styles; scan may have failed.", flush=True)
        for label, latest in zip([s[0] for s in STYLES], style_reports[-len(STYLES):]):
            _print_summary(label, latest)

    print(
        "\nObservation reminder: record signal counts, style feature mirror stats, "
        "and regime tags per two_style_observation_protocol.md.",
        flush=True,
    )


def _print_summary(label: str, report_path: str) -> None:
    """Print triage + shortlist from a single style's report."""
    from pathlib import Path

    text = Path(report_path).read_text()
    triage = re.search(r"## Triage\n(.*?)\n## Shortlist", text, re.S)
    shortlist = re.search(r"## Shortlist\n(.*?)\n## Research Pool", text, re.S)
    print(f"\n[{label}] report: {Path(report_path).name}")
    if triage:
        print(triage.group(1).strip())
    if shortlist:
        lines = [l for l in shortlist.group(1).strip().splitlines() if l.strip()][:20]
        print("\n".join(lines))


if __name__ == "__main__":
    main()
