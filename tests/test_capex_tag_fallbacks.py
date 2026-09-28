"""Regression tests for CAPEX tag coverage fallbacks (2026-09-27).

Third tag-coverage gap of the same class (after DA_TAGS twice): QCOM and
GEV tag capex as generic PaymentsToAcquireProductiveAssets — absent from
CAPEX_TAGS their FCF silently became None (fcf_yield NaN, soft dims
auto-fail). ANET's Q4 derivation also required the fallback tag to close
the fiscal year (4 quarters now sum exactly to the 10-K annual).

Fixtures cover: ProductiveAssets-only filer (QCOM-style), PP&E-primary
with fallback filling a missing quarter (ANET-style), and priority —
same (start,end) under PP&E and ProductiveAssets must resolve to PP&E.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import (  # noqa: E402
    CAPEX_TAGS,
    pick_latest_and_prev_ttm,
    _reconstruct_flow_periods,
)


def _facts_from(observations: list[dict]) -> dict:
    """observations: list of (tag, start, end, val, form)."""
    units: dict[str, list[dict]] = {}
    for tag, start, end, val, form in observations:
        units.setdefault(tag, []).append(
            {"start": start, "end": end, "val": val, "form": form, "filed": "2026-09-01"}
        )
    return {"facts": {"us-gaap": {t: {"units": {"USD": v}} for t, v in units.items()}}}


class CapexTagFallbackTest(unittest.TestCase):
    def test_productive_assets_only_filer(self):
        """QCOM-style: no PP&E tag at all; TTM must come from the fallback."""
        obs = [("PaymentsToAcquireProductiveAssets", "2025-01-01", "2025-03-31", 400.0, "10-Q")]
        obs += [("PaymentsToAcquireProductiveAssets", "2025-01-01", "2025-06-30", 800.0, "10-Q")]
        obs += [("PaymentsToAcquireProductiveAssets", "2025-01-01", "2025-09-30", 1200.0, "10-Q")]
        obs += [("PaymentsToAcquireProductiveAssets", "2025-01-01", "2025-12-31", 1600.0, "10-K")]
        obs += [("PaymentsToAcquireProductiveAssets", "2026-01-01", "2026-03-31", 450.0, "10-Q")]
        facts = _facts_from(obs)
        ttm, _ = pick_latest_and_prev_ttm(facts, CAPEX_TAGS, "USD")
        # TTM ending Q1-2026 = Q4-25 (400) + Q1-26 (450) → 400+450... wait:
        # TTM = Q2+Q3+Q4-25 + Q1-26 = 400 + 400 + 400 + 450 = 1650
        self.assertAlmostEqual(ttm, 1650.0, places=6)

    def test_fallback_closes_missing_q4(self):
        """ANET-style: 9M cumulative under PP&E, but the annual only under
        the fallback tag; Q4 = annual − 9M must close the fiscal year."""
        obs = [
            ("PaymentsToAcquirePropertyPlantAndEquipment", "2025-01-01", "2025-03-31", 100.0, "10-Q"),
            ("PaymentsToAcquirePropertyPlantAndEquipment", "2025-01-01", "2025-06-30", 190.0, "10-Q"),
            ("PaymentsToAcquirePropertyPlantAndEquipment", "2025-01-01", "2025-09-30", 280.0, "10-Q"),
            ("PaymentsToAcquireProductiveAssets", "2025-01-01", "2025-12-31", 400.0, "10-K"),
            ("PaymentsToAcquirePropertyPlantAndEquipment", "2026-01-01", "2026-03-31", 120.0, "10-Q"),
        ]
        facts = _facts_from(obs)
        quarters, annuals = _reconstruct_flow_periods(facts, CAPEX_TAGS, "USD")
        q = dict(quarters)
        self.assertAlmostEqual(q["2025-12-31"], 400.0 - 280.0, places=6)
        # Annual closure: Q1+Q2+Q3+Q4 = 400
        self.assertAlmostEqual(
            q["2025-03-31"] + q["2025-06-30"] + q["2025-09-30"] + q["2025-12-31"],
            400.0,
            places=6,
        )
        # TTM ending Q1-2026 = (400-280) + 120 + Q2-25 + Q3-25
        ttm, _ = pick_latest_and_prev_ttm(facts, CAPEX_TAGS, "USD")
        expected = (400.0 - 280.0) + 120.0 + 90.0 + 90.0
        self.assertAlmostEqual(ttm, expected, places=6)

    def test_priority_ppE_wins_on_collision(self):
        """Same (start,end) under PP&E and ProductiveAssets → PP&E value."""
        obs = [
            ("PaymentsToAcquirePropertyPlantAndEquipment", "2025-01-01", "2025-03-31", 100.0, "10-Q"),
            ("PaymentsToAcquireProductiveAssets", "2025-01-01", "2025-03-31", 999.0, "10-Q"),
        ]
        facts = _facts_from(obs)
        quarters, _ = _reconstruct_flow_periods(facts, CAPEX_TAGS, "USD")
        q = dict(quarters)
        self.assertAlmostEqual(q["2025-03-31"], 100.0, places=6)


if __name__ == "__main__":
    unittest.main()
