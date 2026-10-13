"""Read-only MVP v1.1 A0 inventory. No Modal, SEC, or Alpaca requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.research.mvp_v11 import inspect_frozen_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-dataset", required=True)
    parser.add_argument("--entry-dataset", required=True)
    parser.add_argument("--quality-meta", default=None, help="Metadata file matching quality CSV")
    parser.add_argument("--entry-meta", default=None, help="Metadata file matching entry CSV")
    parser.add_argument("--output", required=True, help="Local audit JSON path (not raw data)")
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing audit: {out}")
    quality = inspect_frozen_dataset(
        args.quality_dataset, expected_kind="company_quality", metadata=args.quality_meta
    )
    entry = inspect_frozen_dataset(
        args.entry_dataset, expected_kind="entry_quality", metadata=args.entry_meta
    )
    result = {
        "stage": "A0 structural data gate, not baseline parity",
        "quality": quality,
        "entry": entry,
        "next_gate": "Verify corrected v3 labels/PIT/SEC/identity and reproduce B0 before any candidate outcomes",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"STRUCTURAL_PASS (PIT and forward labels UNVERIFIED): {out}")


if __name__ == "__main__":
    main()
