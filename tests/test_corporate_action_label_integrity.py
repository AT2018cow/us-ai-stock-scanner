"""Corporate-action label integrity: split-window coverage + continuity guard.

Regression coverage for the BKNG/KLAC/WOLF audit (2026-10-11):
- split_query_end_iso must cover every forward label end (the 2026-03-31
  query cap corrupted all labels crossing later splits).
- A 25:1 split inside a holding window must not print as a near-total loss
  once known (BKNG class); reverse splits must adjust symmetrically.
- Unexplained share-count cliffs (WOLF 156M -> 25.9M) null spanning labels;
  explained moves (matching split event) and ordinary issuance never flag.
All synthetic, deterministic, no network.
"""

from __future__ import annotations

import unittest

import pandas as pd

from ai_value_scanner.backtest import apply_split_adjustment_to_frame
from ai_value_scanner.evaluation.backtest import (
    fetch_split_events_or_raise,
    forward_return_with_exit,
    split_query_end_iso,
)
from ai_value_scanner.evaluation.equity_continuity import (
    detect_discontinuities,
    repair_labels,
)


def _frame(dates: list[str], closes: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(dates, utc=True))
    return pd.DataFrame({
        "open": list(closes), "close": list(closes),
        "high": [c * 1.01 for c in closes], "low": [c * 0.99 for c in closes],
        "volume": [1_000_000.0] * len(closes),
    }, index=idx)


def _daily_dates(start: str, n: int) -> list[str]:
    return [(pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(n)]


def _label_frame(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=[
        "signal_date", "symbol", "price", "shares_outstanding", "shares_stale",
        "fwd_ret_20", "label_end_20", "fwd_ret_60", "label_end_60",
        "fwd_ret_120", "label_end_120",
    ])


class SplitQueryEndTests(unittest.TestCase):
    def test_covers_longest_label_end(self) -> None:        # The exact production case: 2026-03-31 window + 120d labels end
        # 2026-09-22; the query end must not precede any label end.
        self.assertEqual(split_query_end_iso("2026-03-31", [20, 60, 120]), "2026-09-25")
        self.assertGreaterEqual(split_query_end_iso("2026-03-31", [20, 60, 120]), "2026-09-22")

    def test_empty_horizons_fall_back_to_120(self) -> None:
        self.assertEqual(split_query_end_iso("2026-03-31", []), "2026-09-25")

    def test_short_horizons_shrink_envelope(self) -> None:
        short = split_query_end_iso("2026-03-31", [20])
        long = split_query_end_iso("2026-03-31", [20, 60, 120])
        self.assertLess(short, long)


class SplitInsideHoldingWindowTests(unittest.TestCase):
    def test_bkng_class_forward_split_once_known(self) -> None:
        # 25:1 split (mult 0.04) mid-window; flat economics.
        dates = _daily_dates("2026-01-05", 200)
        closes = [2500.0] * 100 + [100.0] * 100
        raw = _frame(dates, closes)
        # Old behavior: split unknown (truncated query) -> near-total loss.
        bad, _ = forward_return_with_exit(raw, "2026-02-01", 120, 0.003)
        self.assertIsNotNone(bad)
        assert bad is not None
        self.assertLess(bad, -0.9)
        # Fixed behavior: known split adjusts pre-split rows -> ~ -cost.
        adj = apply_split_adjustment_to_frame(raw, [("2026-04-15", 0.04)])
        good, exit_dt = forward_return_with_exit(adj, "2026-02-01", 120, 0.003)
        self.assertIsNotNone(good)
        assert good is not None
        self.assertAlmostEqual(good, -0.003, places=6)
        self.assertIsNotNone(exit_dt)

    def test_reverse_split_adjusts_symmetrically(self) -> None:
        dates = _daily_dates("2026-01-05", 200)
        closes = [3.0] * 100 + [30.0] * 100  # 1:10 reverse at session 100
        raw = _frame(dates, closes)
        bad, _ = forward_return_with_exit(raw, "2026-02-01", 120, 0.003)
        self.assertIsNotNone(bad)
        assert bad is not None
        self.assertGreater(bad, 5.0)  # unadjusted reverse split prints a windfall
        adj = apply_split_adjustment_to_frame(raw, [("2026-04-15", 10.0)])
        good, _ = forward_return_with_exit(adj, "2026-02-01", 120, 0.003)
        assert good is not None
        self.assertAlmostEqual(good, -0.003, places=6)


class EquityContinuityTests(unittest.TestCase):
    def test_wolf_class_jump_backdated_and_spanning_nulled(self) -> None:
        # Real WOLF prints: Sep-2025 price x23 on flat shares (reverse split
        # behind stale prints), Nov-2025 share catch-up collapse. The jump
        # month is the economic boundary; spanning labels are nulled.
        df = _label_frame([
            ("2025-08-29", "WOLF", 1.24, 156_471_999.0, False, 0.05, "2025-09-26", 0.10, "2025-11-21", 14.17, "2026-02-23"),
            ("2025-09-30", "WOLF", 28.95, 156_471_999.0, False, 0.02, "2025-10-28", -0.10, "2025-12-24", -0.40, "2026-03-24"),
            ("2025-10-31", "WOLF", 26.25, 156_471_999.0, False, -0.16, "2025-11-28", -0.34, "2026-01-26", 0.12, "2026-04-27"),
            ("2025-11-28", "WOLF", 20.365, 25_892_446.0, False, -0.18, "2025-12-26", -0.05, "2026-02-23", 2.26, "2026-05-22"),
            ("2025-12-31", "WOLF", 17.38, 25_892_446.0, False, -0.12, "2026-01-29", -0.17, "2026-03-26", 1.67, "2026-06-25"),
        ])
        patched, audit = repair_labels(df, {"WOLF": []})
        reasons = set(audit["reason"].tolist())
        self.assertIn("REORG_JUMP_BACKDATED", reasons)
        # +14.17 label spanning Sep is nulled + flagged ...
        r0 = patched.iloc[0]
        self.assertTrue(pd.isna(r0["fwd_ret_120"]))
        self.assertIsNone(r0["label_end_120"])
        self.assertTrue(pd.isna(r0["fwd_ret_60"]))
        self.assertEqual(r0["equity_discontinuity_flag"], 1)
        self.assertIn("REORG_JUMP_BACKDATED", str(r0["equity_discontinuity_reason"]))
        # ... the 20d label ending before Sep is kept ...
        self.assertAlmostEqual(patched.iloc[0]["fwd_ret_20"], 0.05)
        # ... rows at/after the jump month are new-regime reality.
        self.assertAlmostEqual(patched.iloc[1]["fwd_ret_120"], -0.40)
        self.assertEqual(patched.iloc[1]["equity_discontinuity_flag"], 0)
        self.assertAlmostEqual(patched.iloc[4]["fwd_ret_120"], 1.67)

    def test_collapse_with_price_corroboration_nulls(self) -> None:
        # ARQQ class: 14x share collapse with a matching ~14x raw-price jump
        # in the same pair -> real cancellation event missing from the feed.
        df = _label_frame([
            ("2024-11-29", "ARQQ", 2.0, 100_000_000.0, False, 0.01, "2024-12-27", 0.02, "2025-02-26", 0.03, "2025-05-23"),
            ("2024-12-31", "ARQQ", 28.0, 7_059_036.0, False, 0.01, "2025-01-29", 0.02, "2025-03-27", 0.03, "2025-06-25"),
            ("2025-01-31", "ARQQ", 27.0, 7_059_036.0, False, 0.01, "2025-02-26", 0.02, "2025-04-29", 0.03, "2025-07-24"),
        ])
        patched, audit = repair_labels(df, {"ARQQ": []})
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.iloc[0]["reason"], "SHARE_COLLAPSE_PRICE_CORROBORATED")
        self.assertTrue(bool(audit.iloc[0]["null_labels"]))
        self.assertTrue(pd.isna(patched.iloc[0]["fwd_ret_120"]))
        self.assertEqual(patched.iloc[0]["equity_discontinuity_flag"], 1)
        self.assertAlmostEqual(patched.iloc[1]["fwd_ret_120"], 0.03)

    def test_collapse_without_corroboration_is_audit_only(self) -> None:
        # PKG class: 1000x share prints with a flat price -> unit artifact,
        # not a real split. Disclosed, labels kept.
        df = _label_frame([
            ("2024-06-28", "PKG", 200.0, 90_000_000.0, False, 0.01, "2024-07-26", 0.02, "2024-09-25", 0.03, "2024-12-20"),
            ("2024-07-31", "PKG", 201.0, 90_010_000.0, False, 0.01, "2024-08-29", 0.02, "2024-10-29", 0.03, "2024-12-24"),
            ("2024-08-30", "PKG", 199.0, 90_010.0, False, 0.01, "2024-09-27", 0.02, "2024-11-27", 0.03, "2025-02-21"),
            ("2024-09-30", "PKG", 202.0, 90_010.0, False, 0.01, "2024-10-29", 0.02, "2024-12-30", 0.03, "2025-03-25"),
        ])
        patched, audit = repair_labels(df, {"PKG": []})
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.iloc[0]["reason"], "SHARE_CLIFF_PRICE_UNCORROBORATED")
        self.assertFalse(bool(audit.iloc[0]["null_labels"]))
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)

    def test_spike_revert_never_nulls(self) -> None:
        # Meme class: 6x month that crashes back next month, no later
        # collapse -> genuine volatility, labels kept.
        df = _label_frame([
            ("2025-06-30", "MEME", 10.0, 50_000_000.0, False, 0.01, "2025-07-29", 0.02, "2025-09-26", 5.00, "2025-12-19"),
            ("2025-07-31", "MEME", 60.0, 50_000_000.0, False, 0.01, "2025-08-29", 0.02, "2025-10-29", 0.03, "2026-01-22"),
            ("2025-08-29", "MEME", 6.0, 50_000_000.0, False, 0.01, "2025-09-26", 0.02, "2025-11-25", 0.03, "2026-02-20"),
            ("2025-09-30", "MEME", 6.5, 50_000_000.0, False, 0.01, "2025-10-29", 0.02, "2025-12-30", 0.03, "2026-03-25"),
        ])
        patched, audit = repair_labels(df, {"MEME": []})
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)
        self.assertAlmostEqual(patched.iloc[0]["fwd_ret_120"], 5.00)
        if len(audit):
            self.assertFalse(bool(audit["null_labels"].any()))

    def test_explained_move_never_flags(self) -> None:
        df = _label_frame([
            ("2026-03-31", "BKNG", 4209.0, 10_000_000.0, False, 0.01, "2026-04-28", 0.02, "2026-06-25", 0.03, "2026-09-22"),
            ("2026-04-30", "BKNG", 170.0, 250_000_000.0, False, 0.01, "2026-05-28", 0.02, "2026-07-24", 0.03, "2026-10-20"),
        ])
        patched, audit = repair_labels(df, {"BKNG": [("2026-04-06", 0.04)]})
        self.assertEqual(len(audit), 0)
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)

    def test_ordinary_issuance_and_stale_never_flag(self) -> None:
        df = _label_frame([
            ("2025-01-31", "DIL", 10.0, 100_000_000.0, False, 0.01, "2025-02-28", 0.02, "2025-04-28", 0.03, "2025-07-25"),
            ("2025-02-28", "DIL", 10.5, 180_000_000.0, False, 0.01, "2025-03-28", 0.02, "2025-05-27", 0.03, "2025-08-21"),
            ("2025-03-31", "STALE", 11.0, 100_000_000.0, True, 0.01, "2025-04-28", 0.02, "2025-06-26", 0.03, "2025-09-22"),
            ("2025-04-30", "STALE", 11.5, 1_000_000.0, False, 0.01, "2025-05-28", 0.02, "2025-07-25", 0.03, "2025-10-21"),
        ])
        patched, audit = repair_labels(df, {})
        self.assertEqual(len(audit), 0)
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)

    def test_detect_marks_expected_ratio_when_partially_explained(self) -> None:
        discs = detect_discontinuities(
            ["2026-03-31", "2026-04-30"], [10_000_000.0, 250_000_000.0],
            [4209.0, 170.0], [False, False], [("2026-04-06", 0.04)])
        self.assertEqual(discs, [])
        discs = detect_discontinuities(
            ["2025-10-31", "2025-11-28"], [156_471_999.0, 25_892_446.0],
            [26.25, 20.365], [False, False], [])
        self.assertEqual(len(discs), 1)
        self.assertEqual(discs[0]["reason"], "SHARE_CLIFF_PRICE_UNCORROBORATED")
        self.assertFalse(discs[0]["null_labels"])

    def test_jump_is_audit_only_never_nulled(self) -> None:
        # LAES class: 1e5x unexplained jump (units/ATM chaos). Dilution does
        # not break continuity: disclosed, labels kept.
        df = _label_frame([
            ("2024-02-29", "LAES", 1.0, 1_000_000.0, False, 0.01, "2024-03-28", -0.50, "2024-05-28", -0.92, "2024-08-26"),
            ("2024-03-29", "LAES", 1.1, 154_468_100.0, False, 0.02, "2024-04-26", 0.03, "2024-06-27", 0.04, "2024-09-24"),
            ("2024-04-30", "LAES", 1.2, 154_468_100.0, False, 0.02, "2024-05-29", 0.03, "2024-07-30", 0.04, "2024-10-22"),
        ])
        patched, audit = repair_labels(df, {"LAES": []})
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.iloc[0]["reason"], "SHARE_JUMP_UNEXPLAINED")
        self.assertFalse(bool(audit.iloc[0]["null_labels"]))
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)
        self.assertAlmostEqual(patched.iloc[0]["fwd_ret_120"], -0.92)

    def test_oscillating_prints_without_price_move_stay_audit_only(self) -> None:
        # HEI class: alternating 0.4x/2.5x share-class prints on a flat
        # price -> unit artifact, labels kept.
        df = _label_frame([
            ("2024-04-30", "HEI", 300.0, 100_000_000.0, False, 0.01, "2024-05-29", 0.02, "2024-07-30", 0.03, "2024-10-22"),
            ("2024-05-31", "HEI", 301.0, 39_654_290.0, False, 0.01, "2024-06-28", 0.02, "2024-08-29", 0.03, "2024-11-20"),
            ("2024-06-28", "HEI", 299.0, 100_000_000.0, False, 0.01, "2024-07-26", 0.02, "2024-09-26", 0.03, "2024-12-19"),
            ("2024-07-31", "HEI", 302.0, 100_000_000.0, False, 0.01, "2024-08-29", 0.02, "2024-10-30", 0.03, "2024-12-24"),
        ])
        patched, audit = repair_labels(df, {"HEI": []})
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)
        if len(audit):
            self.assertFalse(bool(audit["null_labels"].any()))

    def test_filing_lag_event_explains_delayed_share_print(self) -> None:
        # MOVE class: 1:15 reverse ex-date sits just before the pair window
        # (quarterly filing lag). 120d lookback still matches it.
        discs = detect_discontinuities(
            ["2024-10-31", "2024-11-29"], [1_000_000_000.0, 67_040_050.0],
            [5.0, 70.0], [False, False], [("2024-10-29", 15.0)])
        self.assertEqual(discs, [])
        df = _label_frame([
            ("2024-10-31", "MOVE", 5.0, 1_000_000_000.0, False, 0.01, "2024-11-29", 0.02, "2025-01-30", 0.03, "2025-04-24"),
            ("2024-11-29", "MOVE", 70.0, 67_040_050.0, False, 0.01, "2024-12-27", 0.02, "2025-02-26", 0.03, "2025-05-23"),
        ])
        patched, audit = repair_labels(df, {"MOVE": [("2024-10-29", 15.0)]})
        self.assertEqual(len(audit), 0)
        self.assertEqual(int(patched["equity_discontinuity_flag"].sum()), 0)


class FailClosedSplitFetchTests(unittest.TestCase):
    def test_fetch_failure_raises_instead_of_silent_unadjusted(self) -> None:
        class _Down:
            def get_corporate_action_splits(self, *a: object, **k: object) -> object:
                raise ConnectionError("endpoint down")

        with self.assertRaises(RuntimeError) as ctx:
            fetch_split_events_or_raise(_Down(), ["BKNG"], "2021-11-07", "2026-09-25")
        self.assertIn("refusing to emit unadjusted", str(ctx.exception))

    def test_fetch_success_passes_extended_window_through(self) -> None:
        seen: dict = {}

        class _Up:
            def get_corporate_action_splits(self, symbols: object,
                                            start: object, end: object) -> object:
                seen.update(symbols=symbols, start=start, end=end)
                return {"BKNG": [("2026-04-06", 0.04)]}

        out = fetch_split_events_or_raise(_Up(), ["BKNG"], "2021-11-07", "2026-09-25")
        self.assertEqual(out, {"BKNG": [("2026-04-06", 0.04)]})
        self.assertEqual(seen["end"], "2026-09-25")

    def test_empty_response_returns_empty_dict(self) -> None:
        class _Empty:
            def get_corporate_action_splits(self, *a: object, **k: object) -> object:
                return {}

        self.assertEqual(fetch_split_events_or_raise(_Empty(), ["X"], "2021-11-07", "2026-09-25"), {})


if __name__ == "__main__":
    unittest.main()
