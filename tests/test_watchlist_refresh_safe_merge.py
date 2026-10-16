"""Watchlist refresh safe-merge protection tests.

Covers ``merge_refreshed_watchlist`` (SRC:MANUAL / ai_smallcap / enabled=0
preservation, overlap merge, additive vs prune), the refresh CLI
network-failure guard and ``--dry-run``, LF-only CSV output, and
``build_smallcap_universe.py`` SRC:MANUAL preservation. Pure offline mocks;
no network calls.
"""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import pandas as pd

from ai_value_scanner.scanner import (
    WATCHLIST_CSV_COLUMNS,
    fetch_stockanalysis_etf_symbols,
    merge_refreshed_watchlist,
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


if __name__ == "__main__":
    unittest.main()
