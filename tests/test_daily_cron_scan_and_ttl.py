"""Unified daily cron pipeline & two-tier freshness TTL (no network).

Single-responsibility contract:
- ``scripts/refresh_sec_cache.py`` is 100% pure SEC prewarm and must never
  trigger a stock scan (no ``run_scan`` reference, no ``--skip-scan`` flag).
- ``scripts/run_daily_cron.py`` orchestrates Stage 1 SEC prewarm
  (``--max-age-hours 4.0``) + Stage 2 MVP scan (``--alpaca-ttl-sec 3600``).

Also covers the cron freshness contract:
- interactive (manual) Alpaca TTLs default to 21600s (6h);
- Stage 2 runs when the prewarm has incompletes but is not aborted;
- Stage 2 is skipped on abort/conflict/--skip-scan/limit;
- same-session/weekend reruns preserve an existing immutable snapshot;
- ``latest_<style>.json`` pointers carry only relative paths.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import refresh_sec_cache as rsc
import run_daily_cron as rdc
from run_daily_cron import run_daily_scan_after_prewarm


def _clean_summary(**overrides):
    summary = {
        "total": 1,
        "refreshed": 1,
        "skipped_valid": 0,
        "no_cik": [],
        "conflicted": [],
        "failed": 0,
        "incomplete": 0,
        "retried_ok": 0,
        "aborted": False,
        "processed_ciks": ["1"],
        "pending_ciks": {},
    }
    summary.update(overrides)
    return summary


class InteractiveTtlTests(unittest.TestCase):
    def test_scan_config_defaults_are_6h(self) -> None:
        from ai_value_scanner.scanner import ScanConfig

        cfg = ScanConfig()
        self.assertEqual(cfg.alpaca_cache_ttl_assets_sec, 21600)
        self.assertEqual(cfg.alpaca_cache_ttl_snapshots_sec, 21600)
        self.assertEqual(cfg.alpaca_cache_ttl_bars_sec, 21600)

    def test_production_configs_use_6h_alpaca_ttl(self) -> None:
        from ai_value_scanner.scanner import load_config

        for path in (
            "configs/config.risk_off.json",
            "configs/config.risk_on.json",
            "configs/config.strict_candidate.json",
        ):
            cfg = load_config(path)
            self.assertEqual(cfg.alpaca_cache_ttl_assets_sec, 21600, path)
            self.assertEqual(cfg.alpaca_cache_ttl_snapshots_sec, 21600, path)
            self.assertEqual(cfg.alpaca_cache_ttl_bars_sec, 21600, path)

    def test_pending_checked_scan_cooldown_is_6h(self) -> None:
        from ai_value_scanner import scanner

        self.assertEqual(scanner.PENDING_CHECKED_SCAN_COOLDOWN_SEC, 21600.0)


class Stage2ScanTests(unittest.TestCase):
    def _cfg(self, ttl: int = 21600):
        from ai_value_scanner.scanner import ScanConfig

        return ScanConfig(
            alpaca_cache_ttl_assets_sec=ttl,
            alpaca_cache_ttl_snapshots_sec=ttl,
            alpaca_cache_ttl_bars_sec=ttl,
        )

    def test_executes_when_incomplete_but_not_aborted(self) -> None:
        calls = []

        def fake_scan(scan_cfg, **kwargs):
            calls.append((scan_cfg, kwargs))
            return Path("outputs/decisions/2026-10-15/risk_off")

        res = run_daily_scan_after_prewarm(
            self._cfg(),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(incomplete=3, failed=3),
            scan_fn=fake_scan,
        )
        self.assertEqual(
            res,
            {
                "scan_executed": True,
                "scan_failed": False,
                "output_path": "outputs/decisions/2026-10-15/risk_off",
            },
        )
        self.assertEqual(len(calls), 1)
        scan_cfg, kwargs = calls[0]
        self.assertEqual(scan_cfg.alpaca_cache_ttl_assets_sec, 3600)
        self.assertEqual(scan_cfg.alpaca_cache_ttl_snapshots_sec, 3600)
        self.assertEqual(scan_cfg.alpaca_cache_ttl_bars_sec, 3600)
        self.assertEqual(
            kwargs,
            {
                "scan_config_path": "configs/config.risk_off.json",
                "allow_existing_decision_snapshot": True,
            },
        )

    def test_stage2_does_not_mutate_caller_config(self) -> None:
        cfg = self._cfg()

        def fake_scan(scan_cfg, **kwargs):
            return Path("outputs/decisions/2026-10-15/risk_off")

        run_daily_scan_after_prewarm(
            cfg,
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            scan_fn=fake_scan,
        )
        self.assertEqual(cfg.alpaca_cache_ttl_assets_sec, 21600)
        self.assertEqual(cfg.alpaca_cache_ttl_snapshots_sec, 21600)
        self.assertEqual(cfg.alpaca_cache_ttl_bars_sec, 21600)

    def test_ttl_override_keeps_tighter_values(self) -> None:
        seen = []

        def fake_scan(scan_cfg, **kwargs):
            seen.append(scan_cfg)
            return Path("out")

        run_daily_scan_after_prewarm(
            self._cfg(ttl=1800),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            scan_fn=fake_scan,
        )
        self.assertEqual(seen[0].alpaca_cache_ttl_assets_sec, 1800)
        self.assertEqual(seen[0].alpaca_cache_ttl_snapshots_sec, 1800)
        self.assertEqual(seen[0].alpaca_cache_ttl_bars_sec, 1800)

    def test_default_alpaca_ttl_sec_is_3600(self) -> None:
        param = inspect.signature(run_daily_scan_after_prewarm).parameters[
            "alpaca_ttl_sec"
        ]
        self.assertEqual(param.default, 3600)

    def test_custom_alpaca_ttl_passthrough(self) -> None:
        seen = []

        def fake_scan(scan_cfg, **kwargs):
            seen.append(scan_cfg)
            return Path("out")

        run_daily_scan_after_prewarm(
            self._cfg(ttl=21600),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            alpaca_ttl_sec=1800,
            scan_fn=fake_scan,
        )
        self.assertEqual(seen[0].alpaca_cache_ttl_bars_sec, 1800)
        run_daily_scan_after_prewarm(
            self._cfg(ttl=21600),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            alpaca_ttl_sec=7200,
            scan_fn=fake_scan,
        )
        self.assertEqual(seen[1].alpaca_cache_ttl_bars_sec, 7200)

    def test_skip_scan_flag_skips(self) -> None:
        def fail_if_called(scan_cfg, **kwargs):  # pragma: no cover
            raise AssertionError("scan_fn must not be called")

        res = run_daily_scan_after_prewarm(
            self._cfg(),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            skip_scan=True,
            scan_fn=fail_if_called,
        )
        self.assertEqual(
            res,
            {
                "scan_executed": False,
                "scan_failed": False,
                "reason": "skipped_by_flag_or_limit",
            },
        )

    def test_limit_skips(self) -> None:
        def fail_if_called(scan_cfg, **kwargs):  # pragma: no cover
            raise AssertionError("scan_fn must not be called")

        res = run_daily_scan_after_prewarm(
            self._cfg(),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            limit=5,
            scan_fn=fail_if_called,
        )
        self.assertFalse(res["scan_executed"])
        self.assertFalse(res["scan_failed"])
        self.assertEqual(res["reason"], "skipped_by_flag_or_limit")

    def test_aborted_prewarm_skips(self) -> None:
        def fail_if_called(scan_cfg, **kwargs):  # pragma: no cover
            raise AssertionError("scan_fn must not be called")

        res = run_daily_scan_after_prewarm(
            self._cfg(),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(aborted=True, failed=1),
            scan_fn=fail_if_called,
        )
        self.assertEqual(
            res,
            {
                "scan_executed": False,
                "scan_failed": False,
                "reason": "aborted_or_conflicted_prewarm",
            },
        )

    def test_conflicted_prewarm_skips(self) -> None:
        def fail_if_called(scan_cfg, **kwargs):  # pragma: no cover
            raise AssertionError("scan_fn must not be called")

        res = run_daily_scan_after_prewarm(
            self._cfg(),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(conflicted=["AAA"]),
            scan_fn=fail_if_called,
        )
        self.assertFalse(res["scan_executed"])
        self.assertFalse(res["scan_failed"])
        self.assertEqual(res["reason"], "aborted_or_conflicted_prewarm")

    def test_scan_exception_reports_failure(self) -> None:
        def broken_scan(scan_cfg, **kwargs):
            raise RuntimeError("alpaca down")

        res = run_daily_scan_after_prewarm(
            self._cfg(),
            config_path="configs/config.risk_off.json",
            summary=_clean_summary(),
            scan_fn=broken_scan,
        )
        self.assertEqual(
            res,
            {"scan_executed": False, "scan_failed": True, "error": "alpaca down"},
        )


class RefreshPurityTests(unittest.TestCase):
    """`refresh_sec_cache.py` is 100% pure SEC prewarm: no scan wiring."""

    def test_no_scan_references_in_module(self) -> None:
        self.assertFalse(hasattr(rsc, "run_scan"))
        self.assertFalse(hasattr(rsc, "run_daily_scan_after_prewarm"))

    def test_help_has_no_skip_scan_flag(self) -> None:
        buf = io.StringIO()
        with patch.object(sys, "argv", ["refresh_sec_cache.py", "--help"]):
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    rsc.main()
        self.assertEqual(ctx.exception.code, 0)
        self.assertNotIn("skip-scan", buf.getvalue())

    def test_skip_scan_flag_rejected(self) -> None:
        with patch.object(sys, "argv", ["refresh_sec_cache.py", "--skip-scan"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    rsc.main()
        self.assertEqual(ctx.exception.code, 2)

    def _patch_prewarm_stack(self, summary):
        captured = {}
        sec_instance = MagicMock()
        sec_instance.ticker_map_snapshot.return_value = {
            "frame": pd.DataFrame(),
            "conflicts": set(),
        }

        def fake_refresh(symbols, mapped, sec, cfg, **kwargs):
            captured.update(kwargs)
            return summary

        stack = ExitStack()
        stack.enter_context(
            patch.object(rsc, "collect_symbols", return_value=(["AAA"], ["f.csv"]))
        )
        sec_cls_mock = MagicMock(return_value=sec_instance)
        stack.enter_context(patch.object(rsc, "SecClient", sec_cls_mock))
        stack.enter_context(patch.object(rsc, "refresh_symbols", side_effect=fake_refresh))
        return stack, captured, sec_cls_mock

    def _run_main(self, argv, extra_env):
        env = {"SEC_USER_AGENT": "unittest-agent", "ALPACA_API_KEY": ""}
        env.update(extra_env)
        with patch.object(sys, "argv", ["refresh_sec_cache.py", *argv]):
            with patch.dict(os.environ, env, clear=False):
                rsc.main()

    def test_default_max_age_hours_is_4h(self) -> None:
        stack, captured, sec_cls_mock = self._patch_prewarm_stack(_clean_summary())
        with stack:
            self._run_main(["--limit", "1"], {})
        self.assertEqual(captured.get("max_age_sec"), 4.0 * 3600)
        _, sec_kwargs = sec_cls_mock.call_args
        self.assertEqual(sec_kwargs.get("submissions_ttl_sec"), int(4.0 * 3600))

    def test_main_never_scans_even_with_credentials(self) -> None:
        # No scan entry point exists in this module: a full prewarm with
        # Alpaca credentials configured still only refreshes SEC cache.
        stack, _, _ = self._patch_prewarm_stack(_clean_summary())
        with stack:
            self._run_main([], {"ALPACA_API_KEY": "test-key"})

    def test_main_exits_1_on_failed_summary(self) -> None:
        stack, _, _ = self._patch_prewarm_stack(_clean_summary(failed=2))
        with stack:
            with self.assertRaises(SystemExit) as ctx:
                self._run_main(["--limit", "1"], {})
        self.assertEqual(ctx.exception.code, 1)

    def test_run_sec_prewarm_defaults_and_limit(self) -> None:
        from ai_value_scanner.scanner import ScanConfig

        param = inspect.signature(rsc.run_sec_prewarm).parameters["max_age_hours"]
        self.assertEqual(param.default, 4.0)
        stack, captured, _ = self._patch_prewarm_stack(_clean_summary())
        cfg = ScanConfig()
        with stack:
            summary = rsc.run_sec_prewarm(
                cfg,
                repo=Path("."),
                user_agent="unittest-agent",
                limit=1,
            )
        self.assertEqual(summary["refreshed"], 1)
        self.assertEqual(captured.get("max_age_sec"), 4.0 * 3600)

    def test_run_sec_prewarm_exits_1_without_symbols(self) -> None:
        from ai_value_scanner.scanner import ScanConfig

        with patch.object(rsc, "collect_symbols", return_value=([], [])):
            with self.assertRaises(SystemExit) as ctx:
                rsc.run_sec_prewarm(
                    ScanConfig(), repo=Path("."), user_agent="unittest-agent"
                )
        self.assertEqual(ctx.exception.code, 1)


class DailyCronMainTests(unittest.TestCase):
    """`run_daily_cron.py` orchestrates Stage 1 + Stage 2."""

    def _run_main(self, argv, extra_env, prewarm_summary, stage2_result):
        env = {"SEC_USER_AGENT": "unittest-agent", "ALPACA_API_KEY": ""}
        env.update(extra_env)
        with patch.object(sys, "argv", ["run_daily_cron.py", *argv]):
            with patch.dict(os.environ, env, clear=False):
                with patch.object(
                    rdc, "run_sec_prewarm", return_value=prewarm_summary
                ) as prewarm:
                    with patch.object(
                        rdc,
                        "run_daily_scan_after_prewarm",
                        return_value=stage2_result,
                    ) as stage2:
                        rdc.main()
        return prewarm, stage2

    def test_defaults_wire_stage1_4h_and_stage2_3600(self) -> None:
        prewarm, stage2 = self._run_main(
            [],
            {"ALPACA_API_KEY": "test-key"},
            _clean_summary(),
            {"scan_executed": True, "scan_failed": False, "output_path": "out.csv"},
        )
        self.assertEqual(prewarm.call_count, 1)
        _, pre_kwargs = prewarm.call_args
        self.assertEqual(pre_kwargs.get("max_age_hours"), 4.0)
        self.assertEqual(pre_kwargs.get("limit"), 0)
        self.assertEqual(stage2.call_count, 1)
        _, scan_kwargs = stage2.call_args
        self.assertEqual(scan_kwargs.get("config_path"), "configs/config.risk_off.json")
        self.assertEqual(scan_kwargs.get("limit"), 0)
        self.assertEqual(scan_kwargs.get("skip_scan"), False)
        self.assertEqual(scan_kwargs.get("alpaca_ttl_sec"), 3600)

    def test_custom_freshness_windows_pass_through(self) -> None:
        prewarm, stage2 = self._run_main(
            ["--max-age-hours", "2.0", "--alpaca-ttl-sec", "1800"],
            {"ALPACA_API_KEY": "test-key"},
            _clean_summary(),
            {"scan_executed": True, "scan_failed": False, "output_path": "out.csv"},
        )
        _, pre_kwargs = prewarm.call_args
        self.assertEqual(pre_kwargs.get("max_age_hours"), 2.0)
        _, scan_kwargs = stage2.call_args
        self.assertEqual(scan_kwargs.get("alpaca_ttl_sec"), 1800)

    def test_main_skips_stage2_without_credentials(self) -> None:
        prewarm, stage2 = self._run_main(
            [],
            {"ALPACA_API_KEY": ""},
            _clean_summary(),
            {"scan_executed": True, "scan_failed": False, "output_path": "out.csv"},
        )
        self.assertEqual(prewarm.call_count, 1)
        self.assertEqual(stage2.call_count, 0)

    def test_main_skips_stage2_with_skip_scan_flag(self) -> None:
        prewarm, stage2 = self._run_main(
            ["--skip-scan"],
            {"ALPACA_API_KEY": "test-key"},
            _clean_summary(),
            {"scan_executed": True, "scan_failed": False, "output_path": "out.csv"},
        )
        self.assertEqual(prewarm.call_count, 1)
        self.assertEqual(stage2.call_count, 0)

    def test_main_skips_stage2_with_limit(self) -> None:
        prewarm, stage2 = self._run_main(
            ["--limit", "3"],
            {"ALPACA_API_KEY": "test-key"},
            _clean_summary(),
            {"scan_executed": True, "scan_failed": False, "output_path": "out.csv"},
        )
        self.assertEqual(prewarm.call_count, 1)
        self.assertEqual(stage2.call_count, 0)

    def test_main_exits_1_when_stage2_fails(self) -> None:
        env = {"SEC_USER_AGENT": "unittest-agent", "ALPACA_API_KEY": "test-key"}
        with patch.object(sys, "argv", ["run_daily_cron.py"]):
            with patch.dict(os.environ, env, clear=False):
                with patch.object(
                    rdc, "run_sec_prewarm", return_value=_clean_summary()
                ):
                    with patch.object(
                        rdc,
                        "run_daily_scan_after_prewarm",
                        return_value={
                            "scan_executed": False,
                            "scan_failed": True,
                            "error": "boom",
                        },
                    ):
                        with self.assertRaises(SystemExit) as ctx:
                            rdc.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_main_exits_1_on_failed_prewarm(self) -> None:
        env = {"SEC_USER_AGENT": "unittest-agent", "ALPACA_API_KEY": ""}
        with patch.object(sys, "argv", ["run_daily_cron.py", "--limit", "1"]):
            with patch.dict(os.environ, env, clear=False):
                with patch.object(
                    rdc, "run_sec_prewarm", return_value=_clean_summary(failed=1)
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        rdc.main()
        self.assertEqual(ctx.exception.code, 1)


class SnapshotPreservationTests(unittest.TestCase):
    def test_run_scan_signature_has_allow_existing_flag(self) -> None:
        from ai_value_scanner import scanner

        param = inspect.signature(scanner.run_scan).parameters[
            "allow_existing_decision_snapshot"
        ]
        self.assertEqual(param.default, False)

    def test_existing_snapshot_detected_and_write_refuses_overwrite(self) -> None:
        from ai_value_scanner.reporting.snapshot import (
            decision_snapshot_paths,
            write_decision_snapshot,
        )

        kwargs = dict(
            strategy_style="risk_off",
            decisions=[],
            daily_attention=[],
            weekly_attention=[],
            generated_at_utc="2026-10-15T12:00:00+00:00",
            decision_date="2026-10-15",
            config_fingerprint="abc",
            code_sha=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "decisions"
            first = write_decision_snapshot(output_root=root, **kwargs)
            self.assertTrue(first.root.exists())
            # The immutable contract raises instead of overwriting, so the
            # allow_existing branch in run_scan must skip this call.
            with self.assertRaises(FileExistsError):
                write_decision_snapshot(output_root=root, **kwargs)
            existing = decision_snapshot_paths(
                root, "2026-10-15", strategy_style="risk_off"
            )
            self.assertTrue(existing.root.exists())
            self.assertEqual(existing.root, first.root)


class LatestPointerTests(unittest.TestCase):
    def _assert_no_absolute_paths(self, payload: dict, raw: str) -> None:
        self.assertNotIn("/home/", raw)
        self.assertNotIn("/tmp/", raw)
        for value in payload.values():
            if isinstance(value, str) and "/" in value:
                self.assertFalse(os.path.isabs(value), value)

    def test_pointer_under_absolute_tmp_root_has_relative_paths(self) -> None:
        from ai_value_scanner.scanner import write_latest_decision_pointer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "decisions"
            (root / "2026-10-15" / "risk_off").mkdir(parents=True)
            pointer_path = write_latest_decision_pointer(
                root,
                decision_date="2026-10-15",
                strategy_style="risk_off",
                policy_version="v2",
                layout_version="v2",
            )
            self.assertEqual(pointer_path, root / "latest_risk_off.json")
            payload = json.loads(pointer_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "decision_date": "2026-10-15",
                    "strategy_style": "risk_off",
                    "decision_policy_version": "v2",
                    "report_layout_version": "v2",
                    "snapshot_dir": "2026-10-15/risk_off",
                    "action_list_md": "2026-10-15/risk_off/action_list.md",
                    "weekly_review_md": "2026-10-15/risk_off/weekly_review.md",
                    "run_manifest_json": "2026-10-15/risk_off/run_manifest.json",
                },
            )
            self._assert_no_absolute_paths(
                payload, pointer_path.read_text(encoding="utf-8")
            )

    def test_pointer_under_relative_root(self) -> None:
        from ai_value_scanner.scanner import write_latest_decision_pointer

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path("decisions/2026-10-15/risk_on").mkdir(parents=True)
                pointer_path = write_latest_decision_pointer(
                    "decisions",
                    decision_date="2026-10-15",
                    strategy_style="risk_on",
                )
                self.assertEqual(pointer_path, Path("decisions/latest_risk_on.json"))
                payload = json.loads(pointer_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["snapshot_dir"], "2026-10-15/risk_on")
                self._assert_no_absolute_paths(
                    payload, pointer_path.read_text(encoding="utf-8")
                )
            finally:
                os.chdir(old_cwd)

    def test_pointer_refresh_is_idempotent(self) -> None:
        from ai_value_scanner.scanner import write_latest_decision_pointer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "decisions"
            (root / "2026-10-15" / "risk_off").mkdir(parents=True)
            first = write_latest_decision_pointer(
                root, decision_date="2026-10-15", strategy_style="risk_off"
            )
            second = write_latest_decision_pointer(
                root, decision_date="2026-10-15", strategy_style="risk_off"
            )
            self.assertEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
