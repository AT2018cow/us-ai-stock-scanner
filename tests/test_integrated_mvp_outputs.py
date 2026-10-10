from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import ai_value_scanner.scanner as scanner
from ai_value_scanner.decision import (
    ActionState,
    build_source_list_membership,
    build_stock_decisions,
    decisions_by_symbol,
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.evaluation.action import (
    build_action_evaluation_frame,
    summarize_action_cohorts,
    summarize_action_compactness,
    summarize_action_concentration,
    summarize_action_transitions,
)
from ai_value_scanner.reporting.snapshot import (
    load_previous_snapshot,
    load_snapshot_decisions,
    write_decision_snapshot,
)


def _strong_quality() -> dict[str, object]:
    return {
        "net_margin": 0.25,
        "free_cash_flow": 100.0,
        "ocf_to_net_income": 1.20,
        "accrual_ratio": 0.03,
        "revenue_yoy": 0.20,
        "adjusted_net_income_yoy": 0.20,
        "operating_cash_flow_yoy": 0.20,
        "net_debt_to_ebitda": 0.0,
        "interest_coverage": 10.0,
        "current_ratio": 2.0,
        "shares_yoy": 0.0,
        "fcf_yield": 0.06,
        "ps_hist_percentile": 0.20,
        "pe_hist_percentile": 0.30,
        "receivables_growth_gap": 0.0,
        "inventory_growth_gap": 0.0,
        "shares_stale": False,
        "fundamental_data_asof": "2026-08-01",
    }


def _weak_quality() -> dict[str, object]:
    return {
        "net_margin": -0.10,
        "free_cash_flow": -100.0,
        "ocf_to_net_income": 0.10,
        "accrual_ratio": 0.50,
        "revenue_yoy": -0.20,
        "adjusted_net_income_yoy": -0.30,
        "operating_cash_flow_yoy": -0.20,
        "net_debt_to_ebitda": 6.0,
        "interest_coverage": 0.5,
        "current_ratio": 0.5,
        "shares_yoy": 0.20,
        "fcf_yield": -0.05,
        "ps_hist_percentile": 0.95,
        "pe_hist_percentile": 0.95,
        "receivables_growth_gap": 0.40,
        "inventory_growth_gap": 0.45,
        "shares_stale": False,
        "fundamental_data_asof": "2026-08-01",
    }


def _ready_entry() -> dict[str, object]:
    return {
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.03,
        "days_below_sma200": 0,
        "return_20d": 0.05,
        "return_60d": 0.10,
        "drawdown_from_52w_high": 0.08,
        "range_position_52w": 0.82,
        "relative_strength_60d_qqq": 0.04,
        "volatility_60d": 0.35,
        "regime": "up",
        "benchmark_trend_ok": True,
        "market_asof": "2026-10-09",
    }


def _row(symbol: str, *, weak: bool = False) -> dict[str, object]:
    return {
        **(_weak_quality() if weak else _strong_quality()),
        **_ready_entry(),
        "symbol": symbol,
        "company_name": f"{symbol} Corp",
        "watchlist_bucket": "core_ai",
        "watchlist_etf_count": 2,
        "watchlist_etfs": "AIQ,SMH",
    }


class TestIntegratedDecisionBuilder(unittest.TestCase):
    def test_builds_canonical_actions_and_deterministic_priority(self) -> None:
        rows = [_row("AAA"), _row("BBB"), _row("CCC", weak=True)]
        rows[1]["return_20d"] = 0.20
        frame = pd.DataFrame(rows)
        sources = build_source_list_membership(
            {
                "low_value": pd.DataFrame({"symbol": ["AAA"]}),
                "momentum": pd.DataFrame({"symbol": ["AAA", "BBB"]}),
            }
        )
        decisions = build_stock_decisions(
            frame,
            decision_date="2026-10-10",
            generated_at_utc="2026-10-10T12:00:00+00:00",
            source_lists_by_symbol=sources,
            run_provenance={"code_sha": "abc"},
        )

        self.assertEqual(
            [decision.symbol for decision in decisions],
            ["AAA", "BBB", "CCC"],
        )
        self.assertEqual(
            [decision.action_state for decision in decisions],
            [
                ActionState.PRIORITY_REVIEW,
                ActionState.WATCH_PULLBACK,
                ActionState.AVOID,
            ],
        )
        self.assertEqual([d.priority for d in decisions], [1, 2, 3])
        self.assertEqual(decisions[0].source_lists, ("low_value", "momentum"))
        self.assertGreaterEqual(
            len([x for x in decisions[0].rationale if x.polarity == "positive"]),
            2,
        )
        self.assertIsNotNone(decisions[0].review_trigger)

    def test_previous_snapshot_produces_explicit_state_change_reason(self) -> None:
        previous = build_stock_decisions(
            pd.DataFrame([_row("AAA")]),
            decision_date="2026-10-09",
            generated_at_utc="2026-10-09T12:00:00+00:00",
        )
        current_row = _row("AAA")
        current_row["return_20d"] = 0.20
        current = build_stock_decisions(
            pd.DataFrame([current_row]),
            decision_date="2026-10-10",
            generated_at_utc="2026-10-10T12:00:00+00:00",
            previous_by_symbol=decisions_by_symbol(previous),
        )
        decision = current[0]
        self.assertIs(
            decision.previous_action_state,
            ActionState.PRIORITY_REVIEW,
        )
        self.assertIs(decision.action_state, ActionState.WATCH_PULLBACK)
        self.assertIn("Entry Quality", decision.state_change_reason or "")
        self.assertIn("Action", decision.state_change_reason or "")

    def test_daily_and_weekly_attention_are_capped(self) -> None:
        frame = pd.DataFrame([_row(f"S{i:02d}") for i in range(20)])
        decisions = build_stock_decisions(
            frame,
            decision_date="2026-10-10",
            generated_at_utc="2026-10-10T12:00:00+00:00",
        )
        self.assertEqual(len(select_weekly_attention(decisions, cap=15)), 15)
        self.assertEqual(len(select_daily_attention(decisions, cap=15)), 15)

        with_history = tuple(
            replace(
                decision,
                previous_action_state=decision.action_state,
                state_change_reason=None,
            )
            for decision in decisions
        )
        daily = select_daily_attention(with_history, cap=15)
        self.assertEqual(len(daily), 15)
        self.assertTrue(
            all(d.action_state is ActionState.PRIORITY_REVIEW for d in daily)
        )


class TestDecisionSnapshotArchive(unittest.TestCase):
    def test_snapshot_is_immutable_and_previous_snapshot_is_loadable(self) -> None:
        decisions = build_stock_decisions(
            pd.DataFrame([_row("AAA"), _row("BBB")]),
            decision_date="2026-10-10",
            generated_at_utc="2026-10-10T12:00:00+00:00",
        )
        daily = select_daily_attention(decisions)
        weekly = select_weekly_attention(decisions)

        with tempfile.TemporaryDirectory() as td:
            paths = write_decision_snapshot(
                output_root=td,
                strategy_style="risk_off",
                decisions=decisions,
                daily_attention=daily,
                weekly_attention=weekly,
                generated_at_utc="2026-10-10T12:00:00+00:00",
                decision_date="2026-10-10",
                config_fingerprint="cfg123",
                code_sha="abc123",
                input_provenance={"watchlist": "fixture"},
            )
            self.assertTrue(paths.decisions_jsonl.exists())
            self.assertTrue(paths.action_list_md.exists())
            self.assertTrue(paths.weekly_review_md.exists())
            self.assertTrue((paths.detailed_dir / "AAA.md").exists())
            self.assertTrue(paths.run_manifest_json.exists())

            loaded = load_snapshot_decisions(paths.root)
            self.assertEqual(loaded, decisions)
            self.assertIn(
                "Action State: PRIORITY_REVIEW",
                paths.action_list_md.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Action State: PRIORITY_REVIEW",
                (paths.detailed_dir / "AAA.md").read_text(encoding="utf-8"),
            )

            with self.assertRaisesRegex(FileExistsError, "immutable"):
                write_decision_snapshot(
                    output_root=td,
                    strategy_style="risk_off",
                    decisions=decisions,
                    daily_attention=daily,
                    weekly_attention=weekly,
                    generated_at_utc="2026-10-10T13:00:00+00:00",
                    decision_date="2026-10-10",
                    config_fingerprint="cfg123",
                )

            previous = load_previous_snapshot(
                td,
                "2026-10-11",
                strategy_style="risk_off",
            )
            self.assertEqual(previous, decisions)


class TestLiveFundamentalFreshness(unittest.TestCase):
    def test_latest_fundamental_filing_date_uses_relevant_periodic_facts(self) -> None:
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "end": "2026-06-30",
                                    "filed": "2026-08-01",
                                    "form": "10-Q",
                                },
                                {
                                    "val": 90,
                                    "end": "2026-03-31",
                                    "filed": "2026-05-01",
                                    "form": "10-Q",
                                },
                            ]
                        }
                    },
                    "InventoryNet": {
                        "units": {
                            "USD": [
                                {
                                    "val": 20,
                                    "end": "2026-06-30",
                                    "filed": "2026-08-03",
                                    "form": "10-Q/A",
                                }
                            ]
                        }
                    },
                    "UnrelatedTag": {
                        "units": {
                            "USD": [
                                {
                                    "val": 1,
                                    "end": "2026-09-30",
                                    "filed": "2026-10-09",
                                    "form": "10-Q",
                                }
                            ]
                        }
                    },
                }
            }
        }
        self.assertEqual(
            scanner.latest_fundamental_filing_date(companyfacts),
            "2026-08-03",
        )


class TestIntegratedActionEvaluation(unittest.TestCase):
    def test_action_evaluation_covers_all_quality_states_and_compactness(self) -> None:
        rows = []
        for signal_date in ("2026-01-30", "2026-02-27"):
            ready = _row("AAA")
            ready.update(
                {
                    "signal_date": signal_date,
                    "fwd_ret_20": 0.10,
                    "qqq_return_20": 0.03,
                }
            )
            weak = _row("CCC", weak=True)
            weak.update(
                {
                    "signal_date": signal_date,
                    "fwd_ret_20": -0.10,
                    "qqq_return_20": 0.03,
                }
            )
            rows.extend([ready, weak])

        evaluated = build_action_evaluation_frame(pd.DataFrame(rows))
        self.assertEqual(
            set(evaluated["action_state"]),
            {"PRIORITY_REVIEW", "AVOID"},
        )

        cohorts = summarize_action_cohorts(evaluated, horizons=(20,))
        self.assertIn("overall", set(cohorts["segment_type"]))
        self.assertIn("year", set(cohorts["segment_type"]))
        self.assertIn("regime", set(cohorts["segment_type"]))

        compactness = summarize_action_compactness(
            evaluated,
            attention_cap=1,
        )
        self.assertTrue(
            (compactness["capped_attention_count"] <= 1).all()
        )

        concentration = summarize_action_concentration(evaluated)
        self.assertEqual(
            set(concentration["action_state"]),
            {"PRIORITY_REVIEW", "AVOID"},
        )

        transitions = summarize_action_transitions(evaluated)
        self.assertEqual(int(transitions["n_transitions"].sum()), 2)


if __name__ == "__main__":
    unittest.main()
