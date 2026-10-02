"""Generate an actionable trade plan from the latest two-style observation scan.

Reads the most recent risk_off + risk_on scan artifacts (ranked low_value +
momentum CSVs), the live QQQ breaker state, and produces:

- outputs/trade_plan_<UTC>.csv  (machine-readable positions)
- outputs/trade_plan_<UTC>.md   (human-readable plan with risk rules)

Position model (see docs/live_pilot_protocol.md):
- Two sleeves: risk_on (default 60% capital) + risk_off (40%).
- Each sleeve: union of low_value keeps (full weight) + momentum picks
  (full weight) + low_value watches (half weight), equal-weighted within
  sleeve, capped at --max-position-pct of TOTAL capital.
- Holding horizon: 120 trading days per cohort (the horizon with the
  strongest verified signal, cross-sectional IC t=3~7).
- Entry: next market open. Stops: -25% per position (rule, priced at entry).

Usage:
    .venv/bin/python scripts/generate_trade_plan.py --capital 100000
    .venv/bin/python scripts/generate_trade_plan.py --capital 250000 --risk-on-alloc 0.6
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import load_config  # noqa: E402
from ai_value_scanner.backtest import build_bar_db, load_alpaca_client, load_sec_client, NetworkMonitor  # noqa: E402


def predict_earnings_window(reports: pd.DataFrame, today: pd.Timestamp, buffer_days: int = 7) -> dict:
    """Pure earnings-window prediction from periodic filings.

    reports: DataFrame with form/filed/period columns (datetimes), any order.
    Uses form-aware lags: the NEXT window is predicted with the annual lag
    when the next report is the annual filing (10-K/20-F/40-F), because a
    blended median (~35d) systematically closes the window ~5 weeks before a
    real 10-K lands (~70d) — the gate would clear right into earnings.
    """
    ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
    # Mirror legacy scope (most recent 8 filings): filing-lag regimes drift.
    reps = reports.sort_values("period", ascending=False).head(8).reset_index(drop=True)
    if reps.empty:
        return {"status": "unknown"}
    reps = reps.copy()
    reps["lag"] = (reps["filed"] - reps["period"]).dt.days
    latest = reps.iloc[0]
    q_lags = reps.loc[~reps["form"].isin(ANNUAL_FORMS), "lag"]
    a_lags = reps.loc[reps["form"].isin(ANNUAL_FORMS), "lag"]
    q_lag = int(q_lags.median()) if len(q_lags) else int(reps["lag"].median())
    # Annual filings take ~5 weeks longer; without annual history, assume so.
    a_lag = int(a_lags.median()) if len(a_lags) else q_lag + 35
    annual_periods = reps.loc[reps["form"].isin(ANNUAL_FORMS), "period"]
    fy_end_month = int(annual_periods.iloc[0].month) if len(annual_periods) else None
    # Fiscal cadence: annual filers (20-F/40-F) use 365d, else quarterly.
    cadence = 365 if latest["form"] in ("20-F", "40-F") else 91
    next_period = latest["period"] + pd.Timedelta(days=cadence)
    next_is_annual = fy_end_month is not None and int(next_period.month) == fy_end_month
    lag = a_lag if next_is_annual else q_lag
    win_start = next_period + pd.Timedelta(days=max(lag - 10, 0))
    win_end = next_period + pd.Timedelta(days=lag + 14)
    base = {
        "next_period": str(next_period.date()),
        "window": f"{win_start.date()}~{win_end.date()}",
        "lag_days": lag,
        "predicted_form": "annual" if next_is_annual else "quarterly",
    }
    if today < next_period:
        return {"status": "clear", **base}
    # Next period has ended but not yet filed: imminent only when today
    # falls within buffer_days BEFORE the expected window through its end
    # (+buffer). Between period-end and window-start-7d the report is
    # still weeks away — entering then is fine (e.g. QCOM period ends
    # late Sep, reports late Oct: early-Oct entries are allowed).
    if win_start - pd.Timedelta(days=buffer_days) <= today <= win_end + pd.Timedelta(days=buffer_days):
        return {"status": "imminent", **base,
                "note": f"报告期 {next_period.date()} 已过但未申报，预期窗口 {win_start.date()}~{win_end.date()}"}
    return {"status": "clear", **base}


def earnings_window(symbol: str, sec_client, buffer_days: int = 7) -> dict:
    """Data-driven earnings-window detection from SEC submissions history.

    Infers the NEXT expected report from the latest filed 10-Q/10-K/20-F
    period (+ fiscal cadence) and the filer's own historical filing lag
    (filed - period median). No external earnings calendar needed.

    status:
      imminent  - the next report is unfiled and today (or the entry date)
                  sits inside/within buffer_days of the expected window →
                  entering now is a binary-event gamble.
      filed     - a report newer than the previously known latest exists
                  (data already digested by the market).
      clear     - next expected window is > buffer_days away.
      unknown   - insufficient filing history.
    """
    try:
        cfg0 = load_config("configs/config.risk_off.json")
        mapping = sec_client.ticker_mapping()
        row = mapping[mapping["symbol"] == symbol.upper()]
        if row.empty:
            return {"status": "unknown"}
        cik = row.iloc[0]["cik"]
        subs = sec_client.get_submissions(cik)
        rec = subs.get("filings", {}).get("recent", {})
        df = pd.DataFrame({
            "form": rec.get("form", []),
            "filed": rec.get("filingDate", []),
            "period": rec.get("reportDate", []),
        }).dropna(subset=["period", "filed"])
        reports = df[df["form"].isin(["10-Q", "10-K", "20-F", "40-F"])].copy()
        if reports.empty:
            return {"status": "unknown"}
        reports["filed"] = pd.to_datetime(reports["filed"])
        reports["period"] = pd.to_datetime(reports["period"])
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        return predict_earnings_window(reports, today, buffer_days)
    except Exception:
        return {"status": "unknown"}


def _report_style(report_path: str) -> str | None:
    """Identify the scan style from the report's Config header line.

    Reports written since 2026-09-27 carry "- Config: configs/config.<style>.json".
    Older reports fall back to None (caller must use mtime ordering + warn).
    """
    try:
        text = Path(report_path).read_text()
    except OSError:
        return None
    for line in text.splitlines()[:10]:
        m = re.match(r"- Config: .*config\.(risk_off|risk_on)\.json", line.strip())
        if m:
            return m.group(1)
    return None


def latest_scan_pair() -> tuple[str, str]:
    """Most recent (risk_off_ts, risk_on_ts), style-verified via report headers.

    Style mislabeling here produced a swapped live trade plan once (2026-09-27:
    odd report count made mtime[-2] point at the other style's run) — hence
    headers are authoritative and mismatches fail loudly.
    """
    reports = sorted(
        glob.glob("outputs/ai_value_scan_*_full_ranked_report.md"),
        key=lambda p: os.path.getmtime(p),
    )
    if len(reports) < 2:
        raise SystemExit("需要至少两份风格报告（先跑 scripts/observation_scan.py）")

    def ts(p: str) -> str:
        return Path(p).name.replace("ai_value_scan_", "").split("_")[0]

    by_style: dict[str, str] = {}
    for p in reversed(reports):  # newest first; keep the newest per style
        style = _report_style(p)
        if style and style not in by_style:
            by_style[style] = ts(p)
    if len(by_style) == 2:
        return by_style["risk_off"], by_style["risk_on"]

    # Fallback (legacy reports without Config header): newest two reports,
    # mtime order (risk_off ran first in observation_scan). Warn loudly.
    print(
        "WARNING: 报告缺少 Config 头（旧版产物），退回 mtime 顺序配对——"
        "若报告数为奇数可能拿反风格。建议重跑 observation_scan.py 生成新报告。",
        file=sys.stderr,
    )
    return ts(reports[-2]), ts(reports[-1])


def qqq_breaker_state() -> dict:
    cfg = load_config("configs/config.risk_off.json")
    client, _monitor = load_alpaca_client(cfg)
    bar_db = build_bar_db(client, ["QQQ"], (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=500)).isoformat(), cfg.chunk_size)
    qqq = bar_db.get("QQQ")
    if qqq is None or qqq.empty:
        return {"ok": None, "close": None, "sma200": None, "asof": None}
    close = float(qqq["close"].iloc[-1])
    sma = float(qqq["close"].tail(200).mean())
    return {
        "ok": bool(close >= sma),
        "close": close,
        "sma200": sma,
        "asof": str(qqq.index[-1].date()),
    }


AUXILIARY_CHANNELS = ("ai_smallcap",)


def exclude_auxiliary_channels(df: "pd.DataFrame", include_smallcap: bool = False) -> "pd.DataFrame":
    """Drop auxiliary-channel rows from plan candidates.

    ai_smallcap is an observation sleeve, not a live-money channel: its
    hard-gate survivors show negative absolute forwards at 20d/120d and
    sub-50% win rates in the weight dataset, vs positive for all three main
    channels. Filtering channel rows (not symbols) lets multi-channel names
    keep their best non-auxiliary row via the normal dedup below.
    """
    if include_smallcap or df.empty or "channel" not in df.columns:
        return df
    return df[~df["channel"].isin(AUXILIARY_CHANNELS)].copy()


def sleeve_positions(ts: str, style: str, include_smallcap: bool = False) -> pd.DataFrame:
    """keep=1.0x, watch=0.5x (low_value); momentum picks weighted by
    research priority; dedup by symbol.

    Ordering: low_value and momentum composites come from DIFFERENT weight
    vectors and are not comparable as raw numbers — after the 2026-10-02
    median-sweep weights the momentum scale (~1.2-1.3) sits far above the
    low_value scale (~0.6-0.8), which crowded every keep out of the book.
    Selection therefore ranks each candidate by its percentile WITHIN its own
    list and channel cohort (list_pct): the best keep and the best momentum
    name both stand at 1.0 and compete fairly, while each list's internal
    ordering (what the weight sweep actually optimized) is preserved.

    Momentum priority weights are evidence-based (2021-2026 survivor
    dataset, 120d portfolio basis): research_now +13.1% / watch_for_pullback
    +9.3% / avoid_for_now +8.76% / theme_only +6.3% / left_side_watch +1.0%
    (win 44%). left_side_watch is excluded outright; theme_only halved;
    avoid_for_now halved (its "avoid" semantics target the research pool,
    not momentum — returns are mid-pack here).
    """
    MOMENTUM_PRIORITY_WEIGHT = {
        "research_now": 1.0,
        "watch_for_pullback": 1.0,
        "theme_only": 0.5,
        "avoid_for_now": 0.5,
        "left_side_watch": 0.0,
    }
    parts: list[pd.DataFrame] = []
    lv_path = f"outputs/ai_value_scan_{ts}_full_ranked.csv"
    if Path(lv_path).exists():
        lv = pd.read_csv(lv_path)
        if not lv.empty and "triage_label" in lv.columns:
            keep = lv[lv["triage_label"] == "keep"].copy()
            keep["lists"] = "low_value"
            keep["weight_mult"] = 1.0
            parts.append(keep)
            watch = lv[lv["triage_label"] == "watch"].copy()
            watch["lists"] = "low_value(watch)"
            watch["weight_mult"] = 0.5
            parts.append(watch)
    mo_path = f"outputs/ai_value_scan_{ts}_full_ranked_momentum.csv"
    if Path(mo_path).exists():
        mo = pd.read_csv(mo_path)
        if not mo.empty:
            mo = mo.copy()
            mo["triage_label"] = "momentum"
            mo["lists"] = "momentum"
            if "research_priority" in mo.columns:
                mo["weight_mult"] = mo["research_priority"].map(MOMENTUM_PRIORITY_WEIGHT)
                excluded = mo["weight_mult"].isna() | (mo["weight_mult"] <= 0)
                mo = mo[~excluded].copy()
                mo["lists"] = mo["research_priority"].radd("momentum(") + ")"
            else:
                raise SystemExit(
                    f"momentum 清单缺 research_priority 列（旧版扫描产物）：{mo_path}。"
                    "重跑当日扫描后再生成交易计划（否则 left_side_watch 会被误按全权重买入）。"
                )
            parts.append(mo)
    if not parts:
        return pd.DataFrame(
            columns=["symbol", "lists", "channel", "composite_score", "list_pct", "weight_mult"]
        )
    allp = pd.concat(parts, ignore_index=True)
    allp["symbol"] = allp["symbol"].astype(str).str.upper()
    allp = exclude_auxiliary_channels(allp, include_smallcap)
    # Within-list percentile: the fair cross-list ordering key (see docstring).
    allp["list_source"] = np.where(allp["lists"].str.startswith("low_value"), "low_value", "momentum")
    allp["list_pct"] = allp.groupby(["list_source", "channel"])["composite_score"].rank(
        pct=True, method="average"
    )
    # Dedup: a symbol in multiple lists keeps its best (highest) composite,
    # membership noted; conviction is the best tier across memberships, so a
    # keep+momentum name never loses its 1.0x to the row the dedup happens to keep.
    allp["weight_mult"] = allp.groupby("symbol")["weight_mult"].transform("max")
    allp = allp.sort_values("composite_score", ascending=False)
    allp["lists"] = allp.groupby("symbol")["lists"].transform(lambda s: "+".join(sorted(set(s))))
    dedup = allp.drop_duplicates("symbol", keep="first").copy()
    # Cap per channel top-10 by within-list standing (not raw composite).
    dedup["rank_in_channel"] = dedup.groupby("channel")["list_pct"].rank(ascending=False, method="first")
    dedup = dedup[dedup["rank_in_channel"] <= 10]
    return dedup[
        ["symbol", "lists", "channel", "composite_score", "list_pct", "triage_label", "weight_mult"]
    ].reset_index(drop=True)


def apply_position_caps(conviction: "pd.Series", cap_frac: float, max_iter: int = 100) -> tuple:
    """Cap-and-renormalize conviction weights against the deployable pool.

    Returns (weights, unallocated_frac, converged). weights sum to
    1 - unallocated_frac; unallocated_frac > 0 means every name hit the cap
    and the remainder correctly stays in cash (it is reported, never silently
    dropped). converged=False means max_iter was hit with names still over
    cap — output weights are then hard-clipped so the cap is never breached.
    """
    total = float(conviction.sum())
    if not np.isfinite(total) or total <= 0:
        raise SystemExit(" conviction 总和为 0/非法，无法分配权重——检查候选挑选逻辑")
    raw_w = conviction / total
    w = raw_w.copy()
    converged = False
    for _ in range(max(1, int(max_iter))):
        over = w > cap_frac
        if not over.any():
            converged = True
            break
        excess = (w[over] - cap_frac).sum()
        w[over] = cap_frac
        under = ~over
        if w[under].sum() > 0:
            w[under] = w[under] + excess * (raw_w[under] / raw_w[under].sum())
        else:
            break
    leftover = w > cap_frac * (1.0 + 1e-9)
    if leftover.any():
        w[leftover] = cap_frac
    unallocated = float(max(0.0, 1.0 - w.sum()))
    return w, unallocated, converged


BREAKER_MAX_STALE_DAYS = 4


def check_breaker_state(breaker: dict, today, max_stale_days: int = BREAKER_MAX_STALE_DAYS) -> tuple:
    """Validate the QQQ circuit-breaker snapshot. Returns (proceed, reason).

    proceed=False is a hard stop: unknown or stale breaker data must never
    silently issue positions. Callers may bypass only via an explicit
    --allow-no-breaker flag (logged loudly and stamped on the report).
    """
    ok = breaker.get("ok")
    if ok is None:
        return False, "QQQ 熔断器数据不可用（Alpaca 拉取失败或缓存为空）"
    try:
        asof = datetime.strptime(str(breaker.get("asof")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False, f"QQQ 熔断器 asof 日期无法解析（{breaker.get('asof')}）"
    lag_days = (today - asof).days
    if lag_days > max_stale_days:
        return False, f"QQQ 熔断器数据陈旧（asof {asof}，距今 {lag_days} 天 > {max_stale_days} 天）"
    return True, "bull" if ok else "bear"


def earnings_advisory_rows(plan: "pd.DataFrame", earnings_status: dict[str, dict]) -> list[dict]:
    """Rows for the earnings advisory section: candidates whose expected
    report window is imminent. Advisory only — never blocks or delays."""
    rows = []
    for _, r in plan.iterrows():
        info = earnings_status.get(str(r["symbol"]), {})
        if info.get("status") == "imminent":
            rows.append({
                "symbol": str(r["symbol"]),
                "window": info.get("window", "?"),
                "note": info.get("note", ""),
            })
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, required=True, help="Total pilot capital in USD")
    p.add_argument("--risk-on-alloc", type=float, default=0.60)
    p.add_argument("--risk-off-alloc", type=float, default=0.40)
    p.add_argument("--max-position-pct", type=float, default=0.10, help="Cap per position, fraction of TOTAL capital")
    p.add_argument("--cash-buffer-pct", type=float, default=0.10, help="Unallocated cash per sleeve")
    p.add_argument("--max-positions-per-sleeve", type=int, default=10,
                   help="Concentrate the sleeve: full-weight tiers (keeps + momentum picks) first, "
                        "then half-weight watches; within a tier by within-list percentile (list_pct), "
                        "NOT raw composite (lists use different weight scales)")
    p.add_argument("--earnings-buffer-days", type=int, default=7,
                   help="Days around the expected report window counted as earnings-imminent for the advisory note")
    p.add_argument("--allow-no-breaker", action="store_true", default=False,
                   help="Bypass a failed/stale QQQ breaker check (logged loudly and stamped on the report)")
    p.add_argument("--include-smallcap", action="store_true", default=False,
                   help="Include ai_smallcap channel rows in plan candidates (default: auxiliary observation only)")
    return p


def main() -> None:
    args = build_parser().parse_args()

    off_ts, on_ts = latest_scan_pair()
    breaker = qqq_breaker_state()
    now = datetime.now(timezone.utc)
    proceed, breaker_reason = check_breaker_state(breaker, now.date())
    breaker_overridden = False
    if not proceed:
        if not args.allow_no_breaker:
            raise SystemExit(
                f"熔断器检查未通过，拒绝生成交易计划: {breaker_reason}。"
                "确认数据源恢复后重跑，或用 --allow-no-breaker 显式绕过（将记录在报告中）。"
            )
        breaker_overridden = True
        print(f"WARNING: 熔断器检查未通过但已用 --allow-no-breaker 绕过: {breaker_reason}")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    sec_client = load_sec_client(load_config("configs/config.risk_off.json"), NetworkMonitor())

    sleeves = {
        "risk_on": (on_ts, args.risk_on_alloc),
        "risk_off": (off_ts, args.risk_off_alloc),
    }
    # Stage 1: collect candidates per sleeve with tier conviction multipliers
    # and the sleeve position cap (full-weight tiers first, then half weight).
    candidates: list[dict] = []
    for style, (ts, alloc) in sleeves.items():
        pos = sleeve_positions(ts, style, include_smallcap=args.include_smallcap)
        if pos.empty:
            continue
        pos["tier"] = np.where(pos["weight_mult"] >= 1.0, 0, 1)
        # Full-weight tiers first, then by WITHIN-LIST standing (list_pct):
        # raw composites are not comparable across lists (different weight
        # vectors), composite is only the deterministic tiebreak.
        pos = pos.sort_values(["tier", "list_pct", "composite_score"], ascending=[True, False, False])
        pos = pos.head(args.max_positions_per_sleeve).copy()
        for _, r in pos.iterrows():
            candidates.append({
                "symbol": r["symbol"],
                "style_leg": style,
                "lists": r["lists"],
                "channel": r["channel"],
                "composite_score": round(float(r["composite_score"]), 4),
                "triage": r["triage_label"],
                "conviction": float(r["weight_mult"]),
                "entry_rule": "next market open",
                "holding_rule": "120 trading days (staggered cohort)",
                "stop_rule": "-25% from entry price",
            })
    if not candidates:
        raise SystemExit("无候选——检查扫描产物是否有 keep/momentum 行")

    plan = pd.DataFrame(candidates)

    # Stage 2: cross-sleeve merge. The momentum machinery is style-agnostic,
    # so the same symbol is frequently selected by BOTH styles; merge into
    # ONE position whose conviction is the sum of both sleeves' (a name both
    # styles agree on is the highest-conviction name in the book).
    plan = plan.sort_values("composite_score", ascending=False)
    merged = plan.groupby("symbol", as_index=False).agg(
        conviction=("conviction", "sum"),
        n_sleeves=("style_leg", "nunique"),
    )
    dup = set(merged.loc[merged["n_sleeves"] > 1, "symbol"])
    for sym in dup:
        rows_both = plan[plan["symbol"] == sym]
        keep_idx = rows_both.index[0]  # highest composite (sorted)
        plan.loc[keep_idx, "conviction"] = float(rows_both["conviction"].sum())
        plan.loc[keep_idx, "style_leg"] = "both_styles"
        plan.loc[keep_idx, "lists"] = "+".join(
            sorted({f"{s}:{l}" for s, l in zip(rows_both["style_leg"], rows_both["lists"])})
        )
        plan = plan.drop(rows_both.index[1:])

    # Stage 3: single conviction pool allocation.
    # Budget semantics (fixed 2026-09-27): weights are computed against the
    # TOTAL deployable capital = capital x (1 - cash_buffer), with a hard
    # per-name cap at max_position_pct of total capital. The earlier
    # per-sleeve budget + merge combination over-deployed (merged positions
    # bypassed the sleeve pools: 98k deployed vs 90k budget on a 100k
    # book) — a single pool is the only scheme that stays internally
    # consistent once positions are merged across styles. Style allocation
    # (60/40) remains an OBSERVATION/monitoring lens, not a capital split.
    deployable = args.capital * (1.0 - args.cash_buffer_pct)
    if plan.empty:
        raise SystemExit("无候选——检查扫描产物是否有 keep/momentum 行")
    # Iterative cap-and-renormalize (converges in a few passes for normal
    # books). Unlike a silent loop, the unallocated remainder is tracked and
    # reported: when every name hits the cap, the rest correctly stays cash.
    w, unallocated_frac, caps_converged = apply_position_caps(
        plan["conviction"], args.max_position_pct / (1.0 - args.cash_buffer_pct)
    )
    w.index = plan.index
    if not caps_converged:
        print(
            "WARNING: 仓位上限迭代未收敛，已硬性截断到上限；"
            f"未部署 {unallocated_frac:.1%}（通常意味着候选池太薄）"
        )
    elif unallocated_frac > 0.005:
        print(
            f"WARNING: 可部署资金中 {unallocated_frac:.1%} 因全部仓位触及单仓 "
            f"{args.max_position_pct:.0%} 上限而保留为现金（非缓冲现金）"
        )
    # Weights are reported as a fraction of TOTAL capital (sum = 1 - buffer;
    # the remaining buffer sits in cash). notional = weight x total capital.
    plan["weight_pct_of_total"] = (w * (1.0 - args.cash_buffer_pct) * 100).round(2)
    plan["notional_usd"] = (plan["weight_pct_of_total"] / 100.0 * args.capital).round(0)

    # Stage 4: earnings advisory (pre-registered pilot rule, added
    # 2026-09-28 after the MU gap, simplified 2026-10-01: expected windows
    # are computed from SEC filing history and shown as an advisory note —
    # no auto-delay, no reserved cash, no re-entry machinery. Whether to sit
    # out an imminent report is an explicit operator decision.
    earnings_status: dict[str, dict] = {}
    plan["execution"] = "execute_now"
    for idx, r in plan.iterrows():
        info = earnings_window(str(r["symbol"]), sec_client, args.earnings_buffer_days)
        earnings_status[str(r["symbol"])] = info
    advisory = earnings_advisory_rows(plan, earnings_status)
    if advisory:
        print(
            "财报临近提示 "
            f"{len(advisory)} 个（仅提示，不延迟执行）: "
            + ", ".join(f"{a['symbol']}({a['window']})" for a in advisory)
        )
    plan = plan.reset_index(drop=True)
    out_csv = Path(f"outputs/trade_plan_{stamp}.csv")
    out_md = Path(f"outputs/trade_plan_{stamp}.md")
    plan.to_csv(out_csv, index=False)

    breaker_txt = (
        f"QQQ close={breaker['close']:.2f} vs SMA200={breaker['sma200']:.2f} → trend_ok={breaker['ok']}"
        if breaker["ok"] is not None else "QQQ 数据不可用"
    )
    if breaker_overridden:
        breaker_txt += "（⚠ 已用 --allow-no-breaker 绕过熔断检查）"
    lines = [
        f"# Trade Plan — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"- 扫描来源: risk_off={off_ts} / risk_on={on_ts}",
        f"- 熔断器: {breaker_txt}（as of {breaker['asof']}）",
        f"- 总资金: ${args.capital:,.0f} | 可部署 {(1-args.cash_buffer_pct):.0%}（现金缓冲 {args.cash_buffer_pct:.0%}）| 单仓上限 {args.max_position_pct:.0%} 总资金 | 权重=分层置信度（双风格合并仓置信度累加后归一）",
        f"- 资金模式: 单一置信池（跨风格合并后按分层倍数分配）；risk_on/off {(args.risk_on_alloc):.0%}/{(args.risk_off_alloc):.0%} 仅作为观察与监控的镜头，不是资金分割",
        f"- 持有期: 120 个交易日（分批滚动，每月一个新 cohort）",
        "",
        "## 生效规则（见 docs/live_pilot_protocol.md）",
        "",
        "1. **熔断**: QQQ < SMA200 → 停止一切新开仓（现有 cohort 按止损/到期处理）",
        "2. **入场**: 次日开盘；watch 分级半仓，keep/momentum 全仓；**财报提示**：报告下方",
        f"   “财报临近提示”段所列标的预期财报临近（SEC 申报历史推算，窗口前后各 {args.earnings_buffer_days} 天），是否避开由操作人决定，本计划不做自动延迟",
        "3. **止损**: 单仓位 -25%；组合自启动 -15% → 暂停新开仓 + 人工复盘",
        "4. **验证**: 每周 `validate_ttm_population.py` 必须 PASS，连续 FAIL 暂停开仓",
        "",
        "## 分层 → 权重图例（每仓位的 triage/lists 列对应这里的倍数）",
        "",
        "| 来源 | 标签 | 含义 | 权重倍数 |",
        "|---|---|---|---|",
        "| low_value | keep | 价值折扣 + 综合分双达标 | 1.0x |",
        "| low_value | watch | 仅一项达标（价值溢价不足或综合分不足） | 0.5x |",
        "| low_value | drop | 双项均不达标（scored 架构下实际不触发） | 0x |",
        "| momentum | research_now | 动量+AI关联+估值全达标 | 1.0x |",
        "| momentum | watch_for_pullback | 动量强但有追高风险 | 1.0x |",
        "| momentum | theme_only | 仅有 AI 主题，其余平庸（120d 实证最弱可买层） | 0.5x |",
        "| momentum | avoid_for_now | AI 关联弱（research pool 语义；momentum 实证不弱） | 0.5x |",
        "| momentum | left_side_watch | 左侧下跌接刀（120d 实证 +1%/胜率44%） | **0x 不买** |",
        "| 双风格 | both_styles | 同一标的被两风格同时选中 → 合并为单仓，封顶 10% | 合并 |",
        "",
        "## 持仓明细",
        "",
    ]
    if plan.empty:
        lines.append("- （无持仓——检查扫描产物）")
    else:
        for style in ("both_styles", "risk_on", "risk_off"):
            part = plan[plan["style_leg"] == style]
            if part.empty:
                continue
            label = {
                "both_styles": "双风格合并仓（两风格同时选中，置信度最高）",
                "risk_on": "risk_on 独有",
                "risk_off": "risk_off 独有",
            }[style]
            lines.append(f"### {label}（{len(part)} 个仓位）")
            lines.append("")
            lines.append("| symbol | lists | channel | score | triage | 权重% | 名义$ |")
            lines.append("|---|---|---|---|---|---|---|")
            for _, r in part.sort_values("composite_score", ascending=False).iterrows():
                lines.append(
                    f"| {r['symbol']} | {r['lists']} | {r['channel']} | {r['composite_score']:.3f} "
                    f"| {r['triage']} | {r['weight_pct_of_total']:.1f}% | {r['notional_usd']:,.0f} |"
                )
            lines.append("")
        if advisory:
            lines.append("### ⚠ 财报临近提示（仅提示，不延迟执行）")
            lines.append("")
            lines.append("| symbol | 预期财报窗口 | 说明 |")
            lines.append("|---|---|---|")
            for a in advisory:
                lines.append(f"| {a['symbol']} | {a['window']} | {a['note']} |")
            lines.append("")
            lines.append("- 上表标的预期财报临近，是否避开由操作人决定；本计划不做自动延迟、不预留现金。")
            lines.append("")
    if unallocated_frac > 0.005:
        lines += [
            "### 💰 未部署现金（触及单仓上限）",
            "",
            f"- 可部署资金中 {unallocated_frac:.1%} 因全部仓位触及单仓 {args.max_position_pct:.0%} 上限而保留为现金（非缓冲现金）。",
            "- 这通常意味着候选池太薄：接受低部署率，不可手工加仓突破上限；如下次扫描候选增多会自动填满。",
            "",
        ]
    lines += [
        "## 基线预期（phase4 2026-10-02，诚实口径，当前权重）",
        "",
        "口径: 2023-01→2026-10 月度回放 | union 宇宙（2026-09-22 前为近似，标注向上偏差）|",
        "拆股修正 | 策略与 QQQ 两侧对称扣 30bps | 退市假设 -55% | 中位数稳健 sweep 权重。",
        "",
        "| 清单 | 120d 平均超额 vs QQQ | 超额胜率 | t |",
        "|---|---|---|---|",
        "| risk_on low_value | +5.6pp | 58% | +2.17 |",
        "| risk_on momentum | +4.7pp | 50% | +2.09 |",
        "| risk_off low_value | -2.6pp（设计目标为绝对收益+熔断保护；分年看 2024 起转正）| 31% | -1.95 |",
        "| risk_off momentum | +2.9pp | 50% | +1.80 |",
        "",
        "**定位提醒**: 这是一个受控的实盘实验。截面排名能力经重叠校正后仍然显著",
        "（IC t_nw=2.7~4.6，60/120d），但组合级超额 t≈2 未达显著（n=36 月度事件）；",
        "负超额集中在 2023（QQQ 强动量年），2024-2026 两风格超额均为正。",
        "按试点协议分级放量，不承诺已证明的收益优势。",
        "",
        f"机器可读版: {out_csv.name}",
    ]
    out_md.write_text("\n".join(lines))
    print(f"trade plan: {out_md}")
    print(f"csv:        {out_csv}")
    if plan.empty:
        print("WARNING: 无持仓——检查扫描产物是否有 keep/momentum 行")
    else:
        print(f"\n持仓 {len(plan)} 个 | 总名义 ${plan['notional_usd'].sum():,.0f}")
        if unallocated_frac > 0.005:
            print(f"WARNING: 未部署现金 {unallocated_frac:.1%}（全部触及单仓上限）")
        print(plan.groupby("style_leg")["symbol"].count().to_string())


if __name__ == "__main__":
    main()
