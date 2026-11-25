"""Build offline reading copies from locally archived production SIP reports."""
import argparse
from pathlib import Path

from ai_value_scanner.reporting.reader import export_reading_reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=Path("outputs/decisions"))
    parser.add_argument("--include-history", action="store_true", help="Also export earlier production SIP archives")
    args = parser.parse_args()
    try:
        print(export_reading_reports(args.snapshot_root, include_history=args.include_history))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Report export failed: {exc}\n")


if __name__ == "__main__":
    main()
