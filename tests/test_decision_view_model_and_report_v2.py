"""Track A tests: presentation IR + human-readable report v2 (no network).

All fixtures are synthetic StockDecision shapes. They assert PRESENTATION
behavior only — grades and states are taken as given, never recomputed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.decision.model import (
    ActionState,
    EntryDecision,
    EntryState,
    EvidenceItem,
    QualityDecision,
    QualityGrade,
    StockDecision,
    stock_decisions_to_jsonl,
)
from ai_value_scanner.decision.view_model import (
    build_snapshot_view_model,
    build_stock_card_view_model,
    format_metric_value,
)
from ai_value_scanner.reporting.decision import (
    render_action_list,
    render_detailed_report,
)


def _ev(
    code: str,
    *,
    polarity: str = "positive",
    metric: str | None = "x",
    value: object = 1.0,
    threshold: object = "t",
    label: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        code=code,
        label=label or f"label {code}",
        polarity=polarity,  # type: ignore[arg-type]
        metric=metric,
        value=value,  # type: ignore[arg-type]
        threshold=threshold,  # type: ignore[arg-type]
        message=f"message {code}",
    )


def _ready_entry_positives() -> tuple[EvidenceItem, ...]:
    return (
        _ev("market_data_fresh", metric="market_data_age_days", value=0,
            threshold="<=3", label="Market data fresh"),
        _ev("price_above_sma200", metric="price_to_sma200", value=1.08,
            threshold=">=1.00", label="Price above SMA200"),
        _ev("price_near_sma50_ready_band", metric="price_to_sma50", value=1.0,
            threshold="0.98-1.08", label="Price near SMA50"),
        _ev("return_20d_ready_band", metric="return_20d", value=0.05,
            threshold="-3% to +12%", label="20d return in readiness band"),
        _ev("return_60d_nonnegative", metric="return_60d", value=0.06,
            threshold=">=0%", label="60d trend non-negative"),
        _ev("relative_strength_60d_qqq_ready",
            metric="relative_strength_60d_qqq", value=0.01,
            threshold=">=-3%", label="60d relative strength acceptable"),
        _ev("supportive_market_regime", metric="regime", value="up",
            threshold="supportive", label="Supportive market regime"),
    )


def _decision(
    *,
    symbol: str = "EXM",
    grade: QualityGrade = QualityGrade.A,
    entry_state: EntryState = EntryState.ENTRY_READY,
    action: ActionState = ActionState.PRIORITY_REVIEW,
    priority: int = 1,
    entry_positives: tuple[EvidenceItem, ...] | None = None,
    entry_risks: tuple[EvidenceItem, ...] = (),
    quality_positives: tuple[EvidenceItem, ...] | None = None,
    quality_risks: tuple[EvidenceItem, ...] = (),
    quality_missing: tuple[EvidenceItem, ...] = (),
) -> StockDecision:
    if quality_positives is None:
        quality_positives = (
            _ev("net_margin_strong", metric="net_margin", value=0.236287,
                threshold=">=10% supportive; <0% weak", label="Net margin supportive"),
            _ev("free_cash_flow_strong", metric="free_cash_flow",
                value=15154000000.0, threshold=">0 supportive; <0 weak",
                label="Free cash flow supportive"),
        )
    entry = EntryDecision(
        state=entry_state, score=0.9, confidence=1.0,
        positives=_ready_entry_positives() if entry_positives is None else entry_positives,
        risks=tuple(entry_risks), market_asof="2026-10-12",
    )
    quality = QualityDecision(
        grade=grade, score=0.8, confidence=0.9,
        component_scores={"profitability_cash": 0.8},
        positives=tuple(quality_positives),
        risks=tuple(quality_risks), missing=tuple(quality_missing),
        data_asof="2026-08-27",
    )
    return StockDecision(
        schema_version="1", symbol=symbol, company_name=f"{symbol} Inc.",
        decision_date="2026-10-12",
        generated_at_utc="2026-10-13T00:00:00+00:00",
        quality=quality, entry=entry, action_state=action, priority=priority,
        rationale=(), review_trigger="Review now.",
        source_lists=("research_pool",),
        provenance={"cik": "0001108524"},
    )


def _crm_like_breakout() -> StockDecision:
    """WATCH_BREAKOUT with no Entry risk items and no 20d evidence (silent)."""
    positives = tuple(
        item for item in _ready_entry_positives()
        if item.code != "return_20d_ready_band"
    )
    return _decision(
        symbol="CRM", entry_state=EntryState.WATCH_BREAKOUT,
        action=ActionState.WATCH_BREAKOUT, priority=10,
        entry_positives=positives, entry_risks=(),
    )


class FormatMetricValueTests(unittest.TestCase):
    def test_money_formats(self) -> None:
        self.assertEqual(format_metric_value("free_cash_flow", 15154000000.0), "$15.15B")
        self.assertEqual(format_metric_value("free_cash_flow", -875000000.0), "-$875.0M")
        self.assertEqual(format_metric_value("market_cap", 923900000.0), "$923.9M")
        self.assertEqual(format_metric_value("revenue", 12345.0), "$12,345")

    def test_signed_growth_and_margins(self) -> None:
        self.assertEqual(format_metric_value("revenue_yoy", 0.239), "+23.9%")
        self.assertEqual(
            format_metric_value("relative_strength_60d_qqq", -0.047), "-4.7%"
        )
        self.assertEqual(format_metric_value("net_margin", 0.168), "16.8%")
        self.assertEqual(format_metric_value("net_margin", -0.243), "-24.3%")

    def test_percentiles_multiples_days(self) -> None:
        self.assertEqual(format_metric_value("ps_hist_percentile", 1.0), "100th pctl")
        self.assertEqual(format_metric_value("pe_hist_percentile", 0.25), "25th pctl")
        self.assertEqual(
            format_metric_value("range_position_52w", 0.6), "60% of 52w range"
        )
        self.assertEqual(format_metric_value("price_to_sma200", 1.03), "1.03x")
        self.assertEqual(
            format_metric_value("interest_coverage", 61.396104), "61.40x"
        )
        self.assertEqual(format_metric_value("fundamental_data_age_days", 46), "46d")
        self.assertEqual(format_metric_value("market_data_age_days", 0), "0d")

    def test_none_is_na(self) -> None:
        self.assertEqual(format_metric_value("net_margin", None), "n/a")
        self.assertEqual(format_metric_value(None, None), "n/a")


class SilentGateTests(unittest.TestCase):
    def test_watch_breakout_silent_gate_never_shows_none_risk(self) -> None:
        decision = _crm_like_breakout()
        self.assertEqual(decision.entry.risks, ())
        card = build_stock_card_view_model(decision)
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(len(card.entry_checklist), 7)
        ret20 = by_key["ret20_band"]
        self.assertEqual(ret20.status, "SILENT_OR_UNOBSERVED")
        self.assertIn("silent", ret20.observed_display.lower())
        self.assertNotEqual(card.top_risks_or_blockers_inline, "none")
        self.assertIn("ret20_band", card.top_risks_or_blockers_inline)

    def test_missing_rs_gate_is_silent(self) -> None:
        positives = tuple(
            item for item in _ready_entry_positives()
            if item.code != "relative_strength_60d_qqq_ready"
        )
        decision = _decision(
            symbol="PG", entry_state=EntryState.WATCH_BREAKOUT,
            action=ActionState.WATCH_BREAKOUT, entry_positives=positives,
            entry_risks=(),
        )
        card = build_stock_card_view_model(decision)
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["rs60_qqq"].status, "SILENT_OR_UNOBSERVED")
        self.assertIn("rs60_qqq", card.top_risks_or_blockers_inline)


class M1ForwardCompatTests(unittest.TestCase):
    def test_m1_risk_codes_upgrade_gates_to_fail_blocker(self) -> None:
        positives = tuple(
            item for item in _ready_entry_positives()
            if item.code
            not in {
                "price_above_sma200",
                "price_near_sma50_ready_band",
                "relative_strength_60d_qqq_ready",
            }
        )
        risks = (
            _ev("days_below_sma200_elevated", polarity="negative",
                metric="days_below_sma200", value=20,
                threshold="<=5", label="Days below SMA200 elevated"),
            _ev("price_to_sma50_outside_ready_band", polarity="negative",
                metric="price_to_sma50", value=1.15,
                threshold="0.98-1.08", label="Price outside SMA50 band"),
            _ev("relative_strength_60d_qqq_below_ready", polarity="negative",
                metric="relative_strength_60d_qqq", value=-0.047,
                threshold=">=-3%", label="60d relative strength below gate"),
        )
        decision = _decision(
            symbol="M1", entry_state=EntryState.WATCH_BREAKOUT,
            action=ActionState.WATCH_BREAKOUT,
            entry_positives=positives, entry_risks=risks,
        )
        card = build_stock_card_view_model(decision)
        by_key = {row.gate_key: row for row in card.entry_checklist}
        self.assertEqual(by_key["sma200_trend"].status, "FAIL_BLOCKER")
        self.assertEqual(by_key["sma200_trend"].observed_display, "20d")
        self.assertEqual(by_key["sma50_band"].status, "FAIL_BLOCKER")
        self.assertEqual(by_key["sma50_band"].observed_display, "1.15x")
        self.assertEqual(by_key["rs60_qqq"].status, "FAIL_BLOCKER")
        self.assertEqual(by_key["rs60_qqq"].observed_display, "-4.7%")


class SecondaryRadarTests(unittest.TestCase):
    def test_cap_omitted_and_b_ready_cards(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i,
                      grade=QualityGrade.A,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.PRIORITY_REVIEW)
            for i in range(1, 16)
        )
        omitted = tuple(
            _decision(symbol=f"A{i:02d}", priority=i,
                      grade=QualityGrade.A,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.PRIORITY_REVIEW)
            for i in range(16, 19)
        )
        b_ready = tuple(
            _decision(symbol=f"B{i:02d}", priority=20 + i,
                      grade=QualityGrade.B,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.HOLD_MONITOR)
            for i in range(3)
        )
        all_decisions = primaries + omitted + b_ready
        snapshot = build_snapshot_view_model(
            primaries, all_decisions, title="Daily Action List", cadence="daily"
        )
        self.assertEqual(len(snapshot.primary_cards), 15)
        self.assertEqual(
            [c.symbol for c in snapshot.cap_omitted_priority_cards],
            ["A16", "A17", "A18"],
        )
        self.assertEqual(len(snapshot.secondary_b_ready_cards), 3)
        for card in snapshot.secondary_b_ready_cards:
            self.assertEqual(card.quality_grade, "B")
            self.assertEqual(card.entry_state, "ENTRY_READY")

    def test_no_all_decisions_gives_empty_radar(self) -> None:
        snapshot = build_snapshot_view_model(
            (_decision(),), None, title="Action List", cadence=None
        )
        self.assertEqual(snapshot.cap_omitted_priority_cards, ())
        self.assertEqual(snapshot.secondary_b_ready_cards, ())


class LayoutVersionParityTests(unittest.TestCase):
    def test_v1_default_is_byte_identical_to_explicit_v1(self) -> None:
        decisions = [_crm_like_breakout(), _decision(symbol="ETN")]
        self.assertEqual(
            render_action_list(decisions),
            render_action_list(decisions, layout_version="v1"),
        )
        self.assertEqual(render_action_list([]), "# Action List\n\n- no decisions\n")
        for decision in decisions:
            self.assertEqual(
                render_detailed_report(decision),
                render_detailed_report(decision, layout_version="v1"),
            )

    def test_invalid_layout_version_raises(self) -> None:
        decision = _decision()
        with self.assertRaises(ValueError):
            render_action_list([decision], layout_version="v3")
        with self.assertRaises(ValueError):
            render_detailed_report(decision, layout_version="v3")

    def test_v2_uses_formatted_values_never_raw_floats(self) -> None:
        decision = _decision(
            symbol="CRM",
            quality_risks=(
                _ev("ps_hist_percentile_weak", polarity="negative",
                    metric="ps_hist_percentile", value=1.0,
                    threshold="<=60% supportive; >80% expensive",
                    label="Historical P/S percentile weak"),
            ),
        )
        detailed = render_detailed_report(decision, layout_version="v2")
        self.assertIn("$15.15B", detailed)
        self.assertIn("100th pctl", detailed)
        self.assertNotIn("15154000000.0", detailed)
        self.assertNotIn("0.236287", detailed)
        listed = render_action_list([decision], layout_version="v2",
                                    all_decisions=[decision])
        self.assertIn("(v2)", listed)
        self.assertIn("Priority Review", listed)
        self.assertIn("Secondary Radar", listed)
        self.assertNotIn("15154000000.0", listed)


def _table_lines(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.startswith("|")]


class MobileFirstCompactTests(unittest.TestCase):
    def test_compact_inline_labels(self) -> None:
        card = build_stock_card_view_model(_decision(symbol="CRM"))
        self.assertEqual(
            card.top_positives_inline, "Margin 23.6%; FCF $15.15B; SMA200 1.08x"
        )
        pillar = card.quality_pillars[0]
        self.assertEqual(pillar.supporting_items[0].summary_text, "Margin: 23.6%")
        self.assertEqual(pillar.supporting_items[1].summary_text, "FCF: $15.15B")

    def test_compact_risk_labels(self) -> None:
        decision = _decision(
            symbol="KO",
            quality_risks=(
                _ev("ps_hist_percentile_weak", polarity="negative",
                    metric="ps_hist_percentile", value=1.0,
                    threshold="t", label="Historical P/S percentile weak"),
                _ev("pe_hist_percentile_weak", polarity="negative",
                    metric="pe_hist_percentile", value=1.0,
                    threshold="t", label="Historical P/E percentile weak"),
            ),
        )
        card = build_stock_card_view_model(decision)
        self.assertEqual(
            card.top_risks_or_blockers_inline, "P/S 100th pctl; P/E 100th pctl"
        )

    def test_action_list_v2_has_zero_wide_tables_and_uses_accordion_groups(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 4)
        )
        b_ready = (
            _decision(symbol="B01", priority=10, grade=QualityGrade.B,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.HOLD_MONITOR),
        )
        rendered = render_action_list(
            primaries, title="Daily Action List", cadence="daily",
            layout_version="v2", all_decisions=primaries + b_ready,
        )
        rows = _table_lines(rendered)
        self.assertEqual(rows, [])
        self.assertIn("## Priority Review — Ready for Evaluation (3)", rendered)

    def test_detailed_report_v2_tables_have_at_most_3_columns(self) -> None:
        for decision in (_decision(symbol="CRM"), _crm_like_breakout()):
            with self.subTest(symbol=decision.symbol):
                rendered = render_detailed_report(decision, layout_version="v2")
                rows = _table_lines(rendered)
                self.assertGreater(len(rows), 0)
                for line in rows:
                    with self.subTest(line=line[:60]):
                        self.assertLessEqual(line.count("|"), 4)

    def test_action_list_v2_details_collapsed_with_jump_links(self) -> None:
        primaries = tuple(
            _decision(symbol=f"A{i:02d}", priority=i) for i in range(1, 4)
        )
        b_ready = (
            _decision(symbol="B01", priority=10, grade=QualityGrade.B,
                      entry_state=EntryState.ENTRY_READY,
                      action=ActionState.HOLD_MONITOR),
        )
        rendered = render_action_list(
            primaries, title="Daily Action List", cadence="daily",
            layout_version="v2", all_decisions=primaries + b_ready,
        )
        self.assertIn("<details>", rendered)
        self.assertIn("<summary>", rendered)
        self.assertEqual(rendered.count("<details open"), 0)
        self.assertIn('<a id="top"></a>', rendered)
        self.assertIn("#card-a01", rendered)
        self.assertIn("[↑ Top](#top)", rendered)

    def test_detailed_report_v2_details_collapsed_with_jump_links(self) -> None:
        rendered = render_detailed_report(
            _crm_like_breakout(), layout_version="v2"
        )
        self.assertIn("<details>", rendered)
        self.assertIn("<summary>", rendered)
        self.assertEqual(rendered.count("<details open"), 0)
        self.assertIn('<a id="top"></a>', rendered)
        self.assertIn("[↑ Top](#top)", rendered)
        self.assertIn("[← Back to Action List](../action_list.md)", rendered)

    def test_v2_never_leaks_absolute_filesystem_paths(self) -> None:
        from dataclasses import replace

        decision = replace(
            _decision(symbol="CRM"),
            provenance={
                "cik": "0001108524",
                "scan_config_path": "/home/user/repo/configs/config.risk_off.json",
                "watchlist_csv_path": "/tmp/work/data/ai_watchlist.csv",
            },
        )
        detailed = render_detailed_report(decision, layout_version="v2")
        listed = render_action_list([decision], layout_version="v2")
        for text in (detailed, listed):
            self.assertNotIn("/home/", text)
            self.assertNotIn("/tmp/", text)
        self.assertIn("configs/config.risk_off.json", detailed)
        self.assertIn("data/ai_watchlist.csv", detailed)


class PreviewCliSmokeTests(unittest.TestCase):
    def test_preview_cli_writes_v2_files(self) -> None:
        decisions = (
            _decision(symbol="AAA", priority=1),
            _decision(symbol="BBB", priority=2, grade=QualityGrade.B,
                      action=ActionState.HOLD_MONITOR),
            _decision(symbol="CCC", priority=3),
        )
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap"
            snap.mkdir()
            (snap / "decisions.jsonl").write_text(
                stock_decisions_to_jsonl(decisions), encoding="utf-8"
            )
            (snap / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "decision_date": "2026-10-12",
                        "daily_symbols": ["AAA", "BBB"],
                        "weekly_symbols": ["AAA", "CCC"],
                    }
                ),
                encoding="utf-8",
            )
            out = Path(tmp) / "out"
            script = (
                Path(__file__).resolve().parent.parent
                / "scripts" / "render_snapshot_preview.py"
            )
            proc = subprocess.run(
                [sys.executable, str(script), "--snapshot-dir", str(snap),
                 "--output-dir", str(out)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((out / "action_list_v2.md").exists())
            self.assertTrue((out / "weekly_review_v2.md").exists())
            self.assertTrue((out / "detailed_v2" / "AAA.md").exists())
            body = (out / "action_list_v2.md").read_text(encoding="utf-8")
            self.assertIn("AAA", body)
            self.assertIn("./detailed_v2/AAA.md", body)
            detail_body = (out / "detailed_v2" / "AAA.md").read_text(encoding="utf-8")
            self.assertIn("../action_list_v2.md", detail_body)
            # Snapshot input directory is untouched (no v2 files written there).
            self.assertFalse((snap / "action_list_v2.md").exists())


if __name__ == "__main__":
    unittest.main()
