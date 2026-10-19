"""Observation scanner report-discovery tests (offline, synthetic files).

Covers the two-style observation summary lookup: report globs must accept
both ``full`` and capped/``sample*`` scopes, include the monthly archive
tree (``outputs/scans/<YYYY-MM>/``, README §8.1), order newest-first, and
pick one report per style via the report's ``Config:`` header (so theme
reports can never be mislabelled as a style report).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "obs_" + name.replace(".py", ""), module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


obs = _load_script("observation_scan.py")


def _write(path: Path, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n\n# synthetic report body\n", encoding="utf-8")


class TestReportDiscovery(unittest.TestCase):
    def test_finds_full_and_sample_scope_reports(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            full = (
                root / "outputs"
                / "ai_value_scan_20261018T030503Z_full_ranked_report.md"
            )
            sample = (
                root / "outputs"
                / "ai_value_scan_20261019T202159Z_sample100_ranked_report.md"
            )
            _write(full, "- Config: configs/config.risk_off.json")
            _write(sample, "- Config: configs/config.risk_on.json")
            os.utime(full, (1_000, 1_000))
            os.utime(sample, (2_000, 2_000))
            paths = obs._recent_report_paths(root)
            self.assertEqual(len(paths), 2)
            self.assertTrue(paths[0].endswith(sample.name))  # newest first

    def test_finds_monthly_archived_reports(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archived = (
                root / "outputs" / "scans" / "2026-10"
                / "ai_value_scan_20261019T202159Z_sample100_ranked_report.md"
            )
            _write(archived, "- Config: configs/config.risk_off.json")
            paths = obs._recent_report_paths(root)
            self.assertEqual(len(paths), 1)
            self.assertIn("scans", paths[0])

    def test_ignores_non_report_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "outputs"
                / "ai_value_scan_20261019T000000Z_sample100_ranked.csv",
                "- Config: configs/config.risk_off.json",
            )
            self.assertEqual(obs._recent_report_paths(root), [])

    def test_pick_reports_by_style_uses_config_header(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            off = (
                root / "outputs"
                / "ai_value_scan_20261019T202159Z_sample100_ranked_report.md"
            )
            on = (
                root / "outputs"
                / "ai_value_scan_20261019T202311Z_sample100_ranked_report.md"
            )
            theme = (
                root / "outputs"
                / "ai_value_scan_20261019T230000Z_full_ranked_report.md"
            )
            _write(off, "- Config: configs/config.risk_off.json")
            _write(on, "- Config: configs/config.risk_on.json")
            _write(theme, "- Config: configs/config.theme.biotech.json")
            os.utime(off, (1_000, 1_000))
            os.utime(on, (2_000, 2_000))
            os.utime(theme, (3_000, 3_000))
            picked = obs._pick_reports_by_style(obs._recent_report_paths(root))
            self.assertEqual(set(picked), {"risk_off", "risk_on"})
            self.assertTrue(picked["risk_off"].endswith(off.name))
            self.assertTrue(picked["risk_on"].endswith(on.name))

    def test_pick_reports_newest_wins_per_style(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            older = (
                root / "outputs"
                / "ai_value_scan_20261018T030503Z_full_ranked_report.md"
            )
            newer = (
                root / "outputs" / "scans" / "2026-10"
                / "ai_value_scan_20261019T202159Z_sample100_ranked_report.md"
            )
            _write(older, "- Config: configs/config.risk_off.json")
            _write(newer, "- Config: configs/config.risk_off.json")
            os.utime(older, (1_000, 1_000))
            os.utime(newer, (2_000, 2_000))
            picked = obs._pick_reports_by_style(obs._recent_report_paths(root))
            self.assertTrue(picked["risk_off"].endswith(newer.name))

    def test_pick_reports_skips_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing = str(
                Path(td) / "outputs"
                / "ai_value_scan_missing_ranked_report.md"
            )
            self.assertEqual(obs._pick_reports_by_style([missing]), {})


if __name__ == "__main__":
    unittest.main()
