"""Observation-period scanner: run both styles (risk_off, risk_on) back to back.

Two-style architecture (see docs/two_style_observation_protocol.md): every observation
cycle runs both production configs and prints a side-by-side summary. No
combined weight, no rotation — the styles are observed independently.

Usage:
    .venv/bin/python scripts/observation_scan.py [--max-symbols N]
"""
from __future__ import annotations

import argparse
import glob
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

STYLES = [
    ("risk_off", "configs/config.risk_off.json"),
    ("risk_on", "configs/config.risk_on.json"),
]

# Reports live at the outputs root for fresh scans and under the monthly
# archive (`outputs/scans/<YYYY-MM>/`, README §8.1) after a tidy.
REPORT_GLOBS = (
    "outputs/ai_value_scan_*_ranked_report.md",
    "outputs/scans/*/ai_value_scan_*_ranked_report.md",
)


def _recent_report_paths(root: str | Path = ".") -> list[str]:
    """Ranked style reports (full or capped/sample scopes), newest first."""
    base = Path(root)
    paths: set[str] = set()
    for pattern in REPORT_GLOBS:
        paths.update(glob.glob(str(base / pattern)))
    return sorted(
        paths, key=lambda path: Path(path).stat().st_mtime, reverse=True
    )


def _pick_reports_by_style(paths: Sequence[str]) -> dict[str, str]:
    """Newest report per style, matched via the report's ``Config:`` header.

    Header matching (not mtime pairing) keeps theme-scan reports from being
    mislabelled as style reports.
    """
    picked: dict[str, str] = {}
    for path in paths:
        try:
            head = Path(path).read_text()[:400]
        except OSError:
            continue
        for label, cfg_name in STYLES:
            if f"Config: {cfg_name}" in head and label not in picked:
                picked[label] = path
    return picked


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

    by_style = _pick_reports_by_style(_recent_report_paths())
    if len(by_style) < len(STYLES):
        if args.skip_scan:
            print(
                "[skip-scan] fewer style reports than styles; run a full "
                "observation scan first.",
                flush=True,
            )
            return
        print("[warning] fewer reports than styles; scan may have failed.", flush=True)
    for label, _cfg in STYLES:
        if label in by_style:
            _print_summary(label, by_style[label])

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
