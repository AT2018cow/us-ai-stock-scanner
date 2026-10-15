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


if __name__ == "__main__":
    unittest.main()
