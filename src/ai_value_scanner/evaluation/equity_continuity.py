"""Equity-continuity guard for historical return labels (research-only).

Problem: a forward label is only meaningful if the security at exit is the
same economic equity as at entry. Two failure modes were observed in the
2023-2026 pre-strategy extracts:

1. Splits with ex-dates past the corporate-action query end (fixed
   separately by ``split_query_end_iso``) printed as near-total losses
   (BKNG 25:1 -> fwd_ret_120 ≈ -0.97; KLAC 10:1 -> ≈ -0.88).
2. Cancellation-class events invisible to the actions feed (WOLF reverse
   splits absent from Alpaca corporate-actions since 2020): unadjusted
   reverse splits print as absurd multi-thousand-percent gains, and
   post-bankruptcy paths mix two different equities.

Detection uses the dataset's own monthly prints — raw ``price`` plus
``shares_outstanding`` — with market truth as arbiter. No new fetch, no
return-magnitude threshold on labels, no strategy content:

- Share ratios inside [0.5, 2.0] are normal drift (buybacks, ATM issuance,
  stock dividends) and never flag on their own.
- Split events with ex-dates inside (prev_date - 120d, cur_date] explain a
  share move when the observed ratio falls within [0.5x, 2x] of the
  event-implied ratio (shares scale as 1/price_mult; the lookback absorbs
  quarterly filing lag). Explained moves never flag. A known split also
  explains a same-window extreme RAW price move on flat shares (the share
  print simply hasn't caught up yet — NVDA class).
- An unexplained share COLLAPSE (ratio < 0.5) nulls spanning labels only
  with price corroboration: the raw-price ratio in the same pair must fall
  within [0.25x, 4x] of the inverse (1/ratio). Without it the cliff is an
  oscillating/unit artifact (HEI/MBLY/PKG/SKY class) and is audit-only.
- An extreme raw-price move (>= 5x or <= 0.2x) on flat shares with no event
  is a split hiding behind stale share prints (WOLF Sep-2025 class: price
  x23 while shares sat flat). It becomes a backdated discontinuity only
  when (a) the new price level persists into the next month ([0.2x, 5x]),
  ruling out one-month bad prints and crashed meme spikes, AND (b) an
  unexplained share collapse follows within 6 observations with
  order-of-magnitude consistency (0.1 <= r_share * r_price <= 10).
  Otherwise it stays audit-only.
- Unexplained share JUMPS (ratio > 2.0) are always audit-only: dilution
  does not break equity continuity, so spanning labels are kept.

Only records with ``null_labels=True`` null forward labels whose
(signal_date, label_end] spans the discontinuity date. Labels starting
at/after the cliff are kept as new-regime reality. Stale or non-positive
share prints, and missing prices, never corroborate and never flag.
"""

from __future__ import annotations

import math

import pandas as pd

NORMAL_RATIO_LO = 0.5
NORMAL_RATIO_HI = 2.0
EXPLAIN_TOL_LO = 0.5
EXPLAIN_TOL_HI = 2.0
# Filing-lag lookback for matching a split ex-date to delayed prints.
EVENT_LOOKBACK_DAYS = 120
# Extreme monthly raw-price move signalling a split behind stale prints.
PRICE_JUMP_RATIO = 5.0
# Persistence band for a jump's new price level (rejects bad prints that
# fully revert next month).
JUMP_CONFIRM_LO = 0.2
JUMP_CONFIRM_HI = 5.0
# Corroboration band around the inverse share move.
CORROB_TOL_LO = 0.25
CORROB_TOL_HI = 4.0
# Lookahead (observations) linking a jump to its later share catch-up print.
LINK_LOOKAHEAD = 6
LINK_CONSIST_LO = 0.1
LINK_CONSIST_HI = 10.0

FLAG_COL = "equity_discontinuity_flag"
REASON_COL = "equity_discontinuity_reason"


def _valid_pos(value: object) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _explained(ratio: float, prev_d: str, cur_d: str,
               events: list[tuple[str, float]]) -> float | None:
    """Event-implied share ratio if a matching split explains the move."""
    lag_start = (pd.Timestamp(prev_d, tz="UTC")
                 - pd.Timedelta(days=EVENT_LOOKBACK_DAYS)).date().isoformat()
    window = [(d, m) for d, m in events
              if lag_start < d <= cur_d and m is not None and m > 0]
    if not window:
        return None
    expected = 1.0
    for _, m in window:
        expected *= 1.0 / m
    if EXPLAIN_TOL_LO * expected <= ratio <= EXPLAIN_TOL_HI * expected:
        return expected
    return None


def detect_discontinuities(
    dates: list[str],
    shares: list[object],
    prices: list[object] | None,
    stale: list[bool] | None,
    split_events: list[tuple[str, float]] | None,
) -> list[dict]:
    """Return audit records for one symbol's monthly series (dates ascending).

    Records with ``null_labels=True`` must null spanning forward labels;
    the rest are audit-only disclosures.
    """
    events = sorted((str(d), float(m)) for d, m in (split_events or []) if d)
    n = len(dates)
    px = list(prices) if prices is not None else [None] * n

    def rec(i: int, reason: str, null: bool, expected: float | None,
            ratio: float, price_ratio: float | None) -> dict:
        return {
            "index": i,
            "prev_date": str(dates[i - 1]), "date": str(dates[i]),
            "prev_shares": _valid_pos(shares[i - 1]), "shares": _valid_pos(shares[i]),
            "ratio": ratio, "price_ratio": price_ratio,
            "expected_ratio": expected, "reason": reason, "null_labels": null,
        }

    pairs: list[dict] = []  # per-pair scratch: {ratio, price_ratio, explained, ...}
    out: list[dict] = []
    for i in range(1, n):
        info: dict = {"index": i, "candidate_jump": False}
        pairs.append(info)
        if stale is not None and (bool(stale[i - 1]) or bool(stale[i])):
            continue
        prev_s = _valid_pos(shares[i - 1])
        cur_s = _valid_pos(shares[i])
        if prev_s is None or cur_s is None:
            continue
        ratio = cur_s / prev_s
        prev_p = _valid_pos(px[i - 1])
        cur_p = _valid_pos(px[i])
        price_ratio = (cur_p / prev_p) if prev_p and cur_p else None
        info.update(ratio=ratio, price_ratio=price_ratio)
        prev_d, cur_d = str(dates[i - 1]), str(dates[i])
        expected = _explained(ratio, prev_d, cur_d, events)
        info["explained"] = expected is not None
        if expected is not None:
            continue
        if NORMAL_RATIO_LO <= ratio <= NORMAL_RATIO_HI:
            # Flat shares: an extreme raw-price move with no event in the lag
            # window is a split hiding behind stale prints — unless an event
            # anywhere in the lag window already accounts for price action.
            # (Share prints lag; the price jump itself is the timely witness.)
            if (price_ratio is not None
                    and (price_ratio >= PRICE_JUMP_RATIO
                         or price_ratio <= 1.0 / PRICE_JUMP_RATIO)):
                lag_start = (pd.Timestamp(prev_d, tz="UTC")
                             - pd.Timedelta(days=EVENT_LOOKBACK_DAYS)).date().isoformat()
                if not any(lag_start < d <= cur_d for d, _ in events):
                    info["candidate_jump"] = True
                    out.append(rec(i, "PRICE_JUMP_UNEXPLAINED_FLAT_SHARES",
                                   False, None, ratio, price_ratio))
            continue
        if ratio >= NORMAL_RATIO_LO:
            out.append(rec(i, "SHARE_JUMP_UNEXPLAINED", False, expected,
                           ratio, price_ratio))
            continue
        # Collapse: null only with price corroboration (a real cancellation
        # moves raw price by ~1/ratio in the same pair AND moves it
        # materially — a flat price beside a share cliff is a reporting
        # artifact, not a split).
        inverse = 1.0 / ratio
        corroborated = (
            price_ratio is not None
            and (price_ratio >= 1.5 or price_ratio <= 1.0 / 1.5)
            and CORROB_TOL_LO * inverse <= price_ratio <= CORROB_TOL_HI * inverse
        )
        out.append(rec(
            i,
            "SHARE_COLLAPSE_PRICE_CORROBORATED" if corroborated
            else "SHARE_CLIFF_PRICE_UNCORROBORATED",
            corroborated, expected, ratio, price_ratio))

    # Link pass: a persisted jump followed by a consistent unexplained share
    # collapse is one reorg-type event; backdate the discontinuity to the
    # jump month (the economically correct boundary).
    by_index = {p["index"]: p for p in pairs}
    for r in out:
        if r["reason"] != "PRICE_JUMP_UNEXPLAINED_FLAT_SHARES":
            continue
        i = r["index"]
        if i + 1 >= n:
            continue
        nxt_p = _valid_pos(px[i + 1])
        cur_p = _valid_pos(px[i])
        if nxt_p is None or cur_p is None:
            continue
        persist = nxt_p / cur_p
        if not (JUMP_CONFIRM_LO <= persist <= JUMP_CONFIRM_HI):
            r["reason"] = "PRICE_SPIKE_REVERTED"
            continue
        linked = False
        for j in range(i + 1, min(n, i + 1 + LINK_LOOKAHEAD)):
            pj = by_index.get(j)
            if pj is None or pj.get("explained") or "ratio" not in pj:
                continue
            rj = pj["ratio"]
            if rj is None or rj >= NORMAL_RATIO_LO:
                continue
            # Unexplained later collapse with order-of-magnitude consistency.
            if LINK_CONSIST_LO <= rj * (r["price_ratio"] or 0) <= LINK_CONSIST_HI:
                linked = True
                break
        if linked:
            r["reason"] = "REORG_JUMP_BACKDATED"
            r["null_labels"] = True
    for r in out:
        r.pop("index", None)
    return out


def _fallback_window_end(signal_date: str, horizon: int) -> str:
    dt = pd.Timestamp(signal_date, tz="UTC")
    days = int(math.ceil(max(1, int(horizon)) * 7.0 / 5.0)) + 10
    return (dt + pd.Timedelta(days=days)).date().isoformat()


def repair_labels(
    df: pd.DataFrame,
    splits_by_symbol: dict[str, list[tuple[str, float]]],
    horizons: tuple[int, ...] = (20, 60, 120),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Null labels spanning an equity discontinuity; return (patched, audit).

    Required columns: signal_date, symbol, shares_outstanding, price,
    fwd_ret_{h}, label_end_{h}. Optional: shares_stale. Adds FLAG_COL and
    REASON_COL (0/"" when untouched). Audit rows: one per detected record
    plus per-horizon nulled-label counts for its symbol.
    """
    df = df.copy()
    if FLAG_COL not in df.columns:
        df[FLAG_COL] = 0
    if REASON_COL not in df.columns:
        df[REASON_COL] = ""
    audit_rows: list[dict] = []
    has_stale = "shares_stale" in df.columns
    has_price = "price" in df.columns
    for symbol, g in df.groupby("symbol", sort=True):
        g = g.sort_values("signal_date")
        dates = g["signal_date"].astype(str).tolist()
        shares = g["shares_outstanding"].tolist()
        prices = g["price"].tolist() if has_price else None
        stale = (g["shares_stale"].fillna(False).astype(bool).tolist()
                 if has_stale else None)
        discs = detect_discontinuities(
            dates, shares, prices, stale, splits_by_symbol.get(str(symbol), []))
        for d in discs:
            nulled_here = {h: 0 for h in horizons}
            base = {
                "symbol": symbol, "prev_date": d["prev_date"], "date": d["date"],
                "prev_shares": d["prev_shares"], "shares": d["shares"],
                "ratio": d["ratio"], "price_ratio": d.get("price_ratio"),
                "expected_ratio": d["expected_ratio"],
                "reason": d["reason"], "null_labels": bool(d["null_labels"]),
            }
            if not d["null_labels"]:
                audit_rows.append(base | {f"nulled_h{h}": 0 for h in horizons})
                continue
            for h in horizons:
                fwd_col, end_col = f"fwd_ret_{h}", f"label_end_{h}"
                if fwd_col not in df.columns:
                    continue
                mask = (
                    (df["symbol"] == symbol)
                    & (df["signal_date"].astype(str) < d["date"])
                    & (df[fwd_col].notna())
                )
                if end_col in df.columns:
                    exit_iso = df[end_col].astype(str)
                    span = mask & (
                        (df[end_col].notna() & (exit_iso >= d["date"]))
                        | (df[end_col].isna() & (
                            df["signal_date"].astype(str).apply(
                                lambda s: _fallback_window_end(s, h)) >= d["date"]))
                    )
                else:
                    span = mask
                hit = df.index[span].tolist()
                for ix in hit:
                    df.at[ix, fwd_col] = float("nan")
                    if end_col in df.columns:
                        df.at[ix, end_col] = None
                    df.at[ix, FLAG_COL] = 1
                    prev_raw = df.at[ix, REASON_COL]
                    prev = "" if pd.isna(prev_raw) else str(prev_raw)
                    bits = [b for b in prev.split(";") if b] + [d["reason"]]
                    df.at[ix, REASON_COL] = ";".join(sorted(set(bits)))
                    nulled_here[h] += 1
            audit_rows.append(base | {f"nulled_h{h}": nulled_here[h] for h in horizons})
    audit = pd.DataFrame(audit_rows, columns=[
        "symbol", "prev_date", "date", "prev_shares", "shares", "ratio",
        "price_ratio", "expected_ratio", "reason", "null_labels",
        *[f"nulled_h{h}" for h in horizons],
    ])
    return df, audit
