from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_smallcap_universe.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_smallcap_universe", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load_module()


def _nasdaq_row(symbol="AMKR", industry="Semiconductors", cap=11868574587.0,
                volume=4140232.0, name="Amkor Technology Inc. Common Stock",
                country="United States", sector="Technology"):
    return {
        "symbol": symbol,
        "name": name,
        "country": country,
        "sector": sector,
        "industry": industry,
        "marketCap": f"{cap:.2f}",
        "volume": volume,
    }


class TestNasdaqFilter(unittest.TestCase):
    def test_keeps_amkr_like_row(self) -> None:
        rows = mod.filter_nasdaq_rows([_nasdaq_row()], 300_000_000.0, 15_000_000_000.0, 100_000.0)
        self.assertEqual([r["symbol"] for r in rows], ["AMKR"])
        self.assertEqual(rows[0]["source"], mod.SOURCE_NASDAQ)

    def test_drops_non_tech_wrong_industry_and_warrants(self) -> None:
        rows = mod.filter_nasdaq_rows(
            [
                _nasdaq_row("HEALTH", industry="Biotechnology: Pharmaceutical Preparations"),
                _nasdaq_row("INDUS", industry="Industrial Machinery/Components"),
                _nasdaq_row("WW", name="Whitehawk Therapeutics Inc. Common Stock Warrant"),
                _nasdaq_row("BIG", cap=50_000_000_000.0),
                _nasdaq_row("TINY", cap=10_000_000.0),
                _nasdaq_row("QUIET", volume=10.0),
                _nasdaq_row("FOREIGN", cap=1_000_000_000.0),
            ],
            300_000_000.0, 15_000_000_000.0, 100_000.0,
        )
        self.assertEqual(rows, [])

    def test_allows_power_vertical_across_sectors(self) -> None:
        rows = mod.filter_nasdaq_rows(
            [
                _nasdaq_row("TLN", industry="Electric Utilities: Central", cap=15_200_000_000.0),
                _nasdaq_row("PWRG", industry="Power Generation", cap=5_000_000_000.0),
            ],
            300_000_000.0, 80_000_000_000.0, 100_000.0,
        )
        self.assertEqual({r["symbol"] for r in rows}, {"TLN", "PWRG"})

    def test_foreign_semis_allowed_china_excluded(self) -> None:
        rows = mod.filter_nasdaq_rows(
            [
                _nasdaq_row("TEL", industry="Electronic Components", cap=60_000_000_000.0,
                            name="TE Connectivity plc Ordinary Shares", country="Ireland"),
                _nasdaq_row("CAMT", industry="Electronic Components", cap=6_000_000_000.0,
                            name="Camtek Ltd. Ordinary Shares", country="Israel"),
                _nasdaq_row("BIDU", industry="Computer Software: Programming Data Processing",
                            cap=30_000_000_000.0, name="Baidu Inc. American Depositary Shares",
                            country="China"),
            ],
            300_000_000.0, 80_000_000_000.0, 100_000.0,
        )
        self.assertEqual({r["symbol"] for r in rows}, {"TEL", "CAMT"})

    def test_taxonomy_outlier_still_excluded(self) -> None:
        # BE-like: Energy sector + Industrial Machinery industry is too broad
        # for rules; such names belong in the manual list.
        rows = mod.filter_nasdaq_rows(
            [_nasdaq_row("BE", industry="Industrial Machinery/Components", cap=74_000_000_000.0)],
            300_000_000.0, 80_000_000_000.0, 100_000.0,
        )
        self.assertEqual(rows, [])

    def test_allows_ai_software_industries(self) -> None:
        rows = mod.filter_nasdaq_rows(
            [
                _nasdaq_row("SOFT", industry="Computer Software: Prepackaged Software"),
                _nasdaq_row("DATA", industry="EDP Services"),
                _nasdaq_row("EQ", industry="Semiconductor Equipment & Materials"),
            ],
            300_000_000.0, 15_000_000_000.0, 100_000.0,
        )
        self.assertEqual({r["symbol"] for r in rows}, {"SOFT", "DATA", "EQ"})


class TestYahooFilter(unittest.TestCase):
    def _quote(self, symbol="SMCI", cap=20_000_000_000.0 / 2, exchange="NMS",
               quote_type="EQUITY", name="Super Micro Computer"):
        return {
            "symbol": symbol,
            "shortName": name,
            "quoteType": quote_type,
            "exchange": exchange,
            "marketCap": {"raw": cap},
            "regularMarketVolume": {"raw": 5_000_000},
        }

    def test_keeps_equity_in_cap_range(self) -> None:
        rows = mod.filter_yahoo_quotes([self._quote()], 300_000_000.0, 15_000_000_000.0)
        self.assertEqual([r["symbol"] for r in rows], ["SMCI"])
        self.assertEqual(rows[0]["source"], mod.SOURCE_YAHOO)

    def test_drops_bad_rows(self) -> None:
        rows = mod.filter_yahoo_quotes(
            [
                self._quote("BTC-USD", quote_type="CRYPTOCURRENCY"),
                self._quote("FOREIGN", exchange="LSE"),
                self._quote("FOO-W", name="Foo Warrant"),
                self._quote("MEGA", cap=500_000_000_000.0),
                self._quote("NANO", cap=5_000_000.0),
            ],
            300_000_000.0, 15_000_000_000.0,
        )
        self.assertEqual(rows, [])


class TestRestrictToNasdaq(unittest.TestCase):
    def test_yahoo_kept_only_if_in_nasdaq_universe(self) -> None:
        nasdaq = [
            {"symbol": "AMKR", "volume": 1.0, "source": mod.SOURCE_NASDAQ},
        ]
        yahoo = [
            {"symbol": "AMKR", "volume": 9.0, "source": mod.SOURCE_YAHOO},
            {"symbol": "OLLI", "volume": 8.0, "source": mod.SOURCE_YAHOO},
        ]
        kept = mod.restrict_to_nasdaq(yahoo, nasdaq)
        self.assertEqual([r["symbol"] for r in kept], ["AMKR"])


class TestMergeUniverse(unittest.TestCase):
    def test_manual_priority_and_source_merge(self) -> None:
        cands = [
            {"symbol": "AMKR", "volume": 0.0, "source": mod.SOURCE_MANUAL},
            {"symbol": "AMKR", "volume": 4_000_000.0, "source": mod.SOURCE_NASDAQ},
            {"symbol": "VIAV", "volume": 3_000_000.0, "source": mod.SOURCE_NASDAQ},
            {"symbol": "HOT", "volume": 9_000_000.0, "source": mod.SOURCE_YAHOO},
        ]
        df = mod.merge_universe(cands, set(), 10)
        self.assertEqual(set(df["symbol"]), {"AMKR", "VIAV", "HOT"})
        self.assertTrue((df["bucket"] == "ai_smallcap").all())
        self.assertTrue((df["etf_count"] == 0).all())
        amkr = df[df["symbol"] == "AMKR"].iloc[0]
        self.assertIn(mod.SOURCE_MANUAL, str(amkr["etfs"]))
        self.assertIn(mod.SOURCE_NASDAQ, str(amkr["etfs"]))

    def test_skips_existing_watchlist_symbols_and_caps_total(self) -> None:
        cands = [
            {"symbol": "NVDA", "volume": 1.0, "source": mod.SOURCE_NASDAQ},
            {"symbol": "A", "volume": 3.0, "source": mod.SOURCE_YAHOO},
            {"symbol": "B", "volume": 2.0, "source": mod.SOURCE_YAHOO},
        ]
        df = mod.merge_universe(cands, {"NVDA"}, 2)
        self.assertEqual(set(df["symbol"]), {"A", "B"})


class TestSrcTagsExcludedFromEtfCount(unittest.TestCase):
    def test_src_provenance_tags_do_not_inflate_etf_count(self) -> None:
        import pandas as pd

        from ai_value_scanner.scanner import watchlist_rows_to_scores

        raw = pd.DataFrame(
            [
                {"symbol": "AMKR", "bucket": "ai_smallcap", "etf_count": 0,
                 "etfs": "SRC:MANUAL,SRC:NASDAQ_SCREEN", "enabled": 1},
                {"symbol": "NVDA", "bucket": "core_ai", "etf_count": 3,
                 "etfs": "SMH,SOXX,SRC:YAHOO_HOT", "enabled": 1},
            ]
        )
        out = watchlist_rows_to_scores(raw)
        by_symbol = {r["symbol"]: r for r in out.to_dict("records")}
        self.assertEqual(by_symbol["AMKR"]["watchlist_etf_count"], 0)
        self.assertEqual(by_symbol["NVDA"]["watchlist_etf_count"], 2)
        self.assertIn("SRC:YAHOO_HOT", by_symbol["NVDA"]["watchlist_etfs"])


class TestSmallcapResearchTheme(unittest.TestCase):
    def _row(self, bucket: str) -> "pd.Series":
        import pandas as pd

        return pd.Series(
            {
                "symbol": "AMKR",
                "watchlist_bucket": bucket,
                "watchlist_etfs": "NASDAQ_SCREEN",
                "ai_link_score": 0.20,
                "fundamental_quality_score": 0.50,
                "revenue_yoy": 0.10,
                "net_income_yoy": 0.20,
                "return_20d": 0.0,
                "return_60d": 0.0,
                "ps_discount": 0.0,
                "pe_discount": 0.0,
                "fcf_yield": 0.01,
                "ev_to_ebit": 15.0,
                "pe": 15.0,
                "ps": 3.0,
            }
        )

    def test_smallcap_bucket_gets_infra_tag_not_avoid(self) -> None:
        from ai_value_scanner.scanner import build_research_assessment

        out = build_research_assessment(self._row("ai_smallcap"), "research_pool")
        self.assertIn("ai_infrastructure_exposure", out["research_tags"].split(","))
        self.assertEqual(out["research_priority"], "theme_only")

    def test_unknown_bucket_without_infra_is_avoid(self) -> None:
        from ai_value_scanner.scanner import build_research_assessment

        out = build_research_assessment(self._row("misc_bucket"), "research_pool")
        self.assertEqual(out["research_priority"], "avoid_for_now")


class TestManualCsv(unittest.TestCase):
    def test_manual_csv_contains_amkr(self) -> None:
        rows = mod.load_manual_symbols(REPO_ROOT / "data" / "ai_smallcap_manual.csv")
        symbols = {r["symbol"] for r in rows}
        self.assertIn("AMKR", symbols)
        self.assertGreaterEqual(len(symbols), 10)


if __name__ == "__main__":
    unittest.main()
