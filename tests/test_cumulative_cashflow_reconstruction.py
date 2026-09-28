"""Regression tests for cumulative-only cash-flow-statement TTM reconstruction.

Found 2026-09-27 during pre-observation verification: US GAAP cash-flow
statements (OCF/capex/D&A) are reported as YTD-cumulative only for many
filers (AAPL, GOOGL, AMD, MU). The old _reconstruct_flow_periods derived
Q1 (rule a: H1 − Q2), Q3 (rule b: 9M − H1) and Q4 (annual − 9M) but NOT
Q2 = H1 − Q1, so the rolling TTM window broke and OCF/capex/D&A silently
fell back to stale ANNUAL values — producing mixed-period arithmetic
(annual OCF − TTM capex for FCF; TTM EBIT + annual D&A for EBITDA).

The (b2) rule fixes this: H1 − Q1(discrete, same fiscal start) → Q2.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import _reconstruct_flow_periods  # noqa: E402


def _obs(start: str, end: str, val: float, form: str = "10-Q", filed: str = "2026-09-01"):
    return (start, end, val, filed, form)


def _companyfacts_from(observations: list[tuple]) -> dict:
    units = [
        {"start": o[0], "end": o[1], "val": o[2], "filed": o[3], "form": o[4]}
        for o in observations
    ]
    return {"facts": {"us-gaap": {"TestTag": {"units": {"USD": units}}}}}


class CumulativeOnlyCashFlowTest(unittest.TestCase):
    """Apple-style: fiscal-year-start-aligned cumulative entries only."""

    def test_h1_minus_q1_derives_q2(self):
        observations = [
            # FY2025: 9M cumulative + annual
            _obs("2024-09-29", "2025-06-28", 81_754.0, "10-Q"),
            _obs("2024-09-29", "2025-09-27", 111_482.0, "10-K"),
            # FY2026: Q1 discrete (= first cumulative), H1, 9M cumulative
            _obs("2025-09-28", "2025-12-27", 53_925.0, "10-Q"),
            _obs("2025-09-28", "2026-03-28", 82_627.0, "10-Q"),
            _obs("2025-09-28", "2026-06-27", 116_996.0, "10-Q"),
        ]
        facts = _companyfacts_from(observations)
        quarters, annuals = _reconstruct_flow_periods(facts, ["TestTag"], "USD")
        q = dict(quarters)
        # Q2 FY2026 = H1 − Q1
        self.assertAlmostEqual(q["2026-03-28"], 82_627.0 - 53_925.0, places=6)
        # Q3 FY2026 = 9M − H1 (rule b)
        self.assertAlmostEqual(q["2026-06-27"], 116_996.0 - 82_627.0, places=6)
        # Q4 FY2025 = annual − 9M
        self.assertAlmostEqual(q["2025-09-27"], 111_482.0 - 81_754.0, places=6)
        # Q3 FY2025 = 9M − H1 where H1 is... no FY25 H1 entry in this fixture;
        # only 9M — Q3 FY2025 not derivable (H1 missing) → absent is acceptable
        self.assertNotIn("2025-06-28", q)

    def test_ttm_window_complete(self):
        from ai_value_scanner.scanner import _rolling_ttm_windows  # noqa: E402

        observations = [
            _obs("2024-09-29", "2025-06-28", 81_754.0, "10-Q"),
            _obs("2024-09-29", "2025-09-27", 111_482.0, "10-K"),
            _obs("2025-09-28", "2025-12-27", 53_925.0, "10-Q"),
            _obs("2025-09-28", "2026-03-28", 82_627.0, "10-Q"),
            _obs("2025-09-28", "2026-06-27", 116_996.0, "10-Q"),
        ]
        facts = _companyfacts_from(observations)
        quarters, _ = _reconstruct_flow_periods(facts, ["TestTag"], "USD")
        windows = _rolling_ttm_windows(quarters)
        self.assertTrue(len(windows) >= 1)
        latest_end, latest_val = windows[-1]
        self.assertEqual(latest_end, "2026-06-27")
        # TTM = Q4FY25 + Q1FY26 + Q2FY26 + Q3FY26
        expected = (111_482.0 - 81_754.0) + 53_925.0 + (82_627.0 - 53_925.0) + (116_996.0 - 82_627.0)
        self.assertAlmostEqual(latest_val, expected, places=6)

    def test_discrete_quarters_not_disturbed(self):
        # A filer WITH discrete quarters everywhere must be unaffected.
        observations = [
            _obs("2025-01-01", "2025-03-31", 100.0, "10-Q"),
            _obs("2025-04-01", "2025-06-30", 110.0, "10-Q"),
            _obs("2025-07-01", "2025-09-30", 120.0, "10-Q"),
            _obs("2025-10-01", "2025-12-31", 130.0, "10-K"),
            _obs("2026-01-01", "2026-03-31", 140.0, "10-Q"),
        ]
        facts = _companyfacts_from(observations)
        quarters, _ = _reconstruct_flow_periods(facts, ["TestTag"], "USD")
        q = dict(quarters)
        self.assertAlmostEqual(q["2025-03-31"], 100.0, places=6)
        self.assertAlmostEqual(q["2026-03-31"], 140.0, places=6)
        # No YTD entries → no derivations; 5 discrete quarters stand as-is.
        self.assertEqual(len(quarters), 5)

    def test_nine_month_minus_q1_not_treated_as_quarter(self):
        # 9M − Q1 spans ~6 months: the duration gate must reject it.
        observations = [
            _obs("2025-09-28", "2025-12-27", 50.0, "10-Q"),
            _obs("2025-09-28", "2026-06-27", 200.0, "10-Q"),  # 9M, no H1
        ]
        facts = _companyfacts_from(observations)
        quarters, _ = _reconstruct_flow_periods(facts, ["TestTag"], "USD")
        q = dict(quarters)
        # Q2+Q3 blob must NOT appear as a single quarter at 2026-06-27.
        self.assertNotIn("2026-06-27", q)
        # Q1 stays as observed.
        self.assertAlmostEqual(q["2025-12-27"], 50.0, places=6)


if __name__ == "__main__":
    unittest.main()
