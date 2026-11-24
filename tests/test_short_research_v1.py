"""Short Research v1 tests (offline synthetic + frozen smoke evidence)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ai_value_scanner.decision.entry import ENTRY_V2_POLICY_VERSION
from ai_value_scanner.decision.model import (
    ActionState,
    EntryDecision,
    EntryState,
    EvidenceItem,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.decision.quality import QUALITY_V2_POLICY_VERSION
from ai_value_scanner.reporting import decision as decision_reports
from ai_value_scanner.reporting import short_research as short_reports
from ai_value_scanner.reporting import snapshot as snapshot_module
from ai_value_scanner.reporting.decision import render_action_list
from ai_value_scanner.reporting.snapshot import (
    REPORT_RENDERER_REVISION,
    write_decision_snapshot,
)
from ai_value_scanner.research.short_research_v1 import (
    BORROW_EASY,
    BORROW_HARD,
    BORROW_NOT_SHORTABLE,
    BORROW_UNKNOWN,
    MAX_SHORT_CANDIDATES,
    SHORT_RESEARCH_CONTRACT_VERSION,
    SHORT_RESEARCH_RULE_VERSION,
    ShortResearchInputError,
    build_short_cross_section,
    build_short_feature_frame,
    evaluate_frozen_short_research,
    render_short_research_section,
    resolve_borrow_evidence,
    short_candidates_csv,
    unavailable_short_research_result,
)
from ai_value_scanner.research import short_research_v1_eval as evaluator
from ai_value_scanner.research.short_research_v1_eval import (
    DatasetIdentity,
    MEMBER_COLUMNS,
    _block_bootstrap,
    _group_return,
    _selected_members,
    _settle_labels,
    _peer_medians,
    _planned_endpoints,
    _verdict,
)

DATE = "2025-01-31"
FUND_ASOF = "2024-12-31"


def _load_script(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "short_" + name.replace(".py", ""), module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_script("validate_mvp_snapshot.py")


def _row(
    symbol: str,
    cik: str,
    *,
    sic: str = "3674",
    **overrides,
) -> dict:
    row = {
        "signal_date": DATE,
        "symbol": symbol,
        "cik": cik,
        "sic": sic,
        "market_asof": DATE,
        "fundamental_data_asof": FUND_ASOF,
        "market_data_feed": "sip",
        "watchlist_source": "test",
        "price": 100.0,
        "dollar_volume": 20_000_000.0,
        "avg_dollar_volume_20d": 30_000_000.0,
        "return_20d": -0.05,
        "return_60d": -0.10,
        "price_to_sma50": 0.95,
        "revenue": 1_000_000_000.0,
        "revenue_yoy": -0.05,
        "operating_cash_flow_growth": -0.20,
        "operating_cash_flow_growth_direction": "positive_base",
        "adjusted_net_income": 100_000_000.0,
        "pe": 20.0,
        "shares_stale": False,
        "company_name": f"{symbol} Inc.",
        "sic_description": "Test Industry",
        "regime": "up",
        "relative_strength_60d_qqq": 0.0,
    }
    row.update(overrides)
    return row


def _base_frame() -> pd.DataFrame:
    returns = [-0.08, 0.0, 0.04, 0.10, -0.12]
    pes = [10.0, 12.0, 14.0, 16.0, 20.0]
    return pd.DataFrame(
        [
            _row(symbol, str(index + 1), return_60d=returns[index], pe=pes[index])
            for index, symbol in enumerate(("A", "B", "C", "D", "E"))
        ]
    )


def _boundary_frame() -> pd.DataFrame:
    returns = [-0.10, -0.08, -0.06, -0.12, -0.02]
    pes = [10.0, 12.0, 16.0, 20.0, 24.0]
    return pd.DataFrame(
        [
            _row(symbol, str(index + 1), return_60d=returns[index], pe=pes[index])
            for index, symbol in enumerate(("A", "B", "C", "D", "E"))
        ]
    )


def _three_sic_frame() -> pd.DataFrame:
    rows: list[dict] = []
    for group_index, (sic, symbols) in enumerate(
        (
            ("3674", ("A", "B", "C", "D", "E")),
            ("7372", ("F", "G", "H", "I", "J")),
            ("4911", ("K", "L", "M", "N", "O")),
        )
    ):
        returns = [-0.10, -0.08, -0.06, -0.04, -0.02]
        pes = [20.0, 24.0, 10.0, 12.0, 16.0]
        for index, symbol in enumerate(symbols):
            rows.append(
                _row(
                    symbol,
                    str(group_index * 10 + index + 1),
                    sic=sic,
                    return_60d=returns[index],
                    pe=pes[index],
                )
            )
    return pd.DataFrame(rows)


def _decision(symbol: str = "AAA") -> StockDecision:
    quality = QualityDecision(
        grade=QualityGrade.A,
        score=0.80,
        confidence=0.95,
        component_scores={"profitability_cash": 0.8},
        positives=(),
        risks=(),
        missing=(),
        data_asof=FUND_ASOF,
    )
    entry = EntryDecision(
        state=EntryState.ENTRY_READY,
        score=0.90,
        confidence=0.90,
        positives=(),
        risks=(),
        market_asof=DATE,
    )
    return StockDecision(
        schema_version="1",
        symbol=symbol,
        company_name=f"{symbol} Inc.",
        decision_date=DATE,
        generated_at_utc=f"{DATE}T12:00:00+00:00",
        quality=quality,
        entry=entry,
        action_state=ActionState.PRIORITY_REVIEW,
        priority=1,
        rationale=(),
        review_trigger="Review.",
        source_lists=(),
        provenance={
            "quality_policy_version": QUALITY_V2_POLICY_VERSION,
            "entry_policy_version": ENTRY_V2_POLICY_VERSION,
            "decision_policy_version": "q=v2,e=v2,a=v2",
        },
        previous_action_state=None,
        state_change_reason=None,
    )


def _write_snapshot(
    root: str | Path,
    short_result=None,
    *,
    legacy_lists_paused: bool = False,
):
    decision = _decision()
    return write_decision_snapshot(
        output_root=root,
        strategy_style="production",
        decisions=(decision,),
        daily_attention=(decision,),
        weekly_attention=(decision,),
        generated_at_utc=decision.generated_at_utc,
        decision_date=DATE,
        config_fingerprint="fp",
        input_provenance={"legacy_lists_paused": legacy_lists_paused},
        short_research=short_result,
        policy_version="v2",
        layout_version="v2",
    )


class TestConfigContract(unittest.TestCase):
    def test_default_is_disabled(self) -> None:
        from ai_value_scanner.config import ScanConfig

        self.assertFalse(ScanConfig().enable_short_research)

    def test_enabled_requires_compatible_config(self) -> None:
        from ai_value_scanner.config import ScanConfig

        with self.assertRaises(ValueError) as ctx:
            ScanConfig.from_dict(
                {
                    "enable_short_research": True,
                    "official_market_mode": "snapshot",
                }
            )
        self.assertIn("official_market_mode", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            ScanConfig.from_dict(
                {
                    "enable_short_research": True,
                    "official_market_mode": "sip_eod",
                    "report_layout_version": "v1",
                }
            )
        self.assertIn("report_layout_version", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            ScanConfig.from_dict(
                {
                    "enable_short_research": True,
                    "official_market_mode": "sip_eod",
                    "report_layout_version": "v2",
                    "use_adjusted_quality_metrics": False,
                }
            )
        self.assertIn("use_adjusted_quality_metrics", str(ctx.exception))

    def test_compatible_config_loads(self) -> None:
        from ai_value_scanner.config import ScanConfig

        config = ScanConfig.from_dict(
            {
                "enable_short_research": True,
                "official_market_mode": "sip_eod",
                "report_layout_version": "v2",
                "use_adjusted_quality_metrics": True,
            }
        )
        self.assertTrue(config.enable_short_research)

    def test_bool_is_strict(self) -> None:
        from ai_value_scanner.config import ScanConfig

        with self.assertRaises(ValueError):
            ScanConfig.from_dict({"enable_short_research": "false"})


class TestInputContract(unittest.TestCase):
    def test_mixed_feed_rejected(self) -> None:
        frame = _base_frame()
        frame.loc[0, "market_data_feed"] = "iex"
        with self.assertRaises(ShortResearchInputError) as ctx:
            build_short_cross_section(frame)
        self.assertIn("MIXED_OR_UNKNOWN_FEED", ctx.exception.reason_codes)

    def test_duplicate_date_symbol_rejected(self) -> None:
        frame = _base_frame()
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ShortResearchInputError) as ctx:
            build_short_cross_section(frame)
        self.assertIn("DUPLICATE_DATE_SYMBOL", ctx.exception.reason_codes)

    def test_missing_columns_rejected(self) -> None:
        frame = _base_frame().drop(columns=["pe"])
        with self.assertRaises(ShortResearchInputError) as ctx:
            build_short_cross_section(frame)
        self.assertIn("MISSING_COLUMNS", ctx.exception.reason_codes)

    def test_future_market_and_fundamental_dates_reject_cross_section(self) -> None:
        frame = _base_frame()
        frame.loc[4, "market_asof"] = "2025-02-01"
        frame.loc[3, "fundamental_data_asof"] = "2025-02-01"
        with self.assertRaises(ShortResearchInputError) as caught:
            build_short_cross_section(frame)
        self.assertEqual(
            set(caught.exception.reason_codes), {"MARKET_ASOF_FUTURE", "FUNDAMENTAL_ASOF_FUTURE"}
        )

    def test_unknown_feed_in_one_row_and_missing_adapter_input(self) -> None:
        frame = _base_frame()
        frame.loc[4, "market_data_feed"] = None
        with self.assertRaises(ShortResearchInputError) as caught:
            build_short_cross_section(frame)
        self.assertIn("MIXED_OR_UNKNOWN_FEED", caught.exception.reason_codes)
        adapted = build_short_feature_frame(
            frame.drop(columns="pe"), signal_date=DATE,
            market_data_feed="sip", watchlist_source="fixture",
        )
        with self.assertRaises(ShortResearchInputError) as caught:
            build_short_cross_section(adapted)
        self.assertIn("MISSING_COLUMNS", caught.exception.reason_codes)
        older = build_short_cross_section(_base_frame().assign(market_asof="2025-01-30"))
        self.assertEqual(older.status, "no_candidates")
        self.assertEqual(older.reason_counts["MARKET_ASOF_MISMATCH"], 5)

    def test_nonfinite_and_unknown_stale_reasons(self) -> None:
        frame = _base_frame()
        frame["shares_stale"] = frame["shares_stale"].astype(object)
        frame.loc[0, "price"] = float("nan")
        frame.loc[1, "shares_stale"] = "unknown"
        result = build_short_cross_section(frame)
        by_symbol = {record.symbol: record for record in result.records}
        self.assertIn("PRICE_MISSING", by_symbol["A"].reason_codes)
        self.assertIn("SHARES_STALE_UNKNOWN", by_symbol["B"].reason_codes)
        self.assertEqual(by_symbol["B"].status, "INSUFFICIENT_DATA")

    def test_returns_do_not_affect_selection(self) -> None:
        frame = _base_frame()
        with_labels = frame.copy()
        with_labels["fwd_ret_20"] = [0.9, -0.8, 0.7, -0.6, 0.5]
        with_labels["label_end_20"] = "2099-01-01"
        first = build_short_cross_section(frame)
        second = build_short_cross_section(with_labels)
        self.assertEqual(
            [(c.symbol, c.rank) for c in first.selected],
            [(c.symbol, c.rank) for c in second.selected],
        )
        self.assertEqual(first.status_counts, second.status_counts)


class TestPeerCalculations(unittest.TestCase):
    def test_pe_and_industry_relative_values(self) -> None:
        result = build_short_cross_section(_base_frame())
        target = next(record for record in result.records if record.symbol == "E")
        self.assertAlmostEqual(target.rs60_sic, -0.14, places=6)
        self.assertAlmostEqual(target.peer_median_return_60d, 0.02, places=6)
        self.assertEqual(target.industry_peer_count, 4)
        self.assertEqual(target.pe_peer_count, 5)
        self.assertAlmostEqual(target.pe_peer_median, 14.0, places=6)
        self.assertAlmostEqual(target.pe_percentile, 1.0, places=6)
        self.assertAlmostEqual(target.pe_premium, 20.0 / 14.0 - 1.0, places=6)
        self.assertEqual(target.status, "CONFIRMED")

    def test_insufficient_peers_are_insufficient_data(self) -> None:
        frame = _base_frame().iloc[:4].copy()
        result = build_short_cross_section(frame)
        target = next(record for record in result.records if record.symbol == "D")
        self.assertIsNone(target.rs60_sic)
        self.assertIsNone(target.pe_percentile)
        self.assertEqual(target.status, "INSUFFICIENT_DATA")
        self.assertIn("INDUSTRY_PEERS_INSUFFICIENT", target.reason_codes)
        self.assertIn("PE_PEERS_INSUFFICIENT", target.reason_codes)

    def test_same_cik_share_classes_dedupe_by_adv_then_symbol(self) -> None:
        frame = _base_frame()
        extra = _row("A2", "1", avg_dollar_volume_20d=40_000_000.0, pe=20.0)
        frame = pd.concat([frame, pd.DataFrame([extra])], ignore_index=True)
        result = build_short_cross_section(frame)
        by_symbol = {record.symbol: record for record in result.records}
        self.assertEqual(by_symbol["A"].status, "SCOPE_EXCLUDED")
        self.assertIn("DUPLICATE_CIK_LOWER_ADV", by_symbol["A"].reason_codes)
        self.assertNotEqual(by_symbol["A2"].status, "SCOPE_EXCLUDED")

    def test_pe_ties_use_average_rank(self) -> None:
        frame = _base_frame()
        frame["pe"] = 10.0
        result = build_short_cross_section(frame)
        target = next(record for record in result.records if record.symbol == "E")
        self.assertAlmostEqual(target.pe_percentile, 0.6, places=6)
        self.assertAlmostEqual(target.pe_premium, 0.0, places=6)

    def test_input_order_does_not_change_selection(self) -> None:
        frame = _base_frame()
        shuffled = frame.sample(frac=1.0, random_state=7).reset_index(drop=True)
        first = build_short_cross_section(frame)
        second = build_short_cross_section(shuffled)
        self.assertEqual(
            [(c.symbol, c.rank) for c in first.selected],
            [(c.symbol, c.rank) for c in second.selected],
        )
        self.assertEqual(first.status_counts, second.status_counts)


class TestSelectionRules(unittest.TestCase):
    def test_exact_boundaries_and_subset_chain(self) -> None:
        result = build_short_cross_section(_boundary_frame())
        target = next(record for record in result.records if record.symbol == "D")
        self.assertIn("S0", target.signal_groups)
        self.assertIn("S1", target.signal_groups)
        self.assertIn("S2", target.signal_groups)
        self.assertAlmostEqual(target.pe_percentile, 0.8, places=6)
        self.assertAlmostEqual(target.pe_premium, 0.25, places=6)

    def test_ocf_and_revenue_boundaries_inclusive(self) -> None:
        frame = _boundary_frame()
        frame.loc[3, "operating_cash_flow_growth"] = -0.10
        frame.loc[3, "revenue_yoy"] = 0.0
        result = build_short_cross_section(frame)
        target = next(record for record in result.records if record.symbol == "D")
        self.assertIn("S1", target.signal_groups)
        self.assertIn("S2", target.signal_groups)

    def test_return_20d_minus_20_is_watch_not_s0(self) -> None:
        frame = _boundary_frame()
        frame.loc[3, "return_20d"] = -0.20
        result = build_short_cross_section(frame)
        target = next(record for record in result.records if record.symbol == "D")
        self.assertNotIn("S0", target.signal_groups)
        self.assertEqual(target.status, "WATCH")

    def test_sma50_equal_one_is_watch_not_s0(self) -> None:
        frame = _boundary_frame()
        frame.loc[3, "price_to_sma50"] = 1.0
        result = build_short_cross_section(frame)
        target = next(record for record in result.records if record.symbol == "D")
        self.assertNotIn("S0", target.signal_groups)
        self.assertEqual(target.status, "WATCH")

    def test_no_candidates_status_and_empty_selection(self) -> None:
        frame = _base_frame()
        frame.loc[4, "revenue_yoy"] = 0.05
        result = build_short_cross_section(frame)
        self.assertEqual(result.status, "no_candidates")
        self.assertEqual(result.selected, ())
        self.assertEqual(result.funnel["s2_rows"], 0)

    def test_top_five_cap_and_stable_order(self) -> None:
        result = build_short_cross_section(_three_sic_frame())
        self.assertEqual(result.status, "ready")
        self.assertEqual(len(result.selected), MAX_SHORT_CANDIDATES)
        self.assertEqual([c.rank for c in result.selected], [1, 2, 3, 4, 5])
        keys = [(c.rs60_sic, c.symbol) for c in result.selected]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(result.funnel["s2_rows"], 6)


class TestSettlementAndCosts(unittest.TestCase):
    @staticmethod
    def _settle_record(row, *, horizon):
        frame = pd.DataFrame([row])
        _settle_labels(frame, horizon)
        suffix = f"_{horizon}"
        result = {
            column[:-len(suffix)]: (None if pd.isna(value) else value)
            for column, value in frame.iloc[0].items() if column.endswith(suffix)
        }
        result["label_status"] = (
            "VALID" if result["label_valid"] else "MISSING" if result["mature"] else "NOT_MATURE"
        )
        return result

    def _row_for_settlement(self, **overrides) -> dict:
        row = {
            "signal_date": DATE,
            "symbol": "AAA",
            "sic": "3674",
            "fwd_ret_20": -0.203,
            "label_end_20": "2025-03-03",
            "qqq_return_20": -0.02,
            "qqq_label_end_20": "2025-03-03",
        }
        row.update(overrides)
        return row

    def test_short_gross_and_cost_scenarios(self) -> None:
        settled = self._settle_record(self._row_for_settlement(), horizon=20)
        self.assertAlmostEqual(settled["x_ratio"], 0.80, places=9)
        self.assertAlmostEqual(settled["short_gross"], 0.20, places=9)
        self.assertAlmostEqual(settled["short_cost_trade_only"], 0.1973, places=9)
        self.assertAlmostEqual(settled["short_cost_base"], 0.191930, places=6)
        self.assertEqual(settled["label_status"], "VALID")
        self.assertEqual(settled["planned_entry"], "2025-02-03")

    def test_cover_at_120(self) -> None:
        settled = self._settle_record(
            self._row_for_settlement(fwd_ret_20=0.197),
            horizon=20,
        )
        self.assertAlmostEqual(settled["x_ratio"], 1.20, places=9)
        self.assertAlmostEqual(settled["short_gross"], -0.20, places=9)
        self.assertAlmostEqual(settled["short_cost_trade_only"], -0.2033, places=9)

    def test_missing_or_wrong_endpoint_is_missing_not_imputed(self) -> None:
        missing = self._settle_record(
            self._row_for_settlement(label_end_20=None),
            horizon=20,
        )
        self.assertEqual(missing["label_status"], "MISSING")
        self.assertIsNone(missing["short_gross"])
        wrong = self._settle_record(
            self._row_for_settlement(label_end_20="2025-03-04"),
            horizon=20,
        )
        self.assertEqual(wrong["label_status"], "MISSING")
        self.assertIsNone(wrong["short_gross"])

    def test_valid_looking_label_after_cutoff_is_immature(self) -> None:
        signal = "2026-10-30"
        _, end = _planned_endpoints(signal, 20)
        row = self._row_for_settlement(
            signal_date=signal, label_end_20=end, qqq_label_end_20=end,
        )
        settled = self._settle_record(row, horizon=20)
        self.assertEqual(settled["label_status"], "NOT_MATURE")
        self.assertIsNone(settled["short_gross"])
        self.assertFalse(settled["qqq_valid"])

    def test_split_adjusted_label(self) -> None:
        # 2:1 split: raw 100 -> post-split 55 is economically +10%; the frozen
        # label is already split-adjusted (0.097 net of 30 bps roundtrip).
        settled = self._settle_record(
            self._row_for_settlement(fwd_ret_20=0.097),
            horizon=20,
        )
        self.assertAlmostEqual(settled["x_ratio"], 1.10, places=9)
        self.assertAlmostEqual(settled["short_gross"], -0.10, places=9)

    def test_qqq_requires_exact_endpoint(self) -> None:
        settled = self._settle_record(
            self._row_for_settlement(qqq_label_end_20="2025-03-04"),
            horizon=20,
        )
        self.assertFalse(settled["qqq_valid"])
        self.assertIsNone(settled["qqq_long_gross"])


class TestStatisticsHelpers(unittest.TestCase):
    def test_block_bootstrap_parameters_and_missing_mask(self) -> None:
        values = [0.01] * 130
        values[0] = None
        result = _block_bootstrap(values)
        self.assertEqual(result["repeats"], 2000)
        self.assertEqual(result["seed"], 61122)
        self.assertEqual(result["block"], 6)
        self.assertEqual(result["n"], 130)
        self.assertEqual(result["valid"], 129)
        self.assertIsNotNone(result["ci_low"])
        self.assertIsNotNone(result["ci_high"])

    def test_verdict_insufficient_and_failed_and_support(self) -> None:
        insufficient = _verdict(
            n_dates=10,
            years=[2020, 2021],
            s2_mean=0.1,
            s2_s0=0.1,
            s2_s1=0.1,
            s2_s0_ci={"ci_low": 0.1},
            yearly_s2_s0={2020: 0.1},
            loo_s2_s0=0.1,
            missing_scenarios={},
        )
        self.assertEqual(insufficient["verdict"], "insufficient_evidence")
        failed = _verdict(
            n_dates=30,
            years=[2020, 2021, 2022],
            s2_mean=-0.01,
            s2_s0=0.01,
            s2_s1=0.01,
            s2_s0_ci={"ci_low": 0.01},
            yearly_s2_s0={2020: 0.1, 2021: 0.1},
            loo_s2_s0=0.01,
            missing_scenarios={},
        )
        self.assertEqual(failed["verdict"], "signal_or_increment_failed")
        supported = _verdict(
            n_dates=30,
            years=[2020, 2021, 2022],
            s2_mean=0.05,
            s2_s0=0.02,
            s2_s1=0.01,
            s2_s0_ci={"ci_low": 0.001},
            yearly_s2_s0={2020: 0.1, 2021: 0.1},
            loo_s2_s0=0.005,
            missing_scenarios={},
        )
        self.assertEqual(supported["verdict"], "support_next_round")

    def test_mature_sensitivity_takes_precedence_and_peer_keys_include_target(self) -> None:
        result = _verdict(
            n_dates=30, years=[2020, 2021, 2022], s2_mean=-0.01, s2_s0=-0.01,
            s2_s1=0.01, s2_s0_ci={"ci_low": -0.1}, yearly_s2_s0={}, loo_s2_s0=None,
            missing_scenarios={"s2_mean": {"missing_high": 0.10}},
        )
        self.assertEqual(result["verdict"], "insufficient_evidence")
        frame = pd.DataFrame({
            "dataset": "d", "signal_date": DATE, "sic": "3571", "scope_excluded": False,
            "symbol": list("ABCDE"), "long_gross_20": [-0.3, -0.1, 0, 0.2, 0.5],
        })
        peers = _peer_medians(frame, horizon=20)
        self.assertEqual(peers["d", DATE, "3571", "A", 20], (0.1, 4, 4))
        self.assertEqual(peers["d", DATE, "3571", "E", 20], (-0.05, 4, 4))

    def test_weights_and_cash_slots(self) -> None:
        members = [{"short_gross_20": 0.10}, {"short_gross_20": -0.10}]
        self.assertAlmostEqual(
            _group_return(members, weight=0.5, column="short_gross_20"),
            0.0,
        )
        self.assertIsNone(
            _group_return(
                [{"short_gross_20": None}], weight=1.0, column="short_gross_20"
            )
        )
        self.assertEqual(
            _group_return([], weight=0.2, column="short_gross_20"), 0.0
        )


class TestBorrowEvidence(unittest.TestCase):
    def _raw(self, **overrides) -> dict:
        raw = {
            "source": "alpaca",
            "environment": "paper",
            "observed_at_utc": "2025-01-31T22:00:00+00:00",
            "shortable": True,
            "easy_to_borrow": True,
        }
        raw.update(overrides)
        return raw

    def _resolve(self, raw, **overrides):
        return resolve_borrow_evidence(
            raw,
            signal_date=DATE,
            report_generated_at_utc="2025-02-01T02:00:00+00:00",
            **overrides,
        )

    def test_trusted_statuses(self) -> None:
        self.assertEqual(self._resolve(self._raw()).status, BORROW_EASY)
        self.assertEqual(
            self._resolve(
                self._raw(easy_to_borrow=False, hard_to_borrow=True)
            ).status,
            BORROW_HARD,
        )
        self.assertEqual(
            self._resolve(self._raw(shortable=False)).status,
            BORROW_NOT_SHORTABLE,
        )

    def test_untrusted_inputs_are_unknown(self) -> None:
        self.assertEqual(self._resolve({}).status, BORROW_UNKNOWN)
        self.assertEqual(
            self._resolve(self._raw(observed_at_utc="2025-01-30T22:00:00+00:00")).status,
            BORROW_UNKNOWN,
        )
        self.assertEqual(
            self._resolve(self._raw(observed_at_utc="2025-02-02T00:00:00+00:00")).status,
            BORROW_UNKNOWN,
        )
        self.assertEqual(
            self._resolve(self._raw(source="other"), expected_source="alpaca").status,
            BORROW_UNKNOWN,
        )
        self.assertEqual(
            self._resolve(
                self._raw(easy_to_borrow=True, hard_to_borrow=True)
            ).status,
            BORROW_UNKNOWN,
        )
        self.assertEqual(
            self._resolve(
                self._raw(shortable=None, easy_to_borrow=None, hard_to_borrow=None)
            ).status,
            BORROW_UNKNOWN,
        )

    def test_borrow_does_not_change_selection(self) -> None:
        frame = _base_frame()
        plain = build_short_cross_section(frame)
        with_borrow = build_short_cross_section(
            frame,
            borrow_by_symbol={"E": self._raw()},
            report_generated_at_utc="2025-02-01T02:00:00+00:00",
        )
        self.assertEqual(
            [(c.symbol, c.rank) for c in plain.selected],
            [(c.symbol, c.rank) for c in with_borrow.selected],
        )
        target = next(c for c in with_borrow.selected if c.symbol == "E")
        self.assertEqual(target.borrow.status, BORROW_EASY)


class TestSnapshotIntegration(unittest.TestCase):
    def test_pool_size_requires_full_universe_in_current_and_previous_layouts(self) -> None:
        primary = _decision()
        primary = replace(primary, provenance={**primary.provenance, "watchlist_etfs": "AIQ"})
        for revision in (REPORT_RENDERER_REVISION, "mvp_report_renderer_2026-11-22b"):
            with self.subTest(revision=revision):
                args = dict(
                    layout_version="v2", renderer_revision=revision, legacy_lists_paused=False,
                )
                report = render_action_list((primary,), **args)
                self.assertIn("Top ETFs: AIQ (1)", report)
                self.assertNotIn("Pool (", report)
                self.assertNotIn("<strong>Topic Screens</strong>", report)
                universe = iter((primary, _decision("BBB")))
                report = render_action_list((primary,), all_decisions=universe, **args)
                self.assertIn("Pool (2 names)", report)

    def test_topics_and_optional_research_follow_the_primary_cards(self) -> None:
        primary = replace(_decision("AAA"), source_lists=("low_value", "momentum"))
        off_list = replace(
            _decision("BBB"), source_lists=("industry_trend", "momentum", "momentum", "research_pool")
        )
        report = render_action_list(
            (primary,), layout_version="v2", all_decisions=(primary, off_list),
            legacy_lists_paused=False, short_research=build_short_cross_section(_base_frame()),
        )
        header = report.split('<a id="priority-review"></a>', 1)[0]
        self.assertIn("[Priority Review — Ready for Evaluation](#priority-review)", header)
        for label in ("Growth Leaders", "Secondary Radar", "Topic Screens", "Downside Research"):
            self.assertNotIn(label, header)
            self.assertIn(f"<details>\n<summary><strong>{label}", report)
        self.assertLess(report.index("#1 AAA"), report.index("## Additional Research"))
        self.assertEqual(report.count("<strong>Topic Screens</strong>"), 1)
        self.assertIn("**Low-Value** (1) · AAA", report)
        self.assertIn("**Industry-Trend** (1) · BBB", report)
        self.assertIn("**Momentum** (2) · AAA, BBB", report)

    def test_ready_snapshot_files_report_and_validator(self) -> None:
        short = build_short_cross_section(_base_frame())
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, short)
            self.assertTrue((paths.root / "short_research.json").is_file())
            self.assertTrue((paths.root / "short_candidates.csv").is_file())
            report = paths.action_list_md.read_text(encoding="utf-8")
            self.assertIn("<strong>Downside Research</strong> · 1 candidate", report)
            self.assertIn("[short_candidates.csv](./short_candidates.csv)", report)
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            self.assertTrue(manifest["short_research"]["enabled"])
            self.assertEqual(manifest["short_research"]["status"], "ready")
            result = validator.validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])

    def test_no_candidates_and_unavailable_and_disabled(self) -> None:
        no_candidates = build_short_cross_section(
            _base_frame().assign(revenue_yoy=0.05)
        )
        unavailable = unavailable_short_research_result(
            ("TEST_UNAVAILABLE",), signal_date=DATE, market_data_feed="sip"
        )
        for result, status, summary in (
            (no_candidates, "no_candidates", "No candidates"),
            (unavailable, "unavailable", "Data unavailable"),
            (None, "disabled", None),
        ):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as td:
                    paths = _write_snapshot(td, result)
                    manifest = json.loads(
                        paths.run_manifest_json.read_text(encoding="utf-8")
                    )
                    self.assertEqual(manifest["short_research"]["status"], status)
                    self.assertEqual(
                        (paths.root / "short_candidates.csv").is_file(),
                        summary is not None,
                    )
                    for report_path in (paths.action_list_md, paths.weekly_review_md):
                        report = report_path.read_text(encoding="utf-8")
                        if summary is None:
                            self.assertNotIn("Downside Research", report)
                        else:
                            self.assertIn(
                                f"<details>\n<summary><strong>Downside Research</strong> · {summary}</summary>",
                                report,
                            )
                    validation = validator.validate_snapshot(paths.root)
                    self.assertTrue(validation["ok"], validation["errors"])

    def test_five_cap_csv_and_report(self) -> None:
        short = build_short_cross_section(_three_sic_frame())
        self.assertEqual(len(short.selected), 5)
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, short)
            csv_lines = paths.root.joinpath("short_candidates.csv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(csv_lines), 6)  # header + 5
            self.assertIn("peer_median_return_60d", csv_lines[0])
            report = paths.action_list_md.read_text(encoding="utf-8")
            self.assertIn("<strong>Downside Research</strong> · 5 candidates", report)

    def test_report_shows_reason_counts_when_rows_are_excluded(self) -> None:
        frame = _base_frame()
        frame.loc[0, "price"] = 1.0
        short = build_short_cross_section(frame)
        text = "\n".join(render_short_research_section(short))
        self.assertIn("**Reason counts**", text)
        self.assertIn("PRICE_BELOW_MIN", text)

    def test_short_failure_isolated_from_long_snapshot(self) -> None:
        bad = _base_frame()
        bad.loc[0, "market_data_feed"] = "iex"
        with self.assertRaises(ShortResearchInputError) as ctx:
            build_short_cross_section(bad)
        unavailable = unavailable_short_research_result(
            ctx.exception.reason_codes, signal_date=DATE, market_data_feed="iex"
        )
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, unavailable)
            self.assertTrue(paths.decisions_jsonl.is_file())
            self.assertTrue(paths.action_list_md.is_file())
            self.assertIn("#1 AAA", paths.action_list_md.read_text(encoding="utf-8"))
            validation = validator.validate_snapshot(paths.root)
            self.assertTrue(validation["ok"], validation["errors"])

    def test_qqq_paused_long_report_and_short_list_coexist(self) -> None:
        short = build_short_cross_section(_base_frame())
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, short, legacy_lists_paused=True)
            for report_path in (paths.action_list_md, paths.weekly_review_md):
                report = report_path.read_text(encoding="utf-8")
                self.assertIn("<strong>Topic Screens</strong> · Paused", report)
                heading = "<strong>Downside Research</strong> · 1 candidate</summary>"
                self.assertIn(heading, report)
                downside = report.split(heading, 1)[1]
                folded = downside.split("</details>", 1)[0]
                self.assertIn("For research only. This screen runs independently of Topic Screens.", folded)
                self.assertIn("The long Action List selects and ranks its own candidates.", folded)
                self.assertIn("| 1 | E |", folded)

    def test_snapshot_formatter_failure_allows_long_publication_and_validation(self) -> None:
        from ai_value_scanner.scanner import write_latest_decision_pointer

        short = build_short_cross_section(_base_frame())
        failure = ValueError("persistent Short Research formatter failure")
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(snapshot_module, "render_short_snapshot_section", side_effect=failure) as writer,
            patch.object(short_reports, "render_short_snapshot_section", side_effect=failure) as loader,
            patch.object(decision_reports, "render_short_snapshot_section", side_effect=failure) as report,
        ):
            paths = _write_snapshot(td, short)
            latest = write_latest_decision_pointer(
                td, decision_date=DATE, strategy_style="production", policy_version="v2", layout_version="v2",
            )
            self.assertTrue(latest.is_file())
            self.assertTrue(paths.decisions_jsonl.is_file())
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            self.assertEqual(manifest["short_research"]["status"], "unavailable")
            self.assertEqual(len((paths.root / "short_candidates.csv").read_text().splitlines()), 1)
            for report_path in (paths.action_list_md, paths.weekly_review_md):
                rendered = report_path.read_text(encoding="utf-8")
                self.assertIn("#1 AAA", rendered)
                self.assertIn("<strong>Downside Research</strong> · Data unavailable", rendered)
                self.assertIn("SHORT_RESEARCH_PRESENTATION_FAILED", rendered)
            validation = validator.validate_snapshot(paths.root)
            self.assertTrue(validation["ok"], validation["errors"])
            writer.assert_called_once()
            loader.assert_not_called()
            report.assert_not_called()

    def test_long_decisions_unchanged_by_short_enable(self) -> None:
        short = build_short_cross_section(_base_frame())
        with tempfile.TemporaryDirectory() as td:
            off = _write_snapshot(Path(td) / "off", None)
            on = _write_snapshot(Path(td) / "on", short)
            self.assertEqual(
                off.decisions_jsonl.read_bytes(),
                on.decisions_jsonl.read_bytes(),
            )
            off_manifest = json.loads(
                off.run_manifest_json.read_text(encoding="utf-8")
            )
            on_manifest = json.loads(
                on.run_manifest_json.read_text(encoding="utf-8")
            )
            self.assertEqual(
                off_manifest["daily_symbols"], on_manifest["daily_symbols"]
            )
            self.assertEqual(
                off_manifest["weekly_symbols"], on_manifest["weekly_symbols"]
            )
            off_text = off.action_list_md.read_text()
            on_prefix = on.action_list_md.read_text().split('<a id="short-research"></a>', 1)[0]
            self.assertEqual(off_text.rstrip(), on_prefix.rstrip())
            self.assertIn("#1 AAA", on_prefix)

    def test_adapter_is_read_only_and_whitelisted(self) -> None:
        frame = _base_frame()
        frame["long_only_score"] = 1.23
        before = frame.copy(deep=True)
        adapted = build_short_feature_frame(
            frame,
            signal_date=DATE,
            market_data_feed="sip",
            watchlist_source="test",
        )
        pd.testing.assert_frame_equal(frame, before)
        self.assertNotIn("long_only_score", adapted.columns)
        self.assertIn("signal_date", adapted.columns)
        self.assertIn("market_data_feed", adapted.columns)


class TestReuseAndValidation(unittest.TestCase):
    def test_reuse_switch_and_rule_mismatch(self) -> None:
        from ai_value_scanner.scanner import _evaluate_existing_snapshot_reuse

        short = build_short_cross_section(_base_frame())
        with tempfile.TemporaryDirectory() as td:
            off = _write_snapshot(Path(td) / "off", None)
            status, error = _evaluate_existing_snapshot_reuse(
                off.root,
                decision_date=DATE,
                strategy_style="production",
                policy_version="v2",
                layout_version="v2",
                market_mode="snapshot",
                short_research_enabled=True,
            )
            self.assertEqual(status, "reused_version_mismatch")
            self.assertIn("Short Research switch", error or "")

            on = _write_snapshot(Path(td) / "on", short)
            status, error = _evaluate_existing_snapshot_reuse(
                on.root,
                decision_date=DATE,
                strategy_style="production",
                policy_version="v2",
                layout_version="v2",
                market_mode="snapshot",
                short_research_enabled=True,
                short_rule_version="other_rule",
            )
            self.assertEqual(status, "reused_version_mismatch")
            self.assertIn("Short Research rule", error or "")

    def test_validator_rejects_tampered_short_files_and_report(self) -> None:
        short = build_short_cross_section(_base_frame())
        for target in ("short_research.json", "short_candidates.csv", "action_list.md"):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as td:
                    paths = _write_snapshot(td, short)
                    path = paths.root / target
                    original = path.read_text(encoding="utf-8")
                    path.write_text(original + "\nTAMPER\n", encoding="utf-8")
                    result = validator.validate_snapshot(paths.root)
                    self.assertFalse(result["ok"])

    def test_missing_short_file_fails_validation(self) -> None:
        short = build_short_cross_section(_base_frame())
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, short)
            (paths.root / "short_candidates.csv").unlink()
            result = validator.validate_snapshot(paths.root)
            self.assertFalse(result["ok"])

    def test_historical_snapshot_without_short_field_validates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.object(snapshot_module, "REPORT_RENDERER_REVISION", "mvp_report_renderer_2026-11-22a"):
                paths = _write_snapshot(td, None, legacy_lists_paused=True)
            manifest = json.loads(paths.run_manifest_json.read_text(encoding="utf-8"))
            manifest.pop("short_research", None)
            paths.run_manifest_json.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            result = validator.validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])

    def test_corrupt_short_archive_blocks_reuse_and_latest(self) -> None:
        from ai_value_scanner.scanner import (
            _evaluate_existing_snapshot_reuse, write_latest_decision_pointer,
        )
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, build_short_cross_section(_base_frame()))
            args = dict(
                decision_date=DATE, strategy_style="production",
                policy_version="v2", layout_version="v2",
            )
            latest = write_latest_decision_pointer(td, **args)
            original = latest.read_bytes()
            json_path = paths.root / "short_research.json"
            payload = json.loads(json_path.read_text())
            payload["schema_version"] = "unknown"
            json_path.write_text(json.dumps(payload))
            manifest = json.loads(paths.run_manifest_json.read_text())
            manifest["short_research"]["files"]["json_sha256"] = hashlib.sha256(
                json_path.read_bytes()
            ).hexdigest()
            paths.run_manifest_json.write_text(json.dumps(manifest))
            self.assertFalse(validator.validate_snapshot(paths.root)["ok"])
            status, _ = _evaluate_existing_snapshot_reuse(
                paths.root, short_research_enabled=True, **args,
            )
            self.assertEqual(status, "failed")
            with self.assertRaisesRegex(ValueError, "unknown Short Research"):
                write_latest_decision_pointer(td, **args)
            (paths.root / "short_candidates.csv").unlink()
            with self.assertRaises(FileNotFoundError):
                write_latest_decision_pointer(td, **args)
            self.assertEqual(latest.read_bytes(), original)

    def test_snapshot_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = _write_snapshot(td, None)
            before = paths.action_list_md.read_bytes()
            with self.assertRaises(FileExistsError):
                _write_snapshot(td, None)
            self.assertEqual(paths.action_list_md.read_bytes(), before)

    def test_rejects_archived_candidates_outside_filing_window(self) -> None:
        result = build_short_cross_section(_base_frame())
        for filing in ("2025-02-01", "2024-08-03", None, "bad-date"):
            with self.subTest(filing=filing), tempfile.TemporaryDirectory() as td:
                tampered = replace(
                    result, selected=(replace(result.selected[0], fundamental_data_asof=filing),),
                )
                with self.assertRaisesRegex(ValueError, "Short Research filing date"):
                    _write_snapshot(td, tampered)

    def test_rejects_completed_snapshots_with_conflicting_s2_funnel(self) -> None:
        ready = build_short_cross_section(_base_frame())
        empty = build_short_cross_section(_base_frame().assign(price_to_sma50=1.1))
        for result in (ready, empty):
            with self.subTest(status=result.status), tempfile.TemporaryDirectory() as td:
                contradictory = replace(result, funnel={**result.funnel, "s2_rows": 3})
                with self.assertRaisesRegex(ValueError, "conflicts with S2 count"):
                    _write_snapshot(td, contradictory)

    def test_previous_snapshot_with_short_still_validates_exactly(self) -> None:
        short = build_short_cross_section(_base_frame())
        for revision, short_heading, paused_label in (
            ("mvp_report_renderer_2026-11-22b", "## Short Research (1)", "Legacy lists paused"),
            (
                "mvp_report_renderer_2026-11-24a",
                "Downside Research</strong> · 1 candidate",
                "Topic Screens</strong> · Paused",
            ),
        ):
            with self.subTest(revision=revision), tempfile.TemporaryDirectory() as td:
                with patch.object(snapshot_module, "REPORT_RENDERER_REVISION", revision):
                    paths = _write_snapshot(td, short, legacy_lists_paused=True)
                old_report = paths.action_list_md.read_text(encoding="utf-8")
                self.assertIn(short_heading, old_report)
                self.assertIn(paused_label, old_report)
                self.assertNotIn("This screen runs independently of Topic Screens", old_report)
                validation = validator.validate_snapshot(paths.root)
                self.assertTrue(validation["ok"], validation["errors"])

    def test_renderer_revision_bumped(self) -> None:
        self.assertEqual(
            REPORT_RENDERER_REVISION, "mvp_report_renderer_2026-11-24b"
        )


class TestFrozenEvaluationEdges(unittest.TestCase):
    @staticmethod
    def _labeled_frame(**changes) -> pd.DataFrame:
        frame = _base_frame().assign(**changes)
        for horizon in (20, 60):
            _, end = _planned_endpoints(DATE, horizon)
            frame[f"fwd_ret_{horizon}"] = -0.203
            frame[f"label_end_{horizon}"] = end
            frame[f"qqq_return_{horizon}"] = -0.01
            frame[f"qqq_label_end_{horizon}"] = end
        return frame

    @staticmethod
    def _evaluate(frame: pd.DataFrame, root: Path) -> dict:
        name = "sip_2021_2026_v1"
        identity = DatasetIdentity(
            name=name, path=root / "dataset.csv", rows=len(frame), dates=1,
            dataset_sha256="fixture", metadata_sha256="fixture",
            success_sha256="fixture", splits_sha256="fixture",
            generation_config="config.risk_off.json", config_reference_sha256="fixture",
            frequency="monthly", meta={},
        )
        with patch.object(evaluator, "MONTHLY_DATASETS", (name,)), patch.object(
            evaluator, "load_frozen_dataset_frame", return_value=(frame, identity)
        ):
            return evaluate_frozen_short_research("unused", root, scope="smoke")

    def test_wrong_endpoint_leaves_missing_slot_and_publishes_run(self) -> None:
        for symbol in ("D", "E"):
            with self.subTest(symbol=symbol), tempfile.TemporaryDirectory() as td:
                frame = self._labeled_frame()
                frame.loc[frame["symbol"].eq(symbol), "label_end_60"] = DATE
                root = Path(td)
                self._evaluate(frame, root)
                validation = json.loads((root / "validation.json").read_text())
                self.assertTrue(validation["ok"])
                self.assertEqual(validation["label_checks"]["input_label_mismatch_by_horizon"], {"20": 0, "60": 1})
                self.assertTrue(validation["label_checks"]["all_valid_exit_labels_match_planned_sessions"])
                days = pd.read_csv(root / "paired_by_date.csv").set_index("horizon")
                self.assertTrue(days.loc[20, "same_complete"])
                self.assertEqual(bool(days.loc[60, "same_complete"]), symbol == "D")
                if symbol == "E":
                    rows = pd.read_csv(root / "members.csv")
                    kept = rows.loc[rows["symbol"].eq("E") & rows["horizon"].eq(60)]
                    self.assertGreater(len(kept), 0)
                    self.assertTrue(kept["label_status"].eq("MISSING").all())
                    self.assertTrue(kept["label_reasons"].eq("EXIT_LABEL_NOT_PLANNED_SESSION").all())
                    self.assertTrue(kept["short_gross"].isna().all())

    def test_all_cash_run_writes_headers_and_zero_fixed_returns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = self._evaluate(self._labeled_frame(price_to_sma50=1.1), root)
            self.assertEqual(result["verdict"]["verdict"], "insufficient_evidence")
            members = pd.read_csv(root / "members.csv")
            self.assertTrue(members.empty)
            self.assertEqual(list(members.columns), list(MEMBER_COLUMNS))
            self.assertTrue(pd.read_csv(root / "concentration.csv").empty)
            stats = pd.read_csv(root / "industry_stats.csv")
            fixed = stats.loc[stats["view"].eq("fixed_5")]
            self.assertEqual(len(fixed), 6)
            self.assertTrue(fixed["dates"].eq(1).all())
            self.assertTrue(fixed["active_dates"].eq(0).all())
            self.assertTrue(fixed["gross_mean"].eq(0).all())
            self.assertTrue(fixed["base_net_mean"].eq(0).all())
            self.assertTrue(stats.loc[stats["view"].eq("same_slot"), "gross_mean"].isna().all())

    def test_industry_returns_keep_member_weights_and_cash_dates(self) -> None:
        members = pd.DataFrame([{
            "dataset": "monthly", "frequency": "monthly", "signal_date": DATE,
            "horizon": 20, "view": "fixed_5", "group": "S2", "sic": "3674",
            "symbol": "E", "date_complete": True, "weight": 0.2, "short_gross": 0.20,
            "short_cost_base": 0.19, "peer_count": 4, "peer_pool": 4,
        }], columns=MEMBER_COLUMNS)
        paired = pd.DataFrame({
            "frequency": "monthly", "horizon": 20,
            "fixed_complete": [True, True, False],
            "same_complete": [True, False, False],
            "financial_complete": [True, False, False],
        })
        stats = evaluator._industry_statistics(members, paired)
        fixed_s2 = stats.loc[stats["view"].eq("fixed_5") & stats["group"].eq("S2")]
        self.assertEqual(set(fixed_s2["sic"]), {"ALL", "3674"})
        self.assertTrue(fixed_s2["dates"].eq(2).all())
        self.assertTrue(fixed_s2["active_dates"].eq(1).all())
        for row in fixed_s2.itertuples():
            self.assertAlmostEqual(row.gross_mean, 0.020)
            self.assertAlmostEqual(row.base_net_mean, 0.019)


class TestFrozenSmokeEvaluation(unittest.TestCase):
    def test_smoke_evaluation_reproducible_and_reusable(self) -> None:
        dataset_root = Path("outputs/review_followup_20261106/datasets")
        if not dataset_root.is_dir():
            self.skipTest("frozen short-research datasets are not available")
        with tempfile.TemporaryDirectory() as td:
            first = evaluate_frozen_short_research(
                dataset_root, Path(td) / "a", scope="smoke"
            )
            second = evaluate_frozen_short_research(
                dataset_root, Path(td) / "b", scope="smoke"
            )
            self.assertFalse(first["reused"])
            self.assertEqual(first["verdict"], second["verdict"])
            for name in (
                "coverage.csv",
                "paired_by_date.csv",
                "summary.csv",
                "members.csv",
                "short_research.json",
                "short_candidates.csv",
                "report.md",
                "validation.json",
            ):
                self.assertEqual(
                    (Path(td) / "a" / name).read_bytes(),
                    (Path(td) / "b" / name).read_bytes(),
                    name,
                )
            checksums = (Path(td) / "a" / "SHA256SUMS").read_text(
                encoding="utf-8"
            )
            for line in checksums.splitlines():
                digest, filename = line.split("  ", 1)
                actual = hashlib.sha256(
                    (Path(td) / "a" / filename).read_bytes()
                ).hexdigest()
                self.assertEqual(digest, actual)
            reused = evaluate_frozen_short_research(
                dataset_root, Path(td) / "a", scope="smoke"
            )
            self.assertTrue(reused["reused"])
            paired = Path(td) / "a" / "paired_by_date.csv"
            paired.unlink()
            with self.assertRaisesRegex(ValueError, "paired_by_date.csv"):
                evaluate_frozen_short_research(dataset_root, Path(td) / "a", scope="smoke")

    def test_generated_command_reuses_run_with_custom_root_and_scan_evidence(self) -> None:
        original = Path("outputs/review_followup_20261106/datasets").resolve()
        if not original.is_dir():
            self.skipTest("frozen short-research datasets are not available")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataset_root = root / "custom frozen inputs"
            dataset_root.mkdir()
            for name in evaluator.MONTHLY_DATASETS:
                (dataset_root / name).symlink_to(original / name, target_is_directory=True)
            out = root / "run"
            result = evaluate_frozen_short_research(
                dataset_root, out, scope="smoke", scan_entry_integration={"seed": "scan fixture"}
            )
            self.assertFalse(result["reused"])
            command = (out / "commands.md").read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
            reused = subprocess.run(
                [sys.executable, "-"], input=command, capture_output=True, text=True, check=True,
            )
            self.assertIn("'reused': True", reused.stdout)

    def test_checkpoint_rejects_identity_mismatch(self) -> None:
        dataset_root = Path("outputs/review_followup_20261106/datasets")
        if not dataset_root.is_dir():
            self.skipTest("frozen short-research datasets are not available")
        with tempfile.TemporaryDirectory() as td:
            evaluate_frozen_short_research(dataset_root, td, scope="smoke")
            checkpoint_path = Path(td) / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["identity"]["inputs"]["sip_2016_2020_v1"] = "bad"
            checkpoint_path.write_text(
                json.dumps(checkpoint), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                evaluate_frozen_short_research(dataset_root, td, scope="smoke")


if __name__ == "__main__":
    unittest.main()
