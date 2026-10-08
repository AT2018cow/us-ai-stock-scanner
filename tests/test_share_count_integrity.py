from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

import ai_value_scanner.backtest as backtest
import ai_value_scanner.scanner as scanner
from ai_value_scanner.fundamentals.facts import FactRecord, VisibilityCutoff
from ai_value_scanner.fundamentals.shares import assess_share_count_integrity


def fact(
    *,
    tag: str,
    unit: str,
    value: float,
    end: str,
    filed: str,
    start: str | None = None,
    accession: str = "0001",
    form: str = "10-Q",
) -> FactRecord:
    return FactRecord(
        tag=tag,
        unit=unit,
        value=value,
        period_end=date.fromisoformat(end),
        period_start=date.fromisoformat(start) if start else None,
        filed=date.fromisoformat(filed),
        accession=accession,
        form=form,
    )


def _fundamental(raw: dict[str, list[FactRecord]]) -> backtest.FundamentalPointInTime:
    return backtest.FundamentalPointInTime(
        sic="1234",
        sic_description="Test",
        revenue_series=[],
        net_income_series=[],
        shares_series=[],
        operating_cash_flow_series=[],
        capex_series=[],
        ebit_series=[],
        cash_series=[],
        long_term_debt_series=[],
        current_debt_series=[],
        current_assets_series=[],
        current_liabilities_series=[],
        receivables_series=[],
        inventory_series=[],
        interest_expense_series=[],
        da_series=[],
        backlog_series=[],
        disclosure_series=[],
        ai_disclosure_score=0.0,
        ai_backlog_signal=0.0,
        fact_records=raw,
    )


def _bars(asof: pd.Timestamp) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "date": asof,
                "open": 10.0,
                "close": 10.0,
                "high": 11.0,
                "low": 9.0,
                "volume": 1_000_000.0,
            }
        ]
    ).set_index("date")
    frame["sma200"] = float("nan")
    return frame


def _cross_section(
    raw: dict[str, list[FactRecord]],
    asof: pd.Timestamp,
) -> pd.DataFrame:
    universe = pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "name": "Test",
                "exchange": "NASDAQ",
                "company_name": "Test",
            }
        ]
    )
    return backtest.build_cross_section_asof(
        asof=asof,
        universe=universe,
        bar_db={"TEST": _bars(asof)},
        fundamentals={"TEST": _fundamental(raw)},
        theme_scores={},
        watchlist_by_symbol={"TEST": ("", 0, "")},
        benchmark_return_20d=None,
        benchmark_return_60d=None,
        disclosure_lookback_days=720,
        scan_config=scanner.ScanConfig(price_lookback_days=30),
    )


class TestShareCountIntegrityCore(unittest.TestCase):
    def test_reconciles_thousands_unit_from_eps_and_net_income(self) -> None:
        share = fact(
            tag="CommonStocksIncludingAdditionalPaidInCapital",
            unit="shares",
            value=179_000.0,
            end="2025-03-31",
            filed="2025-05-01",
        )
        eps = fact(
            tag="EarningsPerShareBasic",
            unit="USD/shares",
            value=1.0,
            end="2025-03-31",
            filed="2025-05-01",
        )
        net_income = fact(
            tag="NetIncomeLoss",
            unit="USD",
            value=179_000_000.0,
            start="2025-01-01",
            end="2025-03-31",
            filed="2025-05-01",
        )
        result = assess_share_count_integrity(
            share_records=[share],
            eps_records=[eps],
            net_income_records=[net_income],
            metric_record_groups=([net_income],),
        )
        self.assertEqual(result.value, 179_000_000.0)
        self.assertEqual(result.scale_factor, 1_000.0)
        self.assertEqual(result.period_end, date(2025, 3, 31))
        self.assertFalse(result.stale)

    def test_reconciles_millions_unit(self) -> None:
        share = fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=179.0,
            end="2025-03-31",
            filed="2025-05-01",
        )
        eps = fact(
            tag="EarningsPerShareBasic",
            unit="USD/shares",
            value=1.0,
            end="2025-03-31",
            filed="2025-05-01",
        )
        net_income = fact(
            tag="NetIncomeLoss",
            unit="USD",
            value=179_000_000.0,
            start="2025-01-01",
            end="2025-03-31",
            filed="2025-05-01",
        )
        result = assess_share_count_integrity(
            share_records=[share],
            eps_records=[eps],
            net_income_records=[net_income],
            metric_record_groups=([net_income],),
        )
        self.assertEqual(result.value, 179_000_000.0)
        self.assertEqual(result.scale_factor, 1_000_000.0)

    def test_stale_boundary_is_strictly_greater_than_400_days(self) -> None:
        share = fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=100.0,
            end="2024-01-01",
            filed="2024-02-01",
        )
        metric_400 = fact(
            tag="Revenues",
            unit="USD",
            value=1.0,
            start="2025-01-01",
            end="2025-02-04",
            filed="2025-03-01",
        )
        metric_401 = fact(
            tag="Revenues",
            unit="USD",
            value=1.0,
            start="2025-01-01",
            end="2025-02-05",
            filed="2025-03-01",
        )
        fresh = assess_share_count_integrity(
            share_records=[share],
            eps_records=[],
            net_income_records=[],
            metric_record_groups=([metric_400],),
        )
        stale = assess_share_count_integrity(
            share_records=[share],
            eps_records=[],
            net_income_records=[],
            metric_record_groups=([metric_401],),
        )
        self.assertFalse(fresh.stale)
        self.assertEqual(fresh.value, 100.0)
        self.assertTrue(stale.stale)
        self.assertIsNone(stale.value)

    def test_future_metric_filing_cannot_make_shares_stale_early(self) -> None:
        share = fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=100.0,
            end="2024-01-01",
            filed="2024-02-01",
        )
        later_metric = fact(
            tag="Revenues",
            unit="USD",
            value=1.0,
            start="2025-01-01",
            end="2025-06-30",
            filed="2025-08-01",
        )
        before = assess_share_count_integrity(
            share_records=[share],
            eps_records=[],
            net_income_records=[],
            metric_record_groups=([later_metric],),
            cutoff=VisibilityCutoff(date(2025, 7, 31)),
        )
        after = assess_share_count_integrity(
            share_records=[share],
            eps_records=[],
            net_income_records=[],
            metric_record_groups=([later_metric],),
            cutoff=VisibilityCutoff(date(2025, 8, 1)),
        )
        self.assertFalse(before.stale)
        self.assertEqual(before.value, 100.0)
        self.assertTrue(after.stale)
        self.assertIsNone(after.value)


class TestReplayShareIntegrityIntegration(unittest.TestCase):
    def test_replay_scales_current_shares_before_market_cap(self) -> None:
        asof = pd.Timestamp("2025-05-02", tz="UTC")
        share = fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=179_000.0,
            end="2025-03-31",
            filed="2025-05-01",
        )
        eps = fact(
            tag="EarningsPerShareBasic",
            unit="USD/shares",
            value=1.0,
            end="2025-03-31",
            filed="2025-05-01",
        )
        net_income = fact(
            tag="NetIncomeLoss",
            unit="USD",
            value=179_000_000.0,
            start="2025-01-01",
            end="2025-03-31",
            filed="2025-05-01",
        )
        revenue = fact(
            tag="Revenues",
            unit="USD",
            value=1_000_000_000.0,
            start="2025-01-01",
            end="2025-03-31",
            filed="2025-05-01",
        )
        out = _cross_section(
            {
                "shares": [share],
                "eps": [eps],
                "net_income": [net_income],
                "revenue": [revenue],
            },
            asof,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(float(out.iloc[0]["shares_outstanding"]), 179_000_000.0)
        self.assertEqual(float(out.iloc[0]["market_cap"]), 1_790_000_000.0)
        self.assertFalse(bool(out.iloc[0]["shares_stale"]))
        self.assertEqual(out.iloc[0]["shares_asof_end"], "2025-03-31")

    def test_replay_nulls_stale_shares_at_historical_asof(self) -> None:
        asof = pd.Timestamp("2025-09-01", tz="UTC")
        share = fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=100_000_000.0,
            end="2024-01-01",
            filed="2024-02-01",
        )
        revenue = fact(
            tag="Revenues",
            unit="USD",
            value=1_000_000_000.0,
            start="2025-01-01",
            end="2025-06-30",
            filed="2025-08-01",
        )
        out = _cross_section(
            {
                "shares": [share],
                "eps": [],
                "net_income": [],
                "revenue": [revenue],
            },
            asof,
        )
        self.assertEqual(len(out), 1)
        self.assertTrue(pd.isna(out.iloc[0]["shares_outstanding"]))
        self.assertTrue(pd.isna(out.iloc[0]["market_cap"]))
        self.assertTrue(bool(out.iloc[0]["shares_stale"]))
        self.assertEqual(out.iloc[0]["shares_asof_end"], "2024-01-01")


if __name__ == "__main__":
    unittest.main()
