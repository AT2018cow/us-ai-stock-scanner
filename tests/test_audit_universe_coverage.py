"""Unit tests for scripts/audit_universe_coverage.py (offline, fixture-only)."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from audit_universe_coverage import audit, load_benchmark_ordered, load_symbol_set, normalize_symbol
finally:
    sys.path.pop(0)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class TestNormalizeSymbol(unittest.TestCase):
    def test_class_suffix_unified(self) -> None:
        self.assertEqual(normalize_symbol("BRK.B"), normalize_symbol("BRK-B"))
        self.assertEqual(normalize_symbol("BF.B"), "BFB")

    def test_case_insensitive(self) -> None:
        self.assertEqual(normalize_symbol("aapl"), "AAPL")

    def test_whitespace_stripped(self) -> None:
        self.assertEqual(normalize_symbol("  MSFT "), "MSFT")


class TestAuditMath(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.watch = _write_csv(
            self.root / "watch.csv",
            ["symbol", "bucket"],
            [["AAPL", "core_ai"], ["MSFT", "core_ai"], ["BRK-B", "core_ai"]],
        )
        self.bench = _write_csv(
            self.root / "bench.csv",
            ["Symbol", "Name"],
            [["NVDA", "Nvidia"], ["AAPL", "Apple"], ["BRK.B", "Berkshire"], ["JPM", "JPMorgan"]],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_coverage_counts(self) -> None:
        result = audit(load_symbol_set(self.watch), load_benchmark_ordered(self.bench))
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["covered"], 2)
        self.assertEqual(result["missing"], 2)
        self.assertEqual(result["coverage_pct"], 50.0)

    def test_missing_in_benchmark_order(self) -> None:
        result = audit(load_symbol_set(self.watch), load_benchmark_ordered(self.bench))
        self.assertEqual([s for s, _ in result["missing_list"]], ["NVDA", "JPM"])

    def test_empty_benchmark(self) -> None:
        empty = _write_csv(self.root / "empty.csv", ["Symbol", "Name"], [])
        result = audit(load_symbol_set(self.watch), load_benchmark_ordered(empty))
        self.assertEqual(result, {"total": 0, "covered": 0, "missing": 0,
                                  "coverage_pct": 0.0, "missing_list": []})


if __name__ == "__main__":
    unittest.main()
