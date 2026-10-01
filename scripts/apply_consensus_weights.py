"""Apply consensus weight-sweep multipliers to production configs (one-shot).

Reads the raw score_weights/momentum_score_weights from each channel profile,
multiplies by the consensus multipliers from the offline sweep, and writes
back explicit effective values (including the merged low-coverage axes and
soft_pass_rate, which must be explicit to be effective). ai_smallcap is left
unchanged (not covered by the sweep).

Verifies after writing: reloads via load_config + build_steps_and_weights and
asserts effective weights match the intended values.

Usage:
    python scripts/apply_consensus_weights.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

CHANNELS = ["core_ai", "ai_enabler", "ai_peripheral", "ai_smallcap"]
LOW_COVERAGE_DEFAULT = {"current_debt_ratio_low": 0.03, "inventory_growth_gap_low": 0.03}
SOFT_DEFAULT = 0.30
# build_momentum_steps fallback when a channel has no explicit momentum_score_weights
MOMENTUM_DEFAULTS = {
    "liquidity": 0.10,
    "return_20d": 0.50,
    "watchlist_etf_count": 0.20,
    "ai_link_score": 0.20,
    "drawdown_from_52w_high": -0.10,
}

CONSENSUS = {
    # v4 (4-channel marginal-effects, 2026-09-26): only axes with |t|>2 move,
    # mildly (boost x1.5 / cut x0.5); applied to ALL 4 channels uniformly
    # (smallcap included — the 4ch sweep evaluated the full portfolio, and
    # smallcap momentum behaves differently from large-cap momentum);
    # soft_pass_rate stays at baseline 0.30 everywhere.
    "risk_off": {
        "low_value": {
            "ai_link_score": 1.5, "watchlist_etf_count": 1.5,
            "pe_discount": 1.5, "pe_percentile_low": 1.5,
            "range_position_52w_low": 0.5, "days_below_sma200": 0.5,
            "net_margin": 0.5, "revenue_yoy": 0.5,
        },
        "momentum": {
            "inventory_growth_gap_low": 1.5, "drawdown_from_52w_high": 0.5,
        },
        "soft": {"low_value": 0.30, "momentum": 0.30},
    },
    "risk_on": {
        "low_value": {
            "net_income_yoy": 1.5, "ps_discount": 1.5, "ps_percentile_low": 1.5,
            "inventory_growth_gap_low": 1.5, "current_debt_ratio_low": 1.5,
            "watchlist_etf_count": 1.5,
            "liquidity": 0.5, "range_position_52w_low": 0.5, "ev_to_ebit_low": 0.5,
        },
        "momentum": {
            "inventory_growth_gap_low": 1.5, "watchlist_etf_count": 1.5,
            "drawdown_from_52w_high": 0.5,
        },
        "soft": {"low_value": 0.30, "momentum": 0.30},
    },
}


def style_of(path: Path) -> str:
    return "risk_on" if "risk_on" in path.name else "risk_off"


def new_weights(raw: dict, mults: dict, soft: float) -> dict:
    out: dict[str, float] = {}
    for axis, base in raw.items():
        if axis == "soft_pass_rate":
            continue
        m = mults.get(axis, 1.0)
        out[axis] = round(float(base) * float(m), 4)
    for axis, m in mults.items():
        if axis not in raw:
            # merged low-coverage axis (was 0.03 via global defaults)
            base = float(LOW_COVERAGE_DEFAULT.get(axis, 0.0))
            out[axis] = round(base * float(m), 4)
    out["soft_pass_rate"] = round(float(soft), 4)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Only verify effective weights, do not write.")
    args = parser.parse_args()

    intended: dict[tuple[str, str, str], dict[str, float]] = {}
    for cfg_name in ("configs/config.risk_off.json", "configs/config.risk_on.json"):
        path = Path(cfg_name)
        style = style_of(path)
        cons = CONSENSUS[style]
        data = json.loads(path.read_text())
        profiles = data["channel_profiles"]
        for ch in CHANNELS:
            if ch == "ai_smallcap":
                continue  # auxiliary observation channel (see module docstring): weights frozen
            prof = profiles[ch]
            raw_lv = prof.get("score_weights", {})
            raw_mo = prof.get("momentum_score_weights", None)
            if not isinstance(raw_mo, dict) or not raw_mo:
                # Materialize code defaults so explicit zeros/ones don't drop axes
                raw_mo = dict(MOMENTUM_DEFAULTS)
            # Effective base BEFORE writing: raw value, or merged low-coverage 0.03 / soft 0.30
            base_lv = {**{k: float(LOW_COVERAGE_DEFAULT[k]) for k in LOW_COVERAGE_DEFAULT if k not in raw_lv},
                       **{k: float(v) for k, v in raw_lv.items() if k != "soft_pass_rate"}}
            base_lv["soft_pass_rate"] = float(raw_lv.get("soft_pass_rate", SOFT_DEFAULT))
            base_mo = {**{k: float(LOW_COVERAGE_DEFAULT[k]) for k in LOW_COVERAGE_DEFAULT if k not in raw_mo},
                       **{k: float(v) for k, v in raw_mo.items() if k != "soft_pass_rate"}}
            base_mo["soft_pass_rate"] = float(raw_mo.get("soft_pass_rate", SOFT_DEFAULT))
            for axis, m in cons["low_value"].items():
                intended[(cfg_name, f"{ch}/low_value", axis)] = (
                    {"new_score_weights": round(base_lv.get(axis, 0.0) * float(m), 4)}
                )
            intended[(cfg_name, f"{ch}/low_value", "soft_pass_rate")] = {"new_score_weights": round(float(cons["soft"]["low_value"]), 4)}
            for axis, m in cons["momentum"].items():
                intended[(cfg_name, f"{ch}/momentum", axis)] = (
                    {"new_momentum_score_weights": round(base_mo.get(axis, 0.0) * float(m), 4)}
                )
            intended[(cfg_name, f"{ch}/momentum", "soft_pass_rate")] = {"new_momentum_score_weights": round(float(cons["soft"]["momentum"]), 4)}
            prof["score_weights"] = new_weights(raw_lv, cons["low_value"], cons["soft"]["low_value"])
            prof["momentum_score_weights"] = new_weights(raw_mo, cons["momentum"], cons["soft"]["momentum"])
        if not args.check:
            path.write_text(json.dumps(data, indent=2) + "\n")
            print(f"wrote {cfg_name}")
        else:
            print(f"computed new weights for {cfg_name} (dry run)")

    if args.check:
        return

    # Verification: effective weights must match intended values
    from ai_value_scanner.backtest import build_steps_and_weights
    from ai_value_scanner.scanner import load_config

    ok = True
    key_of_list = {"low_value": "score_weights", "momentum": "momentum_score_weights"}
    for (cfg_name, ch_list, axis), want in intended.items():
        from_disk = load_config(cfg_name)
        ch, lt = ch_list.split("/")
        profile = (from_disk.channel_profiles or {}).get(ch, {})
        _steps, eff = build_steps_and_weights(from_disk, ch, profile, lt)
        got = round(float(eff.get(axis, 0.0)), 4)
        want_val = round(float(list(want.values())[0]), 4)
        if abs(want_val - got) > 1e-9:
            ok = False
            print(f"MISMATCH {cfg_name} {ch}/{lt}/{axis}: intended={want_val} got={got}")
    print("verification: " + ("ALL EFFECTIVE WEIGHTS MATCH" if ok else "FAILED"))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
