from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_flow_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "flow_tracker.py"
    spec = importlib.util.spec_from_file_location("flow_tracker", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load flow_tracker.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flow = _load_flow_module()


def _prints(prices: list[float], size: int = 100, venue: str = "Q") -> list:
    return [(p, size, venue) for p in prices]


class TestComputeDayMetrics(unittest.TestCase):
    def test_empty_prints_returns_none(self) -> None:
        self.assertIsNone(flow.compute_day_metrics([]))

    def test_tick_rule_buy_sell_split(self) -> None:
        # 100, 101(up=buy), 101(unchanged=half), 99(down=sell)
        m = flow.compute_day_metrics(_prints([100.0, 101.0, 101.0, 99.0], size=1000))
        self.assertEqual(m["prints"], 4)
        self.assertEqual(m["volume"], 4000)
        # buy: 1000 (up) + 500 (half) = 1500 of 4000
        self.assertAlmostEqual(m["blocks_100k_buy_sh"], 1500.0)

    def test_block_tiers(self) -> None:
        # $200 x 1000sh = $200K block (>=100K, <1M); $2000 x 1000 = $2M block
        prints = _prints([200.0], size=1000) + _prints([2000.0], size=1000)
        m = flow.compute_day_metrics(prints)
        self.assertEqual(m["n_blocks_100k"], 2)
        self.assertEqual(m["n_blocks_1m"], 1)
        self.assertAlmostEqual(m["mega_max_m"], 2.0)

    def test_dark_share_counts_venue_d(self) -> None:
        prints = _prints([10.0], size=100) + [(10.0, 100, "D")]
        m = flow.compute_day_metrics(prints)
        self.assertAlmostEqual(m["dark_share"], 0.5)


class TestSummarize(unittest.TestCase):
    def _days(self, n: int, **overrides) -> dict:
        base = {
            "prints": 100, "volume": 100000, "notional_m": 10.0, "dark_share": 0.5,
            "vwap": 100.0, "n_blocks_100k": 5, "blocks_100k_sh": 5000,
            "blocks_100k_buy_sh": 3000.0, "n_blocks_1m": 0, "blocks_1m_sh": 0,
            "blocks_1m_buy_sh": 0.0, "mega_max_m": 0.5, "close": 100.0,
        }
        base.update(overrides)
        return {f"2026-09-{d:02d}": {"date": f"2026-09-{d:02d}", **base} for d in range(14, 14 + n)}

    def test_all_zero_days_returns_none(self) -> None:
        import unittest.mock as mock

        with mock.patch.object(flow, "read_cache", return_value=self._days(8, volume=0)):
            self.assertIsNone(flow.summarize("ZERO", 8))

    def test_empty_cache_returns_none(self) -> None:
        import unittest.mock as mock

        with mock.patch.object(flow, "read_cache", return_value={}):
            self.assertIsNone(flow.summarize("NONE", 8))

    def test_verdict_thresholds(self) -> None:
        import unittest.mock as mock

        rows = self._days(8)
        rows["2026-09-21"]["blocks_1m_sh"] = 10000
        rows["2026-09-21"]["blocks_1m_buy_sh"] = 7000.0
        rows["2026-09-21"]["n_blocks_1m"] = 6
        rows["2026-09-21"]["close"] = 101.0
        with mock.patch.object(flow, "read_cache", return_value=rows):
            s = flow.summarize("T", 8)
        self.assertEqual(s["tier"], "1m")
        self.assertAlmostEqual(s["buy_ratio"], 0.7)
        self.assertEqual(s["verdict"], "accumulate_confirm")

    def test_distribute_verdict(self) -> None:
        import unittest.mock as mock

        rows = self._days(8, blocks_1m_sh=10000, blocks_1m_buy_sh=2500.0, n_blocks_1m=6)
        with mock.patch.object(flow, "read_cache", return_value=rows):
            s = flow.summarize("T", 8)
        self.assertEqual(s["verdict"], "distribute")

    def test_tier_falls_back_to_100k(self) -> None:
        import unittest.mock as mock

        with mock.patch.object(flow, "read_cache", return_value=self._days(8)):
            s = flow.summarize("T", 8)
        self.assertEqual(s["tier"], "100k")
        self.assertAlmostEqual(s["buy_ratio"], 0.6)


class TestHelpers(unittest.TestCase):
    def test_sanitize_symbol_accepts_valid(self) -> None:
        self.assertEqual(flow.sanitize_symbol("brk.b"), "BRK.B")
        self.assertEqual(flow.sanitize_symbol("CRDO"), "CRDO")

    def test_sanitize_symbol_rejects_traversal(self) -> None:
        with self.assertRaises(SystemExit):
            flow.sanitize_symbol("../evil")
        with self.assertRaises(SystemExit):
            flow.sanitize_symbol("A/B")

    def test_trading_days_skips_weekends(self) -> None:
        days = flow.trading_days(5, end_date="2026-09-29")
        self.assertEqual(days[0], "2026-09-23")
        self.assertEqual(len(days), 5)
        import datetime as _dt

        for d in days:
            self.assertLess(_dt.date.fromisoformat(d).weekday(), 5)


if __name__ == "__main__":
    unittest.main()
