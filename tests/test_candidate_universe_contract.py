from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ai_value_scanner.decision import (
    ActionState,
    EntryDecision,
    EntryState,
    QualityDecision,
    QualityGrade,
    StockDecision,
)
from ai_value_scanner.decision.universe import (
    ACTIVE_ASSET_MISSING,
    DOLLAR_VOLUME_BELOW_MIN,
    DOLLAR_VOLUME_MISSING,
    EXCHANGE_NOT_ENABLED,
    NOT_TRADABLE,
    PRICE_BELOW_MIN,
    PRICE_MISSING,
    SEC_MAPPING_MISSING,
    apply_price_liquidity_prefilter,
    attach_watchlist_provenance,
    build_candidate_universe_summary,
    classify_asset_mapping_universe,
)
from ai_value_scanner.reporting.snapshot import write_decision_snapshot


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from validate_mvp_snapshot import validate_snapshot
finally:
    sys.path.pop(0)


def _decision(symbol: str = "KEEP") -> StockDecision:
    return StockDecision(
        schema_version="1",
        symbol=symbol,
        company_name=f"{symbol} Corp",
        decision_date="2026-10-09",
        generated_at_utc="2026-10-10T12:00:00+00:00",
        quality=QualityDecision(
            grade=QualityGrade.A,
            score=0.90,
            confidence=1.0,
            component_scores={"profitability_cash": 0.9},
            positives=(),
            risks=(),
            missing=(),
            data_asof="2026-08-01",
        ),
        entry=EntryDecision(
            state=EntryState.ENTRY_READY,
            score=0.90,
            confidence=1.0,
            positives=(),
            risks=(),
            market_asof="2026-10-09",
        ),
        action_state=ActionState.PRIORITY_REVIEW,
        priority=1,
        rationale=(),
        review_trigger="Review now.",
        source_lists=(),
        provenance={"code_sha": "abc"},
    )


class TestCandidateUniverseClassification(unittest.TestCase):
    def test_asset_mapping_reasons_are_mutually_exclusive(self) -> None:
        assets = [
            {"symbol": "KEEP", "status": "active", "tradable": True, "exchange": "NASDAQ"},
            {"symbol": "HALT", "status": "active", "tradable": False, "exchange": "NASDAQ"},
            {"symbol": "OTC1", "status": "active", "tradable": True, "exchange": "OTC"},
            {"symbol": "NOMAP", "status": "active", "tradable": True, "exchange": "NYSE"},
        ]
        mapping = pd.DataFrame(
            {
                "symbol": ["KEEP", "HALT", "OTC1"],
                "cik": ["1", "2", "3"],
            }
        )
        eligible, exclusions = classify_asset_mapping_universe(
            discovery_symbols={"KEEP", "HALT", "OTC1", "NOMAP", "MISSING"},
            assets=assets,
            sec_mapping=mapping,
            enabled_exchanges=["NYSE", "NASDAQ"],
        )
        self.assertEqual(eligible, {"KEEP"})
        by_symbol = {row["symbol"]: row["reason_code"] for row in exclusions}
        self.assertEqual(
            by_symbol,
            {
                "HALT": NOT_TRADABLE,
                "MISSING": ACTIVE_ASSET_MISSING,
                "NOMAP": SEC_MAPPING_MISSING,
                "OTC1": EXCHANGE_NOT_ENABLED,
            },
        )

    def test_price_liquidity_prefilter_preserves_feed_and_thresholds(self) -> None:
        frame = pd.DataFrame(
            [
                {"symbol": "KEEP", "price": 20.0, "dollar_volume": 5_000_000.0},
                {"symbol": "NOPX", "price": None, "dollar_volume": None},
                {"symbol": "PENNY", "price": 0.5, "dollar_volume": 5_000_000.0},
                {"symbol": "NOVOL", "price": 10.0, "dollar_volume": None},
                {"symbol": "QUBT", "price": 7.43, "dollar_volume": 1_410_000.0},
            ]
        )
        kept, exclusions = apply_price_liquidity_prefilter(
            frame,
            min_price=1.0,
            min_dollar_volume=2_000_000.0,
            market_data_feed="iex",
        )
        self.assertEqual(kept["symbol"].tolist(), ["KEEP"])
        by_symbol = {row["symbol"]: row for row in exclusions}
        self.assertEqual(by_symbol["NOPX"]["reason_code"], PRICE_MISSING)
        self.assertEqual(by_symbol["PENNY"]["reason_code"], PRICE_BELOW_MIN)
        self.assertEqual(by_symbol["NOVOL"]["reason_code"], DOLLAR_VOLUME_MISSING)
        self.assertEqual(by_symbol["QUBT"]["reason_code"], DOLLAR_VOLUME_BELOW_MIN)
        self.assertEqual(by_symbol["QUBT"]["market_data_feed"], "iex")
        self.assertEqual(by_symbol["QUBT"]["dollar_volume"], 1_410_000.0)
        self.assertEqual(by_symbol["QUBT"]["min_dollar_volume"], 2_000_000.0)

    def test_watchlist_provenance_and_conservation_summary(self) -> None:
        exclusions = [
            {
                "symbol": "QUBT",
                "status": "excluded",
                "exclusion_stage": "price_liquidity_prefilter",
                "reason_code": DOLLAR_VOLUME_BELOW_MIN,
                "asset_status": "active",
                "tradable": True,
                "exchange": "NYSE",
                "price": 7.43,
                "dollar_volume": 1_410_000.0,
                "market_data_feed": "iex",
                "min_price": 1.0,
                "min_dollar_volume": 2_000_000.0,
                "watchlist_bucket": None,
                "watchlist_etf_count": None,
                "watchlist_etfs": None,
            }
        ]
        watchlist = pd.DataFrame(
            [
                {
                    "symbol": "QUBT",
                    "watchlist_bucket": "core_ai",
                    "watchlist_etf_count": 2,
                    "watchlist_etfs": "AIQ,ARKQ",
                }
            ]
        )
        enriched = attach_watchlist_provenance(exclusions, watchlist)
        self.assertEqual(enriched[0]["watchlist_bucket"], "core_ai")
        self.assertEqual(enriched[0]["watchlist_etf_count"], 2)

        summary = build_candidate_universe_summary(
            discovery_symbols={"KEEP", "QUBT"},
            decision_symbols={"KEEP"},
            exclusions=enriched,
            tradable_mapped_symbols=2,
            post_sample_symbols=2,
            market_data_feed="iex",
            min_price=1.0,
            min_dollar_volume=2_000_000.0,
        )
        self.assertEqual(summary["discovery_unique_symbols"], 2)
        self.assertEqual(summary["decision_universe_symbols"], 1)
        self.assertEqual(summary["excluded_symbols"], 1)
        self.assertEqual(
            summary["exclusion_reason_counts"],
            {DOLLAR_VOLUME_BELOW_MIN: 1},
        )

        with self.assertRaisesRegex(ValueError, "conservation"):
            build_candidate_universe_summary(
                discovery_symbols={"KEEP", "QUBT", "LOST"},
                decision_symbols={"KEEP"},
                exclusions=enriched,
                tradable_mapped_symbols=2,
                post_sample_symbols=2,
                market_data_feed="iex",
                min_price=1.0,
                min_dollar_volume=2_000_000.0,
            )


class TestCandidateUniverseSnapshotContract(unittest.TestCase):
    def test_snapshot_validator_requires_and_reconciles_exclusions(self) -> None:
        decision = _decision()
        exclusion = {
            "symbol": "QUBT",
            "status": "excluded",
            "exclusion_stage": "price_liquidity_prefilter",
            "reason_code": DOLLAR_VOLUME_BELOW_MIN,
            "asset_status": "active",
            "tradable": True,
            "exchange": "NYSE",
            "price": 7.43,
            "dollar_volume": 1_410_000.0,
            "market_data_feed": "iex",
            "min_price": 1.0,
            "min_dollar_volume": 2_000_000.0,
            "watchlist_bucket": "core_ai",
            "watchlist_etf_count": 2,
            "watchlist_etfs": "AIQ,ARKQ",
        }
        summary = build_candidate_universe_summary(
            discovery_symbols={"KEEP", "QUBT"},
            decision_symbols={"KEEP"},
            exclusions=[exclusion],
            tradable_mapped_symbols=2,
            post_sample_symbols=2,
            market_data_feed="iex",
            min_price=1.0,
            min_dollar_volume=2_000_000.0,
        )
        with tempfile.TemporaryDirectory() as td:
            paths = write_decision_snapshot(
                output_root=td,
                strategy_style="risk_off",
                decisions=(decision,),
                daily_attention=(decision,),
                weekly_attention=(decision,),
                generated_at_utc=decision.generated_at_utc,
                decision_date=decision.decision_date,
                config_fingerprint="cfg",
                code_sha="abc",
                universe_exclusions=(exclusion,),
                candidate_universe_summary=summary,
            )
            self.assertTrue(paths.universe_exclusions_jsonl.exists())
            result = validate_snapshot(paths.root)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(
                result["counts"]["candidate_universe"]["excluded_symbols"],
                1,
            )

            paths.universe_exclusions_jsonl.write_text("", encoding="utf-8")
            broken = validate_snapshot(paths.root)
            self.assertFalse(broken["ok"])
            self.assertTrue(
                any("excluded count" in error or "conservation" in error for error in broken["errors"])
            )


class TestFilingCikCoalesce(unittest.TestCase):
    def test_filing_side_wins_and_no_suffixed_columns_remain(self) -> None:
        from ai_value_scanner.scanner import _coalesce_filing_cik

        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "cik": ["0000000001", "0000000002", "0000000003"],
                "cik_filing": ["0000000099", None, ""],
            }
        )
        out = _coalesce_filing_cik(frame)
        self.assertEqual(out["cik"].tolist(), ["0000000099", "0000000002", "0000000003"])
        self.assertNotIn("cik_filing", out.columns)
        self.assertNotIn("cik_x", out.columns)
        self.assertNotIn("cik_y", out.columns)

    def test_absent_filing_column_is_noop(self) -> None:
        from ai_value_scanner.scanner import _coalesce_filing_cik

        frame = pd.DataFrame({"symbol": ["A"], "cik": ["0000000001"]})
        out = _coalesce_filing_cik(frame)
        self.assertEqual(out["cik"].tolist(), ["0000000001"])


if __name__ == "__main__":
    unittest.main()
