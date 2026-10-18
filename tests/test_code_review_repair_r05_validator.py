"""R05 repair tests: version-aware snapshot validation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ai_value_scanner.decision import ActionState, build_stock_decisions
from ai_value_scanner.reporting.snapshot import write_decision_snapshot

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
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
    shares_yoy=0.20,
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


def _decisions(policy_version: str):
    return build_stock_decisions(
        pd.DataFrame([ROW]),
        decision_date="2026-10-09",
        generated_at_utc="2026-10-18T12:00:00+00:00",
        policy_version=policy_version,
    )


def _write(tmp: str, decisions, *, policy: str, layout: str):
    daily = tuple(decisions)
    return write_decision_snapshot(
        output_root=tmp,
        strategy_style="risk_off",
        decisions=decisions,
        daily_attention=daily,
        weekly_attention=daily,
        generated_at_utc="2026-10-18T12:00:00+00:00",
        decision_date="2026-10-09",
        config_fingerprint="cfg",
        policy_version=policy,
        layout_version=layout,
    )


class VersionAwareValidatorTests(unittest.TestCase):
    def test_v2_snapshot_with_b_promotion_passes(self) -> None:
        decisions = _decisions("v2")
        self.assertEqual(decisions[0].quality.grade.value, "B")
        self.assertEqual(decisions[0].action_state.value, "PRIORITY_REVIEW")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])

    def test_v1_snapshot_passes(self) -> None:
        decisions = _decisions("v1")
        self.assertEqual(decisions[0].action_state.value, "HOLD_MONITOR")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v1", layout="v1")
            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            self.assertNotIn("decision_policy_version", manifest)

    def test_supported_mixed_policy_layout_combinations(self) -> None:
        for policy, layout in (("v1", "v2"), ("v2", "v1")):
            with self.subTest(policy=policy, layout=layout):
                with tempfile.TemporaryDirectory() as tmp:
                    paths = _write(
                        tmp,
                        _decisions(policy),
                        policy=policy,
                        layout=layout,
                    )
                    result = validate_snapshot(paths.root)
                    self.assertTrue(result["ok"], result["errors"])

    def test_unknown_version_fails_closed(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            manifest["decision_policy_version"] = "v9"
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("unsupported decision_policy_version" in error for error in result["errors"])
            )

    def test_v2_action_mismatch_is_rejected(self) -> None:
        decisions = _decisions("v2")
        tampered = decisions[0].__class__(
            **{
                **decisions[0].__dict__,
                "action_state": ActionState.HOLD_MONITOR,
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, (tampered,), policy="v2", layout="v2")
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any(
                    "canonical mapping" in error and "action_version=v2" in error
                    for error in result["errors"]
                )
            )

    def test_provenance_manifest_version_mismatch_is_rejected(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            lines = paths.decisions_jsonl.read_text(encoding="utf-8").splitlines()
            payload = json.loads(lines[0])
            payload["provenance"]["decision_policy_version"] = "q=v1,e=v1,a=v1"
            paths.decisions_jsonl.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("do not match manifest policy" in error for error in result["errors"])
            )

    def test_missing_linked_detail_page_is_rejected(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            (paths.detailed_dir / "AAA.md").unlink()
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("missing detailed report for AAA" in error for error in result["errors"])
            )

    def test_tampered_stage_policy_version_is_rejected(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            manifest["quality_policy_version"] = "company_quality_v2_2099-01-01"
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any(
                    "unsupported quality_policy_version" in error
                    or "quality_policy_version" in error
                    for error in result["errors"]
                )
            )

    def test_non_object_manifest_is_rejected_cleanly(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            paths.run_manifest_json.write_text("[]\n", encoding="utf-8")
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("must decode to a JSON object" in error for error in result["errors"])
            )

    def test_unknown_renderer_revision_is_rejected(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            manifest["report_renderer_revision"] = "future_revision_2099"
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any(
                    "unsupported report_renderer_revision" in error
                    for error in result["errors"]
                )
            )

    def test_legacy_snapshot_passes_structurally_with_warning(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            del manifest["report_renderer_revision"]
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])
            self.assertTrue(
                any("legacy snapshot" in warning for warning in result["warnings"])
            )

    def test_legacy_snapshot_still_catches_missing_structure(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            del manifest["report_renderer_revision"]
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (paths.detailed_dir / "AAA.md").unlink()
            paths.action_list_md.write_text("# empty\n", encoding="utf-8")
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("missing detailed report for AAA" in error for error in result["errors"])
            )
            self.assertTrue(
                any("does not mention daily symbols" in error for error in result["errors"])
            )

    def test_renderer_drift_is_still_a_hard_failure(self) -> None:
        decisions = _decisions("v2")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write(tmp, decisions, policy="v2", layout="v2")
            paths.action_list_md.write_text("# tampered\n", encoding="utf-8")
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("action_list.md does not match" in error for error in result["errors"])
            )


if __name__ == "__main__":
    unittest.main()
