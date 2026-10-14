"""M1 correctness: share-scope separation + entry silent-gate completeness.

Track B only. No reporting/view_model/config changes.
"""
from __future__ import annotations

import unittest
from datetime import date

from ai_value_scanner.decision.entry import (
    _entry_score_and_confidence,
    build_entry_quality_v1,
    build_entry_quality_v11_offline,
)
from ai_value_scanner.decision.model import EntryState
from ai_value_scanner.fundamentals.facts import FactRecord
from ai_value_scanner.fundamentals.reconstruction import (
    latest_and_year_ago_level as consistent_latest_and_year_ago_level,
)
from ai_value_scanner.fundamentals.shares import (
    POINT_IN_TIME_SHARES_TAGS,
    WEIGHTED_AVERAGE_SHARES_TAGS,
    ShareCountIntegrity,
    assess_share_count_integrity,
    select_consistent_share_records,
)


def _fact(
    *,
    tag: str,
    unit: str,
    value: float,
    end: str,
    filed: str,
    start: str | None = None,
    accession: str = "0000000001",
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


def _hei_share_records() -> list[FactRecord]:
    """HEI archetype: 10-Q single-class PIT shares mixed with a later-filed
    10-K two-class weighted-average count."""
    return [
        _fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=55_054_000.0,
            end="2025-07-31",
            filed="2025-09-05",
            form="10-Q",
            accession="0000000001",
        ),
        _fact(
            tag="EntityCommonStockSharesOutstanding",
            unit="shares",
            value=54_800_000.0,
            end="2024-07-31",
            filed="2024-09-05",
            form="10-Q",
            accession="0000000002",
        ),
        _fact(
            tag="WeightedAverageNumberOfSharesOutstandingBasic",
            unit="shares",
            value=139_048_000.0,
            end="2025-10-31",
            filed="2025-12-15",
            form="10-K",
            accession="0000000003",
        ),
    ]


def _hei_metric_groups() -> tuple[list[FactRecord], list[FactRecord]]:
    revenue = [
        _fact(
            tag="Revenues",
            unit="USD",
            value=1_000_000_000.0,
            start="2025-08-01",
            end="2025-10-31",
            filed="2025-12-15",
            form="10-K",
            accession="0000000003",
        ),
    ]
    net_income = [
        _fact(
            tag="NetIncomeLoss",
            unit="USD",
            value=500_000_000.0,
            start="2025-08-01",
            end="2025-10-31",
            filed="2025-12-15",
            form="10-K",
            accession="0000000003",
        ),
    ]
    return revenue, net_income


def _ready_entry_metrics(**overrides) -> dict[str, object]:
    metrics: dict[str, object] = {
        "price_to_sma200": 1.05,
        "price_to_sma50": 1.03,
        "days_below_sma200": 0,
        "return_20d": 0.05,
        "return_60d": 0.10,
        "drawdown_from_52w_high": 0.08,
        "range_position_52w": 0.82,
        "relative_strength_60d_qqq": 0.04,
        "volatility_60d": 0.35,
        "regime": "up",
        "benchmark_trend_ok": True,
        "market_asof": "2026-10-09",
    }
    metrics.update(overrides)
    return metrics


def _risk_codes(decision) -> set[str]:
    return {item.code for item in decision.risks}


class TestShareScopeConstants(unittest.TestCase):
    def test_tag_partition_and_backward_compat_concat(self) -> None:
        import ai_value_scanner.scanner as scanner

        self.assertEqual(
            POINT_IN_TIME_SHARES_TAGS,
            (
                "EntityCommonStockSharesOutstanding",
                "CommonStockSharesOutstanding",
            ),
        )
        self.assertEqual(
            WEIGHTED_AVERAGE_SHARES_TAGS,
            (
                "WeightedAverageNumberOfSharesOutstandingBasic",
                "WeightedAverageNumberOfDilutedSharesOutstanding",
            ),
        )
        self.assertEqual(
            list(scanner.SHARES_TAGS),
            [
                *POINT_IN_TIME_SHARES_TAGS,
                *WEIGHTED_AVERAGE_SHARES_TAGS,
            ],
        )

    def test_integrity_defaults_are_backward_compatible(self) -> None:
        integrity = ShareCountIntegrity(
            value=None,
            period_end=None,
            stale=False,
            scale_factor=1.0,
            latest_metric_end=None,
        )
        self.assertEqual(integrity.basis, "missing")
        self.assertIsNone(integrity.source_tag)


class TestHeiShareScopeRegression(unittest.TestCase):
    def test_select_prefers_point_in_time_over_later_weighted_average(self) -> None:
        revenue, net_income = _hei_metric_groups()
        selected, basis = select_consistent_share_records(
            _hei_share_records(),
            metric_record_groups=(revenue, net_income),
        )
        self.assertEqual(basis, "point_in_time_outstanding")
        self.assertTrue(selected)
        self.assertTrue(
            all(
                record.tag == "EntityCommonStockSharesOutstanding"
                for record in selected
            )
        )

    def test_assess_returns_pit_count_with_provenance(self) -> None:
        revenue, net_income = _hei_metric_groups()
        # EPS/NI imply ~2.5x the PIT count (dual-class total vs single-class
        # price series) and must NEVER trigger the 1,000x/1,000,000x scaler.
        eps = [
            _fact(
                tag="EarningsPerShareBasic",
                unit="USD/shares",
                value=2.50,
                start="2025-05-01",
                end="2025-07-31",
                filed="2025-09-05",
                form="10-Q",
            )
        ]
        period_ni = [
            _fact(
                tag="NetIncomeLoss",
                unit="USD",
                value=2.50 * 139_048_000.0,
                start="2025-05-01",
                end="2025-07-31",
                filed="2025-09-05",
                form="10-Q",
            )
        ]
        result = assess_share_count_integrity(
            share_records=_hei_share_records(),
            eps_records=eps,
            net_income_records=period_ni,
            metric_record_groups=(revenue, net_income),
        )
        self.assertEqual(result.value, 55_054_000.0)
        self.assertEqual(result.scale_factor, 1.0)
        self.assertEqual(result.period_end, date(2025, 7, 31))
        self.assertFalse(result.stale)
        self.assertEqual(result.basis, "point_in_time_outstanding")
        self.assertEqual(result.source_tag, "EntityCommonStockSharesOutstanding")

    def test_yoy_uses_same_consistent_basis(self) -> None:
        revenue, net_income = _hei_metric_groups()
        selected, _ = select_consistent_share_records(
            _hei_share_records(),
            metric_record_groups=(revenue, net_income),
        )
        latest, prev = consistent_latest_and_year_ago_level(selected)
        self.assertEqual(latest, 55_054_000.0)
        self.assertEqual(prev, 54_800_000.0)


class TestWeightedAverageFallback(unittest.TestCase):
    def test_wa_only_falls_back_cleanly(self) -> None:
        wa = [
            _fact(
                tag="WeightedAverageNumberOfSharesOutstandingBasic",
                unit="shares",
                value=3_580_000_000.0,
                end="2026-06-30",
                filed="2026-07-23",
                form="10-Q",
            )
        ]
        revenue = [
            _fact(
                tag="Revenues",
                unit="USD",
                value=1_000_000_000.0,
                start="2026-04-01",
                end="2026-06-30",
                filed="2026-07-23",
                form="10-Q",
            )
        ]
        selected, basis = select_consistent_share_records(
            wa, metric_record_groups=(revenue,)
        )
        self.assertEqual(basis, "weighted_average_fallback")
        self.assertEqual(len(selected), 1)
        result = assess_share_count_integrity(
            share_records=wa,
            eps_records=[],
            net_income_records=[],
            metric_record_groups=(revenue,),
        )
        self.assertEqual(result.value, 3_580_000_000.0)
        self.assertEqual(result.basis, "weighted_average_fallback")
        self.assertEqual(
            result.source_tag, "WeightedAverageNumberOfSharesOutstandingBasic"
        )
        self.assertFalse(result.stale)

    def test_empty_records_are_missing(self) -> None:
        selected, basis = select_consistent_share_records([])
        self.assertEqual(selected, [])
        self.assertEqual(basis, "missing")
        result = assess_share_count_integrity(
            share_records=[],
            eps_records=[],
            net_income_records=[],
            metric_record_groups=(),
        )
        self.assertIsNone(result.value)
        self.assertEqual(result.basis, "missing")
        self.assertIsNone(result.source_tag)


class TestScannerShareProvenanceWiring(unittest.TestCase):
    def test_load_one_fundamental_records_consistent_basis(self) -> None:
        import ai_value_scanner.scanner as scanner

        class _FakeSecClient:
            def get_submissions(self, cik: str) -> dict[str, object]:
                return {"sic": "3721", "sicDescription": "Aircraft And Parts"}

            def get_companyfacts(self, cik: str) -> dict[str, object]:
                def entry(end: str, val: float, form: str, filed: str) -> dict[str, object]:
                    return {
                        "end": end,
                        "val": val,
                        "filed": filed,
                        "accn": f"acc-{end}",
                        "form": form,
                    }

                return {
                    "facts": {
                        "us-gaap": {
                            "EntityCommonStockSharesOutstanding": {
                                "units": {
                                    "shares": [
                                        entry("2025-07-31", 55_054_000.0, "10-Q", "2025-09-05"),
                                        entry("2024-07-31", 54_800_000.0, "10-Q", "2024-09-05"),
                                    ]
                                }
                            },
                            "WeightedAverageNumberOfSharesOutstandingBasic": {
                                "units": {
                                    "shares": [
                                        entry("2025-10-31", 139_048_000.0, "10-K", "2025-12-15"),
                                    ]
                                }
                            },
                            "Revenues": {
                                "units": {
                                    "USD": [
                                        {
                                            "start": "2025-08-01",
                                            "end": "2025-10-31",
                                            "val": 1_000_000_000.0,
                                            "filed": "2025-12-15",
                                            "accn": "acc-rev",
                                            "form": "10-K",
                                        }
                                    ]
                                }
                            },
                            "NetIncomeLoss": {
                                "units": {
                                    "USD": [
                                        {
                                            "start": "2025-08-01",
                                            "end": "2025-10-31",
                                            "val": 500_000_000.0,
                                            "filed": "2025-12-15",
                                            "accn": "acc-ni",
                                            "form": "10-K",
                                        }
                                    ]
                                }
                            },
                        }
                    }
                }

        out = scanner.load_one_fundamental(
            _FakeSecClient(),  # type: ignore[arg-type]
            "HEI",
            "0000000001",
            scanner.ScanConfig(),
        )
        self.assertEqual(out["shares_outstanding"], 55_054_000.0)
        self.assertEqual(out["share_count_basis"], "point_in_time_outstanding")
        self.assertEqual(out["share_count_tag"], "EntityCommonStockSharesOutstanding")
        self.assertAlmostEqual(
            float(out["shares_yoy"]), 55_054_000.0 / 54_800_000.0 - 1.0, places=9
        )


class TestEntrySilentGates(unittest.TestCase):
    def test_pg_archetype_rs_below_ready_is_explicit(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(relative_strength_60d_qqq=-0.045),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)
        self.assertIn(
            "relative_strength_60d_qqq_below_ready", _risk_codes(decision)
        )

    def test_txn_archetype_ret60_and_rs_are_explicit(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(
                return_60d=-0.02, relative_strength_60d_qqq=-0.05
            ),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)
        codes = _risk_codes(decision)
        self.assertIn("return_60d_slightly_negative", codes)
        self.assertIn("relative_strength_60d_qqq_below_ready", codes)

    def test_crm_archetype_ret20_outside_band_is_explicit(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(return_20d=0.135),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)
        self.assertIn("return_20d_outside_ready_band", _risk_codes(decision))

    def test_crm_archetype_deep_drawdown_is_explicit(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(drawdown_from_52w_high=0.25),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)
        self.assertIn("drawdown_from_52w_high_deep", _risk_codes(decision))

    def test_sma200_mild_band_is_explicit(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(price_to_sma200=0.97),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)
        self.assertIn("price_below_sma200_trend", _risk_codes(decision))

    def test_sma50_near_miss_band_is_explicit(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(price_to_sma50=0.975),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.WATCH_BREAKOUT)
        self.assertIn(
            "price_to_sma50_outside_ready_band", _risk_codes(decision)
        )

    def test_isrg_archetype_days_below_is_explicit_alongside_extension(self) -> None:
        decision = build_entry_quality_v1(
            _ready_entry_metrics(
                days_below_sma200=18,
                price_to_sma50=1.104,
                return_60d=0.239,
                relative_strength_60d_qqq=0.166,
            ),
            decision_date="2026-10-10",
        )
        self.assertIs(decision.state, EntryState.TREND_DAMAGED)
        codes = _risk_codes(decision)
        self.assertIn("days_below_sma200_elevated", codes)
        self.assertIn("price_extended_above_sma50", codes)

    def test_non_ready_states_always_carry_at_least_one_risk(self) -> None:
        cases = [
            _ready_entry_metrics(relative_strength_60d_qqq=-0.045),
            _ready_entry_metrics(return_60d=-0.02),
            _ready_entry_metrics(return_20d=0.135),
            _ready_entry_metrics(drawdown_from_52w_high=0.25),
            _ready_entry_metrics(price_to_sma200=0.97),
            _ready_entry_metrics(price_to_sma50=1.09),
            _ready_entry_metrics(
                days_below_sma200=18,
                price_to_sma50=1.104,
                return_60d=0.239,
            ),
            _ready_entry_metrics(price_to_sma200=0.90),
            _ready_entry_metrics(return_20d=0.20),
        ]
        for metrics in cases:
            with self.subTest(metrics=metrics):
                decision = build_entry_quality_v1(
                    metrics, decision_date="2026-10-10"
                )
                self.assertIn(
                    decision.state,
                    (EntryState.WATCH_BREAKOUT, EntryState.TREND_DAMAGED,
                     EntryState.WATCH_PULLBACK),
                )
                if decision.state in (
                    EntryState.WATCH_BREAKOUT,
                    EntryState.TREND_DAMAGED,
                ):
                    self.assertGreaterEqual(len(decision.risks), 1)


class TestEntryStateScoreParity(unittest.TestCase):
    def test_score_confidence_match_pure_scorer_across_all_states(self) -> None:
        grid = [
            (_ready_entry_metrics(), EntryState.ENTRY_READY),
            (
                _ready_entry_metrics(return_20d=0.20),
                EntryState.WATCH_PULLBACK,
            ),
            (
                _ready_entry_metrics(relative_strength_60d_qqq=-0.045),
                EntryState.WATCH_BREAKOUT,
            ),
            (
                _ready_entry_metrics(price_to_sma200=0.90),
                EntryState.TREND_DAMAGED,
            ),
            (
                _ready_entry_metrics(price_to_sma50=None),
                EntryState.INSUFFICIENT_DATA,
            ),
        ]
        for metrics, expected_state in grid:
            with self.subTest(expected_state=expected_state):
                decision = build_entry_quality_v1(
                    metrics, decision_date="2026-10-10"
                )
                self.assertIs(decision.state, expected_state)
                expected_score, _ = _entry_score_and_confidence(metrics)
                self.assertEqual(decision.score, expected_score)

    def test_v1_and_v11_offline_default_grid_agree(self) -> None:
        grid = [
            _ready_entry_metrics(),
            _ready_entry_metrics(relative_strength_60d_qqq=-0.045),
            _ready_entry_metrics(return_60d=-0.02),
            _ready_entry_metrics(return_20d=0.135),
            _ready_entry_metrics(price_to_sma200=0.97),
            _ready_entry_metrics(days_below_sma200=18, price_to_sma50=1.104),
        ]
        for metrics in grid:
            with self.subTest(metrics=metrics):
                v1 = build_entry_quality_v1(metrics, decision_date="2026-10-10")
                offline = build_entry_quality_v11_offline(
                    metrics,
                    decision_date="2026-10-10",
                    market_asof=None,
                    ready_rs60_min=-0.03,
                    overextended_return20_gt=0.15,
                )
                self.assertEqual(v1, offline)


if __name__ == "__main__":
    unittest.main()
