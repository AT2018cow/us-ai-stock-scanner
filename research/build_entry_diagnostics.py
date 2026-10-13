"""Entry readiness diagnostics from frozen post-hoc decisions (research-only).

For each of the 11 business-model-study names × 3 dates, reports the Entry
state plus every unmet READY gate with evidence. Two classes of blockers:

1. CODED blockers: entry risk items present in the frozen decision.
2. SILENT blockers: gates v1 evaluates but emits no item for —
   relative_strength_60d_qqq in [-10%, -3%) and return_60d in [-8%, 0%).
   These are reconstructed ONLY from frozen, hash-pinned inputs:
   - RS-silent: row return_60d (from a coded return_60d item in the SAME
     frozen decision) minus run-manifest QQQ trailing 60d.
   - ret60-silent: row return_60d absent from the decision; value taken
     from the committed frozen file silent_gate_inputs.csv (symbol, date,
     source, method pinned there; cache-mutable origin disclosed).

INVARIANT (review-blocking if violated): a non-READY state with an empty
unmet list is a reconstruction failure. Such rows are labelled
UNOBSERVABLE with the candidate silent gates enumerated — never "all
gates met". "NONE - all READY gates met" appears ONLY for ENTRY_READY.

Reads:  outputs/posthoc_62/<date>/{decisions.jsonl,manifest.json}
        data/research/business_model_quality_v0/silent_gate_inputs.csv
Writes: data/research/business_model_quality_v0/entry_readiness_diagnostics.csv
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

NAMES = ["JPM", "BAC", "GS", "MS", "AMT", "EQIX", "O", "PLD",
         "ABBV", "AAPL", "XOM"]
DATES = ("2026-09-30", "2026-10-05", "2026-10-09")
ROOT = Path("outputs/posthoc_62")
FROZEN_INPUTS = Path("data/research/business_model_quality_v0/silent_gate_inputs.csv")
OUT = Path("data/research/business_model_quality_v0/entry_readiness_diagnostics.csv")

CANDIDATE_SILENT_GATES = ("RS [-10%,-3%)", "ret60 [-8%,0%)",
                          "drawdown>22%", "sma50 (1.08,1.10]", "vol (un evidenced)")


def _num(items: list[dict], *codes: str) -> float | None:
    for c in items:
        if c.get("code") in codes:
            try:
                return float(c.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _load_frozen_inputs() -> dict[tuple[str, str, str], dict]:
    if not FROZEN_INPUTS.is_file():
        return {}
    out = {}
    for r in csv.DictReader(FROZEN_INPUTS.open(encoding="utf-8")):
        try:
            value = float(r["value"])
        except (KeyError, TypeError, ValueError):
            continue
        out[(r["symbol"], r["signal_date"] if "signal_date" in r else r.get("date", ""),
             r["field"])] = {"value": value, "source": r.get("source", ""),
                             "method": r.get("method", "")}
    return out


def main() -> None:
    frozen = _load_frozen_inputs()
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
            ret60 = _num(ev, "return_60d_nonnegative", "return_60d_weak")
            has_rs_item = any((c.get("metric") or "") == "relative_strength_60d_qqq" for c in ev)
            # RS-silent: row value + manifest QQQ (both frozen).
            rs = (ret60 - qqq60) if ret60 is not None and qqq60 is not None else None
            if rs is not None and not has_rs_item and rs < -0.03:
                unmet.append(f"SILENT_RS_BAND(relative_strength_60d_qqq)={rs:.4f} "
                             f"(row_ret60={ret60:.4f} - qqq60={qqq60:.4f}; gate >= -3%; "
                             f"v1 emits no item in [-10%,-3%))")
            # ret60-silent: row lacks the value; frozen committed inputs only.
            if ret60 is None:
                key = (symbol, date, "return_60d")
                if key in frozen:
                    v = frozen[key]["value"]
                    if -0.08 <= v < 0:
                        unmet.append(f"RET60_SILENT_BAND(return_60d)={v:.4f} "
                                     f"(frozen silent_gate_inputs.csv; gate >= 0%; "
                                     f"v1 emits no item in [-8%,0))")
            if not unmet and e["state"] != "ENTRY_READY":
                unmet.append("UNOBSERVABLE (no coded or reconstructible blocker; "
                             "candidate silent gates: "
                             + "; ".join(CANDIDATE_SILENT_GATES) + ")")
            met = [f"{c['code']}({c.get('metric')})={c.get('value')}" for c in e["positives"][:6]]
            rows.append({"date": date, "symbol": symbol,
                         "quality": d["quality"]["grade"], "state": e["state"],
                         "action": d["action_state"], "market_asof": e["market_asof"],
                         "unmet_ready_conditions": " | ".join(unmet) if unmet else "NONE - all READY gates met",
                         "met_conditions": " | ".join(met)})
    pd.DataFrame(rows).to_csv(OUT, index=False)
    n_unobs = sum(1 for r in rows if str(r["unmet_ready_conditions"]).startswith("UNOBSERVABLE"))
    n_none = sum(1 for r in rows if str(r["unmet_ready_conditions"]).startswith("NONE"))
    print(f"wrote {OUT} rows={len(rows)} UNOBSERVABLE={n_unobs} NONE={n_none}")
    bad = [r for r in rows if str(r["unmet_ready_conditions"]).startswith("NONE")
           and r["state"] != "ENTRY_READY"]
    if bad:
        raise SystemExit(f"INVARIANT VIOLATED: {len(bad)} non-READY rows claim NONE: {bad}")


if __name__ == "__main__":
    main()
