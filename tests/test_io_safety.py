from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


def _load(name: str, relpath: str):
    module_path = Path(__file__).resolve().parents[1] / relpath
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {relpath}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner = _load("ai_value_scanner.scanner", "src/ai_value_scanner/scanner.py")
theme_obs = _load("theme_observation_scan", "scripts/theme_observation_scan.py")


class TestWriteCsvAtomic(unittest.TestCase):
    def test_roundtrip_identical(self) -> None:
        import tempfile

        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            scanner.write_csv_atomic(df, target)
            self.assertTrue(target.exists())
            self.assertTrue(df.equals(pd.read_csv(target)))
            leftovers = list(Path(tmp).glob(".out.csv.*.tmp"))
            self.assertEqual(leftovers, [])

    def test_overwrite_is_atomic(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            target.write_text("old,content\n1,2\n")
            scanner.write_csv_atomic(pd.DataFrame({"a": [9]}), target)
            self.assertEqual(pd.read_csv(target)["a"].tolist(), [9])


class TestArchiveCohort(unittest.TestCase):
    def _cohort(self, sym: str = "AAA") -> pd.DataFrame:
        return pd.DataFrame([{
            "theme": "quantum", "list_type": "low_value", "symbol": sym, "triage": "watch",
            "research_priority": "theme_only", "composite_score": 0.5,
            "entry_date": "2026-09-29", "entry_price": 10.0,
            "status": "open", "exit_date": "", "return_120d": "",
        }])

    def test_no_signal_writes_exactly_one_row(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "cohorts.csv"
            theme_obs.archive_cohort("quantum", pd.DataFrame(), csv_path, report=None)
            d = pd.read_csv(csv_path)
            self.assertEqual(len(d), 1)
            self.assertEqual(d.iloc[0]["status"], "no_signal")

    def test_no_signal_rerun_is_idempotent(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "cohorts.csv"
            theme_obs.archive_cohort("quantum", pd.DataFrame(), csv_path, report=None)
            theme_obs.archive_cohort("quantum", pd.DataFrame(), csv_path, report=None)
            d = pd.read_csv(csv_path)
            self.assertEqual(len(d), 1)

    def test_normal_append_dedupes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "cohorts.csv"
            theme_obs.archive_cohort("quantum", self._cohort(), csv_path, report=None)
            theme_obs.archive_cohort("quantum", self._cohort(), csv_path, report=None)
            d = pd.read_csv(csv_path)
            self.assertEqual(len(d), 1)
            self.assertEqual(d.iloc[0]["symbol"], "AAA")


if __name__ == "__main__":
    unittest.main()
