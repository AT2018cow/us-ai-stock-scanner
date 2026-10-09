from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import low_value_gate_ablation as broad  # noqa: E402
import low_value_single_gate_ablation as single  # noqa: E402


class TestSameStateSingleRangeGate(unittest.TestCase):
    def test_unique_cross_section_dedupes_channel_rows(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "signal_date": "2025-01-31",
                    "symbol": "A",
                    "channel": "core_ai",
                    "soft_pass_count": 3,
                    "soft_total": 5,
                    "feature": 1.25,
                    "fwd_ret_120": 0.2,
                },
                {
                    "signal_date": "2025-01-31",
                    "symbol": "A",
                    "channel": "ai_enabler",
                    "soft_pass_count": 4,
                    "soft_total": 6,
                    "feature": 1.25,
                    "fwd_ret_120": 0.2,
                },
            ]
        )
        out = single.unique_cross_section(frame)
        self.assertEqual(len(out), 1)
        self.assertNotIn("channel", out.columns)
        self.assertNotIn("soft_pass_count", out.columns)
        self.assertAlmostEqual(float(out.iloc[0]["feature"]), 1.25)

    def test_unique_cross_section_rejects_raw_field_disagreement(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "symbol": "A",
                    "channel": "core_ai",
                    "soft_pass_count": 3,
                    "soft_total": 5,
                    "feature": 1.25,
                },
                {
                    "symbol": "A",
                    "channel": "ai_enabler",
                    "soft_pass_count": 4,
                    "soft_total": 6,
                    "feature": 1.30,
                },
            ]
        )
        with self.assertRaises(ValueError):
            single.unique_cross_section(frame)

    def test_dataset_validator_locks_hash_and_exact_skip_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weight_dataset_risk_off.csv"
            path.write_text("symbol\nA\n")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            meta = {
                "style": "risk_off",
                "list_types": ["low_value"],
                "research_expanded_survivor_dataset": True,
                "allow_latest_watchlist_fallback": False,
                "research_skipped_low_value_hard_steps": sorted(
                    single.EXPECTED_EXPANDED_SKIPS
                ),
            }
            path.with_suffix(".meta.json").write_text(
                json.dumps(meta)
            )

            original = single.EXPECTED_DATASET_SHA256
            try:
                single.EXPECTED_DATASET_SHA256 = digest
                out = single.validate_canonical_dataset(path)
                self.assertEqual(out["dataset_sha256"], digest)

                meta["research_skipped_low_value_hard_steps"] = [
                    "max_range_position_52w"
                ]
                path.with_suffix(".meta.json").write_text(
                    json.dumps(meta)
                )
                with self.assertRaises(ValueError):
                    single.validate_canonical_dataset(path)
            finally:
                single.EXPECTED_DATASET_SHA256 = original

    def test_config_validator_locks_git_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.risk_off.json"
            path.write_text('{"strategy_style":"risk_off"}\n')
            digest = single.git_blob_sha1(path)
            original = single.EXPECTED_CONFIG_GIT_BLOB_SHA1
            try:
                single.EXPECTED_CONFIG_GIT_BLOB_SHA1 = digest
                self.assertEqual(
                    single.validate_canonical_config(path),
                    digest,
                )
                path.write_text('{"strategy_style":"risk_on"}\n')
                with self.assertRaises(ValueError):
                    single.validate_canonical_config(path)
            finally:
                single.EXPECTED_CONFIG_GIT_BLOB_SHA1 = original

    def test_ordered_same_state_parity_detects_reordering(self) -> None:
        row = single._parity_row(
            signal_date="2025-01-31",
            scope="core_ai",
            canonical=["A", "B"],
            research=["B", "A"],
        )
        self.assertFalse(bool(row["exact_match"]))
        self.assertFalse(bool(row["order_match"]))
        self.assertAlmostEqual(float(row["jaccard"]), 1.0)

    def test_single_gate_keeps_other_position_gates_hard(self) -> None:
        cfg = SimpleNamespace(
            strategy_style="risk_off",
            channel_profiles={"core_ai": {}},
        )
        steps = [
            ("min_price", lambda frame: frame["x"] > 0),
            (
                "max_range_position_52w",
                lambda frame: frame["x"] <= 0.8,
            ),
            (
                "min_drawdown_from_52w_high",
                lambda frame: frame["d"] >= 0.1,
            ),
            (
                "max_price_to_sma200",
                lambda frame: frame["p"] <= 1.1,
            ),
            ("min_quality", lambda frame: frame["q"] > 0),
        ]
        weights = {"x": 1.0}
        original = broad.build_steps_and_weights
        try:
            broad.build_steps_and_weights = (
                lambda *args, **kwargs: (steps, weights)
            )
            hard, soft, _weights, active = broad.arm_filter_steps(
                cfg,
                "core_ai",
                {},
                "hard_to_soft",
                {single.TARGET_STEP},
            )
        finally:
            broad.build_steps_and_weights = original

        hard_names = [name for name, _ in hard]
        soft_names = [name for name, _ in soft]
        self.assertNotIn("max_range_position_52w", hard_names)
        self.assertIn("max_range_position_52w", soft_names)
        self.assertIn("min_drawdown_from_52w_high", hard_names)
        self.assertIn("max_price_to_sma200", hard_names)
        self.assertEqual(active, ["max_range_position_52w"])

    def test_block_bootstrap_is_deterministic(self) -> None:
        values = np.asarray(
            [0.01, 0.03, 0.02, 0.04, 0.01, 0.05, 0.02, 0.03]
        )
        first = single.circular_block_bootstrap_mean_ci(
            values,
            block_len=3,
            seed=42,
            n_boot=500,
            confidence=0.90,
        )
        second = single.circular_block_bootstrap_mean_ci(
            values,
            block_len=3,
            seed=42,
            n_boot=500,
            confidence=0.90,
        )
        self.assertEqual(first, second)
        self.assertGreater(first[0], 0.0)

    def test_retrospective_gate_requires_narrow_overlap_and_positive_ci(self) -> None:
        parity = pd.DataFrame(
            {"exact_match": [True, True, True]}
        )
        rows = [
            {
                "scope": "all",
                "scope_value": "ALL",
                "horizon_days": 120,
                "n_dates": 34,
                "avg_delta_return": 0.03,
                "positive_delta_ratio": 0.65,
                "top_abs_date_share": 0.20,
                "median_selection_jaccard": 0.75,
                "bootstrap_ci90_lower": 0.005,
            },
            {
                "scope": "regime",
                "scope_value": "down",
                "horizon_days": 120,
                "n_dates": 8,
                "avg_delta_return": 0.01,
                "positive_delta_ratio": 0.60,
                "top_abs_date_share": 0.20,
                "median_selection_jaccard": 0.72,
                "bootstrap_ci90_lower": -0.01,
            },
        ]
        for year in ("2023", "2024", "2025"):
            rows.append(
                {
                    "scope": "year",
                    "scope_value": year,
                    "horizon_days": 120,
                    "n_dates": 10,
                    "avg_delta_return": 0.02,
                    "positive_delta_ratio": 0.60,
                    "top_abs_date_share": 0.20,
                    "median_selection_jaccard": 0.70,
                    "bootstrap_ci90_lower": -0.01,
                }
            )
        symbols = pd.DataFrame(
            [
                {
                    "horizon_days": 120,
                    "side": "added",
                    "positive_excess_share": 0.20,
                }
            ]
        )
        passed, failures = single.single_gate_retrospective_gate(
            parity,
            pd.DataFrame(rows),
            symbols,
        )
        self.assertTrue(passed)
        self.assertEqual(failures, [])

        rows[0]["median_selection_jaccard"] = 0.65
        passed, failures = single.single_gate_retrospective_gate(
            parity,
            pd.DataFrame(rows),
            symbols,
        )
        self.assertFalse(passed)
        self.assertIn(
            "single_gate_selection_overlap_too_low",
            failures,
        )

        rows[0]["median_selection_jaccard"] = 0.75
        rows[0]["bootstrap_ci90_lower"] = -0.001
        passed, failures = single.single_gate_retrospective_gate(
            parity,
            pd.DataFrame(rows),
            symbols,
        )
        self.assertFalse(passed)
        self.assertIn(
            "all_120d_block_bootstrap_lower_not_positive",
            failures,
        )


if __name__ == "__main__":
    unittest.main()
