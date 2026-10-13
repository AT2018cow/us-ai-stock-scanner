"""Entry-readiness diagnostics rebuild (no network, tmp fixtures).

Proves the SILENT-band reconstruction is deterministic and attributable:
a synthetic decision row with all gates evidenced-met but a sub-(-3%)
relative strength (computed from fixture return_60d minus fixture manifest
QQQ trailing) is labelled SILENT_RS_BAND, never NONE; a fully-met READY
row stays NONE; an explicitly-coded risk row keeps its code.
"""

from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

TMP = Path("/tmp/opencode/entry_diag_test")


def _write_fixture() -> None:
    TMP.mkdir(parents=True, exist_ok=True)

    def dec(symbol, state, ret60=None, rs_code=None, regime="up"):
        pos = [
            {"code": "price_above_sma200", "metric": "price_to_sma200", "value": 1.1},
            {"code": "price_near_sma50_ready_band", "metric": "price_to_sma50", "value": 1.0},
            {"code": "return_20d_ready_band", "metric": "return_20d", "value": 0.01},
            {"code": "supportive_market_regime", "metric": "regime", "value": regime},
        ]
        risks = []
        if ret60 is not None:
            if ret60 >= 0:
                pos.append({"code": "return_60d_nonnegative", "metric": "return_60d", "value": ret60})
            else:
                risks.append({"code": "return_60d_weak", "metric": "return_60d", "value": ret60})
        if rs_code is not None:
            risks.append({"code": rs_code, "metric": "relative_strength_60d_qqq", "value": -0.2})
        return {"symbol": symbol, "quality": {"grade": "A"},
                "entry": {"state": state, "market_asof": "2026-10-09",
                          "positives": pos, "risks": risks},
                "action_state": "HOLD_MONITOR"}

    rows = [
        dec("SILENT", "WATCH_BREAKOUT", ret60=0.01),       # RS = 0.01-0.0642 < -3%, no item
        dec("READYOK", "ENTRY_READY", ret60=0.05),          # placeholder, fixed below
        dec("CODED", "WATCH_BREAKOUT", ret60=-0.20,         # explicit weak codes
            rs_code="relative_strength_60d_qqq_weak"),
    ]
    # READYOK needs an RS positive to be genuinely met:
    rows[1]["entry"]["positives"].append(
        {"code": "relative_strength_60d_qqq_ready",
         "metric": "relative_strength_60d_qqq", "value": 0.01})
    day = TMP / "2026-10-09"
    day.mkdir(parents=True, exist_ok=True)
    (day / "decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (day / "manifest.json").write_text(
        json.dumps({"qqq_trailing_60d": 0.0642}), encoding="utf-8")


class EntryDiagnosticsTests(unittest.TestCase):
    def test_silent_band_reconstruction(self) -> None:
        import build_entry_diagnostics as builder
        _write_fixture()
        out = TMP / "entry_readiness_diagnostics.csv"
        root, dates, names = builder.ROOT, builder.DATES, builder.NAMES
        builder.ROOT = TMP
        builder.DATES = ("2026-10-09",)
        builder.NAMES = ["SILENT", "READYOK", "CODED"]
        builder.OUT = out
        try:
            builder.main()
        finally:
            builder.ROOT, builder.DATES, builder.NAMES = root, dates, names
        got = {r["symbol"]: r for r in csv.DictReader(out.open(encoding="utf-8"))}
        self.assertIn("SILENT_RS_BAND", got["SILENT"]["unmet_ready_conditions"])
        self.assertIn("-0.0542", got["SILENT"]["unmet_ready_conditions"])
        self.assertTrue(got["READYOK"]["unmet_ready_conditions"].startswith("NONE"))
        self.assertIn("return_60d_weak", got["CODED"]["unmet_ready_conditions"])


if __name__ == "__main__":
    unittest.main()
