"""A02 contract tests: isolated data adapter -> decisions -> snapshot -> validator -> cron.

No network, no credentials: a synthetic fundamental/market row stands in for
the scanner data adapter, and the real canonical decision builders, snapshot
writer, validator, pointer writer, and cron status handling are exercised as
one chain.
"""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ai_value_scanner.decision import (
    build_stock_decisions,
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.reporting.snapshot import write_decision_snapshot
from ai_value_scanner.scanner import (
    ScanRunStatus,
    _evaluate_existing_snapshot_reuse,
    write_latest_decision_pointer,
)

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    import run_daily_cron as rdc
    from validate_mvp_snapshot import validate_snapshot
finally:
    sys.path.pop(0)


ROW = dict(
    symbol="AAA",
    company_name="Synthetic AAA",
    fundamental_data_asof="2026-08-01",
    market_asof="2026-10-09",
    revenue=1000.0,
    net_margin=0.25,
    free_cash_flow=200.0,
    adjusted_ebit=250.0,
    ocf_to_net_income=1.2,
    accrual_ratio=-0.05,
    revenue_yoy=0.20,
    adjusted_net_income_yoy=0.20,
    operating_cash_flow_yoy=0.20,
    net_debt_to_ebitda=0.0,
    net_debt_to_ebitda_source="reported",
    interest_coverage=10.0,
    current_ratio=2.0,
    shares_yoy=0.0,
    fcf_yield=0.06,
    ps_hist_percentile=0.20,
    pe_hist_percentile=0.30,
    receivables_growth_gap=0.0,
    inventory_growth_gap=0.0,
    price_to_sma200=1.05,
    price_to_sma50=1.03,
    days_below_sma200=0,
    return_20d=0.05,
    return_60d=0.10,
    drawdown_from_52w_high=0.08,
    range_position_52w=0.82,
    relative_strength_60d_qqq=0.04,
    volatility_60d=0.35,
    regime="up",
    benchmark_trend_ok=True,
)


def _build_frame_decision(**changes):
    row = {**ROW, **changes}
    decisions = build_stock_decisions(
        pd.DataFrame([row]),
        decision_date="2026-10-09",
        generated_at_utc="2026-10-18T12:00:00+00:00",
        policy_version="v2",
    )
    return decisions


def _write_pipeline_snapshot(root: Path):
    decisions = _build_frame_decision()
    paths = write_decision_snapshot(
        output_root=root,
        strategy_style="risk_off",
        decisions=decisions,
        daily_attention=select_daily_attention(decisions, cap=15),
        weekly_attention=select_weekly_attention(decisions, cap=15),
        generated_at_utc="2026-10-18T12:00:00+00:00",
        decision_date="2026-10-09",
        config_fingerprint="synthetic-audit",
        policy_version="v2",
        layout_version="v2",
    )
    return decisions, paths


class EndToEndContractTests(unittest.TestCase):
    def test_isolated_pipeline_validates_and_publishes_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            decisions, paths = _write_pipeline_snapshot(Path(tmp))
            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["counts"]["action"]["PRIORITY_REVIEW"], 1)

            pointer_path = write_latest_decision_pointer(
                Path(tmp),
                decision_date="2026-10-09",
                strategy_style="risk_off",
                policy_version="v2",
                layout_version="v2",
            )
            import json

            payload = json.loads(pointer_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["decision_policy_version"], "v2")
            self.assertEqual(payload["snapshot_dir"], "2026-10-09/risk_off")
            self.assertIn("quality_policy_version", payload)
            self.assertIn("entry_policy_version", payload)

    def test_stage_policy_drift_blocks_same_day_reuse(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            _, paths = _write_pipeline_snapshot(Path(tmp))
            status, error = _evaluate_existing_snapshot_reuse(
                paths.root,
                decision_date="2026-10-09",
                strategy_style="risk_off",
                policy_version="v2",
                layout_version="v2",
            )
            self.assertEqual(status, "reused")
            self.assertIsNone(error)

            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            manifest["quality_policy_version"] = "company_quality_v2_2026-10-15"
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            status, error = _evaluate_existing_snapshot_reuse(
                paths.root,
                decision_date="2026-10-09",
                strategy_style="risk_off",
                policy_version="v2",
                layout_version="v2",
            )
            self.assertEqual(status, "reused_version_mismatch")
            self.assertIn("reusing it would mix evidence", error or "")

    def test_cron_reports_success_only_when_pipeline_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)

            def fake_scan(scan_cfg, **kwargs):
                _, paths = _write_pipeline_snapshot(tmp_root)
                result = validate_snapshot(paths.root)
                pointer_path = write_latest_decision_pointer(
                    tmp_root,
                    decision_date="2026-10-09",
                    strategy_style="risk_off",
                    policy_version="v2",
                    layout_version="v2",
                )
                return ScanRunStatus(
                    output_path=tmp_root / "ranked.csv",
                    report_path=tmp_root / "report.md",
                    decision_snapshot_root=paths.root,
                    decision_output_status="written" if result["ok"] else "failed",
                    decision_output_error=None if result["ok"] else "; ".join(result["errors"]),
                    latest_pointer_status="written" if pointer_path else "failed",
                    latest_pointer_error=None,
                    shadow_status=None,
                )

            from ai_value_scanner.scanner import ScanConfig

            summary = {
                "total": 1,
                "refreshed": 1,
                "no_cik": [],
                "conflicted": [],
                "failed": 0,
                "incomplete": 0,
                "aborted": False,
            }
            outcome = rdc.run_daily_scan_after_prewarm(
                ScanConfig(),
                config_path="configs/config.risk_off.json",
                summary=summary,
                scan_fn=fake_scan,
            )
            self.assertTrue(outcome["scan_executed"])
            self.assertFalse(outcome["scan_failed"])
            self.assertEqual(outcome["decision_output_status"], "written")
            self.assertEqual(outcome["latest_pointer_status"], "written")

    def test_cron_fails_when_validator_would_reject_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)

            def fake_scan(scan_cfg, **kwargs):
                return ScanRunStatus(
                    output_path=tmp_root / "ranked.csv",
                    report_path=tmp_root / "report.md",
                    decision_snapshot_root=None,
                    decision_output_status="failed",
                    decision_output_error="snapshot boom",
                    latest_pointer_status="not_attempted",
                    latest_pointer_error=None,
                    shadow_status=None,
                )

            from ai_value_scanner.scanner import ScanConfig

            outcome = rdc.run_daily_scan_after_prewarm(
                ScanConfig(),
                config_path="configs/config.risk_off.json",
                summary={
                    "total": 1,
                    "refreshed": 1,
                    "no_cik": [],
                    "conflicted": [],
                    "failed": 0,
                    "incomplete": 0,
                    "aborted": False,
                },
                scan_fn=fake_scan,
            )
            self.assertTrue(outcome["scan_failed"])


class AttentionModuleContractTests(unittest.TestCase):
    def test_view_model_reexports_shared_attention_policy(self) -> None:
        from ai_value_scanner.decision import attention
        from ai_value_scanner.decision import view_model

        self.assertIs(
            view_model.is_growth_compounder_offense_eligible,
            attention.is_growth_compounder_offense_eligible,
        )
        self.assertIs(
            view_model.growth_compounder_offense_order_key,
            attention.growth_compounder_offense_order_key,
        )

    def test_scanner_split_deferred_but_signatures_stable(self) -> None:
        from ai_value_scanner import scanner

        self.assertIn(
            "allow_existing_decision_snapshot",
            inspect.signature(scanner.run_scan).parameters,
        )
        self.assertIn(
            "freshness_now_utc",
            inspect.signature(scanner.run_scan).parameters,
        )
        self.assertTrue(hasattr(scanner, "run_scan_with_status"))


if __name__ == "__main__":
    unittest.main()
