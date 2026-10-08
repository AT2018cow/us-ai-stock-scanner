from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.config import ScanConfig
from ai_value_scanner.strategy.filtering import (
    CORE_FILTER_STEP_NAMES,
    apply_filters_with_diagnostics,
    apply_scored_or_hard_filters,
    partition_filter_steps,
)
from ai_value_scanner.strategy.selection import (
    apply_group_caps,
    dedupe_symbol_by_best_channel,
    drop_symbols,
    select_symbols_from_ranked_frames,
)


class TestSharedFilteringCore(unittest.TestCase):
    def test_partition_respects_style_structural_contract(self) -> None:
        steps = [
            ("min_price", lambda df: pd.Series(True, index=df.index)),
            ("min_drawdown_from_52w_high", lambda df: pd.Series(True, index=df.index)),
            ("min_return_20d", lambda df: pd.Series(True, index=df.index)),
            ("min_net_margin", lambda df: pd.Series(True, index=df.index)),
        ]
        hard_off, soft_off = partition_filter_steps(
            steps, "core_ai", "risk_off"
        )
        hard_on, soft_on = partition_filter_steps(
            steps, "core_ai", "risk_on"
        )
        self.assertEqual(
            [name for name, _ in hard_off],
            ["min_price", "min_drawdown_from_52w_high"],
        )
        self.assertEqual(
            [name for name, _ in soft_off],
            ["min_return_20d", "min_net_margin"],
        )
        self.assertEqual(
            [name for name, _ in hard_on],
            ["min_price", "min_return_20d"],
        )
        self.assertEqual(
            [name for name, _ in soft_on],
            ["min_drawdown_from_52w_high", "min_net_margin"],
        )
        self.assertIn("min_price", CORE_FILTER_STEP_NAMES)

    def test_scored_filter_keeps_soft_failures_and_counts_passes(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "price": [10.0, 20.0, 30.0],
                "quality": [1.0, -1.0, 1.0],
            }
        )
        steps = [
            ("min_price", lambda df: df["price"] >= 20.0),
            ("min_net_margin", lambda df: df["quality"] > 0),
        ]
        cfg = SimpleNamespace(
            filter_mode="scored",
            strategy_style="risk_off",
        )
        out, diagnostics = apply_scored_or_hard_filters(
            frame, steps, "core_ai", cfg
        )
        self.assertEqual(out["symbol"].tolist(), ["B", "C"])
        self.assertEqual(out["soft_total"].tolist(), [1, 1])
        self.assertEqual(out["soft_pass_count"].tolist(), [0, 1])
        self.assertEqual(diagnostics[-1]["step"], "min_price")
        self.assertEqual(diagnostics[-1]["remaining"], 2)

    def test_hard_filter_mode_applies_all_steps(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "price": [10.0, 20.0, 30.0],
                "quality": [1.0, -1.0, 1.0],
            }
        )
        steps = [
            ("min_price", lambda df: df["price"] >= 20.0),
            ("min_net_margin", lambda df: df["quality"] > 0),
        ]
        cfg = SimpleNamespace(
            filter_mode="hard",
            strategy_style="risk_off",
        )
        out, _ = apply_scored_or_hard_filters(
            frame, steps, "core_ai", cfg
        )
        self.assertEqual(out["symbol"].tolist(), ["C"])
        self.assertTrue(out["soft_pass_count"].isna().all())

    def test_scanner_reexports_shared_filter_engine(self) -> None:
        self.assertIs(
            scanner.apply_filters_with_diagnostics,
            apply_filters_with_diagnostics,
        )
        self.assertIs(
            scanner.apply_scored_or_hard_filters,
            apply_scored_or_hard_filters,
        )
        self.assertIs(
            scanner.partition_filter_steps,
            partition_filter_steps,
        )


class TestSharedSelectionCore(unittest.TestCase):
    def test_group_caps_preserve_rank_order(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D"],
                "sic": ["1010", "1090", "2010", "2090"],
                "watchlist_etfs": ["AIQ", "AIQ", "SMH", "SMH"],
                "composite_score": [0.9, 0.8, 0.7, 0.6],
            }
        )
        out = apply_group_caps(
            frame,
            max_per_sector=1,
            max_per_watchlist_etf_source=None,
        )
        self.assertEqual(out["symbol"].tolist(), ["A", "C"])

    def test_dedupe_keeps_best_channel_then_etf_coverage(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "AAA", "BBB"],
                "channel": ["z", "a", "x"],
                "composite_score": [0.8, 0.9, 0.7],
                "watchlist_etf_count": [3, 1, 1],
            }
        )
        out, removed = dedupe_symbol_by_best_channel(frame)
        self.assertEqual(removed, 1)
        aaa = out[out["symbol"] == "AAA"].iloc[0]
        self.assertEqual(aaa["channel"], "a")

    def test_drop_symbols_and_channel_selection(self) -> None:
        one = pd.DataFrame(
            {
                "symbol": ["A", "B"],
                "channel": ["core_ai", "core_ai"],
                "composite_score": [0.9, 0.8],
            }
        )
        two = pd.DataFrame(
            {
                "symbol": ["C", "D"],
                "channel": ["ai_enabler", "ai_enabler"],
                "composite_score": [0.95, 0.7],
            }
        )
        picks, symbols, counts = select_symbols_from_ranked_frames(
            [one, two],
            top_n=1,
            per_channel_top_n=True,
        )
        self.assertEqual(picks, ["A", "C"])
        self.assertEqual(symbols["core_ai"], ["A"])
        self.assertEqual(counts["ai_enabler"], 1)

        global_picks, _, _ = select_symbols_from_ranked_frames(
            [one, two],
            top_n=2,
            per_channel_top_n=False,
        )
        self.assertEqual(global_picks, ["C", "A"])

        kept, removed = drop_symbols(one, {"A"})
        self.assertEqual(removed, 1)
        self.assertEqual(kept["symbol"].tolist(), ["B"])

    def test_scanner_reexports_shared_selection_primitives(self) -> None:
        self.assertIs(scanner.apply_group_caps, apply_group_caps)
        self.assertIs(
            scanner.dedupe_symbol_by_best_channel,
            dedupe_symbol_by_best_channel,
        )
        self.assertIs(scanner.drop_symbols, drop_symbols)


class TestReplaySelectionParityFixes(unittest.TestCase):
    def _config(self) -> ScanConfig:
        cfg = ScanConfig()
        cfg.channel_profiles = {"core_ai": {}}
        cfg.strategy_style = "risk_off"
        cfg.filter_mode = "scored"
        cfg.max_per_sector_per_list = 1
        cfg.max_per_watchlist_etf_source_per_list = None
        cfg.enforce_unique_symbol_per_list = False
        return cfg

    @staticmethod
    def _fake_score(
        frame: pd.DataFrame,
        *args,
        **kwargs,
    ) -> pd.DataFrame:
        out = frame.copy()
        out["composite_score"] = pd.to_numeric(
            out["rank_score"], errors="coerce"
        )
        return out.sort_values("composite_score", ascending=False)

    def test_replay_applies_production_sector_cap(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "sic": ["1010", "1090", "2010"],
                "rank_score": [0.9, 0.8, 0.7],
            }
        )
        cfg = self._config()
        with (
            mock.patch.object(
                backtest,
                "build_steps_and_weights",
                return_value=([], {}),
            ),
            mock.patch.object(
                backtest,
                "score_and_rank",
                side_effect=self._fake_score,
            ),
        ):
            picks, diagnostics = backtest.rank_and_pick_symbols_with_diagnostics(
                df=frame,
                scan_config=cfg,
                list_type="momentum",
                top_n=10,
                per_channel_top_n=True,
                include_channels=["core_ai"],
            )
        self.assertEqual(picks, ["A", "C"])
        self.assertEqual(diagnostics["channel_counts"]["core_ai"], 2)

    def test_replay_low_value_applies_production_research_gate(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["KEEP", "DROP"],
                "sic": ["1010", "2010"],
                "rank_score": [0.9, 0.8],
            }
        )
        cfg = self._config()
        cfg.max_per_sector_per_list = 3

        def fake_assessment(
            ranked: pd.DataFrame,
            list_type: str,
        ) -> pd.DataFrame:
            out = ranked.copy()
            out["research_priority"] = [
                "research_now" if symbol == "KEEP" else "theme_only"
                for symbol in out["symbol"]
            ]
            out["research_score"] = [3.0, 3.0]
            out["research_risks"] = ["", ""]
            out["research_tags"] = ["", ""]
            out["research_summary"] = ["", ""]
            return out

        with (
            mock.patch.object(
                backtest,
                "build_steps_and_weights",
                return_value=([], {}),
            ),
            mock.patch.object(
                backtest,
                "score_and_rank",
                side_effect=self._fake_score,
            ),
            mock.patch.object(
                backtest,
                "apply_research_assessment",
                side_effect=fake_assessment,
            ),
        ):
            picks, _ = backtest.rank_and_pick_symbols_with_diagnostics(
                df=frame,
                scan_config=cfg,
                list_type="low_value",
                top_n=10,
                per_channel_top_n=True,
                include_channels=["core_ai"],
            )
        self.assertEqual(picks, ["KEEP"])


if __name__ == "__main__":
    unittest.main()
