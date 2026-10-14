#!/usr/bin/env python3
"""Generate M0 read-only baseline inventory, human review worksheet, and M1 gate."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_value_scanner.research.m0_baseline_review import write_m0_deliverables


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--snap510-dir",
        default="evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff",
        help="Path to frozen 2026-10-09 510-symbol snapshot directory.",
    )
    p.add_argument(
        "--snap62-dir",
        default="outputs/decision_experiments/risk_off_20261013T093029Z/2026-10-12/risk_off",
        help="Path to frozen 2026-10-12 62-symbol MVP Beta snapshot directory.",
    )
    p.add_argument(
        "--output-dir",
        default="docs/m0_baseline_review_20261014",
        help="Destination directory for M0 deliverables.",
    )
    p.add_argument(
        "--git-main-sha",
        default="1a2612e4736c82cb9407bf3ca536e82b6f389578",
        help="Verified main branch commit SHA.",
    )
    p.add_argument(
        "--evidence-branch-sha",
        default="68143bff19f60f014e237d1f95eda28adf074b9b",
        help="Verified evidence-observations branch commit SHA.",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    hashes = write_m0_deliverables(
        output_dir=Path(args.output_dir),
        snap510_dir=Path(args.snap510_dir),
        snap62_dir=Path(args.snap62_dir),
        git_main_sha=args.git_main_sha,
        evidence_branch_sha=args.evidence_branch_sha,
    )
    for name, digest in hashes.items():
        print(f"{digest}  {name}")


if __name__ == "__main__":
    main()
