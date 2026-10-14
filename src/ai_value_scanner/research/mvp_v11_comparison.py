"""Date-paired historical Top-k comparator; library only, not a run CLI.

THIS IS NOT AUTHORIZATION TO RUN REAL CANDIDATE RETURNS. Only synthetic
unittests until owner signs a frozen risk-mask and comparator run contract.
Use unchanged, already net-of-30bps (stock and QQQ) v3 labels.
"""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

from ai_value_scanner.decision.model import StockDecision


HORIZONS = frozenset({20, 60, 120})
CAPS = frozenset({5, 15})


def _indexed(frame: pd.DataFrame, name: str, keys: list[str]) -> pd.DataFrame:
    if not set(keys).issubset(frame):
        raise ValueError(f"{name} missing {sorted(set(keys) - set(frame))}")
    if frame[keys].duplicated().any():
        raise ValueError(f"{name} duplicate {keys}")
    return frame.set_index(keys, verify_integrity=True)


def _top(decisions: Iterable[StockDecision], *, day: str, cap: int) -> tuple[StockDecision, ...]:
    decisions = tuple(decisions)
    if len(decisions) < cap:
        raise ValueError(f"insufficient decisions for Top-{cap}: {len(decisions)}")
    if len({(d.decision_date, d.symbol) for d in decisions}) != len(decisions):
        raise ValueError("duplicate decision date×symbol")
    if any(d.decision_date != day for d in decisions):
        raise ValueError("cross-date decisions")
    priorities = [d.priority for d in decisions]
    if len(priorities) != len(set(priorities)):
        raise ValueError("duplicate decision priorities")
    return tuple(sorted(decisions, key=lambda d: (d.priority, d.symbol))[:cap])


def paired_topk_day(
    *,
    signal_date: str,
    candidate_id: str,
    horizon: int,
    cap: int,
    baseline: Iterable[StockDecision],
    candidate: Iterable[StockDecision],
    labels: pd.DataFrame,
    event_flags: pd.DataFrame,
    score_flags: pd.DataFrame,
) -> dict[str, object]:
    """Compare same signal date on common Top-k label-complete denominator.

    Missing any selected label in EITHER arm masks the WHOLE date pair;
    event/score sensitivities further mask the whole date on EITHER arm,
    never selected names or outcomes based on future event information.
    """
    if horizon not in HORIZONS or cap not in CAPS:
        raise ValueError("only registered horizon and Top-5/15 allowed")
    b0, alt = (_top(baseline, day=signal_date, cap=cap),
               _top(candidate, day=signal_date, cap=cap))
    b0_symbols = tuple(d.symbol for d in b0)
    alt_symbols = tuple(d.symbol for d in alt)
    if len(set(b0_symbols)) != cap or len(set(alt_symbols)) != cap:
        raise ValueError("duplicate selected symbols")
    all_symbols = set(b0_symbols) | set(alt_symbols)

    stock_col, bench_col = f"fwd_ret_{horizon}", f"qqq_return_{horizon}"
    if not {stock_col, bench_col}.issubset(labels):
        raise ValueError("missing frozen net forward return columns")
    lkp = _indexed(labels, "labels", ["signal_date", "symbol"])
    events = _indexed(event_flags, "events", ["signal_date", "symbol", "horizon"])
    scores = _indexed(score_flags, "score risk", ["signal_date", "symbol"])
    if "event_interval_exposed" not in events or "score_source_uncertain" not in scores:
        raise ValueError("frozen event/score masks missing required flag")
    missing_label = []
    event_hit = []
    score_hit = []
    for sym in sorted(all_symbols):
        pair = (signal_date, sym)
        if pair not in lkp.index:
            raise ValueError(f"selected symbol missing frozen label row: {pair}")
        if (*pair, horizon) not in events.index or pair not in scores.index:
            raise ValueError(f"missing uncertainty mask for {pair}/{horizon}")
        flag_event = events.at[(*pair, horizon), "event_interval_exposed"]
        flag_score = scores.at[pair, "score_source_uncertain"]
        if pd.isna(flag_event) or pd.isna(flag_score):
            raise ValueError("null event/score uncertainty flags")
        # Allow only native/CSV boolean representations.
        for flag in (flag_event, flag_score):
            if str(flag).lower() not in {"true", "false"}:
                raise ValueError("non-boolean uncertainty flag")
        if str(flag_event).lower() == "true":
            event_hit.append(sym)
        if str(flag_score).lower() == "true":
            score_hit.append(sym)
        stock, qqq = pd.to_numeric(lkp.at[pair, stock_col], errors="coerce"), pd.to_numeric(
            lkp.at[pair, bench_col], errors="coerce"
        )
        if not (math.isfinite(float(stock)) and math.isfinite(float(qqq))):
            missing_label.append(sym)
    complete = not missing_label
    def excess(symbols: tuple[str, ...]) -> float:
        return sum(
            float(lkp.at[(signal_date, sym), stock_col]) -
            float(lkp.at[(signal_date, sym), bench_col])
            for sym in symbols
        ) / cap
    b0_return = excess(b0_symbols) if complete else None
    alt_return = excess(alt_symbols) if complete else None
    delta = alt_return - b0_return if complete else None

    return {
        "signal_date": signal_date,
        "candidate_id": candidate_id,
        "horizon": horizon,
        "cap": cap,
        "b0_symbols": ";".join(b0_symbols),
        "candidate_symbols": ";".join(alt_symbols),
        "n_topk_swaps": cap - len(set(b0_symbols) & set(alt_symbols)),
        "topk_overlap": len(set(b0_symbols) & set(alt_symbols)) / cap,
        "removed_symbols": ";".join(sorted(set(b0_symbols) - set(alt_symbols))),
        "added_symbols": ";".join(sorted(set(alt_symbols) - set(b0_symbols))),
        "n_entry_state_changed": sum(
            d.entry.state != {b.symbol: b for b in baseline}[d.symbol].entry.state
            for d in candidate if d.symbol in {b.symbol for b in baseline}
        ),
        "n_action_changed": sum(
            d.action_state != {b.symbol: b for b in baseline}[d.symbol].action_state
            for d in candidate if d.symbol in {b.symbol for b in baseline}
        ),
        "primary_paired_valid": complete,
        "missing_label_symbols": ";".join(missing_label),
        "b0_net_qqq_excess": b0_return,
        "candidate_net_qqq_excess": alt_return,
        "paired_delta_net_qqq_excess": delta,
        "event_sensitivity_valid": complete and not event_hit,
        "event_exposed_symbols": ";".join(event_hit),
        "score_sensitivity_valid": complete and not score_hit,
        "score_uncertain_symbols": ";".join(score_hit),
        "note": (
            "MONTHLY HISTORICAL ATTENTION PROXY. Net stock and QQQ each include "
            "source 30bps roundtrip; no second cost. "
            "No performance/alpha claim outside paired date aggregates."
        ),
    }
