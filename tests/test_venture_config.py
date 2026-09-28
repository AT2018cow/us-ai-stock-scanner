"""Venture config semantics (docs/multi_theme_expansion.md §6.3)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import load_config, build_filter_steps, partition_filter_steps


class VentureConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config("configs/config.venture.nuclear.json")

    def test_definitional_window(self):
        self.assertAlmostEqual(self.cfg.min_market_cap, 1e8)
        self.assertAlmostEqual(self.cfg.max_market_cap, 3e9)
        self.assertAlmostEqual(self.cfg.min_dollar_volume, 5e5)

    def test_no_profitability_gates(self):
        self.assertTrue(self.cfg.require_positive_revenue)
        self.assertFalse(self.cfg.require_positive_net_income)
        self.assertFalse(self.cfg.require_positive_operating_cash_flow)
        self.assertFalse(self.cfg.require_positive_free_cash_flow)
        self.assertFalse(self.cfg.require_positive_ebit)

    def test_dilution_monitor_only(self):
        self.assertIsNone(self.cfg.max_shares_yoy)

    def test_hard_gate_partition_contains_window_cap(self):
        prof = (self.cfg.channel_profiles or {})["nuclear"]
        steps = build_filter_steps(self.cfg, "nuclear", prof)
        hard, _soft = partition_filter_steps(steps, "nuclear")
        hard_names = {n for n, _ in hard}
        self.assertIn("min_market_cap", hard_names)
        self.assertIn("max_market_cap", hard_names, "$3B 上限必须是硬门（核心集合已扩展）")
        # 风格结构门必须全部关闭：早期 10x 路径常在 SMA200 下方
        for banned in ("min_drawdown_from_52w_high", "max_range_position_52w", "max_price_to_sma200", "min_price_to_sma200"):
            self.assertNotIn(banned, hard_names, f"{banned} 不应是 venture 硬门")

    def test_venture_scoring_weights(self):
        prof = (self.cfg.channel_profiles or {})["nuclear"]
        w = prof["score_weights"]
        self.assertAlmostEqual(w["revenue_yoy"], 0.25)
        self.assertAlmostEqual(w["ai_link_score"], 0.20)
        self.assertAlmostEqual(w["soft_pass_rate"], 0.15)
        self.assertAlmostEqual(w["ps_discount"], 0.0)
        self.assertAlmostEqual(w["pe_discount"], 0.0)
        self.assertAlmostEqual(w["fundamental_quality_score"], 0.0)

    def test_research_gates_open(self):
        self.assertEqual(self.cfg.low_value_excluded_research_risks, [])
        self.assertEqual(self.cfg.low_value_min_research_score, 0.0)
        self.assertIn("left_side_watch", self.cfg.low_value_allowed_research_priorities)
        self.assertNotIn("avoid_for_now", self.cfg.low_value_allowed_research_priorities)

    def test_isolation_kept_from_theme_base(self):
        self.assertFalse(self.cfg.archive_watchlist_snapshots)
        self.assertEqual(self.cfg.watchlist_csv_path, "data/venture_watchlist_nuclear.json" if False else "data/venture_watchlist_nuclear.csv")
        self.assertEqual(self.cfg.ai_link_weight_disclosure, 0.0)


if __name__ == "__main__":
    unittest.main()
