"""Watchlist refresh safe-merge protection tests.

Covers ``merge_refreshed_watchlist`` (SRC:MANUAL / ai_smallcap / enabled=0
preservation, overlap merge, additive vs prune), the refresh CLI
network-failure guard and ``--dry-run``, LF-only CSV output,
``build_smallcap_universe.py`` SRC:MANUAL preservation, and CIK-based
corporate-action reconciliation (rename migration + delisting hygiene).
Pure offline mocks; no network calls.
"""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import pandas as pd

from ai_value_scanner.scanner import (
    WATCHLIST_CSV_COLUMNS,
    build_sec_ticker_cik_maps,
    fetch_stockanalysis_etf_symbols,
    load_cached_symbol_to_cik,
    merge_refreshed_watchlist,
    reconcile_manual_seed_csv,
    reconcile_watchlist_corporate_actions,
    write_csv_atomic,
)


def _wl(symbol, bucket, etfs="", enabled=1, etf_count=None,
        updated_utc="2026-10-01T00:00:00+00:00"):
    if etf_count is None:
        etf_count = len([
            token for token in str(etfs).split(",")
            if token and not token.strip().upper().startswith("SRC:")
        ])
    return {
        "symbol": symbol,
        "bucket": bucket,
        "etf_count": etf_count,
        "etfs": etfs,
        "enabled": enabled,
        "updated_utc": updated_utc,
    }


def _frame(rows):
    return pd.DataFrame(list(rows), columns=WATCHLIST_CSV_COLUMNS)


def _pairs(frame):
    return set(zip(frame["symbol"], frame["bucket"]))


class TestManualAndSmallcapPreservation(unittest.TestCase):
    def test_src_manual_rows_preserved_across_buckets(self) -> None:
        existing = _frame([
            _wl("MANA", "core_ai", "SRC:MANUAL"),
            _wl("MANB", "ai_enabler", "SRC:MANUAL"),
            _wl("SCAP", "ai_smallcap", "SRC:NASDAQ_SCREEN"),
            _wl("ETFA", "core_ai", "IGV"),
        ])
        refreshed = _frame([_wl("NEWC", "core_ai", "IGV,XLK")])
        merged, stats = merge_refreshed_watchlist(existing, refreshed)
        pairs = _pairs(merged)
        self.assertIn(("MANA", "core_ai"), pairs)
        self.assertIn(("MANB", "ai_enabler"), pairs)
        self.assertIn(("SCAP", "ai_smallcap"), pairs)
        self.assertIn(("ETFA", "core_ai"), pairs)
        self.assertIn(("NEWC", "core_ai"), pairs)
        self.assertEqual(stats["existing_rows"], 4)
        self.assertEqual(stats["fetched_etf_rows"], 1)
        self.assertEqual(stats["added_rows"], 1)
        self.assertEqual(stats["updated_rows"], 0)
        self.assertEqual(stats["preserved_manual_or_smallcap_rows"], 3)
        self.assertEqual(stats["preserved_prior_etf_rows"], 1)
        self.assertEqual(stats["pruned_etf_rows"], 0)
        self.assertEqual(stats["total_rows"], 5)
        self.assertEqual(stats["unique_symbols"], 5)
        man1 = merged[merged["symbol"] == "MANA"].iloc[0]
        self.assertEqual(man1["etfs"], "SRC:MANUAL")
        self.assertEqual(int(man1["etf_count"]), 0)
        self.assertEqual(int(man1["enabled"]), 1)
        sc1 = merged[merged["symbol"] == "SCAP"].iloc[0]
        self.assertEqual(sc1["etfs"], "SRC:NASDAQ_SCREEN")
        self.assertEqual(int(sc1["etf_count"]), 0)

    def test_manual_smallcap_preserved_even_if_only_dropped_row(self) -> None:
        existing = _frame([_wl("MANC", "ai_smallcap", "SRC:MANUAL")])
        merged, stats = merge_refreshed_watchlist(
            existing, _frame([_wl("NEW", "core_ai", "IGV")]),
            prune_dropped_etf_rows=True,
        )
        self.assertIn(("MANC", "ai_smallcap"), _pairs(merged))
        self.assertEqual(stats["preserved_manual_or_smallcap_rows"], 1)
        self.assertEqual(stats["pruned_etf_rows"], 0)


class TestOverlapAndEnabledOverride(unittest.TestCase):
    def test_src_manual_plus_refreshed_etfs_merges_tokens(self) -> None:
        existing = _frame([_wl("HOOD", "core_ai", "SRC:MANUAL")])
        refreshed = _frame([_wl("HOOD", "core_ai", "ARKQ,IGV")])
        merged, stats = merge_refreshed_watchlist(existing, refreshed)
        row = merged.iloc[0]
        self.assertEqual(row["etfs"], "ARKQ,IGV,SRC:MANUAL")
        self.assertEqual(int(row["etf_count"]), 2)
        self.assertEqual(stats["updated_rows"], 1)
        self.assertEqual(stats["added_rows"], 0)
        self.assertEqual(stats["preserved_manual_or_smallcap_rows"], 0)

    def test_enabled_zero_override_survives_refresh(self) -> None:
        existing = _frame([_wl("OFF", "core_ai", "IGV", enabled=0)])
        refreshed = _frame([_wl("OFF", "core_ai", "IGV,SMH")])
        merged, _ = merge_refreshed_watchlist(existing, refreshed)
        row = merged.iloc[0]
        self.assertEqual(int(row["enabled"]), 0)
        self.assertEqual(row["etfs"], "IGV,SMH")
        self.assertEqual(int(row["etf_count"]), 2)

    def test_enabled_zero_row_preserved_without_refresh(self) -> None:
        existing = _frame([_wl("OFF", "ai_enabler", "XLI", enabled=0)])
        merged, stats = merge_refreshed_watchlist(
            existing, _frame([]), prune_dropped_etf_rows=True,
        )
        self.assertIn(("OFF", "ai_enabler"), _pairs(merged))
        self.assertEqual(stats["preserved_manual_or_smallcap_rows"], 1)

    def test_updated_utc_comes_from_refreshed_row(self) -> None:
        existing = _frame([
            _wl("SYM", "core_ai", "IGV", updated_utc="2026-01-01T00:00:00+00:00"),
        ])
        refreshed = _frame([
            _wl("SYM", "core_ai", "IGV,SMH", updated_utc="2026-10-16T12:00:00+00:00"),
        ])
        merged, _ = merge_refreshed_watchlist(existing, refreshed)
        self.assertEqual(
            merged.iloc[0]["updated_utc"], "2026-10-16T12:00:00+00:00")


class TestAdditiveVsPrune(unittest.TestCase):
    def test_default_keeps_dropped_pure_etf_rows(self) -> None:
        existing = _frame([
            _wl("OLD", "ai_enabler", "XLI"),
            _wl("MAN", "ai_enabler", "SRC:MANUAL"),
        ])
        refreshed = _frame([_wl("KEEP", "ai_enabler", "XLI")])
        merged, stats = merge_refreshed_watchlist(existing, refreshed)
        pairs = _pairs(merged)
        self.assertIn(("OLD", "ai_enabler"), pairs)
        self.assertIn(("MAN", "ai_enabler"), pairs)
        self.assertEqual(stats["preserved_prior_etf_rows"], 1)
        self.assertEqual(stats["pruned_etf_rows"], 0)

    def test_prune_removes_only_unprotected_pure_etf_rows(self) -> None:
        existing = _frame([
            _wl("OLD", "ai_enabler", "XLI"),
            _wl("MAN", "ai_enabler", "SRC:MANUAL"),
            _wl("SC", "ai_smallcap", "SRC:YAHOO_HOT"),
            _wl("OFF", "core_ai", "IGV", enabled=0),
        ])
        refreshed = _frame([_wl("KEEP", "ai_enabler", "XLI")])
        merged, stats = merge_refreshed_watchlist(
            existing, refreshed, prune_dropped_etf_rows=True)
        pairs = _pairs(merged)
        self.assertNotIn(("OLD", "ai_enabler"), pairs)
        self.assertIn(("MAN", "ai_enabler"), pairs)
        self.assertIn(("SC", "ai_smallcap"), pairs)
        self.assertIn(("OFF", "core_ai"), pairs)
        self.assertIn(("KEEP", "ai_enabler"), pairs)
        self.assertEqual(stats["pruned_etf_rows"], 1)
        self.assertEqual(stats["preserved_manual_or_smallcap_rows"], 3)
        self.assertEqual(stats["added_rows"], 1)


class TestNormalizationAndCollapse(unittest.TestCase):
    def test_symbol_and_bucket_normalized_and_empty_dropped(self) -> None:
        existing = _frame([
            _wl("brk-b", "Core_AI", "IGV"),
            _wl("", "core_ai", "IGV"),
            _wl("X", "", "IGV"),
        ])
        merged, stats = merge_refreshed_watchlist(existing, _frame([]))
        self.assertEqual(stats["existing_rows"], 1)
        self.assertEqual(merged.iloc[0]["symbol"], "BRK.B")
        self.assertEqual(merged.iloc[0]["bucket"], "core_ai")

    def test_duplicate_existing_rows_collapse_union_and_enabled_zero(self) -> None:
        existing = _frame([
            _wl("DUP", "core_ai", "IGV", enabled=1),
            _wl("DUP", "core_ai", "SMH,SRC:MANUAL", enabled=0),
        ])
        merged, stats = merge_refreshed_watchlist(existing, _frame([]))
        self.assertEqual(stats["existing_rows"], 1)
        row = merged.iloc[0]
        self.assertEqual(row["etfs"], "IGV,SMH,SRC:MANUAL")
        self.assertEqual(int(row["etf_count"]), 2)
        self.assertEqual(int(row["enabled"]), 0)

    def test_duplicate_refreshed_rows_collapse_union(self) -> None:
        refreshed = _frame([
            _wl("NEW", "core_ai", "IGV"),
            _wl("NEW", "core_ai", "SMH"),
        ])
        merged, stats = merge_refreshed_watchlist(_frame([]), refreshed)
        self.assertEqual(stats["fetched_etf_rows"], 1)
        self.assertEqual(stats["added_rows"], 1)
        row = merged.iloc[0]
        self.assertEqual(row["etfs"], "IGV,SMH")
        self.assertEqual(int(row["etf_count"]), 2)
        self.assertEqual(int(row["enabled"]), 1)

    def test_both_empty_returns_typed_empty_frame(self) -> None:
        merged, stats = merge_refreshed_watchlist(pd.DataFrame(), pd.DataFrame())
        self.assertTrue(merged.empty)
        self.assertEqual(list(merged.columns), WATCHLIST_CSV_COLUMNS)
        self.assertEqual(stats["total_rows"], 0)
        self.assertEqual(stats["unique_symbols"], 0)

    def test_sorted_by_bucket_then_symbol(self) -> None:
        existing = _frame([
            _wl("ZZ", "core_ai", "IGV"),
            _wl("AA", "core_ai", "IGV"),
            _wl("MM", "ai_enabler", "XLI"),
        ])
        merged, _ = merge_refreshed_watchlist(existing, _frame([]))
        self.assertEqual(
            list(zip(merged["bucket"], merged["symbol"])),
            [("ai_enabler", "MM"), ("core_ai", "AA"), ("core_ai", "ZZ")],
        )


class TestWriteCsvAtomicLineEndings(unittest.TestCase):
    def test_output_uses_unix_lf_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watchlist.csv"
            write_csv_atomic(
                _frame([_wl("AAPL", "core_ai", "IGV")]), path)
            data = path.read_bytes()
            self.assertNotIn(b"\r\n", data)
            self.assertTrue(
                data.startswith(
                    b"symbol,bucket,etf_count,etfs,enabled,updated_utc\n"))

    def test_fetch_stockanalysis_supports_holdings_table_payload(self) -> None:
        import unittest.mock as mock

        fake_html = (
            'holdingsTable:{query:{type:"a",index:"holdings"},'
            'data:[{no:1,s:"$AMD",n:"AMD"},{no:2,s:"$NVDA",n:"NVIDIA"}]}'
        )
        fake_resp = mock.Mock(status_code=200, text=fake_html)
        with mock.patch("ai_value_scanner.scanner.requests.get", return_value=fake_resp):
            symbols, err = fetch_stockanalysis_etf_symbols("SOXX", 10)
        self.assertIsNone(err)
        self.assertEqual(symbols, ["AMD", "NVDA"])


class TestRefreshCliSafety(unittest.TestCase):
    def _import_cli(self):
        import sys
        sys.path.insert(0, "scripts")
        try:
            import refresh_ai_watchlist
        finally:
            sys.path.pop(0)
        return refresh_ai_watchlist

    def _run_cli(self, cli, argv):
        import sys
        import unittest.mock as mock

        with mock.patch.object(sys, "argv", argv):
            cli.main()

    def test_empty_refresh_preserves_file_byte_for_byte(self) -> None:
        import unittest.mock as mock

        cli = self._import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            write_csv_atomic(
                _frame([_wl("MAN", "core_ai", "SRC:MANUAL")]), out)
            before = out.read_bytes()
            argv = ["refresh_ai_watchlist.py", "--output", str(out)]
            with mock.patch.object(
                cli, "refresh_watchlist_from_etfs",
                return_value=pd.DataFrame(),
            ):
                self._run_cli(cli, argv)
            self.assertEqual(out.read_bytes(), before)

    def test_dry_run_prints_stats_and_writes_nothing(self) -> None:
        import contextlib
        import io
        import unittest.mock as mock

        cli = self._import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            write_csv_atomic(
                _frame([_wl("MAN", "core_ai", "SRC:MANUAL")]), out)
            before = out.read_bytes()
            refreshed = _frame([_wl("NEW", "core_ai", "IGV")])
            argv = [
                "refresh_ai_watchlist.py", "--output", str(out), "--dry-run",
            ]
            buffer = io.StringIO()
            with mock.patch.object(
                cli, "refresh_watchlist_from_etfs", return_value=refreshed,
            ), mock.patch.object(
                cli, "_load_corporate_action_references",
                return_value=({}, {}, None),
            ):
                with contextlib.redirect_stdout(buffer):
                    self._run_cli(cli, argv)
            output = buffer.getvalue()
            self.assertEqual(out.read_bytes(), before)
            self.assertIn("existing=1", output)
            self.assertIn("fetched_etf=1", output)
            self.assertIn("added=1", output)
            self.assertIn("preserved_protected=1", output)
            self.assertIn("dry-run complete", output)
            self.assertIn("+ NEW (core_ai) etfs=IGV", output)

    def test_write_merges_and_archive_only_for_config_path(self) -> None:
        import unittest.mock as mock

        cli = self._import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            write_csv_atomic(
                _frame([_wl("MAN", "core_ai", "SRC:MANUAL")]), out)
            refreshed = _frame([
                _wl("MAN", "core_ai", "IGV"),
                _wl("NEW", "ai_enabler", "XLI"),
            ])
            argv = ["refresh_ai_watchlist.py", "--output", str(out)]
            with mock.patch.object(
                cli, "refresh_watchlist_from_etfs", return_value=refreshed,
            ), mock.patch.object(
                cli, "_load_corporate_action_references",
                return_value=({}, {}, None),
            ):
                with mock.patch.object(
                    cli, "archive_watchlist_snapshot",
                ) as archive_mock:
                    self._run_cli(cli, argv)
            archive_mock.assert_not_called()
            merged = pd.read_csv(out)
            man = merged[merged["symbol"] == "MAN"].iloc[0]
            self.assertEqual(man["etfs"], "IGV,SRC:MANUAL")
            self.assertEqual(int(man["etf_count"]), 1)
            self.assertIn("NEW", set(merged["symbol"]))

    def test_archive_called_when_output_is_config_path(self) -> None:
        import unittest.mock as mock

        cli = self._import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            write_csv_atomic(
                _frame([_wl("MAN", "core_ai", "SRC:MANUAL")]), out)
            fake_cfg = mock.Mock()
            fake_cfg.watchlist_csv_path = str(out)
            refreshed = _frame([_wl("NEW", "core_ai", "IGV")])
            argv = ["refresh_ai_watchlist.py"]
            with mock.patch.object(cli, "load_config", return_value=fake_cfg):
                with mock.patch.object(
                    cli, "refresh_watchlist_from_etfs", return_value=refreshed,
                ), mock.patch.object(
                    cli, "_load_corporate_action_references",
                    return_value=({}, {}, None),
                ):
                    with mock.patch.object(
                        cli, "archive_watchlist_snapshot",
                        return_value=Path(tmp) / "ai_watchlist_snap.csv",
                    ) as archive_mock:
                        self._run_cli(cli, argv)
            archive_mock.assert_called_once()


class TestSmallcapManualPreservation(unittest.TestCase):
    def _import_builder(self):
        import sys
        sys.path.insert(0, "scripts")
        try:
            import build_smallcap_universe
        finally:
            sys.path.pop(0)
        return build_smallcap_universe

    def _run_builder(self, builder, argv):
        import sys
        import unittest.mock as mock

        with mock.patch.object(sys, "argv", argv):
            builder.main()

    def test_offline_rebuild_preserves_manual_smallcap_rows(self) -> None:
        builder = self._import_builder()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            manual_csv = Path(tmp) / "manual.csv"
            manual_csv.write_text(
                "symbol,note\nSEED,seed\n", encoding="utf-8")
            write_csv_atomic(
                _frame([
                    _wl("MANC", "ai_smallcap", "SRC:MANUAL"),
                    _wl("STALE", "ai_smallcap", "SRC:NASDAQ_SCREEN"),
                    _wl("ETFX", "core_ai", "IGV"),
                ]),
                out,
            )
            argv = [
                "build_smallcap_universe.py",
                "--output", str(out),
                "--sources", "manual",
                "--manual-csv", str(manual_csv),
                "--offline",
            ]
            self._run_builder(builder, argv)
            merged = pd.read_csv(out)
            smallcap = merged[merged["bucket"] == "ai_smallcap"]
            symbols = set(smallcap["symbol"])
            self.assertIn("MANC", symbols)
            self.assertIn("SEED", symbols)
            self.assertNotIn("STALE", symbols)
            self.assertIn("ETFX", set(merged["symbol"]))
            keep = smallcap[smallcap["symbol"] == "MANC"].iloc[0]
            self.assertIn("SRC:MANUAL", keep["etfs"])

    def test_manual_row_rederived_by_seed_not_duplicated(self) -> None:
        builder = self._import_builder()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            manual_csv = Path(tmp) / "manual.csv"
            manual_csv.write_text(
                "symbol,note\nMANC,seed\n", encoding="utf-8")
            write_csv_atomic(
                _frame([_wl("MANC", "ai_smallcap", "SRC:MANUAL")]), out)
            argv = [
                "build_smallcap_universe.py",
                "--output", str(out),
                "--sources", "manual",
                "--manual-csv", str(manual_csv),
                "--offline",
            ]
            self._run_builder(builder, argv)
            merged = pd.read_csv(out)
            smallcap = merged[merged["bucket"] == "ai_smallcap"]
            self.assertEqual(len(smallcap), 1)
            self.assertEqual(smallcap.iloc[0]["symbol"], "MANC")
            self.assertIn("SRC:MANUAL", smallcap.iloc[0]["etfs"])


class TestCorporateActionReconciliation(unittest.TestCase):
    """CIK-based ticker rename migration and delisting hygiene (offline)."""

    def test_build_sec_ticker_cik_maps_order_and_zfill(self) -> None:
        ticker_to_cik, cik_to_tickers = build_sec_ticker_cik_maps([
            {"symbol": "VIP", "cik_str": 1652044},
            {"ticker": "GREEL", "cik_str": 1652044},
            {"symbol": "vmrk", "cik": "906831"},
            {"symbol": "", "cik": "1"},
        ])
        self.assertEqual(ticker_to_cik["VIP"], "0001652044")
        self.assertEqual(ticker_to_cik["GREEL"], "0001652044")
        self.assertEqual(ticker_to_cik["VMRK"], "0000906831")
        self.assertEqual(cik_to_tickers["0001652044"], ["VIP", "GREEL"])
        self.assertEqual(cik_to_tickers["0000906831"], ["VMRK"])

    def test_load_cached_symbol_to_cik_reads_cache_fixtures(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "parsed_fund_0001812477.json").write_text(
                json.dumps({"symbol": "bitf", "cik": "0001812477"}),
                encoding="utf-8",
            )
            (base / "submissions_0001812477.json").write_text(
                json.dumps({"tickers": ["KEEL"]}), encoding="utf-8")
            (base / "parsed_fund_0000000002.json").write_text(
                json.dumps({"symbol": "ZZZ"}), encoding="utf-8")
            (base / "parsed_fund_broken.json").write_text(
                "{not json", encoding="utf-8")
            mapping = load_cached_symbol_to_cik(base)
        self.assertEqual(mapping["BITF"], "0001812477")
        self.assertEqual(mapping["KEEL"], "0001812477")
        self.assertEqual(mapping["ZZZ"], "0000000002")

    def test_bitf_renames_to_keel_via_cik(self) -> None:
        watchlist = _frame([_wl("BITF", "ai_smallcap", "SRC:MANUAL")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"KEEP": "0000000001"},
            sec_cik_to_tickers={
                "0001812477": ["KEEL"],
                "0000000001": ["KEEP"],
            },
            historical_symbol_to_cik={"BITF": "0001812477"},
        )
        row = reconciled.iloc[0]
        self.assertEqual(row["symbol"], "KEEL")
        self.assertEqual(row["bucket"], "ai_smallcap")
        self.assertEqual(row["etfs"], "SRC:MANUAL")
        self.assertEqual(int(row["etf_count"]), 0)
        self.assertEqual(int(row["enabled"]), 1)
        self.assertEqual(report["renamed_count"], 1)
        self.assertEqual(report["removed_count"], 0)
        self.assertEqual(
            report["renamed"][0],
            {
                "old_symbol": "BITF",
                "new_symbol": "KEEL",
                "cik": "0001812477",
                "bucket": "ai_smallcap",
            },
        )

    def test_sats_renames_to_echo(self) -> None:
        watchlist = _frame([_wl("SATS", "ai_enabler", "SRC:MANUAL")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"ECHO": "0001493594"},
            sec_cik_to_tickers={"0001493594": ["ECHO"]},
            historical_symbol_to_cik={"SATS": "0001493594"},
        )
        self.assertEqual(reconciled.iloc[0]["symbol"], "ECHO")
        self.assertEqual(report["renamed_count"], 1)

    def test_eqr_rename_folds_into_existing_vmrk_row(self) -> None:
        watchlist = _frame([
            _wl("EQR", "ai_peripheral", "VNQ,SRC:MANUAL"),
            _wl("VMRK", "ai_peripheral", "VNQ,XLRE"),
        ])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"VMRK": "0000906831"},
            sec_cik_to_tickers={"0000906831": ["VMRK"]},
            historical_symbol_to_cik={"EQR": "0000906831"},
        )
        self.assertEqual(len(reconciled), 1)
        row = reconciled.iloc[0]
        self.assertEqual((row["symbol"], row["bucket"]),
                         ("VMRK", "ai_peripheral"))
        self.assertEqual(row["etfs"], "VNQ,XLRE,SRC:MANUAL")
        self.assertEqual(int(row["etf_count"]), 2)
        self.assertEqual(report["renamed_count"], 1)

    def test_cybr_missing_in_sec_removed(self) -> None:
        watchlist = _frame([_wl("CYBR", "core_ai", "IGV")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"OTHER": "0000000002"},
            sec_cik_to_tickers={"0001598110": []},
            historical_symbol_to_cik={"CYBR": "0001598110"},
        )
        self.assertTrue(reconciled.empty)
        self.assertEqual(report["removed_count"], 1)
        self.assertEqual(
            report["removed_delisted"][0],
            {
                "symbol": "CYBR",
                "cik": "0001598110",
                "bucket": "core_ai",
                "reason": "missing_in_sec",
            },
        )

    def test_wbd_inactive_in_alpaca_removed(self) -> None:
        watchlist = _frame([_wl("WBD", "ai_peripheral", "XLC")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"WBD": "0001437107"},
            sec_cik_to_tickers={"0001437107": ["WBD"]},
            historical_symbol_to_cik={"WBD": "0001437107"},
            active_alpaca_symbols={"AAPL", "MSFT"},
        )
        self.assertTrue(reconciled.empty)
        self.assertEqual(report["removed_count"], 1)
        self.assertEqual(
            report["removed_delisted"][0]["reason"], "inactive_in_alpaca")

    def test_dbrg_preferred_only_tickers_not_migrated(self) -> None:
        watchlist = _frame([_wl("DBRG", "ai_peripheral", "VNQ")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"DBRG": "0001679688"},
            sec_cik_to_tickers={"0001679688": ["DBRG-PH", "DBRHP"]},
            historical_symbol_to_cik={"DBRG": "0001679688"},
            active_alpaca_symbols={"DBRG-PH", "DBRHP"},
        )
        self.assertTrue(reconciled.empty)
        self.assertEqual(report["renamed_count"], 0)
        self.assertEqual(report["removed_count"], 1)
        self.assertEqual(report["removed_delisted"][0]["symbol"], "DBRG")

    def test_gree_migrates_to_vip_not_greel(self) -> None:
        watchlist = _frame([_wl("GREE", "ai_smallcap", "SRC:MANUAL")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"VIP": "0000009999"},
            sec_cik_to_tickers={"0000009999": ["VIP", "GREEL"]},
            historical_symbol_to_cik={"GREE": "0000009999"},
            active_alpaca_symbols={"VIP", "GREEL"},
        )
        self.assertEqual(reconciled.iloc[0]["symbol"], "VIP")
        self.assertEqual(report["renamed"][0]["new_symbol"], "VIP")

    def test_empty_sec_mapping_leaves_watchlist_untouched(self) -> None:
        watchlist = _frame([
            _wl("BITF", "ai_smallcap", "SRC:MANUAL"),
            _wl("WBD", "ai_peripheral", "XLC"),
        ])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={},
            sec_cik_to_tickers={},
            historical_symbol_to_cik={"BITF": "0001812477"},
        )
        pd.testing.assert_frame_equal(reconciled, watchlist)
        self.assertEqual(report["renamed"], [])
        self.assertEqual(report["removed_delisted"], [])

    def test_empty_active_alpaca_set_treated_as_none(self) -> None:
        # A transient Alpaca outage (empty set) must not mass-prune: the
        # rename still resolves and no Alpaca-driven removal happens.
        watchlist = _frame([_wl("BITF", "ai_smallcap", "SRC:MANUAL")])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"KEEP": "0000000001"},
            sec_cik_to_tickers={
                "0001812477": ["KEEL"],
                "0000000001": ["KEEP"],
            },
            historical_symbol_to_cik={"BITF": "0001812477"},
            active_alpaca_symbols=set(),
        )
        self.assertEqual(reconciled.iloc[0]["symbol"], "KEEL")
        self.assertEqual(report["renamed_count"], 1)
        self.assertEqual(report["removed_count"], 0)

    def test_unchanged_rows_keep_protected_flags(self) -> None:
        watchlist = _frame([
            _wl("KEEP", "core_ai", "IGV", enabled=0),
            _wl("MANA", "core_ai", "SRC:MANUAL"),
        ])
        reconciled, report = reconcile_watchlist_corporate_actions(
            watchlist,
            sec_ticker_to_cik={"KEEP": "0000000001", "MANA": "0000000003"},
            sec_cik_to_tickers={
                "0000000001": ["KEEP"],
                "0000000003": ["MANA"],
            },
            active_alpaca_symbols={"KEEP", "MANA"},
        )
        rows = {row["symbol"]: row for row in reconciled.to_dict("records")}
        self.assertEqual(int(rows["KEEP"]["enabled"]), 0)
        self.assertEqual(rows["MANA"]["etfs"], "SRC:MANUAL")
        self.assertEqual(report["renamed_count"], 0)
        self.assertEqual(report["removed_count"], 0)

    def test_reconcile_manual_seed_csv_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manual = Path(tmp) / "ai_smallcap_manual.csv"
            original = "symbol,note\nBITF,seed\nCYBR,delisted\nHOOD,keep\n"
            manual.write_text(original, encoding="utf-8")
            report = {
                "renamed": [
                    {"old_symbol": "BITF", "new_symbol": "KEEL"},
                ],
                "removed_delisted": [{"symbol": "CYBR"}],
            }
            dry_stats = reconcile_manual_seed_csv(manual, report, dry_run=True)
            self.assertEqual(dry_stats, {"renamed": 1, "removed": 1})
            self.assertEqual(manual.read_text(encoding="utf-8"), original)
            stats = reconcile_manual_seed_csv(manual, report)
            self.assertEqual(stats, {"renamed": 1, "removed": 1})
            text = manual.read_text(encoding="utf-8")
            self.assertEqual(text, "symbol,note\nKEEL,seed\nHOOD,keep\n")
            self.assertNotIn(b"\r\n", manual.read_bytes())

    def test_reconcile_manual_seed_csv_absent_file_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stats = reconcile_manual_seed_csv(
                Path(tmp) / "missing.csv",
                {"renamed": [{"old_symbol": "BITF", "new_symbol": "KEEL"}]},
            )
        self.assertEqual(stats, {"renamed": 0, "removed": 0})

    def _import_cli(self):
        import sys
        sys.path.insert(0, "scripts")
        try:
            import refresh_ai_watchlist
        finally:
            sys.path.pop(0)
        return refresh_ai_watchlist

    def test_cli_applies_corporate_actions_and_syncs_manual_seed(self) -> None:
        import contextlib
        import io
        import sys
        import unittest.mock as mock

        cli = self._import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            manual = Path(tmp) / "ai_smallcap_manual.csv"
            manual.write_text(
                "symbol,note\nBITF,seed\nCYBR,gone\nHOOD,keep\n",
                encoding="utf-8",
            )
            write_csv_atomic(
                _frame([
                    _wl("BITF", "ai_smallcap", "SRC:MANUAL"),
                    _wl("CYBR", "core_ai", "IGV"),
                ]),
                out,
            )
            refreshed = _frame([_wl("NEW", "core_ai", "IGV")])
            argv = [
                "refresh_ai_watchlist.py",
                "--output", str(out),
                "--manual-seed-csv", str(manual),
            ]
            buffer = io.StringIO()
            with mock.patch.object(
                cli, "refresh_watchlist_from_etfs", return_value=refreshed,
            ), mock.patch.object(
                cli, "_load_corporate_action_references",
                return_value=(
                    {"NEW": "0000000002"},
                    {
                        "0001812477": ["KEEL"],
                        "0000000002": ["NEW"],
                    },
                    None,
                ),
            ), mock.patch.object(
                cli, "load_cached_symbol_to_cik",
                return_value={"BITF": "0001812477", "CYBR": "0001598110"},
            ):
                with contextlib.redirect_stdout(buffer):
                    with mock.patch.object(sys, "argv", argv):
                        cli.main()
            output = buffer.getvalue()
            self.assertIn(
                "corporate_actions renamed=1 removed_delisted=1", output)
            self.assertIn(
                "~ BITF -> KEEL (ai_smallcap, cik=0001812477)", output)
            self.assertIn(
                "- CYBR (core_ai, cik=0001598110, reason=missing_in_sec)",
                output,
            )
            self.assertIn("manual_seed renamed=1 removed=1", output)
            merged = pd.read_csv(out)
            symbols = set(merged["symbol"])
            self.assertIn("KEEL", symbols)
            self.assertIn("NEW", symbols)
            self.assertNotIn("BITF", symbols)
            self.assertNotIn("CYBR", symbols)
            keel = merged[merged["symbol"] == "KEEL"].iloc[0]
            self.assertEqual(keel["etfs"], "SRC:MANUAL")
            manual_text = manual.read_text(encoding="utf-8")
            self.assertEqual(
                manual_text, "symbol,note\nKEEL,seed\nHOOD,keep\n")

    def test_cli_no_reconcile_flag_skips_reconciliation(self) -> None:
        import sys
        import unittest.mock as mock

        cli = self._import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ai_watchlist.csv"
            write_csv_atomic(
                _frame([_wl("BITF", "ai_smallcap", "SRC:MANUAL")]), out)
            refreshed = _frame([_wl("NEW", "core_ai", "IGV")])
            argv = [
                "refresh_ai_watchlist.py",
                "--output", str(out),
                "--no-reconcile-corporate-actions",
            ]
            with mock.patch.object(
                cli, "refresh_watchlist_from_etfs", return_value=refreshed,
            ), mock.patch.object(
                cli, "_load_corporate_action_references",
                side_effect=AssertionError("must not be called"),
            ):
                with mock.patch.object(sys, "argv", argv):
                    cli.main()
            symbols = set(pd.read_csv(out)["symbol"])
            self.assertIn("BITF", symbols)
            self.assertIn("NEW", symbols)


if __name__ == "__main__":
    unittest.main()
