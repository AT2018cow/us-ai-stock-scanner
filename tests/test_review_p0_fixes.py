# Failing-first tests for the 2026-10-03 review P0 calculation fixes.
#
# Each test encodes an independently verified correct answer (see
# docs/design_and_calculation_review_20261003.md): C01 adjusted_ebitda
# double-count, C02 backtest YoY basis, C04 level-series report-period
# selection, C05 backtest non-recurring adjustments, C06 backtest ai_link
# weights, D01 parsed-fund cache binding, D02 same-day facts refresh.
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ai_value_scanner.scanner import (
    REVENUE_TAGS,
    QUARTERLY_FORMS,
    ScanConfig,
    SecClient,
    pick_latest_and_prev_ttm,
)
from ai_value_scanner.backtest import (
    build_flow_ttm_or_annual_series,
    build_level_series,
    extract_metric_points,
    latest_and_year_ago_flow,
    latest_and_year_ago_level,
    series_value_asof,
    compute_adjusted_metrics,
    compute_ai_link_score,
)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestC01AdjustedEbitda(unittest.TestCase):
    def test_adjustment_counted_once(self):
        fixture = _load("p0_fixture", str(Path(__file__).parent / "test_gap12_metrics.py"))
        sec = fixture._FakeSecClient(
            {"sic": "3571", "sicDescription": "Electronic Computers"},
            fixture._build_companyfacts_ttm_full(),
        )
        from ai_value_scanner.scanner import load_one_fundamental

        with tempfile.TemporaryDirectory() as cache_dir:
            result = load_one_fundamental(
                sec, "REVIEW", "9999999999", ScanConfig(cache_dir=cache_dir)
            )
        self.assertEqual(
            result["adjusted_ebitda"],
            result["adjusted_ebit"] + result["depreciation_and_amortization"],
        )
        # Fixture: EBIT=250, D&A=58, addback=8, gain=2 → 250+58+8-2 = 314.
        self.assertEqual(result["adjusted_ebitda"], 314.0)


class TestC04LevelSeries(unittest.TestCase):
    def _points(self, first_end: str, second_end: str) -> list[dict]:
        return [
            {
                "visible": pd.Timestamp("2025-02-01", tz="UTC"),
                "end": pd.Timestamp(first_end, tz="UTC"),
                "value": 80.0,
            },
            {
                "visible": pd.Timestamp("2025-02-01", tz="UTC"),
                "end": pd.Timestamp(second_end, tz="UTC"),
                "value": 100.0,
            },
        ]

    def test_same_visibility_prefers_latest_report_period(self):
        # Same disclosure date carries the prior-year comparative (end 2023,
        # value 80) and the current period (end 2024, value 100). The latest
        # report period must win regardless of input order.
        for order in ("old_first", "new_first"):
            if order == "old_first":
                points = self._points("2023-12-31", "2024-12-31")
            else:
                points = list(reversed(self._points("2023-12-31", "2024-12-31")))
            series = build_level_series(points)
            self.assertEqual(len(series), 1, msg=order)
            self.assertEqual(series[0][1], 100.0, msg=order)


class TestC02ReplayYoY(unittest.TestCase):
    def _facts(self) -> dict:
        entries = []
        for year, value in [(2024, 25.0), (2025, 30.0)]:
            for quarter in range(1, 5):
                start = pd.Timestamp(year=year, month=3 * quarter - 2, day=1)
                end = start + pd.offsets.QuarterEnd()
                entries.append(
                    {
                        "start": str(start.date()),
                        "end": str(end.date()),
                        "filed": str((end + pd.Timedelta(days=35)).date()),
                        "val": value,
                        "form": "10-Q",
                    }
                )
        return {"facts": {"us-gaap": {REVENUE_TAGS[0]: {"units": {"USD": entries}}}}}

    def test_replay_year_ago_matches_scan(self):
        facts = self._facts()
        series = build_flow_ttm_or_annual_series(
            extract_metric_points(facts, REVENUE_TAGS, "USD", QUARTERLY_FORMS)
        )
        latest, year_ago = latest_and_year_ago_flow(
            series, pd.Timestamp("2026-03-01", tz="UTC")
        )
        self.assertEqual((latest, year_ago), (120.0, 100.0))
        # Cross-path consistency with the scanner's own YoY base selection.
        scan_latest, scan_prev = pick_latest_and_prev_ttm(facts, REVENUE_TAGS, "USD")
        self.assertEqual((scan_latest, scan_prev), (120.0, 100.0))

    def test_missing_year_ago_is_none_not_adjacent(self):
        # Only two quarters of history: no TTM ends ~365 days before the
        # latest, so the YoY base must be missing (not the adjacent window).
        entries = []
        for quarter in range(1, 3):
            start = pd.Timestamp(year=2025, month=3 * quarter - 2, day=1)
            end = start + pd.offsets.QuarterEnd()
            entries.append(
                {
                    "start": str(start.date()),
                    "end": str(end.date()),
                    "filed": str((end + pd.Timedelta(days=35)).date()),
                    "val": 10.0,
                    "form": "10-Q",
                }
            )
        facts = {"facts": {"us-gaap": {REVENUE_TAGS[0]: {"units": {"USD": entries}}}}}
        series = build_flow_ttm_or_annual_series(
            extract_metric_points(facts, REVENUE_TAGS, "USD", QUARTERLY_FORMS)
        )
        latest, year_ago = latest_and_year_ago_flow(
            series, pd.Timestamp("2026-03-01", tz="UTC")
        )
        self.assertIsNone(year_ago)


class TestLevelYearAgo(unittest.TestCase):
    def test_prefers_point_at_least_300_days_old(self):
        series = [
            (pd.Timestamp("2026-06-01", tz="UTC"), 120.0, pd.Timestamp("2026-03-31", tz="UTC")),
            (pd.Timestamp("2025-06-01", tz="UTC"), 110.0, pd.Timestamp("2025-03-31", tz="UTC")),
            (pd.Timestamp("2024-06-01", tz="UTC"), 100.0, pd.Timestamp("2024-03-31", tz="UTC")),
        ]
        latest, year_ago = latest_and_year_ago_level(series, pd.Timestamp("2026-07-01", tz="UTC"))
        self.assertEqual(latest, 120.0)
        # Newest point whose report period is ≥300 days older than the
        # latest report period (mirrors the scanner's level semantics).
        self.assertEqual(year_ago, 110.0)

    def test_legacy_two_tuple_entries_fall_back_to_adjacent(self):
        series = [
            (pd.Timestamp("2026-01-05", tz="UTC"), 140.0),
            (pd.Timestamp("2026-01-02", tz="UTC"), 120.0),
        ]
        latest, prev = latest_and_year_ago_level(series, pd.Timestamp("2026-02-01", tz="UTC"))
        self.assertEqual((latest, prev), (140.0, 120.0))

    def test_series_value_asof_generic(self):
        series = [
            (pd.Timestamp("2026-01-02", tz="UTC"), 10.0, pd.Timestamp("2025-12-31", tz="UTC")),
            (pd.Timestamp("2026-02-02", tz="UTC"), 12.0, pd.Timestamp("2026-01-31", tz="UTC")),
        ]
        value, end = series_value_asof(series, pd.Timestamp("2026-02-01", tz="UTC"))
        self.assertEqual((value, end.day), (10.0, 31))


class TestC05AdjustedMetrics(unittest.TestCase):
    def test_adjustment_applied_once_with_cap(self):
        out = compute_adjusted_metrics(
            net_income=100.0,
            ebit=250.0,
            da=58.0,
            revenue=120.0,
            revenue_prev=100.0,
            addback=25.0,
            gain=2.0,
            addback_prev=10.0,
            gain_prev=0.0,
            cap_ratio=0.25,
        )
        # Cap limit latest = 0.25*120 = 30 (25 < 30 → uncapped); prev limit 25.
        self.assertEqual(out["adjusted_net_income"], 123.0)
        self.assertEqual(out["adjusted_ebit"], 273.0)
        # C01 semantics: adjustment already inside adjusted_ebit, raw D&A added.
        self.assertEqual(out["adjusted_ebitda"], 273.0 + 58.0)

    def test_prev_adjustment(self):
        out = compute_adjusted_metrics(
            net_income=100.0,
            ebit=250.0,
            da=58.0,
            revenue=120.0,
            revenue_prev=100.0,
            addback=25.0,
            gain=2.0,
            addback_prev=10.0,
            gain_prev=0.0,
            cap_ratio=0.25,
            net_income_prev=100.0,
            ebit_prev=250.0,
        )
        self.assertEqual(out["adjusted_net_income_prev"], 110.0)
        self.assertEqual(out["adjusted_ebit_prev"], 260.0)

    def test_cap_binds(self):
        out = compute_adjusted_metrics(
            net_income=100.0,
            ebit=250.0,
            da=0.0,
            revenue=120.0,
            revenue_prev=100.0,
            addback=50.0,
            gain=0.0,
            addback_prev=0.0,
            gain_prev=0.0,
            cap_ratio=0.25,
        )
        self.assertEqual(out["adjusted_net_income"], 100.0 + 30.0)

    def test_none_inputs_stay_none(self):
        out = compute_adjusted_metrics(
            net_income=None,
            ebit=None,
            da=None,
            revenue=120.0,
            revenue_prev=None,
            addback=25.0,
            gain=2.0,
            addback_prev=None,
            gain_prev=None,
            cap_ratio=None,
        )
        self.assertIsNone(out["adjusted_net_income"])
        self.assertIsNone(out["adjusted_ebit"])
        self.assertIsNone(out["adjusted_ebitda"])


class TestC06AiLinkWeights(unittest.TestCase):
    def test_default_weights_match_scan_formula(self):
        config = ScanConfig()
        score = compute_ai_link_score(
            config,
            ai_etf_score=1.0,
            ai_disclosure_score=1.0,
            ai_market_score=1.0,
            ai_backlog_signal=1.0,
        )
        self.assertEqual(score, 1.0)
        self.assertAlmostEqual(
            score,
            float(
                config.ai_link_weight_etf_consensus
                + config.ai_link_weight_disclosure
                + config.ai_link_weight_market_link
                + config.ai_link_weight_backlog
            ),
        )

    def test_zeroed_disclosure_weight_removes_component(self):
        config = ScanConfig()
        base = compute_ai_link_score(
            config,
            ai_etf_score=0.0,
            ai_disclosure_score=0.5,
            ai_market_score=0.0,
            ai_backlog_signal=0.0,
        )
        self.assertAlmostEqual(base, 0.5 * float(config.ai_link_weight_disclosure))
        config.ai_link_weight_disclosure = 0.0
        zeroed = compute_ai_link_score(
            config,
            ai_etf_score=0.0,
            ai_disclosure_score=0.5,
            ai_market_score=0.0,
            ai_backlog_signal=0.0,
        )
        self.assertEqual(zeroed, 0.0)


class TestD01ParsedCacheBinding(unittest.TestCase):
    def _fake_sec(self, calls: list[str]):
        class FakeSec:
            def get_submissions(self, cik):
                calls.append("submissions")
                return {"sic": "3571", "filings": {"recent": {"filingDate": ["2026-10-01"]}}}

            def get_companyfacts(self, cik):
                calls.append("facts")
                return {"facts": {}}

        return FakeSec()

    def test_stale_config_cache_misses_and_recomputes(self):
        from ai_value_scanner.scanner import load_one_fundamental

        with tempfile.TemporaryDirectory() as cache_dir:
            cik = "0000000001"
            subs = {"filings": {"recent": {"filingDate": ["2026-10-01"]}}}
            (Path(cache_dir) / f"submissions_{cik}.json").write_text(json.dumps(subs))
            stale = {
                "symbol": "OLD",
                "revenue": 120.0,
                "revenue_form": "ttm",
                "nonrecurring_expense_addback": 25.0,
                "_cache_meta": {"v": 1, "cfg": {}, "latest_filing": "2026-10-01"},
            }
            (Path(cache_dir) / f"parsed_fund_{cik}.json").write_text(json.dumps(stale))
            calls: list[str] = []
            config = ScanConfig(
                cache_dir=cache_dir,
                use_ttm_metrics=False,
                nonrecurring_addback_revenue_cap=0.0,
            )
            result = load_one_fundamental(self._fake_sec(calls), "NEW", cik, config)
            # Config mismatch must force a recompute (slow path), not serve
            # the stale TTM/addback values.
            self.assertIn("submissions", calls)
            self.assertIn("facts", calls)
            self.assertEqual(result["symbol"], "NEW")
            self.assertNotEqual(result.get("revenue"), 120.0)

    def test_matching_config_cache_hits(self):
        from ai_value_scanner.scanner import (
            load_one_fundamental,
            _parsed_fund_cache_meta,
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            cik = "0000000002"
            filing = "2026-10-01"
            subs = {"filings": {"recent": {"filingDate": [filing]}}}
            (Path(cache_dir) / f"submissions_{cik}.json").write_text(json.dumps(subs))
            config = ScanConfig(cache_dir=cache_dir)
            meta = _parsed_fund_cache_meta(config, filing)
            cached = {"symbol": "OLD", "revenue": 120.0, "_cache_meta": meta}
            (Path(cache_dir) / f"parsed_fund_{cik}.json").write_text(json.dumps(cached))
            calls: list[str] = []
            result = load_one_fundamental(self._fake_sec(calls), "NEW", cik, config)
            self.assertEqual(calls, [])
            self.assertEqual(result["revenue"], 120.0)
            self.assertNotIn("_cache_meta", result)


class TestD02FactsRefresh(unittest.TestCase):
    def _make_sec(self, cache_dir: str):
        from ai_value_scanner.scanner import SecClient

        sec = object.__new__(SecClient)
        sec.cache_dir = Path(cache_dir)
        sec.monitor = None
        return sec

    def _write_cache(self, cache_dir: str, cik: str, facts: dict, meta: dict | None):
        (Path(cache_dir) / f"facts_{cik}.json").write_text(json.dumps(facts))
        if meta is not None:
            (Path(cache_dir) / f"facts_meta_{cik}.json").write_text(json.dumps(meta))

    def _write_subs(self, cache_dir: str, cik: str, accession: str):
        subs = {
            "filings": {
                "recent": {
                    "filingDate": ["2026-10-02"],
                    "accessionNumber": [accession],
                }
            }
        }
        (Path(cache_dir) / f"submissions_{cik}.json").write_text(json.dumps(subs))

    def _patch_get(self, payload: dict, hits: list[str]):
        class Resp:
            status_code = 200

            def __init__(self):
                self.text = json.dumps(payload)

            def json(self):
                return payload

            def raise_for_status(self):
                return None

        def fake_get(self, url):
            hits.append(url)
            return Resp()

        return patch.object(SecClient, "_get", fake_get)

    def test_new_accession_triggers_refresh(self):
        cik = "0000000010"
        with tempfile.TemporaryDirectory() as cache_dir:
            self._write_subs(cache_dir, cik, "0000000000-26-000009")
            self._write_cache(
                cache_dir,
                cik,
                {"version": "old"},
                {"covered_accession": "0000000000-26-000001", "pending_accession": None},
            )
            sec = self._make_sec(cache_dir)
            hits: list[str] = []
            with self._patch_get({"version": "new", "accn": "0000000000-26-000009"}, hits):
                payload = sec.get_companyfacts(cik)
            self.assertEqual(payload.get("version"), "new")
            self.assertEqual(len(hits), 1)
            # Second call: accession now covered → cache hit, no fetch.
            with self._patch_get({"version": "newer"}, hits):
                payload = sec.get_companyfacts(cik)
            self.assertEqual(payload.get("version"), "new")
            self.assertEqual(len(hits), 1)

    def test_facts_lag_keeps_pending_state(self):
        cik = "0000000011"
        with tempfile.TemporaryDirectory() as cache_dir:
            self._write_subs(cache_dir, cik, "0000000000-26-000009")
            self._write_cache(
                cache_dir,
                cik,
                {"version": "old"},
                {"covered_accession": "0000000000-26-000001", "pending_accession": None},
            )
            sec = self._make_sec(cache_dir)
            hits: list[str] = []
            # Fetched payload does NOT contain the new accession yet.
            with self._patch_get({"version": "old"}, hits):
                sec.get_companyfacts(cik)
            meta = json.loads((Path(cache_dir) / f"facts_meta_{cik}.json").read_text())
            self.assertEqual(meta.get("pending_accession"), "0000000000-26-000009")
            # Next call retries while pending.
            with self._patch_get({"version": "old2"}, hits):
                sec.get_companyfacts(cik)
            self.assertEqual(len(hits), 2)
            # Facts API catches up → pending clears and the next call hits.
            with self._patch_get(
                {"version": "old3", "accn": "0000000000-26-000009"}, hits
            ):
                sec.get_companyfacts(cik)
            with self._patch_get({"version": "never"}, hits):
                payload = sec.get_companyfacts(cik)
            self.assertEqual(payload.get("version"), "old3")
            self.assertEqual(len(hits), 3)


if __name__ == "__main__":
    unittest.main()
