"""Entry-readiness diagnostics rebuild (no network, tmp fixtures).

Proves every unmet-condition class is reconstructible from frozen inputs:
explicit codes, RS-silent (row ret60 + manifest QQQ), ret60-silent (row
lacks the value; committed frozen inputs file), and the UNOBSERVABLE
fallback (SMA50-slice / missing-metrics rows) which must never read NONE.
"""

from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

TMP = Path("/tmp/opencode/entry_diag_test")


def _dec(symbol, state, positives, risks):
    return {"symbol": symbol, "quality": {"grade": "A"},
            "entry": {"state": state, "market_asof": "2026-10-09",
                      "positives": positives, "risks": risks},
            "action_state": "HOLD_MONITOR"}


def _pos(code, metric, value):
    return {"code": code, "metric": metric, "value": value}


_BASE_POS = [
    ("price_above_sma200", "price_to_sma200", 1.1),
    ("price_near_sma50_ready_band", "price_to_sma50", 1.0),
    ("supportive_market_regime", "regime", "up"),
]


def _write_fixture(rows, frozen_inputs):
    day = TMP / "2026-10-09"
    day.mkdir(parents=True, exist_ok=True)
    (day / "decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (day / "manifest.json").write_text(
        json.dumps({"qqq_trailing_60d": 0.0642}), encoding="utf-8")
    with (TMP / "silent_gate_inputs.csv").open("w", newline="",
                                               encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol", "signal_date", "field",
                                           "value", "source", "method"])
        w.writeheader()
        w.writerows(frozen_inputs)


def _run_case(rows, frozen_inputs):
    import build_entry_diagnostics as builder
    _write_fixture(rows, frozen_inputs)
    out = TMP / "entry_readiness_diagnostics.csv"
    saved = (builder.ROOT, builder.DATES, builder.NAMES, builder.OUT,
             builder.FROZEN_INPUTS)
    builder.ROOT = TMP
    builder.DATES = ("2026-10-09",)
    builder.NAMES = [r["symbol"] for r in rows]
    builder.OUT = out
    builder.FROZEN_INPUTS = TMP / "silent_gate_inputs.csv"
    try:
        builder.main()
    finally:
        (builder.ROOT, builder.DATES, builder.NAMES, builder.OUT,
         builder.FROZEN_INPUTS) = saved
    return {r["symbol"]: r["unmet_ready_conditions"]
            for r in csv.DictReader(out.open(encoding="utf-8"))}


class EntryDiagnosticsTests(unittest.TestCase):
    def test_rs_silent_band_reconstructed(self) -> None:
        pos = [_pos(*t) for t in _BASE_POS] + [
            _pos("return_20d_ready_band", "return_20d", 0.01),
            _pos("return_60d_nonnegative", "return_60d", 0.01)]
        got = _run_case([_dec("S", "WATCH_BREAKOUT", pos, [])], [])
        # RS = 0.01 - 0.0642 = -0.0542, no RS item anywhere.
        self.assertIn("SILENT_RS_BAND", got["S"])
        self.assertIn("-0.0542", got["S"])

    def test_ret60_silent_band_from_frozen_inputs(self) -> None:
        # return_60d = -0.009 lives in NO evidence item (v1 silent band);
        # the committed frozen file supplies it.
        pos = [_pos(*t) for t in _BASE_POS] + [
            _pos("return_20d_ready_band", "return_20d", 0.01)]
        frozen = [{"symbol": "R", "signal_date": "2026-10-09",
                   "field": "return_60d", "value": "-0.009",
                   "source": "unit-test", "method": "fixture"}]
        got = _run_case([_dec("R", "WATCH_BREAKOUT", pos, [])], frozen)
        self.assertIn("RET60_SILENT_BAND", got["R"])
        self.assertIn("-0.0090", got["R"])
        self.assertIn("silent_gate_inputs.csv", got["R"])

    def test_sma50_slice_without_value_is_unobservable(self) -> None:
        # Every evidenced gate met (incl. RS + ret60 positives) yet state is
        # BREAKOUT: the blocker can only be an unevidenced gate such as the
        # sma50 (1.08,1.10] slice or drawdown — values absent everywhere.
        pos = [_pos(*t) for t in _BASE_POS] + [
            _pos("return_20d_ready_band", "return_20d", 0.01),
            _pos("return_60d_nonnegative", "return_60d", 0.05),
            _pos("relative_strength_60d_qqq_ready",
                 "relative_strength_60d_qqq", 0.01)]
        got = _run_case([_dec("M", "WATCH_BREAKOUT", pos, [])], [])
        self.assertTrue(got["M"].startswith("UNOBSERVABLE"))
        self.assertNotIn("NONE", got["M"])

    def test_missing_metrics_row_is_unobservable(self) -> None:
        pos = [_pos(*t) for t in _BASE_POS]
        got = _run_case([_dec("E", "WATCH_BREAKOUT", pos, [])], [])
        self.assertTrue(got["E"].startswith("UNOBSERVABLE"))

    def test_ready_row_with_met_gates_stays_none(self) -> None:
        pos = [_pos(*t) for t in _BASE_POS] + [
            _pos("return_20d_ready_band", "return_20d", 0.01),
            _pos("return_60d_nonnegative", "return_60d", 0.05),
            _pos("relative_strength_60d_qqq_ready",
                 "relative_strength_60d_qqq", 0.01)]
        got = _run_case([_dec("G", "ENTRY_READY", pos, [])], [])
        self.assertTrue(got["G"].startswith("NONE"))

    def test_coded_risk_kept_verbatim(self) -> None:
        pos = [_pos(*t) for t in _BASE_POS]
        risks = [_pos("return_60d_weak", "return_60d", -0.20)]
        risks[0]["code"] = "return_60d_weak"
        got = _run_case([_dec("C", "WATCH_BREAKOUT", pos, risks)], [])
        self.assertIn("return_60d_weak", got["C"])


if __name__ == "__main__":
    unittest.main()
