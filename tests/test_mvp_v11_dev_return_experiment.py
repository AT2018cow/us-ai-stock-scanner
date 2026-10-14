"""Synthetic only: check development report statistics and locked protocol."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ai_value_scanner.research.mvp_v11_dev_reports import paired_metrics, date_quality_report
from scripts.mvp_v11_dev_return_experiment import (
    APPROVAL_PHRASE, _read_protocol, EXPECTED_MEMBERSHIP_SHA,
)


def _rows():
    return pd.DataFrame([
        {
            "candidate_id": candidate, "signal_date": day,
            "horizon": 60, "cap": 15,
            "primary_paired_valid": True,
            "event_sensitivity_valid": day != "2024-02-29",
            "score_sensitivity_valid": day != "2024-01-31",
            "paired_delta_net_qqq_excess": delta if candidate != "B0" else 0.0,
            "b0_net_qqq_excess": 0.05,
            "candidate_net_qqq_excess": 0.05 + (delta if candidate != "B0" else 0),
            "n_topk_swaps": 1 if candidate != "B0" else 0,
        }
        for candidate in ("B0", "E1")
        for day, delta in [
            ("2024-01-31", 0.01),
            ("2024-02-29", -0.02),
            ("2024-03-29", 0.03),
        ]
    ])


class TestMvpV11ReturnStudyContract(unittest.TestCase):
    def test_date_equal_not_symbol_weighted_and_independent_sensitivity(self):
        metrics = paired_metrics(_rows())
        r = metrics.loc[metrics.candidate_id == "E1"].iloc[0]
        self.assertEqual(r.n_dates_valid, 3)
        self.assertAlmostEqual(r.mean_paired_delta, (0.01 - 0.02 + 0.03) / 3)
        self.assertAlmostEqual(r.mean_event_sensitive_delta, (0.01 + 0.03) / 2)
        self.assertAlmostEqual(r.mean_score_sensitive_delta, (-0.02 + 0.03) / 2)
        self.assertEqual(r.n_dates_event_excluded, 1)
        self.assertEqual(r.n_dates_score_excluded, 1)
        self.assertTrue(r.economic_reference_met)
        b = metrics.loc[metrics.candidate_id == "B0"].iloc[0]
        self.assertEqual(b.research_effect, "NO_EFFECT")
        self.assertAlmostEqual(b.mean_paired_delta, 0.0)

    def test_missing_label_date_never_has_return_and_sensitivity_not_restore(self):
        rows = _rows()
        idx = (rows.candidate_id == "E1") & (rows.signal_date == "2024-02-29")
        rows.loc[idx, ["primary_paired_valid", "event_sensitivity_valid",
                       "score_sensitivity_valid"]] = False
        rows.loc[idx, "paired_delta_net_qqq_excess"] = float("nan")
        result = paired_metrics(rows)
        r = result.loc[result.candidate_id == "E1"].iloc[0]
        self.assertEqual(r.n_dates_valid, 2)
        self.assertAlmostEqual(r.mean_paired_delta, .02)
        rows.loc[idx, "event_sensitivity_valid"] = True
        with self.assertRaisesRegex(ValueError, "sensitivity"):
            paired_metrics(rows)

    def test_b0_nonzero_delta_rejected(self):
        rows = _rows()
        rows.loc[(rows.candidate_id == "B0").idxmax(), "paired_delta_net_qqq_excess"] = .1
        with self.assertRaisesRegex(ValueError, "B0 self-comparison"):
            paired_metrics(rows)

    def test_duplicate_pairs_rejected_and_worst_dates_recorded(self):
        rows = _rows()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            paired_metrics(pd.concat([rows, rows.head(1)]))
        bottom = date_quality_report(rows)
        self.assertEqual(bottom["E1"]["bottom_three"][0]["signal_date"], "2024-02-29")
        self.assertEqual(bottom["E1"]["n_positive_delta_dates"], 2)

    def test_frozen_protocol_has_dev_only_lock(self):
        path = Path(__file__).resolve().parents[1] / "configs/archive/mvp_v11_dev_return_protocol.json"
        config, sha = _read_protocol(path)
        self.assertEqual(config["periods"]["development"]["expected_dates"], 24)
        self.assertEqual(config["periods"]["temporal_2025"], "EMBARGOED")
        self.assertEqual(len(sha), 64)
        self.assertEqual(len(EXPECTED_MEMBERSHIP_SHA), 64)
        self.assertIn("2023_2024", APPROVAL_PHRASE)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "protocol.json"
            modified = dict(config)
            modified["periods"] = dict(config["periods"], temporal_2025="OPEN")
            p.write_text(json.dumps(modified), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "embargo"):
                _read_protocol(p)


if __name__ == "__main__":
    unittest.main()
