from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_value_scanner.config import ScanConfig, load_config
import ai_value_scanner.config as config_module
import ai_value_scanner.scanner as scanner_module
from ai_value_scanner.scanner import partition_filter_steps


class TestScanConfigValidation(unittest.TestCase):
    def test_scanner_facade_reexports_canonical_config_api(self) -> None:
        self.assertIs(scanner_module.ScanConfig, config_module.ScanConfig)
        self.assertIs(scanner_module.load_config, config_module.load_config)
        self.assertIs(
            scanner_module.resolve_channel_profile,
            config_module.resolve_channel_profile,
        )
        self.assertIs(
            scanner_module.default_channel_profiles,
            config_module.default_channel_profiles,
        )

    def test_all_runtime_configs_load(self) -> None:
        root = Path(__file__).resolve().parents[1] / "configs"
        paths = sorted(root.glob("config.*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                load_config(str(path))

    def test_unknown_top_level_key_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown ScanConfig keys"):
            ScanConfig.from_dict({"min_price": 1.0, "min_prcie": 2.0})

    def test_metadata_keys_remain_allowed(self) -> None:
        cfg = ScanConfig.from_dict({"_theme_meta": {"theme": "x"}})
        self.assertIsNone(cfg.strategy_style)

    def test_unsupported_schema_version_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported version"):
            ScanConfig.from_dict({"config_schema_version": 2})

    def test_invalid_quantiles_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "lower < upper"):
            ScanConfig.from_dict(
                {"score_winsor_lower_q": 0.95, "score_winsor_upper_q": 0.05}
            )

    def test_invalid_bool_type_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "alpaca_cache_enabled"):
            ScanConfig.from_dict({"alpaca_cache_enabled": "false"})

    def test_unknown_channel_profile_key_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            ScanConfig.from_dict(
                {
                    "channel_profiles": {
                        "core_ai": {
                            "min_ai_link_score": 0.3,
                            "min_ai_lnik_score": 0.4,
                        }
                    }
                }
            )

    def test_unknown_score_weight_dimension_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown score dimensions"):
            ScanConfig.from_dict(
                {
                    "channel_profiles": {
                        "core_ai": {
                            "score_weights": {
                                "liquidity": 0.5,
                                "liquidty": 0.5,
                            }
                        }
                    }
                }
            )

    def test_filter_partition_uses_explicit_style_not_step_heuristic(self) -> None:
        steps = [
            ("price_filter", lambda frame: frame.index == frame.index),
            ("min_price_to_sma200", lambda frame: frame.index == frame.index),
        ]
        hard_off, soft_off = partition_filter_steps(
            steps, "core_ai", strategy_style="risk_off"
        )
        hard_on, soft_on = partition_filter_steps(
            steps, "core_ai", strategy_style="risk_on"
        )
        self.assertNotIn("min_price_to_sma200", {name for name, _ in hard_off})
        self.assertIn("min_price_to_sma200", {name for name, _ in soft_off})
        self.assertIn("min_price_to_sma200", {name for name, _ in hard_on})
        self.assertNotIn("min_price_to_sma200", {name for name, _ in soft_on})

    def test_production_style_identity_must_match_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.risk_on.json"
            path.write_text(
                json.dumps({"strategy_style": "risk_off"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "strategy_style must be 'risk_on'"):
                load_config(str(path))


if __name__ == "__main__":
    unittest.main()
