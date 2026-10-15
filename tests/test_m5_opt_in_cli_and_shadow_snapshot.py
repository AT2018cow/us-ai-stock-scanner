from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ai_value_scanner.config import ScanConfig
from ai_value_scanner.decision.integrated import (
    build_stock_decisions,
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.reporting.snapshot import write_decision_snapshot
from ai_value_scanner.scanner import build_parser


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "MU",
                "company_name": "Micron Technology",
                "fundamental_data_asof": "2026-10-09",
                "market_asof": "2026-10-09",
                "revenue": 40_000_000_000.0,
                "free_cash_flow": 8_000_000_000.0,
                "ebit": 10_000_000_000.0,
                "adjusted_ebit": 10_500_000_000.0,
                "net_margin": 0.25,
                "ocf_to_net_income": 1.15,
                "accrual_ratio": -0.18,
                "revenue_yoy": 0.85,
                "adjusted_net_income_yoy": 1.20,
                "operating_cash_flow_yoy": 0.95,
                "net_debt_to_ebitda": 0.20,
                "interest_coverage": 25.0,
                "current_ratio": 2.8,
                "shares_yoy": 0.01,
                "fcf_yield": 0.04,
                "ps_hist_percentile": 0.85,
                "pe_hist_percentile": 0.40,
                "receivables_growth_gap": 0.45,
                "inventory_growth_gap": 0.05,
                "price_to_sma200": 1.25,
                "price_to_sma50": 1.04,
                "days_below_sma200": 0,
                "return_20d": 0.05,
                "return_60d": 0.18,
                "drawdown_from_52w_high": 0.08,
                "range_position_52w": 0.85,
                "relative_strength_60d_qqq": 0.10,
                "volatility_60d": 0.35,
                "regime": "up",
                "benchmark_trend_ok": True,
            }
        ]
    )


class TestM5OptInCliAndShadowSnapshot(unittest.TestCase):
    def test_scan_config_defaults_and_validation(self) -> None:
        cfg = ScanConfig()
        self.assertEqual(cfg.decision_policy_version, "v1")
        self.assertEqual(cfg.report_layout_version, "v1")
        self.assertFalse(cfg.enable_v2_shadow)
        cfg.validate()

        bad_policy = ScanConfig(decision_policy_version="v3")
        with self.assertRaises(ValueError):
            bad_policy.validate()

        bad_layout = ScanConfig(report_layout_version="v0")
        with self.assertRaises(ValueError):
            bad_layout.validate()

    def test_cli_parser_opt_in_flags(self) -> None:
        parser = build_parser()
        default_args = parser.parse_args([])
        self.assertIsNone(default_args.decision_policy_version)
        self.assertIsNone(default_args.report_layout_version)
        self.assertFalse(default_args.enable_v2_shadow)

        v2_args = parser.parse_args(
            [
                "--decision-policy-version",
                "v2",
                "--report-layout-version",
                "v2",
                "--enable-v2-shadow",
            ]
        )
        self.assertEqual(v2_args.decision_policy_version, "v2")
        self.assertEqual(v2_args.report_layout_version, "v2")
        self.assertTrue(v2_args.enable_v2_shadow)

    def test_v1_and_v2_shadow_snapshots_write_cleanly(self) -> None:
        df = _sample_df()
        decs_v1 = build_stock_decisions(
            df,
            decision_date="2026-10-09",
            generated_at_utc="2026-10-09T23:59:59+00:00",
            policy_version="v1",
        )
        decs_v2 = build_stock_decisions(
            df,
            decision_date="2026-10-09",
            generated_at_utc="2026-10-09T23:59:59+00:00",
            policy_version="v2",
        )
        # Under v1, MU is downgraded to B by receivables_growth_gap=0.45 (>0.30 severe check);
        # under v2, high-growth cash-generative exemption promotes MU to A / PRIORITY_REVIEW.
        self.assertEqual(decs_v1[0].quality.grade.value, "B")
        self.assertEqual(decs_v1[0].action_state.value, "HOLD_MONITOR")
        self.assertEqual(decs_v2[0].quality.grade.value, "A")
        self.assertEqual(decs_v2[0].action_state.value, "PRIORITY_REVIEW")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths_v1 = write_decision_snapshot(
                output_root=root,
                strategy_style="risk_off",
                decisions=decs_v1,
                daily_attention=select_daily_attention(decs_v1),
                weekly_attention=select_weekly_attention(decs_v1),
                generated_at_utc="2026-10-09T23:59:59+00:00",
                decision_date="2026-10-09",
                config_fingerprint="abc123",
                code_sha="deadbeef",
                policy_version="v1",
                layout_version="v1",
            )
            paths_v2 = write_decision_snapshot(
                output_root=root,
                strategy_style="risk_off_shadow_v2",
                decisions=decs_v2,
                daily_attention=select_daily_attention(decs_v2),
                weekly_attention=select_weekly_attention(decs_v2),
                generated_at_utc="2026-10-09T23:59:59+00:00",
                decision_date="2026-10-09",
                config_fingerprint="abc123",
                code_sha="deadbeef",
                policy_version="v2",
                layout_version="v2",
            )

            manifest_v1 = json.loads(paths_v1.run_manifest_json.read_text(encoding="utf-8"))
            manifest_v2 = json.loads(paths_v2.run_manifest_json.read_text(encoding="utf-8"))
            self.assertNotIn("decision_policy_version", manifest_v1)
            self.assertEqual(manifest_v2["decision_policy_version"], "v2")
            self.assertEqual(manifest_v2["report_layout_version"], "v2")

            action_md_v2 = paths_v2.action_list_md.read_text(encoding="utf-8")
            self.assertIn("<details>", action_md_v2)
            self.assertIn("#1 MU", action_md_v2)
            detailed_mu_v2 = (paths_v2.detailed_dir / "MU.md").read_text(encoding="utf-8")
            self.assertIn("Company Quality — 6-Pillar Scorecard", detailed_mu_v2)
            self.assertIn("Entry Quality — 7-Gate Readiness Checklist", detailed_mu_v2)

    def test_production_configs_default_to_v2_and_12h_alpaca_ttl(self) -> None:
        from ai_value_scanner.scanner import load_config

        for path in (
            "configs/config.risk_off.json",
            "configs/config.risk_on.json",
            "configs/config.strict_candidate.json",
        ):
            cfg = load_config(path)
            self.assertEqual(cfg.decision_policy_version, "v2", path)
            self.assertEqual(cfg.report_layout_version, "v2", path)
            self.assertEqual(cfg.alpaca_cache_ttl_snapshots_sec, 43200, path)
            self.assertEqual(cfg.alpaca_cache_ttl_bars_sec, 43200, path)
            self.assertEqual(cfg.alpaca_cache_ttl_assets_sec, 43200, path)

    def test_edgartools_fallback_and_terminal_pending_persist_to_parsed_cache(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from ai_value_scanner import scanner

        cik = "0000004904"
        accn = "0000004904-26-000059"
        subs = {
            "sic": "4911",
            "sicDescription": "ELECTRIC SERVICES",
            "tickers": ["AEP"],
            "filings": {
                "recent": {
                    "form": ["10-Q", "10-Q", "10-K"],
                    "filingDate": ["2026-07-30", "2026-05-05", "2026-02-12"],
                    "accessionNumber": [accn, "0000004904-26-000034", "0000004904-26-000013"],
                }
            },
        }
        old_facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"start": "2025-07-01", "end": "2025-09-30", "val": 100.0, "filed": "2025-10-29", "accn": "q3-25", "form": "10-Q"},
                                {"start": "2025-10-01", "end": "2025-12-31", "val": 100.0, "filed": "2026-02-12", "accn": "q4-25", "form": "10-K"},
                                {"start": "2026-01-01", "end": "2026-03-31", "val": 100.0, "filed": "2026-05-05", "accn": "0000004904-26-000034", "form": "10-Q"},
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {"start": "2025-07-01", "end": "2025-09-30", "val": 20.0, "filed": "2025-10-29", "accn": "q3-25", "form": "10-Q"},
                                {"start": "2025-10-01", "end": "2025-12-31", "val": 20.0, "filed": "2026-02-12", "accn": "q4-25", "form": "10-K"},
                                {"start": "2026-01-01", "end": "2026-03-31", "val": 20.0, "filed": "2026-05-05", "accn": "0000004904-26-000034", "form": "10-Q"},
                            ]
                        }
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "units": {
                            "USD": [
                                {"start": "2025-07-01", "end": "2025-09-30", "val": 30.0, "filed": "2025-10-29", "accn": "q3-25", "form": "10-Q"},
                                {"start": "2025-10-01", "end": "2025-12-31", "val": 30.0, "filed": "2026-02-12", "accn": "q4-25", "form": "10-K"},
                                {"start": "2026-01-01", "end": "2026-03-31", "val": 30.0, "filed": "2026-05-05", "accn": "0000004904-26-000034", "form": "10-Q"},
                            ]
                        }
                    },
                }
            }
        }
        patch_payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [{"start": "2026-04-01", "end": "2026-06-30", "val": 120.0, "filed": "2026-07-30", "accn": accn, "form": "10-Q"}]}},
                    "NetIncomeLoss": {"units": {"USD": [{"start": "2026-04-01", "end": "2026-06-30", "val": 25.0, "filed": "2026-07-30", "accn": accn, "form": "10-Q"}]}},
                    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"start": "2026-04-01", "end": "2026-06-30", "val": 35.0, "filed": "2026-07-30", "accn": accn, "form": "10-Q"}]}},
                }
            }
        }

        class _FakeSec:
            def __init__(self, cache_dir: Path) -> None:
                self.cache_dir = cache_dir
                self.calls: list[str] = []

            def ticker_map_snapshot(self):
                return {"sha256": "map-sha-1"}

            def get_submissions(self, c: str):
                self.calls.append("submissions")
                (self.cache_dir / f"submissions_{c}.json").write_text(json.dumps(subs))
                return subs

            def get_companyfacts(self, c: str):
                self.calls.append("facts")
                (self.cache_dir / f"facts_{c}.json").write_text(json.dumps(old_facts))
                (self.cache_dir / f"facts_meta_{c}.json").write_text(
                    json.dumps({"covered_accession": None, "pending_accession": accn})
                )
                return json.loads(json.dumps(old_facts))

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            cfg = ScanConfig(cache_dir=tmp, sec_cache_ttl_submissions_sec=86400)
            sec = _FakeSec(cache_dir)
            fb_res = SimpleNamespace(status="used", used=True, patch=patch_payload)
            with patch.object(scanner, "fetch_usd_10q_companyfacts_patch", return_value=fb_res) as fb_mock:
                first = scanner.load_one_fundamental(sec, "AEP", cik, cfg, force_refresh_parsed=True)
                self.assertTrue(first["fundamental_edgartools_fallback_used"])
                self.assertEqual(fb_mock.call_count, 1)
                # Verify both cron validator (max_age_sec=72000) and scan validator (max_age_sec=None) hit cache!
                cron_hit = scanner.load_valid_parsed_fundamental_cache(sec, "AEP", cik, cfg, max_age_sec=72000)
                self.assertIsNotNone(cron_hit)
                sec.calls.clear()
                second = scanner.load_one_fundamental(sec, "AEP", cik, cfg)
                self.assertEqual(sec.calls, [])
                self.assertEqual(fb_mock.call_count, 1)
                self.assertEqual(second["revenue"], 420.0)


if __name__ == "__main__":
    unittest.main()
