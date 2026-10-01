from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


def _load_ic():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "ic_analysis.py"
    spec = importlib.util.spec_from_file_location("ic_analysis", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load ic_analysis.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ic = _load_ic()


class TestTstatNw(unittest.TestCase):
    def test_iid_noise_matches_plain_t(self) -> None:
        rng = np.random.default_rng(11)
        vals = list(rng.normal(0.05, 0.2, size=60))
        t = ic.tstat(vals)
        t_nw = ic.tstat_nw(vals, 3)
        self.assertTrue(np.isfinite(t) and np.isfinite(t_nw))
        self.assertLess(abs(t_nw - t) / abs(t), 0.5)

    def test_autocorrelated_series_deflated(self) -> None:
        rng = np.random.default_rng(12)
        eps = rng.normal(0, 0.05, size=120)
        x = [0.05]
        for e in eps[1:]:
            x.append(0.9 * x[-1] + e)
        t = ic.tstat(x)
        t_nw = ic.tstat_nw(x, 17)
        self.assertTrue(np.isfinite(t) and np.isfinite(t_nw))
        self.assertLess(t_nw, t)
        self.assertGreater(t / max(t_nw, 1e-9), 1.5)

    def test_edge_cases_nan(self) -> None:
        self.assertFalse(np.isfinite(ic.tstat_nw([0.1, 0.1], 5)))
        self.assertFalse(np.isfinite(ic.tstat_nw([0.5, 0.5, 0.5, 0.5], 2)))
        self.assertFalse(np.isfinite(ic.tstat_nw([], 2)))

    def test_overlap_lags_from_spacing(self) -> None:
        weekly = [(pd.Timestamp("2026-01-05", tz="UTC") + pd.Timedelta(days=7 * i)).strftime("%Y-%m-%d")
                  for i in range(10)]
        self.assertEqual(ic.overlap_lags(weekly, 120), 17)
        monthly = [f"2026-{m:02d}-01" for m in range(1, 7)]
        self.assertEqual(ic.overlap_lags(monthly, 60), 2)
        self.assertEqual(ic.overlap_lags(["2026-01-01"], 120), 1)

if __name__ == "__main__":
    unittest.main()
