from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.features.peer_valuation import compute_peer_relative_valuation


class TestPeerRelativeValuationCore(unittest.TestCase):
    def test_excludes_stale_and_invalid_rows_from_peer_cohort(self) -> None:
        frame = pd.DataFrame(
            {
                "sic": ["1000"] * 7 + ["2000"] * 4 + [None],
                "ps": [1.0, 2.0, 3.0, 4.0, 5.0, 100.0, -1.0, 2.0, 4.0, 6.0, 8.0, 3.0],
                "pe": [10.0, 20.0, 30.0, 40.0, 50.0, 1000.0, -10.0, 12.0, 14.0, 16.0, 18.0, 22.0],
                "shares_stale": [False, False, False, False, False, True, False, False, False, False, False, False],
            },
            index=[f"R{i}" for i in range(12)],
        )
        before = frame.copy(deep=True)

        out = compute_peer_relative_valuation(frame, min_peer_count=5)

        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(float(out["peer_median_ps"].loc["R0"]), 3.0)
        self.assertEqual(float(out["peer_median_pe"].loc["R0"]), 30.0)
        self.assertAlmostEqual(float(out["ps_discount"].loc["R0"]), 2.0 / 3.0, places=12)
        self.assertAlmostEqual(float(out["pe_discount"].loc["R0"]), 2.0 / 3.0, places=12)

        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R0"]), 0.2)
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R1"]), 0.4)
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R2"]), 0.6)
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R3"]), 0.8)
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R4"]), 1.0)

        # Stale and invalid multiples do not participate and retain neutral rank.
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R5"]), 0.5)
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R6"]), 0.5)
        self.assertEqual(float(out["pe_percentile_in_sic"].loc["R5"]), 0.5)
        self.assertEqual(float(out["pe_percentile_in_sic"].loc["R6"]), 0.5)

        # Four-member SIC cohorts are intentionally neutral for percentile.
        for idx in ["R7", "R8", "R9", "R10"]:
            self.assertEqual(float(out["ps_percentile_in_sic"].loc[idx]), 0.5)
            self.assertEqual(float(out["pe_percentile_in_sic"].loc[idx]), 0.5)
            self.assertEqual(float(out["peer_median_ps"].loc[idx]), 5.0)
            self.assertEqual(float(out["peer_median_pe"].loc[idx]), 15.0)

        self.assertTrue(math.isnan(float(out["peer_median_ps"].loc["R11"])))
        self.assertTrue(math.isnan(float(out["peer_median_pe"].loc["R11"])))
        self.assertEqual(float(out["ps_percentile_in_sic"].loc["R11"]), 0.5)
        self.assertEqual(float(out["pe_percentile_in_sic"].loc["R11"]), 0.5)

    def test_ps_and_pe_eligibility_are_independent(self) -> None:
        frame = pd.DataFrame(
            {
                "sic": ["3000"] * 5,
                "ps": [1.0, 2.0, 3.0, 4.0, 5.0],
                "pe": [10.0, 20.0, 30.0, 40.0, -1.0],
                "shares_stale": [False] * 5,
            }
        )
        out = compute_peer_relative_valuation(frame, min_peer_count=5)

        self.assertEqual(out["ps_percentile_in_sic"].tolist(), [0.2, 0.4, 0.6, 0.8, 1.0])
        self.assertEqual(out["pe_percentile_in_sic"].tolist(), [0.5] * 5)
        self.assertEqual(out["peer_median_ps"].tolist(), [3.0] * 5)
        self.assertEqual(out["peer_median_pe"].tolist(), [25.0] * 5)

    def test_missing_stale_column_defaults_to_fresh(self) -> None:
        frame = pd.DataFrame(
            {
                "sic": ["4000"] * 5,
                "ps": [1.0, 2.0, 3.0, 4.0, 5.0],
                "pe": [5.0, 6.0, 7.0, 8.0, 9.0],
            }
        )
        out = compute_peer_relative_valuation(frame)
        self.assertEqual(out["peer_median_ps"].tolist(), [3.0] * 5)
        self.assertEqual(out["pe_percentile_in_sic"].tolist(), [0.2, 0.4, 0.6, 0.8, 1.0])

    def test_scanner_and_replay_use_same_canonical_function(self) -> None:
        self.assertIs(scanner.compute_peer_relative_valuation, compute_peer_relative_valuation)
        self.assertIs(backtest.compute_peer_relative_valuation, compute_peer_relative_valuation)


if __name__ == "__main__":
    unittest.main()
