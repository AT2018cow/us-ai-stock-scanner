from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.features.derived import compute_cross_section_derived_features


def _sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "revenue_yoy": [0.20, np.nan, 0.10],
            "net_income_yoy": [0.40, np.nan, -0.20],
            "adjusted_net_income_yoy": [0.10, np.nan, 0.30],
            "adjusted_ebit_yoy": [0.15, np.nan, np.nan],
            "ebit_yoy": [0.12, 0.25, -0.20],
            "return_20d": [0.08, np.nan, -0.10],
            "return_60d": [0.06, np.nan, -0.20],
            "avg_dollar_volume_20d": [50_000_000.0, 0.0, np.nan],
        },
        index=pd.Index(["A", "B", "C"], name="symbol"),
    )


class TestCrossSectionDerivedFeatureCore(unittest.TestCase):
    def test_golden_values_and_missing_contract(self) -> None:
        original = _sample()
        before = original.copy(deep=True)
        actual = compute_cross_section_derived_features(
            original,
            earnings_yoy_col="adjusted_net_income_yoy",
            assumed_position_usd=250_000.0,
        )
        pd.testing.assert_frame_equal(original, before)
        self.assertEqual(tuple(actual), (
            "expectation_proxy",
            "cycle_proxy",
            "adv_participation",
            "estimated_slippage_bps",
        ))
        self.assertTrue(all(x.index.equals(original.index) for x in actual.values()))
        self.assertAlmostEqual(float(actual["expectation_proxy"].loc["A"]), 0.08, places=12)
        self.assertAlmostEqual(float(actual["cycle_proxy"].loc["A"]), -0.05, places=12)
        self.assertAlmostEqual(float(actual["adv_participation"].loc["A"]), 0.005, places=12)
        self.assertAlmostEqual(
            float(actual["estimated_slippage_bps"].loc["A"]),
            14.142135623730951,
            places=10,
        )
        self.assertEqual(float(actual["expectation_proxy"].loc["B"]), 0.0)
        self.assertTrue(math.isnan(float(actual["cycle_proxy"].loc["B"])))
        self.assertTrue(math.isnan(float(actual["adv_participation"].loc["B"])))
        self.assertTrue(math.isnan(float(actual["estimated_slippage_bps"].loc["B"])))
        self.assertAlmostEqual(float(actual["cycle_proxy"].loc["C"]), -0.30, places=12)

    def test_earnings_input_respects_adjusted_quality_switch(self) -> None:
        frame = _sample()
        adjusted = compute_cross_section_derived_features(
            frame,
            earnings_yoy_col="adjusted_net_income_yoy",
            assumed_position_usd=250_000.0,
        )
        reported = compute_cross_section_derived_features(
            frame,
            earnings_yoy_col="net_income_yoy",
            assumed_position_usd=250_000.0,
        )
        self.assertAlmostEqual(float(adjusted["expectation_proxy"].loc["A"]), 0.08, places=12)
        self.assertAlmostEqual(float(reported["expectation_proxy"].loc["A"]), 0.23, places=12)
        pd.testing.assert_series_equal(adjusted["cycle_proxy"], reported["cycle_proxy"])
        pd.testing.assert_series_equal(adjusted["adv_participation"], reported["adv_participation"])

    def test_negative_participation_clips_only_slippage(self) -> None:
        frame = _sample().iloc[:1].copy()
        frame["avg_dollar_volume_20d"] = -50_000_000.0
        out = compute_cross_section_derived_features(
            frame,
            earnings_yoy_col="adjusted_net_income_yoy",
            assumed_position_usd=250_000.0,
        )
        self.assertEqual(float(out["adv_participation"].iloc[0]), -0.005)
        self.assertEqual(float(out["estimated_slippage_bps"].iloc[0]), 0.0)

    def test_both_adapters_share_canonical_function(self) -> None:
        self.assertIs(scanner.compute_cross_section_derived_features, compute_cross_section_derived_features)
        self.assertIs(backtest.compute_cross_section_derived_features, compute_cross_section_derived_features)


if __name__ == "__main__":
    unittest.main()
