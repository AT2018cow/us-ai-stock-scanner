"""Short Research v1 scan-entry integration tests (mocked SIP/SEC, no network).

These tests exercise the real ``run_scan_with_status`` path with a frozen
complete cross-section standing in for the Alpaca/SEC adapter.  The mock only
replaces external data acquisition and deterministic ranking internals; the
short-research adapter, snapshot writer, report renderer, manifest, validator
and latest-pointer code are the production implementations.
"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timezone
from functools import lru_cache
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ai_value_scanner import scanner as sc
from ai_value_scanner.decision.model import stock_decisions_from_jsonl
from ai_value_scanner.scanner import ScanConfig, run_scan_with_status
from ai_value_scanner.research.short_research_v1 import build_short_cross_section
from ai_value_scanner.reporting import short_research as archive, snapshot

DATE = "2025-01-31"
FIXED_NOW = datetime(2025, 2, 1, 2, 0, 0, tzinfo=timezone.utc)
DATASET = (
    Path("outputs/review_followup_20261106/datasets")
    / "sip_2021_2026_v1"
    / "dataset.csv"
)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW if tz is not None else FIXED_NOW.replace(tzinfo=None)


class _FakeAlpaca:
    feed = "sip"
    eod_session = date(2025, 1, 31)

    def get_daily_bars(self, symbols, start, chunk):
        return {
            symbol: [
                {
                    "t": DATE,
                    "o": 100.0,
                    "h": 100.0,
                    "l": 100.0,
                    "c": 100.0,
                    "v": 1.0,
                    "symbol": symbol,
                }
            ]
            for symbol in symbols
        }

    def get_corporate_action_splits(self, symbols, start, end):
        return {}

    def get_assets(self, status="active"):
        return []

    def get_snapshots(self, symbols, chunk):
        return {}


class _FakeSec:
    def ticker_map_snapshot(self):
        return {}


class _FakeMonitor:
    def to_dict(self):
        return {
            "services": {},
            "data_provenance": {},
            "had_rate_limit_or_network_issue": False,
            "stale_market_data_fallback_used": False,
        }


@lru_cache(maxsize=1)
def _load_frame() -> tuple[pd.DataFrame, dict[str, dict]]:
    frame = pd.read_csv(
        DATASET,
        dtype={"symbol": str, "cik": str, "sic": str},
        low_memory=False,
    )
    frame = frame.loc[frame["signal_date"] == DATE].copy().reset_index(drop=True)
    for column in ("ai_disclosure_group_hits", "ai_disclosure_keyword_hits"):
        frame[column] = 0.0
    features = {
        row["symbol"]: {
            "return_20d": row["return_20d"],
            "return_60d": row["return_60d"],
            "price_to_sma50": row["price_to_sma50"],
            "price_to_sma200": row["price_to_sma200"],
            "days_below_sma200": row["days_below_sma200"],
            "drawdown_from_52w_high": row["drawdown_from_52w_high"],
            "range_position_52w": row["range_position_52w"],
            "volatility_60d": row["volatility_60d"],
            "avg_dollar_volume_20d": row["avg_dollar_volume_20d"],
        }
        for _, row in frame.iterrows()
    }
    # The mocked price stage recreates these columns; drop them before merge.
    frame = frame.drop(
        columns=[
            "return_20d",
            "return_60d",
            "price_to_sma50",
            "price_to_sma200",
            "days_below_sma200",
            "drawdown_from_52w_high",
            "range_position_52w",
            "volatility_60d",
            "avg_dollar_volume_20d",
            "market_asof",
            "qqq_trailing_return_60d",
            "relative_strength_60d_qqq",
            "regime",
        ],
        errors="ignore",
    )
    return frame, features


def _fake_price_dimension(bars, features):
    symbol = bars[0].get("symbol") if bars else None
    return features.get(symbol, {})


def _fake_score_rank(frame, *args, **kwargs):
    out = frame.copy()
    out["composite_score"] = 0.5
    out["triage_label"] = "keep"
    out["research_priority"] = "research_now"
    out["research_score"] = 1.0
    out["research_tags"] = ""
    out["research_risks"] = ""
    out["research_summary"] = ""
    return out


def _fake_research_assessment(frame, *args, **kwargs):
    out = frame.copy()
    for column, value in (
        ("research_priority", "research_now"),
        ("research_score", 1.0),
        ("research_tags", ""),
        ("research_risks", ""),
        ("research_summary", ""),
    ):
        if column not in out.columns:
            out[column] = value
    return out


def _fake_filters(frame, steps, channel, config):
    return frame.copy(), [
        {
            "step": "base_hard",
            "before": len(frame),
            "remaining": len(frame),
            "removed": 0,
            "layer": "base_hard",
            "pass_rate": 1.0,
        }
    ]


def _fake_diag(diagnostics):
    count = diagnostics[0]["before"]
    return {
        "base_hard": {
            "before": count,
            "remaining": count,
            "removed": 0,
            "pass_rate": 1.0,
        }
    }


def _fake_first_fail(frame, steps):
    return pd.DataFrame(columns=["reason", "count", "pct"])


def _fake_concentration(frame):
    return {"top_reason": "none", "top_count": 0, "top_pct": 0.0}


def _fake_triage(frame, rules):
    out = frame.copy()
    if "triage_label" not in out.columns:
        out["triage_label"] = "keep"
    return out


def _run_scan(
    root: Path,
    *,
    enable_short: bool,
    max_symbols: int | None = None,
    short_failure: bool = False,
    snapshot_failure: bool = False,
    eod_available: bool = True,
    real_legacy_filters: bool = False,
    allow_existing: bool = False,
):
    frame, features = _load_frame()
    config = ScanConfig(
        output_dir=str(root / "outputs"),
        strategy_style="production",
        decision_policy_version="v2",
        report_layout_version="v2",
        enable_short_research=enable_short,
        official_market_mode="sip_eod",
        use_adjusted_quality_metrics=True,
        min_price=5.0,
        min_dollar_volume=2_000_000.0,
        watchlist_csv_path="unused.csv",
        alpaca_cache_enabled=False,
        max_symbols=max_symbols,
        benchmark_trend_filter_symbol="QQQ",
    )
    with ExitStack() as stack:
        def patch_scanner(name, value):
            stack.enter_context(patch.object(sc, name, value))

        patch_scanner(
            "load_runtime_settings",
            lambda cfg: (_FakeAlpaca(), _FakeSec(), _FakeMonitor()),
        )
        patch_scanner(
            "load_watchlist_scores",
            lambda cfg: pd.DataFrame({"symbol": frame["symbol"].tolist()}),
        )
        patch_scanner(
            "collect_candidates_with_universe_audit",
            lambda *args, **kwargs: (
                frame.copy(),
                [],
                {
                    "tradable_mapped_symbols": len(frame),
                    "post_sample_symbols": len(frame),
                },
            ),
        )
        patch_scanner(
            "collect_fundamentals",
            lambda frame, sec, cfg: pd.DataFrame(
                {"symbol": frame["symbol"].tolist()}
            ),
        )
        patch_scanner("price_dimension_from_bars", lambda price, bars: _fake_price_dimension(bars, features))
        patch_scanner("bars_market_asof", lambda bars: DATE)
        patch_scanner("bars_return_from_lookback", lambda bars, days: 0.05)
        patch_scanner("bars_close_from_lookback", lambda bars, days: 90.0)
        patch_scanner("bars_sma_from_lookback", lambda bars, days: 100.0)
        patch_scanner("apply_split_adjustment", lambda bars, events: bars)
        patch_scanner(
            "compute_cross_section_derived_features", lambda frame, **kwargs: {}
        )
        patch_scanner(
            "compute_peer_relative_valuation", lambda frame, **kwargs: {}
        )
        if not real_legacy_filters:
            patch_scanner("build_filter_steps", lambda *args, **kwargs: [])
            patch_scanner("apply_scored_or_hard_filters", _fake_filters)
        patch_scanner("summarize_first_fail_reasons", _fake_first_fail)
        patch_scanner("summarize_diagnostics_by_layer", _fake_diag)
        patch_scanner("first_fail_concentration", _fake_concentration)
        patch_scanner("score_and_rank", _fake_score_rank)
        patch_scanner("apply_research_assessment", _fake_research_assessment)
        patch_scanner("apply_low_value_research_gate", lambda frame, cfg: frame)
        patch_scanner("apply_group_caps", lambda frame, *args, **kwargs: frame)
        patch_scanner("apply_triage_labels", _fake_triage)
        patch_scanner("datetime", _FixedDateTime)
        if short_failure:
            patch_scanner(
                "build_short_cross_section",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("simulated short module failure")
                ),
            )
        if snapshot_failure:
            patch_scanner(
                "write_decision_snapshot",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    OSError("disk full")
                ),
            )
        stack.enter_context(
            patch(
                "ai_value_scanner.market_data.official_eod_window",
                lambda now: (
                    (date(2025, 1, 31), "2025-01-31T21:00:00Z")
                    if eod_available
                    else (None, None)
                ),
            )
        )
        with redirect_stdout(StringIO()):
            return run_scan_with_status(
                config,
                decision_output_root=str(root / "decisions"),
                scan_config_path="mock.json",
                freshness_now_utc=FIXED_NOW,
                allow_existing_decision_snapshot=allow_existing,
            )


def _decision_core(path: Path):
    decisions = stock_decisions_from_jsonl(path.read_text(encoding="utf-8"))
    return [
        (
            decision.symbol,
            decision.quality.grade.value,
            decision.quality.score,
            decision.quality.confidence,
            decision.entry.state.value,
            decision.entry.score,
            decision.action_state.value,
            decision.priority,
            tuple(item.code for item in decision.rationale),
            tuple(decision.source_lists),
            decision.review_trigger,
        )
        for decision in decisions
    ]


def _long_body(report: str) -> str:
    start = report.index("## Priority Review")
    end = report.find('<a id="short-research"></a>')
    body = report[start:] if end < 0 else report[start:end]
    return body.rstrip()


def _legacy_files(root: Path) -> dict[str, Path]:
    outputs = root / "outputs"
    return {
        "ranked": next(outputs.glob("*_full_ranked.csv")),
        "industry_trend": next(outputs.glob("*_industry_trend.csv")),
        "momentum": next(outputs.glob("*_momentum.csv")),
        "research_pool": next(outputs.glob("*_research_pool.csv")),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root: Path) -> dict:
    return json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))


def _git_sha() -> str | None:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def build_scan_entry_evidence() -> dict:
    """Build compact V1-08/V1-09 evidence from the mocked scan entry."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        off = _run_scan(base / "off", enable_short=False, real_legacy_filters=True)
        on = _run_scan(base / "on", enable_short=True, real_legacy_filters=True)
        truncation = _run_scan(
            base / "truncation", enable_short=True, max_symbols=100
        )
        short_failure = _run_scan(
            base / "short_failure", enable_short=True, short_failure=True
        )
        core_failure = _run_scan(
            base / "core_failure",
            enable_short=True,
            snapshot_failure=True,
            eod_available=False,
        )

        off_root = Path(off.decision_snapshot_root)
        on_root = Path(on.decision_snapshot_root)
        off_manifest = _manifest(off_root)
        on_manifest = _manifest(on_root)
        off_legacy = _legacy_files(base / "off")
        on_legacy = _legacy_files(base / "on")
        long_decisions_identical = (
            _decision_core(off_root / "decisions.jsonl")
            == _decision_core(on_root / "decisions.jsonl")
        )
        long_legacy_csv_identical = all(
            off_legacy[name].read_bytes() == on_legacy[name].read_bytes()
            for name in off_legacy
        )
        on_report = (on_root / "action_list.md").read_text(encoding="utf-8")
        trunc_root = Path(truncation.decision_snapshot_root)
        trunc_manifest = _manifest(trunc_root)
        short_failure_root = Path(short_failure.decision_snapshot_root)
        short_failure_manifest = _manifest(short_failure_root)
        core_failure_pointer = (
            base / "core_failure" / "decisions" / "latest_production.json"
        )
        legacy_rows = {}
        for name, path in on_legacy.items():
            with path.open(encoding="utf-8") as handle:
                legacy_rows[name] = sum(1 for _ in csv.DictReader(handle))
        return {
            "evidence_type": "mocked_scan_entry_frozen_input",
            "code_sha": _git_sha(),
            "dataset": "sip_2021_2026_v1",
            "signal_date": DATE,
            "market_data_feed": "sip",
            "qqq_below_sma200": "<strong>Topic Screens</strong> · Paused" in on_report,
            "legacy_csv_rows": legacy_rows,
            "off": {
                "decision_output_status": off.decision_output_status,
                "latest_pointer_status": off.latest_pointer_status,
                "short_status": off_manifest["short_research"]["status"],
                "short_files_present": (
                    (off_root / "short_research.json").exists()
                    or (off_root / "short_candidates.csv").exists()
                ),
                "daily_symbols": off_manifest["daily_symbols"],
                "weekly_symbols": off_manifest["weekly_symbols"],
                "legacy_csv_sha256": {
                    name: _sha256(path) for name, path in off_legacy.items()
                },
            },
            "on": {
                "decision_output_status": on.decision_output_status,
                "latest_pointer_status": on.latest_pointer_status,
                "short_status": on_manifest["short_research"]["status"],
                "short_selected_count": on_manifest["short_research"][
                    "selected_count"
                ],
                "short_files_present": (
                    (on_root / "short_research.json").is_file()
                    and (on_root / "short_candidates.csv").is_file()
                ),
                "short_report_section": "<strong>Downside Research</strong>" in on_report,
                "daily_symbols": on_manifest["daily_symbols"],
                "weekly_symbols": on_manifest["weekly_symbols"],
                "legacy_csv_sha256": {
                    name: _sha256(path) for name, path in on_legacy.items()
                },
            },
            "long_decisions_identical": long_decisions_identical,
            "long_daily_symbols_identical": (
                off_manifest["daily_symbols"] == on_manifest["daily_symbols"]
            ),
            "long_weekly_symbols_identical": (
                off_manifest["weekly_symbols"] == on_manifest["weekly_symbols"]
            ),
            "long_legacy_csv_identical": long_legacy_csv_identical,
            "truncation": {
                "decision_output_status": truncation.decision_output_status,
                "latest_pointer_status": truncation.latest_pointer_status,
                "short_status": trunc_manifest["short_research"]["status"],
                "reason_codes": trunc_manifest["short_research"]["reason_codes"],
                "csv_lines": (
                    (trunc_root / "short_candidates.csv")
                    .read_text(encoding="utf-8")
                    .count("\n")
                ),
                "long_snapshot_published": (
                    trunc_root / "decisions.jsonl"
                ).is_file(),
            },
            "short_failure": {
                "decision_output_status": short_failure.decision_output_status,
                "latest_pointer_status": short_failure.latest_pointer_status,
                "short_status": short_failure_manifest["short_research"][
                    "status"
                ],
                "reason_codes": short_failure_manifest["short_research"][
                    "reason_codes"
                ],
                "long_snapshot_published": (
                    short_failure_root / "decisions.jsonl"
                ).is_file(),
            },
            "core_failure": {
                "decision_output_status": core_failure.decision_output_status,
                "latest_pointer_status": core_failure.latest_pointer_status,
                "latest_pointer_exists": core_failure_pointer.exists(),
            },
            "test_command": (
                ".venv/bin/python -m unittest discover -s tests "
                "-p test_short_research_v1_scan.py"
            ),
        }


class ScanEntryShortResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DATASET.is_file():
            raise unittest.SkipTest("frozen scan-entry dataset is not available")

    def test_off_on_same_frozen_input_preserves_long_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            off = _run_scan(root / "off", enable_short=False)
            on = _run_scan(root / "on", enable_short=True)

            self.assertEqual(off.decision_output_status, "written")
            self.assertEqual(on.decision_output_status, "written")
            off_root = Path(off.decision_snapshot_root)
            on_root = Path(on.decision_snapshot_root)

            self.assertEqual(
                _decision_core(off_root / "decisions.jsonl"),
                _decision_core(on_root / "decisions.jsonl"),
            )
            off_manifest = json.loads(
                (off_root / "run_manifest.json").read_text(encoding="utf-8")
            )
            on_manifest = json.loads(
                (on_root / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                off_manifest["daily_symbols"], on_manifest["daily_symbols"]
            )
            self.assertEqual(
                off_manifest["weekly_symbols"], on_manifest["weekly_symbols"]
            )
            self.assertEqual(
                _long_body((off_root / "action_list.md").read_text(encoding="utf-8")),
                _long_body((on_root / "action_list.md").read_text(encoding="utf-8")),
            )
            self.assertEqual(
                _long_body((off_root / "weekly_review.md").read_text(encoding="utf-8")),
                _long_body((on_root / "weekly_review.md").read_text(encoding="utf-8")),
            )

            off_legacy = _legacy_files(root / "off")
            on_legacy = _legacy_files(root / "on")
            for name in off_legacy:
                self.assertEqual(
                    off_legacy[name].read_bytes(),
                    on_legacy[name].read_bytes(),
                    name,
                )

            self.assertFalse((off_root / "short_research.json").exists())
            self.assertFalse((off_root / "short_candidates.csv").exists())
            self.assertEqual(
                off_manifest["short_research"]["status"], "disabled"
            )
            self.assertTrue((on_root / "short_research.json").is_file())
            self.assertTrue((on_root / "short_candidates.csv").is_file())
            self.assertEqual(on_manifest["short_research"]["status"], "ready")
            self.assertGreater(on_manifest["short_research"]["selected_count"], 0)
            on_report = (on_root / "action_list.md").read_text(encoding="utf-8")
            self.assertIn("<strong>Downside Research</strong> · 1 candidate", on_report)
            self.assertIn("<strong>Topic Screens</strong> · Paused", on_report)
            self.assertIn("short_candidates.csv", on_report)

            off_pointer = json.loads(
                (root / "off" / "decisions" / "latest_production.json").read_text(
                    encoding="utf-8"
                )
            )
            on_pointer = json.loads(
                (root / "on" / "decisions" / "latest_production.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(off_pointer, on_pointer)

    def test_report_revision_preserves_frozen_decisions_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(snapshot, "REPORT_RENDERER_REVISION", "mvp_report_renderer_2026-11-22b"):
                old = _run_scan(root / "old", enable_short=True, real_legacy_filters=True)
            new = _run_scan(root / "new", enable_short=True, real_legacy_filters=True)
            old_root = Path(old.decision_snapshot_root)
            new_root = Path(new.decision_snapshot_root)
            self.assertEqual(
                _decision_core(old_root / "decisions.jsonl"), _decision_core(new_root / "decisions.jsonl")
            )
            for key in ("daily_symbols", "weekly_symbols", "counts"):
                self.assertEqual(_manifest(old_root)[key], _manifest(new_root)[key])
            for name in ("short_research.json", "short_candidates.csv"):
                self.assertEqual((old_root / name).read_bytes(), (new_root / name).read_bytes())
            for name, path in _legacy_files(root / "old").items():
                self.assertEqual(path.read_bytes(), _legacy_files(root / "new")[name].read_bytes())

    def test_sample_truncation_marks_short_unavailable_but_publishes_long(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status = _run_scan(
                Path(td),
                enable_short=True,
                max_symbols=100,
            )
            self.assertEqual(status.decision_output_status, "written")
            root = Path(status.decision_snapshot_root)
            manifest = json.loads(
                (root / "run_manifest.json").read_text(encoding="utf-8")
            )
            short = manifest["short_research"]
            self.assertEqual(short["status"], "unavailable")
            self.assertIn(
                "UNIVERSE_TRUNCATED_MAX_SYMBOLS", short["reason_codes"]
            )
            self.assertTrue((root / "short_candidates.csv").is_file())
            self.assertEqual(
                (root / "short_candidates.csv").read_text(encoding="utf-8").count("\n"),
                1,
            )
            self.assertIn(
                "Unavailable reasons", (root / "action_list.md").read_text(encoding="utf-8")
            )
            self.assertTrue((root / "decisions.jsonl").is_file())

    def test_short_module_failure_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status = _run_scan(
                Path(td),
                enable_short=True,
                short_failure=True,
            )
            self.assertEqual(status.decision_output_status, "written")
            self.assertEqual(status.latest_pointer_status, "written")
            root = Path(status.decision_snapshot_root)
            manifest = json.loads(
                (root / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["short_research"]["status"], "unavailable"
            )
            self.assertIn(
                "SHORT_RESEARCH_CALCULATION_FAILED",
                manifest["short_research"]["reason_codes"],
            )
            self.assertTrue((root / "decisions.jsonl").is_file())

    def test_core_snapshot_failure_does_not_advance_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = _run_scan(
                root,
                enable_short=True,
                snapshot_failure=True,
                eod_available=False,
            )
            self.assertEqual(status.decision_output_status, "failed")
            self.assertEqual(status.latest_pointer_status, "not_attempted")
            self.assertFalse(
                (root / "decisions" / "latest_production.json").exists()
            )
            self.assertIn(
                "decision output failed",
                (root / "outputs").glob("*_report.md").__next__().read_text(
                    encoding="utf-8"
                ),
            )


    def test_benchmark_gate_with_real_filters_and_offline_short_parity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = _run_scan(root, enable_short=True, real_legacy_filters=True)
            for name, path in _legacy_files(root).items():
                if name != "research_pool":
                    with path.open(encoding="utf-8") as handle:
                        self.assertEqual(list(csv.DictReader(handle)), [], name)
            manifest = _manifest(Path(status.decision_snapshot_root))
            self.assertTrue(manifest["daily_symbols"])
            archive = json.loads(
                (Path(status.decision_snapshot_root) / "short_research.json").read_text()
            )
            frozen = pd.read_csv(DATASET, dtype={"cik": str, "sic": str}, low_memory=False)
            offline = build_short_cross_section(frozen.loc[frozen["signal_date"].eq(DATE)])
            self.assertGreater(offline.selected_count, 0)
            self.assertEqual(
                [row["symbol"] for row in archive["selected"]],
                [row.symbol for row in offline.selected],
            )

    def test_same_day_compatibility_report_uses_the_archive(self) -> None:
        for initially_unavailable in (True, False):
            with self.subTest(initially_unavailable=initially_unavailable), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                first = _run_scan(root, enable_short=True, short_failure=initially_unavailable)
                archived = Path(first.decision_snapshot_root) / "short_research.json"
                before = archived.read_bytes()
                rerun = _run_scan(
                    root, enable_short=True, short_failure=not initially_unavailable, allow_existing=True
                )
                status = "unavailable" if initially_unavailable else "ready"
                self.assertEqual(rerun.decision_output_status, "reused")
                self.assertEqual(archived.read_bytes(), before)
                self.assertIn(f"- short research status: {status}", rerun.report_path.read_text())

    def test_short_csv_serialization_failure_preserves_formal_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td, patch.object(
            snapshot, "short_candidates_csv", side_effect=ValueError("synthetic serialization failure")
        ):
            status = _run_scan(Path(td), enable_short=True)
            self.assertEqual(status.decision_output_status, "written")
            self.assertEqual(status.latest_pointer_status, "written")
            root = Path(status.decision_snapshot_root)
            self.assertEqual(_manifest(root)["short_research"]["status"], "unavailable")
            self.assertIn("SHORT_RESEARCH_PRESENTATION_FAILED", (root / "action_list.md").read_text())
            self.assertEqual(len((root / "short_candidates.csv").read_text().splitlines()), 1)
            self.assertIn("- short research status: unavailable", status.report_path.read_text())

    def test_persistent_short_renderer_failure_preserves_formal_snapshot(self) -> None:
        for formatter in ("render_short_research_section", "render_short_snapshot_section"):
            with (
                self.subTest(formatter=formatter),
                tempfile.TemporaryDirectory() as td,
                patch.object(snapshot, formatter, side_effect=ValueError("short renderer failure")) as writer,
                patch.object(archive, formatter, side_effect=ValueError("still broken on reload")) as loader,
            ):
                status = _run_scan(Path(td), enable_short=True)
                self.assertEqual(status.decision_output_status, "written")
                self.assertEqual(status.latest_pointer_status, "written")
                root = Path(status.decision_snapshot_root)
                result = archive.load_short_snapshot(root, _manifest(root))
                self.assertEqual(result.status, "unavailable")
                self.assertEqual(result.selected_count, 0)
                self.assertIn("SHORT_RESEARCH_PRESENTATION_FAILED", result.reason_codes)
                self.assertIn("- short research status: unavailable", status.report_path.read_text())
                writer.assert_called_once()
                loader.assert_not_called()

    def test_scan_entry_evidence_mapping(self) -> None:
        evidence = build_scan_entry_evidence()
        self.assertTrue(evidence["long_decisions_identical"])
        self.assertTrue(evidence["long_daily_symbols_identical"])
        self.assertTrue(evidence["long_weekly_symbols_identical"])
        self.assertTrue(evidence["long_legacy_csv_identical"])
        self.assertTrue(evidence["qqq_below_sma200"])
        self.assertEqual(evidence["off"]["short_status"], "disabled")
        self.assertEqual(evidence["on"]["short_status"], "ready")
        self.assertGreater(evidence["on"]["short_selected_count"], 0)
        self.assertEqual(evidence["truncation"]["short_status"], "unavailable")
        self.assertIn(
            "UNIVERSE_TRUNCATED_MAX_SYMBOLS",
            evidence["truncation"]["reason_codes"],
        )
        self.assertEqual(evidence["short_failure"]["short_status"], "unavailable")
        self.assertIn(
            "SHORT_RESEARCH_CALCULATION_FAILED",
            evidence["short_failure"]["reason_codes"],
        )
        self.assertEqual(evidence["core_failure"]["decision_output_status"], "failed")
        self.assertEqual(
            evidence["core_failure"]["latest_pointer_status"], "not_attempted"
        )
        self.assertFalse(evidence["core_failure"]["latest_pointer_exists"])


if __name__ == "__main__":
    unittest.main()
