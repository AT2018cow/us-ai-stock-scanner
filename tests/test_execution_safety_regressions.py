from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "safety_" + name.replace(".py", ""), module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plan_mod = _load_script("generate_trade_plan.py")
theme_mod = _load_script("theme_observation_scan.py")


class TestTradePlanReportPairSafety(unittest.TestCase):
    def _report(self, root: Path, stamp: str, style: str) -> None:
        outputs = root / "outputs"
        outputs.mkdir(exist_ok=True)
        (outputs / f"ai_value_scan_{stamp}_full_ranked_report.md").write_text(
            f"# report\n- Config: configs/config.{style}.json\n",
            encoding="utf-8",
        )

    def test_fresh_pair_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._report(root, "20261005T010000Z", "risk_off")
            self._report(root, "20261005T020000Z", "risk_on")
            old = Path.cwd()
            try:
                os.chdir(root)
                off, on = plan_mod.latest_scan_pair(
                    now=datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc),
                    max_age_hours=12.0,
                    max_pair_skew_hours=6.0,
                )
            finally:
                os.chdir(old)
            self.assertEqual(off, "20261005T010000Z")
            self.assertEqual(on, "20261005T020000Z")

    def test_mixed_batch_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._report(root, "20261005T010000Z", "risk_off")
            self._report(root, "20261004T120000Z", "risk_on")
            old = Path.cwd()
            try:
                os.chdir(root)
                with self.assertRaises(SystemExit):
                    plan_mod.latest_scan_pair(
                        now=datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc),
                        max_age_hours=48.0,
                        max_pair_skew_hours=6.0,
                    )
            finally:
                os.chdir(old)


class TestThemeFailurePropagation(unittest.TestCase):
    def test_partial_scan_failure_returns_nonzero(self) -> None:
        failed = type("Result", (), {"returncode": 1})()
        with mock.patch.object(sys, "argv", ["theme_observation_scan.py"]), mock.patch.object(
            theme_mod.subprocess, "run", return_value=failed
        ):
            with self.assertRaises(SystemExit) as ctx:
                theme_mod.main()
        self.assertEqual(ctx.exception.code, 1)


class TestParsedFundAccessionBinding(unittest.TestCase):
    def test_new_same_day_accession_bypasses_old_parsed_cache(self) -> None:
        from ai_value_scanner.scanner import (
            ScanConfig,
            _parsed_fund_cache_meta,
            load_one_fundamental,
        )

        class FakeSec:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get_submissions(self, cik: str):
                self.calls.append("submissions")
                return {
                    "sic": "3571",
                    "filings": {
                        "recent": {
                            "filingDate": ["2026-10-05"],
                            "accessionNumber": ["0000000001-26-000002"],
                        }
                    },
                }

            def get_companyfacts(self, cik: str):
                self.calls.append("facts")
                return {"facts": {}}

        with tempfile.TemporaryDirectory() as td:
            cik = "0000000001"
            cache = Path(td)
            config = ScanConfig(cache_dir=td)
            old_accn = "0000000001-26-000001"
            new_accn = "0000000001-26-000002"
            (cache / f"submissions_{cik}.json").write_text(
                json.dumps(
                    {
                        "filings": {
                            "recent": {
                                "filingDate": ["2026-10-05"],
                                "accessionNumber": [new_accn],
                            }
                        }
                    }
                )
            )
            (cache / f"facts_meta_{cik}.json").write_text(
                json.dumps({"covered_accession": old_accn, "pending_accession": None})
            )
            payload = {
                "symbol": "OLD",
                "revenue": 999.0,
                "_cache_meta": _parsed_fund_cache_meta(
                    config,
                    "2026-10-05",
                    old_accn,
                    old_accn,
                ),
            }
            (cache / f"parsed_fund_{cik}.json").write_text(json.dumps(payload))
            sec = FakeSec()
            result = load_one_fundamental(sec, "NEW", cik, config)
            self.assertIn("submissions", sec.calls)
            self.assertIn("facts", sec.calls)
            self.assertEqual(result["symbol"], "NEW")
            self.assertNotEqual(result.get("revenue"), 999.0)

    def test_legacy_facts_cache_detects_same_day_accession(self) -> None:
        from ai_value_scanner.scanner import SecClient

        with tempfile.TemporaryDirectory() as td:
            cik = "0000000010"
            cache = Path(td)
            accession = "0000000010-26-000009"
            (cache / f"submissions_{cik}.json").write_text(
                json.dumps(
                    {
                        "filings": {
                            "recent": {
                                "filingDate": ["2026-10-05"],
                                "accessionNumber": [accession],
                            }
                        }
                    }
                )
            )
            (cache / f"facts_{cik}.json").write_text(json.dumps({"version": "old"}))

            sec = object.__new__(SecClient)
            sec.cache_dir = cache
            sec.monitor = None
            hits: list[str] = []

            class Resp:
                status_code = 200
                text = json.dumps({"version": "new", "accn": accession})

                def json(self):
                    return {"version": "new", "accn": accession}

                def raise_for_status(self):
                    return None

            def fake_get(self, url):
                hits.append(url)
                return Resp()

            with mock.patch.object(SecClient, "_get", fake_get):
                result = sec.get_companyfacts(cik)

            self.assertEqual(result.get("version"), "new")
            self.assertEqual(len(hits), 1)
            meta = json.loads((cache / f"facts_meta_{cik}.json").read_text())
            self.assertEqual(meta.get("covered_accession"), accession)
            self.assertIsNone(meta.get("pending_accession"))


if __name__ == "__main__":
    unittest.main()
