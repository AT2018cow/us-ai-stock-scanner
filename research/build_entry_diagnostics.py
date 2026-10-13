"""Entry readiness diagnostics from frozen post-hoc decisions (research-only).

For each of the 11 business-model-study names × 3 dates, reports the Entry
state plus every unmet READY gate with evidence — including the silent band:
v1 emits NO evidence item for relative_strength_60d_qqq in [-10%, -3%),
yet the READY gate requires >= -3%. Those blockers are reconstructed here
as row return_60d minus the run-manifest QQQ trailing 60d (the exact inputs
the scorer saw), labelled SILENT_RS_BAND, so the diagnostic never claims
"gates all met" when the state proves otherwise.

Reads:  outputs/posthoc_62/<date>/{decisions.jsonl,manifest.json}
Writes: data/research/business_model_quality_v0/entry_readiness_diagnostics.csv
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

NAMES = ["JPM", "BAC", "GS", "MS", "AMT", "EQIX", "O", "PLD",
         "ABBV", "AAPL", "XOM"]
DATES = ("2026-09-30", "2026-10-05", "2026-10-09")
ROOT = Path("outputs/posthoc_62")
OUT = Path("data/research/business_model_quality_v0/entry_readiness_diagnostics.csv")


def _num(items: list[dict], code: str) -> float | None:
    for c in items:
        if c.get("code") == code:
            try:
                return float(c.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def main() -> None:
    rows = []
    for date in DATES:
        manifest = json.loads((ROOT / date / "manifest.json").read_text(encoding="utf-8"))
        qqq60 = manifest.get("qqq_trailing_60d")
        decs = [json.loads(line) for line in
                (ROOT / date / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        for symbol in NAMES:
            hit = [d for d in decs if d["symbol"] == symbol]
            if not hit:
                rows.append({"date": date, "symbol": symbol, "state": "ABSENT",
                             "action": "", "market_asof": "",
                             "unmet_ready_conditions": "no decision row",
                             "met_conditions": ""})
                continue
            d = hit[0]
            e = d["entry"]
            ev = list(e["positives"]) + list(e["risks"])
            unmet = [f"{c['code']}({c.get('metric')})={c.get('value')}" for c in e["risks"]]
            # Silent RS band: gate needs >= -3%, items exist only outside [-10%, -3%).
            ret60 = _num(ev, "return_60d_nonnegative") or _num(ev, "return_60d_weak")
            has_rs_item = any((c.get("metric") or "") == "relative_strength_60d_qqq" for c in ev)
            rs = (ret60 - qqq60) if ret60 is not None and qqq60 is not None else None
            if rs is not None and not has_rs_item and rs < -0.03:
                unmet.append(f"SILENT_RS_BAND(relative_strength_60d_qqq)={rs:.4f} "
                             f"(row_ret60={ret60:.4f} - qqq60={qqq60:.4f}; gate >= -3%; "
                             f"v1 emits no item in [-10%,-3%))")
            met = [f"{c['code']}({c.get('metric')})={c.get('value')}" for c in e["positives"][:6]]
            rows.append({"date": date, "symbol": symbol,
                         "quality": d["quality"]["grade"], "state": e["state"],
                         "action": d["action_state"], "market_asof": e["market_asof"],
                         "unmet_ready_conditions": " | ".join(unmet) if unmet else "NONE - all READY gates met",
                         "met_conditions": " | ".join(met)})
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"wrote {OUT} rows={len(rows)}")


if __name__ == "__main__":
    main()
