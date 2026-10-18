"""R07 repair tests: material downgrades stay visible via a dedicated alert area."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from ai_value_scanner.decision import (
    ActionState,
    build_stock_decisions,
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.decision.attention import (
    is_material_downgrade,
    select_state_change_alerts,
)
from ai_value_scanner.decision.view_model import build_snapshot_view_model
from ai_value_scanner.reporting.snapshot import write_decision_snapshot

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from validate_mvp_snapshot import validate_snapshot
finally:
    sys.path.pop(0)


BASE = dict(
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


def _decision(changes=None, symbol="AAA"):
    row = {**BASE, "symbol": symbol, **(changes or {})}
    return build_stock_decisions(
        pd.DataFrame([row]),
        decision_date="2026-10-09",
        generated_at_utc="2026-10-18T12:00:00+00:00",
        policy_version="v2",
    )[0]


def _unchanged_priority(index: int):
    return replace(
        _decision(symbol=f"OK{index:02d}"),
        priority=index,
        previous_action_state=ActionState.PRIORITY_REVIEW,
        state_change_reason=None,
    )


def _downgraded(symbol="DROPPED", priority=16):
    base = _decision(
        symbol=symbol,
        changes={"net_debt_to_ebitda": 6.0, "interest_coverage": 0.5},
    )
    return replace(
        base,
        priority=priority,
        previous_action_state=ActionState.PRIORITY_REVIEW,
        state_change_reason="Quality A to C; Action PRIORITY_REVIEW to AVOID",
    )


class AlertSelectorTests(unittest.TestCase):
    def test_downgrade_truncated_from_main_lists_is_alerted(self) -> None:
        decisions = tuple(_unchanged_priority(i) for i in range(1, 16)) + (
            _downgraded(),
        )
        self.assertFalse(
            any(
                item.symbol == "DROPPED"
                for item in select_daily_attention(decisions, cap=15)
            )
        )
        self.assertFalse(
            any(
                item.symbol == "DROPPED"
                for item in select_weekly_attention(decisions, cap=15)
            )
        )
        selection = select_state_change_alerts(decisions, cap=15)
        self.assertEqual(selection.total, 1)
        self.assertEqual([item.symbol for item in selection.alerts], ["DROPPED"])
        self.assertFalse(selection.truncated)

    def test_new_avoid_and_unchanged_are_not_alerts(self) -> None:
        new_avoid = replace(
            _decision(changes={"net_debt_to_ebitda": 6.0, "interest_coverage": 0.5}),
            symbol="NEWAVOID",
            action_state=ActionState.AVOID,
            previous_action_state=None,
        )
        unchanged = _unchanged_priority(1)
        selection = select_state_change_alerts((new_avoid, unchanged), cap=15)
        self.assertEqual(selection.total, 0)
        self.assertFalse(is_material_downgrade(new_avoid))
        self.assertFalse(is_material_downgrade(unchanged))

    def test_excluded_symbols_do_not_duplicate_the_main_list(self) -> None:
        dropped = _downgraded()
        selection = select_state_change_alerts(
            (dropped,), exclude_symbols={"DROPPED"}, cap=15
        )
        self.assertEqual(selection.total, 0)

    def test_alert_order_is_deterministic_and_severity_first(self) -> None:
        severe = _downgraded(symbol="SEVERE", priority=30)
        mild = replace(
            _unchanged_priority(3),
            symbol="HOLDDROP",
            action_state=ActionState.HOLD_MONITOR,
            state_change_reason="Entry Quality ENTRY_READY to TREND_DAMAGED.",
        )
        selection = select_state_change_alerts((mild, severe), cap=15)
        self.assertEqual(
            [item.symbol for item in selection.alerts], ["SEVERE", "HOLDDROP"]
        )
        reversed_selection = select_state_change_alerts((severe, mild), cap=15)
        self.assertEqual(
            [item.symbol for item in reversed_selection.alerts],
            ["SEVERE", "HOLDDROP"],
        )

    def test_cap_and_total_are_explicit(self) -> None:
        decisions = tuple(_downgraded(symbol=f"D{i:02d}", priority=20 + i) for i in range(5))
        selection = select_state_change_alerts(decisions, cap=2)
        self.assertEqual(selection.total, 5)
        self.assertEqual(len(selection.alerts), 2)
        self.assertTrue(selection.truncated)


class AlertSnapshotIntegrationTests(unittest.TestCase):
    def _write(self, tmp, decisions, daily, weekly):
        return write_decision_snapshot(
            output_root=tmp,
            strategy_style="risk_off",
            decisions=decisions,
            daily_attention=daily,
            weekly_attention=weekly,
            generated_at_utc="2026-10-18T12:00:00+00:00",
            decision_date="2026-10-09",
            config_fingerprint="cfg",
            policy_version="v2",
            layout_version="v2",
        )

    def test_alert_is_visible_in_report_manifest_and_jsonl(self) -> None:
        decisions = tuple(_unchanged_priority(i) for i in range(1, 16)) + (
            _downgraded(),
        )
        daily = select_daily_attention(decisions, cap=15)
        weekly = select_weekly_attention(decisions, cap=15)
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write(tmp, decisions, daily, weekly)
            action_md = paths.action_list_md.read_text(encoding="utf-8")
            self.assertIn("Attention Changes", action_md)
            self.assertIn("DROPPED", action_md)
            self.assertIn("detailed/DROPPED.md", action_md)
            self.assertTrue((paths.detailed_dir / "DROPPED.md").exists())

            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            alerts = manifest["state_change_alerts"]
            self.assertEqual(alerts["daily"]["total"], 1)
            self.assertEqual(alerts["daily"]["shown_symbols"], ["DROPPED"])
            self.assertEqual(alerts["weekly"]["shown_symbols"], ["DROPPED"])

            rows = [
                json.loads(line)
                for line in (Path(paths.root) / "state_change_alerts.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "DROPPED")
            self.assertEqual(
                rows[0]["previous_action_state"], "PRIORITY_REVIEW"
            )
            self.assertEqual(rows[0]["display_scopes"], ["daily", "weekly"])

            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])

    def test_view_model_alert_section_matches_selection(self) -> None:
        decisions = tuple(_unchanged_priority(i) for i in range(1, 16)) + (
            _downgraded(),
        )
        daily = select_daily_attention(decisions, cap=15)
        view = build_snapshot_view_model(daily, decisions)
        self.assertEqual(
            [card.symbol for card in view.state_change_alert_cards], ["DROPPED"]
        )
        self.assertEqual(view.state_change_alerts_total, 1)

    def test_validator_rejects_tampered_alert_manifest(self) -> None:
        decisions = tuple(_unchanged_priority(i) for i in range(1, 16)) + (
            _downgraded(),
        )
        daily = select_daily_attention(decisions, cap=15)
        weekly = select_weekly_attention(decisions, cap=15)
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write(tmp, decisions, daily, weekly)
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            manifest["state_change_alerts"]["daily"]["shown_symbols"] = []
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("shown_symbols" in error for error in result["errors"])
            )

    def test_validator_rejects_missing_alert_jsonl(self) -> None:
        decisions = tuple(_unchanged_priority(i) for i in range(1, 16)) + (
            _downgraded(),
        )
        daily = select_daily_attention(decisions, cap=15)
        weekly = select_weekly_attention(decisions, cap=15)
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write(tmp, decisions, daily, weekly)
            (Path(paths.root) / "state_change_alerts.jsonl").unlink()
            result = validate_snapshot(paths.root)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("JSONL is missing" in error for error in result["errors"])
            )


if __name__ == "__main__":
    unittest.main()
